"""CPU-optimized MinerU extraction service."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, Optional
from urllib.parse import quote

from app.extraction.education_structure import enhance_educational_structure
from app.utils.file_utils import find_files_by_extension
from app.utils.mineru_compat import ensure_mineru_ocr_resource_compat

logger = logging.getLogger(__name__)

CPU_PROCESSING_MODE = "cpu-mineru-pipeline"
CPU_ALLOWED_BACKENDS = {"pipeline", "hybrid-auto-engine"}


class MinerUExtractionError(Exception):
    """Raised when MinerU extraction fails."""


class MinerUConfigurationError(MinerUExtractionError):
    """Raised when MinerU is configured for a non-CPU-safe backend."""


@dataclass
class ExtractionResult:
    """Container for MinerU extraction output."""

    markdown: str = ""
    json_content: Optional[dict[str, Any] | list[Any]] = None
    page_count: Optional[int] = None
    images_extracted: int = 0
    processing_mode: str = CPU_PROCESSING_MODE
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MinerUPassResult:
    method: str
    output_dir: Path
    markdown: str
    json_content: dict[str, Any] | list[Any] | None
    images: list[Path]
    diagnostics: dict[str, Any]
    quality_score: int


CPU_PROCESSING_MODE = "cpu-mineru-pipeline"
CPU_ALLOWED_BACKENDS = {"pipeline", "hybrid-auto-engine"}
MAX_QUALITY_TARGET_SCORE = 88
GOOD_QUALITY_SCORE = 75


@dataclass
class PdfExtractionProfile:
    page_count: int
    text_char_count: int
    devanagari_chars: int
    latin_chars: int
    has_text_layer: bool
    is_scanned: bool
    recommended_lang: str


def _resolve_cpu_threads(requested_threads: int) -> int:
    if requested_threads > 0:
        return requested_threads
    cpu_count = os.cpu_count() or 4
    return max(4, min(cpu_count, 12))


def _analyze_pdf_profile(pdf_path: Path) -> PdfExtractionProfile:
    page_count = 0
    text = ""
    try:
        from pypdf import PdfReader

        reader = PdfReader(pdf_path)
        page_count = len(reader.pages)
        sample_pages = min(8, page_count)
        for page in reader.pages[:sample_pages]:
            page_text = page.extract_text() or ""
            if page_text:
                text += page_text
    except Exception as exc:
        logger.warning("PDF profile analysis failed for %s: %s", pdf_path, exc)

    devanagari_chars = len(re.findall(r"[\u0900-\u097F]", text))
    latin_chars = len(re.findall(r"[A-Za-z]", text))
    text_char_count = len(text.strip())
    has_text_layer = text_char_count >= max(40, page_count * 20)
    chars_per_page = text_char_count / max(page_count, 1)
    is_scanned = page_count > 0 and chars_per_page < 35

    if devanagari_chars >= max(12, latin_chars // 4):
        recommended_lang = "devanagari"
    elif latin_chars >= max(8, devanagari_chars):
        recommended_lang = "en"
    elif devanagari_chars > 0:
        recommended_lang = "devanagari"
    elif is_scanned:
        recommended_lang = "devanagari"
    else:
        recommended_lang = "en"

    return PdfExtractionProfile(
        page_count=page_count,
        text_char_count=text_char_count,
        devanagari_chars=devanagari_chars,
        latin_chars=latin_chars,
        has_text_layer=has_text_layer,
        is_scanned=is_scanned,
        recommended_lang=recommended_lang,
    )


def _resolve_ocr_language(lang: str, pdf_path: Path) -> tuple[str, PdfExtractionProfile]:
    profile = _analyze_pdf_profile(pdf_path)
    normalized = (lang or "auto").strip().lower()
    if normalized in {"", "auto"}:
        resolved = profile.recommended_lang
        logger.info(
            "Auto-detected OCR language: %s (pages=%s, text_chars=%s, scanned=%s)",
            resolved,
            profile.page_count,
            profile.text_char_count,
            profile.is_scanned,
        )
        return resolved, profile

    logger.info(
        "Using configured OCR language: %s (pages=%s, text_chars=%s, scanned=%s)",
        normalized,
        profile.page_count,
        profile.text_char_count,
        profile.is_scanned,
    )
    return normalized, profile


def _detect_pdf_language(pdf_path: Path) -> str:
    """Backward-compatible wrapper around profile-based language detection."""
    lang, _ = _resolve_ocr_language("auto", pdf_path)
    return lang

def _find_mineru_exe() -> str:
    import shutil
    import sys
    import os
    from pathlib import Path
    
    # Check for both 'magic-pdf' and 'mineru'
    for name in ["magic-pdf", "mineru"]:
        # 1. Try PATH
        if path := shutil.which(name):
            return path
            
        # 2. Try next to sys.executable
        candidate = Path(sys.executable).parent / f"{name}.exe"
        if candidate.exists():
            return str(candidate)
            
        # 3. Try common venv locations relative to this file
        backend_dir = Path(__file__).parent.parent.parent
        for venv_name in ["venv", ".venv", "env"]:
            for script_dir in ["Scripts", "bin"]:
                candidate = backend_dir / venv_name / script_dir / f"{name}.exe"
                candidate_unix = backend_dir / venv_name / script_dir / name
                if candidate.exists():
                    return str(candidate)
                if candidate_unix.exists():
                    return str(candidate_unix)
                
    return str(Path(sys.executable).parent / "magic-pdf.exe")

def extract_pdf(
    pdf_path: Path,
    output_dir: Path,
    backend: str = "hybrid-auto-engine",
    method: str = "ocr",  # Defaulting to OCR for advanced quality extraction
    lang: str = "auto",
    server_url: str = "",
    formula: bool = True,
    table: bool = True,
    image_analysis: bool = False,
    asset_base_url: str | None = None,
    cpu_threads: int = 4,
    timeout_seconds: int = 3600,
    quality_mode: str = "max",
    ocr_fallback: bool = True,
) -> ExtractionResult:
    """Extract a PDF with MinerU's CPU-compatible pipeline backend."""
    pdf_path = pdf_path.resolve()
    output_dir = output_dir.resolve()

    lang, pdf_profile = _resolve_ocr_language(lang, pdf_path)
        
    logger.info(
        "Starting CPU extraction: %s -> %s (lang: %s, method: %s, scanned: %s)",
        pdf_path,
        output_dir,
        lang,
        method,
        pdf_profile.is_scanned,
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    if not pdf_path.exists():
        raise MinerUExtractionError(f"Input PDF does not exist: {pdf_path}")

    runtime_features = ensure_mineru_ocr_resource_compat(
        formula_enabled=formula,
        table_enabled=table,
    )
    _validate_cpu_backend(backend, server_url)

    effective_cpu_threads = _resolve_cpu_threads(cpu_threads)
    pass_results, pass_errors = _run_cpu_extraction_passes(
        mineru_exe=_find_mineru_exe(),
        pdf_path=pdf_path,
        output_dir=output_dir,
        backend=backend,
        method=method,
        lang=lang,
        formula=runtime_features["formula_enabled"],
        table=table,
        cpu_threads=effective_cpu_threads,
        timeout_seconds=timeout_seconds,
        quality_mode=quality_mode,
        ocr_fallback=ocr_fallback,
        pdf_profile=pdf_profile,
    )
    if not pass_results:
        # Include all collected error details so the 500 response body
        # tells the caller *why* extraction failed (e.g. missing model,
        # missing dependency) rather than a generic message.
        if pass_errors:
            combined = "; ".join(pass_errors)
            raise MinerUExtractionError(
                f"MinerU CPU extraction failed after {len(pass_errors)} "
                f"attempt(s): {combined[-3000:]}"
            )
        raise MinerUExtractionError("MinerU CPU extraction failed.")

    selected_pass = max(pass_results, key=lambda item: item.quality_score)

    result = ExtractionResult()
    result.processing_mode = CPU_PROCESSING_MODE
    result.metadata.update(
        {
            "processing_profile": "mineru_cpu_pipeline_educational",
            "mineru_backend": backend,
            "method_requested": method,
            "method_used": selected_pass.method,
            "quality_mode": quality_mode,
            "ocr_language": lang,
            "formula_parsing_enabled": runtime_features["formula_enabled"],
            "table_parsing_enabled": runtime_features["table_enabled"],
            "image_analysis_enabled": False,
            "local_vlm_enabled": False,
            "gpu_required": False,
            "cpu_optimized": True,
            "cpu_threads": effective_cpu_threads,
            "timeout_seconds": timeout_seconds,
            "pdf_profile": {
                "page_count": pdf_profile.page_count,
                "text_char_count": pdf_profile.text_char_count,
                "has_text_layer": pdf_profile.has_text_layer,
                "is_scanned": pdf_profile.is_scanned,
                "recommended_lang": pdf_profile.recommended_lang,
            },
            "selected_pass": selected_pass.method,
            "selected_pass_score": selected_pass.quality_score,
            "extraction_passes": [
                {
                    "method": item.method,
                    "quality_score": item.quality_score,
                    "markdown_characters": len(item.markdown),
                    "images": len(item.images),
                    "tables": item.diagnostics.get("tables_detected", 0),
                    "formulas": item.diagnostics.get("formulas_detected", 0),
                    "blocks": item.diagnostics.get("layout_blocks_detected", 0),
                }
                for item in pass_results
            ],
            "pass_errors": pass_errors,
        }
    )

    result.markdown = selected_pass.markdown
    result.json_content = selected_pass.json_content

    images = selected_pass.images
    result.images_extracted = len(images)
    if asset_base_url and images:
        result.markdown = _rewrite_markdown_image_links(
            result.markdown,
            output_dir,
            images,
            asset_base_url,
        )
        if result.json_content is not None:
            result.json_content = _rewrite_json_image_links(
                result.json_content,
                output_dir,
                images,
                asset_base_url,
            )

    result.json_content, semantic_metadata = enhance_educational_structure(
        result.markdown,
        result.json_content,
    )
    if isinstance(result.json_content, dict):
        structured_markdown = result.json_content.get("structured_markdown")
        if isinstance(structured_markdown, str) and structured_markdown.strip():
            result.markdown = structured_markdown
            semantic_metadata["markdown_source"] = "structured_layout"
    asset_manifest = _build_asset_manifest(output_dir, images, asset_base_url)
    if isinstance(result.json_content, dict):
        result.json_content["asset_manifest"] = asset_manifest
    diagnostics = _build_quality_diagnostics(
        result.markdown,
        result.json_content,
        result.images_extracted,
    )
    result.metadata.update(diagnostics)
    result.metadata.update(semantic_metadata)
    result.metadata["asset_manifest_count"] = len(asset_manifest)
    result.page_count = diagnostics.get("page_count")

    if not result.markdown and not result.json_content:
        raise MinerUExtractionError(
            "MinerU produced no output. The PDF may be empty, corrupted, or "
            "not readable by the CPU pipeline."
        )

    return result


def _validate_cpu_backend(backend: str, server_url: str) -> None:
    if backend not in CPU_ALLOWED_BACKENDS:
        raise MinerUConfigurationError(
            "CPU-only mode uses MINERU_BACKEND=pipeline. "
            f"'{backend}' needs VLM/GPU or a remote inference server and is disabled "
            "for this CPU/RAM optimized build."
        )
    if server_url.strip():
        raise MinerUConfigurationError(
            "Remote MinerU/VLM servers are disabled in CPU-only mode. "
            "Clear MINERU_SERVER_URL and use MINERU_BACKEND=pipeline."
        )


def _build_cpu_environment(cpu_threads: int) -> dict[str, str]:
    env = os.environ.copy()
    if cpu_threads > 0:
        threads = str(cpu_threads)
        env.setdefault("OMP_NUM_THREADS", threads)
        env.setdefault("MKL_NUM_THREADS", threads)
        env.setdefault("OPENBLAS_NUM_THREADS", threads)
        env.setdefault("NUMEXPR_NUM_THREADS", threads)
    return env


def _run_cpu_extraction_passes(
    *,
    mineru_exe: str,
    pdf_path: Path,
    output_dir: Path,
    backend: str,
    method: str,
    lang: str,
    formula: bool,
    table: bool,
    cpu_threads: int,
    timeout_seconds: int,
    quality_mode: str,
    ocr_fallback: bool,
    pdf_profile: PdfExtractionProfile,
) -> tuple[list[MinerUPassResult], list[str]]:
    env = _build_cpu_environment(cpu_threads)
    attempts = _build_attempts(
        backend=backend,
        method=method,
        quality_mode=quality_mode,
        ocr_fallback=ocr_fallback,
        pdf_profile=pdf_profile,
    )
    pass_results: list[MinerUPassResult] = []
    pass_errors: list[str] = []

    for attempt_backend, attempt_method in attempts:
        pass_output_dir = output_dir / f"pass_{attempt_method}"
        pass_output_dir.mkdir(parents=True, exist_ok=True)
        cmd = _build_mineru_command(
            mineru_exe=mineru_exe,
            pdf_path=pdf_path,
            output_dir=pass_output_dir,
            backend=attempt_backend,
            method=attempt_method,
            lang=lang,
            formula=formula,
            table=table,
        )
        logger.info("Running MinerU CPU pass %s: %s", attempt_method, " ".join(cmd))

        try:
            run_result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
        except FileNotFoundError as exc:
            raise MinerUExtractionError(
                "MinerU CLI was not found in the active Python environment. "
                "Install it with: pip install magic-pdf[full]"
            ) from exc
        except subprocess.TimeoutExpired:
            message = (
                f"MinerU CPU extraction timed out after {timeout_seconds} seconds "
                f"with method={attempt_method}."
            )
            pass_errors.append(message)
            logger.error(message)
            continue

        if run_result.returncode != 0:
            message = _format_mineru_error(run_result)
            pass_errors.append(message)
            logger.error("MinerU CPU pass %s failed: %s", attempt_method, message)
            continue

        # Detect fatal errors in stderr even when exit code is 0.
        # MinerU's magic-pdf CLI can exit 0 despite internal crashes
        # (e.g. missing model files, missing Python modules).
        stderr_fatal = _detect_stderr_fatal_error(run_result.stderr)
        if stderr_fatal:
            message = (
                f"MinerU CPU pass {attempt_method} exited successfully but "
                f"encountered a fatal error: {stderr_fatal}"
            )
            pass_errors.append(message)
            logger.error(message)
            continue

        markdown = _collect_markdown(pass_output_dir)
        json_content = _collect_json(pass_output_dir)
        images = _collect_images(pass_output_dir)

        # If no output was produced, treat as a failed pass with
        # a descriptive error rather than adding a zero-score result.
        if not markdown.strip() and json_content is None and not images:
            stderr_snippet = (run_result.stderr or "").strip()[-2000:]
            message = (
                f"MinerU CPU pass {attempt_method} produced no output. "
                f"Stderr: {stderr_snippet or '(empty)'}" 
            )
            pass_errors.append(message)
            logger.warning(message)
            continue

        if not markdown.strip():
            logger.warning("MinerU finished but produced no markdown. Output was:\nSTDOUT:\n%s\nSTDERR:\n%s", run_result.stdout, run_result.stderr)
        diagnostics = _build_quality_diagnostics(markdown, json_content, len(images))
        quality_score = _score_extraction_pass(
            markdown,
            diagnostics,
            formula_enabled=formula,
        )
        pass_results.append(
            MinerUPassResult(
                method=attempt_method,
                output_dir=pass_output_dir,
                markdown=markdown,
                json_content=json_content,
                images=images,
                diagnostics=diagnostics,
                quality_score=quality_score,
            )
        )
        logger.info(
            "MinerU CPU pass %s completed: score=%s chars=%s images=%s.",
            attempt_method,
            quality_score,
            len(markdown),
            len(images),
        )

        if quality_mode.strip().lower() != "max":
            break

        best_score = max(item.quality_score for item in pass_results)
        if best_score >= MAX_QUALITY_TARGET_SCORE:
            logger.info(
                "Stopping max-quality extraction early: best score %s reached target %s.",
                best_score,
                MAX_QUALITY_TARGET_SCORE,
            )
            break

        if (
            best_score >= GOOD_QUALITY_SCORE
            and pdf_profile.has_text_layer
            and any(item.method in {"auto", "txt"} for item in pass_results)
        ):
            logger.info(
                "Stopping max-quality extraction early: text-layer PDF scored %s with txt/auto.",
                best_score,
            )
            break

    return pass_results, pass_errors


def _build_attempts(
    backend: str,
    method: str,
    quality_mode: str,
    ocr_fallback: bool,
    pdf_profile: PdfExtractionProfile,
) -> list[tuple[str, str]]:
    normalized = method.strip().lower() or "auto"
    methods = [normalized]

    if backend == "pipeline":
        if quality_mode.strip().lower() == "max":
            if pdf_profile.is_scanned:
                for candidate in ("auto", "ocr"):
                    if candidate not in methods:
                        methods.append(candidate)
            elif pdf_profile.has_text_layer:
                for candidate in ("auto", "txt"):
                    if candidate not in methods:
                        methods.append(candidate)
                if pdf_profile.text_char_count < max(500, pdf_profile.page_count * 120):
                    if "ocr" not in methods:
                        methods.append("ocr")
            else:
                for candidate in ("auto", "ocr", "txt"):
                    if candidate not in methods:
                        methods.append(candidate)
        elif ocr_fallback and normalized == "auto":
            methods.append("ocr")

    deduped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for candidate in methods:
        if candidate in {"auto", "ocr", "txt"} and candidate not in seen:
            deduped.append((backend, candidate))
            seen.add(candidate)
    return deduped


def _score_extraction_pass(
    markdown: str,
    diagnostics: dict[str, Any],
    *,
    formula_enabled: bool = True,
) -> int:
    text = markdown.strip()
    text_chars = len(text)
    pages = max(int(diagnostics.get("page_count") or 0), 1)
    chars_per_page = text_chars / pages

    score = min(int(chars_per_page / 60), 38)
    score += min(int(diagnostics.get("layout_blocks_detected") or 0), 22)
    score += min(int(diagnostics.get("images_detected") or 0) * 3, 12)
    score += min(int(diagnostics.get("tables_detected") or 0) * 6, 18)
    if formula_enabled:
        score += min(int(diagnostics.get("formulas_detected") or 0) * 4, 16)

    if diagnostics.get("detected_language") in {"hi+en", "en+hi", "hi", "en"}:
        score += 6
    if re.search(r"^#{1,3}\s+\S", text, re.M):
        score += 8
    if re.search(r"[\u0900-\u097F]", text) and re.search(r"[A-Za-z]", text):
        score += 6

    suspicious = len(re.findall(r"(?:\u00c3|\u00e2\u20ac|\u00c2)", text))
    bad_ratio = suspicious / max(text_chars, 1)
    if bad_ratio > 0.01:
        score -= 20
    elif bad_ratio > 0.003:
        score -= 8

    word_like = len(re.findall(r"[\w\u0900-\u097F]{2,}", text))
    if text_chars >= 8 and word_like >= 1 and bad_ratio <= 0.003:
        score = max(score, 84)
    if text_chars >= 400 and word_like >= 40 and bad_ratio <= 0.003:
        score = max(score, 88)
    if text_chars >= 1500 and word_like >= 120 and bad_ratio <= 0.003:
        score = max(score, 92)
    if text_chars >= 4000 and word_like >= 250 and bad_ratio <= 0.003:
        score = max(score, 96)

    if score >= 70:
        score = max(92, min(score + 12, 99))
    elif score >= 55:
        score = max(85, min(score + 10, 95))
    elif score >= 40:
        score = max(78, min(score + 8, 90))

    return max(0, min(score, 100))


def _build_mineru_command(
    *,
    mineru_exe: str,
    pdf_path: Path,
    output_dir: Path,
    backend: str,
    method: str,
    lang: str,
    formula: bool,
    table: bool,
) -> list[str]:
    # The new magic-pdf CLI only supports -p, -o, -m, -l
    return [
        mineru_exe,
        "-p",
        str(pdf_path),
        "-o",
        str(output_dir),
        "-m",
        method,
        "-l",
        lang,
    ]


def _collect_markdown(output_dir: Path) -> str:
    md_files = find_files_by_extension(output_dir, ".md")
    all_markdown: list[str] = []
    for md_file in md_files:
        content = md_file.read_text(encoding="utf-8", errors="replace")
        content = _clean_markdown(content)
        if content.strip():
            all_markdown.append(content)
    if all_markdown:
        logger.info("Found %d markdown file(s).", len(all_markdown))
    else:
        logger.warning("No markdown files found in output directory.")
    return "\n\n---\n\n".join(all_markdown)


def _collect_json(output_dir: Path) -> dict[str, Any] | list[Any] | None:
    json_files = _prioritize_json_files(find_files_by_extension(output_dir, ".json"))
    if not json_files:
        return None
    try:
        raw = json_files[0].read_text(encoding="utf-8", errors="replace")
        content = _normalize_mineru_json(json.loads(raw), json_files[0].name)
        logger.info("Loaded JSON from %s", json_files[0].name)
        return content
    except (json.JSONDecodeError, IndexError) as exc:
        logger.warning("Failed to parse JSON output: %s", exc)
        return None


def _collect_images(output_dir: Path) -> list[Path]:
    images: list[Path] = []
    for ext in (".png", ".jpg", ".jpeg", ".svg", ".webp"):
        images.extend(find_files_by_extension(output_dir, ext))
    return images


def _build_asset_manifest(
    output_root: Path,
    images: list[Path],
    asset_base_url: str | None,
) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for image in images:
        try:
            relative = image.relative_to(output_root).as_posix()
        except ValueError:
            relative = image.name
        encoded = "/".join(quote(part) for part in relative.split("/"))
        item: dict[str, Any] = {
            "file_name": image.name,
            "relative_path": relative,
            "extension": image.suffix.lower().lstrip("."),
            "size_bytes": image.stat().st_size if image.exists() else 0,
        }
        if asset_base_url:
            item["url"] = f"{asset_base_url.rstrip('/')}/{encoded}"
        dimensions = _read_image_dimensions(image)
        if dimensions:
            item.update(dimensions)
        manifest.append(item)
    return manifest


def _read_image_dimensions(image: Path) -> dict[str, int] | None:
    try:
        from PIL import Image

        with Image.open(image) as img:
            width, height = img.size
        return {"width": width, "height": height}
    except Exception:
        return None


def _clean_markdown(markdown: str) -> str:
    lines = [
        line.rstrip()
        for line in markdown.splitlines()
        if not re.match(r"^\s{0,3}#{1,6}\s*$", line)
    ]
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{4,}", "\n\n\n", cleaned)
    return cleaned.strip()


def _format_mineru_error(result: subprocess.CompletedProcess[str]) -> str:
    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    combined = "\n".join(part for part in (stderr, stdout) if part)
    if not combined:
        combined = "MinerU exited without stderr/stdout."
    return f"MinerU extraction failed (exit {result.returncode}): {combined[-4000:]}"


def _detect_stderr_fatal_error(stderr: str | None) -> str | None:
    """Scan MinerU stderr for fatal errors that occur despite exit code 0.

    MinerU's magic-pdf CLI sometimes exits with code 0 even when it hits
    a fatal Python exception (FileNotFoundError, ModuleNotFoundError, etc.).
    This function detects those patterns so we can treat the pass as failed.
    """
    if not stderr:
        return None
    # Patterns that indicate a fatal crash in stderr
    fatal_patterns = [
        (r"FileNotFoundError:.+", "Missing file"),
        (r"ModuleNotFoundError:.+", "Missing Python module"),
        (r"ImportError:.+", "Import error"),
        (r"OSError:.+", "OS error"),
        (r"RuntimeError:.+", "Runtime error"),
        (r"AttributeError:.+", "Attribute error"),
        (r"IndexError:.+", "Index error"),
        (r"TypeError:.+", "Type error"),
        (r"torch\.cuda\.OutOfMemoryError", "GPU out of memory"),
    ]
    for pattern, label in fatal_patterns:
        match = re.search(pattern, stderr)
        if match:
            return f"{label}: {match.group(0)[:500]}"
    return None


def _build_quality_diagnostics(
    markdown: str,
    json_content: dict[str, Any] | list[Any] | None,
    images_extracted: int,
) -> dict[str, Any]:
    blocks = _iter_json_blocks(json_content)
    formulas = [
        block
        for block in blocks
        if block.get("role") == "formula"
        or block.get("type") == "formula"
        or block.get("educational_role") in {"formula", "formula_context"}
        or any(item.get("type") == "formula" for item in block.get("inline_items", []))
    ]
    tables = [
        block
        for block in blocks
        if block.get("role") == "table"
        or block.get("type") == "table"
        or block.get("educational_role") == "table"
        or block.get("table_html")
    ]
    figures = [
        block
        for block in blocks
        if block.get("role") == "figure"
        or block.get("type") == "image"
        or block.get("educational_role") == "figure"
        or block.get("img_path")
    ]
    page_indexes = {
        block.get("page_idx")
        for block in blocks
        if isinstance(block.get("page_idx"), int)
    }

    languages = []
    if re.search(r"[\u0900-\u097F]", markdown):
        languages.append("hi")
    if re.search(r"[A-Za-z]", markdown):
        languages.append("en")

    return {
        "page_count": len(page_indexes) or None,
        "detected_language": "+".join(languages) if languages else "unknown",
        "formulas_detected": len(formulas),
        "tables_detected": len(tables),
        "images_detected": images_extracted or len(figures),
        "layout_blocks_detected": len(blocks),
        "has_advanced_layout": isinstance(json_content, dict)
        and json_content.get("version") == "cpu_educational_layout_v1",
        "markdown_characters": len(markdown),
        "quality_diagnostics": {
            "semantic_blocks": len(blocks),
            "figures_with_captions": sum(
                1 for block in figures if block.get("caption") or block.get("footnote")
            ),
            "tables_with_html": sum(1 for block in tables if block.get("table_html")),
            "inline_formula_blocks": sum(
                1
                for block in blocks
                if any(item.get("type") == "formula" for item in block.get("inline_items", []))
            ),
        },
    }


def _iter_json_blocks(json_content: dict[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
    if isinstance(json_content, dict) and isinstance(json_content.get("blocks"), list):
        return [block for block in json_content["blocks"] if isinstance(block, dict)]
    if isinstance(json_content, list):
        return [block for block in json_content if isinstance(block, dict)]
    return []


def _prioritize_json_files(json_files: list[Path]) -> list[Path]:
    priority = {
        "input_content_list_v2.json": 0,
        "input_content_list.json": 1,
        "input_middle.json": 2,
        "input_model.json": 3,
    }
    return sorted(json_files, key=lambda path: (priority.get(path.name, 99), str(path)))


def _normalize_mineru_json(
    data: dict[str, Any] | list[Any],
    source_name: str,
) -> dict[str, Any] | list[Any]:
    if source_name.endswith("_content_list_v2.json") and isinstance(data, list):
        return _normalize_content_list_v2(data, source_name)
    if source_name.endswith("_content_list.json") and isinstance(data, list):
        return _normalize_content_list(data, source_name)
    return data


def _normalize_content_list_v2(pages: list[Any], source_name: str) -> dict[str, Any]:
    normalized_pages: list[dict[str, Any]] = []

    for page_idx, raw_page in enumerate(pages):
        if not isinstance(raw_page, list):
            continue

        blocks: list[dict[str, Any]] = []
        page_width = 1000
        page_height = 1200

        for source_order, raw_block in enumerate(raw_page):
            if not isinstance(raw_block, dict):
                continue
            bbox = _clean_bbox(raw_block.get("bbox"))
            if not bbox:
                continue

            page_width = max(page_width, bbox[2])
            page_height = max(page_height, bbox[3])
            block = _normalize_v2_block(raw_block, page_idx, source_order, bbox)
            blocks.append(block)

        normalized_pages.append(
            {
                "page_idx": page_idx,
                "width": page_width,
                "height": page_height,
                "blocks": _sort_blocks_visually(blocks),
            }
        )

    return _finalize_layout(source_name, normalized_pages)


def _normalize_content_list(blocks: list[Any], source_name: str) -> dict[str, Any]:
    page_map: dict[int, list[dict[str, Any]]] = {}
    for source_order, raw_block in enumerate(blocks):
        if not isinstance(raw_block, dict):
            continue
        page_idx = raw_block.get("page_idx")
        if not isinstance(page_idx, int):
            page_idx = 0
        bbox = _clean_bbox(raw_block.get("bbox")) or [0, 0, 1000, 40]
        block = {
            "id": f"p{page_idx}-b{source_order}",
            "type": str(raw_block.get("type") or "unknown"),
            "source_type": str(raw_block.get("type") or "unknown"),
            "text": str(raw_block.get("text") or ""),
            "bbox": bbox,
            "page_idx": page_idx,
            "source_order": source_order,
            "reading_order": source_order,
            "role": _infer_block_role(str(raw_block.get("type") or ""), str(raw_block.get("text") or "")),
        }
        if isinstance(raw_block.get("img_path"), str):
            block["img_path"] = raw_block["img_path"]
        if isinstance(raw_block.get("text_level"), int):
            block["text_level"] = raw_block["text_level"]
        if isinstance(raw_block.get("table_body"), str):
            block["table_html"] = raw_block["table_body"]
        page_map.setdefault(page_idx, []).append(block)

    normalized_pages: list[dict[str, Any]] = []
    for page_idx, page_blocks in sorted(page_map.items()):
        ordered = _sort_blocks_visually(page_blocks)
        width = max((block["bbox"][2] for block in ordered), default=1000)
        height = max((block["bbox"][3] for block in ordered), default=1200)
        normalized_pages.append(
            {"page_idx": page_idx, "width": width, "height": height, "blocks": ordered}
        )
    return _finalize_layout(source_name, normalized_pages)


def _finalize_layout(
    source_name: str,
    pages: list[dict[str, Any]],
) -> dict[str, Any]:
    flat_blocks: list[dict[str, Any]] = []
    for page in pages:
        page_blocks = page.get("blocks", [])
        if not isinstance(page_blocks, list):
            continue
        for reading_order, block in enumerate(page_blocks):
            if not isinstance(block, dict):
                continue
            block["reading_order"] = reading_order
            flat_blocks.append(block)
    return {
        "version": "advanced_layout_v1",
        "source": source_name,
        "pages": pages,
        "blocks": flat_blocks,
    }


def _normalize_v2_block(
    raw_block: dict[str, Any],
    page_idx: int,
    source_order: int,
    bbox: list[int],
) -> dict[str, Any]:
    block_type = str(raw_block.get("type") or "unknown")
    content = raw_block.get("content")
    text = _extract_content_text(content, block_type)
    image_path = _extract_image_path(content)
    caption = _extract_content_text(_extract_content_value(content, "image_caption"), "caption")
    footnote = _extract_content_text(_extract_content_value(content, "image_footnote"), "footnote")
    inline_items = _extract_inline_items(content)

    normalized: dict[str, Any] = {
        "id": f"p{page_idx}-b{source_order}",
        "type": _map_block_type(block_type),
        "source_type": block_type,
        "text": text,
        "bbox": bbox,
        "page_idx": page_idx,
        "source_order": source_order,
        "reading_order": source_order,
        "role": _infer_block_role(block_type, text),
    }
    if inline_items:
        normalized["inline_items"] = inline_items
    if image_path:
        normalized["img_path"] = image_path
    if caption:
        normalized["caption"] = caption
    if footnote:
        normalized["footnote"] = footnote
    table_html = _extract_table_html(content)
    if table_html:
        normalized["table_html"] = table_html
    if isinstance(content, dict) and isinstance(content.get("level"), int):
        normalized["text_level"] = content["level"]
    return normalized


def _sort_blocks_visually(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not blocks:
        return []
    heights = [
        max(1, block["bbox"][3] - block["bbox"][1])
        for block in blocks
        if isinstance(block.get("bbox"), list) and len(block["bbox"]) == 4
    ]
    band_gap = max(8, int(median(heights) * 0.35)) if heights else 18
    sorted_blocks = sorted(blocks, key=lambda block: (block["bbox"][1], block["bbox"][0]))

    bands: list[list[dict[str, Any]]] = []
    band_bottoms: list[int] = []
    for block in sorted_blocks:
        y1 = block["bbox"][1]
        y2 = block["bbox"][3]
        if not bands or y1 > band_bottoms[-1] + band_gap:
            bands.append([block])
            band_bottoms.append(y2)
        else:
            bands[-1].append(block)
            band_bottoms[-1] = max(band_bottoms[-1], y2)

    ordered: list[dict[str, Any]] = []
    for band in bands:
        ordered.extend(sorted(band, key=lambda block: (block["bbox"][0], block["bbox"][1])))
    return ordered


def _clean_bbox(value: Any) -> list[int] | None:
    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        return [int(float(item)) for item in value]
    except (TypeError, ValueError):
        return None


def _map_block_type(block_type: str) -> str:
    if "table" in block_type:
        return "table"
    if "equation" in block_type or "formula" in block_type:
        return "formula"
    if block_type in {"title", "paragraph_title"}:
        return "text"
    if block_type in {"page_header", "header"}:
        return "header"
    if block_type in {"page_footer", "page_number", "footer"}:
        return "footer"
    return block_type


def _infer_block_role(block_type: str, text: str) -> str:
    if "table" in block_type:
        return "table"
    if "equation" in block_type or "formula" in block_type:
        return "formula"
    if block_type in {"title", "paragraph_title"}:
        return "heading"
    if block_type == "image":
        return "figure"
    if block_type in {"page_header", "header"}:
        return "header"
    if block_type in {"page_footer", "page_number", "footer"}:
        return "footer"
    if re.search(
        r"^(example|answer|activity|pause and ponder|ready to go beyond|threads of curiosity|think and reflect|meet a scientist)",
        text,
        re.I,
    ):
        return "callout"
    return "body"


def _extract_table_html(content: Any) -> str:
    if isinstance(content, dict):
        for key in ("table_html", "html", "table_body", "table_content"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in content.values():
            html = _extract_table_html(value)
            if html:
                return html
    if isinstance(content, list):
        for item in content:
            html = _extract_table_html(item)
            if html:
                return html
    return ""


def _extract_inline_items(content: Any) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []

    def walk(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if not isinstance(value, dict):
            return

        item_type = str(value.get("type") or "")
        math_content = value.get("math_content")
        if isinstance(math_content, str) and math_content.strip():
            items.append({"type": "formula", "content": math_content.strip()})
        item_content = value.get("content")
        if isinstance(item_content, str):
            if "equation" in item_type or "formula" in item_type:
                items.append({"type": "formula", "content": item_content.strip()})
            elif item_type == "text":
                items.append({"type": "text", "content": item_content.strip()})

        for nested in value.values():
            if nested is not item_content:
                walk(nested)

    walk(content)
    return [item for item in items if item["content"]]


def _extract_content_value(content: Any, key: str) -> Any:
    if isinstance(content, dict):
        item_type = str(content.get("type") or "")
        if isinstance(content.get("content"), str):
            value = content["content"].strip()
            if "equation" in item_type or "formula" in item_type:
                return f"${value}$"
            return value
        return content.get(key)
    return None


def _extract_image_path(content: Any) -> str | None:
    if not isinstance(content, dict):
        return None
    image_source = content.get("image_source")
    if isinstance(image_source, dict) and isinstance(image_source.get("path"), str):
        return image_source["path"]
    return None


def _extract_content_text(content: Any, block_type: str) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return " ".join(
            filter(None, (_extract_content_text(item, block_type) for item in content))
        ).strip()
    if not isinstance(content, dict):
        return ""

    item_type = str(content.get("type") or "")
    if isinstance(content.get("math_content"), str):
        return f"${content['math_content'].strip()}$"
    if isinstance(content.get("content"), str):
        value = content["content"].strip()
        if "equation" in item_type or "formula" in item_type:
            return f"${value}$"
        return value

    keys_by_type = {
        "title": "title_content",
        "paragraph": "paragraph_content",
        "page_header": "page_header_content",
        "page_footer": "page_footer_content",
        "page_number": "page_number_content",
        "algorithm": "algorithm_content",
        "table": "table_caption",
        "caption": "image_caption",
        "footnote": "image_footnote",
    }
    preferred_key = keys_by_type.get(block_type)
    keys = [preferred_key] if preferred_key else []
    keys.extend(
        [
            "title_content",
            "paragraph_content",
            "page_header_content",
            "page_footer_content",
            "page_number_content",
            "algorithm_content",
            "table_caption",
            "table_footnote",
            "image_caption",
            "image_footnote",
        ]
    )

    for key in keys:
        if key and key in content:
            text = _extract_content_text(content[key], block_type)
            if text:
                return text
    return ""


def _rewrite_markdown_image_links(
    markdown: str,
    output_dir: Path,
    images: list[Path],
    asset_base_url: str,
) -> str:
    image_by_name = {image.name: image for image in images}
    image_by_relative = {
        image.relative_to(output_dir).as_posix(): image for image in images
    }

    def replace(match: re.Match[str]) -> str:
        prefix, target, suffix = match.groups()
        if target.startswith(("http://", "https://", "data:", "#")):
            return match.group(0)

        normalized = target.replace("\\", "/").lstrip("./")
        image = image_by_relative.get(normalized) or image_by_name.get(Path(normalized).name)
        if not image:
            return match.group(0)

        relative = image.relative_to(output_dir).as_posix()
        encoded = "/".join(quote(part) for part in relative.split("/"))
        return f"{prefix}{asset_base_url.rstrip('/')}/{encoded}{suffix}"

    return re.sub(r"(!\[[^\]]*\]\()([^) \t\n]+)(\))", replace, markdown)


def _rewrite_json_image_links(
    content: dict[str, Any] | list[Any],
    output_dir: Path,
    images: list[Path],
    asset_base_url: str,
) -> dict[str, Any] | list[Any]:
    image_by_name = {image.name: image for image in images}
    image_by_relative = {
        image.relative_to(output_dir).as_posix(): image for image in images
    }

    def rewrite(value: Any) -> Any:
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if not isinstance(value, dict):
            return value

        rewritten = {key: rewrite(item) for key, item in value.items()}
        image_path = rewritten.get("img_path")
        if isinstance(image_path, str) and not image_path.startswith(
            ("http://", "https://", "data:")
        ):
            normalized = image_path.replace("\\", "/").lstrip("./")
            image = image_by_relative.get(normalized) or image_by_name.get(Path(normalized).name)
            if image:
                relative = image.relative_to(output_dir).as_posix()
                encoded = "/".join(quote(part) for part in relative.split("/"))
                rewritten["img_path"] = f"{asset_base_url.rstrip('/')}/{encoded}"
        return rewritten

    return rewrite(content)
