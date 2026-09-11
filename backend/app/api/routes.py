"""FastAPI routes for NCERT PDF extraction and extracted assets."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.extraction.cache import (
    file_sha256,
    get_cached_response,
    set_cached_response,
)
from app.jobs import (
    accepted as _accepted,
    describe as _describe_job,
    get_result,
    get_status,
    llm_semaphore,
    set_result,
    spawn as _spawn_job,
    submit as submit_job,
    update_status,
)
from app.services.exam_question_service import (
    get_exam_questions,
    process_exam_questions,
)
from app.services.publisher_service import (
    list_publishers,
    seed_reference_data,
    type_map as question_type_map,
)
from app.services.question_ai_tagger import tag_extraction
from app.db.mariadb import (
    SessionLocal,
    DocumentExtraction,
    create_extraction_stub,
    init_mariadb,
    mariadb_status,
    persist_extraction_result,
)
from app.models.schemas import (
    ErrorResponse,
    ExtractionRequest,
    ExtractionResponse,
    HealthResponse,
)

from app.services.mineru_service import (
    MinerUConfigurationError,
    MinerUExtractionError,
    extract_pdf,
)
from app.services.curriculum_service import process_curriculum_by_id, get_all_curriculums, get_curriculum_data_by_extraction_id
from app.services.chapter_service import process_chapter_by_id, get_chapter_data_by_extraction_id, get_all_chapters
from app.services.topic_service import process_topics_by_id, get_topic_data_by_extraction_id, get_all_topics_queue
from app.services.concept_service import process_concepts_by_id, get_concept_data_by_extraction_id, get_all_concepts_queue
from app.services.question_service import (
    generate_questions_by_extraction,
    get_questions_by_extraction,
)
from app.services.validation_service import validate_extraction
from app.services import tab_label_service as tab_labels
from app.semantic_intelligence.deepseek_client import DeepSeekUnavailableError
from app.services.semantic_intelligence_service import get_all_semantic_chapters, process_semantic_chapter_by_id, get_semantic_data_by_extraction_id
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

EXTRACTION_MESSAGE = (
    "Running MinerU CPU pipeline with OCR, table, formula, "
    "image, and layout extraction"
)

# MinerU holds several GB of models in RAM for the duration of a run, so
# extractions are serialised by default rather than run concurrently.
_extraction_semaphore: asyncio.Semaphore | None = None


def _get_extraction_semaphore() -> asyncio.Semaphore:
    global _extraction_semaphore
    if _extraction_semaphore is None:
        _extraction_semaphore = asyncio.Semaphore(
            max(1, settings.max_concurrent_extractions)
        )
    return _extraction_semaphore


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

def _safe_int(val: Any) -> int | None:
    try:
        if val is None or val == "":
            return None
        return int(val)
    except (ValueError, TypeError):
        return None


async def _run_extraction_job(
    *,
    job_id: str,
    pdf_path: Path,
    asset_base_url: str,
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
        asset_base_url=asset_base_url,
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
        # _apply_extraction_payload copies this onto content_sha256. Nothing
        # produced the key before, so that branch had never once run.
        "source_sha256": file_hash,
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


def _mark_extraction_failed(cache_id: int | None, payload: dict[str, Any]) -> None:
    if cache_id is None or not init_mariadb() or SessionLocal is None:
        return
    db = SessionLocal()
    try:
        doc = db.query(DocumentExtraction).filter(DocumentExtraction.id == cache_id).first()
        if doc:
            doc.extraction_metadata = json.dumps(payload, ensure_ascii=False, default=str)
            # Leave the lifecycle column honest. Without this the row keeps the
            # "extracting" it was stamped with at job start, so a failed run is
            # indistinguishable from one still in flight -- and the question-bank
            # queue would offer it to an operator as ready to process.
            doc.extraction_status = "failed"
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _raise_job_error(job_id: str, status_code: int, message: str, exc: Exception, cache_id: int | None = None) -> None:
    update_status(job_id, "failed", message)
    logger.error("Job %s - %s: %s", job_id, message, exc)
    _mark_extraction_failed(
        cache_id,
        {"error": message, "exception": str(exc)},
    )
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


def _fail_job(job_id: str, message: str, exc: Exception, cache_id: int | None) -> None:
    """Record a failure for a background job. Never raises."""
    update_status(job_id, "failed", message, {"error": str(exc)})
    logger.error("Job %s - %s: %s", job_id, message, exc)
    try:
        _mark_extraction_failed(cache_id, {"error": message, "exception": str(exc)})
    except Exception:
        logger.exception("Job %s - could not record failure in MariaDB", job_id)


async def _background_extraction(
    *,
    job_id: str,
    pdf_path: Path,
    asset_base_url: str,
    cache_id: int | None,
    persist_kwargs: dict[str, Any],
) -> None:
    """Run one extraction to completion, recording progress in the job store.

    This is the body of a detached task, so it must never let an exception
    escape: the only channel back to the client is the job status.
    """
    start_time = time.perf_counter()
    try:
        async with _get_extraction_semaphore():
            response = await _run_extraction_job(
                job_id=job_id,
                pdf_path=pdf_path,
                asset_base_url=asset_base_url,
                start_time=start_time,
                cache_message="Checking extraction cache",
                extraction_message=EXTRACTION_MESSAGE,
            )

        new_cache_id = await asyncio.to_thread(
            persist_extraction_result, cache_id, response, **persist_kwargs
        )
        response.metadata["pdf_cache_id"] = new_cache_id
        set_result(job_id, response)
        update_status(job_id, "completed", "Extraction completed", response.metadata)

    except PDFDownloadError as exc:
        _fail_job(job_id, "Download failed", exc, cache_id)
    except MinerUConfigurationError as exc:
        _fail_job(job_id, "MinerU configuration failed", exc, cache_id)
    except MinerUExtractionError as exc:
        _fail_job(job_id, "Extraction failed", exc, cache_id)
    except Exception as exc:
        logger.exception("Job %s - unexpected error", job_id)
        _fail_job(job_id, f"Unexpected error: {exc}", exc, cache_id)
    finally:
        cleanup_temp_job(settings.temp_dir, job_id)


@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Health check",
)
async def health_check() -> HealthResponse:
    """Return service health status."""
    return HealthResponse(mariadb=mariadb_status())


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
    """Return the latest known status for any background job."""
    status = get_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job status not found")
    return _describe_job(status)


@router.get(
    "/jobs/{job_id}/result",
    tags=["Jobs"],
    summary="Fetch the payload of a completed background job",
)
async def get_job_result(job_id: str) -> Any:
    """Return a job's payload once it has finished.

    Shared by every background job, so the shape of the payload depends on
    which endpoint queued it.
    """
    status = get_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    if status.state == "failed":
        raise HTTPException(status_code=500, detail=status.message)

    result = get_result(job_id)
    if result is None:
        # 202 tells the client to keep polling rather than treat this as an error.
        raise HTTPException(status_code=202, detail=f"Job is {status.state}")
    return result


@router.post(
    "/jobs/extract",
    status_code=202,
    tags=["Extraction"],
    summary="Queue an extraction from a PDF URL and return a job id",
)
async def queue_extract_from_url(
    request: ExtractionRequest,
    http_request: Request,
) -> dict[str, Any]:
    """Accept an extraction request and process it in the background.

    Returns immediately with a job id; poll ``/api/status/{job_id}`` and then
    read ``/api/jobs/{job_id}/result``. Use this instead of the synchronous
    endpoint whenever a proxy or browser timeout sits in front of the API.
    """
    job_id = generate_job_id()
    update_status(job_id, "queued", "Extraction job created")
    logger.info("Job %s - queued extraction for %s", job_id, request.pdf_url)

    # The stub cannot be written until the bytes are on disk: it carries the
    # source SHA-256, and a question bank whose chapter is missing has to be
    # refused before any row exists to roll back.
    cache_id: int | None = None
    tenant = request.sub_institute_id or settings.tenant_for_board(request.board)

    # The PDF is downloaded inside the request so an unreachable URL fails fast
    # with a 400 instead of surfacing minutes later as a job status.
    pdf_path = get_temp_pdf_path(settings.temp_dir, job_id)
    try:
        update_status(job_id, "downloading", "Downloading source PDF")
        await download_pdf(str(request.pdf_url), pdf_path)
        _validate_pdf_header(pdf_path, "downloaded file")
    except PDFDownloadError as exc:
        cleanup_temp_job(settings.temp_dir, job_id)
        _raise_job_error(job_id, 400, "Download failed", exc, cache_id)

    # Same digest _run_extraction_job uses for its cache key; hashed off the
    # loop because a large PDF would otherwise stall every other request.
    content_sha256 = await asyncio.to_thread(file_sha256, pdf_path)

    try:
        cache_id = create_extraction_stub(
            document_type=request.document_type,
            document_title=request.document_title,
            chapter_number=_safe_int(request.chapter_number),
            standard=_safe_int(request.standard),
            subject_name=request.subject_name,
            board=request.board,
            syear=request.syear,
            pdf_url=str(request.pdf_url),
            sub_institute_id=tenant,
            content_sha256=content_sha256,
        )
    except ValueError as exc:
        # No chapter matched a question bank -- operator error, so the same
        # 400/str(exc) shape the processing routes use.
        cleanup_temp_job(settings.temp_dir, job_id)
        _raise_job_error(job_id, 400, "No chapter matched this question bank", exc, None)

    _spawn_job(
        _background_extraction(
            job_id=job_id,
            pdf_path=pdf_path,
            asset_base_url=_asset_base_url(http_request, job_id),
            cache_id=cache_id,
            persist_kwargs={
                "document_type": request.document_type,
                "document_title": request.document_title,
                "chapter_number": _safe_int(request.chapter_number),
                "standard": _safe_int(request.standard),
                "subject_name": request.subject_name,
                "board": request.board,
                "syear": request.syear,
                "pdf_url": str(request.pdf_url),
                "sub_institute_id": tenant,
            },
        )
    )
    return _accepted(job_id)


@router.post(
    "/jobs/upload",
    status_code=202,
    tags=["Extraction"],
    summary="Queue an extraction from an uploaded PDF and return a job id",
)
async def queue_extract_from_upload(
    http_request: Request,
    file: UploadFile = File(...),
    document_type: str = Form(None),
    document_title: str = Form(None),
    chapter_number: str = Form(None),
    standard: str = Form(None),
    subject_name: str = Form(None),
    board: str = Form("CBSE"),
    syear: str = Form(None),
) -> dict[str, Any]:
    """Accept a PDF upload and extract it in the background."""
    job_id = generate_job_id()
    update_status(job_id, "queued", "Extraction job created")
    logger.info("Job %s - queued extraction for uploaded file %s", job_id, file.filename)

    cache_id: int | None = None
    tenant = settings.tenant_for_board(board)

    # The upload stream is only valid for the lifetime of this request, so the
    # bytes must reach disk before the background task is handed the path.
    pdf_path = get_temp_pdf_path(settings.temp_dir, job_id)
    try:
        update_status(job_id, "saving_upload", "Saving uploaded PDF")
        with pdf_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        _validate_pdf_header(pdf_path, "uploaded file")
    except PDFDownloadError as exc:
        cleanup_temp_job(settings.temp_dir, job_id)
        _raise_job_error(job_id, 400, "Upload failed", exc, cache_id)
    finally:
        await file.close()

    content_sha256 = await asyncio.to_thread(file_sha256, pdf_path)

    try:
        cache_id = create_extraction_stub(
            document_type=document_type,
            document_title=document_title,
            chapter_number=_safe_int(chapter_number),
            standard=_safe_int(standard),
            subject_name=subject_name,
            board=board,
            syear=syear,
            pdf_url="uploaded",
            sub_institute_id=tenant,
            content_sha256=content_sha256,
        )
    except ValueError as exc:
        cleanup_temp_job(settings.temp_dir, job_id)
        _raise_job_error(job_id, 400, "No chapter matched this question bank", exc, None)

    _spawn_job(
        _background_extraction(
            job_id=job_id,
            pdf_path=pdf_path,
            asset_base_url=_asset_base_url(http_request, job_id),
            cache_id=cache_id,
            persist_kwargs={
                "document_type": document_type,
                "document_title": document_title,
                "chapter_number": _safe_int(chapter_number),
                "standard": _safe_int(standard),
                "subject_name": subject_name,
                "board": board,
                "syear": syear,
                "pdf_url": "uploaded",
                "sub_institute_id": tenant,
            },
        )
    )
    return _accepted(job_id)


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

    cache_id: int | None = None
    tenant = request.sub_institute_id or settings.tenant_for_board(request.board)

    try:
        pdf_path = get_temp_pdf_path(settings.temp_dir, job_id)
        update_status(job_id, "downloading", "Downloading source PDF")
        await download_pdf(str(request.pdf_url), pdf_path)
        _validate_pdf_header(pdf_path, "downloaded file")

        # Stub after the download so the row carries the source SHA-256, and
        # so a question bank with no matching chapter writes no row at all.
        try:
            cache_id = create_extraction_stub(
                document_type=request.document_type,
                document_title=request.document_title,
                chapter_number=_safe_int(request.chapter_number),
                standard=_safe_int(request.standard),
                subject_name=request.subject_name,
                board=request.board,
                syear=request.syear,
                pdf_url=str(request.pdf_url),
                sub_institute_id=tenant,
                content_sha256=await asyncio.to_thread(file_sha256, pdf_path),
            )
        except ValueError as exc:
            _raise_job_error(job_id, 400, "No chapter matched this question bank", exc, None)

        response = await _run_extraction_job(
            job_id=job_id,
            pdf_path=pdf_path,
            asset_base_url=_asset_base_url(http_request, job_id),
            start_time=start_time,
            cache_message="Checking extraction cache",
            extraction_message=EXTRACTION_MESSAGE,
        )

        cache_id = persist_extraction_result(
            cache_id,
            response,
            document_type=request.document_type,
            document_title=request.document_title,
            chapter_number=_safe_int(request.chapter_number),
            standard=_safe_int(request.standard),
            subject_name=request.subject_name,
            board=request.board,
            syear=request.syear,
            pdf_url=str(request.pdf_url),
            sub_institute_id=tenant,
        )
        response.metadata["pdf_cache_id"] = cache_id
        return response

    except PDFDownloadError as exc:
        _raise_job_error(job_id, 400, "Download failed", exc, cache_id)
    except MinerUConfigurationError as exc:
        _raise_job_error(job_id, 503, "MinerU configuration failed", exc, cache_id)
    except MinerUExtractionError as exc:
        _raise_job_error(job_id, 500, "Extraction failed", exc, cache_id)
    except HTTPException:
        # The 400 for an unmatched question bank is raised from inside this
        # try, so without this the blanket handler below reports it as a 500.
        raise
    except Exception as exc:
        update_status(job_id, "failed", f"Unexpected error: {exc}")
        logger.exception("Job %s - unexpected error", job_id)
        _mark_extraction_failed(
            cache_id,
            {"error": str(exc), "stage": "unexpected"},
        )
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
    document_type: str = Form(None),
    document_title: str = Form(None),
    chapter_number: str = Form(None),
    standard: str = Form(None),
    subject_name: str = Form(None),
    board: str = Form("CAMBRIDGE"),
    syear: str = Form(None),
) -> ExtractionResponse:
    """Accept a local PDF upload and extract structured educational content."""
    job_id = generate_job_id()
    start_time = time.perf_counter()
    update_status(job_id, "started", "Extraction job created")
    logger.info("Job %s - starting extraction for uploaded file %s", job_id, file.filename)

    cache_id: int | None = None
    tenant = settings.tenant_for_board(board)

    try:
        pdf_path = get_temp_pdf_path(settings.temp_dir, job_id)
        update_status(job_id, "saving_upload", "Saving uploaded PDF")

        with pdf_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        _validate_pdf_header(pdf_path, "uploaded file")

        # Stub after the save so the row carries the source SHA-256, and so a
        # question bank with no matching chapter writes no row at all.
        try:
            cache_id = create_extraction_stub(
                document_type=document_type,
                document_title=document_title,
                chapter_number=_safe_int(chapter_number),
                standard=_safe_int(standard),
                subject_name=subject_name,
                board=board,
                syear=syear,
                pdf_url="uploaded",
                sub_institute_id=tenant,
                content_sha256=await asyncio.to_thread(file_sha256, pdf_path),
            )
        except ValueError as exc:
            _raise_job_error(job_id, 400, "No chapter matched this question bank", exc, None)

        response = await _run_extraction_job(
            job_id=job_id,
            pdf_path=pdf_path,
            asset_base_url=_asset_base_url(http_request, job_id),
            start_time=start_time,
            cache_message="Checking extraction cache",
            extraction_message=EXTRACTION_MESSAGE,
        )
        cache_id = persist_extraction_result(
            cache_id,
            response,
            document_type=document_type,
            document_title=document_title,
            chapter_number=_safe_int(chapter_number),
            standard=_safe_int(standard),
            subject_name=subject_name,
            board=board,
            syear=syear,
            pdf_url="uploaded",
            sub_institute_id=tenant,
        )
        response.metadata["pdf_cache_id"] = cache_id
        return response

    except PDFDownloadError as exc:
        _raise_job_error(job_id, 400, "Upload failed", exc, cache_id)
    except MinerUConfigurationError as exc:
        _raise_job_error(job_id, 503, "MinerU configuration failed", exc, cache_id)
    except MinerUExtractionError as exc:
        _raise_job_error(job_id, 500, "Extraction failed", exc, cache_id)
    except HTTPException:
        # The 400 for an unmatched question bank is raised from inside this
        # try, so without this the blanket handler below reports it as a 500.
        raise
    except Exception as exc:
        update_status(job_id, "failed", f"Unexpected error: {exc}")
        logger.exception("Job %s - unexpected error", job_id)
        _mark_extraction_failed(
            cache_id,
            {"error": str(exc), "stage": "unexpected"},
        )
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred: {exc}",
        ) from exc
    finally:
        cleanup_temp_job(settings.temp_dir, job_id)
        await file.close()

@router.get(
    "/curriculums",
    tags=["Curriculum Processing"],
    summary="List all curriculums in document_extractions",
)
def list_curriculums() -> list[dict[str, Any]]:
    return get_all_curriculums()

@router.post(
    "/curriculums/{extraction_id}/process",
    tags=["Curriculum Processing"],
    summary="Process a curriculum using DeepSeek and populate lms_curriculum and lms_units",
)
async def process_curriculum(extraction_id: int, force: bool = False) -> dict[str, Any]:
    try:
        result = await asyncio.to_thread(process_curriculum_by_id, extraction_id, force)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to process curriculum")
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}")

@router.get(
    "/curriculums/{extraction_id}/result",
    tags=["Curriculum Processing"],
    summary="Fetch the lms_curriculum and lms_units data for a processed extraction",
)
def get_curriculum_result(extraction_id: int) -> dict[str, Any]:
    try:
        data = get_curriculum_data_by_extraction_id(extraction_id)
        if not data:
            raise HTTPException(status_code=404, detail="Curriculum data not found")
        return data
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch curriculum result")
        raise HTTPException(status_code=500, detail=f"Fetch failed: {exc}")


@router.get(
    "/chapters",
    tags=["Chapter Processing"],
    summary="List all chapters in document_extractions",
)
def list_chapters() -> list[dict[str, Any]]:
    return get_all_chapters()

@router.post(
    "/chapters/{extraction_id}/process",
    tags=["Chapter Processing"],
    summary="Process a chapter using DeepSeek and populate chapter_master",
)
async def process_chapter(extraction_id: int, force: bool = False) -> dict[str, Any]:
    try:
        result = await asyncio.to_thread(process_chapter_by_id, extraction_id, force)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to process chapter")
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}")

@router.get(
    "/chapters/{extraction_id}/result",
    tags=["Chapter Processing"],
    summary="Fetch the chapter_master data for a processed extraction",
)
def get_chapter_result(extraction_id: int) -> dict[str, Any]:
    try:
        data = get_chapter_data_by_extraction_id(extraction_id)
        if not data:
            raise HTTPException(status_code=404, detail="Chapter data not found")
        return data
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch chapter result")
        raise HTTPException(status_code=500, detail=f"Fetch failed: {exc}")

# The queues below run in hierarchy order: a chapter is extracted first, its
# topics are generated chapter-wise from that, and its concepts are generated
# topic-wise from the topics.

@router.get(
    "/topics",
    tags=["Topic Processing"],
    summary="List all chapters ready for topic processing",
)
def list_topics() -> list[dict[str, Any]]:
    return get_all_topics_queue()

@router.post(
    "/topics/{extraction_id}/process",
    tags=["Topic Processing"],
    summary="Find a chapter's main topics in one whole-chapter call and fill topic_master",
)
async def process_topics(extraction_id: int, force: bool = False) -> dict[str, Any]:
    try:
        return await process_topics_by_id(extraction_id, force)
    except DeepSeekUnavailableError as exc:
        # Upstream provider fault (billing/auth/model), not a bad request and
        # not our bug -- 503 so it reads as "retry once the account is fixed".
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to process topics")
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}")

@router.post(
    "/topics/{extraction_id}/part/{segment_index}/process",
    tags=["Topic Processing"],
    summary="Deprecated: chapters are no longer split into parts; re-runs the whole chapter",
    include_in_schema=False,
)
async def process_topics_for_part(extraction_id: int, segment_index: int) -> dict[str, Any]:
    # Topic extraction is a single whole-chapter call now, so there is no part
    # to retry. Kept so an open browser tab does not 404; it just reprocesses.
    return await process_topics(extraction_id, force=True)

@router.get(
    "/topics/{extraction_id}/result",
    tags=["Topic Processing"],
    summary="Fetch the topic_master data for a processed extraction, in teaching order",
)
def get_topic_result(extraction_id: int) -> dict[str, Any]:
    try:
        data = get_topic_data_by_extraction_id(extraction_id)
        if not data:
            raise HTTPException(status_code=404, detail="Topic data not found")
        return data
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch topic result")
        raise HTTPException(status_code=500, detail=f"Fetch failed: {exc}")

@router.get(
    "/concepts",
    tags=["Concept Processing"],
    summary="List all chapters ready for concept processing",
)
def list_concepts() -> list[dict[str, Any]]:
    return get_all_concepts_queue()

@router.post(
    "/concepts/{extraction_id}/process",
    tags=["Concept Processing"],
    summary="Break every topic of a chapter into concepts in one whole-chapter call",
)
async def process_concepts(extraction_id: int, force: bool = False) -> dict[str, Any]:
    try:
        return await process_concepts_by_id(extraction_id, force)
    except DeepSeekUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to process concepts")
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}")

@router.post(
    "/concepts/{extraction_id}/topic/{topic_id}/process",
    tags=["Concept Processing"],
    summary="Re-run concept extraction for one topic, still against the whole chapter",
)
async def process_concepts_for_topic(extraction_id: int, topic_id: int) -> dict[str, Any]:
    # One topic coming back empty should not cost a full reprocess. The retry
    # still sends the whole chapter -- only the set of topics asked about narrows.
    try:
        return await process_concepts_by_id(extraction_id, force=True, topic_id=topic_id)
    except DeepSeekUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to process concepts for topic %s", topic_id)
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}")

@router.get(
    "/validate/{extraction_id}",
    tags=["Validation"],
    summary="Audit a chapter's topics and concepts against the chapter content",
)
def validate_extraction_result(extraction_id: int) -> dict[str, Any]:
    # Deterministic and LLM-free, so it is safe to call as often as you like.
    try:
        return validate_extraction(extraction_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to validate extraction %s", extraction_id)
        raise HTTPException(status_code=500, detail=f"Validation failed: {exc}")

@router.get(
    "/concepts/{extraction_id}/result",
    tags=["Concept Processing"],
    summary="Fetch the lms_concept data for a processed extraction, grouped by topic",
)
def get_concept_result(extraction_id: int) -> dict[str, Any]:
    try:
        data = get_concept_data_by_extraction_id(extraction_id)
        if not data:
            raise HTTPException(status_code=404, detail="Concept data not found")
        return data
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch concept result")
        raise HTTPException(status_code=500, detail=f"Fetch failed: {exc}")


@router.post(
    "/questions/{extraction_id}/generate",
    tags=["Question Generation"],
    summary="Generate concept-wise questions for a chapter from its Semantic Intelligence",
)
async def generate_questions(
    extraction_id: int,
    total: int = 100,
    created_by: int = 0,
    replace: bool = False,
) -> dict[str, Any]:
    """Runs for minutes; prefer POST /api/jobs/questions/{id}/generate for the queued form."""
    try:
        return await generate_questions_by_extraction(
            extraction_id, total=total, created_by=created_by, replace=replace
        )
    except DeepSeekUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to generate questions")
        raise HTTPException(status_code=500, detail=f"Generation failed: {exc}")


@router.get(
    "/questions/{extraction_id}/result",
    tags=["Question Generation"],
    summary="Fetch the generated questions for an extraction, grouped by topic",
)
def get_question_result(extraction_id: int) -> dict[str, Any]:
    try:
        data = get_questions_by_extraction(extraction_id)
        if not data:
            raise HTTPException(status_code=404, detail="Question data not found")
        return data
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch question result")
        raise HTTPException(status_code=500, detail=f"Fetch failed: {exc}")


@router.get(
    "/semantic-intelligence",
    tags=["Semantic Intelligence"],
    summary="List all chapters for semantic intelligence processing",
)
def list_semantic_intelligence() -> list[dict[str, Any]]:
    return get_all_semantic_chapters()

@router.post(
    "/semantic-intelligence/{extraction_id}/process",
    tags=["Semantic Intelligence"],
    summary="Process a chapter using deep semantic intelligence",
)
async def process_semantic_intelligence(extraction_id: int, force: bool = False) -> dict[str, Any]:
    try:
        result = await process_semantic_chapter_by_id(extraction_id, force)
        return result
    except UnicodeError as exc:
        # UnicodeError subclasses ValueError, so without this it would surface
        # as a 400 and read like bad input. It is a server-side encoding fault.
        logger.exception("Encoding failure during semantic intelligence")
        raise HTTPException(status_code=500, detail=f"Encoding failure: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to process semantic intelligence")
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}")

@router.post(
    "/jobs/curriculums/{extraction_id}/process",
    status_code=202,
    tags=["Jobs"],
    summary="Queue curriculum processing and return a job id",
)
async def queue_curriculum_processing(extraction_id: int, force: bool = False) -> dict[str, Any]:
    """Background form of ``/curriculums/{id}/process``. See /api/status/{job_id}."""
    job_id = submit_job(
        f"Curriculum processing for extraction {extraction_id}",
        lambda: asyncio.to_thread(process_curriculum_by_id, extraction_id, force),
        semaphore=llm_semaphore(),
    )
    return _accepted(job_id)


@router.post(
    "/jobs/chapters/{extraction_id}/process",
    status_code=202,
    tags=["Jobs"],
    summary="Queue chapter processing and return a job id",
)
async def queue_chapter_processing(extraction_id: int, force: bool = False) -> dict[str, Any]:
    """Background form of ``/chapters/{id}/process``. See /api/status/{job_id}."""
    job_id = submit_job(
        f"Chapter processing for extraction {extraction_id}",
        lambda: asyncio.to_thread(process_chapter_by_id, extraction_id, force),
        semaphore=llm_semaphore(),
    )
    return _accepted(job_id)


@router.post(
    "/jobs/concepts/{extraction_id}/process",
    status_code=202,
    tags=["Jobs"],
    summary="Queue concept processing and return a job id",
)
async def queue_concept_processing(extraction_id: int, force: bool = False) -> dict[str, Any]:
    """Background form of ``/concepts/{id}/process``. See /api/status/{job_id}."""
    job_id = submit_job(
        f"Concept processing for extraction {extraction_id}",
        lambda: process_concepts_by_id(extraction_id, force),
        semaphore=llm_semaphore(),
    )
    return _accepted(job_id)


@router.post(
    "/jobs/questions/{extraction_id}/generate",
    status_code=202,
    tags=["Jobs"],
    summary="Queue question generation and return a job id",
)
async def queue_question_generation(
    extraction_id: int,
    total: int = 100,
    created_by: int = 0,
    replace: bool = False,
) -> dict[str, Any]:
    """Background form of ``/questions/{id}/generate``. See /api/status/{job_id}."""
    job_id = submit_job(
        f"Question generation for extraction {extraction_id}",
        lambda: generate_questions_by_extraction(
            extraction_id, total=total, created_by=created_by, replace=replace
        ),
        semaphore=llm_semaphore(),
    )
    return _accepted(job_id)


@router.post(
    "/jobs/semantic-intelligence/{extraction_id}/process",
    status_code=202,
    tags=["Jobs"],
    summary="Queue semantic intelligence processing and return a job id",
)
async def queue_semantic_processing(extraction_id: int, force: bool = False) -> dict[str, Any]:
    """Background form of ``/semantic-intelligence/{id}/process``.

    The swarm chains four DeepSeek agents per concept across every concept in
    the chapter, so this routinely outlives any proxy timeout.
    """
    job_id = submit_job(
        f"Semantic intelligence for extraction {extraction_id}",
        lambda: process_semantic_chapter_by_id(extraction_id, force),
        semaphore=llm_semaphore(),
    )
    return _accepted(job_id)


@router.get(
    "/semantic-intelligence/{extraction_id}/result",
    tags=["Semantic Intelligence"],
    summary="Fetch the semantic intelligence data for a processed extraction",
)
def get_semantic_intelligence_result(extraction_id: int) -> dict[str, Any]:
    try:
        data = get_semantic_data_by_extraction_id(extraction_id)
        if not data:
            raise HTTPException(status_code=404, detail="Semantic data not found")
        return data
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch semantic intelligence result")
        raise HTTPException(status_code=500, detail=f"Fetch failed: {exc}")


from sqlalchemy import text
from app.models.schemas import SubjectCreateRequest, TabLabelUpdateRequest

@router.get(
    "/subjects/{standard_name}",
    tags=["Subjects"],
    summary="List all subjects for a given standard",
)
def get_subjects_by_standard(
    standard_name: str,
    board: str | None = None,
    sub_institute_id: int | None = None,
) -> list[dict[str, Any]]:
    """Subjects taught at one standard, within one board's shared bank.

    The tenant was hardcoded to 341, which made the CBSE bank invisible to
    the extraction form. Pass `board` (cbse | cambridge) or an explicit
    `sub_institute_id`; omitting both falls back to the configured default.
    """
    if not init_mariadb() or SessionLocal is None:
        raise HTTPException(status_code=500, detail="Database not ready")
    tenant = (
        sub_institute_id
        if sub_institute_id is not None
        else settings.tenant_for_board(board)
    )
    db = SessionLocal()
    try:
        std_row = db.execute(
            text("SELECT id FROM standard WHERE name = :name AND sub_institute_id = :tenant LIMIT 1"),
            {"name": standard_name, "tenant": tenant}
        ).fetchone()

        if not std_row:
            return []

        std_id = std_row[0]

        subjects_row = db.execute(
            text("""
                SELECT s.id, s.subject_name
                FROM subject s
                JOIN sub_std_map map ON s.id = map.subject_id
                WHERE map.standard_id = :std_id AND s.sub_institute_id = :tenant
            """),
            {"std_id": std_id, "tenant": tenant}
        ).fetchall()

        return [{"id": row[0], "subject_name": row[1]} for row in subjects_row]
    except Exception as exc:
        logger.exception("Failed to fetch subjects")
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        db.close()


@router.post(
    "/subjects",
    tags=["Subjects"],
    summary="Create a new subject and map it to a standard",
)
def create_subject(request: SubjectCreateRequest) -> dict[str, Any]:
    """Create a subject in one board's shared bank and map it to a standard.

    Every statement here used to write sub_institute_id = 341, so a subject
    created while the form said CBSE was filed into the Cambridge bank and
    then never appeared in the CBSE dropdown.
    """
    if not init_mariadb() or SessionLocal is None:
        raise HTTPException(status_code=500, detail="Database not ready")
    tenant = (
        request.sub_institute_id
        if request.sub_institute_id is not None
        else settings.tenant_for_board(request.board)
    )
    db = SessionLocal()
    try:
        std_row = db.execute(
            text("SELECT id FROM standard WHERE name = :name AND sub_institute_id = :tenant LIMIT 1"),
            {"name": request.standard_name, "tenant": tenant}
        ).fetchone()
        if not std_row:
            raise HTTPException(status_code=404, detail="Standard not found")
        std_id = std_row[0]

        sub_row = db.execute(
            text("SELECT id FROM subject WHERE subject_name = :sname AND sub_institute_id = :tenant LIMIT 1"),
            {"sname": request.subject_name, "tenant": tenant}
        ).fetchone()

        if sub_row:
            sub_id = sub_row[0]
        else:
            max_id = db.execute(text("SELECT MAX(id) FROM subject")).scalar() or 0
            new_code = request.subject_code if request.subject_code else str(max_id + 1).zfill(4)
            board_suffix = (request.board or "").strip().upper() or str(tenant)
            short_name = request.short_name if request.short_name else request.subject_name[:5].capitalize() + f"-{board_suffix}"
            subj_type = request.subject_type if request.subject_type else 'Major'

            res = db.execute(
                text("INSERT INTO subject (subject_name, subject_code, subject_type, short_name, status, sub_institute_id) VALUES (:sname, :code, :type, :short, 1, :tenant)"),
                {"sname": request.subject_name, "code": new_code, "type": subj_type, "short": short_name, "tenant": tenant}
            )
            sub_id = res.lastrowid

        map_row = db.execute(
            text("SELECT id FROM sub_std_map WHERE standard_id = :std_id AND subject_id = :sub_id LIMIT 1"),
            {"std_id": std_id, "sub_id": sub_id}
        ).fetchone()

        if not map_row:
            # The old "fallback" re-ran the identical statement inside its own
            # except, so it could only ever fail twice. Dropped.
            d_name = request.display_name if request.display_name else request.subject_name
            db.execute(
                text("INSERT INTO sub_std_map (standard_id, subject_id, sub_institute_id, display_name) VALUES (:std_id, :sub_id, :tenant, :d_name)"),
                {"std_id": std_id, "sub_id": sub_id, "tenant": tenant, "d_name": d_name}
            )

        db.commit()
        return {"id": sub_id, "subject_name": request.subject_name}
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to create subject")
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Semantic Intelligence tab labels (tenant-wise renaming)
# ---------------------------------------------------------------------------

@router.get(
    "/semantic-intelligence-tabs",
    tags=["Semantic Intelligence"],
    summary="Tab display names for a tenant, defaults filled in",
)
def get_semantic_tab_labels(
    sub_institute_id: int = tab_labels.DEFAULT_SUB_INSTITUTE_ID,
) -> dict[str, Any]:
    try:
        return tab_labels.get_tab_labels(sub_institute_id)
    except tab_labels.TabLabelError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to fetch semantic tab labels")
        raise HTTPException(status_code=500, detail=f"Fetch failed: {exc}")


@router.put(
    "/semantic-intelligence-tabs",
    tags=["Semantic Intelligence"],
    summary="Rename Semantic Intelligence tabs for a tenant",
)
def update_semantic_tab_labels(request: TabLabelUpdateRequest) -> dict[str, Any]:
    try:
        return tab_labels.save_tab_labels(request.sub_institute_id, request.labels)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except tab_labels.TabLabelError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to save semantic tab labels")
        raise HTTPException(status_code=500, detail=f"Save failed: {exc}")


@router.delete(
    "/semantic-intelligence-tabs",
    tags=["Semantic Intelligence"],
    summary="Restore default tab names for a tenant",
)
def reset_semantic_tab_labels(
    sub_institute_id: int = tab_labels.DEFAULT_SUB_INSTITUTE_ID,
    tab_key: str | None = None,
) -> dict[str, Any]:
    try:
        return tab_labels.reset_tab_labels(sub_institute_id, tab_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except tab_labels.TabLabelError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to reset semantic tab labels")
        raise HTTPException(status_code=500, detail=f"Reset failed: {exc}")


# ---------------------------------------------------------------------------
# Question bank queue
# ---------------------------------------------------------------------------

@router.get(
    "/question-banks",
    tags=["Question Bank"],
    summary="List question-bank extractions for the ingestion queue",
)
def list_question_banks(
    sub_institute_id: int | None = None,
    standard: int | None = None,
    subject_name: str | None = None,
) -> list[dict[str, Any]]:
    """The /semantic-intelligence queue, narrowed to question banks.

    Unlike that one this filters, because question banks are per-board: the
    CBSE bank (tenant 1) and the Cambridge bank (341) share the table, and an
    unfiltered list would mix them.

    A question bank always hangs off an existing chapter, so `chapter_id` is
    part of the row -- a null there is a row written before the no-auto-create
    rule landed and needs re-mapping before ingestion.

    The document_type set mirrors db.mariadb.is_question_bank exactly; keep
    the two in step if a spelling is ever added there.
    """
    if not init_mariadb() or SessionLocal is None:
        raise HTTPException(status_code=500, detail="Database not ready")
    db = SessionLocal()
    try:
        rows = db.execute(
            text("""
                SELECT d.id, d.document_tittle, d.subject_name, d.standard, d.syear,
                       d.chapter_number, d.chapter_id, d.board, d.sub_institute_id,
                       d.content_sha256, d.extraction_status, d.created_at,
                       (d.extraction_status = 'extracted') AS is_processed
                  FROM document_extractions d
                 WHERE LOWER(TRIM(d.document_type))
                       IN ('question_bank', 'question bank', 'questionbank')
                   AND (:tenant IS NULL OR d.sub_institute_id = :tenant)
                   AND (:standard IS NULL OR d.standard = :standard)
                   AND (:subject_name IS NULL OR d.subject_name = :subject_name)
                 ORDER BY d.id DESC
            """),
            {
                "tenant": sub_institute_id,
                "standard": standard,
                "subject_name": subject_name,
            },
        ).mappings().fetchall()
        return [dict(row) for row in rows]
    except Exception as exc:
        logger.exception("Failed to list question banks")
        raise HTTPException(status_code=500, detail=f"Fetch failed: {exc}")
    finally:
        db.close()


@router.post(
    "/exam-questions/{extraction_id}/process",
    tags=["Question Bank"],
    summary="Parse a question bank into structured exam items and store them",
)
async def process_exam_questions_endpoint(
    extraction_id: int,
    created_by: int = 0,
    replace: bool = False,
    publish_clean: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Synchronous form, for a single chapter and for previews.

    `dry_run=true` parses and validates and writes nothing, which is how the
    queue screen shows an operator what Proceed is about to do.
    """
    try:
        return await asyncio.to_thread(
            process_exam_questions,
            extraction_id,
            created_by=created_by,
            replace=replace,
            publish_clean=publish_clean,
            dry_run=dry_run,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        # Not mapped to a chapter, or nothing extracted yet: operator error.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Question-bank processing failed")
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}") from exc


