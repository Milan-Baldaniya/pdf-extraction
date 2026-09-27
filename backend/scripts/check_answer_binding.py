"""Find questions whose stored answer belongs to a different question.

    python -m scripts.check_answer_binding
    python -m scripts.check_answer_binding --chapter 25967 --verbose

Read-only. Nothing is written; this only reports.

Several pdf.tube books **ship their pages out of reading order** — odd and even
folios interleave, so pdf pages 178/180/182 carry folios 154/152/150. A parser
that walks the file in page order then binds the answer opening one page to the
question closing the previous one, and both rows load clean: the stem is real,
the answer is real, the validators pass, and only the pairing is wrong.

Measured folio inversions per book (a page's printed folio lower than the one
before it):

    c7_Social_Science   76 of 248   30.8%   loaded
    c8_Social_Science   13 of 119   11.0%   loaded
    c8_English          15 of 308    4.9%   loaded
    c6_Science           0           0.0%   loaded after a reading-order fix
    c7_Science           0           0.0%   control

HOW THE CHECK WORKS. An answer explains its own question, so it reuses that
question's words. This scores the vocabulary overlap between each stem and its
stored answer, then reports the share of rows in a chapter that share almost
nothing. A clean book sets the floor; a book above that floor by a wide margin
is losing pairings somewhere.

This is a MEASURE, not a verdict on any single row. A one-word answer ("Delhi")
legitimately shares no vocabulary with its stem, which is why the number only
means something compared against a control book parsed the same way.
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

WORD = re.compile(r"[a-zऀ-ॿ][a-zऀ-ॿ\-]{2,}")
STOP = set("""the and for not but with from that this these those which what when who how
why its are was were has have had can will would should could one two his her they them
their there then than out into over under more most other some any all each both been
being does did doing you your our we us it he she him""".split())
# books to compare, by (standard, subject name fragment)
BOOKS = [("c7 Social Sciences  (shuffled 30.8%)", 40, "Social Science%"),
         ("c8 Social Sciences  (shuffled 11.0%)", 41, "Social Science%"),
         ("c8 English          (shuffled 4.9%)", 41, "English"),
         ("c6 Social Sciences  [control, clean]", 39, "Social Science%"),
         ("c6 Science  [control, reordered]", 39, "Science"),
         ("c7 Science  [control, clean]", 40, "Science"),
         ("c9 Science  [control, clean]", 42, "Science")]


def words(s: str) -> set:
    return {w for w in WORD.findall((s or "").lower()) if w not in STOP}


def answer_text(raw: str | None, hint: str | None) -> str:
    """The model answer, from whichever column holds it."""
    if hint and hint.strip():
        return hint
    if not raw:
        return ""
    try:
        d = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    if isinstance(d, dict):
        for k in ("model_answer", "answer_text", "answer", "solution"):
            v = d.get(k)
            if isinstance(v, str) and v.strip():
                return v
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chapter", type=int)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--limit", type=int, default=8)
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        sel = ("SELECT q.id, q.question_title, q.answer, q.hint_text, c.chapter_name "
               "  FROM lms_question_master q "
               "  JOIN chapter_master c ON c.id = q.chapter_id "
               "  LEFT JOIN subject s ON s.id = c.subject_id "
               " WHERE q.deleted_at IS NULL ")
        groups = ([(f"chapter {a.chapter}", sel + "AND c.id = :cid", {"cid": a.chapter})]
                  if a.chapter else
                  [(lbl, sel + "AND c.standard_id = :std AND s.subject_name LIKE :sub",
                    {"std": std, "sub": sub}) for lbl, std, sub in BOOKS])

        print(f"  {'book':<36} {'rows':>6} {'scored':>7} {'unrelated':>10}   rate")
        worst = []
        for lbl, sql, params in groups:
            rows = db.execute(text(sql), params).fetchall()
            scored = bad = 0
            examples = []
            for qid, stem, raw, hint, cname in rows:
                sw = words(str(stem))
                aw = words(answer_text(raw, hint))
                # Only judge where both sides carry enough words to be comparable.
                if len(sw) < 4 or len(aw) < 4:
                    continue
                scored += 1
                if not (sw & aw):
                    bad += 1
                    if len(examples) < a.limit:
                        examples.append((qid, cname, str(stem), answer_text(raw, hint)))
            rate = bad / scored if scored else 0
            print(f"  {lbl:<36} {len(rows):>6} {scored:>7} {bad:>10}   {rate:.1%}")
            if a.verbose and examples:
                worst.append((lbl, examples))

        if worst:
            for lbl, examples in worst:
                print(f"\n  === {lbl}: examples sharing no vocabulary")
                for qid, cname, stem, ans in examples:
                    print(f"\n    qid {qid}  {str(cname)[:38]}")
                    print(f"      Q: {' '.join(stem.split())[:100]}")
                    print(f"      A: {' '.join(ans.split())[:100]}")
        print("\n  A rate well above the control books is the signal. Read the rows\n"
              "  before concluding; a one-word answer shares no vocabulary either.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
