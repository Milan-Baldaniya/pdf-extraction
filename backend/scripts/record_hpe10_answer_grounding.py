"""Write each derived answer's grounding quotes into the database.

    python -m scripts.record_hpe10_answer_grounding
    python -m scripts.record_hpe10_answer_grounding --apply

WHY. Every answer in the Class X HPE bank was derived from the chapter prose,
because there is no key to read: the subject is 100% internal assessment, CBSE
publishes no marking scheme and the textbook prints no answers. The publisher and
`tagged_by = 'derived'` say that an answer was derived. They do not say WHAT it
was derived from, and without that a reviewer who doubts one answer has no way to
check it except to re-read the chapter.

So the quotes each answer rests on go in `pal_question_metadata.ai_rationale`,
which is the column for "why this is what it is". A reviewer can then open one
row and see the sentences the answer came from. Those quotes were verified
against the mirrored PDF by `shape_ncert_hpe10_for_load` before the load, and the
same match can be re-run from what this writes.

HOW IT MATCHES. On `verbatim_sha256`, the content hash `persist_supplied`
computed over the reproduced stem, options and answer, which is already stored on
`lms_question_extraction` and copied to `pal_question_metadata.content_id_ref`.
Matching on the hash rather than on the item number means a row can only ever be
paired with the item whose text it actually is.

UPDATE only, and only where `ai_rationale` IS NULL, so a value written by a human
or a later authoring pass is never overwritten. `ai_rationale` carries a
json_valid() CHECK, so a bare string would be rejected outright -- the payload is
a JSON object. It is utf8mb4, but the text is folded to ASCII anyway to match
everything else in this bank.
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

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

from scripts.shape_ncert_hpe10_for_load import (  # noqa: E402
    ALIGNMENT, LOAD, PUBLISHER, source_url,
)

BY_N = {row["n"]: row for row in ALIGNMENT}
NOTE = ("Answer derived from the chapter text, not from any printed or official "
        "key. These are the quotes it was derived from, verified against the "
        "source PDF before loading.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        print(f"{'ch':<3} {'items':>5} {'matched':>8} {'already set':>12} "
              f"{'to write':>9}  note")
        print("-" * 78)
        totals = {"items": 0, "matched": 0, "set": 0, "write": 0}
        pending: list[dict] = []
        for path in sorted(LOAD.glob("ch*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            n = data["chapter"]
            row = BY_N[n]
            matched = already = towrite = 0
            missing: list[str] = []
            for item in data["items"]:
                totals["items"] += 1
                if not item.get("grounding"):
                    continue
                # The same hash persist_supplied computes, over the same fields.
                payload = "|".join([
                    " ".join((item.get("stem") or "").split()),
                    "", "",   # assertion, reason -- unused by this bank
                    "|".join(f"{o['label'].upper()}:{' '.join(o['text'].split())}"
                             for o in item.get("options") or []),
                ])
                digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
                found = db.execute(text(
                    "SELECT m.id, m.ai_rationale "
                    "  FROM lms_question_extraction e "
                    "  JOIN pal_question_metadata m ON m.question_id = e.question_id "
                    " WHERE e.verbatim_sha256 = :h AND e.extraction_id = :x"),
                    {"h": digest, "x": data["extraction_id"]}).mappings().fetchall()
                if not found:
                    missing.append(str(item["number"]))
                    continue
                matched += len(found)
                for hit in found:
                    if hit["ai_rationale"]:
                        already += 1
                        continue
                    towrite += 1
                    pending.append({
                        "id": hit["id"],
                        "payload": json.dumps({
                            "answer_provenance": "derived_from_chapter_text",
                            "note": NOTE,
                            "source_url": source_url(row),
                            "ncert_chapter": row["ncert"],
                            "item_number": str(item["number"]),
                            "reproduction": item.get("reproduction", "verbatim"),
                            "grounding": item["grounding"],
                        }, ensure_ascii=True),
                    })
            totals["matched"] += matched
            totals["set"] += already
            totals["write"] += towrite
            note = ("" if not missing
                    else f"NO DB ROW for item(s) {', '.join(missing[:6])}")
            print(f"{n:<3} {len(data['items']):>5} {matched:>8} {already:>12} "
                  f"{towrite:>9}  {note}")
        print("-" * 78)
        print(f"{'ALL':<3} {totals['items']:>5} {totals['matched']:>8} "
              f"{totals['set']:>12} {totals['write']:>9}")

        if not a.apply:
            print("\ndry run -- pass --apply to write")
            return 0
        for chunk_start in range(0, len(pending), 200):
            chunk = pending[chunk_start:chunk_start + 200]
            db.execute(text(
                "UPDATE pal_question_metadata "
                "   SET ai_rationale = :payload "
                " WHERE id = :id AND ai_rationale IS NULL"), chunk)
            db.commit()
        done = db.execute(text(
            "SELECT COUNT(*) FROM pal_question_metadata m "
            "  JOIN lms_question_master q ON q.id = m.question_id "
            " WHERE q.chapter_id IN "
            f"  ({', '.join(str(r['chapter_id']) for r in ALIGNMENT)}) "
            "   AND m.ai_rationale IS NOT NULL")).scalar()
        print(f"\n{len(pending)} row(s) written; "
              f"{done} of the bank's PAL rows now carry their grounding")
        print(f"publisher: {PUBLISHER}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