@router.post(
    "/jobs/exam-questions/{extraction_id}/process",
    status_code=202,
    tags=["Jobs"],
    summary="Queue question-bank processing and return a job id",
)
async def queue_exam_question_processing(
    extraction_id: int,
    created_by: int = 0,
    replace: bool = False,
    publish_clean: bool = True,
) -> dict[str, Any]:
    """Background form of ``/exam-questions/{id}/process``.

    Parsing is CPU-bound rather than LLM-bound, so this does not take the
    LLM semaphore -- it would needlessly block concept and semantic jobs.
    """
    # submit() takes a factory returning an AWAITABLE. process_exam_questions
    # is synchronous (regex parsing plus a DB transaction), so it is handed to
    # a worker thread: returning its dict directly makes the job runner try to
    # await a dict, and wrapping it keeps the blocking write off the single
    # event loop this service runs on.
    job_id = submit_job(
        f"Question-bank processing for extraction {extraction_id}",
        lambda: asyncio.to_thread(
            process_exam_questions,
            extraction_id,
            created_by=created_by,
            replace=replace,
            publish_clean=publish_clean,
        ),
    )
    return _accepted(job_id)


@router.get(
    "/exam-questions/{extraction_id}/result",
    tags=["Question Bank"],
    summary="Read the stored exam items for a chapter, grouped by CBSE section",
)
def get_exam_questions_endpoint(extraction_id: int) -> dict[str, Any]:
    try:
        data = get_exam_questions(extraction_id)
        if not data["total"]:
            raise HTTPException(
                status_code=404,
                detail="No stored questions for this extraction. Run Proceed first.",
            )
        return data
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch exam questions")
        raise HTTPException(status_code=500, detail=f"Fetch failed: {exc}") from exc


