"""Phase 3 Pydantic validation and quality scoring for teaching intelligence output."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


# ─── Pydantic Schema ────────────────────────────────────────────────────────

class SlideTeachingPlan(BaseModel):
    unit_id: str
    topic_title: str
    subtopic_title: str
    bloom_level: str
    slide_number: int
    teacher_narration: str
    student_hook: str
    storytelling_style: str = ""
    attention_strategy: str = ""
    visual_metaphor: str = ""
    classroom_activity: str = ""
    interaction_points: str = ""
    teaching_pacing: str = "medium"
    emotion_curve: str = "maintain_energy"
    visual_scene_description: str = ""
    slide_visual_goal: str = ""
    key_takeaway: str = ""
    diagram_teaching_explanation: Optional[str] = ""
    teacher_board_notes: str = ""
    common_student_questions: List[str] = []
    memory_tricks: List[str] = []
    revision_points: List[str] = []


class TeachingIntelligenceOutput(BaseModel):
    """Top-level validated structure for Phase 3 DeepSeek output."""

    chapter_title: str
    teaching_style: str
    language: str
    difficulty_level: str
    slide_teaching_plans: List[SlideTeachingPlan]


# ─── Validation ─────────────────────────────────────────────────────────────

def validate_teaching_intelligence_output(raw_json: dict) -> TeachingIntelligenceOutput:
    """Parse and validate raw DeepSeek JSON into the Phase 3 Pydantic model."""
    return TeachingIntelligenceOutput(**raw_json)


# ─── Quality Constants ──────────────────────────────────────────────────────

VALID_PACING = {"slow_and_detailed", "medium", "quick_overview"}
VALID_EMOTION = {"build_curiosity", "maintain_energy", "create_surprise", "reflective"}
VALID_BLOOMS = {"Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create"}


# ─── Quality Flag Calculation ───────────────────────────────────────────────

def calculate_teaching_quality_flag(validated: TeachingIntelligenceOutput) -> str:
    """Score the quality of the teaching intelligence output.

    Returns:
        'good'        — ready for Phase 4.
        'needs_review' — usable but could be improved.
        'regenerate'  — too many issues; prompt needs tweaking or re-run.
    """
    plans = validated.slide_teaching_plans
    if not plans:
        return "regenerate"

    issues = 0
    for plan in plans:
        # narration must use personal voice
        narration_lower = plan.teacher_narration.lower()
        if "you" not in narration_lower and "we" not in narration_lower:
            issues += 1

        # narration must be substantive (at least 100 chars)
        if len(plan.teacher_narration) < 100:
            issues += 1

        # hook must not be the subtopic title reworded
        if plan.student_hook.lower().strip() == plan.subtopic_title.lower().strip():
            issues += 1

        # activity must be specific — not generic filler
        generic_activity = ["do an activity", "perform an activity", "think about it"]
        if any(g in plan.classroom_activity.lower() for g in generic_activity):
            issues += 1

        # key_takeaway must be concise
        if len(plan.key_takeaway) > 200:
            issues += 1

        # pacing must be valid
        if plan.teaching_pacing not in VALID_PACING:
            issues += 1

    threshold = len(plans) * 0.3
    if issues > threshold * 2:
        return "regenerate"
    if issues > threshold:
        return "needs_review"
    return "good"
