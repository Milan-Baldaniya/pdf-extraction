"""Print a chapter's concepts and its questions, for a reader to pair.

    python -m scripts.question_concept_context --chapter 25930
    python -m scripts.question_concept_context --chapter 25930 --batch 60 --part 2
    python -m scripts.question_concept_context --chapter 25930 --unlinked
    python -m scripts.question_concept_context --coverage --standard 40
    python -m scripts.question_concept_context --concept-report 25930

**16,360 of 37,841 live questions carry no concept**, and the 21,481 that do
were tagged by an offline lexical matcher whose confidence never exceeds 0.45
anywhere in the table. 26% of its output shares no content word with the concept
it assigned; where two tables disagree, or confidence is under 0.30, it is wrong
about 44% of the time. So this tool exists to replace that output by reading,
not to fill around it.

`concept_id` is load-bearing: `concept_prerequisite` and `pal_concept_relations`
hang off it, so a question without one cannot contribute a prerequisite check or
be routed by PAL's adaptive ladder, and cannot serve as a grounding exemplar for
generation.

PAGINATION IS OVER A STABLE SET. `--part` slices **every** question in the
chapter ordered by `question_id`, whether or not it is linked. An earlier
version sliced the *currently unlinked* set, so applying part 1 made "part 2"
skip 60 rows -- silently. Pass `--unlinked` to filter the print, and the slice
still comes from the stable ordering, so parts never move under an apply.

OPTIONS ARE PRINTED. They live in `answer_master`, not on the question, and they
are often the only thing that makes an item pairable: `qid:113874` reads "Which
of the following is one of the factors of ____", which is unjudgeable, while its
options identify it exactly. The correct one is marked `*`.

STEMS ARE PRINTED WHOLE. On a comprehension item the sub-question sits *after*
the passage, so a truncated print hides the very thing being tested -- 121 Class
9 Hindi stems run past 230 characters and one runs to 4,261. `--max-stem` caps
it only if a chapter is genuinely unmanageable.

Addressing follows `load_question_curriculum`: `verbatim_sha256` where the
question has a sidecar, `qid:<id>` where the LMS itself wrote it and there is no
hash. The print gives whichever is correct for that row.
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
    """Per-chapter linked-vs-total. Sorted in Python: MariaDB refuses an
    aggregate alias in ORDER BY (1247, "Reference 'nk' not supported")."""
    rows = db.execute(text("""
        SELECT c.id, COALESCE(s.subject_name,'?') subj, c.chapter_name,
               COUNT(DISTINCT q.id) nq,
               COUNT(DISTINCT CASE WHEN COALESCE(q.concept_id, e.concept_id, 0) > 0
                                   THEN q.id END) nk,
               (SELECT COUNT(*) FROM lms_concept k WHERE k.chapter_id = c.id) ncon
          FROM chapter_master c
          LEFT JOIN subject s ON s.id = c.subject_id
          LEFT JOIN lms_question_master q
                 ON q.chapter_id = c.id AND q.deleted_at IS NULL
          LEFT JOIN lms_question_extraction e ON e.question_id = q.id
         WHERE c.standard_id = :s
         GROUP BY c.id, subj, c.chapter_name
        HAVING COUNT(DISTINCT q.id) > 0"""), {"s": standard}).fetchall()
    rows = sorted(rows, key=lambda r: (int(r[4]) / int(r[3]), -int(r[3])))

    print(f"  concept coverage, standard {standard}  ({len(rows)} chapters "
          f"holding questions)\n")
    print(f"  {'cid':>7} {'subject':<20} {'chapter':<34} {'q':>5} {'linked':>7} "
          f"{'concepts':>9}")
    tq = tk = 0
    for cid, subj, name, nq, nk, ncon in rows:
        nq, nk, ncon = int(nq), int(nk), int(ncon)
        tq += nq
        tk += nk
        if not ncon:
            flag = "  <- NO CONCEPTS, blocked"
        elif nk == 0:
            flag = "  <- all unlinked"
        elif nk < nq:
            flag = f"  <- {nq - nk} to go"
        else:
            flag = ""
        print(f"  {cid:>7} {str(subj)[:20]:<20} {str(name)[:34]:<34} "
              f"{nq:>5} {nk:>7} {ncon:>9}{flag}")
    print(f"\n  {tk} of {tq} linked ({tk * 100.0 / tq:.1f}%) across standard "
          f"{standard}" if tq else "\n  no questions")


def concept_report(db, chapter: int) -> None:
    """Which of a chapter's concepts no question reaches. 56.2% of concepts
    estate-wide are reached by nothing, which is a gap in the bank rather than
    in the mapping -- worth seeing per chapter before deciding it is one."""
    rows = db.execute(text("""
        SELECT k.id, k.name,
               (SELECT COUNT(*) FROM lms_question_master q
                  LEFT JOIN lms_question_extraction e ON e.question_id = q.id
                 WHERE q.deleted_at IS NULL
                   AND COALESCE(q.concept_id, e.concept_id) = k.id) n
          FROM lms_concept k WHERE k.chapter_id = :c ORDER BY k.id"""),
        {"c": chapter}).fetchall()
    if not rows:
        print(f"  chapter {chapter} has no concepts")
        return
    reached = sum(1 for r in rows if int(r[2]))
    print(f"  chapter {chapter}: {reached} of {len(rows)} concepts reached "
          f"by at least one question\n")
    for cid, name, n in rows:
        mark = f"{n:>4}" if n else "   ."
        print(f"   {mark}  {cid}  {name}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chapter", type=int)
    ap.add_argument("--batch", type=int, default=0, help="questions per part (0 = all)")
    ap.add_argument("--part", type=int, default=1)
    ap.add_argument("--unlinked", action="store_true",
                    help="print only questions that have no concept yet")
    ap.add_argument("--max-stem", type=int, default=0,
                    help="cap stem length (0 = print whole)")
    ap.add_argument("--coverage", action="store_true")
    ap.add_argument("--concept-report", type=int, metavar="CID")
    ap.add_argument("--standard", type=int, default=43)
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        if a.concept_report:
            concept_report(db, a.concept_report)
            return 0
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
            "SELECT id, name, COALESCE(description,'') "
            "  FROM lms_concept WHERE chapter_id = :c ORDER BY id"),
            {"c": a.chapter}).fetchall()
        if not cons:
            print(f"  chapter {a.chapter} | {head[0]} | standard {head[1]} {head[2]}")
            print("\n  THIS CHAPTER HAS NO CONCEPTS. There is nothing legal to "
                  "pair with.\n  Report it -- the concept pipeline has not run "
                  "here -- and do not invent one.")
            return 1

        # Stable ordering over EVERY question in the chapter, so a part never
        # moves under an apply. --unlinked filters the print, not the slice.
        rows = db.execute(text(
            "SELECT q.id, e.verbatim_sha256, q.question_title, "
            "       COALESCE(q.hint_text,''), "
            "       COALESCE(q.concept_id, e.concept_id, 0), COALESCE(q.concept,'') "
            "  FROM lms_question_master q "
            "  LEFT JOIN lms_question_extraction e ON e.question_id = q.id "
            " WHERE q.chapter_id = :c AND q.deleted_at IS NULL "
            " ORDER BY q.id"), {"c": a.chapter}).fetchall()

        total = len(rows)
        if a.batch:
            lo = (a.part - 1) * a.batch
            rows = rows[lo:lo + a.batch]
            span = f"part {a.part}, questions {lo + 1}-{lo + len(rows)} of {total}"
        else:
            span = f"all {total}"
        shown = [r for r in rows if not (a.unlinked and int(r[4]))]

        opts: dict[int, list] = {}
        if shown:
            for qid, txt, ok in db.execute(text(
                    "SELECT question_id, answer, correct_answer FROM answer_master "
                    " WHERE question_id IN :ids ORDER BY question_id, id"),
                    {"ids": tuple(int(r[0]) for r in shown)}).fetchall():
                opts.setdefault(int(qid), []).append((str(txt or ""), int(ok or 0)))

        cname = {int(i): str(n) for i, n, _ in cons}
        print(f"  chapter {a.chapter} | {head[0]} | standard {head[1]} "
              f"{head[2]} | {span}"
              + (f" | {len(shown)} unlinked shown" if a.unlinked else ""))
        print(f"\n  CONCEPTS -- cite one of these EXACT ids. {len(cons)} available.")
        for cid, name, desc in cons:
            print(f"   {cid}  {name}")
            if str(desc).strip():
                print(f"        {' '.join(str(desc).split())}")

        print(f"\n  QUESTIONS")
        for qid, sha, title, ans, cur, curname in shown:
            addr = sha if sha else f"qid:{qid}"
            stem = " ".join(str(title or "").split())
            if a.max_stem and len(stem) > a.max_stem:
                stem = stem[:a.max_stem] + " ...[truncated]"
            print(f"\n   [{addr}]")
            if int(cur):
                print(f"     ALREADY LINKED -> {cur} {cname.get(int(cur), curname)}"
                      f"   (re-read it; do not assume it is right)")
            print(f"     Q: {stem}")
            for i, (o, ok) in enumerate(opts.get(int(qid), [])):
                print(f"       {'*' if ok else ' '} {chr(65+i)}. "
                      f"{' '.join(str(o).split())[:160]}")
            if str(ans).strip():
                print(f"     A: {' '.join(str(ans).split())[:400]}")

        if not shown:
            print("   nothing to show for this slice")
        print(f"\n  Pair the QUESTION with the concept it actually tests, not the "
              f"one its\n  chapter is 'about'. A chapter's concepts are a "
              f"sequence through the text;\n  most questions sit on one of them "
              f"specifically. Read each concept's\n  DESCRIPTION -- the names are "
              f"short and several will sound alike.\n\n  If a question genuinely "
              f"tests none of them, leave it out and say so: an\n  empty link is "
              f"honest, a wrong one is invisible and propagates.\n\n  Write "
              f"{{\"chapter_id\": {a.chapter}, \"links\": "
              f"[{{\"sha\": \"...\", \"concept_id\": N, \"note\": \"why\"}}]}} "
              f"and load it with\n  load_question_concepts.py. Overwriting an "
              f"existing link needs --force and a\n  note saying what it was.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
