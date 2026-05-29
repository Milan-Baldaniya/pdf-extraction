"""FastAPI routes for NCERT PDF extraction and extracted assets."""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.extraction.cache import (
    file_sha256,
    get_cached_response,
    set_cached_response,
)
from app.extraction.status import get_status, update_status
from app.db.supabase_client import supabase
from app.models.schemas import (
    ErrorResponse,
    ExtractionRequest,
    ExtractionResponse,
    HealthResponse,
)
from app.semantic_intelligence.gemini_client import extract_pdf_metadata
from app.services.mineru_service import (
    MinerUConfigurationError,
    MinerUExtractionError,
    extract_pdf,
)
from app.services.pdf_service import PDFDownloadError, download_pdf
from app.utils.config import settings
from app.utils.file_utils import (
    cleanup_temp_job,
    generate_job_id,
    get_output_dir,
    get_temp_pdf_path,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _validate_pdf_header(pdf_path: Path, source_label: str) -> None:
    with pdf_path.open("rb") as file:
        header = file.read(5)
    if header != b"%PDF-":
        raise PDFDownloadError(
            f"The {source_label} does not appear to be a valid PDF."
        )


def _asset_base_url(request: Request, job_id: str) -> str:
    marker = "__asset__"
    asset_url = request.url_for(
        "get_extracted_asset",
        job_id=job_id,
        asset_path=marker,
    )
    return str(asset_url).removesuffix(f"/{marker}")


async def _run_extraction_job(
    *,
    job_id: str,
    pdf_path: Path,
    request: Request,
    start_time: float,
    cache_message: str,
    extraction_message: str,
) -> ExtractionResponse:
    update_status(job_id, "checking_cache", cache_message)
    file_hash = file_sha256(pdf_path)
    cached_response = get_cached_response(settings.output_dir, file_hash)

    if cached_response:
        logger.info("Job %s - cache hit for hash %s", job_id, file_hash)
        cached_response.metadata["cached"] = True
        cached_response.metadata["job_id"] = job_id
        update_status(
            job_id,
            "completed",
            "Extraction loaded from cache",
            cached_response.metadata,
        )
        return cached_response

    output_dir = get_output_dir(settings.output_dir, job_id)
    update_status(job_id, "extracting", extraction_message)

    result = await asyncio.to_thread(
        extract_pdf,
        pdf_path,
        output_dir,
        settings.mineru_backend,
        method=settings.mineru_method,
        lang=settings.mineru_lang,
        server_url=settings.mineru_server_url,
        formula=settings.mineru_formula,
        table=settings.mineru_table,
        image_analysis=settings.mineru_image_analysis,
        asset_base_url=_asset_base_url(request, job_id),
        cpu_threads=settings.mineru_cpu_threads,
        timeout_seconds=settings.mineru_timeout_seconds,
        quality_mode=settings.mineru_quality_mode,
        ocr_fallback=settings.mineru_ocr_fallback,
    )

    elapsed = time.perf_counter() - start_time
    logger.info(
        "Job %s - extraction completed in %.1fs | markdown=%d chars images=%d",
        job_id,
        elapsed,
        len(result.markdown),
        result.images_extracted,
    )

    metadata = {
        **result.metadata,
        "processing_time": f"{elapsed:.2f}s",
        "job_id": job_id,
        "cached": False,
    }
    response = ExtractionResponse(
        status="success",
        processing_mode=result.processing_mode,
        markdown_content=result.markdown,
        json_content=result.json_content,
        metadata=metadata,
        page_count=result.page_count,
        images_extracted=result.images_extracted,
    )

    update_status(job_id, "completed", "Extraction completed", metadata)
    set_cached_response(settings.output_dir, file_hash, response)
    return response


def _raise_job_error(job_id: str, status_code: int, message: str, exc: Exception, cache_id: int | None = None) -> None:
    update_status(job_id, "failed", message)
    logger.error("Job %s - %s: %s", job_id, message, exc)
    if supabase and cache_id:
        try:
            supabase.table("pdf_processing_cache").update({
                "status": "failed",
                "error_message": str(exc),
                "updated_at": "now()"
            }).eq("id", cache_id).execute()
        except Exception:
            pass
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Health check",
)
async def health_check() -> HealthResponse:
    """Return service health status."""
    return HealthResponse()


