# Question-bank ingest — running state

Read this first after any session reset. Decisions live in
`.claude/projects/d--pdf-extraction/memory/qbank-*.md`; this file is progress.

## Goal

All 357 chapters of Classes 6-10, breadth first. Every chapter reaches its
book's real count (~130-180) with concept + CG/LO + PAL tags before any chapter
is pushed toward 500. Official sources only; report shortfalls, never generate.
Every item is read against the source before it loads.

## Class 9 Science — LOADED

| chapter | items | in DB | held | tagged | figures |
|---|---|---|---|---|---|
| 1 Exploration | 143 | 143 | 0 | 143 | clean |
| 2 Cell | 163 | 163 | 0 | 163 | clean |
| 3 Tissues in Action | 165 | 165 | 0 | 165 | clean |
| 4 Describing Motion | 212 | 210 | 2 | 210 | clean |
| **total** | **683** | **681** | **2** | | |

Chapter 4's 2 held rows are genuine V-08 duplicate hashes — the book reprints
the same question under two numbers. 4 rows across the book are `ai_rephrased`
rather than `verbatim`; every other row reproduces the book exactly.

## IN FLIGHT

- **Chapter 5** "Exploring Mixtures and their Separation" (eid 596, 164 items
  drafted): six section readers running, one per section.
- **Chapter 6** "How Forces Affect Motion" (eid 597, 212 items drafted): six
  readers running. Note this chapter has TWO case blocks, at 16063-25301 and
  141972-173393, both feeding the one `ch06_case.json`.

## Drafted, not yet read

ch07 224 · ch08 149 · ch09 204 · ch10 200 · ch11 159 · ch12 161 · ch13 154.
Extraction id is 591 + chapter number.

## The pipeline

    # 0. section ranges + source + concept list for the readers
    venv/Scripts/python.exe -m scripts.section_map --extraction <eid> --dump <scratch>

    # 1. parse drafts (skips files a reader verified; --force overrides)
    venv/Scripts/python.exe -m scripts.parse_qbank_items \
      --extraction <eid> --out scripts/c9sci_items/drafts

    # 2. one agent per section, briefed from <scratch>/BRIEF_qbank.md

    # 3. mechanical check -- must be ok before merging
    venv/Scripts/python.exe -m scripts.check_drafts --chapter <n>

    # 4. merge sections, prefixing numbers by section (P/N/O/V/S/L/C)
    venv/Scripts/python.exe -m scripts.merge_qbank_parts --chapter <n> --write

    # 5. load (--replace is on by default, so re-running a fixed chapter updates)
    venv/Scripts/python.exe -m scripts.load_nodia_items \
      --dir c9sci_items --publisher nodia --only <n> --apply

    # 6. ALWAYS after a load
    venv/Scripts/python.exe -m scripts.check_figure_resolution --extraction <eid>

## What the reading keeps catching

Every chapter so far has had all of these. `BRIEF_qbank.md` tells each agent.

- **Truncated options** — 102 of chapter 2's 240 were fragments.
- **Bled page furniture**, trailing AND spliced mid-sentence. One answer had
  absorbed 3,037 characters of catalog advertising.
- **Fractions flattened denominator-first** — `a t v u = +` is `a = (v+u)/t`;
  `7 5` is 5/7. Superscripts flatten (`3 x 108` is 3 x 10^8) and minus signs
  vanish. Read as written you get the reciprocal. See the memory note.
- **Sub-parts each carrying their own `Ans :`** break into empty-stem fragments.
- **Column reading order** interleaves; a question's answer is usually printed
  on a LATER page. Do NOT use `get_text(sort=True)` — demonstrably worse, it
  reads across both columns on one visual line. Character counts confirm
  nothing is lost either way (2852 vs 2850 on a sample page); ordering only.
- **Questions lost at a section boundary.** Chapter 4's item 172 had its
  passage in one agent's range and its answer in another's, so each correctly
  dropped its half and the question vanished. `merge_qbank_parts` now reports
  numbering gaps, and every boundary agent is told to keep its half and shout.
- **The book's own errors.** Chapter 4 had an answer that did not follow from
  its own working and a question the book never answers. Correcting these is
  allowed; claiming them as verbatim is not. Set `reproduction: ai_rephrased`.

## Next

1. Chapters 5 and 6 in flight; then 7-13, two chapters at a time.
2. Then the other Class 9 subjects, then Classes 8, 7, 6, then Class 10's
   remaining subjects. Excluded: Class 9 English R2, Class 9 Hindi R2, Class 10
   AI, Class 10 IT. Not re-ingested: Class 10 Science, Maths, Social Science.
3. Class 10 Science per-question curriculum mapping: 586 of 2,926 done.
4. **Figures: still unsolved.** No item carries `images`. Several chapters have
   questions that need one (ch2 ten, ch4 nine, ch4 long items 140/142/165/169/
   171), and the manifests hold 28-48 images each, but nothing in the markdown
   ties a file to a question. `figure_required` is deliberately left unset, so
   V-07 stays quiet and the questions load without a figure.
