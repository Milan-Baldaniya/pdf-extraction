"""Run MinerU over the split KVS chapter PDFs, unattended.

The UI uploads one chapter at a time, which is right for a person and wrong for
a book: the eight Class 9 Maths chapters are ~130 pages and MinerU runs at
roughly 30 s/page on CPU. This drives the SAME code path the API uses
(`_run_extraction_job` -> `extract_pdf` -> `persist_extraction_result`) so there
is no second extraction implementation to keep in step -- it only replaces the
HTTP layer and the human clicking Proceed.

Chapter -> PDF mapping comes from each file's own page range, checked against
`chapter_master.sort_order` rather than assumed from it.

    python -m scripts.ingest_kvs_chapters --list
    python -m scripts.ingest_kvs_chapters --only 3,4
    python -m scripts.ingest_kvs_chapters            # every pending chapter
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.api.routes import _run_extraction_job  # noqa: E402
from app.db.mariadb import (  # noqa: E402
    SessionLocal,
    create_extraction_stub,
    persist_extraction_result,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ingest")

PDF_DIR = Path(r"C:\Users\MILAN\Downloads\ilovepdf_split-range")
BOARD = "CBSE"
STANDARD = 9
SUBJECT = "Mathematics"
SYEAR = 2026
# 1 = CBSE. Passed explicitly rather than left to board-string matching,
# because it decides which tenant's chapters the question bank binds to.
TENANT = 1
# The routes derive this from the live request; headless we have to state it.
# It must match what the API produces or chapter 2's images and these would be
# served from different hosts. Chapter 2 stored 127.0.0.1:8000.
ASSET_BASE = "http://127.0.0.1:8000/api/assets"

# The page range in each filename, in chapter order. Confirmed by reading the
# first page of every PDF: "CHAPTER-1 / Orienting Yourself...", etc.
CHAPTER_BY_RANGE = {
    "4-13": 1,
    "14-27": 2,
    "28-42": 3,
    "43-57": 4,
    "58-76": 5,
    "77-90": 6,
    "91-109": 7,
    "110-136": 8,
}

_RANGE_RE = re.compile(r"-(\d+-\d+)\.pdf$", re.IGNORECASE)


def discover() -> list[tuple[int, Path]]:
    """(chapter_number, pdf) pairs, in chapter order."""
    found: list[tuple[int, Path]] = []
    for pdf in PDF_DIR.glob("*.pdf"):
        match = _RANGE_RE.search(pdf.name)
        if not match:
            logger.warning("Skipping %s: no page range in the name", pdf.name)
            continue
        chapter = CHAPTER_BY_RANGE.get(match.group(1))
        if chapter is None:
            logger.warning(
                "Skipping %s: page range %s is not a known chapter", pdf.name, match.group(1)
            )
            continue
        found.append((chapter, pdf))
    return sorted(found)


def chapter_titles() -> dict[int, tuple[int, str]]:
    """sort_order -> (chapter_id, name) for Class 9 Maths at the CBSE tenant."""
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT sort_order, id, chapter_name
                  FROM chapter_master
                 WHERE sub_institute_id = 1 AND standard_id = 42 AND subject_id = 3976
                 ORDER BY sort_order
                """
            )
        ).fetchall()
        return {int(r[0]): (int(r[1]), str(r[2]).strip()) for r in rows}
    finally:
        db.close()


