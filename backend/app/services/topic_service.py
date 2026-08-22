"""Topic Queue: break a chapter into its main teachable topics.

ONE prompt sees the WHOLE chapter and returns its topic list. That is the entire
design, and it is deliberate. This module used to cut the chapter into
prompt-sized segments and extract from each one separately, which produced 19
topics for a 6-section chapter: the prompt asked for "3 to 10 topics from this
part", the chapter was cut into two parts, and 6 to 20 topics was therefore
arithmetically guaranteed. No call could see the whole chapter, so nothing could
calibrate the total.

The whole chapter always fits -- the largest in this corpus is 64k chars, about
17k tokens -- so there was never anything to gain from splitting it.

The output stays small (a topic list, not an essay), so a single whole-chapter
call is also the cheapest option available.

This is the middle level of the extraction hierarchy:

    Chapter -> Topics -> Concepts

so this module depends only on chapter_master. Concepts are generated from
these topics afterwards by concept_service, not before them.

topic_master is shared with the rest of the ERP and its ids are referenced by
content_master, lms_question_master and lms_lesson_plan, so this module never
deletes a row. Topics that disappear from a re-run are hidden
(topic_show_hide = 0), and only rows this pipeline created (extraction_id set)
are ever touched.
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

# Retries for the post-run write. A long chapter runs for minutes, by which
# time pooled connections are stale, and a transient connect failure would
# otherwise throw away the whole LLM run.
_PERSIST_ATTEMPTS = 4
_PERSIST_BACKOFF_SEC = 3


TOPIC_PROMPT = """You are an expert curriculum designer and instructional sequencer. You work across every school board (CBSE/NCERT, Cambridge, ICSE, IB and state boards), standards 1 to 12, and every subject including Hindi, Gujarati, English, Sanskrit, Mathematics, Science, Social Science, History, Geography, Civics, Biology, Chemistry, Physics and Computer Science.

Your task is to read a COMPLETE chapter and return its MAIN TOPICS — the handful of major areas the chapter is built from, the ones a textbook would give their own numbered section to. Return ONLY a valid JSON object. No explanation, no markdown, no preamble, no trailing text.

Rules you must follow:

1. FOLLOW THE BOOK FIRST. `Chapter Outline` below is extracted from the chapter itself. If it is marked AUTHORITATIVE, those numbered sections ARE this chapter's topics: return exactly one topic per listed section, in that order. Do not split one numbered section into several topics. Do not merge two numbered sections into one. Do not add topics that are not in the list.
   Use the book's own wording for `topic_name` — EXCEPT where an outline entry is obviously damaged by text extraction: truncated mid-word, cut off after one word, or with a stray sentence attached ("1.3 HAVE", "1.6 Assess your learning 1."). For those, read that section in the chapter content and write the name the section actually deserves. Fix the wording; never change the number of topics.

2. HOW MANY. When the outline is not authoritative, decide from the content. A chapter of this size normally has 4 to 8 main topics. Returning more than 10 means you have split at the wrong level — go back and merge them upwards. Returning fewer than 3 means you have summarised the chapter rather than divided it.

3. WHAT COUNTS AS A TOPIC. A main topic is a major area a teacher would spend one to three classroom periods on, and which a textbook would give its own numbered section. It is NOT a single explanation, a single worked example, or a single rule.
   Test it: "Adding integers", "Subtracting integers" and "Estimating integer calculations by rounding" are NOT three topics. They are one topic — "Adding and subtracting integers". Likewise "Divisibility test for 7", "Divisibility test for 11" and "Divisibility tests for 8, 9 and 10" are one topic: "Tests for divisibility".
   Before returning a topic, ask: would a textbook print this as its own numbered heading? If not, merge it into the topic it belongs to.

4. LITERARY AND LANGUAGE CHAPTERS. If the chapter is prose, poetry, a story or a play and has no sections or numbered headings, its topics are the teaching units a language teacher delivers: the summary of the text, its central theme or message, the poet or author and context, character study, literary or poetic devices, vocabulary and word meanings, and any grammar point the chapter teaches. Do NOT divide such a chapter paragraph by paragraph or scene by scene.

5. ADAPT TO THE LEVEL:
   - Std 1-5 (Primary): simple topics; basic vocabulary, simple ideas, one activity
   - Std 6-8 (Middle): definitions, processes, simple relationships
   - Std 9-10 (Secondary): principles, laws, formulas, derivational steps, problem types
   - Std 11-12 (Higher Secondary): advanced theory, derivations, analytical and applied topics

