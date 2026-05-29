# PDF Extractor Setup Guide

Welcome to the **PDF Extractor** setup guide. This document explains exactly how to install, configure, and run this project locally on a fresh laptop.

## Prerequisites
Before you start, ensure you have the following installed on the new laptop:
1. **[Git](https://git-scm.com/downloads)** (To clone the repository)
2. **[Python 3.9+](https://www.python.org/downloads/)** (Required for the FastAPI backend and MinerU logic)
3. **[Node.js 18+](https://nodejs.org/en/)** (Required for the Next.js frontend)

---

## 1. Clone the Repository
Open your terminal (or command prompt) and clone your code from GitHub:

```bash
git clone https://github.com/Milan-Baldaniya/pdf-extraction.git
cd pdf-extraction
```

---

## 2. Backend Setup (FastAPI)

The backend processes the PDFs, communicates with Supabase, and uses MinerU.

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
   Create a new file named `.env` inside the `backend` folder and add the following required keys (ask Milan for the actual keys if you do not have them):
   
   ```env
   # Server Configuration
   HOST=0.0.0.0
   PORT=8000
   DEBUG=true
   FRONTEND_URL=http://localhost:3000

   # Supabase Credentials (Required for saving extractions)
   SUPABASE_URL=your_supabase_url
   SUPABASE_SERVICE_KEY=your_supabase_service_role_key

   # Gemini Configuration
   GEMINI_API_KEY=your_gemini_key

   # MinerU Local Config
   MINERU_BACKEND=pipeline
   MINERU_METHOD=auto
   ```

6. **Start the Backend Server**:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
   *The backend will now be running on `http://127.0.0.1:8000`.*

---

## 3. Frontend Setup (Next.js)

The frontend contains the modern iOS liquid-glass UI.

1. **Open a new terminal window** (leave the backend running in the first one) and navigate to the frontend folder:
   ```bash
   cd frontend
   ```

2. **Install Node Modules**:
   ```bash
   npm install
   ```

3. **Configure Environment Variables**:
   Create a file named `.env.local` inside the `frontend` folder and link it to the local backend:
   ```env
   NEXT_PUBLIC_API_URL=http://127.0.0.1:8000/api
   ```

4. **Start the Frontend Development Server**:
   ```bash
   npm run dev
   ```

---

## 4. You're Ready! 🎉
Open your web browser and go to:
**[http://localhost:3000](http://localhost:3000)**

You should see the floating liquid-glass navbar and extraction form!
- Any PDFs you extract will communicate with `http://localhost:8000`.
- Extracted metadata, markdown, and JSON will automatically be stored inside your Supabase `document_extractions` table!
