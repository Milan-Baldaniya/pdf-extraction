"""Runtime schema guard for the concept/topic confidence and curriculum columns.

Everything here mirrors sql/007_concept_curriculum_confidence.sql. The ERP
schema is owned by another application (MARIADB_AUTO_CREATE_TABLES=false), so
new columns are added defensively at runtime rather than assumed present, the
same way chapter_period_service.ensure_periods_column() does for
chapter_master.no_of_periods.

Columns are checked against information_schema rather than using
`ADD COLUMN IF NOT EXISTS`: MariaDB supports it, MySQL does not, and the same
code has to work against both. Each column is added in its own statement so one
failure -- a permissions problem on a shared schema, say -- does not abandon the
rest.

Call it from two places and no fewer:

  * init_mariadb(), so a fresh deploy is ready before the first request.
  * step 0 of the chapter job, before any LLM call.

The second is not belt-and-braces. An INSERT naming a column the database does
not have fails AFTER the whole LLM fan-out has run, which costs a full chapter
of tokens for nothing -- the failure topic_service's _INSERT_TOPIC comment was
written about. The _ready cache makes the repeat call free.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


# Columns added to tables this service does not own. Order within a table is
# the order they are added in; `AFTER` clauses only matter cosmetically.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "lms_concept": {
        # A NEW field, not a rename of description. description stays short and
        # is written by generation because semantic_intelligence/pipeline.py
        # hands it to the four agents; definition is the fuller teaching
        # definition the enrichment stage writes later.
        "definition": "TEXT NULL AFTER description",
        # utf8mb4 pinned: the server default is latin1 and these quotes carry
        # Devanagari, Gujarati and typographic punctuation.
        "source_evidence": (
            "VARCHAR(512) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL"
        ),
        "evidence_verified": "TINYINT(1) NOT NULL DEFAULT 0",
        # Matches lms_question_extraction.concept_confidence, the only other
        # calibrated confidence in this schema.
        "confidence": "DECIMAL(4,3) NULL",
        "confidence_profile": (
            "VARCHAR(24) NULL COMMENT 'content | curriculum | deterministic_backfill'"
        ),
        "confidence_parts": (
            "LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL"
        ),
        # Defaults to 'legacy' while new code writes 'auto_accepted', so the
        # DEFAULT labels exactly the rows nobody ever scored.
        "review_status": "VARCHAR(16) NOT NULL DEFAULT 'legacy'",
        "concept_show_hide": "TINYINT(1) NOT NULL DEFAULT 1",
        # The authoritative "enrichment has run" test. mastery_threshold cannot
        # serve: it is double(8,2) NOT NULL and owned by the ERP, so generation
        # writes a 0.00 sentinel rather than altering it.
        "enriched_at": "TIMESTAMP NULL",
    },
    "topic_master": {
        "source_evidence": (
            "VARCHAR(512) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL"
        ),
        "evidence_verified": "TINYINT(1) NOT NULL DEFAULT 0",
        "confidence": "DECIMAL(4,3) NULL",
    },
    "chapter_master": {
        "extraction_confidence": "DECIMAL(4,3) NULL AFTER no_of_periods",
        # The budget this chapter was actually given, so a count can be
        # explained months later: which anchor fired, what the target was.
        "concept_budget": (
            "LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL"
        ),
    },
}

_ADDED_INDEXES: dict[str, dict[str, str]] = {
    "lms_concept": {
        "idx_concept_ext_topic": "(extraction_id, topic_id)",
    },
    "lms_learning_outcomes": {
        # Every chapter job now reads this table by (chapter_id, type).
        "idx_lo_chapter_type": "(chapter_id, type)",
    },
}

# No foreign keys. save_learning_outcomes() deletes and re-inserts every row of
# a curriculum on each re-process, so outcome_id dangles BY DESIGN -- the
# durable key is (curriculum_id, outcome_code) and resync_outcome_ids() re-links
# the ids afterwards. concept_id is likewise unconstrained, matching the
# convention of every recent table in this schema.
#
# The UNIQUE key is on outcome_code, not outcome_id: outcome_id is nullable and
# MySQL permits unlimited NULLs in a unique index, so keying on it would not
# stop the same competency being mapped to one concept twice.
_TABLES: dict[str, str] = {
    "lms_concept_outcome": """
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
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
}


