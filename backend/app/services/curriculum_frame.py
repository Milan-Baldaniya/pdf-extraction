"""The curriculum a chapter is taught against: its goals, competencies and outcomes.

`lms_learning_outcomes` has held the CG -> C -> LO tree since the Curriculum
Queue shipped, and until now no generation stage ever read it. Chapters were
divided into topics and concepts purely from the book, with the syllabus that
the book exists to deliver sitting unread in the next table.

That is what this module fixes. It answers two questions:

    What does the curriculum say this chapter must achieve?
        -> prompt_block(), handed to the topic and concept prompts
        -> lo_count / competency_count, which anchor the concept budget

    Which goal and competency does each concept serve?
        -> match_concepts() and persist_mappings(), writing lms_concept_outcome

The shape in the database, using chapter 8593 (Cell) as the worked example:

    CG3                              type=goal,             chapter_id=0
      C3.1  "Explains the role ..."  type=competency,       chapter_id=0
        C-3.1-LO-1 "Differentiate between plant and animal cell ..."
                                     type=learning_outcome, chapter_id=8593

Only the learning outcomes carry a chapter_id, so a chapter's competencies are
reached through its outcomes' parent_id -- with a second path for the 167
competency rows that do carry a chapter_id of their own.

Two facts about this table drive the design:

  * 73 rows have `type` set to '' or NULL. They are pre-migration junk and every
    query here filters them out explicitly rather than trusting the ENUM.
  * save_learning_outcomes() DELETEs and re-inserts every row of a curriculum on
    each re-process, so ids are not stable across runs. The durable key is
    (curriculum_id, code), which is why lms_concept_outcome stores the code and
    resync_outcome_ids() re-links the ids afterwards.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

from sqlalchemy import bindparam, text

from app.services import chapter_text as ct

logger = logging.getLogger(__name__)

_VALID_TYPES = ("goal", "competency", "learning_outcome")

# Below this a concept and an outcome merely share a common word. Matches the
# accept threshold question_ai_tagger uses for the same kind of lexical tag.
_MATCH_MIN = 0.25

# A keyword match is not comprehension, so it is never allowed to look
# confident. Same ceiling, and the same reasoning, as question_ai_tagger:322-325.
_LEXICAL_CAP = 0.45

# How many outcomes one concept may be mapped to. A concept that appears to
# serve five different competencies has matched on vocabulary, not on meaning.
_MAX_MAPPINGS_PER_CONCEPT = 3

# Enough chapter-specific outcomes to treat the curriculum as describing THIS
# chapter rather than the subject in general. Mirrors the budget's own
# thresholds so the two never disagree about whether data exists.
_MIN_USABLE_OUTCOMES = 4
_MIN_USABLE_COMPETENCIES = 2


@dataclass
class Outcome:
    id: int
    code: str
    type: str
    description: str
    parent_id: int | None = None
    goal_code: str = ""
    competency_code: str = ""

    @property
    def stems(self) -> set[str]:
        return ct.stems(self.description)


@dataclass
class CurriculumFrame:
    """One chapter's slice of its curriculum. Empty is a valid, common state."""

    chapter_id: int | None = None
    curriculum_id: int | None = None
    framework: str | None = None
    unit_name: str | None = None
    planned_periods: int | None = None
    goals: List[Outcome] = field(default_factory=list)
    competencies: List[Outcome] = field(default_factory=list)
    learning_outcomes: List[Outcome] = field(default_factory=list)
    # Competencies of the curriculum that are NOT tied to this chapter. Useful
    # as prompt context, deliberately excluded from the budget anchors below.
    subject_competencies: List[Outcome] = field(default_factory=list)

    @property
    def lo_count(self) -> int:
        """Chapter-specific outcomes only. This anchors the concept budget."""
        return len(self.learning_outcomes)

    @property
    def competency_count(self) -> int:
        return len(self.competencies)

    @property
    def is_usable(self) -> bool:
        """Whether this chapter has enough curriculum data to be scored on it."""
        return (
            self.lo_count >= _MIN_USABLE_OUTCOMES
            or self.competency_count >= _MIN_USABLE_COMPETENCIES
        )

    def all_outcomes(self) -> List[Outcome]:
        return [*self.goals, *self.competencies, *self.learning_outcomes]

    def anchor_text(self) -> str:
        """Every chapter-specific statement, for token-overlap scoring."""
        return " ".join(
            o.description for o in (*self.competencies, *self.learning_outcomes)
        )

    def codes(self) -> set[str]:
        """Valid codes, for rejecting ones the model invented."""
        return {o.code for o in self.all_outcomes() if o.code}

    def by_code(self) -> Dict[str, Outcome]:
        return {o.code: o for o in self.all_outcomes() if o.code}

    def prompt_block(self, *, limit: int = 40) -> str:
        """The curriculum as the model should see it: the tree, in order.

        Codes are shown because the concept call is asked to cite them back, and
        a code is far cheaper to match than a restated description.
        """
        if not (self.goals or self.competencies or self.learning_outcomes):
            return "(no curriculum outcomes are recorded for this chapter)"

        by_parent: Dict[int | None, List[Outcome]] = {}
        for outcome in (*self.competencies, *self.learning_outcomes):
            by_parent.setdefault(outcome.parent_id, []).append(outcome)

        lines: List[str] = []
        written = 0
        for goal in self.goals:
            lines.append(f"{goal.code} (Curricular Goal): {goal.description}")
            for competency in by_parent.get(goal.id, []):
                lines.append(f"  {competency.code} (Competency): {competency.description}")
                for outcome in by_parent.get(competency.id, []):
                    if written >= limit:
                        break
                    lines.append(f"    {outcome.code}: {outcome.description}")
                    written += 1

        # Competencies whose goal did not resolve would otherwise vanish.
        placed = {
            o.id
            for goal in self.goals
            for o in by_parent.get(goal.id, [])
        }
        orphans = [c for c in self.competencies if c.id not in placed]
        if orphans:
            lines.append("Competencies (goal not recorded):")
            for competency in orphans:
                lines.append(f"  {competency.code} (Competency): {competency.description}")
                for outcome in by_parent.get(competency.id, []):
                    if written >= limit:
                        break
                    lines.append(f"    {outcome.code}: {outcome.description}")
                    written += 1

        if not lines and self.subject_competencies:
            lines.append(
                "(nothing is recorded for this chapter specifically; these are the "
                "subject's competencies)"
            )
            for competency in self.subject_competencies[:12]:
                lines.append(f"  {competency.code}: {competency.description}")

        return "\n".join(lines) if lines else "(no curriculum outcomes for this chapter)"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "curriculum_id": self.curriculum_id,
            "framework": self.framework,
            "unit_name": self.unit_name,
            "planned_periods": self.planned_periods,
            "goals": len(self.goals),
            "competencies": self.competency_count,
            "learning_outcomes": self.lo_count,
            "usable": self.is_usable,
        }


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

