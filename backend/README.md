# NCERT Educational PDF Intelligence Backend

FastAPI backend for CPU-friendly NCERT PDF extraction with MinerU pipeline.

This build intentionally avoids CUDA-only VLM inference and remote GPU servers.
It uses MinerU pipeline mode with OCR, table parsing, formula parsing, image
asset extraction, layout-aware JSON normalization, and educational structure
diagnostics.

## Run

```powershell
cd "C:\Users\MILAN\Downloads\pdf extraction\backend"
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## CPU MinerU Settings

```env
MINERU_BACKEND=pipeline
MINERU_METHOD=auto
MINERU_LANG=devanagari
MINERU_SERVER_URL=
MINERU_FORMULA=true
MINERU_TABLE=true
MINERU_IMAGE_ANALYSIS=false
MINERU_CPU_THREADS=4
MINERU_TIMEOUT_SECONDS=3600
```

Use `MINERU_LANG=en` for English-only OCR, or `devanagari` for Hindi/mixed
Hindi-English NCERT PDFs. `MINERU_METHOD=auto` lets MinerU choose text parsing
or OCR; if that attempt fails, the service retries with `ocr`.

## API

| Method | Endpoint                    | Description |
| ------ | --------------------------- | ----------- |
| GET    | `/api/health`               | Health check |
| GET    | `/api/status/{job_id}`      | In-memory extraction status |
| GET    | `/api/assets/{job_id}/...`  | Extracted image assets |
| POST   | `/api/generate-chapter-ppt` | Extract markdown, JSON, assets, metadata |
| POST   | `/semantic-intelligence/generate` | Generate Gemini educational semantics |
| GET    | `/semantic-intelligence/chapter/{chapter_id}` | Read latest chapter semantics |

Legacy `/phase2/...` semantic-intelligence routes are still mounted as hidden
aliases so older clients continue to work.

## Output Profile

The response uses `processing_mode: "cpu-mineru-pipeline"` and includes:

- `markdown_content`
- `json_content.pages`
- `json_content.blocks`
- `json_content.educational_outline`
- `json_content.educational_assets`
- extraction metadata and diagnostics

The architecture is ready for later semantic layers such as Gemini structuring,
Gamma presentation generation, lesson planning, quizzes, and knowledge graphs.

## Semantic Intelligence Module

`app/semantic_intelligence` contains the Gemini prompt, client, parser, and API
routes for chapter-level educational semantic intelligence. It replaces the old
`phase2` package name with a responsibility-based production name.
