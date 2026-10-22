"""Map printed folios to physical pages, and say where the book's extra pages are.

    python -m scripts.probe_qbook data/qbank/mirror/cbse9_science_qb2026.pdf
    python -m scripts.probe_qbook <pdf> --contents-page 4 --json out.json

These books interleave advertisements between chapters, so the gap between a
printed page number and its index in the PDF is NOT constant and cannot be
fitted. The Class 10 Science book was split by hand against an assumed offset
and pages 260-282 -- 23 printed pages, roughly 190 questions -- were dropped
out of chapter 6 without anything noticing. The loss surfaced weeks later, when
a human read the chapter and wrote a note in ch06.json.

So: read the folio off every page, build the real mapping, and treat a page
that carries no folio as a page the book declines to number -- which is exactly
what an advert is. Nothing here guesses.

Read-only. Prints the ranges a splitter needs and, with --json, writes them.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# A folio sits in the top or bottom margin. 8% of page height each end is
# generous enough for the variation across a 600-page book and tight enough
# that a question numbered "12." in the body is never mistaken for one.
MARGIN = 0.08
FOLIO = re.compile(r"^\d{1,4}$")
CONTENTS_LINE = re.compile(
    r"CHAP\s+(\d{1,2})\.\s*\n?(.+?)\s*\n?(\d{1,4})\s*-\s*(\d{1,4})", re.S
)


def folio_of(page: fitz.Page) -> int | None:
    """The printed folio, read off the running head, or None.

    This book prints it as the two tokens `page 40` at the top left, and only
    on even folios -- an odd page carries the chapter name and nothing else.
    Anchoring on the literal label rather than on "a number in the margin" is
    what keeps a question numbered "12." out of the map.
    """
    height = page.rect.height
    top = [w for w in page.get_text("words") if w[3] <= height * MARGIN]
    top.sort(key=lambda w: (round(w[1], 1), w[0]))
    for i, (_x0, _y0, _x1, _y1, word, *_rest) in enumerate(top):
        if word.strip().lower() != "page" or i + 1 >= len(top):
            continue
        nxt = top[i + 1][4].strip()
        if FOLIO.match(nxt):
            value = int(nxt)
            if 1 <= value <= 2000:
                return value
    return None


def build_folio_map(doc: fitz.Document) -> tuple[dict[int, int], dict[int, int]]:
    """folio -> physical index, and the anchors it was built from.

    Only even folios are printed, so the odd ones are filled in from their
    neighbour. That is arithmetic within a run of consecutive pages, not a
    fitted offset across the book -- the offset changes 24 times here, from 1
    to 46, which is exactly why fitting one mis-splits.
    """
    anchors = {}
    for i in range(doc.page_count):
        f = folio_of(doc[i])
        if f is not None and f not in anchors:
            anchors[f] = i

    folio_to_index = dict(anchors)
    for folio, index in anchors.items():
        # The page before an even folio carries the odd one before it, unless
        # something unnumbered sits between them -- in which case the previous
        # anchor is not one page back and we leave the odd folio unresolved
        # rather than invent a position for it.
        prev = folio - 1
        if prev >= 1 and prev not in folio_to_index and index - 1 >= 0:
            folio_to_index[prev] = index - 1
        nxt = folio + 1
        if nxt not in folio_to_index and index + 1 < doc.page_count:
            folio_to_index[nxt] = index + 1
    return folio_to_index, anchors


def read_contents(doc: fitz.Document, page_index: int) -> list[dict]:
    text = doc[page_index].get_text()
    out = []
    for m in CONTENTS_LINE.finditer(text):
        number, name, start, end = m.groups()
        out.append({
            "number": int(number),
            "name": " ".join(name.split()),
            "folio_start": int(start),
            "folio_end": int(end),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf")
    ap.add_argument("--contents-page", type=int, default=None,
                    help="0-based index; searched for when omitted")
    ap.add_argument("--json", help="write the resolved ranges here")
    a = ap.parse_args()

    doc = fitz.open(a.pdf)
    print(f"{a.pdf}: {doc.page_count} physical pages")

    idx = a.contents_page
    if idx is None:
        for i in range(min(30, doc.page_count)):
            if re.search(r"^\s*Contents\s*$", doc[i].get_text(), re.M | re.I):
                idx = i
                break
    if idx is None:
        raise SystemExit("no CONTENTS page found; pass --contents-page")
    chapters = read_contents(doc, idx)
    print(f"CONTENTS on physical page {idx}: {len(chapters)} chapters\n")

    folio_to_index, anchors = build_folio_map(doc)
    placed = set(folio_to_index.values())
    unnumbered = [i for i in range(doc.page_count) if i not in placed]

    print(f"printed folio anchors  : {len(anchors)} (even folios only)")
    print(f"folios resolved        : {len(folio_to_index)}")
    print(f"pages outside the map  : {len(unnumbered)}  (front matter + adverts)")

    # Where the offset changes is where the book inserted something. Printing
    # the runs is what makes an advert block visible instead of inferred.
    runs, start = [], None
    for i in range(doc.page_count):
        if i in set(unnumbered):
            start = i if start is None else start
        elif start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, doc.page_count - 1))
    print("\nunnumbered runs (physical index):")
    for lo, hi in runs:
        print(f"   {lo:>4}-{hi:<4}  {hi - lo + 1:>3} page(s)")

    print("\nchapter ranges resolved through the folio map:")
    resolved, problems = [], []
    covered: set[int] = set()
    for ch in chapters:
        s, e = folio_to_index.get(ch["folio_start"]), folio_to_index.get(ch["folio_end"])
        row = dict(ch, pdf_start=s, pdf_end=e)
        if s is None or e is None or e < s:
            problems.append(ch["number"])
            row["pages"] = None
        else:
            row["pages"] = e - s + 1
            covered |= set(range(s, e + 1))
        resolved.append(row)
        off = "-" if s is None else str(s - ch["folio_start"])
        print(f"   ch{ch['number']:<3} folio {ch['folio_start']:>4}-{ch['folio_end']:<4} "
              f"-> pdf {str(s):>4}-{str(e):<4} {str(row['pages']):>4}p  offset {off:>4}  "
              f"{ch['name'][:44]}")

    offsets = {r["pdf_start"] - r["folio_start"] for r in resolved if r["pdf_start"]}
    print(f"\ndistinct folio->pdf offsets across the book: {sorted(offsets)}")
    if len(offsets) > 1:
        print("  -> confirms there is no single offset; a fitted one would mis-split.")

    # The assertion that would have caught the Class 10 chapter-6 loss, where
    # 23 printed pages fell between two chapters and nothing noticed: the
    # chapter spans must run edge to edge with no hole between them. Adverts
    # inside a span are simply part of that chapter's pages.
    ok = [r for r in resolved if r["pdf_start"] is not None]
    gaps = []
    for prev, nxt in zip(ok, ok[1:]):
        if nxt["pdf_start"] != prev["pdf_end"] + 1:
            gaps.append((prev["number"], prev["pdf_end"], nxt["number"], nxt["pdf_start"]))
    first, last = (ok[0]["pdf_start"], ok[-1]["pdf_end"]) if ok else (None, None)
    print(f"\ncoverage: chapters span physical pages {first}-{last} "
          f"of 0-{doc.page_count - 1}")
    print(f"  before first chapter: {first} page(s) of front matter")
    print(f"  after last chapter  : {doc.page_count - 1 - last} page(s) of back matter")
    if gaps:
        for a, ae, b, bs in gaps:
            print(f"  GAP between ch{a} (ends {ae}) and ch{b} (starts {bs}): "
                  f"{bs - ae - 1} page(s) belong to neither")
    else:
        print("  no gap between any two chapters - every page in the span is claimed.")
    unaccounted = [p for a, ae, b, bs in gaps for p in range(ae + 1, bs)]
    if problems:
        print(f"  CHAPTERS THAT DID NOT RESOLVE: {problems}")

    if a.json:
        Path(a.json).write_text(json.dumps({
            "pdf": a.pdf, "page_count": doc.page_count,
            "contents_page": idx, "chapters": resolved,
            "unnumbered_runs": runs, "unaccounted": unaccounted,
        }, indent=1), encoding="utf-8")
        print(f"\nwrote {a.json}")
    return 1 if (problems or unaccounted) else 0


if __name__ == "__main__":
    raise SystemExit(main())
