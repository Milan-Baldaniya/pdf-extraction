from pydantic import BaseModel, Field, model_validator
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

class ConceptSlice(BaseModel):
    concept_title: str
    concept_summary: str
    concept_description: str
    start_quote: str
    end_quote: str

class ChapterSlices(BaseModel):
    chapter_summary: str
    concepts: List[ConceptSlice]

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
    ] = Field(..., description="The Bloom's Taxonomy level. Must be UNIQUE across all items in the list. Do not duplicate.")
    coverage_score: float = Field(..., description="Percentage of the concept targeting this level (e.g., 40.0). If multiple levels exist, their scores MUST mathematically sum to exactly 100. DO NOT use 100 for all items.")

# ==========================================================
# DEPTH OF KNOWLEDGE (DOK)
# ==========================================================

class DOKMapping(BaseModel):
    level: Literal[
        "1",
        "2",
        "3",
        "4"
    ] = Field(..., description="The Depth of Knowledge level. Must be UNIQUE across all items in the list. Do not duplicate levels.")
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
    concept_name: str = Field(..., description="The name of the prerequisite concept. CRITICAL: This MUST NOT be the exact same name as the concept currently being analyzed. It must refer to a previously learned, genuinely distinct concept.")
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
    blooms: List[BloomMapping] = Field(..., description="List of UNIQUE Bloom's taxonomy levels. DO NOT repeat the same level multiple times. The sum of coverage_score across all items MUST be exactly 100.")
    dok: List[DOKMapping] = Field(..., description="List of UNIQUE Depth of Knowledge (DOK) levels. DO NOT repeat the same DOK level multiple times.")
    prerequisites: List[Prerequisite] = Field(..., description="List of required prerequisites. The concept_name of each prerequisite MUST NOT equal the name of the current concept.")
    misconceptions: List[Misconception]
    real_world_applications: List[RealWorldApplication]
    pedagogy_recommendations: List[PedagogyRecommendation]
    assessment_blueprint: List[AssessmentBlueprint]
    concept_relationships: List[ConceptRelationship]
    evidence: List[Evidence]

    @model_validator(mode='after')
    def sanitize_and_normalize(self) -> 'ConceptIntelligenceObject':
        # 1. Deduplicate DOK levels (keep first occurrence)
        unique_dok = []
        seen_dok = set()
        for d in self.dok:
            if d.level not in seen_dok:
                unique_dok.append(d)
                seen_dok.add(d.level)
        self.dok = unique_dok

        # 2. Filter self-referencing prerequisites
        if self.concept and self.concept.concept_name:
            concept_name_lower = self.concept.concept_name.lower().strip()
            filtered_prereqs = []
            for p in self.prerequisites:
                if p.concept_name.lower().strip() != concept_name_lower:
                    filtered_prereqs.append(p)
            self.prerequisites = filtered_prereqs

        # 3. Deduplicate and Normalize Blooms
        bloom_dict = {}
        for b in self.blooms:
            if b.level in bloom_dict:
                bloom_dict[b.level].coverage_score += b.coverage_score
            else:
                bloom_dict[b.level] = b

        unique_blooms = list(bloom_dict.values())
        
        # Normalize to exactly 1.0 (since frontend multiplies by 100)
        total_score = sum(b.coverage_score for b in unique_blooms)
        if total_score > 0:
            for b in unique_blooms:
                b.coverage_score = round(b.coverage_score / total_score, 2)
        elif len(unique_blooms) > 0:
            even_score = round(1.0 / len(unique_blooms), 2)
            for b in unique_blooms:
                b.coverage_score = even_score
                
        self.blooms = unique_blooms

        return self

# ==========================================================
# CHAPTER INTELLIGENCE OBJECT (CHIO)
# ==========================================================

class ChapterIntelligenceObject(BaseModel):
    chapter_name: str
    chapter_summary: str
    concepts: List[ConceptIntelligenceObject]
