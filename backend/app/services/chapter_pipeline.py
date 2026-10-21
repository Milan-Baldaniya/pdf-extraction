"""One job, one button: chapter -> unit -> topics -> concepts -> curriculum.

The extraction hierarchy used to be produced by three separate user clicks, and
nothing joined them up. The Chapter Queue asked one model for "5 to 20 key
concepts" and stored them as JSON; the Topic Queue divided the chapter into
topics from the book alone; the Concept Queue then derived its own concept list
from the chapter's CHARACTER COUNT, never reading either. Two of those three
stages invented concepts, at different grain, and the syllabus sat unread in
lms_learning_outcomes throughout.

This module runs the whole thing once, in order, with the curriculum in scope
from the start:

    0  schema      the columns this job writes exist (before any token is spent)
    1  chapter     read the extraction, create/find chapter_master
    2  curriculum  the chapter's goals, competencies and outcomes
    3  unit+topics one call each, concurrently -- they do not depend on each other
    4  topics      persisted, so a later failure does not lose them
    5  budget      how many concepts this chapter may have, from the syllabus
    6  concepts    one call, with the curriculum and a per-topic allowance
    7  enforce     ranked trim back to the allowance, and repair of empty topics
    8  persist     upsert, score, map to CG/C codes, mirror to key_concepts

Two rules govern the whole file:

  * No database session is held across an await. Every LLM call takes minutes,
    and a pooled connection held that long comes back dead -- which is why the
    older services grew retry wrappers. Read into plain dicts, close, call,
    reopen to write.

  * Every stage persists before the next begins. A chapter that dies at the
    concept call keeps its topics, and re-running with force=False resumes
    rather than starting over.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List

from sqlalchemy import text

from app.db.mariadb import SessionLocal
from app.semantic_intelligence.deepseek_client import DeepSeekUnavailableError
from app.services import chapter_service, chapter_text as ct, concept_service
from app.services import concept_budget, confidence as cs, curriculum_frame as curf
from app.services import extraction_schema, topic_service, validation_service

logger = logging.getLogger(__name__)

Progress = Callable[[str], Any] | None


def _say(progress: Progress, message: str) -> None:
    """Report a step. The frontend prints this straight onto the button."""
    logger.info("chapter pipeline: %s", message)
    if progress:
        try:
            progress(message)
        except Exception:
            # Progress reporting must never be able to fail a run.
            logger.debug("progress callback failed", exc_info=True)


async def run(
    extraction_id: int, *, force: bool = False, progress: Progress = None
) -> Dict[str, Any]:
    """Produce a chapter's unit, topics and concepts in one pass."""

    # --- 0. schema -------------------------------------------------------
    # Before any token is spent. An INSERT naming a column the database does
    # not have fails after the whole fan-out has been paid for.
    _say(progress, "Checking schema")
    with SessionLocal() as db:
        extraction_schema.ensure_extraction_schema(db)

    # --- 1. the chapter --------------------------------------------------
    _say(progress, "Reading chapter")
    with SessionLocal() as db:
        row = db.execute(
            text("SELECT * FROM document_extractions WHERE id = :id"),
            {"id": extraction_id},
        ).mappings().fetchone()
        if not row:
            raise ValueError(f"No document_extraction found for id {extraction_id}")
        row = dict(row)

        if str(row.get("document_type", "")).lower() != "chapter":
            raise ValueError(f"document_extraction {extraction_id} is not of type 'Chapter'")

        md_content = row.get("md_content") or ""
        if not md_content:
            raise ValueError(f"document_extraction {extraction_id} has no md_content")

        existing = chapter_service.chapter_row(db, extraction_id)
        if existing and not force:
            done = _already_done(db, extraction_id)
            if done:
                return {
                    "status": "already_processed",
                    "action": "skipped",
                    "chapter_master_id": existing["id"],
                    "message": (
                        "Chapter already processed. Skipped to save LLM tokens. "
                        "Use Reprocess to rebuild it."
                    ),
                    **done,
                }

        chapter_id = chapter_service.upsert_chapter(db, extraction_id=extraction_id, row=row)
        chapter = chapter_service.chapter_row(db, extraction_id) or {}
        units_for_prompt, unit_rows = chapter_service.available_units(
            db, row.get("standard_id"), row.get("subject_id")
        )

    chapter_name = chapter.get("chapter_name") or row.get("document_tittle") or ""
    sub_institute_id = chapter.get("sub_institute_id") or row.get("sub_institute_id") or 341
    syear = chapter.get("syear") or row.get("syear")
    standard_id = chapter.get("standard_id") or row.get("standard_id")
    subject_id = chapter.get("subject_id") or row.get("subject_id")
    subject_name = row.get("subject_name")
    standard = row.get("standard")
    board = row.get("board")

    # --- 2. the curriculum ----------------------------------------------
    _say(progress, "Reading curriculum")
    with SessionLocal() as db:
        frame = curf.load_frame(
            db, chapter_id=chapter_id, standard_id=standard_id, subject_id=subject_id
        )
    if frame.is_usable:
        logger.info(
            "Chapter %s is governed by curriculum %s: %s competencies, %s outcomes",
            chapter_id, frame.curriculum_id, frame.competency_count, frame.lo_count,
        )

    # --- 3. unit and topics, concurrently --------------------------------
    # Independent questions about the same chapter, so there is nothing to gain
    # from asking them in sequence.
    _say(progress, "Mapping unit and finding topics")
    curriculum_block = frame.prompt_block()
    unit_task = chapter_service.map_unit(
        chapter_name=chapter_name, md_content=md_content, units_for_prompt=units_for_prompt
    )
    topic_task = topic_service.generate_topics(
        md_content=md_content,
        chapter_name=chapter_name,
        subject_name=subject_name,
        standard=standard,
        board=board,
        curriculum_block=curriculum_block,
        extraction_id=extraction_id,
    )
    unit_result, topic_result = await asyncio.gather(unit_task, topic_task)

    unit_id = unit_result["unit_id"] or chapter_service.fallback_unit(chapter_name, unit_rows)
    topics = topic_result["topics"]

    # --- 4. persist the topics ------------------------------------------
    _say(progress, f"Saving {len(topics)} topics")
    with SessionLocal() as db:
        chapter_service.upsert_chapter(
            db, extraction_id=extraction_id, row=row, unit_id=unit_id
        )
        chapter_service._sync_periods_for_unit(unit_id, db)

    topic_counts = await asyncio.to_thread(
        topic_service.persist_topics,
        extraction_id=extraction_id,
        chapter_id=chapter_id,
        sub_institute_id=sub_institute_id,
        syear=syear,
        topics=topics,
    )

    with SessionLocal() as db:
        live_topics = [dict(t) for t in db.execute(
            text("""SELECT id, name, description, estimated_minutes
                      FROM topic_master
                     WHERE extraction_id = :id AND COALESCE(topic_show_hide, 1) = 1
                  ORDER BY topic_sort_order ASC, id ASC"""),
            {"id": extraction_id},
        ).mappings().fetchall()]
        periods = (chapter_service.chapter_row(db, extraction_id) or {}).get("no_of_periods")

    if not live_topics:
        raise RuntimeError(
            f"Topics for extraction {extraction_id} were generated but none came back "
            f"from topic_master; the write may have been rolled back."
        )

    # --- 5. the budget ----------------------------------------------------
    # Decided BEFORE the concept call, from the syllabus and the timetable --
    # never from the chapter's length, which is what produced 37 concepts for a
    # six-topic chapter and told the model to expect up to 110.
    spans = ct.partition_by_topics(md_content, [t["name"] for t in live_topics])
    budget = concept_budget.chapter_budget(
        topic_count=len(live_topics),
        spans=spans,
        lo_count=frame.lo_count,
        competency_count=frame.competency_count,
        periods=periods or frame.planned_periods,
        chapter_chars=len(md_content),
    )
    logger.info(
        "Chapter %s concept budget: target %s (%s-%s) from %s; quota %s",
        chapter_id, budget.target, budget.low, budget.high, budget.source, budget.quota,
    )
    for warning in budget.warnings:
        logger.warning("Chapter %s budget: %s", chapter_id, warning)

    # --- 6. the concepts --------------------------------------------------
    _say(progress, f"Extracting concepts (target {budget.target})")
    extracted = await concept_service.generate_concepts(
        extraction_id=extraction_id,
        md_content=md_content,
        all_topics=live_topics,
        budget=budget,
        frame=frame,
        chapter_name=chapter_name,
        subject_name=subject_name,
        standard=standard,
        board=board,
    )
    results = extracted["results"]

    if extracted["trimmed"]:
        _say(
            progress,
            f"Trimmed {len(extracted['trimmed'])} concepts to the budget of {budget.target}",
        )

    # --- 7. repair the topics that came back empty ------------------------
    repaired = await _repair_empty_topics(
        extracted, results,
        extraction_id=extraction_id, md_content=md_content, all_topics=live_topics,
        budget=budget, frame=frame, chapter_name=chapter_name,
        subject_name=subject_name, standard=standard, board=board, progress=progress,
    )

    # --- 8. persist, score, map -------------------------------------------
    _say(progress, "Scoring and saving")
    counts = await asyncio.to_thread(
        concept_service.persist_concepts,
        extraction_id=extraction_id,
        chapter_id=chapter_id,
        standard_id=standard_id,
        subject_id=subject_id,
        sub_institute_id=sub_institute_id,
        syear=syear,
        results=results,
        topic_id=None,
    )

    every_concept = [c for r in results for c in r["concepts"]]
    mappings_written = 0
    with SessionLocal() as db:
        if frame.is_usable:
            mappings_written = curf.persist_mappings(
                db,
                frame=frame,
                extraction_id=extraction_id,
                mappings_by_concept_id={
                    c["concept_id"]: c.get("curriculum_mappings") or []
                    for c in every_concept if c.get("concept_id")
                },
            )
        chapter_service.write_key_concepts(db, chapter_id, every_concept)

    # The audit reads the rows back out of the database and measures them
    # against the chapter, so it can only run once they are written -- which
    # means every concept was necessarily scored before its issues were known.
    # Those penalties are a named term of the confidence formula, so the
    # affected rows are re-scored and updated here rather than shipping a number
    # that quietly omits them.
    audit = _audit(extraction_id)
    penalised = _apply_audit_penalties(extraction_id, every_concept, audit)
    if penalised:
        _say(progress, f"Adjusted {penalised} concept score(s) for audit findings")

    chapter_confidence = cs.chapter_confidence(
        [cs.Score(c.get("confidence") or 0.0, c.get("confidence_profile") or "content",
                  c.get("review_status") or cs.STATUS_ACCEPTED)
         for c in every_concept],
        audit_passed=(audit or {}).get("verdict") != "fail",
    )

    with SessionLocal() as db:
        _write_chapter_rollup(db, chapter_id, chapter_confidence, budget)

    grounded = extracted["grounded_concepts"]
    total = len(every_concept)
    return {
        "status": "success",
        "action": "processed",
        "extraction_id": extraction_id,
        "chapter_master_id": chapter_id,
        "unit_id_mapped": unit_id,
        "unit_confidence": unit_result.get("confidence"),
        "chapter_summary": unit_result.get("chapter_summary"),
        # topics
        "topics_extracted": len(topics),
        "outline_authoritative": topic_result["outline_authoritative"],
        "topic_duplicates_dropped": topic_result["duplicates_dropped"],
        "thin_topics": topic_result["thin_topics"],
        **{f"topics_{k}": v for k, v in topic_counts.items()},
        # concepts
        "concepts_extracted": total,
        "concept_budget": budget.as_dict(),
        "duplicates_dropped": extracted["duplicates_dropped"],
        "trimmed": extracted["trimmed"],
        "repaired_topics": repaired,
        "failed_topics": extracted["failed_topics"],
        "topics_failed": len(extracted["failed_topics"]),
        "grounded_concepts": grounded,
        "ungrounded_concepts": total - grounded,
        "curriculum": frame.as_dict(),
        "curriculum_mappings": mappings_written,
        "extraction_confidence": chapter_confidence,
        "flagged_concepts": sum(
            1 for c in every_concept
            if c.get("review_status") in (cs.STATUS_FLAGGED, cs.STATUS_LOW)
        ),
        "audit": _audit_summary(audit),
        "input_tokens": (
            unit_result["input_tokens"] + topic_result["input_tokens"] + extracted["input_tokens"]
        ),
        "output_tokens": (
            unit_result["output_tokens"] + topic_result["output_tokens"] + extracted["output_tokens"]
        ),
        **counts,
        "chapter_data": chapter_service.get_chapter_data_by_extraction_id(extraction_id),
        **(concept_service.get_concept_data_by_extraction_id(extraction_id) or {}),
    }


