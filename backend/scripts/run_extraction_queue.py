"""Extract every chapter in the queue sheet, unattended, all night.

The UI extracts one chapter per form submission, which is right for a person and
wrong for a syllabus: MinerU runs at roughly 30 s/page on CPU, so a subject is
hours and a class is a night. This drives the SAME code path the API uses
(`_run_extraction_job` -> `extract_pdf` -> `persist_extraction_result`), so there
is no second extraction implementation to keep in step. It replaces the HTTP
layer, the form and the person clicking Proceed -- nothing else.

Scope is deliberately narrow: PDF in, markdown row in `document_extractions`,
stop. The DeepSeek stages (curriculum, topics, concepts) are not run here. They
cost money per call and write into the live LMS tables, and neither should
happen while nobody is watching.

How a night is shaped
---------------------
Chapters run two at a time, then the next two, subject by subject. Three rules
keep that from stalling:

  * A batch that fails is retried one chapter at a time. Two MinerU processes
    are two multi-gigabyte model loads; when the second one is what broke,
    running the same chapters singly usually succeeds.
  * Repeated batch failures drop the whole run to one at a time for good. If
    this machine cannot hold two, there is no sense discovering that forty more
    times before morning.
  * A subject that fails does not stop the queue. Every failure is recorded and
    the runner moves to the next subject. The night ends when the work ends.

Nothing here is allowed to raise past one chapter. A dead PDF link, a MinerU
timeout, a database that went away at 3 a.m. -- each is recorded against its own
row and the queue continues.

    python -m scripts.run_extraction_queue --list        # what would run
    python -m scripts.run_extraction_queue               # run it
    python -m scripts.run_extraction_queue --stop-at 07:30
    python -m scripts.run_extraction_queue --only-standard 10 --only-subject Science
    python -m scripts.run_extraction_queue --sync-sheet  # replay ledger into xlsx
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import ctypes
import logging
import os
import shutil
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.api.routes import _run_extraction_job  # noqa: E402
from app.db.mariadb import (  # noqa: E402
    ChapterNotFoundError,
    SessionLocal,
    create_extraction_stub,
    init_mariadb,
    persist_extraction_result,
)
from app.extraction.cache import file_sha256  # noqa: E402
from app.services.pdf_service import PDFDownloadError, download_pdf  # noqa: E402
from app.utils.config import settings  # noqa: E402
from app.utils.file_utils import cleanup_temp_job, get_temp_pdf_path  # noqa: E402
from scripts import queue_sheet as qs  # noqa: E402

logger = logging.getLogger("queue")

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_SHEET = BACKEND / "queue" / "extraction_queue.xlsx"

# The routes derive this from the live request. Headless it has to be stated,
# and it must match what the API produces or a chapter's images would be served
# from a different host than every chapter extracted through the UI.
DEFAULT_ASSET_BASE = "http://127.0.0.1:8000/api/assets"

# A second MinerU process is a second multi-gigabyte model load. Measured on
# this machine, one chapter peaks around 4.4 GB resident, so two need close to
# 9 GB with nothing else on the box. Below this much free memory the batch runs
# one at a time rather than risking the OOM killer taking the run down at 4 a.m.
#
# On a 16 GB desktop that effectively means: two at a time only with the browser
# and the editor closed. That is the honest number -- lowering it does not buy
# speed, it buys a swap storm.
DEFAULT_MIN_FREE_GB = 9.0


# --------------------------------------------------------------------------
# environment
# --------------------------------------------------------------------------

def setup_logging(run_id: str, verbose: bool) -> Path:
    log_path = BACKEND / "logs" / f"queue_{run_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s  %(levelname)-7s %(message)s", datefmt="%H:%M:%S"
    )
    # Chapter titles out of the database carry en-dashes and curly quotes, and
    # the Windows console is cp1252. Without this, printing "Light - Reflection
    # and Refraction" raises UnicodeEncodeError inside logging and takes the
    # whole run with it.
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8", errors="replace")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console = logging.StreamHandler()
    console.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.handlers = [file_handler, console]
    # MinerU narrates every page at INFO; it belongs in the file, not the run log.
    logging.getLogger("app.services.mineru_service").setLevel(logging.WARNING)
    return log_path


class KeepAwake:
    """Stop Windows sleeping in the middle of the queue.

    Power settings are the most common reason an overnight run is half finished
    in the morning: the machine suspends, the MinerU subprocess is frozen with
    it, and the chapter times out when the box wakes up.
    """

    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    ES_AWAYMODE_REQUIRED = 0x00000040

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled and sys.platform == "win32"
        self.held = False

    def __enter__(self) -> "KeepAwake":
        if not self.enabled:
            return self
        try:
            flags = self.ES_CONTINUOUS | self.ES_SYSTEM_REQUIRED | self.ES_AWAYMODE_REQUIRED
            if ctypes.windll.kernel32.SetThreadExecutionState(flags):
                self.held = True
                logger.info("Sleep suppressed for the duration of the run")
        except Exception:
            logger.debug("Could not suppress sleep", exc_info=True)
        return self

    def __exit__(self, *exc: Any) -> None:
        if self.held:
            with contextlib.suppress(Exception):
                ctypes.windll.kernel32.SetThreadExecutionState(self.ES_CONTINUOUS)


def free_gb() -> float | None:
    """Available RAM, or None if psutil is not installed."""
    try:
        import psutil

        return psutil.virtual_memory().available / (1024**3)
    except Exception:
        return None


# --------------------------------------------------------------------------
# database helpers -- every one of these must tolerate the server going away
# --------------------------------------------------------------------------

def _existing_extraction(row: qs.QueueRow, tenant: int) -> dict | None:
    """The extraction already recorded for this chapter, if any.

    Matched the way the sheet is keyed, not by title: a title edited in the
    sheet must not cause the same chapter to be extracted a second time.

    subject_name is part of that key and cannot be dropped -- every subject in a
    class has a chapter 1, so without it Maths chapter 1 would be skipped on the
    grounds that Science chapter 1 exists.
    """
    with SessionLocal() as db:
        found = db.execute(
            text(
                """
                SELECT id, extraction_status,
                       COALESCE(CHAR_LENGTH(md_content), 0) AS md_len
                  FROM document_extractions
                 WHERE document_type = :dtype
                   AND standard = :std
                   AND chapter_number = :ch
                   AND sub_institute_id = :tenant
                   AND LOWER(TRIM(COALESCE(subject_name, ''))) = :subj
                 ORDER BY md_len DESC, id DESC
                 LIMIT 1
                """
            ),
            {
                "dtype": row.document_type,
                "std": row.standard,
                "ch": row.chapter_number,
                "tenant": tenant,
                "subj": (row.subject_name or "").strip().lower(),
            },
        ).mappings().fetchone()
    return dict(found) if found else None


def resolve_preview(rows: list[qs.QueueRow]) -> dict[str, dict[str, Any]]:
    """What foreign keys each row will actually be stored with.

    The sheet carries names -- "10", "Mathematics", "ARITHMETIC PROGRESSIONS" --
    and `_map_ids` turns those into standard_id, subject_id and chapter_id at
    insert time. A name that matches nothing is not an error: the row is stored
    with a NULL id and the extraction succeeds, so the miss is invisible until
    something downstream looks for the chapter and cannot find it.

    This runs the same three lookups up front, so a mismatch is a line in the
    plan rather than a discovery a week later.
    """
    out: dict[str, dict[str, Any]] = {}
    standards: dict[tuple[int, str], int | None] = {}
    subjects: dict[tuple[int, str], int | None] = {}

    with SessionLocal() as db:
        for row in rows:
            tenant = row.sub_institute_id or settings.tenant_for_board(row.board)

            std_key = (tenant, str(row.standard))
            if std_key not in standards:
                found = db.execute(
                    text(
                        "SELECT id FROM standard WHERE name = :n "
                        "AND sub_institute_id = :t LIMIT 1"
                    ),
                    {"n": str(row.standard), "t": tenant},
                ).fetchone()
                standards[std_key] = int(found[0]) if found else None

            sub_key = (tenant, row.subject_name.lower())
            if sub_key not in subjects:
                found = db.execute(
                    text(
                        "SELECT id FROM subject WHERE subject_name = :n "
                        "AND sub_institute_id = :t LIMIT 1"
                    ),
                    {"n": row.subject_name, "t": tenant},
                ).fetchone()
                subjects[sub_key] = int(found[0]) if found else None

            # Same match _map_ids uses: name AND sort_order, scoped to tenant.
            chapter_id = None
            if row.document_title and row.chapter_number is not None:
                found = db.execute(
                    text(
                        "SELECT id FROM chapter_master WHERE chapter_name = :c "
                        "AND sort_order = :s AND sub_institute_id = :t LIMIT 1"
                    ),
                    {"c": row.document_title, "s": row.chapter_number, "t": tenant},
                ).fetchone()
                chapter_id = int(found[0]) if found else None

            out[row.key] = {
                "tenant": tenant,
                "standard_id": standards[std_key],
                "subject_id": subjects[sub_key],
                "chapter_id": chapter_id,
            }
    return out


def _drop_stale(extraction_id: int) -> None:
    """Remove a run that died before writing any markdown.

    A row left at 'extracting' with no content and no process behind it reads as
    in-flight forever. Deleting rather than failing it keeps one row per
    chapter: create_extraction_stub does not dedupe, so leaving it would strand
    a permanent empty duplicate.
    """
    with SessionLocal() as db:
        db.execute(
            text(
                "DELETE FROM document_extractions "
                "WHERE id = :i AND (md_content IS NULL OR md_content = '')"
            ),
            {"i": extraction_id},
        )
        db.commit()
    logger.info("   dropped orphaned empty extraction %s", extraction_id)


def _mark_failed(extraction_id: int | None, error: str) -> None:
    """Leave the lifecycle column honest when a run dies.

    Mirrors routes._mark_extraction_failed, which is private to that module.
    Without it the stub keeps the 'extracting' stamped at job start, and the
    chapter queue in the UI offers a dead row to an operator as ready.
    """
    if extraction_id is None:
        return
    try:
        with SessionLocal() as db:
            db.execute(
                text(
                    "UPDATE document_extractions SET extraction_status = 'failed', "
                    "extraction_metadata = :m WHERE id = :i"
                ),
                {"i": extraction_id, "m": f'{{"error": {error[:400]!r}}}'},
            )
            db.commit()
    except Exception:
        logger.debug("Could not mark extraction %s failed", extraction_id, exc_info=True)


async def _db_call(func, *args, attempts: int = 3, **kwargs):
    """Run a blocking database call off the loop, retrying a dropped connection.

    The MariaDB server is remote. A momentary network blip is not a reason to
    lose a chapter that took forty minutes of CPU to produce.
    """
    delay = 5.0
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await asyncio.to_thread(func, *args, **kwargs)
        except ChapterNotFoundError:
            raise
        except Exception as exc:
            last = exc
            if attempt == attempts:
                break
            logger.warning(
                "   database call failed (%s/%s): %s -- retrying in %.0fs",
                attempt,
                attempts,
                str(exc)[:120],
                delay,
            )
            await asyncio.sleep(delay)
            delay *= 2
    raise last if last else RuntimeError("database call failed")


# --------------------------------------------------------------------------
# the runner
# --------------------------------------------------------------------------

class Outcome:
    DONE = "done"
    SKIPPED = "skipped"
    EXTRACTED = "extracted"  # MinerU succeeded, the database write did not
    FAILED = "failed"


class QueueRunner:
    def __init__(
        self,
        args: argparse.Namespace,
        ledger: qs.Ledger,
        writer: qs.SheetWriter,
        state: qs.RunState | None = None,
    ) -> None:
        self.args = args
        self.ledger = ledger
        self.writer = writer
        self.state = state
        self.batch_size = max(1, args.batch_size)
        self.degraded = False
        self.batch_failures = 0
        self.low_memory_batches = 0
        self.deadline = _resolve_deadline(args)
        # Latest outcome per chapter, NOT one entry per attempt. A chapter that
        # fails in a batch and succeeds on the serial retry is one chapter that
        # worked, and the morning summary has to say so -- "3 failed" must mean
        # three chapters are broken, not three attempts were made.
        self.outcomes: dict[str, str] = {}
        self.counts: dict[str, int] = {}
        self.total_planned = 0
        self.current_subject = ""
        # Chapters in flight, by key. The live view reads this to say what the
        # machine is chewing on right now, which is the one thing the log
        # cannot show without being tailed.
        self.in_flight: dict[str, dict[str, Any]] = {}
        self.stopped_by_user = False

    # -- bookkeeping ------------------------------------------------------

    def _publish(self, **extra: Any) -> None:
        if self.state is None:
            return
        finished = sum(self.counts.values())
        self.state.publish(
            counts=dict(self.counts),
            finished=finished,
            total=self.total_planned,
            remaining=max(0, self.total_planned - finished),
            current_subject=self.current_subject,
            current=list(self.in_flight.values()),
            degraded=self.degraded,
            batch_failures=self.batch_failures,
            low_memory_batches=self.low_memory_batches,
            free_gb=round(free_gb() or 0.0, 1),
            **extra,
        )

    def _record(self, row: qs.QueueRow, status: str, error: str = "") -> None:
        row.status = status
        row.last_error = error[:500]
        row.finished_at = datetime.now().isoformat(timespec="seconds")
        self.outcomes[row.key] = status
        self.counts = dict(Counter(self.outcomes.values()))
        self.ledger.append(
            qs.LedgerEntry(
                key=row.key,
                status=status,
                label=row.label,
                extraction_id=row.extraction_id,
                pages=row.pages,
                md_chars=row.md_chars,
                images=row.images,
                seconds=row.seconds,
                attempts=row.attempts,
                error=error[:500],
            )
        )
        self.writer.update([row])
        self.in_flight.pop(row.key, None)
        self._publish(last_finished={
            "label": row.label,
            "title": row.document_title,
            "status": status,
            "seconds": round(row.seconds or 0.0, 1),
            "at": row.finished_at,
        })

    def _mark_running(self, row: qs.QueueRow) -> None:
        row.attempts += 1
        self.ledger.append(
            qs.LedgerEntry(
                key=row.key, status="running", label=row.label, attempts=row.attempts
            )
        )
        self.in_flight[row.key] = {
            "label": row.label,
            "title": row.document_title,
            "subject": row.subject_name,
            "standard": row.standard,
            "chapter": row.chapter_number,
            "attempt": row.attempts,
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._publish()

    # -- width decisions --------------------------------------------------

    def width_for_next_batch(self) -> tuple[int, str]:
        if self.batch_size == 1:
            return 1, ""
        if self.degraded:
            return 1, "degraded after repeated batch failures"
        available = free_gb()
        if available is not None and available < self.args.min_free_gb:
            self.low_memory_batches += 1
            return 1, f"only {available:.1f} GB free (need {self.args.min_free_gb:.1f})"
        return self.batch_size, ""

    def out_of_time(self) -> bool:
        """Should the runner stop starting new chapters?

        Two ways to say yes: a deadline (off by default -- a night runs until
        the queue is empty) and the STOP flag, which is how someone arriving in
        the morning ends the run from the web page. Either way this only stops
        work being STARTED. Chapters already in flight finish and are saved;
        killing MinerU mid-chapter would throw away up to forty minutes of CPU
        and leave a stub row claiming to be extracting forever.
        """
        if self.state is not None and self.state.stop_requested():
            if not self.stopped_by_user:
                self.stopped_by_user = True
                logger.warning("Stop requested -- finishing the current chapter(s), then stopping")
                self._publish(state="stopping")
            return True
        return self.deadline is not None and datetime.now() >= self.deadline

    # -- one chapter ------------------------------------------------------

    async def run_one(self, row: qs.QueueRow) -> bool:
        """Extract one chapter. Returns False only if MinerU itself failed.

        Never raises. The queue is the only thing that outlives this call, and
        it must outlive every way a single chapter can go wrong.
        """
        started = time.perf_counter()
        job_id = f"queue-{uuid.uuid4().hex[:10]}"
        tenant = row.sub_institute_id or settings.tenant_for_board(row.board)
        extraction_id: int | None = None
        pdf_path: Path | None = None

        # Validated before the attempt is counted. A row with no pdf_url has not
        # been tried and failed, it has not been filled in -- charging it an
        # attempt would retire the row after three clicks of Start and quietly
        # drop the chapter from every future night.
        problem = row.validate()
        if problem:
            logger.error("-> %s  row is incomplete: %s", row.label, problem)
            self._record(row, Outcome.FAILED, f"sheet row incomplete: {problem}")
            return False

        self._mark_running(row)
        logger.info("-> %s  %s", row.label, (row.document_title or "")[:48])

        try:
            # 1. Has this chapter already been extracted?
            previous = await _db_call(_existing_extraction, row, tenant)
            if previous and previous["md_len"] > 0 and not self.args.force:
                row.extraction_id = int(previous["id"])
                row.md_chars = int(previous["md_len"])
                logger.info(
                    "   already extracted (id %s, %s chars) - skipping",
                    row.extraction_id,
                    row.md_chars,
                )
                self._record(row, Outcome.SKIPPED, "already extracted")
                return True
            if previous and previous["md_len"] == 0:
                await _db_call(_drop_stale, int(previous["id"]))

            # 2. Get the bytes on disk. A URL and a local path are both allowed
            #    in the sheet; people mix them constantly.
            pdf_path = get_temp_pdf_path(settings.temp_dir, job_id)
            await self._fetch(row.pdf_url, pdf_path)
            digest = await asyncio.to_thread(file_sha256, pdf_path)

            # 3. The stub exists before MinerU runs, so a crash leaves a visible
            #    failed row rather than nothing at all.
            meta = dict(
                document_type=row.document_type,
                document_title=row.document_title,
                chapter_number=row.chapter_number,
                standard=row.standard,
                subject_name=row.subject_name,
                board=row.board,
                syear=row.syear,
                sub_institute_id=tenant,
            )
            extraction_id = await _db_call(
                create_extraction_stub, pdf_url=row.pdf_url, content_sha256=digest, **meta
            )
            if extraction_id is None:
                # create_extraction_stub swallows non-ChapterNotFoundError
                # failures and returns None. Going on would make
                # persist_extraction_result insert a second, orphan row.
                raise RuntimeError("create_extraction_stub returned None (database unreachable?)")
            row.extraction_id = extraction_id

            # 4. MinerU. The outer timeout is belt and braces over the
            #    subprocess timeout: a hung child must not eat the whole night.
            response = await asyncio.wait_for(
                _run_extraction_job(
                    job_id=job_id,
                    pdf_path=pdf_path,
                    asset_base_url=f"{self.args.asset_base}/{job_id}",
                    start_time=started,
                    cache_message=f"Checking cache for {row.label}",
                    extraction_message=f"Extracting {row.label} with MinerU",
                ),
                timeout=self.args.chapter_timeout,
            )

            row.pages = response.page_count
            row.images = response.images_extracted
            row.md_chars = len(response.markdown_content or "")
            row.seconds = time.perf_counter() - started

            # 5. Persist. If this is the one thing that fails, the markdown is
            #    already in the on-disk extraction cache keyed by the PDF's
            #    hash, so a later re-run re-persists it in seconds rather than
            #    re-running MinerU. That is what 'extracted' means in the sheet.
            try:
                new_id = await _db_call(
                    persist_extraction_result, extraction_id, response, pdf_url=row.pdf_url, **meta
                )
                row.extraction_id = new_id or extraction_id
            except Exception as exc:
                logger.error("   extracted but NOT saved to the database: %s", str(exc)[:160])
                self._record(row, Outcome.EXTRACTED, f"database write failed: {exc}")
                return True

            logger.info(
                "   DONE in %.0fs | id %s | %s chars | %s pages | %s images",
                row.seconds,
                row.extraction_id,
                row.md_chars,
                row.pages,
                row.images,
            )
            self._record(row, Outcome.DONE)
            return True

        except asyncio.TimeoutError:
            row.seconds = time.perf_counter() - started
            message = f"timed out after {self.args.chapter_timeout}s"
            logger.error("   FAILED: %s", message)
            await self._safe_mark_failed(extraction_id, message)
            self._record(row, Outcome.FAILED, message)
            return False

        except ChapterNotFoundError as exc:
            # Only a question_bank row can raise this, and it is the operator's
            # to fix: extract the chapter before its question bank.
            row.seconds = time.perf_counter() - started
            logger.error("   FAILED: %s", str(exc)[:200])
            self._record(row, Outcome.FAILED, str(exc))
            return False

        except PDFDownloadError as exc:
            row.seconds = time.perf_counter() - started
            logger.error("   FAILED to fetch the PDF: %s", str(exc)[:200])
            await self._safe_mark_failed(extraction_id, str(exc))
            self._record(row, Outcome.FAILED, f"pdf fetch failed: {exc}")
            return False

        except asyncio.CancelledError:
            # Ctrl-C, or the sibling of a failed batch being torn down. Leave the
            # row retryable rather than recording a failure it did not have.
            await self._safe_mark_failed(extraction_id, "cancelled")
            raise

        except Exception as exc:
            row.seconds = time.perf_counter() - started
            logger.exception("   FAILED: %s", str(exc)[:200])
            await self._safe_mark_failed(extraction_id, str(exc))
            self._record(row, Outcome.FAILED, str(exc))
            return False

        finally:
            with contextlib.suppress(Exception):
                cleanup_temp_job(settings.temp_dir, job_id)

    async def _safe_mark_failed(self, extraction_id: int | None, message: str) -> None:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(_mark_failed, extraction_id, message)

    async def _fetch(self, source: str, destination: Path) -> None:
        """Put the chapter PDF at `destination`, from a URL or a local path.

        Downloads are retried, with a long first backoff. ncert.nic.in rate
        limits: asked for forty-eight PDFs back to back it drops every
        connection, and answers normally again after a pause. During a real
        night the downloads are twenty minutes apart and never trip it, but the
        first two chapters of a batch do fetch together, and a chapter is far
        too expensive to abandon over a refusal that waiting clears.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        is_url = source.lower().startswith(("http://", "https://"))

        if not is_url:
            local = Path(source).expanduser()
            if not local.exists():
                raise PDFDownloadError(f"Local PDF not found: {local}")
            await asyncio.to_thread(shutil.copyfile, local, destination)
        else:
            delay = 15.0
            for attempt in range(1, self.args.download_attempts + 1):
                try:
                    await download_pdf(source, destination)
                    break
                except Exception as exc:
                    if attempt == self.args.download_attempts:
                        raise PDFDownloadError(
                            f"{self.args.download_attempts} download attempts failed: {exc}"
                        ) from exc
                    logger.warning(
                        "   download failed (%d/%d): %s -- retrying in %.0fs",
                        attempt,
                        self.args.download_attempts,
                        str(exc)[:110],
                        delay,
                    )
                    destination.unlink(missing_ok=True)
                    await asyncio.sleep(delay)
                    delay *= 2

        # A site that answers a dead link with an HTML error page would
        # otherwise reach MinerU as a "PDF" and fail forty minutes later.
        with destination.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                raise PDFDownloadError(f"Not a PDF (server returned something else): {source}")

    # -- one subject ------------------------------------------------------

    async def run_subject(self, name: str, chapters: list[qs.QueueRow]) -> None:
        logger.info("")
        logger.info("=" * 70)
        logger.info("SUBJECT  %s  --  %d chapter(s)", name, len(chapters))
        logger.info("=" * 70)

        self.current_subject = name
        self._publish()

        index = 0
        while index < len(chapters):
            if self.out_of_time():
                logger.warning("Stopping; the rest of %s stays pending for the next run", name)
                return

            width, reason = self.width_for_next_batch()
            batch = chapters[index : index + width]
            index += len(batch)

            if len(batch) == 1:
                if reason:
                    logger.info("Running one at a time: %s", reason)
                await self.run_one(batch[0])
                continue

            logger.info(
                "Batch of %d: %s",
                len(batch),
                ", ".join(f"ch{c.chapter_number}" for c in batch),
            )
            results = await asyncio.gather(
                *(self.run_one(chapter) for chapter in batch), return_exceptions=True
            )

            failed = [
                chapter
                for chapter, result in zip(batch, results)
                if result is not True
            ]
            for result in results:
                if isinstance(result, BaseException) and not isinstance(result, Exception):
                    raise result  # a CancelledError must propagate

            if not failed:
                self.batch_failures = 0
                continue

            # The rule the queue is built around: a batch that fails is retried
            # one chapter at a time. Two MinerU processes is the usual cause,
            # and singly they fit.
            self.batch_failures += 1
            logger.warning(
                "%d of %d failed in this batch -- retrying them one at a time",
                len(failed),
                len(batch),
            )
            for chapter in failed:
                if self.out_of_time():
                    break
                await self.run_one(chapter)

            if not self.degraded and self.batch_failures >= self.args.degrade_after:
                self.degraded = True
                logger.warning(
                    "%d batches have failed; running one chapter at a time for the "
                    "rest of this run",
                    self.batch_failures,
                )

    # -- the night --------------------------------------------------------

    async def run(self, groups: list[tuple[str, list[qs.QueueRow]]]) -> None:
        self.total_planned = sum(len(chapters) for _, chapters in groups)
        self._publish(state="running")
        for name, chapters in groups:
            if self.out_of_time():
                logger.warning("Stopping; %s and everything after it stays pending", name)
                break
            try:
                await self.run_subject(name, chapters)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A subject must never be able to end the night.
                logger.exception("Subject %s ended unexpectedly; moving to the next", name)
            done = sum(1 for c in chapters if c.status in qs.TERMINAL)
            logger.info("SUBJECT %s finished: %d/%d chapters", name, done, len(chapters))
        self.current_subject = ""
        self._publish()


