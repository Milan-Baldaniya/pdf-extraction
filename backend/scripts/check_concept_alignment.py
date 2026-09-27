"""Detect concept-link files whose rows are attached to the wrong questions.

    python -m scripts.check_concept_alignment
    python -m scripts.check_concept_alignment --glob 'ch25930*.json' --verbose

Read-only. Nothing is written; this only reports.

`load_question_concepts` validates a file whole, so a bad address or a concept
from the wrong chapter writes nothing. **A permutation passes all of that.** If
the addresses slip by one, every note and every concept lands on a neighbour:
each sha exists, each concept belongs to the chapter, the count is right, and
the loader reports success.

That is not hypothetical. During the curriculum pass **three separate agents
produced exactly this shift in their own drafts**, and two only found it because
an address went missing in the slip rather than permuting cleanly.

HOW THE CHECK WORKS. Two independent signals, because either alone is noisy:

  NOTE vs QUESTION   the note explains why a concept fits a question, so it
                     reuses that question's words.
  CONCEPT vs QUESTION the concept's name and description describe what the
                     question is about.

For each row both are scored against its own question and against the questions
one row earlier and later, in file order. A single row scoring better against a
neighbour means nothing -- notes are short and vocabularies collide. A **run**
of them leaning the same way is the signature of a slip, so only a sustained
lean is reported.

WHAT IT CANNOT SEE. A file whose rows were reordered but are individually
correct passes, rightly. A note written generically ("recall from the text")
matches nothing and is scored as indeterminate. And it cannot tell a defensible
link from the best one -- only whether the row is talking about the question it
is attached to.
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

MAPS = Path(__file__).resolve().parent / "concept_maps"
WORD = re.compile(r"[a-zऀ-ॿ][a-zऀ-ॿ\-]{2,}")
# Words a note uses about the mapping rather than about the question.
NOISE = set("""the and for not but with from that this these those which what when
who how why its are was were has have had can will would should could concept
concepts question questions item items chapter tests testing asks asking maps
mapped mapping note rather than because since sibling rejected nearest fits fit
about into over under more most other another same such there their only also
both each""".split())


def words(s: str) -> set:
    return {w for w in WORD.findall((s or "").lower()) if w not in NOISE}


def overlap(a: set, b: set) -> float:
    if not a or not b:
        return -1.0                       # indeterminate, not zero
    return len(a & b) / len(a)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--min-rows", type=int, default=6)
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        files = sorted(MAPS.glob(a.glob))
        print(f"  {len(files)} concept-link file(s) under {MAPS.name}/\n")
        if not files:
            print("  nothing to check yet")
            return 0

        # every question's words, by sha (full and 16-char prefix) and by qid
        by_sha, by_qid = {}, {}
        for qid, sha, stem in db.execute(text(
                "SELECT q.id, e.verbatim_sha256, q.question_title "
                "  FROM lms_question_master q "
                "  LEFT JOIN lms_question_extraction e ON e.question_id = q.id "
                "  JOIN chapter_master c ON c.id = q.chapter_id "
                "   AND c.standard_id BETWEEN 39 AND 43 "
                " WHERE q.deleted_at IS NULL")):
            w = words(str(stem))
            by_qid[int(qid)] = w
            if sha:
                by_sha[str(sha)] = w
                by_sha[str(sha)[:16]] = w
        concepts = {int(i): words(f"{n} {d or ''}") for i, n, d in db.execute(text(
            "SELECT id, name, description FROM lms_concept")).fetchall()}

        flagged, clean = [], 0
        skip_small = skip_unres = 0
        tot_rows = tot_scored = 0
        for f in files:
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                links = d.get("links") or []
            except (ValueError, OSError):
                skip_unres += 1
                continue
            tot_rows += len(links)

            stems, notes, cons = [], [], []
            for m in links:
                s = str(m.get("sha") or "")
                w = (by_qid.get(int(s[4:])) if s.startswith("qid:") and s[4:].isdigit()
                     else by_sha.get(s) or by_sha.get(s[:16]))
                if w is None:
                    continue
                stems.append(w)
                notes.append(words(str(m.get("note") or "")))
                cons.append(concepts.get(int(m.get("concept_id") or 0), set()))
            if len(stems) < a.min_rows:
                skip_small += 1
                continue

            here = ahead = behind = judged = 0
            for i in range(len(stems)):
                probe = notes[i] | cons[i]
                o0 = overlap(probe, stems[i])
                if o0 < 0:
                    continue
                o1 = overlap(probe, stems[i + 1]) if i + 1 < len(stems) else -1.0
                o_1 = overlap(probe, stems[i - 1]) if i else -1.0
                judged += 1
                if o0 >= o1 and o0 >= o_1:
                    here += 1
                elif o1 > o0 and o1 >= o_1:
                    ahead += 1
                else:
                    behind += 1
            tot_scored += judged
            if not judged:
                skip_small += 1
                continue
            lean = max(ahead, behind) / judged
            if lean >= 0.35 and here / judged < 0.5:
                flagged.append((f.name, judged, here, ahead, behind, lean))
            else:
                clean += 1
                if a.verbose:
                    print(f"    ok   {f.name:<38} {here}/{judged} aligned")

        print(f"  {clean} file(s) align, {len(flagged)} suspect")
        print(f"  skipped: {skip_small} with fewer than {a.min_rows} scorable "
              f"rows, {skip_unres} unreadable")
        print(f"  links: {tot_rows} in the files, {tot_scored} scored\n")
        if flagged:
            print(f"  {'file':<40} {'rows':>5} {'own':>5} {'next':>5} {'prev':>5}  lean")
            for name, judged, here, ahead, behind, lean in sorted(
                    flagged, key=lambda r: -r[5]):
                print(f"  {name:<40} {judged:>5} {here:>5} {ahead:>5} "
                      f"{behind:>5}  {lean:.0%}")
            print("\n  A lean means that file's notes and concepts describe a "
                  "neighbouring\n  question better than their own. Re-read it "
                  "before trusting it; nothing\n  here has been changed.")
        else:
            print("  No file shows a sustained lean.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
