import os
import asyncio
import json
import random
import google.generativeai as genai
from pydantic import BaseModel, Field
from typing import List
from dotenv import load_dotenv

# Import the massive user schema definitions
from .schemas import (
    Concept, KnowledgeItem, AbilityItem, SkillItem, CompetencyItem, 
    BloomMapping, DOKMapping, Prerequisite, Misconception, RealWorldApplication, 
    PedagogyRecommendation, ConceptRelationship, LearningObjective, 
    LearningOutcome, AssessmentBlueprint, Evidence, ConceptIntelligenceObject
)

load_dotenv(override=True)

# ==========================================================
# PARTIAL SCHEMAS FOR AGENTS
# We split the mega-schema into 3 perfectly bounded pieces 
# so the LLM doesn't lose attention or hit context limits.
# ==========================================================

class Agent1CognitiveOutput(BaseModel):
    pedagogical_reasoning: str = Field(..., description="Step-by-step reasoning explaining how this concept slice builds cognitive knowledge, why you chose specific Bloom's levels and DOK levels, and how it aligns with the overall chapter goals. Write this before extracting the arrays.")
    concept: Concept
    knowledge_items: List[KnowledgeItem]
    abilities: List[AbilityItem]
    skills: List[SkillItem]
    competencies: List[CompetencyItem]
    blooms: List[BloomMapping]
    dok: List[DOKMapping]
    evidence: List[Evidence]

class Agent2PedagogyOutput(BaseModel):
    pedagogical_reasoning: str = Field(..., description="Step-by-step reasoning for the chosen prerequisites, misconceptions, and teaching strategies based on the cognitive knowledge extracted previously.")
    prerequisites: List[Prerequisite]
    misconceptions: List[Misconception]
    real_world_applications: List[RealWorldApplication]
    pedagogy_recommendations: List[PedagogyRecommendation]
    concept_relationships: List[ConceptRelationship]
    evidence: List[Evidence]

class Agent3AssessmentOutput(BaseModel):
    pedagogical_reasoning: str = Field(..., description="Step-by-step reasoning for your blueprint design choices, explaining why specific question types and difficulty levels match the cognitive abilities and teaching strategies of this concept.")
    learning_objectives: List[LearningObjective]
    learning_outcomes: List[LearningOutcome]
    assessment_blueprint: List[AssessmentBlueprint]
    evidence: List[Evidence]

# ==========================================================
# PHASE 3: THE PARALLEL MICRO-AGENT SWARM
# ==========================================================

from .deepseek_client import async_call_deepseek

