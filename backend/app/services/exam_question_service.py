"""Orchestrate the question-bank stage: parse -> validate -> persist.

This is what the Proceed button drives. It reads a `question_bank` row from
`document_extractions`, parses the stored markdown into structured exam
items, runs the cheap validators, and writes the four question tables.

The validator tier here is deliberately the cheap one — pure Python, no LLM,
no CAS. Its job is to decide what may auto-publish and what must wait for a
teacher. An item that fails is still stored (so a reviewer can see and fix
it) but lands with `status = 0`, which keeps it out of the question bank and
out of any paper until someone clears it.

`dry_run=True` parses and validates and writes nothing. That is the cheapest
way to iterate the parser against a real chapter, and it is what the queue
screen calls for its preview.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text

from app.db.mariadb import SessionLocal, init_mariadb
from app.services.question_bank_writer import write_question_bank
from app.services.publisher_service import (
    ensure_publisher,
    register_question_types,
    render_attribution,
    type_map,
)
from app.services.question_extractor import extract_questions, summarise

logger = logging.getLogger(__name__)

VALIDATOR_VERSION = "v1"

_DEFAULT_ATTRIBUTION = "Extracted from the uploaded source document"


def _load_extraction(extraction_id: int) -> dict[str, Any]:
    if not init_mariadb() or SessionLocal is None:
        raise RuntimeError("Database not ready")
    db = SessionLocal()
    try:
        row = db.execute(
            text(
                """
                SELECT id, document_type, document_tittle, chapter_number,
                       standard, standard_id, subject_name, subject_id, chapter_id,
                       sub_institute_id, board, syear, md_content, asset_manifest,
                       extraction_status, publisher_id
                  FROM document_extractions
                 WHERE id = :id
                """
            ),
            {"id": extraction_id},
        ).mappings().fetchone()
        if not row:
            raise LookupError(f"Extraction {extraction_id} not found")
        return dict(row)
    finally:
        db.close()


def validate_items(items: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Cheap per-item checks. Returns {item_ordinal: report} for failures only.

    Every check here is one the source document can actually be wrong about,
    and each maps to a real defect seen in this corpus:

      V-02  the printed key letter is not among the parsed options
      V-04  an MCQ with no key at all
      V-06  an empty stem (the question text did not survive extraction)
      V-07  the text refers to a figure but no image was captured
      V-08  a duplicate of an item already seen in this chapter
      V-09  an MCQ that did not yield four options
      V-10  an Assertion-Reason item missing either half
      V-11  an option too long for answer_master.answer (varchar 250)
    """
    reports: dict[int, dict[str, Any]] = {}
    seen_hashes: dict[str, str] = {}

    for item in items:
        failures: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        ordinal = item["item_ordinal"]
        options = item.get("options") or []

        if not (item.get("stem") or "").strip():
            failures.append({"code": "V-06", "message": "Question text is empty."})

        digest = item.get("verbatim_sha256")
        if digest:
            if digest in seen_hashes:
                failures.append(
                    {
                        "code": "V-08",
                        "message": f"Duplicate of item {seen_hashes[digest]} in this chapter.",
                    }
                )
            else:
                seen_hashes[digest] = item.get("item_number") or str(ordinal)

        form = item.get("item_form")

        # An MCQ must carry its own four options. An Assertion-Reason item
        # must not be judged the same way: in this corpus the a/b/c/d legend
        # is printed ONCE at the head of the block and the items answer
        # against it, so demanding four parsed options per item flags every
        # correctly-extracted A-R question as broken.
        if form == "mcq" and len(options) != 4:
            failures.append(
                {"code": "V-09", "message": f"Expected 4 options, parsed {len(options)}."}
            )

        if form == "assertion_reason" and not (item.get("assertion") and item.get("reason")):
            failures.append(
                {
                    "code": "V-10",
                    "message": "Assertion and Reason were not both recovered as separate fields.",
                }
            )

        if form in {"mcq", "assertion_reason"}:
            if not item.get("correct_option"):
                failures.append({"code": "V-04", "message": "No correct option in the printed key."})
            elif options and not any(o.get("is_correct") for o in options):
                failures.append(
                    {
                        "code": "V-02",
                        "message": (
                            f"Key letter {item['correct_option']} is not among the parsed options."
                        ),
                    }
                )

        if item.get("figure_required") and not item.get("images"):
            failures.append(
                {"code": "V-07", "message": "Refers to a figure, but no image was captured."}
            )

        for option in options:
            if len(option.get("text") or "") > 250:
                failures.append(
                    {
                        "code": "V-11",
                        "message": (
                            f"Option {option.get('label')} is longer than the 250 characters "
                            "answer_master stores; truncating it would misreproduce the source."
                        ),
                    }
                )
                break

        if not (item.get("answer_text") or "").strip() and item.get("item_form") not in {
            "mcq",
            "assertion_reason",
        }:
            warnings.append({"code": "W-01", "message": "No worked solution found for this item."})

        if failures or warnings:
            reports[ordinal] = {
                "version": VALIDATOR_VERSION,
                "item_number": item.get("item_number"),
                "failed": failures,
                "warnings": warnings,
            }
    return reports


