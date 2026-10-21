"""The PAL V4 sidecar: the fields the master prompt needs and no column holds.

    python -m scripts.pal_sidecar --report
    python -m scripts.pal_sidecar --file pal_payloads/ch8622_part1.json
    python -m scripts.pal_sidecar --file ... --apply

`pal-v4-question-intelligence-master-prompt.md` specifies 27 core fields and
12 rich ones. THIRTEEN OF THE CORE FIELDS HAVE A COLUMN AND NONE OF THE RICH
ONES DO. Missing outright is `curriculum_citation`, which that document calls
never optional and which is the one thing anchoring a generated question's
facts to the syllabus rather than to model memory. Without somewhere to put
it, a generated item fails the master prompt's own quality gate on arrival.

WHERE IT LIVES, AND WHY THERE. `lms_question_extraction.corrected_fields` is
longtext and used on 0 of 12,908 rows -- the only free column of its kind on
the provenance row. The payload is namespaced under a `pal_v4` key so the
column's misleading name cannot be mistaken for its contents. The three
obvious alternatives are all wrong:

    verbatim_payload    feeds uq_lqe_extraction_hash; writing it breaks the
                        constraint and discards AI tags on live rows
    ai_rationale        already holds the concept tagger's score on all
                        12,908 rows
    validation_report   holds the validator's own output on 20 rows

ADDRESSED BY `verbatim_sha256`, NOT `question_id`. `write_question_bank`
reassigns ids on every re-load, and two of these books are being loaded on
another machine. The hash survives a reload, and when a question's text
changes the hash changes with it, so a stale payload is reported rather than
applied to whatever now sits at that id.

UPDATE only. Nothing here inserts or removes a row.
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

NS = "pal_v4"

# Section 7 fields with no column of their own.
CORE_SIDECAR = [
    "answer_explanation", "mark_scheme", "rubric",
    "sub_concept_id", "sub_concept_name", "learning_objective",
    "prerequisite_concepts", "difficulty_score", "difficulty_reason",
    "pal_role", "source_tier", "source_url", "copyright_status",
    "extraction_method",
]
# Section 8 plus the Section 13 grounding block. Empty is fine; fabricated
# is not -- see `gate` below.
RICH_SIDECAR = [
    "difficulty_detail", "distractor_intelligence", "diagnostic",
    "next_action_rules", "h5p", "pedagogy", "career_intelligence",
    "estimated_time_seconds", "quality_confidence", "question_sequence",
    "question_dna", "generation_grounding",
]
GENERATED = {"ai_generated_from_pattern", "ai_generated_concept_grounded"}


def gate(p: dict) -> list[str]:
    """The master prompt's Section 9 gate, for what this sidecar can see.

    Only the checks this payload is in a position to make. Core fields that
    DO have a column (bloom_level, concept_id, difficulty band) are gated by
    the loader, not here, and are not re-checked.
    """
    bad: list[str] = []
    status = (p.get("validation_status") or "").strip()
    grounding = p.get("generation_grounding") or {}
    gtype = (grounding.get("grounding_type") or "").strip()

    if status in GENERATED or gtype:
        cite = (grounding.get("curriculum_citation") or "").strip()
        if not cite:
            bad.append("curriculum_citation is empty on a generated item -- "
                       "never optional under either grounding path")
        if status and gtype and status != gtype:
            bad.append(f"validation_status {status!r} disagrees with "
                       f"grounding_type {gtype!r}")
        srcs = grounding.get("pattern_source_ids") or []
        if gtype == "ai_generated_from_pattern" and not srcs:
            bad.append("Path A names no pattern_source_ids; a concept with no "
                       "sourced sibling is Path B, not Path A")
        if gtype == "ai_generated_concept_grounded":
            if srcs:
                bad.append("Path B must not cite pattern_source_ids")
            if not grounding.get("flagged_for_review"):
                bad.append("Path B must set flagged_for_review")

    # A fabricated rich field fails the gate; an absent one does not.
    for f in RICH_SIDECAR:
        v = p.get(f)
        if isinstance(v, str) and v.strip().lower() in {"n/a", "none", "tbd",
                                                        "placeholder", "unknown"}:
            bad.append(f"{f} holds a placeholder; leave it out instead")
    if p.get("misconception", {}).get("applicable") and not \
            (p.get("misconception", {}).get("misconception_id")
             or p.get("misconception", {}).get("description")):
        bad.append("misconception.applicable is true but nothing evidences it")
    return bad


def _load(db, sha: str) -> dict | None:
    r = db.execute(text(
        "SELECT corrected_fields FROM lms_question_extraction "
        " WHERE verbatim_sha256 LIKE :s LIMIT 1"), {"s": sha + "%"}).scalar()
    if r is None:
        return None
    try:
        return json.loads(r).get(NS, {}) if r else {}
    except Exception:
        return {}


def apply_file(path: Path, write: bool) -> int:
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows = doc.get("payloads") or []
    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    ok = failed = missing = 0
    try:
        for entry in rows:
            sha = (entry.get("sha") or "").strip()
            payload = entry.get(NS) or {}
            bad = gate(payload)
            hit = db.execute(text(
                "SELECT id, verbatim_sha256, corrected_fields "
                "  FROM lms_question_extraction "
                " WHERE verbatim_sha256 LIKE :s LIMIT 1"), {"s": sha + "%"}).fetchone()
            if not hit:
                missing += 1
                print(f"  MISSING  {sha[:16]}  no question carries this hash")
                continue
            if bad:
                failed += 1
                print(f"  GATE     {sha[:16]}")
                for b in bad:
                    print(f"             {b}")
                continue
            ok += 1
            if write:
                try:
                    cur = json.loads(hit[2]) if hit[2] else {}
                except Exception:
                    cur = {}
                cur[NS] = payload
                db.execute(text(
                    "UPDATE lms_question_extraction SET corrected_fields = :c "
                    " WHERE id = :i"), {"c": json.dumps(cur, ensure_ascii=False),
                                        "i": int(hit[0])})
        if write:
            db.commit()
    finally:
        db.close()
    print(f"\n  {ok} passed the gate, {failed} failed it, {missing} matched no question")
    print("  written" if write else "  dry run -- re-run with --apply")
    return 0 if not failed else 1


def report() -> int:
    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        tot = db.execute(text("SELECT COUNT(*) FROM lms_question_extraction")).scalar()
        have = db.execute(text(
            "SELECT COUNT(*) FROM lms_question_extraction "
            " WHERE corrected_fields IS NOT NULL AND corrected_fields <> ''")).scalar()
        print(f"  questions with a provenance row   {tot:>8,}")
        print(f"  carrying a PAL V4 sidecar         {have:>8,}\n")
        fill = {f: 0 for f in CORE_SIDECAR + RICH_SIDECAR}
        for (blob,) in db.execute(text(
            "SELECT corrected_fields FROM lms_question_extraction "
            " WHERE corrected_fields IS NOT NULL AND corrected_fields <> ''")).fetchall():
            try:
                p = json.loads(blob).get(NS, {})
            except Exception:
                continue
            for f in fill:
                v = p.get(f)
                if v not in (None, "", [], {}):
                    fill[f] += 1
        print("  Section 11 fill rate -- a low number is a finding, not a failure")
        print(f"  {'field':<28} {'filled':>8} {'of sidecars':>12}")
        print("  " + "-" * 52)
        for f in CORE_SIDECAR + RICH_SIDECAR:
            print(f"  {f:<28} {fill[f]:>8} {have:>12}")
    finally:
        db.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", help="a payload file: {'payloads': [{'sha', 'pal_v4'}]}")
    ap.add_argument("--apply", action="store_true", help="actually write")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.report or not a.file:
        return report()
    return apply_file(Path(a.file), a.apply)


if __name__ == "__main__":
    raise SystemExit(main())
