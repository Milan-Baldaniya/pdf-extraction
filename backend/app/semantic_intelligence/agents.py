import os
import asyncio
import json
import google.generativeai as genai
from pydantic import BaseModel
from typing import List
from dotenv import load_dotenv

# Import the massive user schema definitions
from .schemas import (
    Concept, KnowledgeItem, AbilityItem, SkillItem, CompetencyItem, 
    BloomMapping, DOKMapping, Prerequisite, Misconception, RealWorldApplication, 
    PedagogyRecommendation, ConceptRelationship, LearningObjective, 
    LearningOutcome, AssessmentBlueprint, Evidence, ConceptIntelligenceObject
)

load_dotenv()

# ==========================================================
# PARTIAL SCHEMAS FOR AGENTS
# We split the mega-schema into 3 perfectly bounded pieces 
# so the LLM doesn't lose attention or hit context limits.
# ==========================================================

class Agent1CognitiveOutput(BaseModel):
    concept: Concept
    knowledge_items: List[KnowledgeItem]
    abilities: List[AbilityItem]
    skills: List[SkillItem]
    competencies: List[CompetencyItem]
    blooms: List[BloomMapping]
    dok: List[DOKMapping]
    evidence: List[Evidence]

class Agent2PedagogyOutput(BaseModel):
    prerequisites: List[Prerequisite]
    misconceptions: List[Misconception]
    real_world_applications: List[RealWorldApplication]
    pedagogy_recommendations: List[PedagogyRecommendation]
    concept_relationships: List[ConceptRelationship]
    evidence: List[Evidence]

class Agent3AssessmentOutput(BaseModel):
    learning_objectives: List[LearningObjective]
    learning_outcomes: List[LearningOutcome]
    assessment_blueprint: List[AssessmentBlueprint]
    evidence: List[Evidence]

# ==========================================================
# PHASE 3: THE PARALLEL MICRO-AGENT SWARM
# ==========================================================

