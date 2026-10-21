"""Move the 1857-revolt questions out of Class 8 Geography's "Resources".

    python -m scripts.refile_c8_1857_questions            # report only
    python -m scripts.refile_c8_1857_questions --apply    # UPDATE

Chapter 25879 is `Social Sciences` chapter 1, "Resources" -- Geography. It
holds 76 questions, and 34 of them are about the 1857 revolt: the annexation
of Jhansi, Bahadur Shah Zafar, Nana Saheb's general, the sepoys who refused to
sail to Burma. Meanwhile `Social Sciences-3` chapter 5, "When People Rebel:
1857 and After" (chapter 25896), holds NONE.

This is pre-existing LMS-native data, not something a loader here put there.
It matters because a question served under "Resources" that asks who ordered
the annexation of Jhansi is wrong for every student who meets it, and because
a chapter reported as empty is not empty -- its questions are filed elsewhere.

THE SPLIT IS BY CONTIGUOUS ID BLOCK, which is what makes it safe to act on:

    110089 - 110130   42 questions, all on resources
    110568 - 110601   34 questions, all on the revolt

Every one of the 34 was read before this script was written; none is
ambiguous, and none of the 42 mentions the colonial period. The move is an
UPDATE of `chapter_id`. Nothing is inserted and nothing is deleted, so it is
reversible by running the same UPDATE in reverse.

`lms_question_extraction.concept_id` is left alone deliberately: these rows
have no sidecar (they are LMS-native), so there is nothing to correct there.
Any curriculum mapping already written against them stays attached, because
`lms_question_outcome` keys on question_id and the question is not moving id.
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

FROM_CHAPTER = 25879          # Social Sciences ch1, Resources
TO_CHAPTER = 25896            # Social Sciences-3 ch5, When People Rebel
ID_LO, ID_HI = 110568, 110601

# Read back over the block as a guard: if the data has changed since this was
# written, a question that is not about the revolt will fail this and the run
# stops rather than moving it.
REVOLT = re.compile(r"(?i)1857|revolt|sepoy|nawab|peshwa|zafar|nana saheb|jhansi|"
                    r"zamindar|company|annex|begum|bahadur|viceroy|subsidiary alliance|"
                    r"christianity|dalhousie|barrackpore|awadh|mughal|british|burma|"
                    r"kanpur|subedar|colonial|rajas|"
                    # Added after the guard refused two: "disobeying of soldier
                    # groups against officers of the Army" is the definition of
                    # mutiny, and "led a group of soldiers from Bareilly to
                    # Delhi" is Bakht Khan. Both are revolt content; neither
                    # names the revolt, because the revolt is the answer.
                    r"mutiny|soldier|army|bareilly|delhi|lucknow|meerut")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        src = db.execute(text(
            "SELECT c.chapter_name, s.subject_name FROM chapter_master c "
            "  JOIN subject s ON s.id=c.subject_id WHERE c.id=:c"),
            {"c": FROM_CHAPTER}).fetchone()
        dst = db.execute(text(
            "SELECT c.chapter_name, s.subject_name FROM chapter_master c "
            "  JOIN subject s ON s.id=c.subject_id WHERE c.id=:c"),
            {"c": TO_CHAPTER}).fetchone()
        print(f"  from  {FROM_CHAPTER}  {src[1]} / {src[0]}")
        print(f"  to    {TO_CHAPTER}  {dst[1]} / {dst[0]}\n")

        rows = db.execute(text(
            "SELECT id, question_title FROM lms_question_master "
            " WHERE chapter_id=:c AND id BETWEEN :lo AND :hi ORDER BY id"),
            {"c": FROM_CHAPTER, "lo": ID_LO, "hi": ID_HI}).fetchall()
        if not rows:
            print("  nothing to move -- already done, or the ids have changed")
            return 0

        odd = [(i, t) for i, t in rows if not REVOLT.search(str(t or ""))]
        print(f"  {len(rows)} questions in the block, {len(odd)} of which do NOT "
              f"read as 1857-revolt content")
        for i, t in odd:
            print(f"      {i}  {str(t)[:86]}")
        if odd:
            print("\n  REFUSING to move: every question in the block must be revolt\n"
                  "  content. Re-read these and narrow the id range before retrying.")
            return 1

        before_src = db.execute(text(
            "SELECT COUNT(*) FROM lms_question_master WHERE chapter_id=:c"),
            {"c": FROM_CHAPTER}).scalar()
        before_dst = db.execute(text(
            "SELECT COUNT(*) FROM lms_question_master WHERE chapter_id=:c"),
            {"c": TO_CHAPTER}).scalar()
        print(f"\n  before:  Resources {before_src}, When People Rebel {before_dst}")
        print(f"  after :  Resources {before_src - len(rows)}, "
              f"When People Rebel {before_dst + len(rows)}")

        if not a.apply:
            print("\n  report only -- re-run with --apply")
            return 0

        db.execute(text(
            "UPDATE lms_question_master SET chapter_id=:to "
            " WHERE chapter_id=:frm AND id BETWEEN :lo AND :hi"),
            {"to": TO_CHAPTER, "frm": FROM_CHAPTER, "lo": ID_LO, "hi": ID_HI})
        db.commit()
        a_src = db.execute(text(
            "SELECT COUNT(*) FROM lms_question_master WHERE chapter_id=:c"),
            {"c": FROM_CHAPTER}).scalar()
        a_dst = db.execute(text(
            "SELECT COUNT(*) FROM lms_question_master WHERE chapter_id=:c"),
            {"c": TO_CHAPTER}).scalar()
        print(f"\n  moved {len(rows)}.  Resources {a_src}, When People Rebel {a_dst}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
