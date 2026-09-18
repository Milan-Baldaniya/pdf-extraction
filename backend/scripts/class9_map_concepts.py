"""Attach orphan Class 9 concepts to their curriculum topic.

    python -m scripts.class9_map_concepts --file scripts/class9_maps/maths_3976.json --dry
    python -m scripts.class9_map_concepts --file scripts/class9_maps/maths_3976.json --apply
    python -m scripts.class9_map_concepts --revert

Every pair in the map file is authored by hand against the printed curriculum,
not matched by string similarity. An earlier attempt at fuzzy concept matching
on this estate produced 512 wrong mappings that had to be cleared, so the only
automation here is validation, never inference.

Refuses to write unless, for every pair:
  - the concept exists and is currently unmapped (never silently re-points a
    concept that already has a topic),
  - the topic exists,
  - and BOTH sit in the same chapter. That last check is what makes a mistyped
    id impossible to apply: a topic from another chapter is rejected, not saved.
Nothing is written if any pair fails, so a map file is all-or-nothing.
"""
from __future__ import annotations
import argparse, io, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text  # noqa: E402
from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REASON = "map_concept_topic"
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


def validate(db, pairs: dict) -> tuple[list, list]:
    """Return (ok, problems). ok entries are (concept_id, topic_id, name)."""
    ok, problems = [], []
    for cid_s, spec in pairs.items():
        cid, tid = int(cid_s), int(spec["topic"])
        c = db.execute(text(
            "SELECT id, chapter_id, topic_id, name FROM lms_concept WHERE id=:i"),
            {"i": cid}).fetchone()
        if not c:
            problems.append(f"concept {cid} does not exist"); continue
        t = db.execute(text(
            "SELECT id, chapter_id, name FROM topic_master WHERE id=:i"),
            {"i": tid}).fetchone()
        if not t:
            problems.append(f"topic {tid} does not exist (concept {cid})"); continue
        if c[2] not in (None, 0):
            problems.append(f"concept {cid} '{c[3]}' already maps to topic {c[2]}"); continue
        if c[1] != t[1]:
            problems.append(
                f"chapter mismatch: concept {cid} is in chapter {c[1]} "
                f"but topic {tid} is in chapter {t[1]}"); continue
        ok.append((cid, tid, c[3], t[2]))
    return ok, problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()
    db = _session()
    try:
        if a.revert:
            rows = db.execute(text(
                "SELECT id,row_id,prev_value FROM class9_curriculum_log "
                " WHERE reason=:r AND reverted_at IS NULL"), {"r": REASON}).fetchall()
            for log_id, rid, prev in rows:
                db.execute(text("UPDATE lms_concept SET topic_id=:v WHERE id=:i"),
                           {"v": None if prev in (None, "NULL") else int(prev), "i": int(rid)})
                db.execute(text("UPDATE class9_curriculum_log SET reverted_at=NOW() WHERE id=:i"),
                           {"i": int(log_id)})
            db.commit()
            print(f"reverted {len(rows)} mapping(s)")
            return 0

        if not a.file:
            ap.error("--file is required unless --revert")
        spec = json.load(io.open(a.file, encoding="utf-8"))
        pairs = spec["map"]
        print(f"{spec.get('subject')} (subject_id={spec.get('subject_id')}): "
              f"{len(pairs)} authored mapping(s)")

        ok, problems = validate(db, pairs)
        if problems:
            print(f"\n  {len(problems)} PROBLEM(S) - nothing written:")
            for p in problems[:20]:
                print(f"    - {p}")
            return 1
        print(f"  all {len(ok)} pairs validated (concept and topic share a chapter)")

        if a.dry or not a.apply:
            for cid, tid, cname, tname in ok[:8]:
                print(f"    {str(cname)[:34]:<36} -> {tname}")
            print(f"  DRY RUN - nothing written")
            return 0

        db.execute(text(LOG_DDL)); db.commit()
        for cid, tid, _, _ in ok:
            db.execute(text(
                "INSERT INTO class9_curriculum_log "
                "(table_name,row_id,column_name,prev_value,new_value,reason) "
                "VALUES ('lms_concept',:r,'topic_id','NULL',:n,:why)"),
                {"r": cid, "n": str(tid), "why": REASON})
            db.execute(text("UPDATE lms_concept SET topic_id=:t WHERE id=:i"),
                       {"t": tid, "i": cid})
        db.commit()
        print(f"  mapped {len(ok)} concept(s)")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
