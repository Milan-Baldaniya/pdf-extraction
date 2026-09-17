"""Gate check for the overnight extraction queue.

The queue's whole value is that it survives a night alone, so the properties
worth asserting are the ones a person would otherwise only discover at 7 a.m.
with half a syllabus missing:

  * two chapters run at once, and the remainder runs as a batch of one
  * a batch that fails is retried one chapter at a time
  * repeated batch failures drop the run to singles for good
  * low memory forces singles without anyone asking
  * a subject that blows up does not stop the subjects after it
  * a subject finishes before the next one starts -- never interleaved
  * a stop time stops starting work, it does not abandon what is running
  * a run killed mid-chapter resumes from the ledger, and does not redo a
    chapter that was already done

MinerU and MariaDB are not involved: `run_one` is replaced with a script of
outcomes, so the scheduling can be tested in milliseconds rather than hours.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import queue_sheet as qs  # noqa: E402
from scripts import run_extraction_queue as req  # noqa: E402


def _args(**overrides) -> argparse.Namespace:
    base = dict(
        batch_size=2,
        degrade_after=2,
        # Zero by default so the machine's real free memory cannot decide the
        # outcome of a scheduling test; test_low_memory_forces_single sets it.
        min_free_gb=0.0,
        chapter_timeout=600,
        stop_at=None,
        max_hours=None,
        force=False,
        asset_base="http://127.0.0.1:8000/api/assets",
        only_standard=None,
        only_subject=None,
        only_chapter=None,
        limit=None,
        skip_failed=False,
        max_attempts=3,
        download_attempts=4,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def _rows(subject: str, count: int, standard: int = 10) -> list[qs.QueueRow]:
    return [
        qs.QueueRow(
            sheet_row=index + 1,
            board="CBSE",
            standard=standard,
            subject_name=subject,
            chapter_number=index,
            document_title=f"{subject} chapter {index}",
            pdf_url=f"https://example.invalid/{subject}-{index}.pdf",
        )
        for index in range(1, count + 1)
    ]


class FakeLedger(qs.Ledger):
    def __init__(self) -> None:  # no file, no fsync
        self.entries: list[qs.LedgerEntry] = []
        self.run_id = "test"

    def append(self, entry: qs.LedgerEntry) -> None:
        self.entries.append(entry)

    def latest(self) -> dict[str, qs.LedgerEntry]:
        return {entry.key: entry for entry in self.entries}


class FakeWriter(qs.SheetWriter):
    def __init__(self) -> None:
        self.enabled = False
        self.writes = 0
        self.failures = 0

    def update(self, rows) -> bool:
        self.writes += 1
        return True


class ScriptedRunner(req.QueueRunner):
    """A runner whose chapters succeed or fail on command.

    `fail_keys` names chapters that fail; a key is removed from it once it has
    failed `fail_times` times, which is how "fails in a batch, succeeds when
    retried alone" is expressed.
    """

    def __init__(self, args, *, fail: dict[str, int] | None = None, duration: float = 0.01):
        super().__init__(args, FakeLedger(), FakeWriter())
        self.fail = dict(fail or {})
        self.duration = duration
        self.calls: list[str] = []
        self.timeline: list[tuple[str, str]] = []
        self.peak_concurrency = 0
        self._in_flight = 0

    async def run_one(self, row: qs.QueueRow) -> bool:
        key = f"{row.subject_name}:{row.chapter_number}"
        self.calls.append(key)
        self.timeline.append(("start", key))
        self._in_flight += 1
        self.peak_concurrency = max(self.peak_concurrency, self._in_flight)
        try:
            await asyncio.sleep(self.duration)
            remaining = self.fail.get(key, 0)
            if remaining > 0:
                self.fail[key] = remaining - 1
                row.attempts += 1
                self._record(row, req.Outcome.FAILED, "scripted failure")
                return False
            row.attempts += 1
            self._record(row, req.Outcome.DONE)
            return True
        finally:
            self._in_flight -= 1
            self.timeline.append(("end", key))


def _expect(failures: list[str], label: str, actual, expected) -> None:
    if actual != expected:
        failures.append(f"{label}: expected {expected!r}, got {actual!r}")


# --------------------------------------------------------------------------

def test_batches_of_two(failures: list[str]) -> None:
    """Five chapters run as 2 + 2 + 1, two at a time."""
    runner = ScriptedRunner(_args())
    rows = _rows("Science", 5)
    asyncio.run(runner.run_subject("Science", rows))

    _expect(failures, "every chapter ran once", runner.calls, [f"Science:{n}" for n in range(1, 6)])
    _expect(failures, "peak concurrency", runner.peak_concurrency, 2)
    _expect(failures, "all done", runner.counts.get("done"), 5)

    # The odd chapter out must run alone, not be dropped or paired across a
    # subject boundary.
    starts = [key for kind, key in runner.timeline if kind == "start"]
    _expect(failures, "last chapter ran last", starts[-1], "Science:5")


def test_failed_batch_retries_singly(failures: list[str]) -> None:
    """A chapter that fails inside a batch is retried on its own and succeeds."""
    runner = ScriptedRunner(_args(), fail={"Science:2": 1})
    rows = _rows("Science", 4)
    asyncio.run(runner.run_subject("Science", rows))

    _expect(failures, "chapter 2 ran twice", runner.calls.count("Science:2"), 2)
    _expect(failures, "chapter 1 ran once", runner.calls.count("Science:1"), 1)
    _expect(failures, "final state", rows[1].status, "done")
    _expect(failures, "done count", runner.counts.get("done"), 4)
    # Counted per chapter, not per attempt: chapter 2 failed once and then
    # worked, so nothing is broken and the summary must not claim otherwise.
    _expect(failures, "no chapter left failed", runner.counts.get("failed"), None)

    # The retry must be serial: nothing else may be in flight beside it.
    retry_index = [i for i, key in enumerate(runner.calls) if key == "Science:2"][1]
    _expect(failures, "retry is after the batch", retry_index >= 2, True)


def test_degrades_to_single(failures: list[str]) -> None:
    """Two failed batches and the rest of the run goes one at a time."""
    # Chapters 1 and 3 fail on every attempt, so batch 1 and batch 2 both fail.
    runner = ScriptedRunner(_args(degrade_after=2), fail={"Science:1": 9, "Science:3": 9})
    rows = _rows("Science", 8)
    asyncio.run(runner.run_subject("Science", rows))

    _expect(failures, "degraded", runner.degraded, True)
    width, reason = runner.width_for_next_batch()
    _expect(failures, "width after degrading", width, 1)
    _expect(failures, "reason given", bool(reason), True)
    # Chapters 5..8 run after degrading, so nothing ever ran three-wide.
    _expect(failures, "peak concurrency", runner.peak_concurrency, 2)
    _expect(failures, "every chapter attempted", len(set(runner.calls)), 8)


def test_low_memory_forces_single(failures: list[str]) -> None:
    """Not enough free RAM is a reason to run singly, decided per batch."""
    original = req.free_gb
    req.free_gb = lambda: 1.2  # type: ignore[assignment]
    try:
        runner = ScriptedRunner(_args(min_free_gb=5.0))
        rows = _rows("Science", 4)
        asyncio.run(runner.run_subject("Science", rows))
    finally:
        req.free_gb = original  # type: ignore[assignment]

    _expect(failures, "never ran two at once", runner.peak_concurrency, 1)
    _expect(failures, "still finished everything", runner.counts.get("done"), 4)
    _expect(failures, "counted the low-memory batches", runner.low_memory_batches >= 4, True)
    _expect(failures, "did not mark the run degraded", runner.degraded, False)


def test_subject_failure_does_not_stop_the_night(failures: list[str]) -> None:
    """A subject that raises is logged; the next subject still runs."""

    class Exploding(ScriptedRunner):
        async def run_subject(self, name, chapters):
            if name.endswith("Maths"):
                raise RuntimeError("subject exploded")
            await super().run_subject(name, chapters)

    runner = Exploding(_args())
    groups = [
        ("CBSE class 10 Maths", _rows("Maths", 2)),
        ("CBSE class 10 Science", _rows("Science", 3)),
    ]
    asyncio.run(runner.run(groups))

    _expect(failures, "science still ran", runner.counts.get("done"), 3)
    _expect(failures, "maths ran nothing", [c for c in runner.calls if c.startswith("Maths")], [])


def test_subjects_do_not_interleave(failures: list[str]) -> None:
    """One subject finishes before the next begins."""
    runner = ScriptedRunner(_args())
    groups = [
        ("CBSE class 10 Maths", _rows("Maths", 3)),
        ("CBSE class 10 Science", _rows("Science", 3)),
    ]
    asyncio.run(runner.run(groups))

    subjects = [key.split(":")[0] for key in runner.calls]
    first_science = subjects.index("Science")
    _expect(failures, "no maths after science started", "Maths" in subjects[first_science:], False)
    _expect(failures, "everything ran", len(runner.calls), 6)


def test_stop_time_halts_new_work(failures: list[str]) -> None:
    """A deadline in the past means nothing new starts."""
    runner = ScriptedRunner(_args())
    runner.deadline = datetime.now() - timedelta(minutes=1)
    rows = _rows("Science", 4)
    asyncio.run(runner.run_subject("Science", rows))

    _expect(failures, "nothing started", runner.calls, [])
    _expect(failures, "rows left pending", [r.status for r in rows], ["pending"] * 4)


def test_stop_flag_finishes_the_chapter_in_flight(failures: list[str]) -> None:
    """The morning stop: no new chapters start, the current one is not killed.

    This is the behaviour the Stop button depends on. Killing MinerU mid-chapter
    would throw away up to forty minutes of CPU and strand a row stamped
    'extracting' that nothing ever clears, so the flag is only ever read
    BETWEEN chapters.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        state = qs.RunState(Path(folder) / "run_state.json")
        runner = ScriptedRunner(_args())
        runner.state = state
        rows = _rows("Science", 6)

        # Stop after the first batch by flipping the flag once two have run.
        original = runner.run_one

        async def run_then_stop(row):
            result = await original(row)
            if len(runner.calls) >= 2:
                state.request_stop("test")
            return result

        runner.run_one = run_then_stop  # type: ignore[assignment]
        asyncio.run(runner.run_subject("Science", rows))

        _expect(failures, "the batch in flight finished", len(runner.calls), 2)
        _expect(failures, "both were saved", runner.counts.get("done"), 2)
        _expect(failures, "nothing new started", len(runner.calls), 2)
        _expect(failures, "the rest stay pending", [r.status for r in rows[2:]], ["pending"] * 4)
        _expect(failures, "run marked as stopped by user", runner.stopped_by_user, True)

        # And the flag is readable/clearable the way the API expects.
        _expect(failures, "flag is set", state.stop_requested(), True)
        state.clear_stop()
        _expect(failures, "flag clears", state.stop_requested(), False)


