"""Cut the ZIET draft into the per-chapter files `load_nodia_items` expects.

    python -m scripts.shape_ziet_for_load
    python -m scripts.shape_ziet_for_load --write

The loader reads `{"chapter": N, "extraction_id": E, "items": [...]}` and
addresses rows by `extraction_id`, so the draft's flat list is cut per chapter
and paired with the row `setup_ziet_extractions` made for this document.

WHAT IS HELD BACK, and why each would otherwise load broken rather than fail:

  no key          an mcq with no `correct_option` fails `V-04`, and a failed
                  validator still INSERTS, with `status = 0`. Two items: the
                  book prints no solution for chapter 4 question 14 (it
                  reprints the question instead), and chapter 8 question 4
                  contradicts itself -- it opens "C) 10th", works out n = 9,
                  then concludes "the correct option is B) 9th".
  needs a figure  chapter 5 question 17 reads "In the given figure, if O is
                  the centre of the circle" and this bank ships no images.
                  Setting `figure_required` would fail `V-07`; leaving it
                  clear publishes a question nobody can answer.
  key disagrees   the answer does not quote the option it names, which means
                  the printed solution belongs to another question. Chapter 1
                  question 16 asks about a rug inset in a floor plan and its
                  solution explains why a square is non-negative.
  already loaded  chapters 1-8 already hold 278 questions from the KVS SSM
                  set. `uq_lqe_extraction_hash` is scoped to ONE extraction,
                  so it cannot see across sources and a repeat would load
                  twice. Matching is on the normalised stem.

Comparison is NFKC-folded before non-alphanumerics are stripped, because the
two halves of this book disagree on notation: the option prints "4p2 -4p+ 1"
and the solution prints "4p^2-4p+1". Compared raw, thirteen correct items look
like mismatches.

`concept` is left empty on purpose. `apply_read_concepts` RAISES on a name
that is not in the chapter's own list and aborts that whole chapter, so a
guessed concept costs more than an absent one. Concepts are assigned by
reading, once the items are in.
"""
from __future__ import annotations

import argparse
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

from scripts.parse_ziet_maths import SOURCE_URL  # noqa: E402

DRAFT = Path(__file__).resolve().parent / "ziet_items" / "drafts" / "c9_maths_ziet.json"
OUT = Path(__file__).resolve().parent / "ziet_items"
STANDARD_ID, SUBJECT_ID = 42, 3976

_FIGURE = re.compile(r"(?i)\b(in the (given )?figure|figure below|shown in fig|"
                     r"see fig|fig\.|diagram below|in the diagram|"
                     r"adjoining figure|given graph)\b")


def norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", ud.normalize("NFKC", t or "").lower())


# Items read against the source and found to be misprinted IN THE BOOK. This
# is a list rather than a rule because each was settled by reading the page,
# and a rule general enough to catch them drops correct questions with them:
# chapter 4 states its working instead of restating the option ("(x+3)^2 =
# x^2+6x+9, so the missing term is 6x" for "The term 6x is missing"), and
# fifteen of its eighteen look exactly as wrong to any automatic test.
MISPRINTED = {
    (1, 16): "solution explains why a square is non-negative; the question "
             "asks the area of a rug inset in a 12x10 floor plan, which is "
             "8x6 = 48, printed as option A, while the key says B (60)",
    (5, 13): "solution reads '(A) 2:3'; the question asks an angle and its "
             "four options are 35, 70, 140 and 210 degrees",
    (5, 15): "the question half prints question 14 again here; the solution "
             "'(B) 60' answers a question the text layer does not hold",
    (5, 16): "the question half prints question 14 again here; the solution "
             "'(A) the centre' answers a question the text layer does not hold",
}


def _opt(it: dict, label: str) -> str:
    return next((o["text"] for o in it["options"] if o["label"] == label), "")


def _quotes_its_option(it: dict) -> bool:
    """Does the printed solution repeat the option it names?

    It usually does -- "Correct Option: B) Rectangle; Quadrant III" -- and when
    it does, question and solution are certainly the same question. When it
    does not, they still usually are: the solution paraphrases ("Both the
    students" for "Both students") or re-sets the algebra. So this is a
    REVIEW signal, never a reason to drop on its own.
    """
    n = norm(_opt(it, it["correct_option"]))
    return len(n) < 6 or n[:40] in norm(it["answer"])


