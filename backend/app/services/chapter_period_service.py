"""Chapter-wise period allocation, written to ``chapter_master.no_of_periods``.

Curriculum documents state instructional time at one of two levels, and both
have to be honoured or most chapters end up with nothing:

1. PER CHAPTER, on the chapter heading -- "Tissues   No. of Periods: 13" (the
   CBSE subject syllabi). This is the exact number for that chapter and is
   used verbatim.
2. PER UNIT/theme -- "UNIT IV: GEOMETRY  No. of periods : 69", "Understanding
   Social Science (4 Hours)" (the NCF-SE 2023 course outlines), stored as
   ``lms_units.planned_periods``. The allocation is split evenly across the
   chapters chapter_master holds for that unit, remainder to the earliest, so a
   unit's chapters sum back to exactly its allocation. A unit covering one
   chapter keeps the document's number verbatim; a 36-period unit spanning 4
   chapters gives 9 each rather than claiming 36 apiece.

Level 1 wins wherever the document provides it, and level 2 fills the rest.

READ THE PDF, NOT THE MARKDOWN. MinerU's OCR silently loses these numbers: in
the Class IX Science syllabus it dropped the count for 3 chapters and omitted 2
chapter headings entirely, and in Class IX Maths it lost 2 of the 6 unit totals.
The digits are simply absent from ``md_content``, so no amount of LLM prompting
could recover them -- but every one of them is present in the PDF's own text
layer. ``extract_chapter_periods_from_pdf`` reads it directly with PyMuPDF,
which costs nothing and is exact. The markdown headings remain a fallback for
extractions whose PDF is no longer on disk, and the LLM's own reading is the
last resort.

Two matching problems sit in between. The ERP rewrites chapter titles, so the
syllabus "Tissues" is "Tissues in Action" in chapter_master and exact-name
matching finds almost nothing -- ``_align_unit`` scores titles on shared words
and falls back to position within the unit, which the data supports because
``unit_chapters`` runs in the same order as the ERP's ``sort_order``. And
``unit_chapters`` means different things per document: chapters for Maths and
Science, but topic bullets for Social Science, Physical Education and Skill
Education ("Meaning, scope and relevance of Social Science"). It is therefore
used for matching and ordering only, never as the denominator of a split, which
would silently divide a 4-period chapter down to 2.

Nothing here calls an LLM, so it is safe to run on every Process click.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
import unicodedata
from typing import Any

from sqlalchemy import text

from app.db.mariadb import SessionLocal
from app.utils.config import settings

logger = logging.getLogger(__name__)

PERIODS_COLUMN = "no_of_periods"
CURRICULUM_PERIODS_COLUMN = "chapter_periods"

# Below this, two titles are treated as unrelated and position decides instead.
# "Structure of an Atom" vs "Journey Inside the Atom" shares only "atom" (0.5)
# and is genuinely a different name for the same chapter, so it must NOT pin.
_MATCH_THRESHOLD = 0.6

_STOPWORDS = frozenset(
    "a an and are as at be by for from in into its of on or the their to with".split()
)

_PERIOD_LABEL = r"(?:no\.?\s*of\s*)?(?:periods?|instructional\s+hours?|hours?|hrs?)"

# "Tissues No. of Periods: 13", "Chapter Name - Periods : 6". The name may be
# empty, which on a PDF page means it sits in a separate box on the same line.
_LABEL_FIRST = re.compile(
    rf"^(?P<name>.*?)[\s\-–—:,()\[\]]*{_PERIOD_LABEL}\s*[:\-–—]?\s*(?P<n>\d{{1,3}})\s*[)\]]*$",
    re.IGNORECASE,
)
# "Understanding Social Science (4 Hours)", "Yoga 14 Hours"
_NUM_FIRST = re.compile(
    rf"^(?P<name>.+?)[\s\-–—:,(\[]+(?P<n>\d{{1,3}})\s*{_PERIOD_LABEL}\s*[)\]]*$",
    re.IGNORECASE,
)
_HEADING_PREFIX = re.compile(r"^\s{0,3}#{1,6}\s*")

# A "name" made only of these is a time label the regex mistook for a title:
# "Time: 03 Hours" leaves "Time", "(Suggestive Instructional Hours: 10)" leaves
# "Instructional". None of them is a chapter.
_TIME_VOCABULARY = frozenset(
    "time times period periods hour hours hr hrs instructional suggestive total "
    "theory practical marks max min duration t p".split()
)
# A leftover allocation inside the name means the line carried several of them
# ("Unit 2 ... 6 Hours (T: 2 hrs, P: 4 hrs)") and none can be attributed.
_INNER_ALLOCATION = re.compile(
    rf"\d+\s*(?:periods?|hours?|hrs?)|{_PERIOD_LABEL}\s*[:\-–—]?\s*\d", re.IGNORECASE
)

# The ALTERs only ever need to run once per database, but Process is the only
# thing that reaches this code, so the check is cached rather than skipped.
_columns_ready = False


def _column_exists(db, table: str, column: str) -> bool:
    return db.execute(
        text(
            """
            SELECT 1 FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :tbl AND COLUMN_NAME = :col
            """
        ),
        {"tbl": table, "col": column},
    ).fetchone() is not None


def ensure_periods_column(db) -> bool:
    """Create the two columns this service writes, if the database lacks them."""
    global _columns_ready
    if _columns_ready:
        return True

    if not _column_exists(db, "chapter_master", PERIODS_COLUMN):
        db.execute(
            text(
                f"ALTER TABLE chapter_master "
                f"ADD COLUMN {PERIODS_COLUMN} INT NULL AFTER key_concepts"
            )
        )
        db.commit()
        logger.info("Added chapter_master.%s", PERIODS_COLUMN)

    if not _column_exists(db, "lms_curriculum", CURRICULUM_PERIODS_COLUMN):
        # utf8mb4 is pinned explicitly: the server default is latin1, and these
        # chapter names carry Devanagari and typographic punctuation.
        db.execute(
            text(
                f"ALTER TABLE lms_curriculum "
                f"ADD COLUMN {CURRICULUM_PERIODS_COLUMN} LONGTEXT "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL"
            )
        )
        db.commit()
        logger.info("Added lms_curriculum.%s", CURRICULUM_PERIODS_COLUMN)

    _columns_ready = True
    return True


def _match_period_line(line: str) -> tuple[str, int] | None:
    """Pull ``(name, periods)`` out of one line of text, if it states one."""
    match = _LABEL_FIRST.match(line) or _NUM_FIRST.match(line)
    if not match:
        return None
    periods = int(match.group("n"))
    # 0 rejects "Max. Marks: 100 Time: 3:00 Hours", which otherwise reads as a
    # chapter of "00" hours.
    if periods < 1:
        return None
    name = match.group("name").strip(" -–—:,.()[]")
    if len(name) > 120:
        return None
    return name, periods


def _is_chapter_title(name: str) -> bool:
    """Reject the things a period regex picks up that are not chapter names."""
    if len(name) < 3:
        return False
    if _INNER_ALLOCATION.search(name):
        return False
    tokens = _normalize(name).split()
    if not tokens or all(t in _TIME_VOCABULARY for t in tokens):
        return False
    # Chapter titles are capitalised; a fragment carved out of a sentence or a
    # table cell ("chains, employment") is not. Scripts without case, such as
    # Devanagari, are unaffected.
    first = next((c for c in name if c.isalpha()), "")
    return not (first.islower() and first.isascii())


def parse_chapter_periods_from_markdown(md_content: str) -> list[dict[str, Any]]:
    """Read per-chapter period counts out of a curriculum's markdown headings.

    Only markdown headings are considered. Period counts also appear inside the
    OCR'd HTML tables, but there they belong to a unit rather than a chapter and
    arrive too mangled to attribute safely ("UNIT IV: GEOMETRY No. of periods
    History of geometry"), so a wider net would invent chapter numbers that the
    document never stated.
    """
    found: list[dict[str, Any]] = []
    seen: set[str] = set()

    for line in (md_content or "").split("\n"):
        stripped = line.strip()
        if not stripped.startswith("#") or len(stripped) > 160:
            continue

        hit = _match_period_line(_HEADING_PREFIX.sub("", stripped))
        if not hit:
            continue

        name, periods = hit
        key = _normalize(name)
        if not key or key in seen or not _is_chapter_title(name):
            continue

        seen.add(key)
        found.append({"chapter_name": name, "no_of_periods": periods})

    return found


def _pdf_heading_lines(page) -> list[dict[str, Any]]:
    """Text lines of one PDF page with the position and weight of each."""
    lines: list[dict[str, Any]] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans") or []
            content = "".join(s.get("text", "") for s in spans).strip()
            if not content:
                continue
            first = spans[0]
            lines.append({
                "text": content,
                "x": line["bbox"][0],
                "y": line["bbox"][1],
                "size": round(float(first.get("size") or 0), 1),
                # bit 4 of the span flags is the bold marker
                "bold": bool(int(first.get("flags") or 0) & 16),
            })
    return lines


def extract_chapter_periods_from_pdf(pdf_path: str) -> list[dict[str, Any]]:
    """Read per-chapter period counts from the curriculum PDF's own text layer.

    This is the accurate source and the reason it exists: MinerU's OCR silently
    drops these numbers. In the Class IX Science syllabus it lost the count for
    3 chapters and omitted 2 chapter headings altogether, so neither the
    markdown nor the LLM could ever recover them -- the digits were simply not
    in the extracted text. The PDF itself has them all.

    On the page the chapter name and its count sit on one visual line, sometimes
    inside a single text run ("Tissues        No. of Periods: 13") and sometimes
    as two boxes at the same height. Both are handled, and a count is only
    accepted when its name is set in a heading weight -- bold, or larger than
    the document's body text. That is what separates a chapter's own allocation
    from the unit totals inside the course-structure tables.
    """
    try:
        import fitz  # PyMuPDF, already used by the extraction pipeline
    except ImportError:
        logger.warning("PyMuPDF unavailable; cannot read chapter periods from %s", pdf_path)
        return []

    found: list[dict[str, Any]] = []
    seen: set[str] = set()

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        logger.warning("Could not open %s: %s", pdf_path, exc)
        return []

    try:
        pages = [_pdf_heading_lines(doc[i]) for i in range(doc.page_count)]

        sizes: dict[float, int] = {}
        for page_lines in pages:
            for line in page_lines:
                sizes[line["size"]] = sizes.get(line["size"], 0) + 1
        body_size = max(sizes, key=lambda s: sizes[s]) if sizes else 0.0

        for page_lines in pages:
            ordered = sorted(page_lines, key=lambda l: (round(l["y"]), l["x"]))
            for index, line in enumerate(ordered):
                hit = _match_period_line(line["text"])
                if not hit:
                    continue
                name, periods = hit
                source_line = line

                if not name:
                    # The count is its own box; the name is the box to its left
                    # on the same line, or failing that the line above.
                    same_line = [
                        other for other in ordered
                        if other is not line and abs(other["y"] - line["y"]) <= 4
                        and other["x"] < line["x"]
                    ]
                    above = [other for other in ordered[:index] if other["y"] < line["y"] - 2]
                    neighbour = (same_line or above or [None])[-1]
                    if neighbour is None:
                        continue
                    name = neighbour["text"].strip(" -–—:,.()[]")
                    source_line = neighbour

                key = _normalize(name)
                if not key or key in seen or not _is_chapter_title(name):
                    continue
                # Body-weight text is prose or a table cell, not a chapter title.
                if not source_line["bold"] and source_line["size"] <= body_size:
                    continue

                seen.add(key)
                found.append({"chapter_name": name, "no_of_periods": periods})
    finally:
        doc.close()

    return found


def _run_dir_pdfs(run_id: str) -> list[str]:
    paths: list[str] = []
    for root in (settings.output_dir, settings.temp_dir):
        for pattern in (
            os.path.join(root, run_id, "**", "input_origin.pdf"),
            os.path.join(root, run_id, "**", "input.pdf"),
            os.path.join(root, run_id, "input.pdf"),
        ):
            paths.extend(p for p in glob.glob(pattern, recursive=True) if os.path.isfile(p))
    return paths


def _all_stored_pdfs() -> list[str]:
    paths: list[str] = []
    for root in (settings.output_dir, settings.temp_dir):
        for name in ("input_origin.pdf", "input.pdf"):
            paths.extend(glob.glob(os.path.join(root, "**", name), recursive=True))
    return sorted(set(p for p in paths if os.path.isfile(p)))


def _pdf_matches_extraction(path: str, page_count: int | None, md_head: str) -> bool:
    """Is this the PDF that produced that extraction?

    Page count plus a strong word overlap on the opening page. Both are needed:
    many stored PDFs share a page count, and OCR noise means the text will never
    compare equal.
    """
    try:
        import fitz
    except ImportError:
        return False
    try:
        doc = fitz.open(path)
    except Exception:
        return False
    try:
        if page_count and doc.page_count != page_count:
            return False
        head = " ".join(doc[i].get_text() for i in range(min(2, doc.page_count)))
    finally:
        doc.close()

    pdf_tokens = _tokens(head[:4000])
    md_tokens = _tokens(md_head[:4000])
    if len(pdf_tokens) < 20 or len(md_tokens) < 20:
        return False
    return len(pdf_tokens & md_tokens) / min(len(pdf_tokens), len(md_tokens)) >= 0.6


def find_source_pdf(
    json_content: str | None,
    page_count: int | None = None,
    md_content: str | None = None,
) -> str | None:
    """Locate the PDF an extraction came from, if it is still on disk.

    Uploaded curricula have no retrievable ``pdf_url``, but MinerU's asset paths
    in ``json_content`` carry the run id, and the run directory keeps the
    original alongside its output. When that directory is gone -- or the
    document was re-extracted later under a new run id, which is why the Class
    IX Maths syllabus was not found by id -- the same PDF is matched by page
    count and opening text instead.
    """
    for run_id in dict.fromkeys(re.findall(r"[0-9a-f]{12}", (json_content or "")[:200_000])):
        for path in _run_dir_pdfs(run_id):
            return path

    if not md_content:
        return None
    for path in _all_stored_pdfs():
        if _pdf_matches_extraction(path, page_count, md_content):
            logger.info("Matched %s to an extraction by content", path)
            return path
    return None


_UNIT_PREFIX = re.compile(
    r"^\s*unit\s*[-–—]?\s*(?:[0-9]{1,2}|[ivxlc]+)\s*[:.\-–—)]*\s*", re.IGNORECASE
)


def sync_unit_periods_from_pdf(db, curriculum_id: int, entries: list[dict[str, Any]]) -> int:
    """Fill ``lms_units.planned_periods`` from counts read off the PDF.

    Curricula that allocate per unit put the count on the unit heading
    ("UNIT IV: GEOMETRY   No. of periods : 69"). MinerU loses some of those the
    same way it loses the chapter ones, and every chapter under an empty unit
    then has nothing to inherit. The PDF is the document itself, so its number
    wins over whatever the LLM read from the mangled markdown.
    """
    if not entries:
        return 0

    units = db.execute(
        text("SELECT id, name, planned_periods FROM lms_units WHERE curriculum_id = :cid"),
        {"cid": curriculum_id},
    ).mappings().fetchall()
    if not units:
        return 0

    candidates = [
        (_normalize(_UNIT_PREFIX.sub("", e["chapter_name"])), int(e["no_of_periods"]))
        for e in entries
        if e.get("chapter_name") and e.get("no_of_periods")
    ]

    changed = 0
    for unit in units:
        target = _normalize(unit["name"])
        if not target:
            continue
        value = next((v for name, v in candidates if name == target), None)
        if value is None or value == unit["planned_periods"]:
            continue
        # planned_periods is a TINYINT UNSIGNED; a bad parse must not throw.
        if not 0 < value <= 255:
            continue
        db.execute(
            text("UPDATE lms_units SET planned_periods = :p, updated_at = NOW() WHERE id = :uid"),
            {"p": value, "uid": unit["id"]},
        )
        changed += 1
        logger.info("Unit %s periods %s -> %s from PDF", unit["id"], unit["planned_periods"], value)

    return changed


def _normalize(name: Any) -> str:
    """Fold a chapter title down to something two sources can agree on.

    Curriculum listings and the ERP disagree on case, curly vs straight
    apostrophes and stray whitespace ("Shaping of the Earth's Surface" vs
    "Shaping of the Earth’s Surface"), so punctuation is dropped entirely.
    NFKC keeps Devanagari titles comparable across the same normalisation.
    """
    if not name:
        return ""
    folded = unicodedata.normalize("NFKC", str(name)).casefold()
    stripped = re.sub(r"[^\w\s]", " ", folded, flags=re.UNICODE)
    return re.sub(r"\s+", " ", stripped).strip()


def _tokens(name: Any) -> frozenset[str]:
    return frozenset(t for t in _normalize(name).split() if t and t not in _STOPWORDS)


def _similarity(a: Any, b: Any) -> float:
    """How strongly two chapter titles refer to the same chapter.

    Scored against the shorter title so the syllabus's terse "Tissues" still
    matches the ERP's "Tissues in Action" -- overlap over the union would score
    that 0.5 and miss it.
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def _align_unit(syllabus_names: list[str], rows: list[dict]) -> dict[int, int]:
    """Map chapter_master id -> index into the unit's syllabus chapter list.

    Confident title matches are pinned first, best score wins; whatever is left
    is paired off by position, which works because a unit's ``unit_chapters``
    runs in the same order as its chapters' ERP ``sort_order``. That positional
    step is what rescues the rewritten titles -- "Structure of an Atom" ->
    "Journey Inside the Atom" shares too little wording to pin on its own.
    """
    scored = [
        (_similarity(name, row["chapter_name"]), si, ri)
        for si, name in enumerate(syllabus_names)
        for ri, row in enumerate(rows)
    ]
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))

    aligned: dict[int, int] = {}
    used_slots: set[int] = set()
    used_rows: set[int] = set()

    for score, si, ri in scored:
        if score < _MATCH_THRESHOLD:
            break
        if si in used_slots or ri in used_rows:
            continue
        used_slots.add(si)
        used_rows.add(ri)
        aligned[rows[ri]["id"]] = si

    free_slots = [i for i in range(len(syllabus_names)) if i not in used_slots]
    free_rows = [i for i in range(len(rows)) if i not in used_rows]
    for si, ri in zip(free_slots, free_rows):
        aligned[rows[ri]["id"]] = si

    return aligned


