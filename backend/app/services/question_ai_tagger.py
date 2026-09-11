"""Map extracted questions onto a chapter's concepts, Bloom level and DOK.

This is the one part of the question-bank pipeline a model is genuinely
worth paying for. Section, marks, options and the correct answer are all
printed on the page and are read deterministically; which concept a question
exercises is not — an exercise stem rarely repeats the concept's name, so it
has to be inferred from meaning.

Two providers:

  deepseek  the real one. Batched per CBSE section so the concept list and
            instructions are paid for once per batch rather than per item.
  offline   a deterministic lexical matcher. It exists because the DeepSeek
            account can be out of balance, and because a pipeline you cannot
            run is a pipeline you cannot test. It scores concept-name and
            keyword overlap against the stem, and is honest about it: every
            row it writes is stamped `ai_model = 'offline-lexical-v1'` with a
            low confidence, so a later real pass can be told apart from it
            and nothing downstream mistakes it for model judgement.

The DeepSeek response is validated with Pydantic. The rest of this codebase
asks for a schema in the prompt and then reads the dict hopefully; for a
stage whose whole purpose is correct tagging, "we asked and hoped" is the
wrong bar, and a malformed batch must fail loudly rather than return {}.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text

from app.db.mariadb import SessionLocal, init_mariadb
from app.semantic_intelligence.deepseek_client import (
    DeepSeekUnavailableError,
    async_call_deepseek,
)
from app.utils.config import settings

logger = logging.getLogger(__name__)

OFFLINE_MODEL = "offline-lexical-v1"

# PAL's closed Bloom vocabulary. Note `recall`, not `remember`: the LMS
# rejects the latter, and a tag the LMS will not accept is worse than none.
BLOOM_LEVELS = ("recall", "understand", "apply", "analyze", "evaluate", "create")

# PAL and the LMS question bank spell Bloom differently: PAL uses the lowercase
# closed set above, while lms_question_master.g_bloom holds Title-Case values
# and calls the first level "Remember". Both are live, so translate at the
# boundary rather than picking a winner.
_LMS_BLOOM = {
    "recall": "Remember",
    "understand": "Understand",
    "apply": "Apply",
    "analyze": "Analyze",
    "evaluate": "Evaluate",
    "create": "Create",
}


def _lms_difficulty(score: int | None) -> str | None:
    """Collapse our 1-5 score onto g_difficulty's three-value varchar(8)."""
    if score is None:
        return None
    if score <= 2:
        return "Easy"
    return "Medium" if score == 3 else "Hard"

_BATCH_SIZE = 12
_STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "is", "are", "in", "on", "for", "to",
    "what", "which", "find", "if", "then", "that", "this", "with", "from", "by",
    "its", "it", "be", "as", "at", "value", "following", "given", "when", "write",
    "state", "show", "prove", "draw", "using", "each", "any", "two", "one",
}


class ConceptTag(BaseModel):
    """One model verdict about one question."""

    ref: str = Field(description="Echo of the ref the request supplied")
    concept_id: int | None = Field(default=None)
    concept_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    bloom_level: str | None = Field(default=None)
    dok_level: int | None = Field(default=None, ge=1, le=4)
    difficulty_1_to_5: int | None = Field(default=None, ge=1, le=5)
    rationale: str | None = Field(default=None)


class ConceptTagBatch(BaseModel):
    items: list[ConceptTag] = Field(default_factory=list)


_SYSTEM_PROMPT = (
    "You tag school exam questions against a fixed list of chapter concepts.\n"
    "Rules:\n"
    "1. concept_id MUST be one of the ids supplied, or null. Never invent one.\n"
    "2. Use null when no supplied concept genuinely matches; a wrong tag is\n"
    "   worse than no tag, because it routes a learner to the wrong remediation.\n"
    "3. bloom_level must be exactly one of: recall, understand, apply, analyze,\n"
    "   evaluate, create.\n"
    "4. dok_level is 1-4. difficulty_1_to_5 is 1-5.\n"
    "5. Echo the ref of every question you were given, exactly once.\n"
    "You must respond ONLY with valid JSON matching this schema:\n"
)


