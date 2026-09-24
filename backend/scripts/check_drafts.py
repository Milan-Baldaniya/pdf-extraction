"""Check verified draft files before they are merged and loaded.

    python -m scripts.check_drafts --chapter 3
    python -m scripts.check_drafts --all

Every draft is read by somebody before it loads; this is the mechanical half of
that, run over their output. It checks the things a reader cannot reliably
eyeball across hundreds of items, and says nothing about whether a stem is
faithful -- that is what the reading is for.

The concept check matters most. `apply_read_concepts` matches a name against
`lms_concept` for the chapter and RAISES on a miss, which abandons concept
assignment for the whole chapter, so one typo costs every question in the file
its concept. Catching it here costs nothing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DRAFTS = Path(__file__).resolve().parent / "c9sci_items" / "drafts"
BLOOM = {"recall", "understand", "apply", "analyze", "evaluate", "create"}

# Page furniture that has turned up bled into a stem or an answer, sometimes
# spliced mid-sentence. Any of these surviving means the item was not cleaned.
JUNK = re.compile(
    r"Click Here to Buy|Downloaded from|www\.pdf\.tube|NODIA|lympiad"
    r"|Chapterwise QB|Previous Year Solved|Order the Hard copy"
    r"|OBJECTIVE\s+QUESTION|VER\s*Y\s+SHO\s*RT|SSHOR\s*T\s+ANSWER"
    r"|CAS\s*E\s+BASED|LON\s*G\s+Answer|NCER\s*T\s+Exercis",
    re.I,
)


def concepts_for(db, chapter_id: int) -> set[str]:
    rows = db.execute(
        text(
            "SELECT name FROM lms_concept WHERE chapter_id = :c "
            "  AND (concept_show_hide IS NULL OR concept_show_hide <> 0)"
        ),
        {"c": chapter_id},
    ).fetchall()
    return {r[0] for r in rows}


def check_file(path: Path, legal: set[str]) -> tuple[list[str], dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("items") or []
    problems: list[str] = []
    stats = {"items": len(items), "tagged": 0,
             "bloom": Counter(), "concepts": set()}

    numbers = Counter(str(i.get("number")) for i in items)
    for number, count in numbers.items():
        if count > 1:
            problems.append(f"number {number} appears {count} times")

    for item in items:
        ref = f"#{item.get('number')}"
        if not (item.get("stem") or "").strip():
            problems.append(f"{ref} empty stem")
        if not (item.get("answer") or "").strip():
            problems.append(f"{ref} no answer")

        concept = item.get("concept")
        if not concept:
            problems.append(f"{ref} no concept")
        elif concept not in legal:
            problems.append(f"{ref} concept not in chapter: {concept!r}")
        else:
            stats["concepts"].add(concept)

        bloom = item.get("bloom")
        if bloom not in BLOOM:
            problems.append(f"{ref} bloom {bloom!r} not legal")
        else:
            stats["bloom"][bloom] += 1
        try:
            if not 1 <= int(item.get("dok")) <= 4:
                raise ValueError
        except (TypeError, ValueError):
            problems.append(f"{ref} dok {item.get('dok')!r} not 1-4")
        try:
            if not 1 <= int(item.get("difficulty")) <= 5:
                raise ValueError
        except (TypeError, ValueError):
            problems.append(f"{ref} difficulty {item.get('difficulty')!r} not 1-5")

        if all(item.get(k) for k in ("concept", "bloom", "dok", "difficulty")):
            stats["tagged"] += 1

        options = item.get("options") or []
        if item.get("form") == "mcq" and len(options) != 4:
            problems.append(f"{ref} mcq has {len(options)} options, V-09 needs 4")
        if options and not item.get("correct_option"):
            problems.append(f"{ref} options but no correct_option")
        labels = [o.get("label") for o in options]
        if item.get("correct_option") and item["correct_option"] not in labels:
            problems.append(f"{ref} correct_option {item['correct_option']!r} not a label")
        if len(labels) != len(set(labels)):
            problems.append(f"{ref} duplicate option labels")
        for option in options:
            if len(option.get("text") or "") > 250:
                problems.append(f"{ref} option over 250 chars, V-11")
            if len((option.get("text") or "").strip()) < 2:
                problems.append(f"{ref} option {option.get('label')} is empty or a fragment")
        if item.get("figure_required") and not item.get("images"):
            problems.append(f"{ref} figure_required with no images, V-07")

        for field in ("stem", "answer"):
            hit = JUNK.search(item.get(field) or "")
            if hit:
                problems.append(f"{ref} {field} still carries {hit.group(0)!r}")
    return problems, stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chapter", type=int, action="append")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=6)
    a = ap.parse_args()

    paths = sorted(DRAFTS.glob("ch*_*.json"))
    if a.chapter:
        wanted = {f"ch{c:02d}_" for c in a.chapter}
        paths = [p for p in paths if any(p.name.startswith(w) for w in wanted)]
    elif not a.all:
        ap.error("give --chapter N or --all")

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    legal_cache: dict[int, set[str]] = {}
    total = tagged = bad_files = 0
    try:
        for path in paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            chapter_id = payload.get("chapter_id")
            if chapter_id not in legal_cache:
                legal_cache[chapter_id] = concepts_for(db, chapter_id)
            problems, stats = check_file(path, legal_cache[chapter_id])
            total += stats["items"]
            tagged += stats["tagged"]
            flag = "ok" if not problems else f"{len(problems)} problem(s)"
            print(f"{path.name:<26} {stats['items']:>4} items  "
                  f"{stats['tagged']:>4} tagged  {len(stats['concepts']):>3} concepts  {flag}")
            if problems:
                bad_files += 1
                for problem in problems[: a.limit]:
                    print(f"      ! {problem}")
                if len(problems) > a.limit:
                    print(f"      ! ... and {len(problems) - a.limit} more")
    finally:
        db.close()
    print(f"\n{total} item(s), {tagged} fully tagged, {bad_files} file(s) with problems")
    return 1 if bad_files else 0


if __name__ == "__main__":
    raise SystemExit(main())
