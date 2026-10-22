"""Re-file KVS English draft items onto the chapters a page map assigns.

    python -m scripts.rechapter_kvs_english --class 9
    python -m scripts.rechapter_kvs_english --class 9 --write

`parse_kvs_english` carries the last matched lesson heading forward, because
most boundaries in the book are not headed. That is a guess, and it was wrong:
127 of 219 items landed on "Follow That Dream" spanning pages 71-152, and 56
on "How I Taught My Grandmother to Read" including pages 10-18 and 31, which
are unseen reading passages and writing-section pages belonging to no chapter
at all.

A reader then mapped all 154 pages against the book's own index and the
chapters' concept lists. This applies that map. It is the same repair as
`refile_class8_science`, which moved 627 questions off one chapter, and it has
the same shape: the source knew the answer all along, and the loader guessed.

TWO THINGS THIS DELIBERATELY DROPS RATHER THAN GUESSES.

  * Pages the map leaves unassigned -- front matter, the Reading Skills
    section's unseen passages, generic Writing and Grammar exercises, and the
    three model papers. A model-paper page is not single-chapter: page 114
    alone carries extracts from chapters 1, 6 and 7. Those need attribution
    per question, not per page, so they are excluded here and reported.

  * Items on a SPLIT page whose minority portion belongs to another chapter.
    Twelve pages genuinely hold two chapters; the map records each boundary's
    y-coordinate. Page 64 is near 50/50 -- Class 5's unsolved long answers
    above, Twin Melodies' first extract below. This script cannot tell which
    half an item came from, because the draft records a page but not a
    y-position, so items on those pages are flagged `needs_split_review`
    rather than silently assigned.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent / "kvs_eng_items"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--class", dest="klass", type=int, default=9)
    ap.add_argument("--write", action="store_true", help="rewrite the drafts file")
    a = ap.parse_args()

    bmap = json.loads((BASE / f"c{a.klass}_english_boundaries.json").read_text(encoding="utf-8"))
    draft_path = BASE / "drafts" / f"c{a.klass}_english_kvs.json"
    draft = json.loads(draft_path.read_text(encoding="utf-8"))

    page_to: dict[int, dict] = {}
    for r in bmap.get("ranges", []):
        for p in range(r["from"], r["to"] + 1):
            page_to[p] = r
    unassigned: dict[int, str] = {}
    for u in bmap.get("unassigned", []):
        for p in range(u["from"], u["to"] + 1):
            unassigned[p] = u.get("why", "not chapter-specific")
    split = {int(s["page"]) for s in bmap.get("split_pages", [])}

    kept, dropped, flagged = [], [], 0
    moved = 0
    for it in draft.get("items", []):
        page = int(it.get("page") or 0)
        if page in unassigned:
            dropped.append((page, unassigned[page]))
            continue
        r = page_to.get(page)
        if not r:
            dropped.append((page, "page not in the map"))
            continue
        if r.get("chapter_id") != it.get("chapter_id"):
            moved += 1
        it["chapter_id"] = r["chapter_id"]
        it["chapter"] = r.get("chapter")
        it["sort_order"] = r.get("sort_order")
        if page in split:
            it["needs_split_review"] = True
            flagged += 1
        kept.append(it)

    answered = [i for i in kept if i.get("answer")]
    per: dict[str, dict[str, int]] = {}
    for i in kept:
        d = per.setdefault(i["chapter"], {"all": 0, "ans": 0})
        d["all"] += 1
        if i.get("answer"):
            d["ans"] += 1

    print(f"Class {a.klass} English -- re-chaptered against the page map\n")
    print(f"  items in the draft      {len(draft.get('items', []))}")
    print(f"  moved to a new chapter  {moved}")
    print(f"  dropped (no chapter)    {len(dropped)}")
    print(f"  kept                    {len(kept)}")
    print(f"  of those, answered      {len(answered)}   <- loadable")
    print(f"  flagged for split page  {flagged}\n")
    print(f"  {'chapter':<40} {'items':>6} {'answered':>9}")
    print("  " + "-" * 58)
    for r in sorted(bmap.get("ranges", []), key=lambda x: x.get("sort_order", 0)):
        nm = r.get("chapter")
        if nm in per:
            print(f"  {nm[:40]:<40} {per[nm]['all']:>6} {per[nm]['ans']:>9}")
            per.pop(nm)

    why: dict[str, int] = {}
    for _, reason in dropped:
        why[reason] = why.get(reason, 0) + 1
    print("\n  dropped, by reason:")
    for reason, n in sorted(why.items(), key=lambda x: -x[1]):
        print(f"      {n:>4}  {reason[:66]}")

    if a.write:
        draft["items"] = kept
        draft["chapter_map"] = f"c{a.klass}_english_boundaries.json"
        draft_path.write_text(json.dumps(draft, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\nrewrote {draft_path.name}")
    else:
        print("\nreport only - re-run with --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
