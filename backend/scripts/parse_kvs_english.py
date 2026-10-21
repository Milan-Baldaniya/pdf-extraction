"""Draft items from the KVS RO Jabalpur Class 9/10 English competency manuals.

    python -m scripts.parse_kvs_english --class 9
    python -m scripts.parse_kvs_english --class 9 --out scripts/c9eng_items/drafts

Source: `rojabalpur.kvs.gov.in/en/study-material/`, session 2026-27, Tier C
under the ingestion prompt's hierarchy. Verified reachable and downloaded to
`data/qbank/mirror/kvs_jabalpur/` on 2026-09-25.

WHY THIS SOURCE FITS WHERE OTHERS DID NOT. KVS built the 2026-27 manual on the
CURRENT curriculum, so its lessons are the same eight the database holds --
"How I Taught My Grandmother to Read", "The Pot Maker", "Vitamin-M". Class 9
Science material sourced for "Matter in Our Surroundings" had no chapter to
land in because Class 9 moved to the new books; this does not have that
problem, and the check was run before any parsing. Do that check first, every
time.

TWO ANSWER LAYOUTS, and a parser that knows only one silently drops half the
bank:

  * `Q1. <stem>` then `Answer: <text>` -- one answer per question, inline.
  * A passage, then questions numbered `i. ii. iii.` each with a marks digit,
    then a single `Answer Key` block whose answers are keyed by the same roman
    numerals. The key sits immediately after the questions, NOT in a
    consolidated key at the back, so it has to be read per extract.

`Answer Key` is also a heading elsewhere in the document, so the roman-numeral
pairing is what binds an answer to its question, never proximity alone.

WHAT THIS DOES NOT DO. It drafts. Concept assignment is left empty on purpose:
the chapter's 98 concepts include grammar and writing-skill concepts
("Noun Clauses", "Diary Entry") alongside content ones, and choosing between
them is a reading judgement, not a string match. Unsolved items come out with
an empty answer and are reported, not silently counted -- the quality gate in
the ingestion prompt requires a non-empty answer, so they do not pass.
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
from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

MIRROR = Path(__file__).resolve().parents[1] / "data" / "qbank" / "mirror" / "kvs_jabalpur"
FILES = {9: ("c9_english_cbq.pdf", 42, 3978), 10: ("c10_english_cbq.pdf", 43, 3978)}

SECTION = re.compile(r"(?i)\b(LITERATURE|GRAMMAR|WRITING|READING|LISTENING)\s+SECTION\b")
QNUM = re.compile(r"(?m)^\s*Q\.?\s*(\d{1,3})[\.\)]\s*(.+)$")
ANSWER = re.compile(r"(?i)\bAnswers?\s*[:\-]\s*")
KEYHEAD = re.compile(r"(?i)\bAnswer\s*Key\b")
ROMAN = re.compile(r"(?m)^\s*\(?([ivx]{1,5})\)?[\.\)]\s*(.+)$", re.I)
OPTION = re.compile(r"(?m)^\s*\(?([A-D])\)?[\.\)]\s+(.+)$")
MARKS = re.compile(r"\s+([1-5])\s*$")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def chapters(standard: int, subject: int) -> list[tuple[int, int, str]]:
    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        return [(int(r[0]), int(r[1]), r[2]) for r in db.execute(
            text("SELECT id, sort_order, chapter_name FROM chapter_master "
                 " WHERE standard_id = :s AND subject_id = :j ORDER BY sort_order"),
            {"s": standard, "j": subject}).fetchall()]
    finally:
        db.close()


def page_chapter(page_text: str, chs: list[tuple[int, int, str]]) -> tuple | None:
    """The lesson a page belongs to, by its heading -- longest name first.

    Longest-first matters: a page naming both a lesson and a cross-reference
    would otherwise bind to whichever the loop reached first.
    """
    key = norm(page_text)
    best = None
    for cid, so, nm in chs:
        n = norm(nm)
        if len(n) >= 10 and n[:24] in key:
            if best is None or len(n) > len(best[2]):
                best = (cid, so, nm)
    return best


def solved_pairs(block: str) -> list[dict]:
    """`Q1. stem` / `Answer: text` pairs inside one page."""
    out = []
    marks = list(QNUM.finditer(block))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(block)
        chunk = block[m.start():end]
        parts = ANSWER.split(chunk, maxsplit=1)
        stem = " ".join(parts[0].split())
        stem = re.sub(r"^Q\.?\s*\d{1,3}[\.\)]\s*", "", stem).strip()
        ans = " ".join(parts[1].split()) if len(parts) > 1 else ""
        opts = [{"label": o.group(1), "text": " ".join(o.group(2).split())}
                for o in OPTION.finditer(parts[0])]
        if opts:
            stem = OPTION.sub("", parts[0])
            stem = re.sub(r"^\s*Q\.?\s*\d{1,3}[\.\)]\s*", "", " ".join(stem.split())).strip()
        if len(stem) < 12:
            continue
        out.append({"number": m.group(1), "stem": stem, "options": opts,
                    "answer": ans, "layout": "Q/Answer"})
    return out


def keyed_extract(block: str) -> list[dict]:
    """Roman-numbered questions bound to a trailing `Answer Key` by numeral."""
    k = KEYHEAD.search(block)
    if not k:
        return []
    body, key = block[:k.start()], block[k.end():]
    answers = {m.group(1).lower(): " ".join(m.group(2).split())
               for m in ROMAN.finditer(key)}
    if not answers:
        return []
    out = []
    qs = list(ROMAN.finditer(body))
    for i, m in enumerate(qs):
        end = qs[i + 1].start() if i + 1 < len(qs) else len(body)
        chunk = body[m.start():end]
        num = m.group(1).lower()
        raw = " ".join(chunk.split())
        raw = re.sub(r"^\(?[ivx]{1,5}\)?[\.\)]\s*", "", raw, flags=re.I)
        mk = MARKS.search(raw)
        marks = int(mk.group(1)) if mk else None
        if mk:
            raw = raw[:mk.start()].strip()
        opts = [{"label": o.group(1), "text": " ".join(o.group(2).split())}
                for o in OPTION.finditer(chunk)]
        if opts:
            raw = re.sub(r"\s*\(?[A-D]\)?[\.\)]\s+.+$", "", raw).strip()
        if len(raw) < 12:
            continue
        out.append({"number": num, "stem": raw, "options": opts,
                    "answer": answers.get(num, ""), "marks": marks,
                    "layout": "keyed-extract"})
    return out


def run(klass: int, out_dir: Path) -> dict:
    fname, standard, subject = FILES[klass]
    chs = chapters(standard, subject)
    doc = fitz.open(MIRROR / fname)

    items: list[dict] = []
    current = None
    section = ""
    for i in range(doc.page_count):
        t = doc[i].get_text()
        s = SECTION.search(t)
        if s:
            section = s.group(1).title() + " Section"
        hit = page_chapter(t, chs)
        if hit:
            current = hit
        if current is None:
            continue
        found = keyed_extract(t) or solved_pairs(t)
        for it in found:
            it.update({"page": i + 1, "chapter_id": current[0],
                       "chapter": current[2], "section_heading": section,
                       "concept": "", "needs_reading": True})
            items.append(it)
    doc.close()

    # Same stem twice is the same question printed in two places, not two items.
    seen, unique = set(), []
    for it in items:
        k = norm(it["stem"])[:90]
        if k in seen:
            continue
        seen.add(k)
        unique.append(it)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"c{klass}_english_kvs.json").write_text(
        json.dumps({"class": klass, "source": fname,
                    "source_url": "https://rojabalpur.kvs.gov.in/en/study-material/",
                    "source_tier": "C", "session": "2026-27",
                    "validation_status": "sourced_verbatim",
                    "items": unique}, indent=1, ensure_ascii=False), encoding="utf-8")

    answered = [i for i in unique if i["answer"]]
    by_ch: dict[str, int] = {}
    for i in answered:
        by_ch[i["chapter"]] = by_ch.get(i["chapter"], 0) + 1
    return {"raw": len(items), "unique": len(unique), "answered": len(answered),
            "by_chapter": by_ch, "chapters": chs}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--class", dest="klass", type=int, choices=sorted(FILES), required=True)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "kvs_eng_items" / "drafts"))
    a = ap.parse_args()

    r = run(a.klass, Path(a.out))
    print(f"Class {a.klass} English -- KVS RO Jabalpur, session 2026-27, Tier C\n")
    print(f"  extracted           {r['raw']}")
    print(f"  after dedup         {r['unique']}")
    print(f"  WITH an answer      {r['answered']}   <- only these pass the quality gate")
    print(f"  without an answer   {r['unique'] - r['answered']}   (unsolved sections)\n")
    print(f"  {'chapter':<46} {'answered':>8}")
    print("  " + "-" * 56)
    for _, so, nm in r["chapters"]:
        print(f"  ch{so:<2} {nm[:42]:<42} {r['by_chapter'].get(nm, 0):>8}")
    print(f"\ndrafts in {a.out}")
    print("Concept is left EMPTY on every item: the chapter's concepts mix content, "
          "grammar and writing skills, and choosing between them is a reading "
          "judgement. Every item still needs reading against the PDF before load.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
