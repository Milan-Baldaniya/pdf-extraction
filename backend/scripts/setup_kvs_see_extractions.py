"""Create `document_extractions` rows for the KVS Lucknow SEE Class 6/7 Maths load.

    python -m scripts.setup_kvs_see_extractions --grade 6
    python -m scripts.setup_kvs_see_extractions --grade 6 --apply

One row per NEP chapter that `shape_kvs_see_for_load` wrote items for, separate
from the CBSE SAS and SCERT Haryana rows on the same chapters because the three
are different publications under different licences.

The question paper's sha256 identifies the row; the marking scheme is a second
file and its name and hash go in `extraction_metadata` beside it, because the key
for every one of these items came from there rather than from the paper.

INSERT only.
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

from scripts.parse_kvs_see_maths import FILES, MIRROR, SOURCE_URL  # noqa: E402
from scripts.shape_c67sas_for_load import STANDARD  # noqa: E402
from scripts.shape_kvs_see_for_load import LOAD, NAME, PUBLISHER  # noqa: E402

INST, SYEAR, BOARD = 1, 2026, "CBSE"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grade", type=int, required=True, choices=(6, 7))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    qp_name, ms_name = FILES[a.grade]
    src = MIRROR / qp_name
    raw = src.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    ms_sha = hashlib.sha256((MIRROR / ms_name).read_bytes()).hexdigest()
    doc = fitz.open(src)
    pages = doc.page_count
    doc.close()
    print(f"{src.name}\n  {len(raw):,} bytes, {pages} pages, sha256 {sha[:16]}...")
    print(f"  marking scheme {ms_name}, sha256 {ms_sha[:16]}...")
    print(f"  source {SOURCE_URL}\n")

    shaped = sorted((LOAD / f"c{a.grade}").glob("ch*.json"))
    if not shaped:
        raise SystemExit(f"no shaped files; run shape_kvs_see_for_load --grade {a.grade}")

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        publisher = ensure_publisher(code=PUBLISHER, name=NAME, board=BOARD)
        subject_id = db.execute(text(
            "SELECT c.subject_id FROM chapter_master c JOIN subject s "
            "  ON s.id = c.subject_id WHERE c.standard_id = :s "
            "   AND s.subject_name = 'Mathematics' LIMIT 1"),
            {"s": STANDARD[a.grade]}).scalar()

        print(f"{'ch':<4} {'chapter_id':<11} {'items':>5} {'extraction':>11}  action")
        print("-" * 62)
        made = 0
        for path in shaped:
            data = json.loads(path.read_text(encoding="utf-8"))
            cid, order = data["chapter_id"], data["chapter"]
            name = db.execute(text("SELECT chapter_name FROM chapter_master WHERE id=:i"),
                              {"i": cid}).scalar()
            existing = db.execute(text(
                "SELECT id FROM document_extractions "
                " WHERE chapter_id = :c AND content_sha256 = :s"),
                {"c": cid, "s": sha}).scalar()
            if existing:
                data["extraction_id"] = existing
                path.write_text(json.dumps(data, indent=1, ensure_ascii=False),
                                encoding="utf-8")
                print(f"{order:<4} {cid:<11} {len(data['items']):>5} {existing:>11}  exists")
                continue
            if not a.apply:
                print(f"{order:<4} {cid:<11} {len(data['items']):>5} {'-':>11}  would insert")
                continue
            meta = json.dumps({
                "mirror_file": qp_name,
                "content_sha256": sha,
                "marking_scheme_file": ms_name,
                "marking_scheme_sha256": ms_sha,
                "scope": "Section A only -- the fifteen one-mark MCQs. Sections "
                         "B to E are worked-solution and construction questions "
                         "with no answer key in the reportable sense.",
                "tagging": "A whole-syllabus exam paper carries no chapter tag; "
                           "the chapter was read off each item. See "
                           "scripts/shape_kvs_see_for_load.py.",
            }, ensure_ascii=False)
            res = db.execute(text(
                """
                INSERT INTO document_extractions
                    (document_type, document_tittle, chapter_number, standard,
                     standard_id, subject_name, subject_id, chapter_id,
                     sub_institute_id, board, syear, pdf_url, page_count,
                     image_extracted, extraction_metadata, content_sha256,
                     extraction_status, publisher_id, updated_at)
                VALUES
                    ('question_bank', :title, :num, :std, :sid, 'Mathematics',
                     :subj, :cid, :inst, :board, :syear, :url, :pages, 0,
                     :meta, :sha, 'extracted', :pub, NOW())
                """), {
                "title": f"KVS Lucknow Region Session Ending Examination 2025-26 "
                         f"- Class {a.grade} Mathematics - {name}",
                "num": order, "std": a.grade, "sid": STANDARD[a.grade],
                "subj": subject_id, "cid": cid, "inst": INST, "board": BOARD,
                "syear": SYEAR, "url": SOURCE_URL, "pages": pages,
                "meta": meta, "sha": sha, "pub": (publisher or {}).get("id"),
            })
            data["extraction_id"] = res.lastrowid
            path.write_text(json.dumps(data, indent=1, ensure_ascii=False),
                            encoding="utf-8")
            made += 1
            print(f"{order:<4} {cid:<11} {len(data['items']):>5} "
                  f"{res.lastrowid:>11}  INSERTED")
        if a.apply:
            db.commit()
        print("-" * 62)
        print(f"{made} row(s) inserted" if a.apply else "dry run -- pass --apply to write")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
