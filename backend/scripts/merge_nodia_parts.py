"""Merge per-section item files into one file per chapter.

    python -m scripts.merge_nodia_parts --list
    python -m scripts.merge_nodia_parts --chapter 1
    python -m scripts.merge_nodia_parts --all

Section readers each write scripts/nodia_items/parts/ch<NN>_<section>.json as
{"items":[...]}. This folds those into scripts/nodia_items/ch<NN>.json, which is
what load_nodia_items reads.

Merging is additive and idempotent: an item whose printed number already exists
in the chapter file is kept as-is rather than replaced, so re-running after one
section is re-read never duplicates and never silently overwrites a hand-checked
item. Numbers genuinely repeat across sections in some chapters, so a collision
is reported rather than assumed to be an error.
"""
from __future__ import annotations
import argparse, io, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent / "nodia_items"
PARTS = ROOT / "parts"

# chapter number -> (chapter_id, extraction_id), resolved from the database so
# this keeps working as later chapters finish extracting. Hardcoding the ids
# would mean editing this file every time a chapter lands, and a stale id here
# would attach a chapter's questions to the wrong extraction row.
def _chapter_map() -> dict[int, tuple[int, int]]:
    from sqlalchemy import text
    from app.db.mariadb import SessionLocal, init_mariadb
    from scripts.extract_sci10_qbank import CHAPTERS as PAGE_MAP, STANDARD_ID, SUBJECT_ID

    by_chapter_id = {cid: num for num, cid, _ in PAGE_MAP.values() if cid}
    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT chapter_id, MAX(id) FROM document_extractions "
            " WHERE standard_id = :s AND subject_id = :su "
            "   AND document_type = 'question_bank' AND extraction_status = 'extracted' "
            " GROUP BY chapter_id"), {"s": STANDARD_ID, "su": SUBJECT_ID}).fetchall()
    finally:
        db.close()
    return {by_chapter_id[c]: (int(c), int(e)) for c, e in rows if c in by_chapter_id}


CHAPTERS = _chapter_map()


def _norm_stem(value) -> str:
    """Compare stems by their words alone.

    Punctuation and line breaks differ freely between two readings of the same
    printed question - "equation:" against "equation." - and comparing raw text
    treated five identical chapter-1 questions as new, duplicating them. Only
    the letters and digits decide.
    """
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()[:140]


def parts_for(chapter: int) -> list[Path]:
    return sorted(PARTS.glob(f"ch{chapter:02d}_*.json"))


def _restarts_numbering(chapter: int) -> bool:
    """Does this chapter restart its question numbering in each section?

    Most chapters number straight through - chapter 1 runs 1..263 across all six
    sections - so the same number appearing twice means one question was read
    twice, and the second copy must be dropped. Chapter 3 genuinely restarts
    (OBJECTIVE 1-63, then ONE MARK 1-86), where the same number is two different
    questions and dropping one costs 63 real items.

    The tell is whether more than one section file opens at a low number.
    """
    openers = 0
    for path in parts_for(chapter):
        try:
            items = json.load(io.open(path, encoding="utf-8")).get("items") or []
        except Exception:
            continue
        numbers = []
        for i in items:
            m = re.match(r"^(\d+)", str(i.get("number") or ""))
            if m:
                numbers.append(int(m.group(1)))
        if numbers and min(numbers) <= 2:
            openers += 1
    return openers > 1


# Chapters whose item file contains readings made by hand, not by a section
# reader. Those items exist in no part file, so rebuilding these from parts
# would delete them. Every other chapter is reproducible from its parts.
HAND_AUTHORED = {1, 6}


