"""Cut the Kaveri draft into the per-chapter files `load_nodia_items` expects.

    python -m scripts.shape_kaveri_for_load
    python -m scripts.shape_kaveri_for_load --write

Held back rather than loaded, because each would otherwise INSERT with
`status = 0` and sit in the bank looking loaded:

  V-09   an mcq that did not parse to exactly four options
  V-04   an mcq with no `correct_option`
  V-02   a `correct_option` naming a label that is not among the options
  V-11   an option over 250 characters, which is `answer_master.answer`'s limit
  W-01   an empty answer -- only a warning, so these would load unanswerable

An item whose stem matches one already in the chapter FROM ANOTHER SOURCE is
also held: `uq_lqe_extraction_hash` is scoped to one extraction and cannot see
across them. This book's own rows are excluded from that comparison, so that
re-shaping after a parser fix does not find its own previous load and hold
everything as a duplicate.

`concept` is left empty deliberately. `apply_read_concepts` RAISES on a name
that is not in the chapter's own list and aborts the whole chapter, so a
guessed concept costs more than an absent one.
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

from scripts.parse_kaveri_english import SOURCE  # noqa: E402

DRAFTS = Path(__file__).resolve().parent / "kaveri_items" / "drafts"
OUT = Path(__file__).resolve().parent / "kaveri_items"


# "1. True, 2. False, 3. True, 4. True, 5. True, 6. False" -- one key for a
# whole exercise, never the answer to a single statement.
_COMBINED_KEY = re.compile(r"(?i)\b\d\s*\.\s*(?:True|False)\b.*?"
                          r"\b\d\s*\.\s*(?:True|False)\b")


def norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", ud.normalize("NFKC", t or "").lower())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--section", choices=("prose", "poetry"), default="prose")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    draft = json.loads((DRAFTS / f"c9_english_{a.section}.json").read_text(encoding="utf-8"))
    sha = hashlib.sha256(SOURCE.read_bytes()).hexdigest()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT e.chapter_number, e.id, e.chapter_id, c.chapter_name "
            "  FROM document_extractions e JOIN chapter_master c ON c.id = e.chapter_id "
            " WHERE e.content_sha256 = :h ORDER BY e.chapter_number"),
            {"h": sha}).fetchall()
        meta = {int(r[0]): {"eid": int(r[1]), "cid": int(r[2]), "name": r[3]} for r in rows}
        if not meta:
            raise SystemExit("No extraction rows -- run setup_kaveri_extractions --apply")
        mine = tuple(m["eid"] for m in meta.values())
        existing: dict[int, set[str]] = {}
        for cid in {m["cid"] for m in meta.values()}:
            existing[cid] = {norm(s[0])[:120] for s in db.execute(text(
                "SELECT q.question_title FROM lms_question_master q "
                "  LEFT JOIN lms_question_extraction x ON x.question_id = q.id "
                " WHERE q.chapter_id = :c AND q.question_title IS NOT NULL "
                "   AND (x.extraction_id IS NULL OR x.extraction_id NOT IN :mine)"),
                {"c": cid, "mine": mine}).fetchall() if s[0]}
    finally:
        db.close()

    kept: dict[int, list] = {}
    held: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for it in draft["items"]:
        ch = int(it["chapter_number"])
        m = meta.get(ch)
        if not m:
            held.append(("no extraction row", it)); continue
        labels = {o["label"] for o in it.get("options") or []}
        if it["form"] == "mcq":
            if len(it.get("options") or []) != 4:
                held.append(("V-09 mcq without exactly 4 options", it)); continue
            if not it.get("correct_option"):
                held.append(("V-04 mcq with no key", it)); continue
            if it["correct_option"] not in labels:
                held.append(("V-02 key names no option", it)); continue
            if any(len(o["text"]) > 250 for o in it["options"]):
                held.append(("V-11 option over 250 chars", it)); continue
        # A TRUE/FALSE EXERCISE IS ONE ANSWER FOR SIX STATEMENTS. The book
        # prints six numbered statements and then a single combined key,
        # "1. True, 2. False, 3. True, 4. True, 5. True, 6. False". Paired the
        # usual way, each statement gets the whole key as its answer, so the
        # item is unanswerable and its stem is one sixth of the question. Two
        # such items exist and both are held.
        if _COMBINED_KEY.search(it.get("answer") or ""):
            held.append(("true/false exercise sharing one combined key", it)); continue
        if not (it.get("answer") or "").strip():
            held.append(("W-01 no answer", it)); continue
        if len(it["stem"]) < 25:
            held.append(("stem under 25 chars", it)); continue
        key = norm(it["stem"])[:120]
        if key in existing.get(m["cid"], set()):
            held.append(("already in the bank from another source", it)); continue
        if (ch, key) in seen:
            held.append(("printed twice in this book", it)); continue
        seen.add((ch, key))
        kept.setdefault(ch, []).append(it)

    forms = ("mcq", "short", "long", "true_false")
    print(f"c9_english_{a.section}  publisher={draft.get('publisher')}\n")
    print(f"  {'ch':>3} {'eid':>5} {'chapter':<40} "
          + " ".join(f"{f:>10}" for f in forms) + f" {'keep':>6}")
    print("  " + "-" * 104)
    tot = 0
    for ch in sorted(meta):
        ks = kept.get(ch, [])
        tot += len(ks)
        print(f"  {ch:>3} {meta[ch]['eid']:>5} {str(meta[ch]['name'])[:40]:<40} "
              + " ".join(f"{sum(1 for i in ks if i['form']==f):>10}" for f in forms)
              + f" {len(ks):>6}")
    print("  " + "-" * 104)
    print(f"  {'':>3} {'':>5} {'total':<40} "
          + " ".join(f"{sum(1 for v in kept.values() for i in v if i['form']==f):>10}" for f in forms)
          + f" {tot:>6}\n")
    print(f"  held back ({len(held)}):")
    for why in dict.fromkeys(w for w, _ in held):
        g = [i for w, i in held if w == why]
        print(f"    {len(g):>4}  {why}")
        for i in g[:2]:
            print(f"          ch{i['chapter_number']}: {' '.join(i['stem'].split())[:78]}")

    if a.write:
        OUT.mkdir(parents=True, exist_ok=True)
        for ch, items in sorted(kept.items()):
            for n, it in enumerate(items, 1):
                it["number"] = n
            (OUT / f"ch{ch:02d}.json").write_text(json.dumps(
                {"chapter": ch, "chapter_id": meta[ch]["cid"],
                 "extraction_id": meta[ch]["eid"], "items": items},
                indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {len(kept)} file(s) to {OUT}")
    else:
        print("\nreport only -- re-run with --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
