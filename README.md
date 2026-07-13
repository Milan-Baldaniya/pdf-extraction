# NCERT Educational PDF Intelligence

A full-stack document intelligence app for extracting structured educational
content from NCERT PDFs. The backend runs a CPU-friendly MinerU pipeline for
OCR, layout, tables, formulas, images, and education-aware diagnostics. The
frontend provides a Next.js interface for URL extraction, PDF upload, layout
preview, markdown/JSON inspection, diagnostics, and optional DeepSeek-powered
semantic intelligence.

## Current Capabilities

- Extract PDFs from a public URL or local upload.
- Run MinerU in CPU pipeline mode with OCR, table parsing, formula parsing, and
  image asset extraction.
- Retry extraction across quality passes when `MINERU_QUALITY_MODE=max`.
- Cache extraction responses by file hash.
- Serve extracted image assets through the API.
- Show job status from in-memory status tracking.
- Normalize output into markdown, layout blocks, educational outline,
  educational sections, assets, and diagnostics.
- Generate chapter-level semantic intelligence with DeepSeek and persist it in
  Supabase when configured.
- Keep legacy `/phase2/...` semantic routes available as hidden aliases for old
  clients.

## Project Structure

```text
pdf extraction/
|-- backend/
|   |-- app/
|   |   |-- api/routes.py                     # Extraction, upload, assets, status
|   |   |-- db/supabase_client.py             # Optional Supabase client
|   |   |-- extraction/                       # Cache, status, education structure
|   |   |-- models/schemas.py                 # Pydantic API schemas
|   |   |-- semantic_intelligence/            # DeepSeek prompts, parser, API routes
|   |   |-- services/mineru_service.py        # CPU MinerU extraction pipeline
|   |   |-- services/pdf_service.py           # Async PDF download
|   |   |-- utils/config.py                   # Environment settings
|   |   `-- main.py                           # FastAPI app entry point
|   |-- .env.example
|   |-- download_models.py                    # Downloads MinerU model files
|   |-- requirements.txt
|   `-- README.md
|
|-- frontend/
|   |-- src/app/                              # Next.js app shell
|   |-- src/components/                       # Extraction form/viewer and UI
|   |-- src/lib/api.ts                        # API client
|   |-- package.json
|   `-- README.md
|
`-- README.md
```

Generated/runtime folders such as `backend/venv`, `backend/output`,
`backend/tmp`, `backend/models`, `backend/logs`, `frontend/node_modules`, and
`frontend/.next` are not source code.

## Tech Stack

| Layer | Technology |
| --- | --- |
| Backend | FastAPI, Python, Uvicorn, Pydantic |
| Extraction | MinerU / `magic-pdf[full]`, CPU pipeline backend |
| Semantic AI | DeepSeek via `openai` SDK |
| Persistence | Optional Supabase table for semantic intelligence |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS 4 |
| UI/Data | shadcn-style components, lucide-react, React Query, Axios |

## Prerequisites

- Python 3.10+ or 3.11+
- Node.js 20+ recommended for the current Next.js version
- Enough disk space for MinerU dependencies and model weights
- Optional: DeepSeek API key and Supabase project for semantic intelligence

## Backend Setup

```powershell
cd "C:\Users\MILAN\Downloads\pdf extraction\backend"

python -m venv venv
.\venv\Scripts\Activate.ps1

pip install -r requirements.txt
copy .env.example .env
```

Download and configure MinerU model files:

```powershell
python download_models.py
```

The script downloads `opendatalab/PDF-Extract-Kit-1.0` into
`backend/models/PDF-Extract-Kit-1.0` and writes `magic-pdf.json` in your user
home directory with CPU settings.

Start the backend:

```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open the API docs at `http://127.0.0.1:8000/docs`.

## Backend Environment

The backend reads `backend/.env`. Start from `backend/.env.example`.

```env
HOST=0.0.0.0
PORT=8000
DEBUG=true
FRONTEND_URL=http://localhost:3000

TEMP_DIR=./tmp/ncert
OUTPUT_DIR=./output

MINERU_BACKEND=pipeline
MINERU_METHOD=auto
MINERU_LANG=devanagari
MINERU_SERVER_URL=
MINERU_FORMULA=true
MINERU_TABLE=true
MINERU_IMAGE_ANALYSIS=false
MINERU_CPU_THREADS=4
MINERU_TIMEOUT_SECONDS=3600
MINERU_QUALITY_MODE=max
MINERU_OCR_FALLBACK=true

SEMANTIC_INTELLIGENCE_PROMPT_VERSION=1
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-v4-pro
SUPABASE_URL=
SUPABASE_SERVICE_KEY=
```

