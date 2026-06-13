from pydantic import BaseModel, Field
from typing import List, Literal, Optional

# ==========================================================
# COMMON MODELS
# ==========================================================

class Evidence(BaseModel):
    source_type: Literal[
        "Curriculum",
        "Textbook",
        "Both",
        "Inferred"
    ]
    source_text: str

# ==========================================================
# CHAPTER STRUCTURE
# ==========================================================

class TopicSlice(BaseModel):
    topic_title: str
    topic_summary: str
    topic_description: str
    start_quote: str
    end_quote: str

class ChapterSlices(BaseModel):
    chapter_summary: str
    topics: List[TopicSlice]

# ==========================================================
# CONCEPT LAYER
# ==========================================================

class Concept(BaseModel):
    concept_id: str
    concept_name: str
    concept_type: Literal[
        "Concept",
        "Definition",
        "Fact",
        "Formula",
        "Rule",
        "Principle",
        "Theory",
        "Law",
        "Process",
        "Procedure",
        "Skill"
    ]
    definition: str
    importance: Literal[
        "Core",
        "Important",
        "Supporting",
        "Optional"
    ]
    difficulty: Literal[
        "Easy",
        "Medium",
        "Hard"
    ]
    confidence: float

# ==========================================================
# KNOWLEDGE INTELLIGENCE
# ==========================================================

class KnowledgeItem(BaseModel):
    knowledge: str
    statement: str
    knowledge_type: Literal[
        "Fact",
        "Definition",
        "Principle",
        "Law",
        "Process",
        "Rule",
        "Relationship",
        "Classification"
    ]
    confidence: float

# ==========================================================
# ABILITY INTELLIGENCE
# ==========================================================

class AbilityItem(BaseModel):
    ability: str
    verb: str
    description: str
    knowledge_refs: List[str]

# ==========================================================
# SKILL INTELLIGENCE
# ==========================================================

class SkillItem(BaseModel):
    skill: str
    ability_refs: List[str]

# ==========================================================
# COMPETENCY INTELLIGENCE
# ==========================================================

class CompetencyItem(BaseModel):
    competency: str
    statement: str
    knowledge_refs: List[str]
    ability_refs: List[str]
    skill_refs: List[str]

# ==========================================================
# LEARNING OBJECTIVES
# ==========================================================

class LearningObjective(BaseModel):
    objective: str
    objective_type: Literal[
        "Knowledge",
        "Ability",
        "Skill",
        "Competency"
    ]
    priority: Literal[
        "High",
        "Medium",
        "Low"
    ]

# ==========================================================
# LEARNING OUTCOMES
# ==========================================================

class LearningOutcome(BaseModel):
    outcome: str
    outcome_type: Literal[
        "Knowledge Outcome",
        "Ability Outcome",
        "Skill Outcome",
        "Competency Outcome"
    ]
    measurable: bool
    assessment_ready: bool

# ==========================================================
# BLOOM'S INTELLIGENCE
# ==========================================================

class BloomMapping(BaseModel):
    level: Literal[
        "Remember",
        "Understand",
        "Apply",
        "Analyze",
        "Evaluate",
        "Create"
    ]
    coverage_score: float

# ==========================================================
# DEPTH OF KNOWLEDGE (DOK)
# ==========================================================

class DOKMapping(BaseModel):
    level: Literal[
        "1",
        "2",
        "3",
        "4"
    ]
    description: Literal[
        "Recall and Reproduction",
        "Skills and Concepts",
        "Strategic Thinking",
        "Extended Thinking"
    ]

# ==========================================================
# PREREQUISITES
# ==========================================================

class Prerequisite(BaseModel):
    concept_name: str
    prerequisite_type: Literal[
        "Knowledge",
        "Ability",
        "Skill",
        "Concept"
    ]
    necessity: Literal[
        "Mandatory",
        "Recommended",
        "Helpful"
    ]

# ==========================================================
# MISCONCEPTIONS
# ==========================================================

class Misconception(BaseModel):
    misconception: str
    statement: str
    root_cause: str
    correction: str

# ==========================================================
# REAL WORLD APPLICATIONS
# ==========================================================

class RealWorldApplication(BaseModel):
    application_type: Literal[
        "Daily Life",
        "Career",
        "Industry",
        "Technology",
        "Environment",
        "Research",
        "Society"
    ]
    example: str
    relevance: Literal[
        "Low",
        "Medium",
        "High"
    ]

# ==========================================================
# PEDAGOGY
# ==========================================================

class PedagogyRecommendation(BaseModel):
    strategy: Literal[
        "Inquiry Based Teaching",
        "Experiential Based Teaching",
        "Art Integrated Teaching",
        "Game Based Teaching",
        "Activity Based Teaching",
        "Project Based Teaching",
        "Flashcard Based / Spaced Repetition Teaching",
        "Flipped Classroom Teaching",
        "Scenario Based Teaching",
        "Skill / Competency Based Teaching"
    ]
    why_effective: str
    concept_characteristics: List[str]

# ==========================================================
# ASSESSMENT BLUEPRINT
# ==========================================================

class AssessmentBlueprint(BaseModel):
    assessment_type: Literal[
        "MCQ",
        "Assertion Reason",
        "Case Study",
        "Short Answer",
        "Long Answer",
        "Numerical",
        "Practical",
        "Project",
        "Viva",
        "HOTS",
        "Competency Based Question"
    ]
    bloom_level: Literal[
        "Remember",
        "Understand",
        "Apply",
        "Analyze",
        "Evaluate",
        "Create"
    ]
    dok_level: Literal[
        "1",
        "2",
        "3",
        "4"
    ]
    difficulty: Literal[
        "Easy",
        "Medium",
        "Hard"
    ]
    marks: int
    recommended_question: str

# ==========================================================
# CONCEPT RELATIONSHIPS
# ==========================================================

class ConceptRelationship(BaseModel):
    source_concept: str
    target_concept: str
    relation_type: Literal[
        "depends_on",
        "part_of",
        "causes",
        "uses",
        "extends",
        "related_to"
    ]

# ==========================================================
# CONCEPT INTELLIGENCE OBJECT (CIO)
# ==========================================================

class ConceptIntelligenceObject(BaseModel):
    concept: Concept
    knowledge_items: List[KnowledgeItem]
    abilities: List[AbilityItem]
    skills: List[SkillItem]
    competencies: List[CompetencyItem]
    learning_objectives: List[LearningObjective]
    learning_outcomes: List[LearningOutcome]
    blooms: List[BloomMapping]
    dok: List[DOKMapping]
    prerequisites: List[Prerequisite]
    misconceptions: List[Misconception]
    real_world_applications: List[RealWorldApplication]
    pedagogy_recommendations: List[PedagogyRecommendation]
    assessment_blueprint: List[AssessmentBlueprint]
    concept_relationships: List[ConceptRelationship]
    evidence: List[Evidence]

# ==========================================================
# TOPIC INTELLIGENCE OBJECT (TIO)
# ==========================================================

class TopicIntelligenceObject(BaseModel):
    topic_name: str
    topic_summary: str
    topic_description: str
    concepts: List[ConceptIntelligenceObject]

# ==========================================================
# CHAPTER INTELLIGENCE OBJECT (CHIO)
# ==========================================================

class ChapterIntelligenceObject(BaseModel):
    chapter_name: str
    chapter_summary: str
    topics: List[TopicIntelligenceObject]
