"""Draft question items for Class 6 English (Poorvi) from three source families.

    python -m scripts.parse_c6_english                 # every family, report
    python -m scripts.parse_c6_english --family sol    # one family
    python -m scripts.parse_c6_english --write         # write the drafts

TWENTY-ONE CHAPTER ROWS, SIXTEEN CHAPTERS. Class 6 English also holds five
unit-level placeholder rows -- "Poorvi Unit 1 - Fables and Folk Tales" through
Unit 5, ids 29889-29893 -- and they share sort_order 1..5 with the real
chapters. Anything that resolves a chapter by sort_order therefore has five
chances to file a question against a placeholder, where it would sit forever
looking loaded. CHAPTERS below is keyed by its own chapter_id and every id is
written out, so no lookup by sort_order happens anywhere in this pipeline.

THE SOURCES ARE ORGANISED BY UNIT, NOT BY CHAPTER, and each family says which
chapter it is on in a different way:

  sol     studentbro NCERT Solutions, 5 files, one per unit. Prints
          "Unit 2: Chapter 4 The Unlikely Best Friends" on the chapter's first
          page, so the chapter is READ, not inferred. Its Unit 2 file
          misprints its own header as "Class 7 English (Poorvi)" -- the body is
          Gajaraj and Buntee, which is Class 6 chapter 4, and routing on the
          header would move three chapters into another class.

  mcq     studentbro MCQ sets. NO chapter heading anywhere. Each file is a
          sequence of separate papers, each opening "STD 6 English / Total
          Marks : N" and closing "----- -----", one paper per chapter in
          chapter order. The paper count is asserted against the unit's
          membership, so a file that gained or lost a paper fails loudly
          instead of shifting every chapter by one -- the failure that filed
          2,545 pdf.tube questions under the wrong chapter.

  iq      vedantu "Important Questions", 5 files, one per unit. Prints
          "Important Questions for The Chair:" per chapter. Titles drift from
          the database's ("Change the Heart", "Ila Sanchani"), so TITLES is an
          explicit alias table -- nothing is fuzzy-matched, because a near
          miss between "The Kites" and "The Chair" is silent.

  The vedantu sol_*.pdf files are deliberately NOT parsed. They are the same
  NCERT exercises as `sol` and only three of the five carry any chapter
  heading at all; on sol_ch04.pdf the only cue is a printed page reference.
  Attributing them means carrying the last-seen chapter forward, which
  misfiled 36% of parse_kvs_english. `sol` prints the chapter on every
  chapter's first page, so it is used instead and nothing is lost.

ANSWERS IN THE MCQ FAMILY ARE A SEPARATE LAYER, NOT A KEY AT THE BACK. They
are drawn before the questions, so they come out of get_text() FIRST and any
reading order based on block index pairs them off by one. Each answer block
sits at the y of the question it belongs to, just under that question's last
option, so the pairing here is geometric: sort by (page, y) and an "Ans. :"
attaches to the question it follows. The value is then checked against the
option text, and where the printed letter and the printed value disagree the
VALUE wins -- see key_on_value().

Everything is folded to ASCII. `lms_question_master.answer` is utf8mb3 and a
single 4-byte character makes MariaDB reject the whole row.
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

MIRROR = Path(__file__).resolve().parents[1] / "data" / "qbank" / "mirror"
SB = MIRROR / "studentbro"
VD = MIRROR / "vedantu" / "c6_english_poorvi"
DRAFTS = Path(__file__).resolve().parent / "c6_english_items" / "drafts"

# sort_order, chapter_id, database chapter_name, unit number.
# THE IDS ARE THE KEY. 29889-29893 are unit placeholders and are not here.
CHAPTERS: list[tuple[int, int, str, int]] = [
    (1, 29860, "A Bottle of Dew", 1),
    (2, 29861, "The Raven and the Fox", 1),
    (3, 29862, "Rama to the Rescue", 1),
    (4, 29863, "The Unlikely Best Friends", 2),
    (5, 29864, "A Friend's Prayer", 2),
    (6, 29865, "The Chair", 2),
    (7, 29866, "Neem Baba", 3),
    (8, 29867, "What a Bird Thought", 3),
    (9, 29868, "Spices that Heal Us", 3),
    (10, 29869, "Change of Heart", 4),
    (11, 29870, "The Winner", 4),
    (12, 29871, "Yoga - A Way of Life", 4),
    (13, 29872, "Hamara Bharat - Incredible India!", 5),
    (14, 29873, "The Kites", 5),
    (15, 29874, "Ila Sachani: Embroidering Dreams with Her Feet", 5),
    (16, 29875, "National War Memorial", 5),
]
BY_SORT = {c[0]: c for c in CHAPTERS}
UNIT_MEMBERS = {u: [c[0] for c in CHAPTERS if c[3] == u] for u in (1, 2, 3, 4, 5)}

# Every spelling any source uses, normalised, mapped to sort_order. Explicit
# because "The Kites" and "The Chair" are three edits apart and a fuzzy match
# between them would be silent.
TITLES: dict[str, int] = {}


def _alias(sort_order: int, *names: str) -> None:
    for n in names:
        TITLES[_key(n)] = sort_order


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", ascii_fold(s or "").lower())


# ---------------------------------------------------------------- ascii fold

_FOLD = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "‒": "-", "―": "-",
    "‐": "-", "‑": "-", "−": "-",
    "…": "...", " ": " ", " ": " ", " ": " ",
    " ": " ", " ": " ", " ": " ", "​": "",
    "‹": "<", "›": ">", "«": '"', "»": '"',
    "·": "-", "•": "-", "­": "", "﻿": "",
    "é": "e", "è": "e", "î": "i", "ô": "o",
    "°": " degrees ", "½": "1/2", "¼": "1/4", "¾": "3/4",
    "′": "'", "″": '"', "×": "x", "÷": "/",
}
_DROPPED: set[str] = set()


def ascii_fold(s: str) -> str:
    """Fold to plain ASCII. `answer` is utf8mb3 and rejects any 4-byte char.

    A 4-byte character does not raise on the way in: MariaDB refuses the whole
    INSERT, so one stray emoji in one answer loses the chapter. Folding also
    keeps the quote anchors ASCII, which is the only form that survives a
    round trip through a JSON payload unchanged.
    """
    out: list[str] = []
    for ch in s or "":
        if ord(ch) < 128:
            out.append(ch)
            continue
        if ch in _FOLD:
            out.append(_FOLD[ch])
            continue
        decomposed = ud.normalize("NFKD", ch)
        stripped = "".join(c for c in decomposed if ord(c) < 128)
        if stripped:
            out.append(stripped)
        else:
            _DROPPED.add(ch)
            out.append(" ")
    return "".join(out)


def tidy(s: str) -> str:
    return " ".join(ascii_fold(s).split())


_alias(1, "A Bottle of Dew", "The Bottle of Dew", "Bottle of Dew")
_alias(2, "The Raven and the Fox", "Raven and the Fox")
_alias(3, "Rama to the Rescue")
_alias(4, "The Unlikely Best Friends", "Unlikely Best Friends")
_alias(5, "A Friend's Prayer", "A Friends Prayer", "Friend's Prayer")
_alias(6, "The Chair")
_alias(7, "Neem Baba")
_alias(8, "What a Bird Thought")
_alias(9, "Spices that Heal Us", "Spices That Heal Us")
_alias(10, "Change of Heart", "Change the Heart", "A Change of Heart")
_alias(11, "The Winner")
_alias(12, "Yoga - A Way of Life", "Yoga A Way of Life")
_alias(13, "Hamara Bharat - Incredible India!", "Hamara Bharat Incredible India",
       "Hamara Bharat - Incredible India")
_alias(14, "The Kites", "Kites")
_alias(15, "Ila Sachani: Embroidering Dreams with Her Feet",
       "Ila Sachani Embroidering Dreams With Her Feet",
       "Ila Sanchani - Embroidering Dreams with Her Feet",
       "Ila Sachani: Embroidering Dreams With",
       "Ila Sanchani Embroidering Dreams with Her Feet")
_alias(16, "National War Memorial")


# ------------------------------------------------------------- shared tidying

# Footers and watermarks that would otherwise land inside a stem or an answer.
NOISE = re.compile(
    r"(?im)^\s*(?:https?://\S+|www\.vedantu\.com|Class\s+(?:VI|6)\s+English\s*"
    r"|Page\s+\d+\s*|\d{1,3}\s*|STD\s+6\s+English\s*|Total\s+Marks\s*:\s*\d+\s*"
    r"|-{3,}\s*-{3,}\s*|NCERT Solutions.*|Important Questions for Class.*)$")


def strip_noise(text: str) -> str:
    return NOISE.sub("", text)


def key_on_value(options: list[dict], printed_letter: str | None,
                 printed_value: str) -> tuple[str | None, str | None]:
    """Return (label, defect) keying on the printed VALUE, not the letter.

    A solution's letter can contradict its own value and no validator sees the
    difference: the letter lands in `correct_option`, the value lands in the
    answer text, and both look well-formed. The value is what a learner is
    marked against, so the option whose text matches the value wins and the
    disagreement is reported rather than silently resolved.
    """
    want = _key(printed_value)
    if not want:
        return (printed_letter, None)
    exact = [o for o in options if _key(o["text"]) == want]
    if len(exact) == 1:
        label = exact[0]["label"]
    else:
        # The value is sometimes printed with its own trailing clause wrapped
        # off; fall back to a prefix match, but only if it is unambiguous.
        pref = [o for o in options if _key(o["text"]).startswith(want)
                or want.startswith(_key(o["text"]))]
        if len(pref) != 1:
            return (printed_letter, "value matches no single option")
        label = pref[0]["label"]
    if printed_letter and printed_letter != label:
        return (label, f"printed letter ({printed_letter}) contradicts its "
                       f"own value, which is option {label}")
    return (label, None)


# ============================================================ family: sol
# studentbro NCERT Solutions, one file per unit, chapter printed per chapter.

SOL_FILES = {u: SB / f"c6_english_sol_u{u}.pdf" for u in (1, 2, 3, 4, 5)}

SOL_HEAD = re.compile(r"(?im)^\s*Unit\s*(\d+)\s*:\s*Chapter\s*(\d+)\s+(.{3,80}?)\s*$")
SOL_Q = re.compile(r"(?im)^\s*Question\s+(\d+)\s*\.?\s*")
SOL_A = re.compile(r"(?im)^\s*Answers?\s*:\s*")
SOL_SECTION = re.compile(
    r"(?im)^\s*(Let us (?:do these activities|discuss|think and reflect|learn|"
    r"explore|use|speak|write|read|listen|play with words|understand)[^\n]{0,60})$")

# A stem or answer containing any of these is a table, a drawing task or a
# "discuss with your classmates" activity: what prints as a numbered question
# but whose answer is a grid. Parsed the usual way the stem is half the table
# and the answer is the other half, so these are held and counted.
SOL_UNUSABLE = re.compile(
    r"(?i)what happened|\boutcome\b|column\s+[ab12]|match the|word web|"
    r"circle the picture|tick the|draw a|colour the|in the table|fill in the "
    r"table|fill in the box|discuss (?:them )?with your (?:classmates|partner|friend)|"
    r"do it yourself|answers? (?:will|may) vary|in pairs|role[- ]play|"
    r"with your teacher|\bdo this yourself\b|your own (?:answer|words based)|"
    # A question about a picture cannot be answered from the text alone, and no
    # figure is extracted here, so figure_resolved would stay 0 for ever.
    r"\bpics?\b|\bpicture|\bimage given|look at the (?:pictures?|image)|"
    r"main characters|\bflow ?chart\b")

# An unsplit compound. "(i) ... (ii) ... (iii)" is two or three questions under
# one number whose answer is one paragraph covering all of them; the stem is
# then half a passage and the answer cannot be marked against any one part.
# Three or more "(a) (b) (c)" in a stem is the same thing, or an MCQ whose
# options were printed inline -- either way not one short-answer question.
SOL_COMPOUND = re.compile(r"\((?:i|ii|iii|iv|v|vi)\)")
SOL_INLINE_OPTS = re.compile(r"\([a-e]\)")

# A COMPREHENSION QUESTION EITHER ASKS SOMETHING OR TELLS YOU TO DO SOMETHING.
# The grammar and vocabulary exercises do neither: they print a sentence with a
# gap and the answer is a word pair. "The color of the feather was not dark but
# pale. at last" / "Pale - Light" is the shape, and it loads as a question with
# an answer and verifies. Filtering by section heading does not work here --
# these books print the heading once and later exercises inherit it -- so the
# gate is on the stem itself.
SOL_ASKS = re.compile(
    r"(?i)^(?:who|what|why|how|when|where|which|whose|whom|do|does|did|is|are|"
    r"was|were|can|could|will|would|should|describe|explain|discuss|write|give|"
    r"state|mention|name|list|identify|compare|imagine|suggest|think|find|say|"
    r"complete|choose|select|analyse|analyze|evaluate|justify|comment|elaborate|"
    r"support|infer|summarise|summarize|pick|read and answer)\b")
SOL_GAP = re.compile(r"\.{4,}|_{3,}|…\s*…")
SOL_WORDPAIR = re.compile(r"^[\w' ]{1,40}\s[-:]\s[\w' ]{1,40}$")

SOL_NONANSWER = re.compile(
    r"(?i)^\s*(?:do it yourself|self|answers? will vary|students?[' ]?s?\s+own|"
    r"do this (?:yourself|activity)|try (?:it|this) yourself|"
    r"answer may vary|as per|open[- ]ended)\b")

# (a) / (i) sub-part labels at the start of a line.
SUBPART = re.compile(r"(?m)^\s*\(([a-z]|i{1,3}v?|iv|vi{0,3}|ix|x)\)\s*")


def _sol_pages(path: Path) -> list[str]:
    doc = fitz.open(path)
    pages = [doc[i].get_text() for i in range(doc.page_count)]
    doc.close()
    return pages


def _split_subparts(stem: str, answer: str) -> list[tuple[str, str]] | None:
    """Split "Question 2. ... (a) ... (b) ..." into one item per sub-part.

    Only when the stem and the answer carry the SAME labels: a lead-in with
    five sub-questions and one undivided paragraph of answer cannot be cut, and
    guessing which sentence answers which part would invent the pairing.
    """
    sm = list(SUBPART.finditer(stem))
    am = list(SUBPART.finditer(answer))
    if len(sm) < 2 or len(am) < 2:
        return None
    slabels = [m.group(1) for m in sm]
    alabels = [m.group(1) for m in am]
    if slabels != alabels or len(set(slabels)) != len(slabels):
        return None
    lead = stem[:sm[0].start()].strip()
    out: list[tuple[str, str]] = []
    for i, m in enumerate(sm):
        s_end = sm[i + 1].start() if i + 1 < len(sm) else len(stem)
        a_end = am[i + 1].start() if i + 1 < len(am) else len(answer)
        part = stem[m.end():s_end].strip()
        ans = answer[am[i].end():a_end].strip()
        if not part or not ans:
            return None
        # The lead-in is kept only when the sub-part cannot stand alone.
        if lead and len(part) < 45 and not part.rstrip().endswith("?"):
            part = f"{lead} {part}"
        out.append((part, ans))
    return out


def _sol_spans(held: list[tuple[str, str]] | None = None
               ) -> list[tuple[int, str, str, int]]:
    """(sort_order, body, file name, first page) for every chapter span.

    THE CHAPTER IS READ TWICE AND THE TWO READINGS MUST AGREE. The heading gives
    both a number and a title -- "Unit 4: Chapter 10 Change the Heart" -- and
    the title is resolved through TITLES independently of the number. Agreement
    is what makes this family safe to derive the other two families' vocabulary
    from; a disagreement is reported and the span is dropped.
    """
    out: list[tuple[int, str, str, int]] = []
    for unit, path in SOL_FILES.items():
        if not path.exists():
            if held is not None:
                held.append(("source missing", path.name))
            continue
        pages = _sol_pages(path)
        starts: list[tuple[int, int, str]] = []
        for pi, t in enumerate(pages):
            for m in SOL_HEAD.finditer(t):
                printed = int(m.group(2))
                title = tidy(m.group(3))
                so = TITLES.get(_key(title))
                if so is None or so != printed or so not in UNIT_MEMBERS[unit]:
                    if held is not None:
                        held.append((
                            f"{path.name} p{pi+1}: heading numbers this chapter "
                            f"{printed} but its title resolves to {so} "
                            f"(unit {unit} holds {UNIT_MEMBERS[unit]}) -- DROPPED",
                            title))
                    continue
                starts.append((pi, so, title))
        if not starts and held is not None:
            held.append((f"{path.name}: no chapter heading found", ""))
        for idx, (pi, so, _title) in enumerate(starts):
            end = starts[idx + 1][0] if idx + 1 < len(starts) else len(pages)
            out.append((so, "\n".join(pages[pi:end]), path.name, pi + 1))
    return out


_SOL_TEXTS: dict[int, str] | None = None


def sol_chapter_texts() -> dict[int, str]:
    global _SOL_TEXTS
    if _SOL_TEXTS is None:
        _SOL_TEXTS = {so: body for so, body, _f, _p in _sol_spans()}
    return _SOL_TEXTS


def parse_sol() -> tuple[list[dict], list[tuple[str, str]]]:
    items: list[dict] = []
    held: list[tuple[str, str]] = []
    for so, body, fname, page in _sol_spans(held):
        items.extend(_sol_chapter(body, so, page, fname, held))
    return items, held


def _sol_chapter(body: str, so: int, first_page: int, fname: str,
                 held: list[tuple[str, str]]) -> list[dict]:
    out: list[dict] = []
    marks = list(SOL_Q.finditer(body))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        chunk = body[m.end():end]
        number = m.group(1)
        heading = None
        pre = body[:m.start()]
        hs = list(SOL_SECTION.finditer(pre))
        if hs:
            heading = tidy(hs[-1].group(1))
        am = SOL_A.search(chunk)
        if not am:
            held.append((f"ch{so} q{number}: no Answer: marker", tidy(chunk)[:70]))
            continue
        stem_raw = strip_noise(chunk[:am.start()])
        ans_raw = strip_noise(chunk[am.end():])
        # THE ANSWER STOPS AT THE NEXT SECTION HEADING. The chunk runs to the
        # next "Question N.", and the book starts a new exercise -- "Let us
        # discuss (Page 23)" -- whose first item is numbered 1 again. Without
        # this cut the answer to "Who entered the house?" is stored as
        # "guest Let us discuss (Page 23.) Write whether True or False.",
        # which reads as an answer and verifies as one.
        nxt = SOL_SECTION.search(ans_raw)
        if nxt:
            ans_raw = ans_raw[:nxt.start()]
        # AN ANSWER NEVER CONTAINS THE WORD "Answer:". Where it does, the book
        # has printed sub-part (a)'s answer, then (b)'s question, then (b)'s
        # answer, all inside one numbered question, and the whole run has been
        # taken as one answer -- "Grandmother found the cures in her kitchen.
        # (b) Give one example of weather-related common illnesses. Answer:
        # Cough and cold. (c) What kind of relationship ...". That stores as an
        # answer, verifies as one, and is wrong from its second sentence on. Cut
        # at the sub-part label that opened the next question, so the item keeps
        # the part its stem actually asked and loses the rest.
        emb = re.search(r"(?i)\bAnswers?\s*:", ans_raw)
        if emb:
            head = ans_raw[:emb.start()]
            labs = list(re.finditer(r"\((?:[a-e]|i{1,3}|iv|vi{0,3}|ix|x)\)", head))
            ans_raw = head[:labs[-1].start()] if labs else head
        # A second Answer: inside the chunk belongs to the next sub-part of the
        # same question; keep the whole tail, it is still this question's answer.
        parts = _split_subparts(stem_raw, ans_raw)
        candidates = parts or [(stem_raw, ans_raw)]
        for n, (s, a) in enumerate(candidates, 1):
            stem, ans = tidy(s), tidy(a)
            label = f"{number}" if len(candidates) == 1 else f"{number}{chr(96+n)}"
            if SOL_UNUSABLE.search(stem) or SOL_UNUSABLE.search(ans):
                held.append((f"ch{so} q{label}: table, picture or classroom activity",
                             stem[:70]))
                continue
            if len(SOL_COMPOUND.findall(stem)) >= 2 or \
                    len(SOL_INLINE_OPTS.findall(stem)) >= 3:
                held.append((f"ch{so} q{label}: several questions under one number",
                             stem[:70]))
                continue
            if "?" not in stem and not SOL_ASKS.match(stem):
                held.append((f"ch{so} q{label}: the stem neither asks nor "
                             f"instructs -- a grammar or vocabulary exercise",
                             stem[:70]))
                continue
            if SOL_GAP.search(stem) or SOL_WORDPAIR.match(ans):
                held.append((f"ch{so} q{label}: a gap-fill or word-pair "
                             f"exercise, not a question", stem[:70]))
                continue
            if not ans or SOL_NONANSWER.match(ans):
                held.append((f"ch{so} q{label}: no usable answer", stem[:70]))
                continue
            if len(stem) < 25 or len(ans) < 12:
                held.append((f"ch{so} q{label}: stem or answer too short", stem[:70]))
                continue
            if len(stem) > 1200:
                held.append((f"ch{so} q{label}: stem over 1200 chars", stem[:70]))
                continue
            out.append({
                "chapter_number": so,
                "source": "sol",
                "source_file": fname,
                "page": first_page,
                "number": label,
                "section_heading": heading,
                "form": "long" if len(ans) > 320 else "short",
                "stem": stem,
                "options": [],
                "correct_option": None,
                "answer": ans,
            })
    return out


# ============================================================ family: mcq
# studentbro MCQ sets. No chapter heading: one paper per chapter, in order.

MCQ_FILES = [
    ("mcqbig", 1, SB / "c6_english_mcqbig_u1.pdf"),
    ("mcqbig", 2, SB / "c6_english_mcqbig_u2.pdf"),
    ("mcq", 2, SB / "c6_english_mcq_u2.pdf"),
    ("mcq", 3, SB / "c6_english_mcq_u3.pdf"),
    ("mcq", 4, SB / "c6_english_mcq_u4.pdf"),
    ("mcq", 5, SB / "c6_english_mcq_u5.pdf"),
]

M_MARKS = re.compile(r"Total Marks\s*:\s*(\d+)")
M_END = re.compile(r"-{3,}\s*-{3,}")
M_ANS = re.compile(r"^Ans\s*\.?\s*:\s*(?:\(([A-Da-d])\)\s*)?(.*)$", re.S)
M_OPT = re.compile(r"\(([A-D])\)\s*")
M_NUM = re.compile(r"^(\d{1,3})\s*\.$")

# Only the sections whose items are one question with one answer. The cloze
# ("fill in the blanks in the text given below") is a single passage with eight
# blanks and one combined key; the case-based and poem-extract sections print a
# passage once and hang sub-questions off it. Parsed item by item all three
# give a stem that is a fragment of a passage, so they are skipped and counted.
M_SECTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)select the most appropriate options"), "mcq"),
    (re.compile(r"(?i)say whether the following sentences are true or false"), "true_false"),
    (re.compile(r"(?i)answer the following questions in one sentence"), "very_short"),
    (re.compile(r"(?i)very short answer questions"), "very_short"),
    (re.compile(r"(?i)answer the following questions in short"), "short"),
    (re.compile(r"(?i)answer the following questions in brief"), "long"),
]
M_SKIP = re.compile(r"(?i)fill in the blanks in the text|case based|"
                    r"read the following poem|read the following passage|"
                    r"match the following")

# The page furniture. It has to be dropped BEFORE a block can become a stem:
# a footer sits between the last option of one question and the number block of
# the next, so a wrapped stem that is looked for behind that number finds
# "Page 1 https://studentbro.in/" instead and loads it as a question.
M_FURNITURE = re.compile(r"(?i)^(?:page\s+\d+|https?://\S+|std\s+6\s+english"
                         r"|total marks\s*:\s*\d+|\W*)$")


def _furniture(text: str) -> bool:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return bool(lines) and all(M_FURNITURE.match(ln) for ln in lines)


# ------------------------------------------------- content anchors (derived)
#
# A chapter that was worked out POSITIONALLY has to be checked against the
# chapter's own words, and the words cannot be hand-written: a guess at what a
# text contains is wrong more often than it looks. "Change of Heart" has no
# thief and no heart in it -- it is Prabhat, Surya and a badminton match -- and
# "The Winner" never says win, race or sport, because it is a poem about
# children running. Hand anchors for both would have rejected the right chapter
# and, worse, could have accepted a wrong one.
#
# So the vocabulary is derived from the `sol` family, which is the only family
# that NAMES its chapter ("Unit 4: Chapter 10 Change the Heart") and whose
# heading is cross-checked title-against-number before it is believed. A word
# counts as distinctive when it appears in at most three of the sixteen
# chapters. An MCQ paper then has to score highest on the chapter it was given,
# among the chapters its own unit holds -- which is exactly the set a dropped or
# added paper could shift it within.

_WORD = re.compile(r"[a-z][a-z'\-]{3,}")
_STOP = frozenset("""
about above after again against also always answer answers because been before
being below between both cannot could does doing done down during each either
following from give given gives have having here himself herself into itself
just like made make many more most much must never next none other over
question questions same should since some such text than that their them then
there these they this those through under until very were what when where
which while whose with would your yours yourself sentence sentences complete
poem story line lines word words write writing read reading following true
false select option options appropriate most describe describes mean means
author poet chapter class english total marks page studentbro vedantu
important activities discuss think reflect
""".split())


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(ascii_fold(text).lower()) if w not in _STOP}


def build_vocab() -> dict[int, set[str]]:
    """Distinctive words per chapter, taken from the family that names its own."""
    per = {so: _tokens(t) for so, t in sol_chapter_texts().items()}
    seen: dict[str, int] = {}
    for words in per.values():
        for w in words:
            seen[w] = seen.get(w, 0) + 1
    return {so: {w for w in words if seen[w] <= 3} for so, words in per.items()}


def rank_chapters(text: str, vocab: dict[int, set[str]],
                  among: list[int]) -> list[tuple[int, int]]:
    words = _tokens(text)
    scored = [(so, len(words & vocab.get(so, set()))) for so in among]
    return sorted(scored, key=lambda kv: -kv[1])


def _mcq_stream(path: Path) -> list[dict]:
    """Every block of the document in true reading order: (page, y) ascending.

    Block INDEX order is wrong here. The answers are a layer drawn before the
    questions, so get_text() returns all of a page's answers first; pairing on
    that order attaches each answer to a question several places away.
    """
    doc = fitz.open(path)
    stream: list[dict] = []
    for pi in range(doc.page_count):
        for b in doc[pi].get_text("blocks"):
            x0, y0, x1, y1, txt, _bno, btype = b
            if btype != 0:
                continue
            t = (txt or "").strip()
            if not t:
                continue
            stream.append({"page": pi + 1, "y": y0, "x": x0, "text": t})
        stream.sort(key=lambda r: (r["page"], round(r["y"], 1), r["x"]))
    stream.sort(key=lambda r: (r["page"], round(r["y"], 1), r["x"]))
    doc.close()
    return stream


def parse_mcq() -> tuple[list[dict], list[tuple[str, str]]]:
    items: list[dict] = []
    held: list[tuple[str, str]] = []
    for family, unit, path in MCQ_FILES:
        if not path.exists():
            held.append(("source missing", path.name))
            continue
        stream = _mcq_stream(path)
        papers: list[list[dict]] = []
        cur: list[dict] | None = None
        for rec in stream:
            if M_MARKS.search(rec["text"]) and "STD" in rec["text"].upper():
                cur = []
                papers.append(cur)
                continue
            if M_END.search(rec["text"]) and len(rec["text"]) < 40:
                cur = None
                continue
            if cur is not None:
                cur.append(rec)
        members = UNIT_MEMBERS[unit]
        if len(papers) != len(members):
            held.append((f"{path.name}: {len(papers)} papers but unit {unit} has "
                         f"{len(members)} chapters -- NOT LOADED", ""))
            continue
        vocab = build_vocab()
        for n, (so, paper) in enumerate(zip(members, papers), 1):
            body = "\n".join(r["text"] for r in paper)
            ranked = rank_chapters(body, vocab, members)
            mine = dict(ranked)[so]
            # A TIE IS NOT A CONTRADICTION. The last paper of the Unit 5 file is
            # two questions long ("the poet is celebrating soldiers") and every
            # chapter in the unit scores 1 on it, because chapter 16's own span
            # in the reference family is a single page. Rejecting on "not the
            # argmax" throws that paper away over a coin toss. The check exists
            # to catch a paper that reads as a DIFFERENT chapter, so it fires
            # only when another chapter scores strictly higher.
            better = [(o, s) for o, s in ranked if s > mine]
            if better:
                held.append((
                    f"{path.name}: paper {n} was given chapter {so} "
                    f"({BY_SORT[so][2]}) by position, but it reads as chapter "
                    f"{better[0][0]} ({BY_SORT[better[0][0]][2]}); scores "
                    f"{ranked} -- NOT LOADED", tidy(body)[:90]))
                continue
            if mine == 0 or len([1 for _o, s in ranked if s == mine]) > 1:
                held.append((
                    f"{path.name}: paper {n} -> chapter {so} ({BY_SORT[so][2]}) "
                    f"is position only, the text does not confirm it; scores "
                    f"{ranked} -- LOADED, worth an eye", tidy(body)[:90]))
            items.extend(_mcq_paper(paper, so, family, path.name, held))
    return items, held


def _mcq_paper(recs: list[dict], so: int, family: str, fname: str,
               held: list[tuple[str, str]]) -> list[dict]:
    """One paper -> its questions. Answers attach by position, keys by value.

    A QUESTION IS NOT ALWAYS ONE BLOCK. A stem that fits on one line shares its
    block with its number ("Who was the mahout?" then "5."); a stem that wraps
    puts the number in a block of its own, indented further left (x=43 against
    the stem's x=61). Reading only same-block numbers drops every wrapped
    question AND hands its options to the question above, which then has eight
    options and looks like a parse failure rather than a missing question.

    A SKIPPED SECTION STILL HAS TO CONSUME ITS ANSWERS. The cloze and the
    case-based sections are not loadable item by item, but they print "Ans. :"
    blocks like every other section. Dropping their questions while leaving
    their answers in the stream attaches each one to the last question of the
    PREVIOUS section, silently re-keying it. So skipped questions are kept as
    placeholders, absorb their answers, and are dropped at the end.
    """
    form = None
    heading = None
    questions: list[dict] = []
    skipping = False
    loose: list[str] = []
    for rec in recs:
        t = rec["text"]
        if _furniture(t):
            continue
        if t.startswith("*"):
            loose = []
            head = tidy(t.lstrip("* ").split("[")[0])
            heading = head
            if M_SKIP.search(head):
                skipping, form = True, None
                continue
            form = None
            for pat, f in M_SECTIONS:
                if pat.search(head):
                    form = f
                    break
            skipping = form is None
            if skipping:
                held.append((f"ch{so} {fname}: unrecognised section, skipped", head))
            continue
        am = M_ANS.match(t)
        if am:
            # Attach to the last question opened, which this block sits under.
            if questions and questions[-1].get("_ans") is None:
                questions[-1]["_ans"] = (am.group(1), tidy(am.group(2)))
            continue
        lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
        if not lines:
            continue
        num = M_NUM.match(lines[-1])
        if num:
            stem = tidy(" ".join(lines[:-1])) or tidy(" ".join(loose))
            loose = []
            questions.append({"number": num.group(1), "form": form,
                              "heading": heading, "stem": stem,
                              "page": rec["page"], "opts": [], "_ans": None,
                              "skip": skipping or form is None})
            continue
        if t.startswith("(") and M_OPT.match(t):
            if questions:
                hits = list(M_OPT.finditer(t))
                for i, m in enumerate(hits):
                    stop = hits[i + 1].start() if i + 1 < len(hits) else len(t)
                    questions[-1]["opts"].append(
                        {"label": m.group(1), "text": tidy(t[m.end():stop])})
            continue
        loose.append(t)
    out: list[dict] = []
    for q in questions:
        ans = q.pop("_ans")
        opts = q["opts"]
        if q["skip"]:
            continue
        if ans is None:
            held.append((f"ch{so} {fname} q{q['number']}: no Ans. block", q["stem"][:70]))
            continue
        letter, value = ans
        if re.fullmatch(r"(?i)self\.?", value or ""):
            held.append((f"ch{so} {fname} q{q['number']}: 'Ans. : self', an "
                         f"open-ender with no key", q["stem"][:70]))
            continue
        if not value:
            held.append((f"ch{so} {fname} q{q['number']}: empty answer", q["stem"][:70]))
            continue
        correct = None
        if q["form"] == "mcq":
            if len(opts) != 4:
                held.append((f"ch{so} {fname} q{q['number']}: {len(opts)} options, "
                             f"not 4", q["stem"][:70]))
                continue
            texts = [_key(o["text"]) for o in opts]
            if len(set(texts)) != len(texts):
                # A real defect in the source, not a parse failure: the book
                # prints the same distractor twice -- "(A) a croak / (B) a
                # croak", "(B) an easy to use application / (D) an easy to use
                # application". Where the duplicate IS the key the item has two
                # right answers; where it is not, the item is still misprinted
                # and cannot be reproduced, so both are held.
                held.append((f"ch{so} {fname} q{q['number']}: the source prints "
                             f"the same option twice", q["stem"][:70]))
                continue
            correct, defect = key_on_value(opts, (letter or "").upper(), value)
            if defect:
                held.append((f"ch{so} {fname} q{q['number']}: {defect}", q["stem"][:70]))
                if correct is None:
                    continue
        elif opts:
            held.append((f"ch{so} {fname} q{q['number']}: {q['form']} with options",
                         q["stem"][:70]))
            continue
        if q["form"] == "true_false" and not re.fullmatch(r"(?i)true|false", value):
            held.append((f"ch{so} {fname} q{q['number']}: true/false answer is "
                         f"{value!r}", q["stem"][:70]))
            continue
        if len(q["stem"]) < 18:
            held.append((f"ch{so} {fname} q{q['number']}: stem under 18 chars",
                         q["stem"][:70]))
            continue
        out.append({
            "chapter_number": so,
            "source": family,
            "source_file": fname,
            "page": q["page"],
            "number": f"{family}-{q['number']}",
            "section_heading": q["heading"],
            "form": q["form"],
            "stem": q["stem"],
            "options": opts,
            "correct_option": correct,
            "answer": value,
        })
    return out


# ============================================================= family: iq
# vedantu "Important Questions", one file per unit, chapter printed per chapter.

IQ_FILES = {u: VD / f"iq_ch{u:02d}.pdf" for u in (1, 2, 3, 4, 5)}

IQ_HEAD = re.compile(r"(?im)^\s*Important Questions for\s+(.{3,80}?)\s*:?\s*$")
IQ_ANS = re.compile(r"(?im)^\s*Ans\s*[:.]\s*")


def parse_iq() -> tuple[list[dict], list[tuple[str, str]]]:
    items: list[dict] = []
    held: list[tuple[str, str]] = []
    for unit, path in IQ_FILES.items():
        if not path.exists():
            held.append(("source missing", path.name))
            continue
        doc = fitz.open(path)
        pages = [doc[i].get_text() for i in range(doc.page_count)]
        doc.close()
        full = "\n".join(pages)
        page_at = []
        pos = 0
        for pi, t in enumerate(pages, 1):
            page_at.append((pos, pi))
            pos += len(t) + 1

        def page_of(offset: int) -> int:
            n = 1
            for start, pi in page_at:
                if start <= offset:
                    n = pi
            return n

        heads = []
        for m in IQ_HEAD.finditer(full):
            title = tidy(m.group(1))
            so = TITLES.get(_key(title))
            if so is None:
                continue          # "Important Questions for Class VI English"
            if so not in UNIT_MEMBERS[unit]:
                held.append((f"{path.name}: chapter {so} is not in unit {unit}", title))
                continue
            heads.append((m.end(), so, title))
        if len(heads) != len(UNIT_MEMBERS[unit]):
            held.append((f"{path.name}: {len(heads)} chapter headings but unit "
                         f"{unit} has {len(UNIT_MEMBERS[unit])} chapters", ""))
        if not heads:
            continue
        vocab = build_vocab()
        for idx, (start, so, title) in enumerate(heads):
            end = heads[idx + 1][0] if idx + 1 < len(heads) else len(full)
            body = full[start:end]
            ranked = rank_chapters(body, vocab, UNIT_MEMBERS[unit])
            if ranked[0][0] != so:
                # The heading names the chapter, so this is not an attribution
                # guess -- it is a disagreement between vedantu's title and
                # studentbro's text for the same chapter, and worth seeing.
                held.append((f"{path.name}: heading says chapter {so} "
                             f"({BY_SORT[so][2]}) but the text reads as chapter "
                             f"{ranked[0][0]}; scores {ranked}", title))
            items.extend(_iq_chapter(body, so, path.name, page_of(start), held))
    return items, held


def _iq_chapter(body: str, so: int, fname: str, page: int,
                held: list[tuple[str, str]]) -> list[dict]:
    """Numbered question, "Ans:" answer. The numbering is used as a gate.

    A wrapped answer line can begin with a digit and a period -- "2021. was
    the year" -- and a bare ^\\d+\\. would cut the answer in half and leave the
    tail as a question. Only a number that continues the run is accepted, so a
    stray one inside an answer stays inside it.
    """
    out: list[dict] = []
    marks = [(m.start(), m.end(), int(m.group(1)))
             for m in re.finditer(r"(?m)^\s*(\d{1,3})\s*[\.\)]\s*", body)]
    keep: list[tuple[int, int, int]] = []
    expect = 1
    for s, e, n in marks:
        if n == expect:
            keep.append((s, e, n))
            expect += 1
    for i, (s, e, n) in enumerate(keep):
        end = keep[i + 1][0] if i + 1 < len(keep) else len(body)
        chunk = body[e:end]
        am = IQ_ANS.search(chunk)
        if not am:
            held.append((f"ch{so} iq{n}: no Ans: marker", tidy(chunk)[:70]))
            continue
        stem = tidy(strip_noise(chunk[:am.start()]))
        ans = tidy(strip_noise(chunk[am.end():]))
        if len(stem) < 20 or len(ans) < 15:
            held.append((f"ch{so} iq{n}: stem or answer too short", stem[:70]))
            continue
        if SOL_NONANSWER.match(ans):
            held.append((f"ch{so} iq{n}: no usable answer", stem[:70]))
            continue
        if "?" not in stem and not SOL_ASKS.match(stem):
            held.append((f"ch{so} iq{n}: the stem neither asks nor instructs",
                         stem[:70]))
            continue
        out.append({
            "chapter_number": so,
            "source": "iq",
            "source_file": fname,
            "page": page,
            "number": f"iq-{n}",
            "section_heading": "Important Questions",
            "form": "long" if len(ans) > 320 else "short",
            "stem": stem,
            "options": [],
            "correct_option": None,
            "answer": ans,
        })
    return out


# ==================================================================== driver

FAMILIES = {"sol": ("studentbro", parse_sol), "mcq": ("studentbro", parse_mcq),
            "iq": ("vedantu", parse_iq)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--family", choices=sorted(FAMILIES), action="append")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--show-held", type=int, default=3)
    a = ap.parse_args()

    names = a.family or sorted(FAMILIES)
    for name in names:
        publisher, fn = FAMILIES[name]
        items, held = fn()
        forms = ("mcq", "true_false", "very_short", "short", "long")
        print(f"\n=== family {name}  publisher={publisher}  "
              f"items={len(items)}  held={len(held)}")
        print(f"  {'ch':>3} {'cid':>7} {'chapter':<46} "
              + " ".join(f"{f:>10}" for f in forms) + f" {'total':>6}")
        print("  " + "-" * 122)
        for so, cid, nm, _u in CHAPTERS:
            mine = [i for i in items if i["chapter_number"] == so]
            print(f"  {so:>3} {cid:>7} {nm[:46]:<46} "
                  + " ".join(f"{sum(1 for i in mine if i['form']==f):>10}" for f in forms)
                  + f" {len(mine):>6}")
        print("  " + "-" * 122)
        print(f"  {'':>3} {'':>7} {'TOTAL':<46} "
              + " ".join(f"{sum(1 for i in items if i['form']==f):>10}" for f in forms)
              + f" {len(items):>6}")
        if held:
            print(f"\n  held / skipped ({len(held)}):")
            seen: dict[str, list[str]] = {}
            for why, what in held:
                bucket = re.sub(r"\b(?:ch|q|iq|p)\d+[a-z]?\b", "#", why)
                bucket = re.sub(r"c6_english_\w+\.pdf", "<file>", bucket)
                seen.setdefault(bucket, []).append(what)
            for bucket, examples in sorted(seen.items(), key=lambda kv: -len(kv[1])):
                print(f"    {len(examples):>4}  {bucket}")
                for ex in examples[:a.show_held]:
                    if ex:
                        print(f"          {ex[:90]}")
        if a.write:
            DRAFTS.mkdir(parents=True, exist_ok=True)
            out = DRAFTS / f"c6_english_{name}.json"
            out.write_text(json.dumps(
                {"publisher": publisher, "family": name, "items": items},
                indent=1, ensure_ascii=False), encoding="utf-8")
            print(f"\n  wrote {out}")
    if _DROPPED:
        print(f"\nnon-ASCII characters folded away entirely: "
              f"{sorted(hex(ord(c)) for c in _DROPPED)}")
    if not a.write:
        print("\nreport only -- re-run with --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