# --------------------------------------------------------------------------
# selection
# --------------------------------------------------------------------------

def _resolve_deadline(args: argparse.Namespace) -> datetime | None:
    if args.max_hours:
        return datetime.now() + timedelta(hours=args.max_hours)
    if args.stop_at:
        hour, _, minute = args.stop_at.partition(":")
        target = dtime(int(hour), int(minute or 0))
        deadline = datetime.combine(datetime.now().date(), target)
        if deadline <= datetime.now():
            deadline += timedelta(days=1)  # a morning stop time, set at night
        return deadline
    return None


def select(rows: list[qs.QueueRow], args: argparse.Namespace) -> list[qs.QueueRow]:
    chosen: list[qs.QueueRow] = []
    for row in rows:
        if not row.is_enabled():
            continue
        if args.only_standard and str(row.standard) != str(args.only_standard):
            continue
        if args.only_subject and row.subject_name.lower() != args.only_subject.lower():
            continue
        if args.only_chapter and row.chapter_number not in args.only_chapter:
            continue
        if not args.force and not row.is_runnable():
            continue
        if not args.force and args.skip_failed and row.status == "failed":
            continue
        if args.max_attempts and row.attempts >= args.max_attempts and not args.force:
            continue
        chosen.append(row)
    if args.limit:
        chosen = chosen[: args.limit]
    return chosen


