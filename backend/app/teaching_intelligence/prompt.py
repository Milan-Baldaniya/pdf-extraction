"""Phase 3 Gemini prompt builder — teaching intelligence generation.

Transforms Phase 2 educational JSON into slide-by-slide teaching plans.
Each subtopic from Phase 2 produces one slide_teaching_plan entry.
"""

from __future__ import annotations

import json

# ─── Teaching Style Persona Instructions ────────────────────────────────────

STYLE_INSTRUCTIONS = {
    "engaging": (
        "Use energy and enthusiasm. Open every concept with a hook or relatable question. "
        "Include memorable analogies. Make students want to lean in and listen."
    ),
    "storytelling": (
        "Frame every concept as a mini-story: a problem or mystery at the start, "
        "the explanation in the middle, an insight or resolution at the end."
    ),
    "serious": (
        "Be clear, precise, and academic. No jokes or informal language. "
        "Focus on accuracy and formal definitions. Exam-oriented."
    ),
    "activity_based": (
        "Center every concept around a hands-on activity or observation. "
        "Make student participation the primary teaching method."
    ),
    "exam_focused": (
        "Emphasize what commonly appears in exams. Lead with key definitions. "
        "Include MCQ-style questions. Highlight marks-worthy points explicitly."
    ),
}

# ─── Difficulty Level Instructions ──────────────────────────────────────────

DIFFICULTY_INSTRUCTIONS = {
    "simplified": "Use very simple language. Short sentences. Many everyday examples.",
    "grade_level": "Use standard language appropriate for this class level.",
    "advanced": "Use precise vocabulary. Include depth beyond the textbook.",
}

# ─── Language Instructions ──────────────────────────────────────────────────

LANGUAGE_INSTRUCTIONS = {
    "english": "Write the entire response in English.",
    "hindi": "Write the entire response in Hindi using Devanagari script.",
    "bilingual": "Write in English but include Hindi translations for all key terms in brackets.",
}

# ─── Subject-Specific Teaching Guidance ─────────────────────────────────────

SUBJECT_TEACHING_NOTES = {
    "science": (
        "For science: build curiosity around every phenomenon. Use the question "
        "'Why does this happen?' as a teaching anchor. Connect formulas to real experiments."
    ),
    "mathematics": (
        "For mathematics: show every step. Anticipate calculation errors. "
        "Use visual number patterns where possible."
    ),
    "social_science": (
        "For social science and geography: always anchor concepts to maps or timelines. "
        "Help students visualize places, movements, and causes-effects."
    ),
    "language": (
        "For language/literature: bring characters and themes alive. "
        "Read important lines with expression. Connect themes to student experiences."
    ),
    "hindi": (
        "For Hindi: pay attention to poetic devices and literary beauty. "
        "Explain the emotion and cultural context behind the text."
    ),
}


def _get_subject_note(subject_name: str) -> str:
    """Select the appropriate subject-specific teaching guidance."""
    name = subject_name.lower()
    if any(w in name for w in ["science", "physics", "chemistry", "biology"]):
        return SUBJECT_TEACHING_NOTES["science"]
    if any(w in name for w in ["math", "maths", "mathematics"]):
        return SUBJECT_TEACHING_NOTES["mathematics"]
    if any(w in name for w in ["social", "history", "geography", "civics"]):
        return SUBJECT_TEACHING_NOTES["social_science"]
    if "hindi" in name:
        return SUBJECT_TEACHING_NOTES["hindi"]
    return SUBJECT_TEACHING_NOTES["language"]