def merge(chapter: int, refresh: bool = False) -> dict:
    cid, eid = CHAPTERS[chapter]
    target = ROOT / f"ch{chapter:02d}.json"
    if refresh and chapter not in HAND_AUTHORED and parts_for(chapter):
        # The verify pass edits the PART files after a chapter has already been
        # merged, and a plain merge keeps the copy it already has - so a fixed
        # answer key or a removed wrong-chapter item never reaches the database.
        # Refresh discards the merged file and rebuilds from the parts, which
        # are the corrected source. Refused for hand-authored chapters, whose
        # items are not in any part file.
        data = {"chapter": chapter, "chapter_id": cid, "extraction_id": eid, "items": []}
    elif target.exists():
        data = json.load(io.open(target, encoding="utf-8"))
    else:
        data = {"chapter": chapter, "chapter_id": cid, "extraction_id": eid, "items": []}
    data.setdefault("items", [])
    data["chapter"], data["chapter_id"], data["extraction_id"] = chapter, cid, eid

    restarts = _restarts_numbering(chapter)
    by_number = {str(i.get("number")): i for i in data["items"]}
    added = kept = qualified = 0
    for path in parts_for(chapter):
        # ch03_one.json -> "one"
        slug = path.stem.split("_", 1)[1] if "_" in path.stem else path.stem
        part = json.load(io.open(path, encoding="utf-8"))
        for item in part.get("items") or []:
            number = str(item.get("number"))
            existing = by_number.get(number)
            if existing is not None:
                # Same printed number can mean two different things. Some
                # chapters restart numbering per section - chapter 3 prints
                # 1-63 under OBJECTIVE and then 1-86 again under ONE MARK - so
                # a clash is usually two distinct questions, not a duplicate.
                # Compare the stems: identical stem means the section was
                # re-read, so keep what is already there; different stem means
                # a real second question, so qualify its label with the section
                # rather than dropping it. Dropping cost 63 real questions on
                # chapter 3 before this existed.
                same = _norm_stem(existing.get("stem")) == _norm_stem(item.get("stem"))
                if same or not restarts:
                    # Not a restarting chapter, so the number is unique in the
                    # book: this is the same question read a second time, even
                    # when the two readings word the stem differently. Keep the
                    # one already stored.
                    kept += 1
                    continue
                number = f"{number}-{slug}"
                if number in by_number:
                    kept += 1
                    continue
                item = dict(item, number=number)
                qualified += 1
            by_number[number] = item
            added += 1

    def sort_key(i):
        m = re.match(r"^(\d+)", str(i.get("number") or ""))
        return (int(m.group(1)) if m else 10**9, str(i.get("number")))

    data["items"] = sorted(by_number.values(), key=sort_key)
    data["qualified_numbers"] = qualified
    io.open(target, "w", encoding="utf-8").write(
        json.dumps(data, ensure_ascii=False, indent=1))
    return {"chapter": chapter, "parts": len(parts_for(chapter)), "added": added,
            "already_present": kept, "qualified": qualified,
            "total": len(data["items"])}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chapter", type=int)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--refresh", action="store_true",
                    help="rebuild from parts so verify-pass corrections land "
                         "(skipped for hand-authored chapters)")
    a = ap.parse_args()

    if a.list or not (a.chapter or a.all):
        print(f"parts in {PARTS}:")
        for p in sorted(PARTS.glob("ch*_*.json")):
            try:
                n = len(json.load(io.open(p, encoding="utf-8")).get("items") or [])
            except Exception as exc:
                n = f"UNREADABLE ({type(exc).__name__})"
            print(f"   {p.name:<26}{n}")
        return 0

    targets = [a.chapter] if a.chapter else sorted(CHAPTERS)
    for ch in targets:
        if ch not in CHAPTERS:
            print(f"  ch {ch}: not mapped, skipping")
            continue
        if not parts_for(ch) and not (ROOT / f"ch{ch:02d}.json").exists():
            continue
        r = merge(ch, refresh=a.refresh)
        print(f"  ch {r['chapter']:<3} parts={r['parts']:<3} added={r['added']:<5} "
              f"already={r['already_present']:<4} qualified={r['qualified']:<4} "
              f"total={r['total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
