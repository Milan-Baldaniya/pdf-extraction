"""
Lesson Intelligence API Router — Phase 0 + Phase 1 Endpoints.

Phase 0: Capacity analysis (pure Python math)
Phase 1: Macro plan generation (chapter-to-week distribution)
All computation is zero LLM cost.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.jobs import accepted, llm_semaphore, submit as submit_job
from app.lesson_intelligence.service import (
    assemble_school_data,
    compute_capacity,
    get_capacity_analysis,
    generate_macro_plan,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Lesson Intelligence"])


# ─── Request / Response Schemas ──────────────────────────────────────────────

class CapacityRequest(BaseModel):
    """Request body for capacity analysis."""
    sub_institute_id: int
    standard_id: int
    subject_id: int
    syear: int
    division_id: Optional[int] = None


class MacroPlanRequest(BaseModel):
    """Request body for macro plan generation."""
    sub_institute_id: int
    standard_id: int
    subject_id: int
    syear: int
    division_id: Optional[int] = None
    force: bool = False


# ─── Phase 0 Endpoints ──────────────────────────────────────────────────────

@router.post("/capacity")
async def capacity_analysis(req: CapacityRequest):
    """
    Phase 0: Compute teaching capacity analysis.

    Reads from existing ERP tables (timetable, period, academic_year,
    calendar_events, result_create_exam) and computes:
    - Total available teaching periods per term
    - Total teaching minutes vs required content minutes
    - Buffer analysis (COMFORTABLE / GOOD / TIGHT / OVERLOADED)
    - Chapter-by-chapter time breakdown

    **LLM Cost: $0** (pure Python math)
    """
    try:
        result = get_capacity_analysis(
            sub_institute_id=req.sub_institute_id,
            standard_id=req.standard_id,
            subject_id=req.subject_id,
            syear=req.syear,
            division_id=req.division_id,
        )
        return {"status": "success", "data": result}

    except Exception as exc:
        logger.exception("Capacity analysis failed")
        raise HTTPException(500, f"Capacity analysis failed: {exc}") from exc


@router.get("/capacity/{sub_institute_id}/{standard_id}/{subject_id}")
async def capacity_analysis_get(
    sub_institute_id: int,
    standard_id: int,
    subject_id: int,
    syear: int = Query(..., description="Academic year (e.g. 2026)"),
    division_id: Optional[int] = Query(None, description="Division ID (A/B/C)"),
):
    """
    Phase 0: GET version of capacity analysis.

    Same as POST but via URL params for easy browser/frontend use.
    """
    try:
        result = get_capacity_analysis(
            sub_institute_id=sub_institute_id,
            standard_id=standard_id,
            subject_id=subject_id,
            syear=syear,
            division_id=division_id,
        )
        return {"status": "success", "data": result}

    except Exception as exc:
        logger.exception("Capacity analysis failed")
        raise HTTPException(500, f"Capacity analysis failed: {exc}") from exc


@router.get("/school-data/{sub_institute_id}/{standard_id}/{subject_id}")
async def get_school_data(
    sub_institute_id: int,
    standard_id: int,
    subject_id: int,
    syear: int = Query(..., description="Academic year (e.g. 2026)"),
    division_id: Optional[int] = Query(None),
):
    """
    Raw school data assembly — returns all ERP data for debugging/inspection.

    Shows exactly what data the engine reads from timetable, period,
    academic_year, calendar_events, and result_create_exam tables.
    """
    try:
        data = assemble_school_data(
            sub_institute_id=sub_institute_id,
            standard_id=standard_id,
            subject_id=subject_id,
            syear=syear,
            division_id=division_id,
        )

        serialized = _deep_serialize(data)
        return {"status": "success", "data": serialized}

    except Exception as exc:
        logger.exception("School data assembly failed")
        raise HTTPException(500, f"School data assembly failed: {exc}") from exc


# ─── Phase 1 Endpoints ──────────────────────────────────────────────────────

@router.post("/macro-plan")
async def create_macro_plan(req: MacroPlanRequest):
    """
    Phase 1: Generate macro plan — distribute chapters across teaching weeks.

    Creates `lms_intelligence_lesson_plans` row(s) per term with:
    - Capacity analysis numbers (teaching days, periods, buffer %)
    - macro_plan_json: week-by-week chapter schedule
    - Chapter-level period allocation (proportional to mastery minutes)

    Set force=true to regenerate existing plans.

    **LLM Cost: $0** (pure Python math)
    """
    try:
        result = generate_macro_plan(
            sub_institute_id=req.sub_institute_id,
            standard_id=req.standard_id,
            subject_id=req.subject_id,
            syear=req.syear,
            division_id=req.division_id,
            force=req.force,
        )
        return result

    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("Macro plan generation failed")
        raise HTTPException(500, f"Macro plan generation failed: {exc}") from exc


@router.get("/macro-plan/{sub_institute_id}/{standard_id}/{subject_id}")
async def get_macro_plan(
    sub_institute_id: int,
    standard_id: int,
    subject_id: int,
    syear: int = Query(..., description="Academic year (e.g. 2026)"),
    division_id: Optional[int] = Query(None),
):
    """
    Phase 1: Retrieve existing macro plan(s) from the database.

    Returns the stored macro_plan_json and capacity analysis for each term.
    """
    from app.db.mariadb import SessionLocal
    from sqlalchemy import text
    from app.lesson_intelligence.service import TBL_LESSON_PLANS
    import json

    try:
        with SessionLocal() as db:
            params = {
                "inst": sub_institute_id, "std": standard_id,
                "sub": subject_id, "year": syear, "div": division_id,
            }
            rows = db.execute(
                text(f"""
                    SELECT * FROM {TBL_LESSON_PLANS}
                    WHERE sub_institute_id = :inst AND syear = :year
                      AND standard_id = :std AND subject_id = :sub
                      AND (division_id = :div OR (division_id IS NULL AND :div IS NULL))
                    ORDER BY term_id
                """),
                params,
            ).mappings().fetchall()

            if not rows:
                raise HTTPException(
                    404,
                    f"No macro plan found. Generate one first via POST /lesson-intelligence/macro-plan"
                )

            plans = []
            for r in rows:
                plan = dict(r)
                # Parse macro_plan_json
                if plan.get("macro_plan_json"):
                    try:
                        plan["macro_plan_json"] = json.loads(plan["macro_plan_json"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                plans.append(_deep_serialize(plan))

            return {"status": "success", "plans": plans}

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Get macro plan failed")
        raise HTTPException(500, f"Get macro plan failed: {exc}") from exc


@router.get("/calendar-events/{sub_institute_id}/{standard_id}/{subject_id}")
async def get_calendar_events(
    sub_institute_id: int,
    standard_id: int,
    subject_id: int,
    syear: int = Query(..., description="Academic year (e.g. 2026)"),
):
    """
    Fetch holidays and exam dates for the calendar view.
    """
    from app.db.mariadb import SessionLocal
    from app.lesson_intelligence.service import get_holidays, get_exam_dates

    try:
        with SessionLocal() as db:
            holidays = get_holidays(db, sub_institute_id, syear)
            exams = get_exam_dates(db, sub_institute_id, standard_id, subject_id, syear)
            
            # Serialize dates to string
            for h in holidays:
                if h.get("date"):
                    h["date"] = str(h["date"])
            for e in exams:
                if e.get("date"):
                    e["date"] = str(e["date"])

            return {
                "status": "success",
                "holidays": holidays,
                "exams": exams
            }
    except Exception as exc:
        logger.exception("Get calendar events failed")
        raise HTTPException(500, f"Get calendar events failed: {exc}") from exc


# ─── Phase 2 Endpoints ──────────────────────────────────────────────────────

class MesoPlanRequest(BaseModel):
    teacher_assignments: dict[int, list[int]] | None = None

@router.post("/meso-plan/{plan_id}")
async def create_meso_plan(plan_id: int, req: MesoPlanRequest | None = None):
    """
    Phase 2: Generate meso plan — allocate concepts into period slots.

    Reads the macro plan from Phase 1, fetches exactly matching concepts
    for each chapter, and maps them to physical period dates/slots.
    Splits long concepts across periods or combines short ones.

    Creates rows in `lms_lesson_plan_periods` and `lms_lesson_plan_concepts`.
    All periods are guaranteed to have a connected `concept_id`.
    Period durations will exactly match the timetable's period duration.

    **LLM Cost: $0** (pure Python math)
    """
    from app.lesson_intelligence.service import generate_meso_plan
    
    try:
        result = generate_meso_plan(plan_id=plan_id, manual_teacher_assignments=req.teacher_assignments if req else None)
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception(f"Meso plan generation failed for plan {plan_id}")
        raise HTTPException(500, f"Meso plan generation failed: {exc}") from exc


@router.get("/meso-plan/{plan_id}/teachers")
async def get_meso_plan_teachers(plan_id: int):
    """
    Returns the unique teachers in the calendar and the chapters in the macro plan
    so the UI can prompt the user to manually map them.
    """
    from app.db.mariadb import SessionLocal
    from sqlalchemy import text
    import json
    
    try:
        with SessionLocal() as db:
            plan_row = db.execute(
                text("""
                    SELECT sub_institute_id, syear, standard_id, subject_id, division_id, term_start_date, term_end_date, macro_plan_json
                    FROM lms_intelligence_lesson_plans 
                    WHERE id = :pid
                """),
                {"pid": plan_id}
            ).mappings().fetchone()
            
            if not plan_row:
                raise HTTPException(404, "Plan not found")
                
            from app.lesson_intelligence.service import assemble_school_data, _build_teaching_calendar
            
            school_data = assemble_school_data(
                plan_row["sub_institute_id"], plan_row["standard_id"], plan_row["subject_id"],
                plan_row["syear"], plan_row["division_id"]
            )
            
            calendar = _build_teaching_calendar(
                plan_row["term_start_date"], plan_row["term_end_date"],
                school_data["weekly_schedule"],
                set(h["date"] for h in school_data["holidays"]),
                set(e["date"] for e in school_data["exam_dates"]),
                school_data["has_saturday"],
            )
            
            for s in calendar:
                if not s.get("teacher_id"):
                    s["teacher_id"] = school_data["teacher_id"]
                    
            unique_tids = list(set(s["teacher_id"] for s in calendar))
            
            # Fetch teacher names
            teachers = []
            if unique_tids:
                format_strings = ','.join([f':t{i}' for i in range(len(unique_tids))])
                params = {f"t{i}": tid for i, tid in enumerate(unique_tids)}
                t_rows = db.execute(
                    text(f"SELECT id, CONCAT(first_name, ' ', last_name) as name FROM tbluser WHERE id IN ({format_strings})"),
                    params
                ).mappings().fetchall()
                teachers = [dict(r) for r in t_rows]
                
            macro_plan = plan_row["macro_plan_json"]
            if isinstance(macro_plan, str):
                macro_plan = json.loads(macro_plan)
                
            chapters = macro_plan.get("chapter_schedule", [])
            
            return {
                "status": "success",
                "teachers": teachers,
                "chapters": chapters
            }
            
    except Exception as exc:
        logger.exception("Failed to get teachers")
        raise HTTPException(500, f"Failed to get teachers: {exc}") from exc


@router.get("/meso-plan/{plan_id}/periods")
async def get_meso_plan_periods(plan_id: int):
    """
    Phase 2: Retrieve the generated lesson plan periods for a given plan.
    Returns the physical schedule mapped to chapters and concepts.
    """
    from app.db.mariadb import SessionLocal
    from sqlalchemy import text
    from app.lesson_intelligence.service import TBL_PLAN_PERIODS, TBL_PLAN_CONCEPTS
    import json

    try:
        with SessionLocal() as db:
            rows = db.execute(
                text(f"""
                    SELECT p.*, CONCAT(u.first_name, ' ', u.last_name) AS teacher_name,
                           TIME_FORMAT(pm.start_time, '%h:%i %p') AS start_time,
                           TIME_FORMAT(pm.end_time, '%h:%i %p') AS end_time
                    FROM {TBL_PLAN_PERIODS} p
                    LEFT JOIN tbluser u ON p.teacher_id = u.id
                    LEFT JOIN period pm ON p.period_id = pm.id
                    WHERE p.lms_intelligence_lesson_plans_id = :pid
                    ORDER BY p.scheduled_date, p.period_slot
                """),
                {"pid": plan_id}
            ).mappings().fetchall()

            if not rows:
                return {"status": "success", "periods": []}

            periods = []
            period_ids = []
            for r in rows:
                p = dict(r)
                if p.get("plan_json"):
                    try:
                        p["plan_json"] = json.loads(p["plan_json"])
                    except Exception:
                        pass
                if p.get("learning_objectives"):
                    try:
                        p["learning_objectives"] = json.loads(p["learning_objectives"])
                    except Exception:
                        pass
                p["concepts"] = []
                periods.append(p)
                period_ids.append(p["id"])

            # 2. Fetch linked concepts
            if period_ids:
                format_strings = ','.join(['%s'] * len(period_ids))
                # using text() with string interpolation for IN clause is tricky,
                # so we can execute directly or use simple bind params.
                # A safe way in sqlalchemy core:
                concept_rows = db.execute(
                    text(f"""
                        SELECT * FROM {TBL_PLAN_CONCEPTS}
                        WHERE lms_lesson_plan_periods_id IN ({','.join(map(str, period_ids))})
                        ORDER BY lms_lesson_plan_periods_id, id
                    """)
                ).mappings().fetchall()
                
                # group by period_id
                from collections import defaultdict
                concepts_by_period = defaultdict(list)
                for cr in concept_rows:
                    concepts_by_period[cr["lms_lesson_plan_periods_id"]].append(dict(cr))
                    
                for p in periods:
                    p["concepts"] = concepts_by_period.get(p["id"], [])

            return {"status": "success", "periods": _deep_serialize(periods)}
            
    except Exception as exc:
        logger.exception(f"Failed to fetch periods for plan {plan_id}")
        raise HTTPException(500, f"Failed to fetch periods: {exc}") from exc


# ─── Phase 3 Endpoints ──────────────────────────────────────────────────────

@router.post("/micro-plan/period/{period_id}")
async def create_micro_plan_for_period(period_id: int):
    """
    Phase 3: Generate micro plan for a single period using LLM.

    Reads the concepts assigned to this period and generates the minute-by-minute
    breakdown (warm-up, core teaching, activity, wrap-up).
    Updates `plan_json` and intelligence metadata in `lms_lesson_plan_periods`.

    **LLM Cost: ~$0.01 per period**
    """
    from app.lesson_intelligence.micro_planner import generate_micro_plan_for_period
    
    try:
        result = await generate_micro_plan_for_period(period_id)
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception(f"Micro plan generation failed for period {period_id}")
        raise HTTPException(500, f"Micro plan generation failed: {exc}") from exc


@router.post("/micro-plan/plan/{plan_id}/batch")
async def create_micro_plan_batch(plan_id: int, limit: int = 10):
    """
    Phase 3: Batch generate micro plans for up to `limit` periods that are not yet generated.
    """
    from app.db.mariadb import SessionLocal
    from sqlalchemy import text
    from app.lesson_intelligence.micro_planner import generate_micro_plan_for_period
    import asyncio
    
    try:
        with SessionLocal() as db:
            rows = db.execute(
                text("""
                    SELECT id FROM lms_lesson_plan_periods
                    WHERE lms_intelligence_lesson_plans_id = :pid
                      AND status = 'not_started'
                    ORDER BY scheduled_date, period_slot
                    LIMIT :limit
                """),
                {"pid": plan_id, "limit": limit}
            ).fetchall()
            
        period_ids = [r[0] for r in rows]
        if not period_ids:
            return {"status": "success", "message": "No pending periods found for this plan."}
            
        # Process sequentially to avoid rate limits
        results = []
        for pid in period_ids:
            res = await generate_micro_plan_for_period(pid)
            results.append(res)
            
        return {
            "status": "success",
            "processed": len(results),
            "results": results
        }
    except Exception as exc:
        logger.exception(f"Batch micro plan generation failed for plan {plan_id}")
        raise HTTPException(500, f"Batch micro plan generation failed: {exc}") from exc


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _deep_serialize(obj):
    """Recursively serialize date/time/Decimal objects for JSON response."""
    from datetime import date as date_type, time as time_type, datetime as dt_type
    from decimal import Decimal

    if isinstance(obj, dict):
        return {k: _deep_serialize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_deep_serialize(v) for v in obj]
    elif isinstance(obj, (date_type, dt_type)):
        return obj.isoformat()
    elif isinstance(obj, time_type):
        return obj.isoformat()
    elif isinstance(obj, Decimal):
        return float(obj)
    return obj

# ─── Dropdowns ───────────────────────────────────────────────────────────────

@router.get("/dropdowns")
async def get_dropdown_options():
    """
    Fetch all standards and subjects with their corresponding institute mapping
    so the frontend can display descriptive dropdowns.
    """
    from app.db.mariadb import SessionLocal
    from sqlalchemy import text
    try:
        with SessionLocal() as db:
            standards = db.execute(text("SELECT id, name, sub_institute_id FROM standard ORDER BY name")).mappings().fetchall()
            subjects = db.execute(text("SELECT id, subject_name, sub_institute_id FROM subject ORDER BY subject_name")).mappings().fetchall()
            institutes_rows = db.execute(text("SELECT Id as id, SchoolName as name FROM school_setup ORDER BY SchoolName")).mappings().fetchall()

            # Also fetch valid timetable combinations so frontend can filter
            timetable_combos = db.execute(text("""
                SELECT DISTINCT sub_institute_id, standard_id, subject_id, syear
                FROM timetable
                ORDER BY sub_institute_id, syear, standard_id
            """)).mappings().fetchall()

            return {
                "status": "success",
                "institutes": [dict(r) for r in institutes_rows],
                "standards": [dict(s) for s in standards],
                "subjects": [dict(s) for s in subjects],
                "timetable_combos": [dict(tc) for tc in timetable_combos],
            }
    except Exception as exc:
        logger.exception("Failed to fetch dropdowns")
        raise HTTPException(500, f"Failed to fetch dropdowns: {exc}") from exc


from typing import Optional
@router.get("/dropdowns/filter")
async def get_filtered_options(
    sub_institute_id: int = Query(..., description="Institute ID to filter by"),
    standard_id: Optional[int] = Query(None, description="Standard ID to filter by"),
    division_id: Optional[int] = Query(None, description="Division ID to filter by"),
    subject_id: Optional[int] = Query(None, description="Subject ID to filter by"),
):
    """
    Cascading dropdown filter: given an institute, returns only the
    standards, divisions, subjects, and years that have actual timetable data and valid periods.
    """
    from app.db.mariadb import SessionLocal
    from sqlalchemy import text
    try:
        with SessionLocal() as db:
            params = {"inst": sub_institute_id}
            
            # 1. Standards
            std_rows = db.execute(text("""
                SELECT DISTINCT t.standard_id, s.name
                FROM timetable t
                JOIN standard s ON t.standard_id = s.id
                JOIN period p ON t.period_id = p.id
                WHERE t.sub_institute_id = :inst
                ORDER BY s.name
            """), params).mappings().fetchall()

            # 2. Divisions (Filtered by standard if provided)
            div_query = """
                SELECT DISTINCT t.division_id, d.name
                FROM timetable t
                JOIN division d ON t.division_id = d.id
                JOIN period p ON t.period_id = p.id
                WHERE t.sub_institute_id = :inst
            """
            if standard_id:
                div_query += " AND t.standard_id = :std"
                params["std"] = standard_id
            div_query += " ORDER BY d.name"
            div_rows = db.execute(text(div_query), params).mappings().fetchall()

            # 3. Subjects (Filtered by standard and division if provided)
            sub_query = """
                SELECT DISTINCT t.subject_id, s.subject_name
                FROM timetable t
                JOIN subject s ON t.subject_id = s.id
                JOIN period p ON t.period_id = p.id
                WHERE t.sub_institute_id = :inst
            """
            if standard_id:
                sub_query += " AND t.standard_id = :std"
            if division_id:
                sub_query += " AND t.division_id = :div"
                params["div"] = division_id
            sub_query += " ORDER BY s.subject_name"
            sub_rows = db.execute(text(sub_query), params).mappings().fetchall()

            # 4. Years (Filtered by standard, division, subject if provided)
            year_query = """
                SELECT DISTINCT t.syear
                FROM timetable t
                JOIN period p ON t.period_id = p.id
                WHERE t.sub_institute_id = :inst
            """
            if standard_id:
                year_query += " AND t.standard_id = :std"
            if division_id:
                year_query += " AND t.division_id = :div"
            if subject_id:
                year_query += " AND t.subject_id = :sub"
                params["sub"] = subject_id
            year_query += " ORDER BY t.syear DESC"
            
            year_rows = db.execute(text(year_query), params).fetchall()

            return {
                "status": "success",
                "standards": [{"id": r["standard_id"], "name": r["name"]} for r in std_rows],
                "divisions": [{"id": r["division_id"], "name": r["name"]} for r in div_rows],
                "subjects": [{"id": r["subject_id"], "name": r["subject_name"]} for r in sub_rows],
                "years": [r[0] for r in year_rows],
            }
    except Exception as exc:
        logger.exception("Failed to fetch filtered dropdowns")
        raise HTTPException(500, f"Failed to fetch filtered options: {exc}") from exc


@router.get("/master-calendar/{sub_institute_id}/{standard_id}/{division_id}")
async def get_master_calendar(
    sub_institute_id: int,
    standard_id: int,
    division_id: int,
    syear: int = Query(...),
):
    """
    Fetch the master calendar for an entire division.
    It returns actual dates combined with the weekly timetable.
    If a subject has a generated Meso Plan, it includes the mapped chapter/concept!
    """
    from app.db.mariadb import SessionLocal
    from sqlalchemy import text
    from datetime import timedelta, date
    from app.lesson_intelligence.service import get_terms, get_holidays

    try:
        with SessionLocal() as db:
            # 1. Get Term Boundaries
            terms = get_terms(db, sub_institute_id, syear)
            if not terms:
                raise HTTPException(400, "No terms found for this year.")
            
            term_start_date = min(t["start_date"] for t in terms)
            term_end_date = max(t["end_date"] for t in terms)

            # 2. Get Holidays
            holidays = get_holidays(db, sub_institute_id, syear)
            holiday_dates = {h["date"] for h in holidays}

            # 3. Get Timetable for this specific division
            tt_rows = db.execute(text("""
                SELECT t.week_day, p.short_name AS slot, p.start_time, p.end_time,
                       s.id AS subject_id, s.subject_name,
                       u.id AS teacher_id, CONCAT(u.first_name, ' ', u.last_name) AS teacher_name
                FROM timetable t
                JOIN period p ON t.period_id = p.id
                JOIN subject s ON t.subject_id = s.id
                LEFT JOIN tbluser u ON t.teacher_id = u.id
                WHERE t.sub_institute_id = :inst
                  AND t.syear = :year
                  AND t.standard_id = :std
                  AND t.division_id = :div
                ORDER BY p.sort_order
            """), {
                "inst": sub_institute_id, "year": syear,
                "std": standard_id, "div": division_id
            }).mappings().fetchall()

            if not tt_rows:
                return {"status": "success", "periods": []}

            # Group by weekday: 'M', 'T', 'W', 'H', 'F', 'S'
            tt_by_day = { 'M': [], 'T': [], 'W': [], 'H': [], 'F': [], 'S': [], 'U': [] }
            for r in tt_rows:
                wd = r["week_day"].upper()
                if wd in tt_by_day:
                    tt_by_day[wd].append(dict(r))

            # 4. Get Generated Lesson Plans for this division
            plan_rows = db.execute(text("""
                SELECT lp.subject_id, p.scheduled_date, p.period_slot, p.chapter_name, p.primary_concept_name, p.plan_json
                FROM lms_intelligence_lesson_plans lp
                JOIN lms_lesson_plan_periods p ON p.lms_intelligence_lesson_plans_id = lp.id
                WHERE lp.sub_institute_id = :inst
                  AND lp.syear = :year
                  AND lp.standard_id = :std
                  AND lp.division_id = :div
            """), {
                "inst": sub_institute_id, "year": syear,
                "std": standard_id, "div": division_id
            }).mappings().fetchall()

            generated_map = {}
            for pr in plan_rows:
                # Use date object to ensure it hashes correctly
                sdate = pr["scheduled_date"]
                if isinstance(sdate, str):
                    sdate = date.fromisoformat(sdate)
                key = (pr["subject_id"], sdate, pr["period_slot"])
                generated_map[key] = {
                    "chapter_name": pr["chapter_name"],
                    "primary_concept_name": pr["primary_concept_name"],
                    "has_micro_plan": bool(pr["plan_json"])
                }

            # 5. Generate Dates
            calendar_periods = []
            
            day_map = {0: 'M', 1: 'T', 2: 'W', 3: 'H', 4: 'F', 5: 'S', 6: 'U'}
            
            curr = term_start_date
            while curr <= term_end_date:
                # Skip holidays
                if curr in holiday_dates:
                    curr += timedelta(days=1)
                    continue
                    
                wd_str = day_map[curr.weekday()]
                day_periods = tt_by_day.get(wd_str, [])
                
                for dp in day_periods:
                    sub_id = dp["subject_id"]
                    slot = dp["slot"]
                    
                    gen_info = generated_map.get((sub_id, curr, slot))
                    
                    # Convert timedelta back to string format HH:MM if it is a timedelta (start_time/end_time)
                    st = dp["start_time"]
                    et = dp["end_time"]
                    if hasattr(st, 'components'): # If it's a timedelta from sqlalchemy
                         st = f"{st.components.hours:02}:{st.components.minutes:02}"
                    elif st:
                         st = str(st)
                    
                    if hasattr(et, 'components'):
                         et = f"{et.components.hours:02}:{et.components.minutes:02}"
                    elif et:
                         et = str(et)
                         
                    # Clean up the trailing seconds if present (HH:MM:SS -> HH:MM)
                    if st and len(st.split(":")) == 3:
                        st = ":".join(st.split(":")[:2])
                    if et and len(et.split(":")) == 3:
                        et = ":".join(et.split(":")[:2])

                    calendar_periods.append({
                        "date": str(curr),
                        "week_day": wd_str,
                        "slot": slot,
                        "start_time": st,
                        "end_time": et,
                        "subject_id": sub_id,
                        "subject_name": dp["subject_name"],
                        "teacher_name": dp["teacher_name"],
                        "is_generated": gen_info is not None,
                        "chapter_name": gen_info["chapter_name"] if gen_info else None,
                        "primary_concept_name": gen_info["primary_concept_name"] if gen_info else None,
                        "has_micro_plan": gen_info["has_micro_plan"] if gen_info else False
                    })
                    
                curr += timedelta(days=1)

            return {
                "status": "success",
                "term_start_date": str(term_start_date),
                "term_end_date": str(term_end_date),
                "periods": calendar_periods
            }

    except Exception as exc:
        logger.exception("Failed to get master calendar")
        raise HTTPException(500, f"Failed to get master calendar: {exc}") from exc


# ─── Background job variants ────────────────────────────────────────────────
#
# Macro and meso planning are pure Python and return fast. Micro planning calls
# the LLM once per period, so a batch of them will outlive a proxy timeout.
# These queue the same work and hand back a job id to poll at
# /api/status/{job_id}.

@router.post("/jobs/micro-plan/period/{period_id}", status_code=202)
async def queue_micro_plan_for_period(period_id: int) -> dict:
    """Background form of ``/micro-plan/period/{period_id}``."""
    job_id = submit_job(
        f"Micro plan for period {period_id}",
        lambda: create_micro_plan_for_period(period_id),
        semaphore=llm_semaphore(),
    )
    return accepted(job_id)


@router.post("/jobs/micro-plan/plan/{plan_id}/batch", status_code=202)
async def queue_micro_plan_batch(plan_id: int, limit: int = 10) -> dict:
    """Background form of ``/micro-plan/plan/{plan_id}/batch``."""
    job_id = submit_job(
        f"Micro plan batch for plan {plan_id}",
        lambda: create_micro_plan_batch(plan_id, limit),
        semaphore=llm_semaphore(),
    )
    return accepted(job_id)
