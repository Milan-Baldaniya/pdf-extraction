"""
PDF download service - async download of remote PDFs to temporary storage.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import aiohttp

logger = logging.getLogger(__name__)

# Maximum PDF size we allow (200 MB)
MAX_PDF_SIZE_BYTES: int = 200 * 1024 * 1024

# Allowed content types for PDF files
ALLOWED_CONTENT_TYPES: set[str] = {
    "application/pdf",
    "application/octet-stream",
    "binary/octet-stream",
}

REQUEST_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,application/octet-stream,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "close",
}


class PDFDownloadError(Exception):
    """Raised when a PDF download fails."""


async def download_pdf(url: str, destination: Path) -> Path:
    """
    Download a PDF from *url* and save it to *destination*.

    Raises
    ------
    PDFDownloadError
        If the download fails for any reason (network, content-type, size ...).
    """
    logger.info("Downloading PDF from %s -> %s", url, destination)

    timeout = aiohttp.ClientTimeout(total=120)

    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=REQUEST_HEADERS) as session:
            async with session.get(str(url), allow_redirects=True) as response:
                if response.status != 200:
                    raise PDFDownloadError(
                        f"HTTP {response.status} when fetching PDF from {url}"
                    )

                # Content-type sanity check (some servers return octet-stream)
                content_type = response.content_type or ""
                if content_type and content_type not in ALLOWED_CONTENT_TYPES:
                    logger.warning(
                        "Unexpected content-type '%s' - proceeding anyway.",
                        content_type,
                    )

                # Size guard
                content_length = response.content_length
                if content_length and content_length > MAX_PDF_SIZE_BYTES:
                    raise PDFDownloadError(
                        f"PDF too large ({content_length / 1024 / 1024:.1f} MB). "
                        f"Max allowed is {MAX_PDF_SIZE_BYTES / 1024 / 1024:.0f} MB."
                    )

                # Stream to disk
                destination.parent.mkdir(parents=True, exist_ok=True)
                bytes_written = 0
                with open(destination, "wb") as fh:
                    async for chunk in response.content.iter_chunked(8192):
                        bytes_written += len(chunk)
                        if bytes_written > MAX_PDF_SIZE_BYTES:
                            raise PDFDownloadError("PDF exceeds maximum allowed size.")
                        fh.write(chunk)

                logger.info(
                    "Download complete - %s (%.2f MB)",
                    destination.name,
                    bytes_written / 1024 / 1024,
                )
                return destination

    except aiohttp.ClientError as exc:
        logger.warning("aiohttp download failed, retrying with urllib: %s", exc)
        try:
            return await asyncio.to_thread(_download_pdf_with_urllib, url, destination)
        except PDFDownloadError as fallback_exc:
            raise PDFDownloadError(
                f"Network error downloading PDF: {exc}; fallback also failed: {fallback_exc}"
            ) from fallback_exc


def _download_pdf_with_urllib(url: str, destination: Path) -> Path:
    request = Request(str(url), headers=REQUEST_HEADERS)

    try:
        with urlopen(request, timeout=120) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise PDFDownloadError(f"HTTP {status} when fetching PDF from {url}")

            content_type = response.headers.get_content_type() or ""
            if content_type and content_type not in ALLOWED_CONTENT_TYPES:
                logger.warning(
                    "Unexpected content-type '%s' from urllib fallback; proceeding anyway.",
                    content_type,
                )

            content_length_raw = response.headers.get("Content-Length")
            if content_length_raw:
                content_length = int(content_length_raw)
                if content_length > MAX_PDF_SIZE_BYTES:
                    raise PDFDownloadError(
                        f"PDF too large ({content_length / 1024 / 1024:.1f} MB). "
                        f"Max allowed is {MAX_PDF_SIZE_BYTES / 1024 / 1024:.0f} MB."
                    )

            destination.parent.mkdir(parents=True, exist_ok=True)
            bytes_written = 0
            with open(destination, "wb") as fh:
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    bytes_written += len(chunk)
                    if bytes_written > MAX_PDF_SIZE_BYTES:
                        raise PDFDownloadError("PDF exceeds maximum allowed size.")
                    fh.write(chunk)

            logger.info(
                "Download complete via urllib fallback - %s (%.2f MB)",
                destination.name,
                bytes_written / 1024 / 1024,
            )
            return destination

    except HTTPError as exc:
        raise PDFDownloadError(f"HTTP {exc.code} when fetching PDF from {url}") from exc
    except URLError as exc:
        raise PDFDownloadError(str(exc.reason)) from exc
    except OSError as exc:
        raise PDFDownloadError(str(exc)) from exc
