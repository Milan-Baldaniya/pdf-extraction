-- Migration: 005_fix_lms_learning_outcomes_type.sql
-- Update type ENUM in lms_learning_outcomes to include 'learning_outcome'
ALTER TABLE lms_learning_outcomes MODIFY COLUMN `type` ENUM('goal', 'competency', 'learning_outcome') DEFAULT NULL;

-- Update unique key to include chapter_id so multiple chapter learning outcomes can exist cleanly
ALTER TABLE lms_learning_outcomes DROP INDEX uq_learning_outcomes;
ALTER TABLE lms_learning_outcomes ADD CONSTRAINT uq_learning_outcomes UNIQUE (curriculum_id, code, chapter_id);
