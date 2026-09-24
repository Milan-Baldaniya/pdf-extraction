# Question-bank ingest — running state

Read this first after any session reset. Decisions live in
`.claude/projects/d--pdf-extraction/memory/qbank-*.md`; this file is progress.

## Goal

All 357 chapters of Classes 6-10, breadth first. Every chapter reaches its
book's real count (~130-180) with concept + CG/LO + PAL tags before any chapter
is pushed toward 500. Official sources only; report shortfalls, never generate.
Every item is read against the source before it loads.

## Done and committed

- `4bcd2be` shape() accepts bloom/dok/difficulty, validated against
  pal_vocabulary; writer merges authored over carried tags.
  `check_figure_resolution.py` added — all 5,795 loaded questions pass.
- `13a9fd5` `parse_qbank_items.py` — 2,289 drafts from 13 Class 9 Science
  chapters against 2,353 answer markers (97%). 14 MCQ defects, 0 missing keys.

Earlier: `73bd246` `637ce1c` `6598929` `b51da31` `e1922a0` `169acf7` `da57d6a`
`04ff1f2` `8532a80` `0dcdf1e`.

## Where the numbers stand

| | chapters | with questions | questions |
|---|---|---|---|
| Class 6 | 54 | 0 | 0 |
| Class 7 | 62 | 0 | 0 |
| Class 8 | 76 | 0 | 0 |
| Class 9 | 50 | 8 | 278 |
| Class 10 | 115 | 31 | 5,517 |

Class 10 Science curriculum mapping: 586 of 2,926 (`lms_question_outcome` 656).

## Class 9 Science — extracted, drafted, being verified

13 chapters extracted (rows 592-604, 2,010,399 chars, 375 figures).
Drafts in `scripts/c9sci_items/drafts/` — 63 files, 2,289 items.

**Chapter 2 is LOADED and passed the gate** (row 592): 163 items, 0 held,
240 options, concept_id AND concept on all 163, g_bloom/g_dok/g_difficulty on
all 163, figure-resolution check clean. Bloom spread recall 55 / understand 40
/ analyze 38 / evaluate 11 / create 10 / apply 9 -- authored, not keyword-
guessed. Forms: mcq 60, very_short 53, short 30, case_study 10, long 10.

Chapter 1 sections verified by agents but not yet merged or loaded.
Chapters 3-13 drafts re-parsed with all four parser fixes; not yet verified.

Known gap: 10 chapter-2 questions reference a figure, but nothing in the
markdown ties an image file to a question. figure_required was deliberately
left off rather than set without images, which would hold every one on V-07.
28 images are available on the extraction if they can be matched.

## Commands

    # re-parse drafts. Skips any file a reader has already verified;
    # --force overwrites those and throws their work away.
    venv/Scripts/python.exe -m scripts.parse_qbank_items \
      --standard 42 --subject 3975 --out scripts/c9sci_items/drafts

    # after any load, always
    venv/Scripts/python.exe -m scripts.check_figure_resolution --extraction <eid>

    # mapping progress
    venv/Scripts/python.exe -m scripts.question_curriculum_context \
      --coverage --standard 43 --subject 3975

## Next

1. Merge verified chapter-2 sections, `load --dry`, inspect, `--apply`,
   publish figures. That is the one-chapter gate.
2. Verify the other 12 chapters, section by section, in parallel.
3. Mirror the remaining pdf.tube books; probe each for text-layer quality
   before assuming MinerU is or is not needed.
4. Continue Class 10 Science mapping alongside.
