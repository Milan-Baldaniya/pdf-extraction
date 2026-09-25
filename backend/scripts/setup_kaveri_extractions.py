"""Create the eight `document_extractions` rows for the Class 9 English bank.

    python -m scripts.setup_kaveri_extractions            # report only
    python -m scripts.setup_kaveri_extractions --apply    # INSERT

One row per (chapter x source document), for the NODIA "QB 2026" Class 9
English book, whose eight prose chapters are exactly the eight chapters the
database holds.

IDENTITY IS content_sha256 + chapter_id, NOT pdf_url. The ZIET bank could
record the shared Drive link it was fetched from; this one was mirrored from
a pdf.tube listing, and the deep link for an individual file is not something
to guess -- a pdf_url that 404s is worse than one that points at the listing.
So the listing URL goes in `pdf_url`, the mirrored file name and its sha256 go
in `extraction_metadata`, and re-running matches on the hash.

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

from scripts.parse_kaveri_english import PROSE, SOURCE, SOURCE_URL  # noqa: E402

STANDARD_ID, SUBJECT_ID, STANDARD, SUBJECT = 42, 3978, 9, "English"
INST, SYEAR, BOARD = 1, 2026, "CBSE"
TITLE = "NODIA Class 9 English Question Bank 2026, Kaveri prose section"


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
        chapters = db.execute(text(
            "SELECT id, sort_order, chapter_name FROM chapter_master "
            " WHERE standard_id=:s AND subject_id=:j ORDER BY sort_order"),
            {"s": STANDARD_ID, "j": SUBJECT_ID}).fetchall()
        by_sort = {int(r[1]): (int(r[0]), r[2]) for r in chapters}
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
        print(f"  {'ch':>3} {'cid':>7}  {'chapter':<40} {'folios':<10} action")
        print("  " + "-" * 82)
        made = 0
        for so, name, lo, hi in PROSE:
            if so not in by_sort:
                print(f"  {so:>3} {'-':>7}  {name[:40]:<40} {f'{lo}-{hi}':<10} NO CHAPTER ROW")
                continue
            cid, db_name = by_sort[so]
            if cid in have:
                print(f"  {so:>3} {cid:>7}  {db_name[:40]:<40} {f'{lo}-{hi}':<10} SKIP, row exists")
                continue
            meta = json.dumps({
                "source": "NODIA Class 9 English QB 2026 (Kaveri)",
                "source_listing": SOURCE_URL,
                "file_name": SOURCE.name,
                "file_sha256": sha,
                "printed_folios": f"{lo}-{hi}",
                "parser": "scripts/parse_kaveri_english.py",
                "note": "Poorvi/Kaveri, the NEP-2020 book. Beehive is a "
                        "different textbook and none of its texts are held.",
            })
            if a.apply:
                db.execute(ins, {"t": f"{db_name} -- {TITLE}", "n": so,
                                 "std": STANDARD, "sid": STANDARD_ID,
                                 "sn": SUBJECT, "jid": SUBJECT_ID, "cid": cid,
                                 "inst": INST, "b": BOARD, "y": SYEAR,
                                 "u": SOURCE_URL, "pc": pages, "meta": meta,
                                 "sha": sha, "pub": pub["id"] if pub else None})
                made += 1
            print(f"  {so:>3} {cid:>7}  {db_name[:40]:<40} {f'{lo}-{hi}':<10} "
                  f"{'INSERT' if a.apply else 'would insert'}")
        if a.apply:
            db.commit()
            print(f"\ninserted {made} row(s)\n")
            for r in db.execute(text(
                "SELECT id, chapter_number, chapter_id, publisher_id "
                "  FROM document_extractions WHERE content_sha256=:h "
                " ORDER BY chapter_number"), {"h": sha}).fetchall():
                print(f"  eid={r[0]:<5} ch={r[1]:<3} cid={r[2]:<7} pub={r[3]}")
        else:
            print("\nreport only -- re-run with --apply")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
