import os
import asyncio
import json
import random
from pydantic import BaseModel, Field
from typing import List
from dotenv import load_dotenv

# Import the massive user schema definitions
from .schemas import (
    Concept, KnowledgeItem, AbilityItem, SkillItem, CompetencyItem,
    BloomMapping, DOKMapping, Prerequisite, Misconception, RealWorldApplication,
    PedagogyRecommendation, ConceptRelationship, LearningObjective,
    LearningOutcome, AssessmentBlueprint, Evidence, ConceptIntelligenceObject,
    AssessmentItem, ConceptAssessmentRubric, OptionRationale, AcceptablePoint,
    TeachingNotes
)
from .rubric_reference import (
    build_ao_block, valid_ao_codes, build_level_descriptors,
    build_criterion_descriptors, build_hpc_descriptors,
    RUBRIC_TYPE_BY_ASSESSMENT_TYPE, uses_mark_bands, nep_stage,
    item_mix_guidance, subject_family, minimum_marks, min_marks_block,
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

# ----------------------------------------------------------
# Agent 4 draft models.
# The LLM supplies the question and the concept-specific content only.
# Level descriptors are assembled in Python from rubric_reference templates so
# that identical item shapes always carry identical bands.
# ----------------------------------------------------------

class CriterionDraft(BaseModel):
    criterion: str = Field(..., description="Criterion name, chosen from the supplied controlled list.")
    weight_marks: int = Field(..., description="Marks allocated to this criterion. All weights MUST sum to the item's total marks.")

class RubricItemDraft(BaseModel):
    question: str = Field(..., description="The full question text, answerable purely from the supplied source material.")
    assessment_type: str = Field(..., description="One of the 11 permitted CBSE assessment types.")
    difficulty: str = Field(..., description="Easy, Medium or Hard.")
    marks: int
    bloom_level: str
    dok_level: str = Field(..., description="Depth of Knowledge level: 1, 2, 3 or 4.")
    assessment_objectives: List[str] = Field(default_factory=list, description="CBSE AO codes assessed by this item. Use only codes valid for this subject.")
    skill_phrase: str = Field(..., description="Short noun phrase naming the capability assessed, e.g. 'the process of iron extraction and its environmental impact'. It is substituted into the level descriptors, so it must read naturally after 'A clear explanation of ...'.")
    source_evidence: List[str] = Field(default_factory=list, description="EXACT verbatim quotes from the supplied source text that this item is drawn from. Copy them character for character.")
    answer_key: List[OptionRationale] = Field(default_factory=list, description="MCQ / Assertion Reason only. Exactly four options, exactly one correct.")
    acceptable_points: List[AcceptablePoint] = Field(default_factory=list, description="Short Answer / Numerical only.")
    indicative_content: List[str] = Field(default_factory=list, description="Extended answers only. Expected content points; indicative, not exhaustive.")
    criteria: List[CriterionDraft] = Field(default_factory=list, description="Project / Practical / Viva only.")
    threshold_conditions: List[str] = Field(default_factory=list, description="Conditions gating the top mark bands.")
    common_errors: List[str] = Field(default_factory=list)

class Agent4RubricOutput(BaseModel):
    pedagogical_reasoning: str = Field(..., description="Step-by-step reasoning explaining how you chose the item mix, how the marks distribute across the official CBSE assessment objective weightings, and why each item is answerable from the source text. Write this before producing the items.")
    items: List[RubricItemDraft]
    teaching_notes: TeachingNotes

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

LANGUAGE & TRANSLATION POLICY (CRITICAL):
Since you are processing content that may be in Hindi or Sanskrit, you must strictly follow this language separation:
1. MUST BE IN ENGLISH (System Frameworks & Framing): 
   - The primary language of your responses, sentence structures, and action verbs.
   - Bloom's Levels, DOK Levels, and standardized Transferable Skills (e.g. "Critical Thinking").
   - The framing of Abilities/Competencies (e.g. "The student will be able to...").
2. MUST BE IN THE TARGET TEXT LANGUAGE (Hindi/Sanskrit):
   - The actual extracted Knowledge facts, formulas, vocabulary, grammar rules, and direct quotes.
Example of a good ability: "Explain the meaning of the Sanskrit shloka 'विद्या ददाति विनयम्' in daily life."
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

LANGUAGE & TRANSLATION POLICY (CRITICAL):
Since you are processing content that may be in Hindi or Sanskrit, you must strictly follow this language separation:
1. MUST BE IN ENGLISH (System Frameworks & Framing): 
   - The primary language of your responses, sentence structures, and action verbs.
   - Pedagogy types, generic prerequisites, and teaching strategies.
2. MUST BE IN THE TARGET TEXT LANGUAGE (Hindi/Sanskrit):
   - The actual extracted Misconceptions, root causes, and specific Real-World Applications.
Example of a good misconception: "Students often confuse the Hindi matras 'इ' and 'ई' when writing."
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

LANGUAGE & TRANSLATION POLICY (CRITICAL):
Since you are processing content that may be in Hindi or Sanskrit, you must strictly follow this language separation:
1. MUST BE IN ENGLISH (System Frameworks & Framing): 
   - The primary language of your responses, sentence structures, and action verbs.
   - Assessment Types (MCQ, Short Answer, etc.), Difficulty Levels, Bloom's Levels, and DOK levels.
   - The framing of Objectives/Outcomes (e.g. "The student will be able to...").
2. MUST BE IN THE TARGET TEXT LANGUAGE (Hindi/Sanskrit):
   - Specific grammar rules, vocabulary, poems, or text references being assessed.
Example of a good objective: "Conjugate the Sanskrit verb 'पठ्' (to read) in Lrt Lakar (Future Tense)."
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

    async def _run_agent_4_rubrics(self, text_slice: str, agent1_json: dict, agent2_json: dict, chapter_name: str, chapter_summary: str, concept_name: str, subject_name: str, class_level: str) -> tuple[dict, int, int]:

        ao_block = build_ao_block(subject_name, class_level)
        allowed_aos = ", ".join(valid_ao_codes(subject_name, class_level))
        stage = nep_stage(class_level)
        family = subject_family(subject_name)
        item_mix = item_mix_guidance(class_level)
        banded = uses_mark_bands(class_level)
        marks_rule = (
            "Assign whole-number marks to every item, appropriate to its depth.\n"
            "MINIMUM MARKS PER TYPE (these are hard floors, never go below them):\n"
            f"{min_marks_block()}\n"
            "Extended-response types (Long Answer, Case Study, HOTS, Competency Based "
            "Question) are marked with bands of quality, which need enough marks to "
            "separate. If a question is only worth 2 or 3 marks, it is a Short Answer, "
            "not a Case Study. Match the marks to the work you are actually asking for: "
            "a question requiring four identifications AND an explanation is worth at "
            "least 5 marks."
            if banded else
            f"This is the NEP {stage} stage (Classes 1-5). CBSE and NCERT assess this stage "
            "with qualitative descriptors under the Holistic Progress Card, NOT with marks. "
            "Set marks to 0 for every item. Performance is reported as Proficient / "
            "Progressing / Beginner, which is applied automatically."
        )
        misconceptions = agent2_json.get("misconceptions", []) if isinstance(agent2_json, dict) else []
        blooms = agent1_json.get("blooms", []) if isinstance(agent1_json, dict) else []
        dok = agent1_json.get("dok", []) if isinstance(agent1_json, dict) else []

        prompt = f"""
ROLE

You are a CBSE Chief Examiner, Mark Scheme Author, and Assessment Moderator, working to the CBSE Assessment Framework for Classes 6 to 10 (British Council / AlphaPlus, 2021).

==================================================
GLOBAL CONTEXT
Chapter: {chapter_name}
Chapter Summary: {chapter_summary}
Target Concept: {concept_name}
Subject: {subject_name} (assessment family: {family})
Class: {class_level}
NEP Stage: {stage}

ASSESSMENT OBJECTIVES FOR THIS SUBJECT AND CLASS:
{ao_block}

REQUIRED QUESTION MIX FOR THIS STAGE:
{item_mix}

MARKS POLICY FOR THIS STAGE:
{marks_rule}

Permitted AO codes for this subject: {allowed_aos}
Do not use any AO code outside this list.

COGNITIVE PROFILE OF THIS CONCEPT (from earlier analysis):
Bloom's coverage: {json.dumps(blooms, ensure_ascii=False)}
Depth of Knowledge: {json.dumps(dok, ensure_ascii=False)}

LANGUAGE & TRANSLATION POLICY (CRITICAL):
1. MUST BE IN ENGLISH (System Frameworks & Framing):
   - Assessment types, difficulty levels, Bloom's levels, DOK levels, AO codes.
   - Marking guidance, skill_phrase, common errors, and all teacher-facing notes.
2. MUST BE IN THE TARGET TEXT LANGUAGE (Hindi/Sanskrit):
   - The question text itself, option text, acceptable answers, indicative content,
     and any quoted subject matter.
Example: a Sanskrit item's question is in Sanskrit, while its skill_phrase reads
"the conjugation of the verb 'पठ्' in Lrt Lakar".
==================================================

Your task is to write assessment items for this concept, each with a complete CBSE-compliant mark scheme, using ONLY the source material supplied at the end.

--------------------------------------------------
STAGE 13: ITEM GENERATION
Generate 4 to 6 assessment items for this concept.
Rules:
1. Every item MUST be answerable from the supplied source text alone.
2. Do NOT assess material that is not present in the source text.
3. For every item, populate source_evidence with EXACT VERBATIM quotes copied
   character for character from the source text. These are checked programmatically;
   an item whose quotes cannot be found in the source will be rejected.
4. Use age-appropriate vocabulary for Class {class_level}.
5. Vary assessment_type across the set. Permitted types:
   MCQ, Assertion Reason, Case Study, Short Answer, Long Answer, Numerical,
   Practical, Project, Viva, HOTS, Competency Based Question.

--------------------------------------------------
STAGE 14: AO BALANCE
Distribute the marks across the items so that the totals approximate the official
CBSE assessment objective weightings listed above. Explain the resulting
distribution in your pedagogical_reasoning.

--------------------------------------------------
STAGE 15: MARK SCHEME SHAPE
The mark scheme shape follows strictly from assessment_type:
  MCQ, Assertion Reason              -> fill answer_key only
  Short Answer, Numerical            -> fill acceptable_points only
  Long Answer, Case Study, HOTS,
    Competency Based Question        -> fill indicative_content only
  Project, Practical, Viva           -> fill criteria only
Leave the other arrays empty. Do not deviate.

--------------------------------------------------
STAGE 16: ANSWER KEY (MCQ / Assertion Reason)
Provide exactly 4 options labelled A, B, C, D, with exactly one is_correct = true.
For every INCORRECT option, explain in rationale why a student would plausibly
choose it, and set misconception_tested to the EXACT misconception statement from
the list supplied below whenever one applies. Distractors must be diagnostic and
plausible, never absurd.

--------------------------------------------------
STAGE 17: POINT-BASED MARK SCHEME (Short Answer / Numerical)
List the creditworthy points, each with its mark value, following CBSE practice:
"Award 1 mark for each point, up to a maximum of N marks."
Supply equally creditworthy alternative phrasings for each point.
The point marks MUST sum to the item's total marks.

--------------------------------------------------
STAGE 18: INDICATIVE CONTENT (extended answers)
List the content points a strong answer would contain. This list is INDICATIVE AND
NOT EXHAUSTIVE: all valid and supported points earn credit.
Use threshold_conditions to state any requirement gating the top mark bands,
e.g. "For the highest two levels, the response must address both the chemical
process and its environmental impact."

DO NOT write level descriptors or mark bands. They are applied automatically from
the official CBSE band templates. Instead, supply skill_phrase: a short noun phrase
naming the capability the item assesses, which must read naturally in the sentence
"A clear, well-developed explanation of ____".

--------------------------------------------------
STAGE 19: ANALYTICAL RUBRIC (Project / Practical / Viva)
Choose 3 to 5 criteria from this controlled list ONLY:
Conceptual Understanding, Scientific Method / Process, Data Handling & Accuracy,
Analysis & Interpretation, Application & Relevance, Presentation & Communication,
Originality & Creativity, Record / Documentation, Viva / Oral Defence,
Collaboration & Teamwork.
Assign weight_marks to each. The weights MUST sum exactly to the item's total marks.
Do not write criterion descriptors; they are applied automatically.

--------------------------------------------------
STAGE 20: COMMON ERRORS
For each item, list the errors examiners should expect, so that marking is
consistent across schools.

--------------------------------------------------
STAGE 21: TEACHING NOTES (once for the whole concept)
Provide:
- key_vocabulary: terms students should use when answering on this concept.
- practical_activities: activities suitable for assessing demonstrate-level performance.
- blooms_verbs_used: the Bloom's action verbs appearing across these items.
- written_evidence_tips, oral_evidence_tips, experimental_evidence_tips: how a
  teacher should gather and judge evidence in each mode.

--------------------------------------------------
OUTPUT RULES
Return only schema-compliant JSON. No markdown. No commentary.
Marks must be positive integers. Every item needs at least one source_evidence quote.

KNOWN MISCONCEPTIONS FOR DISTRACTOR DESIGN:
{json.dumps(misconceptions, ensure_ascii=False)}

SOURCE TEXT:
"""
        return await self._generate_with_fallback(prompt=prompt, text_slice=text_slice, schema=Agent4RubricOutput)

    def _assemble_rubrics(self, draft: dict, text_slice: str, concept_name: str, subject_name: str, class_level: str) -> dict:
        """Turn Agent 4's draft into validated AssessmentItems.

        Applies the official band templates, verifies every source_evidence quote
        against the actual source text, and drops items that fail validation
        rather than persisting a malformed mark scheme.
        """
        if not isinstance(draft, dict) or not draft.get("items"):
            return {}

        def _norm(s: str) -> str:
            return " ".join(str(s).split()).lower()

        haystack = _norm(text_slice)
        allowed = set(valid_ao_codes(subject_name, class_level))
        slug = "".join(ch for ch in concept_name if ch.isalnum())[:20] or "CONCEPT"
        banded = uses_mark_bands(class_level)

        items = []
        for idx, raw in enumerate(draft.get("items", [])):
            if not isinstance(raw, dict):
                continue
            try:
                a_type = str(raw.get("assessment_type", "")).strip()
                rubric_type = RUBRIC_TYPE_BY_ASSESSMENT_TYPE.get(a_type)
                if rubric_type is None:
                    print(f"  [RUBRIC] Skipping item with unknown assessment_type '{a_type}'")
                    continue

                marks = int(raw.get("marks", 0))
                if marks < 0:
                    continue

                # Classes 1-5 are assessed with descriptors, not marks.
                if not banded:
                    marks = 0
                else:
                    # Trust the itemised breakdown over the stated total. If the
                    # model listed criterion weights or point values, those define
                    # the marks, so the two can never disagree and lose the item
                    # to a validation failure.
                    if rubric_type == "analytical":
                        weights = sum(int(c.get("weight_marks", 0)) for c in raw.get("criteria", [])
                                      if isinstance(c, dict))
                        if weights > 0:
                            marks = weights
                    else:
                        if rubric_type == "point_based":
                            points = sum(int(p.get("marks", 0)) for p in raw.get("acceptable_points", [])
                                         if isinstance(p, dict))
                            if points > 0:
                                marks = points
                        # Extended-response types need enough marks to band.
                        floor = minimum_marks(a_type)
                        if marks < floor:
                            print(f"  [RUBRIC] '{a_type}' item had {marks} marks; raising to the "
                                  f"CBSE minimum of {floor} so it can be banded.")
                            marks = floor
                    if marks <= 0:
                        continue

                skill_phrase = str(raw.get("skill_phrase", "")).strip() or concept_name

                # Verify grounding: every quote must appear in the source text.
                quotes = [q for q in raw.get("source_evidence", []) if str(q).strip()]
                verified = bool(quotes) and all(_norm(q) in haystack for q in quotes)

                # Keep only AO codes valid for this subject and class.
                aos = [a for a in raw.get("assessment_objectives", []) if a in allowed]

                item = {
                    "item_id": f"{slug}-Q{idx + 1}",
                    "question": raw.get("question", ""),
                    "assessment_type": a_type,
                    "rubric_type": rubric_type,
                    "difficulty": raw.get("difficulty", "Medium"),
                    "marks": marks,
                    "bloom_level": raw.get("bloom_level", "Understand"),
                    "dok_level": str(raw.get("dok_level", "2")),
                    "assessment_objectives": aos,
                    "skill_phrase": skill_phrase,
                    "source_evidence": quotes,
                    "evidence_verified": verified,
                    "threshold_conditions": raw.get("threshold_conditions", []),
                    "common_errors": raw.get("common_errors", []),
                }

                # Attach only the payload matching the mark scheme shape.
                if rubric_type == "answer_key":
                    item["answer_key"] = raw.get("answer_key", [])
                elif rubric_type == "point_based":
                    item["acceptable_points"] = raw.get("acceptable_points", [])
                elif rubric_type == "levels_of_response":
                    item["indicative_content"] = raw.get("indicative_content", [])
                    bands = build_level_descriptors(marks, skill_phrase, class_level)
                    if not bands:
                        # Unreachable once the mark floor is applied, but a rubric
                        # with no bands is unmarkable, so never persist one.
                        print(f"  [RUBRIC] Dropping '{a_type}' item: no mark bands "
                              f"could be built for {marks} marks.")
                        continue
                    item["level_descriptors"] = bands
                elif rubric_type == "analytical":
                    criteria = []
                    for c in raw.get("criteria", []):
                        if not isinstance(c, dict):
                            continue
                        name = c.get("criterion", "")
                        if not banded:
                            # Descriptor-only stages carry no per-criterion marks.
                            criteria.append({
                                "criterion": name,
                                "weight_marks": 0,
                                "level_descriptors": build_hpc_descriptors(name.lower()),
                            })
                            continue
                        weight = int(c.get("weight_marks", 0))
                        if weight <= 0:
                            continue
                        criteria.append({
                            "criterion": name,
                            "weight_marks": weight,
                            "level_descriptors": build_criterion_descriptors(name, weight),
                        })
                    item["criteria"] = criteria

                items.append(AssessmentItem(**item).model_dump())

            except Exception as e:
                print(f"  [RUBRIC] Dropping item {idx + 1} for '{concept_name}': {e}")
                continue

        if not items:
            return {}

        try:
            return ConceptAssessmentRubric(
                concept_name=concept_name,
                items=items,
                teaching_notes=draft.get("teaching_notes") or None,
            ).model_dump()
        except Exception as e:
            # Individual items are already dropped above, so a failure here is
            # in the surrounding wrapper. The three upstream agents have
            # already done their work; discarding the whole concept over it
            # would throw away four LLM calls.
            print(f"  [RUBRIC] Teaching notes rejected for '{concept_name}': {e}")
            return ConceptAssessmentRubric(
                concept_name=concept_name,
                items=items,
                teaching_notes=None,
            ).model_dump()

    async def process_topic_slice(self, text_slice: str, chapter_name: str = "", chapter_summary: str = "", concept_name: str = "", official_outcomes: str = "", subject_name: str = "", class_level: str = "") -> tuple[dict, int, int]:
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
        
        # Agents 3 and 4 both depend only on Agents 1 and 2, so they run
        # concurrently. Agent 4 works from the source text rather than Agent 3's
        # blueprint, so rubrics are grounded in the chapter and not in another
        # agent's unvalidated output.
        print("  -> Running Agent 3 (Assessment Intelligence) and Agent 4 (Assessment Rubrics) in parallel...")
        (out3, in3, out_tok3), (out4, in4, out_tok4) = await asyncio.gather(
            self._run_agent_3_assessment(text_slice, out1, out2, chapter_name, chapter_summary, concept_name, official_outcomes),
            self._run_agent_4_rubrics(text_slice, out1, out2, chapter_name, chapter_summary, concept_name, subject_name, class_level),
        )
        total_in += in3 + in4
        total_out += out_tok3 + out_tok4

        print("Chain complete. Merging Intelligence Dimensions...")

        # Apply the official CBSE band templates and verify rubric grounding.
        assembled_rubrics = self._assemble_rubrics(out4, text_slice, concept_name, subject_name, class_level)
        
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

            "assessment_rubrics": assembled_rubrics or None,

            # Every agent writes its reasoning before extracting, and it is billed
            # as output tokens regardless. Keep it so the extraction is auditable
            # instead of paying for reasoning nobody can read.
            "agent_reasoning": {
                "cognitive": out1.get("pedagogical_reasoning"),
                "pedagogy": out2.get("pedagogical_reasoning"),
                "assessment": out3.get("pedagogical_reasoning"),
                "rubrics": out4.get("pedagogical_reasoning") if isinstance(out4, dict) else None,
            },

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
