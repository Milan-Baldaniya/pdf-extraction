"""Educational structure enrichment for MinerU CPU pipeline output."""

from __future__ import annotations

import re
from typing import Any


CALLOUT_PATTERNS: list[tuple[str, str]] = [
    (r"^activity\s+\d", "activity"),
    (r"^example\s+\d", "example"),
    (r"^answer\b", "answer"),
    (r"^exercise\b|^exercise set\b", "exercise"),
    (r"^think and reflect\b", "think_reflect"),
    (r"^pause and ponder\b", "pause_ponder"),
    (r"^ready to go beyond\b", "extension_box"),
    (r"^threads of curiosity\b", "curiosity_box"),
    (r"^meet a scientist\b", "biography_box"),
    (r"^let us\b", "activity_prompt"),
]


def enhance_educational_structure(
    markdown: str,
    json_content: dict[str, Any] | list[Any] | None,
) -> tuple[dict[str, Any] | list[Any] | None, dict[str, Any]]:
    """Add deterministic educational roles, outline, assets, and diagnostics."""
    if not isinstance(json_content, dict):
        return json_content, _fallback_metadata(markdown)

    pages = json_content.get("pages")
    blocks = json_content.get("blocks")
    if not isinstance(pages, list) or not isinstance(blocks, list):
        return json_content, _fallback_metadata(markdown)

    enhanced_pages: list[dict[str, Any]] = []
    enhanced_blocks: list[dict[str, Any]] = []

    for page in pages:
        if not isinstance(page, dict):
            continue
        page_blocks: list[dict[str, Any]] = []
        for raw_block in page.get("blocks", []):
            if not isinstance(raw_block, dict):
                continue
            block = dict(raw_block)
            educational_role = infer_educational_role(block)
            block["educational_role"] = educational_role
            block["hierarchy_level"] = infer_hierarchy_level(block, educational_role)
            block["semantic_label"] = build_semantic_label(block, educational_role)
            page_blocks.append(block)
            enhanced_blocks.append(block)

        enhanced_pages.append({**page, "blocks": page_blocks})

    outline = build_outline(enhanced_blocks)
    sections = build_sections(enhanced_blocks, outline)
    assets = build_asset_index(enhanced_blocks, markdown)
    metadata = build_metadata(markdown, enhanced_blocks, outline, sections, assets)

    enhanced_json = {
        **json_content,
        "version": "cpu_educational_layout_v1",
        "processing_profile": "mineru_cpu_pipeline_educational",
        "pages": enhanced_pages,
        "blocks": enhanced_blocks,
        "educational_outline": outline,
        "educational_sections": sections,
        "educational_assets": assets,
    }
    return enhanced_json, metadata


def infer_educational_role(block: dict[str, Any]) -> str:
    text = clean_text(str(block.get("text") or ""))
    source_type = str(block.get("source_type") or block.get("type") or "")
    role = str(block.get("role") or "")

    if block.get("table_html") or source_type == "table" or role == "table":
        return "table"
    if block.get("img_path") or source_type == "image" or role == "figure":
        return "figure"
    if role == "formula" or source_type in {"interline_equation", "formula"}:
        return "formula"
    if re.match(r"^fig\.?\s*\d", text, re.I):
        return "figure_caption"
    if re.match(r"^table\s+\d", text, re.I):
        return "table_caption"
    if role == "heading" or source_type in {"title", "paragraph_title"}:
        if re.match(r"^chapter\b", text, re.I):
            return "chapter_title"
        if re.match(r"^\d+(\.\d+)*\s+\S", text):
            return "section_heading"
        return "heading"

    for pattern, label in CALLOUT_PATTERNS:
        if re.match(pattern, text, re.I):
            return label

    if any(item.get("type") == "formula" for item in block.get("inline_items", [])):
        return "formula_context"
    return "body"


def infer_hierarchy_level(block: dict[str, Any], educational_role: str) -> int | None:
    text_level = block.get("text_level")
    if isinstance(text_level, int):
        return text_level

    if educational_role == "chapter_title":
        return 1
    if educational_role == "section_heading":
        text = clean_text(str(block.get("text") or ""))
        section = re.match(r"^(\d+(?:\.\d+)*)", text)
        if section:
            return min(1 + section.group(1).count(".") + 1, 6)
        return 2
    if educational_role in {"heading", "activity", "example", "exercise"}:
        return 3
    return None


def build_semantic_label(block: dict[str, Any], educational_role: str) -> str:
    text = clean_text(str(block.get("text") or block.get("caption") or ""))
    if educational_role == "figure":
        caption = clean_text(str(block.get("caption") or block.get("footnote") or ""))
        return caption or "Diagram or figure"
    if educational_role == "table":
        return text or "Table"
    if educational_role == "formula":
        return text or "Formula"
    return text[:160]