# MinerU turns a page break into a "## Page 3" heading, and the curriculum
# parser carries it into the middle of a competency statement. Left in, it
# reaches the concept prompt as if it were part of the syllabus, and it adds
# "page" to the token set every lexical match is computed over.
_PAGE_MARKER_RE = re.compile(r"#{1,6}\s*Page\s*\d+", re.IGNORECASE)


def _clean_description(value: Any) -> str:
    return " ".join(_PAGE_MARKER_RE.sub(" ", str(value or "")).split())


def _row_to_outcome(row: Any) -> Outcome:
    return Outcome(
        id=int(row["id"]),
        code=str(row["code"] or "").strip(),
        type=str(row["type"] or "").strip(),
        description=_clean_description(row["description"]),
        parent_id=int(row["parent_id"]) if row["parent_id"] else None,
    )


def resolve_curriculum_id(
    db, *, chapter_id: int | None, standard_id: Any = None, subject_id: Any = None
) -> int | None:
    """Which curriculum governs this chapter.

    The unit is the reliable route: chapter_master.unit_id was mapped by the
    chapter stage and lms_units carries the curriculum_id outright. The
    standard/subject fallback repeats the fuzzy subject-name match
    chapter_service already uses to build its unit list, so a chapter whose unit
    never mapped still finds its syllabus.
    """
    if chapter_id:
        row = db.execute(
            text("""SELECT u.curriculum_id
                      FROM chapter_master cm
                      JOIN lms_units u ON u.id = cm.unit_id
                     WHERE cm.id = :cid AND u.curriculum_id IS NOT NULL"""),
            {"cid": chapter_id},
        ).fetchone()
        if row:
            return int(row[0])

    if not (standard_id and subject_id):
        return None

    row = db.execute(
        text("""
            SELECT c.id
              FROM lms_curriculum c
              LEFT JOIN subject cs ON cs.id = c.subject_id
              LEFT JOIN subject ds ON ds.id = :sub_id
             WHERE c.standard_id = :std_id
               AND (
                    c.subject_id = :sub_id
                 OR LOWER(ds.subject_name) LIKE CONCAT(LOWER(cs.subject_name), '%')
                 OR LOWER(cs.subject_name) LIKE CONCAT(LOWER(ds.subject_name), '%')
               )
          ORDER BY (c.subject_id = :sub_id) DESC, c.id DESC
             LIMIT 1
        """),
        {"std_id": standard_id, "sub_id": subject_id},
    ).fetchone()
    return int(row[0]) if row else None


