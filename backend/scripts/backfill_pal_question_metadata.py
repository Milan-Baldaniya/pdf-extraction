"""Give every Class 6-10 question a `pal_question_metadata` row, and fill the
fields that can be derived without judgement.

    python -m scripts.backfill_pal_question_metadata            # report only
    python -m scripts.backfill_pal_question_metadata --apply
    python -m scripts.backfill_pal_question_metadata --standard 41 --apply

Only 452 of 29,411 Class 6-10 questions have a row in `pal_question_metadata`,
so the table that is meant to carry the PAL V4 intelligence is empty for almost
the whole bank. Nothing else can be tagged until the rows exist.

WHAT THIS WRITES, AND WHAT IT DELIBERATELY DOES NOT.

Every column below is either copied from a column we already hold or decided by
a stated rule. Nothing here is a judgement about an individual question, which
is why it can run unattended over the whole estate:

    copied      question/chapter/topic/concept refs, marks, bloom, DOK,
                difficulty, outcome ref, exam section, figure flag, confidence
    by rule     grade_band, stage, board, blueprint_category, assessment_type,
                item_type, guessing_vulnerability, h5p_type, scaffold_type,
                scaffold_available, response_latency_band, offline_compatible,
                language, reading_level_fk, knowledge_type, aptitude_domain

`tagged_by` is set to 'derived' on every row, never 'ai' or 'human'. That is
the whole point: a later authoring pass must be able to find the rows a rule
touched and the rows a reader touched, and treat them differently. A reviewer
who cannot tell them apart has to re-check all 29,411.

FIELDS LEFT NULL ON PURPOSE. The psychometrics (`irt_a/b/c`,
`discrimination_index`, `avg_time_seconds`, `first_attempt_correct_rate`) come
from `pal_assessment_results`, which already holds 2.4M responses -- they are
measured, not authored, and writing an estimate into them would bury the real
figure when it arrives. The career and personality signals (`riasec_signal`,
`ncdg_goal`, `gardner_intelligence`, `nep_vocational_stream`, `nsqf_level`,
`hpc_lens_primary`, `soft_skill_signal`, `career_cluster_signal`,
`casel_domain`) have no evidence in a Class 7 water-cycle question, and the
PAL V4 rule is that an empty rich field passes the gate while a fabricated one
fails it. `skills`, `misconception_tags`, `distractor_rationale`,
`cultural_context` and `pedagogy_mapping_id` need the question read, so they
belong to the authoring pass, not here.

THE UPSERT IS NON-DESTRUCTIVE. `pqm_question_tenant_unique` is
(question_id, sub_institute_id), and the ON DUPLICATE KEY clause uses
COALESCE(VALUES(col), col) so a re-run never blanks a field, and never
overwrites a value a human or an authoring agent put there -- it only fills
what is still NULL. Re-running after the mapping agents finish is therefore
safe and is how `learning_outcome_ref` and `concept_ref_id` catch up.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

STANDARDS = {39: 6, 40: 7, 41: 8, 42: 9, 43: 10}

# pal_vocabulary.bloom_levels -- the stored codes, not the display labels.
BLOOM = {"remember": "recall", "recall": "recall", "understand": "understand",
         "understanding": "understand", "apply": "apply", "applying": "apply",
         "analyze": "analyze", "analyse": "analyze", "analyzing": "analyze",
         "evaluate": "evaluate", "evaluating": "evaluate", "create": "create",
         "creating": "create"}
# A three-band source cannot justify the ends of a five-point scale.
DIFFICULTY = {"easy": 2, "medium": 3, "moderate": 3, "hard": 4, "difficult": 4}
# pal_vocabulary.response_latency_bands, keyed on Bloom.
LATENCY = {"recall": "fast_recall", "understand": "fast_recall",
           "apply": "medium_application", "analyze": "slow_analysis",
           "evaluate": "slow_analysis", "create": "extended_creation"}
# pal_vocabulary.h5p_types
H5P = {"mcq": "multiple_choice", "assertion_reason": "multiple_choice",
       "true_false": "multiple_choice", "fill_blank": "fill_in_the_blanks",
       "fill_in_the_blanks": "fill_in_the_blanks", "match": "drag_text",
       "match_the_following": "drag_text"}
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
WORD = re.compile(r"[A-Za-z]+")
VOWELS = "aeiouy"


def syllables(w: str) -> int:
    w = w.lower()
    n, prev = 0, False
    for ch in w:
        v = ch in VOWELS
        if v and not prev:
            n += 1
        prev = v
    if w.endswith("e") and n > 1:
        n -= 1
    return max(n, 1)


def reading_level(stem: str) -> float | None:
    """Flesch-Kincaid grade. Latin script only -- it is meaningless otherwise."""
    if not stem or DEVANAGARI.search(stem):
        return None
    words = WORD.findall(stem)
    if len(words) < 6:
        return None
    sents = max(stem.count(".") + stem.count("?") + stem.count("!"), 1)
    sy = sum(syllables(w) for w in words)
    fk = 0.39 * (len(words) / sents) + 11.8 * (sy / len(words)) - 15.59
    return round(max(0.0, min(fk, 20.0)), 2)


def blueprint(section: str | None, form: str | None, marks) -> str | None:
    """CBSE blueprint band. The printed section wins; marks are the fallback."""
    s = (section or "").lower()
    for key, out in (("case", "case_based"), ("assertion", "assertion_reason"),
                     ("very short", "very_short_answer"), ("objective", "objective"),
                     ("multiple choice", "objective"), ("mcq", "objective"),
                     ("long answer", "long_answer"), ("short answer", "short_answer"),
                     ("competency", "competency_based"), ("hots", "hots")):
        if key in s:
            return out
    f = (form or "").lower()
    if f in ("mcq", "true_false", "fill_blank"):
        return "objective"
    try:
        m = float(marks)
    except (TypeError, ValueError):
        return None
    return ("objective" if m <= 1 else "very_short_answer" if m <= 2
            else "short_answer" if m <= 3 else "long_answer")


def knowledge_type(bloom: str | None, form: str | None, subject: str) -> str | None:
    """pal_vocabulary.knowledge_types, by rule.

    Recall is factual. Apply in a calculating subject is procedural -- the
    student runs a method. Everything else that is understood or analysed is
    conceptual. Metacognitive is never assigned by rule: it needs the question
    to ask the student about their own thinking, which only a reader can see.
    """
    if not bloom:
        return None
    if bloom == "recall":
        return "factual"
    calc = any(k in subject.lower() for k in ("math", "science", "physic",
                                              "chem", "account"))
    if bloom == "apply":
        return "procedural" if calc else "conceptual"
    if bloom in ("understand", "analyze", "evaluate", "create"):
        return "conceptual"
    return None


def aptitude(subject: str) -> str | None:
    s = subject.lower()
    if "math" in s:
        return "numerical"
    if any(k in s for k in ("english", "hindi", "sanskrit", "language")):
        return "verbal"
    return None            # Science and Social Science are genuinely mixed.


SELECT = """
SELECT q.id, q.sub_institute_id, q.chapter_id, q.topic_id, q.subconcept,
       q.points, q.hint_text, q.question_title, q.g_bloom, q.g_dok,
       q.g_difficulty, q.concept_id AS q_concept,
       c.standard_id, COALESCE(s.subject_name,'') AS subject,
       e.verbatim_sha256, e.concept_id AS e_concept, e.concept_confidence,
       e.bloom_level, e.dok_level, e.difficulty_1_to_5, e.exam_section,
       e.section_marks, e.item_form, e.figure_required,
       -- `lms_question_outcome` is where the mapping agents write, and it is
       -- ahead of the sidecar: 59.2% of Classes 6-10 have a row there against
       -- 43.4% with e.outcome_id. Reading only the sidecar silently drops
       -- ~4,700 mappings. Best match first; ties break on the lowest id so a
       -- re-run is stable.
       COALESCE((SELECT o.outcome_id FROM lms_question_outcome o
                  WHERE o.question_id = q.id AND o.outcome_id IS NOT NULL
                  ORDER BY o.match_score DESC, o.id ASC LIMIT 1),
                e.outcome_id) AS outcome_id,
       (SELECT COUNT(*) FROM answer_master a WHERE a.question_id=q.id) AS n_opt
  FROM lms_question_master q
  JOIN chapter_master c ON c.id = q.chapter_id
  LEFT JOIN subject s ON s.id = c.subject_id
  LEFT JOIN lms_question_extraction e ON e.question_id = q.id
 WHERE c.standard_id BETWEEN 39 AND 43
