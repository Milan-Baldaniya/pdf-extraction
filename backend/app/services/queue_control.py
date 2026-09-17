"""Start, stop and explain the overnight extraction queue.

The runner is a detached process, not a background task of this API. That is
deliberate: a night lasts eight hours and must survive the API being restarted,
an editor being closed, or uvicorn reloading on a file save. Nothing here holds
a handle on it. Instead the two sides share three files in backend/queue:

    run_state.json   the runner's heartbeat -- what it is doing right now
    STOP             a flag the runner checks between chapters
    ledger.jsonl     every chapter of every night, ever

So this module is mostly a reader. The one thing it writes is the STOP flag,
and the one thing it spawns is the runner itself.

The history it builds is meant to be read by whoever walks in at 9 a.m., not by
whoever wrote it. "Extracted 22 chapters in 6h 49m, Class 10 Science finished"
is the goal; the raw log is there underneath for when that is not enough.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from app.utils.config import settings

logger = logging.getLogger(__name__)

BACKEND = Path(__file__).resolve().parents[2]
QUEUE_DIR = BACKEND / "queue"
LOGS_DIR = BACKEND / "logs"


def list_sheets() -> list[Path]:
    """Every queue sheet on this machine, in name order.

    There is deliberately no single fixed sheet. A class per sheet is the unit
    of work -- one machine runs Class 9 while another runs Class 10 -- and each
    carries its own ledger, heartbeat and stop flag so the two never interfere.
    """
    if not QUEUE_DIR.exists():
        return []
    return sorted(
        path
        for path in QUEUE_DIR.glob("*.xlsx")
        # Skip openpyxl's atomic-save temp files and Excel's lock files.
        if not path.name.startswith((".", "~$"))
    )


def _companions(sheet: Path) -> tuple[Path, Path, Path]:
    """(ledger, state, stop) for one sheet -- the runner's own naming."""
    if sheet.stem == "extraction_queue":
        ledger, state = QUEUE_DIR / "ledger.jsonl", QUEUE_DIR / "run_state.json"
    else:
        ledger = QUEUE_DIR / f"{sheet.stem}.ledger.jsonl"
        state = QUEUE_DIR / f"{sheet.stem}.state.json"
    return ledger, state, QUEUE_DIR / f"{sheet.stem}.STOP"


def resolve_sheet(name: str | None = None) -> Path | None:
    """The sheet a request means.

    Named explicitly, or -- when there is only one on this machine, which is the
    normal case -- that one. With several and no name, the one actually running
    wins, so the status page does not flip to an idle sheet mid-run.
    """
    sheets = list_sheets()
    if not sheets:
        return None
    if name:
        wanted = Path(name).name
        for sheet in sheets:
            if sheet.name == wanted or sheet.stem == Path(wanted).stem:
                return sheet
        return None
    if len(sheets) == 1:
        return sheets[0]
    for sheet in sheets:
        _, state, _ = _companions(sheet)
        data = _read_json(state)
        if data.get("state") in {"running", "starting", "stopping"} and _process_alive(
            data.get("pid")
        ):
            return sheet
    return sheets[0]

# How long without a heartbeat before a run that claims to be running is
# assumed dead. A single chapter can take forty minutes, but the runner
# publishes on every state change and at least once per chapter, so an hour of
# silence means the process is gone.
STALE_AFTER_SECONDS = 3600


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _human_duration(seconds: float | int | None) -> str:
    if not seconds or seconds < 0:
        return "-"
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _human_when(value: Any) -> str:
    moment = _parse(value)
    if moment is None:
        return ""
    if moment.tzinfo is not None:
        moment = moment.astimezone().replace(tzinfo=None)
    return moment.strftime("%a %d %b, %I:%M %p").replace(" 0", " ")


# --------------------------------------------------------------------------
# is it actually running?
# --------------------------------------------------------------------------

def _process_alive(pid: int | None) -> bool:
    """True only if `pid` is a live extraction runner.

    The pid alone is not enough: the state file outlives the process, and a
    recycled pid belonging to something else entirely would make a finished
    night look like it is still going. The command line is what settles it.
    """
    if not pid:
        return False
    try:
        import psutil

        process = psutil.Process(int(pid))
        if not process.is_running():
            return False
        return any("run_extraction_queue" in part for part in process.cmdline())
    except Exception:
        return False


