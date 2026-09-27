"""Create `document_extractions` rows for the CBSE SAS Class 6/7 Maths remap.

    python -m scripts.setup_c67sas_extractions --grade 6
    python -m scripts.setup_c67sas_extractions --grade 6 --apply

One row per NEP chapter that `shape_c67sas_for_load` actually wrote items for.
Rows are created only for those chapters on purpose: a chapter mapped but left
empty -- every Class 6 Data Handling item needs its bar graph -- would otherwise
sit in `document_extractions` with status 'extracted' and no questions under it,
indistinguishable later from a load that failed.

`pdf_url` records the real source, CBSE's own publication, not the mirror path.
The mirrored file name, its sha256 and the old chapter the items were remapped
from go in `extraction_metadata`, so the remap is auditable from the row alone.

CROSS-GRADE ROWS. NEP re-sequenced four Class 6 topics into Class 7, so some
rows hold Class 6 items under a Class 7 chapter. Those rows carry the TARGET
grade in `standard` and `standard_id`, because that is the chapter they belong
to and what a learner will be served by -- and they say so in
`extraction_metadata` under `cross_grade`, naming both grades and the reason, so
a later reader is never left guessing why a Class 6 book is filed under Class 7.

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

from scripts.parse_sas_items import GRADES, _MIRROR_ROOT  # noqa: E402
from scripts.shape_c67sas_for_load import (  # noqa: E402
    LOAD, PUBLISHER, SOURCE_URL, STANDARD,
)

INST, SYEAR, BOARD = 1, 2026, "CBSE"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grade", type=int, required=True, choices=(6, 7))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    sub_dir, files = GRADES[a.grade]
    src = _MIRROR_ROOT / sub_dir / files["maths"]
    raw = src.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    doc = fitz.open(src)
    pages = doc.page_count
    doc.close()
    print(f"{src.name}\n  {len(raw):,} bytes, {pages} pages, sha256 {sha[:16]}...")
    print(f"  source {SOURCE_URL + src.name}\n")

    # Both the same-grade output and any cross-grade output for this book.
    shaped = sorted(LOAD.glob(f"c{a.grade}/ch*.json")) + \
        sorted(LOAD.glob(f"c{a.grade}_to_c*/ch*.json"))
    if not shaped:
        raise SystemExit(f"no shaped files; run shape_c67sas_for_load --grade {a.grade}")

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        publisher = ensure_publisher(code=PUBLISHER, name=None, board=BOARD)

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
                " WHERE chapter_id = :c AND extraction_metadata LIKE :m"),
                {"c": cid, "m": f'%"{src.name}"%'}).scalar()
            if existing:
                # The asset manifest IS updated on an existing row. It is what
                # `write_question_bank` resolves each item's `images` against,
                # and a name that does not resolve is dropped in silence -- so a
                # chapter that gains figures after its row was made must have
                # them written here or every one of them vanishes.
                note = ""
                if data.get("assets") and a.apply:
                    db.execute(text(
                        "UPDATE document_extractions SET asset_manifest = :m "
                        " WHERE id = :i"),
                        {"m": json.dumps(data["assets"], ensure_ascii=False),
                         "i": existing})
                    note = f", {len(data['assets'])} asset(s) written"
                print(f"{label:<6} {order:<4} {cid:<11} {len(data['items']):>5} "
                      f"{existing:>11}  exists{note}")
                data["extraction_id"] = existing
                path.write_text(json.dumps(data, indent=1, ensure_ascii=False),
                                encoding="utf-8")
                continue
            if not a.apply:
                print(f"{label:<6} {order:<4} {cid:<11} {len(data['items']):>5} "
                      f"{'-':>11}  would insert")
                continue
            payload = {
                "mirror_file": src.name,
                "content_sha256": sha,
                "remapped_from": data["old_chapters"],
                "remap": "CBSE SAS is tagged to the superseded Class 6/7 Maths "
                         "books; these items were remapped to the NEP Ganita "
                         "Prakash chapter that teaches the same topic.",
            }
            if cross:
                payload["cross_grade"] = {
                    "item_grade": a.grade,
                    "chapter_grade": target,
                    "reason": f"NEP moved this topic from Class {a.grade} to "
                              f"Class {target}. CBSE wrote these items for the "
                              f"superseded Class {a.grade} book; the Ganita "
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
                     image_extracted, extraction_metadata, asset_manifest,
                     content_sha256, extraction_status, publisher_id, updated_at)
                VALUES
                    ('question_bank', :title, :num, :std, :sid, 'Mathematics',
                     :subj, :cid, :inst, :board, :syear, :url, :pages, :imgs,
                     :meta, :assets, :sha, 'extracted', :pub, NOW())
                """), {
                "sha": sha,
                "imgs": len(data.get("assets") or []),
                "assets": (json.dumps(data["assets"], ensure_ascii=False)
                           if data.get("assets") else None),
                # The title names the SOURCE book, because that is what the
                # questions were taken from, and the row's standard names the
                # DESTINATION, because that is the chapter they sit on.
                "title": f"CBSE SAS Competency Items (Class {a.grade} book) - "
                         f"Class {target} Mathematics - {name}",
                "num": order, "std": target, "board": BOARD, "syear": SYEAR,
                "url": SOURCE_URL + src.name, "sid": std_id,
                "subj": subject_id, "cid": cid, "inst": INST, "pages": pages,
                "meta": meta, "pub": (publisher or {}).get("id"),
            })
            new_id = res.lastrowid
            data["extraction_id"] = new_id
            path.write_text(json.dumps(data, indent=1, ensure_ascii=False),
                            encoding="utf-8")
            made += 1
            print(f"{label:<6} {order:<4} {cid:<11} {len(data['items']):>5} "
                  f"{new_id:>11}  INSERTED")
        if a.apply:
            db.commit()
        print("-" * 70)
        print(f"{made} row(s) inserted" if a.apply else "dry run -- pass --apply to write")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
