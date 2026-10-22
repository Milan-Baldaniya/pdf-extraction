"""Split a chapter into reader-sized page ranges, one work item per range.

    python -m scripts.plan_page_work --chapter 5
    python -m scripts.plan_page_work --chapter 5 --json

The markdown planner (plan_nodia_work) cuts on character offsets into MinerU's
output. Reading the pages directly means there is no markdown, so the unit is
the page - and the section a page belongs to has to be supplied, because an
item's marks and form come from its section heading and a chunk that starts
mid-section cannot see the heading that governs it.

Ranges OVERLAP by one page. A question that straddles a page boundary is then
read by both neighbours, and the merge keeps one copy - which is the behaviour
that stopped question 98 of chapter 3 from falling into a gap. The opposite
arrangement, abutting ranges, loses whatever sits across the seam and does so
silently.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts.extract_maths10_qbank import CHAPTERS as MATHS_CHAPTERS  # noqa: E402
from scripts.render_pages import PAGES_ROOT  # noqa: E402
from scripts.textlayer import text_of  # noqa: E402

# The Maths book predates scripts.books and keeps its own tables. Every book
# added since declares its own section vocabulary, because no two of these
# books use the same words: Maths prints "ONE MARK QUESTIONS", Social Science
# prints "VERY SHORT QUESTION" (singular), and the Hindi books print Devanagari
# in a legacy font. Matching one book's wording against another finds nothing
# and silently yields a chapter with no sections.
MATHS_SLUG = {"OBJECTIVE QUESTIONS": ("obj", "mcq", 1),
              "ONE MARK QUESTIONS": ("one", "very_short", 1),
              "TWO MARKS QUESTIONS": ("two", "very_short", 2),
              "THREE MARKS QUESTIONS": ("three", "short", 3),
              "FOUR MARKS QUESTIONS": ("four", "case_study", 4),
              "FIVE MARKS QUESTIONS": ("five", "long", 5)}

BOOK = "maths10"


def _prefix(book: str) -> str:
    """Part-file prefix. Two books share the parts/ directory, so a wrong
    prefix makes one book's parts invisible to its own merge."""
    if book == "maths10":
        return "mch"
    if book == "sci10":
        return "ch"
    from scripts import books as _books
    return _books.get(book).prefix


def _book_tables(book: str):
    """(chapter number -> (chapter_id, name, subject_id), sections) for a book."""
    if book == "maths10":
        by_number = {num: (cid, name, 3976)
                     for num, cid, name in MATHS_CHAPTERS.values() if cid}
        return by_number, MATHS_SLUG
    from scripts import books as _books
    b = _books.get(book)
    by_number = {c.number: (c.chapter_id, c.title, c.subject_id) for c in b.chapters}
    return by_number, b.sections


BY_NUMBER, SLUG = _book_tables(BOOK)

# Ten pages is what one reader handles without thinning out. The failure mode
# of an over-long slice is silent - fewer questions, no error - so this is
# deliberately conservative.
MAX_PAGES = 10


def sections_of(chapter: int) -> tuple[list[tuple[int, str]], int]:
    body = text_of(BOOK, chapter)
    page_at = [(m.start(), int(m.group(1)))
               for m in re.finditer(r"===== PAGE (\d+) =====", body)]

    def page_of(pos: int) -> int:
        last = 1
        for start, number in page_at:
            if start > pos:
                break
            last = number
        return last

    heads = re.compile("|".join(re.escape(k) for k in SLUG))
    seen, found = set(), []
    for m in heads.finditer(body):
        h = m.group(0).strip()
        if h in seen:
            continue
        seen.add(h)
        found.append((page_of(m.start()), h))
    found.sort()
    total = page_at[-1][1] if page_at else 0
    return found, total


def plan(chapter: int) -> list[dict]:
    chapter_id, name, subject_id = BY_NUMBER[chapter]
    found, total = sections_of(chapter)
    if not found:
        return []

    work = []
    # Anything printed before the first heading still belongs to the chapter.
    if found[0][0] > 1:
        work.append({"section": "BEFORE THE FIRST HEADING", "slug": "pre",
                     "first": 1, "last": found[0][0]})

    for i, (start, heading) in enumerate(found):
        end = found[i + 1][0] if i + 1 < len(found) else total
        span = end - start + 1
        pieces = max(1, -(-span // MAX_PAGES))
        step = -(-span // pieces)
        for k in range(pieces):
            lo = start + k * step
            hi = min(end, lo + step)          # +1 page of overlap by construction
            if lo > end:
                break
            slug = SLUG.get(heading, ("sec", "short", 3))[0]
            if pieces > 1:
                slug = f"{slug}{chr(ord('a') + k)}"
            work.append({"section": heading, "slug": slug, "first": lo, "last": hi})

    out = []
    for w in work:
        out.append({
            "chapter": chapter,
            "chapter_id": chapter_id,
            "subject_id": subject_id,
            "form": SLUG.get(w["section"], ("sec", "short", 3))[1],
            "marks": SLUG.get(w["section"], ("sec", "short", 3))[2],
            "name": name,
            "section": w["section"],
            "slug": w["slug"],
            "first_page": w["first"],
            "last_page": w["last"],
            "pages_dir": str(PAGES_ROOT / f"{BOOK}_ch{chapter:02d}"),
            "out": f"{_prefix(BOOK)}{chapter:02d}_{w['slug']}.json",
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chapter", type=int)
    ap.add_argument("--chapters", help="comma-separated, or a range like 5-14")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--book", default="maths10")
    a = ap.parse_args()

    global BOOK, BY_NUMBER, SLUG
    BOOK = a.book
    BY_NUMBER, SLUG = _book_tables(BOOK)

    if a.chapters and "-" in a.chapters:
        lo, _, hi = a.chapters.partition("-")
        targets = list(range(int(lo), int(hi) + 1))
    elif a.chapters:
        targets = [int(x) for x in a.chapters.split(",") if x.strip()]
    elif a.chapter:
        targets = [a.chapter]
    else:
        ap.error("choose --chapter N or --chapters")

    work = []
    for chapter in targets:
        if chapter not in BY_NUMBER:
            continue
        work.extend(plan(chapter))

    if a.json:
        print(json.dumps({"work": work}))
        return 0

    current = None
    for w in work:
        if w["chapter"] != current:
            current = w["chapter"]
            print(f"  ch {current} {w['name']}")
        print(f"      p{w['first_page']:>3}-{w['last_page']:<3} "
              f"{w['section']:<30} -> {w['out']}")
    print(f"\n  {len(work)} reader(s) across {len(targets)} chapter(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
