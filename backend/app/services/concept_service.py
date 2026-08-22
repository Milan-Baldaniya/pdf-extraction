"""Concept Queue: break each chapter topic into its masterable concepts.

ONE prompt sees the WHOLE chapter and every one of its topics, and returns the
concepts of all of them nested under their topic. Each concept is written into
lms_concept carrying the topic_id of the topic it came from.

This mirrors the Topic Queue, and for the same reason. Concepts used to be
extracted one topic at a time from that topic's slice of the chapter, and a call
holding a sixth of a chapter cannot judge how finely to divide it, cannot see
that a neighbouring topic already covers an idea, and cannot tell whether the
chapter as a whole has been split into forty concepts or a hundred. Rules 4 and
5 of the prompt only mean anything to a model that can see everything at once.

This is the leaf level of the extraction hierarchy:

    Chapter -> Topics -> Concepts

so this module depends on topic_master, which the Topic Queue fills
chapter-wise beforehand. It no longer reads chapter_master.key_concepts: that
JSON is chapter-level summary data used by Semantic Intelligence, not the
parent of a concept.
"""

import asyncio
import logging
import re
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.db.mariadb import SessionLocal
# A provider fault (billing, auth, unknown model) is not caught here. With a
# single call there is nothing to salvage, so it propagates to the route, which
# turns it into a 503 naming the actual cause.
from app.semantic_intelligence.deepseek_client import async_call_deepseek
from app.services import chapter_text as ct

logger = logging.getLogger(__name__)

# Retries for the post-run write, for the same reason as the Topic Queue: the
# call runs for minutes and a stale pooled connection must not throw away it.
_PERSIST_ATTEMPTS = 4
_PERSIST_BACKOFF_SEC = 3

_DEFAULT_TOPIC_MINUTES = 20


CONCEPT_PROMPT = """You are an expert instructional designer and educational content analyst. You work across every school board (CBSE/NCERT, Cambridge, ICSE, IB and state boards), standards 1 to 12, and every subject including Hindi, Gujarati, English, Sanskrit, Mathematics, Science, Social Science, History, Geography, Civics, Biology, Chemistry, Physics and Computer Science.

You are given a COMPLETE chapter and the list of main topics it has already been divided into. Your task is to break EVERY listed topic into the individual CONCEPTS a learner must master to be competent in it, and to assign each concept a scientifically-backed mastery threshold and learning time. This data is used directly for teacher and student training in schools, so precision and pedagogical methodology are critical. Return ONLY a valid JSON object. No explanation, no markdown, no preamble, no trailing text.

Rules you must follow:

1. COVER EVERY TOPIC. Return one entry per topic in `Topics To Process`, in the same order, with `topic_name` copied EXACTLY as given. Never skip a topic, never invent one, never merge two. `Chapter Topics` lists the chapter's full topic list so you can see the boundaries: a topic's material runs from where that topic begins until the next one begins.

2. WHAT A CONCEPT IS. A concept is a single masterable idea a learner either knows or does not: a definition, a law or formula, a relationship, a procedure, a distinction between two things, a grammar rule, a literary device, a cause-effect link. It is NOT a classroom activity, NOT an exercise question, and NOT a restatement of the whole topic.
   Test it: for the topic "Adding and subtracting integers", "Adding integers with different signs" is a concept. "Adding integers" is not — that is just the topic again in fewer words.

3. HOW MANY PER TOPIC. Extract every distinct masterable idea that topic's material actually teaches — normally 3 to 10. Do NOT pad a topic to reach a number, and do NOT merge two distinct ideas into one entry. A topic the chapter covers briefly gets fewer; a topic covering several rules or methods gets more.

4. HOW MANY IN TOTAL. You can see the whole chapter, so judge the total as well as each part. A chapter of this length normally yields between {min_concepts} and {max_concepts} concepts across all its topics. Going far beyond that means you are splitting below the concept level — each entry has stopped being a masterable idea and become a single sentence from the book.

5. NO DUPLICATES ANYWHERE. You can see every topic at once, so this is your responsibility, not a later cleanup. The same idea must appear under exactly ONE topic. If two topics could both claim a concept, give it to the topic that teaches it FIRST and leave it out of the other. Two concepts must never describe the same idea in different words, whether they sit under the same topic or different ones.

6. ADAPT TO THE LEVEL:
   - Std 1-5 (Primary): simple terms, basic ideas, foundational vocabulary
   - Std 6-8 (Middle): definitions, processes, relationships between ideas
   - Std 9-10 (Secondary): principles, laws, theories, formulas, cause-effect
   - Std 11-12 (Higher Secondary): advanced theories, derivations, analytical concepts

7. CRITICAL INSTRUCTION: ALL extracted text (Concept Names AND Descriptions) MUST strictly remain in the ORIGINAL script/language (e.g., Sanskrit, Hindi, Gujarati, Marathi) found in the chapter content. DO NOT translate any text into English. Only the JSON keys must be in English.

8. `name` must be concise (2 to 6 words). `description` must be 1 to 2 sentences max.

9. Assign every concept a `mastery_threshold` (integer percentage) using this strict pedagogical rubric:
   - 90 to 95: Foundational and prerequisite concepts (crucial for future learning; basic formulas, core definitions)
   - 80 to 85: Core/standard concepts (main syllabus content; application of knowledge)
   - 70 to 75: Advanced/enrichment concepts (high-level synthesis, complex analysis, abstract theory where perfection is rare)

10. Assign every concept an `estimated_mastery_minutes` (integer) using Cognitive Load Theory and Bloom's Taxonomy. Within EACH topic, the minutes of that topic's concepts MUST add up to approximately that topic's `Minutes` budget given below. Distribute each budget by cognitive load:
   - Remembering / identifying / defining: the smallest share
   - Understanding / applying / solving basic problems: a medium share
   - Analyzing / evaluating / derivations / multi-step problem solving: the largest share

11. GROUNDING: every concept MUST come from the `Chapter Content` below, and from the part of it that belongs to its own topic. For each concept, `source_evidence` must contain one EXACT quote of 5 to 10 words copied character-for-character from the chapter. Do not paraphrase the quote. Do not invent concepts the chapter does not support.

12. Output ONLY the JSON object. No other text.

Return the JSON in the following format:
{
  "topics": [
    {
      "topic_name": "Exactly the topic name as given to you",
      "concepts": [
        {
          "name": "Concept Name",
          "description": "Concept Description",
          "mastery_threshold": 80,
          "estimated_mastery_minutes": 15,
          "source_evidence": "exact quote from the chapter content"
        }
      ]
    }
  ]
}

Board: {board}
Standard: {standard}
Subject: {subject_name}
Chapter Name: {chapter_name}
Chapter Length: {chapter_chars} characters

Chapter Topics (the full list, in teaching order):
{chapter_outline}

Topics To Process (produce concepts for every one of these):
{topic_table}

Chapter Content (this is the COMPLETE chapter):
{chapter_content}
"""

