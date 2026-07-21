from pydantic import BaseModel, Field, field_validator, model_validator
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
# ASSESSMENT RUBRICS
# Mark schemes following the CBSE Assessment Framework (2021).
# Level descriptors are built from rubric_reference.py templates, not by the
# LLM, so that every item of the same shape carries identical bands.
# ==========================================================

class LevelDescriptor(BaseModel):
    level: int
    quality_band: Literal[
        "Perceptive",
        "Clear",
        "Generally Clear",
        "Straightforward",
        "Limited",
        "Nothing to Reward",
        # Holistic Progress Card scale, Classes 1-5
        "Proficient",
        "Progressing",
        "Beginner"
    ]
    display_label: Literal[
        "Excellent",
        "Good",
        "Fair",
        "Needs Improvement",
        "Beginning",
        "No Credit",
        "Proficient",
        "Progressing",
        "Beginner"
    ]
    descriptors: List[str]
    mark_low: int
    mark_high: int

class AcceptablePoint(BaseModel):
    """One creditworthy point in a point-based mark scheme (framework p.57)."""
    point: str
    marks: int
    alternatives: List[str] = Field(default_factory=list, description="Equally creditworthy phrasings of the same point.")

class OptionRationale(BaseModel):
    """One option of an MCQ / Assertion-Reason item, with its diagnosis."""
    option_label: Literal["A", "B", "C", "D"]
    option_text: str
    is_correct: bool
    rationale: str
    misconception_tested: Optional[str] = Field(None, description="For incorrect options: the EXACT misconception statement this distractor is designed to detect.")

class RubricCriterion(BaseModel):
    """One row of an analytical rubric (Project / Practical / Viva)."""
    criterion: Literal[
        "Conceptual Understanding",
        "Scientific Method / Process",
        "Data Handling & Accuracy",
        "Analysis & Interpretation",
        "Application & Relevance",
        "Presentation & Communication",
        "Originality & Creativity",
        "Record / Documentation",
        "Viva / Oral Defence",
        "Collaboration & Teamwork"
    ]
    weight_marks: int
    level_descriptors: List[LevelDescriptor] = Field(default_factory=list)

class TeachingNotes(BaseModel):
    key_vocabulary: List[str] = Field(default_factory=list)
    practical_activities: List[str] = Field(default_factory=list)
    blooms_verbs_used: List[str] = Field(default_factory=list)
    written_evidence_tips: List[str] = Field(default_factory=list)
    oral_evidence_tips: List[str] = Field(default_factory=list)
    experimental_evidence_tips: List[str] = Field(default_factory=list)

    @field_validator("*", mode="before")
    @classmethod
    def coerce_to_list(cls, value):
        """Accept a bare sentence where a list of sentences is expected.

        The tips fields in particular read like prose instructions, so the
        model frequently answers with one string instead of an array. Losing an
        entire concept's intelligence over teacher guidance is out of all
        proportion to the defect, so a string is wrapped rather than rejected.
        """
        if value is None:
            return []
        if isinstance(value, str):
            stripped = value.strip()
            return [stripped] if stripped else []
        return value

class AssessmentItem(BaseModel):
    """An assessment item fused with its mark scheme.

    The item and the rubric are generated together from the concept's source
    text so that the rubric always has a task to mark, and so that
    source_evidence can be verified against the original markdown.
    """
    item_id: str
    question: str
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
    rubric_type: Literal[
        "answer_key",
        "point_based",
        "levels_of_response",
        "analytical"
    ]
    difficulty: Literal["Easy", "Medium", "Hard"]
    marks: int
    bloom_level: Literal[
        "Remember",
        "Understand",
        "Apply",
        "Analyze",
        "Evaluate",
        "Create"
    ]
    dok_level: Literal["1", "2", "3", "4"]
    assessment_objectives: List[str] = Field(default_factory=list, description="CBSE AO codes this item assesses, valid for the subject.")

    skill_phrase: str = Field("", description="Short phrase naming the capability the item assesses, substituted into the level descriptors.")
    source_evidence: List[str] = Field(default_factory=list, description="EXACT quotes from the source text this item is drawn from.")
    evidence_verified: bool = Field(False, description="Set by the pipeline: whether every source_evidence quote was found in the source text.")

    # Shape-specific payloads. Exactly one family is populated per rubric_type.
    answer_key: List[OptionRationale] = Field(default_factory=list)
    acceptable_points: List[AcceptablePoint] = Field(default_factory=list)
    indicative_content: List[str] = Field(default_factory=list)
    level_descriptors: List[LevelDescriptor] = Field(default_factory=list)
    criteria: List[RubricCriterion] = Field(default_factory=list)

    threshold_conditions: List[str] = Field(default_factory=list)
    common_errors: List[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def check_rubric_shape(self) -> 'AssessmentItem':
        # Mark bands must be contiguous, descending and reach exactly `marks`.
        if self.level_descriptors:
            scored = [d for d in self.level_descriptors if d.level > 0]
            if scored:
                top = max(d.mark_high for d in scored)
                if top != self.marks:
                    raise ValueError(
                        f"top mark band {top} does not equal item marks {self.marks}"
                    )
            # Every level must carry the same number of parallel bullets.
            counts = {len(d.descriptors) for d in scored}
            if len(counts) > 1:
                raise ValueError("level descriptors must have identical bullet counts")

        # Analytical criterion weights must sum to the item total.
        if self.criteria:
            total = sum(c.weight_marks for c in self.criteria)
            if total != self.marks:
                raise ValueError(
                    f"criterion weights sum to {total}, expected {self.marks}"
                )

        # An answer key needs exactly one correct option.
        if self.rubric_type == "answer_key" and self.answer_key:
            correct = [o for o in self.answer_key if o.is_correct]
            if len(correct) != 1:
                raise ValueError(f"answer_key has {len(correct)} correct options, expected 1")

        return self

class AgentReasoning(BaseModel):
    """The chain-of-thought each agent writes before extracting.

    Every agent is asked for this first so the reasoning conditions the output
    that follows. It is billed as output tokens either way, so it is persisted
    rather than discarded, which also makes each extraction auditable.
    """
    cognitive: Optional[str] = None       # Agent 1
    pedagogy: Optional[str] = None        # Agent 2
    assessment: Optional[str] = None      # Agent 3
    rubrics: Optional[str] = None         # Agent 4

class ConceptAssessmentRubric(BaseModel):
    """All assessment items for one concept, plus teacher guidance."""
    concept_name: str
    items: List[AssessmentItem] = Field(default_factory=list)
    teaching_notes: Optional[TeachingNotes] = None

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
    assessment_rubrics: Optional[ConceptAssessmentRubric] = None
    agent_reasoning: Optional[AgentReasoning] = None

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