def _even_shares(total: int, count: int) -> list[int]:
    """Split ``total`` into ``count`` parts that sum back to ``total``."""
    if count <= 0:
        return []
    base, remainder = divmod(total, count)
    return [base + 1 if i < remainder else base for i in range(count)]


def _parse_unit_chapters(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(c) for c in raw]
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return [str(c) for c in parsed] if isinstance(parsed, list) else []


def _chapter_rows_for_unit(db, unit: dict, curriculum: dict, chapter_names: list[str]) -> list[dict]:
    """Chapters belonging to a unit: mapped by ``unit_id``, plus exact name matches.

    A chapter processed before its curriculum has ``unit_id`` NULL, so those are
    picked up by matching the ERP title against the unit's own chapter list.
    Only exact (normalised) titles are claimed here -- the looser similarity
    matching in ``_align_unit`` is safe within a unit the ERP already assigned,
    but would steal unrelated chapters across a whole subject.
    """
    result = [dict(r) for r in db.execute(
        text("SELECT id, chapter_name, sort_order FROM chapter_master WHERE unit_id = :uid"),
        {"uid": unit["id"]},
    ).mappings().fetchall()]

    wanted = {_normalize(c) for c in chapter_names}
    wanted.discard("")
    if wanted:
        claimed = {r["id"] for r in result}
        for row in _subject_scoped_rows(db, curriculum, "cm.unit_id IS NULL"):
            if row["id"] not in claimed and _normalize(row["chapter_name"]) in wanted:
                claimed.add(row["id"])
                result.append(row)

    return result


