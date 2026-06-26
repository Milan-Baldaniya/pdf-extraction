"""
Phase 3: Micro Planner

Uses LLM to generate detailed, minute-by-minute lesson plans for a single period slot.
"""

import json
import logging
from typing import Any

from sqlalchemy import text

from app.db.mariadb import SessionLocal
from app.semantic_intelligence.deepseek_client import async_call_deepseek
from app.lesson_intelligence.service import TBL_PLAN_PERIODS, TBL_PLAN_CONCEPTS

logger = logging.getLogger(__name__)

# System prompt defining the exact JSON schema and persona.
MICRO_PLAN_SYSTEM_PROMPT = """You are an expert curriculum designer and lesson planner.
Your goal is to design a detailed, engaging lesson plan for a single teaching period.
You will receive rich context including: concepts to teach, semantic intelligence data
(learning objectives, abilities, misconceptions, pedagogy strategies, real-world applications),
and official NCF/NCERT learning outcomes. Use ALL of this data to create a well-aligned,
pedagogically sound lesson plan.
You must strictly return a valid JSON object matching the requested schema. Do not include markdown formatting or explanations outside the JSON.

SCHEMA:
{
  "blooms_level": "string (e.g. Remember, Understand, Apply, Analyze, Evaluate, Create)",
  "dok_level": "integer (1 to 4)",
  "pedagogy_method": "string (Strictly map to 5E model)",
  "difficulty_level": "string (Easy, Medium, Hard)",
  "learning_objectives": ["string", "string"],
  "plan_json": {
    "engage": {
      "duration_min": "integer",
      "description": "string (Hook the students, explicitly link to Previous Period context if provided)"
    },
    "explore": {
      "duration_min": "integer",
      "activity_description": "string (Hands-on or conceptual exploration)"
    },
    "explain": {
      "duration_min": "integer",
      "strategy": "string (Core teaching, clarifying misconceptions)"
    },
    "elaborate": {
      "duration_min": "integer",
      "real_world_application": "string"
    },
    "evaluate": {
      "duration_min": "integer",
      "quick_assessment": "string"
    },
    "differentiation": {
      "remedial_strategy": "string (How to help struggling students)",
      "enrichment_activity": "string (Advanced task for fast learners)"
    },
    "formative_assessment": [
      {
        "question": "string (Multiple choice question)",
        "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
        "correct_answer": "string (Exact text of the correct option)"
      }
    ],
    "homework": "string"
  }
}
"""

