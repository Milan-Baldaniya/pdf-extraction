"""One parser for the NODIA "QB 2026" chapter-wise banks, driven by a registry.

    python -m scripts.parse_nodia_qb --book c6_social
    python -m scripts.parse_nodia_qb --book c7_social      # regression check

These books share a house style and differ in the details that matter most,
so each is declared in `BOOKS` rather than given its own parser. The details
that differ, and that silently destroy a run when assumed:

  ANSWER MARKER      Class 7 Social Science prints `AAns` -- a doubled first
                     letter the text layer keeps, as in "NNCERT EXERCIS".
                     Class 6 Social Science prints `Ans :` and holds no
                     `AAns` at all. Parsed with the other book's marker,
                     either one yields nothing and reports no error.
  PARTS              Class 7 is printed in two parts whose chapter numbers
                     RESTART, so "CHAP 1" names two different chapters and
                     the part is what disambiguates. Class 6 has one part.
  FOLIO OFFSET       measured at run time, never assumed.

Everything else is shared, and each rule below was learned from a real
failure:

  * Chapter comes from the printed folio range, not the running header.
  * FOUR LABELLED OPTIONS PLUS AN ANSWER THAT NAMES ONE IS AN MCQ, whatever
    the section banner says -- one Class 7 chapter prints no MULTIPLE CHOICE
    heading at all and reported zero against sixty in its siblings.
  * The key comes from the answer's VALUE, not its letter. A printed letter
    can name a different option than the value beside it, and `V-02` cannot
    see the difference.
  * Banners are letter-spaced ("MULT IPL E CHOICE QUESTIO"), so they are
    matched with whitespace removed, and must be short and capitalised or a
    prose sentence about multiple-choice questions re-types the chapter.
  * A one-word answer is a complete answer.
  * pdf.tube advertisement pages sit INSIDE chapter ranges and are dropped.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import fitz  # noqa: E402

fitz.TOOLS.mupdf_display_errors(False)

MIRROR = Path(__file__).resolve().parents[1] / "data" / "qbank" / "mirror" / "pdftube"
SOURCE_URL = "https://pdf.tube/School/CBSE/"

BOOKS: dict[str, dict] = {
    "c9_hindi": {
        "file": "c9_CBSE_9th_Hindi_R1.pdf",
        "standard_id": 42, "standard": 9, "publisher": "nodia",
        # The marker is printed in a legacy font encoding on most pages
        # -- "mmUkj%" is how the text layer renders उत्तर: -- and in
        # proper Unicode on the rest. 1,776 of the first, 382 of the
        # second. Either alone loses most of the book.
        "marker": r"(?m)^\s*(?:mmÙkj|उत्तर)\s*[%:।]?\s*",
        # QUESTIONS ARE NUMBERED "6-", ANSWERS SUB-POINT WITH "1.".
        # Sharing one pattern, the first sub-point of every answer reads
        # as the next question and truncates the answer to nothing.
        "qstart": r"(?m)^[ 	]*(\d{1,3})\s*[-–]\s*",
        "option_labels": "कखगघ",
        "subject_of_part": {1: "Hindi-A"},
        "title": "NODIA Class 9 Hindi R-1 Question Bank 2026",
        "textbook": "गंगा (NEP-2020)",
        # Only the खंड-ग literature section. The अपठित, व्याकरण and
        # रचनात्मक लेखन sections are not chapters the database holds.
        "chapters": [
            (1, 1, "दो बैलों की कथा", 81, 109),
            (1, 2, "क्या लिखूँ?", 110, 134),
            (1, 3, "संवादहीन", 135, 160),
            (1, 4, "ऐसी भी बातें होती हैं", 161, 186),
            (1, 5, "आखिरी चट्टान तक", 187, 210),
            (1, 6, "रीढ़ की हड्डी", 211, 231),
            (1, 7, "मैं और मेरा देश", 232, 257),
            (1, 8, "पद", 258, 273),
            (1, 9, "राम-लक्ष्मण-परशुराम संवाद", 274, 297),
            (1, 10, "भारति, जय, विजयकरे!", 298, 316),
            (1, 11, "झाँसी की रानी", 317, 349),
            (1, 12, "घर की याद", 350, 381),
        ],
    },
    "c6_social": {
        "file": "c6_Social_Science_QB_2026.pdf",
        "standard_id": 39, "standard": 6, "publisher": "nodia",
        "marker": r"(?m)^\s*Ans\b\s*[:.]?\s*",
        "subject_of_part": {1: "Social Sciences"},
        "title": "NODIA Class 6 Social Science Question Bank 2026",
        "textbook": "Exploring Society: India and Beyond (NEP-2020)",
        "chapters": [
            (1, 1, "Locating Places on the Earth", 5, 19),
            (1, 2, "Oceans and Continents", 20, 35),
            (1, 3, "Landforms and Life", 36, 50),
            (1, 4, "Timeline and Sources of History", 51, 67),
            (1, 5, "India, That Is Bharat", 68, 83),
            (1, 6, "The Beginnings of Indian Civilisation", 84, 101),
            (1, 7, "India's Cultural Roots", 102, 119),
            (1, 8, "Unity in Diversity, or 'Many in the One'", 120, 138),
            (1, 9, "Family and Community", 139, 157),
            # The book's own wording, which is what the running header
            # prints. These three share a long prefix, so a short key
            # matches all of them: at 22 characters chapter 10 took one
            # page, 11 took ten, and 12 swallowed 276.
            (1, 10, "Grass roots Democracy Governance", 158, 175),
            (1, 11, "Grass roots Democracy Local Government in Rural Areas", 176, 195),
            (1, 12, "Grass roots Democracy Local Government in Urban Areas", 196, 215),
            (1, 13, "The Value of Work", 216, 233),
            (1, 14, "Economic Activities Around Us", 234, 250),
        ],
    },
    "c7_science": {
        "file": "c7_Science_QB_2026.pdf",
        "standard_id": 40, "standard": 7, "publisher": "nodia",
        "marker": r"(?m)^\s*Ans\b\s*[:.]?\s*",
        "subject_of_part": {1: "Science"},
        "title": "NODIA Class 7 Science Question Bank 2026",
        "textbook": "Curiosity (NEP-2020)",
        # The book's own contents wording, which is what the running header
        # prints. Chapter 11 is "Light - Shadows and Reflections" in the
        # database and "Light - Shadows and Re(fl)ections" in the text layer,
        # where the fl is a single ligature glyph that squashes away; the key
        # shortens past it.
        "chapters": [
            (1, 1, "The Ever-Evolving World of Science", 5, 11),
            (1, 2, "Exploring Substances : Acidic, Basic and Neutral", 12, 34),
            (1, 3, "Electricity Circuits and their Components", 35, 64),
            (1, 4, "The World of Metals and Non-metals", 65, 89),
            (1, 5, "Changes Around Us Physical and Chemical", 90, 114),
            (1, 6, "Adolescence A Stage of Growth and Change", 115, 137),
            (1, 7, "Heat Transfer in Nature", 138, 162),
            (1, 8, "Measurement of Time and Motion", 163, 185),
            (1, 9, "Life Processes in Animals", 186, 207),
            (1, 10, "Life Processes in Plants", 208, 233),
            (1, 11, "Light Shadows and Reflections", 234, 261),
            (1, 12, "Earth, Moon and the Sun", 262, 284),
        ],
    },
    "c7_social": {
        "file": "c7_Social_Science_QB_2026.pdf",
        "standard_id": 40, "standard": 7, "publisher": "nodia",
        "marker": r"(?m)^\s*A?Ans\b\s*",
        "subject_of_part": {1: "Social Sciences", 2: "Social Sciences-2"},
        "title": "NODIA Class 7 Social Science Question Bank 2026",
        "textbook": "Exploring Society: India and Beyond (NEP-2020)",
        "chapters": [
            (1, 1, "Geographical Diversity of India", 7, 30),
            (1, 2, "Understanding the Weather", 31, 54),
            (1, 3, "Climates of India", 55, 80),
            (1, 4, "New Beginnings: Cities and States", 81, 104),
            (1, 5, "The Rise of Empires", 105, 129),
            (1, 6, "The Age of Reorganisation", 130, 155),
            (1, 7, "The Gupta Era: An Age of Tireless Creativity", 156, 180),
            (1, 8, "How the Land Becomes Sacred", 181, 205),
            (1, 9, "From the Rulers to the Ruled: Types of Governments", 206, 230),
            (1, 10, "The Constitution of India: An Introduction", 231, 256),
            (1, 11, "From Barter to Money", 257, 281),
            (1, 12, "Understanding Markets", 282, 306),
            (2, 1, "The Story of Indian Farming", 307, 331),
            (2, 2, "India and Her Neighbours", 332, 352),
            (2, 3, "Empires and Kingdoms: 6th to 10th Centuries", 353, 377),
            (2, 4, "Turning Tides: 11th and 12th Centuries", 378, 401),
            (2, 5, "India, a Home to Many", 402, 425),
            (2, 6, "The State, the Government, and You", 426, 451),
            (2, 7, "Infrastructure: Engine of India's Development", 452, 478),
            (2, 8, "Banks and the Magic of Finance", 479, 503),
        ],
    },
}

_QSTART = re.compile(r"(?m)^[ \t]*(\d{1,3})\s*\.\s*(?=\S|$)")
_OPT_LINE = re.compile(r"(?m)^[ \t]*\(\s*([A-Da-d])\s*\)[ \t]*(.+?)[ \t]*$")
_OPT_ANY = re.compile(r"\(\s*([A-Da-d])\s*\)\s*([^()]{1,200}?)(?=\s*\(\s*[A-Da-d]\s*\)|\s*$)")
_LEAD = re.compile(r"(?i)^\s*\(?\s*([A-Da-d])\s*\)?[.\s]*")

BANNERS = [
    ("MULTIPLECHOICE", "mcq"), ("ASSERTIONREASON", "assertion_reason"),
    ("CASESTUDY", "case_study"), ("CASEBASED", "case_study"),
    ("VERYSHORT", "very_short"), ("SHORTANSWER", "short"),
    ("LONGANSWER", "long"), ("NCERTEXERCIS", "short"),
    ("COMPETENCYBASED", "short"),
]


def _squash(s: str) -> str:
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def _norm(t: str) -> str:
    """Fold to comparable characters, KEEPING non-Latin scripts.

    An ASCII-only class silently erases Devanagari: every Hindi stem folds to
    the empty string, so the dedupe sees one question repeated and the answer
    key never matches its option. Class 9 Hindi lost 599 of 1,180 items to a
    "printed twice" that was really "both normalised to nothing".
    """
    return re.sub(r"[^0-9a-zऀ-ॿঀ-৿਀-੿]", "",
                  (t or "").lower())


def _is_ad(text: str) -> bool:
    return "pdf.tube" in text and "Ans" not in text


def _is_banner(line: str) -> str:
    s = line.strip()
    if not (6 <= len(s) <= 58):
        return ""
    letters = [c for c in s if c.isalpha()]
    if not letters or sum(c.isupper() for c in letters) / len(letters) < 0.75:
        return ""
    sq = _squash(s)
    for key, f in BANNERS:
        if key in sq:
            return f
    return "skip" if "MATCHINGTYPE" in sq else ""


def _form_at(body: str, pos: int, default: str = "short") -> str:
    form = default
    for line in body[:pos].splitlines():
        f = _is_banner(line)
        if f:
            form = f
    return form


def _label_set(cfg) -> tuple[str, dict]:
    """The option letters this book prints, and how they map to A-D.

    Hindi marks its choices (क)(ख)(ग)(घ), not (A)(B)(C)(D) -- 6,000 of
    them in Class 9 Hindi R-1. Matched only against Latin letters, every
    multiple-choice question in the book reads as a plain short answer.
    `answer_master` stores option ORDER and a correct flag, never the
    printed letter, so folding to A-D loses nothing.
    """
    labs = cfg.get("option_labels") or "ABCD"
    table = {}
    for i, ch in enumerate(labs):
        table[ch] = "ABCD"[i]
        table[ch.lower()] = "ABCD"[i]
    return "".join(sorted(set(labs + labs.lower()))), table


def _options(block: str, labs: str = "A-Da-d", table: dict | None = None) -> list[dict]:
    table = table or {}
    line_re = re.compile(rf"(?m)^[ 	]*\(\s*([{labs}])\s*\)[ 	]*(.+?)[ 	]*$")
    any_re = re.compile(rf"\(\s*([{labs}])\s*\)\s*([^()]{{1,200}}?)"
                        rf"(?=\s*\(\s*[{labs}]\s*\)|\s*$)")
    opts: dict[str, str] = {}
    for m in line_re.finditer(block):
        lab = table.get(m.group(1), m.group(1).upper())
        txt = " ".join(m.group(2).split()).strip(" .,;")
        if txt and lab not in opts:
            opts[lab] = txt[:240]
    if sorted(opts) != ["A", "B", "C", "D"]:
        opts = {}
        for lab0, txt in any_re.findall(" ".join(block.split())):
            lab = table.get(lab0, lab0.upper())
            txt = " ".join(txt.split()).strip(" .,;")
            if txt and lab not in opts:
                opts[lab] = txt[:240]
    return ([{"label": k, "text": opts[k]} for k in sorted(opts)]
            if sorted(opts) == ["A", "B", "C", "D"] else [])


def _key(opts: list[dict], answer: str, lead_re=None, table=None) -> str:
    if not opts:
        return ""
    lead_re = lead_re or _LEAD
    table = table or {}
    body = _norm(lead_re.sub("", answer)[:120])
    hit = [o["label"] for o in opts if _norm(o["text"]) and _norm(o["text"])[:40] in body]
    if len(hit) == 1:
        return hit[0]
    m = lead_re.match(answer)
    lab = table.get(m.group(1), m.group(1).upper()) if m else ""
    return lab if lab in {o["label"] for o in opts} else ""


_FOLIO = re.compile(r"(?im)^\s*page\s+(\d{1,4})\s*$")


def _folio_map(doc, seed: int) -> list:
    """printed folio -> PDF page index, read from each page's own header.

    THERE IS NO CONSTANT OFFSET. pdf.tube inserts advertisement pages into
    the PDF that the printed numbering knows nothing about, so the gap grows
    as you go: in Class 6 Social Science chapter 1 begins at folio 5 on PDF
    page 21, and chapter 2 at folio 20 on PDF page 32 -- +16 and +12, which
    no single offset reconciles. Measured as a constant, chapter 1 returned
    13 items against 88 to 129 in its siblings.

    Every content page states its own folio in the running header ("PAGE 6"),
    so the mapping is read rather than computed.

    THE HEADER IS NOT ON EVERY PAGE -- only 248 of Class 7's 547 carry a
    readable one. So the folios that ARE read are used as anchors and carried
    forward: a page with no header belongs to the last folio seen before it.
    Keyed on readable headers alone, more than half the book is dropped and
    the Class 7 total falls from 2,545 to 1,210.

    Returns one entry per PDF page: the folio it belongs to, or None before
    the first header is seen.
    """
    out: list[int | None] = []
    # Seeded with the first chapter's opening folio so that its pages, which
    # precede the book's first readable header, are not orphaned. Front
    # matter is swept in with them and costs nothing: a cover or a contents
    # page carries no answer marker and so yields no item.
    last: int | None = seed
    for i in range(doc.page_count):
        try:
            head = "\n".join((doc[i].get_text() or "").splitlines()[:4])
        except Exception:
            head = ""
        m = _FOLIO.search(head)
        if m:
            last = int(m.group(1))
        out.append(last)
    return out


def _page_chapter(doc, chapters) -> list[tuple[int, int] | None]:
    """Which chapter each PDF page belongs to, read from its own header.

    THE BOOK IS NOT IN CHAPTER ORDER, so no contiguous span can be right.
    Class 7 Science page 210 is headed "CH 9 : LIFE PROCESSES IN ANIMALS"
    and page 212 is headed "CH 8 : MEASUREMENT OF TIME AND MOTION" --
    chapter 8 resumes after chapter 9 has begun. Given a span, chapter 9
    collected seven of chapter 8's questions about average speed, and
    chapter 11 collected chapter 10's about whether non-green parts of a
    plant respire. Compare [[qbank-two-column-scatters-sections]].

    So every page is attributed on its own header, and a page without one
    inherits the page before it. Two details the header forces:

      IT ABBREVIATES. The contents prints "Empires and Kingdoms: 6th to
      10th Centuries"; the header prints "Empires and Kingdom :" -- so the
      key shortens until it matches.

      SIBLINGS SHARE A PREFIX. Class 6's three "Grassroots Democracy"
      chapters agree for 22 characters, so the longest key is tried first
      and the registry carries the book's own wording.

    A page naming three or more chapters is the contents, not a chapter.
    """
    titles = [_squash(c[2]) for c in chapters]
    sq: list[str] = []
    for i in range(doc.page_count):
        try:
            sq.append(_squash(doc[i].get_text() or ""))
        except Exception:
            sq.append("")

    # The shortest key that identifies each chapter uniquely across the book.
    # THE LONGEST KEY THAT STILL MATCHES, not the shortest that is unique.
    # Shortened too far, "Electricity Circuits and their Components" becomes
    # "ELECTRICIT" and claims every page in the metals chapter that mentions
    # electricity -- chapter 3 took 232 questions and chapter 4 was left 52.
    keys: list[str] = []
    for k, t in enumerate(titles):
        chosen = t
        for width in (len(t), 30, 22, 18, 15, 12, 10):
            cand = t[:width]
            if not cand:
                break
            others = [u[:width] for j, u in enumerate(titles) if j != k]
            if cand not in others and any(cand in s for s in sq):
                chosen = cand
                break
        keys.append(chosen)

    out: list[tuple[int, int] | None] = []
    last: tuple[int, int] | None = None
    for i in range(doc.page_count):
        try:
            raw = doc[i].get_text() or ""
        except Exception:
            raw = ""
        hits = [k for k, key in enumerate(keys) if key and key in sq[i]]
        if len(hits) >= 3:            # the contents page
            out.append(last)
            continue
        if len(hits) == 1:
            last = (chapters[hits[0]][0], chapters[hits[0]][1])
        else:
            # NO TITLE HEADER: fall back to the folio this page prints, and
            # the range the contents gives each chapter. Carrying the last
            # chapter forward is wrong where the book interleaves -- pages
            # 211, 213 and 214 of Class 7 Science hold chapter 8 but follow
            # a page headed chapter 9, and inherited it, taking seven
            # questions about average speed into Life Processes in Animals.
            m = _FOLIO.search("\n".join(raw.splitlines()[:4]))
            if m:
                f = int(m.group(1))
                owner = [(c[0], c[1]) for c in chapters if c[3] <= f <= c[4]]
                # A folio past the last chapter is a section the database
                # does not hold -- Class 9 Hindi prints 18 pages of
                # composition exercises after folio 381, and carried
                # forward they doubled the last chapter.
                last = owner[0] if len(owner) == 1 else None
        out.append(last)
    return out


def _spans_unused(doc, chapters) -> dict[tuple[int, int], tuple[int, int]]:
    """Superseded by `_page_chapter`; kept only for the note it carries.

    NEITHER A CONSTANT OFFSET NOR THE PRINTED FOLIO SURVIVES THIS FAMILY OF
    BOOKS, and getting it wrong does not fail -- it files a chapter's
    questions under its neighbour and reports a clean load.

      a constant offset  pdf.tube inserts advertisement pages the printed
                         numbering knows nothing about, so the gap grows.
                         Class 7 Social Science loaded this way put chapter
                         1's Himalayas and Thar Desert questions under
                         "Understanding the Weather", and chapter 2's weather
                         instruments under "Climates of India" -- 2,545
                         questions, most on the wrong chapter, and the load
                         reported zero failures.
      the printed folio  readable on only 248 of 547 pages, because even
                         folios print "PAGE n" while odd ones print the
                         chapter title instead. Carried forward it lands
                         about a page early on every chapter.

    The title in the running header is the one thing that is both on most
    pages and unambiguous. Chapters are found in order, each from where the
    last one started, and each runs until the next begins. A page carrying
    three or more chapter titles is the contents, not a chapter.
    """
    # THE RUNNING HEADER ABBREVIATES THE TITLE. The contents prints "Empires
    # and Kingdoms: 6th to 10th Centuries" and the header prints "CH 3 :
    # Empires and Kingdom :" -- singular, and without the century range.
    # "Turning Tides: 11th and 12th Centuries" becomes "Turning Tides :". So
    # the key is shortened until it matches rather than fixed, and because
    # chapters are searched in order from where the last one started, a short
    # key cannot reach back into a chapter already placed.
    titles = [_squash(c[2]) for c in chapters]
    sq: list[str] = []
    for i in range(doc.page_count):
        try:
            sq.append(_squash(doc[i].get_text() or ""))
        except Exception:
            sq.append("")
    is_contents = [sum(1 for t in titles if t and t in s) >= 3 for s in sq]

    starts: list[int] = []
    cur = 0
    for k, t in enumerate(titles):
        found = None
        # Longest first: two chapters can share a 22-character prefix and
        # differ only at the end ("...in Rural Areas" vs "...in Urban").
        for width in (len(t), 30, 22, 18, 15, 12, 10):
            key = t[:width]
            if not key:
                break
            found = next((i for i in range(cur, doc.page_count)
                          if not is_contents[i] and key in sq[i]), None)
            if found is not None:
                break
        if found is None:
            raise SystemExit(f"chapter {chapters[k][2]!r} never appears as a header")
        starts.append(found)
        cur = found + 1

    out: dict[tuple[int, int], tuple[int, int]] = {}
    for k, c in enumerate(chapters):
        if k + 1 < len(starts):
            end = starts[k + 1] - 1
        else:
            last = [i for i in range(starts[k], doc.page_count)
                    if titles[k] and titles[k] in sq[i]]
            end = last[-1] if last else doc.page_count - 1
        out[(c[0], c[1])] = (starts[k], end)
    return out


def _blob(doc, pages) -> tuple[str, int]:
    out, skipped = [], 0
    for p in pages:
        try:
            raw = doc[p].get_text() or ""
        except Exception:
            continue
        if _is_ad(raw):
            skipped += 1
            continue
        for ln in raw.splitlines():
            if re.match(r"^\s*page\s+\d+\s*$", ln) or "Chapterwise QB" in ln:
                continue
            out.append(ln)
    return "\n".join(out), skipped


def build(book: str) -> dict:
    cfg = BOOKS[book]
    ans_re = re.compile(cfg["marker"])
    qstart = re.compile(cfg.get("qstart") or _QSTART.pattern)
    labs, table = _label_set(cfg)
    lead_re = re.compile(rf"^\s*\(?\s*([{labs}])\s*\)?[.\s]*")
    opt_line_re = re.compile(rf"(?m)^[ 	]*\(\s*[{labs}]\s*\)")
    opt_any_re = re.compile(rf"\(\s*[{labs}]\s*\)[^()]{{0,200}}?"
                            rf"(?=\s*\(\s*[{labs}]\s*\)|\s*$)")
    doc = fitz.open(MIRROR / cfg["file"])
    doc_pages = doc.page_count
    owner = _page_chapter(doc, cfg["chapters"])
    items, dropped, ads = [], {}, 0

    for part, so, name, lo, hi in cfg["chapters"]:
        body, skipped = _blob(doc, [i for i, o in enumerate(owner) if o == (part, so)])
        ads += skipped
        qpos = [m.start() for m in qstart.finditer(body)]
        apos = list(ans_re.finditer(body))
        for k, a in enumerate(apos):
            before = [q for q in qpos if q < a.start()]
            if not before:
                continue
            start = before[-1]
            nxt_ans = apos[k + 1].start() if k + 1 < len(apos) else len(body)
            stop = min([q for q in qpos if a.end() < q <= nxt_ans] or [nxt_ans])
            raw_stem = body[start:a.start()]
            answer = " ".join(body[a.end():stop].split())
            form = _form_at(body, start)
            if form == "skip":
                dropped["matching-type exercise"] = dropped.get("matching-type exercise", 0) + 1
                continue
            opts = _options(raw_stem, labs, table)
            # Strip the options and the leading number with THIS book's
            # patterns. Using the Latin ones, a Hindi stem keeps its own
            # four choices and its "1-" inside the question text.
            stem_lines = [ln for ln in raw_stem.splitlines()
                          if not (opts and opt_line_re.match(ln))]
            stem = "\n".join(stem_lines)
            stem = qstart.sub("", stem, count=1)
            stem = " ".join(re.sub(r"^\s*\d{1,3}\s*[.\-–]\s*", "", stem).split())
            if opts:
                stem = opt_any_re.sub(" ", stem)
                stem = " ".join(stem.split())
            correct = _key(opts, answer, lead_re, table) if opts else ""
            if opts and correct:
                form = "mcq"
            elif opts:
                dropped["four options but the answer names none"] = \
                    dropped.get("four options but the answer names none", 0) + 1
                continue
            elif form in ("mcq", "assertion_reason"):
                form = "very_short"
            if len(stem.split()) < 5:
                dropped["stem under 5 words"] = dropped.get("stem under 5 words", 0) + 1
                continue
            if not answer.strip():
                dropped["no answer at all"] = dropped.get("no answer at all", 0) + 1
                continue
            items.append({
                "part": part, "chapter_number": so, "chapter": name,
                "number": len(items) + 1, "form": form, "stem": stem,
                "options": opts, "correct_option": correct,
                "answer": answer[:4000], "concept": "", "needs_reading": True,
            })
    doc.close()

    seen, unique = set(), []
    for it in items:
        k = (it["part"], it["chapter_number"],
             _norm(it["stem"] + "".join(o["text"] for o in it["options"]))[:160])
        if k in seen:
            dropped["printed twice"] = dropped.get("printed twice", 0) + 1
            continue
        seen.add(k)
        unique.append(it)
    return {"cfg": cfg, "items": unique, "dropped": dropped,
            "folios": len({o for o in owner if o}), "pages": doc_pages, "raw": len(items)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--book", choices=sorted(BOOKS), required=True)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "nodia_qb_items" / "drafts"))
    a = ap.parse_args()
    r = build(a.book)
    cfg = r["cfg"]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{a.book}.json").write_text(json.dumps(
        {"book": a.book, "source": cfg["file"], "source_url": SOURCE_URL,
         "publisher": cfg["publisher"], "textbook": cfg["textbook"],
         "session": "2026-27", "validation_status": "sourced_verbatim",
         "items": r["items"]}, indent=1, ensure_ascii=False), encoding="utf-8")

    forms = ("mcq", "very_short", "short", "long", "case_study")
    print(f"{a.book} -- {cfg['file']}")
    print(f"  {r['folios']} chapters attributed page by page from the running header, "
          f"over {r['pages']} PDF pages\n")
    print(f"  {'pt':>2} {'ch':>3} {'chapter':<48} " + " ".join(f"{f[:10]:>10}" for f in forms) + f" {'total':>6}")
    print("  " + "-" * 122)
    for part, so, name, lo, hi in cfg["chapters"]:
        ks = [i for i in r["items"] if i["part"] == part and i["chapter_number"] == so]
        print(f"  {part:>2} {so:>3} {name[:48]:<48} "
              + " ".join(f"{sum(1 for i in ks if i['form']==f):>10}" for f in forms)
              + f" {len(ks):>6}")
    print("  " + "-" * 122)
    print(f"  {'':>2} {'':>3} {'total':<48} "
          + " ".join(f"{sum(1 for i in r['items'] if i['form']==f):>10}" for f in forms)
          + f" {len(r['items']):>6}\n")
    print("  dropped:")
    for why, n in sorted(r["dropped"].items(), key=lambda x: -x[1]):
        print(f"      {n:>4}  {why}")
    print(f"\ndrafts in {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
