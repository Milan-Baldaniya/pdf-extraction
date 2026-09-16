"""Put the Class 10 Science questions back on the chapters they belong to.

The questions were imported against the OLD 16-chapter CBSE Science syllabus,
while `chapter_master` holds the rationalised 13-chapter one. CBSE removed
"Periodic Classification of Elements" (old ch 5), so everything from old
chapter 6 onward is stored one chapter too high:

    chapter 1021 is named "The Human Eye" and holds Light questions (86% fit).

Measured before writing this: each affected chapter fits its own name by 0-9%
and fits its old-syllabus position by 29-86%. A student practising "The Human
Eye" is served Light questions, and concept mapping cannot work at all,
because no concept of the named chapter matches the stored question.

Three old chapters have no home in the current syllabus. Their questions are
soft-deleted rather than moved: serving a student a chapter CBSE has removed
is worse than not serving it, and `deleted_at` keeps them recoverable.

Every move is recorded first in `lms_question_chapter_fix` so the whole
operation can be reversed with one UPDATE ... JOIN.

    python -m scripts.fix_class10_science_chapter_shift --dry
    python -m scripts.fix_class10_science_chapter_shift
    python -m scripts.fix_class10_science_chapter_shift --revert
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal  # noqa: E402

# old-syllabus slot -> the chapter whose content it actually is.
MOVES = {
    1017: 1016,  # Life Processes
    1018: 1017,  # Control and Coordination
    1019: 1018,  # How do Organisms Reproduce?
    1020: 1019,  # Heredity
    1021: 1020,  # Light - Reflection and Refraction
    1022: 1021,  # The Human Eye and the Colourful World
    1023: 1022,  # Electricity
    1024: 1023,  # Magnetic Effects of Electric Current
    1026: 1024,  # Our Environment
}

# Chapters CBSE removed from the syllabus. Their questions are soft-deleted.
REMOVED = {
    1016: "Periodic Classification of Elements",
    1025: "Sources of Energy",
    1027: "Management of Natural Resources",
}

BACKUP = "lms_question_chapter_fix"


def ensure_backup(db) -> None:
    db.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {BACKUP} (
                question_id      BIGINT UNSIGNED NOT NULL PRIMARY KEY,
                old_chapter_id   BIGINT UNSIGNED NULL,
                new_chapter_id   BIGINT UNSIGNED NULL,
                action           VARCHAR(16) NOT NULL,
                moved_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                KEY idx_old (old_chapter_id)
            )
            """
        )
    )


def report(db) -> None:
    print(f"{'chapter':<9}{'holds':<42}{'n':>6}  action")
    print("-" * 78)
    total_move = total_del = 0
    for src, dst in sorted(MOVES.items()):
        n = db.execute(
            text(
                "SELECT COUNT(*) FROM lms_question_master "
                "WHERE chapter_id = :c AND deleted_at IS NULL"
            ),
            {"c": src},
        ).scalar()
        name = db.execute(
            text("SELECT chapter_name FROM chapter_master WHERE id = :c"), {"c": dst}
        ).scalar()
        total_move += n
        print(f"{src:<9}{str(name)[:40]:<42}{n:>6}  -> {dst}")
    for src, label in sorted(REMOVED.items()):
        n = db.execute(
            text(
                "SELECT COUNT(*) FROM lms_question_master "
                "WHERE chapter_id = :c AND deleted_at IS NULL"
            ),
            {"c": src},
        ).scalar()
        total_del += n
        print(f"{src:<9}{label[:40]:<42}{n:>6}  -> soft-delete (not in syllabus)")
    print("-" * 78)
    print(f"{'':<51}{total_move:>6}  to move")
    print(f"{'':<51}{total_del:>6}  to soft-delete")


def apply(db) -> None:
    ensure_backup(db)

    # Snapshot FIRST. The moves form a chain (1017->1016, 1018->1017, ...), so
    # applying them one after another against live rows would sweep the same
    # questions forward twice. Recording the original chapter up front means
    # every move is driven by where a question STARTED.
    for src, dst in MOVES.items():
        db.execute(
            text(
                f"""
                INSERT INTO {BACKUP} (question_id, old_chapter_id, new_chapter_id, action)
                SELECT id, chapter_id, :dst, 'move' FROM lms_question_master
                 WHERE chapter_id = :src AND deleted_at IS NULL
                ON DUPLICATE KEY UPDATE old_chapter_id = VALUES(old_chapter_id)
                """
            ),
            {"src": src, "dst": dst},
        )
    for src in REMOVED:
        db.execute(
            text(
                f"""
                INSERT INTO {BACKUP} (question_id, old_chapter_id, new_chapter_id, action)
                SELECT id, chapter_id, NULL, 'soft_delete' FROM lms_question_master
                 WHERE chapter_id = :src AND deleted_at IS NULL
                ON DUPLICATE KEY UPDATE old_chapter_id = VALUES(old_chapter_id)
                """
            ),
            {"src": src},
        )

    moved = db.execute(
        text(
            f"""
            UPDATE lms_question_master q
              JOIN {BACKUP} b ON b.question_id = q.id AND b.action = 'move'
               SET q.chapter_id = b.new_chapter_id
            """
        )
    ).rowcount

    deleted = db.execute(
        text(
            f"""
            UPDATE lms_question_master q
              JOIN {BACKUP} b ON b.question_id = q.id AND b.action = 'soft_delete'
               SET q.deleted_at = NOW()
             WHERE q.deleted_at IS NULL
            """
        )
    ).rowcount

    # Keep the extraction sidecar in step where one exists.
    synced = db.execute(
        text(
            """
            UPDATE lms_question_extraction e
              JOIN lms_question_master q ON q.id = e.question_id
               SET e.sub_institute_id = e.sub_institute_id
             WHERE q.chapter_id BETWEEN 1012 AND 1024
            """
        )
    ).rowcount

    db.commit()
    print(f"moved={moved}  soft_deleted={deleted}  sidecars_touched={synced}")


def revert(db) -> None:
    n = db.execute(
        text(
            f"""
            UPDATE lms_question_master q
              JOIN {BACKUP} b ON b.question_id = q.id
               SET q.chapter_id = b.old_chapter_id,
                   q.deleted_at = CASE WHEN b.action = 'soft_delete' THEN NULL ELSE q.deleted_at END
            """
        )
    ).rowcount
    db.commit()
    print(f"reverted {n} question(s) to their original chapter")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry", action="store_true", help="report only")
    parser.add_argument("--revert", action="store_true", help="undo a previous run")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.revert:
            revert(db)
        elif args.dry:
            report(db)
        else:
            report(db)
            print()
            apply(db)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
