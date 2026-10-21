"""Apply per-question curriculum mappings that a reader wrote.

    python -m scripts.load_question_curriculum --list
    python -m scripts.load_question_curriculum --file curriculum_maps/ch1012.json
    python -m scripts.load_question_curriculum --all --apply

Input is whatever `question_curriculum_context.py` asked for: a chapter id and
a list of `{sha, codes, note}`. `--dry` is the default, and deliberately so --
these rows are what the bank filters curriculum by, and a wrong code reads as
alignment while being nothing of the sort.

Three properties this has to hold, because two of these books are being loaded
on another machine while it runs:

  * addressed by `verbatim_sha256`, not `question_id`. `write_question_bank`
    reassigns ids on every re-load; the hash survives one, and when a question's
    text changes the hash changes with it, so a stale reading is reported rather
    than applied to whatever now sits at that id.

    The one exception is a question the LMS itself wrote. It has no sidecar row
    and so no hash, and is addressed as `qid:<question_id>`. That is safe for
    exactly the reason the id is unsafe above: the renumbering hazard is
    `write_question_bank` reloading rows, and it only ever reloads rows it
    wrote. A `qid:` naming a question that DOES have a sidecar is refused, so
    the weaker address cannot spread to questions the hash rule covers.
  * validated whole, then written. A file with one bad code writes nothing, so a
    chapter is never half mapped.
  * idempotent. `persist_question_outcomes` deletes each question's set before
    inserting, and `uq_qo_question_code` backs it, so re-running is a no-op and
    a re-run after the other machine finishes is the supported repair.

Codes are resolved with `strict=True`: an invented one raises rather than being
dropped. Dropping is right for the concept fan-out, where one bad code among
hundreds should not fail a chapter. Here the mapping IS the deliverable, and a
file whose every citation was silently discarded looks exactly like one that
worked.
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

MAP_DIR = Path(__file__).resolve().parent / "curriculum_maps"


def _chapter_questions(db, chapter_id: int) -> dict[str, tuple[int, int | None]]:
    """sha256 -> (question_id, extraction_id) for one chapter.

    Prefixes are accepted on the reading side, so this is keyed on the full
    hash and matched by prefix later.
    """
    rows = db.execute(
        text(
            "SELECT x.verbatim_sha256, q.id, x.extraction_id "
            "  FROM lms_question_master q "
            "  JOIN lms_question_extraction x ON x.question_id = q.id "
            " WHERE q.chapter_id = :c AND x.verbatim_sha256 IS NOT NULL"
        ),
        {"c": chapter_id},
    ).fetchall()
    return {r[0]: (int(r[1]), int(r[2])) for r in rows}


def _native_questions(db, chapter_id: int) -> set[int]:
    """Ids of this chapter's questions that the LMS wrote, not this pipeline.

    They have no sidecar row and therefore no hash, so `qid:<id>` is the only
    address they have. That is safe HERE and nowhere else: the id hazard in the
    module docstring is `write_question_bank` renumbering rows on reload, and it
    only ever reloads rows it wrote. A question with no sidecar is one it has
    never touched.

    Returned as the set of ids that MAY be addressed that way, so a `qid:`
    naming anything else is refused rather than quietly accepted -- otherwise
    the weaker address would work for every question in the bank and the hash
    rule would be a convention instead of a constraint.
    """
    rows = db.execute(
        text(
            "SELECT q.id FROM lms_question_master q "
            " WHERE q.chapter_id = :c "
            "   AND NOT EXISTS (SELECT 1 FROM lms_question_extraction x "
            "                    WHERE x.question_id = q.id)"
        ),
        {"c": chapter_id},
    ).fetchall()
    return {int(r[0]) for r in rows}


def _resolve_sha(
    sha: str,
    index: dict[str, tuple[int, int | None]],
    native: set[int],
) -> tuple[int, int | None] | str:
    """(question_id, extraction_id), or a string saying why not."""
    if sha.startswith("qid:"):
        raw = sha[4:].strip()
        if not raw.isdigit():
            return f"{sha!r} is not a question id"
        qid = int(raw)
        if qid in native:
            return (qid, None)
        if any(v[0] == qid for v in index.values()):
            return (f"qid:{qid} names a question that HAS a sidecar row; "
                    f"address it by its verbatim_sha256, not its id")
        return f"qid:{qid} is not a question in this chapter"
    if sha in index:
        return index[sha]
    hits = [v for k, v in index.items() if k.startswith(sha)]
    if len(hits) == 1:
        return hits[0]
    return (f"sha {sha[:16]} matches {len(hits)} questions in this chapter"
            if hits else f"sha {sha[:16]} matches no question in this chapter")


def process(path: Path, apply: bool) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    chapter_id = int(payload["chapter_id"])
    mappings = payload.get("mappings") or []

    db = SessionLocal()
    try:
        row = db.execute(
            text(
                "SELECT chapter_name, standard_id, subject_id, sub_institute_id "
                "  FROM chapter_master WHERE id = :c"
            ),
            {"c": chapter_id},
        ).fetchone()
        if not row:
            return {"file": path.name, "status": "chapter_not_found",
                    "chapter_id": chapter_id, "written": 0}
        name, standard_id, subject_id, tenant = row

        frame = curf.load_frame(
            db, chapter_id=chapter_id, standard_id=standard_id, subject_id=subject_id
        )
        index = _chapter_questions(db, chapter_id)
        native = _native_questions(db, chapter_id)

        # Validate everything before writing anything.
        resolved: dict[int, list] = {}
        by_extraction: dict[int, int | None] = {}
        problems: list[str] = []
        for entry in mappings:
            sha = str(entry.get("sha") or "").strip()
            codes = entry.get("codes") or []
            if not sha:
                problems.append("an entry has no sha")
                continue
            hit = _resolve_sha(sha, index, native)
            if isinstance(hit, str):
                problems.append(hit)
                continue
            if not codes:
                continue
            qid, eid = hit
            try:
                resolved[qid] = qo.resolve_codes(frame, codes, strict=True)
            except curf.UnknownOutcomeCode as exc:
                problems.append(f"sha {sha[:16]}: {exc}")
                continue
            by_extraction[qid] = eid

        cited = sum(1 for e in mappings if e.get("codes"))
        rows_out = sum(len(v) for v in resolved.values())
        result = {
            "file": path.name, "chapter_id": chapter_id, "chapter": name,
            "entries": len(mappings), "cited": cited, "questions": len(resolved),
            "rows": rows_out, "problems": problems, "written": 0,
            "status": "ok" if not problems else "refused",
        }
        if problems or not apply or not resolved:
            return result

        # One call per extraction_id rather than one for the file. The old code
        # took the first id and stamped it on every row, which was harmless
        # while a chapter had exactly one extraction and every question came
        # from it -- but a native question has NO extraction, and stamping the
        # book's id on it would claim it came out of a book nobody read it
        # from. `extraction_id` is nullable precisely so that None can be said.
        written = 0
        groups: dict[int | None, dict[int, list]] = {}
        for qid, codes in resolved.items():
            groups.setdefault(by_extraction.get(qid), {})[qid] = codes
        for eid, group in groups.items():
            written += qo.persist_question_outcomes(
                db, frame=frame, extraction_id=eid, sub_institute_id=tenant,
                chapter_id=chapter_id, mappings_by_question_id=group,
            )
        qo.mirror_primary(db, resolved)
        db.commit()
        result["written"] = written
        return result
    finally:
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", action="append", help="a mapping file; repeatable")
    ap.add_argument("--all", action="store_true", help="every file in curriculum_maps/")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry", action="store_true", help="the default")
    ap.add_argument("--apply", action="store_true", help="actually write")
    a = ap.parse_args()

    MAP_DIR.mkdir(exist_ok=True)
    if a.list:
        files = sorted(MAP_DIR.glob("*.json"))
        print(f"{MAP_DIR}: {len(files)} file(s)")
        for f in files:
            try:
                payload = json.loads(f.read_text(encoding="utf-8"))
                n = len(payload.get("mappings") or [])
                print(f"  {f.name:<34} chapter {payload.get('chapter_id')} "
                      f"{n} mapping(s)")
            except Exception as exc:
                print(f"  {f.name:<34} UNREADABLE: {exc}")
        return 0

    if a.file:
        # Accept a bare name, a path relative to cwd, or one relative to
        # curriculum_maps/ -- "curriculum_maps/ch1019.json" typed from backend/
        # used to resolve under MAP_DIR a second time and report MISSING.
        paths = []
        for f in a.file:
            cand = Path(f)
            if not cand.exists():
                for alt in (MAP_DIR / Path(f).name, Path.cwd() / f):
                    if alt.exists():
                        cand = alt
                        break
            paths.append(cand)
    elif a.all:
        paths = sorted(MAP_DIR.glob("*.json"))
    else:
        ap.error("give --file, --all, or --list")

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")

    apply = bool(a.apply)
    print(f"mode={'WRITING' if apply else 'DRY RUN'}  files={len(paths)}\n")
    print(f"{'file':<30} {'chapter':>8} {'cited':>6} {'qs':>5} {'rows':>6} {'wrote':>6}  status")
    print("-" * 82)
    bad = 0
    for path in paths:
        if not path.exists():
            print(f"{path.name:<30} {'-':>8} {'-':>6} {'-':>5} {'-':>6} {'-':>6}  MISSING")
            bad += 1
            continue
        r = process(path, apply)
        print(f"{r['file']:<30} {r.get('chapter_id', '-'):>8} {r.get('cited', 0):>6} "
              f"{r.get('questions', 0):>5} {r.get('rows', 0):>6} {r.get('written', 0):>6}"
              f"  {r['status']}")
        for problem in (r.get("problems") or [])[:6]:
            print(f"    ! {problem}")
        if r.get("problems"):
            extra = len(r["problems"]) - 6
            if extra > 0:
                print(f"    ! ... and {extra} more")
            bad += 1
    print("-" * 82)
    if not apply:
        print("\nDRY RUN - nothing written. Re-run with --apply.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
