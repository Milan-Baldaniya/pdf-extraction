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


# Flattened maths. The PDF text layer loses the layout of fractions and stacked
# equations, leaving the glyphs in reading order with the operator stranded --
# "v u at = +" for v = u + at, "t a v u = -" for t = (v-u)/a. It reads as noise
# but a reader can resolve it from the answer prose, so it is recoverable; what
# it must not do is pass silently. In a numerical section an unreconstructed
# fraction is a WRONG ANSWER, not an ugly one, and no other check can see it:
# a file with thirty damaged equations was reported ok.
MATHS_DAMAGE = (
    # an equals sign with the operator stranded after it
    re.compile(r"=\s*[+\-−×÷](?:\s|$)"),
    # two or more bare single letters before an equals, e.g. "v u at ="
    re.compile(r"(?:[a-zA-Z]\s+){2,}[a-zA-Z]*\s*="),
    # a run of lone digits before an equals, e.g. "s ut at 2 1 2 ="
    re.compile(r"(?:\d\s+){2,}\d*\s*="),
)


def maths_damage(text: str) -> str | None:
    for pattern in MATHS_DAMAGE:
        hit = pattern.search(text or "")
        if hit:
            return hit.group(0).strip()
    return None


# A whole question buried inside another question's field. The books are set in
# two columns and the text layer reads a page column by column, so a question
# printed beside another one can be appended to it -- chapter 5's very short
# Q76 ended up inside objective Q35's option C, and Q76's answer overwrote
# Q35's answer field. Two questions destroyed, and nothing else notices: Q35
# still had four options and an answer, so V-02, V-09 and every other check
# here passed it.
#
# The signature is a question number appearing mid-field. The trap is that
# stems and answers legitimately carry numbered sub-parts, and a naive version
# of this check flagged 51 of them across chapters 3 and 4 -- every one a real
# "1. ... 2. ..." list. Two things separate them: a sub-part list starts at 1
# or 2 and ascends by one, and a buried question's number belongs to the
# book's own sequence, so it runs AHEAD of the item it is buried in.
EMBEDDED_NUMBER = re.compile(
    r"(?<=[.?!\"”)])\s+(\d{1,3})\s*[.)]\s+([A-Z][a-z][^.?!]{25,})"
)


def _own_number(number: object) -> int | None:
    digits = re.sub(r"^[A-Za-z]+", "", str(number or "")).split(".")[0]
    return int(digits) if digits.isdigit() else None


def embedded_question(text: str, own: int | None) -> str | None:
    hits = list(EMBEDDED_NUMBER.finditer((text or "")[8:]))
    if not hits:
        return None
    numbers = [int(h.group(1)) for h in hits]
    # A numbered sub-part list: starts at 1 or 2, ascends by one, no gaps.
    if numbers[0] <= 2 and numbers == list(range(numbers[0], numbers[0] + len(numbers))):
        return None
    if own is None:
        return None
    for hit, number in zip(hits, numbers):
        if number > own:
            return f"{number}. {hit.group(2)[:60]}"
    return None


def running_header(db, chapter_id: int) -> re.Pattern | None:
    """The chapter's own title, which is printed as the running header.

    Every page carries it, so it bleeds into stems and answers like any other
    furniture -- and sometimes mid-sentence, because an item straddling a page
    break gets the header spliced into it. JUNK cannot hold it as a literal
    because it is different in every chapter, so it is built per chapter here.
    It went unnoticed until a reader found it in three items of a file the
    checker had passed as ok.

    Only titles of three or more words are used. A one- or two-word title such
    as "Motion" would match ordinary prose and turn this into noise.
    """
    name = db.execute(
        text("SELECT chapter_name FROM chapter_master WHERE id = :c"),
        {"c": chapter_id},
    ).scalar()
    if not name or len(name.split()) < 3:
        return None
    # Tolerate the whitespace the text layer inserts between words.
    return re.compile(r"\s+".join(re.escape(w) for w in name.split()), re.I)


def concepts_for(db, chapter_id: int) -> set[str]:
    rows = db.execute(
        text(
            "SELECT name FROM lms_concept WHERE chapter_id = :c "
            "  AND (concept_show_hide IS NULL OR concept_show_hide <> 0)"
        ),
        {"c": chapter_id},
    ).fetchall()
    return {r[0] for r in rows}


def check_file(path: Path, legal: set[str],
               header: re.Pattern | None = None) -> tuple[list[str], dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("items") or []
    problems: list[str] = []
    stats = {"items": len(items), "tagged": 0,
             "bloom": Counter(), "concepts": set(), "numbers": []}

    numbers = Counter(str(i.get("number")) for i in items)
    for number, count in numbers.items():
        if count > 1:
            problems.append(f"number {number} appears {count} times")

    for item in items:
        ref = f"#{item.get('number')}"
        own = _own_number(item.get("number"))
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
            damage = maths_damage(item.get(field) or "")
            if damage:
                problems.append(f"{ref} {field} has flattened maths: {damage!r}")
            buried = embedded_question(item.get(field) or "", own)
            if buried:
                problems.append(f"{ref} {field} has another question buried in it: {buried!r}")
            if header and header.search(item.get(field) or ""):
                problems.append(f"{ref} {field} still carries the running header")
        for option in options:
            damage = maths_damage(option.get("text") or "")
            if damage:
                problems.append(
                    f"{ref} option {option.get('label')} has flattened maths: {damage!r}")
            buried = embedded_question(option.get("text") or "", own)
            if buried:
                problems.append(
                    f"{ref} option {option.get('label')} has another question "
                    f"buried in it: {buried!r}")

    stats["numbers"] = [n for n in (_own_number(i.get("number")) for i in items)
                        if n is not None]
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
    header_cache: dict[int, re.Pattern | None] = {}
    seen_numbers: dict[str, list[int]] = {}
    total = tagged = bad_files = 0
    try:
        for path in paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            chapter_id = payload.get("chapter_id")
            if chapter_id not in legal_cache:
                legal_cache[chapter_id] = concepts_for(db, chapter_id)
                header_cache[chapter_id] = running_header(db, chapter_id)
            problems, stats = check_file(path, legal_cache[chapter_id],
                                         header_cache.get(chapter_id))
            seen_numbers.setdefault(path.name[:4], []).extend(stats["numbers"])
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
