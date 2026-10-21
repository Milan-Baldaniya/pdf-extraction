"""Correct eleven Mathematics answer keys that mark the wrong option.

    python -m scripts.fix_maths_answer_keys            # report only
    python -m scripts.fix_maths_answer_keys --apply

A wrong key is the defect that reaches a student most directly and the one no
validator sees: V-02 checks the key names an option that exists, V-04 that an
MCQ has one at all -- neither can tell the option named is the wrong one.

An audit that recomputed the arithmetic across 3,494 Maths rows in Classes 8-10
found 24 wrong keys. **Only the eleven below are repairable by re-keying**,
because only these have the correct value present among their options. Each was
recomputed twice, independently, and each option set was then read from the
database to confirm the right answer is really there. The working is in the
table.

The other thirteen are NOT touched here and must not be "fixed" by moving the
key, because the correct value is absent from the option set -- the item itself
is broken and needs rewriting or retiring:

    113781  floor 50 m^2 x height 20 m = 1000 m^3; options stop at 100
    113852  A:B = 1:3, B:C = 4:5 gives C:A = 15:4; only 15:8 is offered
    113859  20 cows = 15 oxen, so 36 oxen = 48 cows; 48 is not offered
    113448  z + 4 = -8 gives z = -12; only -32 is offered
    113712  2x + 6 = -20 gives x = -13; only -12 is offered
    728340  a die shows >3 on 3 faces, P = 1/2; not among the options
    113545  a parallelogram has 0 lines of symmetry; options are 4, 1, 2
    113679  x^2 - 2x + 1 at x = 1 is 0; options are 1, 2, -2
    plus five free-response model answers that are wrong in their working
    (734384 trisection, 704850 mirror images, 734425 P(x) = 3x+4,
    734612 2/5, 734613 exactly 1/3, 734649 three levels, 728293 mean 220)

THE GUARD. Nothing is changed unless the option now sitting at the target
position still reads as the expected value, and the option currently flagged
still reads as the expected wrong one. If either has moved since this was
written the whole run stops. `answer_master` has no stored label and order is
by id, so a row inserted or reordered would otherwise silently shift the key
onto a different option -- exactly the defect being repaired.

Reversible: the change is one `correct_answer` flag off and one on, per
question. The "was" column below is the state to restore.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

# qid, text that must appear in the RIGHT option, text that must appear in the
# WRONG one now flagged, and why.
FIXES = [
    (113526, "360", "720",
     "the exterior angles of any polygon sum to one full turn"),
    (113596, "9801", "9999",
     "99^2 = 9801; 100^2 = 10000 has five digits, and 9999 is not a square"),
    (113652, "10 : 1", "1 : 10",
     "5 km/h = 5000 m/h, and 5000 : 500 = 10 : 1 -- the key is inverted"),
    (113661, "one-fourth", "four times",
     "quarterly compounding applies R/4 over 4n periods"),
    (113671, "half the given annual rate and double", "double the given annual rate and half",
     "half-yearly compounding is A = P(1 + R/200)^(2n)"),
    (113876, "abc/3", "3a2b2c2",
     "5/15 = 1/3 and every exponent drops by one"),
    (113808, "False", "True",
     "1/a^m IS a^-m, so the reciprocal of a^-m is a^m, not 1/a^m"),
    (734403, "Only Student A", "Both students",
     "in p(x) = 5 - 2x the coefficient of x is -2, not 5"),
    (705087, "4^{5}", "4^{3}",
     "the product of five GP terms is (ar^2)^5 = 4^5"),
    (734543, "Garden A has greater area", "Garden B has greater area",
     "perimeter 40 gives A = 12x8 = 96 and B = 15x5 = 75"),
    (734630, "10th", "9th",
     "a_n = 55 - 5n, so a_9 = 10 which is not below 10, and a_10 = 5"),
]
WS = re.compile(r"\s+")


def norm(s: str) -> str:
    return WS.sub(" ", (s or "")).strip().lower()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        plan, refused = [], []
        for qid, right, wrong, why in FIXES:
            rows = db.execute(text(
                "SELECT id, answer, correct_answer FROM answer_master "
                " WHERE question_id = :q ORDER BY id"), {"q": qid}).fetchall()
            if not rows:
                refused.append(f"{qid}: no options stored")
                continue
            hit = [r for r in rows if norm(right) in norm(str(r[1]))]
            cur = [r for r in rows if r[2]]
            if len(hit) != 1:
                refused.append(f"{qid}: {len(hit)} option(s) contain {right!r} "
                               f"-- expected exactly one")
                continue
            if len(cur) != 1:
                refused.append(f"{qid}: {len(cur)} option(s) flagged correct "
                               f"-- expected exactly one")
                continue
            if norm(wrong) not in norm(str(cur[0][1])):
                refused.append(f"{qid}: the flagged option reads "
                               f"{norm(str(cur[0][1]))[:48]!r}, not {wrong!r} "
                               f"-- it may already be fixed")
                continue
            if hit[0][0] == cur[0][0]:
                refused.append(f"{qid}: already correct")
                continue
            stem = db.execute(text(
                "SELECT question_title FROM lms_question_master WHERE id=:q"),
                {"q": qid}).scalar()
            plan.append((qid, str(stem or ""), cur[0][0], str(cur[0][1]),
                         hit[0][0], str(hit[0][1]), why))

        print(f"  {len(plan)} key(s) to correct, {len(refused)} refused\n")
        for qid, stem, was_id, was, now_id, now, why in plan:
            print(f"   qid {qid}  {norm(stem)[:72]}")
            print(f"      was  [{was_id}] {norm(was)[:60]}")
            print(f"      now  [{now_id}] {norm(now)[:60]}")
            print(f"      why  {why}\n")
        if refused:
            print("  REFUSED:")
            for r in refused:
                print(f"    {r}")
            print("\n  Nothing has been changed. Re-read these before retrying.")
            return 1

        if not a.apply:
            print("  report only -- re-run with --apply")
            return 0

        for qid, _, was_id, _, now_id, _, _ in plan:
            db.execute(text("UPDATE answer_master SET correct_answer = 0 "
                            " WHERE id = :i"), {"i": was_id})
            db.execute(text("UPDATE answer_master SET correct_answer = 1 "
                            " WHERE id = :i"), {"i": now_id})
        db.commit()
        # read back rather than trusting the write
        bad = 0
        for qid, _, was_id, _, now_id, _, _ in plan:
            f = db.execute(text("SELECT id FROM answer_master "
                                " WHERE question_id=:q AND correct_answer=1"),
                           {"q": qid}).fetchall()
            if len(f) != 1 or f[0][0] != now_id:
                print(f"    qid {qid}: VERIFY FAILED, flagged {[r[0] for r in f]}")
                bad += 1
        print(f"\n  corrected {len(plan)} key(s); {bad} failed verification")
        return 1 if bad else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
