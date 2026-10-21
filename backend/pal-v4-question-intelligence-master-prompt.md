# Master Prompt v2 — PAL V4 Question Intelligence Bank

**Supersedes** `qbank-ingestion-master-prompt.md` for chapters where PAL
depth is required; **reuses its source-discovery, verification, and tier
mechanics unchanged** (Sections 2–3 below are carried over, not redesigned).
Use with Claude Code. Fill `{{CLASS}}`, `{{SUBJECT}}`, `{{CHAPTER}}`,
`{{SESSION}}` per run.

---

## 0. Objective — read before anything else

> **Do not build a 500-question database. Build a question intelligence
> system.** The number 500 is a ceiling, never a target to hit by any means.

For every chapter, optimize for, in this order of importance:

1. Curriculum + concept + sub-concept coverage
2. Prerequisite coverage (can PAL check foundations before teaching this?)
3. Bloom / cognitive-demand coverage
4. Misconception coverage (does a wrong answer tell us *why* it's wrong?)
5. Difficulty progression
6. Question-type and PAL-role diversity
7. Provenance and source quality
8. Only then: raw count, bounded 250 (floor) – 500 (ceiling)

**Never create a duplicate or a weak item to close a gap toward 250.** A
chapter with 180 excellent, fully-mapped questions is a better deliverable
than 500 with thin or duplicated metadata. Report the shortfall instead.

## 1. Mandatory-core vs. optional-rich fields

This is the fix for schema overload. Every question **must** carry the
**core fields** (Section 7) to pass the quality gate and count toward the
target. **Rich fields** (Section 8: distractor intelligence, next-action
rules, pedagogy, career/KASBA, IRT-style discrimination estimate) are filled
**only where the source material or question genuinely supports them** —
leave them `null`/empty rather than inventing a plausible-sounding value.
Do not let filling rich fields become a reason to rush or skip core-field
accuracy, and do not let pursuit of rich fields on every item slow a run to
the point real sourcing (Section 3) gets shortchanged.

---

## 2. Source discovery — carried over from v1, unchanged

Run `qbank-ingestion-master-prompt.md` Section 1 as-is: content sources
(Tiers A–H, with G1 = verified private-school Q&A content only) vs.
practice-evidence sources (SAFAL, CBE framework, school workshop/policy
pages — inform schema/vocabulary, never extracted as literal questions).

## 3. Verification gate — carried over from v1, unchanged

Run v1 Section 2 as-is: `web_fetch` every candidate URL before it enters
the corpus; log rejects in `rejected.md`; no domain-pattern guessing.

## 4. Source hierarchy — carried over from v1, with SAFAL anchor

```
A (Curriculum authority) > B (Official SQP+MS) > SAFAL/CBE (competency
vocabulary) > C (KVS/ZIET) > D (CBSE competency banks) > E (DIKSHA)
> F (JNV — pattern only) > G1 (verified private-school content)
> G2 (practice-evidence — schema only) > H (secondary)
```

## 5. Acquisition sequence — source first, generate only the gap

```
1. Build the chapter's Concept Intelligence map from curriculum (Section 6)
   BEFORE sourcing questions — you need to know what to look for.
2. Run source discovery + verification (Sections 2–3).
3. Extract every verified question; map each to the concept map.
4. Deduplicate (same concept + near-identical phrasing → one item,
   multiple source_urls logged).
5. Measure coverage against the concept map: which concepts,
   sub-concepts, Bloom levels, difficulty bands, misconceptions, and
   PAL roles are still empty or thin?
6. Generate ONLY to fill measured gaps — each generated item must be
   grounded in at least one `sourced_verbatim` example for the same
   concept (never generated from a bare description).
7. Run every item (sourced and generated) through the quality gate
   (Section 9).
8. Produce the coverage report (Section 11).
```

Never start by telling the model "create 500 questions." Start by building
the concept map, then let sourcing and the gap analysis determine the
actual count.

## 6. Concept Intelligence — build this first, per chapter

```json
{
  "chapter_concept_map": {
    "chapter": "",
    "concepts": [
      {
        "concept_id": "",
        "concept_name": "",
        "sub_concepts": [{"sub_concept_id": "", "sub_concept_name": ""}],
        "learning_objective": "",
        "prerequisite_concepts": [],
        "dependent_concepts": [],
        "known_misconceptions": [
          {"misconception_id": "", "description": ""}
        ]
      }
    ]
  }
}
```

Populate `known_misconceptions` from actual evidence (a KVS/CBSE competency
resource that names a common error, or a pattern observed across multiple
sourced distractors) — never invent a misconception with no basis.

## 7. Core fields — mandatory, gate the quality check (Section 9)

```json
{
  "question_id": "",
  "class": "", "subject": "", "chapter": "", "session": "",

  "question_text": "", "question_type": "",
  "options": [], "correct_answer": "", "answer_explanation": "",
  "marks": null, "mark_scheme": "", "rubric": "",

  "concept_id": "", "concept_name": "",
  "sub_concept_id": "", "sub_concept_name": "",
  "learning_objective": "",
  "prerequisite_concepts": [],
  "bloom_level": "", "cognitive_demand": "",

  "difficulty": {"band": "easy|moderate|difficult", "score": null, "reason": ""},

  "misconception": {"applicable": false, "misconception_id": "", "description": ""},

  "pal": {"applicable": true, "role": []},

  "exam_assessment": {
    "applicable": true,
    "cbse_pattern_match": "board_official|school_internal_proxy",
    "assessment_objective": ""
  },

  "provenance": {
    "source_tier": "A|B|C|D|E|F|G1|H",
    "source_school": "",
    "source_url": "",
    "document_title": "",
    "publication_year": "",
    "extraction_method": "pdf|ocr|html|manual",
    "verified": true,
    "copyright_status": "government_public_use|school_internal_material|publisher_copyrighted|unknown",
    "validation_status": "sourced_verbatim|ai_rephrased|ai_generated_from_pattern"
  }
}
```

`pal.role` uses the taxonomy in Section 8 — this one sub-field of `pal` is
core (every question needs at least one role or `applicable: false`), even
though the richer PAL fields (next-action rules) are optional.

**`copyright_status` matters practically, not just for completeness:**
Tier A–F (government) content is generally safe for internal/derivative use;
Tier G1 (private-school) and Tier H (commercial publisher) content carries
real copyright risk if reproduced verbatim in a commercial product rather
than used as a pattern reference — flag anything `publisher_copyrighted`
for legal review before it ships in a paying customer's exam paper.

## 8. Rich fields — optional, fill only where evidence supports them

```json
{
  "difficulty_detail": {
    "estimated_grade_level": null,
    "reason_detail": [],
    "discrimination_estimate": null
  },

  "distractor_intelligence": [
    {"option": "", "misconception_id": "", "diagnostic_meaning": "", "remediation_concept": ""}
  ],

  "diagnostic": {
    "diagnostic_value": null,
    "mastery_signal": "",
    "prerequisite_test": false
  },

  "next_action_rules": {
    "correct": {"high_confidence": "advance", "medium_confidence": "practice", "low_confidence": "concept_check"},
    "incorrect": {"misconception_detected": "remediation", "prerequisite_gap": "prerequisite_remediation", "unknown": "diagnostic_probe"}
  },

  "h5p": {"supported": false, "interaction_type": "", "alternative_types": []},

  "pedagogy": [],

  "career_intelligence": {
    "applicable": false,
    "skill": [], "ability": [], "interest": [], "industry": [], "job_role": []
  }
}
```

- `distractor_intelligence`: fill for MCQs where a wrong option maps to a
  *real, evidenced* misconception (from Section 6's known-misconceptions
  list or from a sourced document that explains the distractor). Never
  invent a misconception rationale for a distractor that's simply a
  plausible-sounding wrong number/date/name with no diagnostic meaning.
- `next_action_rules`: only where the PAL orchestrator (confirm with the
  PAL V4 team) actually consumes per-question next-action data today —
  otherwise this is metadata with no reader yet; note in `run_summary.md`
  if left empty for that reason rather than guessing plausible defaults.
- `pedagogy`: only assign where the question's *form* genuinely constrains
  pedagogy (e.g. a case-study question suits problem-based learning) — not
  as a default tag added to hit a completeness score.
- `career_intelligence`: `applicable: false` is the default; only set true
  where the concept has a real, sourced career connection (per the earlier
  Career Intelligence module's own scope), not for every application-type
  question.

## 9. Quality gate — before a question counts toward the target

- [ ] All Section 7 core fields present and non-placeholder.
- [ ] `mark_scheme` or `rubric` present unless a plain single-answer MCQ.
- [ ] `provenance.source_url` verified per Section 3, or
      `validation_status: ai_generated_from_pattern` with a grounding
      `sourced_verbatim` sibling item logged.
- [ ] No near-duplicate `question_text` already tagged with the same
      `concept_id`.
- [ ] If `misconception.applicable: true`, the misconception is evidenced
      (Section 6), not invented.
- [ ] `copyright_status` set; anything `publisher_copyrighted` flagged in
      `run_summary.md` for review, not silently ingested.
- [ ] Rich fields (Section 8), if present, are evidenced — an empty rich
      field is acceptable; a fabricated one is not and fails the gate.

## 10. Volume target — 250 floor, 500 ceiling, quality-gated

Same rule as v1: pull from every available content tier before generating;
generate only to close a measured gap (Section 5); never pad with Tier H
or near-duplicates; report a genuine shortfall rather than inflate. A
question failing Section 9 does not count, regardless of how close the
chapter is to 250.

## 11. Coverage report — end of every run

`run_summary.md` must report:

1. Total questions; sourced vs. ai_rephrased vs. ai_generated_from_pattern counts
2. Concept / sub-concept / prerequisite coverage (which are still gaps)
3. Bloom distribution; difficulty-band distribution; question-type distribution
4. PAL-role distribution; misconception coverage; diagnostic-question count
5. Rich-field fill rate (distractor intelligence, next-action, pedagogy,
   career) — and *why* low, if low (no evidence available vs. not attempted)
6. Rejected/duplicate count and reasons
7. `copyright_status` breakdown, with anything flagged for legal review
8. Unresolved concept/coverage gaps and what real source would close them

## 12. Guardrails

- Everything in v1 Section 8 (Section 8 there) still applies: no fabricated
  URLs, no extracting "questions" from practice-evidence pages, no Tier H
  overriding A–G1, no volume pressure justifying a skipped verification or
  quality-gate step, no silently blending curriculum-transition sessions.
- Do not treat a fully-populated rich-field set as a proxy for quality —
  a core-complete, evidence-grounded question with empty rich fields beats
  a core-complete question with fabricated rich fields, every time.
- Do not let "PAL V4 needs richer metadata" become license to skip the
  acquisition-first sequence (Section 5) — richness describes *what's
  captured about* a sourced question, not a reason to generate first and
  source later.
