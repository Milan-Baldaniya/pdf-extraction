"""Audit an extraction's Chapter -> Topics -> Concepts output against the chapter.

Answers eight questions about a processed chapter, using only the chapter's own
markdown as the source of truth. No LLM is involved: every check is a
deterministic measurement, so the same chapter always produces the same report
and the report costs nothing to run.

    1. grounding      every topic is really in the chapter
    2. attribution    every concept belongs to a live topic of this chapter
    3. relevance      no topic or concept restates one that already exists
    4. coverage       no teaching section of the chapter is left without a topic
    5. granularity    topics are main topics, not sub-topics stored as topics
    6. hierarchy      no childless topic, no orphan concept, minutes add up
    7. semantic       Semantic Intelligence covers these topics and concepts
    8. verdict        the roll-up of the seven above

Severities: "error" means the row is wrong and should not ship; "warning"
means it is suspect and worth a human look.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from sqlalchemy import text

from app.db.mariadb import SessionLocal
from app.services import chapter_text as ct

logger = logging.getLogger(__name__)

# Fraction of a name's content words that must appear in the source text before
# it counts as grounded. Not 1.0: a legitimate topic name generalises its
# section ("Sign rule for integer division" over text that says "negative
# divided by positive"), so a hard requirement would flag good rows.
_GROUNDING_OK = 0.6
_GROUNDING_WEAK = 0.35

# A concept must overlap the text of the topic it hangs off, not merely the
# chapter. Lower than the chapter bar because a topic slice is much smaller.
_ATTRIBUTION_OK = 0.4

# Concept minutes are scaled to the topic budget at write time, so anything
# beyond rounding drift means the rows were edited or written by an older run.
_MINUTES_TOLERANCE = 2

# What a chapter's main-topic count should look like. These mirror rule 2 of the
# topic prompt; outside this band the extraction is at the wrong level, not
# merely unusual. Chapter 147 scored 19 against a true 6 before the Topic Queue
# stopped splitting chapters into parts.
_MIN_EXPECTED_TOPICS = 3
_MAX_EXPECTED_TOPICS = 10


def _stems(value: str) -> set[str]:
    """Token set reduced for comparison, so "simplifying fractions" matches a
    chapter that says "simplify" and "fraction"."""
    return {ct.singular(t) for t in ct.tokens(value)}


def _coverage(name: str, haystack_stems: set[str]) -> float:
    """Fraction of a name's content words present in some body of text."""
    want = _stems(name)
    if not want:
        return 0.0
    return len(want & haystack_stems) / len(want)


def _issue(kind: str, severity: str, message: str, **extra: Any) -> Dict[str, Any]:
    return {"check": kind, "severity": severity, "message": message, **extra}


def _load(extraction_id: int) -> Dict[str, Any]:
    with SessionLocal() as db:
        row = db.execute(
            text("""SELECT id, document_tittle, subject_name, standard, md_content
                      FROM document_extractions WHERE id = :id"""),
            {"id": extraction_id},
        ).mappings().fetchone()
        if not row:
            raise ValueError(f"No document_extraction found for id {extraction_id}")

        chapter = db.execute(
            text("SELECT id, chapter_name, key_concepts FROM chapter_master WHERE extraction_id = :id"),
            {"id": extraction_id},
        ).mappings().fetchone()

        topics = [dict(t) for t in db.execute(
            text("""SELECT id, name, description, estimated_minutes, topic_sort_order, topic_show_hide
                      FROM topic_master WHERE extraction_id = :id
                  ORDER BY topic_sort_order ASC, id ASC"""),
            {"id": extraction_id},
        ).mappings().fetchall()]

        concepts = [dict(c) for c in db.execute(
            text("""SELECT id, topic_id, name, description, mastery_threshold,
                           estimated_mastery_minutes
                      FROM lms_concept WHERE extraction_id = :id ORDER BY topic_id, id"""),
            {"id": extraction_id},
        ).mappings().fetchall()]

        semantic = db.execute(
            text("SELECT * FROM semantic_intelligence WHERE extraction_id = :id"),
            {"id": extraction_id},
        ).mappings().fetchone()

    return {
        "row": dict(row),
        "chapter": dict(chapter) if chapter else None,
        "topics": topics,
        "concepts": concepts,
        "semantic": dict(semantic) if semantic else None,
    }