def test_heartbeat_reports_progress(failures: list[str]) -> None:
    """The live page reads run_state.json; it has to actually say something."""
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        state = qs.RunState(Path(folder) / "run_state.json")
        runner = ScriptedRunner(_args())
        runner.state = state
        asyncio.run(runner.run([("CBSE class 10 Science", _rows("Science", 3))]))

        published = state.read()
        _expect(failures, "total planned", published.get("total"), 3)
        _expect(failures, "finished count", published.get("finished"), 3)
        _expect(failures, "counts published", published.get("counts"), {"done": 3})
        _expect(failures, "nothing left in flight", published.get("current"), [])
        _expect(failures, "last finished recorded", bool(published.get("last_finished")), True)


def test_resume_from_ledger(failures: list[str]) -> None:
    """A run killed mid-chapter resumes without redoing finished work."""
    rows = _rows("Science", 3)
    ledger = FakeLedger()
    ledger.append(qs.LedgerEntry(key=rows[0].key, status="done", extraction_id=101, attempts=1))
    ledger.append(qs.LedgerEntry(key=rows[1].key, status="running", attempts=1))

    changed = qs.apply_ledger(rows, ledger.latest())
    _expect(failures, "two rows restored", changed, 2)
    _expect(failures, "finished chapter stays done", rows[0].status, "done")
    _expect(failures, "killed chapter becomes failed", rows[1].status, "failed")
    _expect(failures, "untouched chapter stays pending", rows[2].status, "pending")

    chosen = req.select(rows, _args())
    _expect(
        failures,
        "only the unfinished chapters are re-queued",
        [r.chapter_number for r in chosen],
        [2, 3],
    )

    # ...and --force takes the finished one back.
    _expect(failures, "force re-queues everything", len(req.select(rows, _args(force=True))), 3)


