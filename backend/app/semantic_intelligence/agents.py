import os
import asyncio
import json
import random
import google.generativeai as genai
from pydantic import BaseModel
from typing import List
from dotenv import load_dotenv

# Import the massive user schema definitions
from .schemas import (
    Concept, KnowledgeItem, AbilityItem, SkillItem, CompetencyItem, 
    BloomMapping, DOKMapping, Prerequisite, Misconception, RealWorldApplication, 
    PedagogyRecommendation, ConceptRelationship, LearningObjective, 
    LearningOutcome, AssessmentBlueprint, Evidence
)

load_dotenv(override=True)

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
        # Reload keys dynamically so live edits to .env take effect immediately
        load_dotenv(override=True)
        # Bind exactly one unique key to each agent
        k1_main = os.getenv("GEMINI_API_KEY_AGENT_1")
        self.keys_1 = [k1_main] if k1_main else []

        k2_main = os.getenv("GEMINI_API_KEY_AGENT_2")
        self.keys_2 = [k2_main] if k2_main else []

        k3_main = os.getenv("GEMINI_API_KEY_AGENT_3")
        self.keys_3 = [k3_main] if k3_main else []

        # Ensure high reasoning capable models are used for the deep intelligence layers
        self.client_1 = genai.GenerativeModel("gemini-2.5-flash")
        self.client_2 = genai.GenerativeModel("gemini-2.5-flash")
        self.client_3 = genai.GenerativeModel("gemini-2.5-flash")
        
    def _get_generation_config(self, schema: BaseModel) -> genai.GenerationConfig:
        return genai.GenerationConfig(
            temperature=0.2,
            response_mime_type="application/json",
            response_schema=schema,
            frequency_penalty=0.0,
            presence_penalty=0.0
        )

    async def _generate_with_fallback(self, client, keys: List[str], prompt: str, text_slice: str, schema: BaseModel) -> dict:
        import time
        from google.api_core.exceptions import ResourceExhausted, InternalServerError
        
        last_error = None
        max_retries = 3
        
        for key in keys:
            if not key:
                continue
            genai.configure(api_key=key)
            print(f"  [API] Trying with key ending in ...{key[-4:]}")
            
            for attempt in range(max_retries):
                try:
                    response = await client.generate_content_async(
                        contents=[prompt, text_slice],
                        generation_config=self._get_generation_config(schema)
                    )
                    return json.loads(response.text)
                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    print(f"  [WARNING] API Error on key ...{key[-4:]} (Attempt {attempt+1}/{max_retries}): {err_str}")
                    
                    if "403" in err_str or "API key not valid" in err_str or "401" in err_str:
                        # Key is invalid or blocked. Don't retry this key.
                        break
                    elif "429" in err_str or "quota" in err_str.lower() or isinstance(e, ResourceExhausted):
                        if attempt < max_retries - 1:
                            print(f"  [API] Rate limit hit. Pausing 60 seconds to reset RPM limit...")
                            await asyncio.sleep(60)
                        else:
                            break
                    else:
                        # Transient error (500, 503). Wait and try this key again.
                        await asyncio.sleep(2)
                        
        # Return an empty dict if it completely failed so the pipeline doesn't crash
        print(f"  [CRITICAL WARNING] Returning empty object due to persistent failure. Last error: {last_error}")
        return {}

    async def _run_agent_1_cognitive(self, text_slice: str) -> dict:
        
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
        return await self._generate_with_fallback(
            client=self.client_1,
            keys=self.keys_1,
            prompt=prompt,
            text_slice=text_slice,
            schema=Agent1CognitiveOutput
        )

    async def _run_agent_2_pedagogy(self, text_slice: str, agent1_json: dict) -> dict:
        
        prompt = f"""
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

NO EXPLANATIONS.

PREVIOUS AGENT EXTRACTED KNOWLEDGE (USE THIS AS CONTEXT):
{json.dumps(agent1_json, indent=2)}

RAW TEXT:
"""
        return await self._generate_with_fallback(
            client=self.client_2,
            keys=self.keys_2,
            prompt=prompt,
            text_slice=text_slice,
            schema=Agent2PedagogyOutput
        )

    async def _run_agent_3_assessment(self, text_slice: str, agent1_json: dict, agent2_json: dict) -> dict:
        
        prompt = f"""
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

NO EXPLANATIONS.

PREVIOUS AGENT KNOWLEDGE EXTRACTION:
{json.dumps(agent1_json, indent=2)}

PREVIOUS AGENT PEDAGOGY EXTRACTION:
{json.dumps(agent2_json, indent=2)}

RAW TEXT:
"""
        return await self._generate_with_fallback(
            client=self.client_3,
            keys=self.keys_3,
            prompt=prompt,
            text_slice=text_slice,
            schema=Agent3AssessmentOutput
        )

    async def process_topic_slice(self, text_slice: str) -> dict:
        """
        The Orchestrator: Fires the 3 expert agents SEQUENTIALLY.
        Passes outputs of earlier agents into downstream agents for perfect cohesion.
        Merges their outputs perfectly into the final Topic Intelligence parameters.
        """
        print("Firing Sequential CBSE Expert Chain...")
        
        print("  -> Running Agent 1 (Cognitive Intelligence)...")
        out1 = await self._run_agent_1_cognitive(text_slice)
        
        print("  -> Running Agent 2 (Pedagogy Intelligence)...")
        out2 = await self._run_agent_2_pedagogy(text_slice, out1)
        
        print("  -> Running Agent 3 (Assessment Intelligence)...")
        out3 = await self._run_agent_3_assessment(text_slice, out1, out2)
        
        print("Chain complete. Merging Intelligence Dimensions...")
        
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
