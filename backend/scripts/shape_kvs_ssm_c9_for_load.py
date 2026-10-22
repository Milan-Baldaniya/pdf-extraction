"""Cut the KVS ZIET Mysuru draft into the per-chapter files the loader expects.

    python -m scripts.shape_kvs_ssm_c9_for_load
    python -m scripts.shape_kvs_ssm_c9_for_load --write

`load_nodia_items` reads `{"chapter": N, "extraction_id": E, "items": [...]}`
and addresses rows by `extraction_id`, so the draft's flat list is cut per
chapter and paired with the row `setup_kvs_ssm_c9_extractions` made. `chapter`
is OUR sort_order, not the PDF's chapter number, because that is what `--only`
and every report downstream mean by a chapter.

DEDUPE REACHES ACROSS SOURCES BECAUSE THE DATABASE CANNOT. `uq_lqe_extraction_hash`
is scoped to one extraction, so it cannot see that a question already exists
under a different one, and a repeat loads twice with nothing raised. The four
chapters here are empty, but Class 9 Mathematics holds 973 questions in its
other ten, and this book is written against the old syllabus: its quadrilateral
questions can perfectly well have been printed in a bank already loaded under a
chapter that covers the same ground. So every item is checked against the whole
subject, two ways -- by `verbatim_sha256`, computed with the writer's own
hash so a byte-identical question is caught, and by a folded stem, which
catches the same question re-typeset.

HELD BY HAND. Each of these was settled by reading the page, and a rule general
enough to catch them takes sound questions with them:

  ch11 exercise q4   the printed key says the volume is "unchanged" when a
                     cone's radius is halved and its height doubled. It is
                     halved -- (1/3)π(r/2)²(2h) = (1/3)πr²h/2 -- and this
                     book's own worked assertion-reason item 1, four pages
                     earlier, says halved. The key is wrong, so the item
                     cannot be loaded from it.
  ch8 very short 7   "The diagonal AC and BD of a parallelogram ABCD intersect
                     at point O. Find ∠DBC." The working uses 75° and 34°,
                     which are printed in the figure and nowhere in the text.
                     Nothing in the stem says there is a figure, so the
                     figure gate does not see it.
  ch12 A-R 3         the reason is the median formula, and the layout printed
                     (n+1)/2 as "the[n+1 2]th observation".

`concept` is left empty. `apply_read_concepts` RAISES on a name that is not in
the chapter's own list and aborts that whole chapter, and these four chapters
have no concepts yet at all, so a guess would abort every one of them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata as ud
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

from scripts.parse_kvs_ssm_c9_maths import CHAPTERS, SOURCE_URL  # noqa: E402

DRAFT = (Path(__file__).resolve().parent / "kvs_ssm_c9_items" / "drafts"
         / "c9_maths_kvs_ssm.json")
OUT = Path(__file__).resolve().parent / "kvs_ssm_c9_items"
STANDARD_ID, SUBJECT_ID = 42, 3976

# (pdf chapter, half, printed form, number) -> why
MISPRINTED = {
    (11, "exercise", "mcq", 4):
        "the printed key says 'unchanged'; halving a cone's radius and "
        "doubling its height halves the volume, and this book's own worked "
        "assertion-reason item 1 says halved",
    (8, "worked", "very_short", 7):
        "the working uses 75 degrees and 34 degrees, which are printed only "
        "in the figure; the stem gives no data at all",
    (12, "worked", "assertion_reason", 3):
        "the reason's formula (n+1)/2 is printed as 'the[n+1 2]th observation'",
}


def fold(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", ud.normalize("NFKC", value or "").lower())


def flat(value: str) -> str:
    return " ".join((value or "").split())


def writer_hash(item: dict) -> str:
    """The hash `supplied_items` will store, computed the same way it does.

    Reproduced rather than imported because it runs there over the SHAPED item,
    after labels are upper-cased and text is whitespace-folded; feeding it the
    draft shape would give a different digest for the same question and the
    comparison against what is already stored would never match anything.
    """
    payload = "|".join([
        flat(item.get("stem") or ""),
        flat(item.get("assertion") or ""),
        flat(item.get("reason") or ""),
        "|".join(f"{str(o['label']).upper()}:{flat(o['text'])}"
                 for o in item.get("options") or []),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    draft = json.loads(DRAFT.read_text(encoding="utf-8"))

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT e.chapter_number, e.id, e.chapter_id, c.chapter_name "
            "  FROM document_extractions e "
            "  JOIN chapter_master c ON c.id = e.chapter_id "
            " WHERE e.pdf_url = :u ORDER BY e.chapter_number"),
            {"u": SOURCE_URL}).fetchall()
        meta = {int(r[0]): {"eid": int(r[1]), "cid": int(r[2]), "name": r[3]}
                for r in rows}
        if not meta:
            raise SystemExit("No extraction rows -- run "
                             "setup_kvs_ssm_c9_extractions --apply")

        # Everything Class 9 Mathematics already holds, from any source but
        # this document's own rows. Excluding our own matters on a re-shape:
        # without it a second run finds the first load and holds every item.
        mine = tuple(m["eid"] for m in meta.values())
        existing = db.execute(text(
            "SELECT q.question_title, x.verbatim_sha256 "
            "  FROM lms_question_master q "
            "  LEFT JOIN lms_question_extraction x ON x.question_id = q.id "
            " WHERE q.standard_id = :s AND q.subject_id = :j "
            "   AND q.question_title IS NOT NULL "
            "   AND (x.extraction_id IS NULL OR x.extraction_id NOT IN :mine)"),
            {"s": STANDARD_ID, "j": SUBJECT_ID, "mine": mine}).fetchall()
        seen_stems = {fold(r[0])[:120] for r in existing if r[0]}
        seen_hashes = {r[1] for r in existing if r[1]}
        print(f"Class 9 Mathematics already holds {len(existing)} question(s) "
              f"outside this document\n")
    finally:
        db.close()

    by_sort = {ch: c["our_sort"] for ch, c in CHAPTERS.items()}
    kept: dict[int, list] = {}
    held: list[tuple[str, str, dict]] = []
    dup_bank, dup_here = [], []
    here: set[str] = set()

    for it in draft["items"]:
        pdf_ch = int(it["chapter_number"])
        sort = by_sort.get(pdf_ch)
        where = (f"pdf ch{pdf_ch} {it['half']} {it['printed_form']} "
                 f"q{it['number']} p{it['page']}")
        if sort is None or sort not in meta:
            held.append((where, "no extraction row", it))
            continue
        key = (pdf_ch, it["half"], it["printed_form"], int(it["number"]))
        if key in MISPRINTED:
            held.append((where, MISPRINTED[key], it))
            continue

        digest = writer_hash(it)
        stem_key = fold(it["stem"])[:120]
        if digest in seen_hashes:
            dup_bank.append((where, "verbatim_sha256", it))
            continue
        if stem_key in seen_stems:
            dup_bank.append((where, "normalised stem", it))
            continue
        # The stem alone is not identity: a book can ask the same question over
        # two different option sets. Key on the stem plus its options.
        local = fold(it["stem"] + "".join(o["text"] for o in it["options"]))[:160]
        if local in here:
            dup_here.append((where, "printed twice in this book", it))
            continue
        here.add(local)
        kept.setdefault(sort, []).append(it)

    print(f"  {'ch':>3} {'eid':>5} {'cid':>7} {'our chapter':<44} "
          + " ".join(f"{f[:4]:>4}" for f in
                     ("mcq", "a-r", "vsho", "shor", "long", "case")) + f" {'keep':>5}")
    print("  " + "-" * 104)
    total = 0
    for sort in sorted(meta):
        items = kept.get(sort, [])
        total += len(items)
        n = {f: sum(1 for i in items if i["form"] == f) for f in
             ("mcq", "assertion_reason", "very_short", "short", "long", "case_study")}
        print(f"  {sort:>3} {meta[sort]['eid']:>5} {meta[sort]['cid']:>7} "
              f"{str(meta[sort]['name'])[:44]:<44} "
              f"{n['mcq']:>4} {n['assertion_reason']:>4} {n['very_short']:>4} "
              f"{n['short']:>4} {n['long']:>4} {n['case_study']:>4} {len(items):>5}")
    print("  " + "-" * 104)
    print(f"  {'':>3} {'':>5} {'':>7} {'total':<44} "
          + " " * 29 + f"{total:>5}\n")

    print(f"  duplicates against the rest of Class 9 Mathematics: {len(dup_bank)}")
    for where, how, it in dup_bank[:12]:
        print(f"      [{how}] {where}: {flat(it['stem'])[:70]}")
    print(f"  printed twice in this book: {len(dup_here)}")
    for where, _, it in dup_here[:8]:
        print(f"      {where}: {flat(it['stem'])[:76]}")
    print(f"  held by hand: {len(held)}")
    for where, why, _ in held:
        print(f"      {where}: {why[:96]}")

    if a.write:
        OUT.mkdir(parents=True, exist_ok=True)
        for sort, items in sorted(kept.items()):
            for n, it in enumerate(items, 1):
                it["number"] = n
            (OUT / f"ch{sort:02d}.json").write_text(json.dumps(
                {"chapter": sort, "chapter_id": meta[sort]["cid"],
                 "extraction_id": meta[sort]["eid"], "source_url": SOURCE_URL,
                 "items": items}, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {len(kept)} file(s) to {OUT}")
    else:
        print("\nreport only -- re-run with --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
