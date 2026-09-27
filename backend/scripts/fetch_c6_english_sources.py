"""Mirror the Class 6 English (Poorvi) question sources into data/qbank/mirror.

    python -m scripts.fetch_c6_english_sources          # report only
    python -m scripts.fetch_c6_english_sources --get    # download

Three independent studentbro families, all commercial editorial content:

  (a) ncert_solutions  5 unit files, ~162 pages, clean ASCII text layer,
                       "Question N." / "Answer:" markers.
  (b) mcq_large        Units 1-2 only, the richest English material found,
                       "Ans. : (D) ..." with both letter and value.
  (c) mcq_short        Units 2-5, "Ans. :" markers. The Unit 1 file of this
                       series is image-only (69 characters of text) and is
                       deliberately absent from the table below.

EVERY FILE IS CHECKED AGAINST THE GET RESPONSE'S OWN Content-Length. A reset
connection yields a short file that opens in a reader, renders its first pages
and looks exactly like a scan or a corrupt PDF -- one source this week was 48%
short and had been written off as image-only. A byte count that disagrees with
the header is deleted rather than kept, so a retry starts clean.

The doubled `.pdf.pdf` in the (a) URLs is not a typo; the server stores them
that way and the single-extension form 404s.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests  # noqa: E402

MIRROR = Path(__file__).resolve().parents[1] / "data" / "qbank" / "mirror" / "studentbro"
BASE = "https://studentbro.in/upload/pdf/"

# local name, url path, family, unit
SOURCES: list[tuple[str, str, str, int]] = [
    ("c6_english_sol_u1.pdf",
     "6937d96aa2497_Unit%201%20-%20Fables%20and%20Folk%20Tales.pdf.pdf", "sol", 1),
    ("c6_english_sol_u2.pdf",
     "6937d99b99b0a_Unit%202%20-%20Friendship.pdf.pdf", "sol", 2),
    ("c6_english_sol_u3.pdf",
     "6937d9b98ff7d_Unit%203%20-%20Nurturing%20Nature.pdf.pdf", "sol", 3),
    ("c6_english_sol_u4.pdf",
     "6937da1db02c7_Unit%204%20-%20Sports%20and%20Wellness.pdf.pdf", "sol", 4),
    ("c6_english_sol_u5.pdf",
     "6937da47966bc_Unit%205%20-%20Culture%20and%20Tradition.pdf.pdf", "sol", 5),
    ("c6_english_mcqbig_u1.pdf",
     "6a7eca7ac2b6f_1._Fables_and_Folk_Tales.pdf", "mcqbig", 1),
    ("c6_english_mcqbig_u2.pdf",
     "6a7ecab887a16_2._Friendship.pdf", "mcqbig", 2),
    ("c6_english_mcq_u2.pdf",
     "6a101fb0d33f6_Ch_-_2_Friendship_-_MCQ.pdf", "mcq", 2),
    ("c6_english_mcq_u3.pdf",
     "6a102043119cb_Ch_-_3_Nurturing_Nature_-_MCQ.pdf", "mcq", 3),
    ("c6_english_mcq_u4.pdf",
     "6a1020abe234d_Ch_-_4_Sports_and_Wellness_-_MCQ.pdf", "mcq", 4),
    ("c6_english_mcq_u5.pdf",
     "6a10212eaa073_Ch_-_5_Culture_and_Tradition_-_MCQ.pdf", "mcq", 5),
]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")


def url_for(path: str) -> str:
    return BASE + path


def fetch(name: str, path: str) -> tuple[str, int]:
    """Download one file, verifying the byte count against Content-Length."""
    dest = MIRROR / name
    url = url_for(path)
    with requests.get(url, headers={"User-Agent": UA}, timeout=180,
                      stream=True) as resp:
        resp.raise_for_status()
        declared = resp.headers.get("Content-Length")
        body = resp.content
    got = len(body)
    if declared is not None and int(declared) != got:
        return (f"SHORT: Content-Length {int(declared):,} but read {got:,}", got)
    if not body.startswith(b"%PDF"):
        return (f"NOT A PDF: starts {body[:8]!r}", got)
    dest.write_bytes(body)
    return ("ok" if declared is not None else "ok (no Content-Length)", got)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--get", action="store_true", help="actually download")
    a = ap.parse_args()

    MIRROR.mkdir(parents=True, exist_ok=True)
    print(f"mirror: {MIRROR}\n")
    print(f"  {'file':<28} {'fam':<7} {'u':>2} {'bytes':>12}  status")
    print("  " + "-" * 78)
    for name, path, fam, unit in SOURCES:
        dest = MIRROR / name
        if dest.exists() and dest.stat().st_size > 0:
            raw = dest.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()[:12]
            print(f"  {name:<28} {fam:<7} {unit:>2} {len(raw):>12,}  have, sha {sha}")
            continue
        if not a.get:
            print(f"  {name:<28} {fam:<7} {unit:>2} {'-':>12}  would download")
            continue
        try:
            status, got = fetch(name, path)
        except Exception as exc:
            status, got = f"{type(exc).__name__}: {str(exc)[:50]}", 0
        print(f"  {name:<28} {fam:<7} {unit:>2} {got:>12,}  {status}")
    if not a.get:
        print("\nreport only -- re-run with --get")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