def build_teaching_intelligence_prompt(
    phase2_json: dict,
    teaching_style: str = "engaging",
    language: str = "english",
    difficulty_level: str = "grade_level",
) -> str:
    """Build the Phase 3 Gemini prompt from Phase 2 intelligence JSON.

    Args:
        phase2_json: The full_intelligence_json from chapter_semantic_intelligence.
        teaching_style: One of engaging/storytelling/serious/activity_based/exam_focused.
        language: One of english/hindi/bilingual.
        difficulty_level: One of simplified/grade_level/advanced.

    Returns:
        A fully formed Gemini prompt string.
    """
    style_note = STYLE_INSTRUCTIONS.get(teaching_style, "")
    difficulty_note = DIFFICULTY_INSTRUCTIONS.get(difficulty_level, "")
    language_note = LANGUAGE_INSTRUCTIONS.get(language, "")
    subject_note = _get_subject_note(phase2_json.get("subject", ""))
    phase2_str = json.dumps(phase2_json, indent=2, ensure_ascii=False)
    chapter_title = phase2_json.get("chapter_title", "this chapter")
    class_level = phase2_json.get("class", "")
    subject = phase2_json.get("subject", "")

    return f"""You are an expert classroom teacher with 20 years of teaching experience
in Indian schools. You have deep knowledge of {subject} for {class_level}.
You know exactly how to make students pay attention, understand concepts deeply,
and remember them long after the lesson ends.

TEACHING STYLE: {teaching_style}
Style instructions: {style_note}

DIFFICULTY LEVEL: {difficulty_level}
Language instructions: {difficulty_note}

LANGUAGE: {language_note}

SUBJECT GUIDANCE: {subject_note}

CHAPTER: {chapter_title}

EDUCATIONAL CONTENT (semantic inteligance analysis — your teaching source):
{phase2_str}

YOUR TASK:
For EVERY subtopic in EVERY teaching_unit above, generate one slide_teaching_plan.
Think of each subtopic as ONE slide in a classroom presentation.
Each slide_teaching_plan is your complete lesson plan for that one slide.

IMPORTANT RULES:
1. Generate one entry for EVERY subtopic. Do NOT skip or combine any.
2. teacher_narration must sound like a real teacher speaking to students.
   Use "you" and "we". Do NOT write like a textbook or encyclopedia.
3. student_hook must create genuine curiosity. It is the FIRST thing said on the slide.
4. classroom_activity must be specific and doable in 2 minutes or less.
5. Use the bloom_level from Phase 2 to guide your teaching approach:
   Remember → definition + memory trick
   Understand → analogy + explanation
   Apply → worked example + activity
   Analyze → comparison + discussion question
   Evaluate → debate or judgment prompt
   Create → design or project challenge

ALSO: If the Phase 2 JSON contains a chapter_apparatus field, use it:
- lets_explore_questions → use as interaction_points for the relevant slide
- dont_miss_out_facts → add as memorable wow-facts inside teacher_narration
- exam_questions → include relevant ones in revision_points

Return ONLY valid JSON. No markdown. No explanation. No code blocks.

{{
  "chapter_title": "{chapter_title}",
  "teaching_style": "{teaching_style}",
  "language": "{language}",
  "difficulty_level": "{difficulty_level}",
  "slide_teaching_plans": [
    {{
      "unit_id": "string — matches unit_id from Phase 2",
      "topic_title": "string — matches topic_title from Phase 2",
      "subtopic_title": "string — matches subtopic_title from Phase 2",
      "bloom_level": "string — copied from Phase 2",
      "slide_number": 1,
      "teacher_narration": "string — exactly what you say to the class. 3-5 sentences. Natural speech. Use you/we.",
      "student_hook": "string — the FIRST sentence before explaining. Creates curiosity. Max 2 sentences.",
      "storytelling_style": "string — how this concept is framed as a story or journey.",
      "attention_strategy": "string — one specific technique to hold student focus.",
      "visual_metaphor": "string — a comparison that makes this concept immediately clear.",
      "classroom_activity": "string — specific activity students do. Doable in under 2 minutes.",
      "interaction_points": "string — a question to ask mid-explanation. Not yes/no.",
      "teaching_pacing": "slow_and_detailed | medium | quick_overview",
      "emotion_curve": "build_curiosity | maintain_energy | create_surprise | reflective",
      "visual_scene_description": "string — what the slide should look like. Colors, mood, layout direction.",
      "slide_visual_goal": "string — the one impression this slide must leave in the student's mind.",
      "key_takeaway": "string — the ONE sentence students must remember. Short and clear.",
      "diagram_teaching_explanation": "string — if there is a diagram, how to walk students through it step by step.",
      "teacher_board_notes": "string — what you would write on the board for this concept.",
      "common_student_questions": ["question 1", "question 2"],
      "memory_tricks": ["mnemonic or trick 1", "trick 2"],
      "revision_points": ["point 1", "point 2", "point 3"]
    }}
  ]
}}
"""
