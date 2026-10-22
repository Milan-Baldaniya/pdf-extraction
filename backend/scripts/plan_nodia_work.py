"""Emit the section work-list for chapters that are extracted but not yet read.

    python -m scripts.plan_nodia_work            # human-readable
    python -m scripts.plan_nodia_work --json     # the args payload for the workflow

Each printed chapter is split into its marks sections (OBJECTIVE / ONE MARK /
... / CASE BASED) and each section becomes one unit of work with an explicit
character range, so a reader is handed a slice rather than a whole chapter.

Sections are found by their printed headings. A chapter whose headings MinerU
scrambled still yields one range per heading it did find, and any text before
the first heading is reported as an uncovered gap rather than silently skipped -
losing a run of questions to a heading that moved is exactly how a chapter ends
up quietly short.
"""
from __future__ import annotations
import argparse, io, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text  # noqa: E402
from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402
# The chapter map and subject differ per book, so they are chosen at run time
# rather than imported once. Adding a subject means adding a line here, not
# copying this file.
from scripts import extract_sci10_qbank as _sci10  # noqa: E402
from scripts import extract_maths10_qbank as _maths10  # noqa: E402

BOOKS = {"sci10": _sci10, "maths10": _maths10}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PARTS = Path(__file__).resolve().parent / "nodia_items" / "parts"

HEAD = re.compile(
    r"(OBJECTIVE QUESTION[S]?|ONE MARK QUESTIONS?|TWO MARKS? QUESTIONS?"
    r"|THREE MARKS? QUESTIONS?|FOUR MARKS? QUESTIONS?|FIVE MARKS? QUESTIONS?"
    r"|CASE BASED[A-Z ]*)")

# Compiled once: writing this inline as a string literal is how it previously
# ended up containing backspace characters instead of word boundaries, which
# silently matched nothing and hid every pre-heading question.
_ANS_RE = re.compile("(?<![A-Za-z])Ans(?![A-Za-z])")

SLUG = {"OBJECTIVE QUESTIONS": "obj", "OBJECTIVE QUESTION": "obj",
        "ONE MARK QUESTIONS": "one", "ONE MARK QUESTION": "one",
        "TWO MARKS QUESTIONS": "two", "TWO MARK QUESTIONS": "two",
        "THREE MARKS QUESTIONS": "three", "THREE MARK QUESTIONS": "three",
        "FOUR MARKS QUESTIONS": "four", "FIVE MARKS QUESTIONS": "five",
        "FIVE MARK QUESTIONS": "five"}


def slug_for(heading: str) -> str:
    if heading in SLUG:
        return SLUG[heading]
    return "case" if heading.startswith("CASE") else re.sub(r"[^a-z]", "", heading.lower())[:6]


def _textlayer_sections(book: str, chapter: int) -> list[tuple[int, str]]:
    """Section headings as the BOOK prints them, from the PDF's own text layer."""
    try:
        from scripts.textlayer import text_of
        body = text_of(book, chapter)
    except Exception:
        return []
    out, seen = [], set()
    for m in HEAD.finditer(body):
        h = m.group(1).strip()
        if h not in seen:
            seen.add(h)
            out.append((m.start(), h, body[m.end():m.end() + 260]))
    out.sort()
    return out


def _locate(md: str, probe: str, after: int = 0) -> int:
    """Find where `probe` (text-layer wording) starts inside MinerU's markdown.

    The two texts never agree character for character - MinerU wraps formulas in
    LaTeX and drops words - so this matches the probe's first few real words in
    order, tolerating arbitrary junk between them.
    """
    words = [w for w in re.findall(r"[A-Za-z]{4,}", probe)][:5]
    if len(words) < 3:
        return -1
    for take in (5, 4, 3):
        if len(words) < take:
            continue
        pat = re.compile(r".{0,120}?".join(re.escape(w) for w in words[:take]),
                         re.IGNORECASE | re.DOTALL)
        m = pat.search(md, after)
        if m:
            return m.start()
    return -1