def process_exam_questions(
    extraction_id: int,
    *,
    created_by: int = 0,
    replace: bool = False,
    publish_clean: bool = True,
    dry_run: bool = False,
    attribution: str | None = None,
    licence: str | None = None,
    publisher_code: str | None = None,
    publisher_name: str | None = None,
) -> dict[str, Any]:
    """Parse, validate and (unless dry_run) persist one chapter's items."""
    record = _load_extraction(extraction_id)

    md = record.get("md_content")
    if not md or not md.strip():
        raise ValueError(
            f"Extraction {extraction_id} has no markdown. Run the PDF extraction first."
        )
    if not record.get("chapter_id"):
        raise ValueError(
            f"Extraction {extraction_id} is not mapped to a chapter. "
            "A question bank must attach to an existing chapter."
        )

    # Resolve the publisher. An unknown one is registered rather than
    # rejected: widening beyond a single source is the whole point, and a new
    # publisher should be ingestable without a code change. What it may not be
    # is anonymous, because attribution is a licence condition.
    publisher = None
    if publisher_code or publisher_name:
        publisher = ensure_publisher(
            code=publisher_code, name=publisher_name, board=record.get("board")
        )
    elif record.get("publisher_id"):
        db = SessionLocal()
        try:
            row = db.execute(
                text("SELECT * FROM question_publisher WHERE id = :i"),
                {"i": record["publisher_id"]},
            ).mappings().fetchone()
            publisher = dict(row) if row else None
        finally:
            db.close()

    source_label = attribution or render_attribution(publisher, record) or _DEFAULT_ATTRIBUTION
    licence = licence or (publisher or {}).get("licence_type")

    parsed = extract_questions(md, attribution=source_label, licence=licence)
    items = parsed["items"]
    reports = validate_items(items)
    failed_ordinals = {k for k, v in reports.items() if v["failed"]}

    summary = summarise(items, has_answer_key=parsed["answer_key_found"])
    response: dict[str, Any] = {
        "status": "success",
        "extraction_id": extraction_id,
        "chapter_id": record["chapter_id"],
        "sub_institute_id": record["sub_institute_id"],
        "dry_run": dry_run,
        "parsed": len(items),
        "blueprint": summary["blueprint"],
        "sections": {k: v["count"] for k, v in summary["sections"].items()},
        "question_types": summary["question_types"],
        "total_marks": summary["totals"]["marks"],
        "validation": {
            "failed": len(failed_ordinals),
            "with_warnings": len(reports) - len(failed_ordinals),
            "by_code": _count_codes(reports),
        },
        "warnings": summary["warnings"] + parsed["warnings"],
        "attribution": source_label,
    }

    if dry_run:
        assets = _asset_index(record.get("asset_manifest"))
        for item in items:
            item["_figures"] = _figures_for(item, assets)
        response["publisher"] = {
            "id": (publisher or {}).get("id"),
            "name": (publisher or {}).get("name"),
            "code": (publisher or {}).get("code"),
            "licence": licence,
        }
        response["preview"] = [_preview(i, reports.get(i["item_ordinal"])) for i in items]
        return response

    publisher_id = (publisher or {}).get("id")
    # Record every form seen, creating catalogue rows for any this publisher
    # uses that we have not met before. That is what keeps a publisher's own
    # question types first-class instead of flattened into "narrative".
    form_counts: dict[str, int] = {}
    for item in items:
        form_counts[item["item_form"]] = form_counts.get(item["item_form"], 0) + 1
    new_types = register_question_types(
        form_counts, publisher_id=publisher_id, extraction_id=extraction_id
    )
    catalog = type_map(publisher_id)
    response["publisher"] = {
        "id": publisher_id,
        "name": (publisher or {}).get("name"),
        "code": (publisher or {}).get("code"),
        "licence": licence,
    }
    response["question_types_new"] = new_types

    counters = write_question_bank(
        extraction_id=extraction_id,
        sub_institute_id=record["sub_institute_id"],
        standard_id=record["standard_id"],
        subject_id=record["subject_id"],
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
    response.update(counters)
    response["published"] = counters["inserted"] - counters["held"]

    if publisher_id and not record.get("publisher_id"):
        db = SessionLocal()
        try:
            db.execute(
                text("UPDATE document_extractions SET publisher_id = :p WHERE id = :e"),
                {"p": publisher_id, "e": extraction_id},
            )
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
    logger.info(
        "Question bank stage complete for extraction %s: %s", extraction_id, counters
    )
    return response


def _count_codes(reports: dict[int, dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for report in reports.values():
        for entry in report["failed"] + report["warnings"]:
            counts[entry["code"]] = counts.get(entry["code"], 0) + 1
    return counts


def _asset_index(manifest: Any) -> dict[str, dict[str, Any]]:
    """Manifest keyed by file name, for resolving a markdown image ref."""
    if isinstance(manifest, str):
        try:
            manifest = json.loads(manifest)
        except ValueError:
            return {}
    if not isinstance(manifest, list):
        return {}
    return {
        str(entry["file_name"]): entry
        for entry in manifest
        if isinstance(entry, dict) and entry.get("file_name")
    }


def _figures_for(item: dict[str, Any], assets: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve an item's markdown image refs to displayable asset records."""
    out: list[dict[str, Any]] = []
    for ref in item.get("images") or []:
        name = str(ref).split("?", 1)[0].replace("\\", "/").rstrip(")").rsplit("/", 1)[-1]
        asset = assets.get(name)
        if not asset:
            continue
        out.append(
            {
                "url": asset.get("url"),
                "sha256": asset.get("sha256"),
                "width": asset.get("width"),
                "height": asset.get("height"),
                "page": asset.get("page_number"),
                "caption": asset.get("caption"),
                # Text read out of the figure itself — for a graph question
                # this is often the only place the values appear.
                "ocr_text": asset.get("ocr_text"),
            }
        )
    return out


def _preview(item: dict[str, Any], report: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "item_number": item["item_number"],
        "exam_section": item["exam_section"],
        "item_form": item["item_form"],
        "marks": item["marks"],
        "stem": (item["stem"] or "")[:400],
        "options": [
            {"label": o["label"], "text": o["text"][:200], "is_correct": o["is_correct"]}
            for o in item.get("options", [])
        ],
        "correct_option": item.get("correct_option"),
        "answer_text": (item.get("answer_text") or "")[:600] or None,
        "source_page": item.get("source_page"),
        "assertion": item.get("assertion"),
        "reason": item.get("reason"),
        "sub_part_labels": item.get("sub_part_labels") or [],
        "figure_required": bool(item.get("figure_required")),
        "figures": item.get("_figures") or [],
        "validation": report,
    }


def get_exam_questions(extraction_id: int) -> dict[str, Any]:
    """Read persisted items back, grouped by CBSE section.

    Served from the database rather than a job payload: the in-memory job
    registry is lost on restart, and the write is already committed, so a
    lost job should cost the client a refresh rather than the data.
    """
    if not init_mariadb() or SessionLocal is None:
        raise RuntimeError("Database not ready")
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT e.item_ordinal, e.item_number, e.exam_section, e.section_heading,
                       e.section_marks, e.item_form, e.validation_status, e.validation_report,
                       e.source_page, e.attribution, e.figure_required, e.figure_resolved,
                       e.bloom_level, e.dok_level, e.difficulty_1_to_5, e.concept_id,
                       e.concept_confidence, e.ai_model, e.question_type_code,
                       lc.name AS concept_name, pub.name AS publisher_name,
                       q.id AS question_id, q.question_title, q.points, q.status, q.answer
                  FROM lms_question_extraction e
                  JOIN lms_question_master q ON q.id = e.question_id
                  LEFT JOIN lms_concept lc ON lc.id = e.concept_id
                  LEFT JOIN question_publisher pub ON pub.id = e.publisher_id
                 WHERE e.extraction_id = :id
                 ORDER BY e.item_ordinal
                """
            ),
            {"id": extraction_id},
        ).mappings().fetchall()

        sections: dict[str, dict[str, Any]] = {}
        total_marks = 0
        for row in rows:
            envelope: dict[str, Any] = {}
            if row["answer"]:
                try:
                    envelope = json.loads(row["answer"])
                except ValueError:
                    envelope = {}
            letter = row["exam_section"] or "?"
            section = sections.setdefault(
                letter,
                {
                    "section": letter,
                    "heading": row["section_heading"],
                    "marks_each": row["section_marks"],
                    "items": [],
                },
            )
            section["items"].append(
                {
                    "question_id": row["question_id"],
                    "item_number": row["item_number"],
                    "item_form": row["item_form"],
                    "marks": row["points"],
                    "published": bool(row["status"]),
                    "validation_status": row["validation_status"],
                    "validation_report": _maybe_json(row["validation_report"]),
                    "stem": row["question_title"],
                    "options": envelope.get("options", []),
                    "correct_option": envelope.get("correct_option"),
                    "model_answer": envelope.get("model_answer"),
                    "assertion": envelope.get("assertion"),
                    "reason": envelope.get("reason"),
                    "sub_part_labels": envelope.get("sub_part_labels", []),
                    "auto_gradable": envelope.get("auto_gradable"),
                    "source_page": row["source_page"],
                    "figure_required": bool(row["figure_required"]),
                    "figure_resolved": bool(row["figure_resolved"]),
                    "attribution": row["attribution"],
                    "publisher": row["publisher_name"],
                    "question_type_code": row["question_type_code"],
                    "concept_id": row["concept_id"],
                    "concept_name": row["concept_name"],
                    "concept_confidence": float(row["concept_confidence"]) if row["concept_confidence"] is not None else None,
                    "bloom_level": row["bloom_level"],
                    "dok_level": row["dok_level"],
                    "difficulty_1_to_5": row["difficulty_1_to_5"],
                    "ai_model": row["ai_model"],
                    "figures": _question_figures(db, row["question_id"]),
                }
            )
            total_marks += row["points"] or 0

        return {
            "extraction_id": extraction_id,
            "total": len(rows),
            "total_marks": total_marks,
            "held": sum(1 for r in rows if not r["status"]),
            "sections": [sections[k] for k in sorted(sections)],
        }
    finally:
        db.close()


def _question_figures(db, question_id: int) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            "SELECT stored_url, asset_sha256, width, height, alt_text, ocr_text, source_page "
            "FROM lms_question_asset WHERE question_id = :q ORDER BY ordinal"
        ),
        {"q": question_id},
    ).mappings().fetchall()
    return [
        {
            "url": r["stored_url"],
            "sha256": r["asset_sha256"],
            "width": r["width"],
            "height": r["height"],
            "caption": r["alt_text"],
            "ocr_text": r["ocr_text"],
            "page": r["source_page"],
        }
        for r in rows
    ]


def _maybe_json(value: Any) -> Any:
    if not value:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None
