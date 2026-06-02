def build_structure_pass_prompt(markdown_content: str, subject: str, class_level: str) -> str:
    return f"""You are an expert curriculum analyst for {class_level} {subject}.

Read the chapter below and identify ONLY its structural skeleton.
Do not explain content. Only identify structure.

CRITICAL: NCERT textbooks contain special pedagogical boxes.
You MUST find and extract ALL of the following:

1. LET'S EXPLORE boxes — student inquiry tasks embedded in the chapter.
   These look like: "LET'S EXPLORE" followed by questions or tasks.
   -> Extract every one into chapter_apparatus.lets_explore_questions

3. "Don't Miss Out" / "Did you know?" boxes
   -> Extract every one into chapter_apparatus.dont_miss_out_facts

4. "Let's Remember" / Definitions
   -> Extract every one into chapter_apparatus.lets_remember_definitions

5. Exercises / Questions at the end of the chapter
   -> Extract all of them into chapter_apparatus.exam_questions

6. Chapter Summary / "What we have learnt"
   -> Extract all bullet points into chapter_apparatus.chapter_summary_points

These boxes are as educationally important as the main text.
Do NOT skip them. Do NOT summarize them. Extract the exact text.

For each section you find, identify:
- Its heading / title
- Its type: one of "theory" / "activity" / "exercise" / "formula" / "example" / "summary"
- Its approximate location (beginning / middle / end of chapter)
- A one-sentence description of what it covers

Return ONLY this JSON:
{{
  "chapter_title": "string",
  "short_summary": "2-3 sentences capturing the essence of the chapter",
  "learning_objectives": "What should the student achieve by the end?",
  "chapter_type": "science|social_science|language|mathematics|other",
  "has_activities": true,
  "has_formulas": true,
  "has_diagrams": true,
  "chapter_apparatus": {{
    "lets_explore_questions": [
      {{
        "question": "exact question text from the LET'S EXPLORE box",
        "location_hint": "which topic this appears near",
        "question_type": "map_activity | critical_thinking | observation | research",
        "linked_unit_id": "Unit_1"
      }}
    ],
    "dont_miss_out_facts": [
      {{
        "fact": "exact content from the DON'T MISS OUT box",
        "linked_unit_id": "Unit_2"
      }}
    ],
    "lets_remember_definitions": [
      {{
        "term": "exact term",
        "definition": "exact definition from the LET'S REMEMBER box",
        "linked_unit_id": "Unit_6"
      }}
    ],
    "chapter_summary_points": [
      "bullet point 1 from the Before we move on section",
      "bullet point 2"
    ],
    "exam_questions": [
      {{
        "number": 1,
        "question": "exact exam question text",
        "question_type": "opinion | factual | creative | map_based | project",
        "bloom_level": "Remember | Understand | Apply | Analyze | Evaluate | Create"
      }}
    ]
  }},
  "teaching_units": [
    {{
      "unit_id": "unit_1",
      "topic_title": "string",
      "section_type": "theory|activity|exercise|formula|example|summary",
      "one_line_description": "string",
      "estimated_importance": "high|medium|low"
    }}
  ]
}}

CHAPTER CONTENT:
{markdown_content}
"""


