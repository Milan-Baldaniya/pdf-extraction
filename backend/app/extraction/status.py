"""In-memory extraction status tracking for development and single-worker runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ExtractionStatus:
    job_id: str
    state: str
    message: str
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = field(default_factory=dict)


_STATUSES: dict[str, ExtractionStatus] = {}


def update_status(
    job_id: str,
    state: str,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> ExtractionStatus:
    status = ExtractionStatus(
        job_id=job_id,
        state=state,
        message=message,
        metadata=metadata or {},
    )
    _STATUSES[job_id] = status
    return status


def get_status(job_id: str) -> ExtractionStatus | None:
    return _STATUSES.get(job_id)
