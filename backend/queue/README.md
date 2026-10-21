# Overnight chapter extraction

Extract a whole syllabus while nobody is at the machine. Start it before you
leave, stop it when you arrive.

MinerU runs at roughly 30–40 seconds per page on CPU, so one chapter is 10–25
minutes and a class is a night. The extraction form handles one chapter per
submission, which is right for a person and wrong for a syllabus. This runs the
same extraction, from a spreadsheet, unattended.

**Scope: extraction only.** PDF in, markdown row in `document_extractions`, stop.
The DeepSeek stages (curriculum, topics, concepts) are deliberately *not* run —
they cost money per call and write into the live LMS tables, and neither should
happen while nobody is watching. Run those from the Chapters queue in the
morning, on what you can see landed.

---

## The three files here

| File | What it is |
|---|---|
| `extraction_queue.xlsx` | **The input.** One row per chapter. You edit this. |
| `ledger.jsonl` | Append-only record of every chapter of every night. The resume record. |
| `run_state.json` | The current run's heartbeat, read by the web page. |
| `STOP` | Appears when you press Stop; the runner checks it between chapters. |

The **ledger**, not the sheet, is what the runner trusts. Excel takes an
exclusive lock on an open `.xlsx`, so if you leave the sheet open overnight the
runner cannot write to it — the run is unaffected, and `--sync-sheet` replays
the ledger into the workbook afterwards.

---

## Everyday use

### From the web app

**Home → Overnight Extraction**, or `/overnight`.

- **Start overnight run** — launches it. It runs until the queue is empty. There
  is no automatic stop.
- **Stop after this chapter** — finishes what is in flight, saves it, then stops.
  It never kills MinerU mid-chapter; that would throw away up to 40 minutes of
  CPU and strand a row stamped `extracting` forever.
- The page shows what it is extracting right now, and a plain-language summary of
  every night so far with the full log underneath.

Closing the page, or the browser, does not stop the run. It is a detached
process and survives the API restarting.

### From the command line

```bash
python -m scripts.run_extraction_queue --list     # what would run, and why not
python -m scripts.run_extraction_queue            # run it
scripts\run_overnight.bat                         # same, double-clickable
```

Useful flags: `--only-standard 10`, `--only-subject Science`, `--only-chapter 5`,
`--force` (re-extract finished rows), `--stop-at 07:30`, `--sync-sheet`.

---

## Filling the sheet

Columns you fill: `enabled, board, standard, subject_name, chapter_number,
document_title, document_type, syear, sub_institute_id, pdf_url`. These are
exactly the fields the extraction form asks a person for — the form derives
`sub_institute_id` from the board, the sheet lets you state it. Everything from
`status` rightward is written by the runner — don't edit those.

`document_title` is the chapter name; a column headed `chapter_name` is accepted
as an alias. `pdf_url` takes a URL **or** a local file path.

### Check it before you commit a night

```bash
python -m scripts.run_extraction_queue --list
```

Besides showing what would run, this resolves every row's `standard_id`,
`subject_id` and `chapter_id` the same way `_map_ids` will at insert time, and
ends with either:

```
Every row resolves to a standard, subject and chapter.
```

or a warning naming the rows that will be stored with a NULL id. That matters
because a name that matches nothing is **not an error** — the extraction
succeeds and the row is saved, but nothing downstream can find the chapter. A
misspelled subject is invisible until a week later without this check.

Build rows from the database rather than typing them, so the titles and chapter
numbers match what `_map_ids` will resolve against `chapter_master`:

```bash
# see what the database has
python -m scripts.build_extraction_sheet --list --standard 10

# one subject, titles filled from chapter_master, NCERT links filled too
python -m scripts.build_extraction_sheet --standard 10 --subject Science --ncert-code jesc1

# every subject of a class (no --ncert-code: one code is one book)
python -m scripts.build_extraction_sheet --standard 10 --all-subjects

# a class that isn't in chapter_master yet: 15 blank rows to fill by hand
python -m scripts.build_extraction_sheet --standard 7 --subject Science --blank 15
```

Re-running only appends chapters not already in the sheet, so a night's results
survive a rebuild.

### NCERT links

NCERT publishes one PDF per chapter at a fixed path:

```
https://ncert.nic.in/textbook/pdf/<code><chapter:02d>.pdf
```

Verified codes: `jesc1` (10 Science), `jemh1` (10 Maths), `iesc1` (9 Science),
`iemh1` (9 Maths). **Check the first link opens the book you meant** — a wrong
code yields perfectly valid PDFs of the wrong book rather than an error.

NCERT also rate-limits: ask for forty-eight PDFs back to back and it drops every
connection. During a run the fetches are twenty minutes apart and never trip it;
the runner retries four times with a growing backoff regardless.

---

## How a night is shaped

Chapters run **two at a time**, then the next two, **subject by subject** — one
subject finishes before the next begins. Three rules keep it from stalling:

- **A failed batch is retried one chapter at a time.** Two MinerU processes are
  two multi-gigabyte model loads; when the second one is what broke, running the
  same chapters singly usually works.
- **Repeated batch failures drop the run to singles permanently.** If this
  machine cannot hold two, there is no sense discovering that forty more times
  before morning.
- **Nothing stops the queue.** A dead link, a MinerU timeout, a subject that
  blows up, the database going away at 3 a.m. — each is recorded against its own
  row and the runner moves on.

### Memory

One chapter peaks around **4.4 GB resident**, so two at once needs close to 9 GB
free. The runner measures free memory before each batch and runs singly below
`--min-free-gb` (default 9). On a 16 GB desktop that means: **two at a time only
with the browser and the editor closed.** It will still finish either way, just
at half the rate.

### Resuming

Everything is resumable and nothing is ever extracted twice:

- Before each chapter the runner checks `document_extractions` for that exact
  (board, class, subject, chapter). Already extracted → skipped in milliseconds.
- A dead stub from a crashed run (status `extracting`, no content) is deleted
  rather than left to read as in-flight forever.
- A run killed mid-chapter leaves a `running` ledger entry; the next run treats
  it as retryable, not as finished.
- If MinerU succeeds but the **database write** fails, the row is marked
  `extracted`, not `failed` — the markdown is already in the on-disk extraction
  cache keyed by the PDF's hash, so a re-run re-persists it in seconds instead of
  another 40 minutes of CPU.

Windows sleep is suppressed for the duration of the run, because a machine that
suspends at 1 a.m. is the most common reason a night is half finished.

---

## Row statuses

| Status | Meaning |
|---|---|
| `pending` | Not tried yet. |
| `done` | Extracted and saved. |
| `skipped` | An extraction already existed; nothing to do. |
| `failed` | Something went wrong; `last_error` says what. Retried next run. |
| `extracted` | MinerU worked, the database write didn't. Re-run to save it, cheaply. |

A row is retired after `--max-attempts` (default 3). An incomplete row — no
`pdf_url`, no title — fails without spending an attempt, since it was never
tried, only unfilled.

---

## Tests

```bash
python tests/test_extraction_queue.py
```

Eleven checks covering batching, the serial retry, degradation, the memory
guard, the stop flag, the heartbeat, and resume-after-crash. MinerU and MariaDB
are stubbed, so it runs in under a second.