def _semantic_concept_names(semantic: Dict[str, Any] | None) -> List[str]:
    """Every concept_name the semantic payload refers to, across all its arrays."""
    if not semantic:
        return []
    names: set[str] = set()
    for value in semantic.values():
        if not isinstance(value, str) or not value.strip().startswith("["):
            continue
        try:
            parsed = json.loads(value)
        except Exception:
            continue
        for item in parsed if isinstance(parsed, list) else []:
            if isinstance(item, dict) and item.get("concept_name"):
                names.add(str(item["concept_name"]))
    return sorted(names)


def validate_extraction(extraction_id: int) -> Dict[str, Any]:
    """The full audit for one processed chapter."""
    loaded = _load(extraction_id)
    md = loaded["row"].get("md_content") or ""
    topics, concepts = loaded["topics"], loaded["concepts"]

    if not md:
        raise ValueError(f"document_extraction {extraction_id} has no md_content")

    sections = ct.split_sections(md)
    chapter_stems = _stems(md)
    issues: List[Dict[str, Any]] = []

    live_topics = [t for t in topics if t["topic_show_hide"] != 0]
    by_topic: Dict[Any, List[Dict[str, Any]]] = {}
    for concept in concepts:
        by_topic.setdefault(concept["topic_id"], []).append(concept)

    # Where each topic lives in the chapter, reused by several checks below.
    # The span comes from the same partition the Concept Queue used, so the
    # attribution check below measures a concept against the exact text its
    # extracting call was shown rather than against an approximation of it.
    spans = ct.partition_by_topics(md, [t["name"] for t in live_topics]) if live_topics else []
    home: Dict[int, Dict[str, Any]] = {}
    for topic, (start, end) in zip(live_topics, spans):
        target = set(ct.tokens(topic["name"])) | set(ct.tokens(topic["description"] or "")[:20])
        scores = [ct.score_section(s, target) for s in sections]
        best = max(range(len(scores)), key=lambda i: scores[i]) if scores else 0
        home[topic["id"]] = {
            "section_index": best,
            "section_kind": sections[best]["kind"] if sections else "teaching",
            "score": round(scores[best], 3) if scores else 0.0,
            "span": (start, end),
            "slice_stems": _stems(md[start:end]),
        }

    # --- 1. grounding --------------------------------------------------------
    grounded = 0
    for topic in live_topics:
        score = _coverage(topic["name"], chapter_stems)
        if score >= _GROUNDING_OK:
            grounded += 1
        elif score >= _GROUNDING_WEAK:
            issues.append(_issue(
                "grounding", "warning",
                f"Topic '{topic['name']}' is only partly supported by the chapter text "
                f"({score:.0%} of its words appear).",
                topic_id=topic["id"], score=round(score, 2)))
        else:
            issues.append(_issue(
                "grounding", "error",
                f"Topic '{topic['name']}' does not appear in the chapter "
                f"({score:.0%} of its words appear).",
                topic_id=topic["id"], score=round(score, 2)))

    # --- 2. relevance: topics built out of revision material -----------------
    for topic in live_topics:
        if home[topic["id"]]["section_kind"] == "revision":
            issues.append(_issue(
                "relevance", "error",
                f"Topic '{topic['name']}' was taken from a revision block "
                f"(Getting started / Check your progress / Summary checklist), which "
                f"practises topics taught elsewhere rather than teaching anything new.",
                topic_id=topic["id"]))

    # --- 3. attribution ------------------------------------------------------
    topic_ids = {t["id"] for t in topics}
    live_ids = {t["id"] for t in live_topics}
    attributed = 0

    # A chapter that has never been through the Topic Queue has every concept
    # unattributed for one reason. Reporting that once says what to do; reporting
    # it per concept buries the other checks under N copies of the same line.
    not_yet_processed = not topics and concepts
    if not_yet_processed:
        issues.append(_issue(
            "attribution", "error",
            f"This chapter has no topics: all {len(concepts)} concepts were written "
            f"chapter-wise by the old Chapter -> Concepts -> Topics flow. Run the "
            f"Topic Queue, then the Concept Queue, to rebuild them topic-wise.",
            concepts=len(concepts)))

    for concept in concepts:
        tid = concept["topic_id"]
        if tid is None:
            if not not_yet_processed:
                issues.append(_issue(
                    "attribution", "error",
                    f"Concept '{concept['name']}' has no topic; it predates the "
                    f"Chapter -> Topics -> Concepts hierarchy or was written by hand.",
                    concept_id=concept["id"]))
            continue
        if tid not in topic_ids:
            issues.append(_issue(
                "attribution", "error",
                f"Concept '{concept['name']}' points at topic {tid}, which does not "
                f"belong to this extraction.",
                concept_id=concept["id"], topic_id=tid))
            continue
        if tid not in live_ids:
            issues.append(_issue(
                "attribution", "error",
                f"Concept '{concept['name']}' hangs off a hidden topic.",
                concept_id=concept["id"], topic_id=tid))
            continue
        score = _coverage(concept["name"], home[tid]["slice_stems"])
        if score >= _ATTRIBUTION_OK:
            attributed += 1
        else:
            issues.append(_issue(
                "attribution", "warning",
                f"Concept '{concept['name']}' barely overlaps the text of its topic "
                f"({score:.0%}); it may belong under a different topic.",
                concept_id=concept["id"], topic_id=tid, score=round(score, 2)))

    # --- 4. relevance: duplicates -------------------------------------------
    def duplicate_pairs(items: List[Dict[str, Any]], label: str,
                        same_parent: Any = None) -> List[Dict[str, Any]]:
        """Repeats across different parents break the hierarchy and are errors.

        Two concepts under the SAME topic are only a warning: they necessarily
        share that topic's vocabulary, and the pipeline's dedupe deliberately
        never merges within a group -- doing so would strip a topic bare.
        """
        found = []
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                if not ct.is_duplicate_name(a["name"], b["name"]):
                    continue
                shared = same_parent and same_parent(a) == same_parent(b)
                found.append(_issue(
                    "relevance", "warning" if shared else "error",
                    f"{'Overlapping' if shared else 'Duplicate'} {label}: "
                    f"'{a['name']}' and '{b['name']}' describe the same unit under "
                    f"different wording" + (" within one topic." if shared else "."),
                    ids=[a["id"], b["id"]]))
        return found

    issues += duplicate_pairs(live_topics, "topic")
    issues += duplicate_pairs([c for c in concepts if c["topic_id"] is not None],
                              "concept", same_parent=lambda c: c["topic_id"])

    # --- 5. coverage ---------------------------------------------------------
    # A running header repeating the chapter's own name ("- Integers" on every
    # page) is not a section anyone can write a topic about.
    chapter_key = ct.normalise_name((loaded["chapter"] or {}).get("chapter_name")
                                    or loaded["row"]["document_tittle"] or "")
    taught = [
        (i, s) for i, s in enumerate(sections)
        if s["kind"] == "teaching" and s["title"] and len(s["text"]) >= 400
        and ct.normalise_name(s["title"]) != chapter_key
    ]
    claimed = {home[t["id"]]["section_index"] for t in live_topics}
    uncovered = []

    # When the book numbers its own sections, that numbering IS the contract the
    # Topic Queue works to, and a block the book chose not to number -- an
    # end-of-unit project, a boxed aside -- is not a topic it failed to produce.
    # Checking coverage against every text block would report those as errors on
    # exactly the chapters whose structure is least in doubt.
    _, outline_is_authoritative = ct.topic_outline(md)

    if not outline_is_authoritative:
        for index, section in taught:
            if index in claimed:
                continue
            # A section is only genuinely missed when no topic even mentions it.
            title_stems = _stems(section["title"])
            if any(_coverage(t["name"], title_stems) >= 0.5 for t in live_topics):
                continue
            uncovered.append(section["title"])
            issues.append(_issue(
                "coverage", "error",
                f"Chapter section '{section['title'][:80]}' produced no topic.",
                section_index=index))

    # --- 6. granularity ------------------------------------------------------
    # The regression guard for the segment-based over-extraction: chapter 147
    # came back with 19 topics for a 6-section chapter, each owning a sliver of
    # text. Both symptoms are measured here so a repeat is visible without
    # anyone re-reading the book.
    if live_topics:
        for topic in live_topics:
            start, end = home[topic["id"]]["span"]
            if end - start < ct.MIN_TOPIC_SPAN_CHARS:
                issues.append(_issue(
                    "granularity", "warning",
                    f"Topic '{topic['name']}' owns only {end - start} characters of the "
                    f"chapter; a main topic normally carries more. It may belong inside "
                    f"a neighbouring topic rather than standing on its own.",
                    topic_id=topic["id"], span_chars=end - start))

        if len(live_topics) > _MAX_EXPECTED_TOPICS:
            issues.append(_issue(
                "granularity", "error",
                f"{len(live_topics)} topics for a {len(md)}-character chapter. A chapter "
                f"normally has {_MIN_EXPECTED_TOPICS} to {_MAX_EXPECTED_TOPICS} main "
                f"topics; more than that means the chapter was split below the topic "
                f"level and sub-topics were stored as topics.",
                topics=len(live_topics)))
        elif len(live_topics) < _MIN_EXPECTED_TOPICS:
            issues.append(_issue(
                "granularity", "warning",
                f"Only {len(live_topics)} topic(s) for a {len(md)}-character chapter; "
                f"the chapter may have been summarised rather than divided.",
                topics=len(live_topics)))

    # --- 7. hierarchy --------------------------------------------------------
    for topic in live_topics:
        children = by_topic.get(topic["id"], [])
        if not children:
            issues.append(_issue(
                "hierarchy", "error",
                f"Topic '{topic['name']}' has no concepts under it.",
                topic_id=topic["id"]))
            continue
        total = sum(c["estimated_mastery_minutes"] or 0 for c in children)
        budget = topic["estimated_minutes"] or 0
        if budget and abs(total - budget) > _MINUTES_TOLERANCE:
            issues.append(_issue(
                "hierarchy", "warning",
                f"Topic '{topic['name']}' is budgeted {budget} min but its concepts "
                f"sum to {total} min.",
                topic_id=topic["id"]))

    # --- 8. semantic scope ---------------------------------------------------
    semantic_names = _semantic_concept_names(loaded["semantic"])
    hierarchy_names = [c["name"] for c in concepts] + [t["name"] for t in live_topics]
    matched = [n for n in semantic_names
               if any(ct.is_duplicate_name(n, h) for h in hierarchy_names)]
    if loaded["semantic"] and semantic_names:
        share = len(matched) / len(semantic_names)
        if share < 0.5:
            issues.append(_issue(
                "semantic", "warning",
                f"Only {len(matched)} of {len(semantic_names)} concept names in the "
                f"Semantic Intelligence payload correspond to a topic or concept of "
                f"this chapter ({share:.0%}). Either it was generated before the topic "
                f"hierarchy existed (it then sliced against chapter_master.key_concepts "
                f"instead), or the hierarchy has been rebuilt since. Re-run Semantic "
                f"Intelligence to bring the two vocabularies back together.",
                matched=len(matched), total=len(semantic_names)))
    elif not loaded["semantic"]:
        issues.append(_issue(
            "semantic", "warning",
            "No Semantic Intelligence row for this extraction."))

    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] == "warning"]

    return {
        "extraction_id": extraction_id,
        "chapter_name": (loaded["chapter"] or {}).get("chapter_name") or loaded["row"]["document_tittle"],
        "subject_name": loaded["row"]["subject_name"],
        "standard": loaded["row"]["standard"],
        "verdict": "pass" if not errors else "fail",
        "totals": {
            "topics": len(topics),
            "topics_live": len(live_topics),
            "topics_hidden": len(topics) - len(live_topics),
            "concepts": len(concepts),
            "chapter_sections": len(sections),
            "teaching_sections": len(taught),
            "revision_sections": sum(1 for s in sections if s["kind"] == "revision"),
            "errors": len(errors),
            "warnings": len(warnings),
        },
        "scores": {
            "topics_grounded": f"{grounded}/{len(live_topics)}" if live_topics else "0/0",
            "concepts_attributed": f"{attributed}/{len(concepts)}" if concepts else "0/0",
            "sections_uncovered": len(uncovered),
            "semantic_aligned": f"{len(matched)}/{len(semantic_names)}" if semantic_names else "0/0",
        },
        "by_check": {
            check: len([i for i in issues if i["check"] == check])
            for check in ("grounding", "attribution", "relevance", "coverage",
                          "granularity", "hierarchy", "semantic")
        },
        "issues": errors + warnings,
    }
