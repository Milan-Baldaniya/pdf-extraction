"""
Lesson Intelligence — Database Migration Script.

Creates the 3 output tables for lesson plan storage:
  1. lms_intelligence_lesson_plans  — Parent plan (1 per std+sub+term)
  2. lms_lesson_plan_periods        — Core (1 row per 40-min lesson)
  3. lms_lesson_plan_concepts       — Junction (concepts per period)

NOTE: These tables are already created via Laravel migrations.
      This script exists only as a Python fallback / reference.

Usage:
    python -m app.lesson_intelligence.migrate
"""

from __future__ import annotations

import logging
import sys

sys.path.insert(0, ".")
from app.db.mariadb import SessionLocal, init_mariadb
from sqlalchemy import text

logger = logging.getLogger(__name__)

MIGRATIONS = [
    # ── Table 1: lms_intelligence_lesson_plans ───────────────────────────
    """
    CREATE TABLE IF NOT EXISTS lms_intelligence_lesson_plans (
        id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,

        -- SCHOOL IDENTITY (from existing ERP)
        sub_institute_id    INT NOT NULL,
        syear               INT NOT NULL,
        term_id             INT NOT NULL,
        standard_id         INT NOT NULL,
        subject_id          INT NOT NULL,
        division_id         INT DEFAULT NULL,

        -- PLAN METADATA
        plan_title          VARCHAR(255) NOT NULL,
        term_start_date     DATE NOT NULL,
        term_end_date       DATE NOT NULL,

        -- CAPACITY ANALYSIS (computed in Phase 0)
        total_teaching_days INT NOT NULL DEFAULT 0,
        total_periods       INT NOT NULL DEFAULT 0,
        periods_per_week    INT NOT NULL DEFAULT 0,
        period_duration_min INT NOT NULL DEFAULT 40,
        total_teaching_min  INT NOT NULL DEFAULT 0,
        total_required_min  INT NOT NULL DEFAULT 0,
        buffer_percent      DECIMAL(5,2) DEFAULT 0.00,
        holidays_count      INT NOT NULL DEFAULT 0,
        exam_days_count     INT NOT NULL DEFAULT 0,

        -- PLAN CONTENT
        macro_plan_json     JSON DEFAULT NULL,

        -- GENERATION STATUS
        generation_status   ENUM('pending','generating','completed','failed','regenerating')
                            NOT NULL DEFAULT 'pending',
        generation_progress INT DEFAULT 0,
        generation_error    TEXT DEFAULT NULL,
        generated_at        DATETIME DEFAULT NULL,
        generated_by        VARCHAR(100) DEFAULT NULL,

        -- TIMESTAMPS (Laravel convention)
        created_at          TIMESTAMP NULL DEFAULT NULL,
        updated_at          TIMESTAMP NULL DEFAULT NULL,

        -- INDEXES
        UNIQUE KEY uk_plan (sub_institute_id, syear, term_id, standard_id, subject_id, division_id),
        INDEX idx_school_year (sub_institute_id, syear),
        INDEX idx_standard_subject (standard_id, subject_id),
        INDEX idx_generation_status (generation_status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,

    # ── Table 2: lms_lesson_plan_periods ─────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS lms_lesson_plan_periods (
        id                                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        lms_intelligence_lesson_plans_id     BIGINT UNSIGNED NOT NULL,

        -- WHEN (Calendar View)
        scheduled_date       DATE NOT NULL,
        week_day             CHAR(1) NOT NULL,
        week_number          INT NOT NULL,
        period_id            INT UNSIGNED NOT NULL,
        period_slot          VARCHAR(10) NOT NULL,

        -- WHO (Teacher View)
        teacher_id           INT UNSIGNED NOT NULL,

        -- WHAT (Content View)
        chapter_id           INT DEFAULT NULL,
        chapter_name         VARCHAR(255) DEFAULT NULL,
        primary_concept_id   INT DEFAULT NULL,
        primary_concept_name VARCHAR(255) DEFAULT NULL,

        -- HOW (The Lesson Plan Content)
        period_type          ENUM('teaching','assessment','revision','activity','lab','project','buffer')
                             NOT NULL DEFAULT 'teaching',
        plan_json            JSON DEFAULT NULL,

        -- INTELLIGENCE METADATA
        blooms_level         VARCHAR(20) DEFAULT NULL,
        dok_level            TINYINT DEFAULT NULL,
        pedagogy_method      VARCHAR(100) DEFAULT NULL,
        difficulty_level     VARCHAR(20) DEFAULT NULL,
        learning_objectives  JSON DEFAULT NULL,
        learning_outcomes_mapped JSON DEFAULT NULL,

        -- PLANNED DURATION
        planned_duration_min INT NOT NULL DEFAULT 40,

        -- TEACHER TRACKING
        status               ENUM('not_started','in_progress','completed','skipped','rescheduled')
                             NOT NULL DEFAULT 'not_started',
        actual_duration_min  INT DEFAULT NULL,
        engagement_rating    TINYINT DEFAULT NULL,
        completion_percent   INT DEFAULT NULL,
        teacher_notes        TEXT DEFAULT NULL,
        completed_at         DATETIME DEFAULT NULL,

        -- RESCHEDULING
        original_date        DATE DEFAULT NULL,
        reschedule_reason    VARCHAR(255) DEFAULT NULL,

        -- TIMESTAMPS (Laravel convention)
        created_at           TIMESTAMP NULL DEFAULT NULL,
        updated_at           TIMESTAMP NULL DEFAULT NULL,

        -- FOREIGN KEYS
        CONSTRAINT fk_lms_intel_lesson_plans
            FOREIGN KEY (lms_intelligence_lesson_plans_id)
            REFERENCES lms_intelligence_lesson_plans(id)
            ON DELETE CASCADE,

        -- INDEXES
        INDEX idx_calendar      (scheduled_date, lms_intelligence_lesson_plans_id),
        INDEX idx_teacher       (teacher_id, scheduled_date, status),
        INDEX idx_chapter       (chapter_id),
        INDEX idx_concept       (primary_concept_id),
        INDEX idx_status        (status, scheduled_date),
        INDEX idx_plan_date     (lms_intelligence_lesson_plans_id, scheduled_date),
        INDEX idx_week          (lms_intelligence_lesson_plans_id, week_number)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,

    # ── Table 3: lms_lesson_plan_concepts ────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS lms_lesson_plan_concepts (
        id                           BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        lms_lesson_plan_periods_id   BIGINT UNSIGNED NOT NULL,
        concept_id                   INT NOT NULL,
        concept_name                 VARCHAR(255) NOT NULL,

        -- COVERAGE DETAILS
        is_primary            BOOLEAN NOT NULL DEFAULT FALSE,
        coverage_percent      INT DEFAULT 0,
        knowledge_items_covered JSON DEFAULT NULL,

        -- TIMESTAMPS
        created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        -- FOREIGN KEYS
        FOREIGN KEY (lms_lesson_plan_periods_id)
            REFERENCES lms_lesson_plan_periods(id)
            ON DELETE CASCADE,

        -- INDEXES
        INDEX idx_concept_lookup (concept_id),
        INDEX idx_period_concepts (lms_lesson_plan_periods_id),
        UNIQUE KEY uk_period_concept (lms_lesson_plan_periods_id, concept_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


def run_migrations():
    """Execute all migration statements."""
    if not init_mariadb():
        print("ERROR: Could not connect to MariaDB.")
        return False

    table_names = [
        "lms_intelligence_lesson_plans",
        "lms_lesson_plan_periods",
        "lms_lesson_plan_concepts",
    ]

    with SessionLocal() as db:
        for i, sql in enumerate(MIGRATIONS):
            name = table_names[i]
            try:
                db.execute(text(sql))
                db.commit()
                print(f"  [OK] {name}")
            except Exception as exc:
                db.rollback()
                print(f"  [FAIL] {name}: {exc}")
                return False

    print("\nAll lesson intelligence tables created successfully.")
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Running Lesson Intelligence migrations...")
    success = run_migrations()
    sys.exit(0 if success else 1)
