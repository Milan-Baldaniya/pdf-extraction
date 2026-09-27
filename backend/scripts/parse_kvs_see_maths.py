"""Parse the KVS Lucknow Session Ending Examination Class 6/7 Maths papers.

    python -m scripts.parse_kvs_see_maths --grade 6
    python -m scripts.parse_kvs_see_maths --grade 7 --show

Section A of each paper is fifteen one-mark MCQs, and the marking scheme gives a
letter for every one. Only section A is taken: sections B to E are "draw", "solve"
and case-study questions whose marking scheme is a worked solution rather than a
key, and several are construction tasks that cannot be posed as text at all.

THESE PAPERS CARRY NO CHAPTER TAG OF ANY KIND -- they are whole-syllabus exams --
so every item's chapter is an editorial call from its content. That call lives in
`shape_kvs_for_load`.

THE DEGREE SIGN IS A SUPERSCRIPT ZERO. Both papers type "180<sup>0</sup>" for
180 degrees, an ordinary Indian typing convention, and a plain text extraction
flattens it to "1800" -- a stem that reads as eighteen hundred degrees and an
option list of "1800 / 600 / 900 / 3600" for the angles of an equilateral
triangle. The superscript is a real span flag in the PDF, so this reads the page
span by span and turns a superscripted 0 into the degree sign it stands for.
Verified by rasterising the two items and looking at them.

WHAT STILL CANNOT BE READ is a fraction. These papers set fractions as stacked
numerator over denominator in a separate text frame, so an option prints as an
empty "(a)" with the digits "1" and "6" arriving somewhere after all four labels.
Those items come out with blank options, are reported here, and are not loaded.
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

MIRROR = Path(__file__).resolve().parents[1] / "data" / "qbank" / "mirror" / "kvs_lucknow"
OUT = Path(__file__).resolve().parent / "kvs_see_items" / "drafts"

FILES = {6: ("c6_maths_see_2526_qp.pdf", "c6_maths_see_2526_ms.pdf"),
         7: ("c7_maths_see_2526_qp.pdf", "c7_maths_see_2526_ms.pdf")}
SOURCE_URL = "https://kvslucknowregion.in/"

SUPERSCRIPT = 1  # fitz span flag bit 0

# "(a)", "( c)", "(c )" and a zero-width space after the bracket all occur.
LABEL = re.compile(r"\(\s*([a-d])\s*\)", re.I)
# A question starts at a line that is just its number, or its number then text.
START = re.compile(r"^\s*Q?\s*(\d{1,2})\s*[.)]?\s*(.*)$")
# ANCHORED TO THE WHOLE LINE. The General Instructions say "Section - A consists
# of 15 questions of 1 mark each" and "Section- B consists of 5 questions", so a
# loose search finds both inside the rubric and returns an empty region.
SECTION_B = re.compile(r"^\s*SECTION\s*[-–\s]*B\b.*$", re.I | re.M)
SECTION_A = re.compile(r"^\s*(?:Q\.?\s*)?(?:No\.?\s*)?SECTION\s*[-–\s]*A\b.*$",
                       re.I | re.M)


def read(path: Path) -> str:
    """The document's text, with a superscripted 0 restored to a degree sign."""
    doc = fitz.open(path)
    lines: list[str] = []
    for page in doc:
        for block in doc[page.number].get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                out = []
                for span in line["spans"]:
                    t = span["text"]
                    if span["flags"] & SUPERSCRIPT and t.strip() == "0":
                        t = "°"
                    out.append(t)
                lines.append("".join(out))
    doc.close()
    return "\n".join(lines)


def section_a(text: str) -> str:
    starts = list(SECTION_A.finditer(text))
    if not starts:
        raise SystemExit("no SECTION A heading on its own line")
    # The LAST such heading: the rubric page can carry one that is a whole line
    # by itself, and the questions follow the one printed above them.
    for start in reversed(starts):
        end = SECTION_B.search(text, start.end())
        region = text[start.end(): end.start() if end else len(text)]
        if LABEL.search(region):
            return region
    return ""


