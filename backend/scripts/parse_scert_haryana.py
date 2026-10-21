"""Parse SCERT Haryana's Class 6/7 Mathematics competency question banks.

    python -m scripts.parse_scert_haryana --grade 6
    python -m scripts.parse_scert_haryana --grade 6 --show 14

Fifty items per class, every one a single-best-answer MCQ, every one answered by
a marking scheme that prints nothing but "Correct Answer: C". These are already
NEP-era material, so unlike CBSE's SAS books they need no old-book remap -- but
they are tagged to Haryana's own COMPETENCY codes rather than to chapters, so
the chapter still has to be decided. `shape_scert_for_load` owns that decision.

THE PAGE IS A THREE-COLUMN TABLE -- serial number, question, marks -- and every
item is printed twice, in English and in Hindi. Two things make the obvious
reading fail, and they differ BETWEEN THE TWO BOOKS:

  * Class 6 merges the serial number into the English stem's cell at x~=43;
    Class 7 gives it a cell of its own at x~=68 and puts the stem at x~=109,
    in the same column as the Hindi. So neither the serial number's position
    nor the stem's is stable.
  * The serial-number cell is vertically CENTRED in its row, so on a tall
    question it sorts BELOW the first line of the stem. Segmenting on it
    therefore drops items -- eight of fifty in Class 6 and all fifty in
    Class 7.

THE MARKS CELL IS THE RELIABLE ANCHOR. It is a bare "1" in the rightmost column,
it appears exactly once per item, and it is top-aligned with the row, so the
blocks between one marks cell and the next are one item. Everything here is
segmented on that.

WHAT IS TAKEN is the English half only: from the start of the row up to the first
Devanagari character. The Hindi is left deliberately -- it is set in a legacy
font that the text layer mangles ("नीचे %दखाए गए"), so loading it would put
unreadable stems in the bank. Options are pulled out of the accumulated English
text rather than a block, because Class 6 sometimes prints them in a cell of
their own and sometimes runs them into the end of the stem.

THE INLINE COMPETENCY TAG IS NOT ALWAYS THERE -- five of the fifty Class 6 items
have none, and two books spell it "MAT 605" with a space. The mapping table on
the contents page lists every competency against its question numbers, so that
is the authority and the inline tag is only a cross-check.
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

MIRROR = Path(__file__).resolve().parents[1] / "data" / "qbank" / "mirror" / "scert_haryana"
OUT = Path(__file__).resolve().parent / "scert_items" / "drafts"

FILES = {6: "c6_maths_2526.pdf", 7: "c7_maths_2526.pdf"}
SOURCE_URL = "https://scertharyana.gov.in/question-bank/"

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
SERIAL = re.compile(r"^(\d{1,2})\s+(?=\S)")
OPTION_RUN = re.compile(r"^\(A\)")
# "MAT605" and "MAT 605" are the same code; the space is a typo in two tags.
COMP = re.compile(r"\[MAT\s?(\d{3})\s*:\s*Competency:\s*(.*?)\]", re.S)
FOLIO = re.compile(r"^\d{1,3} of \d{1,3}$")
HEADER = "Serial No."
# "(A) 1/3 (B) 3/4 (C) 5/12 (D) 7/12" -> four labelled option texts.
SPLIT_OPTS = re.compile(r"\((A|B|C|D)\)\s*")


def blocks(page) -> list[tuple[float, str, bool]]:
    """(x, text, is_marks_anchor) in reading order, furniture removed."""
    right = page.rect.width * 0.8

    def is_anchor(b) -> bool:
        return b[0] > right and bool(re.fullmatch(r"\d{1,2}", " ".join(b[4].split())))

    # THE ANCHOR SORTS FIRST IN ITS ROW. The marks cell is top-aligned with the
    # first line of its question, so a plain (y, x) sort puts the stem -- which
    # is to its left -- ahead of it, and the stem is then attributed to the
    # PREVIOUS item. That emptied one stem and gave its neighbour eight options.
    out = []
    for b in sorted(page.get_text("blocks"),
                    key=lambda r: (round(r[1] / 4), 0 if is_anchor(r) else 1, r[0])):
        s = " ".join(b[4].split())
        if not s or s.startswith(HEADER) or FOLIO.match(s):
            continue
        out.append((b[0], s, is_anchor(b)))
    return out


def competency_table(doc) -> dict[int, tuple[str, str]]:
    """question number -> (competency code, description), from the contents page."""
    blob = "\n".join(p.get_text() for p in doc)
    i = blob.find("Competency Mapping")
    table = blob[i:] if i >= 0 else blob
    out: dict[int, tuple[str, str]] = {}
    # Class 6 puts the code and its description on separate lines, Class 7 on
    # one, so the region between two codes is what is parsed rather than a fixed
    # line shape: its description is everything before the first "Qn", and every
    # "Qn" after that is a question the competency covers.
    marks = [(m.start(), m.group(0).replace(" ", ""))
             for m in re.finditer(r"MAT\s?\d{3}", table)]
    for i, (start, code) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(table)
        region = table[start:end]
        first_q = re.search(r"\bQ\d+", region)
        desc = " ".join(region[len(code):first_q.start()].split()) if first_q else ""
        for n in re.findall(r"\bQ(\d+)", region):
            out[int(n)] = (code, desc)
    return out


def marking_scheme(doc) -> dict[int, str]:
    blob = "\n".join(p.get_text() for p in doc)
    i = blob.find("Marking Scheme")
    if i < 0:
        return {}
    out: dict[int, str] = {}
    for num, letter in re.findall(
            r"^\s*(\d{1,3})\s*\n\s*Correct Answer:\s*([A-D])\s*$", blob[i:], re.M):
        out[int(num)] = letter
    return out


def parse(grade: int) -> dict:
    doc = fitz.open(MIRROR / FILES[grade])
    table = competency_table(doc)
    keys = marking_scheme(doc)

    items: list[dict] = []
    cur: dict | None = None
    for page in doc:
        text = page.get_text()
        # NOT "Marking Scheme": the contents page lists that as a section and a
        # break on the words stops before the first question is ever read. The
        # rubric itself is the only unambiguous marker.
        if "Correct Answer:" in text:
            break
        if HEADER not in text:
            continue
        for x, s, anchor in blocks(page):
            if anchor:
                cur = {"english": [], "tag": None, "done": False}
                items.append(cur)
                continue
            if cur is None:
                continue
            tag = COMP.search(s)
            if tag and cur["tag"] is None:
                cur["tag"] = "MAT" + tag.group(1)
            if cur["done"]:
                continue
            if DEVANAGARI.search(s):
                # The Hindi half has started; this item's English text is over.
                cur["done"] = True
                continue
            cur["english"].append(s)
    doc.close()

    out = []
    last = 0
    for ordinal, it in enumerate(items, start=1):
        text = " ".join(" ".join(it["english"]).split())
        # The competency tag can trail the English text when the Hindi is short.
        text = COMP.sub("", text).strip()
        # A PURELY NUMERIC ITEM HAS NO DEVANAGARI TO STOP AT. "711 + 177 + 33 =
        # (A) 888 ..." is character for character the same in both halves, so
        # the Hindi copy was taken as well and the item came out with eight
        # options. Cutting at the point where the text starts repeating itself
        # keeps the English half and nothing else.
        head = text[:30]
        if len(head) == 30:
            again = text.find(head, 1)
            if again > 0:
                text = text[:again].strip()
        # A LEADING SERIAL NUMBER, where the book merged it into the stem cell.
        # The printed number is what the marking scheme and the competency table
        # are keyed on, so it wins over position -- but only when it CONTINUES
        # the sequence. "711 + 177 + 33 =" and "5 kg of rice" both start with a
        # number that is not a serial, and a row whose serial cell sorted out of
        # its row has none at all, so anything that does not advance the count by
        # a step or two is treated as content and the count is carried on.
        lead = SERIAL.match(text)
        number = last + 1
        if lead and last < int(lead.group(1)) <= last + 3:
            number = int(lead.group(1))
            text = text[lead.end():]
        last = number
        parts = SPLIT_OPTS.split(text)
        stem = " ".join(parts[0].split())
        options, seen = [], set()
        for label, body in zip(parts[1::2], parts[2::2]):
            if label in seen:
                continue
            seen.add(label)
            options.append({"label": label, "text": " ".join(body.split())})
        # THE INLINE TAG WINS. It is printed inside the item's own table row, and
        # it agrees with the contents-page mapping table for 99 of the 100 items
        # in the two books. The one disagreement is the table's fault: Class 7
        # lists "Q1" under MAT709 between Q8 and Q15, out of the ascending order
        # the rest of that list keeps, and Q10 is the only number the table
        # leaves unclaimed. So the table's entry is a typo for Q10 and Q1 is
        # MAT701, which is what its inline tag says.
        t_code, t_desc = table.get(number, (None, ""))
        code = it["tag"] or t_code
        desc = t_desc if code == t_code else next(
            (d for c, d in table.values() if c == code), "")
        out.append({
            "number": number,
            "ordinal": ordinal,
            "stem": stem,
            "options": options,
            "correct_option": keys.get(number),
            "competency": code,
            "competency_desc": desc,
            "inline_tag": it["tag"],
            "form": "mcq",
            "marks": 1,
        })
    return {"grade": grade, "source": FILES[grade], "source_url": SOURCE_URL,
            "items": out, "keys": len(keys), "mapped": len(table)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grade", type=int, required=True, choices=(6, 7))
    ap.add_argument("--show", type=int, help="print one item in full")
    a = ap.parse_args()

    data = parse(a.grade)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"c{a.grade}_maths_scert.json").write_text(
        json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")

    items = data["items"]
    nums = [i["number"] for i in items]
    print(f"{data['source']}: {len(items)} items, numbers {min(nums)}-{max(nums)}, "
          f"{len(set(nums))} distinct")
    print(f"  marking-scheme keys {data['keys']}, competency-table entries {data['mapped']}")
    print(f"  items with no key        : {[i['number'] for i in items if not i['correct_option']]}")
    print(f"  items with no competency : {[i['number'] for i in items if not i['competency']]}")
    print(f"  items without 4 options  : "
          f"{[(i['number'], len(i['options'])) for i in items if len(i['options']) != 4]}")
    disagree = [(i["number"], i["competency"], i["inline_tag"]) for i in items
                if i["inline_tag"] and i["competency"] != i["inline_tag"]]
    print(f"  table vs inline tag clash: {disagree}")
    if a.show:
        it = next(i for i in items if i["number"] == a.show)
        print(json.dumps(it, indent=1, ensure_ascii=False))
    print(f"\ndraft in {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
