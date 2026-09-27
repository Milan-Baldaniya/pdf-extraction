"""Apply per-question concept links that a reader wrote.

    python -m scripts.load_question_concepts --list
    python -m scripts.load_question_concepts --file concept_maps/ch25930.json
    python -m scripts.load_question_concepts --file concept_maps/ch25930.json --apply
    python -m scripts.load_question_concepts --all --apply

Input is what `question_concept_context.py` asked for: a chapter id and a list
of `{sha, concept_id, note}`. `--dry` is the default.

`concept_id` is written to **both** `lms_question_master.concept_id` and
`lms_question_extraction.concept_id`, because different readers use different
ones and a link present on only one side reads as absent to half the estate.
`lms_question_master.concept` (the name) is set alongside so the value is
legible without a join.

VALIDATED WHOLE, THEN WRITTEN. A file with one bad address or one concept that
does not belong to the chapter writes nothing, so a chapter is never half
linked. That is the same rule `load_question_curriculum` uses, and for the same
reason: the link IS the deliverable, and a file whose entries were silently
dropped looks exactly like one that worked.

ADDRESSING, mirroring `load_question_curriculum` exactly:
  * `verbatim_sha256`, full or a 16-character prefix, where the question has a
    sidecar. Ids are reassigned by `write_question_bank` on every re-load; the
    hash survives one, and changes when the question's text changes, so a stale
    reading is reported rather than applied to whatever now sits at that id.
  * `qid:<question_id>` only where the LMS itself wrote the question and there
    is no hash. A `qid:` naming a question that HAS a sidecar is refused, so the
    weaker address cannot spread to questions the hash rule covers.

IDEMPOTENT. Writing the same link twice is a no-op. A link that already differs
is reported and, without `--force`, refused -- someone read that question and
reached a different conclusion, and silently overwriting them is not this
script's call.
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


def _index(db, chapter: int):
    """sha256 -> question_id, and the set of ids with no sidecar."""
    by_sha, native, current = {}, set(), {}
    for qid, sha, cur in db.execute(text(
            "SELECT q.id, x.verbatim_sha256, "
            "       COALESCE(q.concept_id, x.concept_id, 0) "
            "  FROM lms_question_master q "
            "  LEFT JOIN lms_question_extraction x ON x.question_id = q.id "
            " WHERE q.chapter_id = :c AND q.deleted_at IS NULL"),
            {"c": chapter}).fetchall():
        current[int(qid)] = int(cur or 0)
        if sha:
            by_sha[str(sha)] = int(qid)
        else:
            native.add(int(qid))
    return by_sha, native, current


def _resolve(addr: str, by_sha: dict, native: set):
    if addr.startswith("qid:"):
        raw = addr[4:].strip()
        if not raw.isdigit():
            return None, f"{addr!r} is not a question id"
        qid = int(raw)
        if qid in native:
            return qid, None
        if qid in {v for v in by_sha.values()}:
            return None, (f"qid:{qid} has a sidecar -- address it by its "
                          f"verbatim_sha256, not its id")
        return None, f"qid:{qid} is not a live question of this chapter"
    if addr in by_sha:
        return by_sha[addr], None
    hits = [v for k, v in by_sha.items() if k.startswith(addr)]
    if len(hits) == 1:
        return hits[0], None
    return None, (f"sha {addr[:16]} matches {len(hits)} questions in this chapter"
                  if hits else f"sha {addr[:16]} matches no question in this chapter")


def apply_file(db, path: Path, do: bool, force: bool) -> int:
    doc = json.loads(path.read_text(encoding="utf-8"))
    chapter = int(doc["chapter_id"])
    links = doc.get("links") or []
    by_sha, native, current = _index(db, chapter)
    concepts = {int(i): str(n) for i, n in db.execute(text(
        "SELECT id, name FROM lms_concept WHERE chapter_id = :c"),
        {"c": chapter}).fetchall()}

    plan, problems, already, conflict = [], [], 0, []
    seen = set()
    for e in links:
        addr = str(e.get("sha") or "").strip()
        if not addr:
            problems.append("an entry has no sha")
            continue
        qid, err = _resolve(addr, by_sha, native)
        if err:
            problems.append(err)
            continue
        if qid in seen:
            problems.append(f"{addr[:16]} appears twice in this file")
            continue
        seen.add(qid)
        try:
            k = int(e.get("concept_id"))
        except (TypeError, ValueError):
            problems.append(f"{addr[:16]}: concept_id is not a number")
            continue
        if k not in concepts:
            problems.append(f"{addr[:16]}: concept {k} does not belong to "
                            f"chapter {chapter}")
            continue
        if not str(e.get("note") or "").strip():
            problems.append(f"{addr[:16]}: no note")
            continue
        cur = current.get(qid, 0)
        if cur == k:
            already += 1
            continue
        if cur and not force:
            conflict.append(f"{addr[:16]}: already linked to {cur} "
                            f"({concepts.get(cur,'?')}), file says {k}")
            continue
        plan.append((qid, k, concepts[k]))

    print(f"  {path.name}: chapter {chapter}, {len(links)} entr(ies) -> "
          f"{len(plan)} to write, {already} already correct, "
          f"{len(conflict)} conflict, {len(problems)} problem(s)")
    for p in problems[:12]:
        print(f"    ! {p}")
    for c in conflict[:8]:
        print(f"    ~ {c}")
    if problems:
        print("    REFUSED -- nothing written from this file")
        return 0
    if not do or not plan:
        return 0

    for qid, k, name in plan:
        db.execute(text(
            "UPDATE lms_question_master SET concept_id = :k, concept = :n "
            " WHERE id = :q"), {"k": k, "n": name[:255], "q": qid})
        db.execute(text(
            "UPDATE lms_question_extraction SET concept_id = :k "
            " WHERE question_id = :q"), {"k": k, "q": qid})
    db.commit()
    print(f"    wrote {len(plan)} ok")
    return len(plan)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", action="append")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry", action="store_true", help="the default")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="overwrite a link that already differs")
    a = ap.parse_args()

    MAPS.mkdir(exist_ok=True)
    if a.list:
        for f in sorted(MAPS.glob("*.json")):
            print(f"  {f.name}")
        return 0

    files = ([Path(__file__).resolve().parent / f for f in a.file] if a.file
             else sorted(MAPS.glob("*.json")) if a.all else [])
    if not files:
        print("  nothing to do -- pass --file or --all")
        return 0

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        n = 0
        for f in files:
            n += apply_file(db, f, a.apply, a.force)
        print(f"\n  {'wrote' if a.apply else 'would write'} {n} link(s)"
              + ("" if a.apply else "  -- re-run with --apply"))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
