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

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_type = Column(String(255), nullable=True)
    document_tittle = Column(String(255), nullable=True)
    chapter_number = Column(Integer, nullable=True)
    standard = Column(Integer, nullable=True)
    subject_name = Column(String(255), nullable=True)
    board = Column(String(255), nullable=True)
    syear = Column(String(255), nullable=True)
    pdf_url = Column(Text, nullable=True)

    md_content = Column(LONGTEXT, nullable=True)
    json_content = Column(LONGTEXT, nullable=True)
    page_count = Column(Integer, nullable=True)
    image_extracted = Column(Integer, nullable=True)
    extraction_metadata = Column(LONGTEXT, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


def _mariadb_url() -> URL:
    return URL.create(
        "mysql+pymysql",
        username=settings.mariadb_user,
        password=settings.mariadb_password,
        host=settings.mariadb_host,
        port=settings.mariadb_port,
        database=settings.mariadb_db,
    )


def init_mariadb() -> bool:
    """Connect to MariaDB and ensure the extractions table exists."""
    global _engine, SessionLocal, _init_error

    if SessionLocal is not None:
        return True

    try:
        _engine = create_engine(_mariadb_url(), pool_recycle=3600)
        with _engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
        Base.metadata.create_all(bind=_engine)
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


def _apply_extraction_payload(doc: DocumentExtraction, response: ExtractionResponse) -> None:
    doc.md_content = response.markdown_content
    doc.json_content = _json_dumps(response.json_content)
    doc.page_count = response.page_count
    doc.image_extracted = response.images_extracted
    doc.extraction_metadata = _json_dumps(response.metadata)


def create_extraction_stub(
    *,
    document_type: str | None,
    document_title: str | None,
    chapter_number: int | None,
    standard: int | None,
    subject_name: str | None,
    board: str | None,
    syear: str | None,
    pdf_url: str,
) -> int | None:
    """Insert metadata row at job start; returns row id or None."""
    if not init_mariadb() or SessionLocal is None:
        return None

    db = SessionLocal()
    try:
        doc = DocumentExtraction(
            document_type=document_type,
            document_tittle=document_title,
            chapter_number=chapter_number,
            standard=standard,
            subject_name=subject_name,
            board=board,
            syear=syear,
            pdf_url=pdf_url,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc.id
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
    syear: str | None = None,
    pdf_url: str | None = None,
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
            )
            db.add(doc)

        _apply_extraction_payload(doc, response)
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
