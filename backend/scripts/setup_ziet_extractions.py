"""Create the eight `document_extractions` rows for the KVS ZIET Mumbai bank.

    python -m scripts.setup_ziet_extractions            # report only
    python -m scripts.setup_ziet_extractions --apply    # INSERT

One row per (chapter x source document). Class 9 Mathematics chapters 1-8
already carry two rows each -- the NCERT textbook, and the KVS SSM question
set that put 278 questions in the bank -- and this is a third, different
document, so it gets its own rows rather than reusing theirs.

PDF_URL RECORDS WHERE THE FILE CAME FROM. The SSM rows record
`C:\\Users\\MILAN\\Downloads\\ilovepdf_split-range\\...`, a path on a machine
nobody else has, so those 278 questions can no longer be traced to a source.
This row records the shared Drive link the book was fetched from, which is
what makes the extraction re-checkable by someone else later.

Attribution is KVS ZIET Mumbai, not KVS RO Agra (publisher 1) and not NODIA
(publisher 6). They are different institutions and the publisher row is what
gets stamped on every question, so a new one is registered rather than
borrowing the nearest.

INSERT only. A chapter that already has a row for this document is skipped.
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

from scripts.parse_ziet_maths import SOURCE, SOURCE_URL  # noqa: E402

STANDARD_ID, SUBJECT_ID, STANDARD, SUBJECT = 42, 3976, 9, "Mathematics"
INST, SYEAR, BOARD = 1, 2026, "CBSE"
TITLE = "KVS ZIET Mumbai, TGT Mathematics question bank 2026-27"
PUB_CODE = "kvs_ziet_mumbai"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    raw = SOURCE.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    doc = fitz.open(SOURCE)
    pages = doc.page_count
    doc.close()
    print(f"{SOURCE.name}\n  {len(raw):,} bytes, {pages} pages, sha256 {sha[:16]}...\n"
          f"  {SOURCE_URL}\n")

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        chapters = db.execute(text(
            "SELECT id, sort_order, chapter_name FROM chapter_master "
            " WHERE standard_id=:s AND subject_id=:j AND sort_order BETWEEN 1 AND 8 "
            " ORDER BY sort_order"), {"s": STANDARD_ID, "j": SUBJECT_ID}).fetchall()
        have = {int(r[0]) for r in db.execute(text(
            "SELECT chapter_id FROM document_extractions WHERE pdf_url = :u"),
            {"u": SOURCE_URL}).fetchall()}

        pub = None
        if a.apply:
            pub = ensure_publisher(
                code=PUB_CODE,
                name="Kendriya Vidyalaya Sangathan, ZIET Mumbai",
                board=BOARD,
                licence_type="KVS website reuse policy",
            )
            print(f"publisher {PUB_CODE} -> id {pub['id'] if pub else '?'}\n")

        meta = json.dumps({
            "source": "KVS ZIET Mumbai TGT programme, Class 9 Mathematics",
            "source_url": SOURCE_URL,
            "layout": "split document -- questions pp 8-38, solutions pp 39-65",
            "parser": "scripts/parse_ziet_maths.py",
            "file_sha256": sha,
        })
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

        print(f"  {'ch':>3} {'cid':>7}  {'chapter':<38} action")
        print("  " + "-" * 68)
        made = 0
        for cid, so, name in chapters:
            cid, so = int(cid), int(so)
            if cid in have:
                print(f"  {so:>3} {cid:>7}  {str(name)[:38]:<38} SKIP, row exists")
                continue
            if a.apply:
                db.execute(ins, {"t": f"{name} -- {TITLE}", "n": so,
                                 "std": STANDARD, "sid": STANDARD_ID,
                                 "sn": SUBJECT, "jid": SUBJECT_ID, "cid": cid,
                                 "inst": INST, "b": BOARD, "y": SYEAR,
                                 "u": SOURCE_URL, "pc": pages, "meta": meta,
                                 "sha": sha, "pub": pub["id"] if pub else None})
                made += 1
            print(f"  {so:>3} {cid:>7}  {str(name)[:38]:<38} "
                  f"{'INSERT' if a.apply else 'would insert'}")
        if a.apply:
            db.commit()
            print(f"\ninserted {made} row(s)\n")
            rows = db.execute(text(
                "SELECT e.id, e.chapter_number, e.publisher_id, e.pdf_url "
                "  FROM document_extractions e WHERE e.pdf_url = :u "
                " ORDER BY e.chapter_number"), {"u": SOURCE_URL}).fetchall()
            print(f"  {'eid':>5} {'ch':>3} {'pub':>4}  pdf_url")
            print("  " + "-" * 68)
            for r in rows:
                print(f"  {r[0]:>5} {r[1]:>3} {str(r[2] or '-'):>4}  {str(r[3])[:52]}")
        else:
            print("\nreport only -- re-run with --apply")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
