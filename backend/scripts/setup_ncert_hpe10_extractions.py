"""Create `document_extractions` rows for the NCERT Class X HPE exercise bank.

    python -m scripts.setup_ncert_hpe10_extractions
    python -m scripts.setup_ncert_hpe10_extractions --apply

One row per chapter that `shape_ncert_hpe10_for_load` produced items for, and
only for those chapters: a row with no questions under it is indistinguishable
later from a load that failed.

`pdf_url` records NCERT's own URL for that chapter PDF, never the mirror path.
For chapters 6, 8 and 13 that URL contains a DOUBLE DOT before the extension --
`jehp106..pdf` -- which is how NCERT uploaded them. The site's own viewer builds
`jehp106.pdf` and gets a 404, so the obvious URL is the broken one and the odd
one is real. The mirrored bytes were fetched from the URL recorded here, and the
sha256 of what was fetched is in `extraction_metadata`, so the pairing can be
re-checked later.

ALSO REGISTERS THE PUBLISHER, and it is deliberately not `ncert`. The questions
are NCERT's; the answers are not. There is no official key for this subject --
Health and Physical Education for Classes IX-X is 100% internal assessment, so
CBSE publishes no marking scheme and the textbook prints no answers -- and every
answer in this bank was derived from the chapter prose. Filing them under
`ncert` would make a derived answer look like a printed one, which is precisely
the distinction that matters when sixty-plus wrong keys have been found in
banks that WERE published with official keys.

`licence_type` is varchar(64) and a longer string makes the INSERT fail outright
rather than truncate -- losing the publisher row and leaving every question
unattributed -- so the string is measured before it is sent.

INSERT and UPDATE only. A chapter that already has a row for this file is left
alone except for its extraction_id being written back into the shaped file.
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
from app.services.publisher_service import render_attribution  # noqa: E402

from scripts.shape_ncert_hpe10_for_load import (  # noqa: E402
    BY_N, LOAD, MIRROR, PUBLISHER, STANDARD, STANDARD_ID, SUBJECT, source_url,
)

INST, SYEAR, BOARD = 1, 2026, "CBSE"

# Every one of these is measured against its column before the INSERT.
PUBLISHER_ROW = {
    "code": PUBLISHER,                                          # varchar(64)
    "name": "NCERT textbook exercises, answers derived from the chapter text",
    "short_name": "NCERT textbook (derived answers)",            # varchar(64)
    "publisher_type": "derived",                                 # varchar(32)
    "default_board": BOARD,                                      # varchar(64)
    "licence_type": "NCERT terms of use; answers not official",   # varchar(64)
    "licence_url": "https://ncert.nic.in/copyright-policy.php",
    # `lms_question_extraction.attribution` is varchar(255) and the writer
    # CLIPS to it, so a template that renders longer would lose its tail -- and
    # the tail is the part that says the answer is not an official key. It
    # therefore uses {short_name} rather than {publisher} and does not
    # interpolate {title}, which is 121 characters on the longest chapter.
    # ASCII only, and the "not an official key" clause comes first among the
    # things that could be cut.
    "attribution_template": (
        "{short_name} - Class {standard} {subject}, NCERT textbook exercise. "
        "Answer derived from the chapter text, not an official key."
    ),
    "attribution_required": 1,
    "website": "https://ncert.nic.in/textbook.php?jehp1=0-13",
    "notes": (
        "Questions are the printed end-of-chapter Assessment of NCERT's Health "
        "and Physical Education Textbook for Class X (ISBN 978-93-5292-335-9). "
        "The book prints no answer key, and CBSE publishes none: the subject is "
        "100% internal assessment, with no written paper and no marking scheme. "
        "Every answer here was DERIVED from that chapter's own prose and each "
        "item carries the quotes it was derived from. Treat these answers as "
        "reviewable drafts, not as a publisher's or a board's key."
    ),
}
WIDTH_CHECK = ("code", "name", "short_name", "publisher_type", "default_board",
               "licence_type", "licence_url", "attribution_template",
               "website", "notes")

TITLE = "NCERT Health and Physical Education Textbook Exercises"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    shaped = sorted(LOAD.glob("ch*.json"))
    if not shaped:
        raise SystemExit("no shaped files; run shape_ncert_hpe10_for_load first")

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        # --- the publisher ------------------------------------------------
        width = {c: n for c, n in db.execute(text(
            "SELECT COLUMN_NAME, CHARACTER_MAXIMUM_LENGTH "
            "  FROM information_schema.COLUMNS "
            " WHERE TABLE_SCHEMA = DATABASE() "
            "   AND TABLE_NAME = 'question_publisher' "
            "   AND CHARACTER_MAXIMUM_LENGTH IS NOT NULL")).fetchall()}
        over = [(c, len(PUBLISHER_ROW[c]), width[c]) for c in WIDTH_CHECK
                if len(PUBLISHER_ROW[c]) > width.get(c, 10 ** 6)]
        print("publisher field widths")
        for c in WIDTH_CHECK:
            print(f"  {c:<22} {len(PUBLISHER_ROW[c]):>4} / {width.get(c, '?')}")
        if over:
            for c, have, limit in over:
                print(f"  TOO LONG: {c} is {have} chars, column holds {limit}")
            raise SystemExit("publisher row would be rejected; shorten it")

        # The RENDERED attribution has to fit too. The writer clips it to 255
        # rather than failing, so an over-long template loses its tail in
        # silence -- and the tail is the clause that says the answer is derived.
        longest = max((r["ncert"] for r in BY_N.values()), key=len)
        rendered = render_attribution(PUBLISHER_ROW, {
            "document_tittle": f"{TITLE} - Class {STANDARD} - {longest}",
            "standard": STANDARD, "subject_name": SUBJECT, "syear": SYEAR,
            "board": BOARD,
        })
        print(f"  rendered attribution   {len(rendered):>4} / 255")
        print(f"    {rendered}")
        if len(rendered) > 255:
            raise SystemExit("attribution would be clipped; shorten the template")
        if any(ord(ch) > 127 for ch in rendered):
            raise SystemExit("attribution is not ASCII")

        pub = db.execute(text(
            "SELECT id, code, licence_type FROM question_publisher "
            " WHERE code = :c"), {"c": PUBLISHER}).mappings().fetchone()
        if pub:
            print(f"\npublisher {PUBLISHER} exists as id {pub['id']}")
            publisher_id = pub["id"]
        elif not a.apply:
            print(f"\npublisher {PUBLISHER} would be registered")
            publisher_id = None
        else:
            db.execute(text(
                """
                INSERT INTO question_publisher
                    (code, name, short_name, publisher_type, default_board,
                     licence_type, licence_url, attribution_template,
                     attribution_required, website, notes, status)
                VALUES (:code, :name, :short_name, :publisher_type,
                        :default_board, :licence_type, :licence_url,
                        :attribution_template, :attribution_required,
                        :website, :notes, 1)
                """), PUBLISHER_ROW)
            db.commit()
            publisher_id = db.execute(text(
                "SELECT id FROM question_publisher WHERE code = :c"),
                {"c": PUBLISHER}).scalar()
            print(f"\npublisher {PUBLISHER} REGISTERED as id {publisher_id}")

        subject_id = db.execute(text(
            "SELECT id FROM subject WHERE subject_name = :s LIMIT 1"),
            {"s": SUBJECT}).scalar()
        if not subject_id:
            raise SystemExit(f"subject {SUBJECT!r} not found")

        print(f"\n{'ch':<3} {'chapter_id':<11} {'items':>5} {'extraction':>11}  "
              f"action")
        print("-" * 96)
        made = updated = 0
        for path in shaped:
            data = json.loads(path.read_text(encoding="utf-8"))
            n, cid = data["chapter"], data["chapter_id"]
            row = BY_N[n]
            if not data["items"]:
                print(f"{n:<3} {cid:<11} {0:>5} {'-':>11}  "
                      f"skipped, no items survived verification")
                continue

            # The alignment is re-checked against the live row rather than
            # trusted: a chapter_id that moved would file a whole chapter's
            # questions under the wrong heading and report success.
            live = db.execute(text(
                "SELECT chapter_name, standard_id, subject_id "
                "  FROM chapter_master WHERE id = :i"),
                {"i": cid}).mappings().fetchone()
            if not live:
                print(f"{n:<3} {cid:<11} {'-':>5} {'-':>11}  "
                      f"ABORT: chapter row missing")
                raise SystemExit("alignment is stale")
            if (live["standard_id"] != STANDARD_ID
                    or live["subject_id"] != subject_id):
                print(f"{n:<3} {cid:<11} {'-':>5} {'-':>11}  "
                      f"ABORT: chapter {cid} is standard "
                      f"{live['standard_id']}/subject {live['subject_id']}")
                raise SystemExit("alignment points outside Class 10 HPE")
            if live["chapter_name"] != data["db_chapter_name"]:
                print(f"{n:<3} {cid:<11} {'-':>5} {'-':>11}  "
                      f"ABORT: chapter {cid} is now "
                      f"{live['chapter_name']!r}, alignment recorded "
                      f"{data['db_chapter_name']!r}")
                raise SystemExit("alignment is stale")

            src = MIRROR / row["file"]
            raw = src.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            doc = fitz.open(src)
            pages = doc.page_count
            doc.close()
            url = source_url(row)

            existing = db.execute(text(
                "SELECT id FROM document_extractions "
                " WHERE chapter_id = :c AND document_type = 'question_bank' "
                "   AND pdf_url = :u"), {"c": cid, "u": url}).scalar()
            meta = json.dumps({
                "mirror_file": row["file"],
                "content_sha256": sha,
                "ncert_chapter_title": row["ncert"],
                "db_chapter_name": row["db_name"],
                "name_alignment": (
                    "Our chapter name is a paraphrase of the NCERT heading; "
                    "the two were aligned by position and content, not by "
                    "name, and our row was NOT renamed."
                ),
                "answer_provenance": data["answer_provenance"],
                "verified_items": len(data["items"]),
                "rejected_by_verification": len(data.get("rejected") or []),
                "dropped_unanswerable": len(data.get("authored_dropped") or []),
                "url_note": (
                    "NCERT uploaded this chapter with a double dot before the "
                    "extension; the site's own link (jehp1NN.pdf) returns 404."
                ) if row.get("url_file") else None,
            }, ensure_ascii=False)

            if existing:
                data["extraction_id"] = existing
                path.write_text(json.dumps(data, indent=1, ensure_ascii=False),
                                encoding="utf-8")
                if a.apply:
                    db.execute(text(
                        "UPDATE document_extractions "
                        "   SET extraction_metadata = :m, publisher_id = :p, "
                        "       updated_at = NOW() "
                        " WHERE id = :i"),
                        {"m": meta, "p": publisher_id, "i": existing})
                    updated += 1
                print(f"{n:<3} {cid:<11} {len(data['items']):>5} "
                      f"{existing:>11}  exists"
                      f"{', metadata refreshed' if a.apply else ''}")
                continue

            if not a.apply:
                print(f"{n:<3} {cid:<11} {len(data['items']):>5} {'-':>11}  "
                      f"would insert   {url}")
                continue

            res = db.execute(text(
                """
                INSERT INTO document_extractions
                    (document_type, document_tittle, chapter_number, standard,
                     standard_id, subject_name, subject_id, chapter_id,
                     sub_institute_id, board, syear, pdf_url, page_count,
                     image_extracted, extraction_metadata, content_sha256,
                     extraction_status, publisher_id, updated_at)
                VALUES
                    ('question_bank', :title, :num, :std, :sid, :subject,
                     :subj, :cid, :inst, :board, :syear, :url, :pages, 0,
                     :meta, :sha, 'extracted', :pub, NOW())
                """), {
                "title": f"{TITLE} - Class {STANDARD} - {row['ncert']}",
                "num": n, "std": STANDARD, "sid": STANDARD_ID,
                "subject": SUBJECT, "subj": subject_id, "cid": cid,
                "inst": INST, "board": BOARD, "syear": SYEAR, "url": url,
                "pages": pages, "meta": meta, "sha": sha, "pub": publisher_id,
            })
            new_id = res.lastrowid
            data["extraction_id"] = new_id
            path.write_text(json.dumps(data, indent=1, ensure_ascii=False),
                            encoding="utf-8")
            made += 1
            print(f"{n:<3} {cid:<11} {len(data['items']):>5} {new_id:>11}  "
                  f"INSERTED   {url}")
        if a.apply:
            db.commit()
        print("-" * 96)
        print(f"{made} row(s) inserted, {updated} refreshed" if a.apply
              else "dry run -- pass --apply to write")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
