"""Check that each chapter PDF actually starts where its chapter starts.

    python -m scripts.check_split_boundaries

The split ranges come from the book's CONTENTS page, and the contents can be
wrong. Chapter 10 is: the contents says it begins on book page 405, but its
title page, its "OBJECTIVE QUESTIONS" heading and its first two questions are
printed on book page 403 - which the split filed at the END of chapter 9. The
chapter 10 file therefore opens in the middle of question 3, and its objective
section has no heading at all.

Left alone that costs questions twice over: the ones stranded in the previous
chapter's file that nobody reads, and the ones at the start of this chapter
whose section - and therefore marks and form - cannot be determined.

Two checks per chapter, both against the PDF's own text layer:

  HEAD  does page 1 look like a chapter opening (the chapter title banner, or
        a section heading) rather than the middle of a worked solution?
  TAIL  do the last pages contain the NEXT chapter's title banner?

Either one failing means the boundary is in the wrong place.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts.textlayer import text_of  # noqa: E402

# "CHAPTER CHAPTER 1010" is how the two-layer printed banner comes out of the
# text layer - the number is doubled because the design prints it twice.
BANNER = re.compile(r"CHAPTER\s+CHAPTER\s+(\d+)", re.IGNORECASE)
SECTION = re.compile(r"(OBJECTIVE QUESTION|ONE MARK QUESTION|TWO MARKS? QUESTION"
                     r"|THREE MARKS? QUESTION|FIVE MARKS? QUESTION)", re.IGNORECASE)
PAGE = re.compile(r"===== PAGE (\d+) =====")


def pages_of(body: str) -> list[tuple[int, int, int]]:
    """(page number, start offset, end offset) for every page."""
    marks = [(int(m.group(1)), m.end()) for m in PAGE.finditer(body)]
    out = []
    for i, (number, start) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(body)
        out.append((number, start, end))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", default="maths10")
    ap.add_argument("--chapters", default="1-14")
    a = ap.parse_args()

    lo, _, hi = a.chapters.partition("-")
    targets = range(int(lo), int(hi or lo) + 1)

    problems = 0
    for chapter in targets:
        try:
            body = text_of(a.book, chapter)
        except SystemExit:
            print(f"  ch {chapter:<3} no PDF")
            continue
        pages = pages_of(body)
        if not pages:
            continue

        first = body[pages[0][1]:pages[0][2]]
        head_banner = BANNER.search(first)
        head_section = SECTION.search(first)
        head_ok = bool(head_banner or head_section)

        # Look for the NEXT chapter's banner anywhere in this file.
        stray = None
        for number, start, end in pages:
            m = BANNER.search(body[start:end])
            if m and int(m.group(1)) != int(f"{chapter}{chapter}") and \
                    int(m.group(1)) != chapter:
                # the banner doubles the number: chapter 10 prints "1010"
                text_num = m.group(1)
                half = len(text_num) // 2
                real = int(text_num[:half]) if text_num[:half] == text_num[half:] \
                    else int(text_num)
                if real != chapter:
                    stray = (number, real)
                    break

        flags = []
        if not head_ok:
            flags.append("page 1 starts MID-CONTENT (no banner, no section heading)")
        if stray:
            flags.append(f"chapter {stray[1]}'s banner is on page {stray[0]} of this file")

        status = "ok" if not flags else "PROBLEM"
        print(f"  ch {chapter:<3} {len(pages):>3} pages  {status}")
        for f in flags:
            print(f"        - {f}")
            problems += 1

    print(f"\n{problems} boundary problem(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
