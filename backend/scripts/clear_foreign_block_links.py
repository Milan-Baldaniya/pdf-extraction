"""Clear concept links on the five foreign question blocks sitting in ch25838.

    python -m scripts.clear_foreign_block_links            # report only
    python -m scripts.clear_foreign_block_links --apply

Chapter 25838 (*Microorganisms: Friend and Foe*) holds 339 questions, but only
75 of them are about microorganisms. The other 264 are five whole chapters that
have no `chapter_master` row of their own, loaded into 25838 because it was the
nearest thing available:

    Synthetic Fibres and Plastics   114059-114108   50
    Metals and Non-Metals           114109-114158   50
    Cell Structure and Functions    114307-114356   50
    Stars and the Solar System      114786-114844   59
    Pollution of Air and Water      114845-114899   55

`create_missing_chapters_and_refile.py` exists to give them real chapters and
move them. It has not been able to run. **40 of the 264 meanwhile carry a
ch25838 microbiology concept**, assigned by the offline lexical matcher, and
those are the reason this script exists rather than waiting for the refile:

    114114  "gas evolved when magnesium reacts with dilute hydrochloric acid"
            -> "Why organisms need nitrogen"
    114310  "cells present in living organism differ in"
            -> "Living on and in other organisms"
    114821  "the brightest non-star visible to the human EYE"
            -> "Too small for the unaided EYE"          <- the matcher's method
    114846  "increase in concentration of which gas is not responsible for
            Global Warming" -> "Bacteria that close the cycle"

`reconcile_concept_columns.py` cannot see these. Its test is whether the concept
belongs to the question's chapter, and here it does -- the question is in 25838
and so is the concept. Only the *content* is foreign. So after the refile these
40 would move to their proper chapters still carrying a microbiology concept
from a chapter they no longer sit in, and would then look correctly mapped
while being wrong. Clearing them now makes them read as unlinked, which is what
they are, and the refile can move a clean row.

The other 224 already carry nothing and are left exactly as they are. Nothing
is deleted and no question moves; this only clears two columns.

THE GUARD. Each block must still hold exactly the count above, every one of
those rows must still sit in chapter 25838, and nothing outside the five ranges
is touched. If a block's shape has changed -- because the refile finally ran,
or because rows were retired -- the run stops and says which block moved.
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

HOST = 25838
BLOCKS = [
    ("Synthetic Fibres and Plastics", 114059, 114108, 50),
    ("Metals and Non-Metals", 114109, 114158, 50),
    ("Cell Structure and Functions", 114307, 114356, 50),
    ("Stars and the Solar System", 114786, 114844, 59),
    ("Pollution of Air and Water", 114845, 114899, 55),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        refused, plan = [], []
        print(f"  five foreign blocks inside chapter {HOST}\n")
        for name, lo, hi, want in BLOCKS:
            n, outside = db.execute(text(
                "SELECT COUNT(*), SUM(chapter_id <> :h) "
                "  FROM lms_question_master "
                " WHERE id BETWEEN :lo AND :hi AND deleted_at IS NULL"),
                {"h": HOST, "lo": lo, "hi": hi}).fetchone()
            if int(n) != want:
                refused.append(f"{name}: {n} live rows, expected {want}")
                continue
            if int(outside or 0):
                refused.append(f"{name}: {outside} row(s) have left chapter "
                               f"{HOST} -- the refile may have run")
                continue
            rows = db.execute(text(
                "SELECT q.id, q.concept_id, k.name, LEFT(q.question_title, 74) "
                "  FROM lms_question_master q "
                "  LEFT JOIN lms_concept k ON k.id = q.concept_id "
                " WHERE q.id BETWEEN :lo AND :hi AND q.deleted_at IS NULL "
                "   AND COALESCE(q.concept_id,0) > 0 ORDER BY q.id"),
                {"lo": lo, "hi": hi}).fetchall()
            print(f"   {name:<32} {want} rows, {len(rows)} carrying a link")
            for qid, cid, cname, stem in rows:
                plan.append(int(qid))
                print(f"      {qid}  {str(cname)[:34]:<34} "
                      f"{' '.join(str(stem).split())[:60]}")

        if refused:
            print(f"\n  REFUSED -- {len(refused)} block(s) are not in the shape "
                  f"this expects:")
            for m in refused:
                print(f"    ! {m}")
            print("  Nothing has been written.")
            return 1

        print(f"\n  {len(plan)} link(s) to clear; the other "
              f"{sum(b[3] for b in BLOCKS) - len(plan)} rows already carry none")
        if not a.apply:
            print("  report only -- re-run with --apply")
            return 0

        db.execute(text(
            "UPDATE lms_question_master SET concept_id = NULL, concept = NULL "
            " WHERE id IN :ids"), {"ids": tuple(plan)})
        db.execute(text(
            "UPDATE lms_question_extraction SET concept_id = NULL "
            " WHERE question_id IN :ids"), {"ids": tuple(plan)})
        db.commit()
        left = db.execute(text(
            "SELECT COUNT(*) FROM lms_question_master "
            " WHERE id IN :ids AND COALESCE(concept_id,0) > 0"),
            {"ids": tuple(plan)}).scalar()
        print(f"\n  cleared {len(plan) - int(left)} link(s); {left} remain")
        print("  These 264 questions now uniformly read as unlinked. They "
              "should not be\n  linked to anything until they have chapters of "
              "their own -- a concept of\n  chapter 25838 is not what any of "
              "them tests.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