def load_frame(
    db,
    *,
    chapter_id: int | None,
    standard_id: Any = None,
    subject_id: Any = None,
) -> CurriculumFrame:
    """This chapter's curriculum slice. Never raises; an empty frame is normal.

    Only 39 of 122 chapters in this corpus have any curriculum data at all, so
    "nothing found" is the common case and must stay cheap and quiet.
    """
    frame = CurriculumFrame(chapter_id=chapter_id)
    try:
        frame.curriculum_id = resolve_curriculum_id(
            db, chapter_id=chapter_id, standard_id=standard_id, subject_id=subject_id
        )

        if chapter_id:
            meta = db.execute(
                text("""SELECT u.name AS unit_name, u.planned_periods, c.framework
                          FROM chapter_master cm
                          LEFT JOIN lms_units u ON u.id = cm.unit_id
                          LEFT JOIN lms_curriculum c ON c.id = u.curriculum_id
                         WHERE cm.id = :cid"""),
                {"cid": chapter_id},
            ).mappings().fetchone()
            if meta:
                frame.unit_name = meta["unit_name"]
                frame.planned_periods = meta["planned_periods"]
                frame.framework = meta["framework"]

        if not chapter_id:
            return frame

        # 1. The chapter's own learning outcomes.
        frame.learning_outcomes = [
            _row_to_outcome(r)
            for r in db.execute(
                text("""SELECT id, code, type, description, parent_id
                          FROM lms_learning_outcomes
                         WHERE chapter_id = :cid AND type = 'learning_outcome'
                      ORDER BY id ASC"""),
                {"cid": chapter_id},
            ).mappings().fetchall()
        ]

        # 2. Its competencies: the parents of those outcomes, plus any
        #    competency row carrying this chapter_id directly (167 rows in this
        #    database do, because some syllabi tabulate competencies per chapter
        #    without spelling out outcomes).
        parent_ids = {o.parent_id for o in frame.learning_outcomes if o.parent_id}
        competencies: Dict[int, Outcome] = {}
        for row in db.execute(
            text("""SELECT id, code, type, description, parent_id
                      FROM lms_learning_outcomes
                     WHERE type = 'competency' AND chapter_id = :cid
                  ORDER BY id ASC"""),
            {"cid": chapter_id},
        ).mappings().fetchall():
            outcome = _row_to_outcome(row)
            competencies[outcome.id] = outcome
        if parent_ids:
            for row in db.execute(
                text("""SELECT id, code, type, description, parent_id
                          FROM lms_learning_outcomes
                         WHERE type = 'competency' AND id IN :ids
                      ORDER BY id ASC""").bindparams(
                    bindparam("ids", expanding=True)
                ),
                {"ids": list(parent_ids)},
            ).mappings().fetchall():
                outcome = _row_to_outcome(row)
                competencies.setdefault(outcome.id, outcome)
        frame.competencies = sorted(competencies.values(), key=lambda o: o.id)

        # 3. The goals above those competencies.
        goal_ids = {c.parent_id for c in frame.competencies if c.parent_id}
        if goal_ids:
            frame.goals = [
                _row_to_outcome(r)
                for r in db.execute(
                    text("""SELECT id, code, type, description, parent_id
                              FROM lms_learning_outcomes
                             WHERE type = 'goal' AND id IN :ids
                          ORDER BY id ASC""").bindparams(
                        bindparam("ids", expanding=True)
                    ),
                    {"ids": list(goal_ids)},
                ).mappings().fetchall()
            ]

        # 4. Denormalise the tree onto each row so a mapping can record which
        #    goal and competency a concept ultimately serves without re-walking.
        goal_by_id = {g.id: g for g in frame.goals}
        comp_by_id = {c.id: c for c in frame.competencies}
        for competency in frame.competencies:
            goal = goal_by_id.get(competency.parent_id or -1)
            competency.goal_code = goal.code if goal else ""
            competency.competency_code = competency.code
        for outcome in frame.learning_outcomes:
            competency = comp_by_id.get(outcome.parent_id or -1)
            outcome.competency_code = competency.code if competency else ""
            outcome.goal_code = competency.goal_code if competency else ""

        # 5. Subject-wide competencies, as context only when the chapter has
        #    nothing of its own. Never counted toward the budget.
        if not frame.is_usable and frame.curriculum_id:
            frame.subject_competencies = [
                _row_to_outcome(r)
                for r in db.execute(
                    text("""SELECT id, code, type, description, parent_id
                              FROM lms_learning_outcomes
                             WHERE curriculum_id = :cur AND type = 'competency'
                          ORDER BY id ASC LIMIT 40"""),
                    {"cur": frame.curriculum_id},
                ).mappings().fetchall()
            ]
    except Exception as exc:
        # A chapter with no curriculum must still process. Degrading to an empty
        # frame costs the curriculum anchor and nothing else.
        logger.warning("Curriculum frame unavailable for chapter %s: %s", chapter_id, exc)

    return frame


