"""Generic in-memory background job runner.

Several operations in this service run far longer than a reverse proxy, load
balancer, or browser will hold a single request open:

* MinerU extraction — tens of minutes on CPU.
* The DeepSeek agent swarms — four chained LLM calls per concept, fanned out
  across every concept in a chapter.
* Macro/meso/micro lesson planning — LLM calls per period.

Those endpoints accept the work, hand back a job id immediately, and run the
job detached. Clients poll ``GET /api/status/{job_id}`` and then read
``GET /api/jobs/{job_id}/result``.

The registry lives in process memory, so the API must run with a SINGLE
worker. With more than one, a poll can land on a process that never saw the
job and would 404.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.utils.config import settings
from app.utils.file_utils import generate_job_id

logger = logging.getLogger(__name__)

# A job in one of these states will never change again.
TERMINAL_STATES = frozenset({"completed", "failed"})

# How long a finished job stays readable before it is swept. Long enough for a
# client to reconnect after a browser refresh, short enough to bound memory.
JOB_RETENTION_SECONDS = 24 * 60 * 60


@dataclass
class Job:
    job_id: str
    state: str
    message: str
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = field(default_factory=dict)
    # Set only once the job reaches "completed".
    result: Any | None = None
    # Wall clock used for eviction, kept separate from the ISO string above so
    # the sweep does not have to re-parse it.
    touched_at: float = field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp()
    )


_JOBS: dict[str, Job] = {}
_LOCK = threading.Lock()

# Background tasks must stay referenced or the event loop may garbage-collect
# them mid-run; entries are discarded by the done-callback in spawn().
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()

_llm_semaphore: asyncio.Semaphore | None = None


def _evict_expired(now: float) -> None:
    """Drop terminal jobs older than the retention window. Caller holds _LOCK."""
    cutoff = now - JOB_RETENTION_SECONDS
    stale = [
        job_id
        for job_id, job in _JOBS.items()
        if job.state in TERMINAL_STATES and job.touched_at < cutoff
    ]
    for job_id in stale:
        _JOBS.pop(job_id, None)


def update_status(
    job_id: str,
    state: str,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> Job:
    """Record the latest state for a job, preserving any result already set."""
    now = datetime.now(timezone.utc)
    with _LOCK:
        previous = _JOBS.get(job_id)
        job = Job(
            job_id=job_id,
            state=state,
            message=message,
            updated_at=now.isoformat(),
            metadata=metadata or {},
            result=previous.result if previous else None,
            touched_at=now.timestamp(),
        )
        _JOBS[job_id] = job
        _evict_expired(now.timestamp())
        return job


def set_result(job_id: str, result: Any) -> None:
    """Attach a finished payload to a job."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job.result = result


def get_status(job_id: str) -> Job | None:
    with _LOCK:
        return _JOBS.get(job_id)


def get_result(job_id: str) -> Any | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return job.result if job else None


def spawn(coro: Awaitable[Any]) -> None:
    """Start a detached background task and keep it referenced until it ends."""
    task = asyncio.create_task(coro)  # type: ignore[arg-type]
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


def llm_semaphore() -> asyncio.Semaphore:
    """Cap concurrent LLM jobs so a burst cannot exhaust DeepSeek rate limits."""
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(max(1, settings.max_concurrent_llm_jobs))
    return _llm_semaphore


async def _execute(
    job_id: str,
    label: str,
    factory: Callable[[], Awaitable[Any]],
    semaphore: asyncio.Semaphore | None,
) -> None:
    """Run one job to completion. Never raises: the job status is the only
    channel back to the client."""
    guard = semaphore if semaphore is not None else nullcontext()
    try:
        async with guard:
            update_status(job_id, "running", f"{label} in progress")
            result = await factory()
        set_result(job_id, result)
        update_status(job_id, "completed", f"{label} completed")
        logger.info("Job %s - %s completed", job_id, label)
    except Exception as exc:
        logger.exception("Job %s - %s failed", job_id, label)
        # Handlers reused as jobs still raise HTTPException; its str() is
        # "422: detail", so unwrap it for a message worth showing a user.
        detail = getattr(exc, "detail", None)
        message = str(detail if detail is not None else exc) or f"{label} failed"
        update_status(job_id, "failed", message, {"error": message})


def submit(
    label: str,
    factory: Callable[[], Awaitable[Any]],
    *,
    semaphore: asyncio.Semaphore | None = None,
) -> str:
    """Queue an awaitable as a background job and return its id.

    ``factory`` is called inside the job rather than awaited by the caller, so
    no work starts until the job actually runs.
    """
    job_id = generate_job_id()
    update_status(job_id, "queued", f"{label} queued")
    spawn(_execute(job_id, label, factory, semaphore))
    logger.info("Job %s - queued %s", job_id, label)
    return job_id


def describe(job: Job) -> dict[str, Any]:
    """Serialise a job for the status endpoint."""
    return {
        "job_id": job.job_id,
        "state": job.state,
        "message": job.message,
        "updated_at": job.updated_at,
        "metadata": job.metadata,
        "done": job.state in TERMINAL_STATES,
        "result_ready": job.result is not None,
    }


def accepted(job_id: str) -> dict[str, Any]:
    """Standard 202 body pointing at where to poll."""
    return {
        "job_id": job_id,
        "state": "queued",
        "status_url": f"/api/status/{job_id}",
        "result_url": f"/api/jobs/{job_id}/result",
    }
