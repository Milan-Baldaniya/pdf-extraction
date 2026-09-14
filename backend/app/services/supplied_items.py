"""Persist question items that were structured by hand rather than parsed.

`question_extractor` reads a chapter with regexes. That works where the book is
consistent, and this corpus is not: across eight chapters the section headings,
the item numbering ("1." vs "Q1." vs "Q.5"), the option markers ("(a)" vs "a)")
and the answer keys all differ, and some keys are damaged by OCR in ways no
pattern can repair -- chapter 1's key runs items 1 and 2 together as
"12. d) Quadrants a) (0, 8)" and items 12 and 13 as "123. d) 10 b) 3".

So the reading can be done by a model instead, and this module is where that
output lands. It deliberately owns nothing but the shaping: validation,
publishing policy, attribution and the four-table write are the SAME functions
the parser path uses, so a hand-read chapter and a parsed one are stored
identically and nothing downstream can tell them apart.

Supplied items only need what the source actually says. Everything derivable --
ordinal, content hash, section letter, per-item marks, attribution -- is filled
in here.
"""

from __future__ import annotations

import hashlib
from collections import Counter
import json
import logging
from typing import Any

from sqlalchemy import text

from app.db.mariadb import SessionLocal, init_mariadb
from app.services.exam_question_service import validate_items
from app.services.publisher_service import (
    ensure_publisher,
    register_question_types,
    render_attribution,
    type_map,
)
from app.services.question_bank_writer import write_question_bank
from app.services.question_extractor import FORM_TO_SECTION

logger = logging.getLogger(__name__)

_DEFAULT_ATTRIBUTION = "Extracted from the uploaded source document"


def _norm(value: str) -> str:
    return " ".join((value or "").split())


def _hash(item: dict[str, Any]) -> str:
    """Content hash over what was reproduced, so re-runs dedupe stably."""
    payload = "|".join(
        [
            _norm(item.get("stem") or ""),
            _norm(item.get("assertion") or ""),
            _norm(item.get("reason") or ""),
            "|".join(f"{o['label']}:{_norm(o['text'])}" for o in item.get("options") or []),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def shape(raw: list[dict[str, Any]], *, attribution: str, licence: str | None) -> list[dict[str, Any]]:
    """Fill the derivable fields around what was actually read off the page."""
    items: list[dict[str, Any]] = []
    for ordinal, entry in enumerate(raw, start=1):
        form = entry.get("form") or "unknown"
        section, default_marks = FORM_TO_SECTION.get(form, ("A", 1))
        options = [
            {
                "label": str(option["label"]).upper(),
                "sequence": index,
                "text": _norm(option["text"]),
                "is_correct": bool(option.get("is_correct")),
            }
            for index, option in enumerate(entry.get("options") or [])
        ]

        correct = (entry.get("correct_option") or "").upper() or None
        if correct:
            for option in options:
                option["is_correct"] = option["label"] == correct

        item = {
            "item_ordinal": ordinal,
            "item_number": str(entry.get("number") or ordinal),
            "exam_section": entry.get("section") or section,
            "section_heading": entry.get("section_heading"),
            "section_marks": entry.get("marks") or default_marks,
            "item_form": form,
            "marks": entry.get("marks") or default_marks,
            "stem": _norm(entry.get("stem") or ""),
            "options": options,
            "correct_option": correct,
            "answer_text": _norm(entry.get("answer") or "") or None,
            "assertion": _norm(entry.get("assertion") or "") or None,
            "reason": _norm(entry.get("reason") or "") or None,
            "sub_part_labels": entry.get("sub_parts") or [],
            "choice_group_id": None,
            "choice_role": None,
            "figure_required": bool(entry.get("figure_required")),
            "images": entry.get("images") or [],
            "source_page": entry.get("page"),
            "source_char_start": None,
            "source_char_end": None,
            "reproduction": "verbatim",
            "attribution": attribution,
            "licence": licence,
        }
        item["verbatim_sha256"] = _hash(item)
        item["verbatim_payload"] = json.dumps(
            {k: item[k] for k in ("stem", "options", "assertion", "reason", "answer_text")},
            ensure_ascii=False,
            default=str,
        )
        items.append(item)
    return items


def persist_supplied(
    extraction_id: int,
    raw_items: list[dict[str, Any]],
    *,
    created_by: int = 1,
    replace: bool = True,
    publish_clean: bool = True,
    dry_run: bool = False,
    publisher_code: str | None = None,
) -> dict[str, Any]:
    """Validate and write hand-read items for one extraction."""
    if not init_mariadb() or SessionLocal is None:
        raise RuntimeError("Database not ready")

    db = SessionLocal()
    try:
        record = db.execute(
            text(
                """
                SELECT id, document_tittle, chapter_number, standard_id, subject_id,
                       chapter_id, sub_institute_id, board, syear, asset_manifest,
                       publisher_id
                  FROM document_extractions WHERE id = :i
                """
            ),
            {"i": extraction_id},
        ).mappings().fetchone()
    finally:
        db.close()

    if not record:
        raise LookupError(f"Extraction {extraction_id} not found")
    record = dict(record)
    if not record.get("chapter_id"):
        raise ValueError(f"Extraction {extraction_id} is not mapped to a chapter.")

    publisher = ensure_publisher(code=publisher_code, name=None, board=record.get("board")) if publisher_code else None
    attribution = render_attribution(publisher, record) or _DEFAULT_ATTRIBUTION
    licence = (publisher or {}).get("licence_type")

    items = shape(raw_items, attribution=attribution, licence=licence)
    reports = validate_items(items)
    failed = {ordinal for ordinal, report in reports.items() if report["failed"]}

    summary: dict[str, Any] = {
        "status": "success",
        "extraction_id": extraction_id,
        "chapter_id": record["chapter_id"],
        "dry_run": dry_run,
        "parsed": len(items),
        "total_marks": sum(i["marks"] or 0 for i in items),
        "sections": {},
        "question_types": {},
        "validation": {
            "failed": len(failed),
            "with_warnings": sum(1 for r in reports.values() if r["warnings"]),
            "by_code": {},
        },
        "attribution": attribution,
    }
    for item in items:
        summary["sections"][item["exam_section"]] = summary["sections"].get(item["exam_section"], 0) + 1
        summary["question_types"][item["item_form"]] = summary["question_types"].get(item["item_form"], 0) + 1
    for report in reports.values():
        for entry in report["failed"] + report["warnings"]:
            summary["validation"]["by_code"][entry["code"]] = (
                summary["validation"]["by_code"].get(entry["code"], 0) + 1
            )

    if dry_run:
        return summary

    publisher_id = (publisher or {}).get("id") or record.get("publisher_id")
    if publisher_id:
        # Counts per form, so a form this publisher has never used is created
        # and tagged to them rather than rejected.
        register_question_types(
            dict(Counter(i["item_form"] for i in items)),
            publisher_id=publisher_id,
            extraction_id=extraction_id,
        )
    catalog = type_map(publisher_id) if publisher_id else {}

    # write_question_bank owns its own session, transaction and retry loop.
    counters = write_question_bank(
        extraction_id=extraction_id,
        sub_institute_id=record["sub_institute_id"],
        standard_id=record.get("standard_id"),
        subject_id=record.get("subject_id"),
        chapter_id=record["chapter_id"],
        items=items,
        asset_manifest=record.get("asset_manifest"),
        created_by=created_by,
        replace=replace,
        publish_clean=publish_clean,
        validations=reports,
        publisher_id=publisher_id,
        type_catalog=catalog,
    )

    summary.update(counters)
    summary["published"] = counters["inserted"] - counters["held"]
    return summary
