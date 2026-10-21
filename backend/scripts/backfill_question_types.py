"""Give stored questions a real catalog form, marks, Bloom, DOK and difficulty.

    python -m scripts.backfill_question_types --chapters 1012-1024 --dry
    python -m scripts.backfill_question_types --chapters 1012-1024
    python -m scripts.backfill_question_types --subject 3976          # Class 9 Maths
    python -m scripts.backfill_question_types --chapters 1012 --sample 25

`--sample` classifies without writing and prints stem -> form, which is the
only honest way to judge a classifier: read what it did to real questions.

Requires sql/006_question_generated_type.sql.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402
from app.services.question_type_backfill import (  # noqa: E402
    backfill,
    classify_form,
    _strip,
)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

# These stems carry OCR debris that cp1252 cannot encode, and a report that
# crashes on the 20th row is a report no one can read.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def parse_chapters(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return sorted(set(out))


def chapters_of_subject(subject_id: int) -> list[int]:
    db = SessionLocal()
    try:
        return [
            int(r[0])
            for r in db.execute(
                text("SELECT id FROM chapter_master WHERE subject_id = :s ORDER BY id"),
                {"s": subject_id},
            ).fetchall()
        ]
    finally:
        db.close()


def sample(chapter_ids: list[int], n: int) -> int:
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT q.id, q.question_title, qt.question_type,
                       (SELECT COUNT(*) FROM answer_master a
                         WHERE a.question_id = q.id) AS option_count
                  FROM lms_question_master q
                  JOIN question_type_master qt ON qt.id = q.question_type_id
                 WHERE q.chapter_id IN :ids AND q.deleted_at IS NULL
                 ORDER BY RAND() LIMIT :n
                """
            ),
            {"ids": tuple(chapter_ids), "n": n},
        ).mappings().fetchall()
    finally:
        db.close()

    for r in rows:
        form = classify_form(
            r["question_title"],
            is_mcq=r["question_type"] == "multiple",
            has_options=bool(r["option_count"]),
        )
        print(f"  {form:<18}{r['id']:<8}{_strip(r['question_title'])[:96]}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chapters", help="ids, e.g. 1012-1024 or 1012,1013")
    parser.add_argument("--subject", type=int, help="all chapters of a subject id")
    parser.add_argument("--dry", action="store_true", help="classify, write nothing")
    parser.add_argument("--sample", type=int, help="print N classified stems and exit")
    parser.add_argument("--all", action="store_true",
                        help="re-type rows that already have g_qtype_code")
    parser.add_argument("--keep-marks", action="store_true",
                        help="leave points alone (for banks a human has curated)")
    args = parser.parse_args()

    if not init_mariadb():
        print("Database not ready")
        return 1

    ids: list[int] = []
    if args.chapters:
        ids = parse_chapters(args.chapters)
    if args.subject:
        ids.extend(chapters_of_subject(args.subject))
    ids = sorted(set(ids))
    if not ids:
        parser.error("give --chapters or --subject")

    if args.sample:
        return sample(ids, args.sample)

    result = backfill(
        ids,
        only_untyped=not args.all,
        keep_marks=args.keep_marks,
        dry_run=args.dry,
    )
    print(f"chapters={len(ids)}  seen={result['seen']}  written={result['written']}"
          f"  form_from_sidecar={result['from_sidecar']}"
          f"{'  (DRY RUN)' if args.dry else ''}")
    if result["forms"]:
        print("\n  form                    n")
        print("  " + "-" * 26)
        for form, n in sorted(result["forms"].items(), key=lambda kv: -kv[1]):
            print(f"  {form:<22}{n:>5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
