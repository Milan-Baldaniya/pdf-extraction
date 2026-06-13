"""Phase 3 API routes — AI Teaching Intelligence Engine.

Loads Phase 2 semantic JSON from Supabase, calls DeepSeek to produce
slide-by-slide teaching plans, validates them, and persists the result.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db.supabase_client import supabase
from app.semantic_intelligence.deepseek_client import call_deepseek
from app.teaching_intelligence.prompt import build_teaching_intelligence_prompt
from app.teaching_intelligence.parser import (
    validate_teaching_intelligence_output,
    calculate_teaching_quality_flag,
)
from app.utils.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Teaching Intelligence"])


# ─── Request Schema ─────────────────────────────────────────────────────────

class GenerateTeachingRequest(BaseModel):
    """Request body for POST /teaching-intelligence/generate."""

    standard_id: int
    subject_id: int
    chapter_id: int
    language: str = "english"
    teaching_style: str = "engaging"
    difficulty_level: str = "grade_level"
    # force_new=True creates a fresh record even if same style exists
    force_new: bool = False


# ─── Internal Helpers ───────────────────────────────────────────────────────

def _prompt_version() -> int:
    return getattr(settings, "phase3_prompt_version", 1)


def _require_supabase():
    if supabase is None:
        raise HTTPException(503, "Supabase is not configured.")
    return supabase


VALID_LANGUAGES = {"english", "hindi", "bilingual"}
VALID_STYLES = {"engaging", "storytelling", "serious", "activity_based", "exam_focused"}
VALID_LEVELS = {"simplified", "grade_level", "advanced"}


def _validate_style_params(req: GenerateTeachingRequest):
    if req.language not in VALID_LANGUAGES:
        raise HTTPException(400, f"Invalid language. Choose from: {VALID_LANGUAGES}")
    if req.teaching_style not in VALID_STYLES:
        raise HTTPException(400, f"Invalid teaching_style. Choose from: {VALID_STYLES}")
    if req.difficulty_level not in VALID_LEVELS:
        raise HTTPException(400, f"Invalid difficulty_level. Choose from: {VALID_LEVELS}")


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.post("/generate")
async def generate_teaching_intelligence(req: GenerateTeachingRequest):
    """Main Phase 3 endpoint.

    Loads Phase 2 JSON from Supabase -> calls DeepSeek -> validates -> stores result.
    """
    db = _require_supabase()
    _validate_style_params(req)
    prompt_version = _prompt_version()

    # ── STEP 1: Check cache ──────────────────────────────────────────────
    if not req.force_new:
        try:
            existing = (
                db.table("teaching_intelligence")
                .select("*")
                .eq("chapter_id", req.chapter_id)
                .eq("language", req.language)
                .eq("teaching_style", req.teaching_style)
                .eq("difficulty_level", req.difficulty_level)
                .eq("prompt_version", prompt_version)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if existing.data:
                return {"status": "cached", "data": existing.data[0]}
        except Exception as exc:
            logger.warning("Teaching intelligence cache lookup failed: %s", exc)

    # ── STEP 2: Load Phase 2 data from Supabase ─────────────────────────
    try:
        p2_result = (
            db.table("chapter_semantic_intelligence")
            .select("*")
            .eq("chapter_id", req.chapter_id)
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(500, f"Failed to load Phase 2 data: {exc}") from exc

    if not p2_result.data:
        raise HTTPException(
            404,
            f"Phase 2 not found for chapter_id={req.chapter_id}. "
            "Run /semantic-intelligence/generate first.",
        )

    p2_record = p2_result.data[0]

    # ── STEP 3: Block if Phase 2 quality is bad ─────────────────────────
    if p2_record.get("quality_flag") == "regenerate":
        raise HTTPException(
            400,
            "Phase 2 quality_flag is 'regenerate'. Fix Phase 2 before running Phase 3.",
        )

    phase2_json = p2_record["full_intelligence_json"]
    semantic_id = p2_record["id"]

    # Use IDs directly from the request
    standard_id = req.standard_id
    subject_id = req.subject_id
    chapter_id = req.chapter_id

    # ── STEP 4: Build Phase 3 prompt ─────────────────────────────────────
    prompt = build_teaching_intelligence_prompt(
        phase2_json=phase2_json,
        teaching_style=req.teaching_style,
        language=req.language,
        difficulty_level=req.difficulty_level,
    )

    # ── STEP 5: Call DeepSeek ───────────────────────────────────────────────
    try:
        system_prompt = "You are an expert teaching assistant. Return exactly a JSON object."
        deepseek_result = await asyncio.to_thread(call_deepseek, prompt, system_prompt, {"type": "json_object"})
    except Exception as exc:
        raise HTTPException(500, f"DeepSeek call failed: {exc}") from exc

    raw_json = deepseek_result["data"]

    # ── STEP 6: Validate response ─────────────────────────────────────────
    try:
        validated = validate_teaching_intelligence_output(raw_json)
        quality_flag = calculate_teaching_quality_flag(validated)
    except Exception as exc:
        raise HTTPException(422, f"Phase 3 validation failed: {exc}") from exc

    # ── STEP 7: Save to Supabase ──────────────────────────────────────────
    record = {
        "semantic_id": semantic_id,
        "standard_id": standard_id,
        "subject_id": subject_id,
        "chapter_id": chapter_id,
        "language": req.language,
        "teaching_style": req.teaching_style,
        "difficulty_level": req.difficulty_level,
        "full_teaching_json": raw_json,
        "total_slides_planned": len(validated.slide_teaching_plans),
        "llm_model": settings.deepseek_model,
        "prompt_version": prompt_version,
        "input_tokens": deepseek_result["input_tokens"],
        "output_tokens": deepseek_result["output_tokens"],
    }

    try:
        if req.force_new:
            db.table("teaching_intelligence").delete().match({
                "chapter_id": chapter_id,
                "language": req.language,
                "teaching_style": req.teaching_style,
                "difficulty_level": req.difficulty_level,
                "prompt_version": prompt_version
            }).execute()
        db.table("teaching_intelligence").insert(record).execute()
    except Exception as exc:
        raise HTTPException(500, f"Database insert failed: {exc}") from exc

    return {
        "status": "success",
        "chapter_title": validated.chapter_title,
        "teaching_style": req.teaching_style,
        "language": req.language,
        "total_slides_planned": len(validated.slide_teaching_plans),
        "quality_flag": quality_flag,
        "tokens_used": {
            "input": deepseek_result["input_tokens"],
            "output": deepseek_result["output_tokens"],
        },
        "full_teaching_json": raw_json,
    }


@router.get("/chapter/{chapter_id}")
async def get_teaching_intelligence(
    chapter_id: int,
    style: str = "engaging",
    lang: str = "english",
    level: str = "grade_level",
):
    """Get the most recent teaching plan for a chapter and style combination."""
    db = _require_supabase()
    try:
        result = (
            db.table("teaching_intelligence")
            .select("*")
            .eq("chapter_id", chapter_id)
            .eq("teaching_style", style)
            .eq("language", lang)
            .eq("difficulty_level", level)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            raise HTTPException(404, "No teaching intelligence found for this combination")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Database query failed: {exc}") from exc


@router.get("/chapter/{chapter_id}/all-styles")
async def get_all_styles(chapter_id: int):
    """List all generated style variants for a chapter."""
    db = _require_supabase()
    result = (
        db.table("teaching_intelligence")
        .select("id, teaching_style, language, difficulty_level, total_slides_planned, created_at")
        .eq("chapter_id", chapter_id)
        .order("created_at", desc=True)
        .execute()
    )
    return {"chapter_id": chapter_id, "variants": result.data}
