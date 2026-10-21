"""Draft items from the KVS ZIET Mysuru Class 9 Mathematics Student Support Material.

    python -m scripts.parse_kvs_ssm_c9_maths
    python -m scripts.parse_kvs_ssm_c9_maths --out scripts/kvs_ssm_c9_items/drafts

Source: "MATHMATICS CLASS IX STUDENT SUPPORT MATERIALS 2025-26", published on the
ZIET Mysuru learning portal. 148 pages, twelve old-syllabus chapters.

ONLY FOUR CHAPTERS ARE IN SCOPE. Our Class 9 Mathematics rows follow the NEP
Ganita Prakash naming and this book is written against the superseded syllabus.
For quadrilaterals, statistics, surface area and linear equations in two
variables the content is edition-portable -- the question is the same question
either way -- and for the rest it is not. `CHAPTERS` below is the whole of the
mapping and nothing else is read.

THE PRINTED FOLIO RUNS FIVE BEHIND THE PDF PAGE. The index prints
"QUADRILATERALS 80" and that chapter opens on PDF page 85. The spans in
`CHAPTERS` are PDF pages and `main()` asserts the chapter banner really is on
the first of them, because a span that is off by one silently files a whole
section under the neighbouring chapter.

EACH CHAPTER IS TWO DOCUMENTS. First a worked half, where every question is
followed by its own `SOLUTION:` or `ANS:`. Then an `EXERCISE` half printing
five more per section with no solutions at all, answered by a key at the end of
the chapter. They are parsed separately: the worked half joins locally, the
exercise half joins on (section, number) against that key, and an exercise
section whose key does not yield exactly one answer per question is dropped
whole rather than mis-paired.

THE TEXT LAYER IS NOT THE PAGE, and three things have to be rebuilt from span
geometry before any of it can be parsed:

  superscripts  "90o" is a 12pt "90" and an 8pt "o" lifted 4.5pt off the
                baseline. Read flat it is ninety-oh; it is 90 degrees. The
                same loss turns 360 degrees into "3600" and r-squared into
                "r2", and an angle chapter is unreadable without it.
  fractions     Word sets a fraction as two CambriaMath runs with a drawn
                rule between them, and the text layer emits them as separate
                lines: "=>x=" / "360" / "18  = 20" is x = 360/18 = 20. The
                rule is found in the page drawings and the runs contained
                within its width above and below it are the numerator and
                the denominator.
  Symbol font   U+F0DE is a private-use glyph for a double arrow.

`_super` writes the degree sign rather than a raised zero because the raised
zero is exactly the confusion being repaired.

WHAT THE REBUILD CANNOT FIX is a word space that was never in the file. The
statistics chapter prints "Classmarkofthe1stclassintervalis5andthere..." and
the characters are set flush -- the gaps between them are 0.0pt, so there is no
threshold that recovers the spaces because nothing was lost in extraction. Those
items are reported by `_garbled` and held; they are a defect in the source.

THE LETTER IN A PRINTED SOLUTION IS NOT RELIABLE, THE VALUE IS. Where the
solution quotes a value that names exactly one option, that option wins and the
disagreement is recorded, the same rule `parse_ziet_maths` applies.

AN MCQ THAT DID NOT YIELD FOUR OPTIONS IS HELD, NOT DEMOTED. `parse_ziet_maths`
demotes such an item to `very_short`, which is right there because its answers
carry their working. Here many answers are the bare letter "ANS:C", and a
very-short question whose answer is the single letter C is not a question at
all.

`concept` is left empty. `apply_read_concepts` RAISES on a name outside the
chapter's list and aborts the chapter, so a guess costs more than a blank.
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

SOURCE = (Path(__file__).resolve().parents[1] / "data" / "qbank" / "mirror"
          / "kvs_ssm_c9" / "c9_maths_ssm.pdf")
# Listed on https://zietmysore.kvs.gov.in/en/learning-portal/ as "MATHMATICS
# CLASS IX STUDENT SUPPORT MATERIALS 2025 -26". The mirrored file is byte for
# byte this one: 7,015,181 bytes.
SOURCE_URL = ("https://cdnbbsr.s3waas.gov.in/s3kv0172cc68f8c6297abfb8c3c9e575b8/"
              "uploads/2025/12/2025121348.pdf")
PORTAL_URL = "https://zietmysore.kvs.gov.in/en/learning-portal/"

# PDF chapter number -> the span it occupies, its printed title, and the
# sort_order of the Class 9 Mathematics row it belongs to. Spans are PDF pages,
# one-based and inclusive. Statistics runs to 147 because its exercise key is
# printed on the page after the chapter ends.
CHAPTERS: dict[int, dict] = {
    4:  {"pages": (36, 45),   "title": "LINEAR EQUATION IN TWO VARIABLES",
         "our_sort": 13, "our_name": "Two Variables, One Line"},
    8:  {"pages": (85, 98),   "title": "QUADRILATERALS",
         "our_sort": 12, "our_name": "Quadrilaterals"},
    11: {"pages": (124, 133), "title": "SURFACE AREA AND VOLUME",
         "our_sort": 14, "our_name": "Math of Space: Surface Area and Volume"},
    12: {"pages": (134, 147), "title": "STATISTICS",
         "our_sort": 10, "our_name": "How Quantities Combine: Understanding Data"},
}

_RUNNING_HEAD = re.compile(r"^\s*KVS\s+ZIET\s+MYSURU", re.IGNORECASE)
_FOLIO = re.compile(r"^\s*\d{1,3}\s*$")

_SUPER = {"0": "⁰", "1": "¹", "2": "²", "3": "³",
          "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷",
          "8": "⁸", "9": "⁹", "+": "⁺", "-": "⁻",
          "−": "⁻", "(": "⁽", ")": "⁾", "n": "ⁿ"}
_PUA = {"": "⇒", "": "°", "": "×"}

# The book was produced by find-and-replacing "ANS" with "SOLUTION:", which also
# hit the middle of words: "ANSWER the following questions" was printed
# "SOLUTION:wer the following questions", and three section headings read
# "VERY SHORT SOLUTION:WERQUESTIONS". The string cannot occur any other way.
_REPLACE_DAMAGE = re.compile(r"(?i)SOLUTION:wer")

# The banner that ends the worked half of a chapter.
_EXERCISE = re.compile(r"(?m)^[ \t]*EXERCISE[ \t]*$")
# The key that answers the exercise half. "SOLUTION OF EXERCISE QUESTIONS" is
# chapter 11's wording; the other three print a bare "ANSWERS".
_KEYBLOCK = re.compile(r"(?m)^[ \t]*(?:ANSWERS?|SOLUTIONS?\s+OF\s+EXERCISE"
                       r"\s+QUESTIONS?)[ \t]*$")

# Ordered most specific first: "VERY SHORT ANSWER" also contains "SHORT ANSWER",
# and chapter 11's headings are damaged by a find-and-replace of ANS -> SOLUTION:
# ("VERY SHORT SOLUTION:WERQUESTIONS", "LONG SOLUTION: QUESTIONS").
_BANNERS: list[tuple[str, re.Pattern[str]]] = [
    ("assertion_reason", re.compile(r"(?i)ASSERTION\s*(?:\(A\)\s*:?)?\s*"
                                    r"[-–—]?\s*(?:AND\s+)?REASON")),
    ("case_study", re.compile(r"(?i)CASE\s*[-–]?\s*(?:STUDY|STUDIES|BASED)")),
    ("very_short", re.compile(r"(?i)VERY\s*SHORT")),
    ("mcq", re.compile(r"(?i)MULTIPLE\s+CHOICE|\bMCQS?\b")),
    ("short", re.compile(r"(?i)\bSHORT\s+(?:ANSWER|SOLUTION)")),
    ("long", re.compile(r"(?i)\bLONG\s*(?:ANSWER|SOLUTION)")),
    ("hots", re.compile(r"(?m)^[ \t]*HOTS\b")),
]
# HOTS items are extended-response; they take the long-answer section and keep
# their printed heading so the provenance is not lost.
_FORM_OF = {"hots": "long"}

# A question opens with its number at the start of a line. Every section in
# this book numbers from 1.
_Q_START = re.compile(r"(?m)^[ \t]*(\d{1,2})[ \t]+(?=\S)")

# "SOLUTION: (D) ...", "SOLUTION:(B)", "SOLUTION : PT = RT", "Solution: Given",
# "ANS:C", "ANS: B", "ANS.C", and chapter 8's case studies' bare "SOLUTION In".
_ANSWER_MARK = re.compile(r"(?im)^[ \t]*(?:SOLUTIONS?|ANSWERS?|ANS)[ \t]*[:.\)][ \t]*"
                          r"|^[ \t]*SOLUTIONS?\b(?=[ \t]+\S)")

# Option labels: "(A) text", "a) text", "A. text", "(a)text".
_OPT_HEAD = re.compile(r"^[ \t]*\(?([A-Da-d])[\).]")
_OPT_SPLIT = re.compile(r"[ \t]{2,}(?=\(?[A-Da-d][\).])")
_OPT_POS = re.compile(r"(?<![A-Za-z0-9])\(?([A-Da-d])[\).](?=\s|\()")
_OPT_ANY = re.compile(r"(?<![A-Za-z0-9])\(?([A-Da-d])[\).]\s*"
                      r"([^()]{1,200}?)(?=\s*\(?[A-Da-d][\).]|\s*$)")

_CORRECT = re.compile(r"(?i)^\s*(?:correct\s+(?:option|answer)\s*:?\s*)?\(?([A-Da-d])[\).:]?"
                      r"(?=\s|$|\))")
_LEAD = re.compile(r"(?i)^\s*(?:correct\s+(?:option|answer)\s*:?\s*)?\(?[A-Da-d][\).]\s*")

# "Assertion (A):: text ... Reason(R) : text". The doubled marker is this
# document's own find-and-replace damage and is absorbed here.
_AR_SPLIT = re.compile(r"(?is)Assert?i?on\s*(?:\(\s*A\s*\))?\s*:+\s*(.*?)\s*"
                       r"Reason\s*\(?\s*R?\s*\)?\s*:+\s*(.*)")

# A question whose data is in a table. The statistics chapter is full of them
# and a table is not in the text layer in any usable form, so the stem arrives
# as "The following table give the life times of 400 neon lamps." and nothing
# else. "the following data: 268, 220, 368 ..." is NOT this -- that data is
# printed inline and the question stands on its own -- so the word `table` has
# to be there.
_TABLE = re.compile(r"(?i)\b(?:following|given|above|below|this|the)\s+"
                    r"(?:\w+\s+){0,3}table\b|\btable\s+(?:below|above|given)\b"
                    r"|\bdata\s+(?:above|below)\b|\bfrom the table\b"
                    r"|\b(?:found|are|is|was|were)\s+as\s+follows\b"
                    r"|\bthe given (?:information|data|frequency distribution)\b")

# A stem must never contain a solution marker. Where one does, the book's
# find-and-replace has eaten a word out of the question itself: chapter 11's
# third case study asks about "cylindrical tin Solution: to store food items",
# which was "tin cans".
_MARKER_IN_STEM = re.compile(r"(?i)\bSolution\s*:")

_FIGURE = re.compile(r"(?i)\b(in the (given |above |adjoining )?(figure|fig|layout|graph)"
                     r"|figure below|shown in (the )?fig|see fig|from the figure"
                     r"|given figure|in fig|in the given|as shown|diagram below"
                     r"|in the diagram|following figure|above figure|given graph"
                     r"|the figure|the fig\b)")

# A run of characters with no space in it that is far too long to be a word.
# The statistics chapter prints whole clauses this way. Hyphens, slashes and
# punctuation are cut first, or "Histograms-Graphical" and "observations/Number"
# read as run-ons and two sound questions are thrown away with the broken ones.
_RUNON = re.compile(r"[^\s\-/–—,;:()\[\]]{18,}")

# A number at the start of a line opens a question only if what follows it
# reads like one. "4 x 20 = 80°" is the fourth line of the working under
# question 2, and taken as question 4 it swallowed the three real questions
# after it -- they were no longer rising, so they were dropped in silence.
_WORDS = re.compile(r"[A-Za-z]{3,}")


def _deitalic(t: str) -> str:
    """Fold Mathematical Alphanumeric Symbols back onto ASCII.

    The algebra in this book is set in a maths font and the text layer keeps
    it: "3x + 2y = 76" is written with U+1D465 MATHEMATICAL ITALIC SMALL X,
    which reads as an x and is not one. Two reasons to fold it. It is four
    bytes in UTF-8, and `lms_question_master.answer` is utf8mb3, so MariaDB
    refuses the row outright -- three of the four chapters failed to load with
    "Incorrect string value: '\\xF0\\x9D\\x91\\xA5'". And a reader searching
    the bank for "3x" would never find it.

    Only the U+1D400-U+1D7FF block is folded; nothing else is normalised, so
    the degree signs and superscripts rebuilt above survive untouched.
    """
    if not any(0x1D400 <= ord(c) <= 0x1D7FF for c in t):
        return t
    return "".join(ud.normalize("NFKC", c)
                   if 0x1D400 <= ord(c) <= 0x1D7FF else c for c in t)


def _bmp(t: str) -> str:
    """Drop anything still outside the Basic Multilingual Plane.

    utf8mb3 cannot store it and the writer's retry loop cannot recover from a
    rejected row, so a single stray glyph costs the whole chapter.
    """
    return "".join(c for c in t if ord(c) <= 0xFFFF)


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", ud.normalize("NFKC", t or "").lower())


def _flat(t: str) -> str:
    return " ".join((t or "").split())


def _super(text: str, prev_char: str) -> str:
    """Render a raised run.

    A raised "0" or "o" after a digit is a degree sign -- "90o" is ninety
    degrees -- and writing it as a raised zero reproduces the very ambiguity
    that makes the flat text unreadable.
    """
    body = text.strip()
    if not body:
        return text
    # A raised zero is a degree sign. School material does not raise a zero for
    # any other reason, and the angles in this book are written both "90o" and
    # "x0" -- keying on a digit to the left left "x⁰" for "x degrees".
    if body in ("0", "o", "O", "º", "°"):
        return "°"
    if all(c in _SUPER for c in body):
        return "".join(_SUPER[c] for c in body)
    return f"^{body}" if body.isalnum() else body


def _fraction_bars(page) -> list:
    """Thin filled rules that could be a fraction bar.

    TABLE BORDERS LOOK EXACTLY THE SAME and there are five or six a page. Each
    question sits in a two-column table whose first column holds only its
    number, and the rule under that cell is 18pt wide at x=21.8 -- so the
    number of one question sat above it and the number of the next below it,
    and consecutive questions were eaten and replaced with "(3)/(4)". Two
    things tell them apart: a cell rule lives entirely inside the number
    column, and it repeats at the same place and width all the way down the
    page, which a fraction bar does not.
    """
    candidates = []
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        if rect.height <= 2.5 and 3.0 <= rect.width <= 90.0 and rect.x1 >= 45.0:
            candidates.append(rect)
    repeats: dict[tuple[int, int], int] = {}
    for rect in candidates:
        key = (round(rect.x0), round(rect.width))
        repeats[key] = repeats.get(key, 0) + 1
    return [r for r in candidates
            if repeats[(round(r.x0), round(r.width))] < 3]


def _page_text(page) -> str:
    """The page as text, with superscripts and Word fractions put back.

    Rebuilt span by span rather than taken from `get_text()`, because the two
    things that matter most here -- what was raised off the baseline, and what
    sat above a drawn rule -- exist only in the geometry.

    FRACTIONS ARE MATCHED CHARACTER BY CHARACTER, not span by span. A span is
    not the unit a fraction is written in: chapter 11 sets its working at full
    size and runs the numerator in with what precedes it, so "× 22" is one span
    of which only the "22" sits over the rule. Matching whole spans found none
    of those and left a page of "4 3 × 22 7 × 42 20" behind; worse, it paired
    the wrong halves twice and printed a fraction the book never wrote.
    """
    data = page.get_text("rawdict")
    lines: list[list[dict]] = []
    for block in data["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            # WHITESPACE-ONLY SPANS ARE KEPT. Word sets these headings in small
            # capitals, which splits "VERY SHORT ANSWER" into a span per word
            # with the spaces in spans of their own. Dropping those made the
            # heading "VERYSHORTANSWER", and then no section banner matched and
            # a whole chapter parsed as one shapeless block.
            if any(c["c"].strip() for s in line["spans"] for c in s["chars"]):
                lines.append(list(line["spans"]))

    # Every character on the page, in reading order, tagged with the span it
    # belongs to so the span's size and baseline are still available.
    chars: list[dict] = []
    for li, line in enumerate(lines):
        for si, span in enumerate(line):
            for ci, ch in enumerate(span["chars"]):
                chars.append({"c": ch["c"], "bbox": ch["bbox"],
                              "y": span["origin"][1], "line": li,
                              "span": si, "at": len(chars)})

    consumed: dict[int, str] = {}          # char index -> "" eaten, text at anchor
    for rect in sorted(_fraction_bars(page), key=lambda r: (r.y0, r.x0)):
        above, below = [], []
        for ch in chars:
            if ch["at"] in consumed or not ch["c"].strip():
                continue
            mid = (ch["bbox"][0] + ch["bbox"][2]) / 2.0
            if not rect.x0 - 1.5 <= mid <= rect.x1 + 1.5:
                continue
            if rect.y0 - 16.0 < ch["y"] <= rect.y0 + 1.0:
                above.append(ch)
            elif rect.y1 - 1.0 < ch["y"] < rect.y1 + 18.0:
                below.append(ch)
        if not above or not below:
            continue
        # ONLY THE NEAREST ROW ON EACH SIDE. The window is a line and a half
        # deep, so a superscript two lines down that happened to sit under the
        # rule was read as part of the denominator: 5/3 came out as (5)/(32),
        # and the exponent it stole vanished from the option below.
        near_above = max(c["y"] for c in above)
        near_below = min(c["y"] for c in below)
        above = [c for c in above if abs(c["y"] - near_above) < 1.5]
        below = [c for c in below if abs(c["y"] - near_below) < 1.5]
        if near_below - near_above < 5.0:
            continue                       # one row, so not a stacked fraction
        num = _flat("".join(c["c"] for c in sorted(above, key=lambda c: c["at"])))
        den = _flat("".join(c["c"] for c in sorted(below, key=lambda c: c["at"])))
        if not (num and den) or len(num) > 24 or len(den) > 24:
            continue
        if not (re.search(r"[0-9A-Za-zπ]", num)
                and re.search(r"[0-9A-Za-zπ]", den)):
            continue
        # A half that carries an equals sign or opens with an operator is the
        # rule of a neighbouring expression caught by the edge of this one.
        # Leaving it unpaired reads awkwardly; pairing it writes "(=154)/(2)",
        # which is a statement the book never made.
        if any("=" in part or re.match(r"^[+×÷*)\]]", part)
               for part in (num, den)):
            continue
        anchor = min(c["at"] for c in above + below)
        for ch in above + below:
            consumed[ch["at"]] = ""
        consumed[anchor] = f"({num})/({den})"

    by_span: dict[tuple[int, int], list[dict]] = {}
    for ch in chars:
        by_span.setdefault((ch["line"], ch["span"]), []).append(ch)

    out: list[str] = []
    for li, line in enumerate(lines):
        body = [s for si, s in enumerate(line)
                if any(c["at"] not in consumed and c["c"].strip()
                       for c in by_span[(li, si)])]
        if body:
            dom_size = max(s["size"] for s in body)
            dom_base = max(s["origin"][1] for s in body)
        else:
            dom_size, dom_base = 0.0, 0.0
        piece = ""
        prev_x1 = None
        for si, span in enumerate(line):
            text = ""
            for ch in by_span[(li, si)]:
                if ch["at"] in consumed:
                    text += consumed[ch["at"]]
                else:
                    text += ch["c"]
            if not text:
                continue
            for bad, good in _PUA.items():
                text = text.replace(bad, good)
            # A visible gap with no space glyph in it is still a space, which
            # is what `get_text` does and what the option and banner patterns
            # are written against.
            if (prev_x1 is not None and span["bbox"][0] - prev_x1 > 1.5
                    and piece and not piece[-1:].isspace()
                    and not text[:1].isspace()):
                piece += " "
            raised = (dom_size - span["size"] > 1.5
                      and dom_base - span["origin"][1] > 1.0)
            piece += _super(text, piece[-1:] if piece else "") if raised else text
            prev_x1 = span["bbox"][2]
        if _RUNNING_HEAD.match(piece):
            continue
        if _FOLIO.match(piece) and line[0]["origin"][1] > page.rect.height - 50:
            continue
        out.append(_bmp(_deitalic(_REPLACE_DAMAGE.sub("Answer", piece))).rstrip())
    return "\n".join(out)


def _chapter_text(doc, first: int, last: int) -> tuple[str, list[tuple[int, int]]]:
    """The chapter's text, plus (offset, pdf_page) so an item can name its page."""
    parts: list[str] = []
    offsets: list[tuple[int, int]] = []
    total = 0
    for pno in range(first, last + 1):
        text = _page_text(doc[pno - 1]) + "\n"
        offsets.append((total, pno))
        parts.append(text)
        total += len(text)
    return "".join(parts), offsets