class IntelligenceSwarm:
    def __init__(self):
        # Bind specific keys to specific agents to bypass Free Tier RPM limits
        # Fallback to main key if specific keys aren't added to .env yet
        key_1 = os.getenv("GEMINI_API_KEY_AGENT_1") or os.getenv("GEMINI_API_KEY")
        key_2 = os.getenv("GEMINI_API_KEY_AGENT_2") or os.getenv("GEMINI_API_KEY")
        key_3 = os.getenv("GEMINI_API_KEY_AGENT_3") or os.getenv("GEMINI_API_KEY")

        # Initialize isolated client configurations per agent
        self.client_1 = genai.GenerativeModel("gemini-1.5-pro")
        self.client_2 = genai.GenerativeModel("gemini-1.5-pro")
        self.client_3 = genai.GenerativeModel("gemini-1.5-pro")
        
        self.keys = {1: key_1, 2: key_2, 3: key_3}
        
    def _get_generation_config(self, schema: BaseModel) -> genai.GenerationConfig:
        return genai.GenerationConfig(
            temperature=0.2,
            response_mime_type="application/json",
            response_schema=schema,
            frequency_penalty=0.0,
            presence_penalty=0.0
        )

    async def _run_agent_1_cognitive(self, text_slice: str) -> dict:
        genai.configure(api_key=self.keys[1])
        
        prompt = """
ROLE

You are a CBSE Curriculum Intelligence Expert, Educational Psychologist, Learning Scientist, and Knowledge Engineer.

Your task is to transform textbook content into structured Concept Intelligence.

You must follow:

- CBSE Competency Based Education Framework
- NCF 2023
- NEP 2020
- Bloom's Taxonomy
- Webb's Depth of Knowledge (DOK)
- Learning Sciences

--------------------------------------------------

OBJECTIVE

Analyze the provided educational text and extract ALL educational intelligence related to the concepts present.

Do NOT summarize.

Do NOT rewrite.

Do NOT generate teaching content.

Extract intelligence only.

--------------------------------------------------

CONCEPT EXTRACTION RULES

1. Extract ALL concepts present in the text.

2. Do NOT assume a single concept.

3. Identify:

- Core Concepts
- Supporting Concepts
- Definitions
- Facts
- Principles
- Rules
- Formulas
- Processes

4. The concept selected in the schema must represent the PRIMARY concept of this text slice.

--------------------------------------------------

KNOWLEDGE INTELLIGENCE

For every knowledge item:

Determine:

- knowledge_type
- description
- importance
- difficulty
- retention_priority
- confidence

Only extract knowledge explicitly present or strongly implied.

--------------------------------------------------

ABILITY INTELLIGENCE

Identify what students must be able to DO after learning this concept.

Use only:

Identify
Recall
Describe
Explain
Compare
Classify
Interpret
Calculate
Analyze
Evaluate
Create

Every ability must be measurable.

--------------------------------------------------

SKILL INTELLIGENCE

Identify skills developed through this concept.

Possible categories:

- Subject Skill
- Cognitive Skill
- Social Skill
- Communication Skill
- Life Skill
- Digital Skill
- Future Skill

Only extract genuine skills.

Avoid generic skills.

--------------------------------------------------

COMPETENCY INTELLIGENCE

Map concept to CBSE competencies:

- Conceptual Understanding
- Application
- Reasoning
- Investigation
- Problem Solving
- Communication
- Creativity

Assign strength score:

0.0 to 1.0

--------------------------------------------------

BLOOM'S INTELLIGENCE

For every concept determine:

Primary Bloom Level

Possible values:

Remember
Understand
Apply
Analyze
Evaluate
Create

Provide coverage score.

--------------------------------------------------

DOK INTELLIGENCE

Determine depth of learning:

1 Recall and Reproduction

2 Skills and Concepts

3 Strategic Thinking

4 Extended Thinking

Select the dominant DOK level.

--------------------------------------------------

CONFIDENCE SCORING

For every extracted item:

Provide confidence score:

0.0 to 1.0

Confidence must represent certainty from source text.

--------------------------------------------------

EVIDENCE REQUIREMENTS

Every major extraction must be supported by evidence.

Evidence must contain:

source_type:
- Textbook
- Curriculum
- Both
- Inferred

source_text:

Use exact text quote whenever possible.

Never invent evidence.

--------------------------------------------------

OUTPUT RULES

Return only data matching the supplied schema.

No markdown.

No explanations.

No commentary.

No additional fields.

RAW TEXT:
"""
        response = await self.client_1.generate_content_async(
            contents=[prompt, text_slice],
            generation_config=self._get_generation_config(Agent1CognitiveOutput)
        )
        return json.loads(response.text)

    async def _run_agent_2_pedagogy(self, text_slice: str) -> dict:
        genai.configure(api_key=self.keys[2])
        
        prompt = """
ROLE

You are a Master CBSE Teacher, Learning Experience Designer, Instructional Strategist, and Educational Researcher.

Your task is to extract Pedagogical Intelligence.

Follow:

- CBSE Competency Based Education
- NCF 2023
- NEP 2020
- Constructivist Learning Theory
- Experiential Learning
- Inquiry Based Learning

--------------------------------------------------

OBJECTIVE

Determine:

- Prerequisites
- Misconceptions
- Real World Applications
- Pedagogy Recommendations
- Concept Relationships

--------------------------------------------------

PREREQUISITE INTELLIGENCE

Identify knowledge required before learning this concept.

Classify as:

Mandatory
Recommended
Helpful

Only include genuine dependencies.

--------------------------------------------------

MISCONCEPTION INTELLIGENCE

Identify likely student misconceptions.

For every misconception provide:

- misconception
- frequency
- severity
- correction_strategy

Focus on actual learning difficulties.

Avoid generic mistakes.

--------------------------------------------------

REAL WORLD APPLICATIONS

Identify authentic applications.

Possible categories:

Daily Life
Career
Industry
Technology
Environment
Research
Society

Provide realistic examples.

--------------------------------------------------

PEDAGOGY RECOMMENDATIONS

Recommend teaching approaches based on:

- Concept nature
- Bloom level
- Cognitive complexity
- Practicality
- Student engagement

Possible methods:

Direct Instruction
Activity Based Learning
Inquiry Based Learning
Project Based Learning
Experiential Learning
Collaborative Learning
Competency Based Learning
Problem Based Learning
Flipped Classroom
Differentiated Learning

Provide rationale.

--------------------------------------------------

CONCEPT RELATIONSHIPS

Extract relationships:

depends_on
part_of
causes
uses
extends
related_to

Only create relationships supported by the text.

--------------------------------------------------

EVIDENCE REQUIREMENTS

Support every major pedagogical decision.

Use direct quotes whenever possible.

--------------------------------------------------

OUTPUT RULES

Return only schema-compliant JSON.

No explanations.

RAW TEXT:
"""
        response = await self.client_2.generate_content_async(
            contents=[prompt, text_slice],
            generation_config=self._get_generation_config(Agent2PedagogyOutput)
        )
        return json.loads(response.text)

    async def _run_agent_3_assessment(self, text_slice: str) -> dict:
        genai.configure(api_key=self.keys[3])
        
        prompt = """
ROLE

You are a Senior CBSE Assessment Architect, Psychometrician, Examination Designer, and Learning Outcome Specialist.

Your task is to create Assessment Intelligence.

Follow:

- CBSE Assessment Framework
- Competency Based Assessment
- Bloom's Taxonomy
- Webb DOK
- Outcome Based Education

--------------------------------------------------

OBJECTIVE

Extract:

- Learning Objectives
- Learning Outcomes
- Assessment Blueprint

--------------------------------------------------

LEARNING OBJECTIVES

Define what the teacher intends to teach.

Classify:

Knowledge
Ability
Skill
Competency

Assign priority.

--------------------------------------------------

LEARNING OUTCOMES

Define measurable student achievements.

Every outcome must:

- begin with action verb
- be measurable
- be testable
- be assessment ready

--------------------------------------------------

ASSESSMENT BLUEPRINT

Create balanced assessment design.

For every assessment item determine:

assessment_type

Possible values:

MCQ
Assertion Reason
Case Study
Short Answer
Long Answer
Numerical
Practical
Project
Viva
HOTS
Competency Based Question

difficulty

Easy
Medium
Hard

Bloom Level

Remember
Understand
Apply
Analyze
Evaluate
Create

DOK Level

1
2
3
4

marks

recommended_question

Question must directly assess the concept.

--------------------------------------------------

ASSESSMENT DESIGN RULES

Ensure coverage of:

Knowledge
Understanding
Application
Reasoning

Prefer competency based questions.

--------------------------------------------------

EVIDENCE REQUIREMENTS

Every objective and outcome must be traceable to the source text.

Use direct quotes where possible.

--------------------------------------------------

OUTPUT RULES

Return only schema-compliant JSON.

No explanations.

RAW TEXT:
"""
        response = await self.client_3.generate_content_async(
            contents=[prompt, text_slice],
            generation_config=self._get_generation_config(Agent3AssessmentOutput)
        )
        return json.loads(response.text)

    async def process_topic_slice(self, text_slice: str) -> dict:
        """
        The Orchestrator: Fires all 3 expert agents simultaneously using asyncio.
        Merges their outputs perfectly into the final ConceptIntelligenceObject.
        """
        print("Firing parallel CBSE Expert Swarm...")
        
        # Run all three LLM calls at the exact same time
        task1 = self._run_agent_1_cognitive(text_slice)
        task2 = self._run_agent_2_pedagogy(text_slice)
        task3 = self._run_agent_3_assessment(text_slice)
        
        out1, out2, out3 = await asyncio.gather(task1, task2, task3)
        
        print("Swarm complete. Merging Intelligence Dimensions...")
        
        # Merge all evidence arrays
        merged_evidence = out1.get("evidence", []) + out2.get("evidence", []) + out3.get("evidence", [])
        
        # Assemble the flawless mega-object
        mega_concept_object = {
            "concept": out1.get("concept", {}),
            "knowledge_items": out1.get("knowledge_items", []),
            "abilities": out1.get("abilities", []),
            "skills": out1.get("skills", []),
            "competencies": out1.get("competencies", []),
            "blooms": out1.get("blooms", []),
            "dok": out1.get("dok", []),
            
            "prerequisites": out2.get("prerequisites", []),
            "misconceptions": out2.get("misconceptions", []),
            "real_world_applications": out2.get("real_world_applications", []),
            "pedagogy_recommendations": out2.get("pedagogy_recommendations", []),
            "concept_relationships": out2.get("concept_relationships", []),
            
            "learning_objectives": out3.get("learning_objectives", []),
            "learning_outcomes": out3.get("learning_outcomes", []),
            "assessment_blueprint": out3.get("assessment_blueprint", []),
            
            "evidence": merged_evidence
        }
        
        return mega_concept_object
