# Master Prompt — CBSE/NCERT Question Bank Sourcing & Dual-Purpose Ingestion

**Use this with Claude Code.** Paste as-is, then fill in `{{CLASS}}`, `{{SUBJECT}}`,
`{{SESSION}}` per run. One run = one class + subject + session combination.

---

## 0. Context (do not skip)

ScholarClone needs question/answer material for **two distinct downstream
consumers**, and every ingested item must be tagged for the right one(s):

1. **Exam & Assessment module** — CBSE/NCERT-compliant, board/school-facing.
   Feeds question papers, marking schemes, report cards. Must match the
   *actual* current-session pattern (question types, marks split,
   competency-vs-rote ratio) a school can defend to a parent or inspector.
2. **PAL (Concept Intelligence / adaptive quiz)** — formative, continuous,
   diagnostic. Feeds concept mastery, misconception detection, prerequisite
   gaps. Doesn't need to look like an exam paper — needs to be tagged at the
   concept/sub-concept/cognitive-demand level.

A single sourced question can feed both, but the **tags differ** — see
Section 5.

This run optimizes for **two criteria at once, and neither may be sacrificed
for the other**: **Quantity** (Section 6 — 250–500 verified questions per
chapter) and **Quality** (Section 4 — every question carries complete,
validated metadata: learning outcome, competency, cognitive demand, rubric,
expected evidence). A large pile of untagged questions is not a deliverable
here, and neither is a small set of perfectly tagged ones — both bars must
clear.

**Board-class rule:** CBSE publishes official SQP+MS (Sample Question Paper +
Marking Scheme) only for **Class 10 and Class 12**, at cbseacademic.nic.in,
because only those are board-exam years. For Classes 6–9 and 11, there is
**no official CBSE exam paper** — schools set their own papers, guided by
CBSE's curriculum/competency framework. For those classes, treat KVS SSM,
ZIET question banks, and CBSE's CBE competency item banks as the closest
real-world proxy for compliant pattern — not as a substitute for an official
paper, because none exists at that grade.

**SAFAL as the competency reference point:** CBSE's SAFAL (Structured
Assessment For Analyzing Learning) is a real, confirmed, NEP-2020-mandated
competency-based diagnostic assessment run at Grades 3, 5, and 8 — it is
CBSE's own working definition of "competency-based," not a school's
interpretation of one. Where SAFAL's public framework (core concepts,
application of knowledge, higher-order thinking) and a school's stated
practice disagree on what "competency-based" means, SAFAL/CBSE wins — see
Section 3.

---

## 1. Source discovery — do this first, every run

**First distinguish two different kinds of source**, because they're used
differently and conflating them wastes a run:

- **Content sources** — publish actual question+answer material you can
  extract and put in the bank (a PDF, a downloadable question set).
- **Practice-evidence sources** — publish descriptions of *how* a school or
  board assesses (a workshop writeup, a policy page, a circular). These have
  **no literal questions to extract**. Use them only to validate/refine the
  metadata schema in Section 4 (which competencies matter, what a good
  rubric looks like, how assessment stages differ by grade) — never attempt
  to pull "questions" out of a narrative page. If a candidate URL turns out
  to be a blog-style writeup describing a workshop rather than a document
  with actual Q&A content, file it as practice-evidence, not content, even
  if it's Tier A–G by domain.

Search for and confirm, for `{{CLASS}}` / `{{SUBJECT}}` / `{{SESSION}}`:

### Content sources (extract literal Q&A)

- **A — Curriculum authority:** CBSE curriculum/syllabus PDF at
  cbseacademic.nic.in for this class+session; NCERT syllabus/textbook for
  the same.
- **B — Official exam pattern** (Class 10/12 only): CBSE SQP + MS at
  cbseacademic.nic.in.
- **C — KVS/ZIET material:** KVS Student Support Material (SSM), KVS/ZIET
  question banks, via official `*.kvs.ac.in`, `kvs.gov.in`, or
  `zietmysore.kvs.gov.in` domains only.
- **D — CBSE competency evidence:** CBE/SAS competency-based test items and
  item banks at `cbseacademic.nic.in/cbe/`.
- **E — DIKSHA:** CBSE-aligned practice question collections at
  `diksha.gov.in`.