SYSTEM_PROMPT = "You are a helpful assistant. Return ONLY a JSON object."

# Substituted in a single pass so a value can never be rescanned as a
# placeholder, and so the literal braces of the JSON example survive untouched
# (which is also why this prompt is not an f-string).
_PLACEHOLDER_RE = re.compile(
    r"\{(board|standard|subject_name|chapter_name|chapter_chars|chapter_outline"
    r"|topic_table|chapter_content|min_concepts|max_concepts)\}"
)


def _fill(template: str, values: Dict[str, str]) -> str:
    return _PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), ""), template)


# ---------------------------------------------------------------------------
# Deterministic post-pass: coercion, thresholds, dedupe
# ---------------------------------------------------------------------------

# lms_concept.mastery_threshold is a percentage; the rubric in rule 7 never
# licenses anything outside this band, so a model that answers 0 or 120 is
# clamped rather than written through.
_MIN_THRESHOLD = 50
_MAX_THRESHOLD = 100
_DEFAULT_THRESHOLD = 80


def _clean_concepts(raw_concepts: Any) -> List[Dict[str, Any]]:
    """Coerce the model's list into well-formed concept dicts, dropping junk."""
    if not isinstance(raw_concepts, list):
        return []

    cleaned: List[Dict[str, Any]] = []
    for item in raw_concepts:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        threshold = ct.safe_int(item.get("mastery_threshold"), _DEFAULT_THRESHOLD) or _DEFAULT_THRESHOLD
        # lms_concept.name is VARCHAR(191).
        cleaned.append({
            "name": name[:191],
            "description": str(item.get("description") or "").strip(),
            "mastery_threshold": min(_MAX_THRESHOLD, max(_MIN_THRESHOLD, threshold)),
            "estimated_mastery_minutes": max(
                1, ct.safe_int(item.get("estimated_mastery_minutes"), 15) or 15
            ),
            "source_evidence": str(item.get("source_evidence") or "").strip(),
        })

    return cleaned


