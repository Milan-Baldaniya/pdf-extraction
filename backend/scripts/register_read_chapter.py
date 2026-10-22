"""Give a chapter that was READ from page images a row and a figure manifest.

    python -m scripts.register_read_chapter --chapter 5
    python -m scripts.register_read_chapter --chapter 5 --figures
    python -m scripts.register_read_chapter --all

The rest of the pipeline addresses a chapter by its `document_extractions` row:
persist_supplied writes against an extraction_id, chapter_context reads the
concept list through one, and question_bank_writer resolves every figure name
against that row's `asset_manifest`. MinerU used to create the row as a side
effect of OCR-ing the book. Reading the pages directly skips MinerU, so the row
has to be created here instead - otherwise there is nowhere to attach the
questions and every figure is silently dropped.

The row carries no markdown, and that is deliberate: nothing downstream reads
md_content for a chapter read this way, and a half-filled markdown column would
invite someone to trust it later.

--figures rebuilds the manifest from the PNGs in the chapter's crop folder.
Run it AFTER the readers have cropped their figures and BEFORE loading the
items, because the writer drops an image reference that is not in the manifest
without raising anything.
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

from app.db.mariadb import (  # noqa: E402
    SessionLocal,
    create_extraction_stub,
    init_mariadb,
)
from scripts.render_pages import FIGURES_ROOT, chapter_pdf  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BOOK = "maths10"


def _tables(book: str):
    """(book constants, chapter number -> (chapter_id, title, subject_id)).

    subject_id is per CHAPTER, not per book. The Social Science volume covers
    History, Geography, Political Science and Economics, which this estate
    stores as four separate subjects - a single module-level SUBJECT_ID cannot
    express that, and filing the whole book under one subject would put
    Federalism in with Agriculture.
    """
    if book == "maths10":
        from scripts.extract_maths10_qbank import (
            BOARD, CHAPTERS, STANDARD, STANDARD_ID, SUBJECT_ID, SUBJECT_NAME,
            SYEAR, TENANT)
        meta = dict(board=BOARD, standard=STANDARD, standard_id=STANDARD_ID,
                    subject_name=SUBJECT_NAME, syear=SYEAR, tenant=TENANT)
        return meta, {num: (cid, name, SUBJECT_ID)
                      for num, cid, name in CHAPTERS.values() if cid}
    from scripts import books as _books
    b = _books.get(book)
    meta = dict(board=b.board, standard=b.standard, standard_id=b.standard_id,
                subject_name=b.subject_name, syear=b.syear, tenant=b.tenant)
    return meta, {c.number: (c.chapter_id, c.title, c.subject_id) for c in b.chapters}


META, BY_NUMBER = _tables(BOOK)


def find_row(db, chapter_id: int) -> int | None:
    row = db.execute(
        text("SELECT id FROM document_extractions "
             " WHERE chapter_id = :c AND document_type = 'question_bank' "
             " ORDER BY id DESC LIMIT 1"),
        {"c": chapter_id},
    ).fetchone()
    return int(row[0]) if row else None


def ensure_row(chapter: int) -> int:
    chapter_id, title, subject_id = BY_NUMBER[chapter]
    db = SessionLocal()
    try:
        existing = find_row(db, chapter_id)
        if existing:
            # Reusing a row is not enough - it has to be left in a state the
            # rest of the pipeline accepts. Chapter 5's row was created by
            # MinerU and left at 'extracting' when that run was stopped, and
            # merge_nodia_parts only maps rows that read 'extracted', so the
            # chapter silently reported "not mapped, skipping" after a full
            # read had already been done.
            db.execute(
                text("UPDATE document_extractions "
                     "   SET extraction_status = 'extracted', standard_id = :s, "
                     "       subject_id = :su, chapter_id = :c "
                     " WHERE id = :i AND extraction_status <> 'extracted'"),
                {"s": META["standard_id"], "su": subject_id,
                 "c": chapter_id, "i": existing},
            )
            db.commit()
            return existing
    finally:
        db.close()

    pdf = chapter_pdf(BOOK, chapter)

    # create_extraction_stub resolves the chapter itself, by name and
    # sort_order, and raises if it cannot. The printed title and the stored one
    # often differ - the book says "Outcome of Democracy", the database says
    # "Outcomes of Democracy" - so the row is created under the STORED name.
    # We pin chapter_id explicitly straight afterwards either way; this just
    # stops a plural from blocking the creation.
    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT chapter_name, sort_order FROM chapter_master WHERE id = :i"),
            {"i": chapter_id}).fetchone()
        stored, stored_order = (row[0], row[1]) if row else (None, None)
    finally:
        db.close()

    row_id = create_extraction_stub(
        document_type="question_bank",
        document_title=stored or title,
        # The book's own chapter number, not the stored one, would be wrong:
        # this volume numbers straight through 1..19 while the database numbers
        # each subject separately, so the book's chapter 15 is Civics chapter 5.
        chapter_number=int(stored_order) if stored_order else chapter,
        standard=META["standard"],
        subject_name=META["subject_name"],
        board=META["board"],
        syear=META["syear"],
        pdf_url=str(pdf),
        sub_institute_id=META["tenant"],
    )
    if row_id is None:
        raise SystemExit(f"could not create an extraction row for chapter {chapter}")

    import fitz

    doc = fitz.open(str(pdf))
    pages = len(doc)
    doc.close()

    db = SessionLocal()
    try:
        db.execute(
            text("UPDATE document_extractions "
                 "   SET chapter_id = :c, standard_id = :s, subject_id = :su, "
                 "       page_count = :p, extraction_status = 'extracted', "
                 "       extraction_profile = :prof "
                 " WHERE id = :i"),
            {"c": chapter_id, "s": META["standard_id"], "su": subject_id, "p": pages,
             "i": row_id,
             "prof": json.dumps({"reader": "page-image", "page_dpi": 170,
                                 "ocr": False, "page_count": pages})},
        )
        db.commit()
        # Confirm it landed where it should. A chapter filed against the wrong
        # id is the one mistake here that is expensive to undo.
        got = db.execute(
            text("SELECT chapter_id, standard_id, subject_id FROM document_extractions "
                 " WHERE id = :i"), {"i": row_id}).fetchone()
        want = (chapter_id, META["standard_id"], subject_id)
        if tuple(int(v) for v in got) != want:
            raise SystemExit(f"row {row_id} resolved to {got}, expected {want}")
    finally:
        db.close()
    return row_id


def build_manifest(chapter: int, row_id: int) -> int:
    """Index the cropped figures so the writer can resolve them by file name."""
    folder = FIGURES_ROOT / f"{BOOK}_ch{chapter:02d}"
    entries = []
    if folder.exists():
        for path in sorted(folder.glob("*.png")):
            data = path.read_bytes()
            width = height = None
            try:
                import fitz
                pix = fitz.Pixmap(str(path))
                width, height = pix.width, pix.height
            except Exception:
                pass
            # These key names are the ones question_bank_writer actually reads.
            # An entry using "source_path"/"mime" instead looks perfectly
            # reasonable and writes a row with source_path NULL, which then
            # makes every figure unpublishable: publish_question_figures needs
            # source_path to find the file on disk. 286 assets landed that way
            # before this was caught.
            entries.append({
                "file_name": path.name,
                "sha256": hashlib.sha256(data).hexdigest(),
                # Absolute, so publish_question_figures finds the file: it joins
                # relative_path onto its output dir, and joining an absolute
                # path yields the absolute path unchanged.
                "relative_path": str(path),
                "url": path.as_uri(),
                "extension": path.suffix.lstrip(".").lower() or "png",
                "size_bytes": len(data),
                "width": width,
                "height": height,
            })

    db = SessionLocal()
    try:
        # Never replace a populated manifest with an empty one. Running this
        # with --all once did exactly that to the four chapters MinerU had
        # already indexed, because their crop folders are empty - they get
        # their figures from MinerU, not from crops. Nothing stored was lost,
        # but the manifest is what resolves an item's image name at write time,
        # so a reload would have stored every question with no figure.
        current = db.execute(
            text("SELECT JSON_LENGTH(COALESCE(asset_manifest, '[]')) "
                 "  FROM document_extractions WHERE id = :i"), {"i": row_id}).scalar()
        if not entries and int(current or 0) > 0:
            raise SystemExit(
                f"refusing to clear chapter {chapter}: its crop folder is empty but "
                f"row {row_id} already indexes {current} figure(s). If this chapter "
                f"came from MinerU, leave it alone; rebuild with "
                f"scripts.rebuild_mineru_manifest instead.")
        db.execute(
            text("UPDATE document_extractions SET asset_manifest = :m WHERE id = :i"),
            {"m": json.dumps(entries), "i": row_id},
        )
        db.commit()
    finally:
        db.close()
    return len(entries)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chapter", type=int)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--book", default="maths10")
    ap.add_argument("--figures", action="store_true",
                    help="(re)build the asset manifest from the crop folder")
    a = ap.parse_args()
    if not (a.chapter or a.all):
        ap.error("choose --chapter N or --all")

    global BOOK, META, BY_NUMBER
    BOOK = a.book
    META, BY_NUMBER = _tables(BOOK)

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")

    targets = sorted(BY_NUMBER) if a.all else [a.chapter]
    for chapter in targets:
        if chapter not in BY_NUMBER:
            print(f"  ch {chapter}: not mapped, skipping")
            continue
        row_id = ensure_row(chapter)
        chapter_id, title, subject_id = BY_NUMBER[chapter]
        line = f"  ch {chapter:<3} {title[:38]:<40} row {row_id}  chapter_id {chapter_id}"
        if a.figures:
            line += f"  manifest: {build_manifest(chapter, row_id)} figure(s)"
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
