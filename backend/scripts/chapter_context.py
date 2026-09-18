"""Print everything an item author needs about a chapter, in one place.

    python -m scripts.chapter_context 221

Prints the exact concept names an item may cite and the exact image file names
an item may reference. Both are closed lists: a concept name that is not printed
here is rejected by the loader, and an image name that is not printed here is
silently dropped by the writer, storing a question with no figure. Reading them
from here rather than guessing is what keeps those two failures from happening.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text  # noqa: E402
from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("extraction_id", type=int)
    a = ap.parse_args()
    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        row = db.execute(text(
            "SELECT d.chapter_id, c.chapter_name, d.asset_manifest, LENGTH(d.md_content) "
            "  FROM document_extractions d JOIN chapter_master c ON c.id = d.chapter_id "
            " WHERE d.id = :i"), {"i": a.extraction_id}).fetchone()
        if not row:
            raise SystemExit(f"extraction {a.extraction_id} not found")
        chapter_id, name, manifest, md_len = row
        print(f"extraction {a.extraction_id} | chapter_id {chapter_id} | {name} | {md_len:,} md chars\n")

        print("CONCEPTS - use one of these EXACT strings as an item's \"concept\":")
        for r in db.execute(text(
            "SELECT name FROM lms_concept WHERE chapter_id = :c "
            "  AND (concept_show_hide IS NULL OR concept_show_hide <> 0) ORDER BY id"),
            {"c": chapter_id}).fetchall():
            print(f"  - {r[0]}")

        entries = json.loads(manifest) if isinstance(manifest, str) else (manifest or [])
        print(f"\nIMAGES - {len(entries)} available. Use the bare file name in \"images\":")
        for e in sorted(entries, key=lambda x: (x.get("page_number") or 0)):
            print(f"  p{str(e.get('page_number')):<4} {e.get('width')}x{e.get('height'):<6} {e.get('file_name')}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
