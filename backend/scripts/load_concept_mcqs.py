"""Load authored per-concept MCQs from scripts/mcq_items/*.json into the bank.

    python -m scripts.load_concept_mcqs --file mcq_items/sci10_ch1012.json --dry
    python -m scripts.load_concept_mcqs --file mcq_items/sci10_ch1012.json
    python -m scripts.load_concept_mcqs --all --dry

File shape -- one file per chapter, concepts keyed by their `lms_concept.id`:

    {
      "chapter_id": 1012,
      "concepts": {
        "2723": [
          {
            "stem": "...",
            "difficulty": "Easy",           # Easy | Medium | Hard
            "bloom": "Remember",            # must match the ladder for that difficulty
            "explanation": "why the key is right",
            "options": [
              {"text": "...", "correct": true},
              {"text": "...", "why": "the misconception this reveals"},
              ...
            ]
          }
        ]
      }
    }

`dok` is not written in the file -- it is derived from the difficulty so the
two cannot disagree. Every item is validated before anything is stored; a
rejected item is reported with the reason and NOT written.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.concept_mcq_program import (  # noqa: E402
    LADDER,
    TYPE_BLUEPRINT,
    concept_index,
    write_items,
)
from app.services.concept_mcq_program import _norm_concept as _norm_name  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
ITEM_DIR = HERE / "mcq_items"
LEVELS = list(LADDER)


def load_one(path: Path, *, dry: bool, created_by: int, hold: bool) -> dict:
    with path.open(encoding="utf-8") as handle:
        doc = json.load(handle)

    concepts = doc.get("concepts") or {}
    totals = {"written": 0, "rejected": 0, "duplicate": 0, "concepts": 0}
    problems: list[dict] = []

    # Chapter-level form: a flat "items" list where each item names its concept
    # in words. Resolve the names once, here, and fail loudly on any that does
    # not match -- an unresolved concept name silently dropped is how a chapter
    # ends up with questions mapped to nothing, which is the "General" problem
    # this whole exercise exists to fix.
    flat = doc.get("items")
    chapter_level = bool(flat)
    if flat:
        # Count first. A chapter-level file aims at exactly TARGET_PER_CONCEPT
        # items, and an off-by-one is invisible in the per-form table if it
        # lands in a large bucket -- one extra very-short among eight reads as
        # nine, which is easy to miss and had already reached the database once.
        want = sum(LADDER[lv]["slots"] for lv in LADDER)
        if len(flat) != want:
            print(f"\n{path.name}: ABORTED -- file holds {len(flat)} items, "
                  f"the chapter target is {want}.")
            import collections as _c
            by_form = _c.Counter(str(i.get("form") or "mcq") for i in flat)
            for form, target in sorted(TYPE_BLUEPRINT.items(), key=lambda kv: -kv[1]):
                got = by_form.get(form, 0)
                if got != target:
                    print(f"    {form:<20}{got:>4} (want {target})")
            return {"written": 0, "rejected": len(flat), "duplicate": 0}

        chapter_id = int(doc["chapter_id"])
        index = concept_index(chapter_id)
        unknown: dict[str, int] = {}
        grouped: dict[str, list] = {}
        for item in flat:
            key = _norm_name(str(item.get("concept") or ""))
            cid = index.get(key)
            if cid is None:
                unknown[str(item.get("concept"))] = unknown.get(str(item.get("concept")), 0) + 1
                continue
            grouped.setdefault(str(cid), []).append(item)
        if unknown:
            print(f"\n{path.name}: ABORTED -- {sum(unknown.values())} item(s) name a "
                  f"concept that is not in this chapter:")
            for name, n in sorted(unknown.items(), key=lambda kv: -kv[1]):
                print(f"    x{n:<4}{name!r}")
            print("  Chapter concepts are:")
            for name in sorted(index):
                print(f"    - {name}")
            return {"written": 0, "rejected": sum(unknown.values()), "duplicate": 0}
        concepts = grouped

    print(f"\n{path.name}  chapter={doc.get('chapter_id')}"
          f"{'  (DRY RUN)' if dry else ''}")
    header = (f"  {'concept':<10}{'items':>6}{'written':>8}{'dup':>5}{'rej':>5}   "
              + "".join(f"{lv[:4]:>7}" for lv in LEVELS))
    print(header)
    print("  " + "-" * (len(header) - 2))

    forms: dict[str, int] = {}
    difficulty: dict[str, int] = {}
    for concept_id, items in concepts.items():
        if not items:
            continue
        result = write_items(
            int(concept_id), items,
            created_by=created_by,
            publish_clean=not hold,
            dry_run=dry,
        )
        totals["written"] += result["written"]
        totals["rejected"] += result["rejected"]
        totals["duplicate"] += result["duplicate"]
        totals["concepts"] += 1
        for p in result["problems"]:
            problems.append({"concept_id": concept_id, **p})
        for form, n in result.get("by_form", {}).items():
            forms[form] = forms.get(form, 0) + n
        for lv, n in result.get("by_difficulty", {}).items():
            difficulty[lv] = difficulty.get(lv, 0) + n

        cells = "".join(f"{result['by_difficulty'].get(lv, 0):>7}" for lv in LEVELS)
        print(f"  {concept_id:<10}{len(items):>6}{result['written']:>8}"
              f"{result['duplicate']:>5}{result['rejected']:>5}   {cells}")

    print("  " + "-" * (len(header) - 2))
    print(f"  {'TOTAL':<10}{'':>6}{totals['written']:>8}"
          f"{totals['duplicate']:>5}{totals['rejected']:>5}"
          f"   over {totals['concepts']} concept(s)")

    if forms:
        # A chapter-level file aims at ONE blueprint of 50 for the whole
        # chapter; a per-concept file aims at 50 for each concept in it.
        # Comparing either against the other's target is meaningless.
        scale = 1 if chapter_level else max(1, totals["concepts"])
        label = "target" if chapter_level else "target/all"
        print(f"\n  form                 got{label:>11}   diff")
        print("  " + "-" * 42)
        for form in sorted(TYPE_BLUEPRINT, key=lambda f: -TYPE_BLUEPRINT[f]):
            want = TYPE_BLUEPRINT[form] * scale
            got = forms.get(form, 0)
            mark = "" if got == want else f"{got - want:+d}"
            print(f"  {form:<20}{got:>4}{want:>11}{mark:>7}")

        # Difficulty is the other half of the brief and drifts just as easily.
        print(f"\n  difficulty           got{label:>11}   diff")
        print("  " + "-" * 42)
        for lv in LEVELS:
            want = LADDER[lv]["slots"] * scale
            got = difficulty.get(lv, 0)
            mark = "" if got == want else f"{got - want:+d}"
            print(f"  {lv:<20}{got:>4}{want:>11}{mark:>7}")

    if problems:
        print(f"\n  {len(problems)} item(s) REJECTED and not stored:")
        for p in problems[:40]:
            print(f"    concept {p['concept_id']} item {p['index']}: {p['stem']!r}")
            for reason in p["problems"]:
                print(f"       - {reason}")
        if len(problems) > 40:
            print(f"    ... and {len(problems) - 40} more")

    return totals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", help="one JSON file (relative to scripts/)")
    parser.add_argument("--all", action="store_true", help="every mcq_items/*.json")
    parser.add_argument("--dry", action="store_true", help="validate, write nothing")
    parser.add_argument("--created-by", type=int, default=1)
    parser.add_argument("--hold", action="store_true",
                        help="store held for review instead of published")
    args = parser.parse_args()

    paths: list[Path] = []
    if args.all:
        paths = sorted(ITEM_DIR.glob("*.json"))
    elif args.file:
        p = Path(args.file)
        paths = [p if p.is_absolute() else HERE / p]
    else:
        parser.error("give --file or --all")

    if not paths:
        print(f"No item files in {ITEM_DIR}")
        return 1

    grand = {"written": 0, "rejected": 0, "duplicate": 0}
    for path in paths:
        totals = load_one(path, dry=args.dry, created_by=args.created_by, hold=args.hold)
        for k in grand:
            grand[k] += totals[k]

    if len(paths) > 1:
        print(f"\n== {len(paths)} file(s): written={grand['written']} "
              f"duplicate={grand['duplicate']} rejected={grand['rejected']} ==")

    # A rejected item is authored work that did not land. Non-zero exit so a
    # scripted run cannot report success while silently dropping questions --
    # the same failure mode the tagger's empty-batch bug had.
    return 1 if grand["rejected"] else 0


if __name__ == "__main__":
    raise SystemExit(main())