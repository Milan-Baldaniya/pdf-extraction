"""Load hand-read Class 10 Science items from scripts/nodia_items/*.json.

    python -m scripts.load_nodia_items --dry       # validate, write nothing
    python -m scripts.load_nodia_items --only 6    # one chapter
    python -m scripts.load_nodia_items --only 6 --apply
    python -m scripts.load_nodia_items --apply     # everything present

The NODIA sibling of load_kvs_items. It is a separate script rather than a flag
on that one for two reasons that both matter:

  publisher   load_kvs_items hardcodes "kvs_ro_agra". Attributing a NODIA book
              to KVS is a licensing error, not a cosmetic one - the publisher
              row drives the attribution stamped on every question.
  provider    it also hardcodes tag_extraction(provider="auto"), which tries
              DeepSeek first. That account is at a negative balance and
              unavailable, so "auto" buys one failed network call per chapter
              before falling back. "offline" asks for the lexical matcher up
              front, making the degradation a decision rather than an accident.

Writing is opt-in: without --apply this validates and reports only, because a
mistake here lands in the live question bank. --replace is on, so re-running a
chapter after fixing its JSON updates rather than duplicates.

Each file is {"chapter": N, "extraction_id": E, "items": [...]}; `chapter` is
for --only and display, `extraction_id` is what actually addresses the row.
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

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402
from app.services.question_ai_tagger import tag_extraction  # noqa: E402
from app.services.supplied_items import persist_supplied  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

ITEM_DIR = Path(__file__).resolve().parent / "nodia_items"
PUBLISHER = "nodia"


def apply_read_concepts(chapter: dict) -> dict[str, int]:
    """Set concept_id from the `concept` name recorded while reading each item.

    The offline tagger is a keyword matcher and it shows: on chapter 6 it filed
    "Iodine is necessary for the synthesis of which hormone?", "The hormone which
    increases the fertility in males" and "Abscisic acid is a stress hormone" all
    under "Adrenaline Hormone", because that concept's name contains the word
    "Hormone". Three wrong out of twenty, and sixteen more left untagged.

    A wrong concept is worse than none - it routes a learner to the wrong
    remediation - so where the item file names a concept, that reading wins. The
    tagger still runs first and fills in anything not named here.

    Matching is by exact name within the item's own chapter, so a name can never
    pull in a concept from a different chapter. An unrecognised name raises
    rather than being skipped: a typo must not silently leave the keyword guess
    in place.
    """
    items = chapter.get("items") or []
    named = [(i.get("number"), i["concept"]) for i in items if i.get("concept")]
    if not named:
        return {"set": 0, "named": 0}

    if not init_mariadb() or SessionLocal is None:
        raise RuntimeError("Database not ready")
    db = SessionLocal()
    try:
        chapter_id = chapter["chapter_id"]
        by_name = {
            row[1].strip().lower(): int(row[0])
            for row in db.execute(
                text(
                    "SELECT id, name FROM lms_concept WHERE chapter_id = :c "
                    "  AND (concept_show_hide IS NULL OR concept_show_hide <> 0)"
                ),
                {"c": chapter_id},
            ).fetchall()
        }
        unknown = sorted({n for _, n in named if n.strip().lower() not in by_name})
        if unknown:
            raise ValueError(
                f"chapter {chapter.get('chapter')}: concept name(s) not in chapter "
                f"{chapter_id}: {unknown}"
            )

        # Questions are addressed through the extraction sidecar, which carries
        # the item number this file used - the question id is assigned by the
        # writer and is not knowable here.
        done = 0
        for number, concept_name in named:
            result = db.execute(
                text(
                    "UPDATE lms_question_master q "
                    "  JOIN lms_question_extraction x ON x.question_id = q.id "
                    "   SET q.concept_id = :cid "
                    " WHERE x.extraction_id = :e AND x.item_number = :num "
                    "   AND q.chapter_id = :c"
                ),
                {"cid": by_name[concept_name.strip().lower()],
                 "e": chapter["extraction_id"], "num": str(number), "c": chapter_id},
            )
            done += result.rowcount or 0
        db.commit()
        return {"set": done, "named": len(named)}
    finally:
        db.close()


def load(only: set[int] | None) -> list[dict]:
    chapters: list[dict] = []
    for path in sorted(ITEM_DIR.glob("ch*.json")):
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        data["_file"] = path.name
        if only is None or data.get("chapter") in only:
            chapters.append(data)
    return chapters


def _sanity(chapter: dict) -> list[str]:
    """Cheap structural checks before the real validator sees the file.

    These catch the mistakes that are mine rather than the book's - a typo in
    the JSON - and they are worth catching here because validate_items reports
    per item ordinal, which is hard to map back to a hand-written file.
    """
    problems: list[str] = []
    seen_numbers: set[str] = set()
    for index, item in enumerate(chapter.get("items") or [], start=1):
        where = f"item #{index} (number {item.get('number')!r})"
        if not (item.get("stem") or "").strip():
            problems.append(f"{where}: empty stem")
        number = str(item.get("number") or "")
        if number and number in seen_numbers:
            problems.append(f"{where}: duplicate question number")
        seen_numbers.add(number)

        options = item.get("options") or []
        labels = [str(o.get("label", "")).upper() for o in options]
        if len(set(labels)) != len(labels):
            problems.append(f"{where}: duplicate option labels {labels}")
        key = (item.get("correct_option") or "").upper()
        if key and labels and key not in labels:
            problems.append(f"{where}: key {key!r} is not among {labels}")
        if item.get("figure_required") and not item.get("images"):
            problems.append(f"{where}: figure_required with no images (V-07 will hold it)")
        for option in options:
            if len(str(option.get("text") or "")) > 250:
                problems.append(f"{where}: option {option.get('label')} over 250 chars (V-11)")
    return problems


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry", action="store_true",
                        help="validate and report, write nothing (the default)")
    parser.add_argument("--apply", action="store_true", help="actually write")
    parser.add_argument("--only", help="comma-separated chapter numbers")
    parser.add_argument("--no-tag", action="store_true", help="skip concept tagging")
    args = parser.parse_args()

    only = {int(x) for x in args.only.split(",") if x.strip()} if args.only else None
    chapters = load(only)
    if not chapters:
        print(f"No item files in {ITEM_DIR}" + (f" for chapter(s) {sorted(only)}" if only else ""))
        return 1

    dry = not args.apply

    header = (f"{'Ch':<3} {'row':<5} {'items':>5} {'marks':>5} {'held':>5} "
              f"{'opts':>5} {'figs':>5} {'tagged':>7} {'conc':>5}  sections")
    print(f"publisher={PUBLISHER}  mode={'DRY RUN' if dry else 'WRITE'}\n")
    print(header)
    print("-" * len(header))
    totals: Counter = Counter()

    for chapter in chapters:
        problems = _sanity(chapter)
        if problems:
            print(f"{chapter.get('chapter'):<3} {chapter['_file']}: "
                  f"{len(problems)} structural problem(s), skipped")
            for p in problems[:10]:
                print(f"    - {p}")
            continue

        try:
            result = persist_supplied(
                chapter["extraction_id"],
                chapter["items"],
                created_by=1,
                replace=True,
                publish_clean=True,
                dry_run=dry,
                publisher_code=PUBLISHER,
            )
        except Exception as exc:
            print(f"{chapter.get('chapter'):<3} FAILED: {type(exc).__name__}: {str(exc)[:80]}")
            continue

        tags = {"tagged": 0, "with_concept": 0}
        read_concepts = {"set": 0, "named": 0}
        if not dry and not args.no_tag:
            try:
                tags = await tag_extraction(chapter["extraction_id"], provider="offline")
            except Exception as exc:
                print(f"    tagging failed: {type(exc).__name__}: {str(exc)[:70]}")
            # After the tagger, so a concept read off the page overrides its guess.
            try:
                read_concepts = apply_read_concepts(chapter)
                if read_concepts["named"]:
                    print(f"    concepts read from the page: {read_concepts['set']}"
                          f"/{read_concepts['named']} applied")
            except Exception as exc:
                print(f"    concept assignment FAILED: {type(exc).__name__}: {exc}")

        sections = " ".join(f"{k}{v}" for k, v in sorted(result["sections"].items()))
        print(
            f"{chapter.get('chapter'):<3} {chapter['extraction_id']:<5} {result['parsed']:>5} "
            f"{result['total_marks']:>5} {result['validation']['failed']:>5} "
            f"{result.get('options', 0):>5} {result.get('assets', 0):>5} "
            f"{tags.get('tagged', 0):>7} {tags.get('with_concept', 0):>5}  {sections}"
        )
        if result["validation"]["by_code"]:
            print(f"    validators: {result['validation']['by_code']}")

        totals["items"] += result["parsed"]
        totals["marks"] += result["total_marks"]
        totals["held"] += result["validation"]["failed"]
        totals["options"] += result.get("options", 0)
        totals["figures"] += result.get("assets", 0)
        totals["tagged"] += tags.get("tagged", 0)
        totals["concepts"] += tags.get("with_concept", 0)

    print("-" * len(header))
    print(f"TOTAL items={totals['items']} marks={totals['marks']} held={totals['held']} "
          f"options={totals['options']} figures={totals['figures']} "
          f"tagged={totals['tagged']} concepts={totals['concepts']}")
    if dry:
        print("\nDRY RUN - nothing written. Re-run with --apply to store.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))