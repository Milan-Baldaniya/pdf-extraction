"""Put the model answer back on questions that already have one, unreachably.

    python -m scripts.recover_answers_from_payload            # report only
    python -m scripts.recover_answers_from_payload --apply
    python -m scripts.recover_answers_from_payload --standard 43 --apply

**12,388 of 29,236 live Class 6-10 questions (42.4%) have no answer** -- no
option marked correct and no `hint_text`. A question that cannot be marked
cannot be served for homework, practice or board preparation, which is the
whole purpose of the bank, so this is larger than every other defect found so
far put together.

Almost all of it is recoverable, because the answer was read and stored and
then simply never written anywhere a reader looks:

    12,331  are subjective (very short / short / long / case study), so no
            "correct option" was ever expected of them
    11,495  have their model answer sitting in
            `lms_question_extraction.verbatim_payload` as `answer_text`
         5  have a payload with no answer in it
       888  are LMS-native with no payload at all -- genuinely unrecoverable
            from what we hold, and the only part of this that needs sourcing
        57  are MCQs with options but no key marked, which is a different
            defect and is NOT touched here

WHY `hint_text` AND NOT `answer`. `lms_question_master.answer` is not the
answer: `write_question_bank` uses it for a provenance blob
(`{"v": "qbank-1.0", "content_hash": ...}`), and overwriting it would destroy
the record of where a question came from. `hint_text` already holds the model
answer for 3,710 rows -- the whole `10SCIENCE6qa` family stores it there -- so
this follows the convention the bank already uses rather than inventing one.

SAFE TO RE-RUN. The UPDATE carries its own `hint_text IS NULL OR hint_text=''`
guard, so a row that has gained an answer since the last run is never
overwritten, and a second run writes nothing. No row is deleted, no question id
changes, and nothing outside `hint_text` is touched.

Soft-deleted rows are excluded. 175 Class 10 Science questions carry a
`deleted_at`, and `question_curriculum_context` and `load_question_curriculum`
both ignore that column -- worth fixing in those two, separately.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

WS = re.compile(r"\s+")
# Some payloads open with a stray year or a control byte before the answer.
JUNK = re.compile(r"^[\s\u0001​]*(?:20\d\d)?[\s\u0001​]*")

SELECT = """
SELECT q.id, c.standard_id, COALESCE(s.subject_name,'?') subj,
       e.item_form, e.verbatim_payload
  FROM lms_question_master q
  JOIN chapter_master c ON c.id = q.chapter_id
  LEFT JOIN subject s ON s.id = c.subject_id
  JOIN lms_question_extraction e ON e.question_id = q.id
  LEFT JOIN (SELECT question_id, MAX(correct_answer) ok
               FROM answer_master GROUP BY question_id) k
         ON k.question_id = q.id
 WHERE q.deleted_at IS NULL
   AND COALESCE(k.ok, 0) = 0
   AND (q.hint_text IS NULL OR q.hint_text = '')
   AND e.verbatim_payload IS NOT NULL
"""

UPDATE = text(
    "UPDATE lms_question_master SET hint_text = :ans "
    " WHERE id = :id AND (hint_text IS NULL OR hint_text = '')")


def answer_of(payload: str) -> str | None:
    """The model answer held in a payload, or None."""
    try:
        d = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(d, dict):
        return None
    for key in ("answer_text", "answer", "solution", "explanation"):
        v = d.get(key)
        if isinstance(v, str):
            a = WS.sub(" ", JUNK.sub("", v)).strip()
            if len(a) >= 2:
                return a
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--standard", type=int, choices=[39, 40, 41, 42, 43])
    ap.add_argument("--batch", type=int, default=500)
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        sql = SELECT + ("   AND c.standard_id = :s" if a.standard
                        else "   AND c.standard_id BETWEEN 39 AND 43")
        rows = db.execute(text(sql),
                          {"s": a.standard} if a.standard else {}).fetchall()
        print(f"  {len(rows)} answerless questions carrying a payload")

        width = db.execute(text(
            "SELECT CHARACTER_MAXIMUM_LENGTH FROM information_schema.COLUMNS "
            " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME='lms_question_master' "
            "   AND COLUMN_NAME='hint_text'")).scalar()
        print(f"  hint_text holds up to {width} characters")

        payload, empty, clamped = [], 0, 0
        per: dict[tuple, int] = {}
        for qid, std, subj, form, pay in rows:
            ans = answer_of(str(pay))
            if not ans:
                empty += 1
                continue
            if width and len(ans) > int(width):
                ans = ans[:int(width)]
                clamped += 1
            payload.append({"id": int(qid), "ans": ans})
            per[(std, subj)] = per.get((std, subj), 0) + 1

        print(f"  recoverable: {len(payload)}     no answer in payload: {empty}"
              + (f"     clamped to fit: {clamped}" if clamped else ""))
        print(f"\n  {'group':<34} {'answers recovered':>18}")
        for (std, subj), n in sorted(per.items(), key=lambda kv: -kv[1]):
            print(f"  std{std} {str(subj)[:28]:<28} {n:>18}")

        live = db.execute(text(
            "SELECT COUNT(*) FROM lms_question_master q "
            "  JOIN chapter_master c ON c.id=q.chapter_id "
            " WHERE c.standard_id BETWEEN 39 AND 43 AND q.deleted_at IS NULL")).scalar()
        has = db.execute(text(
            "SELECT COUNT(*) FROM lms_question_master q "
            "  JOIN chapter_master c ON c.id=q.chapter_id "
            "  LEFT JOIN (SELECT question_id, MAX(correct_answer) ok FROM answer_master "
            "              GROUP BY question_id) k ON k.question_id=q.id "
            " WHERE c.standard_id BETWEEN 39 AND 43 AND q.deleted_at IS NULL "
            "   AND (COALESCE(k.ok,0)=1 OR (q.hint_text IS NOT NULL AND q.hint_text<>''))"
        )).scalar()
        print(f"\n  answer coverage {has}/{live} ({has * 100.0 / live:.1f}%) "
              f"-> {has + len(payload)}/{live} "
              f"({(has + len(payload)) * 100.0 / live:.1f}%)")

        print("\n  three samples, as they would be written:")
        for p in payload[:3]:
            print(f"    qid {p['id']}: {p['ans'][:150]}")

        if not a.apply:
            print("\n  report only -- re-run with --apply")
            return 0

        done = 0
        for i in range(0, len(payload), a.batch):
            db.execute(UPDATE, payload[i:i + a.batch])
            db.commit()
            done += len(payload[i:i + a.batch])
            print(f"    {done}/{len(payload)}", end="\r", flush=True)
        after = db.execute(text(
            "SELECT COUNT(*) FROM lms_question_master q "
            "  JOIN chapter_master c ON c.id=q.chapter_id "
            "  LEFT JOIN (SELECT question_id, MAX(correct_answer) ok FROM answer_master "
            "              GROUP BY question_id) k ON k.question_id=q.id "
            " WHERE c.standard_id BETWEEN 39 AND 43 AND q.deleted_at IS NULL "
            "   AND (COALESCE(k.ok,0)=1 OR (q.hint_text IS NOT NULL AND q.hint_text<>''))"
        )).scalar()
        print(f"\n  done. answer coverage {has} -> {after} of {live} "
              f"({after * 100.0 / live:.1f}%)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
