"""Question Queue: publish a chapter's assessment items into the question bank.

    Chapter -> Topics -> Concepts -> Semantic Intelligence -> QUESTIONS

The questions are NOT written by a new prompt. Agent 4 of the Semantic
Intelligence swarm is the question-generation prompt for this system -- its
STAGE 13 says "Generate 4 to 6 assessment items FOR EACH concept" and it emits
complete CBSE mark schemes -- and it has already run for every chapter that has
semantic intelligence. Its output sits in
`semantic_intelligence.assessment_rubrics`, concept-wise, already grounded
(every source_evidence quote verified against the chapter) and already carrying
assessment_type, marks, Bloom, DOK, AO codes and distractor rationales.

So this module RE-USES that output rather than regenerating it. Agent 4's prompt
is not read, not copied and not modified here; it is upstream, and this is the
consumer. That also means the bulk of a chapter's questions cost no LLM call.

The one thing Agent 4 provably cannot supply is a PREREQUISITE question. Its
prompt binds every item to "answerable from the supplied source text alone", and
a prerequisite is by definition knowledge from an earlier chapter or grade, which
is not in that text. Those two categories are therefore generated separately,
from the `prerequisites` dimension the swarm already extracted -- a different
question about different material, not a re-run of Agent 4.

The nine categories implement one learning journey:

    1  PREREQUISITE CHECK          prerequisite                 (generated)
    2  ADAPTIVE DIAGNOSTIC         adaptive_diagnostic          (from Agent 4)
    3  CONCEPT DIAGNOSIS           concept_diagnostic           (from Agent 4)
    6  CHECK FOR UNDERSTANDING     concept_understanding        (from Agent 4)
    6b MISCONCEPTION DETECTION     misconception_detection      (from Agent 4)
    7  TARGETED PREREQ RE-CHECK    prerequisite_concept_check   (generated)
    8  ADAPTIVE PRACTICE           adaptive_test                (from Agent 4)
    9  MASTERY CHECK               mastery_check                (from Agent 4)
    11 MASTERY RE-VERIFICATION     mastery_reverification       (from Agent 4)

Selection and distribution are decided in Python, so "every concept is covered"
and "no concept hogs the quota" are arithmetic guarantees rather than requests.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.db.mariadb import SessionLocal
from app.semantic_intelligence.deepseek_client import async_call_deepseek
from app.services import chapter_text as ct
from app.utils.config import settings

logger = logging.getLogger(__name__)

ANSWER_SCHEMA_VERSION = "ans-2.0"
# Agent 4's items are republished as-is; the version records where they came from.
REUSE_SOURCE = "semantic_intelligence.assessment_rubrics (agent4)"
PREREQ_PROMPT_VERSION = "qgen-prereq-1.0"
# Prerequisite items may also be supplied by hand instead of by the LLM. When
# they are, the envelope has to say so -- naming a model that never ran would
# make the provenance on the row a lie.
PREREQ_AUTHORED_VERSION = "qgen-prereq-authored-1.0"
PREREQ_AUTHORED_MODEL = "hand-authored"
PREREQ_AUTHORED_SOURCE = "semantic_intelligence.prerequisites (hand-authored)"
AUTHORED_PREREQ_PATH = Path(__file__).parent / "data" / "authored_prerequisites.json"

_PERSIST_ATTEMPTS = 4
_PERSIST_BACKOFF_SEC = 3

# question_type_master: 1 = multiple (option grid), 2 = narrative (free text).
QT_MULTIPLE = 1
QT_NARRATIVE = 2

MAX_PREREQ_PER_CALL = 6
MAX_CONCURRENCY = 4


class Category:
    PREREQUISITE = "prerequisite"
    ADAPTIVE_DIAGNOSTIC = "adaptive_diagnostic"
    CONCEPT_DIAGNOSTIC = "concept_diagnostic"
    CONCEPT_UNDERSTANDING = "concept_understanding"
    MISCONCEPTION_DETECTION = "misconception_detection"
    PREREQUISITE_CONCEPT_CHECK = "prerequisite_concept_check"
    ADAPTIVE_TEST = "adaptive_test"
    MASTERY_CHECK = "mastery_check"
    MASTERY_REVERIFICATION = "mastery_reverification"


# pal_question_metadata uses a narrow controlled vocabulary already present in
# the table: item_type is one of recall/application/transfer, practice_level 1-5.
CATEGORY_SPEC: Dict[str, Dict[str, Any]] = {
    Category.PREREQUISITE:               {"flow_step": 1,  "item_type": "recall",      "practice_level": 1},
    Category.ADAPTIVE_DIAGNOSTIC:        {"flow_step": 2,  "item_type": "recall",      "practice_level": 2},
    Category.CONCEPT_DIAGNOSTIC:         {"flow_step": 3,  "item_type": "recall",      "practice_level": 2},
    Category.CONCEPT_UNDERSTANDING:      {"flow_step": 6,  "item_type": "application", "practice_level": 3},
    Category.MISCONCEPTION_DETECTION:    {"flow_step": 6,  "item_type": "application", "practice_level": 3},
    Category.PREREQUISITE_CONCEPT_CHECK: {"flow_step": 7,  "item_type": "recall",      "practice_level": 2},
    Category.ADAPTIVE_TEST:              {"flow_step": 8,  "item_type": "application", "practice_level": 4},
    Category.MASTERY_CHECK:              {"flow_step": 9,  "item_type": "application", "practice_level": 4},
    Category.MASTERY_REVERIFICATION:     {"flow_step": 11, "item_type": "transfer",    "practice_level": 5},
}

# The two categories Agent 4's prompt cannot produce, for the reason in the
# module docstring. Everything else is classified out of what it already wrote.
GENERATED_CATEGORIES = (Category.PREREQUISITE, Category.PREREQUISITE_CONCEPT_CHECK)

# Assessment types Agent 4 emits that the ERP renders as an option grid.
_OPTION_TYPES = {"MCQ", "Assertion Reason"}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _load_context(extraction_id: int) -> Dict[str, Any]:
    """Chapter identity, its concepts, and the semantic intelligence for each."""
    with SessionLocal() as db:
        chapter = db.execute(
            text("""SELECT cm.id AS chapter_id, cm.chapter_name, cm.standard_id, cm.subject_id,
                           cm.sub_institute_id, cm.syear
                      FROM chapter_master cm WHERE cm.extraction_id = :e"""),
            {"e": extraction_id},
        ).mappings().fetchone()
        if not chapter:
            raise ValueError(f"No chapter_master for extraction {extraction_id}")

        doc = db.execute(
            text("""SELECT subject_name, standard, full_intelegance_json, assessment_rubrics
                      FROM semantic_intelligence WHERE extraction_id = :e"""),
            {"e": extraction_id},
        ).mappings().fetchone()
        if not doc:
            raise ValueError(
                f"No semantic_intelligence for extraction {extraction_id}. Run the Semantic "
                f"Intelligence pipeline first -- its Agent 4 IS the question generator."
            )

        concept_rows = [dict(r) for r in db.execute(
            text("""SELECT c.id AS concept_id, c.name, c.description, c.topic_id,
                           c.mastery_threshold, t.name AS topic_name, t.topic_sort_order
                      FROM lms_concept c
                 LEFT JOIN topic_master t ON t.id = c.topic_id
                     WHERE c.extraction_id = :e
                  ORDER BY COALESCE(t.topic_sort_order, 0), c.id"""),
            {"e": extraction_id},
        ).mappings().fetchall()]
        if not concept_rows:
            raise ValueError(f"No lms_concept rows for extraction {extraction_id}")

        grade = db.execute(
            text("""SELECT grade_id FROM lms_question_master
                     WHERE standard_id = :s AND grade_id IS NOT NULL
                  GROUP BY grade_id ORDER BY COUNT(*) DESC LIMIT 1"""),
            {"s": chapter["standard_id"]},
        ).fetchone()

    def _load(raw: Any, label: str) -> Any:
        try:
            return json.loads(raw or "null")
        except json.JSONDecodeError as exc:
            raise ValueError(f"semantic_intelligence.{label} is not valid JSON: {exc}")

    payload = _load(doc["full_intelegance_json"], "full_intelegance_json") or {}
    rubrics = _load(doc["assessment_rubrics"], "assessment_rubrics") or []

    intel_by_key = {}
    for block in payload.get("concepts", []):
        name = (block.get("concept") or {}).get("concept_name") or ""
        if name:
            intel_by_key.setdefault(ct.match_key(name), block)

    rubric_by_key: Dict[str, List[Dict[str, Any]]] = {}
    for block in rubrics if isinstance(rubrics, list) else []:
        if not isinstance(block, dict):
            continue
        name = block.get("concept_name") or ""
        if name:
            rubric_by_key.setdefault(ct.match_key(name), []).extend(
                [i for i in block.get("items", []) if isinstance(i, dict)]
            )

    concepts = []
    for row in concept_rows:
        key = ct.match_key(row["name"])
        concepts.append({
            **row,
            "intelligence": intel_by_key.get(key, {}),
            "rubric_items": rubric_by_key.get(key, []),
        })

    return {
        "chapter": dict(chapter),
        "subject_name": doc["subject_name"],
        "standard": doc["standard"],
        "grade_id": grade[0] if grade else None,
        "concepts": concepts,
    }


def _dimension(block: Dict[str, Any], key: str) -> List[Any]:
    value = block.get(key)
    return value if isinstance(value, list) else []


def _prerequisites(concept: Dict[str, Any]) -> List[Dict[str, str]]:
    out = []
    for p in _dimension(concept["intelligence"], "prerequisites"):
        name = (p.get("concept_name") or "").strip()
        if name:
            out.append({
                "concept_name": name,
                "prerequisite_type": (p.get("prerequisite_type") or "").strip(),
                "necessity": (p.get("necessity") or "").strip(),
            })
    return out[:6]


def _misconceptions(concept: Dict[str, Any]) -> List[str]:
    out = []
    for m in _dimension(concept["intelligence"], "misconceptions"):
        statement = (m.get("misconception") or m.get("statement") or "").strip()
        if statement:
            out.append(statement)
    return out


# ---------------------------------------------------------------------------
# Classifying Agent 4's items into the learning-flow categories
# ---------------------------------------------------------------------------

def classify(item: Dict[str, Any]) -> str:
    """Which step of the learning journey an existing Agent 4 item serves.

    Read off the item's own metadata -- what it assesses, how hard, at which
    Bloom/DOK level, and whether its distractors were built on a misconception.
    Priority order matters: an item whose distractors name a misconception is a
    misconception probe first and anything else second.
    """
    a_type = str(item.get("assessment_type") or "")
    difficulty = str(item.get("difficulty") or "Medium")
    bloom = str(item.get("bloom_level") or "Understand")
    rubric = str(item.get("rubric_type") or "")
    dok = ct.safe_int(item.get("dok_level"), 2) or 2
    has_options = bool(item.get("answer_key"))
    targets_misconception = any(
        (o or {}).get("misconception_tested") for o in (item.get("answer_key") or [])
    )

    if targets_misconception:
        return Category.MISCONCEPTION_DETECTION
    # Stretch items are claimed BEFORE the mastery rules. Ordered the other way
    # round, "Hard" was swallowed by mastery_check and adaptive practice ended
    # up with nothing, because every hard item is also a plausible mastery task.
    if a_type == "HOTS" or (difficulty == "Hard" and bloom in ("Apply", "Analyze")):
        return Category.ADAPTIVE_TEST
    # Transfer into a fresh scenario is what re-verification needs: the learner
    # cannot pass it by recalling the original mastery task.
    if a_type in ("Case Study", "Competency Based Question") and dok >= 3:
        return Category.MASTERY_REVERIFICATION
    if bloom in ("Evaluate", "Create") or rubric == "levels_of_response":
        return Category.MASTERY_CHECK
    if difficulty == "Hard":
        return Category.ADAPTIVE_TEST
    if has_options and difficulty == "Easy" and dok <= 1:
        return Category.ADAPTIVE_DIAGNOSTIC
    if has_options:
        return Category.CONCEPT_DIAGNOSTIC
    return Category.CONCEPT_UNDERSTANDING


# A learning-flow step with one question cannot do its job: an adaptive
# diagnostic that owns a single item cannot place a learner across 32 concepts.
# Classification alone does not produce a usable spread, because the strongest
# signal wins every time -- 21 of this chapter's 32 easy option-grid items carry
# a misconception tag, so misconception_detection claimed nearly all of them and
# the two diagnostic steps starved.
_CATEGORY_FLOOR = {
    Category.ADAPTIVE_DIAGNOSTIC: 6,
    Category.CONCEPT_DIAGNOSTIC: 6,
    Category.CONCEPT_UNDERSTANDING: 6,
    Category.ADAPTIVE_TEST: 6,
    Category.MASTERY_CHECK: 6,
}


def _fits(item: Dict[str, Any], category: str) -> bool:
    """Whether an item could honestly serve `category` as its secondary role.

    Reassignment is only allowed where the item genuinely has the shape the
    step needs -- an easy, quick option grid really is a placement item whether
    or not its distractors also happen to probe a misconception.
    """
    has_options = bool(item.get("answer_key")) and item.get("assessment_type") in _OPTION_TYPES
    difficulty = str(item.get("difficulty") or "Medium")
    rubric = str(item.get("rubric_type") or "")
    if category == Category.ADAPTIVE_DIAGNOSTIC:
        return has_options and difficulty == "Easy"
    if category == Category.CONCEPT_DIAGNOSTIC:
        return has_options
    if category == Category.CONCEPT_UNDERSTANDING:
        return difficulty in ("Easy", "Medium")
    if category == Category.ADAPTIVE_TEST:
        return difficulty == "Hard" or item.get("assessment_type") == "HOTS"
    if category == Category.MASTERY_CHECK:
        return rubric in ("levels_of_response", "point_based")
    return False


def rebalance(reused: List[Dict[str, Any]]) -> Dict[str, int]:
    """Lift starved categories to their floor by reassigning surplus items.

    Only ever takes from the category with the most items, and only an item that
    `_fits` the destination, so nothing is relabelled into a role it cannot play.
    Returns how many items each category gained.
    """
    counts = Counter(entry["category"] for entry in reused)
    moved: Dict[str, int] = {}

    for category, floor in _CATEGORY_FLOOR.items():
        while counts[category] < floor:
            donors = [c for c, n in counts.items()
                      if c != category and n > max(_CATEGORY_FLOOR.get(c, 0), floor)]
            if not donors:
                break
            donor = max(donors, key=lambda c: counts[c])
            candidate = next(
                (e for e in reused
                 if e["category"] == donor and _fits(e["item"], category)),
                None,
            )
            if candidate is None:
                # Nothing in the biggest donor fits; try any other donor before
                # giving up on this floor entirely.
                candidate = next(
                    (e for e in reused
                     if e["category"] in donors and _fits(e["item"], category)),
                    None,
                )
                if candidate is None:
                    break
                donor = candidate["category"]
            candidate["category"] = category
            counts[donor] -= 1
            counts[category] += 1
            moved[category] = moved.get(category, 0) + 1

    return moved


# ---------------------------------------------------------------------------
# Selection: every concept covered, no concept hogging the quota
# ---------------------------------------------------------------------------

def select(concepts: List[Dict[str, Any]], total: int,
           prereq_share: float = 0.15) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Choose which existing items to publish and how many prerequisites to write.

    Returns (reused, prereq_plan). Concepts are dealt round-robin rather than
    drained one at a time, so the quota spreads across the chapter instead of
    being consumed by the first few concepts -- and every concept that has any
    item at all contributes before any concept contributes a second.
    """
    if total < len(concepts):
        raise ValueError(
            f"Cannot cover {len(concepts)} concepts with only {total} questions; "
            f"every concept must get at least one."
        )

    # Prerequisite slots go to the concepts that actually have prerequisites
    # extracted; asking for one where none exists would mean inventing it.
    eligible = [c for c in concepts if _prerequisites(c)]
    wanted_prereq = min(len(eligible) * 2, max(0, round(total * prereq_share)))

    pool: Dict[int, List[Dict[str, Any]]] = {}
    for concept in concepts:
        ranked = sorted(
            concept["rubric_items"],
            # Grounded items first; then the cheapest-to-mark; then by depth, so
            # a concept's first contribution is its most reliable item.
            key=lambda i: (not i.get("evidence_verified"),
                           0 if i.get("answer_key") else 1,
                           -(ct.safe_int(i.get("dok_level"), 2) or 2)),
        )
        if ranked:
            pool[concept["concept_id"]] = ranked

    reuse_target = total - wanted_prereq
    reused: List[Dict[str, Any]] = []
    cursor = 0
    # Round-robin over concepts until the reuse target is met or the pool dries up.
    while len(reused) < reuse_target and any(pool.values()):
        progressed = False
        for concept in concepts:
            if len(reused) >= reuse_target:
                break
            items = pool.get(concept["concept_id"])
            if not items:
                continue
            item = items.pop(0)
            reused.append({"concept": concept, "item": item, "category": classify(item)})
            progressed = True
        if not progressed:
            break
        cursor += 1

    # Anything the rubric pool could not fill becomes extra prerequisite work,
    # so the requested total is still met exactly.
    shortfall = total - len(reused) - wanted_prereq
    if shortfall > 0 and eligible:
        wanted_prereq += shortfall

    prereq_plan: List[Dict[str, Any]] = []
    if wanted_prereq and eligible:
        # Both prerequisite categories must appear, so the slots alternate
        # rather than filling the up-front gate first: with 15 slots over 26
        # eligible concepts, a fill-then-overflow scheme never reaches the
        # second category at all.
        gate = round(wanted_prereq * 0.6)
        for position in range(min(wanted_prereq, len(eligible) * 2)):
            concept = eligible[position % len(eligible)]
            prereq_plan.append({
                "concept": concept,
                # The gate is asked before teaching; the re-check is the same
                # prerequisite revisited after an understanding check failed.
                "category": (Category.PREREQUISITE if position < gate
                             else Category.PREREQUISITE_CONCEPT_CHECK),
                "prerequisites": _prerequisites(concept),
            })

    return reused, prereq_plan


