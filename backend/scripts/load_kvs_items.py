"""Load hand-read chapter items from scripts/kvs_items/*.json into the bank.

    python -m scripts.load_kvs_items --dry          # validate, write nothing
    python -m scripts.load_kvs_items --only 1       # one chapter
    python -m scripts.load_kvs_items                # write and tag everything
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.question_ai_tagger import tag_extraction  # noqa: E402
from app.services.supplied_items import persist_supplied  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

ITEM_DIR = Path(__file__).resolve().parent / "kvs_items"
PUBLISHER = "kvs_ro_agra"


def load() -> list[dict]:
    chapters = []
    for path in sorted(ITEM_DIR.glob("ch*.json")):
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        data["_file"] = path.name
        chapters.append(data)
    return chapters


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry", action="store_true")
    parser.add_argument("--only", help="comma-separated chapter numbers")
    parser.add_argument("--no-tag", action="store_true", help="skip concept tagging")
    args = parser.parse_args()

    chapters = load()
    if args.only:
        wanted = {int(x) for x in args.only.split(",") if x.strip()}
        chapters = [c for c in chapters if c["chapter"] in wanted]
    if not chapters:
        print(f"No item files in {ITEM_DIR}")
        return 1

    header = f"{'Ch':<3} {'id':<5} {'items':>5} {'marks':>5} {'held':>5} {'opts':>5} {'tagged':>7} {'conc':>5}  sections"
    print(header)
    print("-" * len(header))
    totals: Counter = Counter()

    for chapter in chapters:
        try:
            result = persist_supplied(
                chapter["extraction_id"],
                chapter["items"],
                created_by=1,
                replace=True,
                publish_clean=True,
                dry_run=args.dry,
                publisher_code=PUBLISHER,
            )
        except Exception as exc:
            print(f"{chapter['chapter']:<3} FAILED: {str(exc)[:80]}")
            continue

        tags = {"tagged": 0, "with_concept": 0}
        if not args.dry and not args.no_tag:
            try:
                tags = await tag_extraction(chapter["extraction_id"], provider="auto")
            except Exception as exc:
                print(f"    tagging failed: {str(exc)[:70]}")

        sections = " ".join(f"{k}{v}" for k, v in sorted(result["sections"].items()))
        print(
            f"{chapter['chapter']:<3} {chapter['extraction_id']:<5} {result['parsed']:>5} "
            f"{result['total_marks']:>5} {result['validation']['failed']:>5} "
            f"{result.get('options', 0):>5} {tags.get('tagged', 0):>7} "
            f"{tags.get('with_concept', 0):>5}  {sections}"
        )
        if result["validation"]["by_code"]:
            print(f"    validators: {result['validation']['by_code']}")

        totals["items"] += result["parsed"]
        totals["marks"] += result["total_marks"]
        totals["held"] += result["validation"]["failed"]
        totals["options"] += result.get("options", 0)
        totals["tagged"] += tags.get("tagged", 0)
        totals["concepts"] += tags.get("with_concept", 0)

    print("-" * len(header))
    print(
        f"TOTAL items={totals['items']} marks={totals['marks']} held={totals['held']} "
        f"options={totals['options']} tagged={totals['tagged']} concepts={totals['concepts']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