# ---------------------------------------------------------------------------
# Mapping concepts onto the curriculum
# ---------------------------------------------------------------------------

def match_concepts(
    concepts: List[Dict[str, Any]], frame: CurriculumFrame
) -> Dict[int, List[Dict[str, Any]]]:
    """Deterministic lexical mapping of concepts onto outcomes.

    Keyed by ``id(concept)`` so it works on dicts that have no database id yet.

    This is the fallback, not the primary mechanism -- the concept call is asked
    to cite codes itself, which it does far better because it understands that
    "Differentiate between plant and animal cell" and "Plant versus animal cell
    structure" are the same requirement. This catches what that misses, and its
    scores are capped accordingly: a keyword match must never look like
    comprehension.
    """
    targets = [*frame.learning_outcomes, *frame.competencies]
    if not targets:
        return {}

    scored = [(o, o.stems) for o in targets if o.stems]
    out: Dict[int, List[Dict[str, Any]]] = {}
    for concept in concepts:
        text_for_match = f"{concept.get('name') or ''} {concept.get('description') or ''}"
        hits: List[tuple[float, Outcome]] = []
        for outcome, stems in scored:
            # Symmetric: the outcome statement is a sentence and the concept
            # name is two words, so one-directional coverage would systematically
            # favour whichever happened to be shorter.
            name_score = ct.coverage(outcome.description, ct.stems(text_for_match))
            concept_score = ct.coverage(text_for_match, stems)
            score = max(name_score, concept_score)
            if score >= _MATCH_MIN:
                hits.append((min(score, _LEXICAL_CAP), outcome))

        hits.sort(key=lambda h: -h[0])
        out[id(concept)] = [
            {
                "outcome_id": outcome.id,
                "outcome_code": outcome.code,
                "outcome_type": outcome.type,
                "match_source": "token_overlap",
                "match_score": round(score, 3),
            }
            for score, outcome in hits[:_MAX_MAPPINGS_PER_CONCEPT]
        ]
    return out


class UnknownOutcomeCode(ValueError):
    """A cited code is not in this chapter's curriculum frame.

    Carries the legal list, because the only useful thing to tell whoever hit
    this is what they could have said instead.
    """

    def __init__(self, code: str, legal: List[str]) -> None:
        self.code = code
        self.legal = legal
        shown = ", ".join(legal[:12]) + (" ..." if len(legal) > 12 else "")
        super().__init__(
            f"curriculum code {code!r} is not in this chapter's frame. "
            f"Legal codes: {shown or '(this chapter has none)'}"
        )


