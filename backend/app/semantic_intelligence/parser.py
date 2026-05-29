from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class SubtopicSchema(BaseModel):
    subtopic_title: str
    bloom_level: str
    subtopic_summary: str
    detailed_explanation: str = ""
    teacher_teaching_notes: str = ""
    real_life_connection: str = ""
    common_student_confusion: str = ""
    examples: List[str] = []
    activities: List[str] = []
    formulas: List[str] = []
    important_lines: List[str] = []
    diagram_explanations: List[str] = []
    learning_outcomes: List[str] = []
    map_activities: List[Dict[str, str]] = []

class TeachingUnitSchema(BaseModel):
    unit_id: str
    topic_title: str
    topic_summary: str
    subtopics: List[SubtopicSchema] = Field(default_factory=list)

class ChapterApparatusSchema(BaseModel):
    lets_explore_questions: List[Dict[str, str]] = []
    dont_miss_out_facts: List[Dict[str, str]] = []
    lets_remember_definitions: List[Dict[str, str]] = []
    chapter_summary_points: List[str] = []
    exam_questions: List[Dict[str, Any]] = []

class SemanticIntelligenceOutputSchema(BaseModel):
    subject: str
    class_: str = Field(alias="class")
    chapter_title: str
    short_summary: str
    learning_objectives: str
    chapter_apparatus: Optional[ChapterApparatusSchema] = None
    teaching_units: List[TeachingUnitSchema] = Field(default_factory=list)

def validate_semantic_intelligence_output(raw_json: dict) -> SemanticIntelligenceOutputSchema:
    return SemanticIntelligenceOutputSchema(**raw_json)

def calculate_quality_flag(validated, validation_result: dict = None) -> str:
    units = validated.teaching_units
    if not units:
        return "regenerate"
    
    total_subs = sum(len(u.subtopics) for u in units)
    if total_subs < 3:
        return "regenerate"

    issues = 0

    for unit in units:
        for sub in unit.subtopics:
            if len(sub.detailed_explanation) < 80:
                issues += 1
            
            valid_blooms = {
                "Remember","Understand","Apply","Analyze","Evaluate","Create"
            }
            if sub.bloom_level not in valid_blooms:
                issues += 1
            
            generic_phrases = [
                "it is important", "in daily life", "very useful",
                "helps us understand", "used everywhere"
            ]
            connection = sub.real_life_connection.lower()
            if any(phrase in connection for phrase in generic_phrases):
                issues += 1
            
            for outcome in sub.learning_outcomes:
                if len(outcome) < 15:
                    issues += 1

    if validation_result:
        if validation_result.get("overall_completeness") == "major_gaps":
            return "regenerate"
        if validation_result.get("overall_completeness") == "minor_gaps":
            issues += 3

    threshold = total_subs * 0.3
    if issues > threshold * 2:
        return "regenerate"
    if issues > threshold:
        return "needs_review"
    return "good"

def extract_summary_fields(validated: SemanticIntelligenceOutputSchema) -> dict:
    total_subtopics = sum(len(unit.subtopics) for unit in validated.teaching_units)
    return {
        "chapter_title": validated.chapter_title,
        "short_summary": validated.short_summary,
        "learning_objectives": validated.learning_objectives,
        "total_topics": len(validated.teaching_units),
        "total_subtopics": total_subtopics
    }
