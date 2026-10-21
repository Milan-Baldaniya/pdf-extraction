"""Draft items from the NODIA Class 9 English "QB 2026" bank (Kaveri).

    python -m scripts.parse_kaveri_english
    python -m scripts.parse_kaveri_english --section poetry

THE BOOK IN THE DATABASE IS NOT BEEHIVE. Class 9 English was replaced under
NEP 2020: the chapters held are Poorvi/Kaveri -- "How I Taught My Grandmother
to Read", "The Pot Maker", "Winds of Change" -- and not one of Beehive's
twenty texts ("The Fun They Had", "The Road Not Taken") exists anywhere in the
estate. A Beehive solution set cannot be loaded against these chapters, and
the same is true of Maths, where the book is now Ganita Prakash.

CHAPTER COMES FROM THE PRINTED CONTENTS, NOT FROM THE RUNNING HEADER. Every
page of a chapter carries its title in capitals, which looks like the obvious
key -- but the text layer only yields it on about 40% of pages (11 of 25 for
chapter 1), so half the book would be attributed to whichever chapter was seen
last. That is exactly the carry-forward that misfiled 36% of `parse_kvs_
english`. The contents page prints an exact folio range per chapter instead,
and the folio-to-page offset is measured at run time rather than assumed.

ONLY TWO EXERCISE TYPES ARE QUESTIONS. Each chapter runs eight to twelve
numbered exercises, and most of them cannot be a row in a question bank: word
webs, cause-and-effect tables, matching columns, and "identify five words with
prefixes" all print a numbered list whose answer is a table. Parsed, they give
a stem that is half a table and an answer that is the other half. Sections are
therefore classified by their heading and anything unrecognised is SKIPPED and
counted, so the loss is visible rather than silent.

No marks are printed anywhere in the book, so `form` comes from the exercise
heading and nothing is inferred from answer length.
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

SOURCE = (Path(__file__).resolve().parents[1] / "data" / "qbank" / "mirror"
          / "pdftube" / "c9_English_R1_QB_2026.pdf")
SOURCE_URL = "https://pdf.tube/School/CBSE/"
PUBLISHER = "nodia"          # the contents page signs off "NODIA"

# sort_order, chapter name, printed folio range -- from the book's own contents.
PROSE = [
    (1, "How I Taught My Grandmother to Read", 299, 323),
    (2, "The Pot Maker", 324, 345),
    (3, "Winds of Change", 346, 366),
    (4, "Vitamin-M", 367, 389),
    (5, "The World of Limitless Possibilities", 390, 414),
    (6, "Twin Melodies", 415, 439),
    (7, "Carrier of Words", 440, 462),
    (8, "Follow That Dream", 463, 484),
]
POETRY = [
    (1, "Bharat Our Land", 485, 503),
    (2, "Gifts of Grace: Honouring Our Vocations", 504, 523),
    (3, "Canvas of Soil", 524, 541),
    (4, "I Cannot Remember My Mother", 542, 558),
    (5, "Nine Gold Medals", 559, 578),
    (6, "A Friend Found in Music", 579, 595),
    (7, "Words", 596, 615),
    (8, "Believe in Yourself", 616, 635),
]

# Heading -> the form its questions take. Anything not listed is skipped.
KEEP = [
    (re.compile(r"(?i)answer the following question"), "short"),
    (re.compile(r"(?i)read the extracts? given below and answer"), "short"),
    (re.compile(r"(?i)read the (following )?extracts? and answer"), "short"),
    (re.compile(r"(?i)state whether the following sentences are true"), "true_false"),
    (re.compile(r"(?i)answer the following in about"), "long"),
]
_SECTION = re.compile(r"(?m)^\s*([IVX]{1,5})\.\s*(.{4,90})$")
_QSTART = re.compile(r"(?m)^\s*(\d{1,3})\.\s*(?=\S)")
_ANS = re.compile(r"(?m)^\s*Ans\s*:\s*")
# A table row: a bare roman numeral, or a line that is only a number.
_TABLEISH = re.compile(r"(?m)^\s*(?:[ivx]{1,5}\.?|\d{1,2}\.?)\s*$")


def _folio_offset(doc, first_name: str, first_folio: int) -> int:
    key = re.sub(r"[^A-Z]", "", first_name.upper())[:20]
    for cand in range(0, 80):
        p = first_folio + cand - 1
        if p >= doc.page_count:
            break
        try:
            raw = doc[p].get_text()
        except Exception:
            continue
        if key and key in re.sub(r"[^A-Z]", "", raw.upper()):
            return cand
    raise SystemExit("Could not measure the folio offset -- layout has changed")


def _blob(doc, lo: int, hi: int, off: int, title: str) -> str:
    head = re.sub(r"[^A-Z]", "", title.upper())
    out = []
    for p in range(lo + off - 1, min(hi + off, doc.page_count)):
        try:
            raw = doc[p].get_text()
        except Exception:
            continue
        for ln in raw.splitlines():
            # Drop the running header, which would otherwise land in a stem.
            if re.sub(r"[^A-Z]", "", ln.upper()) == head:
                continue
            out.append(ln)
    return "\n".join(out)


_OPT_ANY = re.compile(r"\(\s*([a-dA-D])\s*\)\s*([^()]{1,180}?)(?=\s*\(\s*[a-dA-D]\s*\)|\s*$)")


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def _choices(stem: str, answer: str) -> tuple[list[dict], str]:
    """The four printed choices and the one the answer names, or ([], "").

    The key is taken from the answer's VALUE, not its letter, and the letter
    is only a fallback. That is the rule the ZIET Maths bank taught: a
    solution there keyed Rs 400 as C where Rs 400 was option B, and V-02
    cannot see the difference because C exists.
    """
    found = _OPT_ANY.findall(stem)
    opts: dict[str, str] = {}
    for lab, txt in found:
        lab, txt = lab.upper(), " ".join(txt.split()).strip(" .,;")
        if txt and lab not in opts:
            opts[lab] = txt[:240]
    if sorted(opts) != ["A", "B", "C", "D"]:
        return [], ""
    out = [{"label": k, "text": opts[k]} for k in sorted(opts)]

    body = re.sub(r"(?i)^\s*\(?\s*[a-dA-D]\s*\)?[.\s]*", "", answer)
    n_body = _norm(body)
    hit = [k for k, v in opts.items() if _norm(v) and _norm(v) in n_body]
    if len(hit) == 1:
        return out, hit[0]
    m = re.match(r"(?i)^\s*\(?\s*([a-dA-D])\s*\)", answer)
    return out, (m.group(1).upper() if m else "")


def _heading_before(body: str, pos: int) -> str:
    """The nearest instruction line above a question, for the record only.

    It is NOT used to decide whether something is a question -- see the note
    in `build` about roman numerals doubling as option labels.
    """
    best = ""
    for m in _SECTION.finditer(body, 0, pos):
        best = " ".join(m.group(2).split())
    return best


def _not_a_question(stem: str, answer: str, raw_stem: str) -> str:
    """Why this pair cannot be a row in the bank, or "" if it can.

    Most of what a chapter numbers is not a question. Word webs, cause-and-
    effect tables and matching columns all print a numbered list whose answer
    is the other half of a table, and parsed they give a stem that is a
    fragment ("Her grey hair") and an answer that is a column. Each reason is
    counted so the loss shows up in the report rather than vanishing.
    """
    words = stem.split()
    if len(words) < 6:
        return "stem is a fragment, under 6 words"
    if len(answer.split()) < 8:
        return "answer is under 8 words"
    if len(_TABLEISH.findall(raw_stem)) >= 3:
        return "stem is a table or matching column"
    if not re.search(r"[?.]$", stem) and not re.search(
            r"(?i)\b(why|what|how|who|when|where|which|describe|explain|discuss|"
            r"give|state|justify|comment|elaborate|write|do you|according)\b", stem):
        return "stem reads as a fragment, not a question"
    return ""


def _form_for(heading: str) -> str | None:
    for pat, form in KEEP:
        if pat.search(heading):
            return form
    return None


def build(rows: list[tuple], label: str) -> dict:
    doc = fitz.open(SOURCE)
    off = _folio_offset(doc, rows[0][1], rows[0][2])
    items: list[dict] = []
    skipped: dict[str, int] = {}
    per: dict[int, int] = {}

    for so, name, lo, hi in rows:
        body = _blob(doc, lo, hi, off, name)

        # EVERY ANSWER IS PRECEDED BY ITS QUESTION, and that is the only thing
        # in this book that holds. Roman numerals do not: the exercise
        # headings are "I.", "II.", "III." and so are the OPTIONS of a
        # multiple-choice question, so keying on them cut chapter 1 into 40
        # sections, most of them an option line ("Her grey hair", "She spent
        # hours reading"). So pair instead: a stem runs from the numbered line
        # that opens it to its "Ans :", and the answer runs from there to the
        # numbered line that opens the next question.
        qpos = [m.start() for m in _QSTART.finditer(body)]
        apos = [m for m in _ANS.finditer(body)]
        for k, a in enumerate(apos):
            before = [q for q in qpos if q < a.start()]
            if not before:
                continue
            start = before[-1]
            nxt = [q for q in qpos if q > a.end()]
            nxt_ans = apos[k + 1].start() if k + 1 < len(apos) else len(body)
            stop = min([q for q in nxt if q <= nxt_ans] or [nxt_ans])
            stem = " ".join(re.sub(r"^\s*\d{1,3}\.\s*", "", body[start:a.start()]).split())
            answer = " ".join(body[a.end():stop].split())
            heading = _heading_before(body, start)
            form = _form_for(heading) or "short"

            # A LARGE PART OF THIS BOOK IS MULTIPLE CHOICE, printed inline:
            # "What is the name of the grandmother? (a) Saraswati (b) Triveni
            # (c) Krishtakka (d) Karmaveera" with the answer "(c) Krishtakka".
            # Those answers are three words long, so a rule that wanted eight
            # threw away several hundred keyed MCQs -- the most useful rows in
            # the book -- while reporting only "answer is under 8 words".
            opts, correct = _choices(stem, answer)
            if opts:
                stem = _OPT_ANY.split(stem)[0].strip() if _OPT_ANY.search(stem) else stem
                stem = " ".join(re.sub(r"\(\s*[a-dA-D]\s*\).*$", "", stem).split())
                form = "mcq"
            elif form != "true_false":
                why = _not_a_question(stem, answer, body[start:a.start()])
                if why:
                    skipped[why] = skipped.get(why, 0) + 1
                    continue
            if len(stem.split()) < 5:
                skipped["stem is a fragment, under 5 words"] = \
                    skipped.get("stem is a fragment, under 5 words", 0) + 1
                continue
            if form == "mcq" and not correct:
                skipped["mcq whose answer names no option"] = \
                    skipped.get("mcq whose answer names no option", 0) + 1
                continue
            items.append({
                "chapter_number": so, "chapter": name,
                "number": len(items) + 1, "form": form,
                "section_heading": heading[:120],
                "stem": stem, "options": opts, "correct_option": correct,
                "answer": answer[:4000],
                "concept": "", "needs_reading": True,
            })
            per[so] = per.get(so, 0) + 1
    doc.close()

    # Same stem twice in one chapter is the book repeating an extract prompt.
    seen, unique = set(), []
    for it in items:
        k = (it["chapter_number"], re.sub(r"[^a-z0-9]", "", it["stem"].lower())[:110])
        if k in seen:
            continue
        seen.add(k)
        unique.append(it)
    return {"label": label, "offset": off, "items": unique, "raw": len(items),
            "skipped": skipped, "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--section", choices=("prose", "poetry"), default="prose")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent
                                         / "kaveri_items" / "drafts"))
    a = ap.parse_args()

    rows = PROSE if a.section == "prose" else POETRY
    r = build(rows, a.section)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"c9_english_{a.section}.json").write_text(json.dumps(
        {"book": f"c9_english_{a.section}", "source": SOURCE.name,
         "source_url": SOURCE_URL, "publisher": PUBLISHER,
         "session": "2026-27", "validation_status": "sourced_verbatim",
         "items": r["items"]}, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"Class 9 English -- {SOURCE.name}, {a.section} section")
    print(f"  folio offset measured: printed + {r['offset']} = PDF page\n")
    per: dict[int, dict[str, int]] = {}
    for it in r["items"]:
        per.setdefault(it["chapter_number"], {}).setdefault(it["form"], 0)
        per[it["chapter_number"]][it["form"]] += 1
    forms = ("mcq", "short", "long", "true_false")
    print(f"  {'ch':>3} {'chapter':<40} " + " ".join(f"{f:>10}" for f in forms) + f" {'total':>6}")
    print("  " + "-" * 92)
    tot = 0
    for so, name, lo, hi in r["rows"]:
        d = per.get(so, {})
        n = sum(d.values()); tot += n
        print(f"  {so:>3} {name[:40]:<40} " + " ".join(f"{d.get(f,0):>10}" for f in forms) + f" {n:>6}")
    print("  " + "-" * 92)
    print(f"  {'':>3} {'total':<40} " + " ".join(
        f"{sum(d.get(f,0) for d in per.values()):>10}" for f in forms) + f" {tot:>6}\n")
    print(f"  before dedup {r['raw']}, after {len(r['items'])}")
    print(f"\n  exercise sections skipped as not-a-question "
          f"({sum(r['skipped'].values())} occurrences):")
    for h, n in sorted(r["skipped"].items(), key=lambda x: -x[1])[:14]:
        print(f"      {n:>3}  {h}")
    print(f"\ndrafts in {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