# ---------------------------------------------------------------------------
# Stages that are easier to read on their own
# ---------------------------------------------------------------------------

def _already_done(db, extraction_id: int) -> Dict[str, Any] | None:
    """Whether a previous run left a complete hierarchy behind.

    Complete means topics AND concepts. A chapter with topics but no concepts is
    a run that died at the concept call, and re-running it is the point.
    """
    topics = db.execute(
        text("""SELECT COUNT(*) FROM topic_master
                 WHERE extraction_id = :id AND COALESCE(topic_show_hide, 1) = 1"""),
        {"id": extraction_id},
    ).scalar()
    concepts = db.execute(
        text("SELECT COUNT(*) FROM lms_concept WHERE extraction_id = :id"),
        {"id": extraction_id},
    ).scalar()
    if not (topics and concepts):
        return None
    return {"topics_extracted": topics, "concepts_extracted": concepts}


async def _repair_empty_topics(
    extracted: Dict[str, Any],
    results: List[Dict[str, Any]],
    *,
    extraction_id: int,
    md_content: str,
    all_topics: List[Dict[str, Any]],
    budget: concept_budget.Budget,
    frame: curf.CurriculumFrame,
    chapter_name: str,
    subject_name: Any,
    standard: Any,
    board: Any,
    progress: Progress,
) -> List[Dict[str, Any]]:
    """One narrow second call for topics the first pass returned nothing for.

    A topic with no concepts under it breaks the hierarchy -- Semantic
    Intelligence skips it outright and validation_service reports it as an error
    -- so it is worth one more call, scoped to just those topics but still
    showing the whole chapter, because the point of this design is that the
    model always sees what it is dividing.

    Never raises. A repair that fails leaves the chapter exactly as the first
    pass left it, which is strictly better than losing the pass.
    """
    failed = extracted.get("failed_topics") or []
    if not failed:
        return []

    names = {f["topic_id"] for f in failed}
    targets = [t for t in all_topics if t["id"] in names]
    if not targets:
        return []

    _say(progress, f"Repairing {len(targets)} topic(s) with no concepts")
    try:
        retry = await concept_service.generate_concepts(
            extraction_id=extraction_id,
            md_content=md_content,
            all_topics=all_topics,
            budget=budget,
            frame=frame,
            chapter_name=chapter_name,
            subject_name=subject_name,
            standard=standard,
            board=board,
            targets=targets,
        )
    except DeepSeekUnavailableError:
        raise
    except Exception as exc:
        logger.warning("Concept repair pass failed for %s: %s", extraction_id, exc)
        return []

    order = {t["id"]: i for i, t in enumerate(all_topics)}
    recovered = []
    for entry in retry["results"]:
        if entry["topic_id"] in names and entry["concepts"]:
            results.append(entry)
            recovered.append({"topic_id": entry["topic_id"],
                              "topic_name": entry["topic_name"],
                              "concepts": len(entry["concepts"])})
    results.sort(key=lambda r: order.get(r["topic_id"], 0))

    # The repaired topics are no longer failures.
    extracted["failed_topics"] = [f for f in failed
                                  if f["topic_id"] not in {r["topic_id"] for r in recovered}]
    extracted["concepts_extracted"] = sum(len(r["concepts"]) for r in results)
    extracted["grounded_concepts"] += retry["grounded_concepts"]
    extracted["input_tokens"] += retry["input_tokens"]
    extracted["output_tokens"] += retry["output_tokens"]
    return recovered


