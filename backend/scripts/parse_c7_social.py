"""Draft items from the NODIA Class 7 Social Science "QB 2026" bank.

    python -m scripts.parse_c7_social

The book is "Exploring Society: India and Beyond", the NEP-2020 replacement,
and its twenty chapters match the twenty the database holds one for one --
twelve under `Social Sciences` and eight under `Social Sciences-2`. That was
checked before any of this was written: nineteen of the twenty chapter names
appear verbatim in the text layer. See
[[estate-is-on-nep-replacement-books]] for why that check comes first.

THE ANSWER MARKER IS `AAns`, NOT `Ans :`. There are 3,153 of the first and
exactly one of the second. The doubled first letter is a styling artefact that
the text layer keeps -- the same thing turns "NCERT EXERCISE" into "NNCERT
EXERCIS" and "CHAPTER" into "CCHAPTER". Parsing this book for `Ans :` finds
one question in three thousand, and reports no error at all.

FOLIO RANGES, NOT THE RUNNING HEADER. Every page carries a `CH n :` header,
but the book is printed in two parts and the chapter numbers RESTART: "CH 1"
is Geographical Diversity of India in Part 1 and The Story of Indian Farming
in Part 2. The contents pages print an exact folio range per chapter, and the
folio-to-page offset is measured at run time.

TWENTY-SEVEN ADVERTISEMENT PAGES sit INSIDE the chapter ranges -- pdf.tube
catalogue pages listing other books. They carry no question and no answer, and
left in they leak "Click your Subject and Instantly get a free PDF" into
whichever stem happens to span them. A page with a pdf.tube URL and no `AAns`
is dropped.

Section banners are letter-spaced in the text layer ("MULT IPL E CHOICE
QUESTIO"), so they are matched with the whitespace removed.
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

SOURCE = (Path(__file__).resolve().parents[1] / "data" / "qbank" / "mirror"
          / "pdftube" / "c7_Social_Science_QB_2026.pdf")
SOURCE_URL = "https://pdf.tube/School/CBSE/"
PUBLISHER = "nodia"
STANDARD_ID = 40

# part, sort_order, chapter name, printed folio range -- from the book's own
# contents pages. Part 1 is the database's `Social Sciences`, Part 2 its
# `Social Sciences-2`.
CHAPTERS = [
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
]

_ANS = re.compile(r"(?m)^\s*A?Ans\b\s*")
_QSTART = re.compile(r"(?m)^[ \t]*(\d{1,3})\s*\.\s*(?=\S|$)")
_OPT_LINE = re.compile(r"(?m)^[ \t]*\(\s*([A-Da-d])\s*\)[ \t]*(.+?)[ \t]*$")
_OPT_ANY = re.compile(r"\(\s*([A-Da-d])\s*\)\s*([^()]{1,200}?)(?=\s*\(\s*[A-Da-d]\s*\)|\s*$)")
_LEAD = re.compile(r"(?i)^\s*\(?\s*([A-Da-d])\s*\)?[.\s]*")

# Banners, matched with whitespace stripped out because the text layer
# letter-spaces them: "MULT IPL E CHOICE QUESTIO".
BANNERS = [
    ("MULTIPLECHOICE", "mcq"),
    ("ASSERTIONREASON", "assertion_reason"),
    ("CASESTUDY", "case_study"),
    ("CASEBASED", "case_study"),
    ("VERYSHORT", "very_short"),
    ("SHORTANSWER", "short"),
    ("LONGANSWER", "long"),
    ("NCERTEXERCIS", "short"),
    ("COMPETENCYBASED", "short"),
]


def _squash(s: str) -> str:
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def _is_ad(text: str) -> bool:
    """A pdf.tube catalogue page: no question on it, and it is inside a chapter."""
    return "pdf.tube" in text and "AAns" not in text


def _folio_offset(doc) -> int:
    key = _squash(CHAPTERS[0][2])[:24]
    for cand in range(0, 40):
        p = CHAPTERS[0][3] + cand - 1
        if 0 <= p < doc.page_count and key in _squash(doc[p].get_text() or ""):
            return cand
    raise SystemExit("Could not measure the folio offset -- layout has changed")


def _blob(doc, lo: int, hi: int, off: int) -> tuple[str, int]:
    out, skipped = [], 0
    for p in range(lo + off - 1, min(hi + off, doc.page_count)):
        try:
            raw = doc[p].get_text() or ""
        except Exception:
            continue
        if _is_ad(raw):
            skipped += 1
            continue
        for ln in raw.splitlines():
            # the running header, e.g. "page  8" / "Cbse Class 7th Social Science"
            if re.match(r"^\s*page\s+\d+\s*$", ln) or "Chapterwise QB" in ln:
                continue
            out.append(ln)
    return "\n".join(out), skipped


def _is_banner(line: str) -> str:
    """The form a heading announces, or "".

    A banner is SHORT and nearly all capitals. Requiring that is what keeps
    the sentence "Here are 5 Multiple Choice Questions based on the chapter"
    -- which the book prints as ordinary prose -- from re-typing every
    question after it.
    """
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


def _options(block: str) -> list[dict]:
    opts: dict[str, str] = {}
    for m in _OPT_LINE.finditer(block):
        lab, txt = m.group(1).upper(), " ".join(m.group(2).split()).strip(" .,;")
        if txt and lab not in opts:
            opts[lab] = txt[:240]
    if sorted(opts) != ["A", "B", "C", "D"]:
        opts = {}
        for lab, txt in _OPT_ANY.findall(" ".join(block.split())):
            lab, txt = lab.upper(), " ".join(txt.split()).strip(" .,;")
            if txt and lab not in opts:
                opts[lab] = txt[:240]
    if sorted(opts) != ["A", "B", "C", "D"]:
        return []
    return [{"label": k, "text": opts[k]} for k in sorted(opts)]


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def _key(opts: list[dict], answer: str) -> str:
    """The option the answer names -- by VALUE first, letter only as a fallback.

    The rule the ZIET Maths bank taught: a printed letter can name a different
    option than the value beside it, and `V-02` cannot see the difference.
    """
    if not opts:
        return ""
    body = _norm(_LEAD.sub("", answer)[:120])
    hit = [o["label"] for o in opts if _norm(o["text"]) and _norm(o["text"])[:40] in body]
    if len(hit) == 1:
        return hit[0]
    m = _LEAD.match(answer)
    lab = m.group(1).upper() if m else ""
    return lab if lab in {o["label"] for o in opts} else ""


def build() -> dict:
    doc = fitz.open(SOURCE)
    off = _folio_offset(doc)
    items, dropped, ads = [], {}, 0

    for part, so, name, lo, hi in CHAPTERS:
        body, skipped = _blob(doc, lo, hi, off)
        ads += skipped
        qpos = [m.start() for m in _QSTART.finditer(body)]
        apos = list(_ANS.finditer(body))

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
                dropped["matching-type exercise"] = \
                    dropped.get("matching-type exercise", 0) + 1
                continue

            # FOUR LABELLED OPTIONS PLUS AN ANSWER THAT NAMES ONE IS AN MCQ,
            # whatever the banner says. Chapter 3 prints no MULTIPLE CHOICE
            # heading at all, and keyed on the banner alone it reported zero
            # MCQs against sixty to eighty in every sibling chapter -- a
            # shape that is obviously wrong but that nothing would have
            # flagged. The banner still decides the descriptive forms, where
            # there are no options to go on.
            opts = _options(raw_stem)
            stem_lines = [ln for ln in raw_stem.splitlines()
                          if not (opts and _OPT_LINE.match(ln))]
            stem = " ".join(re.sub(r"^\s*\d{1,3}\s*\.\s*", "", "\n".join(stem_lines)).split())
            if opts:
                for o in opts:
                    stem = stem.replace(f"({o['label']}) {o['text']}", " ")
                stem = " ".join(stem.split())

            correct = _key(opts, answer) if opts else ""
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
            # A ONE-WORD ANSWER IS NOT A MISSING ANSWER. "Which region is
            # known as 'moonland'? -- Ladakh." is complete, and so is an
            # mcq's "(C) Chilika Lake". A five-word floor threw away 274 of
            # these, every one of them sourced and correct, and reported the
            # loss as though the book had failed to answer them.
            if not answer.strip():
                dropped["no answer at all"] = dropped.get("no answer at all", 0) + 1
                continue
            items.append({
                "part": part, "chapter_number": so, "chapter": name,
                "number": len(items) + 1, "form": form,
                "stem": stem, "options": opts, "correct_option": correct,
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
    return {"items": unique, "dropped": dropped, "offset": off, "ads": ads,
            "raw": len(items)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent
                                         / "c7social_items" / "drafts"))
    a = ap.parse_args()
    r = build()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "c7_social.json").write_text(json.dumps(
        {"book": "c7_social", "source": SOURCE.name, "source_url": SOURCE_URL,
         "publisher": PUBLISHER, "session": "2026-27",
         "validation_status": "sourced_verbatim", "items": r["items"]},
        indent=1, ensure_ascii=False), encoding="utf-8")

    forms = ("mcq", "very_short", "short", "long", "case_study", "assertion_reason")
    print(f"Class 7 Social Science -- {SOURCE.name}")
    print(f"  folio offset printed + {r['offset']}, advertisement pages skipped {r['ads']}\n")
    print(f"  {'pt':>2} {'ch':>3} {'chapter':<46} " + " ".join(f"{f[:9]:>9}" for f in forms) + f" {'total':>6}")
    print("  " + "-" * 118)
    tot = 0
    for part, so, name, lo, hi in CHAPTERS:
        ks = [i for i in r["items"] if i["part"] == part and i["chapter_number"] == so]
        tot += len(ks)
        print(f"  {part:>2} {so:>3} {name[:46]:<46} "
              + " ".join(f"{sum(1 for i in ks if i['form']==f):>9}" for f in forms)
              + f" {len(ks):>6}")
    print("  " + "-" * 118)
    print(f"  {'':>2} {'':>3} {'total':<46} "
          + " ".join(f"{sum(1 for i in r['items'] if i['form']==f):>9}" for f in forms)
          + f" {tot:>6}\n")
    print(f"  before dedup {r['raw']}, after {len(r['items'])}")
    print("  dropped:")
    for why, n in sorted(r["dropped"].items(), key=lambda x: -x[1]):
        print(f"      {n:>4}  {why}")
    print(f"\ndrafts in {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
