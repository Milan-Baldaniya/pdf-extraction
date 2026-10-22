"""Rebuild a MinerU chapter's asset_manifest from the images left on disk.

    python -m scripts.rebuild_mineru_manifest --chapter 4
    python -m scripts.rebuild_mineru_manifest --chapters 1,2,3,4

Why this exists: register_read_chapter --figures was run across every chapter,
including the four MinerU had already done, and it replaced their manifests
with an empty list built from an empty crop folder. Nothing stored was lost -
lms_question_asset keeps its own rows and those figures are already on the CDN -
but the manifest is what question_bank_writer resolves an item's `images` name
against, so without it a reload of those chapters would silently store every
question with no figure, and a reader asking chapter_context for the legal
image names is told there are none.

MinerU names each image by the sha256 of its own bytes, so the manifest is
fully reconstructible from the files: the file name IS the hash. Reconstructed
entries therefore match what MinerU wrote, not an approximation of it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output"

# What MinerU stamped into each entry's url. Kept identical so a rebuilt row is
# indistinguishable from the original; publish_question_figures rewrites it to
# the CDN anyway, and treats this form as "unreachable, needs uploading".
ASSET_BASE = "http://127.0.0.1:8000/api/assets"


def image_dir(chapter: int) -> Path | None:
    hits = sorted(OUTPUT_DIR.glob(f"maths10_qb_maths10_ch{chapter:02d}_*/pass_auto/*/auto/images"))
    return hits[0] if hits else None


def rebuild(chapter: int, db) -> tuple[int | None, int]:
    row = db.execute(
        text("SELECT id FROM document_extractions "
             " WHERE pdf_url LIKE :p AND document_type = 'question_bank' "
             " ORDER BY id DESC LIMIT 1"),
        {"p": f"%ch{chapter:02d}_%"},
    ).fetchone()
    if not row:
        return None, 0
    row_id = int(row[0])

    folder = image_dir(chapter)
    if folder is None:
        return row_id, 0

    # The prefix MinerU used in the url, e.g.
    # maths10_qb_maths10_ch04_quadratic_equations/pass_auto/.../images
    rel = folder.relative_to(OUTPUT_DIR).as_posix()

    entries = []
    for path in sorted(folder.glob("*.jpg")) + sorted(folder.glob("*.png")):
        # The manifest's sha256 is the hash of the FILE BYTES. MinerU's file
        # NAME is a different hash of its own (of the source region, not the
        # written JPEG), so the two never match and a mismatch is not an error.
        # Verified against three already-published rows: the byte hash is what
        # lms_question_asset.asset_sha256 holds and what keys the CDN object,
        # so computing it here reproduces the original entry exactly.
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        width = height = None
        try:
            import fitz
            pix = fitz.Pixmap(str(path))
            width, height = pix.width, pix.height
        except Exception:
            pass
        entries.append({
            "file_name": path.name,
            "sha256": digest,
            "source_path": path.relative_to(OUTPUT_DIR).as_posix(),
            "url": f"{ASSET_BASE}/{rel}/{path.name}",
            "mime": mimetypes.guess_type(path.name)[0] or "image/jpeg",
            "width": width,
            "height": height,
        })

    db.execute(
        text("UPDATE document_extractions SET asset_manifest = :m WHERE id = :i"),
        {"m": json.dumps(entries), "i": row_id},
    )
    db.commit()
    return row_id, len(entries)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chapter", type=int)
    ap.add_argument("--chapters", help="comma-separated list")
    a = ap.parse_args()

    if a.chapters:
        targets = [int(x) for x in a.chapters.split(",") if x.strip()]
    elif a.chapter:
        targets = [a.chapter]
    else:
        ap.error("choose --chapter N or --chapters 1,2,3")

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")

    db = SessionLocal()
    try:
        for chapter in targets:
            row_id, n = rebuild(chapter, db)
            if row_id is None:
                print(f"  ch {chapter:<3} no extraction row found")
            else:
                print(f"  ch {chapter:<3} row {row_id}  manifest rebuilt: {n} image(s)")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
