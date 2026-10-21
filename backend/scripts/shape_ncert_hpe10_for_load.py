"""Verify and shape the hand-read NCERT Class X HPE exercises for loading.

    python -m scripts.shape_ncert_hpe10_for_load
    python -m scripts.shape_ncert_hpe10_for_load --only 4,5 --verbose

Reads `scripts/ncert_hpe10_items/chNN.json` and writes
`scripts/ncert_hpe10_items/load/chNN.json` in the shape `persist_supplied`
expects, keeping only the items that pass verification.

WHY THIS SCRIPT EXISTS AT ALL

CBSE Health and Physical Education for Classes IX-X is 100% internal
assessment. There is no written paper, no chapter-wise examination syllabus and
no marking scheme, so unlike every other subject in this bank there is no
official answer key to read -- and the NCERT textbook prints none either. Every
answer here was therefore DERIVED from the chapter's own prose.

A derived answer is only worth loading if the derivation can be checked, so each
authored item carries a `grounding` list: quotes copied out of the chapter. This
script re-extracts the text layer from the MIRRORED PDF (not from any
intermediate file, which could have drifted) and refuses any item whose quotes
are not actually in the chapter. An item that fails is dropped and named, never
silently downgraded. That is the whole guarantee: if a quote does not match, the
answer was not read off the page.

THE CHECKS

  G-01  every grounding quote appears in the chapter text
  G-02  at least one grounding quote is 40+ characters (a 6-word quote can
        corroborate almost anything)
  G-03  a verbatim item's stem appears in the chapter text
  G-04  on a fill_blank or true_false item, every NUMBER in the answer appears
        in the grounding, and the answer shares a real word with it. Numbers are
        exactly where a wrong key hides: "the court is 13 x 6 m" reads as
        confidently as "13.40 m x 6.10 m" and only one of them is the book's.
  G-05  four options and a key among them, on an mcq
  G-06  no option longer than the 250 characters answer_master stores
  G-07  every string is ASCII (see below)
  G-08  the item numbering is unique within the chapter
  G-09  form, bloom, dok and difficulty are inside their closed sets

ASCII. `lms_question_master.answer` is utf8mb3. A 4-byte character makes MariaDB
reject the whole row and the writer's retry loop cannot recover from it, so the
row is simply lost. NCERT's text layer is full of curly quotes, en dashes and
bullet glyphs, which are 3-byte and would survive -- but folding everything to
ASCII costs nothing and removes the class of failure. A character with no
mapping is an ERROR, not a silent drop, so nothing is quietly mangled.

PAGES. Items are authored against the page banner of the chapter PDF. What is
stored is the BOOK FOLIO, because `pdf_url` points at that chapter PDF and the
folio is the number printed on the page a reader will turn to. The two differ by
the chapter's start folio, which is taken from the book's own contents page.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import fitz  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ITEMS = Path(__file__).resolve().parent / "ncert_hpe10_items"
LOAD = ITEMS / "load"
MIRROR = ROOT / "data" / "qbank" / "mirror" / "ncert_c10_hpe"

SOURCE_BASE = "https://ncert.nic.in/textbook/pdf/"
PUBLISHER = "ncert_hpe_textbook_derived"
STANDARD_ID = 43
STANDARD = 10
SUBJECT = "Health and Physical Education"

# ---------------------------------------------------------------------------
# THE ALIGNMENT. Our 13 rows are a paraphrase register of the same 13 NCERT
# chapters, in the same order; only four names match outright. Nothing is
# renamed -- the load maps THROUGH this table. `db_name` is recorded so a later
# reader can see which row a number meant at the time, and the setup script
# re-checks it against chapter_master rather than trusting it.
#
# `folio` is the book page the chapter opens on, from the contents page, and is
# what turns an authored PDF-page number into the printed page number.
#
# `file` is the mirrored file name. `url_file`, where present, is what NCERT
# actually serves: chapters 6, 8 and 13 were uploaded with a DOUBLE DOT before
# the extension, so `jehp106.pdf` answers a flat 404 while `jehp106..pdf` is
# the real file. The site's own viewer builds the broken name, which is why
# those three chapters cannot be downloaded from the book's own page at all --
# the complete-book zip is what revealed the real names. They are mirrored
# under the clean name and fetched from the odd URL, and it is the odd URL that
# goes into `document_extractions.pdf_url`, because that is where the bytes
# came from.
# ---------------------------------------------------------------------------
ALIGNMENT: list[dict] = [
    # NCERT is inconsistent with itself on chapter 1: the contents page reads
    # "Relation with other Subjects", the chapter opener and the running head
    # read "Relationship with other Subjects". The contents-page form is used
    # here because that is the book's own table of contents, and the variant is
    # recorded so a later search on either string finds this row.
    {"n": 1, "chapter_id": 23768, "folio": 1, "file": "jehp101.pdf",
     "ncert": "Physical Education: Relation with other Subjects",
     "ncert_variant": "Physical Education: Relationship with other Subjects",
     "db_name": "Physical Education: Meaning, Aims and Objectives"},
    {"n": 2, "chapter_id": 23769, "folio": 11, "file": "jehp102.pdf",
     "ncert": "Effects of Physical Activities on Human Body",
     "db_name": "Effects of Physical Activity on the Organ Systems"},
    {"n": 3, "chapter_id": 23770, "folio": 23, "file": "jehp103.pdf",
     "ncert": "Growth and Development during Adolescence",
     "db_name": "Growth and Development during Adolescence"},
    {"n": 4, "chapter_id": 23771, "folio": 35, "file": "jehp104.pdf",
     "ncert": "Individual Games and Sports I",
     "db_name": "Individual Sports: Track and Field"},
    {"n": 5, "chapter_id": 23772, "folio": 52, "file": "jehp105.pdf",
     "ncert": "Individual Games and Sports II",
     "db_name": "Individual Sports: Badminton"},
    {"n": 6, "chapter_id": 23773, "folio": 77, "file": "jehp106.pdf", "url_file": "jehp106..pdf",
     "ncert": "Team Games and Sports I",
     "db_name": "Team Games and Sports"},
    {"n": 7, "chapter_id": 23774, "folio": 111, "file": "jehp107.pdf",
     "ncert": "Team Games and Sports II",
     "db_name": "Indigenous Team Games: Kabaddi"},
    {"n": 8, "chapter_id": 23775, "folio": 133, "file": "jehp108.pdf", "url_file": "jehp108..pdf",
     "ncert": "Yoga for Healthy Living",
     "db_name": "Stress Management through Yoga"},
    {"n": 9, "chapter_id": 23776, "folio": 165, "file": "jehp109.pdf",
     "ncert": "Dietary Considerations and Food Quality",
     "db_name": "Dietary Planning and Food Safety"},
    {"n": 10, "chapter_id": 23777, "folio": 181, "file": "jehp110.pdf",
     "ncert": "Safety Measures for Healthy Living",
     "db_name": "Safety at the Workplace and First Aid"},
    {"n": 11, "chapter_id": 23778, "folio": 193, "file": "jehp111.pdf",
     "ncert": "Healthy Community Living",
     "db_name": "Healthy Community Living"},
    {"n": 12, "chapter_id": 23779, "folio": 205, "file": "jehp112.pdf",
     "ncert": "Social Health",
     "db_name": "Social Health"},
    {"n": 13, "chapter_id": 23780, "folio": 215, "file": "jehp113.pdf", "url_file": "jehp113..pdf",
     "ncert": "Agencies and Awards Promoting Health, Sports and Yoga",
     "db_name": "Agencies and Awards Promoting Health, Sports and Yoga"},
]
BY_N = {row["n"]: row for row in ALIGNMENT}


def source_url(row: dict) -> str:
    """NCERT's own URL for this chapter -- the odd name where there is one."""
    return SOURCE_BASE + (row.get("url_file") or row["file"])

