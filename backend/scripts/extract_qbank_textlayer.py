"""Extract a question bank from its own text layer, without MinerU.

    python -m scripts.extract_qbank_textlayer --map data/qbank/cbse9_science_folio.json --list
    python -m scripts.extract_qbank_textlayer --map ... --chapter 2 --apply
    python -m scripts.extract_qbank_textlayer --map ... --all --apply --resume

MinerU exists to recover text from pages that do not carry any. The CBSE
question banks on pdf.tube are born-digital: the Class 9 Science book reads
2,215 characters per page straight off the text layer, with question numbers,
option labels and the `Ans :` marker all intact -- cleaner than OCR of the same
page, and in minutes rather than the 22-55 per chapter MinerU costs on a
CPU-only box.

So this reads the text directly and writes the same `document_extractions` row
the MinerU path writes, through the same `persist_extraction_result`. Anything
downstream -- plan_nodia_work, chapter_context, the item loader -- cannot tell
the difference, which is the point.

Page ranges come from a folio map built by `probe_qbook.py`, never from a fitted
offset: this book's folio-to-page offset changes 24 times.

Figures are pulled with the same `_build_asset_manifest` the MinerU service
uses, so `asset_manifest` has an identical shape and `chapter_context.py`
prints the image names a reader may cite.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db.mariadb import (  # noqa: E402
    SessionLocal,
    create_extraction_stub,
    init_mariadb,
    persist_extraction_result,
)
from app.models.schemas import ExtractionResponse  # noqa: E402
from app.services.mineru_service import _build_asset_manifest  # noqa: E402
from app.utils.config import settings  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BOARD = "CBSE"
# Smaller than this and the "image" is a rule, a bullet or a logo, not a figure
# a question could refer to. 377 raw images in this book; the running-head mark
# repeats on every page and would otherwise land 600 times in the manifest.
MIN_IMAGE_BYTES = 4000


def page_markdown(doc: fitz.Document, index: int, folio: int | None) -> str:
    """One page, headed the way the MinerU markdown heads it.

    `## Page N` is the marker the reading helpers already split on, so keeping
    it means nothing downstream needs to know where the text came from.
    """
    body = doc[index].get_text()
    label = f"## Page {folio}" if folio is not None else f"## Page [pdf {index}]"
    return f"{label}\n\n{body.rstrip()}\n"


def extract_images(doc: fitz.Document, first: int, last: int, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    seen: set[int] = set()
    for index in range(first, last + 1):
        for info in doc[index].get_images(full=True):
            xref = info[0]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                raw = doc.extract_image(xref)
            except Exception:
                continue
            data = raw.get("image")
            if not data or len(data) < MIN_IMAGE_BYTES:
                continue
            path = out_dir / f"p{index:04d}_x{xref}.{raw.get('ext', 'png')}"
            path.write_bytes(data)
            written.append(path)
    return written


def chapter_rows(db, chapter_id: int):
    return db.execute(
        text(
            "SELECT standard_id, subject_id, chapter_name, sort_order "
            "  FROM chapter_master WHERE id = :c"
        ),
        {"c": chapter_id},
    ).fetchone()


def pin_chapter(db, row_id: int, expected: int, title: str, std: int, sub: int) -> None:
    """The stub infers chapter_id from the title; force it to the pinned id.

    Refuses rather than repoints when the inferred chapter belongs to another
    standard or subject -- that means the title matched something it should
    not have, and silently moving it would file a whole book's questions under
    the wrong subject.
    """
    got = db.execute(
        text("SELECT chapter_id FROM document_extractions WHERE id = :i"), {"i": row_id}
    ).scalar()
    if got == expected:
        return
    if got is not None:
        owner = chapter_rows(db, got)
        if owner and (owner[0] != std or owner[1] != sub):
            raise SystemExit(
                f"ABORT: extraction {row_id} ('{title}') resolved to chapter {got} "
                f"'{owner[2]}' in standard {owner[0]}/subject {owner[1]}, not "
                f"standard {std}/subject {sub}. Refusing to guess."
            )
    db.execute(
        text("UPDATE document_extractions SET chapter_id = :c WHERE id = :i"),
        {"c": expected, "i": row_id},
    )
    db.commit()
    print(f"      chapter_id {got} -> {expected} (pinned)")


def run_one(doc, spec: dict, book: dict, resume: bool, apply: bool) -> bool:
    chapter_id = spec["chapter_id"]
    number = spec["number"]
    first, last = spec["pdf_start"], spec["pdf_end"]

    db = SessionLocal()
    try:
        row = chapter_rows(db, chapter_id)
        if not row:
            print(f"  ch {number:<3} chapter_id {chapter_id} not found - skipped")
            return False
        std_id, sub_id, db_name, sort_order = row

        if resume:
            done = db.execute(
                text(
                    "SELECT id, COALESCE(LENGTH(md_content), 0) FROM document_extractions "
                    " WHERE chapter_id = :c AND document_type = 'question_bank' "
                    " ORDER BY id DESC LIMIT 1"
                ),
                {"c": chapter_id},
            ).fetchone()
            if done and done[1] > 2000:
                print(f"  ch {number:<3} {db_name[:40]:<42} already extracted "
                      f"(row {done[0]}, {done[1]:,} chars) - skipped")
                return True
    finally:
        db.close()

    folios = {}
    for folio in range(spec["folio_start"], spec["folio_end"] + 1):
        folios[folio] = None
    # Page order is physical; the folio is only a label on the heading.
    md_parts = []
    folio_cursor = spec["folio_start"]
    for index in range(first, last + 1):
        md_parts.append(page_markdown(doc, index, folio_cursor))
        folio_cursor += 1
    markdown = "\n".join(md_parts)

    slug = f"{book['key']}_ch{number:02d}"
    out_dir = Path(settings.output_dir).resolve() / slug
    started = time.perf_counter()
    images = extract_images(doc, first, last, out_dir) if apply else []
    manifest = _build_asset_manifest(
        out_dir, images, f"{settings.queue_asset_base}/{slug}", None
    ) if images else []

    print(f"  ch {number:<3} {db_name[:40]:<42} pdf {first}-{last} "
          f"{last - first + 1:>3}p  {len(markdown):>8,} chars  {len(images):>3} figs")

    if not apply:
        return True

    row_id = create_extraction_stub(
        document_type="question_bank",
        document_title=db_name,
        chapter_number=sort_order,
        standard=book["standard"],
        subject_name=book["subject_name"],
        board=BOARD,
        syear=book["syear"],
        pdf_url=book["source_url"],
        sub_institute_id=book["tenant"],
    )
    if row_id is None:
        print("      stub creation failed")
        return False

    db = SessionLocal()
    try:
        pin_chapter(db, row_id, chapter_id, db_name, std_id, sub_id)
    finally:
        db.close()

    elapsed = time.perf_counter() - started
    response = ExtractionResponse(
        status="success",
        processing_mode="text_layer",
        markdown_content=markdown,
        json_content={"asset_manifest": manifest} if manifest else None,
        metadata={
            "processing_time": f"{elapsed:.2f}s",
            "cached": False,
            "publisher": book["publisher_name"],
            "extraction_method": "pdf_text_layer",
            "source_pages": f"{first}-{last}",
            "source_folios": f"{spec['folio_start']}-{spec['folio_end']}",
            "asset_manifest": manifest,
        },
        page_count=last - first + 1,
        images_extracted=len(images),
    )
    persist_extraction_result(
        row_id,
        response,
        document_type="question_bank",
        document_title=db_name,
        chapter_number=sort_order,
        standard=book["standard"],
        subject_name=book["subject_name"],
        board=BOARD,
        syear=book["syear"],
        pdf_url=book["source_url"],
        sub_institute_id=book["tenant"],
    )
    db = SessionLocal()
    try:
        pin_chapter(db, row_id, chapter_id, db_name, std_id, sub_id)
    finally:
        db.close()
    print(f"      row {row_id} | {len(markdown):,} md chars | {len(images)} figures "
          f"| {elapsed:.1f}s")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--map", required=True, help="folio map JSON from probe_qbook")
    ap.add_argument("--book", default="cbse9_science_qb2026")
    ap.add_argument("--standard", type=int, default=9)
    ap.add_argument("--subject", default="Science")
    ap.add_argument("--syear", type=int, default=2026)
    ap.add_argument("--tenant", type=int, default=1)
    ap.add_argument("--publisher-name", default="pdf.tube CBSE Chapterwise QB 2026")
    ap.add_argument("--source-url",
                    default="https://pdf.tube/School/CBSE/9th%20Class/Science/"
                            "Science%20QB%202026.pdf")
    ap.add_argument("--chapter", type=int, action="append",
                    help="chapter number; repeatable")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--resume", action="store_true",
                    help="skip chapters already carrying markdown")
    ap.add_argument("--apply", action="store_true",
                    help="write; without it nothing is stored")
    a = ap.parse_args()

    spec = json.loads(Path(a.map).read_text(encoding="utf-8"))
    book = {
        "key": a.book, "standard": a.standard, "subject_name": a.subject,
        "syear": a.syear, "tenant": a.tenant,
        "publisher_name": a.publisher_name, "source_url": a.source_url,
    }

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")

    # chapter_id is not in the folio map; resolve it by sort_order within the
    # book's own standard and subject, which is the only key both sides share.
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                "SELECT c.sort_order, c.id, c.chapter_name FROM chapter_master c "
                "  JOIN subject s ON s.id = c.subject_id "
                " WHERE c.standard_id = (SELECT id FROM standard WHERE name = :std "
                "                          LIMIT 1) "
                "   AND s.subject_name = :sub AND COALESCE(c.show_hide, 1) = 1 "
                " ORDER BY c.sort_order"
            ),
            {"std": str(a.standard), "sub": a.subject},
        ).fetchall()
    finally:
        db.close()
    by_sort = {int(r[0]): (int(r[1]), r[2]) for r in rows}
    if not by_sort:
        raise SystemExit(f"no chapters for standard {a.standard} subject {a.subject}")

    chapters = []
    for ch in spec["chapters"]:
        hit = by_sort.get(ch["number"])
        if not hit:
            print(f"  ch {ch['number']} has no chapter_master row - skipped")
            continue
        chapters.append(dict(ch, chapter_id=hit[0], db_name=hit[1]))

    if a.list:
        print(f"{a.book}: {len(chapters)} chapter(s)")
        for c in chapters:
            print(f"  ch {c['number']:<3} chapter_id {c['chapter_id']:<7} "
                  f"pdf {c['pdf_start']}-{c['pdf_end']:<5} "
                  f"folio {c['folio_start']}-{c['folio_end']:<5} {c['db_name'][:40]}")
        return 0

    wanted = set(a.chapter or [])
    if not wanted and not a.all:
        ap.error("give --chapter N (repeatable), --all, or --list")
    todo = [c for c in chapters if not wanted or c["number"] in wanted]

    doc = fitz.open(spec["pdf"])
    print(f"{spec['pdf']}: {doc.page_count} pages | "
          f"{'WRITING' if a.apply else 'DRY RUN - nothing stored'}\n")
    ok = 0
    for c in todo:
        if run_one(doc, c, book, a.resume, a.apply):
            ok += 1
    print(f"\n{ok} of {len(todo)} chapter(s) handled")
    return 0 if ok == len(todo) else 1


if __name__ == "__main__":
    raise SystemExit(main())
