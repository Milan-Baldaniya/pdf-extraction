"""Create `document_extractions` rows for a book in the `parse_nodia_qb` registry.

    python -m scripts.setup_nodia_extractions --book c6_social
    python -m scripts.setup_nodia_extractions --book c6_social --apply

One row per (chapter x source document). THE PART IS WHAT DISAMBIGUATES where
a book has two: Class 7 Social Science restarts its chapter numbering in Part
2, so "CHAP 1" names two different chapters and a row keyed on the number
alone puts eight chapters' questions on the wrong subject.

Identity is content_sha256 + chapter_id. These files were mirrored from a
pdf.tube listing and the deep link for an individual file is not something to
guess, so the listing URL goes in `pdf_url` and the mirrored file name and
its hash go in `extraction_metadata`.

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

from scripts.parse_nodia_qb import BOOKS, MIRROR, SOURCE_URL  # noqa: E402

INST, SYEAR, BOARD = 1, 2026, "CBSE"


def _fold(t):
    import re
    return re.sub(r"[^0-9a-zऀ-ॿ]", "", (t or "").lower())


def _overlap(a, b):
    """How much of the shorter string the two share, as a crude score."""
    if not a or not b:
        return 0
    n = min(len(a), len(b))
    return sum(1 for i in range(n) if a[i] == b[i])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--book", choices=sorted(BOOKS), required=True)
    ap.add_argument("--apply", action="store_true")
    # A TOP-UP IS NOT A FRESH LOAD. Where a book covers chapters the bank
    # already holds from another source, a row per chapter leaves the ones
    # nobody will load sitting in document_extractions with status
    # 'extracted' and no questions under them -- indistinguishable, later,
    # from a load that failed. Naming the chapters to be filled keeps the
    # rows and the questions in step, and makes it structurally impossible
    # for the shaper to write a file for a chapter that was not asked for.
    ap.add_argument("--only", help="comma-separated printed chapter numbers")
    a = ap.parse_args()
    cfg = BOOKS[a.book]
    src = MIRROR / cfg["file"]

    raw = src.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    doc = fitz.open(src)
    pages = doc.page_count
    doc.close()
    print(f"{src.name}\n  {len(raw):,} bytes, {pages} pages, sha256 {sha[:16]}...\n")

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        by_part: dict[int, dict[int, tuple]] = {}
        for part, subj in cfg["subject_of_part"].items():
            rows = db.execute(text(
                "SELECT c.id, c.sort_order, c.chapter_name, c.subject_id "
                "  FROM chapter_master c JOIN subject s ON s.id = c.subject_id "
                " WHERE c.standard_id = :s AND s.subject_name = :n "
                " ORDER BY c.sort_order"),
                {"s": cfg["standard_id"], "n": subj}).fetchall()
            # TWO ROWS CAN SHARE A sort_order. Class 9 Hindi-A has both
            # "Hindi Curriculum" and the real chapter 1 at 1, and keyed on
            # position alone the whole book would load against a curriculum
            # placeholder. Where a number is ambiguous, the row whose name
            # matches the registry wins.
            table: dict[int, list] = {}
            for r in rows:
                table.setdefault(int(r[1]), []).append((int(r[0]), r[2], int(r[3])))
            reg = {c[1]: c[2] for c in cfg["chapters"] if c[0] == part}
            picked: dict[int, tuple] = {}
            for so, cands in table.items():
                if len(cands) == 1:
                    picked[so] = cands[0]
                    continue
                want = _fold(reg.get(so, ""))
                best = max(cands, key=lambda c: _overlap(_fold(c[1]), want))
                picked[so] = best
                print(f"  note: sort_order {so} has {len(cands)} rows "
                      f"{[c[1] for c in cands]}; chose {best[1]!r}")
            by_part[part] = picked
        have = {int(r[0]) for r in db.execute(text(
            "SELECT chapter_id FROM document_extractions WHERE content_sha256 = :h"),
            {"h": sha}).fetchall()}

        pub = None
        if a.apply:
            pub = ensure_publisher(code=cfg["publisher"], name="NODIA Press", board=BOARD)
            print(f"publisher {cfg['publisher']} -> id {pub['id'] if pub else '?'}\n")

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
        print(f"  {'pt':>2} {'ch':>3} {'cid':>7}  {'chapter':<48} action")
        print("  " + "-" * 86)
        made = 0
        only = ({int(x) for x in a.only.split(",") if x.strip()}
                if a.only else None)
        for part, so, name, lo, hi in cfg["chapters"]:
            if only is not None and so not in only:
                print(f"  {part:>2} {so:>3} {'-':>7}  {name[:48]:<48} "
                      f"not asked for")
                continue
            entry = by_part.get(part, {}).get(so)
            if not entry:
                print(f"  {part:>2} {so:>3} {'-':>7}  {name[:48]:<48} NO CHAPTER ROW")
                continue
            cid, db_name, subject_id = entry
            if cid in have:
                print(f"  {part:>2} {so:>3} {cid:>7}  {db_name[:48]:<48} SKIP, row exists")
                continue
            meta = json.dumps({
                "source": cfg["title"], "textbook": cfg["textbook"],
                "source_listing": SOURCE_URL, "file_name": src.name,
                "file_sha256": sha, "part": part,
                "printed_folios": f"{lo}-{hi}",
                "parser": "scripts/parse_nodia_qb.py",
                "answer_marker": cfg["marker"],
            })
            if a.apply:
                db.execute(ins, {"t": f"{db_name} -- {cfg['title']}", "n": so,
                                 "std": cfg["standard"], "sid": cfg["standard_id"],
                                 "sn": cfg["subject_of_part"][part], "jid": subject_id,
                                 "cid": cid, "inst": INST, "b": BOARD, "y": SYEAR,
                                 "u": SOURCE_URL, "pc": pages, "meta": meta,
                                 "sha": sha, "pub": pub["id"] if pub else None})
                made += 1
            print(f"  {part:>2} {so:>3} {cid:>7}  {db_name[:48]:<48} "
                  f"{'INSERT' if a.apply else 'would insert'}")
        if a.apply:
            db.commit()
            print(f"\ninserted {made} row(s)\n")
            for r in db.execute(text(
                "SELECT id, subject_name, chapter_number, chapter_id "
                "  FROM document_extractions WHERE content_sha256=:h "
                " ORDER BY subject_name, chapter_number"), {"h": sha}).fetchall():
                print(f"  eid={r[0]:<5} {str(r[1]):<20} ch={r[2]:<3} cid={r[3]}")
        else:
            print("\nreport only -- re-run with --apply")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
