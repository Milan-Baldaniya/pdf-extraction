"""Find pages inside one chapter's extraction that belong to another chapter.

    python -m scripts.foreign_pages --extraction 599
    python -m scripts.foreign_pages --standard 42 --subject 3975

The book files a chapter's missing folio at the top of the NEXT chapter's
extraction, and it does it often enough to be a rule rather than an accident.
Three confirmed in Class 9 Science alone: chapter 5's questions 132-134 sit in
extraction 597, chapter 6's 193-194 in 598, and chapter 7's 190(c), 191 and 192
in 599, on its pages 337-338.

Every one of those was found by a reader noticing something odd, and one of
them had already been written off as lost in the PDF itself. That conclusion
was one step from being recorded permanently. The running header settles it
mechanically: it names the chapter a page belongs to, not the extraction it
landed in, so a page whose header names a different chapter of the same book is
misfiled and its questions are recoverable.

A misfiled page is worse than a missing one. Its questions look like they
belong to the host chapter, whose closed concept set has nothing that honestly
fits them, so a reader who does not notice buries a good question under a wrong
tag instead of losing it visibly.

Only chapters of the same standard and subject are matched, and only titles of
three or more words, so a short title cannot match ordinary prose.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

PAGE = re.compile(r"##\s*Page\s+(\d+)")
# How much of a page to read looking for its running header. The header is the
# first line after the page marker, but the text layer pads it with tabs and
# blank lines, and on a left-hand page the folio number comes first.
HEAD = 260


def titles_for(db, standard_id: int, subject_id: int) -> dict[int, str]:
    rows = db.execute(
        text("SELECT id, chapter_name FROM chapter_master "
             " WHERE standard_id = :s AND subject_id = :j ORDER BY sort_order"),
        {"s": standard_id, "j": subject_id},
    ).fetchall()
    return {r[0]: r[1] for r in rows if r[1] and len(r[1].split()) >= 3}


# A question number at the start of a line. Knowing WHICH questions are in a
# misfiled block turns recovery from detective work into a lookup: the owning
# chapter's reader is told "your 113, 114 and 115 are over there" instead of
# concluding they are lost, which is what happened three times before this.
NUMBERED = re.compile(r"^\s*(\d{1,3})\s*\.", re.M)

# A displaced page can carry an ANSWER whose question is printed in the other
# extraction. It has no leading number, so counting numbered blocks alone calls
# it "prose only, nothing to file" -- which is a false negative, and a reader
# shown that line may skip a page holding a complete answer. Chapter 10's Q173
# answer sat on exactly such a page and was reported as prose.
ANSWER = re.compile(r"A?Ans\s*:")


def scan(md: str, own: str, others: dict[int, re.Pattern]) -> list[tuple]:
    marks = [(m.start(), m.group(1)) for m in PAGE.finditer(md)]
    found = []
    for index, (start, folio) in enumerate(marks):
        end = marks[index + 1][0] if index + 1 < len(marks) else len(md)
        head = md[start:start + HEAD]
        if own.search(head):
            continue
        for name, pattern in others.items():
            if pattern.search(head):
                # Only numbers that head an answerable block. A worked solution
                # numbers its own parts 1. 2. 3., so the low ones are noise
                # unless the block is genuinely a low-numbered section.
                numbers = sorted({int(n) for n in NUMBERED.findall(md[start:end])})
                answers = len(ANSWER.findall(md[start:end]))
                found.append((start, end, folio, name, numbers, answers))
                break
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--extraction", type=int, action="append")
    ap.add_argument("--standard", type=int)
    ap.add_argument("--subject", type=int)
    a = ap.parse_args()
    if not a.extraction and not (a.standard and a.subject):
        ap.error("give --extraction N (repeatable) or --standard S --subject J")

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        if a.extraction:
            rows = db.execute(
                text("SELECT id, chapter_id FROM document_extractions "
                     " WHERE id IN :e ORDER BY id"),
                {"e": tuple(a.extraction)},
            ).fetchall()
        else:
            rows = db.execute(
                text("SELECT e.id, e.chapter_id FROM document_extractions e "
                     "  JOIN chapter_master c ON c.id = e.chapter_id "
                     " WHERE c.standard_id = :s AND c.subject_id = :j "
                     " ORDER BY c.sort_order"),
                {"s": a.standard, "j": a.subject},
            ).fetchall()
        if not rows:
            raise SystemExit("no extractions matched")

        first = db.execute(
            text("SELECT standard_id, subject_id FROM chapter_master WHERE id = :c"),
            {"c": rows[0][1]},
        ).fetchone()
        titles = titles_for(db, a.standard or first[0], a.subject or first[1])

        total = 0
        for extraction_id, chapter_id in rows:
            md = db.execute(
                text("SELECT md_content FROM document_extractions WHERE id = :e"),
                {"e": extraction_id},
            ).scalar() or ""
            own_title = titles.get(chapter_id, "")
            if not own_title:
                print(f"extraction {extraction_id}: chapter title too short to "
                      f"match on, skipped")
                continue
            spaced = lambda t: re.compile(r"\s+".join(re.escape(w) for w in t.split()),
                                          re.I)
            others = {name: spaced(name) for cid, name in titles.items()
                      if cid != chapter_id}
            hits = scan(md, spaced(own_title), others)
            if not hits:
                continue
            total += len(hits)
            print(f"\nextraction {extraction_id}  {own_title!r}")
            for start, end, folio, name, numbers, answers in hits:
                print(f"    page {folio:>4}  chars {start:>7} - {end:<7} "
                      f"({end - start:>5,})  belongs to {name!r}")
                high = [n for n in numbers if n > 8]
                if high:
                    print(f"              numbered blocks in it: {high}")
                elif numbers:
                    print(f"              only low numbers {numbers} - probably "
                          f"sub-parts or prose, check before claiming questions")
                if answers and not high:
                    print(f"              but {answers} answer marker(s) with no "
                          f"question number: almost certainly a stranded ANSWER "
                          f"whose question is printed in the other extraction. "
                          f"OPEN IT.")
                elif not answers and not numbers:
                    print(f"              no numbered blocks and no answer "
                          f"markers - prose only")
    finally:
        db.close()

    if total:
        print(f"\n{total} misfiled page(s). Their questions belong to the named "
              f"chapter, not the extraction they sit in.")
        print("Read them from the host extraction and file them under the "
              "chapter the header names; do NOT tag them with the host "
              "chapter's concepts.")
    else:
        print("no misfiled pages found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
