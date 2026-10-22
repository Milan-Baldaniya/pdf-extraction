"""Assign every source page to its chapter, in reading order.

    python -m scripts.assign_pages --book sst10
    python -m scripts.assign_pages --book sst10 --apply     # write chapter PDFs

This replaces the folio-range split for this book family, because the folio
range is only half the story.

What went wrong with the simpler approach: folio_map resolves each chapter's
printed range to physical pages and the page COUNTS all matched exactly, which
looked like proof. It was not. Only about half these pages print a folio; the
rest carry a running head and no number, and THOSE are shuffled. Physical page
185 prints chapter 4's question 129 and sits between chapter 5's pages 165 and
167. A folio-only monotonicity check cannot see it, because the pages it
checks are the ordered ones.

The fix uses the two signals the book gives on every page:

  * a folio (`PAGE 167`) - present on ~47% of pages, always correct, always
    ascending. These are the anchors.
  * a running head (`CH 5 : RESOURCES AND DEVELOPMENT`) - present on most of
    the rest, and it names the chapter the page belongs to whatever position
    it landed in.

So: assign each page to a chapter from whichever signal it carries, then within
a chapter order the anchors by folio and slot each headed page into the gap
whose question numbers it continues. A page with neither signal is an advert
and is dropped.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts import books  # noqa: E402
from scripts.split_qbank import out_name  # noqa: E402

HEADER_HEIGHT = 62.0
RUNNING_HEAD = re.compile(r"CH\s+(\d{1,2})\s*:")
QSTART = re.compile(r"^(\d{1,3})\.\s")


def question_numbers(page, book) -> list[int]:
    """The printed question numbers on this page, in layout order.

    Selected by TYPEFACE where the book names one. A plain "^\d+\." match
    also picks up the numbered lists inside answers - Social Science answers
    are full of them - which made pages report ranges like "111..1" and defeated
    any attempt to order them.
    """
    out: list[int] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = line.get("spans") or []
            if not spans:
                continue
            text = "".join(s["text"] for s in spans).strip()
            m = QSTART.match(text)
            if not m:
                continue
            if book.question_font and book.question_font not in spans[0]["font"]:
                continue
            out.append(int(m.group(1)))
    return out


def survey(book: books.Book) -> list[dict]:
    """Per physical page: its folio, its running-head chapter, its questions."""
    import fitz

    doc = fitz.open(str(book.pdf))
    rows = []
    for i, page in enumerate(doc):
        rect = page.rect
        header = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + HEADER_HEIGHT)
        head = page.get_text("text", clip=header) or ""
        folio = book.folio.search(head)
        running = RUNNING_HEAD.search(head)
        numbers = question_numbers(page, book)
        rows.append({
            "index": i,
            "folio": int(folio.group(1)) if folio else None,
            "head_chapter": int(running.group(1)) if running else None,
            "first": numbers[0] if numbers else None,
            "last": numbers[-1] if numbers else None,
        })
    doc.close()
    return rows


def chapter_of_folio(book: books.Book, folio: int) -> int | None:
    for c in book.chapters:
        if c.first_page <= folio <= c.last_page:
            return c.number
    return None


def assign(book: books.Book) -> tuple[dict[int, list[int]], list[str]]:
    rows = survey(book)
    notes: list[str] = []
    by_chapter: dict[int, list[dict]] = {c.number: [] for c in book.chapters}
    dropped = 0

    for r in rows:
        chapter = None
        if r["folio"] is not None:
            chapter = chapter_of_folio(book, r["folio"])
        elif r["head_chapter"] is not None:
            chapter = r["head_chapter"]
        if chapter in by_chapter:
            by_chapter[chapter].append(r)
        else:
            dropped += 1
    notes.append(f"{dropped} page(s) belong to no mapped chapter (adverts, front "
                 f"matter, and chapter 20 Map Work) and were dropped")

    ordered: dict[int, list[int]] = {}
    for number, pages in by_chapter.items():
        anchors = sorted((p for p in pages if p["folio"] is not None),
                         key=lambda p: p["folio"])
        floating = [p for p in pages if p["folio"] is None]
        used: set[int] = set()
        seq: list[int] = []

        # Pages whose questions precede the first anchor's (the chapter opening
        # can be an unnumbered page).
        head_limit = anchors[0]["first"] if anchors else None
        if head_limit is not None:
            for p in sorted(floating, key=lambda p: p["index"]):
                if p["first"] is not None and p["first"] < head_limit:
                    seq.append(p["index"]); used.add(p["index"])

        for pos, anchor in enumerate(anchors):
            seq.append(anchor["index"]); used.add(anchor["index"])
            lo = anchor["last"]
            nxt = anchors[pos + 1] if pos + 1 < len(anchors) else None
            hi = nxt["first"] if nxt else None

            best = None
            for p in floating:
                if p["index"] in used or p["first"] is None:
                    continue
                if lo is not None and p["first"] < lo:
                    continue
                if hi is not None and p["first"] >= hi:
                    continue
                if best is None or p["first"] < best["first"]:
                    best = p
            if best is not None:
                seq.append(best["index"]); used.add(best["index"])

        # Pages carrying no question number at all - a section banner page, a
        # SUMMARY, a full-page map. They cannot be placed by question number,
        # and appending them at the end is wrong: chapter 1's MULTIPLE CHOICE
        # banner ended up after the CASE BASED section, which would have told
        # every reader the wrong section for its pages.
        #
        # In the source such a page immediately PRECEDES the content it
        # introduces, so it is reinserted just after whichever already-placed
        # page it physically follows. That keeps a banner with its own section.
        leftover = sorted((p for p in pages if p["index"] not in used),
                          key=lambda p: p["index"])
        for p in leftover:
            before = [k for k, idx in enumerate(seq) if idx < p["index"]]
            at = (before[-1] + 1) if before else 0
            seq.insert(at, p["index"])
            if p["first"] is not None:
                notes.append(f"ch {number}: physical page {p['index'] + 1} "
                             f"(questions {p['first']}..{p['last']}) placed by "
                             f"position, not by question number")
        ordered[number] = seq

    return ordered, notes


def inversions(book: books.Book, rows: list[dict], seq: list[int]) -> int:
    by_index = {r["index"]: r for r in rows}
    nums = [by_index[i]["first"] for i in seq if by_index[i]["first"] is not None]
    return sum(1 for a, b in zip(nums, nums[1:]) if b < a)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", default="sst10")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    book = books.get(a.book)
    rows = survey(book)
    ordered, notes = assign(book)

    import pypdf
    reader = pypdf.PdfReader(str(book.pdf)) if a.apply else None
    if a.apply:
        book.split_dir.mkdir(parents=True, exist_ok=True)

    print(f"{book.key}: {len(rows)} source pages\n")
    print(f"   {'ch':<4}{'pages':>6}{'expected':>10}{'inversions':>12}   subject")
    total = 0
    for c in book.chapters:
        seq = ordered[c.number]
        expect = c.last_page - c.first_page + 1
        inv = inversions(book, rows, seq)
        flag = "" if len(seq) == expect and inv == 0 else "   <-- CHECK"
        print(f"   {c.number:<4}{len(seq):>6}{expect:>10}{inv:>12}   {c.subject_id}{flag}")
        total += len(seq)

        if a.apply:
            writer = pypdf.PdfWriter()
            for i in seq:
                writer.add_page(reader.pages[i])
            with (book.split_dir / out_name(book, c)).open("wb") as fh:
                writer.write(fh)

    print(f"\n   {total} pages across {len(book.chapters)} chapters")
    for n in notes:
        print(f"   {n}")
    if a.apply:
        print(f"   written to {book.split_dir}")
    else:
        print("   PLAN ONLY - nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
