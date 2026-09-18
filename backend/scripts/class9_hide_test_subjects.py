"""Hide the test subjects polluting Class 9 CBSE.

    python -m scripts.class9_hide_test_subjects --dry
    python -m scripts.class9_hide_test_subjects --apply
    python -m scripts.class9_hide_test_subjects --revert

subject 5574 'Testing by APi', 5575 'module testing by vivek' and 5576 (unnamed)
hold 34 chapters and 448 concepts inside Class 9 CBSE. They are scratch data, but
other tables may still reference their ids, so this hides rather than deletes:
chapter_master.show_hide, topic_master.topic_show_hide and
lms_concept.concept_show_hide all go to 0, and every previous value is logged so
--revert restores exactly what was there.

Each previous value is stored as text, so a row that was NULL comes back NULL.
An INT column cannot tell "was NULL" from "was 0", and 44 chapters are NULL.
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text  # noqa: E402
from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

STD = 42
TEST_SUBJECTS = (5574, 5575, 5576)
NULL_SENTINEL = "NULL"

LOG_DDL = """
CREATE TABLE IF NOT EXISTS class9_curriculum_log (
    id          BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    table_name  VARCHAR(64)  NOT NULL,
    row_id      BIGINT       NOT NULL,
    column_name VARCHAR(64)  NOT NULL,
    prev_value  VARCHAR(64)  NULL,
    new_value   VARCHAR(64)  NULL,
    reason      VARCHAR(64)  NOT NULL,
    reverted_at DATETIME     NULL,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_c9_row (table_name, row_id),
    KEY idx_c9_reason (reason, reverted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

# table -> (visibility column, SQL selecting the ids that belong to the test subjects)
TARGETS = {
    "chapter_master": ("show_hide",
        f"SELECT id FROM chapter_master WHERE standard_id={STD} AND subject_id IN :subs"),
    "topic_master": ("topic_show_hide",
        f"SELECT id FROM topic_master WHERE chapter_id IN "
        f"(SELECT id FROM chapter_master WHERE standard_id={STD} AND subject_id IN :subs)"),
    "lms_concept": ("concept_show_hide",
        f"SELECT id FROM lms_concept WHERE standard_id={STD} AND subject_id IN :subs"),
}
REASON = "hide_test_subject"


def _session():
    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    return SessionLocal()


def apply(db, dry: bool) -> None:
    db.execute(text(LOG_DDL)); db.commit()
    for table, (col, id_sql) in TARGETS.items():
        rows = db.execute(text(f"SELECT id, {col} FROM {table} WHERE id IN ({id_sql})"),
                          {"subs": TEST_SUBJECTS}).fetchall()
        todo = [(int(r[0]), r[1]) for r in rows if r[1] != 0]
        print(f"   {table:<16} {len(rows):>5} row(s), {len(todo):>5} to hide"
              + ("   [DRY RUN]" if dry else ""))
        if dry or not todo:
            continue
        for rid, prev in todo:
            db.execute(text(
                "INSERT INTO class9_curriculum_log "
                "(table_name,row_id,column_name,prev_value,new_value,reason) "
                "VALUES (:t,:r,:c,:p,'0',:why)"),
                {"t": table, "r": rid, "c": col,
                 "p": NULL_SENTINEL if prev is None else str(prev), "why": REASON})
        ids = [r for r, _ in todo]
        for i in range(0, len(ids), 500):
            db.execute(text(f"UPDATE {table} SET {col}=0 WHERE id IN :ids"),
                       {"ids": tuple(ids[i:i+500])})
        db.commit()


def revert(db) -> None:
    rows = db.execute(text(
        "SELECT id,table_name,row_id,column_name,prev_value FROM class9_curriculum_log "
        " WHERE reason=:why AND reverted_at IS NULL"), {"why": REASON}).fetchall()
    for log_id, table, rid, col, prev in rows:
        if prev == NULL_SENTINEL:
            db.execute(text(f"UPDATE {table} SET {col}=NULL WHERE id=:i"), {"i": int(rid)})
        else:
            db.execute(text(f"UPDATE {table} SET {col}=:v WHERE id=:i"),
                       {"v": int(prev), "i": int(rid)})
        db.execute(text("UPDATE class9_curriculum_log SET reverted_at=NOW() WHERE id=:i"),
                   {"i": int(log_id)})
    db.commit()
    print(f"   reverted {len(rows)} row(s)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()
    if not (a.dry or a.apply or a.revert):
        ap.error("choose --dry, --apply or --revert")
    db = _session()
    try:
        if a.revert:
            print("REVERT"); revert(db)
        else:
            print(f"HIDE test subjects {TEST_SUBJECTS} in Class 9 (standard {STD})")
            apply(db, dry=a.dry)
        vis = db.execute(text(f"""
            SELECT COUNT(*) FROM lms_concept
             WHERE standard_id={STD} AND (concept_show_hide IS NULL OR concept_show_hide<>0)""")).scalar()
        print(f"\n   Class 9 visible concepts now: {vis}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