def _erp_order(row: dict) -> tuple:
    order = row.get("sort_order")
    return (order is None, order or 0, row["id"])


def _allocate(
    unit_periods: int | None,
    chapter_names: list[str],
    rows: list[dict],
    explicit: dict[str, int] | None = None,
) -> dict[int, tuple[int | None, str | None]]:
    """Map chapter_master id -> (periods, source) for one unit.

    A chapter the document gave its own period count keeps that number exactly.
    Whatever is left over splits the unit's allocation between them -- minus any
    periods the explicit chapters already account for -- so a unit's chapters
    still sum to its allocation rather than double-counting.
    """
    if not rows:
        return {}

    explicit = explicit or {}
    ordered_rows = sorted(rows, key=_erp_order)
    aligned = _align_unit(chapter_names, ordered_rows)

    result: dict[int, tuple[int | None, str | None]] = {}
    remaining: list[dict] = []

    for row in ordered_rows:
        slot = aligned.get(row["id"])
        value = explicit.get(_normalize(chapter_names[slot])) if slot is not None else None
        if value is None:
            # Fall back to the ERP's own title, for a chapter the curriculum
            # names a period count for but does not list under any unit.
            value = explicit.get(_normalize(row["chapter_name"]))
        if value is None:
            remaining.append(row)
        else:
            result[row["id"]] = (value, "document_chapter")

    if not remaining:
        return result

    if unit_periods is None:
        # No allocation at either level; blanking keeps the row honest rather
        # than leaving a number from a previous, different extraction.
        for row in remaining:
            result[row["id"]] = (None, None)
        return result

    spoken_for = sum(value for value, _ in result.values() if value)
    pool = int(unit_periods) - spoken_for
    if pool <= 0 and spoken_for > 0:
        # The chapters with their own stated counts already account for the
        # whole unit. Nothing is known about the rest, and "0 periods" would be
        # a claim the document never made.
        for row in remaining:
            result[row["id"]] = (None, None)
        return result

    shares = _even_shares(max(pool, 0), len(remaining))

    # Split in the curriculum's own chapter order so the remainder lands
    # deterministically on the same chapters every run.
    remaining.sort(key=lambda row: (aligned.get(row["id"], len(chapter_names)), _erp_order(row)))
    for row, share in zip(remaining, shares):
        result[row["id"]] = (share, "unit_split")

    return result


