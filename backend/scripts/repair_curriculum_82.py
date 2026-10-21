"""Repair the learning outcomes of curriculum 82 (Class 9 Science).

    python -m scripts.repair_curriculum_82
    python -m scripts.repair_curriculum_82 --apply

UPDATE only. Nothing is inserted and nothing is deleted, so no code changes and
the 3,314 question citations and 4,502 concept citations already pointing at
this curriculum keep pointing at the same rows. Only the TEXT those rows show,
and in a few cases the chapter they hang under, is corrected.

WHAT WAS WRONG

`lms_curriculum` 82 was imported from extraction 52, a PDF whose syllabus is
set as a two-column table: a "Key Concepts" cell beside a "Learning Outcomes"
cell holding a run-together list. The text layer reads that table cell by cell,
and a cell's text WRAPS INTO THE NEXT ROW'S CELL. The importer then split each
cell into one outcome row per sentence.

So a sentence that straddled a cell boundary produced two rows: a truncated one
and an orphan holding its tail. C-3.1's last outcome reads "Demonstrate osmosis
in" and C-3.2's cell begins "cells". C-4.2-LO-4 reads "Describe the level of
organisation in a multicellular" and LO-2, the very next row, is the single word
"organism". C-2.1-LO-4 ends "using kinematic" and LO-58 is "equations".

Worse, where the PDF wrapped a cell across the page's two columns the words
INTERLEAVE rather than merely split: LO-32 reads "Display awareness ancient
Indian of indivisible about the contributions of the philosopher, Acharya
Kanad's idea particles (Parmanu)". Every word of the real outcome is present,
in the wrong order.

WHAT IS AND IS NOT REPAIRED HERE

Repaired: rows whose correct text is EVIDENCED -- either the continuation sits
in the adjacent row or cell, or every word is present and only the order is
wrong. Each one below carries the evidence that justifies it.

NOT repaired, deliberately:

  * Rows where words are genuinely ABSENT from the source, not merely displaced
    -- C-1.2-LO-4 "Explain the scientific principles behind different", LO-28's
    atomic-models fragment, C-1.1-LO-6 "Use scientific conventions as per
    international". Inventing the missing words would be indistinguishable from
    a correct repair when read back, which is the worst possible outcome for a
    row 3,000 citations depend on.

  * The eight FUSED rows (C-2.1-LO-1 carries four outcomes, C-2.5-LO-5 three).
    Nothing is lost there -- the text is complete, it is the row boundary that
    is wrong. Splitting them would mint new codes, and the 344 question
    citations already on the fused codes would be left describing only the
    first of the outcomes they were mapped to. That is a re-mapping decision,
    not a text repair.

  * LO-43, "Draw diagrams of electron dot structures of atoms and molecules",
    filed under C5.1 "Explores how literature and arts have influenced Science".
    The SOURCE document files it there too, so this is a defect in the syllabus
    as published, not in the import. It has no citations. Moving it would make
    the database disagree with the document it came from.
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

CURRICULUM = 82

# (row id, expected current text prefix, corrected text, evidence)
#
# The prefix is checked before writing. If a row no longer starts with what was
# read when this was written, it has been edited by somebody else and the repair
# is skipped rather than applied over their change.
REPAIRS: tuple[tuple[int, str, str, str], ...] = (
    (913, "Demonstrate osmosis in",
     "Demonstrate osmosis in cells",
     "C-3.1's cell ends 'Demonstrate osmosis in'; the next cell, C-3.2's, "
     "begins 'cells Prepare slides to observe cell structure'."),

    (928, "Describe the level of organisation in a multicellular",
     "Describe the level of organisation in a multicellular organism",
     "LO-2, the next row, is the single word 'organism'."),
    (929, "organism",
     "Describe the level of organisation in a multicellular organism",
     "This row IS the orphan tail of C-4.2-LO-4. It cannot be deleted, so it "
     "is given the whole sentence it is the end of."),

    (967, "Display awareness about the societal impact of",
     "Display awareness about the societal impact of chemistry in making life "
     "healthier, cleaner and sustainable",
     "LO-18 holds the continuation: 'chemistry in making life healthier, "
     "cleaner and sustainable'."),
    (969, "Display awareness about the societal impact of",
     "Display awareness about the societal impact of chemistry in making life "
     "healthier, cleaner and sustainable",
     "Same truncation as C-5.1-LO-2; same continuation in LO-18."),
    (970, "chemistry in making life healthier",
     "Display awareness about the societal impact of chemistry in making life "
     "healthier, cleaner and sustainable",
     "Orphan tail of the two rows above."),

    (975, "Display",
     "Display awareness about the contributions of Indian scientists, such as "
     "Dilip Mahalanabis",
     "LO-21, three rows earlier, holds 'awareness about the contributions of "
     "Indian scientists, such as Dilip Mahalanabis'."),
    (973, "awareness about the contributions of Indian scientists",
     "Display awareness about the contributions of Indian scientists, such as "
     "Dilip Mahalanabis",
     "Orphan tail of C-7.1-LO-3, which is the bare word 'Display'."),

    (991, "such Bohr's model of 'Journey about Create and present",
     "Create and present a role play, stage play, or story such as 'Journey "
     "Inside the Atom' to display awareness about the contributions of key "
     "scientists in the discovery and development of atomic structure",
     "Two-column interleave. Every word is present in the source cell; only "
     "the order is wrong."),

    (992, "Display for peaceful influenced",
     "Display awareness about the role of Indian scientists and their "
     "contributions to atomic science for peaceful purposes and explore how "
     "their works influenced India's scientific development",
     "Orphan fragment ('for peaceful', 'influenced') of the outcome in LO-31."),
    (993, "Display awareness about the role of Indian scientists",
     "Display awareness about the role of Indian scientists and their "
     "contributions to atomic science for peaceful purposes and explore how "
     "their works influenced India's scientific development",
     "Two-column interleave: 'purposes' and 'India's scientific development' "
     "had been carried past the words they follow."),

    (994, "Display awareness ancient Indian of indivisible",
     "Display awareness about the contributions of the ancient Indian "
     "philosopher Acharya Kanad and his idea of indivisible particles "
     "(Parmanu)",
     "Two-column interleave. The trailing fragment 'of the atomic mass unit "
     "(u) to' belongs to a different outcome and is dropped rather than left "
     "making this row false."),
    (995, "Display awareness ancient Indian of indivisible",
     "Display awareness about the contributions of the ancient Indian "
     "philosopher Acharya Kanad and his idea of indivisible particles "
     "(Parmanu)",
     "Byte-identical duplicate of LO-32, damaged the same way."),

    (997, "Pose question, completely inside an atom?",
     "Pose question, such as - is it possible to understand everything that "
     "happens completely inside an atom?",
     "Two-column interleave; every word present in the source cell."),

    (1018, "Communicate findings and conclusions effectively",
     "Communicate findings and conclusions effectively, such as those from "
     "experiments, activities, or projects, both orally and in written form",
     "Cut at the cell boundary. The same outcome appears in full in the "
     "tissues chapter's C-8.2 cell, ending 'both orally and in written form'."),

    (1029, "Calculate values of unknown physical quantities",
     "Calculate values of unknown physical quantities from the given physical "
     "quantities, using kinematic equations",
     "LO-58, the next row, is the single word 'equations'."),
    (1030, "equations",
     "Calculate values of unknown physical quantities from the given physical "
     "quantities, using kinematic equations",
     "This row IS the orphan tail of C-2.1-LO-4."),

    (1031, "Derive the expression of speed for uniform circular",
     "Derive the expression of speed for uniform circular motion",
     "Two outcomes interleaved. 'real-life events and phenomena, and' belongs "
     "to the Analyse outcome that LO-59 continues; what remains is this one."),
    (1032, "identify the key factors that influence their",
     "Analyse real-life events and phenomena, and identify the key factors "
     "that influence their behaviour",
     "The force chapter's C-8.1 cell carries this outcome complete, which is "
     "where the wording comes from."),

    (1066, "Describe the characteristics of sound waves the",
     "Describe the characteristics of sound waves (wavelength, frequency, "
     "time period, amplitude)",
     "The stray 'the' after 'sound waves' is a wrap artefact. The source cell "
     "itself ends mid-word at 'amplitude, a', so the final term is lost in the "
     "DOCUMENT; the list is closed rather than guessed at."),

    (1071, "Analyse real-life events and phenomena, and of",
     "Analyse real-life events and phenomena, and identify the key factors "
     "that influence their behaviour",
     "The next cell begins 'identify the key factors that influence their "
     "behaviour'; the stray 'of' is a wrap artefact."),

    (1074, "Formulate hypotheses about scientific phenomena based on prior "
           "knowledge and understanding of",
     "Formulate hypotheses about scientific phenomena based on prior knowledge "
     "and understanding of scientific concepts, theories, laws, and principles",
     "The source document ends here, so there is no continuation cell. The "
     "same outcome appears complete in the work-and-energy chapter's C-8.2 "
     "cell, which supplies the wording."),
)


def _chapter_repairs(db) -> list[tuple[int, str, int, str]]:
    """Outcomes stranded at chapter_id 0 whose chapter the neighbours settle.

    The importer wrote rows in document order, so a chapter-0 row sitting
    between two rows of the SAME chapter came from that chapter's table. Where
    the neighbours disagree the row is left alone and reported -- a guess about
    which chapter an outcome belongs to changes which frame may cite it.
    """
    rows = db.execute(
        text("SELECT id, code, chapter_id FROM lms_learning_outcomes "
             " WHERE curriculum_id = :c AND type = 'learning_outcome' "
             " ORDER BY id"),
        {"c": CURRICULUM},
    ).fetchall()
    out: list[tuple[int, str, int, str]] = []
    for i, (rid, code, chapter) in enumerate(rows):
        if chapter:
            continue
        before = next((r[2] for r in reversed(rows[:i]) if r[2]), None)
        after = next((r[2] for r in rows[i + 1:] if r[2]), None)
        if before and before == after:
            out.append((int(rid), code, int(before),
                        f"rows either side of it in import order are chapter "
                        f"{before}"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write the repairs; without it this only reports")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        print(f"curriculum {CURRICULUM}: {len(REPAIRS)} text repair(s)\n")
        applied = skipped = 0
        for rid, prefix, fixed, why in REPAIRS:
            row = db.execute(
                text("SELECT code, description FROM lms_learning_outcomes "
                     " WHERE id = :i AND curriculum_id = :c"),
                {"i": rid, "c": CURRICULUM},
            ).fetchone()
            if not row:
                print(f"  row {rid}: NOT FOUND, skipped")
                skipped += 1
                continue
            code, current = row[0], (row[1] or "").strip()
            if current == fixed:
                print(f"  row {rid:<5} {code:<14} already repaired")
                continue
            if not current.startswith(prefix):
                print(f"  row {rid:<5} {code:<14} SKIPPED - text has changed "
                      f"since this repair was written")
                print(f"        expected to start {prefix[:60]!r}")
                print(f"        found            {current[:60]!r}")
                skipped += 1
                continue
            n = db.execute(
                text("SELECT COUNT(*) FROM lms_question_outcome "
                     " WHERE outcome_code = :c AND curriculum_id = :u"),
                {"c": code, "u": CURRICULUM},
            ).scalar()
            print(f"  row {rid:<5} {code:<14} {n:>3} question citation(s)")
            print(f"        was  {current[:110]!r}")
            print(f"        now  {fixed[:110]!r}")
            print(f"        why  {why}")
            if a.apply:
                db.execute(
                    text("UPDATE lms_learning_outcomes SET description = :d "
                         " WHERE id = :i AND curriculum_id = :c"),
                    {"d": fixed, "i": rid, "c": CURRICULUM},
                )
            applied += 1

        chapters = _chapter_repairs(db)
        stranded = db.execute(
            text("SELECT COUNT(*) FROM lms_learning_outcomes "
                 " WHERE curriculum_id = :c AND type = 'learning_outcome' "
                 "   AND (chapter_id IS NULL OR chapter_id = 0)"),
            {"c": CURRICULUM},
        ).scalar()
        print(f"\n{stranded} outcome(s) stranded at chapter 0; "
              f"{len(chapters)} settled by their neighbours\n")
        for rid, code, chapter, why in chapters:
            print(f"  row {rid:<5} {code:<14} chapter 0 -> {chapter}   ({why})")
            if a.apply:
                db.execute(
                    text("UPDATE lms_learning_outcomes SET chapter_id = :ch "
                         " WHERE id = :i AND curriculum_id = :c"),
                    {"ch": chapter, "i": rid, "c": CURRICULUM},
                )

        if a.apply:
            db.commit()
            print(f"\napplied {applied} text repair(s) and "
                  f"{len(chapters)} chapter repair(s)"
                  + (f"; {skipped} skipped" if skipped else ""))
        else:
            print(f"\nDRY RUN - nothing written. {applied} text repair(s) and "
                  f"{len(chapters)} chapter repair(s) would be made"
                  + (f"; {skipped} skipped" if skipped else "")
                  + ".\nRe-run with --apply.")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
