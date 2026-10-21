"""Draft items from the KVS ZIET Mumbai Class 9 Mathematics bank.

    python -m scripts.parse_ziet_maths
    python -m scripts.parse_ziet_maths --out scripts/ziet_items/drafts

Source: a four-day TGT (Mathematics) capacity-building programme held at KVS
ZIET Mumbai, 17-20 August 2026. The question bank is embedded in the programme
report, which is why it does not look like one from the outside -- the first
seven pages are a commissioner's foreword and a participant list.

A THIRD ANSWER LAYOUT, and the reason this needs its own parser. The two banks
already ingested each bind an answer to its question locally:

  * pdf.tube prints `Ans :` inside the question block.
  * the KVS English manual prints an `Answer Key` after each extract.

This one is a SPLIT DOCUMENT. Every question for all eight chapters comes
first, then every solution for all eight chapters. Nothing but the chapter
banner and the question number connects the two halves, so the join is on
(chapter, number) and an answer that fails to pair is reported rather than
guessed at.

THE SOLUTION HALF IS NOT WRITTEN THE SAME WAY TWICE. Across eight chapters:

    ch 1   Solution Q1: Correct Option: B) Rectangle; Quadrant III
    ch 2   1.<newline>(a) The student is correct.
    ch 3   Q1.<newline>C. Riya is incorrect because ...
    ch 4   13 Correct answer: (B). For p=2,q=1 ...
    ch 6   1<newline>C. 150m
    ch 8   1<newline>B) 33. The AP has a=12, d=3.

The single invariant is a leading question number, so `_SOL_START` matches the
number and treats every prefix around it -- `Solution`, `Q`, the full stop, the
colon -- as optional decoration.

FORM COMES FROM THE PRINTED SECTION BANNER, never from counting options. The
banners are "MULTIPLE CHOICE QUESTIONS", "Assertion-Reason Based MCQs",
"N MARK QUESTIONS" and "CASE STUDY BASED QUESTIONS", and they map onto the
closed set in `FORM_TO_SECTION`. An item under an MCQ banner whose options did
not parse to exactly four is demoted to `very_short` rather than shipped as an
`mcq`, because `V-09` fails an mcq that has any other number and the row would
load with `status = 0`.

Assertion-reason items carry no options of their own -- the four choices are
printed once in a `Directions:` block for the whole section. Those four are
captured and attached to each AR item, so the stored item is what the page
actually offers a student.

`concept` is left empty. `apply_read_concepts` RAISES on a name outside the
chapter's list and aborts the chapter, so a guess is more expensive than a
blank; concepts are assigned by reading, after loading.
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
          / "kvs_ziet_mumbai" / "c9_maths_ziet_tgt_2026.pdf")
SOURCE_URL = "https://drive.google.com/file/d/1Way6BgPcJv9aOItxq3B67EaUz58zPkk2/view"

# The banner that separates the two halves of the document.
_SOLUTIONS_BANNER = re.compile(r"(?m)^\s*SOLUTIONS\s*$")
_CHAPTER = re.compile(r"(?im)^\s*CHAPTER\s*[-: ]{0,3}\s*(\d)\s*[:\-]?\s*(.*)$")

# A question starts at a number alone on its line, or a number leading a line.
_Q_START = re.compile(r"(?m)^[ \t]*(\d{1,3})[ \t]*$|^[ \t]*(\d{1,3})[ \t]+(?=[A-Z(ऀ-ॿ])")
# A solution starts at a number wearing whatever prefix its chapter chose. This
# is deliberately loose -- it also matches a line of working that happens to
# begin with a figure -- and `_monotonic` below throws those away.
_SOL_START = re.compile(r"(?m)^[ \t]*(?:Solution\s*)?Q?\.?\s*(\d{1,3})\s*[\.\):]?[ \t]*$"
                        r"|^[ \t]*(?:Solution\s*)?Q\.?\s*(\d{1,3})\s*[\.\):]\s*(?=\S)"
                        r"|^[ \t]*(\d{1,3})[ \t]+(?=\S)")

_SECTION_BANNERS = [
    (re.compile(r"(?i)MULTIPLE\s+CHOICE\s+QUESTIONS"), "mcq"),
    (re.compile(r"(?i)Assertion\s*[-–—]?\s*Reason"), "assertion_reason"),
    (re.compile(r"(?i)\b2\s*MARKS?\s+QUESTIONS?"), "very_short"),
    (re.compile(r"(?i)\b3\s*MARKS?\s+QUESTIONS?"), "short"),
    (re.compile(r"(?i)\b5\s*MARKS?\s+QUESTIONS?"), "long"),
    (re.compile(r"(?i)CASE\s+STUD(?:Y|IES)\s+BASED\s+QUESTIONS?"), "case_study"),
]

# "A) text" at a line start, or a second option pushed along the same line by
# the table layout: "A) Parallelogram; Quadrant II        B) Rectangle; ..."
# Style varies BY CHAPTER, and all four of these appear in this one document:
#   ch 1 "A) t"   ch 2 "(a) t"   ch 3 "A. t"   ch 4 "(A) t (B) t (C) t (D) t"
# So the label may be parenthesised or not, upper or lower case, and closed by
# either ")" or "."; it is normalised to an upper-case letter on the way in.
_OPT_LINE = re.compile(r"(?m)^[ \t]*\(?([A-Da-d])[\).][ \t]*(.+?)[ \t]*$")
_OPT_SPLIT = re.compile(r"[ \t]{2,}(?=\(?[A-Da-d][\).])")
_OPT_ANY = re.compile(r"(?<![A-Za-z0-9])\(?([A-Da-d])[\).]\s*"
                      r"([^()]{1,200}?)(?=\s*\(?[A-Da-d][\).]|\s*$)")
_OPT_HEAD = re.compile(r"[ \t]*\(?[A-Da-d][\).]")
_OPT_POS = re.compile(r"(?<![A-Za-z0-9])\(?([A-Da-d])[\).](?=\s)")
_CORRECT = re.compile(r"(?i)^\s*(?:Correct\s+(?:Option|Answer)\s*:?\s*)?\(?([A-Da-d])[\)\.]")
# Everything a solution prints before its answer proper.
_LEAD = re.compile(r"(?i)^\s*(?:correct\s+(?:option|answer)\s*:?\s*)?\(?[A-Da-d][\).]\s*")
# Chapters 1 and 2 print "Assertion (A): ... Reason (R): ...", chapter 3 drops
# the markers and prints "Assertion: ... Reason: ...". With (A) and (R)
# mandatory the split silently returned nothing there, so both of chapter 3's
# assertion-reason items loaded with `status = 0` on V-10.
_AR_SPLIT = re.compile(r"(?is)Assertion\s*(?:\(A\))?\s*:\s*(.*?)\s*"
                       r"Reason\s*(?:\(R\))?\s*:\s*(.*)")
_DIRECTIONS = re.compile(r"(?is)Directions?\s*:(.*?)(?=^\s*\d{1,3}\s*$)", re.MULTILINE)


def _deitalic(t: str) -> str:
    """Fold Mathematical Alphanumeric Symbols back onto ASCII.

    Chapter 4 sets its algebra in a maths font and the text layer keeps it:
    that chapter prints its first option label "(A)" as U+1D434 MATHEMATICAL
    ITALIC CAPITAL A. It reads as an A on the page and is not one, so the
    label never matched and those questions lost every option. Only the
    U+1D400-U+1D7FF block is folded; nothing else is normalised.
    """
    if not any(0x1D400 <= ord(c) <= 0x1D7FF for c in t):
        return t
    return "".join(ud.normalize("NFKC", c)
                   if 0x1D400 <= ord(c) <= 0x1D7FF else c for c in t)


def _norm(t: str) -> str:
    """Fold to letters and digits, so "8 cm" and "8" compare equal."""
    return re.sub(r"[^a-z0-9]", "", ud.normalize("NFKC", t or "").lower())


def _pages(doc) -> list[str]:
    out = []
    for i in range(doc.page_count):
        try:
            out.append(_deitalic(doc[i].get_text()))
        except Exception:
            out.append("")
    return out


def _split_halves(pages: list[str]) -> tuple[str, str]:
    for i, t in enumerate(pages):
        if _SOLUTIONS_BANNER.search(t):
            return "\n".join(pages[:i]), "\n".join(pages[i:])
    raise SystemExit("No SOLUTIONS banner found -- layout has changed")


def _by_chapter(blob: str) -> dict[int, str]:
    hits = list(_CHAPTER.finditer(blob))
    out: dict[int, str] = {}
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(blob)
        out[int(m.group(1))] = blob[m.end():end]
    return out


def _options(block: str) -> list[dict]:
    """The four printed choices, however the chapter laid them out.

    Only ever called for a form the section banner says is multiple choice.
    That matters: a 3-mark question's sub-parts are also written "(a) ... (b)
    ...", and reading those as options would invent an mcq out of a long
    answer.
    """
    opts: dict[str, str] = {}

    def keep(label: str, txt: str) -> None:
        label, txt = label.upper(), " ".join(txt.split())
        if txt and label not in opts:
            opts[label] = txt[:240]

    for raw in block.splitlines():
        if not _OPT_HEAD.match(raw):
            continue
        for piece in _OPT_SPLIT.split(raw):
            m = (_OPT_LINE.match(piece)
                 or re.match(r"[ \t]*\(?([A-Da-d])[\).][ \t]*(.+)", piece))
            if m:
                keep(m.group(1), m.group(2))

    # "A) (-6.5, 0) and distance is 6.5 units B) (0, -6.5) and distance is ..."
    # -- two options on one line parted by a SINGLE space, and both texts carry
    # brackets of their own, so neither the two-space split above nor the
    # bracket-free pattern below finds them. Cut the line at its labels
    # instead, and only where they read A, B, C, D in that order.
    if len(opts) != 4:
        flat = " ".join(block.split())
        run, want = [], "ABCD"
        for m in _OPT_POS.finditer(flat):
            if m.group(1).upper() == want[len(run)]:
                run.append(m)
                if len(run) == 4:
                    break
        if len(run) == 4:
            opts = {}
            for i, m in enumerate(run):
                end = run[i + 1].start() if i + 1 < len(run) else len(flat)
                keep(m.group(1), flat[m.end():end])

    # Chapter 4 prints all four on one wrapped line: "(A) 20 (B) 40 (C) 80 ..."
    if len(opts) != 4:
        flat = " ".join(block.split())
        found = _OPT_ANY.findall(flat)
        if len({lab.upper() for lab, _ in found}) == 4:
            opts = {}
            for lab, txt in found:
                keep(lab, txt)
    return [{"label": k, "text": opts[k]} for k in sorted(opts)]


def _monotonic(hits: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    """Keep the rising run of question numbers, discard working that looks like one.

    The solution half is prose, and prose contains figures at line starts --
    "23 Probabilities: ..." is a solution, "2500−100+1=2401" is not. A real
    solution number is larger than the one before it, so a greedy rising scan
    keeps the sequence and drops the arithmetic.
    """
    out: list[tuple[int, int, int]] = []
    last = 0
    for s, e, n in hits:
        if n == last + 1 or (last < n <= last + 3 and out):
            out.append((s, e, n))
            last = n
        elif not out and n == 1:
            out.append((s, e, n))
            last = 1
    return out


def _directions(chapter_text: str) -> list[dict]:
    """The four shared choices printed once above the assertion-reason block."""
    m = _DIRECTIONS.search(chapter_text)
    if not m:
        return []
    opts = []
    for lab, txt in re.findall(r"\(([a-d])\)\s*([^()]+?)(?=\s*\([a-d]\)|\s*$)",
                               " ".join(m.group(1).split())):
        opts.append({"label": lab.upper(), "text": " ".join(txt.split())[:240]})
    return opts if len(opts) == 4 else []


def _numbered(block: str, pattern: re.Pattern, rising: bool = False,
              valid: set[int] | None = None) -> dict[int, str]:
    """Cut a half into numbered blocks.

    `valid` is the set of numbers the other half actually printed, and it is
    the guard against a SILENT TRUNCATION. Chapter 6's solution 34 answers a
    "same perimeter, different area" question with a table of dimensions, and
    a figure in that table reads as a solution number: the tail of the working
    was filed as "solution 36", and solution 34 was stored ending mid-table at
    "Possible dimensions: Length Breadth Area 18 m 2 m". Nothing failed and
    nothing was reported -- the answer simply stopped. A number that no
    question carries is not a new solution, so it is folded back into the one
    before it, digits and all.
    """
    hits = [(m.start(), m.end(), int(next(g for g in m.groups() if g)))
            for m in pattern.finditer(block)]
    hits = [h for h in hits if h[2] > 0]
    if rising:
        hits = _monotonic(hits)
    out: dict[int, str] = {}
    order: list[int] = []
    for i, (s, e, n) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(block)
        if valid is not None and n not in valid and order:
            out[order[-1]] += block[s:end]
            continue
        if n in out:            # a repeat is a page-header artefact, keep the first
            continue
        out[n] = block[e:end]
        order.append(n)
    return out


def build() -> dict:
    doc = fitz.open(SOURCE)
    pages = _pages(doc)
    doc.close()
    qhalf, shalf = _split_halves(pages)
    qchap, schap = _by_chapter(qhalf), _by_chapter(shalf)

    items, unpaired, demoted, overruled = [], [], 0, []
    for ch in sorted(qchap):
        body = qchap[ch]
        ar_opts = _directions(body)

        # Where each section banner starts, so a question inherits its form.
        marks: list[tuple[int, str]] = []
        for pat, form in _SECTION_BANNERS:
            for hit in pat.finditer(body):
                marks.append((hit.start(), form))
        marks.sort()

        # A number alone on a line is how a question starts -- and also how
        # this book prints a table column ("x 0 / 1 / 2 / 3") and the 22 of
        # 22/7. Those land mid-question and cut the block off before its
        # options. Question numbers rise 1..38; a table cell does not.
        qs = _numbered(body, _Q_START, rising=True)
        sols = _numbered(schap.get(ch, ""), _SOL_START, rising=True,
                         valid=set(qs))

        for num in sorted(qs):
            block = qs[num]
            pos = body.find(block)
            form = "mcq"
            for start, f in marks:
                if start <= pos:
                    form = f

            # THE LAST QUESTION OF A SECTION RUNS INTO THE NEXT BANNER. Its
            # block ends where the following number begins, and the banner --
            # with, for the assertion-reason section, its whole "Directions:"
            # list of four choices -- sits in between. Chapter 2 question 18
            # asks a parking charge and printed (a) Rs 50 ... (d) Rs 100, but
            # (c) and (d) were read off the Directions as "A is true, but R is
            # false". Four options either way, so nothing was demoted and
            # nothing was reported. Cut the block at the banner.
            cut = min((m.start() for pat, _ in _SECTION_BANNERS
                       for m in [pat.search(block)] if m), default=len(block))
            block = block[:cut]
            answer = " ".join(sols.get(num, "").split())
            if not answer:
                unpaired.append((ch, num))
                continue

            choice_form = form in ("mcq", "assertion_reason")
            opts = _options(block) if choice_form else []
            stem = "\n".join(ln for ln in block.splitlines()
                             if not (choice_form and _OPT_HEAD.match(ln)))
            stem = " ".join(stem.split())
            if choice_form and opts:
                for o in opts:      # options wrapped onto the stem line
                    for lab in (o["label"], o["label"].lower()):
                        for pat in (f"{lab}) ", f"({lab}) ", f"{lab}. "):
                            stem = stem.replace(pat + o["text"], " ")
                stem = " ".join(stem.split())
            assertion = reason = ""
            if form == "assertion_reason":
                m = _AR_SPLIT.search(stem)
                if m:
                    assertion, reason = " ".join(m.group(1).split()), " ".join(m.group(2).split())
                    stem = f"Assertion (A): {assertion}  Reason (R): {reason}"
                opts = opts or ar_opts

            correct = ""
            cm = _CORRECT.match(answer)
            if cm and opts:
                correct = cm.group(1).upper()
            if correct and correct not in {o["label"] for o in opts}:
                correct = ""

            # THE LETTER IN A SOLUTION IS NOT RELIABLE; THE VALUE IS.
            # Chapter 8 question 5 asks the 7th weekly saving of 100, 150,
            # 200... and prints "A) 350 B) 400 C) 450 D) 500". Its solution
            # reads "C) 400. a7 = 100 + 6(50) = 400" -- the arithmetic is
            # right and 400 is option B, not C. Question 17 does the same,
            # and question 4 argues itself from "C) 10th" to "B) 9th" inside
            # one sentence. Keying on the letter publishes a wrong answer
            # that no validator can see, so where the quoted value names
            # exactly one option, that option wins and the letter is
            # overruled.
            if correct and opts:
                quoted = _norm(_LEAD.sub("", answer)[:70])
                match = [o["label"] for o in opts
                         if (n := _norm(o["text"])) and quoted
                         and (n.startswith(quoted[:len(n)])
                              or quoted.startswith(n[:len(quoted)]))]
                if len(match) == 1 and match[0] != correct:
                    overruled.append((ch, num, correct, match[0]))
                    correct = match[0]

            # V-09: an mcq must carry exactly four options, or it is not an mcq.
            if form in ("mcq", "assertion_reason") and len(opts) != 4:
                form, opts, correct = "very_short", [], ""
                demoted += 1
            if len(stem) < 20:
                continue

            items.append({
                "number": num, "form": form, "chapter_number": ch,
                "stem": stem, "options": opts, "correct_option": correct,
                "answer": answer[:4000],
                **({"assertion": assertion, "reason": reason}
                   if form == "assertion_reason" and assertion else {}),
                "concept": "", "needs_reading": True,
            })

    return {"items": items, "unpaired": unpaired, "demoted": demoted,
            "overruled": overruled,
            "q_chapters": sorted(qchap), "s_chapters": sorted(schap)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent
                                         / "ziet_items" / "drafts"))
    a = ap.parse_args()

    if not SOURCE.exists():
        raise SystemExit(f"Source not mirrored: {SOURCE}")
    r = build()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "c9_maths_ziet.json").write_text(json.dumps(
        {"book": "c9_maths_ziet", "source": SOURCE.name, "source_url": SOURCE_URL,
         "source_tier": "C", "session": "2026-27",
         "publisher": "kvs_ziet_mumbai",
         "validation_status": "sourced_verbatim",
         "items": r["items"]}, indent=1, ensure_ascii=False), encoding="utf-8")

    items = r["items"]
    print("Class 9 Mathematics -- KVS ZIET Mumbai, TGT programme Aug 2026\n")
    print(f"  chapters in the question half   {r['q_chapters']}")
    print(f"  chapters in the solution half   {r['s_chapters']}")
    print(f"  items paired to a solution      {len(items)}")
    print(f"  questions with NO solution      {len(r['unpaired'])}  (dropped)")
    print(f"  demoted from mcq (option count) {r['demoted']}\n")

    per: dict[int, dict] = {}
    for it in items:
        d = per.setdefault(it["chapter_number"], {})
        d[it["form"]] = d.get(it["form"], 0) + 1
    forms = ["mcq", "assertion_reason", "very_short", "short", "long", "case_study"]
    print(f"  {'ch':>3} " + " ".join(f"{f[:9]:>9}" for f in forms) + f" {'total':>6}")
    print("  " + "-" * 72)
    for ch in sorted(per):
        row = per[ch]
        print(f"  {ch:>3} " + " ".join(f"{row.get(f, 0):>9}" for f in forms)
              + f" {sum(row.values()):>6}")
    print("  " + "-" * 72)
    print(f"  {'all':>3} " + " ".join(
        f"{sum(p.get(f, 0) for p in per.values()):>9}" for f in forms)
        + f" {len(items):>6}")

    if r["unpaired"]:
        miss: dict[int, list] = {}
        for ch, n in r["unpaired"]:
            miss.setdefault(ch, []).append(n)
        print("\n  unpaired (question printed, no solution found):")
        for ch in sorted(miss):
            print(f"      ch{ch}: {miss[ch][:14]}{' ...' if len(miss[ch]) > 14 else ''}")
    if r["overruled"]:
        print(f"\n  the solution's letter disagreed with the value it quotes, "
              f"and the value won ({len(r['overruled'])}):")
        for ch, num, was, now in r["overruled"]:
            print(f"      ch{ch} q{num:<3} book said {was}, the value is {now}")
    print(f"\ndrafts in {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