@router.get(
    "/assets/{job_id}/{asset_path:path}",
    tags=["Extraction"],
    summary="Serve an extracted image asset",
)
async def get_extracted_asset(job_id: str, asset_path: str) -> FileResponse:
    """Serve an image generated by MinerU for a completed extraction job."""
    output_root = Path(settings.output_dir).resolve()
    job_root = (output_root / job_id).resolve()
    target = (job_root / asset_path).resolve()

    try:
        target.relative_to(job_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Asset not found") from exc

    if not target.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")

    return FileResponse(target)


@router.get(
    "/status/{job_id}",
    tags=["Extraction"],
    summary="Get extraction job status",
)
async def get_extraction_status(job_id: str) -> dict[str, Any]:
    """Return the latest known status for an extraction job."""
    status = get_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job status not found")
    return {
        "job_id": status.job_id,
        "state": status.state,
        "message": status.message,
        "updated_at": status.updated_at,
        "metadata": status.metadata,
    }


@router.post(
    "/generate-chapter-ppt",
    response_model=ExtractionResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        422: {"model": ErrorResponse, "description": "Validation error"},
        500: {"model": ErrorResponse, "description": "Extraction failure"},
    },
    tags=["Extraction"],
    summary="Extract content from an NCERT PDF URL",
)
async def extract_ncert_pdf(
    request: ExtractionRequest,
    http_request: Request,
) -> ExtractionResponse:
    """Download an NCERT PDF and extract structured educational content."""
    job_id = generate_job_id()
    start_time = time.perf_counter()
    update_status(job_id, "started", "Extraction job created")
    logger.info("Job %s - starting extraction for %s", job_id, request.pdf_url)

    cache_id = None
    if supabase:
        try:
            res = supabase.table("pdf_processing_cache").insert({
                "standard_id": 0,
                "subject_id": 0,
                "chapter_id": 0,
                "pdf_url": str(request.pdf_url),
                "status": "processing"
            }).execute()
            if res.data:
                cache_id = res.data[0]["id"]
        except Exception as e:
            logger.warning(f"Supabase insert failed: {e}")

    try:
        pdf_path = get_temp_pdf_path(settings.temp_dir, job_id)
        update_status(job_id, "downloading", "Downloading source PDF")
        await download_pdf(str(request.pdf_url), pdf_path)
        _validate_pdf_header(pdf_path, "downloaded file")

        response = await _run_extraction_job(
            job_id=job_id,
            pdf_path=pdf_path,
            request=http_request,
            start_time=start_time,
            cache_message="Checking extraction cache",
            extraction_message=(
                "Running MinerU CPU pipeline with OCR, table, formula, "
                "image, and layout extraction"
            ),
        )
        
        meta = await extract_pdf_metadata(response.markdown_content)
        
        if supabase and cache_id:
            try:
                supabase.table("pdf_processing_cache").update({
                    "status": "completed",
                    "standard_id": meta["standard_id"],
                    "subject_id": meta["subject_id"],
                    "chapter_id": meta["chapter_id"],
                    "output_markdown_path": "extracted",
                    "processing_time_seconds": int(time.perf_counter() - start_time),
                    "updated_at": "now()"
                }).eq("id", cache_id).execute()
            except Exception:
                pass
                
        response.metadata["pdf_cache_id"] = cache_id
        return response

    except PDFDownloadError as exc:
        _raise_job_error(job_id, 400, "Download failed", exc, cache_id)
    except MinerUConfigurationError as exc:
        _raise_job_error(job_id, 503, "MinerU configuration failed", exc, cache_id)
    except MinerUExtractionError as exc:
        _raise_job_error(job_id, 500, "Extraction failed", exc, cache_id)
    except Exception as exc:
        update_status(job_id, "failed", f"Unexpected error: {exc}")
        logger.exception("Job %s - unexpected error", job_id)
        if supabase and cache_id:
            try:
                supabase.table("pdf_processing_cache").update({
                    "status": "failed",
                    "error_message": str(exc),
                    "updated_at": "now()"
                }).eq("id", cache_id).execute()
            except Exception:
                pass
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred: {exc}",
        ) from exc
    finally:
        cleanup_temp_job(settings.temp_dir, job_id)


