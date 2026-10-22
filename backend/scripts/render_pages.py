"""Turn question-bank pages into images so they can be READ, and crop figures.

    python -m scripts.render_pages --chapter 5
    python -m scripts.render_pages --chapter 5 --crop 12 0.52 0.18 0.97 0.34 --name ap_ch05_q57

This replaces MinerU for this book. MinerU OCRs a page image into markdown and
took 22-55 minutes per chapter; 72% of the items read from that markdown needed
an OCR repair note, and on chapter 3 it silently dropped an entire "ONE MARK
QUESTIONS" heading, which would have stored 24 one-mark questions as MCQs.

Nothing here reads the page. It only renders: 0.3 s per page against MinerU's
~60 s, and what comes out is the page exactly as printed - every fraction,
exponent and subscript intact - for a reader to look at directly.

--crop takes the figure region in FRACTIONS of the page (x0 y0 x1 y1, origin
top-left) rather than pixels, so the numbers can be read off the page by eye
and do not change if the DPI does.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# The first two books predate scripts.books and keep their literal paths here.
# Everything added since is described in scripts.books, so a new book is a data
# change rather than an edit to this file.
_LEGACY = {
    "maths10": Path(r"C:\Users\MILAN\Downloads\maths10_split"),
    "sci10": Path(r"C:\Users\MILAN\Downloads\ilovepdf_split-range (1)"),
}


def known_books() -> list[str]:
    from scripts import books as _books
    return sorted({*_LEGACY, *_books.BOOKS})


def split_dir(book: str) -> Path:
    if book in _LEGACY:
        return _LEGACY[book]
    from scripts import books as _books
    return _books.get(book).split_dir


PAGES_ROOT = Path(r"C:\Users\MILAN\Downloads\qbank_pages")
FIGURES_ROOT = Path(r"C:\Users\MILAN\Downloads\qbank_figures")

# 170 dpi renders this book's 8.5x11 page at about 1360x1870, which is legible
# down to the subscripts without making each page image large enough to crowd
# out the reading itself.
PAGE_DPI = 170
# Figures are cropped at a higher density because they end up on screen in the
# app at roughly their printed size, and a diagram survives scaling worse than
# body text does.
FIGURE_DPI = 300


def chapter_pdf(book: str, chapter: int) -> Path:
    """The chapter's working PDF - never a backup sitting beside it.

    reorder_pages leaves "<name>.original.pdf" when it rewrites a shuffled
    book. ".original.pdf" sorts BEFORE ".pdf", so a plain glob returned the
    PRE-reorder file and the reorder appeared to have done nothing. Backups now
    live in a sibling folder, and this refuses to return one either way.
    """
    folder = split_dir(book)

    def usable(paths):
        return sorted(q for q in paths if not q.name.endswith(".original.pdf"))

    hits = usable(folder.glob(f"*ch{chapter:02d}_*.pdf")) or         usable(folder.glob(f"*ch{chapter}_*.pdf"))
    if not hits:
        raise SystemExit(f"no chapter {chapter} PDF in {folder}")
    return hits[0]


def render(book: str, chapter: int, first: int | None, last: int | None,
           force: bool) -> list[Path]:
    import fitz

    src = chapter_pdf(book, chapter)
    out_dir = PAGES_ROOT / f"{book}_ch{chapter:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(src))
    lo = (first or 1) - 1
    hi = min(last or len(doc), len(doc))
    written = []
    for i in range(lo, hi):
        target = out_dir / f"p{i + 1:03d}.png"
        if target.exists() and not force:
            written.append(target)
            continue
        doc[i].get_pixmap(dpi=PAGE_DPI).save(str(target))
        written.append(target)
    doc.close()
    return written


def crop(book: str, chapter: int, page: int, box: tuple[float, float, float, float],
         name: str) -> Path:
    """Cut one figure out of a page. The box is chosen by whoever READ the page."""
    import fitz

    x0, y0, x1, y1 = box
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise SystemExit(f"box must be fractions with x0<x1 and y0<y1, got {box}")

    doc = fitz.open(str(chapter_pdf(book, chapter)))
    pg = doc[page - 1]
    r = pg.rect
    clip = fitz.Rect(r.x0 + x0 * r.width, r.y0 + y0 * r.height,
                     r.x0 + x1 * r.width, r.y0 + y1 * r.height)
    out_dir = FIGURES_ROOT / f"{book}_ch{chapter:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{name}.png"
    pg.get_pixmap(dpi=FIGURE_DPI, clip=clip).save(str(target))
    doc.close()
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", choices=known_books(), required=True,
                    help="which book; there is deliberately no default, "
                         "because a wrong one silently renders or crops "
                         "from another book's pages")
    ap.add_argument("--chapter", type=int, required=True)
    ap.add_argument("--from", dest="first", type=int)
    ap.add_argument("--to", dest="last", type=int)
    ap.add_argument("--force", action="store_true", help="re-render existing pages")
    ap.add_argument("--crop", nargs=5, metavar=("PAGE", "X0", "Y0", "X1", "Y1"),
                    help="crop a figure: page number then the box as page fractions")
    ap.add_argument("--name", help="file name for --crop (no extension)")
    a = ap.parse_args()

    if a.crop:
        if not a.name:
            ap.error("--crop needs --name")
        page = int(a.crop[0])
        box = tuple(float(v) for v in a.crop[1:])
        target = crop(a.book, a.chapter, page, box, a.name)
        print(f"{target}  ({target.stat().st_size // 1024} KB)")
        return 0

    import time
    t = time.time()
    pages = render(a.book, a.chapter, a.first, a.last, a.force)
    took = time.time() - t
    if pages:
        print(f"{len(pages)} page(s) -> {pages[0].parent}")
        print(f"   {pages[0].name} .. {pages[-1].name}   {took:.1f}s "
              f"({took / max(len(pages), 1):.2f}s per page)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
