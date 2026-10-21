"""Move Class 8 Science questions to the chapter their own label names.

    python -m scripts.refile_class8_science
    python -m scripts.refile_class8_science --apply

UPDATE only: one column, `lms_question_master.chapter_id`. Nothing is inserted
and nothing is deleted.

WHAT WENT WRONG. Chapter 2 (Microorganisms) holds 966 questions where every
other Class 8 Science chapter holds 70-88 -- half the subject in one chapter.
All 966 stems are distinct, so it is not duplication, and for a while it looked
like genuine depth.

It is a chapter-mapping failure. The rows carry their source label in
`description`, and the labels name eighteen different chapters:

    Euro_CBSE-8_Science_13_Sound                    60 rows
    Euro_CBSE-8_Science_12_Friction                 59 rows
    Euro_CBSE-8_Science_16_Light                    56 rows

The loader could not match those names to a chapter and fell back to a single
id rather than failing, so ten chapters' worth of questions piled onto one. The
label is intact, so the damage is completely reversible.

WHY THE NAMES DID NOT MATCH. The source is the eighteen-chapter
pre-rationalisation book; `chapter_master` holds the rationalised thirteen. Five
of the eighteen have no chapter to go to at all -- Stars and the Solar System,
Pollution of Air and Water, Synthetic Fibres and Plastics, Materials: Metals and
Non-metals, and Cell: Structure and Function. Those 269 rows are left where they
are and reported, because inventing a chapter for them is a separate decision.

Matching is on a normalised key and then on a 14-character prefix, because the
labels differ from the chapter names by punctuation and by a singular:
"Microorganisms- Friend and Foe" against "Microorganisms: Friend and Foe",
"Some natural phenomenon" against "Some Natural Phenomena".
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

STANDARD, SUBJECT = 41, 3975
LABEL = re.compile(r"Euro_CBSE-8_Science_(\d+)_(.+)$")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write; without it, report only")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        chapters = db.execute(
            text("SELECT id, sort_order, chapter_name FROM chapter_master "
                 " WHERE standard_id = :s AND subject_id = :j"),
            {"s": STANDARD, "j": SUBJECT},
        ).fetchall()
        by_name = {norm(c[2]): (int(c[0]), int(c[1])) for c in chapters}

        dump = db.execute(
            text("SELECT id FROM chapter_master WHERE standard_id = :s "
                 "   AND subject_id = :j AND sort_order = 2"),
            {"s": STANDARD, "j": SUBJECT},
        ).scalar()

        rows = db.execute(
            text("SELECT description, COUNT(*) FROM lms_question_master "
                 " WHERE chapter_id = :c GROUP BY description ORDER BY 2 DESC"),
            {"c": dump},
        ).fetchall()

        moves: list[tuple[str, int, int, int]] = []
        stay: list[tuple[str, int, str]] = []
        for desc, n in rows:
            m = LABEL.match(desc or "")
            if not m:
                stay.append((desc or "", int(n), "label not in the expected form"))
                continue
            key = norm(m.group(2))
            hit = by_name.get(key)
            if not hit:
                near = [v for k, v in by_name.items()
                        if k.startswith(key[:14]) or key.startswith(k[:14])]
                hit = near[0] if len(near) == 1 else None
            if not hit:
                stay.append((desc or "", int(n), "chapter removed by rationalisation"))
            elif hit[0] == dump:
                stay.append((desc or "", int(n), "already on the right chapter"))
            else:
                moves.append((desc or "", int(n), hit[0], hit[1]))

        # These rows are LMS-native and unmapped, but check rather than assume:
        # moving a question whose outcome rows name the old chapter would leave
        # lms_question_outcome.chapter_id disagreeing with the question.
        mapped = db.execute(
            text("SELECT COUNT(*) FROM lms_question_outcome o "
                 "  JOIN lms_question_master q ON q.id = o.question_id "
                 " WHERE q.chapter_id = :c"),
            {"c": dump},
        ).scalar()

        print(f"chapter {dump} (Class 8 Science ch2) holds "
              f"{sum(n for _, n, _, _ in moves) + sum(n for _, n, _ in stay)} questions\n")
        print(f"{'MOVE':<48} {'rows':>5}  destination")
        print("-" * 82)
        for desc, n, cid, so in moves:
            print(f"{desc[:48]:<48} {n:>5}  chapter_id {cid} (ch{so})")
        print(f"\n{'STAY':<48} {'rows':>5}  reason")
        print("-" * 82)
        for desc, n, why in stay:
            print(f"{desc[:48]:<48} {n:>5}  {why}")

        total = sum(n for _, n, _, _ in moves)
        print(f"\n{total} row(s) would move, {sum(n for _, n, _ in stay)} stay.")
        if mapped:
            print(f"WARNING: {mapped} of these questions carry curriculum outcome "
                  f"rows; those name the old chapter and would need re-mapping.")

        if a.apply:
            for desc, n, cid, _ in moves:
                db.execute(
                    text("UPDATE lms_question_master SET chapter_id = :new "
                         " WHERE chapter_id = :old AND description = :d"),
                    {"new": cid, "old": dump, "d": desc},
                )
            db.commit()
            print(f"\napplied: {total} question(s) refiled")
        else:
            print("\nDRY RUN - nothing written. Re-run with --apply.")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