async def generate_micro_plan_for_period(period_id: int) -> dict[str, Any]:
    """
    Phase 3: Generate detailed lesson content for a specific period.

    Enriches the LLM prompt with data from:
    - lms_concept (concept name + description)
    - semantic_intelligence (learning objectives, abilities, misconceptions,
      pedagogy strategies, real-world applications, prerequisites)
    - lms_learning_outcomes (official competency goals for the subject)
    """
    # 1. Fetch period, concept, semantic intelligence, and learning outcomes
    with SessionLocal() as db:
        period_row = db.execute(
            text(f"""
                SELECT p.*, lp.standard_id, lp.subject_id
                FROM {TBL_PLAN_PERIODS} p
                JOIN lms_intelligence_lesson_plans lp ON p.lms_intelligence_lesson_plans_id = lp.id
                WHERE p.id = :pid
            """),
            {"pid": period_id}
        ).mappings().fetchone()

        if not period_row:
            raise ValueError(f"Period ID {period_id} not found.")

        # Skip if already completed to save LLM cost
        if period_row["status"] == "completed":
            logger.info("Period %s is already completed. Skipping.", period_id)
            return {"status": "skipped", "reason": "Already completed"}

        duration = period_row["planned_duration_min"]
        chapter_id = period_row.get("chapter_id")

        concepts_rows = db.execute(
            text(f"""
                SELECT c.concept_name, c.coverage_percent, lc.description
                FROM {TBL_PLAN_CONCEPTS} c
                LEFT JOIN lms_concept lc ON c.concept_id = lc.id
                WHERE c.lms_lesson_plan_periods_id = :pid
            """),
            {"pid": period_id}
        ).mappings().fetchall()

        if not concepts_rows:
            return {"status": "skipped", "reason": "No concepts mapped to this period."}

        # Fetch semantic intelligence for this chapter
        semantic_row = None
        if chapter_id:
            semantic_row = db.execute(
                text("""
                    SELECT learning_objective, learning_objectives, learning_outcomes,
                           ability, knowledge, misconceptions, pedagogy,
                           real_world_applications, prerequisites, blooms_level, dok
                    FROM semantic_intelligence
                    WHERE chapter_id = :chid
                    LIMIT 1
                """),
                {"chid": chapter_id}
            ).mappings().fetchone()

        # Fetch official learning outcomes for this subject
        lo_rows = db.execute(
            text("""
                SELECT code, type, description
                FROM lms_learning_outcomes
                WHERE standard_id = :std AND subject_id = :sub
                ORDER BY id
            """),
            {"std": period_row["standard_id"], "sub": period_row["subject_id"]}
        ).mappings().fetchall()

    # 2. Build the enriched LLM prompt
    concepts_text = ""
    for cr in concepts_rows:
        concepts_text += f"- Concept: {cr['concept_name']} (Coverage in this period: {cr['coverage_percent']}%)\n"
        if cr['description']:
            concepts_text += f"  Description: {cr['description']}\n"

    # Build semantic intelligence context
    semantic_context = ""
    if semantic_row:
        si = dict(semantic_row)

        # Parse JSON fields
        for col in ['learning_objectives', 'learning_outcomes', 'ability',
                     'knowledge', 'misconceptions', 'pedagogy',
                     'real_world_applications', 'prerequisites', 'blooms_level', 'dok']:
            if si.get(col) and isinstance(si[col], str):
                try:
                    si[col] = json.loads(si[col])
                except (json.JSONDecodeError, TypeError):
                    pass

        # Learning objectives (for teacher — what to teach)
        if si.get("learning_objectives") and isinstance(si["learning_objectives"], list):
            objectives = [o.get("objective", "") for o in si["learning_objectives"][:5]]
            if objectives:
                semantic_context += "\nTeacher's Learning Objectives (from semantic intelligence):\n"
                for obj in objectives:
                    semantic_context += f"  • {obj}\n"

        # Abilities (action verbs for students)
        if si.get("ability") and isinstance(si["ability"], list):
            abilities = [a.get("ability", "") for a in si["ability"][:4]]
            if abilities:
                semantic_context += "\nTarget Student Abilities:\n"
                for a in abilities:
                    semantic_context += f"  • {a}\n"

        # Pedagogy strategies
        if si.get("pedagogy") and isinstance(si["pedagogy"], list):
            strategies = [p.get("strategy", "") for p in si["pedagogy"][:3]]
            if strategies:
                semantic_context += f"\nRecommended Pedagogy Strategies: {', '.join(strategies)}\n"

        # Misconceptions
        if si.get("misconceptions") and isinstance(si["misconceptions"], list):
            miscs = [m.get("misconception", "") for m in si["misconceptions"][:3]]
            if miscs:
                semantic_context += "\nKnown Student Misconceptions:\n"
                for m in miscs:
                    semantic_context += f"  ⚠ {m}\n"

        # Real-world applications
        if si.get("real_world_applications") and isinstance(si["real_world_applications"], list):
            apps = [r.get("example", "") for r in si["real_world_applications"][:3]]
            if apps:
                semantic_context += "\nReal-World Applications:\n"
                for a in apps:
                    semantic_context += f"  🌍 {a}\n"

        # Prerequisites
        if si.get("prerequisites") and isinstance(si["prerequisites"], list):
            prereqs = list({p.get("concept_name", "") for p in si["prerequisites"][:4]})
            if prereqs:
                semantic_context += f"\nPrerequisite Knowledge: {', '.join(prereqs)}\n"

    # Learning outcomes context
    lo_context = ""
    if lo_rows:
        competencies = [r for r in lo_rows if r.get("type") == "competency"][:5]
        if competencies:
            lo_context = "\nOfficial Learning Outcomes (NCF/NCERT Competencies) to align with:\n"
            for c in competencies:
                desc = c['description'][:120] + "..." if len(c['description']) > 120 else c['description']
                lo_context += f"  [{c['code']}] {desc}\n"

    # Fetch previous period context
    prev_period_context = ""
    with SessionLocal() as db:
        prev_row = db.execute(
            text(f"""
                SELECT primary_concept_name, plan_json
                FROM {TBL_PLAN_PERIODS}
                WHERE lms_intelligence_lesson_plans_id = :plan_id
                  AND id < :pid
                  AND status = 'generated'
                  AND period_type = 'teaching'
                ORDER BY id DESC LIMIT 1
            """),
            {"plan_id": period_row["lms_intelligence_lesson_plans_id"], "pid": period_id}
        ).mappings().fetchone()

        if prev_row:
            prev_concept = prev_row["primary_concept_name"]
            prev_period_context = f"\nPrevious Period Context:\n- Previously taught concept: {prev_concept}\n- Please explicitly reference this in your 'Engage' hook to maintain continuity.\n"

    user_prompt = f"""
Design a {duration}-minute lesson plan for standard (class) {period_row['standard_id']}, chapter "{period_row['chapter_name']}".
Type of period: {period_row['period_type']}

Concepts to cover in this period:
{concepts_text}
{semantic_context}
{lo_context}
{prev_period_context}

Constraints:
- The sum of duration_min for engage, explore, explain, elaborate, and evaluate MUST equal exactly {duration}.
- Make the activities engaging and age-appropriate using the 5E pedagogy model.
- Identify at least one common misconception during the explain phase.
- Align with the official learning outcomes where possible.
- Use the recommended pedagogy strategies from semantic intelligence.
- Include exactly 3 multiple-choice questions in the formative_assessment array.
- Provide strong differentiation strategies for both struggling and gifted learners.
"""

    # 3. Call DeepSeek LLM
    result = await async_call_deepseek(
        prompt=user_prompt,
        system_prompt=MICRO_PLAN_SYSTEM_PROMPT,
        response_format={"type": "json_object"}
    )
    
    data = result["data"]

    # 4. Save back to DB
    with SessionLocal() as db:
        db.execute(
            text(f"""
                UPDATE {TBL_PLAN_PERIODS}
                SET blooms_level = :blooms,
                    dok_level = :dok,
                    pedagogy_method = :pedagogy,
                    difficulty_level = :diff,
                    learning_objectives = :objs,
                    plan_json = :pjson,
                    status = 'generated'
                WHERE id = :pid
            """),
            {
                "blooms": data.get("blooms_level"),
                "dok": data.get("dok_level"),
                "pedagogy": data.get("pedagogy_method"),
                "diff": data.get("difficulty_level"),
                "objs": json.dumps(data.get("learning_objectives", [])),
                "pjson": json.dumps(data.get("plan_json", {})),
                "pid": period_id
            }
        )
        db.commit()

    return {
        "status": "success",
        "period_id": period_id,
        "tokens": {
            "input": result["input_tokens"],
            "output": result["output_tokens"]
        }
    }
