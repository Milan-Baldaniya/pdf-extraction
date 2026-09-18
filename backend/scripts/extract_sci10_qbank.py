"""Extract the Class 10 Science question bank PDFs into document_extractions.

    python -m scripts.extract_sci10_qbank --list
    python -m scripts.extract_sci10_qbank --chapter 6
    python -m scripts.extract_sci10_qbank --all
    python -m scripts.extract_sci10_qbank --all --resume

Stage one of two. This runs MinerU over each split PDF and stores the markdown
and the image manifest on a `document_extractions` row, exactly as the Class 9
Maths bank was ingested (rows 180-188). Stage two is
`scripts.process_sci10_qbank`, which parses those rows into the question tables.

The chapter for each PDF is pinned in CHAPTERS below rather than resolved from
the title. create_extraction_stub() infers chapter_id by matching the document
title against chapter_master, and the printed titles do not match the database
spelling - "Heredity And Evolution" against "Heredity", "How do organisms
Reproduce" against "How do Organisms Reproduce?". A near miss there files a
whole chapter of questions under the wrong chapter, so the id is stated and then
verified: if the stub resolves to anything else, the row is corrected, and if it
resolves to a chapter outside Class 10 Science the run aborts.

MinerU here is CPU-only (torch 2.8.0+cpu), so this is slow - budget minutes per
page, not seconds. --resume skips PDFs that already have an extracted row, so an
interrupted run continues rather than repeating work.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import (  # noqa: E402
    SessionLocal,
    create_extraction_stub,
    init_mariadb,
    persist_extraction_result,
)
from app.models.schemas import ExtractionResponse  # noqa: E402
from app.services.mineru_service import extract_pdf  # noqa: E402
from app.utils.config import settings  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PDF_DIR = Path(r"C:\Users\MILAN\Downloads\ilovepdf_split-range (1)")
STANDARD = 10
STANDARD_ID = 43
SUBJECT_ID = 3975
SUBJECT_NAME = "Science"
BOARD = "CBSE"
SYEAR = 2026
TENANT = 1
PUBLISHER = "NODIA"

# page-range -> (chapter number, chapter_master.id, chapter_master.chapter_name)
# chapter_name is the DATABASE spelling, not the PDF's.
CHAPTERS: dict[str, tuple[int, int | None, str]] = {
    "29-69":   (1,  1012, "Chemical Reactions and Equations"),
    "70-98":   (2,  1013, "Acids, Bases and Salts"),
    "99-136":  (3,  1014, "Metals and Non-metals"),
    "137-196": (4,  1015, "Carbon and its Compounds"),
    "197-244": (5,  1016, "Life Processes"),
    "245-259": (6,  1017, "Control and Coordination"),
    "283-349": (7,  1018, "How do Organisms Reproduce?"),
    "350-370": (8,  1019, "Heredity"),
    "371-427": (9,  1020, "Light – Reflection and Refraction"),
    "428-460": (10, 1021, "The Human Eye and the Colourful World"),
    "461-530": (11, 1022, "Electricity"),
    "531-572": (12, 1023, "Magnetic Effects of Electric Current"),
    "573-609": (13, 1024, "Our Environment"),
    # Management of Natural Resources was dropped from the CBSE syllabus and has
    # no chapter_master row. Extracting it would produce questions with nowhere
    # to live, so it is skipped by design rather than silently failing later.
    "610-634": (14, None, "Management of Natural Resources"),
}


def _session():
    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    return SessionLocal()


def pdf_for(page_range: str) -> Path | None:
    for p in PDF_DIR.glob("*.pdf"):
        if p.stem.endswith(f"-{page_range}"):
            return p
    return None


def existing_row(db, chapter_id: int) -> tuple[int, str, int] | None:
    row = db.execute(
        text(
            "SELECT id, extraction_status, COALESCE(LENGTH(md_content), 0) "
            "  FROM document_extractions "
            " WHERE document_type = 'question_bank' AND chapter_id = :c "
            "   AND standard_id = :s AND subject_id = :su "
            " ORDER BY id DESC LIMIT 1"
        ),
        {"c": chapter_id, "s": STANDARD_ID, "su": SUBJECT_ID},
    ).fetchone()
    return (int(row[0]), str(row[1]), int(row[2])) if row else None


def verify_chapter(db, row_id: int, expected: int, title: str) -> None:
    """The stub guesses chapter_id from the title. Force it to the pinned id."""
    got = db.execute(
        text("SELECT chapter_id FROM document_extractions WHERE id = :i"), {"i": row_id}
    ).scalar()
    if got == expected:
        return
    if got is not None:
        owner = db.execute(
            text(
                "SELECT standard_id, subject_id, chapter_name FROM chapter_master "
                " WHERE id = :i"
            ),
            {"i": got},
        ).fetchone()
        if owner and (owner[0] != STANDARD_ID or owner[1] != SUBJECT_ID):
            raise SystemExit(
                f"ABORT: extraction {row_id} ('{title}') resolved to chapter {got} "
                f"'{owner[2]}' in standard {owner[0]}/subject {owner[1]}, which is "
                f"not Class 10 Science. Refusing to guess."
            )
    print(f"      chapter_id {got} -> {expected} (pinned)")
    db.execute(
        text("UPDATE document_extractions SET chapter_id = :c WHERE id = :i"),
        {"c": expected, "i": row_id},
    )
    db.commit()


def run_one(page_range: str, resume: bool) -> bool:
    number, chapter_id, title = CHAPTERS[page_range]
    pdf = pdf_for(page_range)
    if pdf is None:
        print(f"  ch {number:<3} {title[:42]:<44} PDF NOT FOUND for {page_range}")
        return False
    if chapter_id is None:
        print(f"  ch {number:<3} {title[:42]:<44} SKIPPED - no chapter_master row")
        return False

    db = _session()
    try:
        prior = existing_row(db, chapter_id)
        if resume and prior and prior[1] == "extracted" and prior[2] > 0:
            print(f"  ch {number:<3} {title[:42]:<44} already extracted "
                  f"(row {prior[0]}, {prior[2]} md chars) - skipping")
            return True
    finally:
        db.close()

    print(f"  ch {number:<3} {title[:42]:<44} extracting {pdf.name[-18:]} ...", flush=True)
    started = time.perf_counter()

    row_id = create_extraction_stub(
        document_type="question_bank",
        document_title=title,
        chapter_number=number,
        standard=STANDARD,
        subject_name=SUBJECT_NAME,
        board=BOARD,
        syear=SYEAR,
        pdf_url=str(pdf),
        sub_institute_id=TENANT,
    )
    if row_id is None:
        print("      stub creation failed")
        return False

    db = _session()
    try:
        verify_chapter(db, row_id, chapter_id, title)
    finally:
        db.close()

    out_dir = Path(settings.output_dir).resolve() / f"sci10_qb_{page_range}"
    result = extract_pdf(
        pdf,
        out_dir,
        settings.mineru_backend,
        method=settings.mineru_method,
        lang=settings.mineru_lang,
        server_url=settings.mineru_server_url,
        formula=settings.mineru_formula,
        table=settings.mineru_table,
        image_analysis=settings.mineru_image_analysis,
        asset_base_url=f"{settings.queue_asset_base}/sci10_qb_{page_range}",
        cpu_threads=settings.mineru_cpu_threads,
        timeout_seconds=settings.mineru_timeout_seconds,
        quality_mode=settings.mineru_quality_mode,
        ocr_fallback=settings.mineru_ocr_fallback,
    )
    elapsed = time.perf_counter() - started

    response = ExtractionResponse(
        status="success",
        processing_mode=result.processing_mode,
        markdown_content=result.markdown,
        json_content=result.json_content,
        metadata={**result.metadata, "processing_time": f"{elapsed:.2f}s",
                  "cached": False, "publisher": PUBLISHER},
        page_count=result.page_count,
        images_extracted=result.images_extracted,
    )
    persist_extraction_result(
        row_id,
        response,
        document_type="question_bank",
        document_title=title,
        chapter_number=number,
        standard=STANDARD,
        subject_name=SUBJECT_NAME,
        board=BOARD,
        syear=SYEAR,
        pdf_url=str(pdf),
        sub_institute_id=TENANT,
    )

    db = _session()
    try:
        verify_chapter(db, row_id, chapter_id, title)
    finally:
        db.close()

    print(f"      done in {elapsed/60:.1f} min | {len(result.markdown):,} md chars | "
          f"{result.images_extracted} images | {result.page_count} pages | row {row_id}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="show the plan and exit")
    parser.add_argument("--chapter", type=int, help="run one chapter number")
    parser.add_argument("--all", action="store_true", help="run every chapter")
    parser.add_argument("--resume", action="store_true",
                        help="skip chapters already extracted")
    args = parser.parse_args()

    by_number = {v[0]: k for k, v in CHAPTERS.items()}

    if args.list or not (args.chapter or args.all):
        db = _session()
        try:
            print("Class 10 Science question bank (NODIA QB 2026)\n")
            for rng, (num, cid, title) in sorted(CHAPTERS.items(), key=lambda kv: kv[1][0]):
                pdf = pdf_for(rng)
                prior = existing_row(db, cid) if cid else None
                state = ("no chapter_master row" if cid is None
                         else f"extracted (row {prior[0]})" if prior and prior[1] == "extracted"
                         else "pending")
                print(f"  ch {num:<3} {title[:40]:<42} pages {rng:<9} "
                      f"{'PDF ok' if pdf else 'PDF MISSING':<12} {state}")
        finally:
            db.close()
        return 0

    targets = ([by_number[args.chapter]] if args.chapter
               else [k for k, v in sorted(CHAPTERS.items(), key=lambda kv: kv[1][0])])
    if args.chapter and args.chapter not in by_number:
        raise SystemExit(f"no chapter {args.chapter}")

    ok = 0
    started = time.perf_counter()
    for rng in targets:
        if run_one(rng, resume=args.resume):
            ok += 1
    print(f"\n  {ok}/{len(targets)} chapter(s) extracted "
          f"in {(time.perf_counter()-started)/60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
