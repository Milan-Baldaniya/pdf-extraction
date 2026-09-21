"""Print the questions of a chapter beside the curriculum codes they may cite.

    python -m scripts.question_curriculum_context --chapter 1012
    python -m scripts.question_curriculum_context --chapter 1012 --batch 60 --part 2
    python -m scripts.question_curriculum_context --coverage --standard 43

Sibling of `chapter_context.py`, for the other direction: that one describes a
chapter to somebody about to write items, this one describes items to somebody
about to map them.

Two rules are built in rather than left to the reader.

It never prints the concept's OWN curriculum codes. `lms_concept_outcome` holds
31,743 of them and joining them in would hand over a plausible answer for every
question at once -- which is the chapter's alignment, not the question's, and
every question in the chapter would come back with identical codes. The concept
NAME is printed, because knowing what a question is about helps; the concept's
mapping is deliberately withheld.

It addresses questions by `verbatim_sha256`, not by `question_id`. Ids are
reassigned whenever `write_question_bank(replace=True)` reloads a chapter, and
two of these books are being loaded on another machine right now. The hash
survives a reload, and when a question's text changes the hash changes with it,
so a stale reading is detected instead of being applied to the wrong question.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402
from app.services import curriculum_frame as curf  # noqa: E402
from app.services import question_outcomes as qo  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


_CHAPTER = text(
    "SELECT c.id, c.chapter_name, c.standard_id, c.subject_id, c.sub_institute_id "
    "  FROM chapter_master c WHERE c.id = :c"
)

# LEFT JOIN ... IS NULL is what makes this resumable: the work list shrinks as
# mappings land, so a killed session costs nothing and a re-run never re-reads
# a question that is already mapped.
_QUESTIONS = """
    SELECT q.id, x.verbatim_sha256, x.item_number, x.item_form, q.points,
           q.question_title, q.description, q.answer, q.concept, x.exam_section
      FROM lms_question_master q
      JOIN lms_question_extraction x ON x.question_id = q.id
     WHERE q.chapter_id = :c
       {unmapped}
     ORDER BY x.item_ordinal, q.id