def _session():
    if not init_mariadb() or SessionLocal is None:
        raise RuntimeError("Database not ready")
    return SessionLocal()


def _load_concepts(chapter_id: int) -> list[dict[str, Any]]:
    db = _session()
    try:
        # lms_concept names the column `name` (verified against the live
        # schema); older installs used `concept`, so the fallback below still
        # exists rather than letting a column label kill the stage.
        rows = db.execute(
            text(
                "SELECT id, name, description FROM lms_concept "
                "WHERE chapter_id = :c ORDER BY id"
            ),
            {"c": chapter_id},
        ).mappings().fetchall()
        return [dict(r) for r in rows]
    except Exception:
        db.rollback()
        rows = db.execute(
            text("SELECT * FROM lms_concept WHERE chapter_id = :c ORDER BY id LIMIT 500"),
            {"c": chapter_id},
        ).mappings().fetchall()
        out = []
        for r in rows:
            d = dict(r)
            name = d.get("concept") or d.get("name") or d.get("concept_name") or ""
            out.append({"id": d.get("id"), "name": name, "description": d.get("description")})
        return out
    finally:
        db.close()


def _load_items(extraction_id: int) -> list[dict[str, Any]]:
    db = _session()
    try:
        rows = db.execute(
            text(
                """
                SELECT e.id AS sidecar_id, e.question_id, e.item_number, e.exam_section,
                       e.item_form, e.item_ordinal, q.question_title, q.answer
                  FROM lms_question_extraction e
                  JOIN lms_question_master q ON q.id = e.question_id
                 WHERE e.extraction_id = :e
                 ORDER BY e.item_ordinal
                """
            ),
            {"e": extraction_id},
        ).mappings().fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def _tokens(value: str) -> set[str]:
    words = re.findall(r"[a-z]{3,}", (value or "").lower())
    return {w for w in words if w not in _STOPWORDS}


def _offline_tags(
    items: list[dict[str, Any]], concepts: list[dict[str, Any]]
) -> list[ConceptTag]:
    """Deterministic lexical fallback.

    Scores token overlap between the question and each concept name, with the
    name weighted above the description. Confidence is deliberately capped
    low: this is a keyword match, not comprehension, and nothing downstream
    should treat it as a model's judgement.
    """
    concept_tokens = [
        (c["id"], _tokens(c.get("name") or ""), _tokens(c.get("description") or ""))
        for c in concepts
    ]
    out: list[ConceptTag] = []
    for item in items:
        stem = item.get("question_title") or ""
        stem_tokens = _tokens(stem)
        best_id, best_score = None, 0.0
        for cid, name_tokens, desc_tokens in concept_tokens:
            if not name_tokens:
                continue
            name_hits = len(stem_tokens & name_tokens) / max(1, len(name_tokens))
            desc_hits = len(stem_tokens & desc_tokens) / max(1, len(desc_tokens) or 1)
            score = (name_hits * 0.8) + (desc_hits * 0.2)
            if score > best_score:
                best_id, best_score = cid, score

        form = item.get("item_form") or ""
        bloom = {
            "mcq": "understand",
            "assertion_reason": "analyze",
            "very_short": "recall",
            "short": "apply",
            "long": "apply",
            "case_study_parent": "analyze",
            "proof": "analyze",
        }.get(form, "understand")
        dok = {"mcq": 1, "assertion_reason": 2, "very_short": 1,
               "short": 2, "long": 3, "case_study_parent": 3}.get(form, 2)

        out.append(
            ConceptTag(
                ref=str(item["item_ordinal"]),
                concept_id=best_id if best_score >= 0.25 else None,
                # Capped at 0.45: never let a keyword match look confident.
                concept_confidence=round(min(best_score, 0.45), 3),
                bloom_level=bloom,
                dok_level=dok,
                difficulty_1_to_5={1: 2, 2: 3, 3: 4}.get(dok, 3),
                rationale=f"lexical overlap score {best_score:.2f}",
            )
        )
    return out


