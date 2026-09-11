"""Read text that is printed inside extracted figures.

MinerU writes figures out as image files and does not look inside them, so
a graph's axis labels, the numbers on a number line, or the coordinates on a
grid never reach `md_content`. For a maths question bank that is the
difference between a usable item and an unanswerable one: "find the distance
between the two insects" is meaningless without the values on the plot.

This module runs MinerU's own bundled PyTorch/Paddle recogniser over the
extracted image files. Reusing that engine rather than adding a second OCR
dependency means the language handling, the model weights and the
PP-OCRv5 dictionary patches applied in `app.utils.mineru_compat` all stay
consistent with the main extraction pass.

Every failure path here is non-fatal. Figure OCR is an enrichment: if the
engine cannot load, the extraction still succeeds with `ocr_text: None`.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path
from typing import Any

from app.utils.config import settings

logger = logging.getLogger(__name__)

# Engine construction loads detector + recogniser weights and costs seconds.
# One instance per language, reused for every image in every job.
_ENGINES: dict[str, Any] = {}
_ENGINE_LOCK = threading.Lock()
_ENGINE_FAILED: set[str] = set()

# Below this the recogniser mostly returns noise from bullets, rules and
# decorative glyphs, at full model cost.
_MIN_CONFIDENCE = 0.55


def sha256_file(path: Path, *, chunk_size: int = 1 << 20) -> str | None:
    """Content hash of a file, used as the stable identity of an asset."""
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(chunk_size), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as exc:
        logger.debug("Could not hash %s: %s", path, exc)
        return None


def _normalise_lang(lang: str | None) -> str:
    """Map an extraction language onto one the bundled recogniser accepts."""
    value = (lang or "").strip().lower()
    if not value or value == "auto":
        return "en"
    # The Devanagari and Latin recognisers cover the Indian-curriculum cases;
    # anything else falls through to the engine's own validation.
    if value in {"hi", "mr", "ne", "sa", "devanagari"}:
        return "devanagari"
    if value in {"en", "english"}:
        return "en"
    return value


def _get_engine(lang: str) -> Any | None:
    if lang in _ENGINE_FAILED:
        return None
    engine = _ENGINES.get(lang)
    if engine is not None:
        return engine

    with _ENGINE_LOCK:
        # Re-check: another thread may have built it while we waited.
        engine = _ENGINES.get(lang)
        if engine is not None:
            return engine
        if lang in _ENGINE_FAILED:
            return None
        try:
            from magic_pdf.model.sub_modules.ocr.paddleocr2pytorch.pytorch_paddle import (
                PytorchPaddleOCR,
            )

            engine = PytorchPaddleOCR(lang=lang)
            _ENGINES[lang] = engine
            logger.info("Figure OCR engine ready (lang=%s)", lang)
            return engine
        except Exception as exc:
            # Mark failed so we do not pay the import/load cost per image.
            _ENGINE_FAILED.add(lang)
            logger.warning("Figure OCR unavailable for lang=%s: %s", lang, exc)
            return None


def _load_bgr(path: Path):
    """Decode an image file into the BGR ndarray the recogniser expects.

    The bundled engine asserts that a str is an acceptable input but never
    actually loads one — `preprocess_image` goes straight to `.shape` and
    raises AttributeError. Decoding here also sidesteps `cv2.imread`, which
    silently returns None for non-ASCII Windows paths.
    """
    try:
        import cv2
        import numpy as np

        buffer = np.frombuffer(path.read_bytes(), dtype=np.uint8)
        image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        if image is None:
            logger.debug("Could not decode image %s", path.name)
        return image
    except Exception as exc:
        logger.warning("Could not load image %s for OCR: %s", path.name, exc)
        return None


def _image_pixels(path: Path) -> int:
    try:
        from PIL import Image

        with Image.open(path) as img:
            width, height = img.size
        return int(width) * int(height)
    except Exception:
        return 0


def read_image_text(path: Path, *, lang: str = "en") -> dict[str, Any] | None:
    """OCR a single figure.

    Returns {"text", "line_count", "mean_confidence"} or None when the image
    was skipped, unreadable, or contained no confident text.
    """
    engine = _get_engine(_normalise_lang(lang))
    if engine is None:
        return None

    image = _load_bgr(path)
    if image is None:
        return None

    try:
        raw = engine.ocr(image, det=True, rec=True)
    except Exception as exc:
        # Warn, not debug. A recogniser that has started throwing would
        # otherwise silently blank out every figure in every chapter while
        # the extraction still reported success.
        logger.warning("Figure OCR failed on %s: %s", path.name, exc)
        return None

    # Shape is [[ [box, (text, score)], ... ]] — one entry per input image.
    if not raw or not isinstance(raw, list):
        return None
    page = raw[0]
    if not page:
        return None

    lines: list[str] = []
    scores: list[float] = []
    for entry in page:
        try:
            _box, recognised = entry[0], entry[1]
            text = str(recognised[0]).strip()
            score = float(recognised[1])
        except (IndexError, TypeError, ValueError):
            continue
        if not text or score < _MIN_CONFIDENCE:
            continue
        lines.append(text)
        scores.append(score)

    if not lines:
        return None

    return {
        "text": "\n".join(lines),
        "line_count": len(lines),
        "mean_confidence": round(sum(scores) / len(scores), 4),
    }


def enrich_manifest_with_ocr(
    manifest: list[dict[str, Any]],
    output_root: Path,
    *,
    lang: str = "en",
) -> dict[str, int]:
    """Fill `ocr_text` on each manifest entry, in place.

    Returns counters describing what actually ran, so the caller can record
    honest diagnostics rather than implying every figure was read.
    """
    stats = {"considered": 0, "ocr_attempted": 0, "ocr_with_text": 0, "skipped_small": 0, "skipped_cap": 0}
    if not settings.image_ocr_enabled or not manifest:
        return stats

    budget = max(0, int(settings.image_ocr_max_images))

    for item in manifest:
        if not isinstance(item, dict):
            continue
        stats["considered"] += 1

        relative = item.get("relative_path") or item.get("file_name")
        if not relative:
            continue
        path = output_root / str(relative)
        if not path.exists():
            continue

        # Hash regardless of OCR — it is the asset's durable identity and is
        # what lets a figure survive the output directory being cleaned.
        if not item.get("sha256"):
            digest = sha256_file(path)
            if digest:
                item["sha256"] = digest

        pixels = int(item.get("width") or 0) * int(item.get("height") or 0)
        if not pixels:
            pixels = _image_pixels(path)
        if pixels and pixels < int(settings.image_ocr_min_pixels):
            stats["skipped_small"] += 1
            item["ocr_text"] = None
            continue

        if stats["ocr_attempted"] >= budget:
            stats["skipped_cap"] += 1
            item["ocr_text"] = None
            continue

        stats["ocr_attempted"] += 1
        result = read_image_text(path, lang=lang)
        if result:
            item["ocr_text"] = result["text"]
            item["ocr_line_count"] = result["line_count"]
            item["ocr_confidence"] = result["mean_confidence"]
            stats["ocr_with_text"] += 1
        else:
            item["ocr_text"] = None

    if stats["skipped_cap"]:
        logger.warning(
            "Figure OCR stopped after %s images (IMAGE_OCR_MAX_IMAGES); %s were not read.",
            budget,
            stats["skipped_cap"],
        )
    return stats
