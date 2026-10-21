"""Place SCERT Haryana's Class 6/7 Maths items on the NEP Ganita Prakash chapters.

    python -m scripts.shape_scert_for_load --grade 6
    python -m scripts.shape_scert_for_load --grade 7 --verbose

Reads `scripts/scert_items/drafts/c{6,7}_maths_scert.json` and writes one
`chNN.json` per NEP chapter under `scripts/scert_items/load/c{6,7}/`.

THIS SOURCE NEEDS NO OLD-BOOK REMAP -- it is NEP-era material -- but it is
tagged to Haryana's own COMPETENCY codes rather than to chapters, so a chapter
still has to be chosen. A competency is a coarser thing than a chapter and does
not map one to one: MAT601, "read, write, compare and explain any natural number
and perform all four operations on them", spans twelve items that between them
belong to a number-sequence chapter, a place-value chapter, and nothing at all.
COMPETENCY below therefore records the default reading of each code, and KEEP
records the per-item decision, because the per-item decision is what governs.

THE TAGS ARE NOT ALWAYS RIGHT EITHER. Q41 of Class 7 is tagged MAT703, "calculate
mean, median, mode and range", and asks for the perimeter of a regular polygon.
Where the tag and the item disagree, the item wins.

AND TWO KEYS ARE WRONG, one in each book.

  Class 7 Q50 asks which number decreases by 300 when its 7 becomes a 4, offers
  3079 / 4637 / 5743 / 7340, and its marking scheme says A. Only 5743 works:
  5743 - 5443 = 300, so the answer is C.

  Class 6 Q25 asks how much more 1 is than 0.06, offers 0.4 / 0.04 / 0.05 / 0.94,
  and its marking scheme says B. 1 - 0.06 = 0.94, so the answer is D. Both the
  stem and the options were checked against the page, not just the text layer.

Both are left out. There is no validator anywhere downstream that could catch a
key that is simply untrue, so every key in KEEP was worked through by hand.

CROSS-GRADE PLACEMENT. NEP moved decimals from Class 6 to Class 7, so MAT611's
readable items are filed on Class 7 ch3 A Peek Beyond the Point. The move is
marked `cross_grade` in the shaped file and recorded in the extraction's
metadata, so the decision is visible without reading this file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

from scripts.shape_c67sas_for_load import STANDARD, fold, resolve  # noqa: E402

import re  # noqa: E402

# THE DEGREE SIGN COMES THROUGH AS A LETTER o -- "95o", "108o". Restoring it is
# gated on the item actually being about angles, so a stray "5o" somewhere else
# can never be rewritten into a measurement the source did not print.
DEGREE = re.compile(r"(?<=\d)o\b")
ANGLE_CUE = re.compile(r"angle|degree|clockwise|triangle|°", re.I)


def degrees(s: str, geometric: bool) -> str:
    return DEGREE.sub("°", s) if geometric else s

ROOT = Path(__file__).resolve().parent / "scert_items"
DRAFTS = ROOT / "drafts"
LOAD = ROOT / "load"
PUBLISHER = "scert_haryana"
SOURCE_URL = "https://scertharyana.gov.in/question-bank/"

# What each competency is FOR, and where that lands in Ganita Prakash. This is
# the default reading; KEEP overrides it item by item where an item's own
# content belongs somewhere else, which for the broad codes is often.
COMPETENCY: dict[str, tuple[int | None, str]] = {
    # ---- Class 6 ----
    "MAT601": (None, "natural numbers and the four operations -- too broad to "
        "map as a block; Ganita Prakash 6 has no arithmetic-operations chapter, "
        "so each item is placed on its own merits or declined"),
    "MAT602": (9, "lines of symmetry, reflection and rotational symmetry -> ch9 Symmetry"),
    "MAT605": (5, "factorisation, HCF and LCM -> ch5 Prime Time"),
    "MAT607": (None, "3D shapes by edges, faces and vertices -- no GP6 chapter"),
    "MAT608": (10, "integers and the number line -> ch10 The Other Side of Zero"),
    "MAT609": (7, "fractions pictorially and on a number line -> ch7 Fractions"),
    "MAT610": (7, "converting and comparing fractions, adding and subtracting "
        "them -> ch7 Fractions"),
    "MAT611": ((7, 3), "CROSS-GRADE. GP6 has no decimals chapter at all; NEP "
        "teaches decimals in Class 7 ch3 A Peek Beyond the Point, whose "
        "sections A Hundredth Part, Decimal Place Value and Locating and "
        "Comparing Decimals are what these items test. Six of the nine read "
        "their value off a shaded figure or a drawn rope and one has a wrong "
        "key, so three are loaded"),
    "MAT612": (4, "organising data, tally marks and bar diagrams -> ch4 Data "
        "Handling and Presentation"),
    "MAT613": (6, "area of rectangles and perimeter -> ch6 Perimeter and Area"),
    "MAT614": (None, "statements into expressions and equations -- no GP6 "
        "chapter; the topic is Class 7 ch4 and ch15"),
    "MAT615": (None, "ratio and proportion -- no Ganita Prakash chapter in "
        "either grade"),
    # ---- Class 7 ----
    "MAT701": (10, "multiplying and dividing integers -> ch10 Operations with "
        "Integers, though several of its twelve items are really divisibility "
        "or place value and are placed accordingly"),
    "MAT702": (8, "multiplying and dividing fractions and decimals -> ch8 "
        "Working with Fractions, or ch12 for a decimal item"),
    "MAT703": (13, "mean, median, mode and range -> ch13 Connecting the Dots"),
    "MAT704": (None, "possibility and probability -- no GP7 chapter"),
    "MAT705": (15, "forming and solving simple equations -> ch15 Finding the "
        "Unknown, or ch4 where the item only simplifies an expression"),
    "MAT706": (5, "properties of lines and angles -> ch5 Parallel and "
        "Intersecting Lines"),
    "MAT707": (7, "categorising triangles -> ch7 A Tale of Three Intersecting Lines"),
    "MAT709": (None, "converting between fractions, decimals, percentages and "
        "ratios -- percentage has no GP7 chapter, so only a fraction-or-decimal "
        "item could be placed and none survives"),
    "MAT710": (None, "profit, loss and percentage -- no GP7 chapter"),
    "MAT713": (None, "perimeter and area including the circle -- GP7 has no "
        "area chapter, and GP6 ch6 does not teach the circle"),
    "MAT715": (None, "exponents -- no GP7 chapter; NEP moved it to Class 8"),
}

# THE ALLOW-LIST: question number -> (NEP chapter, why it is answerable and why
# it belongs there). Every key here was worked through by hand against the
# options. Everything absent was read and rejected; --verbose says why.
KEEP: dict[int, dict[int, tuple[int, str]]] = {
    6: {
        6:  (1, "the rule of the sequence 2, 8, 26, 80 -- ch1's Number Sequences "
                "and Relations among Number Sequences. The one item in either "
                "book that genuinely belongs in Patterns in Mathematics"),
        9:  (5, "the two bells ring together again after LCM(20, 35) = 140 min"),
        16: (5, "which of 166, 1079, 96, 73 could be prime"),
        24: (5, "a class divisible by 5, 6 and 10 -- LCM = 30"),
        29: (5, "every multiple of an odd number other than itself is composite"),
        35: (5, "the only factor a prime shares with this list is 1"),
        42: (5, "how many tens divide 6 x 500 x 20 x 5 -- divisibility read off "
                "a factorisation, which is a section of ch5"),
        50: (5, "fewer than 500 and divisible by 3, 4, 5 and 7 -- LCM = 420"),
        36: (9, "an arrow pointing West turned 95 degrees clockwise. The "
                "direction is given in words, so the figure is decorative"),
        # ---- CROSS-GRADE: Class 6 items on Class 7 ch3 A Peek Beyond the
        # Point. Ganita Prakash 6 has no decimals chapter; NEP teaches decimals
        # in Class 7, so the chapter that now covers these items is there.
        2:  ((7, 3), "how many hundredths to take from 1 to leave four tenths "
                     "-- ch3's A Hundredth Part and Decimal Place Value"),
        13: ((7, 3), "which of 75.08, 7.508, 7.058 and 75.8 is greatest -- "
                     "ch3's Locating and Comparing Decimals"),
        47: ((7, 3), "which number is 1 more than 49.36 -- decimal place value"),
    },
    7: {
        1:  (11, "a divisibility test for 12 is the tests for 3 and 4 together "
                 "-- ch11's Primes and Prime Factorisation"),
        30: (11, "the sum of two odd primes is even and composite"),
        18: (1,  "59 x 156 from 58 x 156 -- ch1's Patterns in Products"),
        12: (4,  "simplifying 3x - 1 + 5y + 2"),
        26: (4,  "recognising 5a - 3b + 5 as 4a + a + 5 - 3b"),
        25: (5,  "OP bisects angle QOY on the straight line YZ and angle POQ is "
                 "twice angle QOZ. Every fact is given in words, so the figure "
                 "is not needed: QOZ = 36, POZ = 108"),
        11: (7,  "two angles of a triangle sum to 75, so the third is 105 and "
                 "the triangle is obtuse -- ch7's Types of Triangles"),
        32: (10, "the product is what is 0 when either number is 0"),
        33: (10, "the sum of two negative numbers is the one that cannot be "
                 "positive"),
    },
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grade", type=int, required=True, choices=(6, 7))
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    grade = a.grade

    draft = json.loads((DRAFTS / f"c{grade}_maths_scert.json").read_text(encoding="utf-8"))
    keep = KEEP[grade]
    items = {i["number"]: i for i in draft["items"]}

    missing = set(keep) - set(items)
    if missing:
        raise SystemExit(f"KEEP names items the draft does not hold: {sorted(missing)}")
    unknown = {i["competency"] for i in draft["items"]} - set(COMPETENCY)
    if unknown:
        raise SystemExit(f"competencies with no decision recorded: {sorted(unknown)}")

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        chapters = {g: resolve(g, db) for g in STANDARD}
    finally:
        db.close()

    by_dest: dict[tuple[int, int], list[dict]] = {}
    for number, (dest, _why) in sorted(keep.items()):
        target = dest if isinstance(dest, tuple) else (grade, dest)
        it = items[number]
        if len(it["options"]) != 4 or not it["correct_option"]:
            raise SystemExit(f"Q{number}: {len(it['options'])} options, "
                             f"key {it['correct_option']!r} -- not loadable")
        geometric = bool(ANGLE_CUE.search(
            it["stem"] + " ".join(o["text"] for o in it["options"])))
        stem = degrees(it["stem"], geometric)
        opts = [{"label": o["label"], "text": fold(degrees(o["text"], geometric))}
                for o in it["options"]]
        answer_text = next(o["text"] for o in opts
                           if o["label"] == it["correct_option"])
        by_dest.setdefault(target, []).append({
            "number": f"SCERT-HR-{grade}-Q{number}",
            "form": "mcq",
            "stem": fold(stem),
            "options": opts,
            "correct_option": it["correct_option"],
            "answer": fold(f"{it['correct_option']}. {answer_text}"),
            "marks": 1,
            "reproduction": "verbatim",
        })

    for dest_grade in sorted({g for g, _ in by_dest} | {grade}):
        out_dir = LOAD / (f"c{grade}" if dest_grade == grade
                          else f"c{grade}_to_c{dest_grade}")
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob("ch*.json"):
            old.unlink()

    print(f"Class {grade} Mathematics  {len(draft['items'])} SCERT items read, "
          f"{len(keep)} kept\n")
    print(f"{'dest':<6} {'ch':<4} {'chapter':<38} {'items':>5}  question numbers")
    print("-" * 90)
    total = 0
    for dest_grade, order in sorted(by_dest):
        ch = chapters[dest_grade][order]
        rows = by_dest[(dest_grade, order)]
        cross = dest_grade != grade
        out_dir = LOAD / (f"c{grade}" if not cross else f"c{grade}_to_c{dest_grade}")
        (out_dir / f"ch{order:02d}.json").write_text(json.dumps(
            {"chapter": order, "chapter_id": ch["chapter_id"],
             "extraction_id": None, "source": draft["source"],
             "source_url": SOURCE_URL, "source_grade": grade,
             "target_grade": dest_grade, "standard_id": STANDARD[dest_grade],
             "cross_grade": cross, "items": rows},
            indent=1, ensure_ascii=False), encoding="utf-8")
        nums = " ".join(r["number"].rsplit("-", 1)[1] for r in rows)
        label = f"C{dest_grade}" + ("*" if cross else "")
        print(f"{label:<6} {order:<4} {ch['chapter_name']:<38} {len(rows):>5}  {nums}")
        total += len(rows)
    print("-" * 90)
    print(f"{'':<6} {'':<4} {'':<38} {total:>5}  * = cross-grade, NEP moved the topic")

    if a.verbose:
        print("\nWHY EACH KEPT ITEM IS WHERE IT IS")
        for number, (dest, why) in sorted(keep.items()):
            g, c = dest if isinstance(dest, tuple) else (grade, dest)
            where = f"C{g} ch{c}" + ("*" if g != grade else "")
            print(f"  Q{number:<3} -> {where:<9} {why}")
        print("\nCOMPETENCIES WITH NO CHAPTER")
        codes = {i["competency"] for i in draft["items"]}
        for code in sorted(codes):
            order, why = COMPETENCY[code]
            if order is None:
                n = sum(1 for i in draft["items"] if i["competency"] == code)
                print(f"  {code} ({n} items): {why}")
        print("\nITEMS DROPPED from a competency that DOES have a chapter")
        for i in draft["items"]:
            order, _ = COMPETENCY[i["competency"]]
            if order is not None and i["number"] not in keep:
                why = ("no options parsed" if not i["options"] else
                       "options are pictures" if all(len(o["text"]) <= 1 for o in i["options"])
                       else "needs its figure, or its maths did not survive the text layer")
                print(f"  Q{i['number']:<3} {i['competency']}: {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
