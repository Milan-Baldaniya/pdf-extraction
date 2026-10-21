"""Write authored model answers onto questions stored without one.

    python -m scripts.backfill_answers --chapter 1012 --report
    python -m scripts.backfill_answers --file kvs_items/answers_sci10_ch1012.json --dry
    python -m scripts.backfill_answers --file kvs_items/answers_sci10_ch1012.json

`--report` dumps the answerless stems for a chapter so they can be authored;
`--file` loads a `{"chapter_id": N, "answers": {question_id: text}}` document
through `answer_backfill.backfill`, which merges the JSON envelope and stamps
`answer_origin="authored"` on every row it touches.

The answers in these files were written for the bank. They are NOT a
publisher's marking scheme, and the provenance stamp is what keeps that
distinction checkable later.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.answer_backfill import (  # noqa: E402
    backfill,
    hold_figure_dependent,
    missing_answers,
)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

HERE = Path(__file__).resolve().parent


def report(chapter_id: int, limit: int | None) -> int:
    rows = missing_answers(chapter_id)
    print(f"chapter {chapter_id}: {len(rows)} narrative question(s) with no model answer\n")
    for row in rows[:limit] if limit else rows:
        stem = " ".join(str(row["question_title"] or "").split())
        print(f'{row["id"]}|{stem}')
    return 0


def load(path: Path, *, dry: bool, author: str) -> int:
    if not path.is_absolute():
        path = HERE / path
    with path.open(encoding="utf-8") as handle:
        doc = json.load(handle)

    raw = doc.get("answers") or {}
    if not isinstance(raw, dict) or not raw:
        print(f"{path.name}: no 'answers' object -- nothing to do")
        return 1

    # Keys arrive as JSON strings; the service addresses rows by integer id.
    answers = {int(k): v for k, v in raw.items()}
    chapter_id = doc.get("chapter_id")

    before = len(missing_answers(chapter_id)) if chapter_id else None
    result = backfill(answers, author=author, dry_run=dry)
    after = len(missing_answers(chapter_id)) if chapter_id and not dry else None

    print(f"{path.name}  chapter={chapter_id}  author={author}"
          f"{'  (DRY RUN)' if dry else ''}")
    print(f"  requested={result['requested']}  written={result['written']}"
          f"  skipped={result['skipped']}  missing={result['missing']}")
    if before is not None:
        tail = f" -> {after}" if after is not None else ""
        print(f"  answerless on this chapter: {before}{tail}")

    # A row we could not find is a real problem: the file names a question id
    # that is not in the bank, so the answer has gone nowhere.
    return 1 if result["missing"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chapter", type=int, help="chapter id")
    parser.add_argument("--report", action="store_true",
                        help="print the answerless stems for --chapter")
    parser.add_argument("--limit", type=int, help="with --report, first N only")
    parser.add_argument("--file", help="answers JSON to load")
    parser.add_argument("--dry", action="store_true", help="validate, write nothing")
    parser.add_argument("--author", default="claude-opus-5")
    parser.add_argument("--hold-figures", action="store_true",
                        help="hold answerless items that need a figure the bank "
                             "does not store")
    args = parser.parse_args()

    if args.report:
        if not args.chapter:
            parser.error("--report needs --chapter")
        return report(args.chapter, args.limit)

    if args.hold_figures:
        if not args.chapter:
            parser.error("--hold-figures needs --chapter")
        held = hold_figure_dependent(args.chapter, dry_run=args.dry)
        print(f"chapter {args.chapter}: {held['held']} figure-dependent item(s) "
              f"held{'  (DRY RUN)' if args.dry else ''}")
        return 0

    if args.file:
        return load(Path(args.file), dry=args.dry, author=args.author)

    parser.error("give --file, or --report with --chapter")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