def sanitise_codes(
    cited: Any,
    frame: CurriculumFrame,
    *,
    match_score: float = 0.9,
    strict: bool = False,
    match_source: str = "llm",
) -> List[Dict[str, Any]]:
    """Turn the codes a model cited into mappings, dropping any it invented.

    Hallucinated references are the failure mode that matters here: a mapping
    onto a code this curriculum does not contain is worse than no mapping,
    because it reads as curriculum alignment and is not. Same guard, for the
    same reason, as question_ai_tagger._sanitise.

    `strict` raises UnknownOutcomeCode instead of dropping. Dropping is right
    for the concept fan-out, where one bad code among hundreds should not fail
    a chapter. It is wrong when the mapping IS the deliverable -- a question
    bank loaded with every citation silently discarded looks exactly like one
    loaded correctly. Callers that mean it pass strict=True; the default keeps
    existing behaviour byte for byte.
    """
    if not isinstance(cited, list):
        cited = [cited] if cited else []

    lookup = {_normalise_code(c): o for c, o in frame.by_code().items()}
    mappings: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw in cited:
        code = _normalise_code(str(raw or ""))
        if not code or code in seen:
            continue
        outcome = lookup.get(code)
        if outcome is None:
            if strict:
                raise UnknownOutcomeCode(str(raw), sorted(frame.codes()))
            logger.debug("Dropping curriculum code %r: not in this chapter's frame", raw)
            continue
        seen.add(code)
        mappings.append({
            "outcome_id": outcome.id,
            "outcome_code": outcome.code,
            "outcome_type": outcome.type,
            "match_source": match_source,
            "match_score": match_score,
        })
        if len(mappings) >= _MAX_MAPPINGS_PER_CONCEPT:
            break
    return mappings


