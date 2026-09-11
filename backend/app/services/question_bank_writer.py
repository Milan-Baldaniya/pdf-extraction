"""Persist extracted exam items into the LMS question-bank tables.

Writes four tables in one transaction per chapter:

  lms_question_master      the item itself, with the JSON `answer` envelope
                           the existing generated columns project out of
  answer_master            one row per MCQ option, correct flag included
  lms_question_extraction  CBSE structure, provenance and the verbatim copy
  lms_question_asset       figures, by content hash rather than by URL

Deliberately does NOT write `pal_question_metadata`. That table decides what
a learner is served, and the LMS enforces tenancy and the machine-actor
status rule through `ContentMetadataService`. Writing it with raw SQL from
here would bypass those checks — the existing generator already does that,
and it is a governance hole, not a pattern to copy. The Laravel ingest
endpoint owns that row.

Idempotency comes from two places: `uq_lqe_extraction_hash` on
(extraction_id, verbatim_sha256, sub_institute_id) rejects a duplicate item
inside a re-run, and `replace=True` clears the previous rows for the
extraction first, so a re-parse after a parser fix does not leave orphans.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.mariadb import SessionLocal, init_mariadb

from app.services.question_ai_tagger import _LMS_BLOOM, _lms_difficulty

logger = logging.getLogger(__name__)

# question_type_master ids as they exist in this schema (verified):
#   1 multiple, 2 narrative, 8 assertion & reason
_QUESTION_TYPE_IDS = {
    "mcq": 1,
    "assertion_reason": 8,
    "very_short": 2,
    "short": 2,
    "long": 2,
    "case_study_parent": 2,
    "case_study_child": 2,
    "unknown": 2,
}

# Keeps extracted textbook items separable from the generated PAL-flow
# populations already in this table (adaptive_diagnostic, mastery_check, ...).
_CATEGORY = "textbook_exercise"

_ENVELOPE_VERSION = "qbank-1.0"

_INSERT_QUESTION = text("""
    INSERT INTO lms_question_master (
        question_type_id, standard_id, subject_id, chapter_id, topic_id,
        question_title, description, points, multiple_answer, concept, category,
        sub_institute_id, status, created_by, created_on, answer, hint_text,
        concept_id, g_bloom, g_dok, g_difficulty
    ) VALUES (
        :question_type_id, :standard_id, :subject_id, :chapter_id, NULL,
        :question_title, :description, :points, 0, NULL, :category,
        :sub_institute_id, :status, :created_by, CURRENT_TIMESTAMP, :answer, :hint_text,
        :concept_id, :g_bloom, :g_dok, :g_difficulty
    )
""")

_INSERT_OPTION = text("""
    INSERT INTO answer_master (
        question_id, answer, feedback, correct_answer, sub_institute_id, created_by, created_on
    ) VALUES (
        :question_id, :answer, NULL, :correct_answer, :sub_institute_id, :created_by,
        CURRENT_TIMESTAMP
    )
""")

_INSERT_EXTRACTION = text("""
    INSERT INTO lms_question_extraction (
        question_id, sub_institute_id, extraction_id, source_page,
        source_char_start, source_char_end, exam_section, section_heading,
        section_marks, item_number, item_ordinal, item_form,
        publisher_id, question_type_code,
        parent_question_id, choice_group_id, choice_role,
        reproduction, verbatim_sha256, verbatim_payload,
        attribution, licence, validation_status, validation_report,
        validator_version, figure_required, figure_resolved,
        concept_id, concept_confidence, bloom_level, dok_level,
        difficulty_1_to_5, ai_model, ai_tagged_at, ai_rationale
    ) VALUES (
        :question_id, :sub_institute_id, :extraction_id, :source_page,
        :source_char_start, :source_char_end, :exam_section, :section_heading,
        :section_marks, :item_number, :item_ordinal, :item_form,
        :publisher_id, :question_type_code,
        :parent_question_id, :choice_group_id, :choice_role,
        :reproduction, :verbatim_sha256, :verbatim_payload,
        :attribution, :licence, :validation_status, :validation_report,
        :validator_version, :figure_required, :figure_resolved,
        :concept_id, :concept_confidence, :bloom_level, :dok_level,
        :difficulty_1_to_5, :ai_model, :ai_tagged_at, :ai_rationale
    )
