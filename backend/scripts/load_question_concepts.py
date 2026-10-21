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

THE ALIGNMENT GATE IS ON BY DEFAULT. Before writing anything, each file is
scored the way `check_concept_alignment` scores it, and a file whose notes and
concepts fit their NEIGHBOURING questions better than their own is refused.

That gate exists because applying is central: a sweep picks up whatever is on
disk, which can be **before** the agent that wrote the file has run the check
itself. A permutation passes every other validation here -- every address
resolves, every concept is legal, the count is right, the loader reports success
-- so a one-row slip is exactly the defect nothing else catches. Three separate
agents produced that slip during the curriculum pass. `--no-gate` overrides it.

IDEMPOTENT. Writing the same link twice is a no-op. A link that already differs
is reported and, without `--force`, refused -- someone read that question and
reached a different conclusion, and silently overwriting them is not this
script's call.

UNLINKING. `{"sha": "...", "concept_id": null, "note": "why"}` clears a link
instead of writing one. This exists because reading a chapter turns up items
whose stored concept is wrong and for which **no concept of that chapter is
right** -- a grammar drill in a set with no language concept, a companion poem
the concept set never covers, an authorship question where nothing records the
author. Until this path existed those rows kept the offline matcher's output
because the only alternative on offer was to move them somewhere equally wrong:
one agent finished Class 8 English with a list of 14 such rows it could not
touch. A cleared link reads as unlinked, which is the truth about the row.

An unlink changes an existing link, so it needs `--force`, by the same rule as
any other overwrite. Keep unlinks in their own file -- `ch<CID>_x.json` -- so
the main file never needs `--force` and a forced run can never quietly
overwrite a judgement it was not aimed at.
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


def _leans(db, chapter: int, links: list) -> str | None:
    """Return a reason if this file's rows describe a NEIGHBOURING question
    better than their own, else None.

    This is `check_concept_alignment`'s test, run here so that a sweep cannot
    apply a shifted file. It matters because the sweep is central: a drafting
    agent's file is picked up the moment it is written, which can be before the
    agent has run the check itself. A permutation passes every other validation
    -- each address resolves, each concept is legal, the count is right -- so
    without this a one-row slip would be committed and reported as success.
    """
    try:
        from scripts.check_concept_alignment import words, overlap
    except ImportError:
        return None                      # checker unavailable: do not block
    by_sha, by_qid = {}, {}
    for qid, sha, stem in db.execute(text(
            "SELECT q.id, x.verbatim_sha256, q.question_title "
            "  FROM lms_question_master q "
            "  LEFT JOIN lms_question_extraction x ON x.question_id = q.id "
            " WHERE q.chapter_id = :c AND q.deleted_at IS NULL"),
            {"c": chapter}).fetchall():
        w = words(str(stem))
        by_qid[int(qid)] = w
        if sha:
            by_sha[str(sha)] = w
            by_sha[str(sha)[:16]] = w
    concepts = {int(i): words(f"{n} {d or ''}") for i, n, d in db.execute(text(
        "SELECT id, name, description FROM lms_concept WHERE chapter_id = :c"),
        {"c": chapter}).fetchall()}

    stems, probes = [], []
    for e in links:
        s = str(e.get("sha") or "")
        w = (by_qid.get(int(s[4:])) if s.startswith("qid:") and s[4:].isdigit()
             else by_sha.get(s) or by_sha.get(s[:16]))
        if w is None:
            continue
        stems.append(w)
        probes.append(words(str(e.get("note") or ""))
                      | concepts.get(int(e.get("concept_id") or 0), set()))
    if len(stems) < 6:
        return None                      # too few rows to judge, as the checker
    here = ahead = behind = judged = 0
    dirs = []                            # per judged row, in file order
    for i in range(len(stems)):
        o0 = overlap(probes[i], stems[i])
        if o0 < 0:
            continue
        o1 = overlap(probes[i], stems[i + 1]) if i + 1 < len(stems) else -1.0
        o_1 = overlap(probes[i], stems[i - 1]) if i else -1.0
        judged += 1
        if o0 >= o1 and o0 >= o_1:
            here += 1
            dirs.append("h")
        elif o1 > o0 and o1 >= o_1:
            ahead += 1
            dirs.append("a")
        else:
            behind += 1
            dirs.append("b")
    if not judged:
        return None

    # A WHOLE-FILE shift shows up as a global lean.
    lean = max(ahead, behind) / judged
    if lean >= 0.35 and here / judged < 0.5:
        return (f"{here}/{judged} rows describe their own question, {ahead} the "
                f"next and {behind} the previous ({lean:.0%} lean)")

    # A PARTIAL shift does not. If a row is dropped two thirds of the way down,
    # only the rows after it slide, so the global lean stays under the threshold
    # while every one of those rows is on the wrong question. That is the more
    # likely mistake, because it comes from hand-transcribing a long list and
    # losing one line -- and it was produced for real, on a 53-row file, with
    # 13 rows shifted: 24%, which the test above passes.
    # The signature that survives is a RUN of consecutive rows leaning the same
    # way. Notes are specific enough that a run this long does not happen by
    # chance; a genuinely mixed file alternates.
    best = cur = 0
    cdir = None
    for d in dirs:
        if d == "h":
            cur, cdir = 0, None
            continue
        cur = cur + 1 if d == cdir else 1
        cdir = d
        best = max(best, cur)
    if best >= 6:
        return (f"{best} consecutive rows lean the same way (towards the "
                f"{'next' if cdir == 'a' else 'previous'} question) out of "
                f"{judged} scored -- the signature of a dropped row shifting "
                f"everything after it")
    return None


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


