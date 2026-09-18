"""Parse the extracted Class 10 Science question banks into the question tables.

    python -m scripts.process_sci10_qbank --status
    python -m scripts.process_sci10_qbank --chapter 6 --dry
    python -m scripts.process_sci10_qbank --chapter 6 --apply
    python -m scripts.process_sci10_qbank --all --apply

Stage two. Stage one (`scripts.extract_sci10_qbank`) put MinerU's markdown and
image manifest on a document_extractions row; this turns those into
lms_question_master, answer_master, lms_question_extraction and
lms_question_asset, then tags each item with a concept, Bloom level and DOK.

Both model-backed stages are forced OFFLINE. The DeepSeek account reads
is_available:false at a -0.08 balance, so "auto" would attempt a call, fail, and
fall back anyway - once per chapter, slowly, and with an alarming log line.
Asking for offline up front makes the degradation a decision rather than an
accident:

  split_provider="offline"   structural question/answer splitting
  provider="offline"         lexical concept matching, confidence capped

The offline tagger is a keyword matcher, not comprehension. It only assigns a
concept above a 0.25 overlap score and records itself as 'offline-lexical-v1',
which is what keeps an unreviewed guess distinguishable from a model's judgement
later. This is the same path the Class 9 Maths bank went through.

--replace clears an extraction's previous rows first, so re-running after a
parser fix does not leave orphans behind.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402
from app.services.exam_question_service import process_exam_questions  # noqa: E402
from app.services.question_ai_tagger import tag_extraction  # noqa: E402
from scripts.extract_sci10_qbank import CHAPTERS, STANDARD_ID, SUBJECT_ID  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PUBLISHER_CODE = "nodia"
PUBLISHER_NAME = "NODIA Press"
ATTRIBUTION = "NODIA Science Question Bank 2026, Class 10 (CBSE)"


def _session():
    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    return SessionLocal()


def extraction_for(db, chapter_id: int) -> tuple[int, int] | None:
    row = db.execute(
        text(
            "SELECT id, COALESCE(LENGTH(md_content), 0) FROM document_extractions "
            " WHERE document_type = 'question_bank' AND chapter_id = :c "
            "   AND standard_id = :s AND subject_id = :su "
            "   AND extraction_status = 'extracted' "
            " ORDER BY id DESC LIMIT 1"
        ),
        {"c": chapter_id, "s": STANDARD_ID, "su": SUBJECT_ID},
    ).fetchone()
    return (int(row[0]), int(row[1])) if row else None


def question_counts(db, chapter_id: int) -> tuple[int, int, int]:
    row = db.execute(
        text(
            "SELECT COUNT(*), "
            "       SUM(concept_id IS NOT NULL AND concept_id <> 0), "
            "       SUM(answer IS NOT NULL AND answer <> '') "
            "  FROM lms_question_master "
            " WHERE chapter_id = :c AND category = 'textbook_exercise' "
            "   AND deleted_at IS NULL"
        ),
        {"c": chapter_id},
    ).fetchone()
    return (int(row[0] or 0), int(row[1] or 0), int(row[2] or 0))


def show_status() -> None:
    db = _session()
    try:
        print("Class 10 Science question bank - stage two status\n")
        tot_q = tot_c = 0
        for rng, (num, cid, title) in sorted(CHAPTERS.items(), key=lambda kv: kv[1][0]):
            if cid is None:
                print(f"  ch {num:<3} {title[:38]:<40} (no chapter_master row)")
                continue
            ext = extraction_for(db, cid)
            q, c, a = question_counts(db, cid)
            tot_q += q
            tot_c += c
            state = f"extraction {ext[0]} ({ext[1]:,} md chars)" if ext else "NOT EXTRACTED"
            print(f"  ch {num:<3} {title[:38]:<40} {state:<32} "
                  f"questions={q:<5} concept={c:<5} answers={a}")
        print(f"\n  total {tot_q} question(s), {tot_c} concept-mapped")
    finally:
        db.close()


def run_one(number: int, chapter_id: int, title: str, *, dry: bool,
            replace: bool, tag: bool) -> None:
    db = _session()
    try:
        ext = extraction_for(db, chapter_id)
    finally:
        db.close()
    if not ext:
        print(f"  ch {number:<3} {title[:38]:<40} NOT EXTRACTED - run stage one first")
        return

    extraction_id, md_len = ext
    print(f"  ch {number:<3} {title[:38]:<40} extraction {extraction_id} "
          f"({md_len:,} md chars)", flush=True)
    started = time.perf_counter()

    counters = process_exam_questions(
        extraction_id,
        replace=replace,
        dry_run=dry,
        split_provider="offline",
        publisher_code=PUBLISHER_CODE,
        publisher_name=PUBLISHER_NAME,
        attribution=ATTRIBUTION,
    )
    print(f"      inserted={counters.get('inserted', 0)} "
          f"options={counters.get('options', 0)} assets={counters.get('assets', 0)} "
          f"held={counters.get('held', 0)} published={counters.get('published', 0)} "
          f"dup={counters.get('skipped_duplicate', 0)} "
          f"{'[DRY RUN]' if dry else ''}")

    if dry or not tag:
        return

    report = asyncio.run(tag_extraction(extraction_id, provider="offline"))
    tagged = report.get("tagged", report.get("updated", 0))
    print(f"      tagged={tagged} via {report.get('provider', 'offline')}")

    db = _session()
    try:
        q, c, a = question_counts(db, chapter_id)
    finally:
        db.close()
    print(f"      chapter now: {q} question(s), {c} concept-mapped, {a} with answers "
          f"({(time.perf_counter()-started)/60:.1f} min)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--chapter", type=int)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--dry", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--replace", action="store_true",
                        help="clear the extraction's previous rows first")
    parser.add_argument("--no-tag", action="store_true",
                        help="skip the concept/Bloom/DOK tagging pass")
    args = parser.parse_args()

    if args.status or not (args.chapter or args.all):
        show_status()
        return 0
    if not (args.dry or args.apply):
        parser.error("choose --dry or --apply")

    by_number = {v[0]: (v[0], v[1], v[2]) for v in CHAPTERS.values()}
    if args.chapter:
        if args.chapter not in by_number:
            raise SystemExit(f"no chapter {args.chapter}")
        targets = [by_number[args.chapter]]
    else:
        targets = [v for _, v in sorted(by_number.items())]

    for number, chapter_id, title in targets:
        if chapter_id is None:
            print(f"  ch {number:<3} {title[:38]:<40} skipped - no chapter_master row")
            continue
        try:
            run_one(number, chapter_id, title, dry=args.dry,
                    replace=args.replace, tag=not args.no_tag)
        except Exception as exc:  # one bad chapter must not stop the rest
            print(f"      FAILED: {type(exc).__name__}: {exc}")
    print()
    show_status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
