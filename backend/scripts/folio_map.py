"""Map each physical PDF page to the page number the book prints on it.

    python -m scripts.folio_map --book sst10
    python -m scripts.folio_map --book sst10 --verbose

Why this replaces a constant offset: these books interleave full-page NODIA
adverts, so printed-to-physical drifts from about -2 at the front to -38 at the
back, across 28 distinct values in the Social Science book alone. The Maths
book's single `PAGE_OFFSET = -1` would misplace almost every chapter here.

Only about half the pages print a folio - they alternate with pages carrying a
running head and no number. Those are filled in by interpolation between the
folios on either side. Where the physical gap is LARGER than the printed gap,
the surplus pages are adverts: they carry no book page at all and are excluded
from every chapter rather than being silently handed to whichever chapter they
fall inside.

Nothing here is guessed. A page that cannot be resolved is reported as such.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts import books  # noqa: E402

# The folio sits in the page header. Restricting the search to the top of the
# page stops a "PAGE 25" inside body text from being read as the page number.
HEADER_HEIGHT = 62.0


def folios(book: books.Book) -> list[int | None]:
    """The printed page number found on each physical page, or None."""
    import fitz

    doc = fitz.open(str(book.pdf))
    out: list[int | None] = []
    for page in doc:
        rect = page.rect
        header = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + HEADER_HEIGHT)
        text = page.get_text("text", clip=header) or ""
        m = book.folio.search(text)
        out.append(int(m.group(1)) if m else None)
    doc.close()
    return out


def build(book: books.Book) -> tuple[list[int | None], list[str]]:
    """physical page index (0-based) -> printed page, or None for an advert."""
    found = folios(book)
    notes: list[str] = []

    anchors = [(i, n) for i, n in enumerate(found) if n is not None]
    if not anchors:
        raise SystemExit(f"{book.key}: no printed page numbers found at all")

    # A decrease means the pages are out of order, which this mapping cannot
    # express. Say so rather than producing a plausible-looking wrong answer.
    for (ia, a), (ib, b) in zip(anchors, anchors[1:]):
        if b < a:
            notes.append(f"folio DECREASES: physical {ia + 1} prints {a}, "
                         f"physical {ib + 1} prints {b} - the book is shuffled")

    resolved: list[int | None] = [None] * len(found)
    for i, n in anchors:
        resolved[i] = n

    # Fill between consecutive anchors.
    for (ia, a), (ib, b) in zip(anchors, anchors[1:]):
        physical_gap = ib - ia - 1        # unnumbered pages between them
        printed_gap = b - a - 1           # book pages they should account for
        if physical_gap <= 0:
            continue
        if printed_gap < 0:
            continue                       # already reported as a decrease
        if physical_gap == printed_gap:
            for k in range(1, physical_gap + 1):
                resolved[ia + k] = a + k
        elif physical_gap > printed_gap:
            # The surplus is advertising. The book's own pages come first,
            # immediately after the anchor; the adverts follow as a block.
            for k in range(1, printed_gap + 1):
                resolved[ia + k] = a + k
            for k in range(printed_gap + 1, physical_gap + 1):
                resolved[ia + k] = None    # advert
        else:
            notes.append(
                f"between physical {ia + 1} (prints {a}) and {ib + 1} (prints {b}) "
                f"there are {physical_gap} pages for {printed_gap} book pages - "
                f"cannot resolve, left unassigned")

    # Before the first anchor and after the last.
    first_i, first_n = anchors[0]
    for k in range(first_i):
        back = first_n - (first_i - k)
        resolved[k] = back if back >= 1 else None
    last_i, last_n = anchors[-1]
    for k in range(last_i + 1, len(found)):
        resolved[k] = last_n + (k - last_i)

    return resolved, notes


def physical_range(resolved: list[int | None], first: int, last: int) -> list[int]:
    """0-based physical pages holding printed pages first..last, adverts dropped."""
    return [i for i, n in enumerate(resolved) if n is not None and first <= n <= last]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", default="sst10")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    book = books.get(a.book)
    resolved, notes = build(book)

    numbered = sum(1 for n in resolved if n is not None)
    adverts = len(resolved) - numbered
    print(f"{book.key}: {len(resolved)} physical pages")
    print(f"   resolved to a book page : {numbered}")
    print(f"   adverts / unassigned    : {adverts}")
    for n in notes:
        print(f"   !! {n}")

    print(f"\n   {'ch':<4}{'printed':<12}{'physical':<16}{'pages':>6}{'expected':>10}")
    for c in book.chapters:
        pages = physical_range(resolved, c.first_page, c.last_page)
        expect = c.last_page - c.first_page + 1
        flag = "" if len(pages) == expect else "   <-- MISMATCH"
        span = f"{pages[0] + 1}-{pages[-1] + 1}" if pages else "NONE"
        print(f"   {c.number:<4}{c.first_page}-{c.last_page:<7} {span:<16}"
              f"{len(pages):>6}{expect:>10}{flag}")

    if a.verbose:
        print("\n   physical -> printed (first 40):")
        for i, n in enumerate(resolved[:40]):
            print(f"      {i + 1:>4} -> {n if n is not None else 'advert'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())