_UPDATE_SCORE = text("""
    UPDATE lms_concept
       SET confidence = :confidence,
           confidence_parts = :parts,
           review_status = :review_status,
           updated_at = CURRENT_TIMESTAMP
     WHERE id = :id
""")


def _apply_audit_penalties(
    extraction_id: int,
    concepts: List[Dict[str, Any]],
    audit: Dict[str, Any] | None,
) -> int:
    """Deduct the audit's findings from the concepts they are about.

    Only the rows the audit actually flagged are touched, which on a clean
    chapter is none of them -- so this normally costs one indexing pass and no
    writes at all. The concept dicts are updated in place too, so the chapter
    roll-up and the returned payload agree with what is now in the database.

    Never raises. The scores are already persisted and usable; losing the
    adjustment is a worse report, not a failed run.
    """
    if not audit:
        return 0

    by_concept = cs.issues_by_id(audit, "concept_id")
    if not by_concept:
        return 0

    import json

    updated = 0
    try:
        with SessionLocal() as db:
            if not extraction_schema.supports(db, "lms_concept", "confidence", "review_status"):
                return 0
            for concept in concepts:
                found = by_concept.get(concept.get("concept_id") or -1)
                if not found or not (found["errors"] or found["warnings"]):
                    continue
                score = cs.rescore_with_audit(
                    concept.get("confidence_parts") or {},
                    concept.get("confidence_profile") or "content",
                    found["errors"], found["warnings"],
                )
                concept["confidence"] = score.value
                concept["confidence_parts"] = score.parts
                concept["review_status"] = score.status
                db.execute(_UPDATE_SCORE, {
                    "confidence": score.value,
                    "parts": json.dumps(score.parts, ensure_ascii=False),
                    "review_status": score.status,
                    "id": concept["concept_id"],
                })
                updated += 1
            db.commit()
    except Exception as exc:
        logger.warning("Could not apply audit penalties for %s: %s", extraction_id, exc)
        return 0

    if updated:
        logger.info(
            "Extraction %s: %s concept score(s) adjusted for audit findings",
            extraction_id, updated,
        )
    return updated