def group_by_subject(rows: Iterable[qs.QueueRow]) -> list[tuple[str, list[qs.QueueRow]]]:
    """Subjects in sheet order; chapters within a subject in chapter order."""
    groups: dict[tuple[str, str, str], list[qs.QueueRow]] = {}
    for row in rows:
        groups.setdefault(row.subject_key, []).append(row)
    ordered: list[tuple[str, list[qs.QueueRow]]] = []
    for (board, standard, subject), chapters in groups.items():
        chapters.sort(key=lambda r: (r.chapter_number is None, r.chapter_number or 0))
        ordered.append((f"{board} class {standard} {chapters[0].subject_name or subject}", chapters))
    return ordered


def print_plan(
    groups: list[tuple[str, list[qs.QueueRow]]],
    resolved: dict[str, dict[str, Any]] | None = None,
) -> None:
    total = 0
    unresolved = 0
    for name, chapters in groups:
        logger.info("%s  (%d)", name, len(chapters))
        for chapter in chapters:
            notes = []
            problem = chapter.validate()
            if problem:
                notes.append(problem)

            ids = (resolved or {}).get(chapter.key)
            if ids:
                missing = [
                    label
                    for label, value in (
                        ("standard", ids["standard_id"]),
                        ("subject", ids["subject_id"]),
                        ("chapter", ids["chapter_id"]),
                    )
                    if value is None
                ]
                if missing:
                    unresolved += 1
                    notes.append("no " + "/".join(missing) + " match")

            logger.info(
                "   ch%-3s %-44s %-8s%s",
                chapter.chapter_number if chapter.chapter_number is not None else "-",
                (chapter.document_title or "")[:44],
                chapter.status,
                ("  << " + "; ".join(notes)) if notes else "",
            )
        total += len(chapters)
    logger.info("")
    logger.info("%d chapter(s) across %d subject(s)", total, len(groups))
    if resolved:
        if unresolved:
            logger.warning(
                "%d row(s) will be stored with a NULL id. The extraction still "
                "works, but nothing downstream will find the chapter -- fix the "
                "spelling in the sheet, or create the missing master row first.",
                unresolved,
            )
        else:
            logger.info("Every row resolves to a standard, subject and chapter.")


