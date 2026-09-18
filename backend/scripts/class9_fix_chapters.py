"""Two Class 9 chapter defects that survive the concept work.

    python -m scripts.class9_fix_chapters --dry
    python -m scripts.class9_fix_chapters --apply
    python -m scripts.class9_fix_chapters --revert

1. Chapter 8625 'Hindi Curriculum ' holds no concepts, no topics and no content
   rows. It is a placeholder that renders as an empty chapter in the tree, so it
   is hidden rather than deleted - if it turns out to be a stub someone intends
   to fill, unhiding it is one statement.

2. Chapter 8638 is named 'Follow ThFollow That Dreamat Dream' - the title
   interleaved with itself by a bad edit. The NCERT chapter is 'Follow That
   Dream'.

Both are logged to class9_curriculum_log, and the hide refuses to run if the
chapter has gained concepts or content since this was written.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REASON_HIDE = "hide_empty_chapter"
REASON_NAME = "fix_chapter_name"

EMPTY_CHAPTER = 8625
RENAMES = {8638: "Follow That Dream"}


def _session():
    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    return SessionLocal()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--revert", action="store_true")
    args = parser.parse_args()
    if not (args.dry or args.apply or args.revert):
        parser.error("choose --dry, --apply or --revert")

    db = _session()
    try:
        if args.revert:
            rows = db.execute(
                text(
                    "SELECT id, row_id, column_name, prev_value FROM class9_curriculum_log "
                    " WHERE reason IN (:a, :b) AND reverted_at IS NULL"
                ),
                {"a": REASON_HIDE, "b": REASON_NAME},
            ).fetchall()
            for log_id, rid, col, prev in rows:
                if col == "show_hide":
                    db.execute(
                        text("UPDATE chapter_master SET show_hide = :v WHERE id = :i"),
                        {"v": None if prev in (None, "NULL") else int(prev), "i": int(rid)},
                    )
                else:
                    db.execute(
                        text("UPDATE chapter_master SET chapter_name = :v WHERE id = :i"),
                        {"v": prev, "i": int(rid)},
                    )
                db.execute(
                    text("UPDATE class9_curriculum_log SET reverted_at = NOW() WHERE id = :i"),
                    {"i": int(log_id)},
                )
            db.commit()
            print(f"reverted {len(rows)} chapter change(s)")
            return 0

        # --- the empty chapter -------------------------------------------------
        row = db.execute(
            text("SELECT id, chapter_name, show_hide FROM chapter_master WHERE id = :i"),
            {"i": EMPTY_CHAPTER},
        ).fetchone()
        if not row:
            print(f"  chapter {EMPTY_CHAPTER} no longer exists; skipping")
        else:
            concepts = db.execute(
                text(
                    "SELECT COUNT(*) FROM lms_concept WHERE chapter_id = :i "
                    " AND (concept_show_hide IS NULL OR concept_show_hide <> 0)"
                ),
                {"i": EMPTY_CHAPTER},
            ).scalar()
            content = db.execute(
                text("SELECT COUNT(*) FROM content_master WHERE chapter_id = :i"),
                {"i": EMPTY_CHAPTER},
            ).scalar()
            if concepts or content:
                print(f"  REFUSING to hide chapter {EMPTY_CHAPTER}: it now has "
                      f"{concepts} concept(s) and {content} content row(s)")
            elif row[2] == 0:
                print(f"  chapter {EMPTY_CHAPTER} is already hidden")
            else:
                print(f"  hide chapter {EMPTY_CHAPTER} '{row[1]}' "
                      f"(0 concepts, 0 content)" + ("   [DRY RUN]" if args.dry else ""))
                if args.apply:
                    db.execute(
                        text(
                            "INSERT INTO class9_curriculum_log "
                            "(table_name,row_id,column_name,prev_value,new_value,reason) "
                            "VALUES ('chapter_master',:r,'show_hide',:p,'0',:why)"
                        ),
                        {"r": EMPTY_CHAPTER,
                         "p": "NULL" if row[2] is None else str(row[2]),
                         "why": REASON_HIDE},
                    )
                    db.execute(
                        text("UPDATE chapter_master SET show_hide = 0 WHERE id = :i"),
                        {"i": EMPTY_CHAPTER},
                    )

        # --- the corrupted title ----------------------------------------------
        for cid, correct in RENAMES.items():
            row = db.execute(
                text("SELECT id, chapter_name FROM chapter_master WHERE id = :i"),
                {"i": cid},
            ).fetchone()
            if not row:
                print(f"  chapter {cid} no longer exists; skipping")
                continue
            if row[1] == correct:
                print(f"  chapter {cid} is already named correctly")
                continue
            print(f"  rename chapter {cid}: '{row[1]}' -> '{correct}'"
                  + ("   [DRY RUN]" if args.dry else ""))
            if args.apply:
                db.execute(
                    text(
                        "INSERT INTO class9_curriculum_log "
                        "(table_name,row_id,column_name,prev_value,new_value,reason) "
                        "VALUES ('chapter_master',:r,'chapter_name',:p,:n,:why)"
                    ),
                    {"r": cid, "p": row[1], "n": correct, "why": REASON_NAME},
                )
                db.execute(
                    text("UPDATE chapter_master SET chapter_name = :n WHERE id = :i"),
                    {"n": correct, "i": cid},
                )

        if args.apply:
            db.commit()
            print("  applied")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
