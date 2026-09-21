# Question banks for Classes 10 → 9 → 8 → 7 → 6, mapped to concepts and curriculum

## Context

Chapter extraction runs unattended overnight. The next body of work is the
**question banks**: turn CBSE question-bank PDFs into rows in the question
tables the way Class 10 Science already is (2,926 items), with each question
mapped to its **chapter**, its **concept**, and now its **curricular goal and
learning outcome**.

Three things make this different from chapter extraction:

1. **The source is new.** `https://pdf.tube/School/CBSE/` — verified: plain HTML
   listings, Cloudflare R2, `application/pdf`, HTTP range requests supported
   (downloads resume). 21 question banks across classes 6–10.
2. **The reading is model work, not MinerU.** MinerU produces the markdown; a
   model reads it and writes the item JSON. Deliberate — the team's own notes
   record the regex parser needing an OCR repair on 72% of items and silently
   dropping a whole `ONE MARK QUESTIONS` heading.
3. **Curriculum mapping is new.** Nothing links a question to a learning
   outcome today.

All execution happens on **Vivek's laptop**. Nothing runs on this machine.

---

## Answering the two questions you raised

### `question_type_catalog` / `question_type_master`

The write set is **six tables, not four**. Both type tables are already handled
by the existing flow — no work needed, but they should be named so nobody
thinks they're missing:

| Table | Who writes it | State today |
|---|---|---|
| `lms_question_master` | `question_bank_writer` | the question |
| `answer_master` | `question_bank_writer` | one row per option |
| `lms_question_extraction` | `question_bank_writer` | provenance + verbatim copy |
| `lms_question_asset` | `question_bank_writer` | figures |
| `question_publisher` | `publisher_service.ensure_publisher()` | 6 rows (nodia, kvs, ncert, cbse, cambridge, oswaal) |
| `question_type_catalog` | `publisher_service.register_question_types()` | **18 rows, live** — `mcq` 2612 seen, `very_short` 6161, `short` 2467, `long` 2294, `assertion_reason` 696 |

`question_type_master` is the **LMS's own table** (8 rows) and is read-only here;
`question_type_catalog.lms_question_type_id` maps our fine-grained forms onto it
(1 = multiple, 2 = narrative, 8 = assertion & reason). A publisher-specific row
wins over a standard one. This already works — `nodia` has its own `case_study`
row with 1,150 sightings.

### Curriculum mapping: new column, or new table?

**A new join table — `lms_question_outcome`. Not a column on question master.**

The estate already answered this for concepts: **`lms_concept_outcome`, 31,743
live rows**, written by `curriculum_frame.persist_mappings()`. Three reasons it
must be a table:

- **One question serves several outcomes.** `concept_service.py` tells the model
  to cite *"usually one, at most three"* codes. A case-study parent with four
  sub-parts legitimately spans a competency and two outcomes. A column cannot
  hold that.
- **Outcome ids churn.** `curriculum_service.save_learning_outcomes()` **DELETEs
  the whole curriculum** on every re-process. An `outcome_id` stored on the
  shared ERP table would dangle with no resync path. The durable key is
  `(curriculum_id, outcome_code)` — which is exactly why `lms_concept_outcome`
  stores `outcome_code` beside `outcome_id` and ships `resync_outcome_ids()`.
- **The hierarchy is already there.** `lms_learning_outcomes.parent_id` gives
  CG → C → LO. Storing three independent FKs means three things that stale
  independently. Store `goal_code`/`competency_code` **denormalised on the
  mapping row**, as the concept table already does.

**But also add two columns to `lms_question_master`** — `g_lo_code` and
`g_cg_code`, *codes not ids*, joining the existing `g_bloom` / `g_dok` /
`g_difficulty` / `g_qtype_code` family — so the bank UI can filter by curriculum
without a join. This mirrors how `concept_id`/`concept` are already mirrored
from the sidecar onto the master.

So: **table for the truth, codes on the master for speed.**

---

## What is available and ready (verified against the live DB)

| Class | Book | LMS subject | chapters | CG/C/LO | status |
|---|---|---|---|---|---|
| 10 | Science QB | Science | 13 | 139 | **done** (2,926 items) |
| 10 | Maths Standard QB | Mathematics | 14 | 130 | 4 of 14, in flight |
| 10 | Social Science | Geo / Hist / Civics / Econ | 7+5+5+5 | 82+40+44+39 | in flight |
| 10 | English QB | English | 9 | 96 | ready |
| 10 | Hindi A QB | Hindi-A | 12 | 110 | ready |
| 10 | Hindi B QB | Hindi-B | 14 | 117 | ready |
| 9 | Science QB | Science | 13 | 266 | ready |
| 9 | English R1 QB | English | 8 | 262 | ready |
| 9 | Hindi R1 | Hindi-A | 12 | 234 | ready |
| 8 | Science QB | Science | 13 | 208 | ready |
| 8 | English QB | English | 8 | 179 | ready |
| 8 | Social Science QB | Geo / Civics / Hist | 5+8+8 | 51+78+103 | ready |
| 7 | Science QB | Science | 12 | 205 | ready |
| 7 | English QB | English | 5 | 91 | ready |
| 7 | Social Science QB | Geo / Hist | 12+8 | 290+198 | ready |
| 6 | Science QB | Science | 12 | 169 | ready |
| 6 | Social Science QB | Social Sciences | 14 | 362 | ready |

