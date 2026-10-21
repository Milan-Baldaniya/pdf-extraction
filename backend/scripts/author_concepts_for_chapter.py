"""Write topics and concepts for a chapter, anchored on its own extracted text.

    python -m scripts.author_concepts_for_chapter --file concept_drafts/ch38400.json
    python -m scripts.author_concepts_for_chapter --file concept_drafts/ch38400.json --apply

For the 19 Classes 6-10 chapters that hold questions but carry ZERO rows in
lms_concept (found via a frontend check: filtering the Question Bank by a
concept that does not exist returns nothing, even though the chapter's own
questions clearly test it). Linking cannot fix this -- there is nothing to link
TO. This is the upstream step: writing the concepts themselves.

The input is one JSON file per chapter, written after actually reading the
chapter's own extracted text (never from a bare description):

    {"chapter_id": N, "extraction_id": N, "topic": {"name": "...",
       "description": "...", "source_evidence": "<verbatim quote>"},
     "concepts": [{"name": "...", "description": "...", "definition": "...",
       "source_evidence": "<verbatim quote>"}]}

THE GUARD IS THE SAME ONE THE SESSION HAS USED THROUGHOUT: every
`source_evidence` string must appear in the chapter's own
`document_extractions.md_content` **exactly once**. Two matches means the
anchor is ambiguous (it could be the teacher's front-matter mentioning the
same phrase, not the actual text); zero means it was mistyped or paraphrased
rather than quoted. Either refuses the whole file. This mirrors the anchor
discipline documented in memory: OCR corrupts this estate's PDFs with
Devanagari digit lookalikes for Latin letters (४०५ for various letters), which
makes it easy to anchor on a phrase that "looks right" but doesn't match the
byte-for-byte extracted text -- so the ONLY test that means anything is doing
the count() and reading the surrounding text yourself.

A LITERATURE-CHAPTER TRAP THIS SCRIPT CANNOT SEE: many of these extractions
open with the teacher's handbook front matter for several units, which can
mention a poem's title long before the poem's own text appears far later in
the same document. `The Ant and the Cricket` matched at position 5894 in its
chapter's extraction, in a page of general teaching notes; the real poem was
at position 33829. Confirm you are quoting the STUDENT-FACING text, not
commentary about it, before writing an anchor -- the count() check cannot tell
the difference between the two if a phrase happens to appear in both.

Shared field values (mastery_threshold, estimated_mastery_minutes, syear,
sub_institute_id) are read from a sibling row already in the same standard, so
a new chapter's rows read like the ones a reader wrote by hand.

Nothing existing is touched: this only INSERTs into topic_master and
lms_concept for a chapter that currently has zero rows in either. If the
chapter already has any concept, the whole file is refused rather than adding
a second, possibly-duplicate set.
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

DRAFTS = Path(__file__).resolve().parent / "concept_drafts"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    path = Path(__file__).resolve().parent / a.file
    doc = json.loads(path.read_text(encoding="utf-8"))
    chapter = int(doc["chapter_id"])
    extraction_id = int(doc["extraction_id"])
    topic = doc["topic"]
    concepts = doc["concepts"]

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        ch = db.execute(text(
            "SELECT chapter_name, standard_id, subject_id FROM chapter_master "
            " WHERE id = :c"), {"c": chapter}).fetchone()
        if not ch:
            raise SystemExit(f"chapter {chapter} does not exist")
        print(f"  chapter {chapter}: {ch[0]}")

        existing = db.execute(text(
            "SELECT COUNT(*) FROM lms_concept WHERE chapter_id = :c"),
            {"c": chapter}).scalar()
        if existing:
            print(f"  REFUSED -- chapter {chapter} already has {existing} "
                  f"concept(s). This script only fills a chapter that has "
                  f"none, so a second set is never written on top of one "
                  f"that exists.")
            return 1

        md = db.execute(text(
            "SELECT md_content FROM document_extractions WHERE id = :e"),
            {"e": extraction_id}).scalar()
        if not md:
            raise SystemExit(f"extraction {extraction_id} has no md_content")

        problems = []
        for label, ev in [("topic", topic["source_evidence"])] + [
                (f"concept {i+1} ({c['name']!r})", c["source_evidence"])
                for i, c in enumerate(concepts)]:
            n = md.count(ev)
            if n != 1:
                problems.append(f"{label}: anchor appears {n} time(s) in the "
                                f"extraction, need exactly 1 -- {ev[:60]!r}")

        nq = db.execute(text(
            "SELECT COUNT(*) FROM lms_question_master WHERE chapter_id = :c "
            " AND deleted_at IS NULL"), {"c": chapter}).scalar()
        print(f"  {nq} live question(s) in this chapter")
        print(f"  topic: {topic['name']!r}")
        for c in concepts:
            print(f"   concept: {c['name']!r}")

        if problems:
            print(f"\n  REFUSED -- {len(problems)} anchor problem(s):")
            for p in problems:
                print(f"    ! {p}")
            return 1

        if not a.apply:
            print("\n  dry run only -- re-run with --apply")
            return 0

        sib_std = int(ch[1])
        sib = db.execute(text(
            "SELECT t.sub_institute_id, t.syear FROM topic_master t "
            "  JOIN chapter_master c ON c.id = t.chapter_id "
            " WHERE c.standard_id = :s LIMIT 1"), {"s": sib_std}).fetchone()
        sub_inst, syear = (sib if sib else (1, 2026))
        conc_defaults = db.execute(text(
            "SELECT mastery_threshold, estimated_mastery_minutes "
            "  FROM lms_concept WHERE standard_id = :s LIMIT 1"),
            {"s": sib_std}).fetchone()
        mastery, mins = conc_defaults if conc_defaults else (85.0, 15)

        db.execute(text(
            "INSERT INTO topic_master (sub_institute_id, chapter_id, "
            "  extraction_id, main_topic_id, name, description, "
            "  estimated_minutes, topic_show_hide, topic_sort_order, syear, "
            "  source_evidence, evidence_verified, confidence) "
            "VALUES (:si, :c, :e, 0, :n, :d, 45, 1, 1, :y, :ev, 1, 0.700)"),
            {"si": sub_inst, "c": chapter, "e": extraction_id,
             "n": topic["name"][:255], "d": topic["description"],
             "y": syear, "ev": topic["source_evidence"][:512]})
        topic_id = db.execute(text(
            "SELECT id FROM topic_master WHERE chapter_id = :c "
            " ORDER BY id DESC LIMIT 1"), {"c": chapter}).scalar()

        for c in concepts:
            db.execute(text(
                "INSERT INTO lms_concept (extraction_id, name, description, "
                "  definition, subject_id, standard_id, chapter_id, "
                "  topic_id, sub_institute_id, mastery_threshold, "
                "  estimated_mastery_minutes, syear, source_evidence, "
                "  evidence_verified, confidence, confidence_profile, "
                "  review_status, concept_show_hide) "
                "VALUES (:e, :n, :d, :def, :subj, :std, :c, :t, :si, "
                "  :mast, :mins, :y, :ev, 1, 0.700, 'curriculum', "
                "  'low_confidence', 1)"),
                {"e": extraction_id, "n": c["name"][:255],
                 "d": c["description"], "def": c.get("definition") or c["description"],
                 "subj": int(ch[2]), "std": sib_std, "c": chapter, "t": topic_id,
                 "si": sub_inst, "mast": mastery, "mins": mins, "y": syear,
                 "ev": c["source_evidence"][:512]})
        db.commit()
        print(f"\n  wrote topic {topic_id} and {len(concepts)} concept(s) "
              f"for chapter {chapter}")
        print("  review_status is 'low_confidence' by design: a human-authored "
              "concept has\n  no automated grounding score, so it is marked for "
              "review rather than passed\n  off as machine-verified.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