def _dedupe_across_topics(results: List[Dict[str, Any]]) -> int:
    """Drop a concept that a later topic repeats; the earlier topic keeps it.

    A safety net, not the primary mechanism. Rule 5 makes cross-topic
    de-duplication the model's job now that one call sees every topic at once,
    which it can do far better than name matching -- it knows two differently
    worded entries mean the same idea. This catches what slips through. Results
    must already be in chapter teaching order.

    Matching is by token containment, not exact name, and a topic is never
    stripped bare: a childless topic breaks the hierarchy, which is worse than
    keeping one near-duplicate concept under it.
    """
    return ct.dedupe_by_name(results, "concepts", "name", keep_at_least_one=True)


# ---------------------------------------------------------------------------
# LLM: one master prompt, the whole chapter, every topic at once
# ---------------------------------------------------------------------------

# Expected concept yield, scaled to how much the chapter actually teaches. Given
# to the model as its own global budget (rule 4) so it can judge the total, not
# just each topic in isolation -- the calibration a topic-scoped call could
# never have. Chapters here run 8k-64k chars and land around 40 concepts.
_CONCEPTS_PER_1K_CHARS = (0.8, 1.8)
_CONCEPTS_FLOOR = 12


def _concept_budget(chapter_chars: int, topic_count: int) -> tuple[int, int]:
    low, high = (round(chapter_chars / 1000 * rate) for rate in _CONCEPTS_PER_1K_CHARS)
    # Never below three per topic, whatever the arithmetic says about a short
    # chapter: every topic still has to be divisible into something.
    return max(_CONCEPTS_FLOOR, topic_count * 3, low), max(topic_count * 4, high)


def _topic_table(topics: List[Dict[str, Any]]) -> str:
    """The topics this call must return concepts for, with their minute budgets."""
    lines = []
    for order, topic in enumerate(topics, start=1):
        budget = ct.safe_int(topic.get("estimated_minutes"), _DEFAULT_TOPIC_MINUTES) or _DEFAULT_TOPIC_MINUTES
        description = (topic.get("description") or "").strip()
        lines.append(f"{order}. {topic['name']}  [Minutes: {budget}]")
        if description:
            lines.append(f"     {description}")
    return "\n".join(lines)


def _chapter_outline(topics: List[Dict[str, Any]]) -> str:
    return "\n".join(f"{order}. {t['name']}" for order, t in enumerate(topics, start=1))


