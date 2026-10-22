"""Create the chapter rows a book has but `chapter_master` does not, and move
each one's questions off the neighbour they were parked on.

    python -m scripts.create_missing_chapters_and_refile            # report
    python -m scripts.create_missing_chapters_and_refile --apply
    python -m scripts.create_missing_chapters_and_refile --apply --reorder

A chapter with no row does not make the loader fail. It files that chapter's
questions under a neighbouring chapter that does exist, reports success, and
passes every validator -- the receiving chapter merely looks well stocked. Two
books in Class 8 are affected:

    Class 8 SCIENCE has 13 rows for an 18-chapter book. The five with no row
    put 264 questions into chapter 25838 "Microorganisms", which is why it held
    339 against a ~120 average and was the only chapter with no duplicates --
    its padding is foreign content, not a second copy.

    Class 8 ENGLISH (Honeydew) has the 8 prose chapters and none of the poems,
    so each poem's questions sit on the prose chapter of its own unit: "Who is
    the poet of 'The Ant and the Cricket'?" under "The Best Christmas Present
    in the World".

WHY THE ID RANGES ARE SAFE TO ACT ON. Questions arrive in blocks and a block
loaded against the wrong chapter keeps its own contiguous run of ids. Every
range below was read in full before this script was written. The English blocks
turned out to be exactly regular: the first ten questions of each are the poem
and the remainder are grammar and vocabulary exercises that belong where they
are, so only the first ten move.

    25863 116191-116200 poem, 116201-116220 clauses and gerunds  -- stay
    25864 116221-116230 poem, 116231-116240 subject-verb agreement -- stay
    25865 116241-116250 poem, 116251-116260 agreement             -- stay
    25866 116261-116270 poem, 116271-116280 tenses                -- stay
    25867 116281-116290 poem, 116291-116300 present perfect       -- stay
    25869 116301-116310 poem, 116311-116328 conditionals, adverbs -- stay
    25870 116329-116338 poem, 116339-116356 cloze                 -- stay

THE GUARD REFUSES RATHER THAN GUESSING. Every row in a range is re-read at run
time and tested against that chapter's own vocabulary; a range where too few
rows match, or where a row looks like a grammar exercise, stops the whole run
before anything moves. If the data has shifted since this was written, nothing
happens and the mismatch is named.

WHAT THIS DOES NOT FIX. A row created now carries NO CURRICULUM FRAME: outcomes
are copied per chapter, so these chapters have no outcome rows and their
questions cannot be CG/LO-mapped until a frame is attached -- see
`new-chapter-row-has-no-curriculum-frame`. They can be PAL-tagged immediately,
because that does not depend on the frame. Honeydew's eighth poem, "The Duck
and the Kangaroo", gets NO row: no question in the bank belongs to it, and an
empty row would add a chapter at zero while serving nobody.

INSERT and UPDATE only. Nothing is deleted, and the question ids do not change,
so any mapping already written against them stays attached -- both
`lms_question_outcome` and `pal_question_metadata` key on question_id.
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

# A grammar or vocabulary drill, which belongs to the prose chapter and must
# never be swept into a poem.
DRILL = re.compile(r"(?i)complete the sentence|choosing the correct|type of clause|"
                   r"identify the adverb|replace the adverb|subordinate|gerund|"
                   r"which conditional|choose the correct sentence")

# name, unit_id, book position, source chapter, id range, guard words
SCIENCE = [
    ("Synthetic Fibres and Plastics", 148, 3, 25838, 114059, 114106,
     ("fibre", "fibres", "plastic", "plastics", "nylon", "polyester", "rayon",
      "acrylic", "polymer", "thermoplastic", "fabric", "synthetic")),
    ("Materials: Metals and Non-Metals", 149, 4, 25838, 114107, 114158,
     ("metal", "metals", "non-metal", "nonmetal", "conductor", "malleable",
      "ductile", "rust", "corrosion", "alloy", "sonorous", "displacement")),
    ("Cell - Structure and Functions", 150, 8, 25838, 114307, 114356,
     ("cell", "cells", "nucleus", "cytoplasm", "membrane", "organelle",
      "chloroplast", "vacuole", "tissue", "protoplasm", "chromosome")),
    ("Stars and the Solar System", 153, 17, 25838, 114786, 114844,
     ("star", "stars", "planet", "planets", "solar", "moon", "comet",
      "asteroid", "constellation", "satellite", "galaxy", "orbit", "eclipse")),
    ("Pollution of Air and Water", 153, 18, 25838, 114845, 114899,
     ("pollution", "pollutant", "pollutants", "air", "water", "smog", "acid",
      "greenhouse", "warming", "ganga", "potable", "sewage", "emission")),
]

# Class 10 "Social Sciences" is Democratic Politics II: 5 rows for an 8-chapter
# book. The three with no row are exactly the three blocks found sitting on a
# neighbour, each a clean contiguous id run confirmed against the chapter's own
# totals. Its rows carry unit_id NULL, so the new ones do too.
# name, unit_id, book position, source chapter, id range, guard words
SOCIAL = [
    ("Democracy and Diversity", None, 3, 23712, 105466, 105495,
     ("diversity", "division", "social", "caste", "race", "racial", "ethnic",
      "civil", "rights", "movement", "black", "african", "belgium", "overlap",
      "discrimination", "origin", "identity", "migrant", "religion")),
    ("Popular Struggles and Movements", None, 5, 23713, 105538, 105592,
     ("movement", "struggle", "nepal", "bolivia", "water", "monarchy", "protest",
      "pressure", "group", "agitation", "lobby", "interest", "sectional",
      "mobilisation", "narmada", "andolan", "union", "sangharsh")),
    ("Challenges to Democracy", None, 8, 23714, 105691, 105720,
     ("challenge", "reform", "deepening", "foundational", "expansion",
      "democracy", "democratic", "opportunity", "difficulty", "citizen",
      "accountable", "legal", "political", "participation")),
]

# poem, unit_id, book position, prose chapter it was parked on, id range
ENGLISH = [
    ("The Ant and the Cricket", 165, 2, 25863, 116191, 116200),
    ("Geography Lesson", 165, 4, 25864, 116221, 116230),
    ("Macavity: The Mystery Cat", 166, 6, 25865, 116241, 116250),
    ("The Last Bargain", 166, 8, 25866, 116261, 116270),
    ("The School Boy", 166, 10, 25867, 116281, 116290),
    ("When I Set Out for Lyonnesse", 168, 14, 25869, 116301, 116310),
    ("On the Grasshopper and Cricket", 168, 16, 25870, 116329, 116338),
]

# The book's own order, for --reorder. Existing rows keep their id and change
# only sort_order, so the map printed below is enough to undo it.
SCIENCE_ORDER = [(25837, 1), (25838, 2), (25839, 5), (25840, 6), (25841, 7),
                 (25842, 9), (25843, 10), (25844, 11), (25845, 12), (25846, 13),
                 (25847, 14), (25848, 15), (25849, 16)]
ENGLISH_ORDER = [(25863, 1), (25864, 3), (25865, 5), (25866, 7), (25867, 9),
                 (25868, 11), (25869, 13), (25870, 15)]
SOCIAL_ORDER = [(23710, 1), (23711, 2), (23712, 4), (23713, 6), (23714, 7)]

TEMPLATE = {"syear": 2026, "sub_institute_id": 1, "availability": 1,
            "show_hide": 1, "created_by": 1}
CLASS8 = {"grade_id": 11, "standard_id": 41}
CLASS10 = {"grade_id": 12, "standard_id": 43}
INSERT = text(
    "INSERT INTO chapter_master (syear, sub_institute_id, grade_id, standard_id, "
    "  subject_id, unit_id, chapter_name, sort_order, availability, show_hide, "
    "  created_by, chapter_desc) "
    "VALUES (:syear, :sub_institute_id, :grade_id, :standard_id, :subject_id, "
    "  :unit_id, :chapter_name, :sort_order, :availability, :show_hide, "
    "  :created_by, '')")

SCI_SUBJECT = 3975
ENG_SUBJECT = 3978
SST_SUBJECT = 4064


def words(s: str) -> set:
    return set(re.findall(r"[a-z][a-z\-]{2,}", (s or "").lower()))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--reorder", action="store_true",
                    help="also renumber sort_order to the book's real order")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        # ---- guard every range before anything is created or moved ----
        plan, refused = [], []

        for name, unit, pos, src, lo, hi, guard in SCIENCE:
            rows = db.execute(text(
                "SELECT id, question_title FROM lms_question_master "
                " WHERE chapter_id=:c AND id BETWEEN :a AND :b ORDER BY id"),
                {"c": src, "a": lo, "b": hi}).fetchall()
            if not rows:
                refused.append(f"{name}: no rows at {lo}-{hi} under {src} "
                               f"(already moved, or the ids changed)")
                continue
            hit = sum(1 for _, t in rows if words(str(t)) & set(guard))
            share = hit / len(rows)
            if share < 0.55:
                refused.append(f"{name}: only {hit}/{len(rows)} rows "
                               f"({share:.0%}) use this chapter's vocabulary")
                continue
            plan.append(("C8 Science", name, SCI_SUBJECT, CLASS8, unit, pos,
                         src, lo, hi, [i for i, _ in rows],
                         f"{hit}/{len(rows)} on-topic"))

        for name, unit, pos, src, lo, hi, guard in SOCIAL:
            rows = db.execute(text(
                "SELECT id, question_title FROM lms_question_master "
                " WHERE chapter_id=:c AND id BETWEEN :a AND :b ORDER BY id"),
                {"c": src, "a": lo, "b": hi}).fetchall()
            if not rows:
                refused.append(f"{name}: no rows at {lo}-{hi} under {src} "
                               f"(already moved, or the ids changed)")
                continue
            hit = sum(1 for _, t in rows if words(str(t)) & set(guard))
            share = hit / len(rows)
            if share < 0.45:
                refused.append(f"{name}: only {hit}/{len(rows)} rows "
                               f"({share:.0%}) use this chapter's vocabulary")
                continue
            plan.append(("C10 Social", name, SST_SUBJECT, CLASS10, unit, pos,
                         src, lo, hi, [i for i, _ in rows],
                         f"{hit}/{len(rows)} on-topic"))

        for poem, unit, pos, src, lo, hi in ENGLISH:
            rows = db.execute(text(
                "SELECT id, question_title FROM lms_question_master "
                " WHERE chapter_id=:c AND id BETWEEN :a AND :b ORDER BY id"),
                {"c": src, "a": lo, "b": hi}).fetchall()
            if not rows:
                refused.append(f"{poem}: no rows at {lo}-{hi} under {src}")
                continue
            drills = [i for i, t in rows if DRILL.search(str(t or ""))]
            if drills:
                refused.append(f"{poem}: {len(drills)} row(s) in range look "
                               f"like grammar drills: {drills[:4]}")
                continue
            # The first row of a poem block names the poem; that is the anchor.
            key = set(words(poem)) - {"the", "and", "out", "for"}
            first = words(str(rows[0][1]))
            if not (key & first):
                refused.append(f"{poem}: first row {rows[0][0]} does not name "
                               f"the poem -- {str(rows[0][1])[:60]}")
                continue
            plan.append(("C8 English", poem, ENG_SUBJECT, CLASS8, unit, pos,
                         src, lo, hi, [i for i, _ in rows],
                         "anchored on its own title"))

        print(f"  {len(plan)} chapter(s) to create, {len(refused)} refused\n")
        moved = 0
        for subj, name, sid, cls, unit, pos, src, lo, hi, ids, why in plan:
            moved += len(ids)
            print(f"   {subj:<11} book #{pos:<3} {name[:34]:<34} "
                  f"{len(ids):>3} questions from {src}  ({why})")
        if refused:
            print("\n  REFUSED:")
            for r in refused:
                print(f"    {r}")
            print("\n  Nothing has been created or moved. Re-read the ranges "
                  "above and correct them before retrying.")
            return 1
        print(f"\n  total questions to re-home: {moved}")

        after = db.execute(text(
            "SELECT COUNT(*) FROM lms_question_master WHERE chapter_id=25838")).scalar()
        print(f"  chapter 25838 'Microorganisms': {after} -> "
              f"{after - sum(len(p[9]) for p in plan if p[0] == 'C8 Science')}")

        if not a.apply:
            print("\n  report only -- re-run with --apply")
            return 0

        created = []
        for subj, name, sid, cls, unit, pos, src, lo, hi, ids, _ in plan:
            row = dict(TEMPLATE, **cls, subject_id=sid, unit_id=unit,
                       chapter_name=name, sort_order=pos)
            db.execute(INSERT, row)
            new_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()
            db.execute(text(
                "UPDATE lms_question_master SET chapter_id=:new "
                " WHERE chapter_id=:old AND id BETWEEN :a AND :b"),
                {"new": new_id, "old": src, "a": lo, "b": hi})
            # The sidecar records the chapter too; keep the two consistent.
            db.execute(text(
                "UPDATE lms_question_outcome SET chapter_id=:new "
                " WHERE question_id IN (SELECT id FROM lms_question_master "
                "                        WHERE chapter_id=:new)"),
                {"new": new_id})
            db.commit()
            created.append((new_id, subj, name, len(ids)))
            print(f"    created {new_id}  {name[:40]:<40} moved {len(ids)}")

        if a.reorder:
            print("\n  renumbering sort_order to the book's order "
                  "(before -> after, to undo):")
            for cid, pos in SCIENCE_ORDER + ENGLISH_ORDER + SOCIAL_ORDER:
                old = db.execute(text(
                    "SELECT sort_order FROM chapter_master WHERE id=:c"),
                    {"c": cid}).scalar()
                if old != pos:
                    db.execute(text(
                        "UPDATE chapter_master SET sort_order=:p WHERE id=:c"),
                        {"p": pos, "c": cid})
                    print(f"    {cid}  {old} -> {pos}")
            db.commit()

        print(f"\n  done. {len(created)} chapters created, "
              f"{sum(c[3] for c in created)} questions re-homed.")
        print("  These chapters have NO curriculum frame yet, so their "
              "questions cannot be CG/LO-mapped until outcomes are attached.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
