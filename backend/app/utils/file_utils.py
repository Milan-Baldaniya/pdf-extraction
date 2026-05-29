"""File-system helpers for job directories and cleanup."""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


def ensure_directory(path: str | Path) -> Path:
    """Create a directory and parents if they do not exist."""
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def generate_job_id() -> str:
    """Return a short unique job identifier."""
    return uuid.uuid4().hex[:12]


def get_temp_pdf_path(tmp_dir: str, job_id: str) -> Path:
    """Return the temporary input PDF path for a job."""
    return ensure_directory(Path(tmp_dir) / job_id) / "input.pdf"


def get_output_dir(output_root: str, job_id: str) -> Path:
    """Return and create the output directory for a job."""
    return ensure_directory(Path(output_root) / job_id)


def cleanup_job(tmp_dir: str, output_root: str, job_id: str) -> None:
    """Remove temporary and output artifacts for a job."""
    for base in (tmp_dir, output_root):
        target = Path(base) / job_id
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
            logger.info("Cleaned up: %s", target)


def cleanup_temp_job(tmp_dir: str, job_id: str) -> None:
    """Remove only temporary input files for a job."""
    target = Path(tmp_dir) / job_id
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
        logger.info("Cleaned up temp files: %s", target)


def cleanup_all_temp(tmp_dir: str, output_root: str) -> None:
    """Remove all temporary and output directories, then recreate them."""
    for base in (tmp_dir, output_root):
        directory = Path(base)
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)
            logger.info("Purged directory: %s", directory)
        ensure_directory(directory)


def find_files_by_extension(directory: Path, ext: str) -> list[Path]:
    """Recursively find all files with a given extension."""
    return sorted(directory.rglob(f"*{ext}"))
