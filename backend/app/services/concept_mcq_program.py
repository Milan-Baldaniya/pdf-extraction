"""A managed bank of 50 items per concept, balanced across difficulty and form.

The target is 50 questions for every `lms_concept`, split Easy / Medium / Hard,
spread across the `question_type_catalog` forms, each carrying a Bloom level, a
DOK level and its answer. The point is diagnosis: an adaptive test can only tell
you *which* gap a student has if the concept it is probing has enough items at
enough levels to separate "has not learnt it" from "cannot apply it".

Measured before this existed, chapter 1012 had 21 MCQs on "Precipitation
reaction" and 1 on "Prevention of rancidity". A concept with one question is a
concept the test cannot say anything about.

Four things here are load-bearing:

**The ladder is one closed table.** Difficulty, Bloom and DOK are three views of
the same judgement, and letting them be set independently is how a bank ends up
with an "Easy" question tagged `Analyze` at DOK 3. `LADDER` below is the single
source; everything else derives.

**Every form is first class.** An option-bearing item (mcq, assertion_reason,
true_false) stores its alternatives as `answer_master` rows with the key
flagged. Every other form is answered in prose and stores a model answer in the
same JSON envelope `answer_backfill` writes, so a bank of mixed forms reads
uniformly. A prose item with no model answer is REJECTED, because that is
precisely the state the 2,155 answerless narrative questions were in.

**The validator is a hard gate.** Thousands of items written quickly are
thousands of liabilities unless something checks them. It rejects the specific
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
import json
import logging
import re
import unicodedata
from typing import Any

from sqlalchemy import text

from app.db.mariadb import SessionLocal, init_mariadb
# One marks table for the whole estate. The backfill service assigns marks to
# questions already stored; this one assigns them to questions being authored,
# and a second copy here would drift from it.
from app.services.question_type_backfill import MARKS_BY_FORM

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
#
# For the same reason Medium admits Remember. Recalling the factorisation of
# a^3 + b^3 is harder than recalling (a + b)^2 but is no more cognitively
# complex; both are recall, and only the difficulty differs. Hard deliberately
# does NOT admit Remember: if it did, a bank could be entirely recall and still
# report a full difficulty spread, which is exactly the false signal the ladder
# exists to prevent.
LADDER: dict[str, dict[str, Any]] = {
    "Easy":   {"bloom": ("Remember", "Understand", "Apply"),            "dok": 1, "slots": 17},
    "Medium": {"bloom": ("Remember", "Understand", "Apply", "Analyze"), "dok": 2, "slots": 17},
    "Hard":   {"bloom": ("Analyze", "Evaluate", "Create"),              "dok": 3, "slots": 16},
}
TARGET_PER_CONCEPT = sum(v["slots"] for v in LADDER.values())  # 50

# A concept bank of nothing but MCQs cannot build a paper and cannot test
# whether a student can WRITE chemistry rather than recognise it. These are the
# 50 slots per concept, spread over the catalog forms.
TYPE_BLUEPRINT: dict[str, int] = {
    "mcq": 10,
    "very_short": 8,
    "short": 8,
    "assertion_reason": 4,
    "true_false": 4,
    "fill_blank": 4,
    "long": 4,
    "numerical": 3,
    "match_following": 2,
    "construction": 2,
    "proof": 1,
}

# Forms whose alternatives are stored as rows in `answer_master`. Everything
# else is answered in prose and carries a model answer in the JSON envelope on
# `lms_question_master.answer` instead.
OPTION_FORMS = frozenset({"mcq", "assertion_reason", "true_false"})

# How many options each option-bearing form must have. True/False has two;
# anything else with two options is a coin flip dressed up as a question.
OPTION_COUNT = {"mcq": 4, "assertion_reason": 4, "true_false": 2}

QUESTION_TYPE_NARRATIVE = 2  # question_type_master.id for 'narrative'

# How much prose a model answer must be to count as an answer. The rule exists
# to catch stubs, NOT to outlaw short answers: the correct answer to "An
# insoluble solid formed when two solutions react is called a ______" is the one
# word "precipitate", and a flat three-word minimum rejected every
# fill-in-the-blank in the first batch. Forms that ask for reasoning keep the
# higher bar.
_MIN_ANSWER_WORDS = {"fill_blank": 1, "very_short": 1}

# Tenancy. `sub_institute_id` on a shared content bank is a BOARD, not a
# school: 1 is CBSE, 341 is Cambridge. Getting this wrong publishes CBSE
# content into another board's bank.
CBSE = 1

OPTION_MAX = 250          # answer_master.answer is varchar(250)
STATUS_PUBLISHED = 1
STATUS_HELD = 0
QUESTION_TYPE_MCQ = 1     # question_type_master.id for 'multiple'

PROVENANCE = "authored-item-v1"

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
    # A leading minus is content, not punctuation. Stripping it collapsed the
    # options "-9" and "9" of a y-intercept question onto the same string and
    # reported two correct distractors as duplicates -- and sign errors are
    # exactly what those distractors exist to catch.
    text_ = re.sub(r"(?<![a-z0-9])-(?=[0-9.])", " minus ", text_)
    text_ = text_.replace("+", " plus ").replace("=", " equals ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text_).split())


# Greek letters and accented Latin letters appear in concept names, and plain
# `_norm` deletes anything outside a-z0-9 -- which turns "Irrationality of pi"
# into "irrationality of" and "Sierpinski Triangle" into "sierpi ski triangle".
# Both become names nobody can type, so an item file could never match them and
# the load would abort on a correctly spelled concept.
_GREEK = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta",
    "θ": "theta", "λ": "lambda", "μ": "mu", "π": "pi",
    "ρ": "rho", "σ": "sigma", "φ": "phi", "ω": "omega",
    "Δ": "delta", "Σ": "sigma", "Ω": "omega", "Π": "pi",
}


def _norm_concept(value: str) -> str:
    """Normalise a concept name so a typeable spelling matches the stored one.

    Greek letters become their English names and accents are folded to the base
    letter, so "Irrationality of π" matches "Irrationality of Pi" and
    "Sierpiński Triangle" matches "Sierpinski Triangle".
    """
    text_ = value or ""
    for ch, name in _GREEK.items():
        text_ = text_.replace(ch, f" {name} ")
    # NFKD splits an accented letter into base plus combining mark; dropping the
    # marks leaves the ASCII letter rather than deleting the letter entirely.
    decomposed = unicodedata.normalize("NFKD", text_)
    folded = "".join(c for c in decomposed if not unicodedata.combining(c))

    # Collapse adjacent repeated words. Concept names commonly spell a symbol
    # out alongside it -- "Pi (pi)" -- and expanding the symbol then yields
    # "pi pi", which no one would type. Adjacent repetition is never meaningful
    # in a concept name, so squeezing it makes both spellings agree.
    words = _norm(folded).split()
    squeezed = [w for i, w in enumerate(words) if i == 0 or w != words[i - 1]]
    return " ".join(squeezed)


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

def _validate_common(item: dict[str, Any]) -> tuple[list[str], str]:
    """Checks every form must pass, plus the resolved difficulty."""
    problems: list[str] = []

    stem = str(item.get("stem") or "").strip()
    if len(stem.split()) < 2 or len(stem) < 8:
        problems.append("stem is too short to be a question")
    if len(stem) > 2000:
        problems.append("stem is longer than 2000 characters")

    difficulty = str(item.get("difficulty") or "")
    if difficulty not in LADDER:
        problems.append(f"difficulty must be one of {list(LADDER)}, got {difficulty!r}")
        return problems, difficulty

    rung = LADDER[difficulty]
    bloom = str(item.get("bloom") or "")
    if bloom not in rung["bloom"]:
        problems.append(f"{difficulty} allows Bloom {rung['bloom']}, got {bloom!r}")
    dok = item.get("dok")
    if dok is not None and int(dok) != rung["dok"]:
        problems.append(f"{difficulty} is DOK {rung['dok']}, got {dok}")

    return problems, difficulty


def validate_written(item: dict[str, Any]) -> list[str]:
    """Problems that make a prose-answered item unusable.

    The whole point of a non-MCQ item is the model answer, so an item without
    one is not an item -- it is a prompt a teacher still has to do the work on.
    That is exactly the state the 2,155 answerless narrative questions were in.
    """
    problems, _ = _validate_common(item)

    form = str(item.get("form") or "")
    answer = str(item.get("answer") or "").strip()
    if not answer:
        problems.append("no model answer")
    elif len(answer.split()) < _MIN_ANSWER_WORDS.get(form, 3):
        problems.append("model answer is too short to be an answer")

    if form in OPTION_FORMS:
        problems.append(f"form {form!r} needs options, not a prose answer")
    elif form and form not in TYPE_BLUEPRINT:
        problems.append(f"unknown form {form!r}")

    # A match-the-following item is useless unless the answer states the
    # pairing; a fill-in-the-blank is useless unless the stem has a blank.
    if form == "match_following" and "-" not in answer and "," not in answer:
        problems.append("match_following answer does not state the pairing")
    if form == "fill_blank" and "___" not in str(item.get("stem") or ""):
        problems.append("fill_blank stem has no blank to fill")

    return problems


def validate_item(item: dict[str, Any]) -> list[str]:
    """Validate any item, dispatching on its catalog form."""
    form = str(item.get("form") or "mcq")
    return validate_mcq(item) if form in OPTION_FORMS else validate_written(item)


def validate_mcq(item: dict[str, Any]) -> list[str]:
    """Problems that make an option-bearing item unusable."""
    problems: list[str] = []

    stem = str(item.get("stem") or "").strip()
    # Deliberately loose. The rule exists to catch a stem that was truncated or
    # never written, not to outlaw terse ones: "2Na means" is a perfectly good
    # two-word question.
    if len(stem.split()) < 2 or len(stem) < 8:
        problems.append("stem is too short to be a question")
    if len(stem) > 2000:
        problems.append("stem is longer than 2000 characters")

    form = str(item.get("form") or "mcq")
    wanted = OPTION_COUNT.get(form, 4)
    options = item.get("options") or []
    if not isinstance(options, list) or len(options) != wanted:
        got = len(options) if isinstance(options, list) else "none"
        problems.append(f"{form} needs exactly {wanted} options, got {got}")
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


def concept_index(chapter_id: int) -> dict[str, int]:
    """Normalised concept name -> id, for one chapter.

    Authoring 1,050 items across 21 chapters against numeric concept ids is how
    questions end up on the wrong concept -- silently, because a wrong id is
    still a valid id. A name is checkable by eye, so item files carry the name
    and this resolves it. Matching ignores case and punctuation, since "Ohm's
    Law" and "Ohms Law" are plainly the same concept and a whole file should not
    fail over an apostrophe.
    """
    db = _session()
    try:
        rows = db.execute(
            text("SELECT id, name FROM lms_concept WHERE chapter_id = :c"),
            {"c": chapter_id},
        ).fetchall()
    finally:
        db.close()
    return {_norm_concept(name): int(cid) for cid, name in rows if name}


def _existing_by_form(concept_ids: list[int]) -> dict[int, dict[str, int]]:
    """Per concept, how many items of each catalog form exist.

    A concept holding 50 items that are all MCQs meets the count and misses the
    point, so the gap has to be reported per form and not only as a total.
    """
    if not concept_ids:
        return {}
    db = _session()
    try:
        rows = db.execute(
            text(
                """
                SELECT q.concept_id, COALESCE(q.g_qtype_code, 'untyped') AS f, COUNT(*)
                  FROM lms_question_master q
                 WHERE q.concept_id IN :ids AND q.deleted_at IS NULL
                 GROUP BY q.concept_id, f
                """
            ),
            {"ids": tuple(concept_ids)},
        ).fetchall()
    finally:
        db.close()
    out: dict[int, dict[str, int]] = {}
    for concept_id, form, n in rows:
        out.setdefault(int(concept_id), {})[str(form)] = int(n)
    return out


def _existing_by_difficulty(concept_ids: list[int]) -> dict[int, dict[str, int]]:
    if not concept_ids:
        return {}
    db = _session()
    try:
        rows = db.execute(
            text(
                """
                -- Every form counts towards the 50, not just the MCQs. The
                -- original query joined question_type_master and filtered on
                -- 'multiple', which was right while the programme was MCQ-only
                -- and silently hid every prose item once it was not.
                SELECT q.concept_id, COALESCE(q.g_difficulty, 'Unset') AS d, COUNT(*) AS n
                  FROM lms_question_master q
                 WHERE q.concept_id IN :ids
                   AND q.deleted_at IS NULL
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
    ids = [int(c["id"]) for c in concepts]
    existing = _existing_by_difficulty(ids)
    by_form = _existing_by_form(ids)

    plan = []
    for concept in concepts:
        have = existing.get(int(concept["id"]), {})
        forms = by_form.get(int(concept["id"]), {})
        gap = {
            level: max(0, rung["slots"] - have.get(level, 0))
            for level, rung in LADDER.items()
        }
        form_gap = {
            form: max(0, want - forms.get(form, 0))
            for form, want in TYPE_BLUEPRINT.items()
        }
        plan.append({
            **concept,
            "have": have,
            "have_total": sum(have.values()),
            "gap": gap,
            "gap_total": sum(gap.values()),
            "forms": forms,
            "form_gap": form_gap,
            "form_gap_total": sum(form_gap.values()),
        })
    return plan