# The DDL only ever needs to run once per database, but both call sites reach
# this code on every request, so the result is cached rather than skipped.
_ready = False


def _columns(conn: Any, table: str) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            text(
                "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
            ),
            {"t": table},
        ).fetchall()
    }


def _indexes(conn: Any, table: str) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            text(
                "SELECT INDEX_NAME FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
            ),
            {"t": table},
        ).fetchall()
    }


def _table_exists(conn: Any, name: str) -> bool:
    return bool(
        conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :n"
            ),
            {"n": name},
        ).scalar()
    )


def ensure_extraction_schema(conn: Any, *, force: bool = False) -> list[str]:
    """Add every column, index and table this pipeline writes. Idempotent.

    ``conn`` is anything with ``.execute(text(...))`` and ``.commit()`` -- a
    Session from a service or a Connection from init_mariadb both work, which is
    why this takes the handle rather than opening its own.

    Never raises. A schema this service does not own can refuse DDL for reasons
    that have nothing to do with the caller, and failing the whole chapter job
    over a missing nullable column would be out of all proportion: the writes
    below degrade to skipping that column.
    """
    global _ready
    if _ready and not force:
        return []

    changed: list[str] = []
    try:
        for name, ddl in _TABLES.items():
            if _table_exists(conn, name):
                continue
            try:
                conn.execute(text(ddl))
                conn.commit()
                changed.append(f"table {name}")
            except Exception as exc:
                logger.error("Could not create %s: %s", name, exc)

        for table, columns in _ADDED_COLUMNS.items():
            have = _columns(conn, table)
            if not have:
                # Table absent entirely. Not this module's problem to create.
                logger.warning("Schema check skipped: %s does not exist", table)
                continue
            for column, ddl in columns.items():
                if column in have:
                    continue
                try:
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN `{column}` {ddl}")
                    )
                    conn.commit()
                    changed.append(f"{table}.{column}")
                except Exception as exc:
                    logger.error("Could not add %s.%s: %s", table, column, exc)

        for table, indexes in _ADDED_INDEXES.items():
            have = _indexes(conn, table)
            if not have:
                continue
            for index, columns_sql in indexes.items():
                if index in have:
                    continue
                try:
                    conn.execute(
                        text(f"CREATE INDEX {index} ON {table} {columns_sql}")
                    )
                    conn.commit()
                    changed.append(f"{table}.{index}")
                except Exception as exc:
                    # An index is an optimisation; losing one is not a failure.
                    logger.warning("Could not index %s %s: %s", table, index, exc)

        _ready = True
    except Exception as exc:
        # Left un-cached so the next call retries.
        logger.warning("Extraction schema check skipped: %s", exc)

    if changed:
        logger.info("Extraction schema updated: %s", ", ".join(changed))
    return changed


def has_column(conn: Any, table: str, column: str) -> bool:
    """Whether one column is present. For callers that degrade rather than fail."""
    try:
        return column in _columns(conn, table)
    except Exception:
        return False


# Answers to supports(), cached for the life of the process. The ALTERs above
# run once; after that this is asked on every write and must not cost a query.
_supported: dict[tuple[str, tuple[str, ...]], bool] = {}


def supports(conn: Any, table: str, *columns: str) -> bool:
    """Whether every named column exists, so a caller can choose its SQL.

    The ensure above runs before the first write, so the answer is normally yes.
    It can still be no on a database that refuses DDL to this user, and that
    case has to degrade rather than fail: a chapter's concepts are worth far
    more than their confidence scores, and an INSERT naming a missing column
    would throw the whole LLM run away to save nothing.
    """
    key = (table, columns)
    cached = _supported.get(key)
    if cached is None:
        try:
            have = _columns(conn, table)
            cached = all(column in have for column in columns)
        except Exception:
            cached = False
        _supported[key] = cached
        if not cached:
            logger.warning(
                "%s is missing %s; those values will not be written",
                table, ", ".join(columns),
            )
    return cached