def existing() -> dict[int, dict]:
    """chapter_number -> the question_bank extraction already recorded for it."""
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT id, chapter_number, extraction_status,
                       COALESCE(CHAR_LENGTH(md_content), 0) AS md_len
                  FROM document_extractions
                 WHERE document_type = 'question_bank' AND standard = :std
                """
            ),
            {"std": STANDARD},
        ).mappings().fetchall()
        return {int(r["chapter_number"]): dict(r) for r in rows if r["chapter_number"] is not None}
    finally:
        db.close()


def drop_stale(extraction_id: int) -> None:
    """Remove a run that died before writing any markdown.

    A row left at 'extracting' with no content and no process behind it reads
    as in-flight forever. Deleting rather than failing it keeps one row per
    chapter -- there is nothing in it worth keeping, and create_extraction_stub
    does not dedupe, so leaving it would strand a permanent empty duplicate.
    """
    db = SessionLocal()
    try:
        db.execute(
            text(
                "DELETE FROM document_extractions "
                "WHERE id = :i AND (md_content IS NULL OR md_content = '')"
            ),
            {"i": extraction_id},
        )
        db.commit()
        logger.info("Dropped orphaned empty extraction %s", extraction_id)
    finally:
        db.close()


def mark_failed(extraction_id: int | None, error: str) -> None:
    """Leave the lifecycle column honest when a run dies.

    Mirrors routes._mark_extraction_failed, which is private to that module.
    Without it the stub keeps the 'extracting' stamped at job start and the
    question-bank queue offers a dead row to an operator as ready to process.
    """
    if extraction_id is None:
        return
    db = SessionLocal()
    try:
        db.execute(
            text(
                "UPDATE document_extractions "
                "SET extraction_status = 'failed', extraction_metadata = :m WHERE id = :i"
            ),
            {"i": extraction_id, "m": f'{{"error": {error[:400]!r}}}'},
        )
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


async def ingest(chapter: int, pdf: Path, title: str) -> dict:
    """One chapter: stub row -> MinerU -> persisted extraction."""
    job_id = f"kvs-ch{chapter}-{uuid.uuid4().hex[:8]}"
    started = time.perf_counter()

    meta = dict(
        document_type="question_bank",
        document_title=title,
        chapter_number=chapter,
        standard=STANDARD,
        subject_name=SUBJECT,
        board=BOARD,
        syear=SYEAR,
        sub_institute_id=TENANT,
    )

    # The stub exists before MinerU runs so a crash leaves a visible failed row
    # rather than nothing at all. For a question bank the chapter must already
    # exist; create_extraction_stub raises ChapterNotFoundError otherwise.
    cache_id = create_extraction_stub(pdf_url=str(pdf), **meta)
    if cache_id is None:
        # It swallows non-ChapterNotFoundError failures and returns None. Going
        # on would make persist_extraction_result insert a second, orphan row.
        raise RuntimeError("create_extraction_stub returned None (database unreachable?)")
    logger.info("Ch%-2s %-46s -> extraction %s", chapter, title[:46], cache_id)

    try:
        response = await _run_extraction_job(
            job_id=job_id,
            pdf_path=pdf,
            asset_base_url=f"{ASSET_BASE}/{job_id}",
            start_time=started,
            cache_message=f"Checking cache for chapter {chapter}",
            extraction_message=f"Extracting chapter {chapter} with MinerU",
        )
    except Exception as exc:
        mark_failed(cache_id, str(exc))
        raise

    cache_id = persist_extraction_result(cache_id, response, pdf_url=str(pdf), **meta)
    elapsed = time.perf_counter() - started

    return {
        "chapter": chapter,
        "extraction_id": cache_id,
        "seconds": round(elapsed, 1),
        "markdown": len(response.markdown_content or ""),
        "pages": response.page_count,
        "images": response.images_extracted,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="comma-separated chapter numbers, e.g. 3,4,5")
    parser.add_argument("--list", action="store_true", help="show what would run, then exit")
    parser.add_argument("--force", action="store_true", help="re-extract chapters already done")
    args = parser.parse_args()

    titles = chapter_titles()
    done = existing()
    wanted = (
        {int(x) for x in args.only.split(",") if x.strip()}
        if args.only
        else set(CHAPTER_BY_RANGE.values())
    )

    queue: list[tuple[int, Path, str]] = []
    for chapter, pdf in discover():
        if chapter not in wanted:
            continue
        if chapter not in titles:
            logger.error("Ch%s has no chapter_master row; skipping", chapter)
            continue

        title = titles[chapter][1]
        record = done.get(chapter)
        if record and record["md_len"] > 0 and not args.force:
            logger.info(
                "Ch%-2s already extracted (id %s, %s chars) - skipping",
                chapter, record["id"], record["md_len"],
            )
            continue
        if record and record["md_len"] == 0:
            drop_stale(int(record["id"]))

        queue.append((chapter, pdf, title))

    if args.list or not queue:
        for chapter, pdf, title in queue:
            logger.info("PENDING Ch%-2s %-46s %s", chapter, title[:46], pdf.name)
        logger.info("%d chapter(s) pending", len(queue))
        return 0

    logger.info("Extracting %d chapter(s). CPU-bound; expect roughly 30s per page.", len(queue))
    results: list[dict] = []
    failures: list[tuple[int, str]] = []
    for chapter, pdf, title in queue:
        try:
            results.append(await ingest(chapter, pdf, title))
            last = results[-1]
            logger.info(
                "Ch%-2s DONE in %ss | %s md chars | %s pages | %s images",
                chapter, last["seconds"], last["markdown"], last["pages"], last["images"],
            )
        except Exception as exc:  # one bad chapter must not lose the batch
            logger.exception("Ch%s FAILED: %s", chapter, exc)
            failures.append((chapter, str(exc)))

    logger.info("=" * 62)
    for r in results:
        logger.info(
            "Ch%-2s extraction %-5s %6ss  %7s chars  %2s pages  %2s images",
            r["chapter"], r["extraction_id"], r["seconds"],
            r["markdown"], r["pages"], r["images"],
        )
    for chapter, err in failures:
        logger.error("Ch%-2s FAILED  %s", chapter, err[:120])
    logger.info("%d succeeded, %d failed", len(results), len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