@router.get(
    "/publishers",
    tags=["Question Bank"],
    summary="List known question-bank publishers",
)
def list_publishers_endpoint() -> list[dict[str, Any]]:
    """Populates the publisher picker on the upload form."""
    try:
        seed_reference_data()
        return list_publishers()
    except Exception as exc:
        logger.exception("Failed to list publishers")
        raise HTTPException(status_code=500, detail=f"Fetch failed: {exc}") from exc


@router.get(
    "/question-types",
    tags=["Question Bank"],
    summary="List question forms, including publisher-specific ones",
)
def list_question_types_endpoint(publisher_id: int | None = None) -> list[dict[str, Any]]:
    """The vocabulary the bank filters on.

    A publisher's own form wins over the standard entry of the same code, so
    a house that redefines "case study" gets its own definition back.
    """
    try:
        seed_reference_data()
        return sorted(question_type_map(publisher_id).values(), key=lambda r: r["code"])
    except Exception as exc:
        logger.exception("Failed to list question types")
        raise HTTPException(status_code=500, detail=f"Fetch failed: {exc}") from exc


@router.post(
    "/exam-questions/{extraction_id}/tag",
    tags=["Question Bank"],
    summary="Map stored questions to chapter concepts, Bloom level and DOK",
)
async def tag_exam_questions_endpoint(
    extraction_id: int,
    provider: str = "auto",
) -> dict[str, Any]:
    """Run AFTER Proceed: re-running Proceed with replace clears these tags.

    provider "auto" uses DeepSeek and falls back to the offline lexical
    matcher when the account is unavailable; "deepseek" fails loudly instead;
    "offline" skips the model entirely.
    """
    try:
        return await tag_extraction(extraction_id, provider=provider)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DeepSeekUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Concept tagging failed")
        raise HTTPException(status_code=500, detail=f"Tagging failed: {exc}") from exc


@router.post(
    "/jobs/exam-questions/{extraction_id}/tag",
    status_code=202,
    tags=["Jobs"],
    summary="Queue concept tagging and return a job id",
)
async def queue_exam_question_tagging(
    extraction_id: int,
    provider: str = "auto",
) -> dict[str, Any]:
    """Background form of ``/exam-questions/{id}/tag``.

    Takes the LLM semaphore, because unlike parsing this one really does
    call the model and must queue behind the other LLM stages.
    """
    job_id = submit_job(
        f"Concept tagging for extraction {extraction_id}",
        lambda: tag_extraction(extraction_id, provider=provider),
        semaphore=llm_semaphore(),
    )
    return _accepted(job_id)