def apply_file(db, path: Path, do: bool, force: bool, gate: bool = True) -> int:
    doc = json.loads(path.read_text(encoding="utf-8"))
    chapter = int(doc["chapter_id"])
    links = doc.get("links") or []
    if gate:
        why = _leans(db, chapter, links)
        if why:
            print(f"  {path.name}: chapter {chapter}, {len(links)} entr(ies)")
            print(f"    ! ALIGNMENT: {why}")
            print("    REFUSED -- this file's notes and concepts fit its "
                  "neighbours better than\n    its own rows, which is the "
                  "signature of a one-row address slip. Re-read it.\n"
                  "    Pass --no-gate to apply anyway.")
            return 0
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
        raw = e.get("concept_id")
        # An explicit null (or 0) asks for the existing link to be cleared.
        unlink = raw is None or (isinstance(raw, str)
                                 and raw.strip().lower() in ("", "0", "null"))
        if unlink:
            k = 0
        else:
            try:
                k = int(raw)
            except (TypeError, ValueError):
                problems.append(f"{addr[:16]}: concept_id is not a number")
                continue
            if k == 0:
                unlink = True
            elif k not in concepts:
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
                            f"({concepts.get(cur,'?')}), file says "
                            + ("no concept (unlink)" if unlink else str(k)))
            continue
        plan.append((qid, k, "(unlinked)" if unlink else concepts[k]))

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

    cleared = 0
    for qid, k, name in plan:
        if k:
            db.execute(text(
                "UPDATE lms_question_master SET concept_id = :k, concept = :n "
                " WHERE id = :q"), {"k": k, "n": name[:255], "q": qid})
            db.execute(text(
                "UPDATE lms_question_extraction SET concept_id = :k "
                " WHERE question_id = :q"), {"k": k, "q": qid})
        else:
            cleared += 1
            db.execute(text(
                "UPDATE lms_question_master SET concept_id = NULL, "
                "       concept = NULL WHERE id = :q"), {"q": qid})
            db.execute(text(
                "UPDATE lms_question_extraction SET concept_id = NULL "
                " WHERE question_id = :q"), {"q": qid})
    db.commit()
    print(f"    wrote {len(plan) - cleared} ok"
          + (f", cleared {cleared}" if cleared else ""))
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
    ap.add_argument("--no-gate", action="store_true",
                    help="skip the alignment gate (on by default)")
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
            n += apply_file(db, f, a.apply, a.force, gate=not a.no_gate)
        print(f"\n  {'wrote' if a.apply else 'would write'} {n} link(s)"
              + ("" if a.apply else "  -- re-run with --apply"))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