"""

_UNMAPPED = (
    "AND NOT EXISTS (SELECT 1 FROM lms_question_outcome o WHERE o.question_id = q.id)"
)


def _clean(value: object, limit: int = 600) -> str:
    out = " ".join(str(value or "").split())
    return out[:limit] + (" ..." if len(out) > limit else "")


def _answer_parts(raw: object) -> tuple[str, str]:
    """(options, model answer) out of the verbatim payload.

    `lms_question_master.answer` stores the whole verbatim JSON -- hash, marks,
    section, the lot. Printing it raw buries the two fields a mapper actually
    needs under a content_hash, and costs several hundred characters a question
    across thousands of them.
    """
    if not raw:
        return "", ""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return "", _clean(raw, 300)
    opts = payload.get("options") or []
    rendered = ""
    if isinstance(opts, list) and opts:
        rendered = "  ".join(
            f"({o.get('label')}) {_clean(o.get('text'), 70)}"
            if isinstance(o, dict) else f"{_clean(o, 70)}"
            for o in opts
        )
    correct = payload.get("correct_option")
    if correct:
        rendered = f"{rendered}   [correct: {correct}]" if rendered else f"[correct: {correct}]"
    return rendered, _clean(payload.get("model_answer"), 320)


def _print_frame(frame: curf.CurriculumFrame, chapter_id: int) -> bool:
    codes = sorted(frame.codes())
    if not codes:
        print("\nCURRICULUM - NONE RECORDED for this chapter.")
        print("  There is nothing legal to cite. Leave `codes` empty; do not guess.")
        return False
    counts = frame.as_dict()
    print(
        f"\nCURRICULUM - cite these EXACT codes, at most "
        f"{qo.MAX_OUTCOMES_PER_QUESTION} per question."
    )
    print(
        f"  curriculum {frame.curriculum_id} | {counts.get('goals', 0)} goals, "
        f"{counts.get('competencies', 0)} competencies, "
        f"{counts.get('learning_outcomes', 0)} learning outcomes"
    )
    print(frame.prompt_block(limit=80))
    print(f"\n  legal codes: {', '.join(codes)}")
    print(
        "\n  Map the QUESTION, not its chapter. A concept usually serves several\n"
        "  outcomes and one question usually probes ONE of them -- cite that one.\n"
        "  Two questions in this chapter testing different things should come\n"
        "  back with different codes; identical codes throughout means the\n"
        "  chapter was mapped instead of the questions."
    )
    return True


def _coverage(db, standard: int, subject: int | None) -> int:
    """Per chapter: extraction-sourced questions, and how many are mapped.

    Restricted to questions that have a sidecar row, because those are the ones
    this pipeline produced and the only ones addressable by verbatim_sha256.
    The chapters also hold LMS-native questions loaded by other means; they are
    counted separately rather than folded in, so "left to map" stays a number
    somebody can actually work through.
    """
    rows = db.execute(
        text(
            "SELECT q.chapter_id, c.chapter_name, "
            "       COUNT(DISTINCT q.id) AS ours, "
            "       COUNT(DISTINCT qo.question_id) AS mapped "
            "  FROM lms_question_master q "
            "  JOIN lms_question_extraction x ON x.question_id = q.id "
            "  JOIN chapter_master c ON c.id = q.chapter_id "
            "  LEFT JOIN lms_question_outcome qo ON qo.question_id = q.id "
            " WHERE q.standard_id = :s AND (:su IS NULL OR q.subject_id = :su) "
            " GROUP BY q.chapter_id, c.chapter_name "
            " ORDER BY c.chapter_name"
        ),
        {"s": standard, "su": subject},
    ).fetchall()
    if not rows:
        print(f"no extraction-sourced questions for standard {standard}")
        return 1
    others = dict(
        db.execute(
            text(
                "SELECT q.chapter_id, COUNT(*) FROM lms_question_master q "
                " WHERE q.standard_id = :s AND (:su IS NULL OR q.subject_id = :su) "
                "   AND NOT EXISTS (SELECT 1 FROM lms_question_extraction x "
                "                    WHERE x.question_id = q.id) "
                " GROUP BY q.chapter_id"
            ),
            {"s": standard, "su": subject},
        ).fetchall()
    )
    print(f"{'chapter':>8} {'ours':>6} {'mapped':>7} {'left':>6} {'lms-native':>11}  name")
    tot = mapped = native = 0
    for cid, name, ours, done in rows:
        tot += int(ours)
        mapped += int(done)
        nat = int(others.get(cid, 0))
        native += nat
        print(f"{cid:>8} {ours:>6} {done:>7} {ours - done:>6} {nat:>11}  {_clean(name, 40)}")
    print(f"{'TOTAL':>8} {tot:>6} {mapped:>7} {tot - mapped:>6} {native:>11}")
    if native:
        print(f"\n  {native} LMS-native question(s) carry no sidecar row and are "
              f"not in this work list.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chapter", type=int, help="chapter_master.id")
    ap.add_argument("--batch", type=int, default=0, help="questions per part (0 = all)")
    ap.add_argument("--part", type=int, default=1, help="1-based part when --batch is set")
    ap.add_argument("--all-questions", action="store_true",
                    help="include questions already mapped (default: unmapped only)")
    ap.add_argument("--coverage", action="store_true", help="per-chapter mapped counts")
    ap.add_argument("--standard", type=int, default=43)
    ap.add_argument("--subject", type=int)
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        if a.coverage:
            return _coverage(db, a.standard, a.subject)
        if not a.chapter:
            ap.error("give --chapter, or --coverage")

        ch = db.execute(_CHAPTER, {"c": a.chapter}).fetchone()
        if not ch:
            raise SystemExit(f"chapter {a.chapter} not found")
        chapter_id, name, standard_id, subject_id, tenant = ch

        sql = _QUESTIONS.format(unmapped="" if a.all_questions else _UNMAPPED)
        rows = db.execute(text(sql), {"c": chapter_id}).fetchall()

        total = len(rows)
        if a.batch:
            start = (a.part - 1) * a.batch
            rows = rows[start:start + a.batch]
            span = f"part {a.part}, questions {start + 1}-{start + len(rows)} of {total}"
        else:
            span = f"{total} question(s)"

        print(f"chapter {chapter_id} | {name} | standard {standard_id} "
              f"subject {subject_id} | {span}")
        if not a.all_questions:
            print("  (unmapped only -- already-mapped questions are omitted)")

        frame = curf.load_frame(
            db, chapter_id=chapter_id, standard_id=standard_id, subject_id=subject_id
        )
        _print_frame(frame, chapter_id)

        if not rows:
            print("\nNothing left to map in this chapter.")
            return 0

        print("\n" + "=" * 70)
        for qid, sha, num, form, marks, title, desc, answer, concept, section in rows:
            print(f"\nsha {str(sha)[:16]}  q{qid}  item {num}  {form}  {marks} mark(s)"
                  f"{'  | ' + _clean(section, 40) if section else ''}")
            if concept:
                print(f"  concept: {concept}")
            print(f"  Q: {_clean(title, 700)}")
            if desc:
                print(f"  .. {_clean(desc, 700)}")
            options, model = _answer_parts(answer)
            if options:
                print(f"  O: {options}")
            if model:
                print(f"  A: {model}")
        print("\n" + "=" * 70)
        print(f"\nWrite mappings to scripts/curriculum_maps/ch{chapter_id}"
              f"{f'_part{a.part}' if a.batch else ''}.json as:")
        print(json.dumps({
            "chapter_id": chapter_id,
            "mappings": [{"sha": "<first 16 of sha>", "codes": ["<code>"],
                          "note": "why this outcome and not a sibling"}],
        }, indent=1))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
