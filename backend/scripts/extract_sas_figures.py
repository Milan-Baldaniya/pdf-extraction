"""Render the shared stimulus figure of a CBSE SAS item cluster to a PNG.

    python -m scripts.extract_sas_figures --grade 6 --chapter "Data Handling"
    python -m scripts.extract_sas_figures --grade 7 --chapter "Lines and Angles" --apply

WHY THIS EXISTS. Over half of the SAS items -- 162 of 290 across the two books --
cannot be answered from the text layer because the numbers a learner needs are
inside a bar graph, a pictograph or a labelled diagram. Two chapters sit at zero
for that reason alone: Class 6 Data Handling and Presentation and Class 7
Parallel and Intersecting Lines, both of which map onto their NEP chapter exactly.
This renders the figure so those items can be loaded with it.

WHAT A "CLUSTER" IS. CBSE prints one scenario -- a graph and its introduction --
above a run of two to six items that all refer to it, and the run can carry on
over a page break. So the figure belongs to the CLUSTER, not to one item, and
every item in the cluster gets the same image.

HOW THE BAND IS FOUND. Between one item's content and the next item's question
code there is either nothing, in which case the item continues the cluster above
it, or a run of blocks, in which case those blocks are a new scenario and the
figure sits among them. The band runs from the top of that first scenario block
to the top of the following item's own left-margin text, which is where the
figure stops and the question starts. Nothing is inferred from pixel content.

WHY A RENDER AND NOT THE EMBEDDED IMAGE. Half these figures are vector drawings
-- the Class 7 angle diagrams are 81 line segments, not a picture -- so
`get_images()` returns either nothing or the decorative border. Rasterising the
band captures drawing, image and label together, exactly as the page prints it.

EVERY CROP MUST BE LOOKED AT. This writes PNGs and a manifest; it does not
decide that a crop is good. A figure cropped short is worse than a missing one,
because the item then looks complete.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import fitz  # noqa: E402

from scripts.parse_sas_items import (  # noqa: E402
    CODE, DIVIDER, FURNITURE, GRADES, MISPRINTED, OPTION, _MIRROR_ROOT,
    _MISPRINT_RE,
    fix, parse_metadata,
)

# Where publish_question_figures looks for the local file: backend/output/<rel>.
OUTPUT = Path(__file__).resolve().parents[1] / "output"
REL_ROOT = "sas_figures"
DPI = 150
# The item number and stem sit in the left margin; the question code sits in the
# right. Only the left column tells us where the figure has to stop.
LEFT_COLUMN = 120


def blocks_with_geometry(doc, grade: int, titles: set[str]) -> list[dict]:
    """Every question-half block with its rectangle, furniture flagged.

    `titles` is the set of old chapter names. A chapter divider page prints its
    name as an ordinary block and ALSO carries the first scenario of the chapter,
    so treating the whole page as furniture -- which the first version did --
    loses that scenario and sends the chapter's opening items to the band of the
    previous chapter. Only the name itself is dropped.
    """
    out: list[dict] = []
    for page in doc:
        text = page.get_text()
        if "Question Code" in text or f"Class {grade}" not in text:
            continue
        divider = DIVIDER in text
        for b in sorted(page.get_text("blocks"), key=lambda r: (round(r[1] / 5), r[0])):
            s = fix(" ".join(b[4].split()))
            if not s or s.startswith("Curriculum Aligned") or "Copyright (c) 2021" in s:
                continue
            s = _MISPRINT_RE.sub(lambda m: MISPRINTED[m.group(0)], s)
            m = CODE.search(s)
            out.append({
                "page": page.number, "x0": b[0], "y0": b[1], "y1": b[3],
                "text": s, "code": m.group(0) if m else None,
                "furniture": bool(FURNITURE.match(s))
                             or (divider and s in titles),
            })
    return out


def trailing_rows(rows: list[dict]) -> list[dict]:
    """The blocks after an item's own content -- i.e. the NEXT scenario.

    The same boundary `parse_sas_items.split_item` uses, applied to geometry
    rather than to text: an item ends at the ruled answer space of a written
    response or at the fourth option of an MCQ, and whatever follows on the page
    introduces the item below it. Without this the previous question's own stem
    and options look like a scenario and every band comes out one item late.
    """
    stem, options, closed = 0, 0, False
    for i, row in enumerate(rows):
        if not row["text"].strip("_ "):
            if stem and not options:
                closed = True
            continue
        if closed or options >= 4:
            return rows[i:]
        if OPTION.match(row["text"]) and len(row["text"]) < 230:
            options += 1
        elif not options:
            stem += 1
    return []


def clusters(rows: list[dict]) -> dict[str, dict]:
    """item code -> the cluster band it belongs to, or {} when it has none."""
    code_at = [i for i, r in enumerate(rows) if r["code"]]
    out: dict[str, dict] = {}
    current: dict = {}
    for n, i in enumerate(code_at):
        end = code_at[n + 1] if n + 1 < len(code_at) else len(rows)
        if n:  # the scenario introduced after the PREVIOUS item opens this one
            prev_end = code_at[n]
            scenario = [r for r in trailing_rows(rows[code_at[n - 1] + 1:prev_end])
                        if not r["furniture"]]
            if scenario:
                first = scenario[0]
                after = next((r for r in rows[i:end]
                              if not r["code"] and r["x0"] < LEFT_COLUMN
                              and r["page"] == first["page"]
                              and r["y0"] > first["y0"]), None)
                current = {
                    "page": first["page"],
                    "top": first["y0"] - 4,
                    "bottom": after["y0"] - 3 if after else None,
                    "opened_by": rows[i]["code"],
                    "text": " ".join(r["text"] for r in scenario)[:160],
                }
        out[rows[i]["code"]] = dict(current) if current else {}
    return out


def render(doc, band: dict, out_dir: Path) -> dict:
    page = doc[band["page"]]
    bottom = band["bottom"] if band["bottom"] else page.rect.y1 - 25
    clip = fitz.Rect(page.rect.x0 + 22, max(band["top"], page.rect.y0 + 20),
                     page.rect.x1 - 22, bottom)
    pix = page.get_pixmap(clip=clip, dpi=DPI)
    data = pix.tobytes("png")
    sha = hashlib.sha256(data).hexdigest()
    name = f"{sha}.png"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / name).write_bytes(data)
    return {
        "file_name": name,
        "relative_path": f"{REL_ROOT}/{out_dir.name}/{name}",
        "extension": "png",
        "size_bytes": len(data),
        # The local URL the pipeline stamps; publish_question_figures rewrites
        # it to the CDN once the object is uploaded.
        "url": f"http://127.0.0.1:8000/api/assets/{REL_ROOT}/{out_dir.name}/{name}",
        "width": pix.width, "height": pix.height, "sha256": sha,
        "page_index": band["page"], "page_number": band["page"] + 1,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grade", type=int, required=True, choices=(6, 7))
    ap.add_argument("--chapter", required=True, help="old SAS chapter name")
    ap.add_argument("--apply", action="store_true", help="write the PNGs")
    a = ap.parse_args()

    sub_dir, files = GRADES[a.grade]
    doc = fitz.open(_MIRROR_ROOT / sub_dir / files["maths"])
    meta = parse_metadata(doc)
    wanted = {c for c, m in meta.items()
              if a.chapter.lower() in (m.get("chapter") or "").lower()}
    if not wanted:
        raise SystemExit(f"no items tagged {a.chapter!r} in the Class {a.grade} book")

    titles = {(m.get("chapter") or "").split("|", 1)[-1].strip()
              for m in meta.values()}
    rows = blocks_with_geometry(doc, a.grade, titles)
    bands = clusters(rows)

    out_dir = OUTPUT / REL_ROOT / f"c{a.grade}_{a.chapter.lower().replace(' ', '_')}"
    manifest: dict[str, dict] = {}
    print(f"{'item':<15} {'page':>4} {'band y':>15} {'image':<20} scenario")
    print("-" * 110)
    for code in sorted(wanted):
        band = bands.get(code) or {}
        if not band:
            print(f"{code:<15} {'-':>4} {'no cluster':>15} {'-':<20} "
                  f"(item has no shared scenario)")
            continue
        key = (band["page"], round(band["top"], 1))
        if key not in manifest:
            entry = render(doc, band, out_dir) if a.apply else {
                "file_name": "(dry run)", "relative_path": "", "sha256": ""}
            entry["_band"] = band
            manifest[key] = entry
        entry = manifest[key]
        bottom = band["bottom"] or 0
        print(f"{code:<15} {band['page']:>4} {band['top']:>7.0f}..{bottom:<7.0f} "
              f"{entry['file_name'][:18]:<20} {band['text'][:48]}")
    doc.close()

    if a.apply:
        index = out_dir / "_manifest.json"
        index.write_text(json.dumps({
            "assets": [{k: v for k, v in e.items() if k != "_band"}
                       for e in manifest.values()],
            # item code -> the images it needs, which `shape_c67sas_for_load`
            # reads so that no sha256 file name is ever typed out by hand.
            "items": {code: [manifest[(bands[code]["page"],
                                       round(bands[code]["top"], 1))]["file_name"]]
                      for code in sorted(wanted) if bands.get(code)},
        }, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\n{len(manifest)} image(s) in {out_dir}\n  manifest {index}")
        print("LOOK AT EVERY CROP before loading anything that points at one.")
    else:
        print(f"\n{len(manifest)} distinct band(s); pass --apply to render them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
