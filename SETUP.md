# PDF Extractor Setup Guide

Welcome to the **PDF Extractor** setup guide. This document explains exactly how to install, configure, and run this project locally on a brand new laptop from scratch.

## Prerequisites
Before you start, ensure you have the following installed on the new laptop:
1. **[Git](https://git-scm.com/downloads)** (To clone the repository)
2. **[Python 3.9+](https://www.python.org/downloads/)** (Required for the FastAPI backend and MinerU extraction logic)
3. **[Node.js 18+](https://nodejs.org/en/)** (Required for the Next.js frontend)
4. **MariaDB & HeidiSQL** (Or you can simply use HeidiSQL to connect to your remote MariaDB server at `202.47.117.220`)

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
   Because `.env` files contain sensitive passwords, they are deliberately NOT uploaded to GitHub. You must create a new file named `.env` inside the `backend` folder on the new laptop and paste the following:
   
   ```env
   # Server Configuration
   HOST=0.0.0.0
   PORT=8000
   DEBUG=true
   FRONTEND_URL=http://localhost:3000

   # MariaDB Configuration
   MARIADB_HOST=202.47.117.220
   MARIADB_PORT=3306
   MARIADB_USER=sonika_user
   MARIADB_PASSWORD=sonika@sql
   MARIADB_DB=sonika_erp

   # Gemini API Keys
   GEMINI_API_KEY=your_primary_key_here
   GEMINI_API_KEY2=your_key_here
   GEMINI_API_KEY3=your_key_here
   GEMINI_API_KEY4=your_key_here
   GEMINI_API_KEY5=your_key_here
   GEMINI_API_KEY6=your_key_here
   GEMINI_API_KEY7=your_key_here
   GEMINI_API_KEY8=your_key_here

   # MinerU Local Config
   MINERU_BACKEND=pipeline
   MINERU_METHOD=auto
   MINERU_LANG=devanagari
   ```

---

## 3. Database Setup (HeidiSQL)
Before starting the backend, make sure your database table exists. Open HeidiSQL, connect to `sonika_erp`, and run the following query in a new query tab to create your table:

```sql
CREATE TABLE IF NOT EXISTS `document_extractions` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `document_type` VARCHAR(255) NULL,
  `document_tittle` VARCHAR(255) NULL,
  `chapter_number` INT NULL,
  `standard` INT NULL,
  `subject_name` VARCHAR(255) NULL,
  `board` VARCHAR(255) NULL,
  `syear` VARCHAR(255) NULL,
  `pdf_url` TEXT NULL,
  `md_content` LONGTEXT NULL,
  `json_content` JSON NULL,
  `page_count` INT NULL,
  `image_extracted` INT NULL,
  `extraction_metadata` JSON NULL,
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

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

2. **Start the Frontend**:
   ```bash
   cd frontend
   npm run dev
   ```

Open your web browser and go to: **[http://localhost:3000](http://localhost:3000)**

You should see the floating liquid-glass navbar and extraction form! Any PDFs you extract will now automatically be processed by MinerU and inserted directly into your `sonika_erp` MariaDB table via SQLAlchemy!
