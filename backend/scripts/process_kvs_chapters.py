"""Parse, persist and tag the extracted KVS chapters.

Runs after `ingest_kvs_chapters.py`. Two modes:

    --dry     parse and validate every chapter, write nothing, print a report.
              This is the gate: iterate on the parser here, it costs nothing.
    (default) persist, then tag concepts/Bloom/DOK.

Tagging deliberately follows persistence. A re-run with --replace carries
existing tags across by verbatim_sha256, but a first run has none to carry, so
the order matters.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal  # noqa: E402
from app.services.exam_question_service import process_exam_questions  # noqa: E402
from app.services.question_ai_tagger import tag_extraction  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger("process")

PUBLISHER = "kvs_ro_agra"
# The check that caught the chapter 2 leak: a question must never carry its
# own worked solution, or a student reading the bank reads the answer.
_SOLUTION_RE = re.compile(r"Sol(?:ution)?s?\s*\.?\s*[:\-]", re.IGNORECASE)


def extractions() -> list[dict]:
    """Every extracted Class 9 Maths question bank, in chapter order."""
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT id, chapter_number, chapter_id, document_tittle AS title,
                       COALESCE(CHAR_LENGTH(md_content), 0) AS md_len
                  FROM document_extractions
                 WHERE document_type = 'question_bank' AND standard = 9
                   AND md_content IS NOT NULL AND md_content <> ''
                 ORDER BY chapter_number
                """
            )
        ).mappings().fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def dry(records: list[dict]) -> None:
    header = (
        f"{'Ch':<3} {'id':<5} {'items':>5} {'marks':>5} {'ans':>5} "
        f"{'held':>5}  {'sections':<26} forms"
    )
    print(header)
    print("-" * len(header))

    totals = Counter()
    for record in records:
        try:
            result = process_exam_questions(
                record["id"], created_by=1, replace=False, publish_clean=True,
                dry_run=True, publisher_code=PUBLISHER,
            )
        except Exception as exc:
            print(f"{record['chapter_number']:<3} {record['id']:<5} FAILED: {str(exc)[:70]}")
            continue

        preview = result["preview"]
        answered = sum(1 for i in preview if i["answer_text"] or i["options"])
        failed = result["validation"]["failed"]
        leaked = sum(1 for i in preview if _SOLUTION_RE.search(i["stem"] or ""))
        forms = Counter(i["item_form"] for i in preview)

        totals["items"] += len(preview)
        totals["marks"] += result["total_marks"]
        totals["answered"] += answered
        totals["held"] += failed
        totals["leaked"] += leaked

        sections = " ".join(f"{k}{v}" for k, v in sorted(result["sections"].items()))
        print(
            f"{record['chapter_number']:<3} {record['id']:<5} {len(preview):>5} "
            f"{result['total_marks']:>5} {answered:>5} {failed:>5}  "
            f"{sections:<26} {dict(forms)}"
        )
        if leaked:
            print(f"    !! {leaked} stem(s) still contain a solution marker")
        by_code = result["validation"]["by_code"]
        if by_code:
            print(f"    validators: {by_code}")

    print("-" * len(header))
    print(
        f"TOTAL items={totals['items']} marks={totals['marks']} "
        f"answered={totals['answered']} held={totals['held']} leaked={totals['leaked']}"
    )


async def persist(records: list[dict], replace: bool) -> None:
    header = f"{'Ch':<3} {'id':<5} {'ins':>5} {'pub':>5} {'held':>5} {'opts':>5} {'tagged':>7} {'concepts':>9}"
    print(header)
    print("-" * len(header))

    totals = Counter()
    for record in records:
        try:
            result = process_exam_questions(
                record["id"], created_by=1, replace=replace, publish_clean=True,
                dry_run=False, publisher_code=PUBLISHER,
            )
        except Exception as exc:
            print(f"{record['chapter_number']:<3} {record['id']:<5} WRITE FAILED: {str(exc)[:60]}")
            continue

        try:
            tags = await tag_extraction(record["id"], provider="auto")
        except Exception as exc:
            logger.warning("Ch%s tagging failed: %s", record["chapter_number"], exc)
            tags = {"tagged": 0, "with_concept": 0}

        for key, source in (
            ("inserted", result), ("published", result), ("held", result), ("options", result),
        ):
            totals[key] += source.get(key, 0) or 0
        totals["tagged"] += tags.get("tagged", 0)
        totals["concepts"] += tags.get("with_concept", 0)

        print(
            f"{record['chapter_number']:<3} {record['id']:<5} {result['inserted']:>5} "
            f"{result.get('published', 0):>5} {result.get('held', 0):>5} "
            f"{result.get('options', 0):>5} {tags.get('tagged', 0):>7} "
            f"{tags.get('with_concept', 0):>9}"
        )

    print("-" * len(header))
    print(
        f"TOTAL inserted={totals['inserted']} published={totals['published']} "
        f"held={totals['held']} options={totals['options']} "
        f"tagged={totals['tagged']} concepts={totals['concepts']}"
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry", action="store_true", help="parse and report, write nothing")
    parser.add_argument("--replace", action="store_true", help="replace rows from a previous run")
    parser.add_argument("--only", help="comma-separated chapter numbers")
    args = parser.parse_args()

    records = extractions()
    if args.only:
        wanted = {int(x) for x in args.only.split(",") if x.strip()}
        records = [r for r in records if r["chapter_number"] in wanted]

    if not records:
        print("Nothing extracted yet.")
        return 1

    if args.dry:
        dry(records)
    else:
        await persist(records, args.replace)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
