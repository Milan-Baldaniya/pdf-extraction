"""Turn an extracted question-bank chapter into structured exam items.

The single most important thing about this parser: it works on the TEXT
STREAM, not on lines.

MinerU's layout model merges a whole page of prose into one markdown line.
A real chapter contains lines like

    • Section A: Multiple Choice Questions 1. The degree of the polynomial
    $5y^{3}+y^{2}+2y-1$ is (a) 1 (b) 2 (c) 3 (d) 0 Solution: ... Answer: ( c)
    2. The coefficient of ...

— a section heading, four questions, their options, worked solutions and
answer keys, all on one line. Every line-anchored pattern (`^\\s*\\d+\\.`)
finds nothing here. Anchoring to the stream instead, and leaning on
monotonic question numbering to decide what is really an item boundary, is
what makes this work on real output rather than on a tidy fixture.

Design rule: anything the document states is read, never inferred. Section,
marks and question form come from the heading. Option letters come from the
option markers. The correct answer comes from the printed key. A model is
only worth spending on what the page genuinely does not say — concept,
Bloom, DOK — and that happens later, against this output.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

# --- CBSE vocabulary ------------------------------------------------------
# Marks per section are fixed by the board's paper design. Real extractions
# frequently drop the "(2 marks each)" from the heading, so the form->marks
# table is the fallback, and a stated value always wins over it.
FORM_TO_SECTION: dict[str, tuple[str, int]] = {
    "mcq": ("A", 1),
    "assertion_reason": ("A", 1),
    "true_false": ("A", 1),
    "fill_blank": ("A", 1),
    "very_short": ("B", 2),
    "short": ("C", 3),
    "long": ("D", 5),
    "case_study": ("E", 4),
}

DEFAULT_FORM_BY_SECTION = {
    "A": "mcq", "B": "very_short", "C": "short", "D": "long", "E": "case_study",
}

# "Section A:", "SECTION - B", "Section C." — anywhere in the stream.
_SECTION_RE = re.compile(r"Section\s*[-–—]?\s*([A-E])\s*[:\-–.]", re.IGNORECASE)
# The Assertion-Reason block is its own heading with no letter; it is Section A.
_AR_HEADING_RE = re.compile(r"Assertion\s*[-–—]?\s*Reason(?:ing)?\s+Questions?", re.IGNORECASE)

# Descriptive headings, longest/most specific first.
_FORM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("assertion_reason", re.compile(r"Assertion\s*[-–—]?\s*Reason", re.IGNORECASE)),
    ("case_study", re.compile(r"Case[\s-]*(?:Based|Stud)", re.IGNORECASE)),
    ("very_short", re.compile(r"Very\s+Short", re.IGNORECASE)),
    ("mcq", re.compile(r"Multiple\s+Choice|\bMCQs?\b", re.IGNORECASE)),
    ("true_false", re.compile(r"True\s*/?\s*False", re.IGNORECASE)),
    ("fill_blank", re.compile(r"Fill\s+in\s+the\s+blank", re.IGNORECASE)),
    ("long", re.compile(r"Long\s+Answer|Long\s+Type", re.IGNORECASE)),
    ("short", re.compile(r"Short\s+Answer|Short\s+Type", re.IGNORECASE)),
]

# An item number in the stream: "17." followed by whitespace and the start of
# a question. The lookbehind rejects "3.4" and "= 20." style numerals; the
# lookahead requires the next token to look like the beginning of a question
# rather than a continuation of an equation.
_ITEM_RE = re.compile(
    r"(?:(?<=\s)|(?<=^)|(?<=>))(\d{1,3})\s*[.)]\s+(?=[A-Z(\$\\«\"'‘“]|[A-Za-z]{3,})"
)
_OPTION_RE = re.compile(r"\(\s*([a-dA-D])\s*\)\s*")
_SUBITEM_RE = re.compile(r"\(\s*(i{1,3}|iv|v|vi{0,3})\s*\)", re.IGNORECASE)
_OR_RE = re.compile(r"(?:(?<=\s)|(?<=^))OR(?=\s)")
_ASSERT_RE = re.compile(r"Assertion\s*\(?\s*A\s*\)?\s*[:\-–]", re.IGNORECASE)
_REASON_RE = re.compile(r"Reason\s*\(?\s*R\s*\)?\s*[:\-–]", re.IGNORECASE)
_ANSWER_RE = re.compile(r"Answer\s*[:\-–]\s*\(?\s*([a-dA-D])\s*\)", re.IGNORECASE)
_ANSWER_TEXT_RE = re.compile(r"Answer\s*[:\-–]\s*", re.IGNORECASE)
_SOLUTION_RE = re.compile(r"Sol(?:ution)?s?\s*\.?\s*[:\-–]", re.IGNORECASE)
_PAGE_MARKER_RE = re.compile(r"^\s{0,3}#{1,6}\s*Page\s+(\d+)\s*$", re.MULTILINE | re.IGNORECASE)
_ANSWER_BLOCK_RE = re.compile(r"(?:^|\n)\s{0,3}#{0,6}\s*(?:ANSWERS?|ANSWER\s+KEY)\s*[:\-–]?\s*(?:\n|$)", re.IGNORECASE)
_KEY_ENTRY_RE = re.compile(r"(?:(?<=\s)|(?<=^))(\d{1,3})\s*[.)]\s*([^\n]{0,300}?)(?=\s+\d{1,3}\s*[.)]|\n|$)")
_MARKS_HEADING_RE = re.compile(r"\(\s*(\d+)\s*marks?\s*(?:each)?\s*\)", re.IGNORECASE)
_MARKS_PART_RE = re.compile(r"\(\s*(\d+)\s*marks?\s*\)", re.IGNORECASE)
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_FIGURE_REF_RE = re.compile(
    r"\b(?:in|from|given|shown|see)\s+the\s+(?:figure|diagram|graph|fig\.?|table|grid)"
    r"|\b(?:figure|graph|diagram)\s+(?:below|above|shows|given)|\bas\s+shown\b",
    re.IGNORECASE,
)
# "Draw the graph ... and find its zero from the graph" refers to the graph the
# student has just been told to produce, not one printed in the book. Without
# this, every construction question trips V-07 and is held for a figure that
# was never meant to exist.
_FIGURE_SELF_DRAWN_RE = re.compile(
    r"\b(?:draw|plot|sketch|construct|prepare|make)\s+(?:a|an|the)\s+"
    r"(?:graph|diagram|figure|table|histogram|bar\s+graph|number\s+line)",
    re.IGNORECASE,
)
# An unambiguously *supplied* figure still wins, so "draw the bar graph for the
# data shown in the figure below" stays required.
_FIGURE_GIVEN_RE = re.compile(
    r"\b(?:figure|diagram|graph|fig\.?|grid)\s+(?:below|above|given|shown)"
    r"|\b(?:in|from)\s+the\s+(?:given|adjoining|following)\s+"
    r"(?:figure|diagram|graph|fig\.?)"
    r"|\bas\s+shown\s+in\s+the\s+(?:figure|diagram|graph|fig\.?)",
    re.IGNORECASE,
)


def _figure_required(body: str) -> bool:
    """True when the item needs a figure the document was supposed to supply."""
    if not _FIGURE_REF_RE.search(body):
        return False
    if _FIGURE_GIVEN_RE.search(body):
        return True
    return not _FIGURE_SELF_DRAWN_RE.search(body)




def _page_index(markdown: str) -> list[tuple[int, int]]:
    marks = [(m.start(), int(m.group(1))) for m in _PAGE_MARKER_RE.finditer(markdown)]
    return marks or [(0, 1)]


def _page_for(offset: int, index: list[tuple[int, int]]) -> int | None:
    page = None
    for start, number in index:
        if start <= offset:
            page = number
        else:
            break
    return page


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _content_hash(stem: str, options: list[dict[str, Any]]) -> str:
    payload = _norm(stem) + "|" + "|".join(sorted(_norm(o.get("text", "")) for o in options))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _find_sections(text: str) -> list[dict[str, Any]]:
    """Locate section headings anywhere in the stream, in document order."""
    marks: list[dict[str, Any]] = []
    for match in _SECTION_RE.finditer(text):
        marks.append({"at": match.start(), "end": match.end(), "letter": match.group(1).upper()})
    for match in _AR_HEADING_RE.finditer(text):
        # Only a heading if a Section marker did not already claim this spot.
        if not any(abs(m["at"] - match.start()) < 40 for m in marks):
            marks.append({"at": match.start(), "end": match.end(), "letter": "A"})
    marks.sort(key=lambda m: m["at"])

    sections: list[dict[str, Any]] = []
    for i, mark in enumerate(marks):
        # The heading's descriptive tail decides the question form.
        tail = text[mark["end"]: mark["end"] + 120]
        form = None
        for name, pattern in _FORM_PATTERNS:
            if pattern.search(tail) or pattern.search(text[max(0, mark["at"] - 60): mark["end"]]):
                form = name
                break
        marks_match = _MARKS_HEADING_RE.search(tail)
        sections.append(
            {
                "letter": mark["letter"],
                "form": form,
                "marks": int(marks_match.group(1)) if marks_match else None,
                "heading": re.sub(r"\s+", " ", text[mark["at"]: mark["end"] + 60]).strip()[:191],
                "start": mark["end"],
                "end": marks[i + 1]["at"] if i + 1 < len(marks) else len(text),
            }
        )
    return sections


def _monotonic_items(body: str) -> list[tuple[int, int]]:
    """[(offset, number)] for real item starts.

    A number only opens an item when it continues the run. Without this every
    numeral inside a worked solution, an equation or a coordinate pair reads
    as a new question — and in a stream-joined extraction there are hundreds.
    """
    found: list[tuple[int, int]] = []
    last = 0
    for match in _ITEM_RE.finditer(body):
        number = int(match.group(1))
        if found:
            if number == last + 1:
                found.append((match.start(), number))
                last = number
        elif 1 <= number <= 60:
            found.append((match.start(), number))
            last = number
    return found


def _split_options(body: str) -> tuple[str, list[dict[str, Any]]]:
    """Separate the stem from an inline (a)…(d) option run."""
    # Options must not be searched past the solution: a worked solution that
    # says "(b)" is not a fifth option.
    limit = len(body)
    for pattern in (_SOLUTION_RE, _ANSWER_TEXT_RE):
        hit = pattern.search(body)
        if hit:
            limit = min(limit, hit.start())
    region = body[:limit]

    runs: list[tuple[int, int, str]] = []
    expected = "A"
    for match in _OPTION_RE.finditer(region):
        letter = match.group(1).upper()
        if letter != expected:
            continue
        runs.append((match.start(), match.end(), letter))
        expected = chr(ord(letter) + 1)
        if expected > "D":
            break

    if len(runs) < 2:
        return body.strip(), []

    stem = region[: runs[0][0]].strip()
    options: list[dict[str, Any]] = []
    for i, (_start, end, letter) in enumerate(runs):
        stop = runs[i + 1][0] if i + 1 < len(runs) else len(region)
        options.append(
            {
                "label": letter,
                "sequence": i,
                "text": re.sub(r"\s+", " ", region[end:stop]).strip(" .;,"),
                "is_correct": False,
            }
        )
    return stem, options


def _extract_answer(body: str) -> tuple[str | None, str | None]:
    letter_match = _ANSWER_RE.search(body)
    letter = letter_match.group(1).upper() if letter_match else None

    solution = None
    sol = _SOLUTION_RE.search(body)
    if sol:
        stop = letter_match.start() if (letter_match and letter_match.start() > sol.end()) else len(body)
        solution = re.sub(r"\s+", " ", body[sol.end():stop]).strip() or None
    elif letter_match:
        tail = re.sub(r"\s+", " ", body[letter_match.end():]).strip()
        solution = tail or None
    return letter, solution


def _parse_answer_key(block: str) -> dict[int, dict[str, Any]]:
    key: dict[int, dict[str, Any]] = {}
    last = 0
    for match in _KEY_ENTRY_RE.finditer(block):
        number = int(match.group(1))
        rest = (match.group(2) or "").strip()
        if key and number != last + 1:
            continue
        letter = None
        letter_match = re.match(r"\(?\s*([a-dA-D])\s*\)", rest)
        if letter_match:
            letter = letter_match.group(1).upper()
        key[number] = {"letter": letter, "text": rest}
        last = number
    return key


def _field_after(body: str, pattern: re.Pattern[str], stop_at: re.Pattern[str] | None) -> str | None:
    match = pattern.search(body)
    if not match:
        return None
    tail = body[match.end():]
    if stop_at:
        stop = stop_at.search(tail)
        if stop:
            tail = tail[: stop.start()]
    value = re.sub(r"\s+", " ", tail).strip()
    return value[:2000] or None


def extract_questions(
    md_content: str | None,
    *,
    attribution: str | None = None,
    licence: str | None = None,
) -> dict[str, Any]:
    """Parse a question-bank chapter into structured exam items."""
    if not md_content or not md_content.strip():
        return {"items": [], "answer_key_found": False, "warnings": ["md_content was empty"]}

    pages = _page_index(md_content)
    key_match = _ANSWER_BLOCK_RE.search(md_content)
    region = md_content[: key_match.start()] if key_match else md_content
    answer_key = _parse_answer_key(md_content[key_match.end():]) if key_match else {}

    items: list[dict[str, Any]] = []
    warnings: list[str] = []
    ordinal = 0

    sections = _find_sections(region)
    if not sections:
        return {
            "items": [],
            "answer_key_found": bool(key_match),
            "warnings": ["No CBSE section headings found anywhere in the text."],
        }

    for section in sections:
        body = region[section["start"]: section["end"]]
        form = section["form"] or DEFAULT_FORM_BY_SECTION.get(section["letter"], "unknown")
        section_marks = section["marks"] or FORM_TO_SECTION.get(form, ("", 0))[1] or None

        starts = _monotonic_items(body)
        for i, (start, number) in enumerate(starts):
            end = starts[i + 1][0] if i + 1 < len(starts) else len(body)
            raw = _ITEM_RE.sub("", body[start:end], count=1)

            or_hit = _OR_RE.search(raw)
            alternatives = (
                [raw[: or_hit.start()], raw[or_hit.end():]] if or_hit else [raw]
            )
            choice_group = str(uuid.uuid4()) if len(alternatives) > 1 else None

            for role_index, alt in enumerate(alternatives):
                stem, options = _split_options(alt)
                letter, solution = _extract_answer(alt)

                entry = answer_key.get(number)
                if letter is None and entry:
                    letter = entry.get("letter")
                if solution is None and entry:
                    solution = entry.get("text")
                if letter:
                    for option in options:
                        option["is_correct"] = option["label"] == letter

                item_form = form
                has_ar = bool(_ASSERT_RE.search(alt) and _REASON_RE.search(alt))
                if has_ar:
                    item_form = "assertion_reason"
                elif options and form in {"unknown", "mcq"}:
                    item_form = "mcq"

                # Sub-part labels appear twice in this corpus: once in the
                # question and again in the worked solution ("(i) 100 - 5 x 15
                # = 25"). Count them only in the question half, and dedupe,
                # or a 3-part case study reports 8 parts.
                question_half = alt
                sol_hit = _SOLUTION_RE.search(alt)
                if sol_hit:
                    question_half = alt[: sol_hit.start()]
                seen_parts: list[str] = []
                for label in _SUBITEM_RE.findall(question_half):
                    lowered = label.lower()
                    if lowered not in seen_parts:
                        seen_parts.append(lowered)
                sub_parts = seen_parts

                marks = section_marks
                if form == "case_study" and sub_parts:
                    item_form = "case_study_parent"
                    part_marks = [int(m) for m in _MARKS_PART_RE.findall(question_half)]
                    if part_marks:
                        marks = sum(part_marks)

                offset = section["start"] + start
                ordinal += 1
                items.append(
                    {
                        "item_ordinal": ordinal,
                        "item_number": str(number),
                        "exam_section": section["letter"],
                        "section_heading": section["heading"],
                        "section_marks": section_marks,
                        "item_form": item_form,
                        "marks": marks,
                        "stem": re.sub(r"\s+", " ", stem).strip(),
                        "options": options,
                        "correct_option": letter,
                        "answer_text": solution,
                        "assertion": _field_after(alt, _ASSERT_RE, _REASON_RE) if has_ar else None,
                        "reason": _field_after(alt, _REASON_RE, _SOLUTION_RE) if has_ar else None,
                        "sub_part_labels": sub_parts,
                        "choice_group_id": choice_group,
                        "choice_role": ("a", "b")[role_index] if choice_group else None,
                        "figure_required": _figure_required(alt),
                        "images": _IMAGE_RE.findall(alt),
                        "source_char_start": offset,
                        "source_char_end": section["start"] + end,
                        "source_page": _page_for(offset, pages),
                        "verbatim_sha256": _content_hash(stem, options),
                        "verbatim_payload": alt.strip()[:20000],
                        "attribution": attribution,
                        "licence": licence,
                        "reproduction": "verbatim",
                    }
                )

    if not items:
        warnings.append("Sections were found but no items parsed inside them.")
    blank = [i["item_number"] for i in items if not i["stem"]]
    if blank:
        warnings.append(f"{len(blank)} item(s) have an empty stem: {blank[:10]}")
    unanswered = [i["item_number"] for i in items if i["item_form"] == "mcq" and not i["correct_option"]]
    if unanswered:
        warnings.append(f"{len(unanswered)} MCQ item(s) have no correct option: {unanswered[:10]}")
    if not key_match:
        warnings.append("No trailing answer-key block; relying on inline answers only.")

    return {"items": items, "answer_key_found": bool(key_match), "warnings": warnings}


def summarise(items: list[dict[str, Any]], *, has_answer_key: bool = False) -> dict[str, Any]:
    """Aggregate parsed items into the CBSE section fingerprint."""
    sections: dict[str, dict[str, Any]] = {}
    question_types: dict[str, int] = {}
    total_marks = 0
    figures = 0
    choices = 0

    for item in items:
        letter = item["exam_section"]
        entry = sections.setdefault(
            letter,
            {"count": 0, "marks_each": item.get("section_marks"), "forms": [],
             "headings": [], "internal_choice": 0, "figure_dependent": 0},
        )
        entry["count"] += 1
        if item.get("figure_required"):
            entry["figure_dependent"] += 1
            figures += 1
        if item.get("choice_group_id"):
            entry["internal_choice"] += 1
            choices += 1
        if item["item_form"] not in entry["forms"]:
            entry["forms"].append(item["item_form"])
        if item.get("section_heading") and item["section_heading"] not in entry["headings"]:
            entry["headings"].append(item["section_heading"])
        question_types[item["item_form"]] = question_types.get(item["item_form"], 0) + 1
        total_marks += item.get("marks") or 0

    expected = {"A": 20, "B": 5, "C": 6, "D": 4, "E": 3}
    observed = {k: v["count"] for k, v in sections.items()}
    warnings = []
    for letter, count in expected.items():
        got = observed.get(letter)
        if got is None:
            warnings.append(f"Section {letter} not found.")
        elif got != count:
            warnings.append(f"Section {letter}: found {got} items, CBSE pattern expects {count}.")

    return {
        "sections": sections,
        "question_types": question_types,
        "totals": {
            "items": len(items),
            "sections_detected": len(sections),
            "marks": total_marks,
            "figure_dependent": figures,
            "internal_choice": choices,
        },
        "blueprint": {
            "matches_cbse_pattern": all(observed.get(k) == v for k, v in expected.items()),
            "observed": observed,
            "expected": expected,
        },
        "has_answer_key": has_answer_key,
        "warnings": warnings,
    }