6. CRITICAL INSTRUCTION: ALL extracted text (Topic Names AND Descriptions) MUST strictly remain in the ORIGINAL script/language (e.g., Sanskrit, Hindi, Gujarati, Marathi) found in the chapter content. DO NOT translate any text into English. Only the JSON keys must be in English.

7. `topic_name` must be concise (2 to 8 words). `description` must be 1 to 2 sentences describing what the learner will be taught in this topic.

8. `sequence_order` is an integer starting at 1, in the order the chapter teaches these topics. Follow the chapter's own order; do not resequence it.

9. `estimated_minutes` is an integer of classroom teaching time for that topic, assigned by cognitive load and by how much of the chapter it covers:
   - 10 to 15 mins: Low Cognitive Load (Remembering, Identifying, Memorizing definitions/facts)
   - 20 to 30 mins: Medium Cognitive Load (Understanding, Applying, Solving basic problems, Explaining processes)
   - 45 to 90 mins: High Cognitive Load (Analyzing, Evaluating, Derivations, Complex multi-step problem solving, Abstract reasoning)

10. GROUNDING: every topic MUST come from the `Chapter Content` below. For each topic, `source_evidence` must contain one EXACT quote of 5 to 10 words copied character-for-character from where that topic begins. Do not paraphrase the quote. Do not invent topics the content does not support.

11. Do NOT duplicate topics. Two topics must not describe the same teaching unit in different words.

12. Do NOT create a topic out of revision or practice material. Exercise questions, worked-example question lists, "Getting started", "Check your progress", "Summary checklist" and end-of-unit review items PRACTISE topics that the chapter teaches elsewhere -- they are not themselves new topics. Extract a topic only where the content TEACHES something: an explanation, a definition, a rule, a method, or a worked demonstration of one. A named project or investigation IS teachable content and DOES get its own topic, because it develops something the chapter does not cover anywhere else.

13. Output ONLY the JSON object. No other text.

Return the JSON in the following format:
{
  "topics": [
    {
      "topic_name": "Topic Name",
      "description": "What the learner is taught in this topic.",
      "sequence_order": 1,
      "estimated_minutes": 30,
      "source_evidence": "exact quote from where this topic begins"
    }
  ]
}

Board: {board}
Standard: {standard}
Subject: {subject_name}
Chapter Name: {chapter_name}
Chapter Length: {chapter_chars} characters

Chapter Outline ({outline_status}):
{chapter_outline}

Chapter Content (this is the COMPLETE chapter):
{chapter_content}
"""

SYSTEM_PROMPT = "You are a helpful assistant. Return ONLY a JSON object."

# Substituted in a single pass so a value can never be rescanned as a
# placeholder, and so the literal braces of the JSON example survive untouched
# (which is also why this prompt is not an f-string).
_PLACEHOLDER_RE = re.compile(
    r"\{(board|standard|subject_name|chapter_name|chapter_chars"
    r"|outline_status|chapter_outline|chapter_content)\}"
)


def _fill(template: str, values: Dict[str, str]) -> str:
    return _PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), ""), template)


# ---------------------------------------------------------------------------
# Deterministic post-pass: coercion, dedupe
# ---------------------------------------------------------------------------

def _clean_topics(raw_topics: Any) -> List[Dict[str, Any]]:
    """Coerce the model's list into well-formed topic dicts, dropping junk."""
    if not isinstance(raw_topics, list):
        return []

    cleaned: List[Dict[str, Any]] = []
    for index, item in enumerate(raw_topics):
        if not isinstance(item, dict):
            continue
        name = str(item.get("topic_name") or "").strip()
        if not name:
            continue
        # topic_master.name is VARCHAR(250).
        cleaned.append({
            "topic_name": name[:250],
            "description": str(item.get("description") or "").strip(),
            "sequence_order": ct.safe_int(item.get("sequence_order"), index + 1) or index + 1,
            "estimated_minutes": max(1, ct.safe_int(item.get("estimated_minutes"), 15) or 15),
            "source_evidence": str(item.get("source_evidence") or "").strip(),
        })

    cleaned.sort(key=lambda t: t["sequence_order"])
    return cleaned


def _dedupe_topics(topics: List[Dict[str, Any]]) -> int:
    """Drop a topic the model repeated under different wording.

    Rule 11 asks for this and one call can honour it, but "Common multiples" and
    "Lowest common multiple" still come back as two often enough to be worth
    catching. Matching is by token containment, not exact name.
    """
    group = [{"topics": topics}]
    dropped = ct.dedupe_by_name(group, "topics", "topic_name")
    topics[:] = group[0]["topics"]
    return dropped


