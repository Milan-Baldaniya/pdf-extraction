-- Phase 3: Teaching Intelligence Table
-- Run this SQL in Supabase SQL Editor before using the Phase 3 endpoints.
-- Dashboard → SQL Editor → New Query → paste → Run.

CREATE TABLE IF NOT EXISTS public.teaching_intelligence (
  id                   BIGSERIAL PRIMARY KEY,

  -- Link to Phase 2 record that generated this
  semantic_id          BIGINT REFERENCES chapter_semantic_intelligence(id) ON DELETE CASCADE,

  -- ERP identifiers — passed through from Phase 2
  standard_id          INTEGER NOT NULL,
  subject_id           INTEGER NOT NULL,
  chapter_id           INTEGER NOT NULL,

  -- Teaching style parameters
  language             VARCHAR(20) NOT NULL DEFAULT 'english'
    CHECK (language IN ('english', 'hindi', 'bilingual')),

  teaching_style       VARCHAR(30) NOT NULL DEFAULT 'engaging'
    CHECK (teaching_style IN (
      'engaging',
      'storytelling',
      'serious',
      'activity_based',
      'exam_focused'
    )),

  difficulty_level     VARCHAR(20) NOT NULL DEFAULT 'grade_level'
    CHECK (difficulty_level IN (
      'simplified',
      'grade_level',
      'advanced'
    )),

  -- The complete Phase 3 output from Gemini
  full_teaching_json   JSONB NOT NULL,

  -- How many slide plans were generated
  total_slides_planned INTEGER,

  -- LLM tracking
  llm_model            VARCHAR(100),
  prompt_version       INTEGER NOT NULL DEFAULT 1,
  input_tokens         INTEGER,
  output_tokens        INTEGER,

  created_at           TIMESTAMPTZ DEFAULT NOW()
) TABLESPACE pg_default;

-- Fast lookup by chapter
CREATE INDEX IF NOT EXISTS idx_teaching_chapter
ON public.teaching_intelligence(standard_id, subject_id, chapter_id);

-- Fast lookup by chapter + style combination (most common query)
CREATE INDEX IF NOT EXISTS idx_teaching_style
ON public.teaching_intelligence(chapter_id, teaching_style, language, difficulty_level);

-- Link to Phase 2
CREATE INDEX IF NOT EXISTS idx_teaching_semantic
ON public.teaching_intelligence(semantic_id);

-- GIN index for searching inside the teaching JSON
CREATE INDEX IF NOT EXISTS idx_teaching_json
ON public.teaching_intelligence USING GIN (full_teaching_json);

-- Unique: one record per chapter per style combination per prompt version
CREATE UNIQUE INDEX IF NOT EXISTS idx_teaching_unique
ON public.teaching_intelligence(
  chapter_id, language, teaching_style, difficulty_level, prompt_version
);
