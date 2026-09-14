"""Separate a question from the answer that was printed alongside it.

Most of this corpus is easy: the book writes "Solution:" or "Answer:" and
``question_extractor`` cuts there. This module is the repair pass for what is
left -- items where the answer is present but unmarked, which in practice
means one of:

  * a worked table filled in for the student ("Polynomial | Type | Degree"
    with every row completed),
  * an answer run appended with no lead-in at all.

Three tiers, cheapest first:

  marker    the deterministic cut in question_extractor. Not repeated here.
  offline   structural heuristics. No model, no network, no cost.
  deepseek  the real splitter, for anything the heuristics will not touch.

The offline tier exists for the same reason it does in the tagger: the
DeepSeek account can be out of credit, and a question bank that silently
keeps answers inside its questions is worse than one that took a cheap guess
and said so. Every split records which tier produced it.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.semantic_intelligence.deepseek_client import (
    DeepSeekUnavailableError,
    async_call_deepseek,
)

logger = logging.getLogger(__name__)

OFFLINE_MODEL = "offline-structural-v1"

# A table is the answer when its rows are filled in. MinerU emits these as raw
# HTML inside the markdown, so they survive as one opaque block.
_TABLE_RE = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
_ROW_RE = re.compile(r"<tr\b.*?</tr>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")

# "(i) ... (ii) ..." runs. A question that asks for n parts and is followed by
# n answered parts has its answer appended.
_PART_RE = re.compile(r"\((i{1,3}|iv|v|vi{0,3}|[a-d])\)", re.IGNORECASE)


class QaSplit(BaseModel):
    """One item split into the halves that go to different columns."""

    ref: str
    question: str = Field(min_length=1)
    answer: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class QaSplitBatch(BaseModel):
    items: list[QaSplit]


_SYSTEM = (
    "You split exam items into the question a student is asked and the answer "
    "printed for the teacher. Rules:\n"
    "1. Reproduce both halves VERBATIM. Never paraphrase, correct or complete "
    "anything -- this is published material and accuracy is a licence term.\n"
    "2. The question keeps its stem, every sub-part prompt, and any data table "
    "the student needs to READ.\n"
    "3. The answer takes worked steps, results, and any table that has been "
    "FILLED IN for the student.\n"
    "4. If the item contains no answer at all, return the whole text as the "
    "question and null for the answer. Do not invent one.\n"
    "5. Echo each ref exactly.\n"
    'Return JSON: {"items":[{"ref","question","answer","confidence"}]}'
)


def _strip(html: str) -> str:
    return _TAG_RE.sub(" ", html).replace("&nbsp;", " ").strip()


def _table_is_answered(table_html: str) -> bool:
    """True when a table's body rows are filled rather than blank.

    A question may legitimately print an empty grid for the student to
    complete; that grid belongs to the question. A grid that already has its
    cells populated is the answer key.
    """
    rows = _ROW_RE.findall(table_html)
    if len(rows) < 2:
        return False

    body = rows[1:]
    filled = 0
    for row in body:
        cells = [_strip(cell) for cell in _CELL_RE.findall(row)]
        if not cells:
            continue
        # A row counts as filled when every cell past the first has content:
        # the first column is usually the item being classified.
        if len(cells) > 1 and all(cell for cell in cells[1:]):
            filled += 1

    return filled >= max(1, len(body) // 2)


def offline_split(text: str) -> tuple[str, str | None, float]:
    """Structural split. Returns (question, answer, confidence)."""
    if not text:
        return text, None, 0.0

    # A filled-in table at the end is the answer key.
    tables = list(_TABLE_RE.finditer(text))
    if tables:
        last = tables[-1]
        trailing = text[last.end():].strip()
        # Only when the table actually ends the item; a table followed by more
        # prompt text is data the student reads.
        if len(trailing) <= 40 and _table_is_answered(last.group(0)):
            question = text[: last.start()].strip()
            answer = text[last.start():].strip()
            if question:
                # Capped well below 1.0: this is a structural guess, and the
                # review queue should still be able to sort by confidence.
                return question, answer, 0.55

    return text, None, 0.0


async def deepseek_split(items: list[dict[str, Any]]) -> list[QaSplit]:
    """Split a batch with the model. Raises DeepSeekUnavailableError."""
    payload = "\n\n".join(
        f"[ref {item['ref']}] {item['text']}" for item in items
    )
    prompt = f"ITEMS ({len(items)}):\n{payload}\n\nSplit each. Echo every ref."

    raw = await async_call_deepseek(
        prompt, system_prompt=_SYSTEM, response_format={"type": "json_object"}
    )
    body = raw.get("data") if isinstance(raw, dict) and "data" in raw else raw
    try:
        return QaSplitBatch.model_validate(body).items
    except ValidationError as exc:
        retry = await async_call_deepseek(
            prompt + f"\n\nYour previous reply was rejected: {exc}. Return valid JSON.",
            system_prompt=_SYSTEM,
            response_format={"type": "json_object"},
        )
        body = retry.get("data") if isinstance(retry, dict) and "data" in retry else retry
        return QaSplitBatch.model_validate(body).items


def _needs_split(item: dict[str, Any]) -> bool:
    """Only items the marker pass could not resolve.

    An item with options or a captured solution is already split. Anything
    else that still looks like it carries its own answer is a candidate.
    """
    if item.get("answer_text") or item.get("options"):
        return False
    stem = item.get("stem") or ""
    if not stem:
        return False
    return bool(_TABLE_RE.search(stem)) or len(_PART_RE.findall(stem)) >= 4


async def repair_items(
    items: list[dict[str, Any]], *, provider: str = "auto"
) -> dict[str, Any]:
    """Fill in answer_text for items the deterministic pass left unsplit.

    Mutates `items` in place and returns a report. `provider` follows the same
    contract as the tagger: "auto" tries DeepSeek then falls back, "deepseek"
    fails loudly, "offline" never calls the model.
    """
    candidates = [item for item in items if _needs_split(item)]
    report: dict[str, Any] = {
        "candidates": len(candidates),
        "split": 0,
        "provider": "none",
        "notes": [],
    }
    if not candidates:
        return report

    if provider in {"auto", "deepseek"}:
        try:
            splits = await deepseek_split(
                [
                    {"ref": str(item["item_ordinal"]), "text": item["stem"]}
                    for item in candidates
                ]
            )
            by_ref = {split.ref: split for split in splits}
            for item in candidates:
                split = by_ref.get(str(item["item_ordinal"]))
                if not split or not split.answer:
                    continue
                item["stem"] = split.question.strip()
                item["answer_text"] = split.answer.strip()
                item["answer_source"] = "deepseek"
                item["answer_confidence"] = split.confidence
                report["split"] += 1
            report["provider"] = "deepseek"
            return report
        except DeepSeekUnavailableError as exc:
            if provider == "deepseek":
                raise
            logger.warning("DeepSeek unavailable, splitting offline: %s", exc)
            report["notes"].append(f"DeepSeek unavailable ({exc}); used the structural splitter.")
        except (ValidationError, ValueError) as exc:
            if provider == "deepseek":
                raise
            logger.warning("DeepSeek split rejected, falling back: %s", exc)
            report["notes"].append(f"DeepSeek returned unusable output ({exc}); used the structural splitter.")

    for item in candidates:
        question, answer, confidence = offline_split(item["stem"])
        if not answer:
            continue
        item["stem"] = question
        item["answer_text"] = answer
        item["answer_source"] = OFFLINE_MODEL
        item["answer_confidence"] = confidence
        report["split"] += 1
    report["provider"] = OFFLINE_MODEL
    return report
