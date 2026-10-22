"""Drop concept-link entries that address a question which no longer exists.

    python -m scripts.prune_retired_from_concept_maps
    python -m scripts.prune_retired_from_concept_maps --apply

A drafting pass and a retirement pass run against the same chapters at the same
time. When a question is retired after its concept file was written, the file
still addresses it -- and because `load_question_concepts` validates a file
WHOLE, that one dead address makes the loader refuse the entire file. One
retired question can hold up sixty good links.

That is the right behaviour for the loader: a file whose entries were silently
dropped looks exactly like one that worked. So the fix belongs here, where the
removal is visible and explained, rather than in a loosened loader.

WHAT IT REMOVES. Only entries whose address resolves to no live question of the
file's own chapter -- a retired row, or a sha that matches nothing. Nothing else
in the file is touched, the remaining entries keep their order, and every
removal is printed with the reason and the note that is being discarded, so a
wrong retirement upstream is visible here rather than silently swallowed.

A file that would lose EVERY entry is left alone and reported: that means the
chapter was retired wholesale, or the file addresses the wrong chapter, and
either is a mistake to look at rather than a file to empty.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

MAPS = Path(__file__).resolve().parent / "concept_maps"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--glob", default="*.json")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        files = sorted(MAPS.glob(a.glob))
        print(f"  {len(files)} file(s) under {MAPS.name}/\n")
        live_by_chapter: dict[int, tuple] = {}
        touched = dropped = 0

        for f in files:
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
                chapter = int(doc["chapter_id"])
                links = doc.get("links") or []
            except (ValueError, OSError, KeyError, TypeError):
                print(f"   {f.name}: unreadable, left alone")
                continue

            if chapter not in live_by_chapter:
                shas, native = set(), set()
                for qid, sha in db.execute(text(
                        "SELECT q.id, x.verbatim_sha256 "
                        "  FROM lms_question_master q "
                        "  LEFT JOIN lms_question_extraction x "
                        "         ON x.question_id = q.id "
                        " WHERE q.chapter_id = :c AND q.deleted_at IS NULL"),
                        {"c": chapter}).fetchall():
                    if sha:
                        shas.add(str(sha))
                    else:
                        native.add(int(qid))
                live_by_chapter[chapter] = (shas, native)
            shas, native = live_by_chapter[chapter]

            keep, lose = [], []
            for e in links:
                addr = str(e.get("sha") or "").strip()
                if addr.startswith("qid:"):
                    raw = addr[4:].strip()
                    ok = raw.isdigit() and int(raw) in native
                else:
                    ok = addr in shas or any(s.startswith(addr) for s in shas)
                (keep if ok else lose).append(e)

            if not lose:
                continue
            if not keep:
                print(f"   {f.name}: ALL {len(lose)} entries address nothing "
                      f"live in chapter {chapter} --\n      left alone. Either "
                      f"the chapter was retired wholesale or this file names "
                      f"the wrong\n      chapter. Look at it; do not empty it.")
                continue

            touched += 1
            dropped += len(lose)
            print(f"   {f.name}: dropping {len(lose)} of {len(links)} "
                  f"(chapter {chapter})")
            for e in lose:
                print(f"      - {str(e.get('sha'))[:16]} -> concept "
                      f"{e.get('concept_id')}")
                print(f"        note being discarded: "
                      f"{' '.join(str(e.get('note') or '').split())[:96]}")
            if a.apply:
                doc["links"] = keep
                f.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                             encoding="utf-8")

        print(f"\n  {dropped} entr(ies) in {touched} file(s) address a question "
              f"that is no longer live")
        if not a.apply:
            print("  report only -- re-run with --apply")
        else:
            print("  files rewritten; re-run load_question_concepts to apply "
                  "what remains")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
