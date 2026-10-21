"""Detect mapping files whose rows are attached to the wrong questions.

    python -m scripts.check_mapping_alignment
    python -m scripts.check_mapping_alignment --glob 'ch8633*.json' --verbose

Read-only. Nothing is written; this only reports.

A mapping file is a list of `{sha, codes, note}`. If the shas are transcribed by
hand and slip by one, every note and every code lands on its **neighbour**. The
loader cannot see it: each sha exists, each code is legal, the row count is
right, and it reports `ok`. One agent caught exactly this in its own output
across items 35-47 and only because a sha went missing in the slip -- **a pure
permutation would have passed silently**, and the whole file would be wrong.

That is the worst failure mode available here, because it is invisible
downstream and it corrupts work that looks finished.

HOW THE CHECK WORKS. The note explains why a code fits a question, so it
inevitably reuses that question's own words. For each mapping, this scores the
vocabulary overlap between the note and the stem it points at, then scores the
same note against the stems one row earlier and one row later. Rows are
compared in file order.

    aligned      the note matches its own stem best      -- expected
    shifted +1   the note matches the NEXT stem better   -- suspect
    shifted -1   the note matches the PREVIOUS stem better

One row scoring better against a neighbour means nothing; notes are short and
vocabularies collide. A **run** of them in one direction is the signature of a
slip, so the report is by file and only files with a sustained lean are
flagged.

WHAT IT CANNOT SEE. A note written generically ("recall from the text") shares
no vocabulary with anything and is scored as indeterminate rather than wrong. A
file whose rows were reordered but individually correct also passes, correctly.
And it cannot judge whether the CODE is right -- only whether the note is
talking about the question it is attached to.
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

MAPS = Path(__file__).resolve().parent / "curriculum_maps"
WORD = re.compile(r"[a-zऀ-ॿ][a-zऀ-ॿ\-]{2,}")
# Words a note uses about the mapping itself rather than about the question.
NOISE = set("""the and for not but with from that this these those which what when
who how why its are was were has have had can will would should could outcome
outcomes code codes note maps mapped mapping question questions item items
chapter competency goal frame curriculum learning level cited citing fits fit
nearest sibling because since rather than only also both each such there their
about into over under more most other another same so too very just now then
lo cg qid sha""".split())


def words(s: str) -> set:
    return {w for w in WORD.findall((s or "").lower()) if w not in NOISE}


def overlap(note: set, stem: set) -> float:
    if not note or not stem:
        return -1.0                      # indeterminate, not zero
    return len(note & stem) / len(note)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--min-rows", type=int, default=8)
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        files = sorted(MAPS.glob(a.glob))
        print(f"  {len(files)} mapping file(s) under {MAPS.name}/\n")

        # sha -> stem, and qid -> stem, for everything in Classes 6-10
        by_sha, by_qid = {}, {}
        for qid, sha, stem in db.execute(text(
                "SELECT q.id, e.verbatim_sha256, q.question_title "
                "  FROM lms_question_master q "
                "  JOIN chapter_master c ON c.id=q.chapter_id "
                "   AND c.standard_id BETWEEN 39 AND 43 "
                "  LEFT JOIN lms_question_extraction e ON e.question_id=q.id")):
            w = words(str(stem))
            by_qid[int(qid)] = w
            if sha:
                # Mapping files address questions by a 16-character PREFIX of
                # verbatim_sha256, not the full 64. Indexing only the full hash
                # resolved 11,386 of 29,203 rows and quietly skipped the rest.
                s = str(sha)
                by_sha[s] = w
                by_sha[s[:16]] = w

        flagged, clean = [], 0
        skip_small = skip_unres = skip_nojudge = 0
        tot_rows = tot_resolved = tot_judged = 0
        for f in files:
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                rows = d.get("mappings") or []
            except (ValueError, OSError):
                skip_unres += 1
                continue
            tot_rows += len(rows)
            stems, notes = [], []
            for m in rows:
                s = str(m.get("sha") or "")
                w = (by_qid.get(int(s[4:])) if s.startswith("qid:") and s[4:].isdigit()
                     else by_sha.get(s))
                if w is None:
                    continue
                stems.append(w)
                notes.append(words(str(m.get("note") or "")))
            tot_resolved += len(stems)
            if len(stems) < a.min_rows:
                skip_small += 1
                continue

            here = ahead = behind = judged = 0
            for i, n in enumerate(notes):
                o0 = overlap(n, stems[i])
                if o0 < 0:
                    continue
                o1 = overlap(n, stems[i + 1]) if i + 1 < len(stems) else -1.0
                o_1 = overlap(n, stems[i - 1]) if i else -1.0
                judged += 1
                if o0 >= o1 and o0 >= o_1:
                    here += 1
                elif o1 > o0 and o1 >= o_1:
                    ahead += 1
                else:
                    behind += 1
            tot_judged += judged
            if not judged:
                skip_nojudge += 1
                continue
            lean = max(ahead, behind) / judged
            if lean >= 0.35 and here / judged < 0.5:
                flagged.append((f.name, judged, here, ahead, behind, lean))
            else:
                clean += 1
                if a.verbose:
                    print(f"    ok   {f.name:<34} {here}/{judged} aligned")

        print(f"  {clean} file(s) align, {len(flagged)} suspect")
        print(f"  skipped: {skip_small} with fewer than {a.min_rows} resolvable "
              f"rows, {skip_unres} unreadable, {skip_nojudge} with no judgeable note")
        print(f"  mappings: {tot_rows} in the files, {tot_resolved} resolved to a "
              f"live question, {tot_judged} scored\n")
        if flagged:
            print(f"  {'file':<36} {'rows':>5} {'own':>5} {'next':>5} {'prev':>5}  lean")
            for name, judged, here, ahead, behind, lean in sorted(
                    flagged, key=lambda r: -r[5]):
                print(f"  {name:<36} {judged:>5} {here:>5} {ahead:>5} "
                      f"{behind:>5}  {lean:.0%}")
            print("\n  A lean means the notes in that file describe a neighbouring\n"
                  "  question better than their own. Re-read the file before trusting\n"
                  "  it; nothing here has been changed.")
        else:
            print("  No file shows a sustained lean. Notes sit on their own questions.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
