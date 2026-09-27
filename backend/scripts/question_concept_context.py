"""Print a chapter's concepts and its unlinked questions, for a reader to pair.

    python -m scripts.question_concept_context --chapter 25930
    python -m scripts.question_concept_context --chapter 25930 --batch 60 --part 2
    python -m scripts.question_concept_context --coverage --standard 40

**15,006 of 36,487 live questions carry no concept**, and the gap is almost
entirely the language subjects — every Hindi bank and Class 6 English sit at or
near zero. The concepts themselves exist: `lms_concept` holds 227 for Class 6
Hindi, 210 for Class 10 Hindi, 266 for Class 10 Hindi-B, and so on for every
standard and subject. What is missing is the LINK, and that link is what
`concept_id` on the question is.

It matters more than it looks. `concept_id` is what
[[concept_prerequisite]]-style joins hang off, so a question with no concept
cannot contribute a prerequisite check, cannot be routed by PAL's adaptive
ladder, and cannot be used as a grounding exemplar for generation — PAL V4
requires a generated item to sit against a sourced sibling under the SAME
concept.

This prints the chapter's concept list as a **closed set** and then the
questions that still have no concept. Pair them by reading, the same way the
curriculum mapping was done, and hand the result to
`load_question_concepts.py`.

WHY A CLOSED LIST AND NOT A MATCHER. There is an offline tagger, and it is a
lexical keyword matcher. Six separate readings of this estate found its output
wrong in ways that would mislead anyone who trusted it — a displacement
reaction tagged "Rusting of iron", AgCl photolysis tagged "Oxidation", a
soap-micelle item tagged "Tetravalency of Carbon", and in one chapter
"side of a square whose area is 441 cm2" tagged "Where the name comes from"
when the chapter has a concept called "Finding a side from an area". A wrong
concept is worse than none, because it is invisible and it propagates.

Addressing follows `load_question_curriculum`: `verbatim_sha256` where the
question has a sidecar, `qid:<id>` where the LMS itself wrote it and there is
no hash.
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


def coverage(db, standard: int) -> None:
    print(f"  concept coverage, standard {standard}\n")
    print(f"  {'cid':>7} {'subject':<20} {'chapter':<34} {'q':>5} {'linked':>7} "
          f"{'concepts':>9}")
    for r in db.execute(text("""
        SELECT c.id, COALESCE(s.subject_name,'?') subj, c.chapter_name,
               COUNT(DISTINCT q.id) nq,
               COUNT(DISTINCT CASE WHEN COALESCE(q.concept_id, e.concept_id) > 0
                                   THEN q.id END) nk,
               (SELECT COUNT(*) FROM lms_concept k WHERE k.chapter_id = c.id) ncon
          FROM chapter_master c
          LEFT JOIN subject s ON s.id = c.subject_id
          LEFT JOIN lms_question_master q
                 ON q.chapter_id = c.id AND q.deleted_at IS NULL
          LEFT JOIN lms_question_extraction e ON e.question_id = q.id
         WHERE c.standard_id = :s
         GROUP BY c.id HAVING nq > 0
         ORDER BY (nk / nq) ASC, nq DESC"""), {"s": standard}).fetchall():
        gap = int(r[3]) - int(r[4])
        flag = "  <- all unlinked" if r[4] == 0 else (f"  <- {gap} to go" if gap else "")
        print(f"  {r[0]:>7} {str(r[1])[:20]:<20} {str(r[2])[:34]:<34} "
              f"{r[3]:>5} {r[4]:>7} {r[5]:>9}{flag}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chapter", type=int)
    ap.add_argument("--batch", type=int, default=0, help="questions per part (0 = all)")
    ap.add_argument("--part", type=int, default=1)
    ap.add_argument("--coverage", action="store_true")
    ap.add_argument("--standard", type=int, default=43)
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        if a.coverage or not a.chapter:
            coverage(db, a.standard)
            return 0

        head = db.execute(text(
            "SELECT c.chapter_name, c.standard_id, COALESCE(s.subject_name,'?') "
            "  FROM chapter_master c LEFT JOIN subject s ON s.id = c.subject_id "
            " WHERE c.id = :c"), {"c": a.chapter}).fetchone()
        if not head:
            raise SystemExit(f"chapter {a.chapter} not found")

        cons = db.execute(text(
            "SELECT id, name, LEFT(COALESCE(description,''),150) "
            "  FROM lms_concept WHERE chapter_id = :c ORDER BY id"),
            {"c": a.chapter}).fetchall()
        if not cons:
            print(f"  chapter {a.chapter} | {head[0]} | standard {head[1]} {head[2]}")
            print("\n  THIS CHAPTER HAS NO CONCEPTS. There is nothing legal to "
                  "pair with.\n  Report it -- the concept pipeline has not run "
                  "here -- and do not invent one.")
            return 1

        rows = db.execute(text(
            "SELECT q.id, e.verbatim_sha256, q.question_title, "
            "       LEFT(COALESCE(q.hint_text,''),200) "
            "  FROM lms_question_master q "
            "  LEFT JOIN lms_question_extraction e ON e.question_id = q.id "
            " WHERE q.chapter_id = :c AND q.deleted_at IS NULL "
            "   AND COALESCE(q.concept_id, e.concept_id, 0) = 0 "
            " ORDER BY q.id"), {"c": a.chapter}).fetchall()

        total = len(rows)
        if a.batch:
            lo = (a.part - 1) * a.batch
            rows = rows[lo:lo + a.batch]
            span = f"part {a.part}, questions {lo + 1}-{lo + len(rows)} of {total}"
        else:
            span = f"all {total} unlinked"

        print(f"  chapter {a.chapter} | {head[0]} | standard {head[1]} "
              f"{head[2]} | {span}")
        print(f"\n  CONCEPTS -- cite one of these EXACT ids. {len(cons)} available.")
        for cid, name, desc in cons:
            print(f"   {cid}  {name}")
            if desc.strip():
                print(f"        {' '.join(desc.split())[:132]}")

        print(f"\n  UNLINKED QUESTIONS")
        for qid, sha, title, ans in rows:
            addr = sha if sha else f"qid:{qid}"
            print(f"\n   [{addr}]")
            print(f"     Q: {' '.join(str(title or '').split())[:230]}")
            if ans and str(ans).strip():
                print(f"     A: {' '.join(str(ans).split())[:150]}")

        if not rows:
            print("   nothing left to link in this chapter")
        print(f"\n  Pair the QUESTION with the concept it actually tests, not the "
              f"one its\n  chapter is 'about'. A chapter's concepts are a "
              f"sequence through the text;\n  most questions sit on one of them "
              f"specifically. If a question genuinely\n  tests none of them "
              f"(a generic grammar drill in a literature chapter, an\n  unseen "
              f"passage), leave it out and say so -- an empty link is honest, a\n"
              f"  wrong one is not.\n\n  Write "
              f"{{\"chapter_id\": {a.chapter}, \"links\": "
              f"[{{\"sha\": \"...\", \"concept_id\": N, \"note\": \"why\"}}]}} "
              f"and load it with\n  load_question_concepts.py.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
