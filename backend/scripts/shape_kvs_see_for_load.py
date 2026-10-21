"""Place the KVS Lucknow SEE Class 6/7 Maths MCQs on the NEP chapters.

    python -m scripts.shape_kvs_see_for_load --grade 6
    python -m scripts.shape_kvs_see_for_load --grade 7 --verbose

Reads `scripts/kvs_see_items/drafts/c{6,7}_maths_kvs_see.json` and writes one
`chNN.json` per NEP chapter under `scripts/kvs_see_items/load/c{6,7}/`.

AN EXAM PAPER CARRIES NO CHAPTER TAG AT ALL, so unlike the CBSE SAS books there
is nothing to remap and unlike the SCERT bank there is no competency code to
lean on. Every chapter here is read off the item itself, and KEEP records the
reasoning one item at a time.

These papers matter out of proportion to their size: they are the only source of
the three that can answer Class 6 Lines and Angles, Fractions, Perimeter and Area
and Playing with Constructions, because everything CBSE wrote for those chapters
takes its numbers from a figure.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

from scripts.parse_kvs_see_maths import SOURCE_URL  # noqa: E402
from scripts.shape_c67sas_for_load import STANDARD, fold, resolve  # noqa: E402

ROOT = Path(__file__).resolve().parent / "kvs_see_items"
DRAFTS = ROOT / "drafts"
LOAD = ROOT / "load"
PUBLISHER = "kvs_ro_lucknow"
NAME = "Kendriya Vidyalaya Sangathan, Lucknow Region"

# U+2070 is a superscript zero typed as a degree sign, the same convention the
# parser repairs where the PDF marks it as a superscript span instead.
SUPER_ZERO = "⁰"

# question number -> (NEP chapter, why)
KEEP: dict[int, dict[int, tuple[int, str]]] = {
    6: {
        2:  (2,  "the shortest distance between two points is a line segment -- "
                 "ch2's Dots and Creases and Endless Lines and Rays"),
        3:  (9,  "the three lines of symmetry of an equilateral triangle"),
        7:  (9,  "a regular polygon of n sides has n lines of symmetry"),
        12: (9,  "which capital letter has a vertical line of symmetry"),
        4:  (7,  "45/60 in its lowest form -- ch7's Lowest Terms"),
        6:  (6,  "the perimeter of a regular pentagon of side 5 cm"),
        9:  (6,  "the cost of grassing a 10 m by 6 m plot at Rs 5 per square "
                 "metre -- area of a rectangle applied"),
        8:  (8,  "what a square and a rectangle have in common. ch8 builds both "
                 "with ruler and compass and needs exactly these properties"),
        10: (8,  "which instrument draws arcs and circles -- ch8 is ruler and "
                 "compass work from its first page"),
        11: (10, "how many integers lie between -2 and 2"),
    },
    7: {
        1:  (5,  "two angles summing to 180 degrees are supplementary"),
        10: (5,  "two straight lines meet in at most one point -- ch5's Across "
                 "the Line"),
        2:  (7,  "which of four sets of lengths can form a triangle -- the "
                 "triangle inequality, which is ch7's Constructing a Triangle "
                 "When its Sides are Given"),
        11: (7,  "each interior angle of an equilateral triangle"),
        3:  (9,  "AAA is not a congruence rule -- ch9's SAS, ASA and RHS "
                 "conditions"),
        6:  (9,  "which correspondence is wrong when triangle AIR is congruent "
                 "to triangle FLY"),
        5:  (4,  "evaluating 3n + 4 at n = 8 -- a letter-number expression"),
        8:  (10, "the value of (-5) x {18 + (-3)}"),
        15: (10, "which temperature change is the largest rise, over negative "
                 "and positive values"),
        12: (6,  "the parity of the sum of five odd numbers -- ch6's Picking "
                 "Parity"),
        13: (11, "the greatest common factor of 16, 24 and 18 -- ch11 is HCF "
                 "and LCM"),
        7:  (12, "0.07 x 0.006 -- ch12's Decimal Multiplication"),
        9:  (12, "1526 divided by 4 -- ch12's Division with a Decimal Quotient"),
    },
}

# TWO ITEMS THE PAPER ITSELF BROKE. Class 7 prints no marks cell for question 5,
# and the marks cell is what separates one question from the next, so question 5
# arrived empty and question 6 arrived carrying both questions and eight options.
# Both are perfectly readable on the page; they are restored here verbatim, and
# their keys -- 3(8) + 4 = 28, and IR corresponds to LY rather than FY -- were
# checked against the marking scheme.
REPAIR: dict[int, dict[int, dict]] = {
    7: {
        5: {"stem": "Value of 3n+4 for n = 8",
            "options": ["8", "16", "28", "24"]},
        6: {"stem": "If ∆AIR ≅ ∆FLY, then which of the following "
                    "is incorrect?",
            "options": ["IR=FY", "∠A= ∠F", "AR=FY", "∠R= ∠Y"]},
    },
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grade", type=int, required=True, choices=(6, 7))
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    grade = a.grade

    draft = json.loads((DRAFTS / f"c{grade}_maths_kvs_see.json").read_text(encoding="utf-8"))
    items = {i["number"]: i for i in draft["items"]}
    keep, repair = KEEP[grade], REPAIR.get(grade, {})

    missing = set(keep) - set(items)
    if missing:
        raise SystemExit(f"KEEP names items the draft does not hold: {sorted(missing)}")

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        chapters = resolve(grade, db)
    finally:
        db.close()

    by_chapter: dict[int, list[dict]] = {}
    for number, (order, _why) in sorted(keep.items()):
        it = items[number]
        fix = repair.get(number)
        stem = fix["stem"] if fix else it["stem"]
        texts = fix["options"] if fix else [o["text"] for o in it["options"]]
        if len(texts) != 4 or not all(texts) or not it["correct_option"]:
            raise SystemExit(f"Q{number}: {len(texts)} options, "
                             f"key {it['correct_option']!r} -- not loadable")
        letter = it["correct_option"].upper()
        options = [{"label": chr(ord("A") + i),
                    "text": fold(t.replace(SUPER_ZERO, "°"))}
                   for i, t in enumerate(texts)]
        answer_text = next(o["text"] for o in options if o["label"] == letter)
        by_chapter.setdefault(order, []).append({
            "number": f"KVS-LKO-{grade}-Q{number}",
            "form": "mcq",
            "stem": fold(stem.replace(SUPER_ZERO, "°")),
            "options": options,
            "correct_option": letter,
            "answer": fold(f"{letter}. {answer_text}"),
            "marks": 1,
            "reproduction": "verbatim",
        })

    out_dir = LOAD / f"c{grade}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("ch*.json"):
        old.unlink()

    print(f"Class {grade} Mathematics (standard_id={STANDARD[grade]})  "
          f"{len(draft['items'])} section-A items read, {len(keep)} kept\n")
    print(f"{'NEP ch':<7} {'chapter':<38} {'items':>5}  question numbers")
    print("-" * 86)
    total = 0
    for order in sorted(by_chapter):
        ch = chapters[order]
        rows = by_chapter[order]
        (out_dir / f"ch{order:02d}.json").write_text(json.dumps(
            {"chapter": order, "chapter_id": ch["chapter_id"],
             "extraction_id": None, "source": draft["source"],
             "source_url": SOURCE_URL, "items": rows},
            indent=1, ensure_ascii=False), encoding="utf-8")
        nums = " ".join(r["number"].rsplit("-", 1)[1] for r in rows)
        print(f"{order:<7} {ch['chapter_name']:<38} {len(rows):>5}  {nums}")
        total += len(rows)
    print("-" * 86)
    print(f"{'':<7} {'':<38} {total:>5}  in {out_dir}")

    if a.verbose:
        print("\nWHY EACH KEPT ITEM IS WHERE IT IS")
        for number, (order, why) in sorted(keep.items()):
            print(f"  Q{number:<3} -> ch{order:<3} {why}")
        print("\nSECTION-A ITEMS NOT LOADED")
        for number, it in sorted(items.items()):
            if number in keep:
                continue
            why = ("its options are stacked fractions that the text layer set "
                   "adrift from their labels" if any(not o["text"] for o in it["options"])
                   or len(it["options"]) != 4 else "no key, or nowhere it belongs")
            print(f"  Q{number:<3} {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