def _audit(extraction_id: int) -> Dict[str, Any] | None:
    """The deterministic 8-check audit, run inline.

    It has existed behind GET /api/validate/{id} with no caller since it was
    written. It costs no tokens and it is the only independent opinion in the
    pipeline, so there is no reason not to run it on every chapter.
    """
    try:
        return validation_service.validate_extraction(extraction_id)
    except Exception as exc:
        logger.warning("Audit skipped for extraction %s: %s", extraction_id, exc)
        return None


def _audit_summary(audit: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not audit:
        return None
    return {
        "verdict": audit.get("verdict"),
        "errors": audit.get("totals", {}).get("errors"),
        "warnings": audit.get("totals", {}).get("warnings"),
        "by_check": audit.get("by_check"),
        "scores": audit.get("scores"),
    }


def _write_chapter_rollup(
    db, chapter_id: int, confidence: float, budget: concept_budget.Budget
) -> None:
    import json

    if not extraction_schema.supports(
        db, "chapter_master", "extraction_confidence", "concept_budget"
    ):
        return
    try:
        db.execute(
            text("""UPDATE chapter_master
                       SET extraction_confidence = :conf,
                           concept_budget = :budget,
                           updated_at = NOW()
                     WHERE id = :id"""),
            {
                "conf": confidence,
                "budget": json.dumps(budget.as_dict(), ensure_ascii=False),
                "id": chapter_id,
            },
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        # The rollup is reporting, not content. Losing it must not fail a run
        # that has already written its topics and concepts.
        logger.warning("Could not write chapter rollup for %s: %s", chapter_id, exc)