def split_items(region: str) -> dict[int, list[str]]:
    items: dict[int, list[str]] = {}
    cur: list[str] | None = None
    expect = 1
    for raw in region.split("\n"):
        line = raw.replace("​", "").rstrip()
        if not line.strip():
            continue
        m = START.match(line)
        # Only a number that CONTINUES the sequence starts an item: a bare "1"
        # is also the marks cell at the end of every question, and an option
        # like "(a) 1" would otherwise open item one over and over.
        if m and int(m.group(1)) == expect and not LABEL.match(line.strip()):
            cur = items.setdefault(expect, [])
            expect += 1
            if m.group(2).strip():
                cur.append(m.group(2).strip())
            continue
        if cur is not None:
            cur.append(line.strip())
    return items


def shape(number: int, lines: list[str]) -> dict:
    text = " ".join(lines)
    # The trailing marks cell, and the assertion-reason rubric that is printed
    # once for the pair of items that use it.
    text = re.sub(r"\s*\b1\s*$", "", text).strip()
    first = LABEL.search(text)
    stem = (text[:first.start()] if first else text).strip()
    options = []
    if first:
        parts = LABEL.split(text[first.start():])
        for label, body in zip(parts[1::2], parts[2::2]):
            options.append({"label": label.lower(),
                            "text": " ".join(body.split()).strip(" .")})
    return {
        "number": number,
        "stem": " ".join(stem.split()),
        "options": options,
        "form": "mcq",
        "marks": 1,
    }


def marking_scheme(text: str) -> dict[int, str]:
    """Question number -> key letter.

    The two papers disagree about where the letter goes: Class 6 prints the
    number on its own line and "(c) 1/8" on the next, Class 7 puts both on one.
    So the letter is taken from the number's own line if it is there, and from
    the next few lines otherwise.
    """
    lines = [l.replace("​", "").strip() for l in text.split("\n")]
    out: dict[int, str] = {}
    expect = 1
    for i, line in enumerate(lines):
        m = START.match(line)
        if not m or int(m.group(1)) != expect or LABEL.match(line):
            continue
        for candidate in [m.group(2)] + lines[i + 1:i + 3]:
            hit = LABEL.search(candidate)
            if hit:
                out[expect] = hit.group(1).lower()
                expect += 1
                break
    return out


def parse(grade: int) -> dict:
    qp, ms = FILES[grade]
    region = section_a(read(MIRROR / qp))
    keys = marking_scheme(read(MIRROR / ms))
    items = []
    for number, lines in sorted(split_items(region).items()):
        item = shape(number, lines)
        item["correct_option"] = keys.get(number)
        items.append(item)
    return {"grade": grade, "source": qp, "marking_scheme": ms,
            "source_url": SOURCE_URL, "items": items}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grade", type=int, required=True, choices=(6, 7))
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()

    data = parse(a.grade)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"c{a.grade}_maths_kvs_see.json").write_text(
        json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")

    items = data["items"]
    clean = [i for i in items if len(i["options"]) == 4
             and all(o["text"] for o in i["options"]) and i["correct_option"]]
    print(f"{data['source']}: {len(items)} section-A items, {len(clean)} readable")
    print(f"  no key       : {[i['number'] for i in items if not i['correct_option']]}")
    print(f"  not 4 options: "
          f"{[(i['number'], len(i['options'])) for i in items if len(i['options']) != 4]}")
    print(f"  blank option : "
          f"{[i['number'] for i in items if any(not o['text'] for o in i['options'])]}")
    if a.show:
        for i in items:
            print(f"\n Q{i['number']} key={i['correct_option']}")
            print(f"   {i['stem']}")
            for o in i["options"]:
                print(f"     ({o['label']}) {o['text']}")
    print(f"\ndraft in {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