def _match_returned_topics(
    returned: Any,
    targets: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Line the model's answer back up with the topics we asked about.

    Matching is by name rather than by position: a model that drops or reorders
    a topic would otherwise have every subsequent topic's concepts filed under
    the wrong parent, which is silent and much worse than a missing topic.
    Position is the fallback only when the count came back exactly right.
    """
    blocks = returned if isinstance(returned, list) else []
    by_key: Dict[str, Any] = {}
    for block in blocks:
        if isinstance(block, dict):
            by_key.setdefault(ct.match_key(str(block.get("topic_name") or "")), block)

    results: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []
    for index, topic in enumerate(targets):
        block = by_key.get(ct.match_key(topic["name"]))
        if block is None and len(blocks) == len(targets) and isinstance(blocks[index], dict):
            block = blocks[index]

        budget = ct.safe_int(topic.get("estimated_minutes"), _DEFAULT_TOPIC_MINUTES) or _DEFAULT_TOPIC_MINUTES
        concepts = _clean_concepts((block or {}).get("concepts"))
        if not concepts:
            missing.append({
                "topic_id": topic["id"],
                "topic_name": topic["name"],
                "error": "the model returned no concepts for this topic",
            })
            continue
        results.append({
            "topic_id": topic["id"],
            "topic_name": topic["name"],
            "topic_minutes": budget,
            "concepts": concepts,
        })
    return results, missing


async def _extract_concepts(
    *,
    md_content: str,
    targets: List[Dict[str, Any]],
    all_topics: List[Dict[str, Any]],
    chapter_name: str,
    subject_name: str,
    standard: Any,
    board: Any,
) -> Dict[str, Any]:
    """Ask once, about the entire chapter and every topic in it.

    targets is normally all_topics. A single-topic retry narrows it to one, but
    still sends the whole chapter and the full outline, because the point of
    this design is that the model always sees what it is dividing.
    """
    low, high = _concept_budget(len(md_content), len(all_topics))

    prompt = _fill(CONCEPT_PROMPT, {
        "board": str(board or "").strip() or "(not specified)",
        "standard": str(standard or ""),
        "subject_name": str(subject_name or ""),
        "chapter_name": str(chapter_name or ""),
        "chapter_chars": str(len(md_content)),
        "chapter_outline": _chapter_outline(all_topics),
        "topic_table": _topic_table(targets),
        "chapter_content": md_content,
        "min_concepts": str(low),
        "max_concepts": str(high),
    })

    result = await async_call_deepseek(
        prompt,
        system_prompt=SYSTEM_PROMPT,
        response_format={"type": "json_object"},
    )
    data = result.get("data") or {}
    if not isinstance(data, dict):
        data = {}

    results, missing = _match_returned_topics(data.get("topics"), targets)

    for entry in results:
        ct.normalise_minutes(entry["concepts"], "estimated_mastery_minutes", entry["topic_minutes"])
        # Grounded against the whole chapter, which is what the model was shown.
        ct.verify_grounding(entry["concepts"], md_content)

    return {
        "results": results,
        "missing": missing,
        "concept_budget": [low, high],
        "input_tokens": result.get("input_tokens", 0),
        "output_tokens": result.get("output_tokens", 0),
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

_INSERT_CONCEPT = text("""
    INSERT INTO lms_concept (
        extraction_id, topic_id, name, description, standard_id, subject_id,
        chapter_id, sub_institute_id, mastery_threshold,
        estimated_mastery_minutes, syear, created_at, updated_at
    ) VALUES (
        :extraction_id, :topic_id, :name, :description, :standard_id, :subject_id,
        :chapter_id, :sub_institute_id, :mastery_threshold,
        :estimated_mastery_minutes, :syear, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
    )
""")


def _persist_concepts(
    *,
    extraction_id: int,
    chapter_id: int,
    standard_id: Any,
    subject_id: Any,
    sub_institute_id: Any,
    syear: Any,
    results: List[Dict[str, Any]],
    topic_id: int | None,
) -> Dict[str, int]:
    """Rewrite this extraction's concepts, or one topic's when topic_id is set.

    lms_concept has no show/hide column, so a stale row can only be removed,
    not retired the way topic_master rows are. The delete is scoped as tightly
    as the run: a single-topic retry never touches a sibling topic's concepts.
    """
    with SessionLocal() as db:
        if topic_id is None:
            deleted = db.execute(
                text("DELETE FROM lms_concept WHERE extraction_id = :extraction_id"),
                {"extraction_id": extraction_id},
            ).rowcount
        else:
            deleted = db.execute(
                text("""DELETE FROM lms_concept
                         WHERE extraction_id = :extraction_id AND topic_id = :topic_id"""),
                {"extraction_id": extraction_id, "topic_id": topic_id},
            ).rowcount

        inserted = 0
        for result in results:
            for concept in result["concepts"]:
                concept["concept_id"] = db.execute(_INSERT_CONCEPT, {
                    "extraction_id": extraction_id,
                    "topic_id": result["topic_id"],
                    "name": concept["name"],
                    "description": concept["description"],
                    "standard_id": standard_id,
                    "subject_id": subject_id,
                    "chapter_id": chapter_id,
                    "sub_institute_id": sub_institute_id,
                    "mastery_threshold": concept["mastery_threshold"],
                    "estimated_mastery_minutes": concept["estimated_mastery_minutes"],
                    "syear": syear,
                }).lastrowid
                inserted += 1

        db.commit()
        return {"inserted": inserted, "deleted": deleted}


async def _persist_with_retry(write: Any, extraction_id: int) -> Dict[str, int]:
    """Run a synchronous write off the event loop, retrying transient DB faults."""
    last_error: OperationalError | None = None
    for attempt in range(_PERSIST_ATTEMPTS):
        try:
            return await asyncio.to_thread(write)
        except OperationalError as exc:
            last_error = exc
            if attempt == _PERSIST_ATTEMPTS - 1:
                break
            delay = _PERSIST_BACKOFF_SEC * (2 ** attempt)
            logger.warning(
                "Concept persistence attempt %s/%s for extraction %s failed (%s); retrying in %ss",
                attempt + 1, _PERSIST_ATTEMPTS, extraction_id, exc.orig, delay,
            )
            await asyncio.sleep(delay)

    raise RuntimeError(
        f"Concepts for extraction {extraction_id} were generated but could not "
        f"be saved after {_PERSIST_ATTEMPTS} attempts. The LLM output was lost; re-run once "
        f"the database is reachable. Last error: {last_error}"
    ) from last_error


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def process_concepts_by_id(
    extraction_id: int,
    force: bool = False,
    topic_id: int | None = None,
) -> Dict[str, Any]:
    """Extract concepts for every topic of a chapter (or one topic only)."""
    with SessionLocal() as db:
        row = db.execute(
            text("SELECT * FROM document_extractions WHERE id = :id"),
            {"id": extraction_id},
        ).mappings().fetchone()

        if not row:
            raise ValueError(f"No document_extraction found for id {extraction_id}")

        already = db.execute(
            text("SELECT COUNT(*) FROM lms_concept WHERE extraction_id = :id"),
            {"id": extraction_id},
        ).scalar()

        # A single-topic re-run is always an explicit retry, so it bypasses the
        # token-saving skip that the whole-chapter run applies.
        if already and not force and topic_id is None:
            return {
                "status": "already_processed",
                "action": "skipped",
                "message": "Concepts already processed. Skipped to save LLM tokens.",
                **(get_concept_data_by_extraction_id(extraction_id) or {}),
            }

        chapter = db.execute(
            text("""SELECT id, chapter_name, sub_institute_id, syear, standard_id, subject_id
                      FROM chapter_master WHERE extraction_id = :id"""),
            {"id": extraction_id},
        ).mappings().fetchone()

        if not chapter:
            raise ValueError(
                f"No chapter_master found for extraction_id {extraction_id}. Process the chapter first."
            )

        # Hidden topics are retired rows from an earlier run; breaking them into
        # concepts would resurrect content the chapter no longer teaches.
        all_topics = [dict(t) for t in db.execute(
            text("""SELECT id, name, description, estimated_minutes
                      FROM topic_master
                     WHERE extraction_id = :id AND COALESCE(topic_show_hide, 1) = 1
                  ORDER BY topic_sort_order ASC, id ASC"""),
            {"id": extraction_id},
        ).mappings().fetchall()]

        if not all_topics:
            raise ValueError(
                f"No topic_master rows found for extraction_id {extraction_id}. Process the topics first."
            )

        md_content = row.get("md_content") or ""
        if not md_content:
            raise ValueError(f"document_extraction {extraction_id} has no md_content")

        chapter_id = chapter["id"]
        chapter_name = chapter["chapter_name"] or row.get("document_tittle") or ""
        # Tenant, year, standard and subject come from the chapter, not the
        # extraction: lms_concept rows must sit alongside their parent chapter
        # or the ERP will not list them.
        standard_id = chapter["standard_id"] or row.get("standard_id")
        subject_id = chapter["subject_id"] or row.get("subject_id")
        sub_institute_id = chapter["sub_institute_id"] or row.get("sub_institute_id") or 341
        syear = chapter["syear"] or row.get("syear")
        subject_name = row.get("subject_name")
        standard = row.get("standard")
        board = row.get("board")

    targets = all_topics
    if topic_id is not None:
        targets = [t for t in all_topics if t["id"] == topic_id]
        if not targets:
            raise ValueError(f"Topic {topic_id} does not belong to extraction {extraction_id}")

    # One call, the whole chapter, every topic at once. A provider fault is not
    # caught: with a single call there is nothing to salvage, so it propagates
    # to the route and becomes a 503 naming the actual cause.
    extracted = await _extract_concepts(
        md_content=md_content,
        targets=targets,
        all_topics=all_topics,
        chapter_name=chapter_name,
        subject_name=subject_name,
        standard=standard,
        board=board,
    )

    failed = extracted["missing"]
    # Chapter teaching order, so the dedupe below keeps the occurrence in the
    # topic that teaches it first.
    order = {t["id"]: i for i, t in enumerate(all_topics)}
    results = sorted(extracted["results"], key=lambda r: order[r["topic_id"]])

    if not results:
        raise RuntimeError(
            f"Concept extraction produced nothing for extraction {extraction_id}: the model "
            f"returned no concepts for any of the {len(targets)} topic(s) it was given. "
            f"Check the backend log for the raw response."
        )

    duplicates_dropped = _dedupe_across_topics(results)

    # Re-scaled AFTER the dedupe, not before. _extract_concepts already scaled
    # each topic to its budget, so dropping a concept afterwards leaves the
    # survivors summing to less than it -- one topic came back at 5 minutes
    # against a 20 minute budget that way.
    for result in results:
        ct.normalise_minutes(result["concepts"], "estimated_mastery_minutes",
                             result["topic_minutes"])

    # A whole-chapter run replaces every concept of the extraction. A
    # single-topic retry must leave the other topics' concepts in place, and it
    # must not delete this topic's rows when the run that produced them failed.
    delete_scope = None if topic_id is None else results[0]["topic_id"]

    def write() -> Dict[str, int]:
        return _persist_concepts(
            extraction_id=extraction_id,
            chapter_id=chapter_id,
            standard_id=standard_id,
            subject_id=subject_id,
            sub_institute_id=sub_institute_id,
            syear=syear,
            results=results,
            topic_id=delete_scope,
        )

    counts = await _persist_with_retry(write, extraction_id)

    total_concepts = sum(len(r["concepts"]) for r in results)
    grounded = sum(1 for r in results for c in r["concepts"] if c.get("evidence_verified"))

    return {
        "status": "success",
        "action": "inserted",
        "extraction_id": extraction_id,
        "chapter_id": chapter_id,
        "topics_processed": len(results),
        "topics_failed": len(failed),
        "failed_topics": failed,
        "concepts_extracted": total_concepts,
        "concept_budget": extracted["concept_budget"],
        "duplicates_dropped": duplicates_dropped,
        "grounded_concepts": grounded,
        "ungrounded_concepts": total_concepts - grounded,
        "input_tokens": extracted["input_tokens"],
        "output_tokens": extracted["output_tokens"],
        **counts,
        **(get_concept_data_by_extraction_id(extraction_id) or {}),
    }


def get_concept_data_by_extraction_id(extraction_id: int) -> Dict[str, Any] | None:
    """Concepts for an extraction, grouped topic-wise in teaching order."""
    with SessionLocal() as db:
        rows = db.execute(
            text("""
                SELECT c.id, c.name, c.description, c.mastery_threshold,
                       c.estimated_mastery_minutes, c.topic_id, c.chapter_id, c.syear,
                       t.name AS topic_name, t.estimated_minutes AS topic_minutes,
                       t.topic_sort_order
                  FROM lms_concept c
             LEFT JOIN topic_master t ON t.id = c.topic_id
                 WHERE c.extraction_id = :id
              ORDER BY COALESCE(t.topic_sort_order, 0) ASC, c.id ASC
            """),
            {"id": extraction_id},
        ).mappings().fetchall()

        if not rows:
            return None

        grouped: List[Dict[str, Any]] = []
        index: Dict[Any, Dict[str, Any]] = {}
        for row in rows:
            bucket = index.get(row["topic_id"])
            if bucket is None:
                bucket = {
                    "topic_id": row["topic_id"],
                    # Rows written before the hierarchy was inverted carry no
                    # topic_id; they are still shown rather than hidden.
                    "topic_name": row["topic_name"] or "Unassigned (chapter-wise)",
                    "topic_minutes": row["topic_minutes"],
                    "sort_order": row["topic_sort_order"],
                    "concepts": [],
                }
                index[row["topic_id"]] = bucket
                grouped.append(bucket)
            bucket["concepts"].append({
                "concept_id": row["id"],
                "name": row["name"],
                "description": row["description"],
                "mastery_threshold": row["mastery_threshold"],
                "estimated_mastery_minutes": row["estimated_mastery_minutes"],
            })

        return {
            "extraction_id": extraction_id,
            "chapter_id": rows[0]["chapter_id"],
            "total_concepts": len(rows),
            "topics": grouped,
        }


def get_all_concepts_queue() -> List[Dict[str, Any]]:
    with SessionLocal() as db:
        query = text("""
            SELECT d.id, d.document_tittle, d.subject_name, d.standard, d.syear, d.board,
                   d.chapter_number, d.created_at,
                   EXISTS(SELECT 1 FROM lms_concept c WHERE c.extraction_id = d.id) AS is_processed,
                   EXISTS(SELECT 1 FROM chapter_master cm WHERE cm.extraction_id = d.id) AS has_chapter,
                   EXISTS(SELECT 1 FROM topic_master t WHERE t.extraction_id = d.id) AS has_topic,
                   (SELECT COUNT(*) FROM topic_master t WHERE t.extraction_id = d.id) AS topic_count,
                   (SELECT COUNT(*) FROM lms_concept c WHERE c.extraction_id = d.id) AS concept_count
              FROM document_extractions d
             WHERE LOWER(d.document_type) = 'chapter'
          ORDER BY d.id DESC
        """)
        return [dict(row) for row in db.execute(query).mappings().fetchall()]
