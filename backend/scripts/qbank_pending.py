"""What is sourced on disk, what is in the bank, and what stands between them.

    python -m scripts.qbank_pending

THREE STATES, NOT TWO. "On disk" and "in the bank" are often talked about as
though a question moves straight from one to the other and arrives mapped.
It does not:

  1 DOWNLOADED   a PDF in data/qbank/mirror. The count here is its answer
                 markers, which is an upper bound on what it can yield, not
                 a number of questions -- a marker can sit inside a table or
                 a combined key.
  2 PARSED       an item in a drafts JSON: stem, options, answer, validated.
                 Still nothing in the database.
  3 IN THE BANK  a row in lms_question_master. This is what an exam can draw
                 on, and it says NOTHING about mapping.
  4 MAPPED       concept_id on the sidecar, and CG/LO codes in
                 lms_question_outcome. A separate pass, run after loading.

So loading does not wait for mapping, and being in the bank does not mean
mapped. Today the bank holds far more rows than are mapped, and that gap is
reported here rather than hidden inside a single percentage.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import fitz  # noqa: E402

fitz.TOOLS.mupdf_display_errors(False)

MIRROR = Path(__file__).resolve().parents[1] / "data" / "qbank" / "mirror"
DRAFTS = Path(__file__).resolve().parent

MARKERS = re.compile(r"\bAns\s*[:.]|\bAAns|उत्तर|mmÙkj%|\bAnswer\s*:")

# Standing instructions, applied here so a blocked file is never counted as
# available work.
BLOCKED = {
    "c9_English_R2": "blocked at download",
    "c9_Hindi_R2": "blocked at download",
    "AI": "blocked", "IT": "blocked",
}
OFF_LIMITS = {
    "c10_Science": "Class 10 Science is done",
    "c10_Maths": "Class 10 Maths is in flight on another machine",
    "c10_Social": "Class 10 Social Science is in flight on another machine",
    "c10_CBSE_10th_Social": "Class 10 Social Science is in flight on another machine",
}


def note(name: str) -> str:
    for k, v in {**BLOCKED, **OFF_LIMITS}.items():
        if name.startswith(k) or f"_{k}_" in name:
            return v
    return ""


def main() -> int:
    print(__doc__.split("\n\n", 1)[1].rstrip() + "\n")

    print("DOWNLOADED -- answer markers per mirrored PDF")
    print(f"  {'file':<44} {'pages':>6} {'markers':>8}  note")
    print("  " + "-" * 92)
    avail = held = 0
    for p in sorted(MIRROR.rglob("*.pdf")):
        try:
            doc = fitz.open(p)
        except Exception:
            print(f"  {p.name[:44]:<44} {'?':>6} {'unreadable':>8}")
            continue
        n = 0
        for i in range(doc.page_count):
            try:
                n += len(MARKERS.findall(doc[i].get_text()))
            except Exception:
                continue
        pages = doc.page_count
        doc.close()
        why = note(p.name)
        if why:
            held += n
        else:
            avail += n
        print(f"  {p.name[:44]:<44} {pages:>6} {n:>8}  {why}")
    print("  " + "-" * 92)
    print(f"  available to work on {avail}, excluded by standing instruction {held}\n")

    print("PARSED -- items in drafts")
    print(f"  {'draft':<56} {'items':>7}")
    print("  " + "-" * 66)
    tot = 0
    for d in sorted(DRAFTS.rglob("drafts/*.json")):
        try:
            data = json.loads(d.read_text(encoding="utf-8"))
        except Exception:
            continue
        n = len(data.get("items") or [])
        tot += n
        print(f"  {str(d.relative_to(DRAFTS))[:56]:<56} {n:>7}")
    print("  " + "-" * 66)
    print(f"  {'total parsed':<56} {tot:>7}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
