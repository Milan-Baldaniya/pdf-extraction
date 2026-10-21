"""Read the loaded NCERT Class X HPE bank back out of the database.

    python -m scripts.audit_ncert_hpe10_bank
    python -m scripts.audit_ncert_hpe10_bank --sample 4 --chapter 5

Reads only. It answers four questions a load report cannot:

  1. Is there a question row per chapter, on the chapter we intended?  A load
     that writes to the wrong chapter_id reports success either way, and this
     estate has already had 2,545 questions land under the wrong chapter with
     zero failures.
  2. Did the answer survive?  `lms_question_master.answer` is utf8mb3, so a
     4-byte character rejects the whole row and the writer's retry cannot
     recover -- the symptom is a missing row, not a warning.
  3. Is the provenance readable from the row?  Publisher, licence and the
     attribution line are a licence condition, and `tagged_by` is what tells a
     later reviewer these answers were derived rather than printed.
  4. Do the questions read like real questions?  The sample prints stems and
     model answers in full so a human can see them.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import fitz  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

from scripts.shape_ncert_hpe10_for_load import (  # noqa: E402
    ALIGNMENT, MIRROR, PUBLISHER, contains, dehyphenate, norm,
)

IDS = [row["chapter_id"] for row in ALIGNMENT]
BY_ID = {row["chapter_id"]: row for row in ALIGNMENT}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", type=int, default=2,
                    help="items to print per chapter")
    ap.add_argument("--chapter", type=int, help="print the sample for one chapter only")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    ids = ", ".join(str(i) for i in IDS)
    try:
        pub = db.execute(text(
            "SELECT id, code, name, short_name, publisher_type, licence_type, "
            "       attribution_required FROM question_publisher WHERE code = :c"),
            {"c": PUBLISHER}).mappings().fetchone()
        print("PUBLISHER")
        if not pub:
            print(f"  {PUBLISHER} is NOT registered")
        else:
            for key, value in dict(pub).items():
                print(f"  {key:<20} {value}")

        print("\nPER CHAPTER")
        head = (f"{'n':<3} {'chapter_id':<11} {'questions':>9} {'answered':>9} "
                f"{'held':>5} {'pal':>5} {'derived':>8}  chapter_name")
        print(head)
        print("-" * len(head))
        rows = db.execute(text(f"""
            SELECT c.id AS chapter_id, c.chapter_name,
                   COUNT(q.id) AS questions,
                   SUM(CASE WHEN JSON_EXTRACT(q.answer, '$.model_answer')
                                 IS NOT NULL
                             AND JSON_UNQUOTE(JSON_EXTRACT(q.answer,
                                 '$.model_answer')) <> 'null'
                            THEN 1 ELSE 0 END) AS answered,
                   SUM(CASE WHEN e.validation_status = 'failed'
                            THEN 1 ELSE 0 END) AS held,
                   COUNT(m.id) AS pal_rows,
                   SUM(CASE WHEN m.tagged_by = 'derived' THEN 1 ELSE 0 END)
                       AS derived
              FROM chapter_master c
              LEFT JOIN lms_question_master q ON q.chapter_id = c.id
              LEFT JOIN lms_question_extraction e ON e.question_id = q.id
              LEFT JOIN pal_question_metadata m ON m.question_id = q.id
             WHERE c.id IN ({ids})
             GROUP BY c.id, c.chapter_name
             ORDER BY c.sort_order, c.id
        """)).mappings().fetchall()
        total = {"q": 0, "ans": 0, "held": 0, "pal": 0, "derived": 0}
        for r in rows:
            n = BY_ID[r["chapter_id"]]["n"]
            print(f"{n:<3} {r['chapter_id']:<11} {r['questions'] or 0:>9} "
                  f"{int(r['answered'] or 0):>9} {int(r['held'] or 0):>5} "
                  f"{r['pal_rows'] or 0:>5} {int(r['derived'] or 0):>8}  "
                  f"{r['chapter_name']}")
            total["q"] += r["questions"] or 0
            total["ans"] += int(r["answered"] or 0)
            total["held"] += int(r["held"] or 0)
            total["pal"] += r["pal_rows"] or 0
            total["derived"] += int(r["derived"] or 0)
        print("-" * len(head))
        print(f"{'ALL':<3} {'':<11} {total['q']:>9} {total['ans']:>9} "
              f"{total['held']:>5} {total['pal']:>5} {total['derived']:>8}")

        print("\nFORMS AND SECTIONS")
        for r in db.execute(text(f"""
            SELECT e.item_form, e.exam_section, COUNT(*) n,
                   SUM(e.section_marks) marks
              FROM lms_question_extraction e
              JOIN lms_question_master q ON q.id = e.question_id
             WHERE q.chapter_id IN ({ids})
             GROUP BY e.item_form, e.exam_section
             ORDER BY e.exam_section, n DESC
        """)).mappings():
            print(f"  {r['exam_section']}  {r['item_form']:<18} {r['n']:>4} "
                  f"items, {r['marks'] or 0:>4} marks")

        print("\nNON-ASCII IN ANY STORED ANSWER OR STEM")
        bad = db.execute(text(f"""
            SELECT q.id, LEFT(q.question_title, 60) stem
              FROM lms_question_master q
             WHERE q.chapter_id IN ({ids})
               AND (CONVERT(q.question_title USING ASCII)
                    <> CONVERT(q.question_title USING utf8mb4)
                 OR CONVERT(q.answer USING ASCII)
                    <> CONVERT(q.answer USING utf8mb4))
             LIMIT 10
        """)).mappings().fetchall()
        print(f"  {len(bad)} row(s) carry a non-ASCII character"
              + ("" if not bad else ":"))
        for r in bad:
            print(f"    {r['id']}  {r['stem']}")

        # The end-to-end check. Everything above reads the database against
        # itself; this reads the database against the SOURCE, going back to the
        # mirrored PDF and asking whether the question stored under this chapter
        # is really printed in that chapter. It is the check that would catch a
        # whole chapter filed one row along -- the failure mode that put 2,545
        # questions under the wrong chapter elsewhere in this estate and
        # reported no errors at all.
        print("\nEVERY STORED STEM RE-READ FROM THE MIRRORED PDF")
        head = f"{'n':<3} {'chapter_id':<11} {'stems':>6} {'on page':>8}  verdict"
        print(head)
        print("-" * len(head))
        worst: list[str] = []
        for r in rows:
            row = BY_ID[r["chapter_id"]]
            if not r["questions"]:
                continue
            doc = fitz.open(MIRROR / row["file"])
            raw = "\n".join(p.get_text("text") for p in doc)
            doc.close()
            chapter = (norm(raw), dehyphenate(raw))
            stems = db.execute(text(
                "SELECT q.id, q.question_title, e.item_number, e.reproduction "
                "  FROM lms_question_master q "
                "  JOIN lms_question_extraction e ON e.question_id = q.id "
                " WHERE q.chapter_id = :c"),
                {"c": r["chapter_id"]}).mappings().fetchall()
            hits = 0
            for s in stems:
                if contains(chapter, s["question_title"] or ""):
                    hits += 1
                elif s["reproduction"] == "verbatim":
                    worst.append(f"    ch{row['n']} {s['item_number']} "
                                 f"[{s['id']}] {(s['question_title'] or '')[:80]}")
            adapted = sum(1 for s in stems if s["reproduction"] != "verbatim")
            verdict = ("all verbatim stems found"
                       if hits + adapted >= len(stems) else "MISMATCH")
            print(f"{row['n']:<3} {r['chapter_id']:<11} {len(stems):>6} "
                  f"{hits:>8}  {verdict}"
                  + (f" ({adapted} adapted, checked by grounding)"
                     if adapted else ""))
        if worst:
            print(f"  {len(worst)} verbatim stem(s) NOT found in their chapter:")
            for line in worst[:20]:
                print(line)
        else:
            print("  no verbatim stem is missing from its own chapter PDF")

        print("\nSAMPLE")
        for r in rows:
            n = BY_ID[r["chapter_id"]]["n"]
            if a.chapter and n != a.chapter:
                continue
            if not r["questions"]:
                continue
            print(f"\n--- chapter {n}: {r['chapter_name']}")
            print(f"    NCERT heading: {BY_ID[r['chapter_id']]['ncert']}")
            src = db.execute(text(
                "SELECT DISTINCT d.pdf_url FROM document_extractions d "
                " WHERE d.chapter_id = :c AND d.document_type='question_bank'"),
                {"c": r["chapter_id"]}).scalars().all()
            for url in src:
                print(f"    pdf_url: {url}")
            for item in db.execute(text("""
                SELECT q.id, q.question_title, q.points, q.answer,
                       e.item_number, e.item_form, e.exam_section,
                       e.section_heading, e.source_page, e.attribution,
                       e.licence, e.reproduction, e.validation_status,
                       e.bloom_level, e.dok_level, e.difficulty_1_to_5,
                       m.tagged_by, m.quality_status, m.blueprint_category
                  FROM lms_question_master q
                  JOIN lms_question_extraction e ON e.question_id = q.id
                  LEFT JOIN pal_question_metadata m ON m.question_id = q.id
                 WHERE q.chapter_id = :c
                 ORDER BY e.item_ordinal LIMIT :k
            """), {"c": r["chapter_id"], "k": a.sample}).mappings():
                env = {}
                try:
                    env = json.loads(item["answer"] or "{}")
                except ValueError:
                    pass
                print(f"    [{item['id']}] {item['item_number']} "
                      f"{item['item_form']} / section {item['exam_section']} / "
                      f"{item['points']} mark(s) / folio {item['source_page']} / "
                      f"{item['validation_status']}")
                print(f"      heading  : {item['section_heading']}")
                print(f"      Q        : {item['question_title']}")
                print(f"      A        : {env.get('model_answer')}")
                if env.get("options"):
                    for o in env["options"]:
                        mark = "*" if o["is_correct"] else " "
                        print(f"        {mark}{o['label']}. {o['text']}")
                print(f"      tags     : bloom={item['bloom_level']} "
                      f"dok={item['dok_level']} diff={item['difficulty_1_to_5']} "
                      f"blueprint={item['blueprint_category']}")
                print(f"      provenance: tagged_by={item['tagged_by']} "
                      f"quality={item['quality_status']} "
                      f"reproduction={item['reproduction']} "
                      f"licence={item['licence']}")
                print(f"      attribution: {item['attribution']}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