**Blocked — keep out of every sheet:**
Class 9 **English R2** → `English-2` has 0 chapters / 0 CG-LO ·
Class 9 **Hindi R2** → `Hindi-B` has 0 / 0 ·
Class 10 **AI** and **IT** → no such subject in `sub_std_map`.

`create_extraction_stub()` **raises `ChapterNotFoundError`** for a question bank
with no matching chapter, and `process_exam_questions` hard-fails on a NULL
`chapter_id`. Chapter coverage is a hard prerequisite.

**Classes 6–8 are better prepared than Class 10 English/Hindi** — every target
subject has both chapters and curriculum data.

---

## Honest split: unattended vs model

| Stage | Unattended? | Cost |
|---|---|---|
| 0 Mirror from pdf.tube | yes | ~15–35 MB/book |
| 1 Probe book (folio, sections, answer marker, CONTENTS) | yes (output read next morning) | seconds |
| 2 Split + verify boundaries | yes | minutes |
| 3 **MinerU extract** | **yes — this is the night** | 22–55 min/chapter |
| 4 Render pages / text layer | yes | 0.3 s/page |
| 5 **Read items** | **no — model** | the project |
| 6 Merge → load → tag | yes | minutes |
| 7 Publish figures to Spaces | yes | minutes |

**Stage 3 already has a runner.** `scripts/run_extraction_queue.py` accepts
`document_type='question_bank'`, `_fetch()` takes **local file paths** (so split
chapter PDFs go straight in), and `ChapterNotFoundError` is caught per row so one
bad chapter fails alone. `KeepAwake` stops Windows suspending. No new runner.

**Stage 5 cannot run overnight.** Two books produced 5,741 items. ~150 chapters
in scope is on the order of 500 reading sessions. Writing part files overnight is
safe; **`load_nodia_items --apply` overnight is not** — it is `--dry` by default
precisely because "a mistake here lands in the live question bank". Keep the dry
report as a morning decision.

---

## Work

### Phase 0 — schema and code (once, before any night)

**Schema.** Question DDL lives in `backend/app/db/mariadb.py` (`_QUESTION_TABLES_EXTRA`,
`_EXTRACTION_ITEM_COLUMNS`), applied idempotently by `_ensure_publisher_schema()` —
**not** `backend/sql/`. Add:

- `lms_question_outcome` — mirrors `lms_concept_outcome` column-for-column with
  `question_id` in place of `concept_id`; `UNIQUE (question_id, outcome_code)`
  (on *code*, because `outcome_id` is nullable and MySQL allows unlimited NULLs
  in a unique index). No foreign keys — `save_learning_outcomes()` deletes the
  parent rows by design.
- Sidecar columns on `lms_question_extraction`: `outcome_id`, `outcome_code`,
  `outcome_confidence`, `outcome_source` — the **primary** outcome only.
- `lms_question_master`: `g_lo_code`, `g_cg_code` + index
  `(chapter_id, g_cg_code, g_lo_code)`.
- Mirror to `backend/sql/008_question_curriculum_outcomes.sql` for the explicit
  path — `sql/006` was left file-only and never became idempotent; don't repeat it.

**Code.** New `app/services/question_outcomes.py` (sibling of the concept path):
`resolve_codes()`, `persist_question_outcomes()`, `mirror_primary()`,
`resync_question_outcome_ids()`. Add `strict=` to
`curriculum_frame.sanitise_codes()` — it currently **drops** an invented code at
`logger.debug`, which is right for concepts and wrong here; strict mode raises,
and the loader reports drops per chapter so the loss is loud, never silent.

**Reader's closed list.** `scripts/chapter_context.py` already prints the legal
concept names and legal image names; add the legal CG/C/LO codes via
`curriculum_frame.load_frame().prompt_block()`. When a chapter has no frame,
print *"NONE RECORDED — omit `curriculum_codes`; do not guess"* — that single
line is what makes Class 10 English/Hindi work without a second procedure.

**Item JSON** gains `curriculum_codes: []` — same field name as
`concept_service` so there's one vocabulary. It must **not** enter `_hash()` or
`verbatim_payload`: a curriculum tag is not reproduction, and changing the hash
would break `uq_lqe_extraction_hash` and discard the paid AI tagging carried
across on all 5,741 existing items.

**Regression gate:** `load_nodia_items --book sst10 --only 1 --dry` must be
byte-identical to before.

