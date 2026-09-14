"""Print the question region of an extracted chapter.

A chapter's markdown opens with a concept map, key points and worked
examples -- typically the first third -- which are not questions and do not
need reading. This trims to the first question heading so only the part that
matters is read.

    python -m scripts.dump_questions 182
    python -m scripts.dump_questions 182 --from 8000 --chars 12000
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal  # noqa: E402

# Where a chapter stops explaining and starts asking.
_START_RE = re.compile(
    r"MULTIPLE\s+CHOICE|\bMCQ|Section\s*[-–—]?\s*A\b|OBJECTIVE\s+TYPE"
    r"|Assertion\s*[-–—]?\s*Reason|VERY\s+Short|Questions?\s+for\s+Practice",
    re.IGNORECASE,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extraction_id", type=int)
    parser.add_argument("--from", dest="start", type=int, default=None)
    parser.add_argument("--chars", type=int, default=0, help="0 = to the end")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        md = db.execute(
            text("SELECT md_content FROM document_extractions WHERE id = :i"),
            {"i": args.extraction_id},
        ).scalar()
    finally:
        db.close()

    if not md:
        print(f"Extraction {args.extraction_id} has no markdown.")
        return 1

    if args.start is not None:
        start = args.start
    else:
        hit = _START_RE.search(md)
        start = hit.start() if hit else 0

    end = start + args.chars if args.chars else len(md)
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"### extraction {args.extraction_id}: chars {start}-{min(end, len(md))} of {len(md)}\n")
    print(md[start:end])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