def _normalise_code(value: str) -> str:
    """C 3.1, C-3.1, c3.1 and C–3.1 are one code. The data contains all four."""
    return (
        str(value or "")
        .strip()
        .lower()
        .replace("–", "")
        .replace("—", "")
        .replace("-", "")
        .replace(" ", "")
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

_UPSERT_MAPPING = text("""
    INSERT INTO lms_concept_outcome
        (concept_id, outcome_id, outcome_type, outcome_code, curriculum_id,
         extraction_id, chapter_id, match_source, match_score, created_at, updated_at)
    VALUES
        (:concept_id, :outcome_id, :outcome_type, :outcome_code, :curriculum_id,
         :extraction_id, :chapter_id, :match_source, :match_score,
         CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    ON DUPLICATE KEY UPDATE
        outcome_id   = VALUES(outcome_id),
        outcome_type = VALUES(outcome_type),
        match_source = VALUES(match_source),
        match_score  = VALUES(match_score),
        updated_at   = CURRENT_TIMESTAMP
""")


def persist_mappings(
    db,
    *,
    frame: CurriculumFrame,
    extraction_id: int,
    mappings_by_concept_id: Dict[int, List[Dict[str, Any]]],
) -> int:
    """Write concept -> outcome links. Replaces each concept's set wholesale.

    Scoped per concept rather than per extraction so a single-concept re-run
    cannot wipe its siblings' mappings.
    """
    written = 0
    concept_ids = [cid for cid in mappings_by_concept_id if cid]
    if not concept_ids:
        return 0

    try:
        db.execute(
            text("DELETE FROM lms_concept_outcome WHERE concept_id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": concept_ids},
        )
        for concept_id, mappings in mappings_by_concept_id.items():
            if not concept_id:
                continue
            for mapping in mappings:
                db.execute(_UPSERT_MAPPING, {
                    "concept_id": concept_id,
                    "outcome_id": mapping.get("outcome_id"),
                    "outcome_type": mapping.get("outcome_type") or "competency",
                    "outcome_code": mapping.get("outcome_code") or "",
                    "curriculum_id": frame.curriculum_id,
                    "extraction_id": extraction_id,
                    "chapter_id": frame.chapter_id,
                    "match_source": mapping.get("match_source") or "llm",
                    "match_score": mapping.get("match_score"),
                })
                written += 1
        db.commit()
    except Exception as exc:
        db.rollback()
        # A chapter's concepts are worth far more than their curriculum tags.
        logger.warning("Could not persist curriculum mappings for %s: %s", extraction_id, exc)
        return 0
    return written


def get_chapter_outcomes_data(extraction_id: int) -> Dict[str, Any]:
    """The curriculum frame of one extraction's chapter, with its concept links.

    Read-only, LLM-free, and the quickest way to see whether a subject's
    syllabus has been loaded at all -- which decides whether the concept budget
    is anchored on outcomes, on periods, or on the chapter's own structure.
    """
    from app.db.mariadb import SessionLocal

    with SessionLocal() as db:
        chapter = db.execute(
            text("""SELECT id, chapter_name, standard_id, subject_id, no_of_periods
                      FROM chapter_master WHERE extraction_id = :id
                  ORDER BY id ASC LIMIT 1"""),
            {"id": extraction_id},
        ).mappings().fetchone()
        if not chapter:
            raise ValueError(
                f"No chapter_master found for extraction_id {extraction_id}. "
                f"Run the Chapter queue first."
            )

        frame = load_frame(
            db,
            chapter_id=chapter["id"],
            standard_id=chapter["standard_id"],
            subject_id=chapter["subject_id"],
        )

        try:
            links = [dict(r) for r in db.execute(
                text("""
                    SELECT co.outcome_code, co.outcome_type, co.match_source,
                           co.match_score, c.id AS concept_id, c.name AS concept_name
                      FROM lms_concept_outcome co
                      JOIN lms_concept c ON c.id = co.concept_id
                     WHERE co.extraction_id = :id
                  ORDER BY co.outcome_code ASC, c.id ASC
                """),
                {"id": extraction_id},
            ).mappings().fetchall()]
        except Exception as exc:
            # The mapping table is created at runtime; a database that has not
            # run a chapter since the migration simply has no links yet.
            logger.warning("Could not read concept-outcome links for %s: %s", extraction_id, exc)
            links = []

    by_code: Dict[str, List[Dict[str, Any]]] = {}
    for link in links:
        by_code.setdefault(link["outcome_code"], []).append({
            "concept_id": link["concept_id"],
            "concept_name": link["concept_name"],
            "match_source": link["match_source"],
            "match_score": float(link["match_score"]) if link["match_score"] is not None else None,
        })

    def serialise(outcome: Outcome) -> Dict[str, Any]:
        return {
            "id": outcome.id,
            "code": outcome.code,
            "type": outcome.type,
            "description": outcome.description,
            "parent_id": outcome.parent_id,
            "goal_code": outcome.goal_code,
            "competency_code": outcome.competency_code,
            "concepts": by_code.get(outcome.code, []),
        }

    summary = frame.as_dict()
    return {
        "extraction_id": extraction_id,
        "chapter_id": chapter["id"],
        "chapter_name": chapter["chapter_name"],
        "no_of_periods": chapter["no_of_periods"],
        # The counts live under their own key: the list of goals and the number
        # of goals cannot both be called "goals".
        "summary": summary,
        "curriculum_id": summary["curriculum_id"],
        "usable": summary["usable"],
        "goals": [serialise(o) for o in frame.goals],
        "competencies": [serialise(o) for o in frame.competencies],
        "learning_outcomes": [serialise(o) for o in frame.learning_outcomes],
        "subject_competencies": [serialise(o) for o in frame.subject_competencies],
        "mapped_concepts": len({link["concept_id"] for link in links}),
    }


def resync_outcome_ids(db, curriculum_id: int) -> int:
    """Re-link mappings after a curriculum re-process replaced every outcome row.

    save_learning_outcomes() deletes and re-inserts the whole tree, so every
    lms_concept_outcome.outcome_id written before that run now points at a row
    that no longer exists. The code survives the rewrite, so the ids can be
    recovered from it -- which is the entire reason outcome_code is stored
    alongside the id rather than the id alone.
    """
    try:
        updated = db.execute(
            text("""
                UPDATE lms_concept_outcome co
                  JOIN lms_learning_outcomes lo
                    ON lo.curriculum_id = :cur
                   AND REPLACE(REPLACE(LOWER(lo.code), '-', ''), ' ', '')
                     = REPLACE(REPLACE(LOWER(co.outcome_code), '-', ''), ' ', '')
                   SET co.outcome_id = lo.id,
                       co.outcome_type = lo.type,
                       co.updated_at = CURRENT_TIMESTAMP
                 WHERE co.curriculum_id = :cur
                   AND (co.outcome_id IS NULL OR co.outcome_id <> lo.id)
            """),
            {"cur": curriculum_id},
        ).rowcount
        db.commit()
        if updated:
            logger.info(
                "Re-linked %s concept-outcome mapping(s) for curriculum %s",
                updated, curriculum_id,
            )
        return updated
    except Exception as exc:
        db.rollback()
        logger.warning("Could not resync outcome ids for curriculum %s: %s", curriculum_id, exc)
        return 0