# Beyond this the model has split at the wrong level -- rule 3 is being ignored.
# Reported rather than truncated: cutting the list would silently drop the tail
# of the chapter, which is worse than an over-long list somebody can see.
_EXPECTED_TOPIC_MAX = 10


# ---------------------------------------------------------------------------
# LLM: one master prompt, the whole chapter
# ---------------------------------------------------------------------------

async def _extract_topics(
    *,
    md_content: str,
    chapter_outline: str,
    outline_is_authoritative: bool,
    chapter_name: str,
    subject_name: str,
    standard: Any,
    board: Any,
) -> Dict[str, Any]:
    """Ask once, about the entire chapter."""
    prompt = _fill(TOPIC_PROMPT, {
        "board": str(board or "").strip() or "(not specified)",
        "standard": str(standard or ""),
        "subject_name": str(subject_name or ""),
        "chapter_name": str(chapter_name or ""),
        "chapter_chars": str(len(md_content)),
        "outline_status": (
            "AUTHORITATIVE - these numbered sections are the chapter's topics"
            if outline_is_authoritative
            else "a hint only - this chapter does not number its sections, so derive the topics from the content"
        ),
        "chapter_outline": chapter_outline,
        "chapter_content": md_content,
    })

    result = await async_call_deepseek(
        prompt,
        system_prompt=SYSTEM_PROMPT,
        response_format={"type": "json_object"},
    )
    data = result.get("data") or {}
    if not isinstance(data, dict):
        data = {}

    topics = _clean_topics(data.get("topics"))
    ct.verify_grounding(topics, md_content)

    return {
        "topics": topics,
        "input_tokens": result.get("input_tokens", 0),
        "output_tokens": result.get("output_tokens", 0),
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

_SELECT_EXISTING = text("""
    SELECT id, name, extraction_id, topic_sort_order
    FROM topic_master
    WHERE chapter_id = :chapter_id
      AND (syear <=> :syear)
""")

# concept_id is deliberately not named. Under Chapter -> Topics -> Concepts a
# topic is the PARENT of its concepts, so the link lives on lms_concept.topic_id
# and this column is dead. Naming it even to write NULL makes the INSERT fail
# outright once someone drops it, which is exactly what happened on this
# database -- and the failure lands after the whole LLM fan-out has run, so it
# costs a full chapter of tokens. Leaving it out works whether or not the
# column is still there.
_INSERT_TOPIC = text("""
    INSERT INTO topic_master
        (sub_institute_id, chapter_id, extraction_id, main_topic_id,
         name, description, estimated_minutes, topic_show_hide, topic_sort_order,
         syear, created_at, updated_at)
    VALUES
        (:sub_institute_id, :chapter_id, :extraction_id, 0,
         :name, :description, :estimated_minutes, 1, :sort_order,
         :syear, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
""")

_UPDATE_TOPIC = text("""
    UPDATE topic_master
       SET extraction_id = :extraction_id,
           description = :description,
           estimated_minutes = :estimated_minutes,
           topic_sort_order = :sort_order,
           topic_show_hide = 1,
           updated_at = CURRENT_TIMESTAMP
     WHERE id = :id
""")

# Only ever applied to rows this pipeline created, and only to hide them.
_RETIRE_TOPIC = text("""
    UPDATE topic_master
       SET topic_show_hide = 0, updated_at = CURRENT_TIMESTAMP
     WHERE id = :id AND extraction_id = :extraction_id
""")


def _existing_by_name(rows: List[Any]) -> Dict[str, Any]:
    """Natural key is (chapter_id, syear, match_key(name))."""
    by_name: Dict[str, Any] = {}
    for row in rows:
        key = ct.match_key(row["name"])
        if key and key not in by_name:
            by_name[key] = row
    return by_name


def _persist_topics(
    *,
    extraction_id: int,
    chapter_id: int,
    sub_institute_id: Any,
    syear: Any,
    topics: List[Dict[str, Any]],
) -> Dict[str, int]:
    """Upsert every topic of one chapter. Never deletes."""
    with SessionLocal() as db:
        existing_rows = db.execute(
            _SELECT_EXISTING, {"chapter_id": chapter_id, "syear": syear}
        ).mappings().fetchall()

        # Scoping by syear keeps the hand-entered syear-2021 topics on chapters
        # 1012-1024 out of reach: they belong to an older academic year, not to
        # this extraction.
        by_name = _existing_by_name(existing_rows)

        inserted = updated = 0
        touched_ids: set[int] = set()

        for sort_order, topic in enumerate(topics, start=1):
            params = {
                "sub_institute_id": sub_institute_id,
                "chapter_id": chapter_id,
                "extraction_id": extraction_id,
                "name": topic["topic_name"],
                "description": topic["description"],
                "estimated_minutes": topic["estimated_minutes"],
                "sort_order": sort_order,
                "syear": syear,
            }
            match = by_name.get(ct.match_key(topic["topic_name"]))
            if match:
                db.execute(_UPDATE_TOPIC, {**params, "id": match["id"]})
                topic_id = match["id"]
                updated += 1
            else:
                topic_id = db.execute(_INSERT_TOPIC, params).lastrowid
                inserted += 1
            touched_ids.add(topic_id)
            topic["topic_id"] = topic_id

        # A topic this pipeline wrote before but that no longer appears is
        # hidden, not removed: content_master and lms_question_master rows may
        # already point at its id. This is also what prunes the over-extracted
        # topics an earlier, segment-based run left behind.
        retired = 0
        for row in existing_rows:
            if row["extraction_id"] == extraction_id and row["id"] not in touched_ids:
                db.execute(_RETIRE_TOPIC, {"id": row["id"], "extraction_id": extraction_id})
                retired += 1

        db.commit()
        return {"inserted": inserted, "updated": updated, "retired": retired}


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
                "Topic persistence attempt %s/%s for extraction %s failed (%s); retrying in %ss",
                attempt + 1, _PERSIST_ATTEMPTS, extraction_id, exc.orig, delay,
            )
            await asyncio.sleep(delay)

    raise RuntimeError(
        f"Topics for extraction {extraction_id} were generated but could not "
        f"be saved after {_PERSIST_ATTEMPTS} attempts. The LLM output was lost; re-run once "
        f"the database is reachable. Last error: {last_error}"
    ) from last_error


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def process_topics_by_id(
    extraction_id: int,
    force: bool = False,
) -> Dict[str, Any]:
    """Extract the main topics of a chapter in a single whole-chapter call."""
    with SessionLocal() as db:
        row = db.execute(
            text("SELECT * FROM document_extractions WHERE id = :id"),
            {"id": extraction_id},
        ).mappings().fetchone()

        if not row:
            raise ValueError(f"No document_extraction found for id {extraction_id}")

        already = db.execute(
            text("SELECT COUNT(*) FROM topic_master WHERE extraction_id = :id"),
            {"id": extraction_id},
        ).scalar()

        if already and not force:
            return {
                "status": "already_processed",
                "action": "skipped",
                "message": "Topics already processed. Skipped to save LLM tokens.",
                **(get_topic_data_by_extraction_id(extraction_id) or {}),
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

        md_content = row.get("md_content") or ""
        if not md_content:
            raise ValueError(f"document_extraction {extraction_id} has no md_content")

        chapter_id = chapter["id"]
        chapter_name = chapter["chapter_name"] or row.get("document_tittle") or ""
        # Institute and academic year come from the chapter, not the hardcoded
        # 341: topic_master rows must sit in the same tenant/year as their
        # parent chapter or the ERP will not list them.
        sub_institute_id = chapter["sub_institute_id"] or row.get("sub_institute_id") or 341
        syear = chapter["syear"] or row.get("syear")
        subject_name = row.get("subject_name")
        standard = row.get("standard")
        board = row.get("board")

    # The chapter's own outline, computed once and handed to the model as either
    # its answer (when the book numbers its sections) or a hint (when it does
    # not). Around half this corpus falls in the second case.
    chapter_outline, outline_is_authoritative = ct.topic_outline(md_content)

    result = await _extract_topics(
        md_content=md_content,
        chapter_outline=chapter_outline,
        outline_is_authoritative=outline_is_authoritative,
        chapter_name=chapter_name,
        subject_name=subject_name,
        standard=standard,
        board=board,
    )

    topics = result["topics"]
    if not topics:
        raise RuntimeError(
            f"Topic extraction produced nothing for extraction {extraction_id}: the model "
            f"returned no usable topics for a {len(md_content)}-character chapter. "
            f"Check the backend log for the raw response."
        )

    duplicates_dropped = _dedupe_topics(topics)

    # Spans are derived, never stored: the Concept Queue rebuilds the identical
    # partition from the same chapter text and the same ordered topic names.
    spans = ct.partition_by_topics(md_content, [t["topic_name"] for t in topics])
    for topic, (start, end) in zip(topics, spans):
        topic["span_chars"] = end - start

    thin = [t["topic_name"] for t in topics if t["span_chars"] < ct.MIN_TOPIC_SPAN_CHARS]
    if thin:
        logger.warning(
            "Extraction %s: %s topic(s) own less than %s characters of chapter text (%s). "
            "That usually means the chapter was split below the topic level.",
            extraction_id, len(thin), ct.MIN_TOPIC_SPAN_CHARS, ", ".join(thin[:5]),
        )
    if len(topics) > _EXPECTED_TOPIC_MAX:
        logger.warning(
            "Extraction %s produced %s topics for a %s-character chapter; more than %s "
            "means the model split below the topic level (rule 3).",
            extraction_id, len(topics), len(md_content), _EXPECTED_TOPIC_MAX,
        )

    def write() -> Dict[str, int]:
        return _persist_topics(
            extraction_id=extraction_id,
            chapter_id=chapter_id,
            sub_institute_id=sub_institute_id,
            syear=syear,
            topics=topics,
        )

    counts = await _persist_with_retry(write, extraction_id)

    grounded = sum(1 for t in topics if t.get("evidence_verified"))

    return {
        "status": "success",
        "action": "updated" if counts["updated"] and not counts["inserted"] else "inserted",
        "extraction_id": extraction_id,
        "chapter_id": chapter_id,
        "chapter_chars": len(md_content),
        "outline_authoritative": outline_is_authoritative,
        "topics_extracted": len(topics),
        "duplicates_dropped": duplicates_dropped,
        "grounded_topics": grounded,
        "ungrounded_topics": len(topics) - grounded,
        "thin_topics": thin,
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        **counts,
        **(get_topic_data_by_extraction_id(extraction_id) or {}),
    }


def get_topic_data_by_extraction_id(extraction_id: int) -> Dict[str, Any] | None:
    """The chapter's live topics, in teaching order.

    Retired rows are counted but not listed. They are topics an earlier run
    produced that this chapter no longer teaches -- kept in the table only
    because other ERP rows may reference their ids -- and including them made
    a re-run of chapter 147 report 23 topics when it had just produced 6.

    concept_count comes back with each topic because concepts are generated
    from topics downstream, and the Concept Queue needs to show which topics
    have already been broken down.
    """
    with SessionLocal() as db:
        rows = db.execute(
            text("""
                SELECT t.id, t.name, t.description, t.estimated_minutes, t.topic_sort_order,
                       t.topic_show_hide, t.chapter_id, t.syear,
                       (SELECT COUNT(*) FROM lms_concept c WHERE c.topic_id = t.id) AS concept_count
                  FROM topic_master t
                 WHERE t.extraction_id = :id
              ORDER BY t.topic_sort_order ASC, t.id ASC
            """),
            {"id": extraction_id},
        ).mappings().fetchall()

        if not rows:
            return None

        topics = [{
            "topic_id": row["id"],
            "topic_name": row["name"],
            "description": row["description"],
            "estimated_minutes": row["estimated_minutes"],
            "sort_order": row["topic_sort_order"],
            "is_hidden": False,
            "concept_count": row["concept_count"],
        } for row in rows if row["topic_show_hide"] != 0]

        return {
            "extraction_id": extraction_id,
            "chapter_id": rows[0]["chapter_id"],
            "total_topics": len(topics),
            "hidden_topics": len(rows) - len(topics),
            "total_minutes": sum(t["estimated_minutes"] or 0 for t in topics),
            "topics": topics,
        }


def get_all_topics_queue() -> List[Dict[str, Any]]:
    with SessionLocal() as db:
        query = text("""
            SELECT d.id, d.document_tittle, d.subject_name, d.standard, d.syear, d.board,
                   d.chapter_number, d.created_at,
                   EXISTS(SELECT 1 FROM topic_master t WHERE t.extraction_id = d.id) AS is_processed,
                   EXISTS(SELECT 1 FROM chapter_master cm WHERE cm.extraction_id = d.id) AS has_chapter,
                   (SELECT COUNT(*) FROM topic_master t WHERE t.extraction_id = d.id) AS topic_count,
                   (SELECT COUNT(*) FROM lms_concept c WHERE c.extraction_id = d.id) AS concept_count
              FROM document_extractions d
             WHERE LOWER(d.document_type) = 'chapter'
          ORDER BY d.id DESC
        """)
        return [dict(row) for row in db.execute(query).mappings().fetchall()]
