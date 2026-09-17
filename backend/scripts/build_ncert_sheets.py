"""Build a queue sheet per class, from the live NCERT textbook catalogue.

`build_extraction_sheet.py` builds rows from `chapter_master`, which is right
when the syllabus is already in the database. It is useless for a class that is
not there yet -- and Class 9 and 10 between them have thirty-odd textbooks of
which the database knows four.

So this reads the catalogue from the source instead: ncert.nic.in/textbook.php
carries, in the JavaScript that drives its dropdowns, every book NCERT
publishes -- class, subject, title, book code and chapter count. That is the
authoritative list, and scraping it means the sheet reflects whatever NCERT
publishes today rather than what was true when this file was written.

    python -m scripts.build_ncert_sheets --class 9 --class 10
    python -m scripts.build_ncert_sheets --class 10 --list      # show, write nothing

Two things this script will NOT guess:

  * A book code. Every code comes out of NCERT's own page. A code invented by
    pattern-matching yields thirteen perfectly valid PDFs of the wrong book and
    no error anywhere, which is the worst failure this pipeline has.
  * A chapter title. Titles come from `chapter_master` where the database has
    the chapter under the same name, or under a hand-verified alias. Everything
    else gets a provisional title ("<Book> - Chapter 3") and the log says how
    many of each. A provisional title is visible and fixable; a wrongly guessed
    one is neither.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402
from app.utils.config import settings  # noqa: E402
from scripts import build_extraction_sheet as bes  # noqa: E402
from scripts import queue_sheet as qs  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
logger = logging.getLogger("ncert")

CATALOGUE_URL = "https://ncert.nic.in/textbook.php"
PDF_URL = "https://ncert.nic.in/textbook/pdf/{code}{chapter:02d}.pdf"
QUEUE_DIR = Path(__file__).resolve().parents[1] / "queue"

# NCERT encodes the medium in the code's second character: jesc1 is English,
# jhsc1 the same book in Hindi, jusc1 in Urdu. For an ordinary subject only the
# English edition is wanted -- but for a LANGUAGE subject the Hindi book *is*
# the subject, so every book it lists is kept.
LANGUAGE_SUBJECTS = {"hindi", "sanskrit", "urdu"}

# The dropdown-building JavaScript, which is the catalogue.
_BLOCK = re.compile(
    r"\(document\.test\.tclass\.value==(\d+)\)\s*&&\s*"
    r"\(document\.test\.tsubject\.options\[sind\]\.text==\"([^\"]+)\"\)"
)
_TEXT = re.compile(
    r"^\s*document\.test\.tbook\.options\[(\d+)\]\.text=\"([^\"]*)\";?\s*$", re.M
)
_VALUE = re.compile(
    r"^\s*document\.test\.tbook\.options\[(\d+)\]\.value="
    r"\"textbook\.php\?([a-zA-Z0-9]+)=(\d+)-(\d+)\"\s*;?\s*$",
    re.M,
)


# --------------------------------------------------------------------------
# the catalogue
# --------------------------------------------------------------------------

def fetch_catalogue(cache: Path | None = None) -> str:
    """The textbook page's HTML, cached so a rebuild does not re-download it."""
    if cache and cache.exists():
        logger.info("Using cached catalogue: %s", cache)
        return cache.read_text(encoding="utf-8", errors="replace")

    logger.info("Fetching %s", CATALOGUE_URL)
    request = urllib.request.Request(
        CATALOGUE_URL, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    )

    # ncert.nic.in closes connections under repeated traffic and serves normally
    # again after a pause, so a single failed fetch means nothing.
    html = ""
    delay = 15.0
    for attempt in range(1, 5):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:  # noqa: S310
                html = response.read().decode("utf-8", errors="replace")
            break
        except Exception as exc:
            if attempt == 4:
                raise RuntimeError(
                    f"Could not reach {CATALOGUE_URL} after 4 attempts: {exc}. "
                    "Pass --cache <file> to reuse a copy fetched earlier."
                ) from exc
            logger.warning(
                "  fetch failed (%d/4): %s -- retrying in %.0fs", attempt, str(exc)[:90], delay
            )
            time.sleep(delay)
            delay *= 2

    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(html, encoding="utf-8")
    return html


