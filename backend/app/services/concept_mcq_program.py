"""A managed MCQ bank of 40 items per concept, balanced across difficulty.

The target is 40 multiple-choice questions for every `lms_concept`, split
Easy / Medium / Hard, each carrying a Bloom level and a DOK level. The point is
diagnosis: an adaptive test can only tell you *which* gap a student has if the
concept it is probing has enough items at enough levels to separate "has not
learnt it" from "cannot apply it".

Measured before this existed, chapter 1012 had 21 MCQs on "Precipitation
reaction" and 1 on "Prevention of rancidity". A concept with one question is a
concept the test cannot say anything about.

Three things here are load-bearing:

**The ladder is one closed table.** Difficulty, Bloom and DOK are three views of
the same judgement, and letting them be set independently is how a bank ends up
with an "Easy" question tagged `Analyze` at DOK 3. `LADDER` below is the single
source; everything else derives.

**The validator is a hard gate.** 9,640 MCQs written quickly are 9,640
liabilities unless something checks them. `validate_mcq` rejects the specific
failures that make a question unusable rather than merely imperfect -- most
importantly the length tell, where the correct option is visibly the longest and
a student can score without reading the stem.

**These are authored, not extracted.** There is no `document_extractions` row
and no `lms_question_extraction` sidecar, because no publisher wrote them. That
is why this module has its own writer instead of reusing `persist_supplied`:
routing authored content through the extraction path would make it indexed,
searchable and attributed as though it came out of a book.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from sqlalchemy import text

from app.db.mariadb import SessionLocal, init_mariadb

logger = logging.getLogger(__name__)

# One closed table. Bloom is written in the LMS's Title-Case `g_bloom`
# vocabulary, which starts at "Remember" -- NOT PAL's lowercase set, which
# starts at "recall". Both are live in this estate and must not be unified.
#
# DOK is pinned one-to-one to difficulty, because that is the tie the bank
# needs: an Easy item is a DOK 1 item. Bloom deliberately OVERLAPS between
# rungs, because Bloom and difficulty are different axes and forcing them to
# agree produces nonsense. "10 g of A reacts with 20 g of B; what mass of
# product forms?" is cognitively Apply -- the student uses a rule -- and
# unarguably Easy, being a single-step sum. A rung that refused it would push
# every arithmetic item into Medium and leave Easy as pure recall, which is not
# what an Easy tier is for.
LADDER: dict[str, dict[str, Any]] = {
    "Easy":   {"bloom": ("Remember", "Understand", "Apply"),  "dok": 1, "slots": 14},
    "Medium": {"bloom": ("Understand", "Apply", "Analyze"),   "dok": 2, "slots": 13},
    "Hard":   {"bloom": ("Analyze", "Evaluate", "Create"),    "dok": 3, "slots": 13},
}
TARGET_PER_CONCEPT = sum(v["slots"] for v in LADDER.values())  # 40

# Tenancy. `sub_institute_id` on a shared content bank is a BOARD, not a
# school: 1 is CBSE, 341 is Cambridge. Getting this wrong publishes CBSE
# content into another board's bank.
CBSE = 1

OPTION_MAX = 250          # answer_master.answer is varchar(250)
STATUS_PUBLISHED = 1
STATUS_HELD = 0
QUESTION_TYPE_MCQ = 1     # question_type_master.id for 'multiple'

PROVENANCE = "authored-mcq-v1"

_VAGUE_OPTIONS = re.compile(r"^\s*(all|none)\s+of\s+(the\s+)?above\s*\.?\s*$", re.I)


def _session():
    if not init_mariadb() or SessionLocal is None:
        raise RuntimeError("Database not ready")
    return SessionLocal()


def _norm(value: str) -> str:
    """Normalised stem text, for dedupe. Case, spacing and punctuation out."""
    stripped = re.sub(r"<[^>]+>", " ", value or "")
    stripped = re.sub(r"[^a-z0-9]+", " ", stripped.lower())
    return " ".join(stripped.split())


def _norm_option(value: str) -> str:
    """Normalise an option WITHOUT destroying equation structure.

    Plain `_norm` strips every non-alphanumeric character, which collapses

        "Magnesium + Oxygen -> Magnesium oxide"
        "Magnesium -> Oxygen + Magnesium oxide"

    onto the same string and reports two perfectly good distractors as
    duplicates. In an equation the operators ARE the content -- which side of
    the arrow a substance sits on is the whole question -- so they survive as
    words.
    """
    text_ = re.sub(r"<[^>]+>", " ", value or "").lower()
    text_ = text_.replace("->", " arrow ").replace("→", " arrow ")
    text_ = text_.replace("+", " plus ").replace("=", " equals ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text_).split())


def content_hash(stem: str, options: list[str]) -> str:
    """Stable hash over the stem plus the option SET.

    Options are sorted, so shuffling the same four choices is recognised as the
    same question -- reordering is the cheapest way to accidentally produce a
    duplicate. This goes in `g_content_hash`; `verbatim_sha256` stays reserved
    for content reproduced from a source document.
    """
    payload = _norm(stem) + "|" + "|".join(sorted(_norm(o) for o in options))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- validation

def validate_mcq(item: dict[str, Any]) -> list[str]:
    """Problems that make an MCQ unusable. Empty list means it can be stored."""
    problems: list[str] = []

    stem = str(item.get("stem") or "").strip()
    # Deliberately loose. The rule exists to catch a stem that was truncated or
    # never written, not to outlaw terse ones: "2Na means" is a perfectly good
    # two-word question.
    if len(stem.split()) < 2 or len(stem) < 8:
        problems.append("stem is too short to be a question")
    if len(stem) > 2000:
        problems.append("stem is longer than 2000 characters")

    options = item.get("options") or []
    if not isinstance(options, list) or len(options) != 4:
        problems.append(f"needs exactly 4 options, got {len(options) if isinstance(options, list) else 'none'}")
        return problems

    texts = [str(o.get("text") or "").strip() for o in options]
    if any(not t for t in texts):
        problems.append("an option has no text")
    if len(texts) != len({_norm_option(t) for t in texts}):
        problems.append("two options are the same")
    over = [t for t in texts if len(t) > OPTION_MAX]
    if over:
        problems.append(f"option longer than {OPTION_MAX} chars: {over[0][:40]!r}")

    keys = [i for i, o in enumerate(options) if o.get("correct")]
    if len(keys) != 1:
        problems.append(f"needs exactly one correct option, got {len(keys)}")
        return problems
    key_index = keys[0]
    key_text = texts[key_index]

    # The length tell. When the correct option is conspicuously the longest, a
    # student can score by picking the long one without reading the stem, and
    # the item measures test-wiseness instead of the concept. Tolerance is 35%
    # over the next longest -- a correct answer IS often a little fuller.
    others = [len(t) for i, t in enumerate(texts) if i != key_index]
    if others and len(key_text) > max(others) * 1.35 + 8:
        problems.append(
            f"correct option is conspicuously the longest ({len(key_text)} vs {max(others)} chars)"
        )

    vague = [t for t in texts if _VAGUE_OPTIONS.match(t)]
    if len(vague) > 1:
        problems.append("more than one 'all/none of the above' option")
    if vague and options[key_index].get("correct") and _VAGUE_OPTIONS.match(key_text):
        problems.append("'all/none of the above' used as the key")

    # The stem must not hand over the answer -- but only where it hands it over
    # to the KEY ALONE. A whole class of legitimate question quotes the material
    # it is asking about, and then every option necessarily draws on the stem's
    # vocabulary:
    #
    #   "Zinc + Sulphuric acid -> Zinc sulphate + Hydrogen.
    #    The products in this word equation are"
    #
    # The student still has to know which side of the arrow is which, so this is
    # a real question. It is a giveaway only when the key echoes the stem and
    # the distractors do not, because then matching words is enough to score.
    stem_words = set(_norm(stem).split())

    def _echoes_stem(value: str) -> bool:
        distinctive = {w for w in _norm(value).split() if len(w) > 5}
        return bool(distinctive) and distinctive <= stem_words

    if _echoes_stem(key_text) and not any(
        _echoes_stem(t) for i, t in enumerate(texts) if i != key_index
    ):
        problems.append("the stem gives away the key and no distractor")

    difficulty = str(item.get("difficulty") or "")
    if difficulty not in LADDER:
        problems.append(f"difficulty must be one of {list(LADDER)}, got {difficulty!r}")
    else:
        rung = LADDER[difficulty]
        bloom = str(item.get("bloom") or "")
        if bloom not in rung["bloom"]:
            problems.append(
                f"{difficulty} allows Bloom {rung['bloom']}, got {bloom!r}"
            )
        dok = item.get("dok")
        if dok is not None and int(dok) != rung["dok"]:
            problems.append(f"{difficulty} is DOK {rung['dok']}, got {dok}")

    # Every distractor carries why it is wrong. That text is the diagnostic
    # payload -- it is what turns "got it wrong" into "holds this specific
    # misconception" -- so an item without it is only half an item.
    missing_why = [
        i for i, o in enumerate(options)
        if not o.get("correct") and not str(o.get("why") or "").strip()
    ]
    if missing_why:
        problems.append(f"distractor(s) {missing_why} have no 'why' note")

    if not str(item.get("explanation") or "").strip():
        problems.append("no explanation for the correct answer")

    return problems


# ------------------------------------------------------------------ planning

def _concept_rows(chapter_id: int) -> list[dict[str, Any]]:
    db = _session()
    try:
        return [
            dict(r)
            for r in db.execute(
                text(
                    """
                    SELECT c.id, c.name, c.description, c.chapter_id,
                           ch.chapter_name, ch.standard_id, ch.subject_id
                      FROM lms_concept c
                      JOIN chapter_master ch ON ch.id = c.chapter_id
                     WHERE c.chapter_id = :c
                     ORDER BY c.id
                    """
                ),
                {"c": chapter_id},
            ).mappings()
        ]
    finally:
        db.close()


def _existing_by_difficulty(concept_ids: list[int]) -> dict[int, dict[str, int]]:
    if not concept_ids:
        return {}
    db = _session()
    try:
        rows = db.execute(
            text(
                """
                SELECT q.concept_id, COALESCE(q.g_difficulty, 'Unset') AS d, COUNT(*) AS n
                  FROM lms_question_master q
                  JOIN question_type_master qt ON qt.id = q.question_type_id
                 WHERE q.concept_id IN :ids
                   AND q.deleted_at IS NULL
                   AND qt.question_type = 'multiple'
                 GROUP BY q.concept_id, d
                """
            ),
            {"ids": tuple(concept_ids)},
        ).fetchall()
    finally:
        db.close()

    out: dict[int, dict[str, int]] = {}
    for concept_id, difficulty, n in rows:
        out.setdefault(int(concept_id), {})[str(difficulty)] = int(n)
    return out


def plan_chapter(chapter_id: int) -> list[dict[str, Any]]:
    """Per concept: what exists by difficulty, and the remaining gap.

    Authoring against a gap rather than a total is the difference between
    "write 40" and "write the 6 Hard ones this concept is missing".
    """
    concepts = _concept_rows(chapter_id)
    existing = _existing_by_difficulty([int(c["id"]) for c in concepts])

    plan = []
    for concept in concepts:
        have = existing.get(int(concept["id"]), {})
        gap = {
            level: max(0, rung["slots"] - have.get(level, 0))
            for level, rung in LADDER.items()
        }
        plan.append({
            **concept,
            "have": have,
            "have_total": sum(have.values()),
            "gap": gap,
            "gap_total": sum(gap.values()),
        })
    return plan


# ------------------------------------------------------------------- writing

def write_mcqs(
    concept_id: int,
    items: list[dict[str, Any]],
    *,
    created_by: int = 1,
    sub_institute_id: int = CBSE,
    publish_clean: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Store authored MCQs against one concept.

    No extraction sidecar is written: these questions have no source document,
    and claiming one would make them look reproduced. An item that fails
    `validate_mcq` is not stored at all -- storing a broken MCQ held for review
    just moves the problem to a teacher.
    """
    report: dict[str, Any] = {
        "concept_id": concept_id, "written": 0, "rejected": 0,
        "duplicate": 0, "problems": [], "by_difficulty": {},
    }
    if not items:
        return report

    db = _session()
    try:
        concept = db.execute(
            text(
                """
                SELECT c.id, c.name, c.chapter_id,
                       ch.standard_id, ch.subject_id, ch.chapter_name
                  FROM lms_concept c
                  JOIN chapter_master ch ON ch.id = c.chapter_id
                 WHERE c.id = :i
                """
            ),
            {"i": concept_id},
        ).mappings().fetchone()
        if not concept:
            raise ValueError(f"concept {concept_id} does not exist")

        # Dedupe against the whole chapter, not just the concept: the same
        # question written twice under two neighbouring concepts is still a
        # duplicate to the student who meets it twice.
        seen = {
            r[0] for r in db.execute(
                text(
                    "SELECT g_content_hash FROM lms_question_master "
                    " WHERE chapter_id = :c AND g_content_hash IS NOT NULL"
                ),
                {"c": concept["chapter_id"]},
            ).fetchall()
        }

        accepted = []
        for index, item in enumerate(items):
            problems = validate_mcq(item)
            if problems:
                report["rejected"] += 1
                report["problems"].append({"index": index, "problems": problems,
                                           "stem": str(item.get("stem"))[:90]})
                continue

            options = [str(o["text"]).strip() for o in item["options"]]
            digest = content_hash(item["stem"], options)
            if digest in seen:
                report["duplicate"] += 1
                continue
            seen.add(digest)
            accepted.append((item, digest))

        if dry_run:
            report["written"] = len(accepted)
            for item, _ in accepted:
                d = item["difficulty"]
                report["by_difficulty"][d] = report["by_difficulty"].get(d, 0) + 1
            return report

        for item, digest in accepted:
            difficulty = item["difficulty"]
            rung = LADDER[difficulty]
            db.execute(
                text(
                    """
                    INSERT INTO lms_question_master
                        (question_type_id, standard_id, subject_id, chapter_id,
                         concept_id, concept, question_title, description, points,
                         multiple_answer, sub_institute_id, status, created_by,
                         answer, g_bloom, g_difficulty, g_dok, g_qtype_code,
                         g_content_hash, hint_text)
                    VALUES
                        (:qtype, :standard, :subject, :chapter,
                         :concept_id, :concept_name, :stem, :description, 1,
                         0, :tenant, :status, :created_by,
                         '', :bloom, :difficulty, :dok, 'mcq',
                         :digest, :explanation)
                    """
                ),
                {
                    "qtype": QUESTION_TYPE_MCQ,
                    "standard": concept["standard_id"],
                    "subject": concept["subject_id"],
                    "chapter": concept["chapter_id"],
                    "concept_id": concept["id"],
                    "concept_name": str(concept["name"] or "")[:250],
                    "stem": item["stem"].strip(),
                    "description": PROVENANCE,
                    "tenant": sub_institute_id,
                    "status": STATUS_PUBLISHED if publish_clean else STATUS_HELD,
                    "created_by": created_by,
                    "bloom": item["bloom"],
                    "difficulty": difficulty,
                    "dok": rung["dok"],
                    "digest": digest,
                    "explanation": str(item["explanation"]).strip()[:60000],
                },
            )
            question_id = int(db.execute(text("SELECT LAST_INSERT_ID()")).scalar())

            for option in item["options"]:
                db.execute(
                    text(
                        """
                        INSERT INTO answer_master
                            (question_id, answer, feedback, correct_answer,
                             sub_institute_id, created_by)
                        VALUES (:q, :a, :f, :c, :tenant, :created_by)
                        """
                    ),
                    {
                        "q": question_id,
                        "a": str(option["text"]).strip()[:OPTION_MAX],
                        # The distractor's "why" is the diagnostic payload: it
                        # names the misconception a student who picked it holds.
                        "f": (str(option.get("why") or "").strip()[:OPTION_MAX] or None),
                        "c": 1 if option.get("correct") else 0,
                        "tenant": sub_institute_id,
                        "created_by": created_by,
                    },
                )

            report["written"] += 1
            report["by_difficulty"][difficulty] = (
                report["by_difficulty"].get(difficulty, 0) + 1
            )

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    logger.info("wrote %s MCQ(s) on concept %s", report["written"], concept_id)
    return report


__all__ = [
    "LADDER",
    "TARGET_PER_CONCEPT",
    "content_hash",
    "plan_chapter",
    "validate_mcq",
    "write_mcqs",
]