"""Tenant-wise display names for the Semantic Intelligence viewer tabs.

Every tenant sees the same 13-dimension payload, but schools name those
dimensions differently: one wants the "DOK" tab to read "Depth of Learning",
another wants "Competency" to read "NEP Competency". Only the *label* is
per-tenant. The tab_key is fixed and never renamed because the viewer keys its
panels and the stored JSON off it.

Rows exist only for tabs a tenant has actually renamed; anything without a row
falls back to the default label below, so a fresh tenant needs no seeding.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from app.db.mariadb import SessionLocal, init_mariadb

logger = logging.getLogger(__name__)

_TABLE = "semantic_tab_labels"

# The tenant whose labels are used when a caller does not name one. Matches the
# sub_institute_id hardcoded across the extraction pipeline.
DEFAULT_SUB_INSTITUTE_ID = 341

MAX_LABEL_LENGTH = 120

# Ordered: the viewer renders its tab strip in this order. Keys must match the
# TabsTrigger/TabsContent values in semantic-intelligence-viewer.tsx.
DEFAULT_TAB_LABELS: dict[str, str] = {
    "knowledge": "Knowledge",
    "ability": "Ability",
    "skill": "Skill",
    "competency": "Competency",
    "blooms": "Bloom's",
    "dok": "DOK",
    "prerequisite": "Prerequisites",
    "misconception": "Misconceptions",
    "realworld": "Real World",
    "pedagogy": "Pedagogy",
    "objectives": "Objectives",
    "outcomes": "Outcomes",
    "blueprint": "Blueprint",
    "rubrics": "Rubrics",
    "relationships": "Relationships",
    "evidence": "Evidence",
    "reasoning": "AI Reasoning",
    # Only present on the legacy 6-dimension layout, but renameable all the same.
    "activities": "Activities",
}


class TabLabelError(RuntimeError):
    """Raised when the label store cannot be read or written."""


def _ensure_table(db) -> None:
    """Create the override table on first use.

    The server default charset is latin1, so utf8mb4 is pinned explicitly here —
    without it a label carrying a curly quote or a Devanagari name is rejected
    with error 1366.
    """
    db.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {_TABLE} (
                id INT AUTO_INCREMENT PRIMARY KEY,
                sub_institute_id INT NOT NULL,
                tab_key VARCHAR(64) NOT NULL,
                custom_label VARCHAR({MAX_LABEL_LENGTH}) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_tenant_tab (sub_institute_id, tab_key)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
    )


def _session():
    if not init_mariadb() or SessionLocal is None:
        raise TabLabelError("Database not ready")
    return SessionLocal()


def _overrides(db, sub_institute_id: int) -> dict[str, str]:
    rows = db.execute(
        text(
            f"SELECT tab_key, custom_label FROM {_TABLE} "
            "WHERE sub_institute_id = :tid"
        ),
        {"tid": sub_institute_id},
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def _catalogue(overrides: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "tab_key": key,
            "default_label": default,
            "label": overrides.get(key, default),
            "is_custom": key in overrides,
        }
        for key, default in DEFAULT_TAB_LABELS.items()
    ]


def get_tab_labels(sub_institute_id: int = DEFAULT_SUB_INSTITUTE_ID) -> dict[str, Any]:
    """Full tab catalogue for one tenant, defaults filled in for un-renamed tabs."""
    db = _session()
    try:
        _ensure_table(db)
        db.commit()
        return {
            "sub_institute_id": sub_institute_id,
            "tabs": _catalogue(_overrides(db, sub_institute_id)),
        }
    finally:
        db.close()


def save_tab_labels(
    sub_institute_id: int,
    labels: dict[str, str | None],
) -> dict[str, Any]:
    """Upsert the given tab renames for one tenant.

    A label that is blank, or that equals the default, drops the override row
    rather than storing a redundant copy — so a tenant that renames a tab back
    to "Knowledge" automatically follows any future change to the default.
    """
    unknown = [key for key in labels if key not in DEFAULT_TAB_LABELS]
    if unknown:
        raise ValueError(f"Unknown tab key(s): {', '.join(sorted(unknown))}")

    db = _session()
    try:
        _ensure_table(db)

        for key, raw in labels.items():
            label = (raw or "").strip()
            if len(label) > MAX_LABEL_LENGTH:
                raise ValueError(
                    f"Label for '{key}' exceeds {MAX_LABEL_LENGTH} characters"
                )

            if not label or label == DEFAULT_TAB_LABELS[key]:
                db.execute(
                    text(
                        f"DELETE FROM {_TABLE} "
                        "WHERE sub_institute_id = :tid AND tab_key = :key"
                    ),
                    {"tid": sub_institute_id, "key": key},
                )
                continue

            db.execute(
                text(
                    f"""
                    INSERT INTO {_TABLE} (sub_institute_id, tab_key, custom_label)
                    VALUES (:tid, :key, :label)
                    ON DUPLICATE KEY UPDATE custom_label = VALUES(custom_label)
                    """
                ),
                {"tid": sub_institute_id, "key": key, "label": label},
            )

        db.commit()
        logger.info(
            "Saved %d semantic tab label(s) for tenant %s",
            len(labels),
            sub_institute_id,
        )
        return {
            "sub_institute_id": sub_institute_id,
            "tabs": _catalogue(_overrides(db, sub_institute_id)),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def reset_tab_labels(
    sub_institute_id: int,
    tab_key: str | None = None,
) -> dict[str, Any]:
    """Drop one override, or every override for the tenant when tab_key is None."""
    if tab_key is not None and tab_key not in DEFAULT_TAB_LABELS:
        raise ValueError(f"Unknown tab key: {tab_key}")

    db = _session()
    try:
        _ensure_table(db)
        if tab_key is None:
            db.execute(
                text(f"DELETE FROM {_TABLE} WHERE sub_institute_id = :tid"),
                {"tid": sub_institute_id},
            )
        else:
            db.execute(
                text(
                    f"DELETE FROM {_TABLE} "
                    "WHERE sub_institute_id = :tid AND tab_key = :key"
                ),
                {"tid": sub_institute_id, "key": tab_key},
            )
        db.commit()
        return {
            "sub_institute_id": sub_institute_id,
            "tabs": _catalogue(_overrides(db, sub_institute_id)),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
