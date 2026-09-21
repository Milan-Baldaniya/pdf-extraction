"""Which curricular goals a question is taught against.

The question-side sibling of the concept mapping in `curriculum_frame`, and
deliberately the same shape: cite codes from a closed per-chapter list, resolve
them against that chapter's frame, store the set in a join table and the
primary one beside it for cheap filtering.

Three decisions worth stating, because each has a cheaper-looking alternative:

  * **A join table, not a column.** A question serves more than one outcome --
    a case-based parent with four sub-parts spans a competency and two learning
    outcomes -- and `lms_concept_outcome` already settled this for concepts.

  * **Codes are the key, not ids.** `save_learning_outcomes()` DELETEs a whole
    curriculum on re-process and rebuilds the tree, so every
    `lms_learning_outcomes.id` changes. `outcome_id` is therefore a cache; the
    durable key is `(curriculum_id, outcome_code)`, and `resync_outcome_ids()`
    is what repairs the cache afterwards.

  * **Unknown codes raise here, where they are dropped for concepts.** Dropping
    is right in the concept fan-out: one bad code among hundreds should not
    fail a chapter. It is wrong when the mapping IS the deliverable, because a
    bank loaded with every citation silently discarded looks exactly like one
    loaded correctly. `persist_question_outcomes` re-raises for the same
    reason, where `persist_mappings` swallows and returns 0.

Deliberately NOT derived by query. A question's concept is already mapped to
outcomes in `lms_concept_outcome`, and joining through it would map every
question in a chapter identically, for free. That is the concept's alignment,
not the question's: a concept typically serves three outcomes and a given
question usually probes one of them. A join cannot tell which; a model reading
the question can. So the mapping is read, per question, and `match_source`
records that it was.

A chapter whose subject has no curriculum recorded is a normal, quiet outcome,
not an error -- several books in the current ingest have none. Those questions
load with their concepts and figures and simply carry no curriculum tag.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List

from sqlalchemy import bindparam, text

from app.services import curriculum_frame as curf

logger = logging.getLogger(__name__)

# The reader is told "usually one, at most three". Same cap as the concept side
# so one vocabulary governs both.
MAX_OUTCOMES_PER_QUESTION = curf._MAX_MAPPINGS_PER_CONCEPT

UnknownOutcomeCode = curf.UnknownOutcomeCode


_UPSERT_QUESTION_OUTCOME = text("""
    INSERT INTO lms_question_outcome
        (question_id, sub_institute_id, outcome_id, outcome_type, outcome_code,
         goal_code, competency_code, curriculum_id, extraction_id, chapter_id,
         match_source, match_score, created_at, updated_at)
    VALUES
        (:question_id, :sub_institute_id, :outcome_id, :outcome_type, :outcome_code,
         :goal_code, :competency_code, :curriculum_id, :extraction_id, :chapter_id,
         :match_source, :match_score, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    ON DUPLICATE KEY UPDATE
        outcome_id      = VALUES(outcome_id),
        outcome_type    = VALUES(outcome_type),
        goal_code       = VALUES(goal_code),
        competency_code = VALUES(competency_code),
        curriculum_id   = VALUES(curriculum_id),
        extraction_id   = VALUES(extraction_id),
        chapter_id      = VALUES(chapter_id),
        match_source    = VALUES(match_source),
        match_score     = VALUES(match_score),
        updated_at      = CURRENT_TIMESTAMP
""")


def resolve_codes(
    frame: curf.CurriculumFrame,
    cited: Any,
    *,
    strict: bool = True,
    match_source: str = "read",
    match_score: float = 1.0,
) -> List[Dict[str, Any]]:
    """Cited codes -> mappings, with goal and competency filled in.

    `sanitise_codes` returns the outcome's own id/code/type; the ancestors come
    off the `Outcome`, which `load_frame` has already denormalised. Storing
    them saves every report walking `parent_id`.

    match_score defaults to 1.0 rather than the concept path's 0.9: a code a
    reader copied off the chapter's own closed list is not a guess.
    """
    mappings = curf.sanitise_codes(
        cited, frame, match_score=match_score, strict=strict, match_source=match_source
    )
    by_code = frame.by_code()
    for mapping in mappings[:MAX_OUTCOMES_PER_QUESTION]:
        outcome = by_code.get(mapping["outcome_code"])
        if outcome is None:
            continue
        mapping["goal_code"] = outcome.goal_code or None
        mapping["competency_code"] = outcome.competency_code or None
    return mappings[:MAX_OUTCOMES_PER_QUESTION]


def persist_question_outcomes(
    db,
    *,
    frame: curf.CurriculumFrame,
    extraction_id: int,
    sub_institute_id: int,
    chapter_id: int | None,
    mappings_by_question_id: Dict[int, List[Dict[str, Any]]],
) -> int:
    """Write question -> outcome links. Replaces each question's set wholesale.

    Scoped per question, like `persist_mappings`, so re-reading one chapter
    cannot wipe another's mappings.

    Unlike `persist_mappings` this does NOT swallow. A concept's curriculum tag
    is a nice-to-have; here it is the deliverable, and a silent zero would look
    like success.
    """
    question_ids = [qid for qid in mappings_by_question_id if qid]
    if not question_ids:
        return 0

    db.execute(
        text("DELETE FROM lms_question_outcome WHERE question_id IN :ids").bindparams(
            bindparam("ids", expanding=True)
        ),
        {"ids": question_ids},
    )

    written = 0
    for question_id, mappings in mappings_by_question_id.items():
        if not question_id:
            continue
        for mapping in mappings:
            db.execute(_UPSERT_QUESTION_OUTCOME, {
                "question_id": question_id,
                "sub_institute_id": sub_institute_id,
                "outcome_id": mapping.get("outcome_id"),
                "outcome_type": mapping.get("outcome_type") or "learning_outcome",
                "outcome_code": mapping.get("outcome_code"),
                "goal_code": mapping.get("goal_code"),
                "competency_code": mapping.get("competency_code"),
                "curriculum_id": frame.curriculum_id,
                "extraction_id": extraction_id,
                "chapter_id": chapter_id,
                "match_source": mapping.get("match_source") or "read",
                "match_score": mapping.get("match_score"),
            })
            written += 1
    return written


def mirror_primary(db, mappings_by_question_id: Dict[int, List[Dict[str, Any]]]) -> int:
    """Copy the first mapping onto the sidecar and the question row.

    The same trick `question_ai_tagger` plays with `concept_id`: the truth is
    in the join table, but the bank filters on a plain column and should not
    have to join to do it. `g_lo_code`/`g_cg_code` are CODES because the ids
    churn; see the module docstring.

    "First" is the highest-scoring mapping, and ties keep citation order -- the
    reader cited the governing outcome first.
    """
    touched = 0
    for question_id, mappings in mappings_by_question_id.items():
        if not question_id or not mappings:
            continue
        primary = max(mappings, key=lambda m: m.get("match_score") or 0.0)
        db.execute(
            text(
                "UPDATE lms_question_extraction "
                "   SET outcome_id = :oid, outcome_code = :code, "
                "       outcome_confidence = :score, outcome_source = :src "
                " WHERE question_id = :qid"
            ),
            {
                "oid": primary.get("outcome_id"),
                "code": primary.get("outcome_code"),
                "score": primary.get("match_score"),
                "src": primary.get("match_source") or "read",
                "qid": question_id,
            },
        )
        db.execute(
            text(
                "UPDATE lms_question_master "
                "   SET g_lo_code = :lo, g_cg_code = :cg WHERE id = :qid"
            ),
            {
                # The outcome itself if it is a learning outcome, else the node
                # that was cited -- a question mapped at competency level should
                # say so rather than leave the column empty.
                "lo": primary.get("outcome_code"),
                "cg": primary.get("goal_code"),
                "qid": question_id,
            },
        )
        touched += 1
    return touched


def resync_question_outcome_ids(db, curriculum_id: int) -> int:
    """Repoint outcome_id after a curriculum re-process rebuilt the tree.

    The rows survive because they are keyed on the code; only the cached id
    went stale. Mirror of `curriculum_frame.resync_outcome_ids`.
    """
    result = db.execute(
        text("""
            UPDATE lms_question_outcome qo
              JOIN lms_learning_outcomes lo
                ON lo.curriculum_id = :cid AND lo.code = qo.outcome_code
               SET qo.outcome_id = lo.id
             WHERE qo.curriculum_id = :cid
               AND (qo.outcome_id IS NULL OR qo.outcome_id <> lo.id)
        """),
        {"cid": curriculum_id},
    )
    return int(result.rowcount or 0)


def question_outcome_coverage(db, chapter_ids: Iterable[int]) -> Dict[int, Dict[str, int]]:
    """Per chapter: how many of its questions carry at least one outcome.

    The number to look at before declaring a book done -- "loaded" and "mapped"
    are different claims.
    """
    ids = [int(c) for c in chapter_ids if c]
    if not ids:
        return {}
    rows = db.execute(
        text("""
            SELECT q.chapter_id,
                   COUNT(DISTINCT q.id) AS questions,
                   COUNT(DISTINCT qo.question_id) AS mapped
              FROM lms_question_master q
              LEFT JOIN lms_question_outcome qo ON qo.question_id = q.id
             WHERE q.chapter_id IN :ids
             GROUP BY q.chapter_id
        """).bindparams(bindparam("ids", expanding=True)),
        {"ids": ids},
    ).fetchall()
    return {
        int(r[0]): {"questions": int(r[1] or 0), "mapped": int(r[2] or 0)}
        for r in rows
    }
