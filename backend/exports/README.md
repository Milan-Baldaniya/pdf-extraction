# Export sheets

Workbooks meant for a person or for the LMS bulk importer -- **not** extraction
queues.

They live here rather than in `backend/queue/` on purpose: the Overnight page
lists every `*.xlsx` in that directory as a runnable queue, and these carry
entirely different columns, so each row would fail validation and the picker
would offer work that cannot run.

| File | What it is |
|---|---|
| `Class6_CBSE_Chapters.xlsx` | Class 6 chapter names for `chapter_master`, one `Import <Subject>` tab per subject matching the headers `bulk_chapter_data.php` parses |

Regenerate with:

```bash
python -m scripts.make_class6_sheet
```