async def _deepseek_tags(
    items: list[dict[str, Any]], concepts: list[dict[str, Any]]
) -> list[ConceptTag]:
    """Batched real tagging. Raises on a batch that cannot be validated."""
    concept_list = "\n".join(
        f"  - id={c['id']}: {c.get('name') or '(unnamed)'}"
        + (f" — {str(c['description'])[:160]}" if c.get("description") else "")
        for c in concepts
    )
    system = _SYSTEM_PROMPT + json.dumps(ConceptTagBatch.model_json_schema())

    tags: list[ConceptTag] = []
    for start in range(0, len(items), _BATCH_SIZE):
        batch = items[start: start + _BATCH_SIZE]
        questions = "\n".join(
            f'  {{"ref": "{i["item_ordinal"]}", "section": "{i.get("exam_section")}", '
            f'"form": "{i.get("item_form")}", "question": {json.dumps((i.get("question_title") or "")[:700])}}}'
            for i in batch
        )
        prompt = (
            f"CHAPTER CONCEPTS:\n{concept_list}\n\n"
            f"QUESTIONS ({len(batch)}):\n{questions}\n\n"
            f"Return one entry per question, echoing each ref exactly."
        )
        raw = await async_call_deepseek(
            prompt, system_prompt=system, response_format={"type": "json_object"}
        )
        payload = raw.get("data") if isinstance(raw, dict) and "data" in raw else raw
        try:
            parsed = ConceptTagBatch.model_validate(payload)
        except ValidationError as exc:
            # One retry with the error appended, then fail the batch. Silently
            # returning {} is how a chapter of nulls happens.
            retry = await async_call_deepseek(
                prompt + f"\n\nYour previous reply was rejected: {exc}. Return valid JSON.",
                system_prompt=system,
                response_format={"type": "json_object"},
            )
            payload = retry.get("data") if isinstance(retry, dict) and "data" in retry else retry
            parsed = ConceptTagBatch.model_validate(payload)
        tags.extend(parsed.items)
    return tags


def _sanitise(tags: list[ConceptTag], valid_ids: set[int]) -> list[ConceptTag]:
    """Drop hallucinated concept ids and out-of-vocabulary Bloom levels."""
    cleaned: list[ConceptTag] = []
    for tag in tags:
        if tag.concept_id is not None and tag.concept_id not in valid_ids:
            logger.warning("Dropping hallucinated concept_id %s for ref %s", tag.concept_id, tag.ref)
            tag = tag.model_copy(update={"concept_id": None, "concept_confidence": 0.0})
        if tag.bloom_level and tag.bloom_level.lower() not in BLOOM_LEVELS:
            mapped = {"remember": "recall", "analyse": "analyze"}.get(
                tag.bloom_level.lower()
            )
            tag = tag.model_copy(update={"bloom_level": mapped})
        elif tag.bloom_level:
            tag = tag.model_copy(update={"bloom_level": tag.bloom_level.lower()})
        cleaned.append(tag)
    return cleaned


def _persist(
    extraction_id: int, items: list[dict[str, Any]], tags: list[ConceptTag], model: str
) -> dict[str, int]:
    by_ref = {t.ref: t for t in tags}
    counters = {"tagged": 0, "with_concept": 0, "unmatched": 0}
    db = _session()
    try:
        for item in items:
            tag = by_ref.get(str(item["item_ordinal"]))
            if tag is None:
                counters["unmatched"] += 1
                continue
            db.execute(
                text(
                    """
                    UPDATE lms_question_extraction
                       SET concept_id = :concept_id,
                           concept_confidence = :confidence,
                           bloom_level = :bloom,
                           dok_level = :dok,
                           difficulty_1_to_5 = :difficulty,
                           ai_model = :model,
                           ai_tagged_at = CURRENT_TIMESTAMP,
                           ai_rationale = :rationale
                     WHERE id = :sidecar_id
                    """
                ),
                {
                    "concept_id": tag.concept_id,
                    "confidence": tag.concept_confidence,
                    "bloom": tag.bloom_level,
                    "dok": tag.dok_level,
                    "difficulty": tag.difficulty_1_to_5,
                    "model": model,
                    "rationale": (tag.rationale or "")[:2000] or None,
                    "sidecar_id": item["sidecar_id"],
                },
            )
            # Mirror onto the question itself. g_bloom/g_difficulty/g_dok are
            # plain (not generated) columns in this schema and they carry
            # idx_qm_blueprint(chapter_id, question_type_id, g_bloom,
            # g_difficulty, status) -- so writing them is what makes the bank's
            # bloom/difficulty filters index-backed instead of a 62k scan.
            db.execute(
                text(
                    """
                    UPDATE lms_question_master
                       SET concept_id   = COALESCE(:concept_id, concept_id),
                           g_bloom      = :g_bloom,
                           g_dok        = :g_dok,
                           g_difficulty = :g_difficulty
                     WHERE id = :q
                    """
                ),
                {
                    "concept_id": tag.concept_id,
                    "g_bloom": _LMS_BLOOM.get(tag.bloom_level or ""),
                    "g_dok": tag.dok_level,
                    "g_difficulty": _lms_difficulty(tag.difficulty_1_to_5),
                    "q": item["question_id"],
                },
            )
            if tag.concept_id:
                counters["with_concept"] += 1
            counters["tagged"] += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return counters


