"""Mirror the NCERT Class X Health and Physical Education textbook.

    python -m scripts.fetch_ncert_c10_hpe            # list what it would fetch
    python -m scripts.fetch_ncert_c10_hpe --apply

NCERT serves this book one chapter per PDF under the book code `jehp1`:
`jehp1ps.pdf` is the prelims (cover, contents, syllabus) and `jehp101.pdf` ..
`jehp113.pdf` are the thirteen chapters.

EVERY DOWNLOAD IS CHECKED AGAINST THE GET RESPONSE'S OWN Content-Length, not a
HEAD. ncert.nic.in answers HEAD with `Content-Length: 0` on some paths, so a
HEAD-based check would call a truncated file complete. A short read raises and
the partial file is not left behind under its final name -- a 48%-short PDF
looks exactly like one that needs OCR, and that mistake has already cost a day
this week. Where the server sends no Content-Length at all the file is kept but
flagged `unverified` in the report, so it is never silently treated as checked.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://ncert.nic.in/textbook/pdf/"
BOOK = "jehp1"
# ps = prelims (contents page lives here), then one file per chapter.
PARTS = ["ps"] + [f"{n:02d}" for n in range(1, 14)]

# Chapters 6, 8 and 13 were uploaded with a DOUBLE DOT before the extension --
# `jehp106..pdf`. The site's own script builds `pm + "06.pdf"`, so NCERT's own
# viewer link for those three chapters is broken and the obvious URL answers a
# flat 404. Nothing about that 404 says "typo in the upload": it looks exactly
# like a chapter the book does not have. The complete-book zip
# (`jehp1dd.zip`) is what revealed the real names. The zip's copy of chapter 13
# is also an older, smaller build than the live file, so the three are fetched
# from the live double-dot URLs and not unpacked from the zip -- the mirrored
# bytes then match the URL recorded in `document_extractions.pdf_url`.
ODD_NAMES = {"06": "jehp106..pdf", "08": "jehp108..pdf", "13": "jehp113..pdf"}

MIRROR = Path(__file__).resolve().parents[1] / "data" / "qbank" / "mirror" / "ncert_c10_hpe"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def fetch(url: str, dest: Path) -> tuple[int, str, str]:
    """Download `url` to `dest`, verifying against the GET Content-Length.

    Returns (bytes written, sha256, verification note).
    """
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        declared = resp.headers.get("Content-Length")
        body = resp.read()
    if declared is not None:
        expected = int(declared)
        if len(body) != expected:
            raise IOError(
                f"truncated: got {len(body):,} of {expected:,} bytes "
                f"({len(body) / expected:.0%}) -- not written"
            )
        note = f"ok vs Content-Length {expected:,}"
    else:
        note = "UNVERIFIED (no Content-Length)"
    if not body.startswith(b"%PDF"):
        raise IOError(f"not a PDF: starts {body[:8]!r}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(body)
    tmp.replace(dest)
    return len(body), hashlib.sha256(body).hexdigest(), note


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", help="comma-separated part codes, e.g. ps,01,02")
    a = ap.parse_args()

    parts = PARTS
    if a.only:
        wanted = {x.strip() for x in a.only.split(",") if x.strip()}
        parts = [p for p in PARTS if p in wanted]

    MIRROR.mkdir(parents=True, exist_ok=True)
    print(f"mirror {MIRROR}")
    print(f"{'part':<5} {'bytes':>10}  {'sha256':<16}  note")
    print("-" * 78)
    failed = []
    for part in parts:
        name = ODD_NAMES.get(part, f"{BOOK}{part}.pdf")
        # Kept on disk under the regular name; the URL is what differs.
        dest = MIRROR / f"{BOOK}{part}.pdf"
        if not a.apply:
            state = "have" if dest.exists() else "would fetch"
            print(f"{part:<5} {'-':>10}  {'-':<16}  {state} {BASE + name}")
            continue
        if dest.exists() and dest.stat().st_size > 0:
            raw = dest.read_bytes()
            print(f"{part:<5} {len(raw):>10,}  {hashlib.sha256(raw).hexdigest()[:16]:<16}  "
                  f"already mirrored")
            continue
        try:
            size, sha, note = fetch(BASE + name, dest)
        except (urllib.error.URLError, urllib.error.HTTPError, IOError) as exc:
            print(f"{part:<5} {'-':>10}  {'-':<16}  FAILED {str(exc)[:60]}")
            failed.append(part)
            continue
        print(f"{part:<5} {size:>10,}  {sha[:16]:<16}  {note}")
    print("-" * 78)
    if failed:
        print(f"{len(failed)} part(s) failed: {', '.join(failed)}")
    if not a.apply:
        print("dry run -- pass --apply to download")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
