"""Find pages sitting in the wrong chapter's split, and say where they belong.

    python -m scripts.find_stray_pages
    python -m scripts.find_stray_pages --for 6      # what chapter 6 is missing

The split cuts the book by PHYSICAL page range, but this PDF's pages are
shuffled, so a page printed in chapter 7 can physically sit inside chapter 6's
range. It is then handed to chapter 6's reader, who correctly refuses it as
belonging to another chapter - and nobody reads it. Eleven pages across the
book are like this.

The tell is the running header. Every odd book page prints "CH n : TITLE", and
that names the chapter the page really belongs to, whatever file it landed in.

This is how chapter 13's questions 12-16 were found: they are printed on the
last page of the chapter 12 PDF. reorder_pages cannot fix it, because it only
permutes pages WITHIN one file.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts.check_split_boundaries import pages_of  # noqa: E402
from scripts.render_pages import PAGES_ROOT  # noqa: E402
from scripts.textlayer import text_of  # noqa: E402

BOOK = "maths10"
HEADER = re.compile(r"CH\s+(\d+)\s*:")
QSTART = re.compile(r"(?m)^(\d{1,3})\.\s")


def scan(chapters: range) -> list[dict]:
    out = []
    for ch in chapters:
        try:
            body = text_of(BOOK, ch)
        except SystemExit:
            continue
        for number, start, end in pages_of(body):
            chunk = body[start:end]
            m = HEADER.search(chunk)
            if not m or int(m.group(1)) == ch:
                continue
            questions = sorted({int(q.group(1)) for q in QSTART.finditer(chunk)})
            out.append({
                "found_in_chapter": ch,
                "page": number,
                "belongs_to_chapter": int(m.group(1)),
                "questions": questions,
                "image": str(PAGES_ROOT / f"{BOOK}_ch{ch:02d}" / f"p{number:03d}.png"),
            })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--for", dest="wanted", type=int,
                    help="show only the pages that BELONG to this chapter")
    ap.add_argument("--chapters", default="1-14")
    a = ap.parse_args()

    lo, _, hi = a.chapters.partition("-")
    rows = scan(range(int(lo), int(hi or lo) + 1))
    if a.wanted:
        rows = [r for r in rows if r["belongs_to_chapter"] == a.wanted]
        print(f"pages that belong to chapter {a.wanted} but sit elsewhere:")
    else:
        print("pages sitting in the wrong chapter's split:")

    for r in rows:
        qs = r["questions"]
        span = f"questions {qs[0]}-{qs[-1]}" if qs else "no numbered questions"
        print(f"   ch{r['belongs_to_chapter']:<3} {span:<26} "
              f"is on page {r['page']} of the ch{r['found_in_chapter']} file")
        print(f"        {r['image']}")
    print(f"\n{len(rows)} stray page(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
