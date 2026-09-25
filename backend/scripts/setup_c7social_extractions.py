"""Create the twenty `document_extractions` rows for Class 7 Social Science.

    python -m scripts.setup_c7social_extractions            # report only
    python -m scripts.setup_c7social_extractions --apply    # INSERT

The book is printed in two parts and the database splits it the same way:
Part 1's twelve chapters are the subject `Social Sciences`, Part 2's eight are
`Social Sciences-2`. THE PART IS WHAT DISAMBIGUATES, because the chapter
numbers restart -- "CHAP 1" is Geographical Diversity of India in Part 1 and
The Story of Indian Farming in Part 2, so a row keyed on chapter number alone
would put eight chapters' questions on the wrong subject.

Identity is content_sha256 + chapter_id. The file was mirrored from a pdf.tube
listing and the deep link for one file is not something to guess, so the
listing URL goes in `pdf_url` and the mirrored file name and its hash go in
`extraction_metadata`.

INSERT only. A chapter that already has a row for this file is skipped.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import fitz  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402
from app.services.publisher_service import ensure_publisher  # noqa: E402

from scripts.parse_c7_social import CHAPTERS, SOURCE, SOURCE_URL  # noqa: E402

STANDARD_ID, STANDARD = 40, 7
INST, SYEAR, BOARD = 1, 2026, "CBSE"
TITLE = "NODIA Class 7 Social Science Question Bank 2026 (Exploring Society)"
SUBJECT_OF_PART = {1: "Social Sciences", 2: "Social Sciences-2"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    raw = SOURCE.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    doc = fitz.open(SOURCE)
    pages = doc.page_count
    doc.close()
    print(f"{SOURCE.name}\n  {len(raw):,} bytes, {pages} pages, sha256 {sha[:16]}...\n")

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        by_part: dict[int, dict[int, tuple]] = {}
        for part, subj in SUBJECT_OF_PART.items():
            rows = db.execute(text(
                "SELECT c.id, c.sort_order, c.chapter_name, c.subject_id "
                "  FROM chapter_master c JOIN subject s ON s.id = c.subject_id "
                " WHERE c.standard_id = :s AND s.subject_name = :n "
                " ORDER BY c.sort_order"), {"s": STANDARD_ID, "n": subj}).fetchall()
            by_part[part] = {int(r[1]): (int(r[0]), r[2], int(r[3])) for r in rows}
        have = {int(r[0]) for r in db.execute(text(
            "SELECT chapter_id FROM document_extractions WHERE content_sha256 = :h"),
            {"h": sha}).fetchall()}

        pub = None
        if a.apply:
            pub = ensure_publisher(code="nodia", name="NODIA Press", board=BOARD)
            print(f"publisher nodia -> id {pub['id'] if pub else '?'}\n")

        ins = text("""
            INSERT INTO document_extractions
              (document_type, document_tittle, chapter_number, standard,
               standard_id, subject_name, subject_id, chapter_id,
               sub_institute_id, board, syear, pdf_url, page_count,
               image_extracted, extraction_metadata, content_sha256,
               extraction_status, publisher_id, updated_at)
            VALUES
              ('question_bank', :t, :n, :std, :sid, :sn, :jid, :cid,
               :inst, :b, :y, :u, :pc, 0, :meta, :sha, 'extracted', :pub, NOW())
        """)
        print(f"  {'pt':>2} {'ch':>3} {'cid':>7}  {'chapter':<46} {'folios':<10} action")
        print("  " + "-" * 92)
        made = 0
        for part, so, name, lo, hi in CHAPTERS:
            entry = by_part.get(part, {}).get(so)
            if not entry:
                print(f"  {part:>2} {so:>3} {'-':>7}  {name[:46]:<46} {f'{lo}-{hi}':<10} NO CHAPTER ROW")
                continue
            cid, db_name, subject_id = entry
            if cid in have:
                print(f"  {part:>2} {so:>3} {cid:>7}  {db_name[:46]:<46} "
                      f"{f'{lo}-{hi}':<10} SKIP, row exists")
                continue
            meta = json.dumps({
                "source": "NODIA Class 7 Social Science QB 2026",
                "textbook": "Exploring Society: India and Beyond (NEP-2020)",
                "source_listing": SOURCE_URL,
                "file_name": SOURCE.name, "file_sha256": sha,
                "part": part, "printed_folios": f"{lo}-{hi}",
                "parser": "scripts/parse_c7_social.py",
                "answer_marker": "AAns",
            })
            if a.apply:
                db.execute(ins, {"t": f"{db_name} -- {TITLE}", "n": so,
                                 "std": STANDARD, "sid": STANDARD_ID,
                                 "sn": SUBJECT_OF_PART[part], "jid": subject_id,
                                 "cid": cid, "inst": INST, "b": BOARD, "y": SYEAR,
                                 "u": SOURCE_URL, "pc": pages, "meta": meta,
                                 "sha": sha, "pub": pub["id"] if pub else None})
                made += 1
            print(f"  {part:>2} {so:>3} {cid:>7}  {db_name[:46]:<46} "
                  f"{f'{lo}-{hi}':<10} {'INSERT' if a.apply else 'would insert'}")
        if a.apply:
            db.commit()
            print(f"\ninserted {made} row(s)\n")
            for r in db.execute(text(
                "SELECT e.id, e.subject_name, e.chapter_number, e.chapter_id "
                "  FROM document_extractions e WHERE e.content_sha256=:h "
                " ORDER BY e.subject_name, e.chapter_number"), {"h": sha}).fetchall():
                print(f"  eid={r[0]:<5} {str(r[1]):<20} ch={r[2]:<3} cid={r[3]}")
        else:
            print("\nreport only -- re-run with --apply")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