FORMS = {"mcq": 1, "true_false": 1, "fill_blank": 1, "match_following": 4,
         "very_short": 2, "short": 3, "long": 5}
BLOOM = {"recall", "understand", "apply", "analyze", "evaluate", "create"}
DIFFICULTY = {"easy", "medium", "hard"}

# ---------------------------------------------------------------------------
# ASCII folding
# ---------------------------------------------------------------------------
FOLD = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "′": "'", "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "―": "-", "−": "-", "­": "-",
    "…": "...", "×": "x", "÷": "/",
    "°": " degrees", "·": "-", "•": "-", "▪": "-",
    "●": "-", "◦": "-", "⁃": "-", "∙": "-",
    " ": " ", " ": " ", " ": " ", " ": " ",
    "​": "", "‌": "", "‍": "", "﻿": "",
    "→": "->", "←": "<-", "↔": "<->",
    "½": "1/2", "¼": "1/4", "¾": "3/4", "⅓": "1/3",
    "©": "(c)", "®": "(R)", "™": "(TM)",
    "₹": "Rs.", "£": "GBP", "€": "EUR",
    "é": "e", "è": "e", "ê": "e", "á": "a", "à": "a",
    "í": "i", "ó": "o", "ú": "u", "ü": "u", "ö": "o",
    "ä": "a", "ñ": "n", "ç": "c", "ā": "a", "ū": "u",
    "ī": "i", "ś": "s", "ṣ": "s", "ṭ": "t", "ḍ": "d",
    "ṇ": "n", "ṅ": "n", "ø": "o", "å": "a",
    "‑": "-", "": "-", "": " ", "": "-",
}


