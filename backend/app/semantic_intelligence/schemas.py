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
    topic_summary: str = Field(..., description="A 1-2 sentence summary of what this topic covers.")
    topic_description: str = Field(..., description="A detailed explanation of the topic core concept.")
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

    confidence: float = Field(
        ge=0,
        le=1
    )


# ==========================================================
# KNOWLEDGE INTELLIGENCE
# ==========================================================

class KnowledgeItem(BaseModel):

    name: str

    knowledge_type: Literal[
        "Fact",
        "Concept",
        "Principle",
        "Theory",
        "Procedure",
        "Formula",
        "Rule",
        "Terminology"
    ]

    description: str

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

    retention_priority: Literal[
        "High",
        "Medium",
        "Low"
    ]

    confidence: float = Field(
        ge=0,
        le=1
    )


# ==========================================================
# ABILITY INTELLIGENCE
# ==========================================================

class AbilityItem(BaseModel):

    ability_type: Literal[
        "Identify",
        "Recall",
        "Describe",
        "Explain",
        "Compare",
        "Classify",
        "Interpret",
        "Calculate",
        "Analyze",
        "Evaluate",
        "Create"
    ]

    statement: str

    complexity: Literal[
        "Easy",
        "Medium",
        "Hard"
    ]

    measurable: bool


# ==========================================================
# SKILL INTELLIGENCE
# ==========================================================

class SkillItem(BaseModel):

    skill_name: str

    skill_type: Literal[
        "Subject Skill",
        "Cognitive Skill",
        "Social Skill",
        "Communication Skill",
        "Life Skill",
        "Digital Skill",
        "Future Skill"
    ]

    development_level: Literal[
        "Low",
        "Medium",
        "High"
    ]

    transferability: Literal[
        "Low",
        "Medium",
        "High"
    ]


# ==========================================================
# COMPETENCY INTELLIGENCE
# ==========================================================

class CompetencyItem(BaseModel):

    competency_name: Literal[
        "Conceptual Understanding",
        "Application",
        "Reasoning",
        "Investigation",
        "Problem Solving",
        "Communication",
        "Creativity"
    ]

    strength: float = Field(
        ge=0,
        le=1
    )

    evidence: Optional[str] = None


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

    coverage_score: float = Field(
        ge=0,
        le=1
    )


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

    frequency: Literal[
        "Low",
        "Medium",
        "High"
    ]

    severity: Literal[
        "Low",
        "Medium",
        "High"
    ]

    correction_strategy: Literal[
        "Explanation",
        "Demonstration",
        "Activity",
        "Simulation",
        "Peer Discussion",
        "Guided Practice"
    ]


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

    pedagogy_type: Literal[
        "Direct Instruction",
        "Activity Based Learning",
        "Inquiry Based Learning",
        "Project Based Learning",
        "Experiential Learning",
        "Collaborative Learning",
        "Competency Based Learning",
        "Problem Based Learning",
        "Flipped Classroom",
        "Differentiated Learning"
    ]

    effectiveness: Literal[
        "Low",
        "Medium",
        "High"
    ]

    rationale: str


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
