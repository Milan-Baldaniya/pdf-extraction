"""Print each section's character range in a chapter's markdown.

    python -m scripts.section_map --extraction 597
    python -m scripts.section_map --extraction 597 --dump <dir>

A section reader is given a range and told to check every item in it against
the printed text. The ranges come from `parse_qbank_items.find_sections`, the
same code that split the drafts, so a reader's range and their draft file
always describe the same block of the book. Deriving the ranges by hand from a
banner regex does not: the letter-spaced banners are mixed case ("NCER T
Exercis e"), so a quick uppercase-only search silently misses whole sections.

--dump also writes the markdown and the chapter's legal concept names next to
each other, which is everything a reader needs and nothing they should not
have (no database, no loader).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402
from scripts.parse_qbank_items import find_sections  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--extraction", type=int, required=True)
    ap.add_argument("--dump", help="directory to write source + concepts into")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT chapter_id, document_tittle, md_content "
                 "FROM document_extractions WHERE id = :e"),
            {"e": a.extraction},
        ).fetchone()
        if not row:
            raise SystemExit(f"no extraction {a.extraction}")
        chapter_id, title, md = row
        chapter = db.execute(
            text("SELECT sort_order, chapter_name FROM chapter_master WHERE id = :c"),
            {"c": chapter_id},
        ).fetchone()
        concepts = [
            r[0] for r in db.execute(
                text("SELECT name FROM lms_concept WHERE chapter_id = :c "
                     "  AND (concept_show_hide IS NULL OR concept_show_hide <> 0) "
                     "ORDER BY id"),
                {"c": chapter_id},
            ).fetchall()
        ]
    finally:
        db.close()

    print(f"extraction {a.extraction}  chapter_id {chapter_id}  "
          f"ch{chapter[0]} {chapter[1]!r}")
    print(f"{len(md):,} chars, {len(concepts)} legal concept name(s)\n")

    sections = find_sections(md)
    for index, section in enumerate(sections):
        start = section["start"]
        end = sections[index + 1]["start"] if index + 1 < len(sections) else len(md)
        print(f"  {section['slug']:<10} {start:>7} - {end:<7} "
              f"({end - start:>6,} chars)  form={section['form']}")
    if not sections:
        print("  no section banners found")

    if a.dump:
        out = Path(a.dump)
        out.mkdir(parents=True, exist_ok=True)
        stem = f"ch{chapter[0]:02d}"
        (out / f"{stem}_source.md").write_text(md, encoding="utf-8")
        (out / f"{stem}_concepts.txt").write_text("\n".join(concepts), encoding="utf-8")
        print(f"\nwrote {stem}_source.md and {stem}_concepts.txt to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
