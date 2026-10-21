"""Repair the fifteen Mathematics items an answer-key audit could not re-key.

    python -m scripts.repair_maths_defective_items            # report only
    python -m scripts.repair_maths_defective_items --apply

`fix_maths_answer_keys` repaired eleven wrong keys by moving the flag to the
option that already held the right value. It listed fifteen more it refused to
touch. Re-reading all fifteen shows they are **three different defects**, and
only one of them is "retire it":

  RE-KEY (1). 113781 was listed as unfixable on the grounds that its options
  stop at 100. They do not -- the fourth option is "none of the above", and
  since 50 m^2 x 20 m = 1000 m^3 is genuinely not among 140/120/100, that option
  is the correct answer. The item is sound; only the flag was wrong.

  RETIRE (7). The correct value is absent from the option set, so the item
  cannot be answered correctly by anyone. Two of them (113545, 113679) carry no
  flagged answer at all and offer only three options. Retiring is `deleted_at`,
  which is how this estate already marks a question that should not be served;
  the row stays readable and its curriculum and concept links stay attached, so
  clearing the column restores it.

  REWRITE THE MODEL ANSWER (7). These are free-response items whose **question
  is fine** and whose stored working is wrong. Retiring them would throw away
  seven sound questions to avoid fixing seven paragraphs, so the answer is
  rewritten instead. Four of the seven are a single slip in an otherwise correct
  derivation -- 728293 computes Sum(f.x) = 11000 over Sum(f) = 50 and then
  writes "11000/50 = 200".

WHAT WAS WRONG, kept here because an UPDATE overwrites the only copy:

  734384  claimed P is the midpoint of AM, and mis-divided twice: "(14/2,
          9.5/2) = (8, 4.25)" (14/2 is 7, 9.5/2 is 4.75) and "26/2 = 12".
          Gave P(8, 4.25), Q(12, 0.25). The midpoint of AM is a QUARTER of the
          way along AB, not a third, so the method is wrong as well.
  704850  claimed "PR perpendicular to MP" (PR has slope -1/4, MP is vertical)
          and "No points are mirror images" (M and P plainly are).
  734425  misread the table as rising by 4 and invented "P(1) = 9", giving
          P(x) = 4x + 5, P(0) = 5, P(10) = 45. The table rises by 3 from 4.
  734612  "100/250 = 2/25". The other four parts were right.
  734613  "P(Fruits) = 20/60 < 1/3". 20/60 IS 1/3, so the answer to "state
          whether it is less than 1/3" is no, not yes.
  734649  summed five extra levels (710) and concluded five are needed. Three
          are: 132 + 137 + 142 = 411 and 1675 + 411 = 2086 >= 2000.
  728293  correct to Sum(f.x) = 11000, Sum(f) = 50, then "11000/50 = 200".

THE GUARD. Every row is re-read at run time and must still carry the defect
described -- the wrong option still flagged, or the wrong phrase still in the
model answer. If any row has been edited since this was written the whole run
stops rather than overwrite someone else's correction. Nothing is deleted.
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

# ---------------------------------------------------------------- retire ----
# qid, a fragment that must still be in the stem, the value the item needs and
# does not offer, and the options it does offer.
RETIRE = [
    (113852, "then C : A is equal to", "15 : 4",
     "A:B = 1:3 and B:C = 4:5 put B = 12, so A = 4 and C = 15"),
    (113859, "how many cows will eat", "48",
     "15 oxen eat as much as 20 cows, so 36 oxen eat as much as 36 x 20/15"),
    (113448, "The root of the equation z + 4", "-12",
     "z + 4 = -8 gives z = -12; the flagged option is -32"),
    (113712, "The solution of the equation 2x + 6", "-13",
     "2x = -26 gives x = -13; the flagged option is -12"),
    (728340, "number greater then 3 in throwing a die", "1/2",
     "three of six faces exceed 3, so the probability is 1/2"),
    (113545, "lines of symmetry for a parallelogram", "0",
     "a general parallelogram has no line of symmetry; options are 4, 1, 2 "
     "and none is flagged"),
    (113679, "when x = 1", "0",
     "1 - 2 + 1 = 0; options are 1, 2, -2 and none is flagged"),
    # Found in a second pass, reading all 21 Class 8/9 Mathematics chapters.
    (113851, "statements is CORRECT", "none of these",
     "all three statements are false, and 'All of these' is flagged: a square's "
     "area goes as the SQUARE of its side, a circle's area as the square of its "
     "diameter, and two angles of a triangle with the third fixed have a "
     "constant SUM, not a constant product. No 'none of these' is offered"),
]

# ----------------------------------------------------------------- re-key ----
# qid, the option text to flag, the option text to unflag, why.
REKEY = [
    (113781, "none of the above", "100 m",
     "50 m^2 x 20 m = 1000 m^3, which none of 140/120/100 offers"),
    # Found in a second pass over Classes 8 and 9 Mathematics.
    (113509, "True", "False",
     "a regular polygon is equilateral and equiangular, so each interior angle "
     "is (n-2)180/n, which is under 180 for every n >= 3 -- it is necessarily "
     "convex. 'All regular polygons are convex' is True, not False"),
    (113463, "13, 10", "12, 11",
     "x - y = 3 and x + y = 23 give x = 13, y = 10. The flagged pair 12 and 11 "
     "sums to 23 but differs by 1, so it fails the first condition"),
]

# ------------------------------------------------------- rewritten answers ----
# qid, a phrase that must STILL be present (proving the defect is unrepaired),
# and the replacement model answer.
REWRITE = [
    (734384, "midpoint of segment AM",
     "(i) M is the midpoint of AB, so M = ((4 + 16)/2, (7 + (-2))/2) "
     "= (10, 2.5).\n"
     "(ii) P is the point of trisection nearer A, so P divides AB in the "
     "ratio 1 : 2. By the section formula "
     "P = ((1(16) + 2(4))/3, (1(-2) + 2(7))/3) = (24/3, 12/3) = (8, 4). "
     "Q divides AB in the ratio 2 : 1, so "
     "Q = ((2(16) + 1(4))/3, (2(-2) + 1(7))/3) = (36/3, 3/3) = (12, 1).\n"
     "The midpoint idea checks the result: the midpoint of PQ is "
     "((8 + 12)/2, (4 + 1)/2) = (10, 2.5) = M, as it must be. Note that P is "
     "NOT the midpoint of AM -- that midpoint is (7, 4.75), which lies one "
     "quarter of the way along AB rather than one third.\n"
     "Trisection points: P(8, 4) and Q(12, 1)."),

    (704850, "No points are mirror images",
     "Taking the sides in the order given, RA runs from R(3, 0) to A(0, -2), "
     "AM from A(0, -2) to M(-5, -2), MP from M(-5, -2) to P(-5, 2) and PR "
     "from P(-5, 2) back to R(3, 0). Their slopes are 2/3, 0, undefined and "
     "-1/4.\n"
     "(i) AM is perpendicular to MP: AM is horizontal and MP is vertical, so "
     "they meet at right angles at M. No other pair is perpendicular -- RA "
     "and PR have slopes 2/3 and -1/4, whose product is -1/6, not -1.\n"
     "(ii) AM lies along y = -2, so AM is parallel to the x-axis; MP lies "
     "along x = -5, so MP is parallel to the y-axis.\n"
     "(iii) M(-5, -2) and P(-5, 2) are mirror images of each other in the "
     "x-axis: they share the same x-coordinate and their y-coordinates are "
     "equal and opposite."),

    (734425, "P(x)=4x+5",
     "(a) As x rises by 1 the value of P(x) rises by 3 (4, 7, 10, 13), so "
     "a = 3. At x = 0 the table gives P(0) = 4, so b = 4. Hence "
     "P(x) = 3x + 4.\n"
     "(b) P(0) = 4, read directly from the table, and consistent with "
     "3(0) + 4 = 4.\n"
     "(c) P(10) = 3(10) + 4 = 34."),

    (734612, "100/250 = 2/25",
     "There are 250 customers in all.\n"
     "(i) P(clothes) = 100/250 = 2/5.\n"
     "(ii) P(electronics) = 80/250 = 8/25.\n"
     "(iii) P(groceries) = 50/250 = 1/5.\n"
     "(iv) P(not books) = (250 - 20)/250 = 230/250 = 23/25.\n"
     "(v) P(clothes or electronics) = (100 + 80)/250 = 180/250 = 18/25."),

    (734613, "20/60 < 1/3",
     "There are 60 students in all.\n"
     "(i) P(sandwiches) = 25/60 = 5/12, P(fruits) = 20/60 = 1/3 and "
     "P(snacks) = 15/60 = 1/4. The most chosen item is sandwiches, with "
     "probability 5/12.\n"
     "(ii) No. P(fruits) = 20/60 = 1/3 exactly, so it is equal to 1/3 and "
     "not less than it.\n"
     "(iii) P(sandwiches or snacks) = (25 + 15)/60 = 40/60 = 2/3."),

    (734649, "5 additional complete levels",
     "The level scores 7, 12, 17, ... form an AP with a = 7 and d = 5.\n"
     "S(25) = 25/2 [2(7) + (25 - 1)(5)] = 25/2 [14 + 120] = 25/2 (134) "
     "= 1675 points.\n"
     "The player is short of 2000 by 2000 - 1675 = 325 points.\n"
     "Level 26 scores a(26) = 7 + 25(5) = 132, level 27 scores 137 and level "
     "28 scores 142. Two more levels add 132 + 137 = 269, giving 1944, which "
     "is still short. Three more add 132 + 137 + 142 = 411, giving 2086, "
     "which passes 2000.\n"
     "So 3 additional complete levels are needed."),

    (728293, "11000/50 = 200",
     "The table is of the 'less than' cumulative type, so the ordinary "
     "frequencies come from subtracting successive entries: 0-100 -> 12, "
     "100-200 -> 28 - 12 = 16, 200-300 -> 34 - 28 = 6, 300-400 -> "
     "41 - 34 = 7 and 400-500 -> 50 - 41 = 9, giving Sum(f) = 50.\n"
     "The class marks are 50, 150, 250, 350, 450, so the products f.x are "
     "600, 2400, 1500, 2450 and 4050, giving Sum(f.x) = 11000.\n"
     "Mean = Sum(f.x)/Sum(f) = 11000/50 = 220.\n"
     "Hence the average daily income is Rs. 220."),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        refused: list[str] = []
        to_retire, to_rekey, to_rewrite = [], [], []

        print("  RETIRE -- the correct value is not among the options\n")
        for qid, frag, need, why in RETIRE:
            r = db.execute(text(
                "SELECT question_title, deleted_at FROM lms_question_master "
                " WHERE id = :q"), {"q": qid}).fetchone()
            if not r:
                refused.append(f"{qid} does not exist")
                continue
            if r[1] is not None:
                print(f"   {qid}  already retired, skipping")
                continue
            if frag not in str(r[0]):
                refused.append(f"{qid}: stem no longer contains {frag!r}")
                continue
            opts = [str(t or "") for t, in db.execute(text(
                "SELECT answer FROM answer_master WHERE question_id = :q "
                " ORDER BY id"), {"q": qid}).fetchall()]
            if any(need == o.strip() or need == o.strip().rstrip(".")
                   for o in opts):
                refused.append(f"{qid}: {need!r} IS now among the options -- "
                               f"re-key it instead of retiring it")
                continue
            to_retire.append(qid)
            print(f"   {qid}  needs {need!r}, offers "
                  f"{', '.join(o.strip()[:18] for o in opts)}")
            print(f"          {why}")

        print("\n  RE-KEY -- the right value is present, the flag was wrong\n")
        for qid, right, wrong, why in REKEY:
            rows = db.execute(text(
                "SELECT id, answer, correct_answer FROM answer_master "
                " WHERE question_id = :q ORDER BY id"), {"q": qid}).fetchall()
            hit_r = [i for i, t, _ in rows if right.lower() in str(t or "").lower()]
            hit_w = [i for i, t, f in rows if wrong in str(t or "") and int(f or 0)]
            flagged = [i for i, _, f in rows if int(f or 0)]
            if len(hit_r) == 1 and flagged == hit_r:
                print(f"   {qid}  already re-keyed, skipping")
                continue
            if len(hit_r) != 1 or len(hit_w) != 1:
                refused.append(f"{qid}: expected one option holding {right!r} "
                               f"and one flagged option holding {wrong!r}, "
                               f"found {len(hit_r)} and {len(hit_w)}")
                continue
            to_rekey.append((qid, hit_r[0], hit_w[0]))
            print(f"   {qid}  flag moves off {wrong!r} onto {right!r}")
            print(f"          {why}")

        print("\n  REWRITE THE MODEL ANSWER -- the question is sound\n")
        for qid, frag, new in REWRITE:
            cur = db.execute(text(
                "SELECT COALESCE(hint_text,'') FROM lms_question_master "
                " WHERE id = :q"), {"q": qid}).scalar()
            flat = " ".join(str(cur).split())
            if flat == " ".join(new.split()):
                print(f"   {qid}  already rewritten, skipping")
                continue
            if frag not in flat:
                refused.append(f"{qid}: model answer no longer contains "
                               f"{frag!r} -- it may already be corrected")
                continue
            to_rewrite.append((qid, new))
            print(f"   {qid}  {len(flat)} chars -> {len(new)} chars "
                  f"(was wrong at {frag!r})")

        if refused:
            print(f"\n  REFUSED -- {len(refused)} row(s) are not in the state "
                  f"this script was written for:")
            for m in refused:
                print(f"    ! {m}")
            print("  Nothing has been written. Re-read those rows.")
            return 1

        print(f"\n  {len(to_retire)} to retire, {len(to_rekey)} to re-key, "
              f"{len(to_rewrite)} answers to rewrite")
        if not a.apply:
            print("  report only -- re-run with --apply")
            return 0

        for qid in to_retire:
            db.execute(text("UPDATE lms_question_master SET deleted_at = NOW() "
                            " WHERE id = :q AND deleted_at IS NULL"), {"q": qid})
        for qid, right_id, wrong_id in to_rekey:
            db.execute(text("UPDATE answer_master SET correct_answer = 0 "
                            " WHERE id = :i"), {"i": wrong_id})
            db.execute(text("UPDATE answer_master SET correct_answer = 1 "
                            " WHERE id = :i"), {"i": right_id})
        for qid, new in to_rewrite:
            db.execute(text("UPDATE lms_question_master SET hint_text = :h "
                            " WHERE id = :q"), {"h": new, "q": qid})
        db.commit()

        gone = db.execute(text(
            "SELECT COUNT(*) FROM lms_question_master "
            " WHERE id IN :ids AND deleted_at IS NOT NULL"),
            {"ids": tuple(to_retire)}).scalar() if to_retire else 0
        print(f"\n  retired {gone}, re-keyed {len(to_rekey)}, rewrote "
              f"{len(to_rewrite)} model answer(s)")
        print("  Retirement is reversible by clearing deleted_at. The wrong "
              "working each\n  rewritten answer used to carry is recorded in "
              "this file's docstring.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
