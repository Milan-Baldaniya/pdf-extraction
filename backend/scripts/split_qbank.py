"""Split a question bank into one PDF per chapter, using the folio map.

    python -m scripts.split_qbank --book sst10 --list
    python -m scripts.split_qbank --book sst10 --apply

This supersedes split_maths10_qbank.py for any book that interleaves adverts.
That script resolves a chapter's printed range with a single constant offset,
which is true of the Maths book and of no other book supplied so far. Here the
physical pages come from scripts.folio_map, so advert pages are dropped rather
than being handed to whichever chapter they happen to fall inside.

Each chapter's answer-marker count is reported. That is the number to hold the
reading to later - a chapter that comes back with far fewer items than markers
has lost a section.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts import books, folio_map  # noqa: E402


def out_name(book: books.Book, chapter: books.Chapter) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", chapter.title.lower()).strip("_")
    return f"{book.key}_ch{chapter.number:02d}_{slug}.pdf"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", default="sst10")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if not (a.list or a.apply):
        ap.error("choose --list or --apply")

    import pypdf

    book = books.get(a.book)
    if not book.pdf.exists():
        raise SystemExit(f"source not found: {book.pdf}")

    resolved, notes = folio_map.build(book)
    for n in notes:
        print(f"   !! {n}")

    reader = pypdf.PdfReader(str(book.pdf))
    print(f"source: {book.pdf.name}  ({len(reader.pages)} pages)\n")

    if a.apply:
        book.split_dir.mkdir(parents=True, exist_ok=True)

    grand = 0
    bad = 0
    for chapter in book.chapters:
        pages = folio_map.physical_range(resolved, chapter.first_page, chapter.last_page)
        expect = chapter.last_page - chapter.first_page + 1
        if not pages:
            print(f"   ch {chapter.number:<3} {chapter.title[:34]:<36} NO PAGES RESOLVED")
            bad += 1
            continue

        text = "".join((reader.pages[i].extract_text() or "") for i in pages)
        markers = len(book.answer_marker.findall(text))
        grand += markers
        flag = "" if len(pages) == expect else f"  <-- {len(pages)} pages for {expect}"
        if flag:
            bad += 1
        print(f"   ch {chapter.number:<3} {chapter.title[:34]:<36} "
              f"book {chapter.first_page}-{chapter.last_page:<4} "
              f"pdf {pages[0] + 1}-{pages[-1] + 1:<4} {len(pages):>3}p  "
              f"ans={markers:<5} subj={chapter.subject_id}{flag}")

        if a.apply:
            writer = pypdf.PdfWriter()
            for i in pages:
                writer.add_page(reader.pages[i])
            with (book.split_dir / out_name(book, chapter)).open("wb") as fh:
                writer.write(fh)

    print(f"\n   {len(book.chapters)} chapters, {grand} answer markers in total")
    if bad:
        print(f"   {bad} chapter(s) did not resolve cleanly - fix before reading")
    if a.apply:
        print(f"   written to {book.split_dir}")
    else:
        print("   LIST ONLY - nothing written. Re-run with --apply.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())