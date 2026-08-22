"""
Lesson Intelligence Service — Phase 0 + Phase 1.

Phase 0: Data Assembly + Capacity Computation
  Reads from 5 ERP tables, computes capacity. Zero LLM cost.

Phase 1: Macro Plan Generation
  Distributes chapters across teaching weeks. Zero LLM cost.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text

from app.db.mariadb import SessionLocal

logger = logging.getLogger(__name__)

# ─── Output Table Names (match Laravel migrations) ──────────────────────────
TBL_LESSON_PLANS = "lms_intelligence_lesson_plans"
TBL_PLAN_PERIODS = "lms_lesson_plan_periods"
TBL_PLAN_CONCEPTS = "lms_lesson_plan_concepts"

# ─── Weekday Mappings ────────────────────────────────────────────────────────
# Timetable uses: M=Monday, T=Tuesday, W=Wednesday, H=Thursday, F=Friday, S=Saturday
WEEKDAY_TO_PY = {"M": 0, "T": 1, "W": 2, "H": 3, "F": 4, "S": 5}
PY_TO_WEEKDAY = {v: k for k, v in WEEKDAY_TO_PY.items()}
WEEKDAY_LABELS = {
    "M": "Monday", "T": "Tuesday", "W": "Wednesday",
    "H": "Thursday", "F": "Friday", "S": "Saturday",
}

# Default period duration when data is missing
DEFAULT_PERIOD_DURATION_MIN = 40

# All schools share curriculum content from institute 1 (the master content institute)
MASTER_CONTENT_INSTITUTE_ID = 341

def map_to_master_content_ids(db, school_standard_id: int, school_subject_id: int) -> tuple[int, int]:
    """
    Translates a school-specific standard and subject ID into the Master Institute (1)
    equivalent by matching their normalized names. This handles broken cross-institute
    links in older database architectures.
    """
    def normalize_std(name: str) -> str:
        if not name: return ""
        return str(name).lower().replace('cbse-', '').replace('gseb-', '').strip()

    def normalize_sub(name: str) -> str:
        if not name: return ""
        n = str(name).lower().strip()
        n = n.replace('(orals)', '').strip()
        
        aliases = {
            'maths': 'mathematics',
            'math': 'mathematics',
            'mathematics basic': 'mathematics',
            'e.v.s': 'environmental studies',
            'evs': 'environmental studies',
            'social science': 'social sciences',
            'sst': 'social sciences',
            'sci': 'science',
            'sci.': 'science',
            'hindi': 'hindi-a',
            'eng': 'english',
            'g.k': 'general',
            'g.k.': 'general',
            'general knowledge': 'general',
            'computer': 'it & computer',
            'computer science': 'it & computer',
            'physics': 'physical science',
            'p.e': 'health and physical education',
            'p.e.': 'health and physical education',
            'pt': 'health and physical education',
            'mass p.t.': 'health and physical education'
        }
        return aliases.get(n, n)

    # 1. Fetch original names
    std_row = db.execute(
        text("SELECT name FROM standard WHERE id = :id"), {"id": school_standard_id}
    ).fetchone()
    sub_row = db.execute(
        text("SELECT subject_name FROM subject WHERE id = :id"), {"id": school_subject_id}
    ).fetchone()

    if not std_row or not sub_row:
        return school_standard_id, school_subject_id

    school_std_name = normalize_std(std_row[0])
    school_sub_name = normalize_sub(sub_row[0])

    # 2. Fetch master names
    master_stds = db.execute(
        text("SELECT id, name FROM standard WHERE sub_institute_id = :inst"),
        {"inst": MASTER_CONTENT_INSTITUTE_ID}
    ).fetchall()
    master_subs = db.execute(
        text("SELECT id, subject_name FROM subject WHERE sub_institute_id = :inst"),
        {"inst": MASTER_CONTENT_INSTITUTE_ID}
    ).fetchall()

    # 3. Match
    mapped_std = next((s[0] for s in master_stds if normalize_std(s[1]) == school_std_name), school_standard_id)
    mapped_sub = next((s[0] for s in master_subs if normalize_sub(s[1]) == school_sub_name), school_subject_id)

    return mapped_std, mapped_sub


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 0A: Data Assembly — Read from 5 ERP tables
# ─────────────────────────────────────────────────────────────────────────────

def get_terms(
    db, sub_institute_id: int, syear: int
) -> list[dict[str, Any]]:
    """Fetch term/semester dates from academic_year table."""
    rows = db.execute(
        text("""
            SELECT term_id, title, start_date, end_date,
                   post_start_date, post_end_date, sort_order
            FROM academic_year
            WHERE sub_institute_id = :inst AND syear = :year
            ORDER BY sort_order
        """),
        {"inst": sub_institute_id, "year": syear},
    ).mappings().fetchall()

    terms = []
    for r in rows:
        terms.append({
            "term_id": r["term_id"],
            "title": r["title"],
            "start_date": r["start_date"],
            "end_date": r["end_date"],
            "post_start_date": r.get("post_start_date"),
            "post_end_date": r.get("post_end_date"),
        })
    return terms


def get_weekly_schedule(
    db,
    sub_institute_id: int,
    standard_id: int,
    subject_id: int,
    syear: int,
    division_id: int | None = None,
) -> dict[str, Any]:
    """
    Fetch weekly timetable for a specific standard + subject.

    Returns:
        {
            "schedule": {"M": [{"period_id": 5, "slot": "P2", "sort_order": 2, ...}], ...},
            "periods_per_week": 10,
            "teacher_id": 157,
            "has_saturday": True/False,
            "period_details": [...]   # raw rows for period-duration computation
        }
    """
    params: dict[str, Any] = {
        "inst": sub_institute_id,
        "std": standard_id,
        "sub": subject_id,
        "year": syear,
    }

    division_clause = ""
    if division_id is not None:
        division_clause = "AND t.division_id = :div"
        params["div"] = division_id

    rows = db.execute(
        text(f"""
            SELECT t.week_day, t.period_id, t.teacher_id, t.division_id,
                   p.short_name AS period_slot, p.sort_order,
                   p.start_time, p.end_time, p.length
            FROM timetable t
            JOIN period p ON t.period_id = p.id
            WHERE t.sub_institute_id = :inst
              AND t.standard_id = :std
              AND t.subject_id = :sub
              AND t.syear = :year
              {division_clause}
            ORDER BY FIELD(t.week_day, 'M','T','W','H','F','S'), p.sort_order
        """),
        params,
    ).mappings().fetchall()

    if not rows:
        return {
            "schedule": {},
            "periods_per_week": 0,
            "teacher_id": None,
            "has_saturday": False,
            "period_details": [],
        }

    schedule: dict[str, list[dict]] = defaultdict(list)
    teacher_id = rows[0]["teacher_id"]  # primary teacher

    for r in rows:
        schedule[r["week_day"]].append({
            "period_id": r["period_id"],
            "slot": r["period_slot"],
            "sort_order": r["sort_order"],
            "start_time": str(r["start_time"]) if r["start_time"] else None,
            "end_time": str(r["end_time"]) if r["end_time"] else None,
            "length": int(r["length"]) if r["length"] else 0,
            "teacher_id": r["teacher_id"],
        })

    return {
        "schedule": dict(schedule),
        "periods_per_week": len(rows),
        "teacher_id": teacher_id,
        "has_saturday": "S" in schedule,
        "period_details": [dict(r) for r in rows],
    }


def get_period_duration(db, sub_institute_id: int, syear: int) -> int:
    """
    Compute average period duration in minutes for a school.

    Fallback chain:
      1. period.length (if > 0)
      2. TIMESTAMPDIFF(start_time, end_time) (if start_time != 00:00:00)
      3. Default 40 minutes
    """
    row = db.execute(
        text("""
            SELECT AVG(
                CASE
                    WHEN p.length > 0 THEN CAST(p.length AS UNSIGNED)
                    WHEN p.start_time != '00:00:00' AND p.end_time != '00:00:00'
                         THEN TIMESTAMPDIFF(MINUTE, p.start_time, p.end_time)
                    ELSE :default_dur
                END
            ) AS avg_duration
            FROM timetable t
            JOIN period p ON t.period_id = p.id
            WHERE t.sub_institute_id = :inst AND t.syear = :year
        """),
        {"inst": sub_institute_id, "year": syear, "default_dur": DEFAULT_PERIOD_DURATION_MIN},
    ).fetchone()

    if row and row[0]:
        return max(int(round(float(row[0]))), 20)  # minimum 20 min sanity check
    return DEFAULT_PERIOD_DURATION_MIN


def get_holidays(
    db, sub_institute_id: int, syear: int
) -> list[dict[str, Any]]:
    """Fetch all holidays and vacations for a school year.
    Ignores generic auto-generated 'HOLIDAY' entries on Saturdays to allow timetable classes.
    """
    rows = db.execute(
        text("""
            SELECT school_date, title, event_type
            FROM calendar_events
            WHERE sub_institute_id = :inst
              AND syear = :year
              AND event_type IN ('holiday', 'vacation')
            ORDER BY school_date
        """),
        {"inst": sub_institute_id, "year": syear},
    ).mappings().fetchall()

    holidays = []
    for r in rows:
        d = r["school_date"]
        title = r["title"] or ""
        # Ignore generic "HOLIDAY" entries on Saturdays
        if isinstance(d, date) and d.weekday() == 5 and title.strip().upper() == "HOLIDAY":
            continue
            
        holidays.append({
            "date": d,
            "title": title,
            "type": r["event_type"],
        })

    return holidays


def get_exam_dates(
    db,
    sub_institute_id: int,
    standard_id: int,
    subject_id: int,
    syear: int,
) -> list[dict[str, Any]]:
    """Fetch exam dates for a specific standard + subject."""
    rows = db.execute(
        text("""
            SELECT exam_date, title, points, term_id
            FROM result_create_exam
            WHERE sub_institute_id = :inst
              AND standard_id = :std
              AND subject_id = :sub
              AND syear = :year
              AND exam_date IS NOT NULL
            ORDER BY exam_date
        """),
        {
            "inst": sub_institute_id,
            "std": standard_id,
            "sub": subject_id,
            "year": syear,
        },
    ).mappings().fetchall()

    return [
        {
            "date": r["exam_date"],
            "title": r["title"],
            "marks": r["points"],
            "term_id": r["term_id"],
        }
        for r in rows
    ]


def get_concept_time_requirements(
    db, extraction_id: int
) -> list[dict[str, Any]]:
    """
    Get estimated mastery minutes for all concepts linked to an extraction.

    Joins lms_concept with chapter_master to get chapter-level grouping.
    """
    rows = db.execute(
        text("""
            SELECT c.id AS concept_id, c.name AS concept_name, c.description,
                   c.estimated_mastery_minutes, c.mastery_threshold,
                   cm.id AS chapter_id, cm.chapter_name, cm.sort_order
            FROM lms_concept c
            JOIN chapter_master cm ON c.chapter_id = cm.id
            WHERE c.extraction_id = :eid
            ORDER BY cm.sort_order, c.id
        """),
        {"eid": extraction_id},
    ).mappings().fetchall()

    return [dict(r) for r in rows]


def get_curriculum(
    db, standard_id: int, subject_id: int
) -> dict[str, Any] | None:
    """
    Fetch the curriculum record for a standard + subject.

    Always reads from MASTER_CONTENT_INSTITUTE_ID (institute 341).
    Returns curriculum metadata including objective, board, framework.
    """
    row = db.execute(
        text("""
            SELECT id, curriculum_name, objective, board, framework,
                   total_marks, internal_marks, curriculum_alignment,
                   holistic_curriculum, model_integration
            FROM lms_curriculum
            WHERE sub_institute_id = :inst
              AND standard_id = :std
              AND subject_id = :sub
            ORDER BY id DESC
            LIMIT 1
        """),
        {"inst": MASTER_CONTENT_INSTITUTE_ID, "std": standard_id, "sub": subject_id},
    ).mappings().fetchone()

    return dict(row) if row else None


def get_units(
    db, curriculum_id: int
) -> list[dict[str, Any]]:
    """
    Fetch all units for a curriculum.

    Units group chapters into thematic blocks (e.g., "Chemical Substances",
    "World of Living"). Returns unit name, number, planned periods, and
    the list of chapters within each unit.
    """
    rows = db.execute(
        text("""
            SELECT id, unit_number, name, planned_periods, unit_chapters
            FROM lms_units
            WHERE curriculum_id = :cid
            ORDER BY unit_number
        """),
        {"cid": curriculum_id},
    ).mappings().fetchall()

    import json
    result = []
    for r in rows:
        d = dict(r)
        # Parse unit_chapters JSON string if present
        if d.get("unit_chapters") and isinstance(d["unit_chapters"], str):
            try:
                d["unit_chapters"] = json.loads(d["unit_chapters"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


def get_learning_outcomes(
    db, standard_id: int, subject_id: int
) -> list[dict[str, Any]]:
    """
    Fetch learning outcomes for a standard + subject.

    These define *what students should learn* — competency goals (CG)
    and individual competencies (C) extracted from the NCF/NCERT curriculum.
    Used by the micro planner to align each lesson with official learning outcomes.
    """
    rows = db.execute(
        text("""
            SELECT id, code, type, description, chapter_id, parent_id
            FROM lms_learning_outcomes
            WHERE standard_id = :std AND subject_id = :sub
            ORDER BY id
        """),
        {"std": standard_id, "sub": subject_id},
    ).mappings().fetchall()

    return [dict(r) for r in rows]


def get_semantic_intelligence(
    db, standard_id: int, subject_id: int
) -> list[dict[str, Any]]:
    """
    Fetch semantic intelligence data per chapter.

    This is the richest data source — contains chapter-level AI-generated:
      - learning_objectives: what teachers should teach
      - learning_outcomes: what students should learn
      - ability: action verbs + descriptions for each concept
      - knowledge: factual/conceptual/procedural knowledge items
      - blooms_level: Bloom's taxonomy coverage per concept
      - dok: Depth of Knowledge levels
      - pedagogy: recommended teaching strategies
      - misconceptions: common student misconceptions
      - real_world_applications: real-life connections
      - prerequisites: what students must already know
      - assessment_blueprint: suggested assessment types and questions
    """
    rows = db.execute(
        text("""
            SELECT id, chapter_id, chapter_number,
                   learning_objective, learning_objectives, learning_outcomes,
                   ability, knowledge, skill, competency,
                   blooms_level, dok, pedagogy,
                   misconceptions, real_world_applications,
                   prerequisites, assessment_blueprint,
                   total_topics
            FROM semantic_intelligence
            WHERE standard_id = :std AND subject_id = :sub
            ORDER BY chapter_number
        """),
        {"std": standard_id, "sub": subject_id},
    ).mappings().fetchall()

    import json
    result = []
    for r in rows:
        d = dict(r)
        # Parse JSON string columns
        json_cols = [
            'learning_objectives', 'learning_outcomes', 'ability', 'knowledge',
            'skill', 'competency', 'blooms_level', 'dok', 'pedagogy',
            'misconceptions', 'real_world_applications', 'prerequisites',
            'assessment_blueprint',
        ]
        for col in json_cols:
            if d.get(col) and isinstance(d[col], str):
                try:
                    d[col] = json.loads(d[col])
                except (json.JSONDecodeError, TypeError):
                    pass
        result.append(d)
    return result


def assemble_school_data(
    sub_institute_id: int,
    standard_id: int,
    subject_id: int,
    syear: int,
    division_id: int | None = None,
) -> dict[str, Any]:
    """
    Master function: reads ALL scheduling data from existing ERP tables.
    NO frontend input needed.

    Scheduling data (terms, timetable, holidays, exams) comes from the
    actual school's sub_institute_id.

    Curriculum content data (chapters, concepts, units, learning outcomes,
    semantic intelligence) ALWAYS comes from MASTER_CONTENT_INSTITUTE_ID (341)
    because all schools share the same curriculum from institute 1.

    Returns a complete school-data dict ready for capacity computation.
    """
    # Content always comes from institute 1
    content_inst_id = MASTER_CONTENT_INSTITUTE_ID

    with SessionLocal() as db:
        # ── SCHEDULING DATA (from actual school) ──────────────────────

        # 1. Term/Semester dates
        terms = get_terms(db, sub_institute_id, syear)
        if not terms:
            logger.warning(
                "No terms found for inst=%s year=%s", sub_institute_id, syear
            )

        # 2. Weekly timetable
        weekly = get_weekly_schedule(
            db, sub_institute_id, standard_id, subject_id, syear, division_id
        )

        # 3. Period duration (school-wide average)
        period_duration = get_period_duration(db, sub_institute_id, syear)

        # 4. Holidays & vacations
        holidays = get_holidays(db, sub_institute_id, syear)

        # 5. Exam dates for this subject
        exams = get_exam_dates(
            db, sub_institute_id, standard_id, subject_id, syear
        )

        # ── CURRICULUM CONTENT (always from institute 1) ──────────────
        mapped_std, mapped_sub = map_to_master_content_ids(db, standard_id, subject_id)

        # 6. Curriculum metadata
        curriculum = get_curriculum(db, mapped_std, mapped_sub)

        # 7. Units (grouped chapters)
        units = []
        if curriculum:
            units = get_units(db, curriculum["id"])

        # 8. Learning outcomes (what students learn)
        learning_outcomes = get_learning_outcomes(db, mapped_std, mapped_sub)

        # 9. Semantic intelligence (teacher objectives, abilities, etc.)
        semantic_intel = get_semantic_intelligence(db, mapped_std, mapped_sub)

        # 10. Find matching extraction_id for concept-time data
        #     Always from institute 1 content
        extraction_row = db.execute(
            text("""
                SELECT id FROM document_extractions
                WHERE sub_institute_id = :inst
                  AND standard_id = :std
                  AND subject_id = :sub
                LIMIT 1
            """),
            {"inst": content_inst_id, "std": mapped_std, "sub": mapped_sub},
        ).fetchone()

        concepts = []
        if extraction_row:
            concepts = get_concept_time_requirements(db, extraction_row[0])

    return {
        "sub_institute_id": sub_institute_id,
        "standard_id": standard_id,
        "subject_id": subject_id,
        "syear": syear,
        "division_id": division_id,
        "content_institute_id": content_inst_id,
        "terms": terms,
        "weekly_schedule": weekly["schedule"],
        "periods_per_week": weekly["periods_per_week"],
        "teacher_id": weekly["teacher_id"],
        "has_saturday": weekly["has_saturday"],
        "period_duration_min": period_duration,
        "holidays": holidays,
        "exam_dates": exams,
        "concepts": concepts,
        "total_concept_minutes": sum(
            c.get("estimated_mastery_minutes", 0) for c in concepts
        ),
        # ── NEW: Enriched curriculum content ──
        "curriculum": curriculum,
        "units": units,
        "learning_outcomes": learning_outcomes,
        "semantic_intelligence": semantic_intel,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 0B: Capacity Computation — Pure Python math, Zero LLM
# ─────────────────────────────────────────────────────────────────────────────

def _count_teaching_days_per_weekday(
    start_date: date,
    end_date: date,
    holiday_set: set[date],
    exam_set: set[date],
    has_saturday: bool,
) -> dict[str, int]:
    """
    Walk day-by-day from start to end, counting available teaching days
    per weekday code (M, T, W, H, F, S).

    Excludes: Sundays, holidays, exam days, and Saturdays if school has no Saturday.
    """
    day_counts: dict[str, int] = {k: 0 for k in WEEKDAY_TO_PY}
    current = start_date

    while current <= end_date:
        py_wd = current.weekday()  # 0=Mon … 6=Sun

        # Skip Sundays always
        if py_wd == 6:
            current += timedelta(days=1)
            continue

        code = PY_TO_WEEKDAY.get(py_wd)
        if not code:
            current += timedelta(days=1)
            continue

        # Skip Saturday if school doesn't have Saturday classes
        if code == "S" and not has_saturday:
            current += timedelta(days=1)
            continue

        # Skip holidays and exam days
        if current not in holiday_set and current not in exam_set:
            day_counts[code] += 1

        current += timedelta(days=1)

    return day_counts


def compute_capacity(school_data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Compute teaching capacity per term.

    For each term, calculates:
      - Teaching days per weekday
      - Total available periods (based on weekly schedule)
      - Total teaching minutes
      - Required minutes (from concept mastery times)
      - Buffer % and status
    """
    terms = school_data.get("terms", [])
    if not terms:
        return []

    schedule = school_data.get("weekly_schedule", {})
    period_duration = school_data.get("period_duration_min", DEFAULT_PERIOD_DURATION_MIN)
    has_saturday = school_data.get("has_saturday", False)

    # Build holiday and exam date sets
    holiday_set: set[date] = set()
    for h in school_data.get("holidays", []):
        d = h.get("date")
        if isinstance(d, date):
            holiday_set.add(d)

    exam_set: set[date] = set()
    for e in school_data.get("exam_dates", []):
        d = e.get("date")
        if isinstance(d, date):
            exam_set.add(d)

    total_required = school_data.get("total_concept_minutes", 0)

    results = []
    for term in terms:
        start = term.get("start_date")
        end = term.get("end_date")

        if not isinstance(start, date) or not isinstance(end, date):
            logger.warning("Skipping term %s: invalid dates", term.get("title"))
            continue

        if end <= start:
            logger.warning("Skipping term %s: end <= start", term.get("title"))
            continue

        # Count holidays and exams in this term
        holidays_in_term = sum(
            1 for d in holiday_set if start <= d <= end
        )
        exams_in_term = sum(
            1 for d in exam_set if start <= d <= end
        )

        # Count teaching days per weekday
        day_counts = _count_teaching_days_per_weekday(
            start, end, holiday_set, exam_set, has_saturday
        )

        # Calculate total available periods
        # For each weekday that has timetable slots, multiply by teaching days
        total_periods = 0
        for day_code, period_list in schedule.items():
            total_periods += day_counts.get(day_code, 0) * len(period_list)

        total_minutes = total_periods * period_duration

        # Calculate teaching weeks (for reference)
        total_raw_days = (end - start).days + 1
        days_per_week = 6 if has_saturday else 5
        teaching_weeks = round(
            sum(day_counts.values()) / days_per_week, 1
        ) if days_per_week > 0 else 0

        # Buffer computation
        # Spread required_minutes proportionally across terms if multiple
        if len(terms) > 1:
            # Proportional: this term gets its share based on duration fraction
            total_term_days = sum(
                (t["end_date"] - t["start_date"]).days
                for t in terms
                if isinstance(t.get("start_date"), date) and isinstance(t.get("end_date"), date)
            )
            if total_term_days > 0:
                term_fraction = (end - start).days / total_term_days
            else:
                term_fraction = 1 / len(terms)
            term_required = int(total_required * term_fraction)
        else:
            term_required = total_required

        buffer_minutes = total_minutes - term_required
        buffer_pct = round(
            (buffer_minutes / total_minutes * 100), 1
        ) if total_minutes > 0 else 0

        if buffer_pct > 15:
            status = "COMFORTABLE"
        elif buffer_pct > 5:
            status = "GOOD"
        elif buffer_pct > 0:
            status = "TIGHT"
        else:
            status = "OVERLOADED"

        results.append({
            "term_id": term.get("term_id"),
            "term_title": term.get("title"),
            "term_start": start.isoformat() if isinstance(start, date) else None,
            "term_end": end.isoformat() if isinstance(end, date) else None,
            "total_raw_days": total_raw_days,
            "teaching_weeks": teaching_weeks,
            "teaching_days_by_weekday": {
                WEEKDAY_LABELS.get(k, k): v
                for k, v in day_counts.items() if v > 0
            },
            "holidays_in_term": holidays_in_term,
            "exam_days_in_term": exams_in_term,
            "total_teaching_periods": total_periods,
            "period_duration_min": period_duration,
            "total_teaching_minutes": total_minutes,
            "total_teaching_hours": round(total_minutes / 60, 1),
            "required_minutes": term_required,
            "buffer_minutes": buffer_minutes,
            "buffer_percent": buffer_pct,
            "status": status,
        })

    return results