SUBJECT_PROFILES = {
    "science": {
        "emphasis": "Extract every formula, every experiment, every diagram, every scientific term definition.",
        "extra_fields": ["formulas", "experiments", "scientific_terms", "diagram_explanations"],
        "bloom_distribution": "Expect Remember and Understand for definitions, Apply for experiments.",
    },
    "mathematics": {
        "emphasis": "Extract every formula, theorem, proof step, and worked example. Show all calculation steps.",
        "extra_fields": ["formulas", "theorems", "worked_examples", "common_errors"],
        "bloom_distribution": "Expect Apply and Analyze levels mostly. Remember only for formulas.",
    },
    "social_science": {
        "emphasis": "Extract dates, events, people, causes, effects, maps described, and economic data.",
        "extra_fields": ["key_dates", "key_people", "causes_effects", "map_references"],
        "bloom_distribution": "Expect Remember for facts, Analyze for causes/effects, Evaluate for impacts.",
        "geography_note": """
        For geography chapters specifically:
        Extract every map task into a dedicated map_activities field per subtopic.
        Each map task should include:
        - instruction: the exact task
        - map_type: 'political' | 'physical' | 'outline' | 'atlas'
        - skill_type: 'location_identification' | 'route_tracing' | 'comparison' | 'labeling'
        """
    },
    "language": {
        "emphasis": "Extract literary devices, character analysis, themes, author context, important quotes.",
        "extra_fields": ["literary_devices", "characters", "themes", "important_quotes", "author_context"],
        "bloom_distribution": "Expect Analyze and Evaluate levels mostly. Remember only for facts.",
    },
    "hindi": {
        "emphasis": "Extract literary devices, character analysis, themes, author background, important lines.",
        "extra_fields": ["literary_devices", "characters", "themes", "important_lines", "author_context"],
        "bloom_distribution": "Focus on Analyze and Evaluate. Capture poetic devices if applicable.",
    },
}

def detect_subject_profile(subject_name: str) -> dict:
    name = subject_name.lower()
    if any(w in name for w in ["science", "physics", "chemistry", "biology"]):
        return SUBJECT_PROFILES["science"]
    if any(w in name for w in ["math", "maths", "mathematics"]):
        return SUBJECT_PROFILES["mathematics"]
    if any(w in name for w in ["social", "history", "geography", "civics", "economics"]):
        return SUBJECT_PROFILES["social_science"]
    if "hindi" in name:
        return SUBJECT_PROFILES["hindi"]
    if any(w in name for w in ["english", "language", "literature"]):
        return SUBJECT_PROFILES["language"]
    return SUBJECT_PROFILES["science"]  # default

def build_deep_extraction_prompt(
    unit_text: str,
    unit_title: str,
    chapter_title: str,
    subject: str,
    class_level: str,
    chapter_type: str,
) -> str:
    profile = detect_subject_profile(subject)
    subject_emphasis = profile["emphasis"]
    bloom_hint = profile["bloom_distribution"]
    
    return f"""You are an expert {subject} teacher for {class_level} in India.
You are deeply analyzing ONE section of the chapter "{chapter_title}".

Section title: {unit_title}
Subject type: {chapter_type}

Subject-specific instructions: {subject_emphasis}
Bloom's level guidance for this subject: {bloom_hint}
{profile.get('geography_note', '')}

Read this section carefully and extract COMPLETE educational intelligence.
Every field must be filled based strictly on the text. No hallucination.

Return ONLY this JSON:
{{

  "topic_title": "{unit_title}",
  "topic_summary": "2-3 sentence summary",
  "subtopics": [
    {{
      "subtopic_title": "string",
      "bloom_level": "Remember|Understand|Apply|Analyze|Evaluate|Create",
      "subtopic_summary": "1-2 sentences",
      "detailed_explanation": "Full explanation — minimum 3 sentences. Not from textbook. Your own teaching words.",
      "teacher_teaching_notes": "What to emphasize. Common student mistakes for this concept.",
      "real_life_connection": "Specific real-world example relevant to Indian students. Not generic.",
      "common_student_confusion": "What students typically misunderstand here.",
      "examples": ["example 1", "example 2"],
      "activities": ["activity if present in this section, else empty list"],
      "formulas": ["formula in plain text if present, else empty list"],
      "important_lines": ["key sentence directly from the text"],
      "diagram_explanations": ["what any diagram in this section shows and teaches"],
      "learning_outcomes": ["what student can DO after this subtopic"],
      "map_activities": [
        {{
          "instruction": "the exact task",
          "map_type": "political | physical | outline | atlas",
          "skill_type": "location_identification | route_tracing | comparison | labeling"
        }}
      ]
    }}
  ]
}}

SECTION TEXT:
{unit_text}
"""