def _write_periods(db, chapter_master_id: int, value: int | None) -> int:
    """Store one chapter's periods; returns 1 only if the value actually moved."""
    return db.execute(
        text(
            f"""
            UPDATE chapter_master
            SET {PERIODS_COLUMN} = :periods, updated_at = NOW()
            WHERE id = :cm_id AND NOT ({PERIODS_COLUMN} <=> :periods)
            """
        ),
        {"periods": value, "cm_id": chapter_master_id},
    ).rowcount


def _subject_scoped_rows(db, curriculum: dict, extra_where: str) -> list[dict]:
    """chapter_master rows for this curriculum's standard and subject.

    The subject join mirrors ``chapter_service``: lms_curriculum and
    chapter_master routinely hold different subject ids for the same subject
    (Social Science is 4064 on the curriculum and 4469 on the chapters), so a
    plain id comparison would find nothing.
    """
    if not curriculum.get("standard_id"):
        return []
    return [dict(r) for r in db.execute(
        text(
            f"""
            SELECT cm.id, cm.chapter_name, cm.sort_order
            FROM chapter_master cm
            LEFT JOIN subject cs ON cs.id = :curr_sub_id
            LEFT JOIN subject ms ON ms.id = cm.subject_id
            WHERE cm.standard_id = :std_id
              AND (:sub_inst IS NULL OR cm.sub_institute_id = :sub_inst)
              AND (
                    cm.subject_id = :curr_sub_id
                 OR LOWER(ms.subject_name) LIKE CONCAT(LOWER(cs.subject_name), '%')
                 OR LOWER(cs.subject_name) LIKE CONCAT(LOWER(ms.subject_name), '%')
              )
              AND {extra_where}
            """
        ),
        {
            "std_id": curriculum.get("standard_id"),
            "curr_sub_id": curriculum.get("subject_id"),
            "sub_inst": curriculum.get("sub_institute_id"),
        },
    ).mappings().fetchall()]