def build_outline(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    outline_roles = {
        "chapter_title",
        "section_heading",
        "heading",
        "activity",
        "example",
        "exercise",
        "think_reflect",
        "pause_ponder",
        "extension_box",
        "curiosity_box",
        "biography_box",
    }
    outline: list[dict[str, Any]] = []
    for block in blocks:
        role = str(block.get("educational_role") or "")
        text = clean_text(str(block.get("text") or block.get("semantic_label") or ""))
        if role not in outline_roles or not text:
            continue
        outline.append(
            {
                "id": block.get("id"),
                "role": role,
                "title": text[:220],
                "page_idx": block.get("page_idx"),
                "level": block.get("hierarchy_level") or 4,
                "reading_order": block.get("reading_order"),
            }
        )
    return outline


def build_asset_index(
    blocks: list[dict[str, Any]],
    markdown: str,
) -> dict[str, list[dict[str, Any]]]:
    figures: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    formulas: list[dict[str, Any]] = []

    for index, block in enumerate(blocks):
        role = str(block.get("educational_role") or "")
        text = clean_text(str(block.get("text") or ""))
        if role == "figure":
            caption = clean_text(str(block.get("caption") or block.get("footnote") or ""))
            figures.append(
                {
                    "id": block.get("id"),
                    "page_idx": block.get("page_idx"),
                    "bbox": block.get("bbox"),
                    "reading_order": block.get("reading_order"),
                    "img_path": block.get("img_path"),
                    "caption": caption,
                    "nearby_text": nearby_text(blocks, index),
                    "references": find_caption_references(caption, markdown),
                }
            )
        elif role == "table":
            tables.append(
                {
                    "id": block.get("id"),
                    "page_idx": block.get("page_idx"),
                    "bbox": block.get("bbox"),
                    "reading_order": block.get("reading_order"),
                    "caption": text or clean_text(str(block.get("caption") or "")),
                    "has_html": bool(block.get("table_html")),
                    "html": block.get("table_html") or "",
                    "nearby_text": nearby_text(blocks, index),
                }
            )
        elif role in {"formula", "formula_context"}:
            formulas.append(
                {
                    "id": block.get("id"),
                    "page_idx": block.get("page_idx"),
                    "bbox": block.get("bbox"),
                    "reading_order": block.get("reading_order"),
                    "text": text,
                    "inline_count": sum(
                        1
                        for item in block.get("inline_items", [])
                        if item.get("type") == "formula"
                    ),
                }
            )

    return {"figures": figures, "tables": tables, "formulas": formulas}


def build_sections(
    blocks: list[dict[str, Any]],
    outline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    outline_ids = {item.get("id"): item for item in outline}
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for block in blocks:
        block_id = block.get("id")
        outline_item = outline_ids.get(block_id)
        if outline_item:
            if current:
                sections.append(current)
            current = {
                "id": block_id,
                "title": outline_item.get("title"),
                "role": outline_item.get("role"),
                "level": outline_item.get("level"),
                "page_idx": outline_item.get("page_idx"),
                "block_ids": [block_id],
                "figures": [],
                "tables": [],
                "formulas": [],
            }
            continue

        if current is None:
            continue
        current["block_ids"].append(block_id)
        role = str(block.get("educational_role") or "")
        if role == "figure":
            current["figures"].append(block_id)
        elif role == "table":
            current["tables"].append(block_id)
        elif role in {"formula", "formula_context"}:
            current["formulas"].append(block_id)

    if current:
        sections.append(current)
    return sections


def build_metadata(
    markdown: str,
    blocks: list[dict[str, Any]],
    outline: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    assets: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    role_counts: dict[str, int] = {}
    for block in blocks:
        role = str(block.get("educational_role") or "unknown")
        role_counts[role] = role_counts.get(role, 0) + 1

    return {
        "educational_outline_items": len(outline),
        "educational_sections": len(sections),
        "educational_role_counts": role_counts,
        "figures_indexed": len(assets["figures"]),
        "tables_indexed": len(assets["tables"]),
        "formulas_indexed": len(assets["formulas"]),
        "cpu_semantic_enrichment": True,
        "educational_structure_score": score_structure(markdown, blocks, outline, assets),
    }


def _fallback_metadata(markdown: str) -> dict[str, Any]:
    return {
        "educational_outline_items": len(re.findall(r"^#{1,6}\s+\S", markdown, re.M)),
        "cpu_semantic_enrichment": False,
        "educational_structure_score": 0,
    }


def score_structure(
    markdown: str,
    blocks: list[dict[str, Any]],
    outline: list[dict[str, Any]],
    assets: dict[str, list[dict[str, Any]]],
) -> int:
    score = 0
    if blocks:
        score += 25
    if outline:
        score += 20
    if assets["figures"]:
        score += 15
    if assets["tables"]:
        score += 15
    if assets["formulas"] or "$" in markdown:
        score += 15
    if re.search(r"[\u0900-\u097F]", markdown) and re.search(r"[A-Za-z]", markdown):
        score += 10
    return min(score, 100)


def find_caption_references(caption: str, markdown: str) -> list[str]:
    label_match = re.search(r"(fig\.?\s*\d+(?:\.\d+)*)", caption, re.I)
    if not label_match:
        return []
    label = re.escape(label_match.group(1))
    references = re.findall(rf".{{0,60}}{label}.{{0,80}}", markdown, flags=re.I)
    return [clean_text(item) for item in references[:5]]


def nearby_text(blocks: list[dict[str, Any]], index: int) -> str:
    snippets: list[str] = []
    for neighbor in (index - 1, index + 1):
        if 0 <= neighbor < len(blocks):
            text = clean_text(str(blocks[neighbor].get("text") or ""))
            if text and len(text) > 12:
                snippets.append(text[:240])
    return " ".join(snippets)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