def _recover_missing_sections(md: str, secs: list[tuple[int, str]], book: str,
                              chapter: int) -> list[str]:
    """Insert sections the book prints but MinerU's OCR lost.

    Chapter 3 is why this exists: the book prints OBJECTIVE, ONE MARK, THREE
    MARKS and FIVE MARKS, but "ONE MARK QUESTIONS" never made it into the
    markdown. Planning from the markdown alone put 49 questions into one
    "OBJECTIVE" slice, which would have stored a whole section of one-mark
    questions as MCQs - or left them unread, the way chapter 5 and 7 of the
    science bank lost their bleed blocks.
    """
    printed = _textlayer_sections(book, chapter)
    if not printed:
        return []
    have = {h for _, h in secs}
    notes = []
    for _, heading, following in printed:
        if heading in have:
            continue
        pos = _locate(md, following)
        if pos < 0:
            notes.append(f"        !! the book prints {heading!r} but it is absent "
                         f"from the markdown AND could not be located - read by hand")
            continue
        secs.append((pos, heading))
        notes.append(f"        recovered {heading!r} at {pos:,} from the PDF text "
                     f"layer (MinerU lost the heading)")
    secs.sort()
    return notes


def _split_points(md: str, start: int, end: int, book: str, chapter: int,
                  max_chars: int) -> list[int]:
    """Cut an oversized section into reader-sized pieces at question boundaries.

    A 116,000-character slice is three times anything a single reader has
    handled well, and the failure mode is silent - the reader thins out rather
    than stopping. Cutting mid-question is worse than a big slice, so the cuts
    are made at printed question numbers: the text layer lists them cleanly at
    line starts, and each chosen question's own wording is then located in the
    markdown.
    """
    span = end - start
    if span <= max_chars:
        return []
    pieces = -(-span // max_chars)                       # ceil
    try:
        from scripts.textlayer import text_of
        body = text_of(book, chapter)
    except Exception:
        return []

    # Printed question numbers, in order, with the words that follow each.
    anchors = [(m.start(), int(m.group(1)), body[m.end():m.end() + 200])
               for m in re.finditer(r"(?m)^(\d{1,3})\.\s", body)]
    if len(anchors) < pieces * 2:
        return []

    # Keep only the anchors that fall inside this section of the MARKDOWN.
    inside = []
    for _, number, following in anchors:
        pos = _locate(md, following, start)
        if start < pos < end:
            inside.append((pos, number))
    inside.sort()
    if len(inside) < pieces * 2:
        return []

    cuts = []
    for k in range(1, pieces):
        want = start + (span * k) // pieces
        pos, _ = min(inside, key=lambda t: abs(t[0] - want))
        if cuts and pos <= cuts[-1]:
            continue
        if start < pos < end:
            cuts.append(pos)
    return cuts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--chapter", type=int, action="append",
                    help="limit to these chapter numbers (repeatable)")
    ap.add_argument("--include-read", action="store_true",
                    help="include chapters whose part files already exist")
    ap.add_argument("--max-chars", type=int, default=45000,
                    help="split a section larger than this across several readers")
    ap.add_argument("--book", choices=sorted(BOOKS), default="sci10",
                    help="which question bank to plan (default sci10)")
    a = ap.parse_args()

    book = BOOKS[a.book]
    PAGE_MAP, STANDARD_ID, SUBJECT_ID = book.CHAPTERS, book.STANDARD_ID, book.SUBJECT_ID
    prefix = "ch" if a.book == "sci10" else "mch"
    by_chapter_id = {cid: (num, name) for num, cid, name in PAGE_MAP.values() if cid}
    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    work, report = [], []
    try:
        rows = db.execute(text(
            "SELECT chapter_id, MAX(id) FROM document_extractions "
            " WHERE standard_id = :s AND subject_id = :su AND document_type = 'question_bank' "
            "   AND extraction_status = 'extracted' GROUP BY chapter_id"),
            {"s": STANDARD_ID, "su": SUBJECT_ID}).fetchall()
        for chapter_id, eid in sorted(rows, key=lambda r: by_chapter_id.get(r[0], (99,))[0]):
            if chapter_id not in by_chapter_id:
                continue
            num, name = by_chapter_id[chapter_id]
            if a.chapter and num not in a.chapter:
                continue
            done = sorted(PARTS.glob(f"{prefix}{num:02d}_*.json"))
            if done and not a.include_read:
                report.append(f"  ch {num:<3} {name[:34]:<36} already read ({len(done)} part file(s))")
                continue

            md = db.execute(text("SELECT md_content FROM document_extractions WHERE id = :i"),
                            {"i": int(eid)}).scalar() or ""
            seen, secs = set(), []
            for m in HEAD.finditer(md):
                h = m.group(1).strip()
                if h in seen:
                    continue
                seen.add(h)
                secs.append((m.start(), h))
            secs.sort()
            for note in _recover_missing_sections(md, secs, a.book, num):
                report.append(note)
            if not secs:
                report.append(f"  ch {num:<3} {name[:34]:<36} NO SECTION HEADINGS FOUND - needs a look")
                continue
            report.append(f"  ch {num:<3} {name[:34]:<36} {len(md):,} chars, {len(secs)} sections"
                          f"  (first heading at {secs[0][0]:,})")

            # MinerU reorders pages, so a chapter's first printed heading can
            # land well after questions that belong under it. Chapters 5, 7 and
            # 8 each carry real questions before their first heading - 9, 25 and
            # 35 answer markers - and slicing from the heading alone dropped
            # every one of them. Anything before it with more than a couple of
            # answer markers is its own unit of work.
            head_answers = len(re.findall(_ANS_RE, md[:secs[0][0]]))
            if head_answers > 3:
                work.append({"chapter": num, "chapter_id": int(chapter_id),
                             "extraction_id": int(eid), "name": name,
                             "section": "PRE-HEADING (questions printed before the first section heading)",
                             "slug": "pre", "start": 0, "end": secs[0][0],
                             "out": f"{prefix}{num:02d}_pre.json"})
                report.append(f"        {'PRE-HEADING':<24} {0:>7}-{secs[0][0]:<7} "
                              f"({secs[0][0]:,}, {head_answers} answer markers)")
            for i, (pos, h) in enumerate(secs):
                end = secs[i + 1][0] if i + 1 < len(secs) else len(md)
                slug = slug_for(h)
                cuts = _split_points(md, pos, end, a.book, num, a.max_chars)
                bounds = [pos, *cuts, end]
                for k in range(len(bounds) - 1):
                    lo, hi = bounds[k], bounds[k + 1]
                    part = slug if len(bounds) == 2 else f"{slug}{chr(ord('a') + k)}"
                    work.append({"chapter": num, "chapter_id": int(chapter_id),
                                 "extraction_id": int(eid), "name": name, "section": h,
                                 "slug": part, "start": lo, "end": hi,
                                 "out": f"{prefix}{num:02d}_{part}.json"})
                    label = h if len(bounds) == 2 else f"{h} ({k + 1}/{len(bounds) - 1})"
                    report.append(f"        {label:<30} {lo:>7}-{hi:<7} ({hi - lo:,})")
                if cuts:
                    report.append(f"        ^ split into {len(cuts) + 1} at printed "
                                  f"question boundaries (over {a.max_chars:,} chars)")
    finally:
        db.close()

    if a.json:
        print(json.dumps({"work": work}, ensure_ascii=False))
    else:
        print("\n".join(report))
        print(f"\n  {len(work)} section(s) of work across "
              f"{len({w['chapter'] for w in work})} chapter(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