def _key_check(it: dict, siblings: list[dict]) -> str:
    """Hold an item only where the solution is provably not this question's.

    Two things prove it, and neither needs a similarity threshold:

      * the solution quotes a DIFFERENT option of this same question, so the
        page contradicts itself;
      * the solution quotes the correct option of ANOTHER question in this
        chapter, so it was printed against the wrong number.

    Chapter 1 question 16 asks about a rug inset in a floor plan; its solution
    reads "Because squaring any real number yields a non-negative result",
    which is another question's option. Its key cannot be trusted either, so
    the item is held rather than loaded with a guess.
    """
    if _quotes_its_option(it):
        return ""
    ans = norm(it["answer"])
    for o in it["options"]:
        if o["label"] != it["correct_option"] and len(norm(o["text"])) >= 10 \
                and norm(o["text"])[:40] in ans:
            return "answer names one option and quotes another"
    for other in siblings:
        if other is it or other["form"] != "mcq" or not other.get("correct_option"):
            continue
        n = norm(_opt(other, other["correct_option"]))
        if len(n) >= 12 and n[:40] in ans:
            return "solution belongs to another question"
    return ""


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
            raise SystemExit("No extraction rows -- run setup_ziet_extractions --apply")

        # Every stem already in the bank for these chapters from ANOTHER
        # source. This document's own rows are excluded deliberately: without
        # that, re-shaping after a parser fix finds its own previous load and
        # holds all 295 items as duplicates, leaving a chapter file holding
        # only the items the fix happened to change.
        mine = tuple(m["eid"] for m in meta.values())
        existing: dict[int, set[str]] = {}
        for cid in {m["cid"] for m in meta.values()}:
            stems = db.execute(text(
                "SELECT q.question_title FROM lms_question_master q "
                "  LEFT JOIN lms_question_extraction x ON x.question_id = q.id "
                " WHERE q.chapter_id = :c AND q.question_title IS NOT NULL "
                "   AND (x.extraction_id IS NULL OR x.extraction_id NOT IN :mine)"),
                {"c": cid, "mine": mine}).fetchall()
            existing[cid] = {norm(s[0])[:120] for s in stems if s[0]}
    finally:
        db.close()

    by_chapter: dict[int, list] = {}
    for it in draft["items"]:
        by_chapter.setdefault(int(it["chapter_number"]), []).append(it)

    kept: dict[int, list] = {}
    held: list[tuple[str, dict]] = []
    review: list[dict] = []
    seen_here: set[str] = set()
    for it in draft["items"]:
        ch = int(it["chapter_number"])
        m = meta.get(ch)
        if not m:
            held.append(("no extraction row", it)); continue
        if (ch, int(it["number"])) in MISPRINTED:
            held.append(("misprinted in the book", it)); continue
        choice = it["form"] in ("mcq", "assertion_reason")
        if choice and not it.get("correct_option"):
            held.append(("no key", it)); continue
        if _FIGURE.search(it["stem"]):
            held.append(("needs a figure", it)); continue
        if not (it.get("answer") or "").strip():
            held.append(("no answer", it)); continue
        if len(it["stem"]) < 20:
            held.append(("stem too short", it)); continue
        if it["form"] == "mcq" and it.get("correct_option"):
            verdict = _key_check(it, by_chapter[ch])
            if verdict:
                held.append((verdict, it)); continue
            if not _quotes_its_option(it):
                review.append(it)
        # The stem alone is NOT the identity of a question here. Chapter 7
        # asks "A die is rolled once. Which statement is correct?" twice, and
        # "A bag has 6 white and 4 black balls. Which statement is correct?"
        # twice, each time over a different set of four options. Keyed on the
        # stem, half of chapter 7 disappears as a duplicate.
        key = norm(it["stem"] + "".join(o["text"] for o in it["options"]))[:160]
        if norm(it["stem"])[:120] in existing.get(m["cid"], set()):
            held.append(("already in the bank", it)); continue
        if key in seen_here:
            held.append(("printed twice in this book", it)); continue
        seen_here.add(key)
        kept.setdefault(ch, []).append(it)

    print(f"{draft['book']}  publisher={draft.get('publisher', '?')}\n")
    print(f"  {'ch':>3} {'eid':>5} {'chapter':<38} {'mcq':>4} {'a-r':>4} "
          f"{'vs':>4} {'s':>4} {'l':>4} {'cs':>4} {'keep':>5}")
    print("  " + "-" * 86)
    tot = 0
    for ch in sorted(meta):
        ks = kept.get(ch, [])
        tot += len(ks)
        n = {f: sum(1 for i in ks if i["form"] == f) for f in
             ("mcq", "assertion_reason", "very_short", "short", "long", "case_study")}
        print(f"  {ch:>3} {meta[ch]['eid']:>5} {str(meta[ch]['name'])[:38]:<38} "
              f"{n['mcq']:>4} {n['assertion_reason']:>4} {n['very_short']:>4} "
              f"{n['short']:>4} {n['long']:>4} {n['case_study']:>4} {len(ks):>5}")
    print("  " + "-" * 86)
    print(f"  {'':>3} {'':>5} {'total':<38} {'':>4} {'':>4} {'':>4} {'':>4} "
          f"{'':>4} {'':>4} {tot:>5}\n")

    print(f"  held back ({len(held)}):")
    for why in dict.fromkeys(w for w, _ in held):
        group = [i for w, i in held if w == why]
        print(f"    {len(group):>3}  {why}")
        for i in group[:4]:
            print(f"         ch{i['chapter_number']} q{i['number']}: "
                  f"{' '.join(i['stem'].split())[:82]}")

    print(f"\n  loaded, but READ THESE ({len(review)}) -- the solution does not "
          f"repeat the option it names:")
    for i in review:
        print(f"      ch{i['chapter_number']} q{i['number']:>3} key={i['correct_option']}"
              f" | {_opt(i, i['correct_option'])[:46]}"
              f" | {' '.join(i['answer'].split())[:52]}")

    if a.write:
        OUT.mkdir(parents=True, exist_ok=True)
        for ch, items in sorted(kept.items()):
            for n, it in enumerate(items, 1):
                it["number"] = n
            (OUT / f"ch{ch:02d}.json").write_text(json.dumps(
                {"chapter": ch, "chapter_id": meta[ch]["cid"],
                 "extraction_id": meta[ch]["eid"], "source_url": SOURCE_URL,
                 "items": items}, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {len(kept)} file(s) to {OUT}")
    else:
        print("\nreport only -- re-run with --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
