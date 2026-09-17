"""Chapter Queue: the whole hierarchy, from one button.

Pressing Process on a chapter now produces everything below it:

    chapter_master (+ its unit)  ->  topic_master  ->  lms_concept  ->  CG/C map

It used to produce only the chapter row and a JSON blob of "key concepts", while
two further queues produced the topics and the concepts separately. That split
is what made the counts incoherent: this prompt asked for "between 5 and 20 key
concepts" and wrote them to chapter_master.key_concepts, while the Concept Queue
independently derived its own list from the chapter's length and wrote a
different set of names to lms_concept, never having read the first. The same
chapter would report 17 concepts here and 37 there, and neither number came from
the curriculum.

So the responsibilities moved rather than merged. This module now owns exactly
one LLM call -- which unit of the syllabus this chapter belongs to -- and
chapter_pipeline orchestrates the rest. key_concepts is still written, because
Semantic Intelligence falls back to it, but it is now derived from the concepts
that were actually stored, so the two can no longer disagree.
"""

import json
import logging
from typing import Any, Dict

from sqlalchemy import bindparam, text

from app.db.mariadb import SessionLocal
from app.semantic_intelligence.deepseek_client import async_call_deepseek
from app.services.chapter_period_service import sync_chapter_periods_for_unit

logger = logging.getLogger(__name__)


def _sync_periods_for_unit(unit_id, db):
    """Re-split the unit's periods now that this chapter belongs to it.

    A new chapter changes how many ways its unit's allocation is divided, so
    the unit's siblings are recomputed too. Never fails chapter processing.
    """
    if not unit_id:
        return None
    try:
        return sync_chapter_periods_for_unit(unit_id, db=db)
    except Exception as exc:
        logger.warning("Chapter period sync failed for unit %s: %s", unit_id, exc)
        return {"status": "failed", "error": str(exc)}


UNIT_PROMPT = """You are an expert curriculum analyst placing a textbook chapter into the syllabus it is taught from. You work across every school board (CBSE/NCERT, Cambridge, ICSE, IB and state boards), standards 1 to 12, and every subject.

You are given a chapter and the units of its curriculum. Decide which ONE unit this chapter belongs to. Return ONLY a valid JSON object. No explanation, no markdown, no preamble, no trailing text.

Rules you must follow:

1. Compare the `Chapter Name` and `Chapter Content` against each unit's name and its `chapters_in_this_unit` list. The chapter list is the strongest evidence: a chapter named in a unit's list belongs to that unit, even where the wording differs slightly ("Cell: The Building Block of Life" and "The Cell" are the same chapter).

2. Where no chapter list matches, judge by subject matter against the unit name and theme.

3. Return the integer `unit_id` of the best match in `mapped_unit_id`. If `Available Units` is empty, or the chapter genuinely belongs to none of them, return null. A wrong unit is worse than none: it mis-files the chapter's period allocation and its learning outcomes.

4. `chapter_summary` is 1 to 2 sentences saying what this chapter teaches, in the ORIGINAL script/language of the chapter content (e.g. Sanskrit, Hindi, Gujarati, Marathi). DO NOT translate into English. Only the JSON keys are in English.

5. `confidence` is your own certainty in the unit match, 0.0 to 1.0. Return a low number when you are guessing; it is recorded, and a guess that admits itself is more useful than one that does not.

6. Output ONLY the JSON object. No other text.

Return the JSON in the following format:
{
  "mapped_unit_id": 123,
  "chapter_summary": "What this chapter teaches.",
  "confidence": 0.9
}

Chapter Name: {chapter_name}

Available Units:
{available_units}

Chapter Content:
{md_content}
"""

SYSTEM_PROMPT = "You are a helpful assistant. Return ONLY a JSON object."


