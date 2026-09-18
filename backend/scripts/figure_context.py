"""Show every figure reference in a chapter with the evidence needed to place it.

    python -m scripts.figure_context 233
    python -m scripts.figure_context 233 --only-unplaced
    python -m scripts.figure_context 233 --context 600

A figure printed in a question must be attached to it; a figure printed inside
the worked solution must not be, or the answer is given away on the question
paper. The two are told apart by ONE piece of evidence: whether the chapter's
"Ans" marker for that question appears before or after the image reference.

For each reference this prints:
  - the nearest question number printed before it
  - whether an "Ans" marker sits between that number and the image
      BEFORE_ANS -> the image is part of the question   -> attach
      AFTER_ANS  -> the image is part of the solution   -> do not attach
  - the surrounding text, so a judgement call can be made on wording such as
    "in the figure below" or "draw a labelled diagram"
  - whether the file is already attached to a stored question

The verdict is a strong default, not a rule: a question whose stem says "draw"
owns no figure even when one precedes the answer, and a multi-part case study
can legitimately carry a figure after its first sub-answer.
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text  # noqa: E402
from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

IMG = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
NUM = re.compile(r"(?<![0-9.])([0-9]{1,3})\s*[.)]\s+(?=[A-Z(])")
ANS = re.compile(r"(?<![A-Za-z])Ans(?![A-Za-z])")


def base_name(ref: str) -> str:
    return ref.split("?")[0].rstrip(")").replace("\\", "/").rsplit("/", 1)[-1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("extraction_id", type=int)
    ap.add_argument("--context", type=int, default=420)
    ap.add_argument("--only-unplaced", action="store_true",
                    help="hide references already attached to a question")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        row = db.execute(text(
            "SELECT chapter_id, md_content, asset_manifest FROM document_extractions "
            " WHERE id = :i"), {"i": a.extraction_id}).fetchone()
        if not row:
            raise SystemExit(f"extraction {a.extraction_id} not found")
        chapter_id, md, manifest = row
        entries = json.loads(manifest) if isinstance(manifest, str) else (manifest or [])
        pages = {e.get("file_name"): e.get("page_number") for e in entries}
        attached = {r[0] for r in db.execute(text(
            "SELECT DISTINCT SUBSTRING_INDEX(a.source_path, '/', -1) "
            "  FROM lms_question_asset a JOIN lms_question_master q ON q.id = a.question_id "
            " WHERE q.chapter_id = :c"), {"c": chapter_id}).fetchall()}
    finally:
        db.close()

    hits = list(IMG.finditer(md or ""))
    print(f"extraction {a.extraction_id} | chapter {chapter_id} | "
          f"{len(hits)} figure reference(s)\n")
    shown = 0
    for m in hits:
        name = base_name(m.group(1))
        is_attached = name in attached
        if a.only_unplaced and is_attached:
            continue
        shown += 1
        before = md[max(0, m.start() - a.context):m.start()]
        after = md[m.end():m.end() + a.context // 2]
        nums = NUM.findall(before)
        last_num = nums[-1] if nums else "?"
        tail = before[before.rfind(last_num + ".") if last_num != "?" else 0:]
        verdict = "AFTER_ANS  (solution figure - do NOT attach)" if ANS.search(tail) \
            else "BEFORE_ANS (question figure - attach)"
        print(f"--- {name}  page {pages.get(name)}  "
              f"{'ALREADY ATTACHED' if is_attached else 'not attached'}")
        print(f"    nearest question number before it: {last_num}")
        print(f"    verdict: {verdict}")
        print(f"    ...{' '.join(before[-a.context:].split())}")
        print(f"    >>> IMAGE <<< {' '.join(after.split())[:160]}...\n")
    print(f"shown {shown} of {len(hits)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
