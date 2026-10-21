"""Create `document_extractions` rows for the studentbro Malhar Hindi banks.

    python -m scripts.setup_studentbro_extractions --book c6
    python -m scripts.setup_studentbro_extractions --book c6 --apply

One row per chapter, `document_type='question_bank'`. INSERT only: a chapter
that already has a row for this file is skipped, and nothing existing is
touched.

WHY A NEW ROW RATHER THAN THE ONE ALREADY THERE. Every one of these 23 chapters
already has a `document_extractions` row -- but it is `document_type='Chapter'`
and its `pdf_url` is the NCERT textbook PDF. Hanging a commercial publisher's
question bank off it would attribute this material to NCERT and lose the only
record of where it came from.

WHY THE PUBLISHER MATTERS HERE. studentbro is a commercial publisher's
editorial content, not government material, and it is ingested on the condition
that it stays identifiable. `publisher_id` is set on every row and `pdf_url`
holds the real source page, so the whole haul can be found -- and removed -- with
one query if the licensing position changes:

    SELECT * FROM document_extractions
     WHERE publisher_id = (SELECT id FROM question_publisher WHERE code='studentbro');
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata as ud
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import fitz  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402
from app.services.publisher_service import ensure_publisher  # noqa: E402

from scripts.parse_studentbro_hindi import BOOKS, MIRROR, PUBLISHER  # noqa: E402

INST, SYEAR, BOARD = 1, 2026, "CBSE"

PUBLISHER_NAME = "StudentBro"
LICENCE = (
    "Commercial publisher's editorial content, reproduced with the account "
    "owner's approval on condition that the source stays identifiable. Not "
    "government material and not licensed for redistribution -- review before "
    "publishing outside this estate."
)


def _fold(t: str) -> str:
    """Compare-key that keeps Devanagari, including its combining marks."""
    text_ = ud.normalize("NFC", t or "").casefold()
    return "".join(c for c in text_ if ud.category(c)[0] in ("L", "N", "M"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", choices=sorted(BOOKS), required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    cfg = BOOKS[a.book]
    folder = MIRROR / cfg["dir"]
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT c.id, c.sort_order, c.chapter_name, c.subject_id "
            "  FROM chapter_master c JOIN subject s ON s.id = c.subject_id "
            " WHERE c.standard_id = :s AND s.subject_name = :n "
            " ORDER BY c.sort_order, c.id"),
            {"s": cfg["standard_id"], "n": cfg["subject"]}).fetchall()
        by_order: dict[int, tuple[int, str, int]] = {}
        for r in rows:
            by_order.setdefault(int(r[1]), (int(r[0]), r[2], int(r[3])))
        print(f"{len(rows)} chapter row(s) for standard {cfg['standard_id']} "
              f"{cfg['subject']}\n")

        pub = None
        if a.apply:
            pub = ensure_publisher(code=PUBLISHER, name=PUBLISHER_NAME,
                                   board=BOARD, licence_type=LICENCE)
            print(f"publisher {PUBLISHER} -> id {pub['id'] if pub else '?'}\n")

        ins = text("""
            INSERT INTO document_extractions
              (document_type, document_tittle, chapter_number, standard,
               standard_id, subject_name, subject_id, chapter_id,
               sub_institute_id, board, syear, pdf_url, page_count,
               image_extracted, extraction_metadata, content_sha256,
               extraction_status, publisher_id, created_at, updated_at)
            VALUES
              ('question_bank', :t, :n, :std, :sid, :sn, :jid, :cid,
               :inst, :b, :y, :u, :pc, 0, :meta, :sha, 'extracted', :pub,
               NOW(), NOW())
        """)

        print(f"  {'ch':>3} {'cid':>7} {'eid':>6} {'pages':>5}  "
              f"{'chapter (db)':<40} action")
        print("  " + "-" * 92)
        made = 0
        for number, name in cfg["chapters"]:
            src = folder / f"ch{number:02d}.pdf"
            entry = by_order.get(number)
            if not entry:
                print(f"  {number:>3} {'-':>7} {'-':>6} {'-':>5}  "
                      f"{name[:40]:<40} NO CHAPTER ROW")
                continue
            cid, db_name, subject_id = entry
            if not src.exists():
                print(f"  {number:>3} {cid:>7} {'-':>6} {'-':>5}  "
                      f"{db_name[:40]:<40} NO MIRRORED FILE")
                continue

            raw = src.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            doc = fitz.open(src)
            pages = doc.page_count
            doc.close()

            info = manifest["files"].get(src.name) or {}
            if info.get("sha256") and info["sha256"] != sha:
                print(f"  {number:>3} {cid:>7} {'-':>6} {pages:>5}  "
                      f"{db_name[:40]:<40} SHA DOES NOT MATCH THE MANIFEST")
                continue
            # The page the download button lives on, not the asset: the asset
            # name is the server's sanitisation of a Devanagari title and is
            # neither readable nor stable, and the page is what a licensing
            # review would be pointed at.
            url = info.get("page_url") or cfg["listing"]

            existing = db.execute(text(
                "SELECT id FROM document_extractions "
                " WHERE content_sha256 = :h AND chapter_id = :c"),
                {"h": sha, "c": cid}).fetchone()
            if existing:
                print(f"  {number:>3} {cid:>7} {existing[0]:>6} {pages:>5}  "
                      f"{db_name[:40]:<40} SKIP, row exists")
                continue

            note = None
            if _fold(db_name) != _fold(name):
                note = f"db name {db_name!r} vs registry {name!r}"
            official = (cfg.get("official_names") or {}).get(number)
            if official:
                note = (f"db/registry name {db_name!r} is wording about the "
                        f"lesson; the book, the publisher slug and the stems "
                        f"all name it {official!r}. Same chapter, matched on "
                        f"position and content.")

            meta = json.dumps({
                "source": cfg["title"], "textbook": cfg["textbook"],
                "book": a.book, "publisher": PUBLISHER,
                "source_listing": cfg["listing"],
                "source_page": url,
                "source_asset": info.get("url"),
                "server_filename": info.get("server_filename"),
                "file_name": src.name, "file_sha256": sha,
                "downloaded_bytes": info.get("bytes"),
                "declared_content_length": info.get("declared"),
                "parser": "scripts/parse_studentbro_hindi.py",
                "answer_marker": cfg["marker"],
                "chapter_name_note": note,
            }, ensure_ascii=False)

            eid = "-"
            if a.apply:
                res = db.execute(ins, {
                    "t": f"{db_name} -- {cfg['title']}", "n": number,
                    "std": cfg["standard"], "sid": cfg["standard_id"],
                    "sn": cfg["subject"], "jid": subject_id, "cid": cid,
                    "inst": INST, "b": BOARD, "y": SYEAR, "u": url,
                    "pc": pages, "meta": meta, "sha": sha,
                    "pub": pub["id"] if pub else None})
                eid = res.lastrowid
                made += 1
            print(f"  {number:>3} {cid:>7} {str(eid):>6} {pages:>5}  "
                  f"{db_name[:40]:<40} {'INSERT' if a.apply else 'would insert'}")
            if note:
                print(f"      note: {note}")

        if a.apply:
            db.commit()
            print(f"\ninserted {made} row(s)\n")
            for r in db.execute(text(
                "SELECT d.id, d.chapter_number, d.chapter_id, d.page_count, d.pdf_url "
                "  FROM document_extractions d "
                " WHERE d.document_type = 'question_bank' AND d.standard_id = :s "
                "   AND d.subject_name = :n AND d.extraction_metadata LIKE :tag "
                " ORDER BY d.chapter_number"),
                {"s": cfg["standard_id"], "n": cfg["subject"],
                 "tag": f'%"book": "{a.book}"%'}).fetchall():
                print(f"  eid={r[0]:<5} ch={r[1]:<3} cid={r[2]:<7} pages={r[3]:<3} {r[4]}")
        else:
            print("\nreport only -- re-run with --apply")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
