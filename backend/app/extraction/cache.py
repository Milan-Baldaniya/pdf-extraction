"""File hash and response cache helpers for extraction jobs."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from app.models.schemas import ExtractionResponse

logger = logging.getLogger(__name__)


def file_sha256(filepath: Path) -> str:
    hasher = hashlib.sha256()
    with filepath.open("rb") as file:
        for chunk in iter(lambda: file.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_cached_response(output_dir: str, file_hash: str) -> ExtractionResponse | None:
    cache_file = Path(output_dir).resolve() / "cache" / f"{file_hash}.json"
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        return ExtractionResponse(**data)
    except Exception as exc:
        logger.warning("Failed to load extraction cache for %s: %s", file_hash, exc)
        return None


def set_cached_response(
    output_dir: str,
    file_hash: str,
    response: ExtractionResponse,
) -> None:
    cache_dir = Path(output_dir).resolve() / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{file_hash}.json"
    try:
        cache_file.write_text(response.model_dump_json(), encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed to write extraction cache for %s: %s", file_hash, exc)
