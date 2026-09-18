"""Dump Class 9 CBSE curriculum rows to a local file OUTSIDE every git repo.

    python -m scripts.backup_class9

Same rule as backup_content_master: the destination is a sibling of the
repositories, never a child, so a production dump cannot be committed by
accident. Full rows as INSERT IGNORE plus a CSV per table.
"""
from __future__ import annotations
import csv, io, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text  # noqa: E402
from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKUP_DIR = Path(r"C:\Users\MILAN\content-library-backups")
STD = 42
TEST_SUBJECTS = (5574, 5575, 5576)


def _assert_outside_git(path: Path) -> None:
    for parent in [path, *path.parents]:
        if (parent / ".git").exists():
            raise SystemExit(f"REFUSING to write a backup inside a git repo: {parent}")


def _lit(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    e = (str(v).replace("\\", "\\\\").replace("'", "\'")
         .replace("\n", "\n").replace("\r", "\r"))
    return f"'{e}'"


# Every row this session may touch: the whole Class 9 curriculum tree.
QUERIES = {
    "chapter_master": f"SELECT * FROM chapter_master WHERE standard_id={STD}",
    "topic_master": (f"SELECT * FROM topic_master WHERE chapter_id IN "
                     f"(SELECT id FROM chapter_master WHERE standard_id={STD})"),
    "lms_concept": f"SELECT * FROM lms_concept WHERE standard_id={STD}",
}


def main() -> int:
    _assert_outside_git(BACKUP_DIR)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sql_path = BACKUP_DIR / f"class9_cbse_{stamp}.sql"
    total = 0
    try:
        with io.open(sql_path, "w", encoding="utf-8") as fh:
            fh.write(f"-- Class 9 CBSE (standard_id={STD}) curriculum backup\n")
            fh.write(f"-- taken : {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            fh.write("-- restore: mysql <db> < this_file.sql\n\n")
            for table, q in QUERIES.items():
                cols = [r[0] for r in db.execute(text(f"SHOW COLUMNS FROM {table}")).fetchall()]
                rows = db.execute(text(q)).fetchall()
                total += len(rows)
                collist = ", ".join(f"`{c}`" for c in cols)
                fh.write(f"-- {table}: {len(rows)} rows\n")
                for row in rows:
                    fh.write(f"INSERT IGNORE INTO `{table}` ({collist}) VALUES "
                             f"({', '.join(_lit(v) for v in row)});\n")
                fh.write("\n")
                with io.open(BACKUP_DIR / f"class9_{table}_{stamp}.csv", "w",
                             encoding="utf-8", newline="") as cf:
                    w = csv.writer(cf); w.writerow(cols); w.writerows(rows)
                print(f"   {table:<18}{len(rows):>6} rows")
    finally:
        db.close()
    print(f"\nbacked up {total} rows")
    print(f"  sql : {sql_path}")
    print(f"  size: {sql_path.stat().st_size/1024:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
