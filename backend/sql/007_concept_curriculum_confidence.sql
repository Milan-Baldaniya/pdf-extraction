-- Concept curriculum mapping and confidence (MariaDB / vivek_erp).
--
-- Three things this adds, all of which the pipeline previously computed and
-- then threw away or never computed at all:
--
--   1. EVIDENCE. Both extraction queues already ask the model for an exact
--      source_evidence quote and already verify it against the chapter
--      (ct.verify_grounding). Neither ever persisted the quote or the verdict,
--      so the one hard, checkable signal about a row was discarded at INSERT.
--
--   2. CONFIDENCE. There was no confidence on a concept or a topic anywhere.
--      confidence is the score, confidence_profile says which weighting
--      produced it (a chapter with no curriculum must not be scored as though
--      it FAILED curriculum anchoring), and confidence_parts keeps the named
--      components so a low score is explainable rather than magic.
--
--   3. CURRICULUM. lms_learning_outcomes has held the CG -> C -> LO tree since
--      the curriculum queue shipped, and no generation stage has ever read it.
--      lms_concept_outcome is the mapping from a concept to the curricular
--      goals and competencies it serves.
--
-- Plus concept_show_hide, which is what lets lms_concept stop being
-- DELETE-then-INSERT. Today every re-run churns lms_concept.id, and those ids
-- are referenced by lms_question_master, lms_question_extraction,
-- lms_lesson_plan_concepts and lms_lesson_plan_periods. On this database that
-- has already orphaned 132 lesson-plan concept rows, 60 period rows and 21
-- question rows. topic_master solved the same problem years ago by retiring
-- rather than deleting; this column lets lms_concept do the same.
--
-- app.services.extraction_schema.ensure_extraction_schema() applies every
-- change here at runtime, so this file is only needed for an explicit
-- migration. It runs from init_mariadb() on boot AND as step 0 of the chapter
-- job, because a column missing at INSERT time fails AFTER the whole LLM
-- fan-out has been paid for.

-- ---------------------------------------------------------------------------
-- lms_concept
-- ---------------------------------------------------------------------------
-- definition is a NEW field, not a rename of description. description stays
-- short (1-2 sentences) and is written by the generation stage, because
-- semantic_intelligence/pipeline.py hands it to the four agents. definition is
-- the fuller teaching definition written later by the enrichment stage.
ALTER TABLE lms_concept
  ADD COLUMN definition TEXT NULL AFTER description;

-- utf8mb4 pinned explicitly: the server default is latin1 and these quotes
-- carry Devanagari, Gujarati and typographic punctuation.
ALTER TABLE lms_concept
  ADD COLUMN source_evidence VARCHAR(512)
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL;

ALTER TABLE lms_concept
  ADD COLUMN evidence_verified TINYINT(1) NOT NULL DEFAULT 0;

-- DECIMAL(4,3) matches lms_question_extraction.concept_confidence, the only
-- other calibrated confidence in this schema.
ALTER TABLE lms_concept
  ADD COLUMN confidence DECIMAL(4,3) NULL;

ALTER TABLE lms_concept
  ADD COLUMN confidence_profile VARCHAR(24) NULL
    COMMENT 'content | curriculum | deterministic_backfill';

ALTER TABLE lms_concept
  ADD COLUMN confidence_parts LONGTEXT
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL
    COMMENT 'JSON: the named components behind confidence';

-- Defaults to 'legacy' while new code writes 'auto_accepted', so the DEFAULT
-- labels exactly the rows nobody ever scored.
ALTER TABLE lms_concept
  ADD COLUMN review_status VARCHAR(16) NOT NULL DEFAULT 'legacy'
    COMMENT 'legacy | auto_accepted | flagged | low_confidence';

ALTER TABLE lms_concept
  ADD COLUMN concept_show_hide TINYINT(1) NOT NULL DEFAULT 1;

-- The authoritative "has the enrichment stage run on this row" test.
-- mastery_threshold cannot serve: it is double(8,2) NOT NULL and owned by the
-- ERP, so the generation stage writes a 0.00 sentinel rather than altering it.
ALTER TABLE lms_concept
  ADD COLUMN enriched_at TIMESTAMP NULL;

ALTER TABLE lms_concept
  ADD INDEX idx_concept_ext_topic (extraction_id, topic_id);

-- ---------------------------------------------------------------------------
-- topic_master
-- ---------------------------------------------------------------------------
-- Shared with the rest of the ERP, so additive nullable columns only.
ALTER TABLE topic_master
  ADD COLUMN source_evidence VARCHAR(512)
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL;

ALTER TABLE topic_master
  ADD COLUMN evidence_verified TINYINT(1) NOT NULL DEFAULT 0;

ALTER TABLE topic_master
  ADD COLUMN confidence DECIMAL(4,3) NULL;

-- ---------------------------------------------------------------------------
-- chapter_master
-- ---------------------------------------------------------------------------
ALTER TABLE chapter_master
  ADD COLUMN extraction_confidence DECIMAL(4,3) NULL AFTER no_of_periods;

-- The budget this chapter was actually given, kept so a count can be explained
-- months later: which anchor fired, what the target was, what got trimmed.
ALTER TABLE chapter_master
  ADD COLUMN concept_budget LONGTEXT
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL;

-- ---------------------------------------------------------------------------
-- lms_learning_outcomes
-- ---------------------------------------------------------------------------
-- Every chapter job now reads this table by (chapter_id, type).
ALTER TABLE lms_learning_outcomes
  ADD INDEX idx_lo_chapter_type (chapter_id, type);

-- ---------------------------------------------------------------------------
-- lms_concept_outcome
-- ---------------------------------------------------------------------------
-- No foreign key on outcome_id, and that is deliberate. curriculum_service's
-- save_learning_outcomes() runs
--     DELETE FROM lms_learning_outcomes WHERE curriculum_id = :cid
-- on every re-process, so outcome_id is a dangling reference BY DESIGN. The
-- durable key is (curriculum_id, outcome_code); resync_outcome_ids() re-links
-- the ids after each curriculum re-process.
--
-- No foreign key on concept_id either, matching the convention of every recent
-- table in this schema: the referents are soft-deleted and some carry
-- MyISAM-era ids.
CREATE TABLE IF NOT EXISTS lms_concept_outcome (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  concept_id     BIGINT UNSIGNED NOT NULL,
  outcome_id     BIGINT UNSIGNED NULL
                 COMMENT 'lms_learning_outcomes.id; stale after a curriculum re-process',
  outcome_type   VARCHAR(20) NOT NULL COMMENT 'goal | competency | learning_outcome',
  outcome_code   VARCHAR(32) NOT NULL COMMENT 'CG-3 / C-3.2 / C-3.2-LO-1 - the DURABLE key',
  curriculum_id  BIGINT UNSIGNED NULL,
  extraction_id  BIGINT UNSIGNED NULL,
  chapter_id     BIGINT UNSIGNED NULL,
  match_source   VARCHAR(16) NOT NULL DEFAULT 'llm'
                 COMMENT 'llm | token_overlap | inherited',
  match_score    DECIMAL(4,3) NULL,
  created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_concept_outcome_code (concept_id, outcome_code),
  KEY idx_co_outcome (outcome_id),
  KEY idx_co_extraction (extraction_id),
  KEY idx_co_code (chapter_id, outcome_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