def get_capacity_analysis(
    sub_institute_id: int,
    standard_id: int,
    subject_id: int,
    syear: int,
    division_id: int | None = None,
) -> dict[str, Any]:
    """
    Full Phase 0 pipeline: assemble data + compute capacity.

    Returns a complete analysis dict ready for API response.
    """
    logger.info(
        "Running capacity analysis: inst=%s std=%s sub=%s year=%s",
        sub_institute_id, standard_id, subject_id, syear,
    )

    school_data = assemble_school_data(
        sub_institute_id, standard_id, subject_id, syear, division_id
    )

    capacity = compute_capacity(school_data)

    # Calculate grand totals
    grand_periods = sum(t["total_teaching_periods"] for t in capacity)
    grand_minutes = sum(t["total_teaching_minutes"] for t in capacity)
    grand_required = school_data["total_concept_minutes"]
    grand_buffer = grand_minutes - grand_required
    grand_buffer_pct = round(
        (grand_buffer / grand_minutes * 100), 1
    ) if grand_minutes > 0 else 0

    # Chapter breakdown
    chapters: dict[str, dict] = {}
    for c in school_data["concepts"]:
        ch_name = c.get("chapter_name", "Unknown")
        ch_id = c.get("chapter_id")
        if ch_name not in chapters:
            chapters[ch_name] = {
                "chapter_id": ch_id,
                "chapter_name": ch_name,
                "sort_order": c.get("sort_order"),
                "concept_count": 0,
                "total_mastery_minutes": 0,
                "concepts": [],
            }
        chapters[ch_name]["concept_count"] += 1
        chapters[ch_name]["total_mastery_minutes"] += c.get("estimated_mastery_minutes", 0)
        chapters[ch_name]["concepts"].append({
            "concept_id": c["concept_id"],
            "name": c["concept_name"],
            "mastery_minutes": c.get("estimated_mastery_minutes", 0),
            "mastery_threshold": c.get("mastery_threshold"),
        })

    chapter_list = sorted(chapters.values(), key=lambda x: x.get("sort_order") or 0)

    return {
        "school_data": {
            "sub_institute_id": sub_institute_id,
            "standard_id": standard_id,
            "subject_id": subject_id,
            "syear": syear,
            "division_id": division_id,
            "teacher_id": school_data["teacher_id"],
            "periods_per_week": school_data["periods_per_week"],
            "period_duration_min": school_data["period_duration_min"],
            "has_saturday": school_data["has_saturday"],
            "weekly_schedule": {
                WEEKDAY_LABELS.get(k, k): [
                    s["slot"] for s in slots
                ]
                for k, slots in school_data["weekly_schedule"].items()
            } if school_data["weekly_schedule"] else {},
        },
        "terms": capacity,
        "grand_totals": {
            "total_periods": grand_periods,
            "total_teaching_minutes": grand_minutes,
            "total_teaching_hours": round(grand_minutes / 60, 1),
            "total_required_minutes": grand_required,
            "buffer_minutes": grand_buffer,
            "buffer_percent": grand_buffer_pct,
            "status": (
                "COMFORTABLE" if grand_buffer_pct > 15 else
                "GOOD" if grand_buffer_pct > 5 else
                "TIGHT" if grand_buffer_pct > 0 else
                "OVERLOADED"
            ),
        },
        "content_breakdown": {
            "total_chapters": len(chapter_list),
            "total_concepts": len(school_data["concepts"]),
            "total_concept_minutes": grand_required,
            "chapters": chapter_list,
        },
        "calendar_data": {
            "holidays": [
                {"date": h["date"].isoformat() if isinstance(h["date"], date) else h["date"],
                 "title": h["title"], "type": h["type"]}
                for h in school_data["holidays"]
            ],
            "exams": [
                {"date": e["date"].isoformat() if isinstance(e["date"], date) else e["date"],
                 "title": e["title"], "marks": e["marks"]}
                for e in school_data["exam_dates"]
            ],
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1: Macro Plan — Distribute chapters across weeks. Zero LLM.
# ─────────────────────────────────────────────────────────────────────────────

def _get_chapters_for_subject(
    db, sub_institute_id: int, standard_id: int, subject_id: int
) -> list[dict[str, Any]]:
    """
    Get chapters with their concept time requirements.

    Aggregates concept minutes per chapter from lms_concept.
    Falls back to equal distribution if no concept data.
    """
    rows = db.execute(
        text("""
            SELECT cm.id AS chapter_id, cm.chapter_name, cm.sort_order,
                   cm.extraction_id, cm.unit_id,
                   COALESCE(SUM(c.estimated_mastery_minutes), 0) AS total_mastery_minutes,
                   COUNT(c.id) AS concept_count
            FROM chapter_master cm
            LEFT JOIN lms_concept c ON c.chapter_id = cm.id
            WHERE cm.sub_institute_id = :inst
              AND cm.standard_id = :std
              AND cm.subject_id = :sub
              AND cm.availability = 1
            GROUP BY cm.id, cm.chapter_name, cm.sort_order, cm.extraction_id, cm.unit_id
            ORDER BY cm.sort_order
        """),
        {"inst": sub_institute_id, "std": standard_id, "sub": subject_id},
    ).mappings().fetchall()

    return [dict(r) for r in rows]


def _build_teaching_calendar(
    term_start: date,
    term_end: date,
    schedule: dict[str, list[dict]],
    holiday_set: set[date],
    exam_set: set[date],
    has_saturday: bool,
) -> list[dict[str, Any]]:
    """
    Build a day-by-day teaching calendar showing every available period slot.

    Returns a list of dicts, each representing one teaching slot:
    {
        "date": date,
        "week_day": "M",
        "week_number": 1,
        "period_id": 5,
        "period_slot": "P2",
        "sort_order": 2,
    }
    """
    slots = []
    current = term_start
    week_num = 1
    prev_monday = term_start - timedelta(days=term_start.weekday())

    while current <= term_end:
        py_wd = current.weekday()

        # Track week number (resets every Monday)
        this_monday = current - timedelta(days=current.weekday())
        if this_monday > prev_monday:
            week_num += 1
            prev_monday = this_monday

        # Skip Sundays
        if py_wd == 6:
            current += timedelta(days=1)
            continue

        code = PY_TO_WEEKDAY.get(py_wd)
        if not code:
            current += timedelta(days=1)
            continue

        # Skip Saturday if no Saturday classes
        if code == "S" and not has_saturday:
            current += timedelta(days=1)
            continue

        # Skip holidays and exam days
        if current in holiday_set or current in exam_set:
            current += timedelta(days=1)
            continue

        # Add all period slots for this weekday
        day_periods = schedule.get(code, [])
        for p in day_periods:
            slots.append({
                "date": current,
                "week_day": code,
                "week_number": week_num,
                "period_id": p["period_id"],
                "period_slot": p["slot"],
                "sort_order": p.get("sort_order", 0),
                "teacher_id": p.get("teacher_id"),
            })

        current += timedelta(days=1)

    return slots


def _distribute_chapters_to_slots(
    chapters: list[dict],
    total_slots: int,
    period_duration: int,
) -> list[dict[str, Any]]:
    """
    Distribute chapters across available period slots proportionally.

    Strategy:
      1. If concepts have estimated_mastery_minutes -> proportional distribution
      2. If concept_count > 0 -> proportional distribution by concept count
      3. If no concept data -> equal distribution across chapters
      4. Minimum 1 period per chapter

    Returns chapters with allocated `periods` count.
    """
    if not chapters or total_slots <= 0:
        return []

    total_minutes = sum(ch.get("total_mastery_minutes", 0) for ch in chapters)
    total_concepts = sum(ch.get("concept_count", 0) for ch in chapters)

    result = []
    
    # Reserve 5 periods for Assessment Preparation at the end of the term
    buffer_periods = min(5, total_slots // 10)
    teaching_slots = total_slots - buffer_periods

    if total_minutes > 0:
        # Proportional distribution based on mastery minutes
        for ch in chapters:
            ch_minutes = ch.get("total_mastery_minutes", 0) or period_duration
            fraction = ch_minutes / total_minutes
            raw_periods = fraction * teaching_slots
            periods = max(1, round(raw_periods))
            result.append({
                **ch,
                "allocated_periods": periods,
                "estimated_minutes": ch_minutes,
                "periods_by_mastery": raw_periods,
            })
            
    elif total_concepts > 0:
        # Proportional distribution based on concept count
        for ch in chapters:
            ch_concepts = ch.get("concept_count", 0) or 1
            fraction = ch_concepts / total_concepts
            raw_periods = fraction * teaching_slots
            periods = max(1, round(raw_periods))
            result.append({
                **ch,
                "allocated_periods": periods,
                "estimated_minutes": ch_concepts * period_duration,
                "periods_by_mastery": raw_periods,
            })

    else:
        # Equal distribution (no concept data)
        per_chapter = max(1, teaching_slots // len(chapters))
        remainder = teaching_slots - (per_chapter * len(chapters))

        for i, ch in enumerate(chapters):
            extra = 1 if i < remainder else 0
            result.append({
                **ch,
                "allocated_periods": per_chapter + extra,
                "estimated_minutes": 0,
                "periods_by_mastery": 0,
            })

    # Adjust to fit exact teaching slots count
    allocated = sum(r["allocated_periods"] for r in result)
    diff = teaching_slots - allocated
    if diff != 0 and result:
        # Add/remove from the largest chapter
        result.sort(key=lambda x: x["allocated_periods"], reverse=True)
        result[0]["allocated_periods"] = max(1, result[0]["allocated_periods"] + diff)
        result.sort(key=lambda x: x.get("sort_order") or 0)
        
    # Inject Assessment Preparation block
    if buffer_periods > 0:
        result.append({
            "chapter_id": -1,
            "chapter_name": "Assessment Preparation & Revision",
            "sort_order": 9999,
            "allocated_periods": buffer_periods,
            "concept_count": 0,
            "estimated_minutes": buffer_periods * period_duration,
            "periods_by_mastery": buffer_periods
        })

    # The actual remaining unused buffer periods (should be 0 because we used teaching_slots perfectly)
    total_teaching = sum(r["allocated_periods"] for r in result)
    remaining_slots = total_slots - total_teaching

    return result, remaining_slots


def _assign_chapters_to_weeks(
    chapters_with_periods: list[dict],
    teaching_calendar: list[dict],
    buffer_periods: int,
) -> dict[str, Any]:
    """
    Assign chapter periods to specific weeks in the teaching calendar.

    Walks through the calendar chronologically and fills slots with
    chapter content in sort_order.

    Returns macro_plan_json structure.
    """
    if not chapters_with_periods or not teaching_calendar:
        return {"weeks": [], "summary": {}}

    # Group calendar slots by week number
    weeks: dict[int, list[dict]] = defaultdict(list)
    for slot in teaching_calendar:
        weeks[slot["week_number"]].append(slot)

    sorted_weeks = sorted(weeks.keys())

    # Walk through chapters and assign to weeks
    slot_index = 0
    total_slots = len(teaching_calendar)
    chapter_schedule = []

    for ch in chapters_with_periods:
        ch_periods = ch["allocated_periods"]
        ch_start_slot = slot_index
        ch_end_slot = min(slot_index + ch_periods - 1, total_slots - 1)

        if ch_start_slot >= total_slots:
            break

        start_date = teaching_calendar[ch_start_slot]["date"]
        end_date = teaching_calendar[min(ch_end_slot, total_slots - 1)]["date"]
        start_week = teaching_calendar[ch_start_slot]["week_number"]
        end_week = teaching_calendar[min(ch_end_slot, total_slots - 1)]["week_number"]

        chapter_schedule.append({
            "chapter_id": ch["chapter_id"],
            "chapter_name": ch["chapter_name"],
            "sort_order": ch.get("sort_order"),
            "allocated_periods": ch_periods,
            "concept_count": ch.get("concept_count", 0),
            "estimated_minutes": ch.get("estimated_minutes", 0),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "start_week": start_week,
            "end_week": end_week,
            "weeks_span": end_week - start_week + 1,
        })

        slot_index += ch_periods

    # Build week-level summary
    week_plan = []
    slot_idx = 0
    for ch_info in chapter_schedule:
        for _ in range(ch_info["allocated_periods"]):
            if slot_idx < total_slots:
                cal_slot = teaching_calendar[slot_idx]
                wk = cal_slot["week_number"]
                # Find or create week entry
                existing = next((w for w in week_plan if w["week_number"] == wk), None)
                if not existing:
                    # Get all dates in this week
                    week_dates = [s["date"] for s in weeks.get(wk, [])]
                    existing = {
                        "week_number": wk,
                        "start_date": min(week_dates).isoformat() if week_dates else None,
                        "end_date": max(week_dates).isoformat() if week_dates else None,
                        "total_slots": len(weeks.get(wk, [])),
                        "chapters": [],
                    }
                    week_plan.append(existing)
                # Add chapter reference if not already there
                if not any(c["chapter_id"] == ch_info["chapter_id"] for c in existing["chapters"]):
                    existing["chapters"].append({
                        "chapter_id": ch_info["chapter_id"],
                        "chapter_name": ch_info["chapter_name"],
                        "periods_this_week": 0,
                    })
                # Increment periods for this chapter in this week
                for c in existing["chapters"]:
                    if c["chapter_id"] == ch_info["chapter_id"]:
                        c["periods_this_week"] += 1
                        break
                slot_idx += 1

    # Add buffer slots at the end
    remaining_slots = total_slots - slot_idx
    if remaining_slots > 0:
        for i in range(remaining_slots):
            if slot_idx + i < total_slots:
                cal_slot = teaching_calendar[slot_idx + i]
                wk = cal_slot["week_number"]
                existing = next((w for w in week_plan if w["week_number"] == wk), None)
                if not existing:
                    week_dates = [s["date"] for s in weeks.get(wk, [])]
                    existing = {
                        "week_number": wk,
                        "start_date": min(week_dates).isoformat() if week_dates else None,
                        "end_date": max(week_dates).isoformat() if week_dates else None,
                        "total_slots": len(weeks.get(wk, [])),
                        "chapters": [],
                    }
                    week_plan.append(existing)
                if not any(c.get("is_buffer") for c in existing["chapters"]):
                    existing["chapters"].append({
                        "chapter_id": None,
                        "chapter_name": "Buffer / Revision",
                        "periods_this_week": 0,
                        "is_buffer": True,
                    })
                for c in existing["chapters"]:
                    if c.get("is_buffer"):
                        c["periods_this_week"] += 1
                        break

    return {
        "chapter_schedule": chapter_schedule,
        "week_plan": week_plan,
        "summary": {
            "total_teaching_weeks": len(week_plan),
            "total_chapters": len(chapter_schedule),
            "total_teaching_periods": sum(ch["allocated_periods"] for ch in chapter_schedule),
            "buffer_periods": buffer_periods,
            "total_slots_used": total_slots,
        },
    }


def generate_macro_plan(
    sub_institute_id: int,
    standard_id: int,
    subject_id: int,
    syear: int,
    division_id: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    Phase 1: Generate macro plan — distribute chapters across teaching weeks.

    Creates/updates lms_intelligence_lesson_plans row per term with:
      - Capacity analysis numbers
      - macro_plan_json (chapter-to-week mapping)

    LLM Cost: $0 (pure Python math)
    """
    logger.info(
        "Generating macro plan: inst=%s std=%s sub=%s year=%s",
        sub_institute_id, standard_id, subject_id, syear,
    )

    with SessionLocal() as db:
        # 1. Assemble school data (Phase 0 reuse)
        school_data = assemble_school_data(
            sub_institute_id, standard_id, subject_id, syear, division_id
        )

        std_name = db.execute(text("SELECT name FROM standard WHERE id = :id"), {"id": standard_id}).scalar() or f"Std {standard_id}"
        sub_name = db.execute(text("SELECT subject_name FROM subject WHERE id = :id"), {"id": subject_id}).scalar() or f"Sub {subject_id}"

        if not school_data["terms"]:
            raise ValueError(
                f"No terms found for inst={sub_institute_id} year={syear}"
            )

        if school_data["periods_per_week"] == 0:
            raise ValueError(
                f"No timetable data for inst={sub_institute_id} "
                f"std={standard_id} sub={subject_id} year={syear}"
            )

        # 2. Get chapters (always from master content institute 1)
        mapped_std, mapped_sub = map_to_master_content_ids(db, standard_id, subject_id)
        chapters = _get_chapters_for_subject(
            db, MASTER_CONTENT_INSTITUTE_ID, mapped_std, mapped_sub
        )

        if not chapters:
            raise ValueError(
                f"No chapters found for inst={sub_institute_id} "
                f"std={standard_id} sub={subject_id}"
            )

        # 3. Build holiday and exam sets
        holiday_set: set[date] = set()
        for h in school_data["holidays"]:
            d = h.get("date")
            if isinstance(d, date):
                holiday_set.add(d)

        exam_set: set[date] = set()
        for e in school_data["exam_dates"]:
            d = e.get("date")
            if isinstance(d, date):
                exam_set.add(d)

        # 4. Compute capacity
        capacity = compute_capacity(school_data)

        # 5. Process each term
        plan_results = []
        now = datetime.now()

        for term_idx, term in enumerate(school_data["terms"]):
            term_start = term["start_date"]
            term_end = term["end_date"]
            term_id = term["term_id"]

            if not isinstance(term_start, date) or not isinstance(term_end, date):
                continue
            if term_end <= term_start:
                continue

            term_capacity = capacity[term_idx] if term_idx < len(capacity) else None

            # Build teaching calendar for this term
            calendar = _build_teaching_calendar(
                term_start, term_end,
                school_data["weekly_schedule"],
                holiday_set, exam_set,
                school_data["has_saturday"],
            )

            total_slots = len(calendar)
            if total_slots == 0:
                continue

            # Distribute chapters proportionally
            # For multi-term: split chapters across terms
            if len(school_data["terms"]) > 1:
                total_term_days = sum(
                    (t["end_date"] - t["start_date"]).days
                    for t in school_data["terms"]
                    if isinstance(t.get("start_date"), date) and isinstance(t.get("end_date"), date)
                )
                term_fraction = (
                    (term_end - term_start).days / total_term_days
                    if total_term_days > 0 else 0.5
                )
                ch_start = int(len(chapters) * sum(
                    (school_data["terms"][i]["end_date"] - school_data["terms"][i]["start_date"]).days / total_term_days
                    for i in range(term_idx)
                    if isinstance(school_data["terms"][i].get("start_date"), date)
                ))
                ch_end = int(len(chapters) * sum(
                    (school_data["terms"][i]["end_date"] - school_data["terms"][i]["start_date"]).days / total_term_days
                    for i in range(term_idx + 1)
                    if isinstance(school_data["terms"][i].get("start_date"), date)
                ))
                term_chapters = chapters[ch_start:ch_end] if ch_end > ch_start else chapters
            else:
                term_chapters = chapters

            # Allocate periods
            chapters_with_periods, buffer_periods = _distribute_chapters_to_slots(
                term_chapters, total_slots, school_data["period_duration_min"]
            )

            # Assign to weeks
            macro_plan = _assign_chapters_to_weeks(
                chapters_with_periods, calendar, buffer_periods
            )

            # 6. Compute plan title
            term_title = term.get('title', f'Term {term_idx + 1}')
            plan_title = f"{std_name} - {sub_name} - {term_title} ({syear})"

            # 7. Check for existing plan
            existing = db.execute(
                text(f"""
                    SELECT id, generation_status FROM {TBL_LESSON_PLANS}
                    WHERE sub_institute_id = :inst AND syear = :year
                      AND term_id = :tid AND standard_id = :std
                      AND subject_id = :sub
                      AND (division_id = :div OR (division_id IS NULL AND :div IS NULL))
                """),
                {
                    "inst": sub_institute_id, "year": syear, "tid": term_id,
                    "std": standard_id, "sub": subject_id, "div": division_id,
                },
            ).fetchone()

            if existing and not force:
                plan_results.append({
                    "term_id": term_id,
                    "term_title": term.get("title"),
                    "status": "already_exists",
                    "plan_id": existing[0],
                    "generation_status": existing[1],
                })
                continue

            # 8. Insert or update plan
            plan_data = {
                "inst": sub_institute_id,
                "year": syear,
                "tid": term_id,
                "std": standard_id,
                "sub": subject_id,
                "div": division_id,
                "title": plan_title,
                "term_start": term_start,
                "term_end": term_end,
                "teaching_days": term_capacity["total_teaching_periods"] if term_capacity else total_slots,
                "total_periods": total_slots,
                "ppw": school_data["periods_per_week"],
                "pdm": school_data["period_duration_min"],
                "ttm": total_slots * school_data["period_duration_min"],
                "trm": sum(ch.get("estimated_minutes", 0) for ch in chapters_with_periods),
                "buf": term_capacity["buffer_percent"] if term_capacity else 0,
                "hol": term_capacity["holidays_in_term"] if term_capacity else 0,
                "exam": term_capacity["exam_days_in_term"] if term_capacity else 0,
                "now": now,
            }

            import json
            macro_json = json.dumps(macro_plan, default=str)

            if existing:
                db.execute(
                    text(f"""
                        UPDATE {TBL_LESSON_PLANS}
                        SET plan_title = :title,
                            term_start_date = :term_start, term_end_date = :term_end,
                            total_teaching_days = :teaching_days,
                            total_periods = :total_periods,
                            periods_per_week = :ppw, period_duration_min = :pdm,
                            total_teaching_min = :ttm, total_required_min = :trm,
                            buffer_percent = :buf,
                            holidays_count = :hol, exam_days_count = :exam,
                            macro_plan_json = :macro_json,
                            generation_status = 'completed',
                            generation_progress = 100,
                            generation_error = NULL,
                            generated_at = :now,
                            generated_by = 'macro_plan_v1',
                            updated_at = :now
                        WHERE id = :plan_id
                    """),
                    {**plan_data, "macro_json": macro_json, "plan_id": existing[0]},
                )
                plan_id = existing[0]
            else:
                db.execute(
                    text(f"""
                        INSERT INTO {TBL_LESSON_PLANS}
                        (sub_institute_id, syear, term_id, standard_id, subject_id,
                         division_id, plan_title, term_start_date, term_end_date,
                         total_teaching_days, total_periods, periods_per_week,
                         period_duration_min, total_teaching_min, total_required_min,
                         buffer_percent, holidays_count, exam_days_count,
                         macro_plan_json, generation_status, generation_progress,
                         generated_at, generated_by, created_at, updated_at)
                        VALUES
                        (:inst, :year, :tid, :std, :sub,
                         :div, :title, :term_start, :term_end,
                         :teaching_days, :total_periods, :ppw,
                         :pdm, :ttm, :trm,
                         :buf, :hol, :exam,
                         :macro_json, 'completed', 100,
                         :now, 'macro_plan_v1', :now, :now)
                    """),
                    {**plan_data, "macro_json": macro_json},
                )
                plan_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()

            db.commit()

            plan_results.append({
                "term_id": term_id,
                "term_title": term.get("title"),
                "status": "generated",
                "plan_id": plan_id,
                "macro_plan": macro_plan,
                "capacity": term_capacity,
            })

    return {
        "status": "success",
        "sub_institute_id": sub_institute_id,
        "standard_id": standard_id,
        "subject_id": subject_id,
        "syear": syear,
        "total_chapters": len(chapters),
        "terms_processed": len(plan_results),
        "plans": plan_results,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2: Meso Plan — Allocate concepts to periods. Zero LLM.
# ─────────────────────────────────────────────────────────────────────────────

def generate_meso_plan(plan_id: int, manual_teacher_assignments: dict[int, list[int]] | None = None) -> dict[str, Any]:
    """
    Phase 2: Generate meso plan — map concepts to period slots.

    Reads the macro plan generated in Phase 1, rebuilds the exact calendar,
    and walks through the concepts for each chapter, splitting their
    estimated_mastery_minutes into exact period slots (e.g., 40 mins).

    Creates rows in `lms_lesson_plan_periods` and `lms_lesson_plan_concepts`.
    Ensures every period is strictly linked to a concept (no NULLs).

    LLM Cost: $0 (pure Python math)
    """
    logger.info("Generating meso plan for plan_id=%s", plan_id)
    import json

    with SessionLocal() as db:
        # 1. Fetch the macro plan
        plan_row = db.execute(
            text(f"SELECT * FROM {TBL_LESSON_PLANS} WHERE id = :pid"),
            {"pid": plan_id}
        ).mappings().fetchone()

        if not plan_row:
            raise ValueError(f"Plan ID {plan_id} not found.")

        macro_plan = plan_row.get("macro_plan_json")
        if isinstance(macro_plan, str):
            try:
                macro_plan = json.loads(macro_plan)
            except json.JSONDecodeError:
                macro_plan = None

        if not macro_plan or "chapter_schedule" not in macro_plan:
            raise ValueError(f"Plan ID {plan_id} lacks macro_plan_json. Run Phase 1 first.")

        sub_inst = plan_row["sub_institute_id"]
        std_id = plan_row["standard_id"]
        sub_id = plan_row["subject_id"]
        syear = plan_row["syear"]
        div_id = plan_row["division_id"]
        term_start = plan_row["term_start_date"]
        term_end = plan_row["term_end_date"]
        period_duration = plan_row["period_duration_min"] or 40

        # 2. Re-assemble calendar data to get exact slots
        school_data = assemble_school_data(sub_inst, std_id, sub_id, syear, div_id)
        holiday_set = {h["date"] for h in school_data["holidays"] if isinstance(h["date"], date)}
        exam_set = {e["date"] for e in school_data["exam_dates"] if isinstance(e["date"], date)}

        calendar = _build_teaching_calendar(
            term_start, term_end,
            school_data["weekly_schedule"],
            holiday_set, exam_set,
            school_data["has_saturday"],
        )

        if not calendar:
            raise ValueError("No available teaching slots found in the calendar.")

        # 3. Clean up existing Phase 2 data for a fresh generation
        db.execute(
            text(f"DELETE FROM {TBL_PLAN_PERIODS} WHERE lms_intelligence_lesson_plans_id = :pid"),
            {"pid": plan_id}
        )
        db.commit()

        # 4. Fetch all concepts for this subject (always from institute 1)
        mapped_std, mapped_sub = map_to_master_content_ids(db, std_id, sub_id)
        concepts_rows = db.execute(
            text("""
                SELECT c.id, c.name, c.estimated_mastery_minutes, cm.id as chapter_id, cm.chapter_name
                FROM lms_concept c
                JOIN chapter_master cm ON c.chapter_id = cm.id
                WHERE cm.sub_institute_id = :inst
                  AND cm.standard_id = :std
                  AND cm.subject_id = :sub
                  AND cm.availability = 1
                ORDER BY cm.sort_order, c.id
            """),
            {"inst": MASTER_CONTENT_INSTITUTE_ID, "std": mapped_std, "sub": mapped_sub}
        ).mappings().fetchall()

        chapter_concepts = defaultdict(list)
        for r in concepts_rows:
            chapter_concepts[r["chapter_id"]].append(dict(r))

        # 5. Distribute concepts into slots (Parallel Teacher Allocation)
        for s in calendar:
            if not s.get("teacher_id"):
                s["teacher_id"] = school_data["teacher_id"]
                
        unique_tids = list(set(s["teacher_id"] for s in calendar))
        teacher_calendars = {tid: [s for s in calendar if s["teacher_id"] == tid] for tid in unique_tids}
        teacher_assignments = {tid: [] for tid in unique_tids}
        
        # Greedily assign chapters to teachers based on remaining slot capacity, UNLESS manual is provided
        if manual_teacher_assignments:
            for ch in macro_plan["chapter_schedule"]:
                assigned = False
                for tid, chapter_ids in manual_teacher_assignments.items():
                    if ch["chapter_id"] in chapter_ids:
                        if tid in teacher_assignments:
                            teacher_assignments[tid].append(ch)
                            assigned = True
                            break
                if not assigned:
                    # Fallback to auto if they didn't map a chapter
                    best_teacher = max(unique_tids, key=lambda t: len(teacher_calendars[t]) - sum(c["allocated_periods"] for c in teacher_assignments[t]))
                    teacher_assignments[best_teacher].append(ch)
        else:
            for ch in macro_plan["chapter_schedule"]:
                best_teacher = max(unique_tids, key=lambda t: len(teacher_calendars[t]) - sum(c["allocated_periods"] for c in teacher_assignments[t]))
                teacher_assignments[best_teacher].append(ch)

        periods_inserted = 0
        concepts_inserted = 0
        now = datetime.now()

        for tid in unique_tids:
            t_calendar = teacher_calendars[tid]
            t_chapters = teacher_assignments[tid]
            
            slot_idx = 0
            continuous_teaching_count = 0
            
            for ch_schedule in t_chapters:
                ch_id = ch_schedule["chapter_id"]
                ch_name = ch_schedule["chapter_name"]
                alloc_periods = ch_schedule["allocated_periods"]

                if ch_id is None or ch_id < 0:
                    ch_slots = t_calendar[slot_idx : slot_idx + alloc_periods]
                    slot_idx += alloc_periods
                    for slot in ch_slots:
                        db.execute(
                            text(f"""
                                INSERT INTO {TBL_PLAN_PERIODS}
                                (lms_intelligence_lesson_plans_id, scheduled_date, week_day, week_number,
                                 period_id, period_slot, teacher_id, chapter_id, chapter_name, period_type, planned_duration_min,
                                 created_at, updated_at)
                                VALUES (:pid, :date, :wd, :wn, :p_id, :ps, :tid, :chid, :chname, 'buffer', :dur, :now, :now)
                            """),
                            {
                                "pid": plan_id, "date": slot["date"], "wd": slot["week_day"],
                                "wn": slot["week_number"], "p_id": slot["period_id"],
                                "ps": slot["period_slot"], "tid": tid,
                                "chid": ch_id, "chname": ch_name,
                                "dur": period_duration, "now": now,
                            }
                        )
                        periods_inserted += 1
                    continue

                c_list = chapter_concepts.get(ch_id, [])
                ch_slots = t_calendar[slot_idx : slot_idx + alloc_periods]
                slot_idx += alloc_periods

                if not ch_slots:
                    continue

                concept_idx = 0
                current_concept_remaining_min = 0
                if c_list:
                    current_concept_remaining_min = c_list[0]["estimated_mastery_minutes"] or period_duration

                slot_i = 0
                while slot_i < len(ch_slots):
                    slot = ch_slots[slot_i]
                    current_period_duration = period_duration
                    combined_slot_name = slot["period_slot"]

                    if continuous_teaching_count >= 5:
                        period_type = "revision"
                        primary_concept_name = "Doubt Clearing & Review"
                        primary_concept_id = None
                        period_concepts = []
                        continuous_teaching_count = 0
                        if concept_idx > 0 and c_list:
                            last_c = c_list[concept_idx - 1]
                            primary_concept_id = last_c["id"]
                            primary_concept_name = f"Review: {last_c['name']}"
                    else:
                        period_type = "teaching"
                        primary_concept_id = None
                        primary_concept_name = None
                        period_concepts = []
                        slot_remaining_min = current_period_duration
                        continuous_teaching_count += 1

                        while slot_remaining_min > 0 and concept_idx < len(c_list):
                            c = c_list[concept_idx]
                            used_min = min(slot_remaining_min, current_concept_remaining_min)

                            if primary_concept_id is None:
                                primary_concept_id = c["id"]
                                primary_concept_name = c["name"]

                            total_min = c["estimated_mastery_minutes"] or period_duration
                            coverage_pct = int((used_min / total_min) * 100) if total_min > 0 else 100

                            period_concepts.append({
                                "concept_id": c["id"],
                                "concept_name": c["name"],
                                "is_primary": (primary_concept_id == c["id"]),
                                "coverage_percent": coverage_pct,
                            })

                            slot_remaining_min -= used_min
                            current_concept_remaining_min -= used_min

                            if current_concept_remaining_min <= 0:
                                concept_idx += 1
                                if concept_idx < len(c_list):
                                    current_concept_remaining_min = c_list[concept_idx]["estimated_mastery_minutes"] or period_duration

                        if not period_concepts and period_type != "revision":
                            period_type = "revision"
                            if c_list:
                                last_c = c_list[-1]
                                primary_concept_id = last_c["id"]
                                primary_concept_name = last_c["name"]
                                period_concepts.append({
                                    "concept_id": last_c["id"],
                                    "concept_name": last_c["name"],
                                    "is_primary": True,
                                    "coverage_percent": 100,
                                })

                    db.execute(
                        text(f"""
                            INSERT INTO {TBL_PLAN_PERIODS}
                            (lms_intelligence_lesson_plans_id, scheduled_date, week_day, week_number,
                             period_id, period_slot, teacher_id, chapter_id, chapter_name,
                             primary_concept_id, primary_concept_name, period_type, planned_duration_min,
                             status, created_at, updated_at)
                            VALUES (:pid, :date, :wd, :wn, :p_id, :ps, :tid, :chid, :chname,
                             :pcid, :pcname, :ptype, :dur, 'not_started', :now, :now)
                        """),
                        {
                            "pid": plan_id, "date": slot["date"], "wd": slot["week_day"],
                            "wn": slot["week_number"], "p_id": slot["period_id"],
                            "ps": combined_slot_name, "tid": tid,
                            "chid": ch_id, "chname": ch_name,
                            "pcid": primary_concept_id, "pcname": primary_concept_name,
                            "ptype": period_type, "dur": current_period_duration, "now": now,
                        }
                    )
                    
                    period_row_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()
                    periods_inserted += 1
                    slot_i += 1

                    for pc in period_concepts:
                        db.execute(
                            text(f"""
                                INSERT INTO {TBL_PLAN_CONCEPTS}
                                (lms_lesson_plan_periods_id, concept_id, concept_name,
                                 is_primary, coverage_percent, created_at)
                                VALUES (:per_id, :cid, :cname, :pri, :cov, :now)
                            """),
                            {
                                "per_id": period_row_id, "cid": pc["concept_id"],
                                "cname": pc["concept_name"], "pri": pc["is_primary"],
                                "cov": pc["coverage_percent"], "now": now,
                            }
                        )
                        concepts_inserted += 1

        db.commit()

        return {
            "status": "success",
            "plan_id": plan_id,
            "periods_created": periods_inserted,
            "concept_mappings_created": concepts_inserted,
        }
