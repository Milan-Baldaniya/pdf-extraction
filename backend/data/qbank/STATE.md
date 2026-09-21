# Question-bank ingest — running state

Written by the overnight run. Read this first after any session reset.

## Done and committed

- `73bd246` local concept-ancestry committed; migration renumbered 009
- `637ce1c` merged origin/master (question_outcomes, strict sanitise_codes, DDL)
- `6598929` fix: resolve_codes was destroying the ancestry sanitise_codes filled
- `b51da31` fix: 4 silent losses (orphaned mappings on reload, NULL concept,
  _map_ids ambiguity, hardcoded Laravel .env)
- `e1922a0` probe_qbook.py + question_curriculum_context.py
- `169acf7` extract_qbank_textlayer.py + load_question_curriculum.py
- `da57d6a` mapper display fix; repaired 5,516 NULL concept names

## Key facts established

- Class 9 Science QB is born-digital: 2,215 chars/page text layer. **No MinerU.**
  160 s/chapter vs 22-55 min. Book = 634 pages, 13 chapters, sha on disk.
- Folio map verified: offsets change 24 times (1 -> 44). Chapters contiguous,
  no gaps. `data/qbank/cbse9_science_folio.json`.
- Book holds **2,353 answered questions**, ~181/chapter (144-226). 500/chapter
  needs ~4,160 more from other official sources. Top-up yield UNPROVEN.
- Class 10 Science: 2,926 mappable (sidecar-backed) + 4,438 LMS-native.
- `lms_question_outcome` was 0 rows at start.

## Commands

    # extract remaining Class 9 Science chapters (idempotent)
    venv/Scripts/python.exe -m scripts.extract_qbank_textlayer \
      --map data/qbank/cbse9_science_folio.json --all --apply --resume

    # mapping progress
    venv/Scripts/python.exe -m scripts.question_curriculum_context \
      --coverage --standard 43 --subject 3975

    # apply a reader's mapping file (dry by default)
    venv/Scripts/python.exe -m scripts.load_question_curriculum --all
    venv/Scripts/python.exe -m scripts.load_question_curriculum --all --apply

## In flight

- extract_qbank_textlayer --all (13 chapters, ~35 min total)
- mapping agents on Class 10 Science chapters 1019, 1017, 1021

## Next

1. Load mapping files as agents finish; verify codes differ within a chapter.
2. Map remaining Class 10 Science chapters, then Maths / SST / Class 9 Maths.
   Class 10 Maths + SST need a re-run after the other machine finishes.
3. Read Class 9 Science items into parts files, merge, load, publish figures.
4. Top-up sourcing toward 500/chapter; report real counts, never generate.