async def tag_extraction(
    extraction_id: int,
    *,
    provider: str = "auto",
) -> dict[str, Any]:
    """Tag every stored item for one extraction.

    provider: "auto" tries DeepSeek and falls back to the offline matcher if
    the account is unavailable; "deepseek" fails loudly instead; "offline"
    skips the model entirely.
    """
    db = _session()
    try:
        record = db.execute(
            text(
                "SELECT id, chapter_id, sub_institute_id, document_tittle "
                "FROM document_extractions WHERE id = :e"
            ),
            {"e": extraction_id},
        ).mappings().fetchone()
    finally:
        db.close()
    if not record:
        raise LookupError(f"Extraction {extraction_id} not found")
    if not record["chapter_id"]:
        raise ValueError("Extraction is not mapped to a chapter; cannot tag concepts.")

    items = _load_items(extraction_id)
    if not items:
        raise ValueError("No stored questions for this extraction. Run Proceed first.")

    concepts = _load_concepts(record["chapter_id"])
    if not concepts:
        # Not fatal. Chapter-level routing is already the estate's reality for
        # the overwhelming majority of rows, so tag what we can and say so.
        logger.warning("Chapter %s has no concepts; tagging Bloom/DOK only.", record["chapter_id"])

    model = OFFLINE_MODEL
    used = "offline"
    notes: list[str] = []

    if provider in {"auto", "deepseek"} and concepts:
        try:
            tags = await _deepseek_tags(items, concepts)
            model = settings.active_llm_model
            used = "deepseek"
        except DeepSeekUnavailableError as exc:
            if provider == "deepseek":
                raise
            notes.append(f"DeepSeek unavailable ({exc}); used the offline matcher instead.")
            logger.warning("DeepSeek unavailable, falling back to offline tagging: %s", exc)
            tags = _offline_tags(items, concepts)
        except (ValidationError, Exception) as exc:  # noqa: BLE001 - reported, not hidden
            if provider == "deepseek":
                raise
            notes.append(f"DeepSeek tagging failed ({type(exc).__name__}); used the offline matcher.")
            logger.warning("DeepSeek tagging failed, falling back: %s", exc)
            tags = _offline_tags(items, concepts)
    else:
        tags = _offline_tags(items, concepts)
        if not concepts:
            notes.append("Chapter has no concepts; concept_id left null on every item.")

    tags = _sanitise(tags, {c["id"] for c in concepts})
    counters = _persist(extraction_id, items, tags, model)

    bloom_spread: dict[str, int] = {}
    for tag in tags:
        if tag.bloom_level:
            bloom_spread[tag.bloom_level] = bloom_spread.get(tag.bloom_level, 0) + 1

    return {
        "status": "success",
        "extraction_id": extraction_id,
        "chapter_id": record["chapter_id"],
        "provider": used,
        "model": model,
        "concepts_available": len(concepts),
        "items": len(items),
        **counters,
        "bloom_spread": bloom_spread,
        "notes": notes,
    }
