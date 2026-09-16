"""How far along is the 40-MCQ-per-concept programme.

    python -m scripts.concept_mcq_status --chapters 1012
    python -m scripts.concept_mcq_status --chapters 1012-1024 --summary
    python -m scripts.concept_mcq_status --chapters 1012 --gaps-only
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.concept_mcq_program import (  # noqa: E402
    LADDER,
    TARGET_PER_CONCEPT,
    plan_chapter,
)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LEVELS = list(LADDER)


def parse_chapters(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return sorted(set(out))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chapters", required=True, help="e.g. 1012 or 1012-1024")
    parser.add_argument("--summary", action="store_true", help="one line per chapter")
    parser.add_argument("--gaps-only", action="store_true",
                        help="hide concepts already at target")
    args = parser.parse_args()

    grand_have = grand_target = 0

    for chapter_id in parse_chapters(args.chapters):
        plan = plan_chapter(chapter_id)
        if not plan:
            print(f"chapter {chapter_id}: no concepts")
            continue

        target = len(plan) * TARGET_PER_CONCEPT
        have = sum(p["have_total"] for p in plan)
        grand_have += have
        grand_target += target
        name = str(plan[0].get("chapter_name") or "")[:44]

        if args.summary:
            pct = 100 * have / target if target else 0
            print(f"  {chapter_id:<6}{name:<46}{len(plan):>3}c "
                  f"{have:>5}/{target:<6} {pct:>5.1f}%")
            continue

        print(f"\nchapter {chapter_id}  {name}   "
              f"{len(plan)} concepts, {have}/{target} MCQs")
        head = f"  {'concept':<44}" + "".join(f"{lv[:4]:>7}" for lv in LEVELS) \
               + f"{'unset':>7}{'have':>6}{'gap':>6}"
        print(head)
        print("  " + "-" * (len(head) - 2))
        for p in plan:
            if args.gaps_only and p["gap_total"] == 0:
                continue
            cells = "".join(f"{p['have'].get(lv, 0):>7}" for lv in LEVELS)
            print(f"  {str(p['name'])[:42]:<44}{cells}"
                  f"{p['have'].get('Unset', 0):>7}{p['have_total']:>6}{p['gap_total']:>6}")

    if args.summary and grand_target:
        print(f"\n  {'TOTAL':<52}{grand_have:>5}/{grand_target:<6} "
              f"{100 * grand_have / grand_target:>5.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())