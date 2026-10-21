"""Cut the Class 6 English drafts into the per-extraction files the loader wants.

    python -m scripts.shape_c6_english_for_load
    python -m scripts.shape_c6_english_for_load --write

ONE FILE PER EXTRACTION ROW, NOT PER CHAPTER. `persist_supplied` writes the
whole item list of one extraction row, so the unit of a load file is
(chapter x source file). Chapters 4, 5 and 6 are covered by two different
studentbro MCQ files and therefore get two MCQ files each; merging them into
one would put both files' items under one of the two extraction rows and leave
the other looking like a source that produced nothing.

TWO PUBLISHERS MEANS TWO DIRECTORIES. The loader takes one --publisher for the
whole run, and the publisher is what gets stamped on every question as
attribution, so studentbro items and vedantu items cannot be in the same run.
They are written to c6_english_items/studentbro/ and .../vedantu/ and loaded
separately.

Held back rather than loaded, because each would otherwise INSERT with
`status = 0` and sit in the bank looking loaded:

  V-09  an mcq that did not parse to exactly four options
  V-04  an mcq with no `correct_option`
  V-02  a `correct_option` naming a label that is not among the options
  V-11  an option over 250 characters, which is `answer_master.answer`'s limit
  V-08  a duplicate of another item in the same chapter -- and this one is why
        the dedupe below is chapter-wide rather than per file: the unique index
        `uq_lqe_extraction_hash` is scoped to ONE extraction, so the same
        question arriving from studentbro and from vedantu passes the database
        and fails the validator, landing with status = 0.
  W-01  an empty answer -- only a warning, so these would load unanswerable

FOUR-BYTE CHARACTERS ARE REJECTED, NOT TRUNCATED. `lms_question_master.answer`
and `.question_title` are utf8mb3. One astral character anywhere in a chapter's
items makes MariaDB refuse that INSERT, so the parser folds everything to ASCII
and this asserts the fold held: a non-ASCII byte here is a bug upstream, and
finding it now costs a re-shape instead of a half-loaded chapter.

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

from scripts.parse_c6_english import CHAPTERS, SB, VD  # noqa: E402

ROOT = Path(__file__).resolve().parent / "c6_english_items"
DRAFTS = ROOT / "drafts"

# The order a duplicate is resolved in. sol is the book's own exercise set and
# its answers are the publisher's worked solutions, so it wins; mcq contributes
# forms the other two do not have and collides with neither; iq is the largest
# and fills what is left.
ORDER = ("sol", "mcq", "iq")

PLACEHOLDERS = {29889, 29890, 29891, 29892, 29893}
VALID_IDS = {c[1] for c in CHAPTERS}
NAME_OF = {c[1]: c[2] for c in CHAPTERS}
CID_OF = {c[0]: c[1] for c in CHAPTERS}


def norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", ud.normalize("NFKC", t or "").lower())


def sha_of(name: str) -> str:
    path = (SB / name) if (SB / name).exists() else (VD / name)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    drafts = {}
    for fam in ORDER:
        p = DRAFTS / f"c6_english_{fam}.json"
        if not p.exists():
            raise SystemExit(f"missing {p} -- run parse_c6_english --write")
        drafts[fam] = json.loads(p.read_text(encoding="utf-8"))

    files = sorted({i["source_file"] for d in drafts.values() for i in d["items"]})
    shas = {f: sha_of(f) for f in files}

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        # (source file, chapter_id) -> extraction_id, found through the file's
        # own sha256. Nothing is resolved by chapter_number, which would be
        # ambiguous for 1-5 against the unit placeholder rows.
        eid: dict[tuple[str, int], int] = {}
        for f, sha in shas.items():
            for r in db.execute(text(
                "SELECT id, chapter_id FROM document_extractions "
                " WHERE content_sha256 = :h AND document_type = 'question_bank'"),
                {"h": sha}).fetchall():
                eid[(f, int(r[1]))] = int(r[0])
        mine = tuple(sorted(set(eid.values())))
        if not mine:
            raise SystemExit("No extraction rows -- run "
                             "setup_c6_english_extractions --apply")
        stray = {c for (_f, c) in eid if c not in VALID_IDS}
        if stray:
            raise SystemExit(f"extraction rows point at chapters outside "
                             f"29860-29875: {sorted(stray)}")
        # What the chapter already holds from somewhere else. Empty today; the
        # check stays because the next source loaded here will not be.
        existing: dict[int, set[str]] = {}
        for cid in VALID_IDS:
            existing[cid] = {norm(s[0])[:120] for s in db.execute(text(
                "SELECT q.question_title FROM lms_question_master q "
                "  LEFT JOIN lms_question_extraction x ON x.question_id = q.id "
                " WHERE q.chapter_id = :c AND q.question_title IS NOT NULL "
                "   AND (x.extraction_id IS NULL OR x.extraction_id NOT IN :mine)"),
                {"c": cid, "mine": mine}).fetchall() if s[0]}
    finally:
        db.close()

    kept: dict[tuple[str, int], list[dict]] = {}
    held: list[tuple[str, dict]] = []
    seen: set[tuple[int, str]] = set()
    for fam in ORDER:
        draft = drafts[fam]
        for it in draft["items"]:
            so = int(it["chapter_number"])
            cid = CID_OF.get(so)
            if cid is None or cid in PLACEHOLDERS:
                held.append(("chapter is not one of the sixteen", it))
                continue
            key = (it["source_file"], cid)
            if key not in eid:
                held.append((f"no extraction row for {it['source_file']} "
                             f"on chapter {cid}", it))
                continue
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
            elif labels:
                held.append(("options on a non-mcq form", it)); continue
            if not (it.get("answer") or "").strip():
                held.append(("W-01 no answer", it)); continue
            blob = it["stem"] + it.get("answer", "") + "".join(
                o["text"] for o in it.get("options") or [])
            if any(ord(c) > 127 for c in blob):
                bad = sorted({hex(ord(c)) for c in blob if ord(c) > 127})
                held.append((f"non-ASCII survived the fold {bad} -- utf8mb3 "
                             f"would refuse the row", it)); continue
            k = norm(it["stem"])[:120]
            if k in existing.get(cid, set()):
                held.append(("already in the bank from another source", it)); continue
            if (cid, k) in seen:
                held.append(("V-08 the same question from more than one source", it))
                continue
            seen.add((cid, k))
            kept.setdefault(key, []).append(it)

    forms = ("mcq", "true_false", "very_short", "short", "long")
    print(f"  {'ch':>3} {'cid':>7} {'eid':>5} {'pub':<11} {'source file':<26} "
          + " ".join(f"{f:>6}" for f in forms) + f" {'keep':>5}")
    print("  " + "-" * 116)
    per_chapter: dict[int, int] = {c[1]: 0 for c in CHAPTERS}
    total = 0
    for so, cid, name, _u in CHAPTERS:
        for (f, c), items in sorted(kept.items(), key=lambda kv: kv[0][0]):
            if c != cid:
                continue
            pub = "vedantu" if f.startswith("iq_") else "studentbro"
            per_chapter[cid] += len(items)
            total += len(items)
            print(f"  {so:>3} {cid:>7} {eid[(f, c)]:>5} {pub:<11} {f:<26} "
                  + " ".join(f"{sum(1 for i in items if i['form']==g):>6}" for g in forms)
                  + f" {len(items):>5}")
    print("  " + "-" * 116)
    print(f"\n  {'ch':>3} {'cid':>7} {'chapter':<48} {'questions':>9}")
    for so, cid, name, _u in CHAPTERS:
        flag = "  <-- ZERO" if per_chapter[cid] == 0 else ""
        print(f"  {so:>3} {cid:>7} {name[:48]:<48} {per_chapter[cid]:>9}{flag}")
    print(f"  {'':>3} {'':>7} {'TOTAL':<48} {total:>9}")
    forms_total = {g: sum(1 for v in kept.values() for i in v if i["form"] == g)
                   for g in forms}
    print(f"\n  by form: " + "  ".join(f"{g}={n}" for g, n in forms_total.items()))

    print(f"\n  held back ({len(held)}):")
    for why in dict.fromkeys(w for w, _ in held):
        g = [i for w, i in held if w == why]
        print(f"    {len(g):>4}  {why}")
        for i in g[:2]:
            print(f"          ch{i['chapter_number']} [{i['source']}]: "
                  f"{' '.join(i['stem'].split())[:76]}")

    if a.write:
        for (f, cid), items in sorted(kept.items()):
            pub = "vedantu" if f.startswith("iq_") else "studentbro"
            out = ROOT / pub
            out.mkdir(parents=True, exist_ok=True)
            so = next(c[0] for c in CHAPTERS if c[1] == cid)
            # Renumbered per file. The printed numbers restart at every exercise
            # heading, so a chapter's items carry the number "1" several times
            # over and the loader's own sanity check rejects the file as having
            # duplicate question numbers.
            for n, it in enumerate(items, 1):
                it["number"] = n
            tag = Path(f).stem.replace("c6_english_", "")
            (out / f"ch{so:02d}_{tag}.json").write_text(json.dumps(
                {"chapter": so, "chapter_id": cid, "extraction_id": eid[(f, cid)],
                 "source_file": f, "publisher": pub, "items": items},
                indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {len(kept)} file(s) under {ROOT}")
    else:
        print("\nreport only -- re-run with --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