**Prove it on data that already exists** before any reader is asked to cite a
code: run the mapping over Class 10 Science/Maths, which already have both
questions and curriculum, and inspect `lms_question_outcome`.

### Phase 1 — generalisation fixes found during research

- `check_split_boundaries.py` takes `--book` but hardcodes the **Maths** banner
  vocabulary; on any other book it reports every chapter as "MID-CONTENT".
- `find_stray_pages.py` has no `--book` at all (`BOOK = "maths10"`).
- `assign_pages.py` / `folio_map.py` hardcode `HEADER_HEIGHT`, running-head and
  question-start regexes that belong on `books.Book`.
- `plan_page_work.plan()` returns `[]` **silently** when no section heading
  matches — the likeliest silent failure across 15 books with unknown banner
  vocabulary. Make it loud.
- `apply_read_concepts()` writes `concept_id` but **not** `concept`, so a
  re-pointed item keeps the tagger's wrong concept *name* — which is what the
  bank UI falls back to. One-line fix, do it here.
- `_map_ids`' primary chapter lookup has **no standard/subject guard**
  (`chapter_name` + `sort_order` + tenant only). Only 1 ambiguous pair exists
  today, but we are about to add ~150 chapters with generic names. Add a
  pre-flight ambiguity check; `run_extraction_queue` does not verify afterwards
  the way `register_read_chapter` does.

### Phase 2 — new scripts

| Script | Does |
|---|---|
| `scripts/mirror_pdftube.py` | Parse the HTML listing (never hardcode URLs — filenames contain double spaces), skip sample papers, resume via range requests, verify `%PDF-`, write a manifest with sha256 + page count |
| `scripts/probe_book.py` | Emit a **draft `Book(...)` literal** — folio regex, answer marker (`Ans` / `Sol :` / `उत्तर`), section banners with counts, CONTENTS page ranges, fuzzy chapter_id match. Never writes `books.py` |
| `scripts/qb_prereq.py` | One report before anything is queued: chapter coverage, **ambiguity**, concept coverage, curriculum coverage (FULL/PARTIAL/NONE), publisher, and whether the Laravel `.env` is even readable on this machine |
| `scripts/build_qb_sheet.py` | Split PDFs → queue sheet rows with `document_type=question_bank` |
| `scripts/run_overnight_qbank.bat` | Sibling of `run_overnight.bat` |

`books.py` gains a `publisher` field (today `load_nodia_items.PUBLISHER` is a
module constant, and **these banks are not NODIA** — identify each from its title
page and `ensure_publisher()` before loading, or every row gets
`"Extracted from the uploaded source document"`, which is not an attribution).

Do not reuse the key strings `sci10` / `maths10` — five modules special-case
those literals before consulting `books.py`.

---

## Order

**10 → 9 → 8 → 7 → 6**, and within that, cheapest-and-most-instructive first:

1. **Class 9 Science** — chapters + 266 outcomes; exercises the whole design.
2. **Class 10 English, Hindi A, Hindi B** — first real test of *partial*
   curriculum coverage, and Devanagari section vocabulary.
3. **Class 8** — Science, English, Social Science (3 subjects, per-chapter
   `subject_id`, as you asked).
4. **Class 7**, then **Class 6**.

Class 10 Science is done; Maths and Social Science are in flight elsewhere —
use them only as the Phase-0 proving target, never queue them on Vivek's machine.

---

## Verification

1. Boot once; confirm `lms_question_outcome` + the six columns exist and a second
   run is a no-op.
2. An invented code raises under `strict=True`; a real one resolves to the right
   `lms_learning_outcomes.id` **for that chapter**.
3. `load_nodia_items --book sst10 --only 1 --dry` byte-identical to before.
4. **One chapter end to end** before committing a night: mirror → probe → split →
   verify → MinerU → read one section → `--dry` → inspect → `--apply`. Confirm
   rows in all six tables, `lms_question_outcome` populated with that chapter's
   own codes, `concept_id` **and** `concept` set, figures on a CDN URL not
   `127.0.0.1`.
5. Every sheet preflights to *"Every row resolves to a standard, subject and
   chapter."*
6. Blocked books absent: Class 9 English R2 / Hindi R2, Class 10 AI / IT.

---

## Risks

- **Volume.** ~150 chapters of MinerU is many nights, and the model reading is
  larger still. This is weeks of work, not a night.
- **Provenance.** pdf.tube's publisher is unknown per book. `licence_type` for
  both NODIA and Oswaal already reads *"Unspecified — confirm before
  publishing"*. Settle licence before anything reaches learners.
- **Chapter collision.** `_map_ids` can resolve a question bank onto the wrong
  chapter silently. Pre-flight check, not an afterthought.
- **Silent failures everywhere.** A dropped image name, a wrong concept, a
  curriculum code quietly discarded. Every guard in this codebase exists to turn
  a silent loss into a loud one; keep adding them.
