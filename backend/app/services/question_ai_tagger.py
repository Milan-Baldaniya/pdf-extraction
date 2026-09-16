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
from collections import Counter
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
    # No default. With `Field(default_factory=list)` here, `{}` -- or any
    # reply using the wrong top-level key -- validated CLEAN, so a whole
    # batch was silently dropped while the caller still reported success.
    # That is exactly the "chapter of nulls" this module exists to prevent.
    items: list[ConceptTag]


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


def _load_chapter_items(chapter_id: int, *, only_untagged: bool = False) -> list[dict[str, Any]]:
    """Every question on a chapter, whether or not it came from an extraction.

    `_load_items` joins `lms_question_extraction`, so it can only see questions
    this pipeline wrote. Most of the bank did not come from here -- the Class 10
    Science chapters hold ~3,000 generated questions with no sidecar at all --
    and those are precisely the ones with no concept, no Bloom and no DOK. The
    join is LEFT so a sidecar is used when present and simply absent otherwise.

    `item_ordinal` is the question id in this mode. It only has to be a stable,
    unique ref for matching the model's echo back to the row.
    """
    db = _session()
    try:
        extra = ""
        if only_untagged:
            # Re-running a whole chapter is wasteful once it is tagged, and it
            # would also overwrite a human correction.
            extra = " AND (q.concept_id IS NULL OR q.g_bloom IS NULL OR q.g_dok IS NULL)"
        rows = db.execute(
            text(
                f"""
                SELECT e.id AS sidecar_id, q.id AS question_id, q.id AS item_ordinal,
                       e.item_number, e.exam_section, e.item_form,
                       q.question_title, q.answer
                  FROM lms_question_master q
                  LEFT JOIN lms_question_extraction e ON e.question_id = q.id
                 WHERE q.chapter_id = :c AND q.deleted_at IS NULL{extra}
                 ORDER BY q.id
                """
            ),
            {"c": chapter_id},
        ).mappings().fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def _tokens(value: str) -> set[str]:
    words = re.findall(r"[a-z]{3,}", (value or "").lower())
    return {w for w in words if w not in _STOPWORDS}


# Bloom's taxonomy is defined by the task verb, so the verb is the signal --
# not the question's format. Ordered most-specific first: a stem containing
# "justify" is Evaluate even though it also contains "explain".
_BLOOM_VERBS: list[tuple[str, re.Pattern[str]]] = [
    ("create", re.compile(
        r"\b(design|devise|propose|formulate|create|invent|develop a|construct a plan"
        r"|suggest (?:a|an|two|some) (?:way|method|design|improvement))", re.I)),
    ("evaluate", re.compile(
        r"\b(evaluate|justify|assess|critic|comment on|do you agree|which is better"
        r"|defend|is it (?:correct|valid)|give reasons? (?:for|why)|support your answer)", re.I)),
    ("analyze", re.compile(
        r"\b(analys|analyz|compare|contrast|differ|distinguish|derive|prove"
        r"|show that|deduce|examine|relate|why does|what would happen|interpret the"
        r"|assertion)", re.I)),
    ("apply", re.compile(
        r"\b(calculat|comput|solve|find the|determine|balance the|apply|use the"
        r"|draw|plot|construct|complete the|how much|how many|convert)", re.I)),
    ("understand", re.compile(
        r"\b(explain|describ|discuss|illustrat|summaris|summariz|classif|why is"
        r"|what happens|give (?:an )?example|distinguish between|in your own words)", re.I)),
    ("recall", re.compile(
        r"\b(define|list|state|name|what is|what are|who|when|where|identify|label"
        r"|write the (?:formula|name|symbol|full form)|recall|mention)", re.I)),
]

# Where a verb gives no signal, the question's format still says something.
_BLOOM_BY_FORM = {
    "mcq": "understand",
    "true_false": "recall",
    "fill_blank": "recall",
    "match_following": "understand",
    "assertion_reason": "analyze",
    "very_short": "recall",
    "numerical": "apply",
    "short": "apply",
    "construction": "apply",
    "long": "analyze",
    "proof": "analyze",
    "case_study": "analyze",
    "case_study_parent": "analyze",
    "case_study_child": "apply",
}

# DOK follows from the cognitive demand, then is nudged by how many marks the
# question is worth: a 5-mark "explain" asks for more chained reasoning than a
# 1-mark one.
_DOK_BY_BLOOM = {"recall": 1, "understand": 2, "apply": 2,
                 "analyze": 3, "evaluate": 3, "create": 4}


