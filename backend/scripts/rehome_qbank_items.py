"""Move items to the section file the book says they belong to.

    python -m scripts.rehome_qbank_items --chapter 5 \
      --section veryshort=65-94 --section short=95-122 --section long=123-131
    ... add --write to actually move them

The books are set in two columns and the text layer reads a page column by
column, so a section's questions are routinely PRINTED inside a neighbouring
section's character range and parse into the wrong file. In Class 9 Science
chapter 5, very short 77-87 landed in the objective file and short 106-121
landed in the long file; chapter 4 had 25 very short items in the wrong file.

This is not fatal on its own -- the item itself is correct and loads -- but it
mislabels `section_heading` and gives the item the wrong section prefix in
`item_number` (O77 rather than V77), which is the handle `apply_read_concepts`
uses and the only thing a human reading the row has to go on.

Ranges are given explicitly rather than guessed, because only a reader who has
been through the printed text knows where a section really starts and stops.
A number outside every range given is left exactly where it is and reported,
since an unexplained number is more likely to be a parse artefact than a
question in need of moving.

USE THIS ONLY WHERE A READER HAS REPORTED THE MIS-FILING. The printed number
does not always decide the section, and a range will happily overrule a
judgement that was made with the book open. Chapter 4's Q172 is the example:
it is numbered inside the long-answer run but is printed UNDER the case-based
banner, and the reader who found it filed it as case on purpose. A tidy
--section long=126-185 moves it back and silently undoes that.

Nothing is deleted. An item moves from one file to another or it stays put,
and the run refuses to write at all if the total item count changes.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DRAFTS = Path(__file__).resolve().parent / "c9sci_items" / "drafts"


def _number(value: object) -> int | None:
    import re
    digits = re.sub(r"^[A-Za-z]+", "", str(value or "")).split(".")[0]
    return int(digits) if digits.isdigit() else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chapter", type=int, required=True)
    ap.add_argument("--section", action="append", required=True,
                    metavar="SLUG=LOW-HIGH",
                    help="the printed numbers a section owns, e.g. short=95-122")
    ap.add_argument("--write", action="store_true",
                    help="move them; without it this only reports")
    a = ap.parse_args()

    owns: dict[str, range] = {}
    for spec in a.section:
        slug, _, span = spec.partition("=")
        low, _, high = span.partition("-")
        if not (low.isdigit() and high.isdigit()):
            ap.error(f"bad --section {spec!r}, want slug=LOW-HIGH")
        owns[slug] = range(int(low), int(high) + 1)

    files = sorted(DRAFTS.glob(f"ch{a.chapter:02d}_*.json"))
    if not files:
        raise SystemExit(f"no draft files for chapter {a.chapter}")

    payloads = {p: json.loads(p.read_text(encoding="utf-8")) for p in files}
    slug_of = {p: p.stem.split("_", 1)[1] for p in files}
    by_slug = {slug_of[p]: p for p in files}

    moves: dict[tuple[str, str], list[int]] = defaultdict(list)
    unplaced: list[tuple[str, int]] = []
    keep: dict[Path, list[dict]] = {p: [] for p in files}
    incoming: dict[str, list[dict]] = defaultdict(list)

    for path, payload in payloads.items():
        here = slug_of[path]
        for item in payload.get("items") or []:
            number = _number(item.get("number"))
            target = next((s for s, span in owns.items() if number in span), None) \
                if number is not None else None
            if target is None:
                if number is not None and here in owns:
                    unplaced.append((here, number))
                keep[path].append(item)
            elif target == here:
                keep[path].append(item)
            elif target not in by_slug:
                unplaced.append((here, number))
                keep[path].append(item)
            else:
                moves[(here, target)].append(number)
                item = dict(item)
                item["section"] = target
                incoming[target].append(item)

    if not moves:
        print("nothing to move")
    for (here, target), numbers in sorted(moves.items()):
        numbers.sort()
        print(f"  {here:>10} -> {target:<10} {len(numbers):>3} item(s): "
              f"{numbers[:14]}" + (" ..." if len(numbers) > 14 else ""))
    if unplaced:
        print(f"\n  {len(unplaced)} number(s) outside every range given, left where "
              f"they are:")
        for here, number in sorted(set(unplaced))[:20]:
            print(f"      {here} #{number}")

    total_before = sum(len(p.get("items") or []) for p in payloads.values())
    total_after = sum(len(v) for v in keep.values()) + sum(len(v) for v in incoming.values())
    print(f"\n{total_before} item(s) before, {total_after} after")
    if total_before != total_after:
        raise SystemExit("REFUSING: the item count changed, nothing written")

    if not a.write:
        print("report only - re-run with --write")
        return 0

    for path, payload in payloads.items():
        items = keep[path] + incoming.get(slug_of[path], [])
        items.sort(key=lambda i: (_number(i.get("number")) or 0))
        payload["items"] = items
        path.write_text(json.dumps(payload, indent=1, ensure_ascii=False),
                        encoding="utf-8")
    print(f"rewrote {len(payloads)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