def parse_catalogue(html: str) -> dict[int, dict[str, list[dict[str, Any]]]]:
    """{class: {subject: [{title, code, chapters}]}} exactly as NCERT lists it."""
    marks = [(m.start(), int(m.group(1)), m.group(2)) for m in _BLOCK.finditer(html)]
    catalogue: dict[int, dict[str, list[dict[str, Any]]]] = {}

    for index, (start, klass, subject) in enumerate(marks):
        end = marks[index + 1][0] if index + 1 < len(marks) else len(html)
        block = html[start:end]
        titles = {int(i): t for i, t in _TEXT.findall(block)}
        books = []
        for i, code, _lo, hi in _VALUE.findall(block):
            # The range is 0-N: index 0 is the front matter, N is the last
            # chapter, so N is the chapter count.
            books.append(
                {"title": titles.get(int(i), code), "code": code, "chapters": int(hi)}
            )
        if books:
            catalogue.setdefault(klass, {})[subject] = books
    return catalogue


def english_medium(subject: str, books: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop translations, keep every book of a language subject."""
    if subject.strip().lower() in LANGUAGE_SUBJECTS:
        return books
    english = [b for b in books if len(b["code"]) > 1 and b["code"][1] == "e"]
    # A subject whose books follow no such convention keeps all of them rather
    # than silently becoming empty.
    return english or books


# --------------------------------------------------------------------------
# titles
# --------------------------------------------------------------------------

def known_titles(tenant: int, standard: str) -> dict[str, dict[int, str]]:
    """{subject_lower: {chapter_number: title}} from chapter_master."""
    out: dict[str, dict[int, str]] = {}
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT sub.subject_name, cm.sort_order, cm.chapter_name
                  FROM chapter_master cm
                  JOIN standard st ON st.id = cm.standard_id AND st.sub_institute_id = :t
                  JOIN subject sub ON sub.id = cm.subject_id
                 WHERE cm.sub_institute_id = :t AND st.name = :s
                 GROUP BY sub.subject_name, cm.sort_order, cm.chapter_name
                """
            ),
            {"t": tenant, "s": str(standard)},
        ).fetchall()
    for subject, sort_order, name in rows:
        if sort_order is None:
            continue
        out.setdefault(str(subject).strip().lower(), {})[int(sort_order)] = str(name).strip()
    return out


def subject_names(tenant: int) -> dict[str, str]:
    """{lowercased: exact spelling} of every subject the tenant has.

    The sheet must carry the database's spelling, not NCERT's, or `_map_ids`
    resolves subject_id to NULL and the extraction attaches to nothing.
    """
    with SessionLocal() as db:
        rows = db.execute(
            text("SELECT subject_name FROM subject WHERE sub_institute_id = :t"),
            {"t": tenant},
        ).fetchall()
    return {str(r[0]).strip().lower(): str(r[0]).strip() for r in rows}


# NCERT and the database spell subjects differently, and only a human reading
# both can say whether two names are the same book. Each entry here was checked
# by downloading the NCERT chapter and comparing its first page against the
# chapter_master titles -- (class, NCERT subject) -> chapter_master subject.
#
# Do NOT add entries by pattern. A count-and-prefix heuristic was tried and
# matched Class 9 "Hindi" (Ganga, 12 chapters) to "Hindi-A", whose chapter 1 is
# "Hindi Curriculum" -- a different book that happened to collapse to twelve
# distinct sort_orders. A wrong title here is invisible and permanent.
VERIFIED_ALIASES: dict[tuple[int, str], str] = {
    # iest101 page 1 reads "Understanding Social Science Chapter 1", which is
    # chapter_master's Social Sciences-2 chapter 1 verbatim.
    (9, "social science"): "social sciences-2",
}


def match_titles(
    standard: int,
    ncert_subject: str,
    sheet_subject: str,
    titles: dict[str, dict[int, str]],
) -> dict[int, str]:
    """The chapter_master titles for this book, if the database has them.

    Exact name match, or a hand-verified alias. Nothing else -- an unmatched
    book gets provisional titles, which is a visible, fixable state, whereas a
    wrongly matched one is neither.
    """
    for candidate in (sheet_subject, ncert_subject):
        exact = titles.get(candidate.strip().lower())
        if exact:
            return exact

    alias = VERIFIED_ALIASES.get((int(standard), ncert_subject.strip().lower()))
    if alias and titles.get(alias):
        logger.info("      '%s' -> chapter_master '%s' (verified alias)", ncert_subject, alias)
        return titles[alias]
    return {}


def resolve_subject(ncert_subject: str, book_title: str, many: bool, known: dict[str, str]) -> str:
    """What to write in subject_name.

    A subject with several books needs one sheet-subject per book, or every book
    would claim chapter 1 and the rows would collide on the queue key. The
    database already works this way -- 'Social Sciences', 'Social Sciences-2'.
    """
    base = known.get(ncert_subject.strip().lower(), ncert_subject.strip())
    if not many:
        return base
    return f"{base} - {book_title.strip()}"


