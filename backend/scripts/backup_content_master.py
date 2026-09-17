"""Dump content_master rows to a local file OUTSIDE every git repository.

    python -m scripts.backup_content_master --duplicates
    python -m scripts.backup_content_master --categories
    python -m scripts.backup_content_master --ids 53829,53831
    python -m scripts.backup_content_master --all-gamma

Why the destination is hard-coded outside the repos: a backup of production
content must not be committable by accident. Putting it in the working tree and
relying on .gitignore leaves it one `git add -f` or one forgotten pattern away
from being pushed, and this table holds every school's material. BACKUP_DIR is
therefore a sibling of the repositories, not a child of one, and the script
refuses to write anywhere inside a directory containing a .git folder.

Every dump is self-contained: the full row, as runnable INSERT statements that
recreate it exactly, plus a CSV for reading by eye. Dumping ids alone would be
useless, since the point of a backup is to restore content that no longer
exists in the table.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Deliberately outside every repository. See the module docstring.
BACKUP_DIR = Path(r"C:\Users\MILAN\content-library-backups")

TABLE = "content_master"

# The strict duplicate key. Nothing whose url or filename differs is included,
# so two same-titled experiments pointing at different PDFs both survive.
DUPE_KEY = (
    "chapter_id, concept_id, title, content_category, url, filename, sub_institute_id"
)

# Category spellings that fragment the tabs, and what each merges into.
CATEGORY_MERGES = {
    "Videos": "Recorded Videos",
    "Presentation": "Classroom Presentation",
    "notes": "Revision Notes",
}


def _assert_outside_git(path: Path) -> None:
    """Refuse to write a production dump anywhere inside a git working tree."""
    for parent in [path, *path.parents]:
        if (parent / ".git").exists():
            raise SystemExit(
                f"REFUSING to write a backup inside a git repository: {parent}\n"
                "Point BACKUP_DIR somewhere outside every repo."
            )


def _session():
    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    return SessionLocal()


def _sql_literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = (
        str(value)
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return f"'{escaped}'"


def select_ids(db, mode: str, explicit: list[int]) -> tuple[list[int], str]:
    """The ids to dump, and a one-line description of why."""
    if mode == "ids":
        return explicit, f"{len(explicit)} explicitly named row(s)"

    if mode == "duplicates":
        rows = db.execute(
            text(
                f"""
                SELECT cm.id
                  FROM {TABLE} cm
                  JOIN (SELECT MIN(id) keeper, {DUPE_KEY}
                          FROM {TABLE} GROUP BY {DUPE_KEY} HAVING COUNT(*) > 1) k
                    ON  (cm.chapter_id       <=> k.chapter_id)
                    AND (cm.concept_id       <=> k.concept_id)
                    AND (cm.title            <=> k.title)
                    AND (cm.content_category <=> k.content_category)
                    AND (cm.url              <=> k.url)
                    AND (cm.filename         <=> k.filename)
                    AND (cm.sub_institute_id <=> k.sub_institute_id)
                 WHERE cm.id <> k.keeper
                 ORDER BY cm.id
                """
            )
        ).fetchall()
        return [int(r[0]) for r in rows], "strict duplicates (keeping the lowest id)"

    if mode == "categories":
        rows = db.execute(
            text(f"SELECT id FROM {TABLE} WHERE content_category IN :c ORDER BY id"),
            {"c": tuple(CATEGORY_MERGES)},
        ).fetchall()
        return [int(r[0]) for r in rows], "rows whose content_category will be merged"

    if mode == "all-gamma":
        rows = db.execute(
            text(
                f"SELECT id FROM {TABLE} "
                " WHERE url LIKE '%gamma%' OR filename LIKE '%gamma%' ORDER BY id"
            )
        ).fetchall()
        return [int(r[0]) for r in rows], "every row referencing gamma"

    raise SystemExit(f"unknown mode {mode!r}")


def dump(ids: list[int], reason: str) -> Path | None:
    if not ids:
        print("nothing to back up")
        return None

    _assert_outside_git(BACKUP_DIR)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sql_path = BACKUP_DIR / f"{TABLE}_{stamp}.sql"
    csv_path = BACKUP_DIR / f"{TABLE}_{stamp}.csv"

    db = _session()
    try:
        cols = [
            r[0]
            for r in db.execute(text(f"SHOW COLUMNS FROM {TABLE}")).fetchall()
        ]
        # Chunked: a single IN with thousands of ids is fine for MariaDB but the
        # fetch is large, and chunking keeps memory flat on a 31k-row table.
        rows: list[tuple] = []
        CHUNK = 500
        for i in range(0, len(ids), CHUNK):
            part = ids[i : i + CHUNK]
            rows.extend(
                db.execute(
                    text(
                        f"SELECT {', '.join(f'`{c}`' for c in cols)} "
                        f"FROM {TABLE} WHERE id IN :ids ORDER BY id"
                    ),
                    {"ids": tuple(part)},
                ).fetchall()
            )
    finally:
        db.close()

    collist = ", ".join(f"`{c}`" for c in cols)
    with sql_path.open("w", encoding="utf-8") as fh:
        fh.write(f"-- {TABLE} backup\n")
        fh.write(f"-- taken    : {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        fh.write(f"-- reason   : {reason}\n")
        fh.write(f"-- rows     : {len(rows)}\n")
        fh.write("--\n")
        fh.write("-- Restore with:  mysql <db> < this_file.sql\n")
        fh.write("-- Rows are written as INSERT IGNORE, so restoring over a table\n")
        fh.write("-- that still holds them is a no-op rather than an error.\n\n")
        for row in rows:
            values = ", ".join(_sql_literal(v) for v in row)
            fh.write(f"INSERT IGNORE INTO `{TABLE}` ({collist}) VALUES ({values});\n")

    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(cols)
        writer.writerows(rows)

    print(f"backed up {len(rows)} row(s)")
    print(f"  reason : {reason}")
    print(f"  sql    : {sql_path}")
    print(f"  csv    : {csv_path}")
    print(f"  size   : {sql_path.stat().st_size / 1024:.1f} KB")
    return sql_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--duplicates", action="store_true",
                       help="the strict duplicate rows, keeping the lowest id")
    group.add_argument("--categories", action="store_true",
                       help="rows whose content_category is about to be merged")
    group.add_argument("--all-gamma", action="store_true",
                       help="every row referencing gamma")
    group.add_argument("--ids", help="comma-separated ids")
    args = parser.parse_args()

    mode = ("duplicates" if args.duplicates else
            "categories" if args.categories else
            "all-gamma" if args.all_gamma else "ids")
    explicit = [int(x) for x in args.ids.split(",") if x.strip()] if args.ids else []

    db = _session()
    try:
        ids, reason = select_ids(db, mode, explicit)
    finally:
        db.close()

    dump(ids, reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())