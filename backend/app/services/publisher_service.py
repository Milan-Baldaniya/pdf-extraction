"""Publishers and the question-type catalogue.

Two jobs.

**Publishers.** A question bank belongs to whoever published it, and that is
not the same thing as the board it targets: KVS publishes CBSE material, a
private house may publish for several boards, and the licence and required
attribution line are properties of the publisher. Every extracted item is
stamped with the publisher so the source can always be named on screen and
on a printed paper.

**The type catalogue.** Publishers invent question forms. One prints
"Competency Focused Questions", another "Source-Based Integrated". The LMS
`question_type_master` cannot absorb those: its ids are referenced by live
papers and it is tenant-scoped, so adding rows there would either collide or
be invisible to other tenants. Instead an unknown form is recorded here
against the publisher that used it, mapped onto an existing LMS type id for
delivery. Nothing is lost, nothing existing has to move, and the next time
that publisher is ingested the form is already known.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import text

from app.db.mariadb import SessionLocal, init_mariadb

logger = logging.getLogger(__name__)

# LMS question_type_master ids in this schema (verified):
#   1 multiple, 2 narrative, 8 assertion & reason
_LMS_MCQ = 1
_LMS_NARRATIVE = 2
_LMS_ASSERTION = 8

# The board-standard forms. Seeded with publisher_id NULL, meaning "not
# specific to any publisher".
STANDARD_TYPES: list[dict[str, Any]] = [
    {"code": "mcq", "label": "Multiple Choice", "lms": _LMS_MCQ, "section": "A", "marks": 1, "auto": 1},
    {"code": "assertion_reason", "label": "Assertion & Reason", "lms": _LMS_ASSERTION, "section": "A", "marks": 1, "auto": 1},
    {"code": "true_false", "label": "True / False", "lms": _LMS_MCQ, "section": "A", "marks": 1, "auto": 1},
    {"code": "fill_blank", "label": "Fill in the Blank", "lms": _LMS_NARRATIVE, "section": "A", "marks": 1, "auto": 0},
    {"code": "match_following", "label": "Match the Following", "lms": _LMS_NARRATIVE, "section": "A", "marks": 1, "auto": 0},
    {"code": "very_short", "label": "Very Short Answer", "lms": _LMS_NARRATIVE, "section": "B", "marks": 2, "auto": 0},
    {"code": "short", "label": "Short Answer", "lms": _LMS_NARRATIVE, "section": "C", "marks": 3, "auto": 0},
    {"code": "long", "label": "Long Answer", "lms": _LMS_NARRATIVE, "section": "D", "marks": 5, "auto": 0},
    {"code": "case_study_parent", "label": "Case-Based (stem)", "lms": _LMS_NARRATIVE, "section": "E", "marks": 4, "auto": 0},
    {"code": "case_study_child", "label": "Case-Based (sub-part)", "lms": _LMS_NARRATIVE, "section": "E", "marks": 1, "auto": 0},
    {"code": "proof", "label": "Prove / Show That", "lms": _LMS_NARRATIVE, "section": "D", "marks": 5, "auto": 0},
    {"code": "construction", "label": "Plot / Draw / Construct", "lms": _LMS_NARRATIVE, "section": "C", "marks": 3, "auto": 0},
    {"code": "numerical", "label": "Numerical Response", "lms": _LMS_NARRATIVE, "section": "B", "marks": 2, "auto": 0},
    {"code": "unknown", "label": "Unclassified", "lms": _LMS_NARRATIVE, "section": None, "marks": None, "auto": 0},
]

# Publishers we already know about. Seeding these means an operator picks
# from a list instead of retyping an attribution line per upload.
SEED_PUBLISHERS: list[dict[str, Any]] = [
    {
        "code": "kvs_ro_agra",
        "name": "Kendriya Vidyalaya Sangathan, Regional Office Agra",
        "short_name": "KVS RO Agra",
        "publisher_type": "government",
        "default_board": "CBSE",
        "licence_type": "KVS website reuse policy",
        "licence_url": "https://kvsangathan.nic.in/en/website-policies/",
        "attribution_template": "{publisher} — {title}, Class {standard} {subject}, Session {syear}",
        "attribution_required": 1,
        "notes": "Free reuse permitted if reproduced accurately and the source is prominently acknowledged. Does not cover third-party material inside the document.",
    },
    {
        "code": "ncert",
        "name": "National Council of Educational Research and Training",
        "short_name": "NCERT",
        "publisher_type": "government",
        "default_board": "CBSE",
        "licence_type": "NCERT terms of use",
        "attribution_template": "{publisher} — {title}, Class {standard} {subject}",
        "attribution_required": 1,
    },
    {
        "code": "cbse",
        "name": "Central Board of Secondary Education",
        "short_name": "CBSE",
        "publisher_type": "board",
        "default_board": "CBSE",
        "licence_type": "CBSE terms of use",
        "attribution_template": "{publisher} — {title}, Class {standard} {subject}, {syear}",
        "attribution_required": 1,
    },
    {
        "code": "cambridge",
        "name": "Cambridge Assessment International Education",
        "short_name": "Cambridge",
        "publisher_type": "board",
        "default_board": "CAMBRIDGE",
        "licence_type": "Publisher permission required",
        "attribution_template": "{publisher} — {title}, {subject}, {syear}",
        "attribution_required": 1,
    },
]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")[:64]


def _session():
    if not init_mariadb() or SessionLocal is None:
        raise RuntimeError("Database not ready")
    return SessionLocal()


def seed_reference_data() -> dict[str, int]:
    """Insert the known publishers and standard question forms. Idempotent."""
    db = _session()
    created = {"publishers": 0, "types": 0}
    try:
        for pub in SEED_PUBLISHERS:
            exists = db.execute(
                text("SELECT id FROM question_publisher WHERE code = :c"), {"c": pub["code"]}
            ).scalar()
            if exists:
                continue
            db.execute(
                text(
                    """
                    INSERT INTO question_publisher
                        (code, name, short_name, publisher_type, default_board,
                         licence_type, licence_url, attribution_template,
                         attribution_required, notes, status)
                    VALUES (:code, :name, :short_name, :publisher_type, :default_board,
                            :licence_type, :licence_url, :attribution_template,
                            :attribution_required, :notes, 1)
                    """
                ),
                {
                    "licence_url": None,
                    "notes": None,
                    **pub,
                },
            )
            created["publishers"] += 1

        for spec in STANDARD_TYPES:
            exists = db.execute(
                text(
                    "SELECT id FROM question_type_catalog "
                    "WHERE code = :c AND publisher_id IS NULL"
                ),
                {"c": spec["code"]},
            ).scalar()
            if exists:
                continue
            db.execute(
                text(
                    """
                    INSERT INTO question_type_catalog
                        (code, label, publisher_id, lms_question_type_id, exam_section,
                         default_marks, auto_gradable, is_standard, status)
                    VALUES (:code, :label, NULL, :lms, :section, :marks, :auto, 1, 1)
                    """
                ),
                spec,
            )
            created["types"] += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    if created["publishers"] or created["types"]:
        logger.info("Seeded reference data: %s", created)
    return created


def ensure_publisher(
    *,
    code: str | None = None,
    name: str | None = None,
    board: str | None = None,
    licence_type: str | None = None,
    attribution_template: str | None = None,
) -> dict[str, Any] | None:
    """Find a publisher by code or name, creating it if it is new.

    An unknown publisher is registered rather than rejected: the point of
    widening beyond KVS is that a new source should be ingestable without a
    code change. What it must not do is go in unnamed, because attribution
    is a licence condition.
    """
    if not code and not name:
        return None
    code = _slug(code or name or "")
    db = _session()
    try:
        row = db.execute(
            text("SELECT * FROM question_publisher WHERE code = :c"), {"c": code}
        ).mappings().fetchone()
        if row:
            return dict(row)

        db.execute(
            text(
                """
                INSERT INTO question_publisher
                    (code, name, short_name, publisher_type, default_board,
                     licence_type, attribution_template, attribution_required, status)
                VALUES (:code, :name, :short_name, 'other', :board,
                        :licence_type, :attribution_template, 1, 1)
                """
            ),
            {
                "code": code,
                "name": name or code.replace("_", " ").title(),
                "short_name": (name or code)[:64],
                "board": board,
                "licence_type": licence_type or "Unspecified — confirm before publishing",
                "attribution_template": attribution_template
                or "{publisher} — {title}, Class {standard} {subject}, {syear}",
            },
        )
        db.commit()
        logger.info("Registered new publisher %s", code)
        row = db.execute(
            text("SELECT * FROM question_publisher WHERE code = :c"), {"c": code}
        ).mappings().fetchone()
        return dict(row) if row else None
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def list_publishers() -> list[dict[str, Any]]:
    db = _session()
    try:
        rows = db.execute(
            text(
                "SELECT id, code, name, short_name, publisher_type, default_board, "
                "licence_type, attribution_required FROM question_publisher "
                "WHERE status = 1 ORDER BY name"
            )
        ).mappings().fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def register_question_types(
    codes: dict[str, int],
    *,
    publisher_id: int | None,
    extraction_id: int | None = None,
) -> list[str]:
    """Record the forms seen in one ingest; create any that are new.

    `codes` maps a form code to how many times it appeared. A code already in
    the standard set is counted there; anything else is filed against this
    publisher, which is what makes a publisher-specific form first-class
    rather than silently flattened to "narrative".
    """
    if not codes:
        return []
    db = _session()
    new: list[str] = []
    try:
        for code, count in codes.items():
            row = db.execute(
                text(
                    "SELECT id, publisher_id FROM question_type_catalog "
                    "WHERE code = :c AND (publisher_id IS NULL OR publisher_id = :p) "
                    "ORDER BY publisher_id IS NULL DESC LIMIT 1"
                ),
                {"c": code, "p": publisher_id},
            ).mappings().fetchone()

            if row:
                db.execute(
                    text(
                        "UPDATE question_type_catalog "
                        "SET seen_count = seen_count + :n WHERE id = :id"
                    ),
                    {"n": count, "id": row["id"]},
                )
                continue

            db.execute(
                text(
                    """
                    INSERT INTO question_type_catalog
                        (code, label, publisher_id, lms_question_type_id, exam_section,
                         default_marks, auto_gradable, is_standard,
                         description, first_seen_extraction_id, seen_count, status)
                    VALUES (:code, :label, :publisher_id, :lms, NULL,
                            NULL, 0, 0,
                            :description, :extraction_id, :count, 1)
                    """
                ),
                {
                    "code": code,
                    "label": code.replace("_", " ").title(),
                    "publisher_id": publisher_id,
                    # Unknown forms deliver as narrative: it is the only LMS
                    # type that can hold an arbitrary answer without claiming
                    # the item is auto-gradable.
                    "lms": _LMS_NARRATIVE,
                    "description": "Discovered during ingestion; review the mapping and marks.",
                    "extraction_id": extraction_id,
                    "count": count,
                },
            )
            new.append(code)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    if new:
        logger.info(
            "New question types registered for publisher %s: %s", publisher_id, ", ".join(new)
        )
    return new


def type_map(publisher_id: int | None = None) -> dict[str, dict[str, Any]]:
    """code -> catalogue row, with the publisher's own entry winning."""
    db = _session()
    try:
        rows = db.execute(
            text(
                "SELECT code, label, publisher_id, lms_question_type_id, exam_section, "
                "default_marks, auto_gradable, is_standard "
                "FROM question_type_catalog WHERE status = 1 "
                "AND (publisher_id IS NULL OR publisher_id = :p) "
                "ORDER BY publisher_id IS NULL DESC"
            ),
            {"p": publisher_id},
        ).mappings().fetchall()
        # publisher_id NULL first, so a publisher-specific row overwrites it.
        return {r["code"]: dict(r) for r in rows}
    finally:
        db.close()


def render_attribution(publisher: dict[str, Any] | None, record: dict[str, Any]) -> str:
    """Build the source line that must appear with the item."""
    if not publisher:
        return (
            f"{record.get('board') or 'Source'} — {record.get('document_tittle') or 'Question bank'}"
        )
    template = publisher.get("attribution_template") or "{publisher} — {title}"
    try:
        return template.format(
            publisher=publisher.get("name") or publisher.get("short_name") or "",
            short_name=publisher.get("short_name") or "",
            title=record.get("document_tittle") or "Question bank",
            standard=record.get("standard") or "",
            subject=record.get("subject_name") or "",
            syear=record.get("syear") or "",
            board=record.get("board") or "",
        ).replace("  ", " ").strip(" ,—-")
    except (KeyError, IndexError, ValueError):
        return f"{publisher.get('name')} — {record.get('document_tittle') or ''}".strip(" —")
