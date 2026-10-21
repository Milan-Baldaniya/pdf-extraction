"""Create `document_extractions` rows for the SCERT Haryana Class 6/7 Maths load.

    python -m scripts.setup_scert_extractions --grade 6
    python -m scripts.setup_scert_extractions --grade 6 --apply

One row per NEP chapter that `shape_scert_for_load` wrote items for. Separate
rows from the CBSE SAS ones on the same chapters, because they are a different
publication with a different licence and a different `pdf_url`, and an extraction
row is what carries both.

INSERT only. A chapter that already has a row for this file is left alone.
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

from scripts.parse_scert_haryana import FILES, MIRROR  # noqa: E402
from scripts.shape_c67sas_for_load import STANDARD  # noqa: E402
from scripts.shape_scert_for_load import LOAD, PUBLISHER, SOURCE_URL  # noqa: E402

INST, SYEAR, BOARD = 1, 2026, "CBSE"
NAME = "State Council of Educational Research and Training, Haryana"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grade", type=int, required=True, choices=(6, 7))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    src = MIRROR / FILES[a.grade]
    raw = src.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    doc = fitz.open(src)
    pages = doc.page_count
    doc.close()
    print(f"{src.name}\n  {len(raw):,} bytes, {pages} pages, sha256 {sha[:16]}...")
    print(f"  source {SOURCE_URL}\n")

    shaped = sorted(LOAD.glob(f"c{a.grade}/ch*.json")) + \
        sorted(LOAD.glob(f"c{a.grade}_to_c*/ch*.json"))
    if not shaped:
        raise SystemExit(f"no shaped files; run shape_scert_for_load --grade {a.grade}")

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        publisher = ensure_publisher(code=PUBLISHER, name=NAME, board=BOARD)

        def subject_of(standard_id: int) -> int:
            return db.execute(text(
                "SELECT c.subject_id FROM chapter_master c JOIN subject s "
                "  ON s.id = c.subject_id WHERE c.standard_id = :s "
                "   AND s.subject_name = 'Mathematics' LIMIT 1"),
                {"s": standard_id}).scalar()

        print(f"{'dest':<6} {'ch':<4} {'chapter_id':<11} {'items':>5} "
              f"{'extraction':>11}  action")
        print("-" * 70)
        made = 0
        for path in shaped:
            data = json.loads(path.read_text(encoding="utf-8"))
            cid, order = data["chapter_id"], data["chapter"]
            target = data.get("target_grade", a.grade)
            std_id = data.get("standard_id", STANDARD[a.grade])
            cross = bool(data.get("cross_grade"))
            subject_id = subject_of(std_id)
            label = f"C{target}" + ("*" if cross else "")
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
                print(f"{label:<6} {order:<4} {cid:<11} {len(data['items']):>5} "
                      f"{existing:>11}  exists")
                continue
            if not a.apply:
                print(f"{label:<6} {order:<4} {cid:<11} {len(data['items']):>5} "
                      f"{'-':>11}  would insert")
                continue
            payload = {
                "mirror_file": src.name,
                "content_sha256": sha,
                "tagging": "SCERT Haryana tags its items to Haryana competency "
                           "codes, not to chapters. The chapter was chosen per "
                           "item; see scripts/shape_scert_for_load.py.",
            }
            if cross:
                payload["cross_grade"] = {
                    "item_grade": a.grade,
                    "chapter_grade": target,
                    "reason": f"NEP moved this topic from Class {a.grade} to "
                              f"Class {target}. These items come from SCERT "
                              f"Haryana's Class {a.grade} bank; the Ganita "
                              f"Prakash chapter that now teaches the topic is in "
                              f"Class {target}, so the items are filed there. "
                              f"The chapter, not the source book, sets the grade "
                              f"a learner sees them at.",
                    "approved": "explicitly approved before loading",
                }
            meta = json.dumps(payload, ensure_ascii=False)
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
                "title": f"SCERT Haryana Competency Question Bank 2025-26 "
                         f"(Class {a.grade} bank) - Class {target} Mathematics "
                         f"- {name}",
                "num": order, "std": target, "sid": std_id,
                "subj": subject_id, "cid": cid, "inst": INST, "board": BOARD,
                "syear": SYEAR, "url": SOURCE_URL, "pages": pages,
                "meta": meta, "sha": sha, "pub": (publisher or {}).get("id"),
            })
            data["extraction_id"] = res.lastrowid
            path.write_text(json.dumps(data, indent=1, ensure_ascii=False),
                            encoding="utf-8")
            made += 1
            print(f"{label:<6} {order:<4} {cid:<11} {len(data['items']):>5} "
                  f"{res.lastrowid:>11}  INSERTED")
        if a.apply:
            db.commit()
        print("-" * 70)
        print(f"{made} row(s) inserted" if a.apply else "dry run -- pass --apply to write")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
