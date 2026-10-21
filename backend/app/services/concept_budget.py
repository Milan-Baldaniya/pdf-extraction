"""How many concepts a chapter gets, and which ones survive.

This module exists because the count used to come from `len(md_content)`:

    _CONCEPTS_PER_1K_CHARS = (0.8, 1.8)
    low, high = (round(chapter_chars / 1000 * rate) for rate in ...)

A 61k-character chapter was therefore told, in the prompt, that it "normally
yields between 49 and 110 concepts across all its topics" -- and it obliged with
74, for six topics. Measured across this corpus the same formula produced 86,
74, 66, 62 and 50 for single chapters, at up to 14 concepts per topic.

The mistake is not the constant. It is the input. Two decisions were conflated:

    HOW MANY IN TOTAL        is a pedagogical question. Never document length.
    HOW THEY ARE DISTRIBUTED is a question about where the text sits.

Length is legitimate for the second -- a topic owning 18k characters really does
teach more than one owning 3k -- and never for the first.

So the total comes from a cascade of curriculum signals, falling back on the
chapter's own structure, and length is used only to split that total across
topics. Both halves are pure functions: no DB, no LLM, no clock, so the same
chapter always gets the same budget and the whole module is testable offline.

The second half of the module is enforcement. The old budget was prompt text and
a `logger.warning`; nothing in code ever capped anything. Here the quota goes
into the prompt per-topic AND is enforced afterwards by ranking each topic's
concepts on evidence and trimming the weakest -- with the deliberate property
that a grounded concept can never be trimmed for being over budget.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

from app.services import chapter_text as ct

logger = logging.getLogger(__name__)


# --- the total ------------------------------------------------------------

# An NCF learning outcome ("Differentiate between voluntary and involuntary
# muscles") IS a masterable idea, so the ratio is near 1. The extra quarter
# covers what the book teaches that the syllabus did not spell out.
_PER_LEARNING_OUTCOME = 1.25
_MIN_LEARNING_OUTCOMES = 4

# A competency is a whole capability ("C-3.2 Explains the role of tissues"),
# coarser than an outcome; three or four concepts serve one.
_PER_COMPETENCY = 3.0
_MIN_COMPETENCIES = 2

# A 40-minute period can teach about two ideas to mastery. More than that and
# nothing is mastered -- which is the entire complaint this module answers.
_PER_PERIOD = 2.0

# Last resort, when the curriculum says nothing and no period count was found.
# Structural, not textual: it reads the chapter's own section count.
_PER_TOPIC_FALLBACK = 3.0

# Structural bounds. Every topic has to divide into something, and no chapter
# in this corpus teaches thirty discrete masterable ideas -- beyond that the
# entries have stopped being ideas and become sentences from the book.
_FLOOR_PER_TOPIC = 2
_CEILING_PER_TOPIC = 4
_ABSOLUTE_FLOOR = 8
_ABSOLUTE_CEILING = 30

# How wide a band the prompt is given around the target. Narrow, because a wide
# band is what let the model sit at the top of it.
_BAND_LOW = 0.8
_BAND_HIGH = 1.2

# Per-topic quota bounds, applied when the target is split across topics.
MIN_PER_TOPIC = 2
MAX_PER_TOPIC = 5

# Two anchors disagreeing by more than this means one of them is wrong -- almost
# always a partly-parsed learning-outcome table. Reported, never acted on.
_ANCHOR_DIVERGENCE = 2.0


@dataclass
class Budget:
    """The concept allowance for one chapter, and why it is that number."""

    target: int
    low: int
    high: int
    floor: int
    ceiling: int
    source: str                       # learning_outcomes | competencies | periods | topics
    quota: List[int] = field(default_factory=list)   # one per topic, sums to target
    signals: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        """Persisted onto chapter_master.concept_budget and returned to the UI."""
        return {
            "target": self.target,
            "low": self.low,
            "high": self.high,
            "floor": self.floor,
            "ceiling": self.ceiling,
            "source": self.source,
            "quota": self.quota,
            "signals": self.signals,
            "warnings": self.warnings,
        }


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _anchor(
    *, lo_count: int, competency_count: int, periods: int | None, topic_count: int
) -> tuple[int, str]:
    """The first signal that fires wins. Ordered most to least specific."""
    if lo_count >= _MIN_LEARNING_OUTCOMES:
        return round(_PER_LEARNING_OUTCOME * lo_count), "learning_outcomes"
    if competency_count >= _MIN_COMPETENCIES:
        return round(_PER_COMPETENCY * competency_count), "competencies"
    if periods and periods >= 1:
        return round(_PER_PERIOD * periods), "periods"
    return round(_PER_TOPIC_FALLBACK * topic_count), "topics"


def distribute(
    target: int,
    spans: Sequence[tuple[int, int]],
    *,
    minimum: int = MIN_PER_TOPIC,
    maximum: int = MAX_PER_TOPIC,
) -> List[int]:
    """Split ``target`` across topics in proportion to the text each one owns.

    This is the one place chapter length belongs. ``spans`` comes from
    ct.partition_by_topics, which tiles the chapter with no gaps and no overlaps,
    so the shares are a real measure of how much each topic teaches.

    Guarantees: every topic gets at least ``minimum``, none gets more than
    ``maximum``, and the result sums to ``target`` whenever the bounds allow it
    (when they do not -- a target of 8 across 6 topics at a minimum of 2 -- the
    bounds win and the caller's target is quietly raised to 12, because a topic
    with one concept under it is a broken hierarchy).
    """
    count = len(spans)
    if count == 0:
        return []

    sizes = [max(1, end - start) for start, end in spans]
    total = sum(sizes)

    quota = [_clamp(round(target * size / total), minimum, maximum) for size in sizes]

    # Push the remainder onto the topics that can still take it, largest span
    # first, so the correction lands where there is most material to draw on.
    order = sorted(range(count), key=lambda i: sizes[i], reverse=True)
    guard = 0
    while sum(quota) != target and guard < count * (maximum - minimum + 1):
        guard += 1
        drift = target - sum(quota)
        moved = False
        for index in (order if drift > 0 else reversed(order)):
            if drift > 0 and quota[index] < maximum:
                quota[index] += 1
                moved = True
                break
            if drift < 0 and quota[index] > minimum:
                quota[index] -= 1
                moved = True
                break
        if not moved:
            # Every topic is pinned at a bound. The bounds win.
            break

    return quota


def chapter_budget(
    *,
    topic_count: int,
    spans: Sequence[tuple[int, int]] | None = None,
    lo_count: int = 0,
    competency_count: int = 0,
    periods: int | None = None,
    chapter_chars: int | None = None,
) -> Budget:
    """The concept allowance for one chapter.

    ``chapter_chars`` is accepted only so it can be recorded alongside the
    decision. It is deliberately not an input to the arithmetic.
    """
    topic_count = max(1, int(topic_count or 1))

    raw, source = _anchor(
        lo_count=lo_count,
        competency_count=competency_count,
        periods=periods,
        topic_count=topic_count,
    )

    warnings: List[str] = []

    floor = max(_FLOOR_PER_TOPIC * topic_count, _ABSOLUTE_FLOOR)
    ceiling = min(_CEILING_PER_TOPIC * topic_count, _ABSOLUTE_CEILING)
    if floor > ceiling:
        # More than 15 topics: two concepts each already exceeds the absolute
        # ceiling. The floor wins, because a topic with fewer than two concepts
        # under it is a broken hierarchy -- validation_service reports a
        # childless topic as an error -- whereas the ceiling is a judgement
        # about granularity. It is still worth saying out loud, because the
        # topic stage caps a chapter at 10 and warns beyond that, so reaching
        # here at all means the chapter was split below the topic level.
        warnings.append(
            f"{topic_count} topics need at least {floor} concepts, above the "
            f"cap of {_ABSOLUTE_CEILING}; the chapter was probably split below "
            f"the topic level"
        )
        ceiling = floor

    target = _clamp(raw, floor, ceiling)
    low = max(floor, round(target * _BAND_LOW))
    high = min(ceiling, max(low, round(target * _BAND_HIGH)))

    # Cross-check the two independent curriculum signals where both exist. A
    # wide divergence almost always means the learning-outcome table was only
    # partly parsed out of the syllabus PDF.
    period_anchor = round(_PER_PERIOD * periods) if periods else None
    if source == "learning_outcomes" and period_anchor:
        ratio = max(raw, period_anchor) / max(1, min(raw, period_anchor))
        if ratio > _ANCHOR_DIVERGENCE:
            warnings.append(
                f"learning outcomes suggest {raw} concepts but {periods} periods "
                f"suggest {period_anchor}; the outcome table may be incomplete"
            )

    quota = distribute(target, spans) if spans else []
    if quota and sum(quota) != target:
        # distribute() hit its bounds. The bounds are the real constraint.
        warnings.append(
            f"per-topic bounds moved the total from {target} to {sum(quota)}"
        )
        target = sum(quota)
        low = min(low, target)
        high = max(high, target)

    return Budget(
        target=target,
        low=low,
        high=high,
        floor=floor,
        ceiling=ceiling,
        source=source,
        quota=quota,
        signals={
            "topic_count": topic_count,
            "learning_outcomes": lo_count,
            "competencies": competency_count,
            "periods": periods,
            "chapter_chars": chapter_chars,
            "anchor_raw": raw,
            "period_anchor": period_anchor,
        },
        warnings=warnings,
    )


# --- enforcement ----------------------------------------------------------

# What a concept has to score before the quality trim will spare it when the
# topic is over quota. Set below the grounding weight on purpose: a concept
# whose evidence quote was found verbatim in the chapter scores 2.0 and is
# therefore never removed for being over budget. Only the hard ceiling can
# touch it.
QUALITY_BAR = 1.2

_W_GROUNDED = 2.0
_W_ATTRIBUTION = 1.0
_W_OUTCOME = 0.5
_W_IN_OUTLINE = 0.3
_P_REVISION = 1.0

# Attribution saturates here rather than at 1.0: a legitimately generalised
# concept name ("Sign rule for integer division" over text that says "negative
# divided by positive") never reaches full overlap, and should not be punished
# for it. Mirrors _ATTRIBUTION_OK in validation_service.
_ATTRIBUTION_FULL = 0.6


def keep_score(
    concept: Dict[str, Any],
    *,
    slice_stems: set[str],
    outline_stems: set[str],
    outcome_stems: set[str],
    in_revision_block: bool = False,
) -> float:
    """How much evidence there is that this concept belongs in the chapter.

    Not a confidence score -- this one only has to rank a topic's concepts
    against each other well enough to decide which to drop. Confidence is
    computed separately, after the survivors are known.
    """
    score = 0.0
    if concept.get("evidence_verified"):
        score += _W_GROUNDED

    name = concept.get("name") or ""
    attribution = ct.coverage(name, slice_stems)
    score += _W_ATTRIBUTION * min(1.0, attribution / _ATTRIBUTION_FULL)

    if outcome_stems:
        score += _W_OUTCOME * ct.coverage(name, outcome_stems)

    if outline_stems and ct.coverage(name, outline_stems) >= 0.5:
        score += _W_IN_OUTLINE

    if in_revision_block:
        # Exercise and revision blocks practise material taught elsewhere. A
        # concept drawn from one is a duplicate of a real concept, worded
        # differently -- exactly what validation_service check 2 detects.
        score -= _P_REVISION

    return score


def enforce_quota(
    results: List[Dict[str, Any]],
    budget: Budget,
    *,
    md_content: str,
    outline_text: str = "",
    outcome_text: str = "",
    ceiling_per_topic: int = MAX_PER_TOPIC,
    min_per_topic: int = MIN_PER_TOPIC,
) -> List[Dict[str, Any]]:
    """Cut each topic back to its quota, weakest evidence first.

    ``results`` is the shape concept_service builds: a list of
    ``{"topic_id", "topic_name", "concepts": [...]}`` in chapter teaching order.
    It is modified in place; the return value is the list of what was dropped,
    so the job payload can show it rather than trimming silently.

    Two rules, applied in order, and the difference between them matters:

      1. A COUNT ceiling: at most one more than the topic's allowance, and never
         more than ceiling_per_topic. Nothing survives above it whatever it
         scores.
      2. An EVIDENCE floor: anything below QUALITY_BAR is dropped, down to
         min_per_topic, whether or not the topic is over its allowance.

    Rule 2 is deliberately not conditioned on being over quota. Keeping a
    concept that no quote supports merely because the topic has not reached its
    allowance is padding to a number, which is the thing the allowance exists to
    prevent; a topic that honestly teaches three ideas should return three.

    Between them, a chapter returning 37 concepts with a long ungrounded tail is
    cut hard, while one whose concepts are all well evidenced keeps up to its
    allowance plus one per topic. Trimming purely to the number would throw away
    good concepts from good chapters to hit an average.
    """
    if not results:
        return []

    spans = ct.partition_by_topics(md_content, [r["topic_name"] for r in results])
    sections = ct.split_sections(md_content)
    outline_stems = ct.stems(outline_text)
    outcome_stems = ct.stems(outcome_text)

    quota = budget.quota or [budget.target // max(1, len(results))] * len(results)

    dropped: List[Dict[str, Any]] = []
    for index, result in enumerate(results):
        concepts = result.get("concepts") or []
        if not concepts:
            continue

        start, end = spans[index] if index < len(spans) else (0, len(md_content))
        slice_stems = ct.stems(md_content[start:end])
        revision = _is_revision_span(sections, start, end)

        for concept in concepts:
            concept["keep_score"] = round(
                keep_score(
                    concept,
                    slice_stems=slice_stems,
                    outline_stems=outline_stems,
                    outcome_stems=outcome_stems,
                    in_revision_block=revision,
                ),
                3,
            )

        # Stable sort, so equal scores keep the model's own order -- which is
        # the order the book teaches them in.
        ranked = sorted(concepts, key=lambda c: -c["keep_score"])
        want = max(min_per_topic, quota[index] if index < len(quota) else min_per_topic)

        # 1. Count ceiling. The prompt asks for the allowance "or N-1 or N+1",
        #    so one over is honoured and anything beyond it is not.
        limit = max(min_per_topic, min(ceiling_per_topic, want + 1))
        kept = ranked[:limit]
        for concept in ranked[limit:]:
            dropped.append(_drop(result, concept, f"over the allowance of {want}"))

        # 2. Evidence floor, applied whether or not the topic is over its
        #    allowance. A concept no quote supports is not worth keeping to
        #    reach a number.
        while len(kept) > min_per_topic and kept[-1]["keep_score"] < QUALITY_BAR:
            dropped.append(_drop(result, kept.pop(), "not supported by the chapter text"))

        # Back into teaching order: the dedupe downstream keeps the earliest
        # occurrence of an idea, which is only meaningful if order is preserved.
        by_id = {id(c): i for i, c in enumerate(concepts)}
        result["concepts"] = sorted(kept, key=lambda c: by_id[id(c)])

    if dropped:
        logger.info(
            "Quota enforcement dropped %s concept(s) against a target of %s (%s)",
            len(dropped), budget.target, budget.source,
        )
    return dropped


def _drop(result: Dict[str, Any], concept: Dict[str, Any], reason: str) -> Dict[str, Any]:
    return {
        "topic_id": result.get("topic_id"),
        "topic_name": result.get("topic_name"),
        "name": concept.get("name"),
        "keep_score": concept.get("keep_score"),
        "evidence_verified": bool(concept.get("evidence_verified")),
        "reason": reason,
    }


def _is_revision_span(
    sections: List[Dict[str, Any]], start: int, end: int
) -> bool:
    """Whether a topic's span sits mostly inside revision rather than teaching.

    split_sections already classifies each block; this only has to find which
    block holds the midpoint of the span, which is cheap and robust to a span
    that laps slightly over a boundary.
    """
    if not sections:
        return False
    midpoint = (start + end) // 2
    cursor = 0
    for section in sections:
        length = len(section["text"])
        if cursor <= midpoint < cursor + length:
            return section["kind"] == "revision"
        cursor += length
    return False