def _unmapped_chapter_rows(db, curriculum: dict, already_assigned: set[int]) -> list[dict]:
    rows = _subject_scoped_rows(db, curriculum, "cm.unit_id IS NULL")
    return [r for r in rows if r["id"] not in already_assigned]


def resolve_curriculum_chapter_periods(db, curriculum: dict) -> list[dict[str, Any]]:
    """The curriculum's per-chapter period counts, resolved once and cached.

    Three sources, best first:

    1. the source PDF's own text layer, which has every number the document
       states -- MinerU's OCR does not;
    2. the extracted markdown's headings, for extractions whose PDF is no
       longer on disk;
    3. whatever the LLM reported during Process, for layouts neither reads.

    The result is kept on ``lms_curriculum.chapter_periods`` so it can be
    audited against the document.
    """
    stored: list[dict[str, Any]] = []
    raw = curriculum.get(CURRICULUM_PERIODS_COLUMN)
    if raw:
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, list):
                stored = [e for e in parsed if isinstance(e, dict)]
        except (ValueError, TypeError):
            logger.warning("Unreadable chapter_periods on curriculum %s", curriculum.get("id"))

    extraction = db.execute(
        text(
            """
            SELECT md_content, json_content, page_count
            FROM document_extractions WHERE id = :ext
            """
        ),
        {"ext": curriculum.get("extraction_id")},
    ).mappings().fetchone() if curriculum.get("extraction_id") else None

    from_pdf: list[dict[str, Any]] = []
    if extraction:
        pdf_path = find_source_pdf(
            extraction["json_content"], extraction["page_count"], extraction["md_content"]
        )
        if pdf_path:
            from_pdf = extract_chapter_periods_from_pdf(pdf_path)
            # The same headings carry the unit totals, which chapters fall back
            # on when the document states nothing for the chapter itself.
            sync_unit_periods_from_pdf(db, curriculum["id"], from_pdf)

    from_markdown = parse_chapter_periods_from_markdown(extraction["md_content"] if extraction else "")

    merged: dict[str, dict[str, Any]] = {}
    for entry in from_pdf:
        merged[_normalize(entry["chapter_name"])] = {**entry, "source": "pdf_text_layer"}
    for entry in from_markdown:
        key = _normalize(entry["chapter_name"])
        if key not in merged:
            merged[key] = {**entry, "source": "document_heading"}
    for entry in stored:
        key = _normalize(entry.get("chapter_name"))
        if key and key not in merged and entry.get("no_of_periods"):
            merged[key] = {
                "chapter_name": entry["chapter_name"],
                "no_of_periods": int(entry["no_of_periods"]),
                "source": entry.get("source") or "llm",
            }

    entries = list(merged.values())
    # Compare on the values, not the JSON text, so a re-sync that found exactly
    # the same counts leaves the row (and its updated_at) alone.
    was = {_normalize(e.get("chapter_name")): e.get("no_of_periods") for e in stored}
    now = {_normalize(e["chapter_name"]): e["no_of_periods"] for e in entries}
    if was != now:
        db.execute(
            text(f"UPDATE lms_curriculum SET {CURRICULUM_PERIODS_COLUMN} = :val WHERE id = :cid"),
            {"val": json.dumps(entries, ensure_ascii=False), "cid": curriculum["id"]},
        )
    return entries