# ---------------------------------------------------------------------------
# Prerequisite generation (the two categories Agent 4 cannot produce)
# ---------------------------------------------------------------------------

_PREREQ_SYSTEM = (
    "You are a CBSE assessment item writer. Return ONLY a valid JSON object, "
    "with no markdown fence, no preamble and no trailing commentary."
)

_PREREQ_PROMPT = """You write PREREQUISITE check questions for a Personalised Adaptive Learning system.

A prerequisite question tests the PRIOR knowledge a learner must already have BEFORE a new
concept can be taught. It is deliberately NOT a question about the new concept itself: a
learner who has never studied the new concept, but who holds the prior knowledge, must be
able to answer it correctly.

Board: CBSE
Standard / Class: {standard}
Subject: {subject_name}
Chapter: {chapter_name}

WHAT EACH CATEGORY IS FOR
- prerequisite (learning-flow step 1): the gate asked BEFORE teaching begins. If the learner
  fails it, the prerequisite must be taught first.
- prerequisite_concept_check (learning-flow step 7): asked AFTER a learner has failed an
  understanding check on the new concept, to find out whether the real cause is the missing
  prerequisite rather than the new concept.

ITEMS TO WRITE ({total} in total)

Write EXACTLY these items, in this order, echoing `ref` verbatim:

{order_block}

RULES
1. Return exactly {total} items, one per `ref`.
2. Every item is a four-option MCQ: options labelled A, B, C, D, exactly ONE is_correct=true.
3. The question must test the named PREREQUISITE, not the target concept. Do not mention or
   require the target concept to answer it.
4. Keep it to knowledge a learner would have from an earlier class or an earlier chapter.
5. Every incorrect option needs a `rationale` saying why a learner would plausibly pick it.
6. `remediation` says what to reteach when the learner gets it wrong -- name the prerequisite.
7. `hint_text` nudges without giving the answer away.
8. Age-appropriate vocabulary for Class {standard}. Write in English.
9. Do not write two items that test the same thing.
10. Output ONLY the JSON object.

Return this exact shape:
{{
  "items": [
    {{
      "ref": "the ref given above",
      "question": "the full question text",
      "prerequisite_tested": "the exact prerequisite name given for this ref",
      "bloom_level": "Remember",
      "dok_level": 1,
      "difficulty": "Easy",
      "estimated_time_seconds": 45,
      "options": [
        {{"label": "A", "text": "...", "is_correct": true, "rationale": "..."}}
      ],
      "correct_option": "A",
      "explanation": "why the correct answer is correct",
      "remediation": "what prior knowledge to reteach on failure",
      "hint_text": "a nudge"
    }}
  ]
}}
"""