class IntelligenceSwarm:
    def __init__(self):
        pass

    async def _generate_with_fallback(self, prompt: str, text_slice: str, schema: BaseModel) -> dict:
        import time
        import asyncio
        
        system_prompt = f"You are a helpful assistant. You must respond ONLY with valid JSON exactly matching this schema:\n{schema.model_json_schema()}"
        full_prompt = f"{prompt}\n\nContent:\n{text_slice}"
        
        try:
            result = await async_call_deepseek(full_prompt, system_prompt=system_prompt, response_format={"type": "json_object"})
            return result["data"], result.get("input_tokens", 0), result.get("output_tokens", 0)
        except Exception as e:
            print(f"  [CRITICAL WARNING] Returning empty object due to persistent failure. Last error: {e}")
            return {}, 0, 0

    async def _run_agent_1_cognitive(self, text_slice: str, chapter_name: str, chapter_summary: str, concept_name: str) -> tuple[dict, int, int]:
        
        prompt = f"""
ROLE

You are a CBSE Curriculum Intelligence Expert, Educational Psychologist, Learning Scientist, and Knowledge Engineer.

==================================================
GLOBAL CONTEXT
Chapter: {chapter_name}
Chapter Summary: {chapter_summary}
Target Concept to Extract: {concept_name}
You must ensure all concepts, abilities, and skills extracted below perfectly align with the broader goals of this chapter.
==================================================

Your task is to transform textbook content into structured Concept Intelligence.

--------------------------------------------------
STAGE 1: KNOWLEDGE EXTRACTION
Definition: Knowledge = facts, principles, theories, laws, definitions, processes, relationships and conceptual understanding directly taught by the concept.
Instructions:
1. Extract atomic knowledge statements.
2. Each statement must be independently understandable.
3. Avoid learning objectives.
4. Avoid skills.
5. Avoid competencies.
6. Avoid pedagogy.
7. Avoid applications.
8. Normalize statements into canonical form.
Types: Fact, Definition, Principle, Law, Process, Rule, Relationship, Classification.

--------------------------------------------------
STAGE 2: ABILITY EXTRACTION
Definition: Ability = capability to apply knowledge in a meaningful context.
Rules: Abilities must start with action verbs. Use controlled vocabulary only: Explain, Interpret, Classify, Compare, Differentiate, Predict, Analyze, Evaluate, Apply, Model, Design, Solve.

--------------------------------------------------
STAGE 3: SKILL EXTRACTION
Definition: Skill = trainable capability strengthened through practice.
Rules:
1. Do not create subject content.
2. Create transferable skills.
3. Use standardized skill vocabulary (e.g., Problem Solving, Scientific Investigation, Observation, Experimentation, Classification, Communication, Reasoning, Data Interpretation, Model Building, Critical Thinking).

--------------------------------------------------
STAGE 4: COMPETENCY GENERATION
Definition: Competency = Knowledge + Ability + Skill demonstrated in context.

--------------------------------------------------
STAGE 7: BLOOM CLASSIFICATION
Classify every ability into: Remember, Understand, Apply, Analyze, Evaluate, Create.
CRITICAL RULE: DO NOT generate duplicate Bloom's levels. Each level in your output array must be UNIQUE. The coverage_scores MUST sum exactly to 100 across all items. DO NOT use 100% for all items unless there is literally only 1 level.

--------------------------------------------------
STAGE 8: DOK CLASSIFICATION
Classify every ability into:
Level 1 Recall
Level 2 Skill and Concept
Level 3 Strategic Thinking
Level 4 Extended Thinking
CRITICAL RULE: DO NOT generate duplicate DOK levels. Each level in your output array must be UNIQUE.

--------------------------------------------------
EVIDENCE REQUIREMENTS
Every major extraction must be supported by evidence. Use exact text quote whenever possible.

--------------------------------------------------
OUTPUT RULES
Return only data matching the supplied schema. No markdown. No explanations. No commentary.
CRITICAL RULE FOR REFERENCES: When filling out `knowledge_refs`, `ability_refs`, or `skill_refs`, you MUST write out the EXACT string value of the referenced item. DO NOT use shorthand identifiers like "K1", "K2", "A1", or "S1".

RAW TEXT:
"""
        return await self._generate_with_fallback(prompt=prompt, text_slice=text_slice, schema=Agent1CognitiveOutput)

    async def _run_agent_2_pedagogy(self, text_slice: str, agent1_json: dict, chapter_name: str, chapter_summary: str, concept_name: str) -> tuple[dict, int, int]:
        
        prompt = f"""
ROLE

You are a Master CBSE Teacher, Learning Experience Designer, Instructional Strategist, and Educational Researcher.

==================================================
GLOBAL CONTEXT
Chapter: {chapter_name}
Chapter Summary: {chapter_summary}
Target Concept to Extract: {concept_name}
Align all pedagogical strategies, real-world applications, and prerequisites with the overarching goals of this chapter.
==================================================

Your task is to extract Pedagogical Intelligence.

--------------------------------------------------
STAGE 9: MISCONCEPTION EXTRACTION
Identify common misconceptions associated with the concept.
Rules:
1. Extract misconceptions found in: textbooks, classroom observations, assessment literature
2. For each misconception provide: misconception statement, root cause, corrected understanding.

--------------------------------------------------
STAGE 10: REAL-LIFE APPLICATION EXTRACTION
Identify authentic real-world applications of the concept.
Classify under: Daily Life, Industry, Environment, Society.

--------------------------------------------------
STAGE 11: CONCEPT PREREQUISITE EXTRACTION
Identify prerequisite concepts required before mastering this concept.
Rules:
1. Only conceptual dependencies.
2. No chapter dependencies.
3. No curriculum dependencies.
4. Atomic concepts only.
5. CRITICAL RULE FOR PREREQUISITES: The prerequisite concept_name MUST NOT be the exact same as the concept currently being analyzed. It must refer to foundational knowledge required BEFORE learning this concept (e.g. from previous grades or previous chapters).

--------------------------------------------------
STAGE 12: PEDAGOGY RECOMMENDATION GENERATION
Recommend pedagogical approaches most effective for teaching the concept.
Choose from:
- Inquiry Based Teaching
- Experiential Based Teaching
- Art Integrated Teaching
- Game Based Teaching
- Activity Based Teaching
- Project Based Teaching
- Flashcard Based / Spaced Repetition Teaching
- Flipped Classroom Teaching
- Scenario Based Teaching
- Skill / Competency Based Teaching

--------------------------------------------------
CONCEPT RELATIONSHIPS
Extract relationships: depends_on, part_of, causes, uses, extends, related_to.

--------------------------------------------------
EVIDENCE REQUIREMENTS
Support every major pedagogical decision. Use direct quotes whenever possible.

--------------------------------------------------
OUTPUT RULES
Return only schema-compliant JSON. NO EXPLANATIONS.
CRITICAL RULE FOR REFERENCES: When filling out any reference array, you MUST write out the EXACT string value of the referenced item. DO NOT use shorthand identifiers like "K1", "K2", "A1", or "S1".

PREVIOUS AGENT EXTRACTED KNOWLEDGE (USE THIS AS CONTEXT):
{json.dumps(agent1_json, indent=2)}

RAW TEXT:
"""
        return await self._generate_with_fallback(prompt=prompt, text_slice=text_slice, schema=Agent2PedagogyOutput)

    async def _run_agent_3_assessment(self, text_slice: str, agent1_json: dict, agent2_json: dict, chapter_name: str, chapter_summary: str, concept_name: str, official_outcomes: str) -> tuple[dict, int, int]:
        
        prompt = f"""
ROLE

You are a Senior CBSE Assessment Architect, Psychometrician, Examination Designer, and Learning Outcome Specialist.

==================================================
GLOBAL CONTEXT
Chapter: {chapter_name}
Chapter Summary: {chapter_summary}
Target Concept to Extract: {concept_name}
Ensure all learning objectives, outcomes, and assessment blueprints test the overarching conceptual themes of this chapter.

OFFICIAL CURRICULUM OUTCOMES:
{official_outcomes}

CRITICAL RULE FOR LEARNING OUTCOMES: When generating learning_outcomes, you MUST strictly align and map the concept to these official outcomes wherever possible. If an outcome directly satisfies an official outcome, you should explicitly reference it.
==================================================

Your task is to create Assessment Intelligence.

--------------------------------------------------
STAGE 5: LEARNING OBJECTIVE GENERATION
Generate measurable learning objectives.
Rules:
1. One action verb only.
2. Must be teachable.
3. Must be measurable.
4. Use Bloom action verbs.

--------------------------------------------------
STAGE 6: LEARNING OUTCOME GENERATION
Generate observable learner outcomes.
Rules:
1. Evidence based.
2. Observable.
3. Assessable.
4. Student-centered.

--------------------------------------------------
ASSESSMENT BLUEPRINT
Create balanced assessment design.
For every assessment item determine:
assessment_type: MCQ, Assertion Reason, Case Study, Short Answer, Long Answer, Numerical, Practical, Project, Viva, HOTS, Competency Based Question
difficulty: Easy, Medium, Hard
Bloom Level: Remember, Understand, Apply, Analyze, Evaluate, Create
DOK Level: 1, 2, 3, 4
marks, recommended_question

--------------------------------------------------
EVIDENCE REQUIREMENTS
Every objective and outcome must be traceable to the source text. Use direct quotes where possible.

--------------------------------------------------
OUTPUT RULES
Return only schema-compliant JSON. NO EXPLANATIONS.
CRITICAL RULE FOR REFERENCES: When filling out any reference array, you MUST write out the EXACT string value of the referenced item. DO NOT use shorthand identifiers like "K1", "K2", "A1", or "S1".

PREVIOUS AGENT KNOWLEDGE EXTRACTION:
{json.dumps(agent1_json, indent=2)}

PREVIOUS AGENT PEDAGOGY EXTRACTION:
{json.dumps(agent2_json, indent=2)}
RAW TEXT:
"""
        return await self._generate_with_fallback(prompt=prompt, text_slice=text_slice, schema=Agent3AssessmentOutput)

    async def process_topic_slice(self, text_slice: str, chapter_name: str = "", chapter_summary: str = "", concept_name: str = "", official_outcomes: str = "") -> tuple[dict, int, int]:
        """
        The Orchestrator: Fires the 3 expert agents SEQUENTIALLY.
        Passes outputs of earlier agents into downstream agents for perfect cohesion.
        Merges their outputs perfectly into the final Topic Intelligence parameters.
        """
        print("Firing Sequential CBSE Expert Chain...")
        total_in = 0
        total_out = 0
        
        print("  -> Running Agent 1 (Cognitive Intelligence)...")
        out1, in1, out_tok1 = await self._run_agent_1_cognitive(text_slice, chapter_name, chapter_summary, concept_name)
        total_in += in1
        total_out += out_tok1
        
        print("  -> Running Agent 2 (Pedagogy Intelligence)...")
        out2, in2, out_tok2 = await self._run_agent_2_pedagogy(text_slice, out1, chapter_name, chapter_summary, concept_name)
        total_in += in2
        total_out += out_tok2
        
        print("  -> Running Agent 3 (Assessment Intelligence)...")
        out3, in3, out_tok3 = await self._run_agent_3_assessment(text_slice, out1, out2, chapter_name, chapter_summary, concept_name, official_outcomes)
        total_in += in3
        total_out += out_tok3
        
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
        
        # Override the concept name BEFORE validation to ensure prerequisites self-reference logic matches the canonical name
        if "concept" not in mega_concept_object or not mega_concept_object["concept"]:
            mega_concept_object["concept"] = {}
        if concept_name:
            mega_concept_object["concept"]["concept_name"] = concept_name
            
        # GUARANTEED FILTERING: Filter self-referencing prerequisites explicitly before Pydantic
        if concept_name and "prerequisites" in mega_concept_object:
            c_name_lower = concept_name.lower().strip()
            filtered_prereqs = []
            for p in mega_concept_object["prerequisites"]:
                p_name = str(p.get("concept_name", "")).lower().strip()
                if p_name != c_name_lower:
                    filtered_prereqs.append(p)
            mega_concept_object["prerequisites"] = filtered_prereqs
            
        # GUARANTEED MATH: Normalize Bloom's percentages explicitly before Pydantic
        if "blooms" in mega_concept_object:
            bloom_dict = {}
            for b in mega_concept_object["blooms"]:
                level = b.get("level")
                if level in bloom_dict:
                    bloom_dict[level]["coverage_score"] += float(b.get("coverage_score", 0))
                else:
                    bloom_dict[level] = b.copy()
                    bloom_dict[level]["coverage_score"] = float(b.get("coverage_score", 0))
            
            unique_blooms = list(bloom_dict.values())
            total_score = sum(b["coverage_score"] for b in unique_blooms)
            if total_score > 0:
                for b in unique_blooms:
                    b["coverage_score"] = round(b["coverage_score"] / total_score, 2)
            elif len(unique_blooms) > 0:
                even_score = round(1.0 / len(unique_blooms), 2)
                for b in unique_blooms:
                    b["coverage_score"] = even_score
            mega_concept_object["blooms"] = unique_blooms
        
        # ACTIVATE PYDANTIC VALIDATORS
        try:
            validated_obj = ConceptIntelligenceObject(**mega_concept_object)
            mega_concept_object = validated_obj.model_dump()
        except Exception as e:
            print(f"  [VALIDATION WARNING] Pydantic validation failed, falling back to raw dict: {e}")
        
        return mega_concept_object, total_in, total_out
