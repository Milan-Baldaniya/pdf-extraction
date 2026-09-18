"""Create curriculum topics for Class 9 chapters and file their concepts under them.

    python -m scripts.class9_build_topics --file scripts/class9_maps/social_science_4469.json --dry
    python -m scripts.class9_build_topics --file scripts/class9_maps/social_science_4469.json --apply
    python -m scripts.class9_build_topics --revert

For chapters that have no topic_master rows at all, so their concepts can only
render as one flat list. The sections are authored against the printed
curriculum; the script itself infers nothing.

Validation before any write, all-or-nothing:
  - every concept id exists and already sits in the chapter it is listed under,
    so a concept cannot be dragged into another chapter's topic by a typo,
  - no concept appears twice across the whole file,
  - a chapter that already has topics is refused unless --allow-existing, which
    stops a second run from silently duplicating a chapter's sections.

Reversible: created topic ids and concept updates are logged, and --revert
deletes the topics it created and restores every concept's previous topic_id.
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

REASON_TOPIC = "create_topic"
REASON_MAP = "map_concept_topic_pack"

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


def _session():
    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    return SessionLocal()


def validate(db, spec, allow_existing: bool):
    """Every reason this file must not be applied. Empty list means safe."""
    problems: list[str] = []
    seen: dict[int, int] = {}
    for chapter_id, topics in spec["chapters"].items():
        cid = int(chapter_id)
        ch = db.execute(
            text("SELECT id, subject_id, standard_id FROM chapter_master WHERE id=:i"),
            {"i": cid},
        ).fetchone()
        if not ch:
            problems.append(f"chapter {cid} does not exist")
            continue
        if ch[1] != spec["subject_id"] or ch[2] != spec["standard_id"]:
            problems.append(
                f"chapter {cid} belongs to subject {ch[1]}/standard {ch[2]}, "
                f"not {spec['subject_id']}/{spec['standard_id']}"
            )
            continue
        existing = db.execute(
            text("SELECT COUNT(*) FROM topic_master WHERE chapter_id=:i"), {"i": cid}
        ).scalar()
        if existing and not allow_existing:
            problems.append(f"chapter {cid} already has {existing} topic(s); refusing")
            continue
        for topic in topics:
            for concept_id in topic["concepts"]:
                if concept_id in seen:
                    problems.append(
                        f"concept {concept_id} listed twice "
                        f"(chapters {seen[concept_id]} and {cid})"
                    )
                    continue
                seen[concept_id] = cid
                row = db.execute(
                    text("SELECT id, chapter_id FROM lms_concept WHERE id=:i"),
                    {"i": concept_id},
                ).fetchone()
                if not row:
                    problems.append(f"concept {concept_id} does not exist")
                elif row[1] != cid:
                    problems.append(
                        f"concept {concept_id} is in chapter {row[1]}, "
                        f"but listed under chapter {cid}"
                    )
    return problems, seen


def revert(db) -> None:
    maps = db.execute(
        text(
            "SELECT id, row_id, prev_value FROM class9_curriculum_log "
            " WHERE reason = :r AND reverted_at IS NULL"
        ),
        {"r": REASON_MAP},
    ).fetchall()
    for log_id, rid, prev in maps:
        db.execute(
            text("UPDATE lms_concept SET topic_id = :v WHERE id = :i"),
            {"v": None if prev in (None, "NULL") else int(prev), "i": int(rid)},
        )
        db.execute(
            text("UPDATE class9_curriculum_log SET reverted_at = NOW() WHERE id = :i"),
            {"i": int(log_id)},
        )
    # Topics are removed only after their concepts have been detached, so a
    # failure part way through never leaves a concept pointing at a topic that
    # no longer exists.
    topics = db.execute(
        text(
            "SELECT id, row_id FROM class9_curriculum_log "
            " WHERE reason = :r AND reverted_at IS NULL"
        ),
        {"r": REASON_TOPIC},
    ).fetchall()
    for log_id, rid in topics:
        db.execute(text("DELETE FROM topic_master WHERE id = :i"), {"i": int(rid)})
        db.execute(
            text("UPDATE class9_curriculum_log SET reverted_at = NOW() WHERE id = :i"),
            {"i": int(log_id)},
        )
    db.commit()
    print(f"reverted {len(maps)} mapping(s), removed {len(topics)} created topic(s)")


def apply(db, spec) -> None:
    db.execute(text(LOG_DDL))
    db.commit()
    made = placed = 0
    for chapter_id, topics in spec["chapters"].items():
        cid = int(chapter_id)
        # Continue the chapter's existing numbering rather than restarting at 1,
        # so --allow-existing appends instead of colliding.
        base = db.execute(
            text(
                "SELECT COALESCE(MAX(topic_sort_order), 0) FROM topic_master "
                " WHERE chapter_id = :i"
            ),
            {"i": cid},
        ).scalar() or 0
        for order, topic in enumerate(topics, start=1):
            db.execute(
                text(
                    "INSERT INTO topic_master "
                    "(sub_institute_id, chapter_id, main_topic_id, name, "
                    " estimated_minutes, topic_show_hide, topic_sort_order, syear, "
                    " evidence_verified, created_at, updated_at) "
                    "VALUES (:si, :ch, 0, :nm, :mins, 1, :so, :sy, 0, NOW(), NOW())"
                ),
                {
                    "si": spec.get("sub_institute_id", 1),
                    "ch": cid,
                    "nm": topic["name"],
                    "mins": topic.get("minutes"),
                    "so": base + order,
                    "sy": spec.get("syear", 2026),
                },
            )
            topic_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()
            made += 1
            db.execute(
                text(
                    "INSERT INTO class9_curriculum_log "
                    "(table_name, row_id, column_name, prev_value, new_value, reason) "
                    "VALUES ('topic_master', :r, 'id', NULL, :n, :why)"
                ),
                {"r": topic_id, "n": str(topic_id), "why": REASON_TOPIC},
            )
            for concept_id in topic["concepts"]:
                prev = db.execute(
                    text("SELECT topic_id FROM lms_concept WHERE id = :i"),
                    {"i": concept_id},
                ).scalar()
                db.execute(
                    text(
                        "INSERT INTO class9_curriculum_log "
                        "(table_name, row_id, column_name, prev_value, new_value, reason) "
                        "VALUES ('lms_concept', :r, 'topic_id', :p, :n, :why)"
                    ),
                    {
                        "r": concept_id,
                        "p": "NULL" if prev is None else str(prev),
                        "n": str(topic_id),
                        "why": REASON_MAP,
                    },
                )
                db.execute(
                    text("UPDATE lms_concept SET topic_id = :t WHERE id = :i"),
                    {"t": topic_id, "i": concept_id},
                )
                placed += 1
        db.commit()
    print(f"  created {made} topic(s), placed {placed} concept(s)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file")
    parser.add_argument("--dry", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--revert", action="store_true")
    parser.add_argument("--allow-existing", action="store_true")
    args = parser.parse_args()

    db = _session()
    try:
        if args.revert:
            revert(db)
            return 0

        if not args.file:
            parser.error("--file is required unless --revert")
        spec = json.load(io.open(args.file, encoding="utf-8"))
        n_topics = sum(len(v) for v in spec["chapters"].values())
        n_concepts = sum(
            len(t["concepts"]) for v in spec["chapters"].values() for t in v
        )
        print(
            f"{spec['subject']}: {len(spec['chapters'])} chapter(s), "
            f"{n_topics} topic(s) to create, {n_concepts} concept(s) to place"
        )

        problems, _ = validate(db, spec, args.allow_existing)
        if problems:
            print(f"\n  {len(problems)} PROBLEM(S) - nothing written:")
            for p in problems[:20]:
                print(f"    - {p}")
            return 1
        print("  validated: every concept exists and already sits in its listed chapter")

        if args.dry or not args.apply:
            print("  DRY RUN - nothing written")
            return 0

        apply(db, spec)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