def chapter_row(db, extraction_id: int) -> Dict[str, Any] | None:
    """The chapter_master row for an extraction, chosen deterministically.

    Ten extractions on this database have TWO chapter_master rows, and every
    service reads them with a bare fetchone(). Two runs could therefore pick
    different parents for the same extraction, which is how 16 chapters ended up
    holding every concept twice -- once under each row. Lowest id always wins, so
    every stage agrees on the same parent, and the duplicate is reported rather
    than silently chosen between.
    """
    rows = db.execute(
        text("""SELECT id, chapter_name, sub_institute_id, syear, standard_id,
                       subject_id, unit_id, no_of_periods
                  FROM chapter_master WHERE extraction_id = :id
              ORDER BY id ASC"""),
        {"id": extraction_id},
    ).mappings().fetchall()

    if not rows:
        return None
    if len(rows) > 1:
        logger.warning(
            "Extraction %s has %s chapter_master rows (%s); using the lowest id. "
            "The duplicates should be merged: topics and concepts written under "
            "different parents are what caused the doubled concept rows.",
            extraction_id, len(rows), ", ".join(str(r["id"]) for r in rows),
        )
    return dict(rows[0])


def available_units(db, standard_id: Any, subject_id: Any) -> tuple[list[dict], list]:
    """The units this chapter could belong to, and the raw rows behind them."""
    if not (standard_id and subject_id):
        return [], []

    curriculums = db.execute(
        text("""
            SELECT c.id
              FROM lms_curriculum c
              LEFT JOIN subject cs ON c.subject_id = cs.id
              LEFT JOIN subject ds ON ds.id = :sub_id
             WHERE c.standard_id = :std_id
               AND (
                    c.subject_id = :sub_id
                 OR LOWER(ds.subject_name) LIKE CONCAT(LOWER(cs.subject_name), '%')
                 OR LOWER(cs.subject_name) LIKE CONCAT(LOWER(ds.subject_name), '%')
               )
        """),
        {"std_id": standard_id, "sub_id": subject_id},
    ).fetchall()

    if not curriculums:
        return [], []

    units = db.execute(
        text("SELECT id, name, unit_chapters FROM lms_units WHERE curriculum_id IN :ids")
        .bindparams(bindparam("ids", expanding=True)),
        {"ids": [c[0] for c in curriculums]},
    ).mappings().fetchall()

    listed = []
    for unit in units:
        try:
            raw = unit["unit_chapters"]
            listed.append({
                "unit_id": unit["id"],
                "unit_name": unit["name"],
                "chapters_in_this_unit": json.loads(raw) if raw else [],
            })
        except Exception as exc:
            logger.warning("Failed to parse unit_chapters for unit_id %s: %s", unit["id"], exc)
    return listed, list(units)


def fallback_unit(chapter_name: str, units: list) -> Any:
    """Substring match of the chapter name against each unit's chapter list.

    Kept as the fallback for a model that returned null or an id that is not on
    the list -- it costs nothing and it resolves the common case where the two
    names differ only by an article.
    """
    for unit in units:
        try:
            raw = unit["unit_chapters"]
            if not raw:
                continue
            for listed in json.loads(raw):
                a, b = chapter_name.lower(), str(listed).lower()
                if a and b and (a in b or b in a):
                    return unit["id"]
        except Exception:
            continue
    return None


async def map_unit(
    *, chapter_name: str, md_content: str, units_for_prompt: list[dict]
) -> Dict[str, Any]:
    """Which unit of the syllabus this chapter belongs to. One LLM call.

    No database session is held across this call. The previous version kept one
    open for the whole of process_chapter_by_id, including the blocking LLM
    request, which is why the other services grew connection-retry wrappers that
    this one never had.
    """
    prompt = (
        UNIT_PROMPT
        .replace("{chapter_name}", chapter_name or "")
        .replace("{available_units}", json.dumps(units_for_prompt, indent=2, ensure_ascii=False)
                 if units_for_prompt else "[]")
        .replace("{md_content}", md_content or "")
    )
    result = await async_call_deepseek(
        prompt, system_prompt=SYSTEM_PROMPT, response_format={"type": "json_object"}
    )
    data = result.get("data") or {}
    if not isinstance(data, dict):
        data = {}

    valid = {u["unit_id"] for u in units_for_prompt}
    unit_id = data.get("mapped_unit_id")
    try:
        unit_id = int(unit_id) if unit_id is not None else None
    except (TypeError, ValueError):
        unit_id = None
    if unit_id is not None and valid and unit_id not in valid:
        # A unit id that is not on the list mis-files the chapter's periods and
        # its learning outcomes, so it is dropped rather than written through.
        logger.warning("Model returned unit_id %s, which is not in this subject's units", unit_id)
        unit_id = None

    return {
        "unit_id": unit_id,
        "chapter_summary": str(data.get("chapter_summary") or "").strip(),
        "confidence": data.get("confidence"),
        "input_tokens": result.get("input_tokens", 0),
        "output_tokens": result.get("output_tokens", 0),
    }