""")

_INSERT_ASSET = text("""
    INSERT INTO lms_question_asset (
        question_id, sub_institute_id, extraction_id, role, option_label,
        asset_sha256, source_path, stored_url, mime, width, height,
        byte_size, alt_text, ocr_text, source_page, ordinal
    ) VALUES (
        :question_id, :sub_institute_id, :extraction_id, :role, :option_label,
        :asset_sha256, :source_path, :stored_url, :mime, :width, :height,
        :byte_size, :alt_text, :ocr_text, :source_page, :ordinal
    )
""")


def _clip(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value[:limit] if len(value) > limit else value


def _describe(item: dict[str, Any]) -> str:
    """The one-line label the question bank shows beneath the stem."""
    bits = [item["item_form"].replace("_", " ").title()]
    if item.get("exam_section"):
        bits.append(f"Section {item['exam_section']}")
    if item.get("marks"):
        bits.append(f"{item['marks']} mark{'s' if item['marks'] != 1 else ''}")
    return _clip(" | ".join(bits), 250) or ""


def _envelope(item: dict[str, Any], validation: dict[str, Any] | None) -> str:
    """The JSON `answer` blob. Existing generated columns read from this."""
    payload = {
        "v": _ENVELOPE_VERSION,
        "content_hash": item["verbatim_sha256"],
        "exam_section": item.get("exam_section"),
        "marks": item.get("marks"),
        "item_form": item.get("item_form"),
        "item_number": item.get("item_number"),
        "correct_option": item.get("correct_option"),
        "model_answer": item.get("answer_text"),
        "assertion": item.get("assertion"),
        "reason": item.get("reason"),
        "sub_part_labels": item.get("sub_part_labels") or [],
        "choice_group_id": item.get("choice_group_id"),
        "choice_role": item.get("choice_role"),
        "figure_required": bool(item.get("figure_required")),
        "auto_gradable": item.get("item_form") in {"mcq", "assertion_reason"},
        "options": [
            {"label": o["label"], "text": o["text"], "is_correct": bool(o["is_correct"])}
            for o in item.get("options", [])
        ],
        "source": {
            "extraction_id": item.get("extraction_id"),
            "page": item.get("source_page"),
            "attribution": item.get("attribution"),
            "licence": item.get("licence"),
        },
        "validation": validation or {},
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def _asset_lookup(manifest: Any) -> dict[str, dict[str, Any]]:
    """Manifest keyed by file name, for joining markdown image refs."""
    index: dict[str, dict[str, Any]] = {}
    if isinstance(manifest, str):
        try:
            manifest = json.loads(manifest)
        except ValueError:
            return index
    if not isinstance(manifest, list):
        return index
    for entry in manifest:
        if isinstance(entry, dict) and entry.get("file_name"):
            index[str(entry["file_name"])] = entry
    return index


def write_question_bank(
    *,
    extraction_id: int,
    sub_institute_id: int,
    standard_id: int | None,
    subject_id: int | None,
    chapter_id: int | None,
    items: list[dict[str, Any]],
    asset_manifest: Any = None,
    created_by: int = 0,
    replace: bool = False,
    publish_clean: bool = True,
    validations: dict[int, dict[str, Any]] | None = None,
    publisher_id: int | None = None,
    type_catalog: dict[str, dict[str, Any]] | None = None,
    max_attempts: int = 4,
) -> dict[str, Any]:
    """Persist parsed items. Returns counters; raises only on total failure."""
    if not items:
        return {"inserted": 0, "options": 0, "assets": 0, "skipped_duplicate": 0, "held": 0}
    if not init_mariadb() or SessionLocal is None:
        raise RuntimeError("MariaDB unavailable - question bank was not written")

    assets_by_name = _asset_lookup(asset_manifest)
    validations = validations or {}

    delay = 3.0
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        db: Session = SessionLocal()
        try:
            counters = _write_once(
                db,
                extraction_id=extraction_id,
                sub_institute_id=sub_institute_id,
                standard_id=standard_id,
                subject_id=subject_id,
                chapter_id=chapter_id,
                items=items,
                assets_by_name=assets_by_name,
                created_by=created_by,
                replace=replace,
                publish_clean=publish_clean,
                validations=validations,
                publisher_id=publisher_id,
                type_catalog=type_catalog or {},
            )
            db.commit()
            logger.info(
                "Question bank written for extraction %s: %s",
                extraction_id,
                counters,
            )
            return counters
        except Exception as exc:
            db.rollback()
            last_error = exc
            # The remote MariaDB drops idle connections; the existing
            # generator retries for the same reason.
            logger.warning(
                "Question-bank write attempt %s/%s failed: %s", attempt, max_attempts, exc
            )
            if attempt < max_attempts:
                time.sleep(delay)
                delay *= 2
        finally:
            db.close()

    raise RuntimeError(
        f"Questions were parsed but could not be saved after {max_attempts} attempts: {last_error}"
    )


def _write_once(
    db: Session,
    *,
    extraction_id: int,
    sub_institute_id: int,
    standard_id: int | None,
    subject_id: int | None,
    chapter_id: int | None,
    items: list[dict[str, Any]],
    assets_by_name: dict[str, dict[str, Any]],
    created_by: int,
    replace: bool,
    publish_clean: bool,
    validations: dict[int, dict[str, Any]],
    publisher_id: int | None = None,
    type_catalog: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    counters = {"inserted": 0, "options": 0, "assets": 0, "skipped_duplicate": 0, "held": 0}
    carried_tags: dict[str, dict[str, Any]] = {}

    if replace:
        # Concept/Bloom/DOK tagging is a separate, paid step that runs after
        # Proceed. A re-run must not silently throw that work away, so carry
        # the tags across keyed by the verbatim hash -- an item whose text is
        # byte-identical is the same question and keeps its tags. Anything
        # whose text changed is genuinely new and comes back untagged.
        carried_tags = {
            row["verbatim_sha256"]: dict(row)
            for row in db.execute(
                text(
                    """
                    SELECT verbatim_sha256, concept_id, concept_confidence,
                           bloom_level, dok_level, difficulty_1_to_5,
                           ai_model, ai_tagged_at, ai_rationale
                      FROM lms_question_extraction
                     WHERE extraction_id = :e AND sub_institute_id = :t
                       AND ai_model IS NOT NULL
                    """
                ),
                {"e": extraction_id, "t": sub_institute_id},
            ).mappings()
        }
        if carried_tags:
            logger.info("Carrying %s AI tag sets across the re-run", len(carried_tags))

        # Remove the question rows this extraction previously produced, then
        # their sidecars. Ordered so nothing is orphaned midway.
        old = [
            row[0]
            for row in db.execute(
                text(
                    "SELECT question_id FROM lms_question_extraction "
                    "WHERE extraction_id = :e AND sub_institute_id = :t"
                ),
                {"e": extraction_id, "t": sub_institute_id},
            ).fetchall()
        ]
        if old:
            db.execute(
                text("DELETE FROM answer_master WHERE question_id IN :ids"),
                {"ids": tuple(old)},
            )
            db.execute(
                text("DELETE FROM lms_question_asset WHERE question_id IN :ids"),
                {"ids": tuple(old)},
            )
            db.execute(
                text("DELETE FROM lms_question_extraction WHERE question_id IN :ids"),
                {"ids": tuple(old)},
            )
            db.execute(
                text("DELETE FROM lms_question_master WHERE id IN :ids"),
                {"ids": tuple(old)},
            )
            logger.info("Replaced %s previously extracted questions", len(old))

    seen_hashes: set[str] = set()
    # Ordinal -> new question id, so a case sub-part can point at its parent.
    parent_ids: dict[int, int] = {}

    for item in items:
        digest = item["verbatim_sha256"]
        if digest in seen_hashes:
            counters["skipped_duplicate"] += 1
            continue
        seen_hashes.add(digest)

        item = {**item, "extraction_id": extraction_id}
        validation = validations.get(item["item_ordinal"])
        failed = bool(validation and validation.get("failed"))
        status = 1 if (publish_clean and not failed) else 0
        if status == 0:
            counters["held"] += 1

        catalog_entry = (type_catalog or {}).get(item["item_form"]) or {}
        lms_type = catalog_entry.get("lms_question_type_id") or _QUESTION_TYPE_IDS.get(
            item["item_form"], 2
        )
        result = db.execute(
            _INSERT_QUESTION,
            {
                "question_type_id": lms_type,
                "standard_id": standard_id,
                "subject_id": subject_id,
                "chapter_id": chapter_id,
                "question_title": item["stem"],
                "description": _describe(item),
                "points": item.get("marks") or 1,
                "category": _CATEGORY,
                "sub_institute_id": sub_institute_id,
                "status": status,
                "created_by": created_by,
                "answer": _envelope(item, validation),
                "hint_text": None,
                # Carried from a previous tagging pass when the text is
                # unchanged, so a re-Proceed does not wipe paid AI work.
                "concept_id": _carried(carried_tags, digest).get("concept_id"),
                "g_bloom": _LMS_BLOOM.get(
                    _carried(carried_tags, digest).get("bloom_level") or ""
                ),
                "g_dok": _carried(carried_tags, digest).get("dok_level"),
                "g_difficulty": _lms_difficulty(
                    _carried(carried_tags, digest).get("difficulty_1_to_5")
                ),
            },
        )
        question_id = result.lastrowid
        counters["inserted"] += 1

        if item["item_form"] == "case_study_parent":
            parent_ids[item["item_ordinal"]] = question_id

        for option in item.get("options", []):
            db.execute(
                _INSERT_OPTION,
                {
                    "question_id": question_id,
                    # answer_master.answer is varchar(250) and is NOT widened:
                    # it is live across many tenants. An option longer than
                    # that is a validator failure, not something to truncate
                    # silently — a truncated option breaks the licence's
                    # "reproduced accurately" condition.
                    "answer": _clip(option["text"], 250),
                    "correct_answer": 1 if option.get("is_correct") else 0,
                    "sub_institute_id": sub_institute_id,
                    "created_by": created_by,
                },
            )
            counters["options"] += 1

        figures = [assets_by_name.get(_file_name(ref)) for ref in item.get("images", [])]
        figures = [f for f in figures if f]
        for ordinal, asset in enumerate(figures):
            db.execute(
                _INSERT_ASSET,
                {
                    "question_id": question_id,
                    "sub_institute_id": sub_institute_id,
                    "extraction_id": extraction_id,
                    "role": "stem",
                    "option_label": None,
                    "asset_sha256": asset.get("sha256") or "",
                    "source_path": _clip(asset.get("relative_path"), 512),
                    "stored_url": _clip(asset.get("url"), 512),
                    "mime": f"image/{asset.get('extension') or 'jpeg'}",
                    "width": asset.get("width"),
                    "height": asset.get("height"),
                    "byte_size": asset.get("size_bytes"),
                    "alt_text": _clip(asset.get("caption"), 512),
                    "ocr_text": asset.get("ocr_text"),
                    "source_page": asset.get("page_number") or item.get("source_page"),
                    "ordinal": ordinal,
                },
            )
            counters["assets"] += 1

        db.execute(
            _INSERT_EXTRACTION,
            {
                "question_id": question_id,
                "sub_institute_id": sub_institute_id,
                "extraction_id": extraction_id,
                "source_page": item.get("source_page"),
                "source_char_start": item.get("source_char_start"),
                "source_char_end": item.get("source_char_end"),
                "exam_section": item.get("exam_section"),
                "section_heading": _clip(item.get("section_heading"), 191),
                "section_marks": item.get("section_marks"),
                "item_number": _clip(item.get("item_number"), 16),
                "item_ordinal": item.get("item_ordinal"),
                "item_form": _clip(item.get("item_form"), 24),
                "publisher_id": publisher_id,
                "question_type_code": _clip(item.get("item_form"), 48),
                "parent_question_id": None,
                "choice_group_id": item.get("choice_group_id"),
                "choice_role": item.get("choice_role"),
                "reproduction": item.get("reproduction") or "verbatim",
                "verbatim_sha256": digest,
                "verbatim_payload": item.get("verbatim_payload"),
                "attribution": _clip(item.get("attribution"), 255),
                "licence": _clip(item.get("licence"), 64),
                "validation_status": "failed" if failed else ("passed" if validation else "pending"),
                "validation_report": json.dumps(validation, default=str) if validation else None,
                "validator_version": validation.get("version") if validation else None,
                "figure_required": 1 if item.get("figure_required") else 0,
                "figure_resolved": 1 if figures else 0,
                **_carried(carried_tags, digest),
            },
        )

    return counters


_TAG_FIELDS = (
    "concept_id",
    "concept_confidence",
    "bloom_level",
    "dok_level",
    "difficulty_1_to_5",
    "ai_model",
    "ai_tagged_at",
    "ai_rationale",
)


def _carried(tags: dict[str, dict[str, Any]], digest: str) -> dict[str, Any]:
    """AI tags preserved from a previous run of this same item, else nulls."""
    previous = tags.get(digest) or {}
    return {field: previous.get(field) for field in _TAG_FIELDS}


def _file_name(markdown_image_ref: str) -> str:
    """Pull the file name out of a markdown image reference or URL."""
    ref = markdown_image_ref
    if "](" in ref:
        ref = ref.split("](", 1)[1].rstrip(")")
    ref = ref.split("?", 1)[0].rstrip(")")
    return ref.replace("\\", "/").rsplit("/", 1)[-1]