# --------------------------------------------------------------------------

def build_rows_for_class(
    standard: str,
    catalogue: dict[str, list[dict[str, Any]]],
    *,
    board: str,
    tenant: int,
    syear: int,
) -> tuple[list[qs.QueueRow], list[str]]:
    titles = known_titles(tenant, standard)
    known_subjects = subject_names(tenant)

    rows: list[qs.QueueRow] = []
    notes: list[str] = []

    for ncert_subject, all_books in sorted(catalogue.items()):
        books = english_medium(ncert_subject, all_books)
        many = len(books) > 1
        for book in books:
            subject = resolve_subject(ncert_subject, book["title"], many, known_subjects)
            have = match_titles(int(standard), ncert_subject, subject, titles)
            filled = 0
            for chapter in range(1, book["chapters"] + 1):
                title = have.get(chapter)
                if title:
                    filled += 1
                else:
                    # Provisional. Honest about being provisional, and unique,
                    # so it can be found and replaced later.
                    title = f"{book['title']} - Chapter {chapter}"
                rows.append(
                    qs.QueueRow(
                        enabled="yes",
                        board=board,
                        standard=int(standard),
                        subject_name=subject,
                        chapter_number=chapter,
                        document_title=title,
                        document_type="Chapter",
                        syear=syear,
                        sub_institute_id=tenant,
                        pdf_url=PDF_URL.format(code=book["code"], chapter=chapter),
                        status="pending",
                    )
                )
            notes.append(
                f"  {subject:<46} {book['code']:<14} {book['chapters']:>2} ch"
                f"  titles {filled}/{book['chapters']}"
            )
    return rows, notes


def write_sheet(path: Path, rows: list[qs.QueueRow]) -> int:
    """A fresh workbook. Any existing one is replaced -- this is a rebuild."""
    path.unlink(missing_ok=True)
    bes.create_workbook(path)
    return bes.append_rows(path, rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--class", dest="classes", action="append", required=True,
        help="class number; repeat for more than one (--class 9 --class 10)",
    )
    parser.add_argument("--board", default="CBSE")
    parser.add_argument("--tenant", type=int)
    parser.add_argument("--syear", type=int, default=2026)
    parser.add_argument("--out-dir", type=Path, default=QUEUE_DIR)
    parser.add_argument("--cache", type=Path, help="reuse/save the fetched catalogue here")
    parser.add_argument("--list", action="store_true", help="show the catalogue, write nothing")
    parser.add_argument(
        "--all-media",
        action="store_true",
        help="include Hindi/Urdu editions of English-medium books",
    )
    args = parser.parse_args()

    if not init_mariadb() or SessionLocal is None:
        logger.error("MariaDB is unreachable; check the MARIADB_* settings in .env")
        return 2

    tenant = args.tenant if args.tenant is not None else settings.tenant_for_board(args.board)
    catalogue = parse_catalogue(fetch_catalogue(args.cache))
    if not catalogue:
        logger.error("Could not parse the NCERT catalogue -- the page layout may have changed")
        return 2

    if args.all_media:
        global english_medium  # noqa: PLW0603
        english_medium = lambda _subject, books: books  # noqa: E731

    written: list[tuple[Path, int]] = []
    for klass in args.classes:
        subjects = catalogue.get(int(klass))
        if not subjects:
            logger.error("NCERT lists no books for class %s", klass)
            continue

        rows, notes = build_rows_for_class(
            str(klass), subjects, board=args.board, tenant=tenant, syear=args.syear
        )
        logger.info("")
        logger.info("CLASS %s  (%s, tenant %s)", klass, args.board, tenant)
        for note in notes:
            logger.info("%s", note)
        logger.info("  %d chapter(s) across %d book(s)", len(rows), len(notes))

        if args.list:
            continue

        path = args.out_dir / f"class{klass}_{args.board.lower()}_queue.xlsx"
        added = write_sheet(path, rows)
        written.append((path, added))
        logger.info("  -> %s  (%d rows)", path, added)

    if written:
        logger.info("")
        logger.info("Built %d sheet(s):", len(written))
        for path, added in written:
            logger.info("  %-52s %3d rows", path.name, added)
        logger.info("")
        logger.info("Check one before running it:")
        logger.info("  python -m scripts.run_extraction_queue --sheet %s --list", written[0][0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
