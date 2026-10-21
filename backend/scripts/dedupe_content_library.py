"""Hide duplicate content_master rows and merge fragmented category names.

    python -m scripts.dedupe_content_library --dry
    python -m scripts.dedupe_content_library --apply
    python -m scripts.dedupe_content_library --apply --categories
    python -m scripts.dedupe_content_library --revert

Hide, not delete. 21 tables reference content_master by id, so a DELETE would
orphan them; `show_hide = 0` makes a row vanish from both libraries while every
reference stays valid, and it reverses in one statement. The flag is already
honoured by the write paths, and this change makes the read path honour it too.

The keeper is the lowest id in each group, because the duplicate inserts came
from one import re-running: the first row is the one any existing reference is
most likely to point at.

Every write is recorded in content_master_dedupe_log with the previous value,
so --revert restores exactly what was there rather than assuming it was 1. That
matters here: 5,205 rows have show_hide NULL, and restoring those as 1 would be
a silent data change.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402
from scripts.backup_content_master import CATEGORY_MERGES, DUPE_KEY  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HIDDEN = 0

LOG_DDL = """
CREATE TABLE IF NOT EXISTS content_master_dedupe_log (
    id                  BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    content_id          BIGINT       NOT NULL,
    keeper_id           BIGINT       NULL,
    action              VARCHAR(32)  NOT NULL,
    prev_show_hide      VARCHAR(8)   NULL,
    prev_category       VARCHAR(191) NULL,
    new_category        VARCHAR(191) NULL,
    reverted_at         DATETIME     NULL,
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_dl_content (content_id),
    KEY idx_dl_action  (action, reverted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

# `prev_show_hide` is VARCHAR, not INT, so the three states the column really
# has - NULL, 0, 1 - survive the round trip. An INT column cannot tell "was
# NULL" from "was not logged".
_NULL_SENTINEL = "NULL"


def _session():
    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    return SessionLocal()


def duplicate_groups(db) -> list[dict]:
    """Each group of strictly identical rows: the keeper and the rows to hide."""
    rows = db.execute(
        text(
            f"""
            SELECT cm.id, k.keeper, cm.show_hide, cm.content_category, cm.title
              FROM content_master cm
              JOIN (SELECT MIN(id) keeper, {DUPE_KEY}
                      FROM content_master
                     GROUP BY {DUPE_KEY} HAVING COUNT(*) > 1) k
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
    return [
        {
            "id": int(r[0]),
            "keeper": int(r[1]),
            "show_hide": r[2],
            "category": r[3],
            "title": r[4],
        }
        for r in rows
    ]


def _report(victims: list[dict]) -> None:
    by_cat: dict[str, int] = {}
    already = 0
    for v in victims:
        by_cat[v["category"] or "(NULL)"] = by_cat.get(v["category"] or "(NULL)", 0) + 1
        if v["show_hide"] == HIDDEN:
            already += 1
    print(f"  {len(victims)} redundant row(s) across "
          f"{len({v['keeper'] for v in victims})} group(s)")
    if already:
        print(f"  {already} already hidden - they will be skipped")
    print("  by category:")
    for cat, n in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        print(f"    {cat:<34}{n:>6}")


def apply_dedupe(db, victims: list[dict], dry: bool) -> int:
    todo = [v for v in victims if v["show_hide"] != HIDDEN]
    if not todo:
        print("  nothing to hide")
        return 0
    if dry:
        print(f"  DRY RUN - would hide {len(todo)} row(s)")
        return 0

    db.execute(text(LOG_DDL))
    db.commit()

    for v in todo:
        db.execute(
            text(
                "INSERT INTO content_master_dedupe_log "
                "(content_id, keeper_id, action, prev_show_hide) "
                "VALUES (:cid, :keep, 'hide_duplicate', :prev)"
            ),
            {
                "cid": v["id"],
                "keep": v["keeper"],
                "prev": _NULL_SENTINEL if v["show_hide"] is None else str(v["show_hide"]),
            },
        )

    ids = [v["id"] for v in todo]
    CHUNK = 500
    for i in range(0, len(ids), CHUNK):
        db.execute(
            text("UPDATE content_master SET show_hide = :h WHERE id IN :ids"),
            {"h": HIDDEN, "ids": tuple(ids[i : i + CHUNK])},
        )
    db.commit()
    print(f"  hid {len(todo)} row(s)")
    return len(todo)


def apply_categories(db, dry: bool) -> int:
    total = 0
    for old, new in CATEGORY_MERGES.items():
        rows = db.execute(
            text("SELECT id FROM content_master WHERE content_category = :c"),
            {"c": old},
        ).fetchall()
        if not rows:
            print(f"  {old!r}: nothing to merge")
            continue
        print(f"  {old!r} -> {new!r}: {len(rows)} row(s)"
              + ("  [DRY RUN]" if dry else ""))
        if dry:
            continue

        db.execute(text(LOG_DDL))
        db.commit()
        for (rid,) in rows:
            db.execute(
                text(
                    "INSERT INTO content_master_dedupe_log "
                    "(content_id, action, prev_category, new_category) "
                    "VALUES (:cid, 'merge_category', :old, :new)"
                ),
                {"cid": int(rid), "old": old, "new": new},
            )
        db.execute(
            text("UPDATE content_master SET content_category = :new "
                 "WHERE content_category = :old"),
            {"new": new, "old": old},
        )
        db.commit()
        total += len(rows)
    return total


def revert(db) -> None:
    """Undo every write this script made that has not already been reverted."""
    hides = db.execute(
        text(
            "SELECT id, content_id, prev_show_hide FROM content_master_dedupe_log "
            " WHERE action = 'hide_duplicate' AND reverted_at IS NULL"
        )
    ).fetchall()
    merges = db.execute(
        text(
            "SELECT id, content_id, prev_category FROM content_master_dedupe_log "
            " WHERE action = 'merge_category' AND reverted_at IS NULL"
        )
    ).fetchall()

    for log_id, cid, prev in hides:
        # prev is restored verbatim - NULL stays NULL, 1 stays 1.
        if prev == _NULL_SENTINEL:
            db.execute(
                text("UPDATE content_master SET show_hide = NULL WHERE id = :i"),
                {"i": int(cid)},
            )
        else:
            db.execute(
                text("UPDATE content_master SET show_hide = :v WHERE id = :i"),
                {"v": int(prev), "i": int(cid)},
            )
        db.execute(
            text("UPDATE content_master_dedupe_log SET reverted_at = NOW() "
                 "WHERE id = :i"),
            {"i": int(log_id)},
        )

    for log_id, cid, prev in merges:
        db.execute(
            text("UPDATE content_master SET content_category = :c WHERE id = :i"),
            {"c": prev, "i": int(cid)},
        )
        db.execute(
            text("UPDATE content_master_dedupe_log SET reverted_at = NOW() "
                 "WHERE id = :i"),
            {"i": int(log_id)},
        )

    db.commit()
    print(f"  reverted {len(hides)} hide(s) and {len(merges)} category merge(s)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry", action="store_true", help="report, write nothing")
    parser.add_argument("--apply", action="store_true", help="perform the writes")
    parser.add_argument("--categories", action="store_true",
                        help="also merge the fragmented category names")
    parser.add_argument("--revert", action="store_true",
                        help="undo everything recorded in the log table")
    args = parser.parse_args()

    if not (args.dry or args.apply or args.revert):
        parser.error("choose --dry, --apply or --revert")

    db = _session()
    try:
        before = db.execute(text("SELECT COUNT(*) FROM content_master")).scalar()
        hidden_before = db.execute(
            text("SELECT COUNT(*) FROM content_master WHERE show_hide = 0")
        ).scalar()
        print(f"content_master: {before} row(s), {hidden_before} already hidden\n")

        if args.revert:
            print("REVERT")
            revert(db)
        else:
            print("DUPLICATES")
            victims = duplicate_groups(db)
            _report(victims)
            apply_dedupe(db, victims, dry=args.dry)

            if args.categories:
                print("\nCATEGORY MERGES")
                apply_categories(db, dry=args.dry)

        after = db.execute(text("SELECT COUNT(*) FROM content_master")).scalar()
        hidden_after = db.execute(
            text("SELECT COUNT(*) FROM content_master WHERE show_hide = 0")
        ).scalar()
        print(f"\ncontent_master: {after} row(s), {hidden_after} hidden")
        if after != before:
            print("  !! ROW COUNT CHANGED - this script must never delete a row")
            return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())