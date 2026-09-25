"""Draft item JSON from CBSE's SAS competency PDFs for Class 8.

    python -m scripts.parse_sas_items --subject science
    python -m scripts.parse_sas_items --all --out scripts/c8sas_items/drafts

Each SAS PDF is two halves, not interleaved: the question pages come first,
then a metadata table. They join on a question code that appears in both
(`SAS21S080101`). The metadata half is the valuable part -- CBSE states the
chapter, the concept and sub-concept, the competency, the item type and the
answer, so none of that has to be inferred here.

WHAT THIS DOES NOT DO. It drafts; it does not verify. A reader still has to
check every item against the PDF before it loads, for two reasons this parser
cannot fix:

  * The question half reads in layout order, so on an MCQ page the options can
    precede the stem they belong to. Sorting blocks by (y, x) recovers the
    printed order, but a figure or a two-column table still lands wherever its
    box sits.
  * Mathematical notation fragments. A fraction prints as three separate
    blocks -- "A. -5 ," / "3 , 7" / "2" -- and reassembling those from the text
    layer is guesswork. Maths items with fractions come out wrong more often
    than they come out right; see the `qbank-text-layer-flattens-fractions`
    note. Science and English are far cleaner.

LIGATURES. These PDFs encode `fi`/`ff` through private glyphs, and `U+1D10`
renders as `f`, NOT as `fi` -- "Scientiϐic" is "Scientific", so mapping it to
"fi" yields "Scientifiic". That was wrong in the first draft of this file and
is the kind of error that reads as a typo in the bank forever.

CHAPTER NAMES differ from `chapter_master` by a plural often enough to matter:
SAS writes "Exponents and Power", "Direct and Inverse Proportion" and
"Introduction to Graph" where the database has all three in the plural.
Matching is therefore on a normalised key (alphanumeric, lowercased), which
also absorbs the curly-vs-straight apostrophe in "Bepin Choudhury's".
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

MIRROR = Path(__file__).resolve().parents[1] / "data" / "qbank" / "mirror" / "class8"

FILES = {
    "science": "SAS_Science-Class-8.pdf",
    "maths": "SAS_Maths-Class-8.pdf",
    "english": "SAS_English-Class-8.pdf",
}

# U+1D10 is `f`, not `fi`. See the module docstring.
LIGATURES = {
    "ᴐ": "f", "ϐ": "f",
    "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
    "−": "-",
}

CODE = re.compile(r"\bSAS\d{2}[A-Z]\d{2}[A-Z0-9]{2,10}\b")
OPTION = re.compile(r"^([A-D])[\.\)]\s*(.+)$", re.S)
RULE = re.compile(r"^_{5,}$")

# CBSE's own label differs by subject: Maths says "Chapter", Science and
# English say "Unit", and English swaps Concept for Theme. A parser keyed on
# only the Maths spelling silently returns no chapter for 356 of 519 items.
KEYS = {
    "Question Code": "code",
    "Grade & Chapter Name": "chapter",
    "Grade & Unit Name": "chapter",
    "Concept | Sub-concept": "concept",
    "Theme | Sub -Theme": "concept",
    "Theme | Sub-Theme": "concept",
    "Competency": "competency",
    "Item Type": "item_type",
    "Full Credit (Full Score)": "answer",
    "Partial Credit (Partial Score)": "partial",
    "No Credit (No Score)": "no_credit",
    "Item Number": "_num",
}


def fix(s: str) -> str:
    for a, b in LIGATURES.items():
        s = s.replace(a, b)
    return s


def _is_meta_page(text: str) -> bool:
    return "Question Code" in text


def parse_metadata(doc) -> dict[str, dict]:
    blob = fix("\n".join(p.get_text() for p in doc if _is_meta_page(p.get_text())))
    lines = [l.strip() for l in blob.split("\n")]
    items: list[dict] = []
    cur: dict | None = None
    i = 0
    while i < len(lines):
        if lines[i] in KEYS:
            key = KEYS[lines[i]]
            vals, j = [], i + 1
            while j < len(lines) and lines[j] not in KEYS:
                if lines[j]:
                    vals.append(lines[j])
                j += 1
            if key == "_num":
                if cur:
                    items.append(cur)
                cur = {}
            elif cur is not None:
                cur[key] = " ".join(vals).strip()
            i = j
        else:
            i += 1
    if cur:
        items.append(cur)
    return {x["code"]: x for x in items if x.get("code")}


def parse_questions(doc) -> dict[str, list[str]]:
    """code -> the printed blocks that follow it, in reading order."""
    seq: list[str] = []
    for page in doc:
        text = page.get_text()
        if _is_meta_page(text) or "Class 8" not in text:
            continue
        # (y, x) with y bucketed: a row of option boxes shares a baseline but
        # is emitted in arbitrary order, and bucketing keeps them left-to-right.
        for block in sorted(page.get_text("blocks"), key=lambda r: (round(r[1] / 5), r[0])):
            s = fix(" ".join(block[4].split()))
            if not s or s.startswith("Curriculum Aligned") or "Copyright (c) 2021" in s:
                continue
            seq.append(s)
    out: dict[str, list[str]] = {}
    cur = None
    for s in seq:
        m = CODE.search(s)
        if m:
            cur = m.group(0)
            out.setdefault(cur, [])
            rest = CODE.sub("", s).strip()
            if rest:
                out[cur].append(rest)
        elif cur:
            out[cur].append(s)
    return out


def shape(code: str, blocks: list[str], meta: dict) -> dict:
    stem_parts: list[str] = []
    options: list[dict] = []
    for b in blocks:
        if RULE.match(b) or not b.strip("_ "):
            continue
        # A leading bare number is the printed item number, not content.
        if not stem_parts and not options and re.fullmatch(r"\d{1,3}", b):
            continue
        m = OPTION.match(b)
        if m and len(m.group(2)) < 220:
            options.append({"label": m.group(1), "text": m.group(2).strip()})
        elif options:
            # Text after the options began is usually a wrapped option line.
            options[-1]["text"] = (options[-1]["text"] + " " + b).strip()
        else:
            stem_parts.append(b)
    stem = " ".join(stem_parts).strip()
    stem = re.sub(r"\s*_{5,}\s*", " ", stem).strip()
    form = "mcq" if len(options) == 4 else "short"
    itype = (meta.get("item_type") or "").lower()
    if "multiple choice" in itype and len(options) == 4:
        form = "mcq"
    elif "constructed response" in itype:
        form = "short"
    return {
        "code": code,
        "stem": stem,
        "options": options,
        "answer": meta.get("answer", ""),
        "form": form,
        "chapter_label": (meta.get("chapter") or "").replace("Grade 8 |", "").strip(),
        "concept_label": meta.get("concept", ""),
        "competency": meta.get("competency", ""),
        "item_type": meta.get("item_type", ""),
        "no_credit": meta.get("no_credit", ""),
        "needs_reading": True,
    }


def run(subject: str, out_dir: Path) -> dict:
    path = MIRROR / FILES[subject]
    doc = fitz.open(path)
    meta = parse_metadata(doc)
    ques = parse_questions(doc)
    doc.close()

    items, orphan_q, orphan_m = [], [], []
    for code, blocks in ques.items():
        if code not in meta:
            orphan_q.append(code)
            continue
        items.append(shape(code, blocks, meta[code]))
    for code in meta:
        if code not in ques:
            orphan_m.append(code)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"c8_{subject}_sas.json").write_text(
        json.dumps({"subject": subject, "source": FILES[subject], "items": items},
                   indent=1, ensure_ascii=False), encoding="utf-8")

    empty = sum(1 for i in items if not i["stem"])
    noans = sum(1 for i in items if not i["answer"])
    return {"subject": subject, "meta": len(meta), "questions": len(ques),
            "paired": len(items), "no_stem": empty, "no_answer": noans,
            "q_without_meta": len(orphan_q), "meta_without_q": len(orphan_m)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--subject", choices=sorted(FILES))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "c8sas_items" / "drafts"))
    a = ap.parse_args()
    subjects = sorted(FILES) if a.all else ([a.subject] if a.subject else [])
    if not subjects:
        ap.error("give --subject NAME or --all")

    print(f"{'subject':<10} {'meta':>5} {'quest':>6} {'paired':>7} {'no stem':>8} "
          f"{'no answer':>10} {'q w/o meta':>11} {'meta w/o q':>11}")
    print("-" * 76)
    for s in subjects:
        r = run(s, Path(a.out))
        print(f"{r['subject']:<10} {r['meta']:>5} {r['questions']:>6} {r['paired']:>7} "
              f"{r['no_stem']:>8} {r['no_answer']:>10} {r['q_without_meta']:>11} "
              f"{r['meta_without_q']:>11}")
    print(f"\ndrafts in {a.out}")
    print("EVERY ITEM STILL NEEDS READING against the PDF before it loads -- the "
          "parser cannot fix fragmented fractions or a figure that moved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
