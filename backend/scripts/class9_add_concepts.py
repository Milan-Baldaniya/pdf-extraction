"""Author concepts for curriculum sections that have none.

    python -m scripts.class9_add_concepts --file scripts/class9_maps/maths_gap_concepts.json --dry
    python -m scripts.class9_add_concepts --file scripts/class9_maps/maths_gap_concepts.json --apply
    python -m scripts.class9_add_concepts --revert

A topic with no concept renders as "0 concepts" in the chapter tree, which reads
as a broken screen rather than as a gap in the extraction. These rows are written
by hand against the printed curriculum.

They are stamped review_status='authored', not 'legacy', so the authored set
stays distinguishable from the extracted set. Validation refuses to write unless
the topic exists, sits in the stated chapter, and has no visible concept already:
adding a second concept to a section that is already populated would be a silent
duplicate rather than a gap being filled.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REASON = "author_concept"
VISIBLE = "(concept_show_hide IS NULL OR concept_show_hide <> 0)"


def _session():
    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    return SessionLocal()


def validate(db, spec) -> list[str]:
    problems: list[str] = []
    for c in spec["concepts"]:
        topic = db.execute(
            text("SELECT id, chapter_id, name FROM topic_master WHERE id = :i"),
            {"i": c["topic_id"]},
        ).fetchone()
        if not topic:
            problems.append(f"topic {c['topic_id']} does not exist")
            continue
        if topic[1] != c["chapter_id"]:
            problems.append(
                f"topic {c['topic_id']} is in chapter {topic[1]}, "
                f"not {c['chapter_id']} as stated"
            )
            continue
        existing = db.execute(
            text(f"SELECT COUNT(*) FROM lms_concept WHERE topic_id = :t AND {VISIBLE}"),
            {"t": c["topic_id"]},
        ).scalar()
        if existing:
            problems.append(
                f"topic {c['topic_id']} '{topic[2]}' already has {existing} "
                f"concept(s); this is for empty sections only"
            )
        clash = db.execute(
            text("SELECT id FROM lms_concept WHERE chapter_id = :ch AND name = :n"),
            {"ch": c["chapter_id"], "n": c["name"]},
        ).fetchone()
        if clash:
            problems.append(
                f"chapter {c['chapter_id']} already has a concept named "
                f"'{c['name']}' (id {clash[0]})"
            )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file")
    parser.add_argument("--dry", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--revert", action="store_true")
    args = parser.parse_args()

    db = _session()
    try:
        if args.revert:
            rows = db.execute(
                text(
                    "SELECT id, row_id FROM class9_curriculum_log "
                    " WHERE reason = :r AND reverted_at IS NULL"
                ),
                {"r": REASON},
            ).fetchall()
            for log_id, rid in rows:
                db.execute(text("DELETE FROM lms_concept WHERE id = :i"), {"i": int(rid)})
                db.execute(
                    text("UPDATE class9_curriculum_log SET reverted_at = NOW() WHERE id = :i"),
                    {"i": int(log_id)},
                )
            db.commit()
            print(f"removed {len(rows)} authored concept(s)")
            return 0

        if not args.file:
            parser.error("--file is required unless --revert")
        spec = json.load(io.open(args.file, encoding="utf-8"))
        print(f"{spec['subject']}: {len(spec['concepts'])} concept(s) to author")

        problems = validate(db, spec)
        if problems:
            print(f"\n  {len(problems)} PROBLEM(S) - nothing written:")
            for p in problems[:20]:
                print(f"    - {p}")
            return 1
        print("  validated: every target section exists, matches its chapter, and is empty")

        if args.dry or not args.apply:
            for c in spec["concepts"]:
                print(f"    + {c['name']}")
            print("  DRY RUN - nothing written")
            return 0

        for c in spec["concepts"]:
            db.execute(
                text(
                    "INSERT INTO lms_concept "
                    "(name, description, subject_id, standard_id, chapter_id, topic_id, "
                    " sub_institute_id, mastery_threshold, estimated_mastery_minutes, "
                    " syear, review_status, concept_show_hide, evidence_verified, "
                    " created_at, updated_at) "
                    "VALUES (:nm, :ds, :su, :st, :ch, :tp, :si, 85.0, :mins, :sy, "
                    " 'authored', 1, 0, NOW(), NOW())"
                ),
                {
                    "nm": c["name"],
                    "ds": c["description"],
                    "su": spec["subject_id"],
                    "st": spec["standard_id"],
                    "ch": c["chapter_id"],
                    "tp": c["topic_id"],
                    "si": spec.get("sub_institute_id", 1),
                    "mins": c.get("minutes"),
                    "sy": spec.get("syear", 2026),
                },
            )
            new_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()
            db.execute(
                text(
                    "INSERT INTO class9_curriculum_log "
                    "(table_name, row_id, column_name, prev_value, new_value, reason) "
                    "VALUES ('lms_concept', :r, 'id', NULL, :n, :why)"
                ),
                {"r": new_id, "n": str(new_id), "why": REASON},
            )
        db.commit()
        print(f"  authored {len(spec['concepts'])} concept(s)")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