@router.post(
    "/upload-chapter-ppt",
    response_model=ExtractionResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        500: {"model": ErrorResponse, "description": "Extraction failure"},
    },
    tags=["Extraction"],
    summary="Upload and extract content from a local NCERT PDF",
)
async def upload_ncert_pdf(
    http_request: Request,
    file: UploadFile = File(...),
) -> ExtractionResponse:
    """Accept a local PDF upload and extract structured educational content."""
    job_id = generate_job_id()
    start_time = time.perf_counter()
    update_status(job_id, "started", "Extraction job created")
    logger.info("Job %s - starting extraction for uploaded file %s", job_id, file.filename)

    cache_id = None
    if supabase:
        try:
            res = supabase.table("pdf_processing_cache").insert({
                "standard_id": 0,
                "subject_id": 0,
                "chapter_id": 0,
                "pdf_url": "uploaded",
                "status": "processing"
            }).execute()
            if res.data:
                cache_id = res.data[0]["id"]
        except Exception as e:
            logger.warning(f"Supabase insert failed: {e}")

    try:
        pdf_path = get_temp_pdf_path(settings.temp_dir, job_id)
        update_status(job_id, "saving_upload", "Saving uploaded PDF")

        with pdf_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        _validate_pdf_header(pdf_path, "uploaded file")

        response = await _run_extraction_job(
            job_id=job_id,
            pdf_path=pdf_path,
            request=http_request,
            start_time=start_time,
            cache_message="Checking extraction cache",
            extraction_message=(
                "Running MinerU CPU pipeline with OCR, table, formula, "
                "image, and layout extraction"
            ),
        )
        
        meta = await extract_pdf_metadata(response.markdown_content)
        
        if supabase and cache_id:
            try:
                supabase.table("pdf_processing_cache").update({
                    "status": "completed",
                    "standard_id": meta["standard_id"],
                    "subject_id": meta["subject_id"],
                    "chapter_id": meta["chapter_id"],
                    "output_markdown_path": "extracted",
                    "processing_time_seconds": int(time.perf_counter() - start_time),
                    "updated_at": "now()"
                }).eq("id", cache_id).execute()
            except Exception:
                pass
                
        response.metadata["pdf_cache_id"] = cache_id
        return response

    except PDFDownloadError as exc:
        _raise_job_error(job_id, 400, "Upload failed", exc, cache_id)
    except MinerUConfigurationError as exc:
        _raise_job_error(job_id, 503, "MinerU configuration failed", exc, cache_id)
    except MinerUExtractionError as exc:
        _raise_job_error(job_id, 500, "Extraction failed", exc, cache_id)
    except Exception as exc:
        update_status(job_id, "failed", f"Unexpected error: {exc}")
        logger.exception("Job %s - unexpected error", job_id)
        if supabase and cache_id:
            try:
                supabase.table("pdf_processing_cache").update({
                    "status": "failed",
                    "error_message": str(exc),
                    "updated_at": "now()"
                }).eq("id", cache_id).execute()
            except Exception:
                pass
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred: {exc}",
        ) from exc
    finally:
        cleanup_temp_job(settings.temp_dir, job_id)
        await file.close()