"""

COLS = ["question_id", "sub_institute_id", "scope", "content_id_ref",
        "concept_ref_id", "chapter_ref_id", "topic_ref_id", "sub_concept_ref",
        "grade_band", "stage", "board", "blueprint_category", "marks",
        "learning_outcome_ref", "bloom_level", "practice_level",
        "knowledge_type", "item_type", "difficulty_1_to_5",
        "guessing_vulnerability", "assessment_type", "format", "h5p_type",
        "scaffold_type", "scaffold_available", "response_latency_band",
        "visual_dependency", "offline_compatible", "language",
        "reading_level_fk", "aptitude_domain", "quality_status", "tagged_by",
        "confidence", "version"]
# Never blank a filled column, and never overwrite an authored one.
KEEP = [c for c in COLS if c not in ("question_id", "sub_institute_id")]
UPSERT = (f"INSERT INTO pal_question_metadata ({', '.join(COLS)}) VALUES "
          f"({', '.join(':' + c for c in COLS)}) "
          f"ON DUPLICATE KEY UPDATE "
          + ", ".join(f"{c}=COALESCE(VALUES({c}), {c})" for c in KEEP))


def build(r) -> dict:
    d = r._mapping
    subject = str(d["subject"] or "")
    std = int(d["standard_id"])
    stem = str(d["question_title"] or "")
    form = (str(d["item_form"]) if d["item_form"] else None)

    bloom = BLOOM.get(str(d["bloom_level"] or d["g_bloom"] or "").strip().lower())
    dok = d["dok_level"] if d["dok_level"] is not None else d["g_dok"]
    try:
        dok = max(1, min(int(dok), 5))
    except (TypeError, ValueError):
        dok = None
    diff = d["difficulty_1_to_5"]
    if diff is None:
        diff = DIFFICULTY.get(str(d["g_difficulty"] or "").strip().lower())
    marks = d["section_marks"] if d["section_marks"] is not None else d["points"]
    try:
        marks = round(float(marks), 2)
    except (TypeError, ValueError):
        marks = None

    n_opt = int(d["n_opt"] or 0)
    # Four options is a 25% blind guess; two is 50%; a written answer is none.
    guess = ("medium" if n_opt >= 4 else "high" if n_opt >= 2 else "low")
    fig = 1 if d["figure_required"] else 0
    hint = bool(str(d["hint_text"] or "").strip())
    concept = d["e_concept"] or (d["q_concept"] or None)

    return {
        "question_id": int(d["id"]),
        "sub_institute_id": int(d["sub_institute_id"] or 1),
        "scope": "tenant",
        "content_id_ref": d["verbatim_sha256"] or None,
        "concept_ref_id": int(concept) if concept else None,
        "chapter_ref_id": int(d["chapter_id"]) if d["chapter_id"] else None,
        "topic_ref_id": int(d["topic_id"]) if d["topic_id"] else None,
        "sub_concept_ref": (str(d["sub_concept_ref"])[:191]
                            if d.get("sub_concept_ref") else
                            (str(d["subconcept"])[:191] if d["subconcept"] else None)),
        "grade_band": "middle" if std <= 41 else "secondary",
        "stage": "Middle" if std <= 41 else "Secondary",
        "board": "CBSE",
        "blueprint_category": blueprint(d["exam_section"], form, marks),
        "marks": marks,
        "learning_outcome_ref": int(d["outcome_id"]) if d["outcome_id"] else None,
        "bloom_level": bloom,
        "practice_level": dok,
        "knowledge_type": knowledge_type(bloom, form, subject),
        # item_type is varchar(16); "case_study_parent" is 17 and would clamp
        # to "case_study_paren". It is the stem of a case-study set, so it is
        # named for what it is rather than shortened into a typo.
        "item_type": ("case_study" if form == "case_study_parent"
                      else (form or None)),
        "difficulty_1_to_5": diff,
        "guessing_vulnerability": guess,
        "assessment_type": ("competency" if n_opt == 0 else "formative"),
        "format": "text_diagram" if fig else "h5p" if n_opt else None,
        "h5p_type": H5P.get((form or "").lower()) or ("multiple_choice"
                                                      if n_opt >= 2 else None),
        "scaffold_type": "hint_available" if hint else "none",
        # SIX COLUMNS CARRY A json_valid() CHECK and reject a bare string:
        # scaffold_available, skills, misconception_tags, distractor_rationale,
        # language_variants_available, ai_rationale. The column comment reads
        # "hint_1..3 + worked_example content ids", so the hint on
        # lms_question_master is announced as hint_1.
        "scaffold_available": '["hint_1"]' if hint else None,
        "response_latency_band": LATENCY.get(bloom or ""),
        "visual_dependency": fig,
        "offline_compatible": 0 if fig else 1,
        "language": "hi" if DEVANAGARI.search(stem) else "en",
        "reading_level_fk": reading_level(stem),
        "aptitude_domain": aptitude(subject),
        "quality_status": "draft",
        "tagged_by": "derived",
        "confidence": d["concept_confidence"],
        "version": "4.0",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--standard", type=int, choices=sorted(STANDARDS))
    # A newly loaded subject needs its own rows without a standard-wide pass
    # over every other subject in that class. The upsert is non-destructive
    # either way, but "touch only these chapters" is a real instruction to
    # honour and an unscoped run cannot be narrowed after the fact.
    ap.add_argument("--chapters",
                    help="comma-separated chapter_master ids; narrows the scope "
                         "to exactly those chapters")
    ap.add_argument("--batch", type=int, default=500)
    a = ap.parse_args()

    chapter_ids: list[int] = []
    if a.chapters:
        chapter_ids = [int(x) for x in a.chapters.split(",") if x.strip()]
        if not chapter_ids:
            raise SystemExit("--chapters was given but held no ids")

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        sql = SELECT + (" AND c.standard_id = :s" if a.standard else "")
        params: dict = {"s": a.standard} if a.standard else {}
        if chapter_ids:
            keys = [f":c{i}" for i in range(len(chapter_ids))]
            sql += f" AND c.id IN ({', '.join(keys)})"
            params.update({f"c{i}": cid for i, cid in enumerate(chapter_ids)})
        rows = db.execute(text(sql), params).fetchall()
        print(f"  {len(rows)} questions in scope")
        if not rows:
            return 0

        payload = [build(r) for r in rows]

        # Clamp every string to its real column width, read from the live
        # schema rather than hardcoded -- `item_type` is varchar(16) and
        # `item_form` carries longer codes than that. A silent truncation would
        # put a value like "match_the_followi" into a closed-vocabulary column
        # and nothing downstream would notice, so each one is counted and named.
        width = {c: n for c, n in db.execute(text(
            "SELECT COLUMN_NAME, CHARACTER_MAXIMUM_LENGTH "
            "  FROM information_schema.COLUMNS "
            " WHERE TABLE_SCHEMA = DATABASE() "
            "   AND TABLE_NAME = 'pal_question_metadata' "
            "   AND CHARACTER_MAXIMUM_LENGTH IS NOT NULL")).fetchall()}
        cut: dict[tuple, int] = {}
        for p in payload:
            for c, v in p.items():
                n = width.get(c)
                if n and isinstance(v, str) and len(v) > n:
                    cut[(c, v)] = cut.get((c, v), 0) + 1
                    p[c] = v[:n]
        if cut:
            print("\n  CLAMPED to column width:")
            for (c, v), n in sorted(cut.items(), key=lambda kv: -kv[1]):
                print(f"    {c} ({width[c]}) <- {v!r} x{n}")

        fill = {c: sum(1 for p in payload if p[c] is not None) for c in COLS}
        print(f"\n  {'column':<24} {'filled':>7}   of {len(payload)}")
        for c in COLS:
            n = fill[c]
            print(f"  {c:<24} {n:>7}  {n * 100.0 / len(payload):5.1f}%")

        existing = db.execute(text(
            "SELECT COUNT(*) FROM pal_question_metadata m "
            "  JOIN lms_question_master q ON q.id = m.question_id "
            "  JOIN chapter_master c ON c.id = q.chapter_id "
            " WHERE c.standard_id BETWEEN 39 AND 43")).scalar()
        print(f"\n  rows already present for Classes 6-10: {existing}")
        print(f"  rows this run would insert or top up  : {len(payload)}")

        if not a.apply:
            print("\n  report only -- re-run with --apply")
            return 0

        done = 0
        for i in range(0, len(payload), a.batch):
            chunk = payload[i:i + a.batch]
            db.execute(text(UPSERT), chunk)
            db.commit()
            done += len(chunk)
            print(f"    {done}/{len(payload)}", end="\r", flush=True)
        after = db.execute(text(
            "SELECT COUNT(*) FROM pal_question_metadata m "
            "  JOIN lms_question_master q ON q.id = m.question_id "
            "  JOIN chapter_master c ON c.id = q.chapter_id "
            " WHERE c.standard_id BETWEEN 39 AND 43")).scalar()
        print(f"\n  done. Classes 6-10 rows in pal_question_metadata: "
              f"{existing} -> {after}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