_INSERT_CHAPTER = text("""
    INSERT INTO chapter_master
        (extraction_id, sub_institute_id, subject_id, standard_id, grade_id,
         unit_id, chapter_name, syear, created_at, updated_at)
    VALUES
        (:ext_id, :sub_inst, :sub_id, :std_id, :grade_id,
         :unit_id, :cname, :syear, NOW(), NOW())
""")


def upsert_chapter(db, *, extraction_id: int, row: Dict[str, Any], unit_id: Any = None) -> int:
    """Create or find this extraction's chapter_master row. No LLM involved.

    Called before any generation stage, for two reasons: lms_learning_outcomes
    points at chapter_master.id, so the curriculum frame cannot be loaded until
    the row exists; and a job that dies halfway then leaves a usable chapter
    rather than nothing at all.
    """
    existing = chapter_row(db, extraction_id)
    chapter_name = row.get("document_tittle") or ""

    if not existing:
        # Match an ERP-created chapter before inserting a duplicate of it.
        found = db.execute(
            text("""SELECT id FROM chapter_master
                     WHERE LOWER(TRIM(chapter_name)) = LOWER(TRIM(:cname))
                       AND standard_id = :std_id
                       AND subject_id = :sub_id
                       AND sub_institute_id = :sub_inst
                  ORDER BY id ASC LIMIT 1"""),
            {
                "cname": chapter_name,
                "std_id": row.get("standard_id"),
                "sub_id": row.get("subject_id"),
                "sub_inst": row.get("sub_institute_id"),
            },
        ).fetchone()
        if found:
            existing = {"id": found[0]}

    grade_id = None
    if row.get("standard_id"):
        grade = db.execute(
            text("SELECT grade_id FROM standard WHERE id = :st_id"),
            {"st_id": row.get("standard_id")},
        ).fetchone()
        if grade:
            grade_id = grade[0]

    params = {
        "ext_id": extraction_id,
        "sub_inst": row.get("sub_institute_id"),
        "sub_id": row.get("subject_id"),
        "std_id": row.get("standard_id"),
        "grade_id": grade_id,
        "unit_id": unit_id,
        "cname": chapter_name,
        "syear": row.get("syear"),
    }

    if existing:
        # unit_id is only overwritten when this run actually resolved one, so a
        # re-run that could not reach the LLM does not erase a good mapping.
        db.execute(
            text("""
                UPDATE chapter_master
                   SET extraction_id = :ext_id,
                       sub_institute_id = :sub_inst,
                       subject_id = :sub_id,
                       standard_id = :std_id,
                       grade_id = :grade_id,
                       unit_id = COALESCE(:unit_id, unit_id),
                       chapter_name = :cname,
                       syear = :syear,
                       updated_at = NOW()
                 WHERE id = :cm_id
            """),
            {**params, "cm_id": existing["id"]},
        )
        db.commit()
        return existing["id"]

    chapter_id = db.execute(_INSERT_CHAPTER, params).lastrowid
    db.commit()
    return chapter_id


