"""MariaDB persistence for completed PDF extractions."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.sql import func

from app.models.schemas import ExtractionResponse
from app.utils.config import settings

logger = logging.getLogger(__name__)

Base = declarative_base()

_engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None
_init_error: str | None = None


class DocumentExtraction(Base):
    __tablename__ = "document_extractions"
    # create_all() would otherwise inherit the latin1 database default.
    __table_args__ = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_type = Column(String(255), nullable=True)
    document_tittle = Column(String(255), nullable=True)
    chapter_number = Column(Integer, nullable=True)
    standard = Column(Integer, nullable=True)
    subject_name = Column(String(255), nullable=True)
    board = Column(String(255), nullable=True)
    syear = Column(Integer, nullable=True)
    pdf_url = Column(Text, nullable=True)
    
    # Declared once. These were previously repeated below the payload block;
    # SQLAlchemy silently kept the last definition, so the duplicates were
    # dead weight that made the model disagree with itself on inspection.
    standard_id = Column(Integer, nullable=True)
    subject_id = Column(Integer, nullable=True)
    chapter_id = Column(Integer, nullable=True)
    sub_institute_id = Column(Integer, nullable=True)

    md_content = Column(LONGTEXT, nullable=True)
    json_content = Column(LONGTEXT, nullable=True)
    page_count = Column(Integer, nullable=True)
    image_extracted = Column(Integer, nullable=True)
    extraction_metadata = Column(LONGTEXT, nullable=True)

    # --- question-bank ingestion payload -------------------------------
    # Everything below exists so a downstream consumer (the DeepSeek pass
    # that fills the question-bank tables) can work from this row alone
    # and never has to reach back to the extraction host's disk.

    # SHA-256 of the source PDF. Re-uploading the same chapter finds the
    # existing row instead of creating a second one.
    content_sha256 = Column(String(64), nullable=True)

    # pending | extracting | extracted | failed
    extraction_status = Column(String(32), nullable=True)

    # Per-image records: sha256, page, url, dimensions, OCR text, role.
    # This is what makes a figure recoverable after the output dir is
    # cleaned — the markdown only carries a host-bound absolute URL.
    asset_manifest = Column(LONGTEXT, nullable=True)

    # Text recovered from inside images (graph axis labels, values written
    # on a diagram). MinerU's markdown does not contain this.
    image_ocr_text = Column(LONGTEXT, nullable=True)

    # Detected question types and their counts, e.g. {"mcq": 16, "assertion_reason": 4}
    question_types = Column(LONGTEXT, nullable=True)

    # CBSE section fingerprint, e.g. {"A": {"count": 20, "marks_each": 1}, ...}
    section_summary = Column(LONGTEXT, nullable=True)

    # How this extraction actually ran: OCR language, whether formula and
    # table recognition were on, which method won, quality score. Without
    # this you cannot tell a good extraction from a degraded one later.
    extraction_profile = Column(LONGTEXT, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# Added after the table shipped. create_all() only creates missing TABLES —
# it never alters an existing one — so new columns need an explicit,
# idempotent migration. Ordered dict so the ALTER reads in schema order.
_ADDED_COLUMNS: dict[str, str] = {
    "content_sha256": "VARCHAR(64) NULL",
    "extraction_status": "VARCHAR(32) NULL",
    "asset_manifest": "LONGTEXT NULL",
    "image_ocr_text": "LONGTEXT NULL",
    "question_types": "LONGTEXT NULL",
    "section_summary": "LONGTEXT NULL",
    "extraction_profile": "LONGTEXT NULL",
}


def _mariadb_url() -> URL:
    return URL.create(
        "mysql+pymysql",
        username=settings.mariadb_user,
        password=settings.mariadb_password,
        host=settings.mariadb_host,
        port=settings.mariadb_port,
        database=settings.mariadb_db,
        # The server default charset is latin1; without this the connection
        # would inherit it and mangle/reject non-cp1252 text (maths symbols,
        # curly quotes) on the way in.
        query={"charset": "utf8mb4"},
    )


def init_mariadb() -> bool:
    """Connect to MariaDB and ensure the extractions table exists."""
    global _engine, SessionLocal, _init_error

    if SessionLocal is not None:
        return True

    try:
        _engine = create_engine(
            _mariadb_url(),
            # Must stay below the server's wait_timeout (2000s) or the pool
            # hands out connections the server has already dropped.
            pool_recycle=1800,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 15},
        )
        with _engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
        if settings.mariadb_auto_create_tables:
            try:
                Base.metadata.create_all(bind=_engine)
            except Exception as schema_exc:
                # Reflection/DDL can fail while the server is still fully queryable
                # (e.g. DESCRIBE needs a temp table and the server tmpdir is full).
                # The connection is live, so keep the session factory usable.
                logger.warning("MariaDB schema check skipped: %s", schema_exc)
        else:
            logger.info(
                "Skipping create_all() (MARIADB_AUTO_CREATE_TABLES=false) — "
                "the target schema is owned by another application."
            )
        _ensure_extraction_columns(_engine)
        _ensure_question_tables(_engine)
        _ensure_publisher_schema(_engine)
        _init_error = None
        logger.info(
            "MariaDB ready (%s:%s/%s)",
            settings.mariadb_host,
            settings.mariadb_port,
            settings.mariadb_db,
        )
        return True
    except Exception as exc:
        _engine = None
        SessionLocal = None
        _init_error = str(exc)
        logger.warning("MariaDB unavailable: %s", exc)
        return False


def _ensure_extraction_columns(engine: Engine) -> list[str]:
    """Add any missing question-bank columns to a pre-existing table.

    Idempotent and safe to run on every boot. Columns are checked against
    information_schema rather than using `ADD COLUMN IF NOT EXISTS`, which
    MariaDB supports but MySQL does not — the same code has to work against
    both. Each column is added in its own statement so one failure (a
    permissions problem on a shared schema, say) does not abandon the rest.
    """
    added: list[str] = []
    try:
        with engine.connect() as connection:
            existing = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                        "WHERE TABLE_SCHEMA = DATABASE() "
                        "AND TABLE_NAME = 'document_extractions'"
                    )
                ).fetchall()
            }
            if not existing:
                # Table absent entirely — create_all() owns that case.
                return added

            for column, ddl in _ADDED_COLUMNS.items():
                if column in existing:
                    continue
                try:
                    connection.execute(
                        text(
                            f"ALTER TABLE document_extractions ADD COLUMN `{column}` {ddl}"
                        )
                    )
                    connection.commit()
                    added.append(column)
                except Exception as exc:
                    logger.error(
                        "Could not add document_extractions.%s: %s", column, exc
                    )

            # Re-uploading the same PDF should update its row, not add another.
            if "content_sha256" in existing or "content_sha256" in added:
                try:
                    indexes = {
                        row[0]
                        for row in connection.execute(
                            text(
                                "SELECT INDEX_NAME FROM information_schema.STATISTICS "
                                "WHERE TABLE_SCHEMA = DATABASE() "
                                "AND TABLE_NAME = 'document_extractions'"
                            )
                        ).fetchall()
                    }
                    if "idx_doc_extractions_sha" not in indexes:
                        connection.execute(
                            text(
                                "CREATE INDEX idx_doc_extractions_sha "
                                "ON document_extractions (content_sha256)"
                            )
                        )
                        connection.commit()
                except Exception as exc:
                    logger.warning("Could not index content_sha256: %s", exc)
    except Exception as exc:
        logger.warning("Column check on document_extractions skipped: %s", exc)

    if added:
        logger.info("Added document_extractions columns: %s", ", ".join(added))
    return added


# The two tables that hold extracted exam items. Created here rather than in
# the Laravel migration set because this service owns them end to end, and
# because Laravel's migrations are forward-only (an AppServiceProvider guard
# throws on DROP TABLE), so a table it creates cannot be rolled back.
#
# No foreign keys, matching the convention of every recent table in this
# schema: the referents are soft-deleted and some carry MyISAM-era ids.
_QUESTION_TABLES: dict[str, str] = {
    "lms_question_extraction": """
        CREATE TABLE IF NOT EXISTS lms_question_extraction (
          id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
          question_id        BIGINT UNSIGNED NOT NULL,
          sub_institute_id   BIGINT UNSIGNED NOT NULL,
          extraction_id      BIGINT UNSIGNED NOT NULL,
          source_page        SMALLINT UNSIGNED NULL,
          source_char_start  INT UNSIGNED NULL,
          source_char_end    INT UNSIGNED NULL,
          exam_section       CHAR(1) NULL,
          section_heading    VARCHAR(191) NULL,
          section_marks      TINYINT UNSIGNED NULL,
          item_number        VARCHAR(16) NULL,
          item_ordinal       SMALLINT UNSIGNED NULL,
          item_form          VARCHAR(24) NULL,
          parent_question_id BIGINT UNSIGNED NULL,
          choice_group_id    CHAR(36) NULL,
          choice_role        VARCHAR(8) NULL,
          reproduction       VARCHAR(16) NOT NULL DEFAULT 'verbatim',
          verbatim_sha256    CHAR(64) NULL,
          verbatim_payload   LONGTEXT NULL,
          correction_reason  VARCHAR(191) NULL,
          corrected_fields   JSON NULL,
          corrected_by       BIGINT UNSIGNED NULL,
          corrected_at       TIMESTAMP NULL,
          attribution        VARCHAR(255) NULL,
          licence            VARCHAR(64) NULL,
          validation_status  VARCHAR(16) NOT NULL DEFAULT 'pending',
          validation_report  JSON NULL,
          validator_version  VARCHAR(16) NULL,
          figure_required    TINYINT(1) NOT NULL DEFAULT 0,
          figure_resolved    TINYINT(1) NOT NULL DEFAULT 0,
          created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          PRIMARY KEY (id),
          UNIQUE KEY uq_lqe_question_tenant (question_id, sub_institute_id),
          UNIQUE KEY uq_lqe_extraction_hash (extraction_id, verbatim_sha256, sub_institute_id),
          KEY idx_lqe_extraction_order (extraction_id, item_ordinal),
          KEY idx_lqe_blueprint (extraction_id, exam_section, section_marks),
          KEY idx_lqe_parent (parent_question_id),
          KEY idx_lqe_choice (choice_group_id),
          KEY idx_lqe_review (sub_institute_id, validation_status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    "lms_question_asset": """
        CREATE TABLE IF NOT EXISTS lms_question_asset (
          id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
          question_id      BIGINT UNSIGNED NOT NULL,
          sub_institute_id BIGINT UNSIGNED NOT NULL,
          extraction_id    BIGINT UNSIGNED NOT NULL,
          role             VARCHAR(16) NOT NULL DEFAULT 'stem',
          option_label     CHAR(1) NULL,
          asset_sha256     CHAR(64) NOT NULL,
          source_path      VARCHAR(512) NULL,
          stored_url       VARCHAR(512) NULL,
          mime             VARCHAR(32) NULL,
          width            SMALLINT UNSIGNED NULL,
          height           SMALLINT UNSIGNED NULL,
          byte_size        INT UNSIGNED NULL,
          alt_text         VARCHAR(512) NULL,
          ocr_text         TEXT NULL,
          source_page      SMALLINT UNSIGNED NULL,
          ordinal          TINYINT UNSIGNED NOT NULL DEFAULT 0,
          created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          PRIMARY KEY (id),
          UNIQUE KEY uq_lqa_question_asset (question_id, asset_sha256, role, option_label),
          KEY idx_lqa_extraction (extraction_id),
          KEY idx_lqa_sha (asset_sha256)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
}


_QUESTION_TABLES_EXTRA: dict[str, str] = {
    # Who published the source document. Separate from `board` because one
    # publisher issues material for several boards (and one board's material
    # comes from many publishers), and because the licence and the attribution
    # line are properties of the publisher, not of the board.
    "question_publisher": """
        CREATE TABLE IF NOT EXISTS question_publisher (
          id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
          code                 VARCHAR(64) NOT NULL,
          name                 VARCHAR(191) NOT NULL,
          short_name           VARCHAR(64) NULL,
          publisher_type       VARCHAR(32) NULL COMMENT 'board|government|private|school|other',
          default_board        VARCHAR(64) NULL,
          licence_type         VARCHAR(64) NULL,
          licence_url          VARCHAR(512) NULL,
          attribution_template VARCHAR(512) NULL
                               COMMENT 'e.g. {publisher} - {title}, Class {standard} {subject}, {syear}',
          attribution_required TINYINT(1) NOT NULL DEFAULT 1,
          website              VARCHAR(512) NULL,
          notes                VARCHAR(512) NULL,
          status               TINYINT(1) NOT NULL DEFAULT 1,
          created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          PRIMARY KEY (id),
          UNIQUE KEY uq_qpub_code (code)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # Question forms, including ones a particular publisher invents. The LMS
    # `question_type_master` cannot absorb these: its ids are referenced by
    # live papers and it is tenant-scoped, so a new publisher form would
    # either collide or be invisible to other tenants. This catalogue records
    # the publisher's own vocabulary and maps it onto an LMS type id for
    # delivery, so nothing is lost and nothing existing has to move.
    "question_type_catalog": """
        CREATE TABLE IF NOT EXISTS question_type_catalog (
          id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
          code                  VARCHAR(48) NOT NULL COMMENT 'mcq, assertion_reason, match_following, ...',
          label                 VARCHAR(191) NOT NULL,
          publisher_id          BIGINT UNSIGNED NULL COMMENT 'NULL = standard board form',
          lms_question_type_id  INT NULL COMMENT 'question_type_master.id used on delivery',
          exam_section          CHAR(1) NULL,
          default_marks         TINYINT UNSIGNED NULL,
          auto_gradable         TINYINT(1) NOT NULL DEFAULT 0,
          is_standard           TINYINT(1) NOT NULL DEFAULT 0,
          description           VARCHAR(512) NULL,
          first_seen_extraction_id BIGINT UNSIGNED NULL,
          seen_count            INT UNSIGNED NOT NULL DEFAULT 0,
          status                TINYINT(1) NOT NULL DEFAULT 1,
          created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          PRIMARY KEY (id),
          UNIQUE KEY uq_qtc_code_publisher (code, publisher_id),
          KEY idx_qtc_publisher (publisher_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
}

# Columns added to the item sidecar after it shipped.
_EXTRACTION_ITEM_COLUMNS: dict[str, str] = {
    "publisher_id":       "BIGINT UNSIGNED NULL",
    "question_type_code": "VARCHAR(48) NULL",
    "concept_id":         "BIGINT UNSIGNED NULL",
    "concept_confidence": "DECIMAL(4,3) NULL",
    "bloom_level":        "VARCHAR(16) NULL",
    "dok_level":          "TINYINT UNSIGNED NULL",
    "difficulty_1_to_5":  "TINYINT UNSIGNED NULL",
    "ai_model":           "VARCHAR(64) NULL",
    "ai_tagged_at":       "TIMESTAMP NULL",
    "ai_rationale":       "TEXT NULL",
}

_PUBLISHER_COLUMN = {"publisher_id": "BIGINT UNSIGNED NULL"}


def _ensure_publisher_schema(engine: Engine) -> list[str]:
    """Create the publisher tables and add their columns. Idempotent."""
    changed: list[str] = []
    try:
        with engine.connect() as connection:
            for name, ddl in _QUESTION_TABLES_EXTRA.items():
                exists = connection.execute(
                    text(
                        "SELECT COUNT(*) FROM information_schema.TABLES "
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :name"
                    ),
                    {"name": name},
                ).scalar()
                if exists:
                    continue
                try:
                    connection.execute(text(ddl))
                    connection.commit()
                    changed.append(f"table {name}")
                except Exception as exc:
                    logger.error("Could not create %s: %s", name, exc)

            for table, columns in (
                ("lms_question_extraction", _EXTRACTION_ITEM_COLUMNS),
                ("document_extractions", _PUBLISHER_COLUMN),
            ):
                have = {
                    row[0]
                    for row in connection.execute(
                        text(
                            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
                        ),
                        {"t": table},
                    ).fetchall()
                }
                if not have:
                    continue
                for column, ddl in columns.items():
                    if column in have:
                        continue
                    try:
                        connection.execute(
                            text(f"ALTER TABLE {table} ADD COLUMN `{column}` {ddl}")
                        )
                        connection.commit()
                        changed.append(f"{table}.{column}")
                    except Exception as exc:
                        logger.error("Could not add %s.%s: %s", table, column, exc)
    except Exception as exc:
        logger.warning("Publisher schema check skipped: %s", exc)
    if changed:
        logger.info("Publisher schema updated: %s", ", ".join(changed))
    return changed


def _ensure_question_tables(engine: Engine) -> list[str]:
    """Create the extracted-item tables if they are absent. Idempotent."""
    created: list[str] = []
    try:
        with engine.connect() as connection:
            for name, ddl in _QUESTION_TABLES.items():
                exists = connection.execute(
                    text(
                        "SELECT COUNT(*) FROM information_schema.TABLES "
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :name"
                    ),
                    {"name": name},
                ).scalar()
                if exists:
                    continue
                try:
                    connection.execute(text(ddl))
                    connection.commit()
                    created.append(name)
                except Exception as exc:
                    logger.error("Could not create %s: %s", name, exc)
    except Exception as exc:
        logger.warning("Question-table check skipped: %s", exc)
    if created:
        logger.info("Created question tables: %s", ", ".join(created))
    return created


def mariadb_status() -> dict[str, Any]:
    """Return connection status for health checks."""
    if SessionLocal is None and not init_mariadb():
        return {"connected": False, "error": _init_error}
    return {
        "connected": True,
        "host": settings.mariadb_host,
        "database": settings.mariadb_db,
    }


def _json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


# Metadata keys that describe HOW the run executed, as opposed to what it
# found. Lifted into their own column because "was formula recognition on?"
# decides whether the maths in md_content can be trusted, and nobody should
# have to grep a metadata blob to answer it.
_PROFILE_KEYS = (
    "ocr_language",
    "formula_parsing_enabled",
    "table_parsing_enabled",
    "image_analysis_enabled",
    "local_vlm_enabled",
    "processing_mode",
    "selected_method",
    "quality_score",
    "detected_language",
    "formulas_detected",
    "tables_detected",
    "images_detected",
    "layout_blocks_detected",
    "page_count",
)


def _apply_extraction_payload(
    doc: DocumentExtraction,
    response: ExtractionResponse,
    *,
    document_type: str | None = None,
) -> None:
    doc.md_content = response.markdown_content
    doc.json_content = _json_dumps(response.json_content)
    doc.page_count = response.page_count
    doc.image_extracted = response.images_extracted
    doc.extraction_metadata = _json_dumps(response.metadata)

    metadata = response.metadata or {}

    # The manifest is built into json_content by the extractor; promote it to
    # its own column so a figure can be located without parsing the whole blob.
    manifest: Any = None
    if isinstance(response.json_content, dict):
        manifest = response.json_content.get("asset_manifest")
    if manifest is None:
        manifest = metadata.get("asset_manifest")
    doc.asset_manifest = _json_dumps(manifest) if manifest else None

    # Concatenated so the downstream LLM pass can read figure text as context
    # without walking the manifest itself.
    if isinstance(manifest, list):
        fragments = [
            str(item.get("ocr_text")).strip()
            for item in manifest
            if isinstance(item, dict) and str(item.get("ocr_text") or "").strip()
        ]
        doc.image_ocr_text = "\n\n".join(fragments) if fragments else None

    profile = {key: metadata[key] for key in _PROFILE_KEYS if key in metadata}
    doc.extraction_profile = _json_dumps(profile) if profile else None

    # Structure fingerprint. The extractor may already have computed it; if
    # not, derive it here for question banks. It is what tells the later
    # DeepSeek pass how many items to expect per CBSE section, and it makes a
    # mis-parsed chapter obvious before any model spend is committed to it.
    structure: dict[str, Any] | None = None
    if metadata.get("question_structure"):
        raw_structure = metadata["question_structure"]
        structure = raw_structure if isinstance(raw_structure, dict) else None
    elif is_question_bank(document_type or doc.document_type):
        try:
            from app.services.question_structure import analyze_question_structure

            structure = analyze_question_structure(response.markdown_content)
        except Exception as exc:  # never fail a completed extraction over this
            logger.warning("Question structure analysis failed: %s", exc)

    if structure:
        doc.question_types = _json_dumps(structure.get("question_types"))
        doc.section_summary = _json_dumps(
            {
                "sections": structure.get("sections"),
                "blueprint": structure.get("blueprint"),
                "totals": structure.get("totals"),
                "has_answer_key": structure.get("has_answer_key"),
                "warnings": structure.get("warnings"),
            }
        )
    else:
        if metadata.get("question_types"):
            doc.question_types = _json_dumps(metadata["question_types"])
        if metadata.get("section_summary"):
            doc.section_summary = _json_dumps(metadata["section_summary"])
    if metadata.get("source_sha256"):
        doc.content_sha256 = str(metadata["source_sha256"])[:64]

    doc.extraction_status = "extracted"


class ChapterNotFoundError(ValueError):
    """A question bank was uploaded for a chapter that does not exist.

    Subclasses ValueError so route handlers that catch ValueError surface it
    as a 400, while callers that want to distinguish it from any other bad
    value can still catch it by name. Deliberately NOT swallowed by the
    generic insert handler: this is operator error (wrong chapter picked, or
    the chapter was never extracted), and silently filing the questions
    against chapter_id=NULL would strand ~400 items against nothing.
    """


def is_question_bank(document_type_val: str | None) -> bool:
    """A question set FOR a chapter, rather than the chapter itself."""
    return str(document_type_val or "").strip().lower() in {
        "question_bank",
        "question bank",
        "questionbank",
    }


def _map_ids(
    db: Session,
    standard_val: int | None,
    subject_name_val: str | None,
    chapter_name_val: str | None,
    chapter_number_val: int | None,
    document_type_val: str | None = None,
    sub_institute_id: int | None = None,
) -> tuple[int | None, int | None, int | None]:
    standard_id = None
    subject_id = None
    chapter_id = None
    tenant = sub_institute_id if sub_institute_id is not None else settings.default_sub_institute_id

    try:
        if standard_val is not None:
            row = db.execute(
                text(
                    "SELECT id FROM standard "
                    "WHERE name = :name AND sub_institute_id = :tenant LIMIT 1"
                ),
                {"name": str(standard_val), "tenant": tenant},
            ).fetchone()
            if row:
                standard_id = row[0]

        if subject_name_val is not None:
            row = db.execute(
                text(
                    "SELECT id FROM subject "
                    "WHERE subject_name = :subject_name AND sub_institute_id = :tenant LIMIT 1"
                ),
                {"subject_name": subject_name_val, "tenant": tenant},
            ).fetchone()
            if row:
                subject_id = row[0]

        if document_type_val not in ("Curriculum", "Syllabus"):
            if chapter_name_val is not None and chapter_number_val is not None:
                row = db.execute(
                    text(
                        "SELECT id FROM chapter_master "
                        "WHERE chapter_name = :chapter_name AND sort_order = :sort_order "
                        "AND sub_institute_id = :tenant LIMIT 1"
                    ),
                    {
                        "chapter_name": chapter_name_val,
                        "sort_order": chapter_number_val,
                        "tenant": tenant,
                    },
                ).fetchone()
                if row:
                    chapter_id = row[0]

            # A question bank must attach to a chapter that already exists.
            # Matching on (name, sort_order) is brittle across boards, so fall
            # back to the chapter number alone before giving up.
            if chapter_id is None and is_question_bank(document_type_val) and chapter_number_val is not None:
                row = db.execute(
                    text(
                        "SELECT id FROM chapter_master "
                        "WHERE sort_order = :sort_order AND sub_institute_id = :tenant "
                        "AND (:std_id IS NULL OR standard_id = :std_id) "
                        "AND (:sub_id IS NULL OR subject_id = :sub_id) LIMIT 1"
                    ),
                    {
                        "sort_order": chapter_number_val,
                        "tenant": tenant,
                        "std_id": standard_id,
                        "sub_id": subject_id,
                    },
                ).fetchone()
                if row:
                    chapter_id = row[0]
    except Exception as exc:
        logger.warning("Failed to map IDs: %s", exc)

    return standard_id, subject_id, chapter_id


def create_extraction_stub(
    *,
    document_type: str | None,
    document_title: str | None,
    chapter_number: int | None,
    standard: int | None,
    subject_name: str | None,
    board: str | None,
    syear: int | None,
    pdf_url: str,
    sub_institute_id: int | None = None,
    content_sha256: str | None = None,
) -> int | None:
    """Insert metadata row at job start; returns row id or None.

    `sub_institute_id` is the board's shared-bank tenant (1 = CBSE,
    341 = Cambridge). It is resolved from the board selected on the
    extraction form; passing None falls back to the configured default.
    """
    if not init_mariadb() or SessionLocal is None:
        return None

    tenant = sub_institute_id if sub_institute_id is not None else settings.tenant_for_board(board)

    db = SessionLocal()
    try:
        standard_id, subject_id, chapter_id = _map_ids(
            db, standard, subject_name, document_title, chapter_number, document_type, tenant
        )

        # A question bank is a set of questions FOR an existing chapter. If we
        # cannot find that chapter, inventing one would silently file the
        # questions against a chapter no syllabus refers to — fail loudly here
        # instead, so the operator picks the right chapter on the form.
        if chapter_id is None and is_question_bank(document_type):
            raise ChapterNotFoundError(
                f"No chapter found for question bank '{document_title}' "
                f"(chapter {chapter_number}, standard_id={standard_id}, "
                f"subject_id={subject_id}, tenant={tenant}). "
                "Extract the chapter first, or pick an existing chapter."
            )

        doc = DocumentExtraction(
            document_type=document_type,
            document_tittle=document_title,
            chapter_number=chapter_number,
            standard=standard,
            subject_name=subject_name,
            board=board,
            syear=syear,
            pdf_url=pdf_url,
            standard_id=standard_id,
            subject_id=subject_id,
            chapter_id=chapter_id,
            sub_institute_id=tenant,
            content_sha256=content_sha256,
            extraction_status="extracting",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        if (
            chapter_id is None
            and document_title
            and document_type not in ("Curriculum", "Syllabus")
            and not is_question_bank(document_type)
        ):
            try:
                res = db.execute(
                    text("""
                        INSERT INTO chapter_master 
                        (extraction_id, sub_institute_id, standard_id, subject_id, chapter_name, sort_order) 
                        VALUES (:ext_id, :tenant, :std_id, :sub_id, :cname, :sort_order)
                    """),
                    {
                        "ext_id": doc.id,
                        "tenant": tenant,
                        "std_id": standard_id,
                        "sub_id": subject_id,
                        "cname": document_title,
                        "sort_order": chapter_number
                    }
                )
                new_chapter_id = res.lastrowid
                doc.chapter_id = new_chapter_id
                db.commit()
            except Exception as e:
                logger.warning("Failed to auto-insert chapter: %s", e)
                db.rollback()

        return doc.id
    except ChapterNotFoundError:
        # Operator error, not an infrastructure failure. Surface it.
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("MariaDB insert failed: %s", exc)
        return None
    finally:
        db.close()


def persist_extraction_result(
    cache_id: int | None,
    response: ExtractionResponse,
    *,
    document_type: str | None = None,
    document_title: str | None = None,
    chapter_number: int | None = None,
    standard: int | None = None,
    subject_name: str | None = None,
    board: str | None = None,
    syear: int | None = None,
    pdf_url: str | None = None,
    sub_institute_id: int | None = None,
) -> int | None:
    """Save extraction output; updates existing row or inserts a full row."""
    if not init_mariadb() or SessionLocal is None:
        logger.error("MariaDB unavailable — extraction result was not persisted")
        return cache_id

    db = SessionLocal()
    try:
        doc: DocumentExtraction | None = None
        if cache_id is not None:
            doc = (
                db.query(DocumentExtraction)
                .filter(DocumentExtraction.id == cache_id)
                .first()
            )

        # Prefer the tenant already stored on the stub row; only fall back to
        # resolving from the board name when this is a fresh insert.
        tenant = (
            doc.sub_institute_id
            if doc is not None and doc.sub_institute_id is not None
            else (sub_institute_id if sub_institute_id is not None else settings.tenant_for_board(board))
        )

        standard_id, subject_id, chapter_id = _map_ids(
            db, standard, subject_name, document_title, chapter_number, document_type, tenant
        )

        if doc is None:
            doc = DocumentExtraction(
                document_type=document_type,
                document_tittle=document_title,
                chapter_number=chapter_number,
                standard=standard,
                subject_name=subject_name,
                board=board,
                syear=syear,
                pdf_url=pdf_url or "unknown",
                standard_id=standard_id,
                subject_id=subject_id,
                chapter_id=chapter_id,
                sub_institute_id=tenant,
            )
            db.add(doc)
        else:
            # Update mapped IDs in case they were not mapped during stub creation
            if standard_id is not None:
                doc.standard_id = standard_id
            if subject_id is not None:
                doc.subject_id = subject_id
            if chapter_id is not None:
                doc.chapter_id = chapter_id

        _apply_extraction_payload(doc, response, document_type=document_type)
        db.commit()
        db.refresh(doc)
        logger.info(
            "MariaDB saved extraction id=%s (md=%d chars)",
            doc.id,
            len(response.markdown_content or ""),
        )
        return doc.id
    except Exception as exc:
        db.rollback()
        logger.exception("MariaDB save failed: %s", exc)
        return cache_id
    finally:
        db.close()


# Eager init on import (retried lazily via init_mariadb if this fails).
init_mariadb()
