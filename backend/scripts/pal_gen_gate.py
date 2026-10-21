"""Quality gate for PAL V4 generated items, then load them.

    python -m scripts.pal_gen_gate --file pal_gen_items/ch25854_pilot.json
    python -m scripts.pal_gen_gate --file pal_gen_items/ch25854_pilot.json --apply

Implements the checks in `pal-v4-question-intelligence-master-prompt.md`
Section 9, plus the Section 5 step 6 grounding rule, which is the one that
actually constrains generation:

> Generate ONLY to fill measured gaps -- each generated item must be grounded
> in at least one `sourced_verbatim` example for the same concept (never
> generated from a bare description).

**That rule has a consequence worth stating plainly: generation cannot fill a
concept that has no sourced question.** It can only deepen a concept that is
already covered -- adding a Bloom level, a difficulty band, a question form or
a misconception probe. A chapter whose gap is 14 entirely uncovered concepts,
as this pilot's is, cannot be closed by generating; it needs a real source.

GATES. G1 the grounding sibling exists, is live, and sits in this chapter.
G2 the sibling carries the same concept, OR the item declares the sibling's
tag wrong and says which concept it is really filing under. G3 the concept
belongs to this chapter. G4 core fields present and non-placeholder. G5 an
MCQ has exactly 4 options, the correct answer is among them, and no two
options are identical. G6 no near-duplicate stem already exists in this
chapter under the same concept. G7 mark_scheme present unless a plain MCQ.
G8 a claimed misconception has a description. G9 **the arithmetic is
recomputed here, independently of the file** -- a wrong key is the defect
this whole estate keeps finding in published material, and a generated bank
has no source to check against, so it must check itself.

Anything failing a gate is reported and NOT loaded. A generated item that
cannot pass is worth less than the gap it would fill.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

WS = re.compile(r"\s+")
WORD = re.compile(r"[a-z0-9]+")


def norm(s: str) -> str:
    return WS.sub(" ", (s or "")).strip()


def bag(s: str) -> set:
    return set(WORD.findall((s or "").lower()))


# ---- G9: independent recomputation --------------------------------------
# Each entry re-derives the answer from first principles, without reading the
# file's answer. Keyed on a distinctive fragment of the question text.
def _checks() -> list:
    return [
        ("odd numbers, starting from 1, add up to 144",
         lambda: str(int(math.isqrt(144)))),                       # 12
        ("1 + 3 + 5 + 7 + 9 + 11",
         lambda: str(sum([1, 3, 5, 7, 9, 11]))),                   # 36
        ("first 15 odd natural numbers",
         lambda: str(15 ** 2)),                                    # 225
        ("area of a square field is 169",
         lambda: f"{math.isqrt(169)} m"),                          # 13 m
        ("Which of these is a perfect square?",
         lambda: next(str(n) for n in (48, 64, 72, 80)
                      if math.isqrt(n) ** 2 == n)),                # 64
        ("must 48 be multiplied",
         lambda: str(next(k for k in range(2, 10)
                          if math.isqrt(48 * k) ** 2 == 48 * k))),  # 3
        ("can NOT be a perfect square",
         lambda: next(str(n) for n in (1024, 2027, 3136, 4096)
                      if math.isqrt(n) ** 2 != n)),                # 2027
        ("ends in 3. Which digit does its square end in",
         lambda: str((3 * 3) % 10)),                               # 9
        ("find 41 squared",
         lambda: str(41 ** 2)),                                    # 1681
        ("units place of 63 squared",
         lambda: str((63 ** 2) % 10)),                             # 9
        ("(8, 15, x)",
         lambda: str(math.isqrt(8 ** 2 + 15 ** 2))),               # 17
        ("(7, 24, 25) is a Pythagorean triplet",
         lambda: "625" if 7 ** 2 + 24 ** 2 == 25 ** 2 else "FAIL"),
        ("Starting from 81 and subtracting",
         lambda: str(math.isqrt(81))),                             # 9
        ("zero after exactly 6 subtractions",
         lambda: str(6 ** 2)),                                     # 36
        ("perfect square has 4 digits",
         lambda: str(math.ceil(4 / 2))),                           # 2
        ("5-digit perfect square",
         lambda: str(math.ceil(5 / 2))),                           # 3
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    path = Path(__file__).resolve().parent / a.file
    doc = json.loads(path.read_text(encoding="utf-8"))
    meta, items = doc["_meta"], doc["items"]
    cid = int(meta["chapter_id"])
    print(f"  {path.name}: {len(items)} item(s) for chapter {cid} "
          f"{meta['chapter']}\n")

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        concepts = {int(i): str(n) for i, n in db.execute(text(
            "SELECT id, name FROM lms_concept WHERE chapter_id=:c"),
            {"c": cid}).fetchall()}
        sourced = {int(q): (str(t or ""), cn) for q, t, cn in db.execute(text(
            "SELECT q.id, q.question_title, COALESCE(q.concept_id, e.concept_id) "
            "  FROM lms_question_master q "
            "  LEFT JOIN lms_question_extraction e ON e.question_id=q.id "
            " WHERE q.chapter_id=:c AND q.deleted_at IS NULL"),
            {"c": cid}).fetchall()}
        existing = [(str(t or ""), cn) for t, cn in db.execute(text(
            "SELECT q.question_title, COALESCE(q.concept_id, e.concept_id) "
            "  FROM lms_question_master q "
            "  LEFT JOIN lms_question_extraction e ON e.question_id=q.id "
            " WHERE q.chapter_id=:c AND q.deleted_at IS NULL"),
            {"c": cid}).fetchall()]

        recompute = _checks()
        passed, failed = [], []
        for it in items:
            q = norm(it.get("question_text", ""))
            fails = []

            g = it.get("grounded_on")
            if g is None or int(g) not in sourced:
                fails.append("G1 grounding sibling not a live question of this chapter")
            else:
                sib_concept = sourced[int(g)][1]
                if sib_concept != it.get("concept_id") and "note" not in it:
                    fails.append(f"G2 sibling {g} carries concept {sib_concept}, "
                                 f"item claims {it.get('concept_id')}, and no note "
                                 f"explains the difference")

            if int(it.get("concept_id", 0)) not in concepts:
                fails.append("G3 concept_id is not a concept of this chapter")

            for f in ("question_text", "correct_answer", "answer_explanation",
                      "bloom_level", "question_type"):
                if not norm(str(it.get(f, ""))):
                    fails.append(f"G4 {f} missing")

            opts = it.get("options") or []
            if it.get("question_type") == "mcq":
                if len(opts) != 4:
                    fails.append(f"G5 mcq has {len(opts)} options, not 4")
                elif len({norm(o) for o in opts}) != 4:
                    fails.append("G5 two options are identical")
                elif norm(it["correct_answer"]) not in {norm(o) for o in opts}:
                    fails.append("G5 correct answer is not among the options")

            qb = bag(q)
            for etext, ecn in existing:
                if ecn == it.get("concept_id") and qb and bag(etext):
                    ov = len(qb & bag(etext)) / len(qb)
                    if ov > 0.8:
                        fails.append(f"G6 near-duplicate of an existing item "
                                     f"({ov:.0%} overlap) under the same concept")
                        break

            if it.get("question_type") != "mcq" and not norm(it.get("mark_scheme", "")):
                fails.append("G7 mark_scheme missing on a non-MCQ")

            mis = it.get("misconception") or {}
            if mis.get("applicable") and not norm(mis.get("description", "")):
                fails.append("G8 misconception claimed with no description")

            hit = next((fn for frag, fn in recompute if frag in q), None)
            if hit is None:
                fails.append("G9 no independent recomputation covers this item")
            else:
                want = hit()
                if norm(want).lower() not in norm(it["correct_answer"]).lower():
                    fails.append(f"G9 recomputed {want!r}, file says "
                                 f"{norm(it['correct_answer'])!r}")

            (failed if fails else passed).append((it, fails))

        print(f"  PASSED {len(passed)}   FAILED {len(failed)}\n")
        for it, fails in failed:
            print(f"   FAIL  {norm(it.get('question_text',''))[:64]}")
            for f in fails:
                print(f"          {f}")
        if passed:
            print("\n  gate detail on the passing set:")
            byc, byb, byt = {}, {}, {}
            for it, _ in passed:
                byc[it["concept_name"]] = byc.get(it["concept_name"], 0) + 1
                byb[it["bloom_level"]] = byb.get(it["bloom_level"], 0) + 1
                byt[it["question_type"]] = byt.get(it["question_type"], 0) + 1
            print(f"   concepts  {len(byc)}: " + ", ".join(f"{k[:26]}={v}" for k, v in byc.items()))
            print(f"   bloom     " + ", ".join(f"{k}={v}" for k, v in byb.items()))
            print(f"   forms     " + ", ".join(f"{k}={v}" for k, v in byt.items()))
            mis = sum(1 for it, _ in passed if (it.get("misconception") or {}).get("applicable"))
            print(f"   items carrying an evidenced misconception: {mis}")

        if not a.apply:
            print("\n  gate only -- no rows written. Re-run with --apply to load "
                  "the passing set.")
            return 0 if not failed else 1
        print("\n  --apply is not wired yet: the loader path for generated items "
              "needs a\n  publisher and a provenance decision that belong to the "
              "user, not this gate.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