def fold(value: str, *, where: str, bad: list[str]) -> str:
    """Fold to ASCII. An unmapped character is reported, not dropped."""
    out: list[str] = []
    for ch in value:
        if ord(ch) < 128:
            out.append(ch)
            continue
        if ch in FOLD:
            out.append(FOLD[ch])
            continue
        decomposed = unicodedata.normalize("NFKD", ch)
        stripped = "".join(c for c in decomposed if ord(c) < 128)
        if stripped.strip():
            out.append(stripped)
            continue
        bad.append(f"{where}: U+{ord(ch):04X} {unicodedata.name(ch, '?')}")
        out.append(" ")
    return "".join(out)


_WS = re.compile(r"\s+")
_UNDER = re.compile(r"_{2,}")
# C0 CONTROL BYTES IN THE TEXT LAYER. Chapter 3 sets each "Choose the Correct
# Option" statement and its "(Yes/No/Don't know)" legend with a literal
# BACKSPACE (0x08) between them. `\s` does not match it, so a stem copied
# correctly off the page did not contain the legend and every one of those eight
# items was rejected as not being in the chapter. They carry no text, so they
# become spaces.
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_DOTS = re.compile(r"\.{3,}|…+|+")


_HYPHEN_WRAP = re.compile(r"-\s+")


def norm(value: str) -> str:
    """Whitespace-insensitive, blank-length-insensitive comparison form.

    The text layer wraps mid-sentence and a printed blank is a run of
    underscores whose length carries no meaning, so both are flattened. Case is
    NOT flattened: a quote that differs in case was retyped, not copied, and
    retyping is exactly what this check exists to catch.

    A line that breaks inside a hyphenated word is the awkward case. "the game
    of Kho-Kho" is set as "Kho-" / "Kho", and collapsing the newline to a space
    leaves "Kho- Kho", which does not contain "Kho-Kho" -- so a stem copied
    correctly off the page fails. The space after a hyphen is therefore dropped,
    on BOTH the quote and the chapter, which can only ever make the two agree
    about hyphen spacing and never make them disagree.
    """
    bad: list[str] = []
    value = fold(value, where="cmp", bad=bad)
    value = _CTRL.sub(" ", value)
    value = _UNDER.sub("__", value)
    value = _DOTS.sub("__", value)
    # NCERT's dot-leader glyphs in the contents and the "........" answer
    # blanks both flatten to the same token as an underscore blank.
    value = value.replace("\t", " ")
    value = _WS.sub(" ", value).strip()
    return _HYPHEN_WRAP.sub("-", value)


def dehyphenate(value: str) -> str:
    """`norm`, but a wrap hyphen is removed rather than kept.

    Where the break falls inside a word that is not hyphenated in print --
    "categor-" / "ised" -- the hyphen belongs to the typesetting, not the word,
    and a reader quoting the sentence writes "categorised". Comparing against
    both forms accepts the quote either way; a quote is checked against this
    form only after the primary one has already failed.
    """
    return _HYPHEN_WRAP.sub("", norm(value))


def contains(chapter: tuple[str, str], quote: str) -> bool:
    """Is `quote` in the chapter, under either hyphen convention?"""
    return norm(quote) in chapter[0] or dehyphenate(quote) in chapter[1]


def flat(value: object, *, where: str, bad: list[str]) -> str:
    """One-line, ASCII, control-free -- the form that gets STORED."""
    return _WS.sub(" ", _CTRL.sub(
        " ", fold(str(value or ""), where=where, bad=bad))).strip()