Notes:

- `MINERU_BACKEND` should stay `pipeline` for this CPU-oriented build.
- `MINERU_SERVER_URL` should stay empty; remote VLM servers are disabled here.
- `MINERU_LANG=devanagari` is useful for Hindi/mixed NCERT PDFs. Use `en` for
  English-only documents, or `auto` to let the service sample the PDF.
- DeepSeek and Supabase values are only required for the Semantic AI tab and
  `/semantic-intelligence/*` endpoints.

## Frontend Setup

```powershell
cd "C:\Users\MILAN\Downloads\pdf extraction\frontend"
npm install
npm run dev
```

Create or update `frontend/.env.local` if the backend URL changes:

```env
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000/api
```

Open `http://localhost:3000`.

## API Reference

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/api/health` | Service health check |
| GET | `/api/status/{job_id}` | Latest in-memory extraction status |
| GET | `/api/assets/{job_id}/{asset_path}` | Serve an extracted image asset |
| POST | `/api/generate-chapter-ppt` | Download a PDF URL and extract content |
| POST | `/api/upload-chapter-ppt` | Upload a local PDF and extract content |
| POST | `/semantic-intelligence/generate` | Generate DeepSeek semantic intelligence |
| GET | `/semantic-intelligence/chapter/{chapter_id}` | Fetch latest stored chapter intelligence |

Hidden compatibility aliases also exist under `/phase2/generate` and
`/phase2/chapter/{chapter_id}`.

### URL Extraction Request

```json
{
  "pdf_url": "https://ncert.nic.in/textbook/pdf/iesc101.pdf"
}
```

### Extraction Response Shape

```json
{
  "status": "success",
  "processing_mode": "cpu-mineru-pipeline",
  "markdown_content": "# Chapter ...",
  "json_content": {
    "pages": [],
    "blocks": [],
    "educational_outline": [],
    "educational_sections": [],
    "educational_assets": {},
    "asset_manifest": []
  },
  "metadata": {
    "job_id": "example",
    "cached": false,
    "method_used": "ocr",
    "educational_structure_score": 0
  },
  "page_count": 1,
  "images_extracted": 0
}
```

### Semantic Intelligence Request

Provide either `markdown_content` or `markdown_file_path`.

```json
{
  "standard_id": 10,
  "subject_id": 1,
  "chapter_id": 101,
  "subject_name": "Science",
  "class_level": "Class 10",
  "markdown_content": "# Chapter markdown...",
  "pdf_cache_id": null,
  "force_regenerate": false
}
```

The semantic pipeline performs a two-pass DeepSeek extraction: first it builds a
chapter skeleton, then it extracts each teaching unit in parallel. Output is
validated with Pydantic, summarized, quality-flagged as `good`, `needs_review`,
or `regenerate`, and upserted into Supabase.

Expected Supabase table: `chapter_semantic_intelligence`. The backend upserts on
`chapter_id,prompt_version`.

## Frontend Workflow

1. Choose `URL` or `Upload` in the PDF Source panel.
2. Run extraction and wait for MinerU to finish.
3. Inspect the result in these tabs:
   - `Layout`: page-like layout reconstruction from detected blocks.
   - `Rendered`: rendered markdown.
   - `Raw`: raw markdown.
   - `JSON`: normalized extraction JSON.
   - `Diagnostics`: metadata, outline, sections, assets, and quality passes.
   - `Semantic AI`: DeepSeek semantic intelligence, if backend credentials exist.
4. Copy or download the active result tab.

## Development Notes

- The root folder is not currently a git repository, but `frontend/` contains a
  nested `.git` directory.
- `backend/test_api.py` is stale: it posts to `/api/extract`, while the current
  extraction routes are `/api/generate-chapter-ppt` and
  `/api/upload-chapter-ppt`.
- Long-running extraction is expected. The frontend Axios client has no timeout
  and the backend default MinerU timeout is 3600 seconds.
- The semantic frontend demo currently sends hard-coded subject/class values and
  a random `chapter_id`; wire those to real chapter metadata before production
  use.

