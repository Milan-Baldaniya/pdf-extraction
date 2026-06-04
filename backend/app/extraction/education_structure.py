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
    structured_markdown = rebuild_structured_markdown(enhanced_pages, enhanced_blocks)
    metadata = build_metadata(
        structured_markdown or markdown,
        enhanced_blocks,
        outline,
        sections,
        assets,
    )
    if structured_markdown.strip():
        metadata["structured_markdown_chars"] = len(structured_markdown)
        metadata["markdown_rebuilt_from_layout"] = True

    enhanced_json = {
        **json_content,
        "version": "cpu_educational_layout_v1",
        "processing_profile": "mineru_cpu_pipeline_educational",
        "pages": enhanced_pages,
        "blocks": enhanced_blocks,
        "educational_outline": outline,
        "educational_sections": sections,
        "educational_assets": assets,
        "structured_markdown": structured_markdown,
    }
    return enhanced_json, metadata


_SKIP_LAYOUT_ROLES = frozenset({"header", "footer", "page_number"})
_CALLOUT_ROLES = frozenset(
    {
        "activity",
        "example",
        "answer",
        "exercise",
        "think_reflect",
        "pause_ponder",
        "extension_box",
        "curiosity_box",
        "biography_box",
        "activity_prompt",
    }
)


def rebuild_structured_markdown(
    pages: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
) -> str:
    """Rebuild reading-order markdown from enriched layout blocks."""
    if not blocks:
        return ""

    page_block_map: dict[int, list[dict[str, Any]]] = {}
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_idx = page.get("page_idx")
        if not isinstance(page_idx, int):
            continue
        page_blocks = page.get("blocks")
        if isinstance(page_blocks, list) and page_blocks:
            page_block_map[page_idx] = [dict(block) for block in page_blocks if isinstance(block, dict)]

    if not page_block_map:
        page_block_map = _group_blocks_by_page(blocks)

    parts: list[str] = []
    for page_idx in sorted(page_block_map):
        page_blocks = _merge_fragmented_body_blocks(page_block_map[page_idx])
        if not page_blocks:
            continue

        if len(page_block_map) > 1:
            parts.append(f"## Page {page_idx + 1}")
            parts.append("")

        for block in page_blocks:
            rendered = _render_layout_block_markdown(block)
            if rendered:
                parts.append(rendered)
                parts.append("")

    return _normalize_markdown_document("\n\n".join(parts))


