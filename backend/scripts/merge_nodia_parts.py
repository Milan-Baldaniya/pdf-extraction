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


def parts_for(chapter: int) -> list[Path]:
    return sorted(PARTS.glob(f"ch{chapter:02d}_*.json"))


def merge(chapter: int) -> dict:
    cid, eid = CHAPTERS[chapter]
    target = ROOT / f"ch{chapter:02d}.json"
    if target.exists():
        data = json.load(io.open(target, encoding="utf-8"))
    else:
        data = {"chapter": chapter, "chapter_id": cid, "extraction_id": eid, "items": []}
    data.setdefault("items", [])
    data["chapter"], data["chapter_id"], data["extraction_id"] = chapter, cid, eid

    by_number = {str(i.get("number")): i for i in data["items"]}
    added = kept = 0
    for path in parts_for(chapter):
        part = json.load(io.open(path, encoding="utf-8"))
        for item in part.get("items") or []:
            number = str(item.get("number"))
            if number in by_number:
                kept += 1
                continue
            by_number[number] = item
            added += 1

    def sort_key(i):
        m = re.match(r"^(\d+)", str(i.get("number") or ""))
        return (int(m.group(1)) if m else 10**9, str(i.get("number")))

    data["items"] = sorted(by_number.values(), key=sort_key)
    io.open(target, "w", encoding="utf-8").write(
        json.dumps(data, ensure_ascii=False, indent=1))
    return {"chapter": chapter, "parts": len(parts_for(chapter)),
            "added": added, "already_present": kept, "total": len(data["items"])}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chapter", type=int)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
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
        r = merge(ch)
        print(f"  ch {r['chapter']:<3} parts={r['parts']:<3} added={r['added']:<5} "
              f"already_present={r['already_present']:<5} total={r['total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
