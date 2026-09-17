"""Create the subject and chapter_master rows a queue sheet needs.

Extraction stores `standard_id`, `subject_id` and `chapter_id` alongside the
markdown, and `_map_ids` derives all three by looking up the names the sheet
carries. A name that matches nothing is not an error -- the row is written with
a NULL id and the extraction succeeds, so the chapter is in the database and
invisible to everything that looks for it by class and subject.

For the NCERT Class 9 and 10 sheets that is 349 of 405 chapters: the tenant has
no Arts, Sanskrit, Urdu, Skill Education or Vocational subject, and no
chapter_master rows for any book but Maths and Science. This creates them, so
the ids resolve on the way in rather than needing a backfill afterwards.

It follows the same sequence the "Others" option on the extraction form uses --
subject, then sub_std_map, then chapter_master -- so a subject created here is
indistinguishable from one created through the UI.

    python -m scripts.seed_master_from_sheet --sheet queue/class9_cbse_queue.xlsx
    python -m scripts.seed_master_from_sheet --sheet queue/*.xlsx --apply
    python -m scripts.seed_master_from_sheet --rollback queue/seed_20260917.json

Nothing is written without --apply. Every insert is recorded to a rollback file
first, so the whole thing can be undone by id. Existing rows are never touched:
this only ever inserts what is missing.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402
from app.utils.config import settings  # noqa: E402
from scripts import queue_sheet as qs  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
logger = logging.getLogger("seed")

QUEUE_DIR = Path(__file__).resolve().parents[1] / "queue"

# chapter_master rows the app creates carry these; mirrored so a seeded chapter
# behaves like one the pipeline made.
DEFAULT_AVAILABILITY = 1
DEFAULT_SHOW_HIDE = 1


def _tenant(row: qs.QueueRow) -> int:
    return row.sub_institute_id or settings.tenant_for_board(row.board)


# --------------------------------------------------------------------------
# planning -- read everything, decide everything, write nothing
# --------------------------------------------------------------------------

def plan(sheets: list[Path]) -> dict[str, Any]:
    """What is missing, without changing anything."""
    rows: list[qs.QueueRow] = []
    for sheet in sheets:
        loaded = qs.load(sheet)
        logger.info("%-32s %d row(s)", sheet.name, len(loaded))
        rows.extend(loaded)

    new_subjects: dict[tuple[int, str], dict[str, Any]] = {}
    new_chapters: list[dict[str, Any]] = []
    new_maps: dict[tuple[int, int, str], dict[str, Any]] = {}
    problems: list[str] = []

    with SessionLocal() as db:
        standards: dict[tuple[int, str], int | None] = {}
        subjects: dict[tuple[int, str], int | None] = {}
        grades: dict[int, int | None] = {}
        existing_chapters: dict[tuple[int, int, int], set[int]] = {}

        for row in rows:
            if not row.is_enabled():
                continue
            tenant = _tenant(row)

            std_key = (tenant, str(row.standard))
            if std_key not in standards:
                found = db.execute(
                    text("SELECT id FROM standard WHERE name = :n AND sub_institute_id = :t LIMIT 1"),
                    {"n": str(row.standard), "t": tenant},
                ).fetchone()
                standards[std_key] = int(found[0]) if found else None
            standard_id = standards[std_key]
            if standard_id is None:
                # Standards are not created here. A class that does not exist is
                # a sheet mistake, not missing master data.
                problems.append(f"class {row.standard} does not exist for tenant {tenant}")
                continue

            sub_key = (tenant, row.subject_name.strip().lower())
            if sub_key not in subjects:
                found = db.execute(
                    text(
                        "SELECT id FROM subject WHERE subject_name = :n "
                        "AND sub_institute_id = :t LIMIT 1"
                    ),
                    {"n": row.subject_name.strip(), "t": tenant},
                ).fetchone()
                subjects[sub_key] = int(found[0]) if found else None

            subject_id = subjects[sub_key]
            if subject_id is None and sub_key not in new_subjects:
                new_subjects[sub_key] = {
                    "tenant": tenant,
                    "subject_name": row.subject_name.strip(),
                    "board": row.board,
                }

            # grade_id is copied from a sibling chapter of the same class rather
            # than invented; the column is unused by extraction but every real
            # row has one.
            if standard_id not in grades:
                found = db.execute(
                    text(
                        "SELECT grade_id FROM chapter_master WHERE standard_id = :s "
                        "AND sub_institute_id = :t AND grade_id IS NOT NULL LIMIT 1"
                    ),
                    {"s": standard_id, "t": tenant},
                ).fetchone()
                grades[standard_id] = int(found[0]) if found else None

            if subject_id is not None:
                ch_key = (tenant, standard_id, subject_id)
                if ch_key not in existing_chapters:
                    found = db.execute(
                        text(
                            "SELECT sort_order FROM chapter_master WHERE sub_institute_id = :t "
                            "AND standard_id = :s AND subject_id = :u AND sort_order IS NOT NULL"
                        ),
                        {"t": tenant, "s": standard_id, "u": subject_id},
                    ).fetchall()
                    existing_chapters[ch_key] = {int(r[0]) for r in found}
                if row.chapter_number in existing_chapters[ch_key]:
                    continue  # already there; never touched

            new_maps.setdefault(
                (tenant, standard_id, row.subject_name.strip().lower()),
                {"tenant": tenant, "standard_id": standard_id, "subject": row.subject_name.strip()},
            )
            new_chapters.append(
                {
                    "tenant": tenant,
                    "standard_id": standard_id,
                    "subject": row.subject_name.strip(),
                    "subject_id": subject_id,  # None until the subject is created
                    "grade_id": grades.get(standard_id),
                    "chapter_name": row.document_title.strip(),
                    "sort_order": row.chapter_number,
                    "syear": row.syear,
                    "standard": row.standard,
                }
            )

    return {
        "subjects": list(new_subjects.values()),
        "chapters": new_chapters,
        "maps": list(new_maps.values()),
        "problems": problems,
    }


# --------------------------------------------------------------------------
# applying
# --------------------------------------------------------------------------

def apply(work: dict[str, Any], created_by: int) -> dict[str, Any]:
    """Insert what is missing, recording every id for rollback."""
    written: dict[str, Any] = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "subject_ids": [],
        "sub_std_map_ids": [],
        "chapter_ids": [],
    }

    with SessionLocal() as db:
        try:
            # 1. subjects -- same columns and defaults as the form's "Others".
            created: dict[tuple[int, str], int] = {}
            for entry in work["subjects"]:
                tenant, name = entry["tenant"], entry["subject_name"]
                max_id = db.execute(text("SELECT MAX(id) FROM subject")).scalar() or 0
                suffix = (entry.get("board") or "").strip().upper() or str(tenant)
                db.execute(
                    text(
                        "INSERT INTO subject (subject_name, subject_code, subject_type, "
                        "short_name, status, sub_institute_id) "
                        "VALUES (:n, :c, 'Major', :s, 1, :t)"
                    ),
                    {
                        "n": name,
                        "c": str(max_id + 1).zfill(4),
                        "s": f"{name[:5].capitalize()}-{suffix}",
                        "t": tenant,
                    },
                )
                subject_id = int(db.execute(text("SELECT LAST_INSERT_ID()")).scalar())
                created[(tenant, name.lower())] = subject_id
                written["subject_ids"].append(subject_id)
                logger.info("  + subject %-46s id %s", name[:46], subject_id)

            # 2. sub_std_map -- without it the subject exists but belongs to no
            #    class, which is how it would vanish from the UI's dropdowns.
            for entry in work["maps"]:
                tenant = entry["tenant"]
                subject_id = created.get((tenant, entry["subject"].lower()))
                if subject_id is None:
                    found = db.execute(
                        text(
                            "SELECT id FROM subject WHERE subject_name = :n "
                            "AND sub_institute_id = :t LIMIT 1"
                        ),
                        {"n": entry["subject"], "t": tenant},
                    ).fetchone()
                    subject_id = int(found[0]) if found else None
                if subject_id is None:
                    continue
                exists = db.execute(
                    text(
                        "SELECT id FROM sub_std_map WHERE standard_id = :s "
                        "AND subject_id = :u LIMIT 1"
                    ),
                    {"s": entry["standard_id"], "u": subject_id},
                ).fetchone()
                if exists:
                    continue
                db.execute(
                    text(
                        "INSERT INTO sub_std_map (standard_id, subject_id, sub_institute_id, "
                        "display_name) VALUES (:s, :u, :t, :d)"
                    ),
                    {
                        "s": entry["standard_id"],
                        "u": subject_id,
                        "t": tenant,
                        "d": entry["subject"],
                    },
                )
                written["sub_std_map_ids"].append(
                    int(db.execute(text("SELECT LAST_INSERT_ID()")).scalar())
                )

            # 3. chapters.
            for entry in work["chapters"]:
                tenant = entry["tenant"]
                subject_id = entry["subject_id"] or created.get(
                    (tenant, entry["subject"].lower())
                )
                if subject_id is None:
                    found = db.execute(
                        text(
                            "SELECT id FROM subject WHERE subject_name = :n "
                            "AND sub_institute_id = :t LIMIT 1"
                        ),
                        {"n": entry["subject"], "t": tenant},
                    ).fetchone()
                    subject_id = int(found[0]) if found else None
                if subject_id is None:
                    logger.warning("  ! no subject for %s; chapter skipped", entry["subject"])
                    continue

                db.execute(
                    text(
                        "INSERT INTO chapter_master (syear, sub_institute_id, grade_id, "
                        "standard_id, subject_id, chapter_name, chapter_desc, availability, "
                        "show_hide, sort_order, created_by) "
                        "VALUES (:y, :t, :g, :s, :u, :n, '', :a, :h, :o, :b)"
                    ),
                    {
                        "y": entry["syear"],
                        "t": tenant,
                        "g": entry["grade_id"],
                        "s": entry["standard_id"],
                        "u": subject_id,
                        "n": entry["chapter_name"],
                        "a": DEFAULT_AVAILABILITY,
                        "h": DEFAULT_SHOW_HIDE,
                        "o": entry["sort_order"],
                        "b": created_by,
                    },
                )
                written["chapter_ids"].append(
                    int(db.execute(text("SELECT LAST_INSERT_ID()")).scalar())
                )

            db.commit()
        except Exception:
            db.rollback()
            logger.error("Insert failed; nothing was committed")
            raise

    return written


def rollback(path: Path) -> None:
    """Delete exactly what a previous --apply inserted, newest first."""
    record = json.loads(path.read_text(encoding="utf-8"))
    chapters = record.get("chapter_ids") or []
    maps = record.get("sub_std_map_ids") or []
    subjects = record.get("subject_ids") or []

    with SessionLocal() as db:
        try:
            for table, ids in (
                ("chapter_master", chapters),
                ("sub_std_map", maps),
                ("subject", subjects),
            ):
                if not ids:
                    continue
                # Chunked: a 349-id IN list is fine, but this stays safe if a
                # later run seeds far more.
                for start in range(0, len(ids), 500):
                    chunk = ids[start : start + 500]
                    db.execute(
                        text(f"DELETE FROM {table} WHERE id IN :ids").bindparams(
                            __import__("sqlalchemy").bindparam("ids", expanding=True)
                        ),
                        {"ids": chunk},
                    )
                logger.info("  - deleted %d row(s) from %s", len(ids), table)
            db.commit()
        except Exception:
            db.rollback()
            raise
    logger.info("Rolled back %s", path.name)


# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--sheet", type=Path, action="append", help="repeatable")
    parser.add_argument("--apply", action="store_true", help="actually write (default: dry run)")
    parser.add_argument("--created-by", type=int, default=1)
    parser.add_argument("--rollback", type=Path, help="undo a previous --apply from its record")
    parser.add_argument("--record-dir", type=Path, default=QUEUE_DIR)
    args = parser.parse_args()

    if not init_mariadb() or SessionLocal is None:
        logger.error("MariaDB is unreachable; check the MARIADB_* settings in .env")
        return 2

    if args.rollback:
        rollback(args.rollback)
        return 0

    sheets = args.sheet or sorted(QUEUE_DIR.glob("*.xlsx"))
    sheets = [s for s in sheets if not s.name.startswith((".", "~$"))]
    if not sheets:
        logger.error("No queue sheets found")
        return 2

    work = plan(sheets)
    logger.info("")
    logger.info("MISSING MASTER DATA")
    for entry in work["subjects"]:
        logger.info("  subject       %s (tenant %s)", entry["subject_name"], entry["tenant"])
    by_subject: dict[str, int] = {}
    for entry in work["chapters"]:
        by_subject[f"class {entry['standard']} {entry['subject']}"] = (
            by_subject.get(f"class {entry['standard']} {entry['subject']}", 0) + 1
        )
    for name, count in sorted(by_subject.items()):
        logger.info("  chapters %3d  %s", count, name)
    for problem in work["problems"]:
        logger.warning("  ! %s", problem)

    logger.info("")
    logger.info(
        "TOTAL: %d subject(s), %d class-subject link(s), %d chapter(s)",
        len(work["subjects"]),
        len(work["maps"]),
        len(work["chapters"]),
    )

    if not args.apply:
        logger.info("")
        logger.info("Dry run -- nothing was written. Add --apply to insert.")
        return 0

    if not (work["subjects"] or work["chapters"]):
        logger.info("Nothing to do.")
        return 0

    written = apply(work, args.created_by)
    args.record_dir.mkdir(parents=True, exist_ok=True)
    record = args.record_dir / f"seed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    record.write_text(json.dumps(written, indent=2), encoding="utf-8")

    logger.info("")
    logger.info(
        "Inserted %d subject(s), %d link(s), %d chapter(s)",
        len(written["subject_ids"]),
        len(written["sub_std_map_ids"]),
        len(written["chapter_ids"]),
    )
    logger.info("Undo with: python -m scripts.seed_master_from_sheet --rollback %s", record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
