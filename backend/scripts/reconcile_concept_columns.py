"""Make the two concept columns agree, and clear links that cannot be right.

    python -m scripts.reconcile_concept_columns            # report only
    python -m scripts.reconcile_concept_columns --apply

A question's concept lives in two places: `lms_question_master.concept_id` and
`lms_question_extraction.concept_id`. Different readers use different ones, so a
link present on only one side reads as absent to half the estate, and a link
that DIFFERS between them reads as two different answers.

PART 1 -- CLEAR THE IMPOSSIBLE LINKS. 70 questions carry a concept that belongs
to a **different chapter**. That is not a debatable pairing, it is invalid by
construction: `lms_concept` rows are per chapter, so a concept of chapter X
cannot be what a question of chapter Y tests. 51 of the 70 are one defect --
eleven Class 8 Science chapters all pointing into ch25838's concept list -- and
19 are Class 9 English pointing at each other's.

They are cleared rather than repointed. Repointing would mean guessing which of
the right chapter's concepts was meant, and the guess would be invisible. A
cleared link shows up as unlinked, which is what it actually is, and the reading
pass then fills it. **This lowers the linked count by 70, correctly.**

PART 2 -- THE SIDECAR FOLLOWS THE MASTER. The two columns disagree on 3,977
rows. `lms_question_master` is authoritative: it is the column the reading pass
writes, the one the LMS serves, and the one every tool in this estate reads
first. The sidecar's values are leftover output from the offline lexical matcher.

That choice is only lossless because the sidecar never holds a link the master
lacks -- 0 rows have `master = 0 AND sidecar > 0`. **The script re-checks that
before writing** and refuses if it has stopped being true, because then the
sidecar would hold information this would destroy.

Nothing is deleted. Both parts are UPDATEs on the two concept columns only.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

SCOPE = "c.standard_id BETWEEN 39 AND 43"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        # ---- the premise of part 2, re-checked before anything is written ----
        unique = db.execute(text(f"""
            SELECT COUNT(*) FROM lms_question_master q
              JOIN lms_question_extraction e ON e.question_id = q.id
              JOIN chapter_master c ON c.id = q.chapter_id
             WHERE {SCOPE} AND q.deleted_at IS NULL
               AND COALESCE(q.concept_id,0) = 0
               AND COALESCE(e.concept_id,0) > 0""")).scalar()
        print(f"  premise check: {unique} row(s) where the sidecar holds a link "
              f"the master lacks")
        if unique:
            print("  REFUSED -- the sidecar now carries links of its own, so "
                  "overwriting it would\n  destroy them. Read those rows and "
                  "decide before running this again.")
            return 1

        # ---------------------------------------------------- part 1 ----------
        bad = db.execute(text(f"""
            SELECT q.id, q.chapter_id, q.concept_id, k.chapter_id,
                   COALESCE(s.subject_name,'?'), c.standard_id
              FROM lms_question_master q
              JOIN chapter_master c ON c.id = q.chapter_id
              LEFT JOIN subject s ON s.id = c.subject_id
              JOIN lms_concept k ON k.id = q.concept_id
             WHERE {SCOPE} AND q.deleted_at IS NULL
               AND k.chapter_id <> q.chapter_id
             ORDER BY c.standard_id, q.chapter_id, q.id""")).fetchall()

        print(f"\n  PART 1 -- {len(bad)} link(s) point at another chapter's "
              f"concept\n")
        by_pair: dict[tuple, int] = {}
        for _, ch, _, kch, subj, std in bad:
            by_pair[(std, subj, ch, kch)] = by_pair.get((std, subj, ch, kch), 0) + 1
        for (std, subj, ch, kch), n in sorted(by_pair.items(), key=lambda r: -r[1]):
            print(f"   std{std - 33} {str(subj)[:20]:<20} ch{ch} -> concepts of "
                  f"ch{kch}   {n} question(s)")

        # ---------------------------------------------------- part 2 ----------
        dis = db.execute(text(f"""
            SELECT COUNT(*) FROM lms_question_master q
              JOIN lms_question_extraction e ON e.question_id = q.id
              JOIN chapter_master c ON c.id = q.chapter_id
             WHERE {SCOPE} AND q.deleted_at IS NULL
               AND COALESCE(q.concept_id,0) > 0
               AND COALESCE(e.concept_id,0) > 0
               AND q.concept_id <> e.concept_id""")).scalar()
        print(f"\n  PART 2 -- {dis} row(s) where the sidecar contradicts the "
              f"master; the sidecar\n  will be set to the master's value")

        if not a.apply:
            print("\n  report only -- re-run with --apply")
            return 0

        ids = tuple(int(r[0]) for r in bad)
        if ids:
            db.execute(text(
                "UPDATE lms_question_master SET concept_id = NULL, concept = NULL "
                " WHERE id IN :ids"), {"ids": ids})
            db.execute(text(
                "UPDATE lms_question_extraction SET concept_id = NULL "
                " WHERE question_id IN :ids"), {"ids": ids})

        # Set the sidecar from the master in one statement, scoped the same way.
        db.execute(text(f"""
            UPDATE lms_question_extraction e
              JOIN lms_question_master q ON q.id = e.question_id
              JOIN chapter_master c ON c.id = q.chapter_id
               SET e.concept_id = q.concept_id
             WHERE {SCOPE} AND q.deleted_at IS NULL
               AND COALESCE(q.concept_id,0) > 0
               AND COALESCE(e.concept_id,0) > 0
               AND q.concept_id <> e.concept_id"""))
        db.commit()

        left_bad = db.execute(text(f"""
            SELECT COUNT(*) FROM lms_question_master q
              JOIN chapter_master c ON c.id = q.chapter_id
              JOIN lms_concept k ON k.id = q.concept_id
             WHERE {SCOPE} AND q.deleted_at IS NULL
               AND k.chapter_id <> q.chapter_id""")).scalar()
        left_dis = db.execute(text(f"""
            SELECT COUNT(*) FROM lms_question_master q
              JOIN lms_question_extraction e ON e.question_id = q.id
              JOIN chapter_master c ON c.id = q.chapter_id
             WHERE {SCOPE} AND q.deleted_at IS NULL
               AND COALESCE(q.concept_id,0) > 0
               AND COALESCE(e.concept_id,0) > 0
               AND q.concept_id <> e.concept_id""")).scalar()
        print(f"\n  cleared {len(ids)} impossible link(s); {left_bad} remain")
        print(f"  reconciled the sidecar; {left_dis} contradiction(s) remain")
        print(f"  the {len(ids)} cleared questions now read as unlinked, which "
              f"is what they are --\n  the reading pass will reach them.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