_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_WORD = re.compile(r"[A-Za-z]{4,}")
# An ordered-list marker in an answer -- "(1)", "(iii)", "(b)". The digit in
# "(2)" is the second bullet, not a measurement, and counting it as an unsourced
# number rejected a correct five-part answer.
_ENUM = re.compile(r"\((?:\d{1,2}|[ivxlcdm]{1,5}|[a-h])\)", re.IGNORECASE)
# A cross-reference, not a measurement: "Fig. 6.2 labels the ring 18 inch wide"
# is grounded on the figure's own label, and 6.2 is the figure's number. Left
# in, it read as an unsourced quantity and rejected a correct answer.
_XREF = re.compile(
    r"\b(?:fig|figure|table|chapter|chap|ch|activity|section|page|box)s?\.?\s*"
    r"\d+(?:\.\d+)?", re.IGNORECASE)


def sourced(number: str, pool: str) -> bool:
    """Is `number` in `pool` as a whole number rather than as a substring?

    A substring test is wrong in both directions: "2" is inside "12 x 12", so a
    fabricated 2 passes, while a genuine 2 next to a fabricated 5 gets the item
    rejected for the wrong reason. Both happened.
    """
    return re.search(r"(?<![\d.,])" + re.escape(number) + r"(?![\d])",
                     pool) is not None

