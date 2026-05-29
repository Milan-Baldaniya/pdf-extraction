"""API routes for Gemini-powered chapter semantic intelligence."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db.supabase_client import supabase
from app.semantic_intelligence.gemini_client import call_gemini
from app.semantic_intelligence.parser import (
    calculate_quality_flag,
    extract_summary_fields,
    validate_semantic_intelligence_output,
)
from app.utils.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Semantic Intelligence"])


class GenerateRequest(BaseModel):
    markdown_file_path: str | None = None
    markdown_content: str | None = None
    pdf_cache_id: int | None = None
    force_regenerate: bool = False


def _prompt_version() -> int:
    return (
        settings.semantic_intelligence_prompt_version
        or settings.phase2_prompt_version
        or 1
    )


def _require_supabase():
    if supabase is None:
        raise HTTPException(
            status_code=503,
            detail="Supabase is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_KEY.",
        )
    return supabase


def _read_markdown(req: GenerateRequest) -> str:
    if req.markdown_content:
        return req.markdown_content
    if req.markdown_file_path:
        markdown_path = Path(req.markdown_file_path).expanduser().resolve()
        if not markdown_path.is_file():
            raise HTTPException(status_code=404, detail="Markdown file not found")
        return markdown_path.read_text(encoding="utf-8", errors="replace")
    raise HTTPException(status_code=400, detail="Must provide markdown_content or markdown_file_path")


def split_markdown_by_headings(markdown: str, units: list) -> dict:
    import re
    lines = markdown.split("\n")
    sections = {}
    current_unit_id = None
    current_lines = []
    
    def is_match(line_clean, unit_title_clean):
        if not line_clean or not unit_title_clean:
            return False
        # Remove numbers from the start to help matching "1.1 Intro" with "Intro"
        line_no_num = re.sub(r'^[\d\.\s]+', '', line_clean).strip()
        unit_no_num = re.sub(r'^[\d\.\s]+', '', unit_title_clean).strip()
        if not line_no_num or not unit_no_num:
            return False
        return unit_no_num in line_no_num or line_no_num in unit_no_num
    
    for line in lines:
        if line.strip().startswith("#"):
            clean = re.sub(r'^#+\s*', '', line).lower().strip()
            
            matched_unit_id = None
            for u in units:
                title = u.get("topic_title", "").lower().strip()
                if is_match(clean, title):
                    matched_unit_id = u.get("unit_id")
                    break
            
            if matched_unit_id:
                if current_unit_id:
                    sections[current_unit_id] = "\n".join(current_lines)
                current_unit_id = matched_unit_id
                current_lines = [line]
                continue
                
        current_lines.append(line)
            
    if current_unit_id:
        sections[current_unit_id] = "\n".join(current_lines)
        
    for u in units:
        uid = u.get("unit_id")
        if uid not in sections:
            sections[uid] = markdown
            
    return sections


async def _two_pass_extraction(markdown_content: str, subject: str, class_level: str):
    from app.semantic_intelligence.prompt import build_structure_pass_prompt, build_deep_extraction_prompt
    
    structure_prompt = build_structure_pass_prompt(markdown_content, subject, class_level)
    structure_result = await asyncio.to_thread(call_gemini, structure_prompt)
    skeleton = structure_result["data"]
    
    sections = split_markdown_by_headings(markdown_content, skeleton.get("teaching_units", []))
    
    semaphore = asyncio.Semaphore(4)
    
    async def _process_unit(unit):
        async with semaphore:
            try:
                result = await asyncio.to_thread(
                    call_gemini,
                    build_deep_extraction_prompt(
                        unit_text=sections.get(unit["unit_id"], "No content found."),
                        unit_title=unit["topic_title"],
                        chapter_title=skeleton.get("chapter_title", "Unknown"),
                        subject=subject,
                        class_level=class_level,
                        chapter_type=skeleton.get("chapter_type", "other"),
                    )
                )
                if result and "data" in result:
                    result["data"]["unit_id"] = unit["unit_id"]
                return result
            except Exception as e:
                logger.error(f"Failed to extract unit {unit['unit_id']}: {e}")
                return None

    tasks = [_process_unit(unit) for unit in skeleton.get("teaching_units", [])]
    
    unit_results = await asyncio.gather(*tasks)
    
    valid_results = [r for r in unit_results if r is not None]
    teaching_units = [r["data"] for r in valid_results]
    
    total_input_tokens = structure_result["input_tokens"] + sum(r["input_tokens"] for r in valid_results)
    total_output_tokens = structure_result["output_tokens"] + sum(r["output_tokens"] for r in valid_results)
    
    assembled_json = {
        "subject": subject,
        "class": class_level,
        "chapter_title": skeleton.get("chapter_title", ""),
        "short_summary": skeleton.get("short_summary", ""),
        "learning_objectives": skeleton.get("learning_objectives", ""),
        "chapter_apparatus": skeleton.get("chapter_apparatus", None),
        "teaching_units": teaching_units
    }
    
    return assembled_json, total_input_tokens, total_output_tokens


@router.post("/generate")
async def generate_semantic_intelligence(req: GenerateRequest):
    db = _require_supabase()
    prompt_version = _prompt_version()
    llm_model = settings.gemini_model

    if not req.force_regenerate and req.pdf_cache_id:
        try:
            cached = (
                db.table("chapter_semantic_intelligence")
                .select("*")
                .eq("pdf_cache_id", req.pdf_cache_id)
                .eq("prompt_version", prompt_version)
                .execute()
            )
            if cached.data:
                return {"status": "cached", "data": cached.data[0]}
        except Exception as exc:
            logger.warning("Semantic intelligence cache lookup failed: %s", exc)

    markdown_content = _read_markdown(req)
    
    # Get metadata for this run
    meta = {
        "standard_id": 10,
        "subject_id": 5,
        "chapter_id": 1,
        "subject_name": "Generic",
        "class_level": "Class 10"
    }
    
    if req.pdf_cache_id:
        try:
            db_res = db.table("pdf_processing_cache").select("*").eq("id", req.pdf_cache_id).execute()
            if db_res.data:
                row = db_res.data[0]
                meta["standard_id"] = row.get("standard_id", 10)
                meta["subject_id"] = row.get("subject_id", 5)
                meta["chapter_id"] = row.get("chapter_id", 1)
        except Exception as exc:
            logger.warning("Failed to fetch pdf_processing_cache metadata: %s", exc)
    
    # Do a quick Gemini extraction for names if needed
    try:
        from app.semantic_intelligence.gemini_client import extract_pdf_metadata
        extracted_meta = await extract_pdf_metadata(markdown_content)
        meta["subject_name"] = extracted_meta.get("subject_name", meta["subject_name"])
        meta["class_level"] = extracted_meta.get("class_level", meta["class_level"])
        if not req.pdf_cache_id:
            meta.update(extracted_meta)
    except Exception as exc:
        logger.warning("Failed to extract textual metadata for prompt: %s", exc)
    
    try:
        raw_json, input_tokens, output_tokens = await _two_pass_extraction(
            markdown_content, meta["subject_name"], meta["class_level"]
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gemini two-pass call failed: {exc}") from exc

    try:
        validated = validate_semantic_intelligence_output(raw_json)
        summary_fields = extract_summary_fields(validated)
        quality_flag = calculate_quality_flag(validated)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Failed to parse or validate semantic intelligence output: {exc}",
        ) from exc
        
    import datetime
    
    final_json = {
        "metadata": {
            "extraction_strategy": "two_pass",
            "prompt_version": prompt_version,
            "total_units_extracted": len(raw_json.get("teaching_units", [])),
            "extraction_timestamp": datetime.datetime.utcnow().isoformat(),
            "model_used": llm_model,
        },
        "intelligence": raw_json
    }

    record = {
        "pdf_cache_id": req.pdf_cache_id,
        "standard_id": meta["standard_id"],
        "subject_id": meta["subject_id"],
        "chapter_id": meta["chapter_id"],
        "subject_name": meta["subject_name"],
        "class_level": meta["class_level"],
        "prompt_version": prompt_version,
        "chapter_title": summary_fields["chapter_title"],
        "short_summary": summary_fields["short_summary"],
        "learning_objectives": summary_fields["learning_objectives"],
        "total_topics": summary_fields["total_topics"],
        "total_subtopics": summary_fields["total_subtopics"],
        "full_intelligence_json": final_json,
        "llm_model": llm_model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "quality_flag": quality_flag,
    }

    try:
        db.table("chapter_semantic_intelligence").upsert(
            record,
            on_conflict="chapter_id,prompt_version",
        ).execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database upsert failed: {exc}") from exc

    return {
        "status": "success",
        "chapter_title": summary_fields["chapter_title"],
        "total_topics": summary_fields["total_topics"],
        "total_subtopics": summary_fields["total_subtopics"],
        "quality_flag": quality_flag,
        "full_intelligence_json": final_json,
        "tokens_used": {
            "input": input_tokens,
            "output": output_tokens,
        },
    }


@router.get("/chapter/{chapter_id}")
async def get_chapter(chapter_id: int):
    db = _require_supabase()
    try:
        result = (
            db.table("chapter_semantic_intelligence")
            .select("*")
            .eq("chapter_id", chapter_id)
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Chapter not found")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database query failed: {exc}") from exc
