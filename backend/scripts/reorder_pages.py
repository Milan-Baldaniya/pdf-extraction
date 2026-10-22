"""Put a chapter's pages back into reading order.

    python -m scripts.reorder_pages --chapter 5            # show the plan
    python -m scripts.reorder_pages --chapter 5 --apply    # rewrite the PDF
    python -m scripts.reorder_pages --chapters 4-14 --apply

The source PDF's pages are not in reading order. Chapter 5 page 1 prints
questions 1-5 and ends mid-solution; the page that continues it is physical
page 8. Page 2 prints questions 40-45. Chapters 4 to 14 each have 13-26 such
inversions; chapters 1 to 3 are clean, which is why their reads came out with
contiguous question numbers.

Left alone this breaks two things. A question split across a page boundary
loses its second half to a page somewhere else in the file. And the section
map - which is what tells a reader whether an item is worth 1 mark or 5 - is
derived from the page a heading appears on, so shuffled pages mis-mark whole
runs of questions.

How the order is recovered, in order of how much the evidence is trusted:

  1. EVEN book pages print "PAGE nnn CBSE ..." in their header. Those are
     unambiguous and become fixed anchors.
  2. ODD book pages print no number. Each one is placed by CONTENT: it is the
     page whose question numbers fall in the gap between two consecutive
     anchors.

Nothing is guessed. A page that cannot be placed is reported and left where it
is, rather than being dropped or put somewhere plausible.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts.render_pages import chapter_pdf  # noqa: E402

BOOK = "maths10"
PRINTED = re.compile(r"PAGE\s+(\d{2,3})\s+CBSE")
QSTART = re.compile(r"(?m)^(\d{1,3})\.\s")


def page_facts(pdf: Path) -> list[dict]:
    """Per physical page: its printed book number if any, and its question starts."""
    import pypdf

    reader = pypdf.PdfReader(str(pdf))
    facts = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        printed = PRINTED.search(text)
        numbers = [int(m.group(1)) for m in QSTART.finditer(text)]
        facts.append({
            "index": i,
            "printed": int(printed.group(1)) if printed else None,
            "questions": numbers,
            "first": numbers[0] if numbers else None,
            "last": numbers[-1] if numbers else None,
        })
    return facts


def plan_order(facts: list[dict]) -> tuple[list[int], list[str]]:
    anchors = [f for f in facts if f["printed"] is not None]
    floating = [f for f in facts if f["printed"] is None]
    notes: list[str] = []

    if not anchors:
        return [f["index"] for f in facts], ["no printed page numbers - left as is"]

    anchors.sort(key=lambda f: f["printed"])

    # An odd book page sits between two consecutive even ones. Its questions
    # therefore start at or after where the page before it ended, and before
    # the page after it begins.
    order: list[int] = []
    used: set[int] = set()

    # Pages that come BEFORE the first anchor. The chapter's opening page is
    # always one of these - it is an odd book page, so it prints no number, and
    # matching it "between two anchors" can never succeed. Without this it was
    # appended at the END of the chapter, putting question 1 after question 200.
    head_limit = anchors[0]["first"]
    if head_limit is not None:
        for f in sorted(floating, key=lambda f: f["index"]):
            if f["first"] is not None and f["first"] < head_limit:
                order.append(f["index"])
                used.add(f["index"])

    for pos, anchor in enumerate(anchors):
        order.append(anchor["index"])
        used.add(anchor["index"])

        lo = anchor["last"]
        nxt = anchors[pos + 1] if pos + 1 < len(anchors) else None
        hi = nxt["first"] if nxt else None

        best = None
        for f in floating:
            if f["index"] in used or f["first"] is None:
                continue
            if lo is not None and f["first"] < lo:
                continue
            if hi is not None and f["first"] >= hi:
                continue
            # Prefer the candidate that starts earliest in the window; a page
            # continuing the anchor begins as soon as the anchor stops.
            if best is None or f["first"] < best["first"]:
                best = f
        if best is not None:
            order.append(best["index"])
            used.add(best["index"])

    leftover = [f for f in facts if f["index"] not in used]
    for f in leftover:
        notes.append(f"could not place physical page {f['index'] + 1} "
                     f"(questions {f['first']}..{f['last']}) - appended in place")
    # Keep unplaced pages in their original relative order at the end of the
    # nearest anchor run rather than dropping them.
    for f in sorted(leftover, key=lambda f: f["index"]):
        order.append(f["index"])

    return order, notes


def apply_order(pdf: Path, order: list[int]) -> None:
    import pypdf

    reader = pypdf.PdfReader(str(pdf))
    writer = pypdf.PdfWriter()
    for i in order:
        writer.add_page(reader.pages[i])
    tmp = pdf.with_suffix(".reordered.pdf")
    with tmp.open("wb") as fh:
        writer.write(fh)
    # The backup goes in a SIBLING folder, not beside the file. Left in place
    # it was picked up by every glob for the chapter - ".original.pdf" sorts
    # before ".pdf" - so the tools kept reading the un-reordered original.
    backups = pdf.parent.parent / (pdf.parent.name + "_originals")
    backups.mkdir(parents=True, exist_ok=True)
    backup = backups / pdf.name
    if not backup.exists():
        pdf.replace(backup)          # keep the original, once
    else:
        pdf.unlink()
    tmp.replace(pdf)


def inversions(facts: list[dict], order: list[int]) -> int:
    by_index = {f["index"]: f for f in facts}
    seq = [by_index[i]["first"] for i in order if by_index[i]["first"] is not None]
    return sum(1 for a, b in zip(seq, seq[1:]) if b < a)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chapter", type=int)
    ap.add_argument("--chapters", help="range like 4-14")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if a.chapters:
        lo, _, hi = a.chapters.partition("-")
        targets = list(range(int(lo), int(hi or lo) + 1))
    elif a.chapter:
        targets = [a.chapter]
    else:
        ap.error("choose --chapter N or --chapters A-B")

    for chapter in targets:
        pdf = chapter_pdf(BOOK, chapter)
        facts = page_facts(pdf)
        before = inversions(facts, [f["index"] for f in facts])
        order, notes = plan_order(facts)
        after = inversions(facts, order)

        moved = sum(1 for pos, i in enumerate(order) if i != pos)
        print(f"  ch {chapter:<3} {len(facts):>3} pages  inversions {before:>3} -> {after:<3} "
              f"({moved} page(s) move)")
        for n in notes:
            print(f"        {n}")

        if a.apply:
            if after > before:
                print("        REFUSING to apply: the new order is worse than the old one")
                continue
            if moved == 0:
                continue
            apply_order(pdf, order)
            print(f"        rewritten; original kept in "
                  f"{pdf.parent.name}_originals/{pdf.name}")
    if not a.apply:
        print("\n  PLAN ONLY - nothing rewritten. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
