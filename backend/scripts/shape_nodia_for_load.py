"""Cut a `parse_nodia_qb` draft into the per-chapter files the loader expects.

    python -m scripts.shape_nodia_for_load --book c6_social
    python -m scripts.shape_nodia_for_load --book c6_social --write

Files are numbered `ch01.json` upward in one flat sequence, NOT by the chapter
number printed in the book. A two-part book restarts its numbering, so two
chapters would claim "1" and `load_nodia_items --only` could not tell them
apart. `extraction_id` is what actually addresses the row.

Held back rather than loaded, because each would otherwise INSERT with
`status = 0` and sit in the bank looking loaded:

  V-09  an mcq that did not parse to exactly four options
  V-04  an mcq with no `correct_option`
  V-02  a `correct_option` naming a label that is not among the options
  V-11  an option over 250 characters, `answer_master.answer`'s limit
  W-01  an empty answer -- a warning only, so these would load unanswerable

A one-word answer is NOT held: "Which desert is also known as the Great Indian
Desert? -- Thar Desert." is complete.

`concept` is left empty. `apply_read_concepts` RAISES on a name that is not in
the chapter's own list and aborts that whole chapter.
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
from app.services.supplied_items import shape as _shape  # noqa: E402

from scripts.parse_nodia_qb import BOOKS, MIRROR  # noqa: E402

DRAFTS = Path(__file__).resolve().parent / "nodia_qb_items" / "drafts"
OUT_ROOT = Path(__file__).resolve().parent / "nodia_qb_items"


def _digest(item: dict) -> str:
    """The verbatim_sha256 this item WILL be stored under.

    Produced by running the writer's own `shape()`, so that a change to how
    the hash is built cannot make this check quietly stop matching.
    """
    return _shape([item], attribution="x", licence=None)[0]["verbatim_sha256"]


def norm(t: str) -> str:
    """Fold for comparison, KEEPING non-Latin scripts.

    An ASCII-only class erases Devanagari entirely, so every Hindi stem folds
    to the empty string and the dedupe sees one question repeated: Class 9
    Hindi held back 919 of 1,007 items as "printed twice" and loaded 88.
    """
    return re.sub(r"[^0-9a-zऀ-ॿঀ-৿਀-੿]", "",
                  ud.normalize("NFKC", t or "").lower())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--book", choices=sorted(BOOKS), required=True)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    cfg = BOOKS[a.book]
    out_dir = OUT_ROOT / a.book

    draft = json.loads((DRAFTS / f"{a.book}.json").read_text(encoding="utf-8"))
    sha = hashlib.sha256((MIRROR / cfg["file"]).read_bytes()).hexdigest()
    part_of = {v: k for k, v in cfg["subject_of_part"].items()}

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        meta: dict[tuple[int, int], dict] = {}
        foreign = 0
        for r in db.execute(text(
            "SELECT e.subject_name, e.chapter_number, e.id, e.chapter_id, c.chapter_name "
            "  FROM document_extractions e JOIN chapter_master c ON c.id = e.chapter_id "
            " WHERE e.content_sha256 = :h"), {"h": sha}).fetchall():
            # ONE FILE CAN CARRY TWO SUBJECTS, and the rows are found by the
            # file's hash. c10_English_QB_2026.pdf holds both First Flight
            # (subject "English", already loaded) and the Footprints Without
            # Feet supplementary reader ("English-2"), and each numbers its
            # chapters 1 to 9. Defaulted to part 1, the nine English rows
            # land on the same nine keys as the nine English-2 rows and
            # whichever the database returns last wins -- so a run of
            # c10_english2 would file the supplementary reader's questions
            # against First Flight's chapters, in a subject this book has no
            # business writing to. A row for a subject this book does not
            # claim is not ours.
            if r[0] not in part_of:
                foreign += 1
                continue
            meta[(part_of[r[0]], int(r[1]))] = {
                "eid": int(r[2]), "cid": int(r[3]), "name": r[4]}
        if foreign:
            print(f"  note: {foreign} extraction row(s) for this file belong to "
                  f"another subject and were left alone\n")
        if not meta:
            raise SystemExit("No extraction rows -- run setup_nodia_extractions --apply")
        mine = tuple(m["eid"] for m in meta.values())
        existing: dict[int, set[str]] = {}
        # THE UNIQUE INDEX IS SCOPED TO ONE EXTRACTION. It is
        # (extraction_id, verbatim_sha256, sub_institute_id), so it rejects
        # the same question twice within a load and cannot see the same
        # question arriving from a different source. On a top-up -- where
        # some of the book's chapters are already stocked from elsewhere --
        # that is the only index the load has, and it will not fire. So the
        # hashes already filed against each chapter are read here and
        # matched by hand, alongside the normalised-stem check that catches
        # the same question reproduced with different punctuation.
        digests: dict[int, set[str]] = {}
        for cid in {m["cid"] for m in meta.values()}:
            existing[cid] = {norm(s[0])[:120] for s in db.execute(text(
                "SELECT q.question_title FROM lms_question_master q "
                "  LEFT JOIN lms_question_extraction x ON x.question_id = q.id "
                " WHERE q.chapter_id = :c AND q.question_title IS NOT NULL "
                "   AND (x.extraction_id IS NULL OR x.extraction_id NOT IN :mine)"),
                {"c": cid, "mine": mine}).fetchall() if s[0]}
            digests[cid] = {s[0] for s in db.execute(text(
                "SELECT x.verbatim_sha256 FROM lms_question_extraction x "
                "  JOIN lms_question_master q ON q.id = x.question_id "
                " WHERE q.chapter_id = :c AND x.verbatim_sha256 IS NOT NULL "
                "   AND x.extraction_id NOT IN :mine"),
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
        # The floor catches a fragment left behind by a bad split. An mcq has
        # already passed the four checks above -- four options, a key, and the
        # key naming one of them -- and that is the evidence a fragment cannot
        # produce, so it is held to a shorter one. "What is science?" and
        # "What is a habitat?" are whole questions at 16 and 18 characters.
        if len(it["stem"]) < (12 if it["form"] == "mcq" else 20):
            held.append(("stem under 20 chars", it)); continue
        k = norm(it["stem"])[:120]
        if k in existing.get(m["cid"], set()):
            held.append(("already in the bank from another source", it)); continue
        # Computed by the writer's OWN shaper, not reimplemented here: the
        # digest has to agree with the one already stored or the check
        # silently passes everything.
        if _digest(it) in digests.get(m["cid"], set()):
            held.append(("same verbatim_sha256 already in the bank", it)); continue
        dk = (key, norm(it["stem"] + "".join(o["text"] for o in it["options"]))[:160])
        if dk in seen:
            held.append(("printed twice in this book", it)); continue
        seen.add(dk)
        kept.setdefault(key, []).append(it)

    forms = ("mcq", "very_short", "short", "long", "case_study")
    print(f"{a.book}  publisher={cfg['publisher']}\n")
    print(f"  {'pt':>2} {'ch':>3} {'eid':>5} {'chapter':<46} "
          + " ".join(f"{f[:10]:>10}" for f in forms) + f" {'keep':>6}")
    print("  " + "-" * 122)
    tot = 0
    for part, so, name, lo, hi in cfg["chapters"]:
        ks = kept.get((part, so), [])
        tot += len(ks)
        m = meta.get((part, so), {})
        print(f"  {part:>2} {so:>3} {m.get('eid', '-'):>5} {str(m.get('name', name))[:46]:<46} "
              + " ".join(f"{sum(1 for i in ks if i['form']==f):>10}" for f in forms)
              + f" {len(ks):>6}")
    print("  " + "-" * 122)
    print(f"  {'':>2} {'':>3} {'':>5} {'total':<46} "
          + " ".join(f"{sum(1 for v in kept.values() for i in v if i['form']==f):>10}" for f in forms)
          + f" {tot:>6}\n")
    print(f"  held back ({len(held)}):")
    for why in dict.fromkeys(w for w, _ in held):
        g = [i for w, i in held if w == why]
        print(f"    {len(g):>4}  {why}")
        for i in g[:2]:
            print(f"          pt{i['part']} ch{i['chapter_number']}: "
                  f"{' '.join(i['stem'].split())[:72]}")

    if a.write:
        out_dir.mkdir(parents=True, exist_ok=True)
        seq = 0
        for part, so, name, lo, hi in cfg["chapters"]:
            key = (part, so)
            if key not in meta:
                continue
            seq += 1
            items = kept.get(key, [])
            for n, it in enumerate(items, 1):
                it["number"] = n
            (out_dir / f"ch{seq:02d}.json").write_text(json.dumps(
                {"chapter": seq, "printed_chapter": so, "part": part,
                 "chapter_id": meta[key]["cid"], "extraction_id": meta[key]["eid"],
                 "items": items}, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {seq} file(s) to {out_dir}")
    else:
        print("\nreport only -- re-run with --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
