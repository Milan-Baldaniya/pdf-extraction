-- ---------------------------------------------------------------------------
-- 008_concept_outcome_ancestry.sql
--
-- Record a concept's whole curriculum chain, not just the one node it matched.
--
-- The curriculum is three levels deep in lms_learning_outcomes, joined by
-- parent_id:
--
--     curricular goal  ->  competency  ->  learning outcome
--
-- lms_concept_outcome stored only the single node a concept matched, so a
-- concept knew its competency and nothing at all about the goal above it. On
-- Class 10 that meant 2392 links to competencies, 66 to learning outcomes and
-- ZERO to curricular goals, even though every competency has a parent goal.
--
-- Nothing here is newly derived. curriculum_frame.load_frame() already
-- denormalises goal_code onto every competency and goal_code + competency_code
-- onto every learning outcome (step 4); persist_mappings() simply discarded
-- them. These two columns are where that existing work now lands.
--
-- Codes, not ids, for exactly the reason outcome_code is the durable key:
-- save_learning_outcomes() runs
--     DELETE FROM lms_learning_outcomes WHERE curriculum_id = :cid
-- on every re-process, so a goal_id or competency_id would dangle the same way
-- outcome_id already does.
--
-- Mirrored by app/services/extraction_schema.py, which adds the same columns
-- defensively at runtime because the ERP owns this schema
-- (MARIADB_AUTO_CREATE_TABLES=false). Apply whichever suits the environment;
-- both are idempotent.
-- ---------------------------------------------------------------------------

ALTER TABLE lms_concept_outcome
  ADD COLUMN competency_code VARCHAR(32) NULL
      COMMENT 'competency this row rolls up to; itself when the row IS one'
      AFTER outcome_code,
  ADD COLUMN goal_code VARCHAR(32) NULL
      COMMENT 'curricular goal this row rolls up to'
      AFTER competency_code;

-- "Which concepts serve CG-3?" is the question goal_code was added to answer.
ALTER TABLE lms_concept_outcome
  ADD KEY idx_co_goal (curriculum_id, goal_code);

-- ---------------------------------------------------------------------------
-- Companion repair: top-level rows that were never typed.
--
-- 73 rows across the project sit at the top of the chain (parent_id IS NULL)
-- with type '' instead of 'goal' -- every curricular goal of Class 10
-- Mathematics and Science among them. load_frame() selects goals by
-- `type = 'goal'`, so those goals were invisible to the frame and every
-- goal_code derived for those subjects would have come back NULL.
--
-- A row with no parent is a goal by construction, which is the safer test.
-- ---------------------------------------------------------------------------

UPDATE lms_learning_outcomes
   SET type = 'goal', updated_at = CURRENT_TIMESTAMP
 WHERE parent_id IS NULL
   AND (type IS NULL OR type = '');
