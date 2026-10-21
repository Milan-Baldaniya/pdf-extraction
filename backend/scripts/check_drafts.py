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
KNOWN_GAPS = Path(__file__).resolve().parents[1] / "data" / "qbank" / "known_gaps.json"
BLOOM = {"recall", "understand", "apply", "analyze", "evaluate", "create"}

# Page furniture that has turned up bled into a stem or an answer, sometimes
# spliced mid-sentence. Any of these surviving means the item was not cleaned.
# The publisher's own strings can be matched case-insensitively; they do not
# occur in ordinary prose.
JUNK = re.compile(
    r"Click Here to Buy|Downloaded from|www\.pdf\.tube|NODIA|lympiad"
    r"|Chapterwise QB|Previous Year Solved|Order the Hard copy",
    re.I,
)

# The section banners are a different matter and must stay CASE SENSITIVE and
# anchored on the whole banner. Matching "VER Y SHO RT" case-insensitively also
# matches the perfectly ordinary phrase "in a very short time of 0.01 s", and a
# reader hit exactly that: to get a clean check they changed the book's "short"
# to "brief" and flagged the item as rephrased. The checker made the text less
# faithful, which is the opposite of its job. The banners are set in capitals
# with the letter-spacing the text layer leaves behind, so requiring the case
# and the trailing word costs nothing and removes the collision.
BANNER = re.compile(
    r"OBJECTIVE\s+QUESTION|VER\s*Y\s+SHO\s*RT\s+ANSWER|SSHOR\s*T\s+ANSWER"
    r"|CAS\s*E\s+BASED|LON\s*G\s+Answer|NCER\s*T\s+Exercis|PAUS\s*E\s+A\s*ND"
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
    # Two or more bare single letters before an equals, e.g. "v u at =".
    # The letters must be STANDALONE, hence the lookarounds. Without them
    # this also matched "the equation F = ma", because the final "n" of
    # "equation" counts as one of the single letters, so no draft could
    # carry that phrase and report ok. Readers worked around it by
    # parenthesising the book's own formula and marking the item
    # rephrased, putting false provenance on text nobody had touched.
    # The separators must be spaces or tabs, NOT newlines. A correctly
    # formatted worked solution puts each step on its own line, so a line
    # ending in a variable is followed by a line beginning with it --
    #     0 = 625 - s
    #     s = 625 m.
    # -- which is two standalone letters before an equals and nothing wrong
    # at all. Eight of chapter 4's long answers look exactly like that.
    re.compile(r"(?:(?<![A-Za-z])[a-zA-Z](?![A-Za-z])[ \t]+){2,}[a-zA-Z]*[ \t]*="),
    # a run of lone digits before an equals, e.g. "s ut at 2 1 2 ="
    re.compile(r"(?:(?<!\d)\d(?!\d)[ \t]+){2,}\d*[ \t]*="),
    # Column-collapsed equations DO arrive newline-separated, so they need
    # their own shape: consecutive lines each holding one bare character, as
    # in "E / T / = / and L / w / T / 2 / + / =" where each of those is its
    # own line. A formatted solution never has a line containing just "s",
    # so this cannot collide with one.
    re.compile(r"(?:^[ \t]*[A-Za-z0-9][ \t]*$\r?\n){2,}", re.M),
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
    # A numbered sub-part list. Requiring it to start at 1 or 2 and ascend by
    # exactly one was too brittle: the regex needs a capitalised sentence of
    # 25+ characters, so a short sub-part is skipped and the run reads as
    # [1, 3] rather than [1, 2, 3]. Six correct items tripped on that. What
    # actually separates the two is size -- sub-parts in these books run to
    # about six and never past eight, while a buried question carries the
    # book's own sequence number, in the dozens or hundreds.
    #
    # A real burial numbered eight or under is therefore missed here. That is
    # deliberate rather than overlooked: it still shows up as a hole in the
    # chapter-wide numbering check, which is the other half of this pair.
    # Nor can the run be required to ascend. One answer carries two separate
    # lists -- "Comparison: 1. 2. 3." then "Situations for preference: 1. 2.
    # 3." -- so the numbers read [2, 3, 2, 3]. Size is doing all the work, and
    # the ascending test only added a way to be wrong.
    if all(n <= 8 for n in numbers):
        return None
    # The buried number is NOT required to run ahead of its host. Requiring
    # that was how chapter 7's Q96 got through: its whole stem was appended to
    # Q113's stem and its answer had overwritten Q113's answer field, so Q96
    # existed nowhere, and 96 < 113 so nothing fired. The sub-part list above
    # is what separates a real burial from a numbered list; the direction of
    # the number never was.
    for hit, number in zip(hits, numbers):
        if number != own:
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

    The match is CASE SENSITIVE, for the same reason the banners above are. The
    running header is set in title case on every page, but a chapter's title is
    made of ordinary words and the book writes them in ordinary prose too:
    chapter 9's objective Q58 opens "Based on the comprehensive study of the
    atomic foundations of matter, identify ..." -- the book's own sentence, in
    lower case, which a case-insensitive pattern reports as bled furniture. In
    chapter 9's source the title appears 24 times as the header and once like
    that, so requiring the case loses nothing and stops the check from pushing
    a reader into editing the book's text to silence it.
    """
    name = db.execute(
        text("SELECT chapter_name FROM chapter_master WHERE id = :c"),
        {"c": chapter_id},
    ).scalar()
    if not name or len(name.split()) < 3:
        return None
    # Tolerate the whitespace the text layer inserts between words.
    return re.compile(r"\s+".join(re.escape(w) for w in name.split()))


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
    per_file: dict[str, list[int]] = {}
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
            per_file[path.name] = stats["numbers"]
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

    # A hole in the printed numbering means a question reached no file at all,
    # which is what happens when one is buried inside a neighbouring item. It
    # is invisible otherwise: every file it should have been in is individually
    # valid without it. Chapter 5's Q76 was buried inside objective Q35's
    # option C with its answer overwriting Q35's, and nothing else noticed.
    #
    # A chapter is not one numbering run and it is not one run per file: it is
    # several. Both chapter 4 and chapter 5 restart at 1 in Pause and Ponder,
    # again in the reprinted NCERT exercise, and then number the objective
    # block onward straight through to the end. Checking the chapter whole
    # hides every hole, because the restarts cover the low numbers. Checking
    # file by file invents holes, because those later sections are one run
    # between them -- ch04_long holds 126-171 and 173-185 while ch04_case holds
    # 172, and neither file is missing anything.
    #
    # So the files are walked in order of their lowest number and merged into a
    # run while each one starts above where the last left off. A file that
    # starts back inside the previous run begins a new one.
    try:
        known = json.loads(KNOWN_GAPS.read_text(encoding="utf-8"))
    except Exception:
        known = {}

    # A number that known_gaps explains is left out of the grouping entirely.
    # Chapter 4's Q172 is filed in ch04_case because that is where the book
    # prints it, which drags that file's lowest number down from 186 to 172 and
    # splits the run in two -- and then 173-185 look missing from the case file
    # although they are all present in ch04_long. Excluding an explained number
    # from the grouping, not just from the report, keeps one recorded oddity
    # from manufacturing a second one.
    runs: dict[str, list[int]] = {}
    for chapter in sorted(seen_numbers):
        skip = {int(k) for k in known.get(chapter, {}) if k.isdigit()}
        files = sorted((( min(rest), max(rest), name, rest)
                        for name, n in per_file.items()
                        if name.startswith(chapter)
                        and (rest := [x for x in n if x not in skip])),
                       key=lambda f: (f[0], f[1]))
        current: list[int] = []
        names: list[str] = []
        for low, high, name, numbers in files:
            if current and low <= max(current):
                runs[f"{chapter} {' + '.join(names)}"] = current
                current, names = [], []
            current.extend(numbers)
            names.append(name.replace(f"{chapter}_", "").replace(".json", ""))
        if current:
            runs[f"{chapter} {' + '.join(names)}"] = current

    gaps = 0
    for name, numbers in sorted(runs.items()):
        if len(numbers) < 3:
            continue
        low, high = min(numbers), max(numbers)
        missing = sorted(set(range(low, high + 1)) - set(numbers))
        if not missing:
            continue
        explained = {**known.get(name[:4], {}), **known.get(name.split()[0], {})}
        for number in missing:
            if str(number) in explained:
                print(f"\n{name}: #{number} is absent from the book, not lost:")
                print(f"      {explained[str(number)][:400]}")
        unexplained = [n for n in missing if str(n) not in explained]
        if unexplained:
            gaps += 1
            print(f"\n{name}: {len(unexplained)} number(s) missing between {low} "
                  f"and {high}: {unexplained[:15]}"
                  + (" ..." if len(unexplained) > 15 else ""))
            print("      a question in no file at all is usually buried inside a "
                  "neighbouring item's option or answer. If you check the source "
                  "and it truly is not there, record it in "
                  "data/qbank/known_gaps.json with the evidence.")

    print(f"\n{total} item(s), {tagged} fully tagged, {bad_files} file(s) with problems"
          + (f", {gaps} numbering gap(s)" if gaps else ""))
    return 1 if (bad_files or gaps) else 0


if __name__ == "__main__":
    raise SystemExit(main())
