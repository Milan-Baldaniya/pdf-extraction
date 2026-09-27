"""Draft item JSON from CBSE's SAS competency PDFs.

    python -m scripts.parse_sas_items --subject science
    python -m scripts.parse_sas_items --all --out scripts/c8sas_items/drafts
    python -m scripts.parse_sas_items --grade 6 --subject maths

Grade 8 is the default because these three books were drafted first; grades 6
and 7 hold Maths only and live in a different mirror directory. The page
layout, the metadata table and the question codes are identical across all
three grades, so only the file registry and the running-head marker differ.

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

_MIRROR_ROOT = Path(__file__).resolve().parents[1] / "data" / "qbank" / "mirror"
MIRROR = _MIRROR_ROOT / "class8"

FILES = {
    "science": "SAS_Science-Class-8.pdf",
    "maths": "SAS_Maths-Class-8.pdf",
    "english": "SAS_English-Class-8.pdf",
}

# grade -> (mirror subdirectory, {subject: file name})
GRADES = {
    6: ("cbse_sas", {"maths": "SAS_Maths-Class-6.pdf"}),
    7: ("cbse_sas", {"maths": "SAS_Maths-Class-7.pdf"}),
    8: ("class8", FILES),
}

# U+1D10 is `f`, not `fi`. See the module docstring.
LIGATURES = {
    "ᴐ": "f", "ϐ": "f",
    "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
    "−": "-",
}

CODE = re.compile(r"\bSAS\d{2}[A-Z]\d{2}[A-Z0-9]{2,10}\b")

# MISPRINTED QUESTION CODES, repaired. The Class 6 Maths book prints five codes
# wrongly, and because the code is the only join between the question half and
# the metadata half, each one loses an item AND corrupts its predecessor: an
# unmatched code is not a boundary, so the orphan's stem and options are
# appended to the item printed above it.
#
# Four are a dropped digit -- `SAS21M6...` for `SAS21M06...`, and `N010` for
# `N0710`. The fifth is not a typo but the wrong code entirely: the third Data
# Handling item is labelled `SAS21S090204`, a Class 9 SCIENCE code. It is
# nonetheless certainly `SAS21M06D0903`: it sits between D0902 and D0904, it
# is printed as item 3, and its four options match that row's `Full Credit`
# of "B. 100". Verified against pages 16, 19, 23, 32 and 37 of the PDF.
MISPRINTED = {
    "SAS21M6N0308": "SAS21M06N0308",
    "SAS21M6S0408": "SAS21M06S0408",
    "SAS21M6S0508": "SAS21M06S0508",
    "SAS21M06N010": "SAS21M06N0710",
    "SAS21S090204": "SAS21M06D0903",
}
# Longest first, and a trailing boundary: `SAS21M06N010` must not be allowed to
# eat the leading twelve characters of a longer, correctly printed code.
_MISPRINT_RE = re.compile(
    "(?:%s)\\b" % "|".join(re.escape(k) for k in sorted(MISPRINTED, key=len, reverse=True)))
OPTION = re.compile(r"^([A-D])[\.\)]\s*(.+)$", re.S)
RULE = re.compile(r"^_{5,}$")

# PAGE FURNITURE, dropped wherever it lands. The running head and the chapter
# divider page both sit on pages that carry questions in reading order, so
# without this the words "Class 6 - Chapter 2" appear inside a stem.
FURNITURE = re.compile(
    r"^(?:Mathematics|Science|English"
    r"|Class\s*\d+\s*[-‐-―]\s*Chapter\s*\d+"
    r"|CENTRAL BOARD OF SECONDARY EDUCATION.*"
    r"|Page\s*\d{1,3}"
    r"|Note:.{0,4})$")

# A CHAPTER DIVIDER PAGE. Its banner is the only reliable chapter boundary in
# the question half, and a boundary is what stops a shared stimulus from being
# carried across into the next chapter's first item.
DIVIDER = "CENTRAL BOARD OF SECONDARY EDUCATION"
BREAK = "\x00BREAK"

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


def read_blocks(doc, grade: int = 8) -> list[tuple[str, str]]:
    """The question half as a flat event list of ('code'|'text'|'break', value).

    A 'break' is a chapter divider page. Blocks are emitted in printed reading
    order, which is what lets a shared stimulus be attributed to the item it
    introduces rather than to the item printed above it.
    """
    seq: list[tuple[str, str]] = []
    for page in doc:
        text = page.get_text()
        if _is_meta_page(text) or f"Class {grade}" not in text:
            continue
        if DIVIDER in text:
            seq.append(("break", ""))
        # (y, x) with y bucketed: a row of option boxes shares a baseline but
        # is emitted in arbitrary order, and bucketing keeps them left-to-right.
        for block in sorted(page.get_text("blocks"), key=lambda r: (round(r[1] / 5), r[0])):
            s = fix(" ".join(block[4].split()))
            if not s or s.startswith("Curriculum Aligned") or "Copyright (c) 2021" in s:
                continue
            s = _MISPRINT_RE.sub(lambda m: MISPRINTED[m.group(0)], s)
            m = CODE.search(s)
            if m:
                seq.append(("code", m.group(0)))
                rest = CODE.sub("", s).strip()
                if rest:
                    seq.append(("text", rest))
            elif FURNITURE.match(s):
                continue
            else:
                seq.append(("text", s))
    return seq


def parse_questions(doc, grade: int = 8) -> dict[str, list[str]]:
    """code -> the printed blocks that follow it, in reading order."""
    out: dict[str, list[str]] = {}
    cur = None
    for kind, value in read_blocks(doc, grade):
        if kind == "code":
            cur = value
            out.setdefault(cur, [])
        elif kind == "text" and cur:
            out[cur].append(value)
    return out


def split_item(blocks: list[str]) -> tuple[list[str], list[dict], list[str]]:
    """One item's blocks -> (stem parts, options, trailing).

    TRAILING IS THE NEXT ITEM'S STIMULUS, not this item's text. CBSE prints a
    shared scenario -- a table, a passage, a price list -- above the first item
    that uses it, so in reading order it falls between the previous item's
    answer space and the next item's code. Appending it to the stem, as this
    function used to, produced stems that ran two unrelated questions together
    and left the item that actually needs the scenario without it.

    The boundary is the end of this item's own answer area: the ruled blanks of
    a constructed response, or the fourth option of an MCQ. Nothing legitimate
    follows either.
    """
    stem_parts: list[str] = []
    options: list[dict] = []
    trailing: list[str] = []
    closed = False
    for b in blocks:
        if b == BREAK:
            # A chapter divider fell inside this item's trailing text. Whatever
            # precedes it closed the old chapter; whatever follows introduces
            # the new one, so the trailing to hand on starts again here.
            closed, trailing = True, []
            continue
        if not b.strip("_ "):
            # The ruled answer space. For a constructed response it closes the
            # item; before the stem it is the previous item's, so ignore it.
            if stem_parts and not options:
                closed = True
            continue
        if closed or len(options) >= 4:
            trailing.append(b)
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
    return stem_parts, options, trailing


def shape(code: str, blocks: list[str], meta: dict, grade: int = 8,
          context: str = "") -> dict:
    stem_parts, options, trailing = split_item(blocks)
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
        "context": context,
        "context_own": False,
        "options": options,
        "answer": meta.get("answer", ""),
        "form": form,
        "chapter_label": (meta.get("chapter") or "").replace(f"Grade {grade} |", "").strip(),
        "concept_label": meta.get("concept", ""),
        "competency": meta.get("competency", ""),
        "item_type": meta.get("item_type", ""),
        "no_credit": meta.get("no_credit", ""),
        "trailing": " ".join(trailing).strip(),
        "needs_reading": True,
    }


def assemble(doc, meta: dict[str, dict], grade: int = 8) -> tuple[list[dict], list[str]]:
    """Walk the question half in printed order, carrying the stimulus forward.

    A scenario introduced above one item usually serves the two to five items
    that follow it, and only the first of them is printed next to it. Carrying
    it forward until the next scenario or the next chapter divider is therefore
    closer to what the child sees on the page than dropping it would be. It can
    over-supply context; it cannot leave an item unanswerable, which is the
    failure that matters.
    """
    order: list[tuple[str, list[str]]] = []
    cur: list[str] | None = None
    for kind, value in read_blocks(doc, grade):
        if kind == "break":
            if cur is not None:
                cur.append(BREAK)
        elif kind == "code":
            cur = []
            order.append((value, cur))
        elif cur is not None:
            cur.append(value)

    items, orphan_q, stimulus = [], [], ""
    for code, blocks in order:
        if code not in meta:
            orphan_q.append(code)
            continue
        item = shape(code, blocks, meta[code], grade, context=stimulus)
        if item["trailing"]:
            # This item introduced the scenario itself, so the next items in the
            # cluster inherit it rather than the one before.
            stimulus = item["trailing"]
            item["context_own"] = True
        items.append(item)
    return items, orphan_q


def run(subject: str, out_dir: Path, grade: int = 8) -> dict:
    sub_dir, files = GRADES[grade]
    path = _MIRROR_ROOT / sub_dir / files[subject]
    doc = fitz.open(path)
    meta = parse_metadata(doc)
    ques = parse_questions(doc, grade)
    items, orphan_q = assemble(doc, meta, grade)
    doc.close()

    orphan_m = [code for code in meta if code not in ques]

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"c{grade}_{subject}_sas.json").write_text(
        json.dumps({"subject": subject, "grade": grade, "source": files[subject],
                    "items": items}, indent=1, ensure_ascii=False), encoding="utf-8")

    empty = sum(1 for i in items if not i["stem"])
    noans = sum(1 for i in items if not i["answer"])
    return {"subject": subject, "meta": len(meta), "questions": len(ques),
            "paired": len(items), "no_stem": empty, "no_answer": noans,
            "q_without_meta": len(orphan_q), "meta_without_q": len(orphan_m)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--grade", type=int, default=8, choices=sorted(GRADES))
    ap.add_argument("--subject", choices=sorted(FILES))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "c8sas_items" / "drafts"))
    a = ap.parse_args()
    available = GRADES[a.grade][1]
    subjects = sorted(available) if a.all else ([a.subject] if a.subject else [])
    if not subjects:
        ap.error("give --subject NAME or --all")
    for s in subjects:
        if s not in available:
            ap.error(f"grade {a.grade} has no {s} book; it holds {sorted(available)}")

    print(f"{'subject':<10} {'meta':>5} {'quest':>6} {'paired':>7} {'no stem':>8} "
          f"{'no answer':>10} {'q w/o meta':>11} {'meta w/o q':>11}")
    print("-" * 76)
    for s in subjects:
        r = run(s, Path(a.out), a.grade)
        print(f"{r['subject']:<10} {r['meta']:>5} {r['questions']:>6} {r['paired']:>7} "
              f"{r['no_stem']:>8} {r['no_answer']:>10} {r['q_without_meta']:>11} "
              f"{r['meta_without_q']:>11}")
    print(f"\ndrafts in {a.out}")
    print("EVERY ITEM STILL NEEDS READING against the PDF before it loads -- the "
          "parser cannot fix fragmented fractions or a figure that moved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