def _classify_bloom(stem: str, form: str | None) -> tuple[str, int]:
    """(bloom_level, dok_level) for one question stem."""
    text_ = stem or ""
    for level, pattern in _BLOOM_VERBS:
        if pattern.search(text_):
            return level, _DOK_BY_BLOOM[level]
    level = _BLOOM_BY_FORM.get((form or "").strip().lower(), "understand")
    return level, _DOK_BY_BLOOM[level]


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

        # The verb decides Bloom. Deriving it from item_form alone gave every
        # sidecar-less question the same level -- 255 of 255 came out
        # "understand" -- which looks tagged and carries no signal at all.
        bloom, dok = _classify_bloom(stem, item.get("item_form"))

        # A long answer asks for more chained reasoning than a one-marker of
        # the same verb, so marks nudge DOK without overriding the verb.
        marks = item.get("marks")
        if isinstance(marks, int):
            if marks >= 5 and dok < 3:
                dok += 1
            elif marks <= 1 and dok > 2:
                dok -= 1

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
    extraction_id: int,
    items: list[dict[str, Any]],
    tags: list[ConceptTag],
    model: str,
    concept_names: dict[int, str] | None = None,
) -> dict[str, int]:
    by_ref = {t.ref: t for t in tags}
    names = concept_names or {}
    counters = {"tagged": 0, "with_concept": 0, "unmatched": 0}
    db = _session()
    try:
        for item in items:
            tag = by_ref.get(str(item["item_ordinal"]))
            if tag is None:
                counters["unmatched"] += 1
                continue
            # A question that did not come from an extraction has no sidecar
            # row to update; the mirror onto lms_question_master below is the
            # only write it needs.
            if item.get("sidecar_id"):
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
                           concept      = COALESCE(:concept_name, concept),
                           g_bloom      = :g_bloom,
                           g_dok        = :g_dok,
                           g_difficulty = :g_difficulty
                     WHERE id = :q
                    """
                ),
                {
                    "concept_id": tag.concept_id,
                    # The name as well as the id. The bank UI resolves a
                    # concept_id against the chapter's concept list fetched from
                    # a separate endpoint; when that endpoint is unavailable
                    # every question falls back to "General". Storing the name
                    # on the question makes the label survive on its own.
                    "concept_name": names.get(tag.concept_id) if tag.concept_id else None,
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


async def tag_chapter(
    chapter_id: int,
    *,
    provider: str = "auto",
    only_untagged: bool = True,
) -> dict[str, Any]:
    """Tag every question on a chapter, extraction-sourced or not.

    `tag_extraction` can only reach questions this pipeline wrote, because it
    joins the extraction sidecar. Most of the bank did not come from here, and
    those questions are the ones sitting with no concept, no Bloom and no DOK --
    which is why the bank shows them all under "General".

    `only_untagged` defaults to True so a re-run is cheap and, more importantly,
    does not overwrite a tag a teacher has corrected.
    """
    concepts = _load_concepts(chapter_id)
    items = _load_chapter_items(chapter_id, only_untagged=only_untagged)

    report: dict[str, Any] = {
        "status": "success",
        "chapter_id": chapter_id,
        "provider": "none",
        "model": None,
        "concepts_available": len(concepts),
        "candidates": len(items),
        "tagged": 0,
        "with_concept": 0,
        "unmatched": 0,
        "notes": [],
    }
    if not items:
        report["notes"].append("Nothing left to tag on this chapter.")
        return report
    if not concepts:
        # Bloom and DOK do not depend on the concept list, so this is a
        # degraded run rather than a failure -- but say so, because a chapter
        # with no concepts can never leave "General".
        report["notes"].append(
            "Chapter has no lms_concept rows; concept_id will stay null."
        )

    used = OFFLINE_MODEL
    tags: list[ConceptTag] = []
    if provider in {"auto", "deepseek"} and concepts:
        try:
            tags = await _deepseek_tags(items, concepts)
            used = settings.deepseek_model
            report["provider"] = "deepseek"
        except DeepSeekUnavailableError as exc:
            if provider == "deepseek":
                raise
            report["notes"].append(f"DeepSeek unavailable ({exc}); used the offline matcher.")
            logger.warning("DeepSeek unavailable, tagging chapter offline: %s", exc)
            tags = []
        except Exception as exc:  # noqa: BLE001 - reported, not hidden
            if provider == "deepseek":
                raise
            report["notes"].append(
                f"DeepSeek tagging failed ({type(exc).__name__}); used the offline matcher."
            )
            logger.warning("DeepSeek chapter tagging failed, falling back: %s", exc)
            tags = []

    if not tags:
        tags = _offline_tags(items, concepts)
        used = OFFLINE_MODEL
        report["provider"] = OFFLINE_MODEL

    tags = _sanitise(tags, {c["id"] for c in concepts})
    names = {c["id"]: c["name"] for c in concepts if c.get("id")}
    counters = _persist(None, items, tags, used, concept_names=names)

    report.update(counters)
    report["model"] = used
    report["bloom_spread"] = dict(
        Counter(t.bloom_level for t in tags if t.bloom_level)
    )
    return report


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