def write_key_concepts(db, chapter_id: int, concepts: list[dict]) -> int:
    """Mirror the stored concepts onto chapter_master.key_concepts.

    Derived, never generated. semantic_intelligence/pipeline.py falls back to
    this JSON when a chapter has no topics, and validation_service check 8
    exists precisely to catch it drifting away from the real hierarchy -- which
    it always did, because it used to come from its own separate LLM call with
    its own separate idea of what the chapter's concepts were.
    """
    payload = json.dumps(
        [{"name": c.get("name"), "description": c.get("description")} for c in concepts],
        ensure_ascii=False,
    )
    db.execute(
        text("UPDATE chapter_master SET key_concepts = :kc, updated_at = NOW() WHERE id = :id"),
        {"kc": payload, "id": chapter_id},
    )
    db.commit()
    return len(concepts)


async def process_chapter_by_id(
    extraction_id: int, force: bool = False, progress=None
) -> Dict[str, Any]:
    """Run the whole chapter pipeline. Kept here so existing callers still work."""
    from app.services import chapter_pipeline

    return await chapter_pipeline.run(extraction_id, force=force, progress=progress)


def get_chapter_data_by_extraction_id(extraction_id: int):
    with SessionLocal() as db:
        chp = db.execute(
            text("SELECT * FROM chapter_master WHERE extraction_id = :id ORDER BY id ASC LIMIT 1"),
            {"id": extraction_id},
        ).mappings().fetchone()

        if not chp:
            return None

        unit_name = None
        if chp.get("unit_id"):
            unit = db.execute(
                text("SELECT name FROM lms_units WHERE id = :uid"), {"uid": chp["unit_id"]}
            ).mappings().fetchone()
            if unit:
                unit_name = unit["name"]

        concepts = []
        try:
            if chp.get("key_concepts"):
                concepts = json.loads(chp["key_concepts"])
        except Exception:
            pass

        budget = None
        try:
            if chp.get("concept_budget"):
                budget = json.loads(chp["concept_budget"])
        except Exception:
            pass

        return {
            "chapter_master_id": chp["id"],
            "unit_id": chp["unit_id"],
            "unit_name": unit_name,
            "chapter_name": chp["chapter_name"],
            "no_of_periods": chp.get("no_of_periods"),
            "syear": chp["syear"],
            "key_concepts": concepts,
            "concept_budget": budget,
            "extraction_confidence": (
                float(chp["extraction_confidence"])
                if chp.get("extraction_confidence") is not None else None
            ),
        }


def get_all_chapters() -> list[dict[str, Any]]:
    """The Chapter Queue listing.

    Carries the topic and concept counts now, because this queue produces them:
    a row that says "processed" but shows no concepts is a run that failed
    halfway, and that has to be visible without opening the row.
    """
    with SessionLocal() as db:
        from app.services import extraction_schema

        scored = extraction_schema.supports(db, "lms_concept", "confidence")
        confidence_expr = (
            "(SELECT ROUND(AVG(c.confidence), 3) FROM lms_concept c "
            " WHERE c.extraction_id = d.id AND c.confidence IS NOT NULL)"
            if scored else "NULL"
        )
        query = text(f"""
            SELECT d.id, d.document_tittle, d.subject_name, d.standard, d.syear,
                   d.chapter_number, d.created_at,
                   EXISTS(SELECT 1 FROM chapter_master c WHERE c.extraction_id = d.id) AS is_processed,
                   (SELECT COUNT(*) FROM topic_master t
                     WHERE t.extraction_id = d.id AND COALESCE(t.topic_show_hide, 1) = 1) AS topic_count,
                   (SELECT COUNT(*) FROM lms_concept c WHERE c.extraction_id = d.id) AS concept_count,
                   {confidence_expr} AS mean_confidence
              FROM document_extractions d
             WHERE LOWER(d.document_type) = 'chapter'
          ORDER BY d.id DESC
        """)
        rows = [dict(row) for row in db.execute(query).mappings().fetchall()]

    for row in rows:
        if row.get("mean_confidence") is not None:
            row["mean_confidence"] = float(row["mean_confidence"])
    return rows
