-- Fine-grained question form for questions that have no extraction sidecar.
--
-- `question_type_catalog` defines 13 meaningful forms (mcq, assertion_reason,
-- fill_blank, match_following, proof, ...), but the only place the API can read
-- one from is `lms_question_extraction.question_type_code`. That table means
-- "this question came out of a PDF extraction", and 2,985 of the Class 10
-- Science questions were generated, not extracted -- so every one of them
-- resolves to catalog label "(none)" and the bank's type filter cannot see them.
--
-- Writing sidecar rows for generated questions would fix the display by
-- falsifying the provenance. Instead this column joins the existing family of
-- plain, writable, machine-derived tags on the question itself:
--
--     g_bloom       varchar(12)          Remember / Understand / ...
--     g_dok         tinyint unsigned     1-4
--     g_difficulty  varchar(8)           Easy / Medium / Hard
--     g_qtype_code  varchar(32)          <-- this one
--
-- The API resolves the form as: sidecar code (extracted) -> g_qtype_code
-- (derived) -> the coarse question_type_master fallback. Nullable and additive,
-- so nothing breaks before the Laravel side ships.

ALTER TABLE `lms_question_master`
  ADD COLUMN `g_qtype_code` VARCHAR(32) NULL DEFAULT NULL AFTER `g_dok`;

-- The bank's hot path is "this chapter, this form, this difficulty", which is
-- what idx_qm_blueprint already serves for g_bloom/g_difficulty. The per-concept
-- MCQ programme adds "this concept, this form, this difficulty" on top.
ALTER TABLE `lms_question_master`
  ADD INDEX `idx_qm_concept_form` (`concept_id`, `g_qtype_code`, `g_difficulty`);
