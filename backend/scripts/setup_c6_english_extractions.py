"""Create the `document_extractions` rows for the Class 6 English (Poorvi) bank.

    python -m scripts.setup_c6_english_extractions            # report only
    python -m scripts.setup_c6_english_extractions --apply    # INSERT

One row per (chapter x source file), for the sixteen real chapters only.

THE CHAPTER IDS ARE WRITTEN OUT AND NOTHING IS LOOKED UP BY sort_order. Class 6
English holds twenty-one chapter rows: the sixteen texts, 29860-29875, and five
unit-level placeholders, 29889-29893 ("Poorvi Unit 1 - Fables and Folk Tales"
... "Unit 5"), which share sort_order 1..5 with the first five real chapters.
A resolver keyed on sort_order therefore has two candidates for chapters 1-5 and
would file a third of the bank against rows that are not chapters. Every id here
comes from scripts.parse_c6_english.CHAPTERS, and the database's own
chapter_name is asserted against it before anything is written.

TWO PUBLISHERS, REGISTERED SEPARATELY. These are commercial publishers'
editorial content, ingested on the condition that it stays identifiable, and
"studentbro" and "vedantu" are different companies with different terms. One
combined publisher row would make the two indistinguishable the moment anyone
asks where a question came from. `pdf_url` carries the real source URL for the
same reason -- a local mirror path names a file on one laptop and attributes
nothing.

IDENTITY IS content_sha256 + chapter_id. A chapter that already has a row for a
given file is skipped, so re-running after a parser fix updates nothing and
duplicates nothing.
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

from scripts.fetch_c6_english_sources import SOURCES, url_for  # noqa: E402
from scripts.parse_c6_english import (  # noqa: E402
    CHAPTERS, SB, UNIT_MEMBERS, VD,
)

STANDARD_ID, SUBJECT_ID, STANDARD, SUBJECT = 39, 3978, 6, "English"
INST, SYEAR, BOARD = 1, 2026, "CBSE"

PLACEHOLDERS = (29889, 29890, 29891, 29892, 29893)

PUBLISHERS = {
    "studentbro": ("StudentBro", "https://studentbro.in/"),
    "vedantu": ("Vedantu", "https://www.vedantu.com/"),
}

# local path, publisher code, unit, family, document title, source url
def _plan() -> list[tuple[Path, str, int, str, str, str]]:
    plan: list[tuple[Path, str, int, str, str, str]] = []
    titles = {
        "sol": "NCERT Solutions, Class 6 English (Poorvi) Unit {u}",
        "mcqbig": "Class 6 English (Poorvi) Unit {u} MCQ and question bank",
        "mcq": "Class 6 English (Poorvi) Unit {u} MCQ set",
    }
    for name, urlpath, fam, unit in SOURCES:
        if fam == "mcqbig":
            family = "mcq"
        elif fam == "mcq":
            family = "mcq"
        else:
            family = "sol"
        plan.append((SB / name, "studentbro", unit, family,
                     titles[fam].format(u=unit), url_for(urlpath)))
    for unit in (1, 2, 3, 4, 5):
        plan.append((VD / f"iq_ch{unit:02d}.pdf", "vedantu", unit, "iq",
                     f"Important Questions, Class 6 English (Poorvi) Unit {unit}",
                     "https://www.vedantu.com/ncert-solutions/"
                     "ncert-solutions-class-6-english-poorvi"))
    return plan


INSERT = text("""
    INSERT INTO document_extractions
      (document_type, document_tittle, chapter_number, standard,
       standard_id, subject_name, subject_id, chapter_id,
       sub_institute_id, board, syear, pdf_url, page_count,
       image_extracted, extraction_metadata, content_sha256,
       extraction_status, publisher_id, updated_at)
    VALUES
      ('question_bank', :t, :n, :std, :sid, :sn, :jid, :cid,
       :inst, :b, :y, :u, :pc, 0, :meta, :sha, 'extracted', :pub, NOW())
