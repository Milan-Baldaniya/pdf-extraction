"""Cut the Class 7 Social Science draft into per-chapter files for the loader.

    python -m scripts.shape_c7social_for_load
    python -m scripts.shape_c7social_for_load --write

Files are named `ch01.json` .. `ch20.json` in one flat sequence, NOT by the
chapter number printed in the book. The book restarts numbering in Part 2, so
two chapters claim "1" and `load_nodia_items --only` could not tell them
apart; `extraction_id` is what actually addresses the row, and the file's own
`chapter` field carries the printed number for display.

Held back rather than loaded, because each would otherwise INSERT with
`status = 0` and sit in the bank looking loaded:

  V-09  an mcq that did not parse to exactly four options
  V-04  an mcq with no `correct_option`
  V-02  a `correct_option` naming a label that is not among the options
  V-11  an option over 250 characters, `answer_master.answer`'s limit
  W-01  an empty answer -- a warning only, so these would load unanswerable

A one-word answer is NOT held: "Which desert is also known as the Great Indian
Desert? -- Thar Desert." is complete. An earlier five-word floor discarded 274
such items and reported them as though the book had not answered them.

`concept` is left empty. `apply_read_concepts` RAISES on a name that is not in
the chapter's own list and aborts that whole chapter, so a guessed concept
costs more than an absent one.
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

from scripts.parse_c7_social import CHAPTERS, SOURCE  # noqa: E402

DRAFT = Path(__file__).resolve().parent / "c7social_items" / "drafts" / "c7_social.json"
OUT = Path(__file__).resolve().parent / "c7social_items"
SUBJECT_OF_PART = {1: "Social Sciences", 2: "Social Sciences-2"}


def norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", ud.normalize("NFKC", t or "").lower())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    draft = json.loads(DRAFT.read_text(encoding="utf-8"))
    sha = hashlib.sha256(SOURCE.read_bytes()).hexdigest()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        meta: dict[tuple[int, int], dict] = {}
        for r in db.execute(text(
            "SELECT e.subject_name, e.chapter_number, e.id, e.chapter_id, c.chapter_name "
            "  FROM document_extractions e JOIN chapter_master c ON c.id = e.chapter_id "
            " WHERE e.content_sha256 = :h"), {"h": sha}).fetchall():
            part = 1 if r[0] == SUBJECT_OF_PART[1] else 2
            meta[(part, int(r[1]))] = {"eid": int(r[2]), "cid": int(r[3]), "name": r[4]}
        if not meta:
            raise SystemExit("No extraction rows -- run setup_c7social_extractions --apply")
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

    kept: dict[tuple[int, int], list] = {}
    held: list[tuple[str, dict]] = []
    seen: set = set()
    for it in draft["items"]:
        key = (int(it["part"]), int(it["chapter_number"]))
        m = meta.get(key)
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
        if not (it.get("answer") or "").strip():
            held.append(("W-01 no answer", it)); continue
        if len(it["stem"]) < 20:
            held.append(("stem under 20 chars", it)); continue
        k = norm(it["stem"])[:120]
        if k in existing.get(m["cid"], set()):
            held.append(("already in the bank from another source", it)); continue
        dk = (key, norm(it["stem"] + "".join(o["text"] for o in it["options"]))[:160])
        if dk in seen:
            held.append(("printed twice in this book", it)); continue
        seen.add(dk)
        kept.setdefault(key, []).append(it)

    forms = ("mcq", "very_short", "short", "long", "case_study")
    print(f"c7_social  publisher={draft.get('publisher')}\n")
    print(f"  {'pt':>2} {'ch':>3} {'eid':>5} {'chapter':<44} "
          + " ".join(f"{f[:10]:>10}" for f in forms) + f" {'keep':>6}")
    print("  " + "-" * 122)
    tot = 0
    for part, so, name, lo, hi in CHAPTERS:
        ks = kept.get((part, so), [])
        tot += len(ks)
        m = meta.get((part, so), {})
        print(f"  {part:>2} {so:>3} {m.get('eid', '-'):>5} {str(m.get('name', name))[:44]:<44} "
              + " ".join(f"{sum(1 for i in ks if i['form']==f):>10}" for f in forms)
              + f" {len(ks):>6}")
    print("  " + "-" * 122)
    print(f"  {'':>2} {'':>3} {'':>5} {'total':<44} "
          + " ".join(f"{sum(1 for v in kept.values() for i in v if i['form']==f):>10}" for f in forms)
          + f" {tot:>6}\n")
    print(f"  held back ({len(held)}):")
    for why in dict.fromkeys(w for w, _ in held):
        g = [i for w, i in held if w == why]
        print(f"    {len(g):>4}  {why}")
        for i in g[:2]:
            print(f"          pt{i['part']} ch{i['chapter_number']}: "
                  f"{' '.join(i['stem'].split())[:74]}")

    if a.write:
        OUT.mkdir(parents=True, exist_ok=True)
        seq = 0
        for part, so, name, lo, hi in CHAPTERS:
            key = (part, so)
            if key not in meta:
                continue
            seq += 1
            items = kept.get(key, [])
            for n, it in enumerate(items, 1):
                it["number"] = n
            (OUT / f"ch{seq:02d}.json").write_text(json.dumps(
                {"chapter": seq, "printed_chapter": so, "part": part,
                 "chapter_id": meta[key]["cid"], "extraction_id": meta[key]["eid"],
                 "items": items}, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {seq} file(s) to {OUT}")
    else:
        print("\nreport only -- re-run with --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
