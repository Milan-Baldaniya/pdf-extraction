# PDF Extractor Setup Guide

Welcome to the **PDF Extractor** setup guide. This document explains exactly how to install, configure, and run this project locally on a brand new laptop from scratch.

If you are setting up a machine specifically to run chapters overnight, do sections 1–6 as normal, then jump to **[7. Overnight extraction](#7-overnight-extraction)**.

## Prerequisites
Before you start, ensure you have the following installed on the new laptop:
1. **[Git](https://git-scm.com/downloads)** (To clone the repository)
2. **[Python 3.12 (64-bit)](https://www.python.org/downloads/windows/)** (Use 3.12 for the pinned backend and MinerU dependencies; Python 3.14 triggers incompatible source builds.)
3. **[Node.js 18+](https://nodejs.org/en/)** (Required for the Next.js frontend)
4. **MariaDB & HeidiSQL** (Or you can simply use HeidiSQL to connect to your remote MariaDB server at `202.47.117.220`)

**For an overnight extraction machine, also check:** at least **16 GB RAM** and, ideally, nothing else running. MinerU holds about **4.4 GB** per chapter, so two chapters at a time needs roughly **9 GB free**. It works with less — it just drops to one chapter at a time.

---

## 1. Clone the Repository
Open your terminal (or command prompt) and clone your code from GitHub:

```bash
git clone https://github.com/Milan-Baldaniya/pdf-extraction.git
cd pdf-extraction
```

*(Note: We recommend opening the new `pdf_extraction.code-workspace` file in VS Code to easily manage both frontend and backend without Python path errors!)*

---

## 2. Backend Setup (FastAPI)

The backend processes the PDFs, communicates with MariaDB, and uses MinerU.

1. **Navigate to the backend folder**:
   ```bash
   cd backend
   ```

2. **Install Python 3.12 and create a Virtual Environment**:
   On Windows PowerShell:
   ```powershell
   winget install --id Python.Python.3.12 --exact --source winget --scope user
   py -3.12 -m venv venv
   ```
   If `venv` was created with Python 3.14, first run `deactivate` in the terminal
   where it is active, rename it to `venv-py314-backup`, then create `venv` again
   using the command above. Installing Python does not change an existing venv.
   On macOS/Linux, use `python3.12 -m venv venv`.

   > On Windows you can also just run `.\rebuild_venv.ps1`, which does all of the
   > above and verifies the result with `pip check`.

3. **Activate the Virtual Environment**:
   - **On Windows PowerShell**:
     ```powershell
     .\venv\Scripts\Activate.ps1
     ```
   - **On Mac/Linux**:
     ```bash
     source venv/bin/activate
     ```

4. **Install Python Dependencies**:
   ```bash
   python --version
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```
   Confirm the version is `Python 3.12.x` before installing dependencies.

   > `requirements.txt` pins `numpy<2` on purpose: the MinerU 1.3.3 stack is built
   > against NumPy 1.x. Do not upgrade it.

---

## 3. Download the MinerU models

From `backend`, with the environment active:

```powershell
python download_models.py
python -m pip check
```

Downloads require internet access and several GB of disk space. The script stores
weights in `backend/models/PDF-Extract-Kit-1.0` and writes the CPU configuration
to `%USERPROFILE%\magic-pdf.json`. Wait for it to finish before extracting a PDF.
Rerunning reuses previously downloaded files.

> The model snapshot revision is **pinned** in `download_models.py`. Later
> snapshots drop the v3/v4 OCR weights magic-pdf 1.3.3 needs and replace them
> with incompatible v5 recognizers, so do not "update" it casually.

---

## 4. Configure Environment Variables

Because `.env` files contain sensitive passwords, they are deliberately NOT
uploaded to GitHub. Copy `backend/.env.example` to `backend/.env` and fill in the
real values:

```bash
copy .env.example .env      # Windows
cp .env.example .env        # Mac/Linux
```

The settings that matter most:

```env
# Server
HOST=0.0.0.0
PORT=8000
FRONTEND_URL=http://localhost:3000

# MariaDB -- ask a teammate for the password, it is not in the repository
MARIADB_HOST=202.47.117.220
MARIADB_PORT=3306
MARIADB_USER=sonika_user
MARIADB_PASSWORD=<ask a teammate>
MARIADB_DB=vivek_erp
MARIADB_AUTO_CREATE_TABLES=false

# Board -> shared content-bank tenant (sub_institute_id is a BOARD id here)
BOARD_TENANT_MAP=cbse=1,cambridge=341
DEFAULT_SUB_INSTITUTE_ID=1

# DeepSeek (only needed for the concept/curriculum stages, NOT for extraction)
DEEPSEEK_API_KEY=<your key>

# MinerU -- CPU pipeline. Do not use CUDA/VLM backends here.
MINERU_BACKEND=pipeline
MINERU_METHOD=auto
MINERU_LANG=devanagari
MINERU_CPU_THREADS=4
MINERU_TIMEOUT_SECONDS=3600
MINERU_QUALITY_MODE=max
```

> **Note:** the database is `vivek_erp`, not `sonika_erp`. The LMS owns this
> schema — keep `MARIADB_AUTO_CREATE_TABLES=false` so SQLAlchemy never tries to
> create tables in it.

The LMS schema already exists on the shared server, so there is normally
**nothing to create**. Confirm you can connect:

```bash
python -c "from app.db.mariadb import init_mariadb; print('connected' if init_mariadb() else 'FAILED')"
```

Migrations this project added live in `backend/sql/` and are applied in order if
you are ever building a fresh schema.

---

## 5. Frontend Setup (Next.js)

The frontend contains the modern iOS liquid-glass UI.

1. **Open a new terminal window** and navigate to the frontend folder:
   ```bash
   cd frontend
   ```

2. **Install Node Modules**:
   ```bash
   npm install
   ```

3. **Configure Environment Variables**:
   Just like the backend, you must create a new file named `.env.local` inside the `frontend` folder:
   ```env
   NEXT_PUBLIC_API_URL=http://127.0.0.1:8000/api
   ```

---

## 6. Start the Application! 🎉

1. **Start the Backend** (Ensure your `venv` is active):
   ```bash
   cd backend
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

   > Run with a **single worker**. The job registry lives in process memory, so
   > with more than one worker a status poll can land on a process that never saw
   > the job.

2. **Start the Frontend**:
   ```bash
   cd frontend
   npm run dev
   ```

Open your web browser and go to: **[http://localhost:3000](http://localhost:3000)**

---

## 7. Overnight extraction

Extracting one chapter takes 10–25 minutes of CPU, so a class is a night's work. Instead of filling the extraction form once per chapter, a **queue sheet** lists every chapter and a runner works through it unattended.

Full reference: **[`backend/queue/README.md`](backend/queue/README.md)**. This section is just the setup.

### 7.1 One class per machine

Each class is its own sheet, and each sheet carries its own ledger, heartbeat and stop flag — so **two machines can run two classes with no coordination at all**. Nothing is shared but the database, and the runner never extracts a chapter that is already in it.

| Machine | Sheet |
|---|---|
| PC 1 | `backend/queue/class9_cbse_queue.xlsx` |
| PC 2 | `backend/queue/class10_cbse_queue.xlsx` |

Put one sheet on each machine — or just leave both, since the web page shows a **Class 9 / Class 10** picker and you start only the one you want.

### 7.2 Build the sheets

The sheets are generated from NCERT's own published catalogue, so the book codes and chapter counts are whatever NCERT publishes today:

```bash
cd backend
python -m scripts.build_ncert_sheets --class 9 --class 10 --syear 2026
```

Add `--list` to see what it would build without writing anything.

Chapter titles come from `chapter_master` where the database already has the chapter; anything else gets a provisional title like `First Flight - Chapter 3` that you can overwrite in Excel.

### 7.3 Create the master rows (once)

Extraction stores `standard_id`, `subject_id` and `chapter_id` next to the markdown, derived from the names in the sheet. **A name that matches nothing is not an error** — the row saves with a NULL id and the chapter becomes invisible to everything that looks it up by class and subject.

Check first, write second:

```bash
python -m scripts.run_extraction_queue --sheet queue/class9_cbse_queue.xlsx --list
```

It ends with either `Every row resolves to a standard, subject and chapter.` or a count of rows that would be stored with a NULL id. To create what is missing:

```bash
python -m scripts.seed_master_from_sheet                 # dry run, writes nothing
python -m scripts.seed_master_from_sheet --apply         # insert
```

It creates `subject`, `sub_std_map` and `chapter_master` rows following the same sequence the "Others" option on the extraction form uses, so a subject created here is indistinguishable from one created through the UI. Every insert is recorded to `queue/seed_<timestamp>.json`, so it is reversible:

```bash
python -m scripts.seed_master_from_sheet --rollback queue/seed_20260917_190000.json
```

### 7.4 Run it

**From the web app** (recommended) — **Home → Overnight Extraction**, or `/overnight`:

- **Start overnight run** — runs until the queue is empty. There is **no automatic stop**.
- **Stop after this chapter** — finishes what is in flight, saves it, then stops. It never kills MinerU mid-chapter, because that would throw away up to 40 minutes of CPU and strand a row stamped `extracting`.
- The page shows what is extracting right now, and a plain-language report of every night with the full log underneath.

Closing the browser does **not** stop the run — it is a detached process and survives the API restarting.

**Or from the command line:**

```bash
scripts\run_overnight.bat                                   # double-clickable
python -m scripts.run_extraction_queue --sheet queue/class9_cbse_queue.xlsx
```

### 7.5 Before you leave for the night

1. **Close Chrome and VS Code.** Two chapters at a time needs ~9 GB free; otherwise it runs one at a time (still fine, just slower).
2. **Close the queue sheet in Excel.** Excel locks the file, so the runner can only write to the ledger. The run is unaffected and `--sync-sheet` fixes the sheet afterwards, but it is easier to just close it.
3. **Leave the machine plugged in.** The runner suppresses Windows sleep for the duration of the run, but it cannot do anything about power.

### 7.6 What it does on its own

- Two chapters at a time, then the next two, **subject by subject**.
- A batch that fails is retried **one chapter at a time**; repeated batch failures drop the run to singles for the rest of the night.
- A dead link, a MinerU timeout, or the database going away at 3 a.m. is recorded against that one row — **the queue keeps going**.
- Chapters already in `document_extractions` are skipped in milliseconds, so re-running costs nothing.
- If MinerU succeeds but the database write fails, the row is marked `extracted` and a re-run saves it from cache in **seconds**, not another 40 minutes.

### 7.7 Scope

Extraction only: PDF → markdown row in `document_extractions`. The DeepSeek stages (curriculum, units, topics, concepts) are deliberately **not** run overnight — they cost money per call and write into the live LMS tables. Run those from the **Chapters queue** in the morning, on what you can see landed.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Source builds / wheel errors on install | You are on Python 3.14 or 3.13. Use **3.12** — see section 2. |
| `MinerU CLI was not found` | `pip install magic-pdf[full]` inside the activated venv, then rerun `python download_models.py`. |
| OCR fails or produces nonsense | The model snapshot was updated past the pinned revision. Delete `backend/models/PDF-Extract-Kit-1.0` and rerun `python download_models.py`. |
| `pip check` reports numpy conflicts | Something upgraded NumPy past 2.0. `pip install "numpy>=1.26.4,<2"`. |
| Overnight page says **"No queue sheet on this machine"** | Build one: `python -m scripts.build_ncert_sheets --class 10`. |
| Overnight page says **"Ended unexpectedly"** | The machine slept or was shut down. Finished chapters are safe; press Start again and it resumes. |
| Sheet shows nothing but the ledger has runs | The sheet was open in Excel. Close it and run `python -m scripts.run_extraction_queue --sync-sheet --sheet <sheet>`. |
| Everything is `skipped` | Those chapters are already extracted. Use `--force` only if you really want to redo them. |
| NCERT downloads fail in bursts | `ncert.nic.in` rate-limits. The runner already retries 4× with a growing backoff; during a real night the fetches are 20 minutes apart and never trip it. |
| Rows stored with NULL ids | Run section 7.3. |