def _prereq_order(entries: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Dict[str, Any]]]:
    lines: List[str] = []
    index: Dict[str, Dict[str, Any]] = {}
    for position, entry in enumerate(entries, start=1):
        concept = entry["concept"]
        prereq = entry["prerequisites"][0] if entry["prerequisites"] else {}
        ref = f"P{concept['concept_id']}-{position}"
        detail = ", ".join(x for x in (prereq.get("prerequisite_type"), prereq.get("necessity")) if x)
        lines.append(
            f'- ref "{ref}" | category {entry["category"]} '
            f'| prerequisite to test: "{prereq.get("concept_name", "")}"'
            + (f" ({detail})" if detail else "")
            + f' | it is needed before the concept "{concept["name"]}"'
        )
        index[ref] = entry
    return "\n".join(lines), index


def _authored_prerequisites(extraction_id: int) -> Dict[int, List[Dict[str, Any]]]:
    """Hand-authored prerequisite items for a chapter, keyed by concept id.

    Prerequisites are the only items this module cannot take from Agent 4, so they
    are the only ones that would otherwise cost an LLM call. Anything found here is
    used in place of that call, which is what lets a whole chapter be published
    without reaching a provider at all.
    """
    try:
        with AUTHORED_PREREQ_PATH.open(encoding="utf-8") as handle:
            doc = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Authored prerequisite bank unreadable (%s); falling back to the LLM", exc)
        return {}

    chapter = doc.get(str(extraction_id))
    if not isinstance(chapter, dict):
        return {}

    out: Dict[int, List[Dict[str, Any]]] = {}
    for concept_id, items in chapter.items():
        if not str(concept_id).isdigit() or not isinstance(items, list):
            continue
        usable = [item for item in items if isinstance(item, dict)]
        if usable:
            out[int(concept_id)] = usable
    return out


