"""Draft item JSON from a question bank's extracted text.

    python -m scripts.parse_qbank_items --extraction 592 --out parts/
    python -m scripts.parse_qbank_items --extraction 592 --section objective
    python -m scripts.parse_qbank_items --standard 42 --subject 3975 --out parts/

This produces a DRAFT. Every item it emits is read against the source before it
loads -- the parser exists so a reader verifies and corrects rather than
transcribing two thousand stems by hand, not so the reading can be skipped.

What it knows about this book's shape, all measured rather than assumed:

  * Five section banners, letter-spaced arbitrarily in the PDF, so they are
    matched on letters alone: PAUSE AND PONDER, OBJECTIVE QUESTION, VERY SHORT
    ANSWER, SHORT ANSWER QUESTION, CASE BASED QUESTION. Raw forms in the text
    run to things like '\\x01VER Y SHO RT ANSWER' and 'SSHOR T ANSWER  QUESTION'
    -- the doubled first letter is a styled badge glyph, which is also why the
    answer marker reads 'AAns'.
  * Questions open with `N.` followed by a tab.
  * Options are `(A)` through `(D)`, tab separated.
  * The answer follows `Ans :`; for an MCQ its first parenthesised letter is
    the key.
  * Advertisement furniture is interleaved throughout and is stripped: the
    running head, `## Page N`, the pdf.tube footer, and the 'CBSE CLASS 12'
    cross-sell blocks that sit between chapters.

Anything the parser is unsure of it leaves for the reader rather than guessing:
a question whose option count is not four keeps whatever it found, and the
loader's V-09 will hold it rather than publish it wrong.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Banner -> (slug, item form). PAUSE AND PONDER carries answered reflective
# questions, so it is read like any other very-short section rather than
# skipped as front matter.
SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("PAUSEANDPONDE", "pause", "very_short"),
    # The book reprints the NCERT textbook exercise as its own block in 12 of
    # the 13 chapters. Missed on the first pass, so those questions were being
    # swept into whichever section preceded them. The banner truncates to
    # 'NCER T Exercis' in the text layer, hence the key without a trailing E.
    ("NCERTEXERCIS", "ncert", "short"),
    ("OBJECTIVEQUESTION", "objective", "mcq"),
    ("VERYSHORTANSWER", "veryshort", "very_short"),
    ("SHORTANSWERQUESTION", "short", "short"),
    # Present in all 13 chapters and missed on the first pass, so ten items per
    # chapter were filed as 3-mark short answers when the book prints them as
    # 5-mark long ones. Found by a reader noticing that a "short" file ended in
    # multi-part (a)/(b)/(c) questions.
    ("LONGANSWERQUESTION", "long", "long"),
    ("CASEBASEDQUESTION", "case", "case_study"),
)

BANNER_LINE = re.compile(r"^.{0,4}([A-Z][A-Z \t]{8,60})\s*$", re.M)
QUESTION_START = re.compile(r"^(\d{1,3})\.\t", re.M)
# UPPERCASE only. The book sets answer options as (A)-(D) and sub-parts of a
# multi-part question as (a)-(d), so a case-insensitive match turned "(a)
# Differentiate between a scientific law..." into an option and left the
# question looking like a one-option MCQ.
OPTION = re.compile(r"^\(([A-D])\)\t?\s*(.+?)\s*$", re.M)
# Just the label. An option is sliced from its label to the NEXT label, because
# the PDF wraps long choices and matching to end-of-line truncated 102 of
# chapter 2's 240 options to fragments like "It", "Massive", "Matthias".
OPTION_LABEL = re.compile(r"\(([A-D])\)\t?")
ANSWER = re.compile(r"\x01?A?Ans\s*:")
KEY_LETTER = re.compile(r"^\s*\x01?\s*\(([A-Da-d])\)")

# Everything the book prints that is not question content.
NOISE = re.compile(
    r"^(?:## Page \d+"
    r"|page\s+\d+\s*$"
    r"|Cbse \d+\w* science Chapterwise QB"
    r"|Downloaded from www\.pdf\.tube"
    r"|NODIA"
    r"|CBSE CLASS \d+"
    r"|Previous Year Solved Question Bank"
    r"|Click your Subject.*"
    r"|Order the Hard copy.*"
    r"|For Olympiad Books Visit.*"
    r"|Olympiad .*"
    r"|Worksheets?"
    r"|Mathematics|Science|Social Science|English|Hindi|Sanskrit"
    r"|IT \(\d+\)|AI \(\d+\)"
    r")\s*$",
    re.M,
)


def _squash(value: str) -> str:
    return re.sub(r"[^A-Z]", "", value.upper())


def _clean(block: str) -> str:
    block = NOISE.sub("", block)
    block = block.replace("\x01", " ")
    # Line breaks here are page layout, not sentence structure -- the PDF wraps
    # mid-clause -- so they collapse to spaces like any other whitespace.
    return re.sub(r"\s+", " ", block).strip()


def _banner_key(line: str) -> str | None:
    """The section this line announces, or None.

    Matched on the WHOLE line reduced to letters, not on containment. A
    containment test looked reasonable and was badly wrong: 'OBJECTIVE
    QUESTION' occurs inside ordinary sentences, and in chapter 13 one such
    sentence was taken for the banner and swallowed 62,000 characters into the
    wrong section, leaving that section with five items instead of forty.

    The leading letter is doubled on some banners ('SSHOR T ANSWER') because
    the PDF sets the first character as a styled badge glyph -- the same reason
    the answer marker reads 'AAns'. One such doubling is tolerated.
    """
    squashed = _squash(line)
    if len(squashed) < 10:
        return None
    candidates = [squashed]
    if len(squashed) > 1 and squashed[0] == squashed[1]:
        candidates.append(squashed[1:])
    for key, _slug, _form in SECTIONS:
        if key in candidates:
            return key
    return None


def find_sections(md: str) -> list[dict]:
    """Where each known banner starts, in document order."""
    hits: list[dict] = []
    offset = 0
    for line in md.split("\n"):
        key = _banner_key(line)
        if key:
            slug, form = next((s, f) for k, s, f in SECTIONS if k == key)
            hits.append({"slug": slug, "form": form,
                         "start": offset + len(line) + 1,
                         "banner": line.strip()})
        offset += len(line) + 1
    for index, hit in enumerate(hits):
        hit["end"] = hits[index + 1]["start"] if index + 1 < len(hits) else len(md)
    return hits


ASSERTION = re.compile(r"\bAssertion\b", re.I)
REASON = re.compile(r"\bReason\b", re.I)


def _infer_form(section_form: str, options: list, stem: str) -> str:
    """The item's own shape beats the section it sits under.

    The OBJECTIVE section is not uniformly multiple choice: in chapter 9 it
    carries "Write the formulae of the compounds formed from the following
    pairs of ions" and "Determine the formula unit mass", which have no options
    at all. Filing those as mcq made 151 items look like parser defects when
    they were simply a different kind of question, and would have had V-09 hold
    every one of them for having the wrong number of options.
    """
    if options:
        if ASSERTION.search(stem) and REASON.search(stem):
            return "assertion_reason"
        return "mcq"
    if section_form == "mcq":
        # Answered, no options, sitting among the objective questions: short
        # enough to be a very-short rather than a full short answer.
        return "very_short"
    return section_form


def parse_question(block: str, number: str, form: str, page: int | None) -> dict:
    """One question out of the text between two question numbers."""
    answer_match = ANSWER.search(block)
    body = block[: answer_match.start()] if answer_match else block
    answer_raw = block[answer_match.end():] if answer_match else ""

    # An option runs to the NEXT option, not to the end of its line. The PDF
    # wraps long choices, and matching only the first line truncated 102 of
    # chapter 2's 240 options to fragments like "It", "The", "Massive" and
    # "It is a hypotonic solution, causing water to".
    option_starts = [
        m for m in OPTION_LABEL.finditer(body) if m.start() == 0 or body[m.start() - 1] == "\n"
    ]
    options = []
    if option_starts:
        for index, match in enumerate(option_starts):
            stop = (option_starts[index + 1].start()
                    if index + 1 < len(option_starts) else len(body))
            text = _clean(body[match.end():stop])
            # "Assertion (A) :" wraps so "(A) :" starts its own line and reads
            # as an option whose whole text is a colon. That is punctuation.
            if len(text) > 1:
                options.append({"label": match.group(1), "text": text})
        if options:
            body = body[: option_starts[0].start()]

    form = _infer_form(form, options, _clean(body))

    item: dict = {
        "number": number,
        "form": form,
        "page": page,
        "stem": _clean(body),
        "answer": _clean(answer_raw),
    }
    if options:
        item["options"] = options
        key = KEY_LETTER.match(answer_raw)
        if key:
            item["correct_option"] = key.group(1).upper()
            # The key letter is part of the answer only as a label; the
            # explanation after it is what a learner should see.
            item["answer"] = _clean(answer_raw[key.end():]) or item["answer"]
    return item


def parse_extraction(md: str) -> dict[str, list[dict]]:
    """Draft items per section slug.

    The ANSWER MARKER is the anchor, not the question number. Every question in
    this book is answered exactly once, so one `Ans :` is one item and the
    marker count is the ground truth for how many there are.

    Numbering cannot play that role. Stems carry their own numbered lists
    ("Consider the following statements: 1. ... 2. ..."), and Pause and Ponder
    restarts at 1 after each summary topic -- in chapter 13 that section holds
    77 answers under numbering that resets repeatedly. Splitting on numbers
    shattered some questions and, once filtered to increasing numbers only,
    silently discarded most of that section.
    """
    out: dict[str, list[dict]] = {}
    for section in find_sections(md):
        chunk = md[section["start"]: section["end"]]
        answers = list(ANSWER.finditer(chunk))
        items: list[dict] = []
        cursor = 0
        for index, answer in enumerate(answers):
            # This item runs from where the last one ended to the start of the
            # NEXT answer; the split point between them is the last question
            # number after this answer, which begins the following question.
            stop = len(chunk)
            if index + 1 < len(answers):
                following = list(QUESTION_START.finditer(
                    chunk, answer.end(), answers[index + 1].start()))
                # The FIRST number after this answer opens the next question.
                # Taking the last one split inside list-type questions: the
                # preamble and statements 1..n-1 were glued onto the previous
                # item's answer and statement n became an orphan stem, in 11 of
                # chapter 2's 60 objective questions.
                stop = following[0].start() if following else answers[index + 1].start()
            block = chunk[cursor:stop]
            cursor = stop

            number_match = QUESTION_START.search(block)
            number = number_match.group(1) if number_match else str(len(items) + 1)
            if number_match:
                block = block[:number_match.start()] + block[number_match.end():]

            # The page is where the QUESTION is printed, so it is read back
            # from the question's own start. Reading back from the answer gave
            # the page the answer landed on, which differs whenever an item
            # straddles a page break -- nine of chapter 2's ten case studies
            # came out with no page at all and the tenth with the wrong one.
            page = None
            page_match = None
            for page_match in re.finditer(r"## Page (\d+)", chunk[:cursor] or chunk[:1]):
                pass
            if page_match:
                page = int(page_match.group(1))
            items.append(parse_question(block, number, section["form"], page))
        if items:
            out.setdefault(section["slug"], []).extend(items)
    return out


def report(slug: str, items: list[dict]) -> str:
    bad_options = sum(
        1 for i in items if i["form"] == "mcq" and len(i.get("options") or []) != 4
    )
    no_key = sum(1 for i in items if i["form"] == "mcq" and not i.get("correct_option"))
    no_answer = sum(1 for i in items if not i.get("answer"))
    long_option = sum(
        1 for i in items for o in (i.get("options") or []) if len(o["text"]) > 250
    )
    bits = [f"{len(items):>4} items"]
    if bad_options:
        bits.append(f"{bad_options} not-4-options")
    if no_key:
        bits.append(f"{no_key} no-key")
    if no_answer:
        bits.append(f"{no_answer} no-answer")
    if long_option:
        bits.append(f"{long_option} option>250")
    return f"  {slug:<12} " + "  ".join(bits)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--extraction", type=int, action="append")
    ap.add_argument("--standard", type=int)
    ap.add_argument("--subject", type=int)
    ap.add_argument("--section", help="only this slug")
    ap.add_argument("--out", help="directory for draft part files")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        if a.extraction:
            rows = db.execute(
                text(
                    "SELECT d.id, c.sort_order, c.id, c.chapter_name "
                    "  FROM document_extractions d JOIN chapter_master c ON c.id = d.chapter_id "
                    " WHERE d.id IN :ids"
                ).bindparams(__import__("sqlalchemy").bindparam("ids", expanding=True)),
                {"ids": a.extraction},
            ).fetchall()
        else:
            rows = db.execute(
                text(
                    "SELECT d.id, c.sort_order, c.id, c.chapter_name "
                    "  FROM document_extractions d JOIN chapter_master c ON c.id = d.chapter_id "
                    " WHERE d.document_type = 'question_bank' AND c.standard_id = :s "
                    "   AND (:su IS NULL OR c.subject_id = :su) ORDER BY c.sort_order"
                ),
                {"s": a.standard, "su": a.subject},
            ).fetchall()

        out_dir = Path(a.out) if a.out else None
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)

        grand = 0
        for eid, sort_order, chapter_id, name in rows:
            md = db.execute(
                text("SELECT md_content FROM document_extractions WHERE id = :i"),
                {"i": eid},
            ).scalar() or ""
            drafts = parse_extraction(md)
            total = sum(len(v) for v in drafts.values())
            grand += total
            print(f"\neid {eid} | ch {sort_order} | {name[:44]} | {total} draft item(s)")
            for slug, items in drafts.items():
                if a.section and slug != a.section:
                    continue
                print(report(slug, items))
                if out_dir:
                    path = out_dir / f"ch{sort_order:02d}_{slug}.json"
                    path.write_text(json.dumps(
                        {"chapter": sort_order, "chapter_id": chapter_id,
                         "extraction_id": eid, "section": slug, "items": items},
                        indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\n{grand} draft item(s) across {len(rows)} chapter(s)")
        if out_dir:
            print(f"written to {out_dir}")
        print("\nDRAFT ONLY - every item is read against the source before it loads.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
