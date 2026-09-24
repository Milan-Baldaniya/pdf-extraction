# Question-bank ingest — running state

Read this first after any session reset. Decisions live in
`.claude/projects/d--pdf-extraction/memory/qbank-*.md`; this file is progress.

## Goal

All 357 chapters of Classes 6-10, breadth first. Every chapter reaches its
book's real count (~130-180) with concept + CG/LO + PAL tags before any chapter
is pushed toward 500. Official sources only; report shortfalls, never generate.
Every item is read against the source before it loads.

## Class 9 Science — LOADED SO FAR

| chapter | items | held | tagged | figure check |
|---|---|---|---|---|
| 1 Exploration | 143 | 0 | 143/143 | clean |
| 2 Cell | 163 | 0 | 163/163 | clean |
| 3 Tissues in Action | 165 | 0 | 165/165 | clean |
| **total** | **471** | | | |

Chapter 4 (Describing Motion) is 211 items, 184 verified; pause/ncert/case in
flight. Chapters 5-13 drafted, not yet read.

## The pipeline

    # 1. parse drafts (skips files a reader already verified; --force overrides)
    venv/Scripts/python.exe -m scripts.parse_qbank_items \
      --extraction <eid> --out scripts/c9sci_items/drafts

    # 2. agents read each section file and add concept/bloom/dok/difficulty

    # 3. mechanical check -- must be ok before merging
    venv/Scripts/python.exe -m scripts.check_drafts --chapter <n>

    # 4. merge sections, prefixing numbers by section (P/N/O/V/S/L/C)
    venv/Scripts/python.exe -m scripts.merge_qbank_parts --chapter <n> --write

    # 5. load
    venv/Scripts/python.exe -m scripts.load_nodia_items \
      --dir c9sci_items --publisher nodia --only <n> --apply

    # 6. ALWAYS after a load
    venv/Scripts/python.exe -m scripts.check_figure_resolution --extraction <eid>

## What the reading keeps catching

Every chapter so far has had all of these. Tell each agent up front:

- **Truncated options** — the PDF wraps long choices; 102 of chapter 2's 240
  were fragments like "It", "Massive". Fixed in the parser, but check anyway.
- **Bled page furniture**, trailing AND spliced mid-sentence: the running
  header, `Click Here to Buy book on Amazon/Flipkart`, `Downloaded from
  www.pdf.tube`, `NODIA`, `wwww.nodia.i`, the next section's banner. One answer
  had absorbed 3,037 characters of catalog advertising.
- **Fractions flattened denominator-first** — `a t v u = +` is `a = (v+u)/t`,
  "7 5" is 5/7. See the memory note; read as written you get the reciprocal.
- **A question whose sub-parts each carry their own `Ans :`** breaks into
  fragments with empty stems, its text bled onto the previous item's answer.
- **Column reading order** can interleave in a two-column section. Chapter 4's
  long section needed real reconstruction. Do NOT "fix" this with
  `get_text(sort=True)` -- that is demonstrably worse, it reads across both
  columns on one visual line and splices `AAns :` mid-sentence. Character
  counts confirm nothing is lost either way (2852 vs 2850 on a sample page);
  it is ordering only.

## Next

1. Finish chapter 4, merge, load.
2. Chapters 5-13, three agents at a time, one section each.
3. Then the other Class 9 subjects, then Classes 8, 7, 6.
4. Figures: no item yet carries `images`. Several chapters have questions that
   need one (ch2 ten, ch4 nine), and the manifests hold 28-48 images each, but
   nothing in the markdown ties a file to a question. Unsolved.