def _take_authored(plan: List[Dict[str, Any]], authored: Dict[int, List[Dict[str, Any]]],
                   batch_id: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    """Build every planned prerequisite that has an authored item waiting for it.

    Returns (questions, still_to_generate, unusable). An authored item that
    `_build_prereq_row` rejects is reported rather than silently swallowed, and its
    slot goes back to the LLM so the chapter still reaches the requested total.
    """
    remaining = {concept_id: list(items) for concept_id, items in authored.items()}
    built: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []
    unusable: List[str] = []

    for entry in plan:
        concept_id = entry["concept"]["concept_id"]
        queue = remaining.get(concept_id)
        if not queue:
            pending.append(entry)
            continue
        row = _build_prereq_row(queue.pop(0), entry, batch_id, (0, 0), authored=True)
        if row is None:
            unusable.append(f'authored item for concept {concept_id} ({entry["category"]})')
            pending.append(entry)
        else:
            built.append(row)

    return built, pending, unusable


async def _generate_prereq(entries: List[Dict[str, Any]], context: Dict[str, Any],
                           batch_id: str) -> Dict[str, Any]:
    order, index = _prereq_order(entries)
    prompt = _PREREQ_PROMPT.format(
        standard=context["standard"],
        subject_name=context["subject_name"],
        chapter_name=context["chapter"]["chapter_name"],
        order_block=order,
        total=len(entries),
    )
    result = await async_call_deepseek(
        prompt, system_prompt=_PREREQ_SYSTEM, response_format={"type": "json_object"}
    )
    data = result.get("data")
    data = data if isinstance(data, dict) else {}
    tokens = (result.get("input_tokens", 0), result.get("output_tokens", 0))

    raw_items = data.get("items")
    raw_items = raw_items if isinstance(raw_items, list) else []
    by_ref = {}
    for raw in raw_items:
        if isinstance(raw, dict):
            ref = _clean(raw.get("ref"))
            if ref in index and ref not in by_ref:
                by_ref[ref] = raw

    built: List[Dict[str, Any]] = []
    missing: List[str] = []
    for position, (ref, entry) in enumerate(index.items()):
        raw = by_ref.get(ref)
        if raw is None and len(raw_items) == len(index) and isinstance(raw_items[position], dict):
            raw = raw_items[position]
        row = _build_prereq_row(raw, entry, batch_id, tokens) if raw else None
        if row is None:
            missing.append(ref)
        else:
            built.append(row)

    return {"questions": built, "missing": missing,
            "input_tokens": tokens[0], "output_tokens": tokens[1]}


# ---------------------------------------------------------------------------
# Row building
# ---------------------------------------------------------------------------

_BLOOMS = {"remember", "understand", "apply", "analyze", "analyse", "evaluate", "create"}
_DIFFICULTY = {"easy": "Easy", "medium": "Medium", "hard": "Hard"}


def _clean(value: Any, limit: int | None = None) -> str:
    out = " ".join(str(value or "").split())
    return out[:limit] if limit else out


def _str_list(value: Any, limit: int = 8) -> List[str]:
    if not isinstance(value, list):
        return []
    return [_clean(v) for v in value if _clean(v)][:limit]


def _semantic_key(name: str, concept_id: int) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()[:40] or "CONCEPT"
    return f"{slug}_{concept_id:04d}"


def _content_hash(question: str, options: List[Dict[str, Any]]) -> str:
    basis = _clean(question).lower()
    if options:
        basis += "||" + "|".join(sorted(_clean(o.get("text")).lower() for o in options))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _base_answer(question_type: str, sub_type: str, bloom: str, dok: int, difficulty: str,
                 concept: Dict[str, Any], category: str, seconds: int) -> Dict[str, Any]:
    spec = CATEGORY_SPEC[category]
    return {
        "v": ANSWER_SCHEMA_VERSION,
        "question_type": question_type,
        "sub_type": sub_type,
        "bloom_level": bloom,
        "dok_level": dok,
        "difficulty": difficulty,
        "estimated_time_seconds": seconds,
        "semantic_concept_key": _semantic_key(concept["name"], concept["concept_id"]),
        "pedagogical_stage": category,
        "flow_step": spec["flow_step"],
        "times_served": 0,
        "times_correct": 0,
        "p_value": None,
        "discrimination": None,
    }


def _row(concept: Dict[str, Any], category: str, question: str, question_type_id: int,
         points: int, answer: Dict[str, Any], subconcept: str, hint: str,
         outcome: str | None, options: List[Dict[str, Any]]) -> Dict[str, Any]:
    answer["content_hash"] = _content_hash(question, options)
    return {
        "category": category,
        "concept_id": concept["concept_id"],
        "topic_id": concept["topic_id"],
        "concept_name": concept["name"],
        "question_type_id": question_type_id,
        "question_title": question,
        "points": max(1, points),
        "subconcept": _clean(subconcept, 250) or concept["name"][:250],
        "hint_text": _clean(hint),
        "learning_outcome": json.dumps([outcome], ensure_ascii=False) if outcome else None,
        "answer": answer,
        "bloom": answer["bloom_level"],
        "difficulty": answer["difficulty"],
        "dok": answer["dok_level"],
    }


def _build_reuse_row(concept: Dict[str, Any], item: Dict[str, Any],
                     category: str) -> Dict[str, Any] | None:
    """Republish one Agent 4 item as a question-bank row.

    Agent 4's mark scheme shapes are carried across intact: answer_key becomes
    the option grid, acceptable_points becomes the marking scheme, and
    indicative_content plus the official band descriptors travel with extended
    responses so nothing that was generated is thrown away.
    """
    question = _clean(item.get("question"))
    if not question:
        return None

    a_type = _clean(item.get("assessment_type")) or "Short Answer"
    bloom = _clean(item.get("bloom_level")) or "Understand"
    if bloom.lower() not in _BLOOMS:
        bloom = "Understand"
    difficulty = _DIFFICULTY.get(_clean(item.get("difficulty")).lower(), "Medium")
    dok = min(4, max(1, ct.safe_int(item.get("dok_level"), 2) or 2))
    marks = max(1, ct.safe_int(item.get("marks"), 1) or 1)
    is_options = a_type in _OPTION_TYPES and bool(item.get("answer_key"))

    options: List[Dict[str, Any]] = []
    correct = None
    if is_options:
        for position, raw in enumerate(item.get("answer_key") or []):
            if not isinstance(raw, dict):
                continue
            body = _clean(raw.get("option_text"))
            if not body:
                continue
            misconception = _clean(raw.get("misconception_tested")) or None
            options.append({
                "label": _clean(raw.get("option_label")) or "ABCD"[position % 4],
                "text": body,
                "is_correct": bool(raw.get("is_correct")),
                "distractor_type": ("correct" if raw.get("is_correct")
                                    else ("misconception" if misconception else "plausible")),
                "misconception_ref": misconception,
                "knowledge_ref": None,
                "rationale": _clean(raw.get("rationale")),
            })
        chosen = [o for o in options if o["is_correct"]]
        # An option grid the ERP cannot auto-mark is worse than a free-text
        # item, so a malformed key falls back to narrative rather than dropping
        # an item Agent 4 already paid to produce.
        if len(options) < 2 or len(chosen) != 1:
            is_options, options, correct = False, [], None
        else:
            correct = chosen[0]["label"]
            marks = max(1, marks)

    answer = _base_answer(
        "mcq" if is_options else "narrative", a_type, bloom, dok, difficulty,
        concept, category, 60 if is_options else 60 * max(1, marks),
    )
    answer.update({
        "competency_ref": None,
        "stimulus": None,
        "skill_phrase": _clean(item.get("skill_phrase")),
        "assessment_objectives": _str_list(item.get("assessment_objectives"), 6),
        "source_evidence": _str_list(item.get("source_evidence"), 4),
        "evidence_verified": bool(item.get("evidence_verified")),
        "common_errors": _str_list(item.get("common_errors"), 6),
        "threshold_conditions": _str_list(item.get("threshold_conditions"), 4),
        "misconception_refs": sorted({o["misconception_ref"] for o in options
                                      if o.get("misconception_ref")}),
        "knowledge_refs": _str_list(item.get("source_evidence"), 3),
        "ability_ref": _clean(item.get("skill_phrase")) or None,
        "explanation": "",
        "remediation": "",
        "generation_meta": {
            "model": settings.active_llm_model,
            "prompt_version": "agent4",
            "source": REUSE_SOURCE,
            "origin_item_id": _clean(item.get("item_id")),
            "reused": True,
        },
    })

    if is_options:
        answer["options"] = options
        answer["correct_option"] = correct
        rationale = next((o["rationale"] for o in options if o["is_correct"]), "")
        answer["explanation"] = rationale
        answer["remediation"] = "; ".join(answer["common_errors"][:2])
    else:
        points_list = item.get("acceptable_points") or []
        marking = []
        for raw in points_list:
            if not isinstance(raw, dict):
                continue
            criterion = _clean(raw.get("point") or raw.get("criterion"))
            if not criterion:
                continue
            marking.append({
                "mark": max(1, ct.safe_int(raw.get("marks"), 1) or 1),
                "criterion": criterion,
                "accept": _str_list(raw.get("alternatives") or raw.get("accept"), 6),
                "reject": _str_list(raw.get("reject"), 4),
                "knowledge_ref": None,
            })
        if marking:
            ct.normalise_minutes(marking, "mark", marks)
        answer["marking_points"] = marking
        # The question bank only paints an answer body when model_answer is a
        # non-empty STRING, so fall through every shape Agent 4 might have used:
        # a point-based scheme, indicative content, or -- for an extended item
        # carrying neither -- the top mark band, which describes what a full
        # credit answer looks like. Without this an item with only band
        # descriptors renders as a question with no answer at all.
        bands = item.get("level_descriptors") or []
        top_band = ""
        if isinstance(bands, list) and bands:
            best = bands[0] if isinstance(bands[0], dict) else {}
            for band in bands:
                if isinstance(band, dict) and ct.safe_int(band.get("max_marks"), 0) >= ct.safe_int(
                        best.get("max_marks"), 0):
                    best = band
            top_band = _clean(best.get("descriptor") or best.get("description"))
        answer["model_answer"] = (
            " ".join(m["criterion"] for m in marking)
            or _clean(" ".join(_str_list(item.get("indicative_content"), 6)))
            or top_band
            or _clean(" ".join(_str_list(item.get("threshold_conditions"), 3)))
            or f"A full-credit response demonstrates {_clean(item.get('skill_phrase')) or concept['name']}."
        )
        answer["indicative_content"] = _str_list(item.get("indicative_content"), 8)
        answer["level_descriptors"] = item.get("level_descriptors") or []
        answer["criteria"] = item.get("criteria") or []
        answer["full_credit_threshold"] = marks
        answer["remediation"] = "; ".join(answer["common_errors"][:2])
        answer["explanation"] = answer["model_answer"][:600]

    return _row(
        concept, category, question, QT_MULTIPLE if is_options else QT_NARRATIVE, marks,
        answer, _clean(item.get("skill_phrase")) or concept["name"],
        "", None, options,
    )


def _build_prereq_row(raw: Dict[str, Any], entry: Dict[str, Any], batch_id: str,
                      tokens: Tuple[int, int],
                      authored: bool = False) -> Dict[str, Any] | None:
    concept = entry["concept"]
    category = entry["category"]
    question = _clean(raw.get("question"))
    if not question:
        return None

    options: List[Dict[str, Any]] = []
    for position, opt in enumerate((raw.get("options") or [])[:4]):
        if not isinstance(opt, dict):
            continue
        body = _clean(opt.get("text"))
        if not body:
            continue
        options.append({
            "label": _clean(opt.get("label")) or "ABCD"[position],
            "text": body,
            "is_correct": bool(opt.get("is_correct")),
            "distractor_type": "correct" if opt.get("is_correct") else "plausible",
            "misconception_ref": None,
            "knowledge_ref": None,
            "rationale": _clean(opt.get("rationale")),
        })
    chosen = [o for o in options if o["is_correct"]]
    if len(options) != 4 or len(chosen) != 1:
        return None

    bloom = _clean(raw.get("bloom_level")) or "Remember"
    if bloom.lower() not in _BLOOMS:
        bloom = "Remember"
    difficulty = _DIFFICULTY.get(_clean(raw.get("difficulty")).lower(), "Easy")
    dok = min(4, max(1, ct.safe_int(raw.get("dok_level"), 1) or 1))
    prerequisite = _clean(raw.get("prerequisite_tested")) or (
        entry["prerequisites"][0]["concept_name"] if entry["prerequisites"] else ""
    )

    answer = _base_answer("mcq", "MCQ", bloom, dok, difficulty, concept, category,
                          max(20, ct.safe_int(raw.get("estimated_time_seconds"), 45) or 45))
    answer.update({
        "competency_ref": None,
        "stimulus": None,
        "options": options,
        "correct_option": chosen[0]["label"],
        "explanation": _clean(raw.get("explanation")),
        "remediation": _clean(raw.get("remediation")),
        "knowledge_refs": [],
        "ability_ref": None,
        "misconception_refs": [],
        "prerequisite_ref": prerequisite,
        "assessment_objectives": [],
        "source_evidence": [],
        "evidence_verified": False,
        "generation_meta": {
            "model": PREREQ_AUTHORED_MODEL if authored else settings.active_llm_model,
            "temperature": None if authored else 0.2,
            "prompt_version": PREREQ_AUTHORED_VERSION if authored else PREREQ_PROMPT_VERSION,
            "batch_id": batch_id,
            "source": PREREQ_AUTHORED_SOURCE if authored else "semantic_intelligence.prerequisites",
            "reused": False,
            "input_tokens": tokens[0],
            "output_tokens": tokens[1],
        },
    })

    return _row(concept, category, question, QT_MULTIPLE, 1, answer,
                prerequisite or concept["name"], _clean(raw.get("hint_text")), None, options)


def _dedupe(questions: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    seen: set[str] = set()
    kept: List[Dict[str, Any]] = []
    dropped = 0
    for question in questions:
        digest = question["answer"]["content_hash"]
        if digest in seen:
            dropped += 1
            continue
        seen.add(digest)
        kept.append(question)
    return kept, dropped


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

_INSERT_QUESTION = text("""
    INSERT INTO lms_question_master (
        question_type_id, grade_id, standard_id, subject_id, chapter_id, concept_id, topic_id,
        question_title, description, points, multiple_answer, concept, subconcept, category,
        sub_institute_id, status, created_by, created_on, answer,
        g_bloom, g_difficulty, g_dok, g_content_hash, hint_text, learning_outcome
    ) VALUES (
        :question_type_id, :grade_id, :standard_id, :subject_id, :chapter_id, :concept_id, :topic_id,
        :question_title, :description, :points, 0, :concept, :subconcept, :category,
        :sub_institute_id, 1, :created_by, CURRENT_TIMESTAMP, :answer,
        :g_bloom, :g_difficulty, :g_dok, :g_content_hash, :hint_text, :learning_outcome
    )
""")

_INSERT_PAL = text("""
    INSERT INTO pal_question_metadata (
        question_id, sub_institute_id, scope, concept_ref_id, chapter_ref_id, topic_ref_id,
        sub_concept_ref, stage, bloom_level, practice_level, item_type, difficulty_1_to_5,
        response_count, misconception_tags, distractor_rationale, scaffold_type,
        language, quality_status, tagged_by, confidence, sensitivity_flag,
        usage_count, version, ai_rationale, visual_dependency, offline_compatible,
        created_at, updated_at
    ) VALUES (
        :question_id, :sub_institute_id, 'tenant', :concept_ref_id, :chapter_ref_id, :topic_ref_id,
        :sub_concept_ref, :stage, :bloom_level, :practice_level, :item_type, :difficulty_1_to_5,
        0, :misconception_tags, :distractor_rationale, :scaffold_type,
        'en', 'draft', 'ai', :confidence, 0,
        0, '1.0', :ai_rationale, 0, 1,
        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
    )
""")

_INSERT_ANSWER_OPTION = text("""
    INSERT INTO answer_master (
        question_id, answer, feedback, correct_answer, sub_institute_id, created_by, created_on
    ) VALUES (
        :question_id, :answer, :feedback, :correct_answer, :sub_institute_id, :created_by,
        CURRENT_TIMESTAMP
    )
""")

_DIFFICULTY_1_TO_5 = {"Easy": 1, "Medium": 3, "Hard": 5}
_PAL_BLOOM = {"remember": "recall", "understand": "understand", "apply": "apply",
              "analyze": "analyze", "analyse": "analyze", "evaluate": "evaluate",
              "create": "create"}


def _describe(question: Dict[str, Any]) -> str:
    """The short label the question bank shows under the stem."""
    answer = question["answer"]
    label = question["category"].replace("_", " ").title()
    bits = [f"{label} | {answer['sub_type']} | {question['bloom']} | DOK {question['dok']}"]
    if answer.get("misconception_refs"):
        bits.append(f"targets: {answer['misconception_refs'][0]}")
    elif answer.get("prerequisite_ref"):
        bits.append(f"prerequisite: {answer['prerequisite_ref']}")
    elif answer.get("skill_phrase"):
        bits.append(answer["skill_phrase"])
    return _clean(" — ".join(bits), 250)


def _persist(context: Dict[str, Any], questions: List[Dict[str, Any]],
             created_by: int, replace: bool) -> Dict[str, int]:
    chapter = context["chapter"]
    concept_ids = [c["concept_id"] for c in context["concepts"]]

    with SessionLocal() as db:
        deleted = 0
        if replace and concept_ids:
            # Scoped to THIS chapter's concepts, so hand-authored questions that
            # carry no concept_id are never caught by it.
            db.execute(
                text("""DELETE p FROM pal_question_metadata p
                          JOIN lms_question_master q ON q.id = p.question_id
                         WHERE q.chapter_id = :ch AND q.concept_id IN :ids"""),
                {"ch": chapter["chapter_id"], "ids": tuple(concept_ids)},
            )
            # Options are keyed only by question_id, so they must go before the
            # questions do or they are orphaned rows nothing will ever clean up.
            db.execute(
                text("""DELETE a FROM answer_master a
                          JOIN lms_question_master q ON q.id = a.question_id
                         WHERE q.chapter_id = :ch AND q.concept_id IN :ids"""),
                {"ch": chapter["chapter_id"], "ids": tuple(concept_ids)},
            )
            deleted = db.execute(
                text("""DELETE FROM lms_question_master
                         WHERE chapter_id = :ch AND concept_id IN :ids"""),
                {"ch": chapter["chapter_id"], "ids": tuple(concept_ids)},
            ).rowcount

        inserted = 0
        for question in questions:
            answer = question["answer"]
            question_id = db.execute(_INSERT_QUESTION, {
                "question_type_id": question["question_type_id"],
                "grade_id": context["grade_id"],
                "standard_id": chapter["standard_id"],
                "subject_id": chapter["subject_id"],
                "chapter_id": chapter["chapter_id"],
                "concept_id": question["concept_id"],
                "topic_id": question["topic_id"],
                "question_title": question["question_title"],
                "description": _describe(question),
                "points": question["points"],
                "concept": question["concept_name"][:250],
                "subconcept": question["subconcept"],
                # The Question Bank's category dropdown filters on this column, so
                # it lives on the question itself rather than only on the PAL
                # sidecar -- the bank never joins pal_question_metadata.
                "category": question["category"][:48],
                "sub_institute_id": chapter["sub_institute_id"],
                "created_by": created_by,
                "answer": json.dumps(answer, ensure_ascii=False),
                "g_bloom": question["bloom"][:12],
                "g_difficulty": question["difficulty"][:8],
                "g_dok": question["dok"],
                "g_content_hash": answer["content_hash"],
                "hint_text": question["hint_text"] or None,
                "learning_outcome": question["learning_outcome"],
            }).lastrowid

            # The Next.js bank paints options straight from the JSON envelope,
            # but the exam runtime and the legacy edit screen read answer_master,
            # so an MCQ needs its options materialised there too or it renders
            # with no choices outside the new bank. Insertion order IS the A-D
            # order: both readers label the rows by id.
            if question["question_type_id"] == QT_MULTIPLE:
                for option in answer.get("options", []):
                    db.execute(_INSERT_ANSWER_OPTION, {
                        "question_id": question_id,
                        "answer": option["text"][:250],
                        "feedback": (option.get("rationale") or "")[:250] or None,
                        "correct_answer": 1 if option["is_correct"] else 0,
                        "sub_institute_id": chapter["sub_institute_id"],
                        "created_by": created_by,
                    })

            misconceptions = answer.get("misconception_refs") or []
            rationales = [
                {"label": o["label"], "distractor_type": o["distractor_type"],
                 "misconception_ref": o["misconception_ref"], "rationale": o["rationale"]}
                for o in answer.get("options", []) if not o["is_correct"]
            ]
            spec = CATEGORY_SPEC[question["category"]]
            # Every longtext column here carries a json_valid() CHECK constraint,
            # so a bare sentence is rejected -- ai_rationale must be JSON too.
            rationale_doc = {
                "remediation": answer.get("remediation") or None,
                "category": question["category"],
                "flow_step": spec["flow_step"],
                "source": answer["generation_meta"].get("source"),
            }
            db.execute(_INSERT_PAL, {
                "question_id": question_id,
                "sub_institute_id": chapter["sub_institute_id"],
                "concept_ref_id": question["concept_id"],
                "chapter_ref_id": chapter["chapter_id"],
                "topic_ref_id": question["topic_id"],
                "sub_concept_ref": question["subconcept"][:191],
                "stage": question["category"][:32],
                "bloom_level": _PAL_BLOOM.get(question["bloom"].lower(), "understand")[:16],
                "practice_level": spec["practice_level"],
                "item_type": spec["item_type"][:16],
                "difficulty_1_to_5": _DIFFICULTY_1_TO_5.get(question["difficulty"], 3),
                "misconception_tags": json.dumps(misconceptions, ensure_ascii=False) if misconceptions else None,
                "distractor_rationale": json.dumps(rationales, ensure_ascii=False) if rationales else None,
                "scaffold_type": "hint_available" if question["hint_text"] else "none",
                "confidence": 0.8,
                "ai_rationale": json.dumps(rationale_doc, ensure_ascii=False),
            })
            question["question_id"] = question_id
            inserted += 1

        db.commit()
        return {"inserted": inserted, "deleted": deleted}


async def _persist_with_retry(write, extraction_id: int) -> Dict[str, int]:
    last_error: OperationalError | None = None
    for attempt in range(_PERSIST_ATTEMPTS):
        try:
            return await asyncio.to_thread(write)
        except OperationalError as exc:
            last_error = exc
            if attempt == _PERSIST_ATTEMPTS - 1:
                break
            delay = _PERSIST_BACKOFF_SEC * (2 ** attempt)
            logger.warning("Question persistence attempt %s/%s for extraction %s failed (%s); "
                           "retrying in %ss", attempt + 1, _PERSIST_ATTEMPTS, extraction_id,
                           exc.orig, delay)
            await asyncio.sleep(delay)
    raise RuntimeError(
        f"Questions for extraction {extraction_id} were generated but could not be saved "
        f"after {_PERSIST_ATTEMPTS} attempts. Last error: {last_error}"
    ) from last_error


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_questions_by_extraction(
    extraction_id: int,
    total: int = 100,
    created_by: int = 0,
    replace: bool = False,
    concurrency: int = MAX_CONCURRENCY,
) -> Dict[str, Any]:
    """Publish `total` questions for a chapter into the question bank."""
    context = _load_context(extraction_id)
    concepts = context["concepts"]

    reused, prereq_plan = select(concepts, total)
    rebalanced = rebalance(reused)
    batch_id = str(uuid.uuid4())

    questions: List[Dict[str, Any]] = []
    skipped_reuse = 0
    for entry in reused:
        row = _build_reuse_row(entry["concept"], entry["item"], entry["category"])
        if row is None:
            skipped_reuse += 1
            continue
        questions.append(row)

    # Prerequisites are the only items that can cost an LLM call. Hand-authored
    # ones are taken first, so a chapter whose bank is complete is published
    # without contacting a provider at all.
    authored_rows, pending_prereq, unusable_authored = _take_authored(
        prereq_plan, _authored_prerequisites(extraction_id), batch_id
    )
    questions.extend(authored_rows)

    batches = [pending_prereq[i:i + MAX_PREREQ_PER_CALL]
               for i in range(0, len(pending_prereq), MAX_PREREQ_PER_CALL)]
    semaphore = asyncio.Semaphore(max(1, concurrency))
    tokens_in = tokens_out = 0
    missing: List[str] = list(unusable_authored)

    async def run(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        async with semaphore:
            try:
                return await _generate_prereq(entries, context, batch_id)
            except Exception as exc:
                logger.exception("Prerequisite batch failed")
                return {"questions": [], "missing": [f"batch: {exc}"],
                        "input_tokens": 0, "output_tokens": 0}

    if batches:
        for result in await asyncio.gather(*(run(b) for b in batches)):
            questions.extend(result["questions"])
            missing.extend(result["missing"])
            tokens_in += result["input_tokens"]
            tokens_out += result["output_tokens"]

    questions, duplicates = _dedupe(questions)
    if not questions:
        raise RuntimeError(
            f"Question generation produced nothing for extraction {extraction_id}."
        )

    counts = await _persist_with_retry(
        lambda: _persist(context, questions, created_by, replace), extraction_id
    )

    by_category: Dict[str, int] = {}
    by_concept: Dict[int, int] = {}
    for question in questions:
        by_category[question["category"]] = by_category.get(question["category"], 0) + 1
        by_concept[question["concept_id"]] = by_concept.get(question["concept_id"], 0) + 1

    per_concept = sorted(by_concept.values())
    return {
        "status": "success",
        "extraction_id": extraction_id,
        "chapter_id": context["chapter"]["chapter_id"],
        "requested": total,
        "generated": len(questions),
        "reused_from_agent4": sum(1 for q in questions if q["answer"]["generation_meta"].get("reused")),
        "generated_prerequisites": sum(1 for q in questions
                                       if not q["answer"]["generation_meta"].get("reused")),
        "authored_prerequisites": len(authored_rows),
        "unusable_rubric_items": skipped_reuse,
        "duplicates_dropped": duplicates,
        "missing_items": missing,
        "concepts_total": len(concepts),
        "concepts_covered": len(by_concept),
        "uncovered_concepts": [c["name"] for c in concepts if c["concept_id"] not in by_concept],
        "questions_per_concept_min": per_concept[0] if per_concept else 0,
        "questions_per_concept_max": per_concept[-1] if per_concept else 0,
        "by_category": by_category,
        "categories_represented": len(by_category),
        "rebalanced": rebalanced,
        "batch_id": batch_id,
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        **counts,
    }


def get_questions_by_extraction(extraction_id: int) -> Dict[str, Any] | None:
    """The published questions for a chapter, grouped topic -> question."""
    with SessionLocal() as db:
        rows = db.execute(
            text("""
                SELECT q.id, q.question_title, q.question_type_id, q.points, q.concept_id,
                       q.topic_id, q.concept, q.subconcept, q.hint_text, q.answer,
                       q.g_bloom, q.g_difficulty, q.g_dok, q.description, q.category,
                       p.stage, p.item_type, p.practice_level,
                       t.name AS topic_name, t.topic_sort_order
                  FROM lms_question_master q
                  JOIN lms_concept c ON c.id = q.concept_id
             LEFT JOIN pal_question_metadata p ON p.question_id = q.id
             LEFT JOIN topic_master t ON t.id = q.topic_id
                 WHERE c.extraction_id = :e AND q.deleted_at IS NULL
              ORDER BY COALESCE(t.topic_sort_order, 0), q.concept_id, q.id
            """),
            {"e": extraction_id},
        ).mappings().fetchall()

    if not rows:
        return None

    topics: List[Dict[str, Any]] = []
    index: Dict[Any, Dict[str, Any]] = {}
    for row in rows:
        bucket = index.get(row["topic_id"])
        if bucket is None:
            bucket = {"topic_id": row["topic_id"], "topic_name": row["topic_name"], "questions": []}
            index[row["topic_id"]] = bucket
            topics.append(bucket)
        try:
            answer = json.loads(row["answer"]) if row["answer"] else {}
        except json.JSONDecodeError:
            answer = {}
        bucket["questions"].append({
            "question_id": row["id"],
            "concept_id": row["concept_id"],
            "concept": row["concept"],
            "subconcept": row["subconcept"],
            # The question's own column is authoritative; the PAL sidecar is only a
            # fallback for rows written before the column existed, and its LEFT JOIN
            # yields NULL for any question that never got a sidecar row at all.
            "category": row["category"] or row["stage"],
            "flow_step": answer.get("flow_step"),
            "question": row["question_title"],
            "description": row["description"],
            "question_type_id": row["question_type_id"],
            "points": row["points"],
            "bloom": row["g_bloom"],
            "difficulty": row["g_difficulty"],
            "dok": row["g_dok"],
            "hint": row["hint_text"],
            "answer": answer,
        })

    return {"extraction_id": extraction_id, "total_questions": len(rows), "topics": topics}
