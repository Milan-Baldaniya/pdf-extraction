"""Create the four `document_extractions` rows for the KVS ZIET Mysuru SSM.

    python -m scripts.setup_kvs_ssm_c9_extractions            # report only
    python -m scripts.setup_kvs_ssm_c9_extractions --apply    # INSERT

One row per (chapter x source document), for the four Class 9 Mathematics
chapters this book can serve.

PDF_URL RECORDS WHERE THE FILE CAME FROM, not where it happens to sit on this
laptop. The earlier KVS SSM load recorded
`C:\\Users\\MILAN\\Downloads\\ilovepdf_split-range\\...` against all eight of
its chapters, and those 278 questions can no longer be traced to anything:
nobody else has that path and the file name does not name the book. This row
records the ZIET Mysuru portal's own link, and the mirrored file is byte for
byte what that link serves -- 7,015,181 bytes, checked -- so the extraction
stays re-checkable by someone who was not here.

Attribution is KVS ZIET MYSURU. It is not KVS RO Agra (publisher 1) and not
KVS ZIET Mumbai (publisher 7): a Zonal Institute of Education and Training is
its own institution, the publisher row is stamped on every question, and the
nearest available name is not the right one.

THE CHAPTER MAPPING IS THE POINT OF THIS SCRIPT, so it is spelled out rather
than derived. Our rows follow the NEP Ganita Prakash naming and this book
follows the syllabus that preceded it, so the names do not match and no lookup
would find them. Each pairing below was confirmed twice: by reading the source
span, and against `lms_units.unit_chapters`, which still lists the old
syllabus names against the same unit the new chapter hangs off.

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

from scripts.parse_kvs_ssm_c9_maths import (  # noqa: E402
    CHAPTERS, PORTAL_URL, SOURCE, SOURCE_URL,
)

STANDARD_ID, SUBJECT_ID, STANDARD, SUBJECT = 42, 3976, 9, "Mathematics"
INST, SYEAR, BOARD = 1, 2026, "CBSE"
TITLE = "KVS ZIET Mysuru Student Support Material 2025-26"
PUB_CODE = "kvs_ziet_mysuru"

# our sort_order -> the PDF chapter that serves it
BY_SORT = {meta["our_sort"]: (ch, meta) for ch, meta in CHAPTERS.items()}


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
          f"  {SOURCE_URL}\n  listed on {PORTAL_URL}\n")

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        chapters = db.execute(text(
            "SELECT id, sort_order, chapter_name FROM chapter_master "
            " WHERE standard_id = :s AND subject_id = :j "
            "   AND sort_order IN :want ORDER BY sort_order"),
            {"s": STANDARD_ID, "j": SUBJECT_ID,
             "want": tuple(sorted(BY_SORT))}).fetchall()
        if len(chapters) != len(BY_SORT):
            raise SystemExit(f"expected {len(BY_SORT)} chapter rows, found "
                             f"{len(chapters)} -- check the mapping")

        # THESE FOUR CHAPTERS MUST STILL BE EMPTY. They were chosen because
        # they hold nothing; if one has acquired questions since, the reason
        # for touching it has gone and this should be looked at rather than
        # added to.
        for cid, so, name in chapters:
            held = db.execute(text(
                "SELECT COUNT(*) FROM lms_question_master WHERE chapter_id = :c"),
                {"c": int(cid)}).scalar()
            if held:
                raise SystemExit(f"chapter {cid} (sort {so}, {name}) already holds "
                                 f"{held} question(s) -- stopping")

        have = {int(r[0]) for r in db.execute(text(
            "SELECT chapter_id FROM document_extractions WHERE pdf_url = :u"),
            {"u": SOURCE_URL}).fetchall()}

        pub = None
        if a.apply:
            pub = ensure_publisher(
                code=PUB_CODE,
                name="Kendriya Vidyalaya Sangathan, ZIET Mysuru",
                board=BOARD,
                licence_type="KVS website reuse policy",
            )
            print(f"publisher {PUB_CODE} -> id {pub['id'] if pub else '?'}\n")

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

        print(f"  {'ch':>3} {'cid':>7}  {'our chapter':<44} {'pdf ch':>6} "
              f"{'pages':>8}  action")
        print("  " + "-" * 96)
        made = 0
        for cid, so, name in chapters:
            cid, so = int(cid), int(so)
            pdf_ch, meta = BY_SORT[so]
            lo, hi = meta["pages"]
            if name.strip() != meta["our_name"]:
                raise SystemExit(f"sort {so} is {name!r}, the mapping expects "
                                 f"{meta['our_name']!r} -- stopping")
            if cid in have:
                print(f"  {so:>3} {cid:>7}  {name[:44]:<44} {pdf_ch:>6} "
                      f"{f'{lo}-{hi}':>8}  SKIP, row exists")
                continue
            body = json.dumps({
                "source": "KVS ZIET Mysuru Student Support Material, "
                          "Class 9 Mathematics 2025-26",
                "source_url": SOURCE_URL,
                "portal_url": PORTAL_URL,
                "pdf_chapter": pdf_ch,
                "pdf_chapter_title": meta["title"],
                "pdf_pages": f"{lo}-{hi}",
                "printed_folio_offset": -5,
                "layout": "worked half with inline solutions, then an EXERCISE "
                          "half answered by a key at the end of the chapter",
                "edition_note": "old-syllabus chapter mapped onto the NEP Ganita "
                                "Prakash row for the same content",
                "parser": "scripts/parse_kvs_ssm_c9_maths.py",
                "file_sha256": sha,
            })
            if a.apply:
                db.execute(ins, {"t": f"{name} -- {TITLE}", "n": so,
                                 "std": STANDARD, "sid": STANDARD_ID,
                                 "sn": SUBJECT, "jid": SUBJECT_ID, "cid": cid,
                                 "inst": INST, "b": BOARD, "y": SYEAR,
                                 "u": SOURCE_URL, "pc": pages, "meta": body,
                                 "sha": sha, "pub": pub["id"] if pub else None})
                made += 1
            print(f"  {so:>3} {cid:>7}  {name[:44]:<44} {pdf_ch:>6} "
                  f"{f'{lo}-{hi}':>8}  {'INSERT' if a.apply else 'would insert'}")

        if a.apply:
            db.commit()
            print(f"\ninserted {made} row(s)\n")
            rows = db.execute(text(
                "SELECT id, chapter_number, chapter_id, publisher_id, pdf_url "
                "  FROM document_extractions WHERE pdf_url = :u "
                " ORDER BY chapter_number"), {"u": SOURCE_URL}).fetchall()
            print(f"  {'eid':>5} {'ch':>3} {'cid':>7} {'pub':>4}  pdf_url")
            print("  " + "-" * 92)
            for r in rows:
                print(f"  {r[0]:>5} {r[1]:>3} {r[2]:>7} {str(r[3] or '-'):>4}  "
                      f"{str(r[4])[:66]}")
        else:
            print("\nreport only -- re-run with --apply")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
