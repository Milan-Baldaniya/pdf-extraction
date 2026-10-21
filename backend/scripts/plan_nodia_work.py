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
from scripts.extract_sci10_qbank import CHAPTERS as PAGE_MAP, STANDARD_ID, SUBJECT_ID  # noqa: E402

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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--chapter", type=int, action="append",
                    help="limit to these chapter numbers (repeatable)")
    ap.add_argument("--include-read", action="store_true",
                    help="include chapters whose part files already exist")
    a = ap.parse_args()

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
            done = sorted(PARTS.glob(f"ch{num:02d}_*.json"))
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
                             "out": f"ch{num:02d}_pre.json"})
                report.append(f"        {'PRE-HEADING':<24} {0:>7}-{secs[0][0]:<7} "
                              f"({secs[0][0]:,}, {head_answers} answer markers)")
            for i, (pos, h) in enumerate(secs):
                end = secs[i + 1][0] if i + 1 < len(secs) else len(md)
                slug = slug_for(h)
                work.append({"chapter": num, "chapter_id": int(chapter_id),
                             "extraction_id": int(eid), "name": name, "section": h,
                             "slug": slug, "start": pos, "end": end,
                             "out": f"ch{num:02d}_{slug}.json"})
                report.append(f"        {h:<24} {pos:>7}-{end:<7} ({end - pos:,})")
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
