"""Find questions that asked for a figure and did not get one.

    python -m scripts.check_figure_resolution --extraction 592
    python -m scripts.check_figure_resolution --standard 42 --subject 3975
    python -m scripts.check_figure_resolution --all

This is the one failure in the load path that leaves no trace at all.
`write_question_bank` resolves each image name against the extraction's
`asset_manifest` with `assets_by_name.get(name)` and then filters out the
misses -- no log, no counter, no validation failure. And V-07 only checks that
`images` is non-empty, never that it resolved. So an item naming a file that is
not in the manifest publishes cleanly with `status = 1`, records
`figure_required = 1, figure_resolved = 0`, and writes no asset row. The
question reaches a learner with its figure missing and nothing anywhere says so.

Run it after every load. A clean run prints one line.

Also reports the inverse -- `figure_resolved = 1` where the manifest entry has
no `stored_url` on a reachable host -- because a figure pointing at the
extraction box is as unusable to a learner as a missing one.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# The forms a stored_url takes when it points at this machine rather than a CDN.
UNREACHABLE = re.compile(r"^\s*$|127\.0\.0\.1|localhost|^/|^file:", re.IGNORECASE)

_WHERE = {
    "extraction": "x.extraction_id = :v",
    "standard": "q.standard_id = :v",
    "all": "1 = 1",
}


def _manifest_names(db, extraction_id: int) -> set[str]:
    raw = db.execute(
        text("SELECT asset_manifest FROM document_extractions WHERE id = :i"),
        {"i": extraction_id},
    ).scalar()
    if not raw:
        return set()
    try:
        manifest = json.loads(raw)
    except (TypeError, ValueError):
        return set()
    if not isinstance(manifest, list):
        return set()
    return {str(e.get("file_name")) for e in manifest if isinstance(e, dict) and e.get("file_name")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--extraction", type=int)
    ap.add_argument("--standard", type=int)
    ap.add_argument("--subject", type=int)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=25, help="rows to list per finding")
    a = ap.parse_args()

    if a.extraction:
        where, value = _WHERE["extraction"], a.extraction
    elif a.standard:
        where, value = _WHERE["standard"], a.standard
    elif a.all:
        where, value = _WHERE["all"], None
    else:
        ap.error("give --extraction, --standard or --all")

    subject = " AND q.subject_id = :su" if a.subject else ""
    params = {"v": value, "su": a.subject}

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        total = db.execute(
            text(
                "SELECT COUNT(*) FROM lms_question_extraction x "
                "  JOIN lms_question_master q ON q.id = x.question_id "
                f" WHERE {where}{subject}"
            ),
            params,
        ).scalar()

        missing = db.execute(
            text(
                "SELECT x.extraction_id, x.item_number, q.id, q.chapter_id, "
                "       LEFT(q.question_title, 70) "
                "  FROM lms_question_extraction x "
                "  JOIN lms_question_master q ON q.id = x.question_id "
                f" WHERE {where}{subject} "
                "   AND x.figure_required = 1 AND x.figure_resolved = 0 "
                " ORDER BY x.extraction_id, x.item_ordinal"
            ),
            params,
        ).fetchall()

        unreachable = db.execute(
            text(
                "SELECT s.extraction_id, s.item_number, q.id, asset.stored_url "
                "  FROM lms_question_extraction s "
                "  JOIN lms_question_master q ON q.id = s.question_id "
                "  JOIN lms_question_asset asset ON asset.question_id = q.id "
                f" WHERE {where.replace('x.', 's.')}{subject}"
            ),
            params,
        ).fetchall()
        unreachable = [r for r in unreachable if UNREACHABLE.search(r[3] or "")]

        print(f"questions in scope: {total}")
        print(f"  figure_required = 1 AND figure_resolved = 0 : {len(missing)}")
        print(f"  asset stored_url not on a reachable host     : {len(unreachable)}")

        if missing:
            print("\nFIGURE ASKED FOR AND NOT ATTACHED")
            print("  The item named an image the extraction's asset_manifest does")
            print("  not contain, so the writer dropped it silently.\n")
            for eid, number, qid, chapter, title in missing[: a.limit]:
                names = _manifest_names(db, eid)
                print(f"   eid {eid} item {number} (q{qid}, chapter {chapter})")
                print(f"     {title}")
                print(f"     manifest holds {len(names)} file name(s)")
            if len(missing) > a.limit:
                print(f"   ... and {len(missing) - a.limit} more")

        if unreachable:
            print("\nFIGURE ATTACHED BUT NOT PUBLISHED")
            for eid, number, qid, url in unreachable[: a.limit]:
                print(f"   eid {eid} item {number} (q{qid}): {url}")
            if len(unreachable) > a.limit:
                print(f"   ... and {len(unreachable) - a.limit} more")
            print("\n   Run publish_question_figures --apply.")

        if not missing and not unreachable:
            print("\nevery required figure resolved and is on a reachable host.")
        return 1 if (missing or unreachable) else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
