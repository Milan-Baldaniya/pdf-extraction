# PDF Extractor Setup Guide

Welcome to the **PDF Extractor** setup guide. This document explains exactly how to install, configure, and run this project locally on a brand new laptop from scratch.

If you are setting up a machine specifically to run chapters overnight, do sections 1–5 as normal, then jump to **[6. Overnight extraction](#6-overnight-extraction)**.

## Prerequisites
Before you start, ensure you have the following installed on the new laptop:
1. **[Git](https://git-scm.com/downloads)** (To clone the repository)
2. **[Python 3.11](https://www.python.org/downloads/)** (Required for the FastAPI backend and MinerU extraction logic)
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

2. **Create a Virtual Environment**:
   It's highly recommended to use a virtual environment so dependencies don't conflict.
   ```bash
   python -m venv venv
   ```

3. **Activate the Virtual Environment**:
   - **On Windows**:
     ```cmd
     venv\Scripts\activate
     ```
   - **On Mac/Linux**:
     ```bash
     source venv/bin/activate
     ```

4. **Install Python Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

5. **Configure Environment Variables**:
   Because `.env` files contain sensitive passwords, they are deliberately NOT uploaded to GitHub. Copy `backend/.env.example` to `backend/.env` and fill in the real values:

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

   > **Note:** the database is `vivek_erp`, not `sonika_erp`. The LMS owns this schema — keep `MARIADB_AUTO_CREATE_TABLES=false` so SQLAlchemy never tries to create tables in it.

---

## 3. Database

The LMS schema already exists on the shared server, so there is normally **nothing to create** — just point `.env` at it and confirm you can connect:

```bash
python -c "from app.db.mariadb import init_mariadb; print('connected' if init_mariadb() else 'FAILED')"
```

Migrations this project added live in `backend/sql/` and are applied in order if you are ever building a fresh schema.

---

## 4. Frontend Setup (Next.js)

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

## 5. Start the Application! 🎉

1. **Start the Backend** (Ensure your `venv` is active):
   ```bash
   cd backend
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

   > Run with a **single worker**. The job registry lives in process memory, so with more than one worker a status poll can land on a process that never saw the job.

2. **Start the Frontend**:
   ```bash
   cd frontend
   npm run dev
   ```

Open your web browser and go to: **[http://localhost:3000](http://localhost:3000)**

---

## 6. Overnight extraction

Extracting one chapter takes 10–25 minutes of CPU, so a class is a night's work. Instead of filling the extraction form once per chapter, a **queue sheet** lists every chapter and a runner works through it unattended.

Full reference: **[`backend/queue/README.md`](backend/queue/README.md)**. This section is just the setup.

### 6.1 One class per machine

Each class is its own sheet, and each sheet carries its own ledger, heartbeat and stop flag — so **two machines can run two classes with no coordination at all**. Nothing is shared but the database, and the runner never extracts a chapter that is already in it.

| Machine | Sheet |
|---|---|
| PC 1 | `backend/queue/class9_cbse_queue.xlsx` |
| PC 2 | `backend/queue/class10_cbse_queue.xlsx` |

Put one sheet on each machine — or just leave both, since the web page shows a **Class 9 / Class 10** picker and you start only the one you want.

### 6.2 Build the sheets

The sheets are generated from NCERT's own published catalogue, so the book codes and chapter counts are whatever NCERT publishes today:

```bash
cd backend
python -m scripts.build_ncert_sheets --class 9 --class 10 --syear 2026
```

Add `--list` to see what it would build without writing anything.

Chapter titles come from `chapter_master` where the database already has the chapter; anything else gets a provisional title like `First Flight - Chapter 3` that you can overwrite in Excel.

### 6.3 Create the master rows (once)

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

### 6.4 Run it

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

### 6.5 Before you leave for the night

1. **Close Chrome and VS Code.** Two chapters at a time needs ~9 GB free; otherwise it runs one at a time (still fine, just slower).
2. **Close the queue sheet in Excel.** Excel locks the file, so the runner can only write to the ledger. The run is unaffected and `--sync-sheet` fixes the sheet afterwards, but it is easier to just close it.
3. **Leave the machine plugged in.** The runner suppresses Windows sleep for the duration of the run, but it cannot do anything about power.

### 6.6 What it does on its own

- Two chapters at a time, then the next two, **subject by subject**.
- A batch that fails is retried **one chapter at a time**; repeated batch failures drop the run to singles for the rest of the night.
- A dead link, a MinerU timeout, or the database going away at 3 a.m. is recorded against that one row — **the queue keeps going**.
- Chapters already in `document_extractions` are skipped in milliseconds, so re-running costs nothing.
- If MinerU succeeds but the database write fails, the row is marked `extracted` and a re-run saves it from cache in **seconds**, not another 40 minutes.

### 6.7 Scope

Extraction only: PDF → markdown row in `document_extractions`. The DeepSeek stages (curriculum, units, topics, concepts) are deliberately **not** run overnight — they cost money per call and write into the live LMS tables. Run those from the **Chapters queue** in the morning, on what you can see landed.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `MinerU CLI was not found` | `pip install magic-pdf[full]` inside the activated venv. |
| Overnight page says **"No queue sheet on this machine"** | Build one: `python -m scripts.build_ncert_sheets --class 10`. |
| Overnight page says **"Ended unexpectedly"** | The machine slept or was shut down. Finished chapters are safe; press Start again and it resumes. |
| Sheet shows nothing but the ledger has runs | The sheet was open in Excel. Close it and run `python -m scripts.run_extraction_queue --sync-sheet --sheet <sheet>`. |
| Everything is `skipped` | Those chapters are already extracted. Use `--force` only if you really want to redo them. |
| NCERT downloads fail in bursts | `ncert.nic.in` rate-limits. The runner already retries 4× with a growing backoff; during a real night the fetches are 20 minutes apart and never trip it. |
| Rows stored with NULL ids | Run section 6.3. |
