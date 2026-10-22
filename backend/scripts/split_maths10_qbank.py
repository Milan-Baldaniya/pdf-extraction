"""Split the single Class 10 Maths question-bank PDF into one file per chapter.

    python -m scripts.split_maths10_qbank --list
    python -m scripts.split_maths10_qbank --apply

The Science bank arrived pre-split, with the page ranges already in the file
names - and those splits were scrambled, which cost real questions. This book is
one 627-page file, so the ranges come from its own CONTENTS page and the split
is done here, in order, once.

The contents lists BOOK page numbers; the PDF is offset by one (book page 35 is
PDF page 34), verified at three chapter boundaries. CHAPTERS below stores the
book range as printed and the offset is applied on the way out, so the table can
be checked against the book by eye.

Each chapter is written to its own PDF and its question count is reported from
the `Ans` markers, which is the number to hold the extraction to later.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SOURCE = Path(r"C:\Users\MILAN\Downloads\Maths Standard  QB 2026 (1)_removed.pdf")
OUT_DIR = Path(r"C:\Users\MILAN\Downloads\maths10_split")

# The PDF page index is one less than the printed book page.
PAGE_OFFSET = -1

# (chapter number, printed book first page, printed book last page, title,
#  chapter_master.id) - ids matched by meaning against the Class 10 Mathematics
# chapters of subject 3976, which are 14 and in the same order as the book.
#
# The CONTENTS page is wrong for four chapters. Verified against each chapter's
# printed "CHAPTER <n>" banner in the PDF's own text layer by
# scripts.check_split_boundaries:
#
#     ch 6   contents 239  ->  really starts 241
#     ch 7   contents 271  ->  really starts 273
#     ch 9   contents 349  ->  really starts 353
#     ch 10  contents 405  ->  really starts 403
#
# Each error moves questions into the neighbouring chapter's file, where the
# reader for that chapter correctly ignores them as belonging elsewhere - so
# they are simply lost. Chapter 10 was the visible case: its title page,
# OBJECTIVE heading and first two questions sat at the end of chapter 9, and
# its own file opened halfway through question 3. Chapters 5 and 8 were the
# quiet ones - they lost pages off the END and nothing flagged it, because a
# file that merely stops early still looks well-formed.
#
# Ends are now derived from the next chapter's true start rather than from the
# contents, so the ranges cannot disagree with each other.
CHAPTERS: list[tuple[int, int, int, str, int]] = [
    (1,   35,  57, "Real Numbers",                              22905),
    (2,   58,  88, "Polynomials",                               22907),
    (3,   89, 135, "Pair of Linear Equations in Two Variables",  22910),
    (4,  136, 187, "Quadratic Equations",                       23126),
    (5,  188, 240, "Arithmetic Progressions",                   23197),
    (6,  241, 272, "Triangles",                                 23513),
    (7,  273, 309, "Coordinate Geometry",                       23512),
    (8,  310, 352, "Introduction to Trigonometry",              23511),
    (9,  353, 402, "Some Applications of Trigonometry",         23199),
    (10, 403, 446, "Circles",                                   23198),
    (11, 447, 477, "Areas Related to Circles",                  23196),
    (12, 478, 520, "Surface Areas and Volumes",                 22909),
    (13, 521, 579, "Statistics",                                22908),
    (14, 580, 628, "Probability",                               22906),
]

# This book marks its worked answers "Sol :", not "Ans" - counting "Ans"
# reported 246 questions for 594 pages where the true figure is several
# thousand. Both are counted because a handful of items still print "Ans".
ANS = re.compile(r"(?<![A-Za-z])(?:Sol\s*:|Ans(?![A-Za-z]))")


def out_name(num: int, title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return f"maths10_ch{num:02d}_{slug}.pdf"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not (args.list or args.apply):
        ap.error("choose --list or --apply")

    import pypdf

    if not SOURCE.exists():
        raise SystemExit(f"source not found: {SOURCE}")
    reader = pypdf.PdfReader(str(SOURCE))
    total = len(reader.pages)
    print(f"source: {SOURCE.name}  ({total} pages)\n")

    if args.apply:
        OUT_DIR.mkdir(parents=True, exist_ok=True)

    grand = 0
    for num, first, last, title, chapter_id in CHAPTERS:
        start = first + PAGE_OFFSET - 1          # 0-based, inclusive
        end = min(last + PAGE_OFFSET, total)     # 0-based, exclusive
        if start < 0 or start >= total or end <= start:
            print(f"   ch {num:<3} {title[:38]:<40} BAD RANGE book {first}-{last}")
            continue

        text = "".join((reader.pages[i].extract_text() or "") for i in range(start, end))
        answers = len(ANS.findall(text))
        grand += answers
        name = out_name(num, title)
        print(f"   ch {num:<3} {title[:38]:<40} book {first}-{last:<4} "
              f"pdf {start+1}-{end:<4} {end-start:>3}p  Ans={answers:<4} -> {name}")

        if args.apply:
            writer = pypdf.PdfWriter()
            for i in range(start, end):
                writer.add_page(reader.pages[i])
            with (OUT_DIR / name).open("wb") as fh:
                writer.write(fh)

    print(f"\n   {len(CHAPTERS)} chapters, {grand} answer markers in total")
    if args.apply:
        print(f"   written to {OUT_DIR}")
    else:
        print("   LIST ONLY - nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