# --------------------------------------------------------------------------

def _chapter_list(value: str) -> set[int]:
    try:
        return {int(part) for part in value.split(",") if part.strip()}
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected chapter numbers like 5 or 3,4,5 -- got {value!r}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    # Both default to names derived from the sheet, so two sheets never share a
    # ledger or a heartbeat. See queue_sheet.companion_paths.
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--batch-size", type=int, default=2, help="chapters at a time (default 2)")
    parser.add_argument(
        "--degrade-after",
        type=int,
        default=2,
        help="failed batches before the run drops to one at a time (default 2)",
    )
    parser.add_argument(
        "--min-free-gb",
        type=float,
        default=DEFAULT_MIN_FREE_GB,
        help="run singly when less memory than this is free (default 5.0)",
    )
    parser.add_argument(
        "--chapter-timeout",
        type=int,
        default=settings.mineru_timeout_seconds + 900,
        help="seconds before one chapter is abandoned",
    )
    parser.add_argument(
        "--download-attempts",
        type=int,
        default=4,
        help="tries before a PDF link is called dead (default 4)",
    )
    parser.add_argument("--stop-at", help="clock time to stop starting new work, e.g. 07:30")
    parser.add_argument("--max-hours", type=float, help="stop starting new work after N hours")
    parser.add_argument("--only-standard")
    parser.add_argument("--only-subject")
    parser.add_argument(
        "--only-chapter",
        type=_chapter_list,
        help="comma-separated chapter numbers, e.g. 5 or 3,4,5",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true", help="re-extract rows already done")
    parser.add_argument("--skip-failed", action="store_true", help="do not retry failed rows")
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="give up on a row after this many attempts (default 3)",
    )
    parser.add_argument("--asset-base", default=DEFAULT_ASSET_BASE)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--list", action="store_true", help="show the plan and exit")
    parser.add_argument("--sync-sheet", action="store_true", help="replay the ledger into the sheet and exit")
    parser.add_argument("--no-keep-awake", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    ledger, state = qs.companion_paths(args.sheet)
    args.ledger = args.ledger or ledger
    args.state = args.state or state
    return args


async def main_async(args: argparse.Namespace, run_id: str) -> int:
    rows = qs.load(args.sheet)
    if not rows:
        logger.error("The queue sheet has no rows: %s", args.sheet)
        return 2

    ledger = qs.Ledger(args.ledger, run_id=run_id)
    writer = qs.SheetWriter(args.sheet)
    state = qs.RunState(args.state)

    # The ledger is authoritative. A sheet that was locked in Excel during the
    # last run still shows every row pending; this puts it right before anything
    # is chosen to run, so nothing is extracted twice.
    changed = qs.apply_ledger(rows, ledger.latest())
    if changed:
        logger.info("Restored %d row(s) from the ledger", changed)
        writer.update(rows)

    if args.sync_sheet:
        ok = writer.update(rows)
        logger.info(
            "Sheet %s from %d ledger entries", "updated" if ok else "NOT updated", changed
        )
        return 0 if ok else 1

    chosen = select(rows, args)
    groups = group_by_subject(chosen)

    if args.list or not chosen:
        # Resolve the foreign keys for the plan when the database is reachable.
        # It is the difference between "48 chapters queued" and "48 chapters
        # queued, 9 of which will not attach to anything".
        resolved = None
        if chosen and init_mariadb() and SessionLocal is not None:
            try:
                resolved = resolve_preview(chosen)
            except Exception:
                logger.debug("Could not resolve ids for the plan", exc_info=True)
        print_plan(groups, resolved)
        if not chosen:
            logger.info("Nothing to do.")
        return 0

    if not init_mariadb() or SessionLocal is None:
        logger.error("MariaDB is unreachable; check the MARIADB_* settings in .env")
        return 2

    available = free_gb()
    logger.info("Run %s", run_id)
    logger.info("Sheet     %s", args.sheet)
    logger.info("Ledger    %s", args.ledger)
    logger.info(
        "Plan      %d chapter(s), %d subject(s), %d at a time",
        len(chosen),
        len(groups),
        args.batch_size,
    )
    if available is not None:
        logger.info("Memory    %.1f GB free (singles below %.1f GB)", available, args.min_free_gb)
        if available < args.min_free_gb:
            logger.warning(
                "Low memory right now. Close other applications before an overnight "
                "run -- MinerU needs several GB per chapter."
            )
    # A leftover flag from last night would stop tonight before it began.
    state.clear_stop()
    state.publish(
        run_id=run_id,
        pid=os.getpid(),
        state="starting",
        started_at=datetime.now().isoformat(timespec="seconds"),
        finished_at=None,
        log=str(BACKEND / "logs" / f"queue_{run_id}.log"),
        plan={
            "chapters": len(chosen),
            "subjects": [
                {"name": name, "chapters": len(items)} for name, items in groups
            ],
            "batch_size": args.batch_size,
        },
        counts={},
        current=[],
    )

    runner = QueueRunner(args, ledger, writer, state)
    if runner.deadline:
        logger.info("Stop at   %s", runner.deadline.strftime("%Y-%m-%d %H:%M"))
    logger.info("Extraction only -- no DeepSeek calls, no LMS writes beyond document_extractions")

    started = time.perf_counter()
    interrupted = False
    try:
        await runner.run(groups)
    except (KeyboardInterrupt, asyncio.CancelledError):
        interrupted = True
        logger.warning("Interrupted -- finished chapters are saved, the rest stay pending")

    elapsed = time.perf_counter() - started
    logger.info("")
    logger.info("=" * 70)
    for status in (Outcome.DONE, Outcome.SKIPPED, Outcome.EXTRACTED, Outcome.FAILED):
        if runner.counts.get(status):
            logger.info("%-10s %d", status, runner.counts[status])
    logger.info("elapsed    %s", str(timedelta(seconds=int(elapsed))))
    if runner.degraded:
        logger.info("note       dropped to one chapter at a time after repeated batch failures")
    if runner.low_memory_batches:
        logger.info("note       %d batch(es) ran singly for lack of memory", runner.low_memory_batches)
    if runner.counts.get(Outcome.EXTRACTED):
        logger.info(
            "note       %d chapter(s) extracted but not saved; re-run to persist "
            "them from cache (seconds, not minutes)",
            runner.counts[Outcome.EXTRACTED],
        )
    if writer.failures and not writer.writes:
        logger.info("note       the sheet was never writable; run --sync-sheet with Excel closed")
    for row in (r for r in rows if r.status == Outcome.FAILED):
        logger.info("FAILED     %-38s %s", row.label, row.last_error[:80])

    state.publish(
        state="stopped" if runner.stopped_by_user else ("interrupted" if interrupted else "finished"),
        finished_at=datetime.now().isoformat(timespec="seconds"),
        elapsed_seconds=int(elapsed),
        current=[],
        failures=[
            {"label": r.label, "title": r.document_title, "error": r.last_error[:200]}
            for r in rows
            if r.status == Outcome.FAILED
        ],
    )
    state.clear_stop()

    if interrupted:
        return 130
    return 1 if runner.counts.get(Outcome.FAILED) else 0


def main() -> int:
    args = parse_args()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = setup_logging(run_id, args.verbose)

    with KeepAwake(not args.no_keep_awake):
        try:
            code = asyncio.run(main_async(args, run_id))
        except FileNotFoundError as exc:
            logger.error("%s", exc)
            return 2
        except KeyboardInterrupt:
            logger.warning("Interrupted")
            return 130
    logger.info("Log        %s", log_path)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
