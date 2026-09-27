"""Load the verified NCERT Class X HPE exercise items into the question bank.

    python -m scripts.load_ncert_hpe10_items --dry        # validate, write nothing
    python -m scripts.load_ncert_hpe10_items --only 1,2   # one or two chapters
    python -m scripts.load_ncert_hpe10_items --apply      # write
    python -m scripts.load_ncert_hpe10_items --apply --no-tag

Reads `scripts/ncert_hpe10_items/load/chNN.json`, which
`shape_ncert_hpe10_for_load` wrote and `setup_ncert_hpe10_extractions` stamped
with an `extraction_id`. Everything downstream -- validation, publishing policy,
attribution, the four-table write -- is the same code every other bank in this
estate goes through, so a derived-answer item is stored identically to a parsed
one and the ONLY thing that distinguishes it is its publisher and its
`tagged_by`. That is deliberate and it is the point: the distinction lives in
data a query can filter on, not in a file name.

`--apply` is required to write. There is no bare "just run it" mode, because
`replace=True` rewrites a chapter's items and a mistyped `--only` would be
expensive.
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

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

from app.services.question_ai_tagger import tag_extraction  # noqa: E402
from app.services.supplied_items import persist_supplied  # noqa: E402

from scripts.shape_ncert_hpe10_for_load import LOAD, PUBLISHER  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry", action="store_true")
    mode.add_argument("--apply", action="store_true")
    ap.add_argument("--only", help="comma-separated chapter numbers")
    ap.add_argument("--no-tag", action="store_true",
                    help="skip concept tagging")
    a = ap.parse_args()

    chapters = []
    for path in sorted(LOAD.glob("ch*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["_file"] = path.name
        chapters.append(data)
    if a.only:
        wanted = {int(x) for x in a.only.split(",") if x.strip()}
        chapters = [c for c in chapters if c["chapter"] in wanted]
    chapters = [c for c in chapters if c["items"]]
    if not chapters:
        print(f"No loadable chapters in {LOAD}")
        return 1

    missing = [c["chapter"] for c in chapters if not c.get("extraction_id")]
    if missing:
        print("No extraction_id on chapter(s) "
              f"{', '.join(str(m) for m in missing)} -- run "
              "setup_ncert_hpe10_extractions --apply first")
        return 1

    head = (f"{'ch':<3} {'extr':<6} {'items':>5} {'marks':>5} {'held':>5} "
            f"{'opts':>5} {'tagged':>7} {'conc':>5}  sections")
    print(head)
    print("-" * len(head))
    totals: Counter = Counter()
    attribution = None

    for chapter in chapters:
        try:
            result = persist_supplied(
                chapter["extraction_id"],
                chapter["items"],
                created_by=1,
                replace=True,
                publish_clean=True,
                dry_run=a.dry,
                publisher_code=PUBLISHER,
            )
        except Exception as exc:
            print(f"{chapter['chapter']:<3} FAILED: {str(exc)[:80]}")
            totals["failed"] += 1
            continue
        attribution = result.get("attribution") or attribution

        tags = {"tagged": 0, "with_concept": 0}
        if a.apply and not a.no_tag:
            try:
                tags = await tag_extraction(chapter["extraction_id"],
                                            provider="auto")
            except Exception as exc:
                print(f"    tagging failed: {str(exc)[:70]}")

        sections = " ".join(f"{k}{v}" for k, v in sorted(result["sections"].items()))
        print(f"{chapter['chapter']:<3} {chapter['extraction_id']:<6} "
              f"{result['parsed']:>5} {result['total_marks']:>5} "
              f"{result['validation']['failed']:>5} "
              f"{result.get('options', 0):>5} {tags.get('tagged', 0):>7} "
              f"{tags.get('with_concept', 0):>5}  {sections}")
        if result["validation"]["by_code"]:
            print(f"    validators: {result['validation']['by_code']}")

        totals["items"] += result["parsed"]
        totals["marks"] += result["total_marks"]
        totals["held"] += result["validation"]["failed"]
        totals["options"] += result.get("options", 0)
        totals["tagged"] += tags.get("tagged", 0)
        totals["concepts"] += tags.get("with_concept", 0)
        for form, count in result["question_types"].items():
            totals[f"form:{form}"] += count

    print("-" * len(head))
    print(f"TOTAL items={totals['items']} marks={totals['marks']} "
          f"held={totals['held']} options={totals['options']} "
          f"tagged={totals['tagged']} concepts={totals['concepts']} "
          f"failed_chapters={totals['failed']}")
    forms = {k[5:]: v for k, v in totals.items() if k.startswith("form:")}
    print("forms: " + " ".join(f"{k}={v}" for k, v in sorted(forms.items())))
    if attribution:
        print(f"attribution: {attribution}")
    if a.dry:
        print("\ndry run -- pass --apply to write")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