def _page_of(offsets: list[tuple[int, int]], pos: int) -> int:
    page = offsets[0][1]
    for start, pno in offsets:
        if start <= pos:
            page = pno
        else:
            break
    return page


def _monotonic(hits: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    """Keep the rising run, discard working and table cells that open with a figure."""
    out: list[tuple[int, int, int]] = []
    last = 0
    for start, end, num in hits:
        if num == last + 1 or (out and last < num <= last + 2):
            out.append((start, end, num))
            last = num
        elif not out and num <= 2:
            # Chapter 4's first case study lost its "1" to the text layer, so
            # the section opens at 2. Anchoring only on 1 threw the whole
            # section away; the rising run still rejects a stray figure.
            out.append((start, end, num))
            last = num
    return out


def _numbered(block: str) -> list[tuple[int, int, str]]:
    """Cut a section into (number, start, body) on its rising run of numbers."""
    hits = []
    for m in _Q_START.finditer(block):
        num = int(m.group(1))
        if not 0 < num <= 40:
            continue
        stop = block.find("\n", m.end())
        rest = block[m.end(): stop if stop > 0 else len(block)]
        if len(_WORDS.findall(rest)) < 2:
            continue                       # a line of working, not a question
        hits.append((m.start(), m.end(), num))
    hits = _monotonic(hits)
    out = []
    for i, (start, end, num) in enumerate(hits):
        stop = hits[i + 1][0] if i + 1 < len(hits) else len(block)
        out.append((num, start, block[end:stop]))
    return out


def _sections(body: str) -> list[tuple[int, str, str]]:
    """Where each printed section banner starts: (position, form, heading)."""
    marks: list[tuple[int, int, str, str]] = []
    for rank, (name, pattern) in enumerate(_BANNERS):
        for hit in pattern.finditer(body):
            line_start = body.rfind("\n", 0, hit.start()) + 1
            line_end = body.find("\n", hit.end())
            heading = _flat(body[line_start: line_end if line_end > 0 else len(body)])
            # A banner is a heading on a line of its own, not a phrase inside a
            # question ("Choose the correct answer", "the short answer is").
            if len(heading) > 70 or not heading:
                continue
            marks.append((line_start, rank, name, heading))
    # TWO PATTERNS HIT THE SAME HEADING and the more specific one has to win:
    # "VERY SHORT ANSWER TYPE" matches both `very_short` and `short`, and sorted
    # by name `short` came first, so every very-short section in the book was
    # stored as a three-mark short answer. `_BANNERS` is ordered most specific
    # first and that rank is the tie-break.
    marks.sort(key=lambda m: (m[0], m[1]))
    deduped: list[tuple[int, str, str]] = []
    for pos, _, name, heading in marks:
        if deduped and pos == deduped[-1][0]:
            continue
        deduped.append((pos, name, heading))
    return deduped


def _options(block: str) -> list[dict]:
    """The four printed choices, however this chapter laid them out."""
    opts: dict[str, str] = {}

    def keep(label: str, text: str) -> None:
        label, text = label.upper(), _flat(text)
        if text and label not in opts:
            opts[label] = text[:240]

    def run_scan(text: str) -> dict[str, str]:
        """A, B, C, D in that order, cut at their labels."""
        run, want = [], "ABCD"
        for m in _OPT_POS.finditer(text):
            if m.group(1).upper() == want[len(run)]:
                run.append(m)
                if len(run) == 4:
                    break
        if len(run) != 4:
            return {}
        found: dict[str, str] = {}
        for i, m in enumerate(run):
            stop = run[i + 1].start() if i + 1 < len(run) else len(text)
            found[m.group(1).upper()] = _flat(text[m.end():stop])[:240]
        return found

    for raw in block.splitlines():
        if not _OPT_HEAD.match(raw):
            continue
        for piece in _OPT_SPLIT.split(raw):
            m = re.match(r"[ \t]*\(?([A-Da-d])[\).][ \t]*(.+)", piece)
            if m:
                keep(m.group(1), m.group(2))

    # "(A) a square (B)a rectangle (C) a rhombus (D) a parallelogram" -- four on
    # one line with single spaces between them, so the line pass takes them for
    # one long option A. Rescan JUST THAT LINE. Scanning the whole block instead
    # reaches back into the stem, and "O is joined to A. If P and Q are the
    # mid-points..." offered that sentence as option A of a question whose real
    # first choice was "a square".
    if len(opts) != 4:
        for raw in block.splitlines():
            if not _OPT_HEAD.match(raw):
                continue
            found = run_scan(_flat(raw))
            if found and all(found.values()):
                opts = dict(found)
                break

    # EVERY REMAINING FALLBACK IS CONFINED TO THE OPTION REGION -- from the
    # first labelled line to the end. Let one reach back into the stem and an
    # "A." that merely ends a sentence becomes option A.
    lines = block.splitlines()
    head = next((i for i, ln in enumerate(lines) if _OPT_HEAD.match(ln)), None)
    region = "\n".join(lines[head:]) if head is not None else block

    if len(opts) != 4:
        found = run_scan(_flat(region))
        if found:
            opts = found

    if len(opts) != 4:
        found = _OPT_ANY.findall(_flat(region))
        if len({lab.upper() for lab, _ in found}) == 4:
            opts = {}
            for lab, text in found:
                keep(lab, text)
    return [{"label": k, "text": opts[k]} for k in sorted(opts)]


def _directions(preamble: str) -> list[dict]:
    """The four shared choices printed once above an assertion-reason section."""
    opts: dict[str, str] = {}
    for raw in preamble.splitlines():
        m = re.match(r"[ \t]*\(?([A-Da-d])\)?\s*[\).]\s*(?:\)|\.)?\s*(.{10,200})", raw)
        if m and re.search(r"(?i)assertion|reason|\bA\b.*\bR\b", m.group(2)):
            opts.setdefault(m.group(1).upper(), _flat(m.group(2))[:240])
    return ([{"label": k, "text": opts[k]} for k in sorted(opts)]
            if len(opts) == 4 else [])


def _garbled(stem: str) -> str:
    """Why this stem cannot be put in front of a student, or "" if it can."""
    runon = [t for t in _RUNON.findall(stem)
             if sum(c.isalpha() for c in t) >= 12]
    if runon:
        return f"word spaces missing in the source ({runon[0][:40]}...)"
    if re.search(r"(?<![\w)])\d+\s+\d+\s*[πa-zA-Z(]", stem) and "/" not in stem:
        return "a fraction the text layer split and the rebuild did not pair"
    return ""


def _key_from(text: str, want: int) -> list[str]:
    """`want` answer letters read off an exercise key, or [] if it is not certain.

    Two layouts, and the count is the guard on both. Chapter 4 prints its key
    as a four-column table and the text layer scatters it, so the numbers and
    the letters land in different places; there the bare ordered letters are
    all there is. A block that does not yield exactly one letter per question
    is not used at all -- a key that is short by one shifts every answer after
    it onto the wrong question and nothing downstream can see that.
    """
    numbered = re.findall(r"(?<![\w.])(\d{1,2})\s*[.\)]\s*\(?([A-Da-d])\)?(?![\w])", text)
    if len(numbered) == want and [int(n) for n, _ in numbered] == list(range(1, want + 1)):
        return [c.upper() for _, c in numbered]
    ordered = re.findall(r"(?m)^[ \t]*\(?([A-Da-d])\)[ \t]", text)
    if len(ordered) == want:
        return [c.upper() for c in ordered]
    return []


def _build_item(num: int, block: str, form: str, heading: str, page: int,
                ar_opts: list[dict], answer: str,
                worked: bool) -> tuple[dict | None, str]:
    """Shape one question, or say why it was held."""
    choice = form in ("mcq", "assertion_reason")
    opts = _options(block) if choice else []
    if form == "assertion_reason" and not opts:
        opts = list(ar_opts)

    # An option's text can pick up the NEXT option's label when the book runs
    # them together on one line: "343/2 π cm³ c)". Only a label that leaves the
    # brackets unbalanced is a stray one, though -- the "a)" ending the option
    # "(0, a)" is the coordinate, and stripping it turned four sound choices
    # into "(0,", "(a," and "(a, -".
    for opt in opts:
        text = opt["text"]
        if text.count("(") < text.count(")"):
            text = re.sub(r"\s*\(?[A-Da-d][\).]\s*$", "", text)
        opt["text"] = re.sub(r"\s*\($", "", text).strip()
    if choice:
        for opt in opts:
            if not opt["text"]:
                return None, "an option whose text did not survive the layout"
            if re.search(r"[=+−–—\-×÷/:]\s*$", opt["text"]):
                return None, ("an option the layout cut in half "
                              f"({opt['label']}: {opt['text'][:40]!r})")

    stem_src = "\n".join(ln for ln in block.splitlines()
                         if not (choice and _OPT_HEAD.match(ln)))
    stem = _flat(stem_src)
    if choice and opts:
        for opt in opts:                   # options that wrapped onto the stem line
            for lab in (opt["label"], opt["label"].lower()):
                for pat in (f"({lab}) ", f"({lab})", f"{lab}) ", f"{lab})", f"{lab}. "):
                    stem = stem.replace(pat + opt["text"], " ")
        # A choice whose label and text were split across lines by a fraction
        # leaves the text behind, unlabelled, at the END of the stem. Only the
        # tail is peeled: an option's words can legitimately appear inside the
        # question, and deleting every occurrence turned "If each observation of
        # the data is increased by 5 then their mean:" into "If each observation
        # of the data then their mean:" -- option (d) was "is increased by 5".
        texts = [o["text"] for o in opts if len(o["text"]) >= 8]
        for _ in range(8):
            stem = re.sub(r"\s*\(?[A-Da-d][\).]\s*$", "", stem.rstrip()).rstrip()
            hit = next((t for t in texts if stem.endswith(t)), None)
            if not hit:
                break
            stem = stem[: -len(hit)].rstrip()
        stem = _flat(stem)

    assertion = reason = ""
    if form == "assertion_reason":
        m = _AR_SPLIT.search(stem)
        if not m:
            return None, "assertion-reason item that does not split into A and R"
        assertion, reason = _flat(m.group(1)), _flat(m.group(2))
        stem = f"Assertion (A): {assertion}  Reason (R): {reason}"

    if len(stem) < 18:
        return None, "stem too short to be a question"
    why = _garbled(stem)
    if why:
        return None, why
    if _FIGURE.search(stem):
        return None, "needs a figure this bank does not ship"
    if _TABLE.search(stem):
        return None, "needs a table the text layer does not carry"
    if _MARKER_IN_STEM.search(stem):
        return None, "the find-and-replace ate a word out of the question"

    # THE PRINTED SOLUTION IS SOMETIMES A DRAWING. Half the statistics chapter
    # answers "Draw a histogram for the data above" with the histogram, and
    # what reaches the text layer is the word ANS and nothing after it. The
    # marker was found, so the item looked answered; it was not.
    #
    # Only free-response items are judged this way. A choice question's whole
    # printed answer is often the single letter "c", and requiring three
    # characters of it threw away every mcq and every assertion-reason item in
    # the book -- 105 items where there had been 177.
    if worked and not choice:
        flat_answer = _flat(answer)
        if len(re.sub(r"[^0-9A-Za-z]", "", flat_answer)) < 3:
            return None, "the printed solution is a drawing or a table, not text"
        if "= =" in flat_answer or "==" in flat_answer:
            return None, "the working lost a value the layout moved elsewhere"

    correct = ""
    overruled = ""
    if choice:
        if len(opts) != 4:
            return None, f"a choice question that yielded {len(opts)} options, not 4"
        m = _CORRECT.match(answer)
        if m:
            correct = m.group(1).upper()
        if correct not in {o["label"] for o in opts}:
            return None, "no answer letter could be read from the solution"

        # THE LETTER IS NOT RELIABLE, THE VALUE IS -- but only where a value
        # was printed. An exercise answer is the bare letter off the key, and
        # comparing "d" against the options matched "doubled" on its first
        # character and overruled a correct key with a wrong one.
        quoted = _norm(_LEAD.sub("", answer)[:70])
        if worked and len(quoted) >= 4:
            match = [o["label"] for o in opts
                     if (n := _norm(o["text"])) and len(n) >= 4
                     and (n.startswith(quoted[:len(n)])
                          or quoted.startswith(n[:len(quoted)]))]
            if len(match) == 1 and match[0] != correct:
                overruled = f"book said {correct}, the value it quotes is {match[0]}"
                correct = match[0]

    return {
        "number": num, "form": _FORM_OF.get(form, form), "printed_form": form,
        "section_heading": heading, "page": page,
        "stem": stem, "options": opts, "correct_option": correct,
        "answer": _flat(answer)[:4000],
        **({"assertion": assertion, "reason": reason} if assertion else {}),
        "concept": "", "needs_reading": True,
        **({"overruled": overruled} if overruled else {}),
    }, ""


def _harvest(body: str, offsets: list[tuple[int, int]], base: int,
             worked: bool, keys: dict[str, list[str]],
             items: list, held: list, overruled: list, chapter: int) -> None:
    """Cut one half of a chapter into items."""
    marks = _sections(body)
    if not marks:
        return
    for i, (pos, form, heading) in enumerate(marks):
        stop = marks[i + 1][0] if i + 1 < len(marks) else len(body)
        section = body[pos:stop]
        numbered = _numbered(section)
        preamble = section[:numbered[0][1]] if numbered else section
        ar_opts = _directions(preamble) if form == "assertion_reason" else []
        key = keys.get(form, []) if not worked else []

        for num, start, block in numbered:
            page = _page_of(offsets, base + pos + start)
            # THE LAST QUESTION OF A SECTION RUNS INTO THE NEXT BANNER, because
            # its block ends only where the following number begins. The banner
            # and its preamble then read as part of the question, and the last
            # option of the last MCQ in every exercise section ended "... a
            # parallelogram ASSERTION".
            edge = min((m.start() for _, pat in _BANNERS
                        for m in [pat.search(block)] if m), default=len(block))
            block = block[:edge]
            where = f"ch{chapter} {'worked' if worked else 'exercise'} {form} q{num}"

            if worked:
                marker = list(_ANSWER_MARK.finditer(block))
                if not marker:
                    held.append((where, "the book prints no solution", block))
                    continue
                if form == "case_study" and len(marker) > 1:
                    held.append((where, "case study whose sub-answers are printed "
                                        "between its sub-questions", block))
                    continue
                question = block[:marker[0].start()]
                answer = block[marker[0].end():]
                # AN OPTION LIST PUSHED PAST THE SOLUTION BY A PAGE BREAK still
                # belongs to the question -- chapter 4 question 10 prints its
                # four choices on the next page, below its own answer. Only
                # reach into the answer when the question is actually short of
                # options, though: a solution opening "b) 150.8 cm³" reads as an
                # option too, and pulling it in overwrote a correct option D.
                if form in ("mcq", "assertion_reason") and len(_options(question)) != 4:
                    for line in answer.splitlines():
                        if _OPT_HEAD.match(line):
                            question += "\n" + line
            else:
                if not key:
                    held.append((where, "exercise section with no usable key", block))
                    continue
                if num > len(key):
                    held.append((where, "exercise question beyond the end of its key",
                                 block))
                    continue
                question, answer = block, key[num - 1]

            item, why = _build_item(num, question, form, heading, page,
                                    ar_opts, answer, worked)
            if item is None:
                held.append((where, why, block))
                continue
            if not worked:
                letter = item["correct_option"]
                text = next((o["text"] for o in item["options"]
                             if o["label"] == letter), "")
                item["answer"] = _flat(f"{letter}) {text}")
                item["reproduction"] = "verbatim"
            item["chapter_number"] = chapter
            item["half"] = "worked" if worked else "exercise"
            if item.pop("overruled", ""):
                overruled.append((where, item["correct_option"]))
            items.append(item)


def build() -> dict:
    doc = fitz.open(SOURCE)
    items: list[dict] = []
    held: list[tuple[str, str, str]] = []
    overruled: list[tuple[str, str]] = []
    spans: dict[int, dict] = {}

    for chapter, meta in sorted(CHAPTERS.items()):
        first, last = meta["pages"]
        text, offsets = _chapter_text(doc, first, last)

        # The span must open on this chapter's own banner. An off-by-one files
        # a whole section under the neighbour and nothing afterwards can see it.
        head = _page_text(doc[first - 1]).upper()
        want = re.sub(r"[^A-Z]", "", meta["title"])[:14]
        if want not in re.sub(r"[^A-Z]", "", head):
            raise SystemExit(f"ch{chapter}: page {first} does not open "
                             f"{meta['title']!r} -- the span is wrong")
        spans[chapter] = {"pages": meta["pages"], "title": meta["title"],
                          "chars": len(text)}

        cut = _EXERCISE.search(text)
        worked = text[:cut.start()] if cut else text
        rest = text[cut.end():] if cut else ""
        keyhit = _KEYBLOCK.search(rest)
        exercise = rest[:keyhit.start()] if keyhit else rest
        keytext = rest[keyhit.end():] if keyhit else ""

        # How many questions each exercise section prints, so its key can be
        # checked for length before any of it is believed.
        keys: dict[str, list[str]] = {}
        if keytext:
            kmarks = _sections(keytext)
            counts: dict[str, int] = {}
            for i, (pos, form, _) in enumerate(_sections(exercise)):
                stop = ([m[0] for m in _sections(exercise)] + [len(exercise)])[i + 1]
                counts[form] = len(_numbered(exercise[pos:stop]))
            for i, (pos, form, _) in enumerate(kmarks):
                if form not in ("mcq", "assertion_reason"):
                    continue
                stop = kmarks[i + 1][0] if i + 1 < len(kmarks) else len(keytext)
                want_n = counts.get(form, 0)
                if want_n:
                    found = _key_from(keytext[pos:stop], want_n)
                    if found:
                        keys[form] = found

        _harvest(worked, offsets, 0, True, {}, items, held, overruled, chapter)
        if exercise:
            base = len(text) - len(rest) + 0
            _harvest(exercise, offsets, base, False, keys, items, held,
                     overruled, chapter)

    doc.close()
    return {"items": items, "held": held, "overruled": overruled, "spans": spans}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent
                                         / "kvs_ssm_c9_items" / "drafts"))
    ap.add_argument("--show-held", action="store_true")
    a = ap.parse_args()

    if not SOURCE.exists():
        raise SystemExit(f"Source not mirrored: {SOURCE}")
    r = build()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "c9_maths_kvs_ssm.json").write_text(json.dumps(
        {"book": "c9_maths_kvs_ssm_mysuru", "source": SOURCE.name,
         "source_url": SOURCE_URL, "portal_url": PORTAL_URL,
         "source_tier": "C", "session": "2025-26",
         "publisher": "kvs_ziet_mysuru",
         "validation_status": "sourced_verbatim",
         "items": r["items"]}, indent=1, ensure_ascii=False), encoding="utf-8")

    print("Class 9 Mathematics -- KVS ZIET Mysuru Student Support Material 2025-26\n")
    print(f"  {'pdf ch':>6} {'pages':>9}  {'title':<34} {'our ch':>6}  our chapter")
    print("  " + "-" * 104)
    for ch, meta in sorted(CHAPTERS.items()):
        lo, hi = meta["pages"]
        print(f"  {ch:>6} {f'{lo}-{hi}':>9}  {meta['title'][:34]:<34} "
              f"{meta['our_sort']:>6}  {meta['our_name']}")

    forms = ["mcq", "assertion_reason", "very_short", "short", "long", "case_study"]
    print(f"\n  {'ch':>3} {'half':<9} " + " ".join(f"{f[:9]:>9}" for f in forms)
          + f" {'total':>6}")
    print("  " + "-" * 84)
    for ch in sorted(CHAPTERS):
        for half in ("worked", "exercise"):
            group = [i for i in r["items"]
                     if i["chapter_number"] == ch and i["half"] == half]
            if not group:
                continue
            row = {f: sum(1 for i in group if i["form"] == f) for f in forms}
            print(f"  {ch:>3} {half:<9} " + " ".join(f"{row[f]:>9}" for f in forms)
                  + f" {len(group):>6}")
    print("  " + "-" * 84)
    print(f"  {'':>3} {'all':<9} " + " ".join(
        f"{sum(1 for i in r['items'] if i['form'] == f):>9}" for f in forms)
        + f" {len(r['items']):>6}")

    reasons: dict[str, list] = {}
    for where, why, block in r["held"]:
        reasons.setdefault(why, []).append((where, block))
    print(f"\n  held back at parse time ({len(r['held'])}):")
    for why in sorted(reasons, key=lambda k: -len(reasons[k])):
        group = reasons[why]
        print(f"    {len(group):>3}  {why}")
        if a.show_held:
            for where, block in group[:6]:
                print(f"           {where}: {_flat(block)[:84]}")

    if r["overruled"]:
        print(f"\n  the solution's letter disagreed with the value it quotes "
              f"({len(r['overruled'])}), and the value won:")
        for where, now in r["overruled"]:
            print(f"      {where} -> {now}")

    print(f"\ndraft in {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