def status(sheet: str | None = None) -> dict[str, Any]:
    """What one sheet's queue is doing, right now."""
    path = resolve_sheet(sheet)
    sheets = [p.name for p in list_sheets()]
    if path is None:
        return {
            "running": False,
            "state": "idle",
            "message": (
                "No queue sheet on this machine. Build one with "
                "scripts.build_ncert_sheets."
            ),
            "stop_requested": False,
            "sheet_exists": False,
            "sheet": None,
            "sheets": sheets,
        }

    _ledger, state_path, stop_path = _companions(path)
    data = _read_json(state_path)
    base = {"sheet": path.name, "sheets": sheets, "sheet_exists": True}

    if not data:
        return {
            **base,
            "running": False,
            "state": "idle",
            "message": "No overnight run has been started for this sheet yet.",
            "stop_requested": stop_path.exists(),
        }

    claimed = str(data.get("state") or "")
    alive = _process_alive(data.get("pid"))
    heartbeat = _parse(data.get("updated_at"))
    silent_for = (datetime.now() - heartbeat).total_seconds() if heartbeat else None

    if claimed in {"finished", "stopped", "interrupted"}:
        state = claimed
    elif alive:
        state = "stopping" if (claimed == "stopping" or stop_path.exists()) else "running"
    elif silent_for is not None and silent_for > STALE_AFTER_SECONDS:
        # Claims to be running, no process, and silent for an hour: the machine
        # was shut down or the process was killed mid-chapter.
        state = "crashed"
    else:
        state = "crashed" if claimed in {"running", "starting"} else claimed or "idle"

    finished = int(data.get("finished") or 0)
    total = int(data.get("total") or 0)

    return {
        **base,
        "running": state in {"running", "stopping"},
        "state": state,
        "message": _status_message(state, data),
        "run_id": data.get("run_id"),
        "pid": data.get("pid"),
        "started_at": data.get("started_at"),
        "started_human": _human_when(data.get("started_at")),
        "finished_at": data.get("finished_at"),
        "updated_at": data.get("updated_at"),
        "elapsed_seconds": _elapsed(data),
        "elapsed_human": _human_duration(_elapsed(data)),
        "counts": data.get("counts") or {},
        "finished_count": finished,
        "total": total,
        "remaining": data.get("remaining"),
        "percent": round(100 * finished / total) if total else 0,
        "current": data.get("current") or [],
        "current_subject": data.get("current_subject") or "",
        "last_finished": data.get("last_finished"),
        "plan": data.get("plan") or {},
        "degraded": bool(data.get("degraded")),
        "low_memory_batches": int(data.get("low_memory_batches") or 0),
        "free_gb": data.get("free_gb"),
        "failures": data.get("failures") or [],
        "stop_requested": stop_path.exists(),
        "log_file": Path(str(data.get("log") or "")).name or None,
    }


def _elapsed(data: dict[str, Any]) -> int | None:
    if data.get("elapsed_seconds") is not None:
        return int(data["elapsed_seconds"])
    start = _parse(data.get("started_at"))
    if start is None:
        return None
    end = _parse(data.get("finished_at")) or datetime.now()
    return int((end - start).total_seconds())


def _status_message(state: str, data: dict[str, Any]) -> str:
    counts = data.get("counts") or {}
    done = int(counts.get("done") or 0)
    current = data.get("current") or []
    if state == "running":
        if current:
            names = ", ".join(str(c.get("title") or c.get("label")) for c in current)
            return f"Extracting {names}"
        return "Starting the next chapter"
    if state == "stopping":
        return "Stop requested - finishing the chapter in progress, then stopping"
    if state == "finished":
        return f"Finished. {done} chapter(s) extracted."
    if state == "stopped":
        return f"Stopped by you. {done} chapter(s) extracted before stopping."
    if state == "interrupted":
        return f"Interrupted. {done} chapter(s) were saved."
    if state == "crashed":
        return (
            f"The run ended unexpectedly (power, shutdown, or the window was closed). "
            f"{done} chapter(s) were saved and the rest are still pending."
        )
    return "Idle"


# --------------------------------------------------------------------------
# starting and stopping
# --------------------------------------------------------------------------

