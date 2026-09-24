"""Merge verified section files into one loadable file per chapter.

    python -m scripts.merge_qbank_parts --chapter 2
    python -m scripts.merge_qbank_parts --all --out scripts/c9sci_items

Section files are produced by `parse_qbank_items` and then read and corrected
one section at a time. This joins them back into the shape
`load_nodia_items` expects, and fixes the one thing that cannot be left alone.

ITEM NUMBERS COLLIDE ACROSS SECTIONS. The book restarts numbering in every
block: objective runs 1-60, very short 61-90, but Pause and Ponder restarts at
1 and the reprinted NCERT exercise restarts at 1 again. `apply_read_concepts`
addresses a row with

    WHERE x.extraction_id = :e AND x.item_number = :num AND q.chapter_id = :c

so with three items numbered "1" in one extraction, a concept written for the
pause question also lands on the objective question and on the NCERT one. The
concept would be wrong on two rows out of three and nothing would report it.

So each number is prefixed with its section -- P1, N1, O1, V61, S91, L121,
C131. `item_number` is varchar(16), the printed number survives inside it, and
the three "1"s become distinct. Ordering across sections follows the book.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DRAFTS = Path(__file__).resolve().parent / "c9sci_items" / "drafts"

# Printed order within a chapter, and the prefix each section's numbers get.
ORDER: tuple[tuple[str, str], ...] = (
    ("pause", "P"),
    ("ncert", "N"),
    ("objective", "O"),
    ("veryshort", "V"),
    ("short", "S"),
    ("long", "L"),
    ("case", "C"),
)

REQUIRED = ("stem", "form")
TAGS = ("concept", "bloom", "dok", "difficulty")


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"   UNREADABLE {path.name}: {exc}")
        return None


def merge_chapter(chapter: int) -> tuple[dict | None, list[str]]:
    problems: list[str] = []
    items: list[dict] = []
    chapter_id = extraction_id = None
    seen_numbers: set[str] = set()

    for slug, prefix in ORDER:
        path = DRAFTS / f"ch{chapter:02d}_{slug}.json"
        if not path.exists():
            continue
        payload = _load(path)
        if not payload:
            problems.append(f"{path.name} unreadable")
            continue
        chapter_id = chapter_id or payload.get("chapter_id")
        extraction_id = extraction_id or payload.get("extraction_id")

        for entry in payload.get("items") or []:
            item = dict(entry)
            number = f"{prefix}{str(item.get('number') or len(items) + 1)}"[:16]
            if number in seen_numbers:
                # A section file can itself hold two numbered blocks: chapter
                # 2's pause file carries Pause and Ponder 1-7 followed by the
                # reprinted NCERT exercise 1-16, so 1-7 occur twice inside one
                # file. Suffixing the position keeps both addressable and keeps
                # the printed number visible.
                number = f"{number}.{len(items) + 1}"[:16]
            seen_numbers.add(number)
            item["number"] = number
            item["section_heading"] = slug

            for field in REQUIRED:
                if not item.get(field):
                    problems.append(f"{number}: empty {field}")
            if not item.get("answer"):
                problems.append(f"{number}: no answer")
            for field in TAGS:
                if item.get(field) in (None, ""):
                    problems.append(f"{number}: missing {field}")

            options = item.get("options") or []
            if item.get("form") == "mcq" and len(options) != 4:
                problems.append(f"{number}: mcq has {len(options)} options, needs 4")
            if options and not item.get("correct_option"):
                problems.append(f"{number}: options but no correct_option")
            labels = [o.get("label") for o in options]
            if len(labels) != len(set(labels)):
                problems.append(f"{number}: duplicate option labels")
            if item.get("correct_option") and item["correct_option"] not in labels:
                problems.append(f"{number}: correct_option not among labels")
            for option in options:
                if len(option.get("text") or "") > 250:
                    problems.append(f"{number}: option over 250 chars")
            if item.get("figure_required") and not item.get("images"):
                problems.append(f"{number}: figure_required with no images")
            items.append(item)

    if not items:
        return None, problems or ["no section files found"]
    return {
        "chapter": chapter,
        "chapter_id": chapter_id,
        "extraction_id": extraction_id,
        "items": items,
    }, problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chapter", type=int, action="append")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "c9sci_items"))
    ap.add_argument("--write", action="store_true",
                    help="write merged files; without it this only reports")
    a = ap.parse_args()

    if a.all:
        chapters = sorted({int(m.group(1))
                           for p in DRAFTS.glob("ch*_*.json")
                           if (m := re.match(r"ch(\d+)_", p.name))})
    elif a.chapter:
        chapters = sorted(set(a.chapter))
    else:
        ap.error("give --chapter N or --all")

    out_dir = Path(a.out)
    if a.write:
        out_dir.mkdir(parents=True, exist_ok=True)

    total = clean = 0
    for chapter in chapters:
        merged, problems = merge_chapter(chapter)
        count = len(merged["items"]) if merged else 0
        total += count
        blocking = [p for p in problems if "missing " not in p]
        tags_missing = len(problems) - len(blocking)
        status = "ok" if not problems else f"{len(blocking)} issue(s)"
        if not problems:
            clean += 1
        print(f"ch{chapter:02d}  {count:>4} items  {status}"
              + (f"  ({tags_missing} untagged)" if tags_missing else ""))
        for problem in blocking[:8]:
            print(f"      ! {problem}")
        if len(blocking) > 8:
            print(f"      ! ... and {len(blocking) - 8} more")
        if merged and a.write:
            path = out_dir / f"ch{chapter:02d}.json"
            path.write_text(json.dumps(merged, indent=1, ensure_ascii=False),
                            encoding="utf-8")

    print(f"\n{total} item(s) across {len(chapters)} chapter(s); {clean} clean")
    if a.write:
        print(f"written to {out_dir}")
    else:
        print("report only - re-run with --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
