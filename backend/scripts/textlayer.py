"""Read a chapter's printed text straight from the PDF's embedded text layer.

    python -m scripts.textlayer --chapter 2 --find "twice the zeroes"
    python -m scripts.textlayer --chapter 2 --question 7
    python -m scripts.textlayer --chapter 2 --from 0 --chars 4000

Why this exists: MinerU OCRs the page image, and on this maths bank that loses
things the book prints perfectly well. 72% of the chapter 1-2 items needed an
OCR repair note, and three MCQs arrived with their option sets destroyed -
question 1's "(b) 5/2" came through as "25", question 4 lost "(b) 1" entirely.
All three are clean in the text layer.

This is a lookup, not a replacement. MinerU still supplies the cropped figures
and the reading order; this answers "what does the book actually print here?"
when a formula or an option looks wrong. Where the two disagree on a formula or
an option, the text layer is the book and MinerU is a guess at it.

Offsets here are into the text layer and do NOT line up with the markdown
offsets the section readers work from, so locate by --find or --question.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# One source of truth for where a book's chapter PDFs live.
from scripts.render_pages import known_books, split_dir  # noqa: E402
CACHE = Path(__file__).resolve().parent / "textlayer_cache"


def chapter_pdf(book: str, chapter: int) -> Path:
    folder = split_dir(book)
    hits = sorted(folder.glob(f"*ch{chapter:02d}_*.pdf")) or \
        sorted(folder.glob(f"*ch{chapter}_*.pdf"))
    if not hits:
        raise SystemExit(f"no chapter {chapter} PDF in {folder}")
    return hits[0]


def text_of(book: str, chapter: int) -> str:
    """Extract once, then serve from a cache file - readers call this often."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{book}_ch{chapter:02d}.txt"
    if cached.exists():
        return cached.read_text(encoding="utf-8", errors="replace")

    import pypdf

    reader = pypdf.PdfReader(str(chapter_pdf(book, chapter)))
    parts = []
    for n, page in enumerate(reader.pages, start=1):
        parts.append(f"\n\n===== PAGE {n} =====\n" + (page.extract_text() or ""))
    body = "".join(parts)
    cached.write_text(body, encoding="utf-8", errors="replace")
    return body


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", choices=known_books(), default="maths10")
    ap.add_argument("--chapter", type=int, required=True)
    ap.add_argument("--find", help="print the window around this phrase")
    ap.add_argument("--question", type=int, help="print printed question N and its solution")
    ap.add_argument("--from", dest="start", type=int, default=0)
    ap.add_argument("--chars", type=int, default=3000)
    ap.add_argument("--all", action="store_true", help="print the whole chapter")
    ap.add_argument("--sections", action="store_true",
                    help="list the section headings with the PAGE each starts on")
    a = ap.parse_args()

    body = text_of(a.book, a.chapter)

    if a.sections:
        # Page-image readers work in pages, not character offsets, and an item's
        # marks come from its section - so a reader handed pages 20-30 has to be
        # told which section those pages sit in. The heading is printed on the
        # page, but a chunk that starts mid-section would otherwise have to guess.
        page_at = [(m.start(), int(m.group(1)))
                   for m in re.finditer(r"===== PAGE (\d+) =====", body)]

        def page_of(pos: int) -> int:
            last = 1
            for start, number in page_at:
                if start > pos:
                    break
                last = number
            return last

        heads = re.compile(
            r"(OBJECTIVE QUESTION[S]?|ONE MARK QUESTIONS?|TWO MARKS? QUESTIONS?"
            r"|THREE MARKS? QUESTIONS?|FOUR MARKS? QUESTIONS?|FIVE MARKS? QUESTIONS?"
            r"|CASE BASED[A-Z ]*)")
        seen, found = set(), []
        for m in heads.finditer(body):
            h = m.group(1).strip()
            if h in seen:
                continue
            seen.add(h)
            found.append((page_of(m.start()), h))
        found.sort()
        total = page_at[-1][1] if page_at else 0
        print(f"chapter {a.chapter}: {total} pages, {len(found)} sections")
        for i, (pg, h) in enumerate(found):
            end = found[i + 1][0] if i + 1 < len(found) else total
            print(f"   p{pg:>3}-{end:<3}  {h}")
        return 0

    if a.all:
        print(body)
        return 0

    if a.question is not None:
        # The book numbers straight through a chapter, so "N." at a line start
        # is the question and "N+1." ends it.
        m = re.search(rf"(?m)^{a.question}\.\s", body)
        if not m:
            print(f"question {a.question} not found by line anchor; "
                  f"try --find with a phrase from its stem")
            return 1
        nxt = re.search(rf"(?m)^{a.question + 1}\.\s", body[m.end():])
        end = m.end() + (nxt.start() if nxt else a.chars)
        print(body[m.start():end])
        return 0

    if a.find:
        # Whitespace in the text layer is unreliable (columns interleave), so
        # match the phrase's words with any spacing between them.
        pat = re.compile(r"\s*".join(re.escape(w) for w in a.find.split()), re.IGNORECASE)
        hits = list(pat.finditer(body))
        if not hits:
            print(f"not found: {a.find!r}  (chapter {a.chapter}, {len(body):,} chars)")
            return 1
        for h in hits[:5]:
            print(f"----- match at {h.start()}")
            print(body[max(0, h.start() - 200):h.start() + a.chars])
            print()
        if len(hits) > 5:
            print(f"({len(hits) - 5} further match(es) not shown)")
        return 0

    print(f"chapter {a.chapter}: {len(body):,} chars")
    print(body[a.start:a.start + a.chars])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
