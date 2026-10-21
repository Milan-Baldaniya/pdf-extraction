"""Give the four new Class 9 Maths chapters a curriculum frame to map against.

    python -m scripts.seed_c9_maths_chapter_frames            # report only
    python -m scripts.seed_c9_maths_chapter_frames --apply

156 questions were loaded into four Class 9 Maths chapters that hold **zero**
`lms_learning_outcomes` rows, so `question_curriculum_context` prints
"CURRICULUM - NONE RECORDED for this chapter. There is nothing legal to cite"
and every mapping file is refused whole. This is the
`new-chapter-row-has-no-curriculum-frame` trap: outcomes are copied per chapter,
and a row created later gets no copy.

HOW CURRICULUM 94 IS SHAPED. Goals sit once at `chapter_id = 0`. Every chapter
then carries its **own copies** of the competencies and learning outcomes it
needs, linked `learning_outcome -> competency -> goal` by `parent_id`. Codes are
semantic and stable here (`C-5.2-LO-1`), not renumbered per chapter as they are
in several other curricula.

WHAT THIS COPIES, AND WHY THOSE CHOICES. Each new chapter is given the
competencies from curriculum 94 whose text actually describes its content, with
their learning outcomes. The selection is a judgement and is listed in full
below so it can be argued with:

    38387 Understanding Data          C-6.1  central tendency: mean/median/mode
                                      C-8.1  models phenomena using graphs
    38389 Quadrilaterals              C-7.3  theorems for angles, triangles,
                                             quadrilaterals
                                      C-4.1  congruence of 2-D shapes
    38390 Two Variables, One Line     C-3.2  solves contextualised problems
                                             using equations
                                      C-8.1  models phenomena using graphs
    38391 Surface Area and Volume     C-5.2  discovers formulae for surface
                                             area and volume
                                      C-7.1  proves statements, geometric
                                             construction

Note that the frame this copies from is itself loose — chapter 8598, on circles,
carries C-6.1 and C-6.2 on statistics and probability, which do not describe it.
So "what the unit sibling has" is NOT a safe rule, and this script deliberately
picks by the competency's own wording instead.

**The two remaining empty chapters are left alone on purpose.** 38386
"Propositions and their Converses" and 38388 "The World of Algorithms" are new
NEP topics with no question loaded and no clean competency in curriculum 94;
seeding them would invent a frame rather than complete one.

SAFE TO RE-RUN. Nothing is copied to a chapter that already has rows for that
code, so a second run writes nothing. INSERT only: no existing outcome row is
modified and none is deleted. To undo, delete the rows this prints — they are
the only ones carrying these four `chapter_id`s.
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

CURRICULUM = 94
# chapter -> [(competency code, copy its learning outcomes too?)]
#
# THE COMPETENCY TEXT AND ITS OUTCOMES DO NOT ALWAYS AGREE. A first pass here
# selected competencies purely on their own wording and would have been wrong:
# C-7.3's text names quadrilaterals, but its four outcomes are the area of a
# parallelogram, the circumference of a circle, arc length and the area of a
# circle -- they were authored for "Measuring Space: Perimeter and Area" and say
# nothing about quadrilateral properties. C-7.1's outcomes are perimeter-versus-
# area and the irrationality of pi, nothing about surface area or volume. Copying
# them would have produced confident mappings onto outcomes about circles.
#
# So the outcomes are copied ONLY where they genuinely describe the new chapter.
# Where they do not, the competency is copied alone, and questions there are
# cited at competency level -- which is the honest altitude, and what every
# mapping agent already does wherever a frame is thin.
PLAN = {
    38387: ("How Quantities Combine: Understanding Data", [
        # Central tendency: mean, median, mode -- exactly this chapter's content.
        # VERIFIED: C-6.1 carries NO learning outcomes anywhere in curriculum 94
        # (all three of its competency copies have zero children, and the only
        # C-6.x outcomes in this curriculum are C-6.2's, on probability). So this
        # chapter is competency-level only, whatever the flag says. Curriculum
        # 101 does define C-6.1-LO-1..3, but importing them would be authoring
        # new Class 9 curriculum rather than completing a copy -- an editorial
        # decision, deliberately not taken here.
        ("C-6.1", True),
        # C-8.1's outcomes are about graphing LINEAR RELATIONSHIPS, not about
        # bar graphs or histograms, so the competency comes without them.
        ("C-8.1", False),
    ]),
    38389: ("Quadrilaterals", [
        ("C-7.3", False),   # outcomes are circle and area work
        ("C-4.1", False),   # congruence of 2-D shapes; carries no outcomes
    ]),
    38390: ("Two Variables, One Line", [
        # LO-1..3 are linear patterns, the rule ax + b, linear growth and decay.
        ("C-3.2", True),
        # LO-4..6 draw a linear relationship, read slope and intercept, explain
        # parallel lines. This chapter IS linear equations in two variables.
        ("C-8.1", True),
    ]),
    38391: ("Math of Space: Surface Area and Volume", [
        # text is exactly "formulae to calculate surface area and volume";
        # it carries no outcomes of its own.
        ("C-5.2", True),
    ]),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        # One donor row per competency code: any chapter's copy will do, since
        # the text is identical across copies. Lowest id for determinism.
        plan_rows, refused = [], []
        for cid, (name, codes) in PLAN.items():
            have = {r[0] for r in db.execute(text(
                "SELECT code FROM lms_learning_outcomes "
                " WHERE curriculum_id=:cu AND chapter_id=:c"),
                {"cu": CURRICULUM, "c": cid}).fetchall()}
            for code, with_los in codes:
                if code in have:
                    refused.append(f"{cid} already has {code}")
                    continue
                comp = db.execute(text(
                    "SELECT id, parent_id, code, description, standard_id, subject_id "
                    "  FROM lms_learning_outcomes "
                    " WHERE curriculum_id=:cu AND code=:code AND type='competency' "
                    " ORDER BY id LIMIT 1"),
                    {"cu": CURRICULUM, "code": code}).fetchone()
                if not comp:
                    refused.append(f"{cid}: competency {code} not found in "
                                   f"curriculum {CURRICULUM}")
                    continue
                los = db.execute(text(
                    "SELECT code, description FROM lms_learning_outcomes "
                    " WHERE curriculum_id=:cu AND parent_id=:p "
                    "   AND type='learning_outcome' ORDER BY code"),
                    {"cu": CURRICULUM, "p": comp[0]}).fetchall() if with_los else []
                plan_rows.append((cid, name, comp, los))

        print(f"  curriculum {CURRICULUM}, {len(plan_rows)} competency copy(ies) "
              f"to make, {len(refused)} skipped\n")
        total_lo = 0
        for cid, name, comp, los in plan_rows:
            total_lo += len(los)
            print(f"   chapter {cid}  {name[:44]}")
            print(f"      + {comp[2]:<10} {str(comp[3])[:82]}")
            for code, desc in los:
                print(f"          + {code:<14} {str(desc)[:72]}")
        print(f"\n   totals: {len(plan_rows)} competencies, {total_lo} learning outcomes")
        if refused:
            print("\n  skipped:")
            for r in refused:
                print(f"    {r}")

        if not a.apply:
            print("\n  report only -- re-run with --apply")
            return 0

        made = 0
        for cid, _, comp, los in plan_rows:
            db.execute(text(
                "INSERT INTO lms_learning_outcomes (curriculum_id, standard_id, "
                "  subject_id, chapter_id, parent_id, code, type, description) "
                "VALUES (:cu, :std, :sub, :c, :par, :code, 'competency', :desc)"),
                {"cu": CURRICULUM, "std": comp[4], "sub": comp[5], "c": cid,
                 "par": comp[1], "code": comp[2], "desc": comp[3]})
            new_comp = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()
            made += 1
            for code, desc in los:
                db.execute(text(
                    "INSERT INTO lms_learning_outcomes (curriculum_id, standard_id, "
                    "  subject_id, chapter_id, parent_id, code, type, description) "
                    "VALUES (:cu, :std, :sub, :c, :par, :code, 'learning_outcome', :desc)"),
                    {"cu": CURRICULUM, "std": comp[4], "sub": comp[5], "c": cid,
                     "par": new_comp, "code": code, "desc": desc})
                made += 1
            db.commit()

        print(f"\n  inserted {made} row(s). Per-chapter totals now:")
        for cid, (name, _) in PLAN.items():
            n = db.execute(text(
                "SELECT COUNT(*) FROM lms_learning_outcomes "
                " WHERE curriculum_id=:cu AND chapter_id=:c"),
                {"cu": CURRICULUM, "c": cid}).scalar()
            print(f"    {cid}  {name[:44]:<44} {n}")
        print("\n  The 156 loaded questions can now be mapped; re-run the mapping "
              "pass.\n  Chapters 38386 and 38388 were left with no frame on purpose.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
