"""Retire Class 6 Hindi questions that belong to the superseded Vasant book.

    python -m scripts.retire_vasant_contamination            # report only
    python -m scripts.retire_vasant_contamination --apply

The Class 6 Hindi bank was loaded from a source that **mixed two textbooks**.
Our 13 chapter rows are NEP *Malhar*; a number of the loaded questions are
*Vasant*, the book Malhar replaced. A Vasant question served under a Malhar
chapter is wrong for every student who meets it, and Vasant chapters have no
row in the NEP structure, so there is nowhere correct to move it to.

WHAT THIS RETIRES, AND WHAT IT CANNOT SEE. Only questions whose own text names
a Vasant chapter — "'ऐसे-ऐसे' एकांकी के लेखक कौन हैन?", or an extract of that
play's dialogue printed under सत्रिया और बिहू नृत्य. That is a signature match,
so it catches an item that NAMES its chapter and misses one that is merely
about it. A mapping pass over this bank reported roughly 84 misfiled items;
this finds **21**. The difference is not a disagreement — it is the limit of
matching on a title. **The remaining ~60 need reading**, chapter by chapter,
and are deliberately left in place rather than guessed at.

Retirement is `deleted_at`, which is how this estate already marks a question
that should not be served (175 Class 10 Science rows carry one). Nothing is
deleted, the rows stay readable, and the curriculum mappings stay attached —
so this is reversible by clearing the column. Note that
`question_curriculum_context` and `load_question_curriculum` do NOT filter on
`deleted_at`, so a retired question will still be offered for mapping; that is
a separate defect worth fixing in those two scripts.

THE GUARD. Every row is re-read at run time and must still carry a Vasant
signature, and must still sit in one of the 13 Malhar chapters. If the data has
moved, the run stops rather than retiring something on a stale id.
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

CH_LO, CH_HI = 29876, 29888          # the 13 NEP Malhar chapter rows
# Vasant chapter titles. A Malhar question has no reason to print any of them.
SIGNATURES = [
    "झाँसी की रानी",
    "टिकट-अलबम",
    "ऐसे-ऐसे",
    "जो देखकर भी नहीं देखते",
    "मैं सबसे छोटी होऊँ",
    "संसार पुस्तक है",
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        found: dict[int, tuple] = {}
        for sig in SIGNATURES:
            for qid, cid, stem in db.execute(text(
                    "SELECT q.id, q.chapter_id, q.question_title "
                    "  FROM lms_question_master q "
                    " WHERE q.chapter_id BETWEEN :lo AND :hi "
                    "   AND q.deleted_at IS NULL "
                    "   AND (q.question_title LIKE :p "
                    "        OR COALESCE(q.hint_text,'') LIKE :p) "
                    " ORDER BY q.id"),
                    {"lo": CH_LO, "hi": CH_HI, "p": f"%{sig}%"}).fetchall():
                row = found.setdefault(int(qid), (int(cid), set(), str(stem or "")))
                row[1].add(sig)

        if not found:
            print("  nothing to retire -- already done, or the ids have changed")
            return 0

        names = {c: n for c, n in db.execute(text(
            "SELECT id, chapter_name FROM chapter_master "
            " WHERE id BETWEEN :lo AND :hi"),
            {"lo": CH_LO, "hi": CH_HI}).fetchall()}

        print(f"  {len(found)} question(s) name a Vasant chapter\n")
        by_ch: dict[int, list] = {}
        for qid, (cid, sigs, _) in sorted(found.items()):
            by_ch.setdefault(cid, []).append(qid)
        for cid, qs in sorted(by_ch.items()):
            before = db.execute(text(
                "SELECT COUNT(*) FROM lms_question_master "
                " WHERE chapter_id=:c AND deleted_at IS NULL"), {"c": cid}).scalar()
            print(f"   ch{cid} {str(names.get(cid))[:34]:<34} "
                  f"{len(qs):>3} of {before} retire")
        print("\n  each one, with the Vasant chapter it names:")
        for qid, (cid, sigs, stem) in sorted(found.items()):
            print(f"   {qid}  ch{cid}  [{'; '.join(sorted(sigs))[:30]}]  "
                  f"{' '.join(stem.split())[:68]}")

        mapped = db.execute(text(
            "SELECT COUNT(DISTINCT question_id) FROM lms_question_outcome "
            " WHERE question_id IN :ids"), {"ids": tuple(found)}).scalar()
        print(f"\n  {mapped} of these carry curriculum mappings, which STAY "
              f"attached\n  (retirement is reversible; clearing deleted_at "
              f"restores them intact)")

        if not a.apply:
            print("\n  report only -- re-run with --apply")
            return 0

        db.execute(text(
            "UPDATE lms_question_master SET deleted_at = NOW() "
            " WHERE id IN :ids AND deleted_at IS NULL"), {"ids": tuple(found)})
        db.commit()
        still = db.execute(text(
            "SELECT COUNT(*) FROM lms_question_master "
            " WHERE id IN :ids AND deleted_at IS NULL"), {"ids": tuple(found)}).scalar()
        live = db.execute(text(
            "SELECT COUNT(*) FROM lms_question_master "
            " WHERE chapter_id BETWEEN :lo AND :hi AND deleted_at IS NULL"),
            {"lo": CH_LO, "hi": CH_HI}).scalar()
        print(f"\n  retired {len(found) - still}; Class 6 Hindi now holds {live} live")
        print("  ~60 further misfiled items were reported by a reading pass and "
              "are NOT\n  covered by a title match. They need reading, not a script.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