# ------------------------------------------------------------------- writing

def _answer_envelope(answer: str, *, marks: int, author: str) -> str:
    """The JSON envelope the bank reads a prose answer out of.

    Same shape and the same provenance stamp `answer_backfill` writes, so a
    teacher reading the bank cannot tell an authored answer for a NEW question
    from an authored answer backfilled onto an OLD one -- and in both cases can
    tell it apart from a publisher's marking scheme.
    """
    return json.dumps(
        {
            "model_answer": answer,
            "v": "authored-item-1.0",
            "marks": marks,
            "answer_origin": "authored",
            "answer_author": author,
        },
        ensure_ascii=False,
    )


def write_items(
    concept_id: int,
    items: list[dict[str, Any]],
    *,
    created_by: int = 1,
    sub_institute_id: int = CBSE,
    publish_clean: bool = True,
    dry_run: bool = False,
    author: str = "claude-opus-5",
) -> dict[str, Any]:
    """Store authored items of any catalog form against one concept.

    No extraction sidecar is written: these questions have no source document,
    and claiming one would make them look reproduced. An item that fails
    validation is not stored at all -- storing a broken question held for
    review just moves the problem to a teacher.
    """
    report: dict[str, Any] = {
        "concept_id": concept_id, "written": 0, "rejected": 0,
        "duplicate": 0, "problems": [], "by_difficulty": {}, "by_form": {},
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
            problems = validate_item(item)
            if problems:
                report["rejected"] += 1
                report["problems"].append({"index": index, "problems": problems,
                                           "stem": str(item.get("stem"))[:90]})
                continue

            form = str(item.get("form") or "mcq")
            # Hash over the stem plus whatever the item's alternatives are. For
            # a prose item there are none, so the stem alone identifies it.
            parts = (
                [str(o["text"]).strip() for o in item["options"]]
                if form in OPTION_FORMS else []
            )
            digest = content_hash(item["stem"], parts)
            if digest in seen:
                report["duplicate"] += 1
                continue
            seen.add(digest)
            # Resolve marks here rather than at write time, so a --dry run
            # exercises the same lookups the real run does. A dry run that
            # stops short of the writer cannot catch a writer bug, which is
            # exactly how a missing MARKS_BY_FORM import survived one.
            accepted.append((item, digest, MARKS_BY_FORM.get(form, 1)))

        if dry_run:
            report["written"] = len(accepted)
            for item, _, _marks in accepted:
                d = item["difficulty"]
                f = str(item.get("form") or "mcq")
                report["by_difficulty"][d] = report["by_difficulty"].get(d, 0) + 1
                report["by_form"][f] = report["by_form"].get(f, 0) + 1
            return report

        for item, digest, marks in accepted:
            difficulty = item["difficulty"]
            rung = LADDER[difficulty]
            form = str(item.get("form") or "mcq")
            has_options = form in OPTION_FORMS
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
                         :concept_id, :concept_name, :stem, :description, :marks,
                         0, :tenant, :status, :created_by,
                         :answer, :bloom, :difficulty, :dok, :form,
                         :digest, :explanation)
                    """
                ),
                {
                    "qtype": QUESTION_TYPE_MCQ if has_options else QUESTION_TYPE_NARRATIVE,
                    "marks": marks,
                    "form": form,
                    # An option-bearing item's answer is the flagged row in
                    # answer_master, so the envelope stays empty for those.
                    # A prose item's answer IS the envelope.
                    "answer": "" if has_options else _answer_envelope(
                        str(item["answer"]).strip(), marks=marks, author=author
                    ),
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
                    "explanation": str(item.get("explanation") or "").strip()[:60000],
                },
            )
            question_id = int(db.execute(text("SELECT LAST_INSERT_ID()")).scalar())

            for option in (item.get("options") or []) if has_options else []:
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
            report["by_form"][form] = report["by_form"].get(form, 0) + 1

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    logger.info("wrote %s item(s) on concept %s", report["written"], concept_id)
    return report


# Kept so the MCQ-only item files already on disk keep loading unchanged.
write_mcqs = write_items


__all__ = [
    "LADDER",
    "OPTION_FORMS",
    "TYPE_BLUEPRINT",
    "validate_item",
    "validate_written",
    "write_items",
    "TARGET_PER_CONCEPT",
    "content_hash",
    "plan_chapter",
    "validate_mcq",
    "write_mcqs",
]