def start(
    *,
    sheet: str | None = None,
    batch_size: int = 2,
    only_standard: str | None = None,
    only_subject: str | None = None,
    force: bool = False,
    stop_at: str | None = None,
) -> dict[str, Any]:
    """Launch the overnight runner, detached. Refuses if one is already up."""
    path = resolve_sheet(sheet)
    if path is None:
        raise FileNotFoundError(
            "No queue sheet on this machine. Build one with: "
            "python -m scripts.build_ncert_sheets --class 10"
        )

    current = status(path.name)
    if current["running"]:
        raise RuntimeError(
            f"{path.name} is already running (started {current['started_human']}). "
            "Stop it before starting another."
        )

    _ledger, _state, stop_path = _companions(path)
    # A stop flag left over from this morning would end tonight's run instantly.
    stop_path.unlink(missing_ok=True)

    command = [
        sys.executable,
        "-m",
        "scripts.run_extraction_queue",
        "--sheet",
        str(path),
        "--batch-size",
        str(batch_size),
    ]
    if only_standard:
        command += ["--only-standard", str(only_standard)]
    if only_subject:
        command += ["--only-subject", str(only_subject)]
    if force:
        command.append("--force")
    # Passed explicitly so a run started from the web page writes the same image
    # URLs as one started from the command line. Without it the button would
    # silently fall back to 127.0.0.1 and the images would only ever load on
    # the machine that extracted them.
    command += ["--asset-base", settings.queue_asset_base]
    if stop_at:
        command += ["--stop-at", stop_at]

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    console = LOGS_DIR / "queue_console.log"

    # Detached, in its own process group, with no inherited handles. The run has
    # to outlive this request, this uvicorn worker, and a reload -- and on
    # Windows a child sharing the parent's console dies with it.
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(
            subprocess, "DETACHED_PROCESS", 0x00000008
        )

    with console.open("ab") as sink:
        process = subprocess.Popen(  # noqa: S603
            command,
            cwd=str(BACKEND),
            stdout=sink,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )

    # Stamp the heartbeat ourselves before returning. The runner takes ten
    # seconds or so to import torch and publish its own, and until it does the
    # status endpoint would keep serving LAST night's state -- so the page would
    # say "finished" immediately after you pressed Start. It also means a runner
    # that dies during import reads as "crashed" rather than as nothing at all.
    _, state_path, _ = _companions(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        state_path.write_text(
            json.dumps(
                {
                    "run_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
                    "pid": process.pid,
                    "state": "starting",
                    "started_at": datetime.now().isoformat(timespec="seconds"),
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "counts": {},
                    "current": [],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        logger.debug("Could not stamp the initial run state", exc_info=True)

    logger.info("Overnight extraction queue started for %s as pid %s", path.name, process.pid)
    return {
        "started": True,
        "sheet": path.name,
        "pid": process.pid,
        "command": " ".join(command),
        "message": "Overnight extraction started. It runs until the queue is empty or you stop it.",
    }


def stop(sheet: str | None = None, requested_by: str = "user") -> dict[str, Any]:
    """Ask the run to stop after the chapters in flight finish.

    Never kills the process. A MinerU run killed at minute thirty loses thirty
    minutes of CPU and leaves a row stamped 'extracting' that nothing will ever
    clear, so the flag is checked between chapters instead.
    """
    path = resolve_sheet(sheet)
    if path is None:
        return {"stopped": False, "message": "No queue sheet on this machine.", "state": "idle"}

    current = status(path.name)
    if not current["running"]:
        return {
            "stopped": False,
            "message": f"Nothing is running for {path.name} (state: {current['state']}).",
            "state": current["state"],
        }

    _ledger, _state, stop_path = _companions(path)
    stop_path.parent.mkdir(parents=True, exist_ok=True)
    stop_path.write_text(
        json.dumps({"requested_by": requested_by, "at": datetime.now().isoformat(timespec="seconds")}),
        encoding="utf-8",
    )
    in_flight = current.get("current") or []
    tail = (
        f" Finishing {len(in_flight)} chapter(s) in progress first - this can take "
        "up to 40 minutes."
        if in_flight
        else ""
    )
    return {
        "stopped": True,
        "message": "Stop requested." + tail,
        "state": "stopping",
        "current": in_flight,
    }


# --------------------------------------------------------------------------
# history: every night, in plain language
# --------------------------------------------------------------------------

def _ledger_files(sheet: str | None = None) -> list[Path]:
    """The ledgers to read history from.

    With no sheet named, every ledger in the queue directory, so the history
    page shows all of this machine's nights rather than one sheet's. The legacy
    bare ledger.jsonl is included, which is what keeps runs recorded before the
    per-sheet naming existed.
    """
    if sheet:
        path = resolve_sheet(sheet)
        if path is None:
            return []
        ledger, _state, _stop = _companions(path)
        return [ledger] if ledger.exists() else []
    if not QUEUE_DIR.exists():
        return []
    found = sorted(QUEUE_DIR.glob("*.ledger.jsonl"))
    legacy = QUEUE_DIR / "ledger.jsonl"
    if legacy.exists():
        found.append(legacy)
    return found


def _ledger_entries(sheet: str | None = None) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in _ledger_files(sheet):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # a line torn in half by a hard kill
    return entries


def nights(limit: int = 30, sheet: str | None = None) -> list[dict[str, Any]]:
    """One summary per run, newest first, across every sheet on this machine."""
    by_run: dict[str, list[dict[str, Any]]] = {}
    for entry in _ledger_entries(sheet):
        by_run.setdefault(str(entry.get("run_id") or "unknown"), []).append(entry)

    live = status()
    summaries = [
        _summarise(run_id, entries, live)
        for run_id, entries in by_run.items()
    ]
    # A "run" whose every entry is `pending` did no work -- it is a maintenance
    # write against the ledger (a row reset, a re-queue), not a night. Showing
    # it would put an empty card at the top of the history.
    summaries = [
        summary
        for summary in summaries
        if set(summary["counts"]) - {"pending"}
    ]
    summaries.sort(key=lambda s: s["run_id"], reverse=True)
    return summaries[:limit]


def _summarise(run_id: str, entries: list[dict[str, Any]], live: dict[str, Any]) -> dict[str, Any]:
    # Last entry per chapter is that chapter's outcome for this run.
    final: dict[str, dict[str, Any]] = {}
    for entry in entries:
        final[str(entry.get("key"))] = entry

    counts: dict[str, int] = {}
    for entry in final.values():
        status_name = str(entry.get("status") or "unknown")
        counts[status_name] = counts.get(status_name, 0) + 1

    times = [t for t in (_parse(e.get("at")) for e in entries) if t]
    started = min(times) if times else None
    ended = max(times) if times else None

    is_live = live.get("running") and live.get("run_id") == run_id
    if is_live:
        state = live["state"]
    elif counts.get("running"):
        # Chapters still marked running in a run that is not live: the process
        # died mid-chapter.
        state = "crashed"
    elif live.get("run_id") == run_id:
        state = live.get("state") or "finished"
    else:
        state = "finished"

    subjects = _subject_rollup(final.values())
    chapters = sorted(
        (_chapter_view(e) for e in final.values()),
        key=lambda c: (c["subject"], c["chapter"] if c["chapter"] is not None else 0),
    )

    done = counts.get("done", 0)
    duration = (ended - started).total_seconds() if started and ended else None
    if is_live and started:
        duration = (datetime.now(started.tzinfo) - started).total_seconds()

    return {
        "run_id": run_id,
        "state": state,
        "live": bool(is_live),
        "started_at": started.isoformat() if started else None,
        "finished_at": ended.isoformat() if ended else None,
        "when_human": _human_when(started.isoformat() if started else None),
        "duration_seconds": int(duration) if duration else None,
        "duration_human": _human_duration(duration),
        "counts": counts,
        "headline": _headline(state, done, duration, is_live),
        "details": _details(counts, subjects, chapters),
        "subjects": subjects,
        "chapters": chapters,
        "log_file": _log_for(run_id),
    }


def _headline(state: str, done: int, duration: float | None, live: bool) -> str:
    chapters = f"{done} chapter{'s' if done != 1 else ''}"
    if live:
        return f"Running now - {chapters} done so far"
    if done == 0:
        if state == "crashed":
            return "Ended unexpectedly before any chapter finished"
        return "No chapters were extracted"
    return f"Extracted {chapters} in {_human_duration(duration)}"


def _details(
    counts: dict[str, int], subjects: list[dict[str, Any]], chapters: list[dict[str, Any]]
) -> list[str]:
    """The three or four sentences someone actually wants at 9 a.m."""
    lines: list[str] = []
    if counts.get("done"):
        lines.append(f"{counts['done']} chapter(s) extracted and saved to the database.")
    if counts.get("skipped"):
        lines.append(f"{counts['skipped']} skipped - already extracted before.")
    if counts.get("extracted"):
        lines.append(
            f"{counts['extracted']} extracted but the database write failed. "
            "Re-run and they are saved from cache in seconds."
        )
    if counts.get("failed"):
        reasons = [c["error"] for c in chapters if c["status"] == "failed" and c["error"]]
        first = f" First: {reasons[0][:120]}" if reasons else ""
        lines.append(f"{counts['failed']} failed.{first}")
    if counts.get("running"):
        lines.append(
            f"{counts['running']} chapter(s) were still in progress when the run ended - "
            "they stay pending and run again next time."
        )

    complete = [s["name"] for s in subjects if s["complete"]]
    if complete:
        lines.append("Finished completely: " + ", ".join(complete) + ".")
    partial = [s for s in subjects if not s["complete"] and s["done"]]
    for subject in partial:
        lines.append(f"{subject['name']}: {subject['done']} of {subject['touched']} chapters done.")
    return lines


def _subject_rollup(entries) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for entry in entries:
        label = str(entry.get("label") or "")
        # "CBSE std10 Mathematics ch5" -> "CBSE std10 Mathematics"
        name = label.rsplit(" ch", 1)[0] if " ch" in label else label
        bucket = groups.setdefault(
            name, {"name": name, "done": 0, "failed": 0, "skipped": 0, "touched": 0}
        )
        bucket["touched"] += 1
        status_name = str(entry.get("status") or "")
        if status_name in bucket:
            bucket[status_name] += 1
    for bucket in groups.values():
        settled = bucket["done"] + bucket["skipped"]
        bucket["complete"] = settled == bucket["touched"] and bucket["touched"] > 0
    return sorted(groups.values(), key=lambda b: b["name"])


def _chapter_view(entry: dict[str, Any]) -> dict[str, Any]:
    label = str(entry.get("label") or "")
    parts = label.rsplit(" ch", 1)
    try:
        chapter = int(parts[1]) if len(parts) == 2 else None
    except ValueError:
        chapter = None
    return {
        "key": entry.get("key"),
        "label": label,
        "subject": parts[0] if parts else label,
        "chapter": chapter,
        "status": entry.get("status"),
        "extraction_id": entry.get("extraction_id"),
        "pages": entry.get("pages"),
        "md_chars": entry.get("md_chars"),
        "images": entry.get("images"),
        "seconds": entry.get("seconds"),
        "duration_human": _human_duration(entry.get("seconds")),
        "attempts": entry.get("attempts"),
        "error": entry.get("error") or "",
        "at": entry.get("at"),
        "at_human": _human_when(entry.get("at")),
    }


def _log_for(run_id: str) -> str | None:
    candidate = LOGS_DIR / f"queue_{run_id}.log"
    return candidate.name if candidate.exists() else None


def log_text(run_id: str, tail_lines: int = 400) -> dict[str, Any]:
    """The raw log for one night, for when the summary is not enough."""
    path = LOGS_DIR / f"queue_{run_id}.log"
    if not path.exists() or path.parent.resolve() != LOGS_DIR.resolve():
        raise FileNotFoundError(f"No log for run {run_id}")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return {
        "run_id": run_id,
        "file": path.name,
        "total_lines": len(lines),
        "truncated": len(lines) > tail_lines,
        "text": "\n".join(lines[-tail_lines:]),
    }


# --------------------------------------------------------------------------
# what is still waiting
# --------------------------------------------------------------------------

def queue_overview(sheet: str | None = None) -> dict[str, Any]:
    """The sheet, grouped by subject, with how far each one has got."""
    # scripts/ is not a package on the import path of the API process. Guarded
    # because this runs on every poll of the overview and an unguarded insert
    # would grow sys.path without bound.
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from scripts import queue_sheet as qs  # noqa: PLC0415

    path = resolve_sheet(sheet)
    if path is None:
        return {"exists": False, "subjects": [], "totals": {}, "sheets": []}

    ledger, _state, _stop = _companions(path)
    rows = qs.load(path)
    qs.apply_ledger(rows, qs.Ledger(ledger).latest())

    groups: dict[str, dict[str, Any]] = {}
    totals: dict[str, int] = {}
    for row in rows:
        name = f"{row.board} class {row.standard} {row.subject_name}"
        bucket = groups.setdefault(
            name,
            {"name": name, "standard": row.standard, "subject": row.subject_name,
             "board": row.board, "total": 0, "chapters": []},
        )
        state = row.status if row.is_enabled() else "disabled"
        bucket["total"] += 1
        bucket[state] = bucket.get(state, 0) + 1
        totals[state] = totals.get(state, 0) + 1
        bucket["chapters"].append(
            {
                "chapter": row.chapter_number,
                "title": row.document_title,
                "status": state,
                "extraction_id": row.extraction_id,
                "pages": row.pages,
                "md_chars": row.md_chars,
                "attempts": row.attempts,
                "error": row.last_error,
                "pdf_url": row.pdf_url,
            }
        )

    for bucket in groups.values():
        bucket["chapters"].sort(key=lambda c: c["chapter"] or 0)
        settled = bucket.get("done", 0) + bucket.get("skipped", 0)
        bucket["settled"] = settled
        bucket["percent"] = round(100 * settled / bucket["total"]) if bucket["total"] else 0

    return {
        "exists": True,
        "sheet": path.name,
        "sheets": [p.name for p in list_sheets()],
        "subjects": sorted(groups.values(), key=lambda b: b["name"]),
        "totals": totals,
        "total_rows": len(rows),
        "pending": totals.get("pending", 0) + totals.get("failed", 0) + totals.get("extracted", 0),
    }
