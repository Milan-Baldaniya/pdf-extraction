"""CBSE section fingerprint for an extracted question-bank chapter.

This is a thin view over `question_extractor`. It used to carry its own
line-anchored parser, which passed a tidy fixture and then found 4 of 38
items on real MinerU output, because MinerU merges a whole page of prose
onto one markdown line. Rather than maintain two parsers that disagree,
the fingerprint is now derived from the same items the writer persists —
so what the queue screen reports is exactly what will be stored.

The fingerprint is stored on `document_extractions` so the later DeepSeek
pass knows what it should find, and so a bad extraction is visible before
any model spend follows it: a Class 9 maths chapter reporting 3 items in
Section A did not parse correctly.
"""

from __future__ import annotations

from typing import Any

from app.services.question_extractor import (  # re-exported for callers
    DEFAULT_FORM_BY_SECTION,
    FORM_TO_SECTION,
    extract_questions,
    summarise,
)

__all__ = [
    "analyze_question_structure",
    "FORM_TO_SECTION",
    "DEFAULT_FORM_BY_SECTION",
]


def analyze_question_structure(md_content: str | None) -> dict[str, Any]:
    """Return the section / question-type fingerprint for a chapter."""
    if not md_content or not md_content.strip():
        return {
            "sections": {},
            "question_types": {},
            "totals": {
                "items": 0,
                "sections_detected": 0,
                "marks": 0,
                "figure_dependent": 0,
                "internal_choice": 0,
            },
            "blueprint": {"matches_cbse_pattern": False, "observed": {}, "expected": {}},
            "has_answer_key": False,
            "warnings": ["md_content was empty"],
        }

    parsed = extract_questions(md_content)
    summary = summarise(parsed["items"], has_answer_key=parsed["answer_key_found"])
    # Surface parser warnings (empty stems, MCQs with no key) alongside the
    # blueprint gaps, so one glance covers both kinds of problem.
    summary["warnings"] = list(summary.get("warnings", [])) + list(parsed.get("warnings", []))
    return summary