# Words that would satisfy G-04's "shares a real word" test without meaning
# anything -- a true/false answer says "False, the chapter states ..." whatever
# the chapter states.
_STOP = {
    "true", "false", "chapter", "states", "state", "text", "book", "textbook",
    "says", "said", "that", "this", "these", "those", "which", "there", "here",
    "with", "from", "have", "having", "been", "because", "while", "also",
    "only", "both", "each", "every", "than", "then", "they", "their", "them",
    "will", "would", "shall", "should", "must", "does", "doing", "when",
    "what", "into", "over", "under", "about", "given", "gives", "given",
    "answer", "question", "printed", "prints", "according", "given",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="comma-separated chapter numbers")
    ap.add_argument("--verbose", action="store_true",
                    help="print every rejected item, not just the count")
    a = ap.parse_args()

    wanted = ({int(x) for x in a.only.split(",") if x.strip()} if a.only
              else set(BY_N))
    LOAD.mkdir(parents=True, exist_ok=True)

    head = (f"{'ch':<3} {'src':>4} {'kept':>5} {'cut':>4} {'author':>7} "
            f"{'marks':>6}  forms")
    print(head)
    print("-" * 96)
    rejects: list[str] = []
    unmapped: list[str] = []
    totals = {"src": 0, "kept": 0, "cut": 0, "authored_drop": 0, "marks": 0}

    for n in sorted(wanted):
        row = BY_N[n]
        src = ITEMS / f"ch{n:02d}.json"
        if not src.exists():
            print(f"{n:<3} {'-':>4} {'-':>5} {'-':>4} {'-':>7} {'-':>6}  "
                  f"MISSING {src.name}")
            continue
        data = json.loads(src.read_text(encoding="utf-8"))

        pdf = MIRROR / row["file"]
        doc = fitz.open(pdf)
        pages = [page.get_text("text") for page in doc]
        doc.close()
        raw_text = "\n".join(pages)
        chapter = (norm(raw_text), dehyphenate(raw_text))

        kept: list[dict] = []
        cut: list[dict] = []
        seen_numbers: set[str] = set()
        forms: dict[str, int] = {}

        for entry in data.get("items") or []:
            number = str(entry.get("number") or "")
            fails: list[str] = []

            form = entry.get("form")
            if form not in FORMS:
                fails.append(f"G-09 form {form!r}")
            if entry.get("bloom") and str(entry["bloom"]).lower() not in BLOOM:
                fails.append(f"G-09 bloom {entry['bloom']!r}")
            if entry.get("difficulty") and \
                    str(entry["difficulty"]).lower() not in DIFFICULTY:
                fails.append(f"G-09 difficulty {entry['difficulty']!r}")
            dok = entry.get("dok")
            if dok is not None and not (isinstance(dok, int) and 1 <= dok <= 4):
                fails.append(f"G-09 dok {dok!r}")
            if number in seen_numbers:
                fails.append(f"G-08 duplicate number {number!r}")
            seen_numbers.add(number)

            bad: list[str] = []
            stem = flat(entry.get("stem"),
                        where=f"ch{n:02d} {number} stem", bad=bad)
            answer = flat(entry.get("answer"),
                          where=f"ch{n:02d} {number} answer", bad=bad)
            options = []
            for opt in entry.get("options") or []:
                options.append({
                    "label": str(opt["label"]).upper()[:2],
                    "text": flat(opt["text"],
                                 where=f"ch{n:02d} {number} option", bad=bad),
                })
            grounding = [
                flat(q, where=f"ch{n:02d} {number} grounding", bad=bad)
                for q in (entry.get("grounding") or [])
            ]
            unmapped.extend(bad)

            if not stem:
                fails.append("G-03 empty stem")
            if not answer:
                fails.append("empty answer")

            # G-01 / G-02 -- the grounding must really be in the chapter.
            if not grounding:
                fails.append("G-01 no grounding")
            for quote in grounding:
                if len(quote) < 12:
                    fails.append(f"G-01 quote too short: {quote!r}")
                elif not contains(chapter, quote):
                    fails.append(f"G-01 quote not in chapter: {quote[:70]!r}")
            if grounding and max(len(q) for q in grounding) < 40:
                fails.append("G-02 no grounding quote of 40+ characters")

            # G-03 -- a verbatim stem must be on the page.
            reproduction = entry.get("reproduction") or "verbatim"
            if reproduction == "verbatim" and stem and not contains(chapter, stem):
                fails.append(f"G-03 stem not in chapter: {stem[:70]!r}")
            if reproduction != "verbatim" and not entry.get("adaptation"):
                fails.append("G-03 adapted stem with no adaptation note")

            # G-04 -- a one-mark factual answer must not carry a number, or a
            # word of substance, that the grounding does not.
            if form in {"fill_blank", "true_false"} and grounding:
                # The STEM counts as well as the grounding. A true/false answer
                # that refutes the question quotes the question's own figure --
                # "False, a match has two innings, not 4" -- and 4 comes from a
                # stem this script has already matched against the chapter, so
                # it is not an unsourced number. Counting it as unsourced
                # rejected a correct answer.
                pool = norm(" ".join(grounding) + " " + stem).lower()
                body = re.sub(r"^\s*(true|false|yes|no)\b[\s,.:;-]*", "",
                              answer, flags=re.IGNORECASE)
                body = _XREF.sub(" ", _ENUM.sub(" ", body))
                missing = [m for m in _NUM.findall(body)
                           if not sourced(m, pool)
                           and not sourced(m.replace(",", ""), pool)]
                if missing:
                    fails.append(
                        f"G-04 number(s) not in grounding: {', '.join(missing)}")
                words = {w.lower() for w in _WORD.findall(body)} - _STOP
                if words and not (words & set(_WORD.findall(pool))):
                    fails.append("G-04 answer shares no substantive word "
                                 "with its grounding")

            # G-05 / G-06 -- option shape.
            if form == "mcq":
                if len(options) != 4:
                    fails.append(f"G-05 {len(options)} options, expected 4")
                key = str(entry.get("correct_option") or "").upper()
                if not key:
                    fails.append("G-05 no correct_option")
                elif key not in {o["label"] for o in options}:
                    fails.append(f"G-05 key {key!r} not among the options")
                # An MCQ answer here opens with the letter and then justifies
                # it -- "B. The chapter's criteria include ...". If that letter
                # and `correct_option` disagree, one of the two is wrong and
                # nothing downstream would notice: the writer keys the option
                # flag off `correct_option` while a marker reads the prose. The
                # estate has already found a bank where the printed letter
                # contradicted the printed value.
                head = re.match(r"\s*([A-D])\s*[.)\]:-]", answer)
                if key and head and head.group(1).upper() != key:
                    fails.append(
                        f"G-05 answer opens with {head.group(1).upper()!r} but "
                        f"correct_option is {key!r}")
            for opt in options:
                if len(opt["text"]) > 250:
                    fails.append(f"G-06 option {opt['label']} over 250 chars")

            if fails:
                cut.append({"number": number, "stem": stem[:120],
                            "failures": fails})
                continue

            marks = entry.get("marks") or FORMS[form]
            pdf_page = entry.get("page")
            try:
                folio = row["folio"] + int(pdf_page) - 1
            except (TypeError, ValueError):
                folio = None
            item = {
                "number": number,
                "form": form,
                "marks": marks,
                "page": folio,
                "section_heading": (fold(str(entry.get("section_heading") or ""),
                                         where="heading", bad=unmapped)[:191]
                                    or None),
                "stem": stem,
                "answer": answer,
                "reproduction": reproduction,
                "bloom": (str(entry["bloom"]).lower()
                          if entry.get("bloom") else None),
                "dok": dok,
                "difficulty": (str(entry["difficulty"]).lower()
                               if entry.get("difficulty") else None),
                # Ignored by shape(); kept in the file so the derivation
                # travels with the item and a reviewer never has to take the
                # answer on trust.
                "grounding": grounding,
            }
            if options:
                item["options"] = options
            if entry.get("correct_option"):
                item["correct_option"] = str(entry["correct_option"]).upper()
            if entry.get("adaptation"):
                item["adaptation"] = fold(str(entry["adaptation"]),
                                          where="adaptation", bad=unmapped)
            kept.append(item)
            forms[form] = forms.get(form, 0) + 1

        # `setup_ncert_hpe10_extractions` stamps the shaped file with the
        # extraction_id it created, and the loader refuses to run without one.
        # Re-shaping must therefore CARRY THAT STAMP FORWARD: writing a fresh
        # dict over it would silently un-stamp every chapter, and the next
        # loader run would stop with "no extraction_id" on work that had
        # already been set up.
        previous = LOAD / f"ch{n:02d}.json"
        stamp = None
        if previous.exists():
            try:
                stamp = json.loads(previous.read_text(
                    encoding="utf-8")).get("extraction_id")
            except ValueError:
                stamp = None

        out = {
            "chapter": n,
            "chapter_id": row["chapter_id"],
            "standard_id": STANDARD_ID,
            "standard": STANDARD,
            "subject_name": SUBJECT,
            "ncert_title": row["ncert"],
            "db_chapter_name": row["db_name"],
            "source_url": source_url(row),
            "mirror_file": row["file"],
            "publisher": PUBLISHER,
            "answer_provenance": (
                "Questions reproduced verbatim from the chapter's printed "
                "Assessment. Answers DERIVED from the chapter prose -- the "
                "textbook prints no key and CBSE publishes none for this "
                "subject, which is 100% internal assessment. Each item's "
                "grounding quotes were re-verified against the mirrored PDF."
            ),
            "items": kept,
            "rejected": cut,
            "authored_dropped": data.get("dropped") or [],
        }
        if stamp:
            out["extraction_id"] = stamp
        previous.write_text(json.dumps(out, indent=1, ensure_ascii=False),
                            encoding="utf-8")

        marks = sum(i["marks"] for i in kept)
        n_src = len(data.get("items") or [])
        n_auth = len(out["authored_dropped"])
        totals["src"] += n_src
        totals["kept"] += len(kept)
        totals["cut"] += len(cut)
        totals["authored_drop"] += n_auth
        totals["marks"] += marks
        shape = " ".join(f"{k}:{v}" for k, v in sorted(forms.items()))
        print(f"{n:<3} {n_src:>4} {len(kept):>5} {len(cut):>4} {n_auth:>7} "
              f"{marks:>6}  {shape}")
        for bad_item in cut:
            rejects.append(f"  ch{n:02d} {bad_item['number']:<20} "
                           f"{'; '.join(bad_item['failures'])[:150]}")

    print("-" * 96)
    print(f"{'ALL':<3} {totals['src']:>4} {totals['kept']:>5} "
          f"{totals['cut']:>4} {totals['authored_drop']:>7} "
          f"{totals['marks']:>6}")
    if rejects:
        print(f"\nREJECTED BY VERIFICATION ({len(rejects)}):")
        for line in (rejects if a.verbose else rejects[:40]):
            print(line)
        if not a.verbose and len(rejects) > 40:
            print(f"  ... {len(rejects) - 40} more; pass --verbose")
    if unmapped:
        seen = sorted(set(unmapped))
        print(f"\nUNMAPPED NON-ASCII ({len(seen)} distinct) -- add to FOLD:")
        for line in seen[:30]:
            print(f"  {line}")
    print(f"\nshaped files in {LOAD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
