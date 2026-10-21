"""Print everything an item author needs about a chapter, in one place.

    python -m scripts.chapter_context 221

Prints the exact concept names an item may cite, the exact curriculum codes it
may cite, and the exact image file names it may reference. All three are closed
lists, and each fails differently when guessed at:

  * a concept name not printed here is rejected by the loader;
  * a curriculum code not printed here is rejected too, loudly, because a
    mapping onto a code the chapter's curriculum does not contain reads as
    alignment and is not;
  * an image name not printed here is SILENTLY dropped by the writer, storing a
    question with no figure at all.

Reading them from here rather than guessing is what keeps all three from
happening.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text  # noqa: E402
from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402
from app.services import curriculum_frame as curf  # noqa: E402

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
            "SELECT d.chapter_id, c.chapter_name, d.asset_manifest, LENGTH(d.md_content), "
            "       d.standard_id, d.subject_id "
            "  FROM document_extractions d JOIN chapter_master c ON c.id = d.chapter_id "
            " WHERE d.id = :i"), {"i": a.extraction_id}).fetchone()
        if not row:
            raise SystemExit(f"extraction {a.extraction_id} not found")
        chapter_id, name, manifest, md_len, standard_id, subject_id = row
        # md_len is NULL for a chapter read from page images rather than OCR'd.
        # Those rows carry no markdown by design, and formatting None crashed.
        source = f"{md_len:,} md chars" if md_len else "read from page images (no markdown)"
        print(f"extraction {a.extraction_id} | chapter_id {chapter_id} | {name} | {source}\n")

        print("CONCEPTS - use one of these EXACT strings as an item's \"concept\":")
        for r in db.execute(text(
            "SELECT name FROM lms_concept WHERE chapter_id = :c "
            "  AND (concept_show_hide IS NULL OR concept_show_hide <> 0) ORDER BY id"),
            {"c": chapter_id}).fetchall():
            print(f"  - {r[0]}")

        # standard_id/subject_id are passed because a chapter whose unit never
        # mapped falls back to the subject-wide competencies, which is common.
        frame = curf.load_frame(
            db, chapter_id=chapter_id, standard_id=standard_id, subject_id=subject_id
        )
        codes = sorted(frame.codes())
        if codes:
            counts = frame.as_dict()
            print(
                f"\nCURRICULUM - cite these EXACT codes in \"curriculum_codes\", at most "
                f"{curf._MAX_MAPPINGS_PER_CONCEPT} per item."
            )
            print(
                f"  curriculum {frame.curriculum_id} | "
                f"{counts.get('goals', 0)} goals, {counts.get('competencies', 0)} competencies, "
                f"{counts.get('learning_outcomes', 0)} learning outcomes"
            )
            print(frame.prompt_block(limit=60))
            print(f"  legal codes: {', '.join(codes)}")
            print(
                "  Map the QUESTION, not its chapter. A concept usually serves "
                "several outcomes\n  and one question usually probes one of them "
                "-- cite that one."
            )
        else:
            # The quiet, normal case: several books in this ingest have no
            # curriculum recorded. Saying so plainly is what stops a reader
            # inventing a plausible-looking code to fill the field.
            print("\nCURRICULUM - NONE RECORDED for this chapter.")
            print("  OMIT \"curriculum_codes\" entirely. Do not guess a code: an")
            print("  invented one reads as curriculum alignment and is not.")

        entries = json.loads(manifest) if isinstance(manifest, str) else (manifest or [])
        print(f"\nIMAGES - {len(entries)} available. Use the bare file name in \"images\":")
        for e in sorted(entries, key=lambda x: (x.get("page_number") or 0)):
            print(f"  p{str(e.get('page_number')):<4} {e.get('width')}x{e.get('height'):<6} {e.get('file_name')}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