""")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        # The names are asserted, not fetched. A chapter_id whose row has moved
        # or been renamed must stop this script, because the whole safety of the
        # id-first approach rests on the ids still meaning what they meant.
        rows = {
            int(r[0]): (r[1], int(r[2] or 0), int(r[3] or 0))
            for r in db.execute(text(
                "SELECT id, chapter_name, standard_id, subject_id "
                "  FROM chapter_master WHERE id IN :ids"),
                {"ids": tuple(c[1] for c in CHAPTERS)}).fetchall()
        }
        problems = []
        for so, cid, name, _u in CHAPTERS:
            if cid not in rows:
                problems.append(f"chapter_id {cid} ({name}) does not exist")
                continue
            got, std, subj = rows[cid]
            if (got or "").strip() != name:
                problems.append(f"chapter_id {cid} is {got!r}, expected {name!r}")
            if std != STANDARD_ID or subj != SUBJECT_ID:
                problems.append(f"chapter_id {cid} is standard {std} subject {subj}, "
                                f"expected {STANDARD_ID}/{SUBJECT_ID}")
        if problems:
            print("chapter_master does not match CHAPTERS -- nothing written:")
            for p in problems:
                print("  " + p)
            return 1
        print(f"verified {len(CHAPTERS)} chapter rows 29860-29875 by id and name")
        print(f"placeholders {PLACEHOLDERS} are excluded by construction\n")

        pubs: dict[str, int | None] = {}
        if a.apply:
            for code, (name, _site) in PUBLISHERS.items():
                # licence_type is varchar(64) and the INSERT is not truncated,
                # it is REFUSED, so a sentence here loses the publisher row and
                # with it every row's attribution.
                p = ensure_publisher(
                    code=code, name=name, board=BOARD,
                    licence_type="Commercial - permission required")
                pubs[code] = p["id"] if p else None
                print(f"publisher {code:<12} -> id {pubs[code]}")
            print()

        print(f"  {'ch':>3} {'cid':>7} {'chapter':<34} {'family':<4} "
              f"{'file':<26} {'pages':>5}  action")
        print("  " + "-" * 104)
        made = skipped = 0
        for path, code, unit, family, title, url in _plan():
            if not path.exists():
                print(f"  {'-':>3} {'-':>7} {'':<34} {family:<4} "
                      f"{path.name:<26} {'-':>5}  SOURCE MISSING")
                continue
            raw = path.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            doc = fitz.open(path)
            pages = doc.page_count
            doc.close()
            have = {int(r[0]) for r in db.execute(text(
                "SELECT chapter_id FROM document_extractions "
                " WHERE content_sha256 = :h"), {"h": sha}).fetchall()}
            for so in UNIT_MEMBERS[unit]:
                cid, name = next((c[1], c[2]) for c in CHAPTERS if c[0] == so)
                if cid in PLACEHOLDERS:
                    raise SystemExit("refusing to write against a placeholder row")
                if cid in have:
                    skipped += 1
                    print(f"  {so:>3} {cid:>7} {name[:34]:<34} {family:<4} "
                          f"{path.name:<26} {pages:>5}  skip, row exists")
                    continue
                meta = json.dumps({
                    "source": PUBLISHERS[code][0],
                    "family": family,
                    "unit": unit,
                    "unit_members": UNIT_MEMBERS[unit],
                    "file_name": path.name,
                    "file_sha256": sha,
                    "source_url": url,
                    "parser": "scripts/parse_c6_english.py",
                    "note": "The source is organised by unit; this row is one "
                            "chapter of that unit. Chapter attribution is read "
                            "from the printed chapter heading (sol, iq) or from "
                            "the paper order within the file, checked against "
                            "chapter vocabulary derived from the sol family "
                            "(mcq). Placeholder rows 29889-29893 are excluded.",
                })
                if a.apply:
                    db.execute(INSERT, {
                        "t": f"{name} -- {title}", "n": so, "std": STANDARD,
                        "sid": STANDARD_ID, "sn": SUBJECT, "jid": SUBJECT_ID,
                        "cid": cid, "inst": INST, "b": BOARD, "y": SYEAR,
                        "u": url, "pc": pages, "meta": meta, "sha": sha,
                        "pub": pubs.get(code)})
                    made += 1
                print(f"  {so:>3} {cid:>7} {name[:34]:<34} {family:<4} "
                      f"{path.name:<26} {pages:>5}  "
                      f"{'INSERT' if a.apply else 'would insert'}")
        if a.apply:
            db.commit()
            print(f"\ninserted {made} row(s), skipped {skipped}")
            print("\n  chapter rows now carrying question_bank extractions:")
            for r in db.execute(text(
                "SELECT e.chapter_id, c.chapter_name, COUNT(*) n, "
                "       GROUP_CONCAT(DISTINCT e.publisher_id) pubs "
                "  FROM document_extractions e "
                "  JOIN chapter_master c ON c.id = e.chapter_id "
                " WHERE e.chapter_id IN :ids AND e.document_type='question_bank' "
                " GROUP BY e.chapter_id, c.chapter_name ORDER BY e.chapter_id"),
                {"ids": tuple(c[1] for c in CHAPTERS)}).fetchall():
                print(f"    {r[0]}  {str(r[1])[:44]:<44} rows={r[2]} pubs={r[3]}")
        else:
            print(f"\nreport only ({skipped} row(s) already present) -- "
                  f"re-run with --apply")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
