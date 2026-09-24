# Question-bank ingest — running state

Read this first after any session reset. Decisions live in
`.claude/projects/d--pdf-extraction/memory/qbank-*.md`; this file is progress.

## Goal

All 357 chapters of Classes 6-10, breadth first. Every chapter reaches its
book's real count (~130-180) with concept + CG/LO + PAL tags before any chapter
is pushed toward 500. Official sources only; report shortfalls, never generate.
Every item is read against the source before it loads.

## Loaded

| chapter | items | in DB | held | tagged | curriculum |
|---|---|---|---|---|---|
| 9 Sci 1 Exploration | 143 | 143 | 0 | 143 | 143 mapped |
| 9 Sci 2 Cell | 163 | 163 | 0 | 163 | 163 mapped |
| 9 Sci 3 Tissues in Action | 165 | 165 | 0 | 165 | — |
| 9 Sci 4 Describing Motion | 212 | 210 | 2 | 210 | — |
| **Class 9 Science** | **683** | **681** | **2** | | **306** |

Estate-wide: 6,476 questions, 957 with per-question curriculum codes.
Chapter 4's 2 held rows are genuine duplicate hashes — the book reprints the
same question under two numbers. 4 rows are `ai_rephrased`; the rest are the
book's own words.

## The honest rate

Measured on chapters 5 and 6: **about 850K subagent tokens to read one
chapter** across six section readers, plus ~150K to consolidate it and ~140K
to curriculum-map it. Call it **1M tokens per finished chapter**. 357 chapters
is therefore not a single-session goal; budget accordingly and finish whole
books rather than starting many.

## In flight

- Chapter 5 (eid 596) — all six readers done, consolidation running.
- Chapter 6 (eid 597) — all six readers done, consolidation running.
- Chapter 7 (eid 598) — five readers running.

Drafted, not yet read: ch08 149 · ch09 204 · ch10 200 · ch11 159 · ch12 161 ·
ch13 154. Extraction id is 591 + chapter number.

## The pipeline

    # 0. section ranges + source + concept list for the readers
    venv/Scripts/python.exe -m scripts.section_map --extraction <eid> --dump <scratch>

    # 1. parse drafts (skips files a reader verified; --force overrides)
    venv/Scripts/python.exe -m scripts.parse_qbank_items \
      --extraction <eid> --out scripts/c9sci_items/drafts

    # 2. one agent per section, briefed from <scratch>/BRIEF_qbank.md
    # 3. ONE consolidation agent per chapter -- see below, this is not optional
    # 4. venv/Scripts/python.exe -m scripts.check_drafts --chapter <n>
    # 5. venv/Scripts/python.exe -m scripts.merge_qbank_parts --chapter <n> --write
    # 6. venv/Scripts/python.exe -m scripts.load_nodia_items \
    #      --dir c9sci_items --publisher nodia --only <n> --apply
    # 7. venv/Scripts/python.exe -m scripts.check_figure_resolution --extraction <eid>

    # curriculum, independent of the above and runnable in parallel
    venv/Scripts/python.exe -m scripts.question_curriculum_context --chapter <id> --batch 25 --part 1
    venv/Scripts/python.exe -m scripts.load_question_curriculum --all --apply

## Why a consolidation pass is mandatory

A section reader can only see its own byte range, and the books do not respect
those ranges. Every chapter so far has needed items moved between files, and
several questions per chapter exist in NO file until someone goes looking.
Chapter 5 had twelve very-short questions filed under objective and one buried
inside another question's option with its answer overwriting the host's.
Chapter 6 had eight questions above the first banner, five objective questions
filed under very-short, and a block of eighteen filed under short.

Readers must be told to KEEP and REPORT foreign items, never delete them, and
to park anything they remove. Relay findings between still-running readers
with SendMessage — it works and is the cheapest fix available.

## What the reading keeps catching

- **Truncated options** — 102 of chapter 2's 240 were fragments.
- **Bled page furniture**, trailing AND spliced mid-sentence. One answer had
  absorbed 3,037 characters of catalog advertising. The running header is the
  chapter's own title, which `check_drafts` now builds per chapter.
- **Fractions flattened denominator-first** — `a t v u = +` is `a = (v+u)/t`.
  Superscripts flatten and minus signs vanish. See the memory note.
- **Cross-item splices** — a truncated answer usually has another question's
  text pasted on, so the fix is a swap, not a trim. Chapter 6's long section
  had ten answers rotated into a closed cycle.
- **The book's own errors** — an answer that does not follow from its own
  working, a question the book never answers, a unit printed as ms-1 that the
  working treats as ms-2. Correcting these is allowed; claiming them as
  verbatim is not. Set `reproduction: "ai_rephrased"`.
- **Pages from another chapter.** Chapter 6's extraction contains pages whose
  running header reads "Exploring Mixtures and their Separation", carrying
  chapter 5's questions 132-134 — which are therefore missing from chapter 5's
  own extraction. Check the header before forcing a concept onto a question.
- **Page order is NOT shuffled.** The `## Page N` markers are strictly
  ascending in every chapter checked. What is out of order is the content: the
  publisher prints a question's continuation several pages later. Do not go
  looking for a page-ordering bug, and do not re-extract; there is nothing
  there to fix.

## Known source losses

`data/qbank/known_gaps.json` records numbers that are missing for a reason,
with the evidence, so the numbering-gap check does not cry wolf forever.
Chapter 5's NCERT 6 and 7 were replaced by a duplicated summary page — checked
against the mirrored PDF at page index 215. Chapter 6's case block is missing
193 and 194, replaced by a page of chapter 7 theory.

## Unsolved

**Figures.** No item carries `images`, and none can from the markdown: it
holds zero image references of any kind. The `asset_manifest` is every image
on the page, not a list of figures — 24 of Class 9 Science's 375 entries are
the publisher's advertising. `figure_required` is deliberately left unset so
V-07 stays quiet and the question loads without a figure; the item numbers
that want one are noted in each reading report.
