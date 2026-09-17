"""Give every question a real catalog form, honest marks and a difficulty.

Three columns on `lms_question_master` were effectively dead for generated
content, and each one broke something visible:

* **form** -- `question_type_catalog` has 13 meaningful forms, but the API reads
  the code only from `lms_question_extraction`. 0 of 2,985 Class 10 Science
  questions have that sidecar, so all of them render as catalog label "(none)"
  and the bank's type filter cannot see them. `g_qtype_code` (sql/006) is the
  derived-tag column that fixes this without claiming the questions were
  extracted. See that migration for why a sidecar row would have been a lie.

* **marks** -- every one of the 2,155 answerless narrative rows is `points = 1`,
  including five-mark "Explain with a diagram" questions. Any blueprint or paper
  built on that is wrong before it starts.

* **difficulty** -- `g_difficulty` is NULL on ~59k rows. The per-concept MCQ
  programme counts slots by difficulty, so an untagged question counts for
  nothing even when it is a perfectly good question.

All three are derived from the stem's own shape and verb. Nothing here invents
content; it reads what is already stored and labels it.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import text

from app.db.mariadb import SessionLocal, init_mariadb
from app.services.question_ai_tagger import (
    _LMS_BLOOM,
    _classify_bloom,
    _lms_difficulty,
)

logger = logging.getLogger(__name__)

# The 13 forms worth assigning. `unknown` is the catalog's own escape hatch and
# is never written -- an unclassifiable question keeps its coarse type instead,
# because "unknown" in a filter dropdown is noise. `case_study`,
# `competency_focused` and `source_based_integrated` are legacy aliases that
# overlap the case-study pair and are left to extracted content.
CATALOG_FORMS = (
    "mcq", "assertion_reason", "true_false", "fill_blank", "match_following",
    "very_short", "short", "long", "case_study_parent", "case_study_child",
    "proof", "construction", "numerical",
)

# Marks by form. A one-mark bank cannot produce a board paper: Section A is
# 1 mark, B is 2-3, C is 3, D is 5 and E is the 4-mark case study.
MARKS_BY_FORM = {
    "mcq": 1, "assertion_reason": 1, "true_false": 1, "fill_blank": 1,
    "match_following": 1, "very_short": 1,
    "short": 3, "numerical": 3, "construction": 3,
    "case_study_parent": 4, "case_study_child": 1,
    "long": 5, "proof": 5,
}

# Ordered most-specific first: a stem that is both an assertion-reason item and
# a four-option MCQ is an assertion-reason item, and testing MCQ first would
# swallow it. Every pattern below keys off structure the stem actually carries,
# never off a guess about the subject.
_FORM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("assertion_reason", re.compile(
        r"(assertion\s*\(?\s*a\s*\)?\s*[:\-]|reason\s*\(?\s*r\s*\)?\s*[:\-]"
        r"|\bassertion\b.{0,80}\breason\b)", re.I | re.S)),
    ("match_following", re.compile(
        r"(match\s+the\s+follow|match\s+column|column\s*-?\s*i\b.{0,120}column\s*-?\s*ii"
        r"|match\s+list\s*-?\s*i)", re.I | re.S)),
    ("fill_blank", re.compile(
        r"(fill\s+in\s+the\s+blank|_{3,}|\.{4,}\s*$|\bblank\s+space)", re.I)),
    ("true_false", re.compile(
        r"(true\s+or\s+false|state\s+whether.{0,40}true|write\s+true\s+or\s+false"
        r"|\(\s*true\s*/\s*false\s*\))", re.I)),
    ("case_study_parent", re.compile(
        r"(read\s+the\s+(?:following\s+)?(?:passage|paragraph|case|text)"
        r"|case\s*[-\s]?(?:study|based)\s+question"
        r"|answer\s+the\s+(?:following\s+)?questions?\s+(?:that\s+follow|given\s+below)"
        r"|based\s+on\s+the\s+above\s+passage)", re.I)),
    ("proof", re.compile(
        r"\b(prove\s+that|show\s+that|verify\s+that|establish\s+that"
        r"|prove\s+the|derive\s+(?:the\s+)?(?:expression|formula|relation))", re.I)),
    ("construction", re.compile(
        r"\b(draw\s+(?:a|an|the|ray|neat|labelled|well)"
        r"|construct\s+(?:a|an|the)|plot\s+(?:a|the)|sketch\s+(?:a|the)"
        r"|label(?:led)?\s+diagram|trace\s+the\s+(?:path|ray))", re.I)),
    ("numerical", re.compile(
        r"\b(calculat|comput|find\s+the\s+(?:value|resistance|current|power|focal"
        r"|magnification|distance|mass|number|amount|concentration)"
        r"|how\s+much\s+(?:current|power|energy|heat|work|time)"
        r"|determine\s+the\s+(?:value|resistance|current|magnification)"
        r"|what\s+is\s+the\s+(?:value|resistance|current|power)\s+of)", re.I)),
]

# `(a) ... (b) ... (c) ... (d)` in a stem is ambiguous, and getting it wrong
# both ways is a real bug already seen in this bank:
#
#   84850  "Give the characteristic tests for the following gases :
#            (a) CO2 (b) SO2 (c) O2 (d) H2"        <- SUB-PARTS, do all four
#   84816  "The following reaction is an example of ...
#            (i) displacement (ii) combustion ..."  <- OPTIONS, choose one
#
# Both have labelled segments of bare noun phrases, so the segments cannot tell
# them apart -- the discriminator is the LEAD-IN. "Give ... the following" asks
# for work on each; "is an example of" asks for one. Same shape of structural
# discriminator the section parser needed.
_LABELLED_PARTS_RE = re.compile(
    r"\(?\s*(?:a|i)\s*[\)\.]\s*.{1,400}?\(?\s*(?:b|ii)\s*[\)\.]",
    re.I | re.S,
)

# Asks the student to CHOOSE ONE of the labelled segments. Split in two because
# of where the cue sits. "is an example of" can be followed by the thing being
# classified -- often a chemical equation -- so it cannot be end-anchored:
#
#   "The following reaction is an example of 4NH3 + SO2 -> 4NO + 6H2O
#    (i) displacement (ii) combustion (iii) redox"
#
# whereas a bare "is" only means "choose one" when it is the last word before
# the options, or every question containing the word "is" becomes an MCQ.
_CHOOSE_ONE_STRONG_RE = re.compile(
    r"(which\s+(?:one\s+)?of\s+the\s+follow"
    r"|which\s+(?:one|among|is)\b"
    r"|(?:is|are)\s+an?\s+(?:example|instance|case)\s+of"
    r"|(?:is|are)\s+(?:called|known\s+as|termed)"
    r"|(?:correct|incorrect|right|wrong|best)\s+(?:option|answer|statement|choice|one)"
    r"|the\s+correct\s+(?:sequence|order|match|pair|formula))",
    re.I,
)
_CHOOSE_ONE_TRAILING_RE = re.compile(
    r"(?:is|are|will\s+be|would\s+be|can\s+be|should\s+be|was"
    # A stem ending in "of" right before the labels is a sentence-completion
    # MCQ: "... This is due to the formation of (a) Ag2S (b) AgNO3 ...".
    # A sub-part lead-in never ends this way, and _DO_EACH_RE guards the rest.
    r"|of|than|by|in|to"
    r"|called|known\s+as|termed|represented\s+by)\s*[:\-]?\s*$",
    re.I,
)

# Individual labelled segments, for counting how many answers a stem wants.
# Requires the closing bracket, so "4NH3(g)" and "cone. HNO3" do not count.
_SUBPART_LABEL_RE = re.compile(r"\(\s*(?:[a-f]|i{1,3}|iv|v)\s*\)", re.I)

# Asks the student to DO SOMETHING TO EACH labelled segment.
_DO_EACH_RE = re.compile(
    r"\b(give|explain|name|write|describe|define|draw|complete|balance|state"
    r"|answer|match|distinguish|classif|identify|list|find|calculat|comput"
    r"|suggest|mention|justify|account\s+for|what\s+happens\s+when)\b"
    r"[^.?]{0,80}?\b(?:the\s+)?(?:follow|each|these|below)",
    re.I,
)

# Length thresholds for the plain answer forms, in words of stem. A question
# asking for more is generally phrased with more.
_VERY_SHORT_WORDS = 22
_SHORT_WORDS = 45

# Stems in this bank carry OCR debris -- runs of mojibake and box-drawing
# characters where the PDF had rules or spacing. Counted as words they inflate
# a one-liner into a "long answer": stem 87042 is a nine-word question followed
# by a dozen stray glyphs. Word count has to see the question, not the noise.
_NOISE_RUN_RE = re.compile(r"[^\w\s\?\.\,\;\:\(\)\[\]\-\+\=\/\'\"%°]+")


def _session():
    if not init_mariadb() or SessionLocal is None:
        raise RuntimeError("Database not ready")
    return SessionLocal()


def _strip(html: str | None) -> str:
    text_ = re.sub(r"<[^>]+>", " ", html or "")
    return " ".join(text_.split())


def classify_form(stem: str, *, is_mcq: bool, has_options: bool = False) -> str:
    """Resolve one question stem to a `question_type_catalog` code.

    `is_mcq` comes from `question_type_master`, which is authoritative about
    whether options were stored -- the stem text is not, because a narrative
    question can quote options it is asking the student to criticise.
    """
    plain = _strip(stem)

    for form, pattern in _FORM_PATTERNS:
        if pattern.search(plain):
            # An assertion-reason or match item is that form whether or not the
            # bank stored options for it. The rest are only their special form
            # if they are NOT a stored MCQ: "Calculate the resistance" with four
            # options is an MCQ that happens to be numerical, and the bank has
            # to render it as an MCQ or the options vanish.
            if form in ("assertion_reason", "match_following") or not (is_mcq or has_options):
                return form
            break

    # `question_type_master` and the stored options are facts; the stem is
    # evidence. Facts first.
    if is_mcq or has_options:
        return "mcq"

    # An MCQ whose options were never separated out of the stem. Only claim
    # this when the lead-in asks for a choice AND does not ask for work on each
    # part: a sub-part list mislabelled `mcq` would have its parts treated as
    # options, which is how an editor save silently destroys a question.
    labelled = _LABELLED_PARTS_RE.search(plain)
    if labelled:
        head = plain[: labelled.start()]
        chooses = bool(
            _CHOOSE_ONE_STRONG_RE.search(head) or _CHOOSE_ONE_TRAILING_RE.search(head)
        )
        if chooses and not _DO_EACH_RE.search(head):
            return "mcq"

    # Length decides the plain answer forms -- but a multi-part question is
    # sized by how much it asks for, not by how briefly it asks. "Give the
    # characteristic tests for the following gases: (a) CO2 (b) SO2 (c) O2
    # (d) H2" is 13 words and four answers.
    parts = len(_SUBPART_LABEL_RE.findall(plain))
    if parts >= 3:
        return "long"

    words = len([w for w in _NOISE_RUN_RE.sub(" ", plain).split() if any(c.isalnum() for c in w)])
    if parts >= 2:
        return "short" if words <= _SHORT_WORDS else "long"
    if words <= _VERY_SHORT_WORDS:
        return "very_short"
    if words <= _SHORT_WORDS:
        return "short"
    return "long"


def classify_row(row: dict[str, Any]) -> dict[str, Any]:
    """Derive form, marks, bloom, dok and difficulty for one stored question."""
    stem = _strip(row.get("question_title"))
    is_mcq = str(row.get("question_type") or "") == "multiple"
    form = classify_form(stem, is_mcq=is_mcq, has_options=bool(row.get("option_count")))

    bloom, dok = _classify_bloom(stem, form)
    marks = MARKS_BY_FORM.get(form, 1)

    # Marks nudge DOK the same way the tagger does, so the two agree: a 5-mark
    # "explain" is more chained reasoning than a 1-mark one.
    if marks >= 5 and dok < 3:
        dok += 1
    elif marks <= 1 and dok > 2:
        dok -= 1

    return {
        "id": int(row["id"]),
        "g_qtype_code": form,
        "points": marks,
        # _classify_bloom speaks PAL's lowercase vocabulary ("recall"); g_bloom
        # holds the LMS's Title-Case one ("Remember"). Both are live -- translate
        # at the boundary, as the tagger does, and never unify them.
        "g_bloom": _LMS_BLOOM.get(bloom, "Understand"),
        "g_dok": dok,
        # _lms_difficulty takes the tagger's 1-5 score, so map DOK onto it the
        # same way _offline_tags does rather than inventing a second scale.
        "g_difficulty": _lms_difficulty({1: 2, 2: 3, 3: 4, 4: 5}.get(dok, 3)),
    }


def _load(chapter_ids: list[int], *, only_untyped: bool) -> list[dict[str, Any]]:
    extra = " AND q.g_qtype_code IS NULL" if only_untyped else ""
    db = _session()
    try:
        return [
            dict(r)
            for r in db.execute(
                text(
                    f"""
                    SELECT q.id, q.question_title, q.points,
                           qt.question_type,
                           e.question_type_code AS sidecar_code,
                           (SELECT COUNT(*) FROM answer_master a
                             WHERE a.question_id = q.id) AS option_count
                      FROM lms_question_master q
                      JOIN question_type_master qt ON qt.id = q.question_type_id
                      LEFT JOIN lms_question_extraction e ON e.question_id = q.id
                     WHERE q.chapter_id IN :ids AND q.deleted_at IS NULL{extra}
                     ORDER BY q.id
                    """
                ),
                {"ids": tuple(chapter_ids)},
            ).mappings()
        ]
    finally:
        db.close()


def backfill(
    chapter_ids: list[int],
    *,
    only_untyped: bool = True,
    keep_marks: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Write g_qtype_code, points, g_bloom, g_dok and g_difficulty.

    An extraction sidecar wins on form where it has one: that code was read off
    the source document, and a derived guess must never overwrite a fact.
    `keep_marks` leaves `points` alone for banks where a human set them.
    """
    rows = _load(chapter_ids, only_untyped=only_untyped)
    report: dict[str, Any] = {
        "seen": len(rows), "written": 0, "from_sidecar": 0, "forms": {},
    }
    if not rows:
        return report

    updates = []
    for row in rows:
        derived = classify_row(row)
        sidecar = (row.get("sidecar_code") or "").strip()
        if sidecar in CATALOG_FORMS:
            derived["g_qtype_code"] = sidecar
            derived["points"] = MARKS_BY_FORM.get(sidecar, derived["points"])
            report["from_sidecar"] += 1
        if keep_marks and row.get("points"):
            derived["points"] = row["points"]
        report["forms"][derived["g_qtype_code"]] = (
            report["forms"].get(derived["g_qtype_code"], 0) + 1
        )
        updates.append(derived)

    if dry_run:
        report["written"] = len(updates)
        return report

    db = _session()
    try:
        for u in updates:
            db.execute(
                text(
                    """
                    UPDATE lms_question_master
                       SET g_qtype_code = :g_qtype_code,
                           points       = :points,
                           g_bloom      = :g_bloom,
                           g_dok        = :g_dok,
                           g_difficulty = :g_difficulty
                     WHERE id = :id
                    """
                ),
                u,
            )
            report["written"] += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    logger.info("typed %s question(s) across %s chapter(s)", report["written"], len(chapter_ids))
    return report


__all__ = [
    "CATALOG_FORMS",
    "MARKS_BY_FORM",
    "backfill",
    "classify_form",
    "classify_row",
]
