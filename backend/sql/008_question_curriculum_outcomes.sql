-- 008 — Curriculum mapping for questions.
--
-- Mirrors what app/db/mariadb.py creates at boot (_QUESTION_TABLES_EXTRA,
-- _EXTRACTION_ITEM_COLUMNS, _QUESTION_MASTER_COLUMNS, _QUESTION_INDEXES), the
-- way 007 mirrors extraction_schema.py. Running this by hand and letting the
-- app boot are interchangeable; both are idempotent.
--
-- 006 was left as a file only and never became idempotent at runtime, so its
-- g_qtype_code column exists on some databases and not others. Not repeated.
--
-- WHY A TABLE AND NOT A COLUMN
--
-- The concept side has answered this already: lms_concept_outcome, written by
-- curriculum_frame.persist_mappings(). Three reasons it cannot be a column on
-- lms_question_master:
--
--   1. One question serves several outcomes. The reader is instructed to cite
--      "usually one, at most three". A case-based parent with four sub-parts
--      legitimately spans a competency and two learning outcomes.
--   2. outcome_id does not survive a curriculum re-process.
--      curriculum_service.save_learning_outcomes() runs
--          DELETE FROM lms_learning_outcomes WHERE curriculum_id = :cid
--      and rebuilds the tree, so every id changes. The durable key is
--      (curriculum_id, outcome_code) -- hence outcome_code stored beside it,
--      and hence resync_outcome_ids() on the concept side.
--   3. The hierarchy is already on lms_learning_outcomes.parent_id. Storing
--      goal and competency as two further ids gives three things that stale
--      independently; they are derived once at map time and denormalised here.
--
-- No FOREIGN KEY constraints, for the same reason lms_concept_outcome has
-- none: the parent rows are deleted by design.

CREATE TABLE IF NOT EXISTS `lms_question_outcome` (
  `id`               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `question_id`      BIGINT UNSIGNED NOT NULL,
  `sub_institute_id` BIGINT UNSIGNED NOT NULL,
  `outcome_id`       BIGINT UNSIGNED NULL
                     COMMENT 'lms_learning_outcomes.id; stale after a curriculum re-process',
  `outcome_type`     VARCHAR(20) NOT NULL COMMENT 'goal | competency | learning_outcome',
  `outcome_code`     VARCHAR(32) NOT NULL COMMENT 'CG 1 / C 1.1 / C-1.1-LO-2 -- the durable key',
  `goal_code`        VARCHAR(32) NULL COMMENT 'denormalised from parent_id at map time',
  `competency_code`  VARCHAR(32) NULL COMMENT 'denormalised from parent_id at map time',
  `curriculum_id`    BIGINT UNSIGNED NULL,
  `extraction_id`    BIGINT UNSIGNED NULL,
  `chapter_id`       BIGINT UNSIGNED NULL,
  `match_source`     VARCHAR(16) NOT NULL DEFAULT 'read'
                     COMMENT 'read | llm | token_overlap | inherited',
  `match_score`      DECIMAL(4,3) NULL,
  `created_at`       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  -- On the CODE, not the id: outcome_id is nullable and MySQL permits
  -- unlimited NULLs in a unique index, so keying on it would not stop one
  -- question being mapped to one competency twice.
  UNIQUE KEY `uq_qo_question_code` (`question_id`, `outcome_code`),
  KEY `idx_qo_outcome` (`outcome_id`),
  KEY `idx_qo_extraction` (`extraction_id`),
  KEY `idx_qo_chapter_code` (`chapter_id`, `outcome_code`),
  KEY `idx_qo_blueprint` (`chapter_id`, `outcome_type`, `outcome_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- The PRIMARY outcome, mirrored onto the item sidecar so the bank can filter
-- without a join. Exactly how concept_id / concept_confidence / ai_model are
-- already carried. The full set stays in lms_question_outcome.
--
-- Guarded rather than ADD COLUMN IF NOT EXISTS: MariaDB has that syntax, MySQL
-- does not, and this file has to run on both.

SET @db := DATABASE();

SET @sql := (SELECT IF(COUNT(*) > 0, 'SELECT "outcome_id exists"',
  'ALTER TABLE `lms_question_extraction` ADD COLUMN `outcome_id` BIGINT UNSIGNED NULL')
  FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db
   AND TABLE_NAME = 'lms_question_extraction' AND COLUMN_NAME = 'outcome_id');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

SET @sql := (SELECT IF(COUNT(*) > 0, 'SELECT "outcome_code exists"',
  'ALTER TABLE `lms_question_extraction` ADD COLUMN `outcome_code` VARCHAR(32) NULL')
  FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db
   AND TABLE_NAME = 'lms_question_extraction' AND COLUMN_NAME = 'outcome_code');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- DECIMAL(4,3) to match concept_confidence, as extraction_schema.py does.
SET @sql := (SELECT IF(COUNT(*) > 0, 'SELECT "outcome_confidence exists"',
  'ALTER TABLE `lms_question_extraction` ADD COLUMN `outcome_confidence` DECIMAL(4,3) NULL')
  FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db
   AND TABLE_NAME = 'lms_question_extraction' AND COLUMN_NAME = 'outcome_confidence');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

SET @sql := (SELECT IF(COUNT(*) > 0, 'SELECT "outcome_source exists"',
  'ALTER TABLE `lms_question_extraction` ADD COLUMN `outcome_source` VARCHAR(16) NULL')
  FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db
   AND TABLE_NAME = 'lms_question_extraction' AND COLUMN_NAME = 'outcome_source');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;


-- Codes, not ids, on the ERP-owned question table. See the header.
SET @sql := (SELECT IF(COUNT(*) > 0, 'SELECT "g_lo_code exists"',
  'ALTER TABLE `lms_question_master` ADD COLUMN `g_lo_code` VARCHAR(32) NULL')
  FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db
   AND TABLE_NAME = 'lms_question_master' AND COLUMN_NAME = 'g_lo_code');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

SET @sql := (SELECT IF(COUNT(*) > 0, 'SELECT "g_cg_code exists"',
  'ALTER TABLE `lms_question_master` ADD COLUMN `g_cg_code` VARCHAR(32) NULL')
  FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db
   AND TABLE_NAME = 'lms_question_master' AND COLUMN_NAME = 'g_cg_code');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;


-- "This chapter, this goal, this outcome" -- the bank's curriculum filter.
-- Last, because it names columns the statements above may have just added.
SET @sql := (SELECT IF(COUNT(*) > 0, 'SELECT "idx_qm_outcome exists"',
  'ALTER TABLE `lms_question_master` ADD INDEX `idx_qm_outcome` (`chapter_id`, `g_cg_code`, `g_lo_code`)')
  FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = @db
   AND TABLE_NAME = 'lms_question_master' AND INDEX_NAME = 'idx_qm_outcome');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