def _group_blocks_by_page(blocks: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    page_map: dict[int, list[dict[str, Any]]] = {}
    for block in blocks:
        page_idx = block.get("page_idx")
        if not isinstance(page_idx, int):
            page_idx = 0
        page_map.setdefault(page_idx, []).append(dict(block))
    for page_blocks in page_map.values():
        page_blocks.sort(
            key=lambda block: (
                block.get("reading_order", 0),
                (block.get("bbox") or [0, 0, 0, 0])[1],
                (block.get("bbox") or [0, 0, 0, 0])[0],
            )
        )
    return page_map


def _merge_fragmented_body_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not blocks:
        return []

    merged: list[dict[str, Any]] = []
    for block in blocks:
        role = str(block.get("educational_role") or block.get("role") or "")
        if role in _SKIP_LAYOUT_ROLES:
            continue

        if merged and _should_merge_body_blocks(merged[-1], block):
            previous = merged[-1]
            previous_text = clean_text(str(previous.get("text") or ""))
            current_text = clean_text(str(block.get("text") or ""))
            if current_text:
                joiner = "" if previous_text.endswith("-") else " "
                previous["text"] = f"{previous_text}{joiner}{current_text}".strip()
            previous_items = previous.get("inline_items")
            current_items = block.get("inline_items")
            if isinstance(current_items, list):
                if isinstance(previous_items, list):
                    previous_items.extend(current_items)
                else:
                    previous["inline_items"] = list(current_items)
            bbox = block.get("bbox")
            if isinstance(bbox, list) and len(bbox) == 4:
                previous["bbox"] = [
                    min(previous.get("bbox", bbox)[0], bbox[0]),
                    min(previous.get("bbox", bbox)[1], bbox[1]),
                    max(previous.get("bbox", bbox)[2], bbox[2]),
                    max(previous.get("bbox", bbox)[3], bbox[3]),
                ]
            continue

        merged.append(dict(block))
    return merged


def _should_merge_body_blocks(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    if previous.get("page_idx") != current.get("page_idx"):
        return False

    previous_role = str(previous.get("educational_role") or previous.get("role") or "")
    current_role = str(current.get("educational_role") or current.get("role") or "")
    if previous_role not in {"body", "formula_context"} or current_role not in {
        "body",
        "formula_context",
    }:
        return False

    if previous.get("table_html") or current.get("table_html"):
        return False
    if previous.get("img_path") or current.get("img_path"):
        return False

    previous_bbox = previous.get("bbox")
    current_bbox = current.get("bbox")
    if not (
        isinstance(previous_bbox, list)
        and isinstance(current_bbox, list)
        and len(previous_bbox) == 4
        and len(current_bbox) == 4
    ):
        return len(clean_text(str(previous.get("text") or ""))) < 120

    vertical_gap = current_bbox[1] - previous_bbox[3]
    line_height = max(10, previous_bbox[3] - previous_bbox[1])
    return vertical_gap <= line_height * 1.25


def _render_layout_block_markdown(block: dict[str, Any]) -> str:
    role = str(block.get("educational_role") or block.get("role") or "body")
    text = clean_text(str(block.get("text") or ""))

    if role in _SKIP_LAYOUT_ROLES:
        return ""

    if role == "table":
        return _render_table_block(block, text)
    if role in {"figure", "figure_caption"}:
        return _render_figure_block(block, text)
    if role in {"formula", "formula_context"}:
        return _render_formula_block(block, text)
    if role in _CALLOUT_ROLES:
        return _render_callout_block(role, text)
    if role in {"chapter_title", "section_heading", "heading"} or block.get("text_level"):
        heading = _heading_prefix(block)
        if heading and text:
            return f"{heading}{text}"
        if text:
            return text
        return ""

    inline = _render_inline_items(block.get("inline_items"))
    if inline:
        return inline
    return text


def _heading_prefix(block: dict[str, Any]) -> str:
    role = str(block.get("educational_role") or "")
    hierarchy = block.get("hierarchy_level")
    text_level = block.get("text_level")

    if role == "chapter_title":
        level = 1
    elif role == "section_heading":
        level = 2
    elif role == "heading":
        level = 3
    elif isinstance(hierarchy, int) and hierarchy > 0:
        level = max(1, min(hierarchy, 6))
    elif isinstance(text_level, int) and text_level > 0:
        level = max(1, min(text_level, 6))
    else:
        return ""

    return f"{'#' * level} "


def _render_table_block(block: dict[str, Any], text: str) -> str:
    table_html = str(block.get("table_html") or "").strip()
    caption = clean_text(str(block.get("caption") or text or ""))
    parts: list[str] = []
    if caption:
        parts.append(f"**{caption}**")
    if table_html:
        parts.append(table_html)
    elif text:
        parts.append(text)
    return "\n\n".join(parts)


def _render_figure_block(block: dict[str, Any], text: str) -> str:
    img_path = str(block.get("img_path") or "").strip()
    caption = clean_text(str(block.get("caption") or block.get("footnote") or text or ""))
    alt = caption or "Figure"
    parts: list[str] = []
    if img_path:
        parts.append(f"![{alt}]({img_path})")
    if caption and caption != alt:
        parts.append(f"*{caption}*")
    elif text and not img_path:
        parts.append(f"*{text}*")
    return "\n\n".join(parts)


def _render_formula_block(block: dict[str, Any], text: str) -> str:
    inline = _render_inline_items(block.get("inline_items"))
    if inline:
        return inline
    if text:
        stripped = text.strip()
        if stripped.startswith("$") and stripped.endswith("$"):
            return stripped
        return f"$${stripped}$$"
    return ""


def _render_callout_block(role: str, text: str) -> str:
    if not text:
        return ""
    label = role.replace("_", " ").title()
    return f"> **{label}**\n>\n> {text}"


def _render_inline_items(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        content = clean_text(str(item.get("content") or ""))
        if not content:
            continue
        if item.get("type") == "formula":
            if not (content.startswith("$") and content.endswith("$")):
                content = f"${content}$"
        parts.append(content)
    return clean_text(" ".join(parts))


def _normalize_markdown_document(markdown: str) -> str:
    lines = [line.rstrip() for line in markdown.splitlines()]
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{4,}", "\n\n\n", cleaned)
    return cleaned.strip()


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