- **F — JNV (Navodaya Vidyalaya Samiti) entrance-test material:** JNVST
  previous-year papers and syllabus at `navodaya.gov.in`. **Note the
  difference from KVS**: this is a *selection/entrance test* (on the prior
  grade's syllabus, aptitude-weighted), not a chapter-wise teacher-authored
  Student Support Material. Use for exam-pattern and aptitude-style question
  evidence, not as a primary concept/competency source.
- **G1 — Private-school Q&A content** (rare): a specific, verified page from
  DPS, Bal Bharati, Shiv Nadar School, National Public School, CMR NPS,
  Lotus Valley, DAV, BBPS, or similar, that hosts an actual downloadable
  sample paper, worksheet, or question set — not a policy/blog page. These
  are franchise/society networks, **not single centralized organizations**:
  each individual school runs its own site, and only some publish material
  publicly (many are behind a parent/student login). Treat as **per-school,
  per-URL verified only** — never assume a domain pattern, and never assume
  one branch's material implies another branch has the same. Log the exact
  school (e.g. "DPS RK Puram" vs "DPS Faridabad") against each item.
- **H — Secondary (lowest priority, pattern reference only):** Vedantu,
  Infinity Learn, SelfStudys, LearnCram, AglaSem, Educart, Oswaal, Tiwari
  Academy. Never treat these as ground truth for concept/competency
  mapping — use only to sanity-check coverage gaps against A–G1.

### Practice-evidence sources (inform Section 4's schema only — no extraction)

- **CBSE SAFAL** (`cbseacademic.nic.in/safal/`) — the board's own working
  definition of competency-based diagnostic assessment. Use to validate the
  `competency` and `cognitive_demand` vocabulary in Section 4.
- **CBSE CBE framework/teacher-resources pages** (`cbseacademic.nic.in/cbe/`)
  — assessment objectives, learning-framework language.
- **G2 — Private/KVS workshop and policy writeups**: e.g. a school's
  "diagnostic assessment workshop" page, an academic planner, an assessment
  policy page. Read these for pattern (what evidence types they use: oral,
  project, portfolio, peer-assessment) to inform whether a given extracted
  question should also carry an `evidence_type` beyond "written test" — but
  do not create question records from them.
- Treat any KVS circular reproduced on a third-party site (e.g. Scribd) as
  **secondary/unverified** until the same content is found on an official
  `.kvs.ac.in`/`.gov.in` page — note this explicitly if used at all.

## 2. Verification gate — mandatory before any URL enters the corpus

For every candidate URL:

1. `web_fetch` it directly. If it 404s, redirects to an unrelated page, or
   you cannot confirm it resolves to the claimed document, **discard it** —
   do not include it "as reported."
2. Never accept a URL pattern by inference (e.g. guessing another subject's
   PDF exists because one subject's did, by editing the filename/ID).
   Each URL must be independently confirmed reachable.
3. Log discarded/unverifiable candidates in a `rejected.md` file with the
   claimed source and reason, so the next run doesn't re-attempt them blind.
4. Domains ending in `.kvs.ac.in`, `.kvs.gov.in`, `cbseacademic.nic.in`,
   `ncert.nic.in`, `diksha.gov.in` count as Tier A/B/C/D/E. `navodaya.gov.in`
   counts as Tier F. A specific private-school domain (e.g. `dpsrkp.net`)
   counts as Tier G1 **only for that verified URL, and only if it hosts an
   actual downloadable Q&A document** — a workshop/policy writeup on the
   same domain is G2 (practice-evidence), not G1, regardless of domain.
   Anything else, however well-formatted, is Tier H.

## 3. Source hierarchy (for conflict resolution)

When sources disagree on a concept, competency label, or question pattern,
resolve in this order — higher tier wins:

```
A (Curriculum authority)
  > B (Official SQP+MS, board classes only)
  > SAFAL/CBE (competency vocabulary authority — see Section 0)
  > C (KVS/ZIET)
  > D (CBSE competency banks)
  > E (DIKSHA)
  > F (JNV entrance-test — pattern evidence, not concept authority)
  > G1 (Verified private-school Q&A content — per-URL only)
  > G2 (Practice-evidence — informs schema, never overrides a tag)
  > H (Secondary — never overrides A–G1)
```

## 4. Quality schema — apply to every extracted question

This is the metadata every question must carry before it counts toward the
Section 6 volume target. A question with `question_text` and `answer_text`
but missing the fields below is **incomplete, not done** — do not count it
as filling the quota until tagging is complete.

```json
{
  "question_id": "",
  "class": "",
  "subject": "",
  "chapter": "",
  "session": "",
  "source_tier": "A|B|C|D|E|F|G1|H",
  "source_school": "",
  "source_url": "",
  "verified": true,
  "validation_status": "sourced_verbatim|ai_rephrased|ai_generated_from_pattern",

  "question_text": "",
  "answer_text": "",
  "mark_scheme": "",
  "rubric": "",
  "expected_evidence": "",
  "question_type": "MCQ|short_answer|long_answer|case_based|assertion_reason|competency|extrapolation",
  "marks": null,

  "learning_outcome": "",
  "content_domain": "",
  "assessment_objective": "",
  "concept": "",
  "sub_concept": "",
  "prerequisite": [],
  "competency": "",
  "cognitive_demand": "",
  "misconception_flag": "",

  "exam_assessment": {
    "applicable": true,
    "cbse_pattern_match": "board_official|school_internal_proxy",
    "difficulty_band": "easy|moderate|difficult"
  },

  "pal_concept_intelligence": {
    "applicable": true,
    "h5p_interaction_type": ""
  }
}
```

Notes:

- `validation_status` matters: `sourced_verbatim` (came directly from a
  Tier A–G1 document) outranks `ai_rephrased` (Claude reworded a sourced
  question) which outranks `ai_generated_from_pattern` (Claude wrote a new
  question modeled on verified examples, because a chapter fell short of
  250 on sourced content alone — see Section 6). Never silently upgrade an
  `ai_generated_from_pattern` item's tier to look sourced.
- `learning_outcome`, `competency`, and `cognitive_demand` must use
  vocabulary consistent with SAFAL/CBE (Section 0/3), not an invented or
  source-specific label — if a KVS document uses different wording than
  CBSE's CBE framework for the same idea, normalize to CBE's term and note
  the original KVS wording in a comment field.
- A question can have `exam_assessment.applicable: false` if it's too
  open-ended/creative for a formal paper but great for PAL (or vice versa —
  `pal_concept_intelligence.applicable: false` for a purely rote-recall
  item with no diagnostic value).

## 5. Quality gate — before a question is accepted into either bank

Reject or send back for completion any item that fails any of these:

- [ ] `question_text` and `answer_text` are both non-empty and coherent
      (not truncated mid-sentence from a bad PDF extraction).
- [ ] `learning_outcome`, `competency`, `cognitive_demand`, and `concept`
      are filled — not left blank or set to a placeholder.
- [ ] `mark_scheme` or `rubric` is present for anything other than a
      straightforward MCQ with a single correct option.
- [ ] `source_tier` and `source_url` are set, and `verified: true` only if
      Section 2's gate actually passed for that URL.
- [ ] If `validation_status: ai_generated_from_pattern`, at least one
      `sourced_verbatim` example for the same concept/competency exists in
      the bank that it was modeled on — never generate from a description
      alone with no grounding example.
- [ ] No duplicate `question_text` (near-identical phrasing) already exists
      tagged with the same `concept` — see Section 6's dedup rule.

## 6. Volume target — per chapter

**Minimum 250, maximum 500 questions per chapter**, combined across both
output banks (a question counted in both `exam_bank` and `pal_bank` counts
once toward this target, not twice).

- Pull from as many verified content tiers as are actually available for
  that chapter — don't stop at Tier A/B/C if it's still short of 250;
  continue down through D–G1 before touching Tier H.
- **First priority for closing a gap is sourcing more real material**, not
  generation. Only use `ai_generated_from_pattern` (Section 4) after
  exhausting Tiers A–H, and even then it must be grounded in a
  `sourced_verbatim` example per the Section 5 gate.
- **Never pad the count with Tier H (secondary) material alone**, and never
  invent variants of an existing question to hit the number. If sources
  genuinely cap out below 250 for a chapter, report the actual count and
  the shortfall in `run_summary.md` — a true count under target is more
  useful downstream than an inflated one.
- If verified sources exceed 500 for a chapter, prioritize by tier (A→H)
  and within a tier by question-type diversity, so the final set isn't
  skewed toward one question type just because one source had many of them.
- Deduplicate near-identical questions (same concept + same phrasing across
  two sources) before counting toward the target — count the item once,
  but keep both `source_url`s logged against it for provenance.
- Quantity never overrides Quality: an item that fails Section 5's gate
  does not count toward the 250, however close the chapter is to target.

## 7. Extraction workflow

1. Confirm content and practice-evidence sources (Section 1) for this run's
   class/subject/session; run Section 2's verification gate on every
   candidate content URL.
2. Download verified PDFs to a working folder; extract text (OCR where the
   PDF is scanned).
3. Segment into individual question+answer units.
4. Tag each per Section 4's schema; run each through Section 5's quality
   gate before counting it.
5. Where tiers conflict on concept/competency labeling, resolve per
   Section 3 and note the override in `conflicts.md`.
6. Check running count against Section 6's target per chapter; continue
   sourcing (preferred) or, only as a last resort, generate
   pattern-grounded items (Section 4/6) to close the gap.
7. Output two files per run:
   - `{{class}}_{{subject}}_{{session}}_exam_bank.json` — items where
     `exam_assessment.applicable: true`, sorted by `marks`/`question_type`
     to mirror CBSE pattern proportions.
   - `{{class}}_{{subject}}_{{session}}_pal_bank.json` — items where
     `pal_concept_intelligence.applicable: true`, grouped by `concept`.
8. Write a short `run_summary.md`: source count by tier (content vs
   practice-evidence), items extracted, items rejected at the quality gate,
   per-chapter count against the 250–500 target, `validation_status`
   breakdown (how many sourced_verbatim vs ai_rephrased vs
   ai_generated_from_pattern), and any conflicts overridden.

## 8. Guardrails

- Never fabricate a question, answer, or source URL. If coverage for a
  concept is thin after Section 1, say so in `run_summary.md` rather than
  filling the gap with invented content passed off as sourced.
- Never extract "questions" from a practice-evidence source (Section 1) —
  those inform the schema only.
- Never let Tier H content override or "correct" Tier A–G1 labeling.
- Never let per-chapter volume pressure (Section 6) justify accepting an
  unverified URL (Section 2), skipping the Section 5 quality gate, or
  inflating the count with near-duplicates.
- Flag session mismatches explicitly (e.g. don't silently blend 2025-26 and
  2026-27 material for a class with a curriculum change — keep them in
  separate output files, consistent with the Class 9 curriculum-transition
  finding).
