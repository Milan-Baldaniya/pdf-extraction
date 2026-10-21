"""Draft items from a pdf.tube chapter-wise "QB 2026" bank.

    python -m scripts.parse_pdftube_qb --book c7_english
    python -m scripts.parse_pdftube_qb --book c7_english --out scripts/pdftube_items/drafts

These banks are the volume source. Every item is a question, an answer, and an
explanation, and the book states its own chapter on nearly every page:

    CH 2 : EXPLORING SUBSTANCES : ACIDIC, BASIC AND NEUTRAL
    1. What type of substances turn blue litmus paper red?
       (A) Basic  (B) Neutral  (C) Acidic  (D) Salty
       Ans : (C) Acidic substances
       Acidic substances are characterized by ... changing blue litmus to red.

That running `CH n :` header is what makes these tractable where the KVS
English manual was not: chapter comes from the page itself, never from the
last heading seen. `parse_kvs_english` had to carry a heading forward and
misfiled 36% of its items doing so.

BOOK CHAPTER IS NOT DATABASE CHAPTER. Class 7 English prints fifteen literature
texts, but `chapter_master` holds five -- the book's texts are grouped three to
a unit, and the unit is what the database calls a chapter. The mapping is
declared per book in `BOOKS` below and is evidenced by the chapters' own
concept lists, not by position: chapter 2 "Wit and Humour" owns Dr Dolittle,
A Funny Man and Say the Right Thing because its concepts name all three.

WHAT IS SKIPPED. These books open with Comprehension, Writing and Grammar
sections that also number their chapters `CH 1`, `CH 2`... A parser keyed on
the header alone would file "CH 1 MESSAGE WRITING" as literature chapter 1.
Each book therefore declares the page at which its literature section starts,
and everything before it is excluded and reported.

The answer marker differs per book -- `Ans :`, `AAns`, `उत्तर`, `mmÙkj%` -- so
it is declared per book too. One pattern under-counted Class 7 Social Science
by roughly four thousand.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import fitz  # noqa: E402

MIRROR = Path(__file__).resolve().parents[1] / "data" / "qbank" / "mirror" / "pdftube"

# book_chapter -> database chapter_id, plus where the literature section starts.
BOOKS: dict[str, dict] = {
    "c7_english": {
        "file": "c7_English_QB_2026.pdf",
        "standard": 40, "subject": 3978, "from_page": 286,
        "answer": r"\bAns\s*[:.]",
        # Each database chapter is a UNIT of three printed texts.
        "units": {
            25925: ("The Day the River Spoke", [1, 2, 3]),
            25926: ("Wit and Humour", [4, 5, 6]),
            25927: ("My Brother's Great Invention", [7, 8, 9]),
            25928: ("The Tunnel", [10, 11, 12]),
            25929: ("A Homage to Our Brave Soldiers", [13, 14, 15]),
        },
    },
}

HEADER = re.compile(r"(?i)\bCH\s*[-–]?\s*0?(\d{1,2})\s*[:.]")
QSTART = re.compile(r"(?m)^\s*(\d{1,3})\s*[\.\)]\s+(.+)$")
OPTION = re.compile(r"\(([A-D])\)\s*([^()]{1,180}?)(?=\s*\([A-D]\)|\s*$)")


def build(book: str) -> dict:
    cfg = BOOKS[book]
    doc = fitz.open(MIRROR / cfg["file"])
    ans_re = re.compile(cfg["answer"])
    ch_of: dict[int, tuple] = {}
    for cid, (name, printed) in cfg["units"].items():
        for p in printed:
            ch_of[p] = (cid, name)

    items: list[dict] = []
    skipped_before = 0
    no_chapter = 0
    current: tuple | None = None

    for i in range(doc.page_count):
        page_no = i + 1
        try:
            raw = doc[i].get_text()
        except Exception:
            continue
        if page_no < cfg["from_page"]:
            skipped_before += 1
            continue
        m = HEADER.search(" ".join(raw.split()))
        if m:
            printed = int(m.group(1))
            if printed in ch_of:
                current = (ch_of[printed], printed)
        if current is None:
            no_chapter += 1
            continue
        (cid, cname), printed = current

        # Split the page into question blocks on a leading number.
        starts = list(QSTART.finditer(raw))
        for k, s in enumerate(starts):
            end = starts[k + 1].start() if k + 1 < len(starts) else len(raw)
            block = raw[s.start():end]
            a = ans_re.search(block)
            if not a:
                continue
            head = " ".join(block[:a.start()].split())
            tail = " ".join(block[a.end():].split())
            opts = [{"label": o.group(1), "text": o.group(2).strip(" .,")}
                    for o in OPTION.finditer(head)]
            stem = OPTION.sub("", head)
            stem = re.sub(r"^\s*\d{1,3}\s*[\.\)]\s*", "", stem).strip()
            if len(stem) < 12:
                continue
            correct = ""
            cm = re.match(r"\(?([A-D])\)?", tail)
            if cm and opts:
                correct = cm.group(1)
            items.append({
                "page": page_no, "printed_chapter": printed,
                "chapter_id": cid, "chapter": cname,
                "stem": stem, "options": opts,
                "correct_option": correct,
                "answer": tail,
                "form": "mcq" if len(opts) == 4 else "short",
                "concept": "", "needs_reading": True,
            })
    doc.close()

    seen, unique = set(), []
    for it in items:
        k = re.sub(r"[^a-z0-9]", "", it["stem"].lower())[:90]
        if k in seen:
            continue
        seen.add(k)
        unique.append(it)
    return {"book": book, "cfg": cfg, "items": unique,
            "skipped_before": skipped_before, "no_chapter": no_chapter,
            "raw": len(items)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--book", choices=sorted(BOOKS), required=True)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "pdftube_items" / "drafts"))
    a = ap.parse_args()

    r = build(a.book)
    cfg = r["cfg"]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{a.book}.json").write_text(json.dumps(
        {"book": a.book, "source": cfg["file"],
         "source_url": "https://pdf.tube/School/CBSE/",
         "session": "2026-27", "validation_status": "sourced_verbatim",
         "items": r["items"]}, indent=1, ensure_ascii=False), encoding="utf-8")

    mcq = sum(1 for i in r["items"] if i["form"] == "mcq")
    keyed = sum(1 for i in r["items"] if i["correct_option"])
    print(f"{a.book} -- {cfg['file']}\n")
    print(f"  pages before the literature section, skipped   {r['skipped_before']}")
    print(f"  pages after it with no chapter header          {r['no_chapter']}")
    print(f"  items extracted                                {r['raw']}")
    print(f"  after dedup                                    {len(r['items'])}")
    print(f"  of those MCQ with 4 options                    {mcq}")
    print(f"  with a keyed correct option                    {keyed}\n")
    per: dict[str, int] = {}
    for i in r["items"]:
        per[i["chapter"]] = per.get(i["chapter"], 0) + 1
    print(f"  {'database chapter':<42} {'items':>6}")
    print("  " + "-" * 50)
    for cid, (name, _) in cfg["units"].items():
        print(f"  {name[:42]:<42} {per.get(name, 0):>6}")
    print(f"\ndrafts in {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
