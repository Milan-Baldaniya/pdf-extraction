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

from app.services.concept_mcq_program import LADDER, write_mcqs  # noqa: E402

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

    print(f"\n{path.name}  chapter={doc.get('chapter_id')}"
          f"{'  (DRY RUN)' if dry else ''}")
    header = (f"  {'concept':<10}{'items':>6}{'written':>8}{'dup':>5}{'rej':>5}   "
              + "".join(f"{lv[:4]:>7}" for lv in LEVELS))
    print(header)
    print("  " + "-" * (len(header) - 2))

    for concept_id, items in concepts.items():
        if not items:
            continue
        result = write_mcqs(
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

        cells = "".join(f"{result['by_difficulty'].get(lv, 0):>7}" for lv in LEVELS)
        print(f"  {concept_id:<10}{len(items):>6}{result['written']:>8}"
              f"{result['duplicate']:>5}{result['rejected']:>5}   {cells}")

    print("  " + "-" * (len(header) - 2))
    print(f"  {'TOTAL':<10}{'':>6}{totals['written']:>8}"
          f"{totals['duplicate']:>5}{totals['rejected']:>5}"
          f"   over {totals['concepts']} concept(s)")

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