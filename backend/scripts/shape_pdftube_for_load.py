"""Split a pdf.tube draft into the per-chapter files `load_nodia_items` expects.

    python -m scripts.shape_pdftube_for_load --book c7_english
    python -m scripts.shape_pdftube_for_load --book c7_english --write

The loader reads `{"chapter": N, "extraction_id": E, "items": [...]}` and
addresses rows by `extraction_id`, so the draft's flat item list has to be cut
per chapter and paired with that chapter's extraction row.

PUBLISHER IS NODIA, not pdf.tube and not CBSE. The book's own imprint page
reads "Published by: NODIA, An Imprint of NODIA EDITIONS LLP", edition March
2026; pdf.tube is only where it is distributed. Attribution drives the
publisher stamped on every question, and `load_nodia_items` warns that getting
it wrong is a licensing error rather than a cosmetic one. NODIA is already
registered as publisher 6 -- the same publisher whose Class 10 Science book
took that subject past 500 per chapter, which is also why
`c9_Science_QB_2026.pdf` is byte-identical to the book already in the bank.

THREE CLASSES OF ITEM ARE DROPPED HERE rather than left for a validator to
flag with `status = 0`:

  * an empty answer. `W-01` is only a warning, so these would load and sit in
    the bank unanswerable and invisible.
  * `correct_option` naming a label that is not among the options, which `V-02`
    fails. Two items, both from an option list the text layer split oddly.
  * a stem under 20 characters, which is a fragment rather than a question.

`concept` is left empty deliberately. `apply_read_concepts` RAISES on a name
that is not in the chapter's own list and aborts the whole chapter, so a
guessed concept costs more than an absent one. Concepts are assigned by
reading, after the items are in.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

DRAFTS = Path(__file__).resolve().parent / "pdftube_items" / "drafts"
OUT = Path(__file__).resolve().parent / "pdftube_items"

BOOKS = {"c7_english": {"standard": 40, "subject": 3978}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--book", choices=sorted(BOOKS), required=True)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    cfg = BOOKS[a.book]

    draft = json.loads((DRAFTS / f"{a.book}.json").read_text(encoding="utf-8"))

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        rows = db.execute(
            text("SELECT c.id, c.sort_order, c.chapter_name, e.id "
                 "  FROM chapter_master c "
                 "  LEFT JOIN document_extractions e ON e.chapter_id = c.id "
                 " WHERE c.standard_id = :s AND c.subject_id = :j "
                 " ORDER BY c.sort_order"),
            {"s": cfg["standard"], "j": cfg["subject"]},
        ).fetchall()
    finally:
        db.close()
    meta = {int(r[0]): {"sort": int(r[1]), "name": r[2],
                        "extraction_id": int(r[3]) if r[3] else None} for r in rows}

    kept: dict[int, list] = {}
    dropped = {"no answer": 0, "bad correct_option": 0, "stem too short": 0,
               "no extraction row": 0}
    for it in draft["items"]:
        cid = it["chapter_id"]
        if not meta.get(cid, {}).get("extraction_id"):
            dropped["no extraction row"] += 1
            continue
        if not (it.get("answer") or "").strip() or len(it["answer"].strip()) < 3:
            dropped["no answer"] += 1
            continue
        labels = [o["label"] for o in it.get("options") or []]
        if it.get("correct_option") and it["correct_option"] not in labels:
            dropped["bad correct_option"] += 1
            continue
        if len(it["stem"]) < 20:
            dropped["stem too short"] += 1
            continue
        kept.setdefault(cid, []).append(it)

    print(f"{a.book}  publisher=nodia\n")
    print(f"  {'chapter':<40} {'eid':>5} {'items':>7}")
    print("  " + "-" * 56)
    total = 0
    for cid, m in sorted(meta.items(), key=lambda x: x[1]["sort"]):
        n = len(kept.get(cid, []))
        total += n
        print(f"  {m['name'][:40]:<40} {m['extraction_id'] or '-':>5} {n:>7}")
    print("  " + "-" * 56)
    print(f"  {'total':<40} {'':>5} {total:>7}\n")
    print("  dropped:")
    for why, n in dropped.items():
        if n:
            print(f"      {n:>4}  {why}")

    if a.write:
        OUT.mkdir(parents=True, exist_ok=True)
        for cid, items in kept.items():
            m = meta[cid]
            for n, it in enumerate(items, 1):
                it["number"] = n
            path = OUT / f"ch{m['sort']:02d}.json"
            path.write_text(json.dumps(
                {"chapter": m["sort"], "chapter_id": cid,
                 "extraction_id": m["extraction_id"], "items": items},
                indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {len(kept)} file(s) to {OUT}")
    else:
        print("\nreport only - re-run with --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
