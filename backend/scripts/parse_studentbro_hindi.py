"""Read the studentbro.in Malhar Hindi question banks for Class 6 and Class 7.

    python -m scripts.parse_studentbro_hindi --book c6 --report
    python -m scripts.parse_studentbro_hindi --book c6 --only 1 --show 8
    python -m scripts.parse_studentbro_hindi --book c6 --write

``--report`` prints one line per chapter plus the section breakdown and every
anomaly found. ``--write`` emits ``scripts/studentbro_items/<book>/chNN.json``
in the shape ``load_nodia_items`` consumes, with the extraction id resolved
from the database.

FOUR THINGS ABOUT THESE FILES
-----------------------------

**pdftotext returns an ASCII skeleton.** The Devanagari is a Type0/Identity-H
subset (NotoSansDevanagari, TimesNewRomanPSMT) with a ToUnicode CMap poppler
mishandles, so ``pdftotext -layout`` gives back the question numbers and the
``(A)``-``(D)`` labels and nothing else -- which reads exactly like a corpus of
empty stems. PyMuPDF decodes the same files perfectly. Everything here goes
through ``fitz``.

**The answers are a separate content stream, drawn first.** Raw extraction
order therefore emits every answer on a page before any of that page's
questions, and a sequential reader binds answer 1 to question 1 only by luck.
But the answer block is *positioned* inline: each ``जवाब :`` sits between its
own question's last option and the next question's number. So sorting every
line by (page, y, x) puts the page back into true reading order with each
answer already attached to its question, and an answer that continues onto the
next page lands at the top of that page where it belongs. No index arithmetic,
nothing to get off by one.

**The key is printed three different ways.** ``जवाब : सिंधु`` (value only),
``जवाब : D सभी`` (Latin letter and value), ``जवाब : (क) हरी दूब को``
(Devanagari letter and value), and occasionally ``जवाब : B`` with the reasoning
in a following ``व्याख्या :`` line. Where letter and value are both present
they can disagree, so the VALUE decides and the disagreement is reported. A
value-matched key also repairs the letter when the letter is the thing that is
wrong.

**A comprehension block is one printed question.** Under a गद्यांश/पद्यांश
heading the book prints a passage, then five sub-questions numbered
``प्रश्न 1.`` to ``प्रश्न 5.`` with ``(क)``-``(घ)`` options, and a single
answer block keying all five. The chapter numbers that whole thing as one item,
so it is stored as one item: splitting it would invent item numbers the source
does not have, and flattening the sub-options into the parent's option list
would produce a twenty-option "MCQ". Those sections are read as passages --
their option-looking lines stay in the stem.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata as ud
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import fitz  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MIRROR = ROOT / "data" / "qbank" / "mirror" / "studentbro"
OUT = Path(__file__).resolve().parent / "studentbro_items"

PUBLISHER = "studentbro"

# ---------------------------------------------------------------------------
# Books
# ---------------------------------------------------------------------------
# `chapters` is (printed number, the chapter_master.chapter_name to match).
# Class 7 chapter 5 is officially "नहीं होना बीमार" and the DB row is named
# "बीमारी का बहाना" -- wording *about* the chapter rather than its title. The
# position and the content agree (the stems name the lesson), so the DB name is
# what has to be matched on and it is recorded here as the alias it is.
BOOKS: dict[str, dict] = {
    "c6": {
        "dir": "c6_hindi_malhar",
        "standard": 6,
        "standard_id": 39,
        "subject": "Hindi-A",
        "title": "Important Questions -- Class 6 Hindi (Malhar)",
        "textbook": "Malhar (NCERT Class 6 Hindi)",
        "marker": "जवाब",
        "listing": "https://studentbro.in/topics/important-question/english/6/hindimalhar",
        "chapters": [
            (1, "मातृभूमि"),
            (2, "गोल"),
            (3, "पहली बूँद"),
            (4, "हार की जीत"),
            (5, "रहीम के दोहे"),
            (6, "मेरी माँ"),
            (7, "जलाते चलो"),
            (8, "सत्रिया और बिहू नृत्य"),
            (9, "मैया मैं नहिं माखन खायो"),
            (10, "परीक्षा"),
            (11, "चेतक की वीरता"),
            (12, "हिंद महासागर में छोटा-सा हिंदुस्तान"),
            (13, "पेड़ की बात"),
        ],
        # Downloaded and parseable, but there is no chapter row for either:
        # they are the book's grammar and composition appendices, not lessons.
        "unmapped": {90: "व्याकरण विभाग", 91: "लेखन विभाग"},
    },
    "c7": {
        "dir": "c7_hindi_malhar",
        "standard": 7,
        "standard_id": 40,
        "subject": "Hindi-A",
        "title": "Important Questions -- Class 7 Hindi (Malhar)",
        "textbook": "Malhar (NCERT Class 7 Hindi)",
        "marker": "उत्तर",
        "listing": "https://studentbro.in/topics/important-question/english/7/5-hindi-malhar",
        "chapters": [
            (1, "माँ कह एक कहानी"),
            (2, "तीन बुद्धिमान"),
            (3, "फूल और काँटा"),
            (4, "पानी रे पानी"),
            (5, "बीमारी का बहाना"),
            (6, "गिरधर कविराय की कुंडलियाँ"),
            (7, "वर्षा बहार"),
            (8, "बिरजू महाराज से साक्षात्कार"),
            (9, "चिड़िया"),
            (10, "मीरा के पद"),
        ],
        # Where the DB row is not the lesson's title. Chapter 5's row reads
        # "बीमारी का बहाना" -- "pretending to be ill", wording ABOUT the
        # lesson -- while the book, the publisher's slug
        # (5-nahin-hona-beemaar) and the questions themselves
        # ("'नहीं होना बीमार' पाठ में...") all name it नहीं होना बीमार. Same
        # chapter, matched on position and content; recorded so the next reader
        # does not have to work it out again.
        "official_names": {5: "नहीं होना बीमार"},
        "unmapped": {},
    },
}

# ---------------------------------------------------------------------------
# Line classification
# ---------------------------------------------------------------------------
# A top-level item number is printed in its own narrow gutter column: x is
# 36.8 for two digits and 43.4 for one, never above 50. Option labels start at
# 60.8, the section heading at 45.0 and the answer column at 57.0. Keying on x
# rather than on the text is what keeps "2.(ख) दक्षिण दिशा" -- a line inside a
# comprehension answer -- from being read as the opening of question 2.
_GUTTER_MAX_X = 50.0
_HEADING_X = (44.0, 46.5)
# The Class 7 comprehension column starts at 45.8, i.e. left of the gutter the
# rest of the book numbers in.
_INLINE_MAX_X = 50.0

_NUMBER = re.compile(r"^(\d{1,3})\s*\.$")
# Class 7 prints its comprehension sub-questions with the number and the
# question on ONE line, in the body column rather than the gutter, and they
# continue the chapter's own numbering: "74.  ... कौन कह रहा है?". They are
# separate printed questions and are stored as such. The "must be the next
# number in sequence" guard is what stops a line of verse that happens to open
# with a numeral from being read as a question.
_INLINE = re.compile(r"^(\d{1,3})\s*\.\s+(\S.*)$")
# "(क) यशोधरा (ख) राहुल (ग) सिद्धार्थ (घ) आखेटक" -- four options on one line.
_INLINE_OPTS = re.compile(r"[(\[]\s*([कखगघ]|[A-Da-d])\s*[)\]]\s*")
# "उत्तर : 1. (ख) राहुल" then "2. (ग) हंस" ... -- one key per sub-question,
# numbered 1..5 inside the block regardless of the questions' own numbers.
_SUBKEY = re.compile(r"(?:^|\s)([1-9])\s*\.\s+")
_MARKS = re.compile(r"^\[(\d{1,4})\]$")
_HEADING = re.compile(r"^\*\s*(.+?)\s*$")

# (A) / (a) / A) / (क) -- one label, at the start of a line.
_OPTION = re.compile(r"^[(\[]?\s*([A-Da-d]|[कखगघ])\s*[)\].]\s*(.*)$")

_LETTER_OF = {"क": "A", "ख": "B", "ग": "C", "घ": "D",
              "A": "A", "B": "B", "C": "C", "D": "D",
              "a": "A", "b": "B", "c": "C", "d": "D"}

# The key as printed: an optional label, then the value.
_KEY_HEAD = re.compile(r"^[(\[]?\s*([A-Da-d]|[कखगघ])\s*[)\]]?\s*[.:\-–—]?\s*(.*)$")

_FURNITURE = re.compile(
    r"^(?:https?://studentbro\.in/?|Page\s+\d+|STD\s+\d+\s+HINDI.*|STD\s+\d+\s+Hindi.*"
    r"|कुल\s*गुण\s*:.*|Click\s+Here.*|[-–—\s]+)$",
    re.IGNORECASE,
)


def _flat(t: str) -> str:
    return " ".join((t or "").split())


def _bmp(t: str) -> str:
    """Fold anything outside the Basic Multilingual Plane onto ASCII or drop it.

    `lms_question_master.question_title`, `.description` and `.answer` are all
    utf8mb3. A single 4-byte character -- a mathematical alphanumeric, an
    emoji -- makes MariaDB reject the whole row with "Incorrect string value:
    '\\xF0\\x9D...'", and the writer's retry loop cannot recover from it, so
    one stray glyph costs the entire chapter. Devanagari is 3 bytes and passes
    through untouched.
    """
    if all(ord(c) <= 0xFFFF for c in t):
        return t
    out = []
    for c in t:
        if ord(c) <= 0xFFFF:
            out.append(c)
            continue
        folded = ud.normalize("NFKC", c)
        out.append(folded if all(ord(x) <= 0xFFFF for x in folded) else "")
    return "".join(out)


_KEEP_CATEGORIES = ("L", "N", "M")


def _fold(t: str) -> str:
    """Compare-key: case-folded, punctuation- and space-free, SCRIPT-PRESERVING.

    Two traps, one after the other.

    A `[^a-z0-9]` fold erases every Devanagari character, so every question in
    the book compares equal to every other and the whole chapter looks like one
    duplicated item.

    `\\W` is not the fix either, and this is the subtler failure. Python's `\\w`
    means "alphanumeric", and a Devanagari vowel sign is a combining MARK, not
    a letter -- so `\\W` strips every matra. "नानीजी को" and "नानाजी को" both
    collapse to the same consonant skeleton, and an MCQ whose options are
    "नानीजी को" and "नानाजी को" has two options that compare equal. The key
    then matches both, resolves to neither, and falls back to the printed
    letter. Keeping categories L, N and M keeps the marks and drops only
    punctuation, separators and symbols.
    """
    text = ud.normalize("NFC", t or "").casefold()
    return "".join(c for c in text if ud.category(c)[0] in _KEEP_CATEGORIES)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
# Ordered, most specific first. `passage` means the block's option-looking
# lines belong to the stem, not to an option list.
_SECTIONS: list[tuple[str, str, str | None]] = [
    # (regex source, form, forced exam section)
    (r"सत्य\s*या\s*असत्य", "true_false", "A"),
    (r"रिक्त\s*स्थान", "fill_blank", "A"),
    (r"सही\s*जोड़", "match_following", "A"),
    (r"गद्यांश\s*को\s*पढ़कर", "passage", "E"),
    (r"पद्यांश\s*को\s*पढ़कर", "passage", "E"),
    (r"अपठित\s*(?:गद्यांश|पद्यांश)", "passage", "E"),
    (r"बहुविकल्पी", "mcq", "A"),
    (r"सही\s*विकल्प\s*चुनकर", "mcq", "A"),
    (r"\bMCQ\b", "mcq", "A"),
    (r"पर्यायवाची", "synonym", "A"),
    (r"विलोम", "antonym", "A"),
    (r"मुहावर", "idiom", "B"),
    (r"मूलशब्द\s*और\s*प्रत्यय", "word_formation", "A"),
    (r"शब्दों\s*के\s*अर्थ", "word_meaning", "A"),
    (r"अशुद्ध\s*शब्द", "spelling_correction", "A"),
    (r"काव्य\s*पंक्ति", "explain_lines", "C"),
    (r"निबंध", "essay", "D"),
    (r"पत्र\s*लेखन", "letter", "D"),
    (r"अनुच्छेद", "essay", "D"),
    (r"एक\s*वाक्य\s*में", "very_short", "B"),
    (r"सक्षिप्त|संक्षिप्त", "short", "C"),
    (r"सूचना\s*अनुसार", "short", "C"),
    (r"उत्तर\s*लिखिए", "short", "C"),
    (r"उत्तर\s*लिखो", "short", "C"),
]
# NFC BOTH SIDES OR THE NUKTA LETTERS NEVER MATCH. "ड़" and "ढ़" exist twice in
# Unicode -- precomposed (U+095C, U+095D) and as base + nukta (U+0921/U+0922
# followed by U+093C) -- and because both are composition exclusions, NFC
# DECOMPOSES them. The PDFs emit one form and a pattern typed into this file
# may hold the other, so "सही जोड़ मिलाए" and "पद्यांश को पढ़कर" silently fell
# through to the generic descriptive form. Normalising the patterns at compile
# time and the heading at match time puts both in the same spelling.
_SECTIONS_C = [(re.compile(ud.normalize("NFC", p)), form, sec)
               for p, form, sec in _SECTIONS]

# Forms whose items carry their own (A)-(D) option list.
_OPTIONED = {"mcq", "true_false"}

# Fallback marks per form when the section total does not divide evenly and the
# heading does not say. These are the FORM_TO_SECTION defaults where a form
# exists there, and the book's own habit otherwise.
_DEFAULT_MARKS = {
    "mcq": 1, "true_false": 1, "fill_blank": 1, "match_following": 5,
    "synonym": 1, "antonym": 1, "word_meaning": 1, "word_formation": 1,
    "spelling_correction": 1, "idiom": 2, "very_short": 1, "short": 3,
    "explain_lines": 3, "long": 5, "essay": 5, "letter": 5, "passage": 5,
}
_DEFAULT_SECTION = {1: "A", 2: "B", 3: "C", 4: "D", 5: "D"}

_MARK_IN_HEADING = re.compile(r"\(\s*(\d{1,2})\s*Mark", re.IGNORECASE)


def classify(heading: str) -> tuple[str, str | None]:
    probe = ud.normalize("NFC", heading or "")
    for pattern, form, section in _SECTIONS_C:
        if pattern.search(probe):
            return form, section
    return "short", "C"


# The generic descriptive headings ("निम्नलिखित प्रश्नों के उत्तर लिखिए") say
# nothing about length; the marks do. Once a section's per-item marks are known
# the descriptive family is re-graded onto the repo's own scale -- very_short 2
# / short 3 / long 5 -- so a 4-mark question is not filed as a 3-mark one.
_DESCRIPTIVE = {"very_short", "short", "long"}
_BY_MARKS = {1: ("very_short", "B"), 2: ("very_short", "B"), 3: ("short", "C")}


def regrade(form: str, marks: int) -> tuple[str, str]:
    if form not in _DESCRIPTIVE:
        return form, ""
    return _BY_MARKS.get(marks, ("long", "D"))


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
# Two pieces of the same visual row can differ by a couple of points, because
# the gutter number and the text it labels are drawn by different streams. A
# plain y-sort then puts "गाय = ____" (y 313.4) BEFORE the "5." that numbers it
# (y 315.5), so the stem is attached to the previous question and item 5 loads
# with an empty stem -- which is what happened to every पर्यायवाची and विलोम
# section. Quantise into rows first, then order within the row by x. Real line
# spacing in these files is 18-22pt, so 6pt cannot merge two rows.
_ROW_TOL = 6.0


def doc_lines(doc) -> list[tuple[int, float, float, str]]:
    """Every text line in the document, in visual reading order."""
    rows: list[tuple[int, float, float, str]] = []
    for pno in range(doc.page_count):
        page_rows = []
        for block in doc[pno].get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                txt = _bmp("".join(s["text"] for s in line["spans"]))
                if not txt.strip():
                    continue
                stripped = _flat(txt)
                if _FURNITURE.match(stripped):
                    continue
                page_rows.append((round(line["bbox"][1], 1),
                                  round(line["bbox"][0], 1), stripped))
        page_rows.sort(key=lambda r: (r[0], r[1]))
        band, top = 0, None
        keyed = []
        for y, x, t in page_rows:
            if top is None or y - top > _ROW_TOL:
                band += 1
                top = y
            keyed.append((band, x, y, t))
        keyed.sort(key=lambda r: (r[0], r[1]))
        rows.extend((pno + 1, y, x, t) for _, x, y, t in keyed)
    return rows


class Item:
    __slots__ = ("number", "page", "stem", "options", "answer", "explain",
                 "heading", "form", "section", "notes", "marks", "inline")

    def __init__(self, number: str, page: int, heading, form, section,
                 inline: bool = False):
        self.number = number
        self.page = page
        self.stem: list[str] = []
        self.options: list[dict] = []
        self.answer: list[str] = []
        self.explain: list[str] = []
        self.heading = heading
        self.form = form
        self.section = section
        self.notes: list[str] = []
        self.marks: int | None = None
        # True for a Class 7 comprehension sub-question, which owns its own
        # options and shares one answer block with its four siblings.
        self.inline = inline


def parse(pdf: Path, marker: str) -> dict:
    """Read one chapter into items, sections and a list of anomalies."""
    doc = fitz.open(pdf)
    rows = doc_lines(doc)
    pages = doc.page_count
    doc.close()

    marker_re = re.compile(rf"^{re.escape(marker)}\s*[:：]\s*(.*)$")
    explain_re = re.compile(r"^व्याख्या\s*[:：]?\s*(.*)$")

    items: list[Item] = []
    sections: list[dict] = []
    problems: list[str] = []

    heading = None
    form, section = "short", "C"
    cur: Item | None = None
    answer_x: float | None = None
    # The passage a comprehension block opens with, held until the block's
    # first question appears. `lead_used` says it has already been handed to an
    # item, so the next passage line starts a fresh block rather than adding to
    # the one that is already in use.
    lead: list[str] = []
    lead_used = False
    # Pending [N] that arrived just before its heading, and the last heading
    # still waiting for its [N].
    pending_marks: tuple[int, int, float] | None = None

    for page, y, x, text in rows:
        # ---- section marks -------------------------------------------------
        m = _MARKS.match(text)
        if m:
            value = int(m.group(1))
            if sections and sections[-1]["page"] == page and abs(sections[-1]["y"] - y) < 8:
                sections[-1]["marks"] = value
            else:
                pending_marks = (value, page, y)
            continue

        # ---- section heading ----------------------------------------------
        if text.startswith("*") and _HEADING_X[0] <= x <= _HEADING_X[1]:
            heading = _flat(_HEADING.match(text).group(1))
            form, section = classify(heading)
            entry = {"heading": heading, "form": form, "section": section,
                     "marks": None, "page": page, "y": y, "count": 0}
            if pending_marks and pending_marks[1] == page and abs(pending_marks[2] - y) < 8:
                entry["marks"] = pending_marks[0]
            pending_marks = None
            sections.append(entry)
            cur = None
            answer_x = None
            lead, lead_used = [], False
            continue

        # ---- a new item ----------------------------------------------------
        m = _NUMBER.match(text)
        if m and x <= _GUTTER_MAX_X:
            cur = Item(m.group(1), page, heading, form, section)
            items.append(cur)
            if sections:
                sections[-1]["count"] += 1
            answer_x = None
            # A Class 6 comprehension block IS one numbered item, so its
            # passage is consumed here and must not leak into the next one.
            cur.stem.extend(lead)
            lead, lead_used = [], False
            continue

        if form == "passage":
            m = _INLINE.match(text)
            if m and x <= _INLINE_MAX_X and int(m.group(1)) == len(items) + 1:
                cur = Item(m.group(1), page, heading, form, section, inline=True)
                # The passage the block opened with belongs to every one of its
                # sub-questions: "'आखेटक' का क्या अर्थ है?" cannot be answered
                # without it, so each item carries it rather than pointing at a
                # parent row this writer has no way to link. It is therefore
                # NOT cleared here -- the four siblings still to come need it.
                cur.stem.extend(lead)
                lead_used = True
                cur.stem.append(m.group(2))
                items.append(cur)
                if sections:
                    sections[-1]["count"] += 1
                answer_x = None
                continue
            if cur is None:
                # The passage that opens the section's FIRST block is printed
                # before any item of that section exists. "No current item"
                # used to mean "drop it", which cost the whole first block its
                # context.
                if lead_used:
                    lead, lead_used = [], False
                lead.append(text)
                continue

        if cur is None:
            # Text before the first numbered item of a non-passage section: a
            # paper header. Nothing to attach it to.
            continue

        # ---- the answer ----------------------------------------------------
        m = marker_re.match(text)
        if m:
            cur.answer.append(m.group(1))
            answer_x = x
            continue
        m = explain_re.match(text)
        if m:
            cur.explain.append(m.group(1))
            answer_x = x
            continue
        if answer_x is not None and abs(x - answer_x) < 2.0:
            (cur.explain if cur.explain else cur.answer).append(text)
            continue

        # ---- anything after the answer marker -------------------------------
        # Once an item's answer has started, the question is over, so text that
        # is not a number, a heading or an option cannot belong to the stem.
        # For an inline item it is the passage the NEXT block opens with, and
        # buffering it keeps the verse out of the previous question's stem. For
        # everything else it is more of the answer: a सही जोड़ key is sometimes
        # printed as a second copy of the table rather than as "(1 → D)" text,
        # and treated as stem that key ends up printed inside the question.
        if cur.answer or cur.explain:
            if form == "passage":
                # The next block's passage, not more of this answer.
                if lead_used:
                    lead, lead_used = [], False
                lead.append(text)
            else:
                cur.answer.append(text)
            continue

        # ---- options -------------------------------------------------------
        if cur.form in _OPTIONED or cur.inline:
            hits = list(_INLINE_OPTS.finditer(text))
            if len(hits) >= 2 and hits[0].start() == 0:
                for index, hit in enumerate(hits):
                    end = hits[index + 1].start() if index + 1 < len(hits) else len(text)
                    body = text[hit.end(): end].strip()
                    if body:
                        cur.options.append({"label": _LETTER_OF[hit.group(1)],
                                            "text": body, "x": x, "y": y})
                continue
            m = _OPTION.match(text)
            if m and m.group(2).strip():
                cur.options.append({"label": _LETTER_OF[m.group(1)],
                                    "text": m.group(2).strip(), "x": x, "y": y})
                continue
            if cur.options:
                # A wrapped option. Attach it to the option in the same column
                # -- 2x2 layouts put (A) and (C) at the same x, so the nearest
                # option ABOVE at this x is the one that wrapped.
                same = [o for o in cur.options if abs(o["x"] - x) < 3.0 and o["y"] <= y]
                target = max(same, key=lambda o: o["y"]) if same else cur.options[-1]
                target["text"] = f"{target['text']} {text}".strip()
                continue

        # ---- stem ----------------------------------------------------------
        cur.stem.append(text)

    # Items were appended in order and each one incremented its own section's
    # count, so replaying the counts re-pairs them. Marks and the final form
    # are only knowable once a section's item count and option count are final,
    # which is why this is a second pass rather than set on the way through.
    pos = 0
    for entry in sections:
        entry["members"] = items[pos: pos + entry["count"]]
        pos += entry["count"]
    if pos != len(items):
        problems.append(f"{len(items) - pos} item(s) belong to no section")

    for entry in sections:
        stated = _MARK_IN_HEADING.search(entry["heading"])
        per = None
        if entry["marks"] and entry["count"] and entry["marks"] % entry["count"] == 0:
            per = entry["marks"] // entry["count"]
        elif stated:
            per = int(stated.group(1))
        elif entry["members"] and all(i.inline for i in entry["members"]):
            # A comprehension sub-question is worth one mark. The division only
            # fails where the book dropped a sub-question it still allotted
            # marks for -- Class 7 chapter 6 prints [20] over 18 questions --
            # and inflating each survivor to make the total come out would
            # misstate every one of them.
            per = max(1, (entry["marks"] or 0) // entry["count"])
        entry["per_item"] = per or _DEFAULT_MARKS.get(entry["form"], 1)

        # A HEADING CAN SAY "बहुविकल्पी" AND MEAN NOTHING OF THE KIND. The
        # grammar drills are headed "निर्देशानुसार ' विशेषण ' पर आधारित
        # बहुविकल्पी प्रश्नों में से उचित विकल्प चयन कर लिखिए" -- "choose the
        # right option" -- and then print a sentence with a free-text answer
        # and no options at all. Taken at its word that is twenty MCQs with
        # zero options, every one of them a V-09 failure. Whether the items
        # actually carry options is a fact about the page, so it overrules the
        # heading.
        if entry["form"] in _OPTIONED and entry["members"] and not any(
                i.options for i in entry["members"]):
            entry["form"], entry["section"] = "very_short", "B"
            entry["note"] = "heading says multiple-choice; no item has options"

        form2, section2 = regrade(entry["form"], entry["per_item"])
        if section2:
            entry["form"], entry["section"] = form2, section2

        for item in entry["members"]:
            item.marks = entry["per_item"]
            item.section = entry["section"]
            item.heading = entry["heading"]
            # A Class 7 comprehension block mixes three real MCQs with two
            # write-the-answer questions, so the form is the item's own, not
            # the section's.
            if item.inline:
                item.form = "mcq" if item.options else "very_short"
                item.section = "A" if item.options else "B"
            else:
                item.form = entry["form"]

    problems.extend(split_block_answers(items))

    numbers = [int(i.number) for i in items]
    if numbers != list(range(1, len(numbers) + 1)):
        gaps = [n for i, n in enumerate(numbers) if n != i + 1]
        problems.append(f"item numbers are not 1..{len(numbers)}: first off at {gaps[:4]}")

    return {"pdf": pdf.name, "pages": pages, "items": items,
            "sections": sections, "problems": problems, "marker": marker}


def split_block_answers(items: list[Item]) -> list[str]:
    """Hand each Class 7 comprehension sub-question its own key.

    A block of five sub-questions carries ONE answer block, numbered 1..5
    inside itself and printed after the fifth question -- so the whole thing
    lands on that fifth item while the first four have nothing. The numbering
    inside the block is what binds: part k belongs to the k-th sub-question of
    that block, never to question k of the chapter.

    A block is a run of consecutive inline items ending at the one that holds
    the answer.

    THE COUNTS DO NOT ALWAYS AGREE, and when they disagree the book is wrong,
    not the reader. Class 7 chapter 6's last block prints three sub-questions
    and five keys (and prints key 4 and key 5 identically); chapter 10's last
    block prints five sub-questions and three keys. Both are recorded as source
    defects and the parts that exist are still bound, in order -- part k to the
    k-th printed sub-question -- because the key list is ordered and every MCQ
    part is independently re-checked against its own options afterwards. What
    is not done is guessing: a question with no part keeps no answer.
    """
    problems: list[str] = []
    block: list[Item] = []
    for item in items:
        if not item.inline:
            if block:
                problems.append(f"q{block[0].number}: block of {len(block)} "
                                f"sub-question(s) has no answer block")
                block = []
            continue
        block.append(item)
        if not (item.answer or item.explain):
            continue

        whole = _flat(" ".join(item.answer))
        starts = list(_SUBKEY.finditer(whole))
        parts: list[str] = []
        if starts and [s.group(1) for s in starts] == [
                str(n) for n in range(1, len(starts) + 1)]:
            for index, hit in enumerate(starts):
                end = starts[index + 1].start() if index + 1 < len(starts) else len(whole)
                parts.append(whole[hit.end(): end].strip())

        if not parts:
            problems.append(
                f"q{item.number}: block of {len(block)} carries an answer that "
                f"is not numbered 1..n; left whole on the last question")
            block = []
            continue

        if len(parts) != len(block):
            problems.append(
                f"q{block[0].number}-{item.number}: the book prints "
                f"{len(block)} sub-question(s) and {len(parts)} key part(s)")
        for index, target in enumerate(block):
            target.answer = [parts[index]] if index < len(parts) else []
            target.explain = []
        block = []
    if block:
        problems.append(f"q{block[0].number}: block of {len(block)} "
                        f"sub-question(s) has no answer block")
    return problems


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------
def resolve_key(item: Item) -> tuple[str | None, list[str]]:
    """Which option the printed answer names. The value decides, not the letter.

    Returns (label or None, notes). A note is raised when the printed letter
    and the printed value point at different options, and when neither can be
    resolved at all.
    """
    notes: list[str] = []
    if not item.options:
        return None, notes
    raw = _flat(" ".join(item.answer))
    if not raw:
        return None, ["no answer printed"]

    m = _KEY_HEAD.match(raw)
    letter = _LETTER_OF.get(m.group(1)) if m else None
    value = (m.group(2) if m else raw).strip()
    # "जवाब : सिंधु" has no label at all, and its first character may well be a
    # letter this table knows; only treat it as a label when what follows was
    # separated from it, which _KEY_HEAD's bracket/punctuation requirement
    # already enforces for the bracketed forms. For the bare "D सभी" form the
    # label is a single ASCII letter followed by a space.
    if letter and not re.match(r"^[(\[]?\s*(?:[A-Da-d]|[कखगघ])\s*[)\]]", raw):
        if not re.match(r"^[A-Da-d]\s", raw) and raw.strip() not in list("ABCDabcd"):
            letter, value = None, raw

    by_value = None
    folded = _fold(value)
    if folded:
        exact = [o for o in item.options if _fold(o["text"]) == folded]
        if len(exact) == 1:
            by_value = exact[0]["label"]
        elif not exact:
            # The key sometimes prints a little more or a little less than the
            # option ("शस्य - श्यामला बनने की" for "शस्य - श्यामला बनने").
            near = [o for o in item.options
                    if _fold(o["text"]) and (
                        _fold(o["text"]) in folded or folded in _fold(o["text"]))
                    and min(len(_fold(o["text"])), len(folded)) >= 3
                    and min(len(_fold(o["text"])), len(folded)) /
                        max(len(_fold(o["text"])), len(folded)) >= 0.6]
            if len(near) == 1:
                by_value = near[0]["label"]

    if by_value and letter and by_value != letter:
        notes.append(f"printed letter {letter} but the printed value is option {by_value}")
    if by_value:
        return by_value, notes
    if folded:
        # A LETTER WITH A VALUE THAT FITS NOTHING IS NOT A KEY. Class 7 chapter
        # 8 prints "2. (ग) भगवान" and then "3. (ग) भगवान" -- the same part
        # twice -- so question 115's real key was never printed, and its own
        # option (C) is something else entirely. Taking the letter on trust
        # would publish a confidently wrong answer; leaving it unkeyed makes
        # V-04 hold the item where somebody can see it.
        notes.append(f"key {raw[:50]!r} names no option of this question; left unkeyed")
        return None, notes
    if letter and any(o["label"] == letter for o in item.options):
        return letter, notes
    notes.append(f"unresolved key {raw[:60]!r}")
    return None, notes


# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------
def to_entries(book: str, chapter_no: int, chapter_name: str, parsed: dict) -> tuple[list[dict], list[str]]:
    entries: list[dict] = []
    problems: list[str] = list(parsed["problems"])
    for item in parsed["items"]:
        form = item.form
        stem = _flat(" ".join(item.stem))
        answer = _flat(" ".join(item.answer))
        explain = _flat(" ".join(item.explain))
        if explain:
            answer = f"{answer} व्याख्या : {explain}".strip()

        options = [{"label": o["label"], "text": _flat(o["text"])} for o in item.options]
        key, notes = resolve_key(item)
        for note in notes:
            problems.append(f"q{item.number}: {note}")

        if form == "mcq" and len(options) != 4:
            problems.append(f"q{item.number}: mcq with {len(options)} option(s)")
        if not stem:
            problems.append(f"q{item.number}: empty stem")
        if not answer:
            problems.append(f"q{item.number}: no answer")

        marks = getattr(item, "marks", None) or _DEFAULT_MARKS.get(form, 1)
        entry = {
            "chapter_number": chapter_no,
            "chapter": chapter_name,
            "number": item.number,
            "form": form,
            "section": item.section or _DEFAULT_SECTION.get(marks, "A"),
            "section_heading": item.heading,
            "marks": marks,
            "stem": stem,
            "page": item.page,
            "answer": answer,
        }
        if options:
            entry["options"] = options
        if key:
            entry["correct_option"] = key
        entries.append(entry)
    return entries, problems


def chapter_files(cfg: dict) -> list[tuple[int, str, Path]]:
    out = []
    folder = MIRROR / cfg["dir"]
    for number, name in cfg["chapters"]:
        path = folder / f"ch{number:02d}.pdf"
        if path.exists():
            out.append((number, name, path))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", choices=sorted(BOOKS), required=True)
    ap.add_argument("--only", help="comma-separated printed chapter numbers")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--show", type=int, help="print the first N items of each chapter")
    ap.add_argument("--write", action="store_true",
                    help="write scripts/studentbro_items/<book>/chNN.json")
    a = ap.parse_args()

    cfg = BOOKS[a.book]
    only = {int(x) for x in a.only.split(",") if x.strip()} if a.only else None

    extraction: dict[int, tuple[int, int]] = {}
    if a.write:
        from sqlalchemy import text as sql
        from app.db.mariadb import SessionLocal, init_mariadb
        if not init_mariadb() or SessionLocal is None:
            raise SystemExit("Database not ready")
        db = SessionLocal()
        try:
            rows = db.execute(sql(
                "SELECT d.id, d.chapter_number, d.chapter_id "
                "  FROM document_extractions d "
                " WHERE d.document_type = 'question_bank' "
                "   AND d.standard_id = :s AND d.subject_name = :n "
                "   AND d.extraction_metadata LIKE :tag "
                " ORDER BY d.chapter_number"),
                {"s": cfg["standard_id"], "n": cfg["subject"],
                 "tag": f'%"book": "{a.book}"%'}).fetchall()
            extraction = {int(r[1]): (int(r[0]), int(r[2])) for r in rows}
        finally:
            db.close()
        if not extraction:
            raise SystemExit(
                "No question_bank extraction rows for this book. Run "
                "scripts.setup_studentbro_extractions first.")

    grand = 0
    all_problems: list[str] = []
    print(f"{'ch':>3} {'file':<9} {'pg':>3} {'items':>6} {'mcq':>4} {'keyed':>6} "
          f"{'marks':>6} {'flags':>6}  chapter")
    print("-" * 100)
    for number, name, path in chapter_files(cfg):
        if only is not None and number not in only:
            continue
        parsed = parse(path, cfg["marker"])
        entries, problems = to_entries(a.book, number, name, parsed)
        mcqs = [e for e in entries if e.get("options")]
        keyed = [e for e in mcqs if e.get("correct_option")]
        marks = sum(e["marks"] for e in entries)
        grand += len(entries)
        all_problems.extend(f"ch{number:02d} {p}" for p in problems)
        print(f"{number:>3} {path.name:<9} {parsed['pages']:>3} {len(entries):>6} "
              f"{len(mcqs):>4} {len(keyed):>6} {marks:>6} {len(problems):>6}  {name}")

        if a.report:
            for s in parsed["sections"]:
                print(f"      [{s['marks'] or '?':>3}] x{s['count']:<3} "
                      f"{s['per_item']}m {s['form']:<20} {s['heading'][:60]}")
        if a.show:
            for e in entries[: a.show]:
                print(f"      --- q{e['number']} {e['form']} {e['marks']}m "
                      f"key={e.get('correct_option')}")
                print(f"          stem: {e['stem'][:110]}")
                for o in e.get("options", []):
                    print(f"          ({o['label']}) {o['text'][:70]}")
                print(f"          ans : {e['answer'][:110]}")

        if a.write:
            if number not in extraction:
                print(f"      SKIP write: no extraction row for chapter {number}")
                continue
            eid, cid = extraction[number]
            folder = OUT / a.book
            folder.mkdir(parents=True, exist_ok=True)
            payload = {"chapter": number, "printed_chapter": number,
                       "chapter_name": name, "chapter_id": cid,
                       "extraction_id": eid, "source": path.name,
                       "items": entries}
            target = folder / f"ch{number:02d}.json"
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                              encoding="utf-8")
            print(f"      wrote {target.relative_to(ROOT)}  ({len(entries)} items)")

    print("-" * 100)
    print(f"TOTAL {grand} items, {len(all_problems)} flag(s)")
    if all_problems:
        print("\nflags:")
        for p in all_problems[:80]:
            print("  ", p)
        if len(all_problems) > 80:
            print(f"   ... and {len(all_problems) - 80} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