def store_llm_chapter_periods(db, curriculum_id: int, entries: Any) -> int:
    """Merge the per-chapter periods the curriculum LLM reported during Process.

    Headings parsed from the document still win; this only covers layouts the
    heading parser cannot see.
    """
    if not entries or not isinstance(entries, list):
        return 0

    ensure_periods_column(db)
    cleaned: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("chapter_name") or entry.get("name") or "").strip()
        periods = entry.get("no_of_periods", entry.get("periods"))
        try:
            periods = int(periods)
        except (TypeError, ValueError):
            continue
        if name and periods > 0:
            cleaned.append({"chapter_name": name, "no_of_periods": periods, "source": "llm"})

    if not cleaned:
        return 0

    db.execute(
        text(f"UPDATE lms_curriculum SET {CURRICULUM_PERIODS_COLUMN} = :val WHERE id = :cid"),
        {"val": json.dumps(cleaned, ensure_ascii=False), "cid": curriculum_id},
    )
    db.commit()
    return len(cleaned)


def sync_chapter_periods_for_curriculum(curriculum_id: int, db=None) -> dict[str, Any]:
    """Push every unit's period allocation down onto its chapters.

    Idempotent and LLM-free, so it is safe to run on every Process click --
    including the "already processed, skipped" path.
    """
    own_session = db is None
    db = db or SessionLocal()
    try:
        # Columns first: the SELECT below reads one of them.
        ensure_periods_column(db)

        curriculum = db.execute(
            text(
                f"""
                SELECT id, extraction_id, standard_id, subject_id, sub_institute_id,
                       {CURRICULUM_PERIODS_COLUMN}
                FROM lms_curriculum WHERE id = :cid
                """
            ),
            {"cid": curriculum_id},
        ).mappings().fetchone()

        if not curriculum:
            return {"curriculum_id": curriculum_id, "status": "curriculum_not_found",
                    "units": 0, "chapters_matched": 0, "chapters_updated": 0,
                    "explicit_chapter_periods": 0, "assignments": []}

        explicit_entries = resolve_curriculum_chapter_periods(db, dict(curriculum))
        explicit = {
            _normalize(e["chapter_name"]): e["no_of_periods"]
            for e in explicit_entries
            if e.get("chapter_name") and e.get("no_of_periods")
        }

        units = db.execute(
            text(
                """
                SELECT id, unit_number, name, planned_periods, unit_chapters
                FROM lms_units WHERE curriculum_id = :cid ORDER BY unit_number ASC
                """
            ),
            {"cid": curriculum_id},
        ).mappings().fetchall()

        assignments: list[dict[str, Any]] = []
        assigned: set[int] = set()
        updated = 0

        for unit in units:
            chapter_names = _parse_unit_chapters(unit["unit_chapters"])
            rows = _chapter_rows_for_unit(db, dict(unit), dict(curriculum), chapter_names)
            if not rows:
                continue

            periods = unit["planned_periods"]
            allocation = _allocate(periods, chapter_names, rows, explicit)

            by_id = {r["id"]: r for r in rows}
            for chapter_id, (value, source) in allocation.items():
                updated += _write_periods(db, chapter_id, value)
                assigned.add(chapter_id)
                assignments.append({
                    "chapter_master_id": chapter_id,
                    "chapter_name": by_id[chapter_id]["chapter_name"],
                    "unit_id": unit["id"],
                    "unit_name": unit["name"],
                    "unit_planned_periods": periods,
                    "no_of_periods": value,
                    "source": source,
                })

        # Chapters the curriculum names a period count for but that no unit
        # claims -- a chapter processed before its curriculum, or one the LLM
        # left unmapped -- would otherwise never receive a number.
        for row in _unmapped_chapter_rows(db, dict(curriculum), assigned):
            value = explicit.get(_normalize(row["chapter_name"]))
            if value is None:
                continue
            updated += _write_periods(db, row["id"], value)
            assignments.append({
                "chapter_master_id": row["id"],
                "chapter_name": row["chapter_name"],
                "unit_id": None,
                "unit_name": None,
                "unit_planned_periods": None,
                "no_of_periods": value,
                "source": "document_chapter",
            })

        db.commit()
        return {
            "curriculum_id": curriculum_id,
            "status": "success",
            "units": len(units),
            "explicit_chapter_periods": len(explicit),
            "chapters_matched": len(assignments),
            "chapters_with_periods": sum(1 for a in assignments if a["no_of_periods"] is not None),
            "chapters_updated": updated,
            "assignments": assignments,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        if own_session:
            db.close()


def sync_chapter_periods_for_unit(unit_id: int, db=None) -> dict[str, Any]:
    """Re-run the allocation for the curriculum owning ``unit_id``.

    A chapter joining a unit changes how many ways that unit's periods are
    split, so the whole curriculum is recomputed rather than just the one row.
    """
    own_session = db is None
    db = db or SessionLocal()
    try:
        row = db.execute(
            text("SELECT curriculum_id FROM lms_units WHERE id = :uid"),
            {"uid": unit_id},
        ).fetchone()
        if not row:
            return {"status": "unit_not_found", "unit_id": unit_id,
                    "units": 0, "chapters_matched": 0, "chapters_updated": 0, "assignments": []}
        return sync_chapter_periods_for_curriculum(row[0], db=db)
    finally:
        if own_session:
            db.close()


def sync_chapter_periods_for_extraction(extraction_id: int, db=None) -> dict[str, Any]:
    """Same, addressed by the curriculum's ``document_extractions`` id."""
    own_session = db is None
    db = db or SessionLocal()
    try:
        row = db.execute(
            text("SELECT id FROM lms_curriculum WHERE extraction_id = :ext"),
            {"ext": extraction_id},
        ).fetchone()
        if not row:
            return {"status": "curriculum_not_found", "extraction_id": extraction_id,
                    "units": 0, "chapters_matched": 0, "chapters_updated": 0, "assignments": []}
        return sync_chapter_periods_for_curriculum(row[0], db=db)
    finally:
        if own_session:
            db.close()


def sync_all_chapter_periods() -> dict[str, Any]:
    """Backfill every processed curriculum. For curricula filled before this
    field existed; Process keeps new ones in sync on its own."""
    with SessionLocal() as db:
        ids = [r[0] for r in db.execute(
            text("SELECT id FROM lms_curriculum ORDER BY id ASC")
        ).fetchall()]

        results = []
        for cid in ids:
            try:
                res = sync_chapter_periods_for_curriculum(cid, db=db)
                results.append({k: v for k, v in res.items() if k != "assignments"})
            except Exception as exc:
                logger.warning("Period sync failed for curriculum %s: %s", cid, exc)
                results.append({"curriculum_id": cid, "status": "failed", "error": str(exc)})

        return {
            "curriculums": len(ids),
            "chapters_updated": sum(r.get("chapters_updated", 0) for r in results),
            "chapters_matched": sum(r.get("chapters_matched", 0) for r in results),
            "results": results,
        }