def test_selection_filters(failures: list[str]) -> None:
    """The filters a person reaches for at 11 p.m."""
    rows = _rows("Science", 2) + _rows("Maths", 2) + _rows("History", 2, standard=9)

    _expect(failures, "--only-subject", len(req.select(rows, _args(only_subject="maths"))), 2)
    _expect(failures, "--only-standard", len(req.select(rows, _args(only_standard="9"))), 2)
    _expect(failures, "--limit", len(req.select(rows, _args(limit=3))), 3)
    _expect(failures, "--only-chapter", len(req.select(rows, _args(only_chapter={1}))), 3)
    _expect(
        failures,
        "--only-chapter with a subject",
        len(req.select(rows, _args(only_chapter={2}, only_subject="Science"))),
        1,
    )

    rows[0].enabled = "no"
    _expect(failures, "enabled=no is skipped", len(req.select(rows, _args())), 5)

    rows[1].status = "failed"
    rows[1].attempts = 3
    _expect(failures, "--max-attempts gives up", len(req.select(rows, _args(max_attempts=3))), 4)
    _expect(failures, "--skip-failed", len(req.select(rows, _args(skip_failed=True))), 4)

    groups = req.group_by_subject(req.select(rows, _args(max_attempts=0)))
    _expect(failures, "grouped by board+class+subject", len(groups), 3)


def main() -> int:
    failures: list[str] = []
    tests = (
        test_batches_of_two,
        test_failed_batch_retries_singly,
        test_degrades_to_single,
        test_low_memory_forces_single,
        test_subject_failure_does_not_stop_the_night,
        test_subjects_do_not_interleave,
        test_stop_time_halts_new_work,
        test_stop_flag_finishes_the_chapter_in_flight,
        test_heartbeat_reports_progress,
        test_resume_from_ledger,
        test_selection_filters,
    )
    for test in tests:
        try:
            test(failures)
        except Exception as exc:
            failures.append(f"{test.__name__} raised {type(exc).__name__}: {exc}")

    if failures:
        print("\nFAIL")
        for failure in failures:
            print("  -", failure)
        return 1

    print(f"\nPASS  {len(tests)} checks: batching, serial retry, degradation, stop, resume")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
