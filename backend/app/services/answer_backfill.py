"""Write model answers onto questions that were stored without one.

The bank holds thousands of generated narrative questions whose `answer`
column is an empty string: the generator wrote the question and never the
answer, so the question is visible to a teacher and useless to a student.

Two things make this non-trivial and are the reason this is a service rather
than an UPDATE:

1. `lms_question_master.answer` is not a text column in practice -- it is a
   JSON envelope that other code reads (`model_answer`, `options`,
   `correct_option`, the generated `g_*` columns are projected out of it).
   Backfilling by overwriting the column would destroy whatever a row already
   holds, so the envelope is merged, never replaced.

2. These answers are AUTHORED, not reproduced from a book. Everything written
   here is stamped so that no one can later mistake it for a publisher's own
   marking scheme -- `answer_origin: "authored"` plus who/when. The bank
   already distinguishes extracted from generated content and this keeps that
   distinction honest for the answer as well as the question.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import text

from app.db.mariadb import SessionLocal, init_mariadb

logger = logging.getLogger(__name__)

ENVELOPE_VERSION = "ans-backfill-1.0"

# `lms_question_master.status`: 1 is published and servable, 0 is held for
# review. The Laravel bank filters on exactly these two (`ApiLmsCourseController`
# `status === 'held'` -> `status = 0`).
STATUS_HELD = 0

# A question that says "in the given figure..." cannot be answered without the
# figure. These chapters have zero rows in `lms_question_asset`, so the figure
# was never stored and no honest answer exists -- the only truthful outcomes are
# to hold the item or to guess, and guessing is how a bank starts lying.
_FIGURE_REFERENCE_RE = re.compile(
    r"(given (?:figure|diagram|circuit|graph|table)"
    r"|following (?:figure|diagram|circuit|graph)"
    r"|(?:figure|diagram|circuit|graph) (?:below|above|given|shown)"
    r"|shown in (?:the )?(?:fig|figure|diagram)"
    r"|above (?:figure|diagram)"
    r"|the (?:adjoining|adjacent) (?:figure|diagram)"
    r"|\bthe diagram\b)",
    re.I,
)

HOLD_REASON = (
    "Held for a teacher: this question refers to a figure, diagram or circuit "
    "that was not stored with it, so it cannot be answered from the text alone. "
    "Supply the figure and the answer can be written."
)


def _session():
    if not init_mariadb() or SessionLocal is None:
        raise RuntimeError("Database not ready")
    return SessionLocal()


def _merge(
    existing: str | None,
    answer: str,
    *,
    marks: int | None,
    author: str,
    origin: str = "authored",
) -> str:
    """Merge a model answer into whatever envelope the row already has.

    `origin` must stay truthful: "authored" is a real model answer written for
    the bank, "held_no_figure" is a note explaining why no answer exists. They
    look the same in the column and must not look the same to a reader.
    """
    envelope: dict[str, Any] = {}
    if existing:
        stripped = existing.strip()
        if stripped.startswith("{"):
            try:
                loaded = json.loads(stripped)
                if isinstance(loaded, dict):
                    envelope = loaded
            except ValueError:
                # Not JSON after all. Keep the old text rather than dropping
                # it: it may be the only answer content the row ever had.
                envelope = {"legacy_answer": stripped[:4000]}
        elif stripped:
            envelope = {"legacy_answer": stripped[:4000]}

    envelope["model_answer"] = answer
    envelope.setdefault("v", ENVELOPE_VERSION)
    if marks is not None:
        envelope.setdefault("marks", marks)
    # Provenance: this answer was written for the bank, not copied from a book.
    envelope["answer_origin"] = origin
    envelope["answer_author"] = author
    return json.dumps(envelope, ensure_ascii=False)


def missing_answers(chapter_id: int) -> list[dict[str, Any]]:
    """Narrative questions on a chapter that still have no model answer."""
    db = _session()
    try:
        rows = db.execute(
            text(
                """
                SELECT q.id, q.points AS marks, q.question_title, q.answer
                  FROM lms_question_master q
                  JOIN question_type_master qt ON qt.id = q.question_type_id
                 WHERE q.chapter_id = :c
                   AND q.deleted_at IS NULL
                   AND qt.question_type <> 'multiple'
                   AND (
                        JSON_EXTRACT(q.answer, '$.model_answer') IS NULL
                     OR JSON_UNQUOTE(JSON_EXTRACT(q.answer, '$.model_answer')) = ''
                   )
                 ORDER BY q.id
                """
            ),
            {"c": chapter_id},
        ).mappings().fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def hold_figure_dependent(
    chapter_id: int,
    *,
    author: str = "claude-opus-5",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Hold answerless questions whose figure the bank never stored.

    Only fires where the chapter genuinely has no assets. If a figure IS on
    file the question is answerable and is left alone for the normal
    authoring pass, because holding it would hide usable content.
    """
    db = _session()
    try:
        assets = db.execute(
            text(
                "SELECT COUNT(*) FROM lms_question_asset a "
                "JOIN lms_question_master q ON q.id = a.question_id "
                "WHERE q.chapter_id = :c"
            ),
            {"c": chapter_id},
        ).scalar()
    finally:
        db.close()

    if assets:
        return {"held": 0, "skipped_chapter_has_assets": int(assets)}

    candidates = [
        row for row in missing_answers(chapter_id)
        if _FIGURE_REFERENCE_RE.search(str(row.get("question_title") or ""))
    ]
    if not candidates or dry_run:
        return {"held": len(candidates)}

    db = _session()
    try:
        for row in candidates:
            db.execute(
                text(
                    "UPDATE lms_question_master "
                    "   SET answer = :a, status = :s WHERE id = :i"
                ),
                {
                    "a": _merge(
                        row.get("answer"),
                        HOLD_REASON,
                        marks=row.get("marks"),
                        author=author,
                        origin="held_no_figure",
                    ),
                    "s": STATUS_HELD,
                    "i": int(row["id"]),
                },
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return {"held": len(candidates)}


def backfill(
    answers: dict[int, str],
    *,
    author: str = "claude-opus-5",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Write `{question_id: model_answer}` onto existing rows.

    Only fills a blank. A row that already has a `model_answer` is left alone
    and counted as skipped, so a re-run is safe and a human correction is
    never overwritten.
    """
    report = {"requested": len(answers), "written": 0, "skipped": 0, "missing": 0}
    if not answers:
        return report

    db = _session()
    try:
        rows = db.execute(
            text(
                "SELECT id, points, answer FROM lms_question_master "
                "WHERE id IN :ids AND deleted_at IS NULL"
            ),
            {"ids": tuple(answers)},
        ).mappings().fetchall()
        found = {int(r["id"]): dict(r) for r in rows}

        for qid, answer in answers.items():
            row = found.get(int(qid))
            if row is None:
                report["missing"] += 1
                continue

            current = row.get("answer") or ""
            if current.strip().startswith("{"):
                try:
                    if (json.loads(current) or {}).get("model_answer"):
                        report["skipped"] += 1
                        continue
                except ValueError:
                    pass

            text_ = (answer or "").strip()
            if not text_:
                report["skipped"] += 1
                continue

            if dry_run:
                report["written"] += 1
                continue

            db.execute(
                text("UPDATE lms_question_master SET answer = :a WHERE id = :i"),
                {
                    "a": _merge(current, text_, marks=row.get("points"), author=author),
                    "i": int(qid),
                },
            )
            report["written"] += 1

        if not dry_run:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return report
