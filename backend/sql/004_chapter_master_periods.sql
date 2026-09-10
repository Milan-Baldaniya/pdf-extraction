-- Chapter-wise period allocation (MariaDB / vivek_erp).
--
-- chapter_master.no_of_periods holds the periods for one chapter. It is filled
-- from two places, in this order of preference:
--   1. a per-chapter count stated in the curriculum document itself
--      ("Tissues  No. of Periods: 13"), cached on lms_curriculum.chapter_periods
--   2. lms_units.planned_periods, split across the chapters of that unit
-- Both are read from the source PDF's text layer where it is still on disk,
-- because MinerU's OCR drops some of these numbers entirely.
-- See app/services/chapter_period_service.py.
--
-- app.services.chapter_period_service.ensure_periods_column() applies both
-- changes at runtime, so this file is only needed for an explicit migration.

ALTER TABLE chapter_master
  ADD COLUMN no_of_periods INT NULL AFTER key_concepts;

-- utf8mb4 is pinned explicitly: the server default is latin1 and these chapter
-- names carry Devanagari and typographic punctuation.
ALTER TABLE lms_curriculum
  ADD COLUMN chapter_periods LONGTEXT
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL;
