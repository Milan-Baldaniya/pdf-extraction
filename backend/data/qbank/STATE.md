# Question-bank ingest — running state

Read this first after any session reset. Decisions live in
`.claude/projects/d--pdf-extraction/memory/qbank-*.md`; this file is progress.

## Goal

All 357 chapters of Classes 6-10, breadth first. Every chapter reaches its
book's real count with concept + CG/LO + PAL tags before any chapter is pushed
toward 500. Official sources only; report shortfalls, never generate. Every
item is read against the source before it loads.

## CLASS 9 SCIENCE — COMPLETE, 2,346 questions

| ch | name | items | mapped |
|---|---|---|---|
| 1 | Exploration | 143 | yes |
| 2 | Cell | 163 | yes |
| 3 | Tissues in Action | 165 | yes |
| 4 | Describing Motion | 210 | yes |
| 5 | Exploring Mixtures | 167 | yes |
| 6 | How Forces Affect Motion | 222 | yes |
| 7 | Work, Energy, Machines | 226 | yes |
| 8 | Journey Inside the Atom | 150 | running |
| 9 | Atomic Foundations | 213 | running |
| 10 | Sound Waves | 200 | running |
| 11 | Reproduction | 162 | running |
| 12 | Patterns in Life | 167 | running |
| 13 | Earth as a System | 158 | running |

Three rows held across the whole book, all genuine duplicate hashes. Figures
clean on every chapter. 92% of the corpus is the book's own words; every
departure carries `reproduction: ai_rephrased`.

Estate: 8,141 questions (was 5,795 at the start of this book).

## The measured cost

About **850K subagent tokens to read a chapter** across five or six section
readers, ~150K to consolidate and ~180K to curriculum-map it. Call it 1.2M for
a finished chapter. Budget accordingly and finish whole books.

## The pipeline

    # 0. ranges, source and concept list for the readers
    venv/Scripts/python.exe -m scripts.section_map --extraction <eid> --dump <scratch>
    # 0b. ALWAYS, before assigning anyone
    venv/Scripts/python.exe -m scripts.foreign_pages --extraction <eid>

    # 1. parse drafts (skips verified files; --force overrides)
    venv/Scripts/python.exe -m scripts.parse_qbank_items --extraction <eid> --out scripts/c9sci_items/drafts

    # 2. one agent per section, briefed from <scratch>/BRIEF_qbank.md
    # 3. relay findings between running readers with SendMessage
    # 4. venv/Scripts/python.exe -m scripts.check_drafts --chapter <n>
    # 5. venv/Scripts/python.exe -m scripts.merge_qbank_parts --chapter <n> --write
    # 6. venv/Scripts/python.exe -m scripts.load_nodia_items --dir c9sci_items --publisher nodia --only <n> --apply
    # 7. venv/Scripts/python.exe -m scripts.check_figure_resolution --extraction <eid>

    # curriculum, independent and parallel
    venv/Scripts/python.exe -m scripts.question_curriculum_context --chapter <id> --batch 25 --part 1
    venv/Scripts/python.exe -m scripts.load_question_curriculum --all --apply

## THE ONE THING THAT MATTERS MOST

**Derive the numbering map before reading anything.** Take the number
immediately before and after each banner; that fixes each section's run. Then
go and find those questions wherever the book prints them. Byte ranges are
close to worthless in this book:

- chapter 12: 6 of 30 very-short questions were inside the very-short range
- chapter 13: 18 of 30 very short, 17 of 30 short
- chapter 9: 7 of 30 very short; its pre-banner region was the MIDDLE of Pause
  and Ponder, printed above the banner that introduces it
- chapter 11: its Pause and Ponder section appeared not to exist at all

Every chapter needed a consolidation pass afterwards, and several questions per
chapter existed in NO file until someone went looking.

## Where text hides — four routes, two of them undetectable mechanically

1. **A displaced folio in a NEIGHBOURING extraction.** `foreign_pages` finds
   these: 21 misfiled pages across the 13 extractions. It is a mutual swap, one
   page each way, same folio number.
2. **A non-adjacent page of the same extraction.** Overflow direction is not
   consistent — 403's top continues 406's bottom, 410's top continues 407's.
3. **The tail of an unrelated question's answer, sections away.** Chapter 10's
   Q159(c) was 10,000 chars from its stem, on a different section's item.
4. **Chapter 12's page LABELS are permuted** — markers 509/511/513/515 head the
   content of printed 515/509/511/513. Odd pages print no folio line, so this
   is invisible until you follow a sentence across a page foot.

**If you are about to write an answer yourself, open every keyword hit first,
whatever its offset.** Four "not printed anywhere" findings were disproved this
way; in each, the text was outside the range the reader was searching.

## Silent destroyers

- **A question buried in another question's option**, either direction, with
  its answer overwriting the host's. Destroys two at once and the host still
  passes every check. Chapter 12 had six lost in three such pairs.
- **The parser's one-place shift** on items with numbered sub-parts: empty
  `answer`, next record's `stem` holds it. Cost ten stems in one section.
- **Rotated answers** — two questions each carrying the other's answer, both
  individually valid. Only checking that the answer solves its stem finds it.

## Next

Classes 8, 7, 6, then Class 10's remaining subjects. Excluded: Class 9 English
R2, Class 9 Hindi R2, Class 10 AI, Class 10 IT. Not re-ingested: Class 10
Science, Maths, Social Science.

## Unsolved

**Figures.** No item carries `images` and none can from the markdown: it holds
zero image references. The `asset_manifest` is every image on the page, not a
list of figures. `figure_required` is deliberately left unset so V-07 stays
quiet; the items that want a figure are named in each reading report.
