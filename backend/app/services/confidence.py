"""How much to believe a generated topic or concept.

Before this module there was no confidence on a concept or a topic anywhere.
The extraction queues asked the model for an exact `source_evidence` quote,
checked it against the chapter, counted the result into the HTTP response --
and then dropped both the quote and the verdict at INSERT time. The one hard,
checkable fact about a row was computed and thrown away.

Everything scored here is measured, never self-reported. Asking a model for its
own confidence produces 0.85-0.95 for everything, which ranks nothing; the
Semantic Intelligence payload has carried exactly such a field for a year and
nothing has ever branched on it.

    grounding_chapter   the evidence quote is present in the chapter, verbatim
    grounding_span      ...and inside the part of the chapter its own topic owns
    attribution         the name's words appear in that same span
    distinctness        the name is not a near-repeat of a sibling
    curriculum_anchor   the concept maps to a competency or outcome of this chapter

WHAT THIS SCORE DOES NOT MEASURE, stated plainly: granularity. Nothing above
can tell that a chapter was split into 74 ideas where it teaches 20 -- every one
of the 74 can be perfectly grounded. Granularity is handled structurally, by
concept_budget's quota and trim, and deliberately not here. The component that
would catch it is cross-sample agreement (generate twice, see what survives),
which costs a second call per chapter; the weights below are laid out so it can
be added later without re-deriving the rest.

Two profiles, recorded per row, because 83 of 122 chapters in this corpus have
no curriculum data at all. Scoring those against a curriculum term they had no
chance to satisfy would cap them below the flag line for a reason that is not
their fault, and the flag would then mean "this subject has no syllabus loaded"
rather than "this concept is doubtful".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

from app.services import chapter_text as ct

logger = logging.getLogger(__name__)


# Weights per profile. Each set sums to 1.0.
WEIGHTS: Dict[str, Dict[str, float]] = {
    # No usable curriculum: the book is the only authority, so the evidence
    # terms carry everything.
    "content": {
        "grounding_chapter": 0.30,
        "grounding_span": 0.25,
        "attribution": 0.30,
        "distinctness": 0.15,
    },
    # A syllabus exists for this chapter, and serving it is the strongest single
    # statement that a concept belongs.
    "curriculum": {
        "grounding_chapter": 0.22,
        "grounding_span": 0.18,
        "attribution": 0.20,
        "distinctness": 0.10,
        "curriculum_anchor": 0.30,
    },
    # Legacy rows, scored by the backfill. source_evidence was never persisted
    # before this release, so neither grounding term can be computed and the
    # score is NOT comparable with a live one -- which is why it is a separate
    # profile name rather than a "content" score with two zeroes in it.
    "deterministic_backfill": {
        "attribution": 0.55,
        "distinctness": 0.20,
        "curriculum_anchor": 0.25,
    },
}

# Attribution saturates below 1.0 for the same reason as in concept_budget: a
# concept that legitimately generalises its section ("Sign rule for integer
# division" over text reading "a negative divided by a positive") never reaches
# full word overlap and must not be punished for it. Mirrors
# validation_service._ATTRIBUTION_OK.
_ATTRIBUTION_FULL = 0.6
_TOPIC_GROUNDING_FULL = 0.6

# An audit error means the row is wrong; a warning means it is suspect. Sized so
# that one error drops a mid-band row under the flag line and two drop it under
# the repair line, while a couple of warnings only nudge it.
_ERROR_PENALTY = 0.20
_WARNING_PENALTY = 0.08

# Bands. Nothing here blocks on a human: `flagged` still ships.
ACCEPT = 0.80
FLAG = 0.55

STATUS_ACCEPTED = "auto_accepted"
STATUS_FLAGGED = "flagged"
STATUS_LOW = "low_confidence"

# A chapter whose audit fails outright cannot have concepts that are individually
# above suspicion, so the roll-up is discounted rather than averaged blindly.
_FAILED_AUDIT_FACTOR = 0.85


@dataclass
class Score:
    value: float
    profile: str
    status: str
    parts: Dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {"value": self.value, "profile": self.profile,
                "status": self.status, "parts": self.parts}


def band(value: float) -> str:
    if value >= ACCEPT:
        return STATUS_ACCEPTED
    if value >= FLAG:
        return STATUS_FLAGGED
    return STATUS_LOW


def _combine(parts: Dict[str, float], profile: str, errors: int, warnings: int) -> Score:
    """Weighted mean over the components that could actually be measured.

    Renormalising over the PRESENT components, rather than dividing by the
    profile's full weight, is the whole point of having profiles. A component
    that could not be computed -- no curriculum loaded for this subject, or a
    legacy row whose evidence quote was never stored -- must be absent, not
    zero. Counting it as zero is indistinguishable from the row having failed
    it, and the first measurement over real data showed exactly what that costs:
    every chapter without a syllabus capped at 0.55, the precise value of the
    one weight it could satisfy, so nothing above the flag line was reachable
    and the score ranked nothing.

    A caller therefore signals "not measurable" by leaving the key out of
    ``parts``, and "measured, and it failed" by passing 0.0.
    """
    weights = WEIGHTS.get(profile) or WEIGHTS["content"]
    present = {key: weight for key, weight in weights.items() if key in parts}
    if not present:
        present = weights

    total = sum(present.values()) or 1.0
    raw = sum(weight * parts.get(key, 0.0) for key, weight in present.items()) / total

    value = raw - (_ERROR_PENALTY * errors) - (_WARNING_PENALTY * warnings)
    value = max(0.0, min(1.0, value))
    rounded = round(value, 3)

    recorded = {key: round(parts[key], 3) for key in present}
    recorded["raw"] = round(raw, 3)
    if len(present) < len(weights):
        recorded["not_measured"] = sorted(set(weights) - set(present))
    if errors:
        recorded["errors"] = errors
    if warnings:
        recorded["warnings"] = warnings

    return Score(value=rounded, profile=profile, status=band(rounded), parts=recorded)


def profile_for(*, curriculum_usable: bool) -> str:
    return "curriculum" if curriculum_usable else "content"


def distinctness(name: str, siblings: Sequence[str]) -> float:
    """1.0 when nothing else in the chapter says the same thing.

    Uses the same containment test the dedupe pass uses, so a concept that only
    just survived dedupe scores low here rather than looking clean. On extraction
    175 the audit reports 37 overlapping-concept warnings against 74 concepts --
    half the chapter -- which is exactly the signal this term exists to surface.
    """
    if not siblings:
        return 1.0
    worst = max(
        (ct.name_containment(name, other) for other in siblings if other), default=0.0
    )
    return max(0.0, 1.0 - worst)


def score_concept(
    concept: Dict[str, Any],
    *,
    profile: str,
    md_content: str,
    span: tuple[int, int],
    slice_stems: set[str] | None = None,
    siblings: Sequence[str] = (),
    outcome_stems: set[str] | None = None,
    mapped_outcomes: Sequence[Dict[str, Any]] = (),
    curriculum_available: bool = False,
    errors: int = 0,
    warnings: int = 0,
) -> Score:
    """Confidence for one concept, from evidence only.

    ``span`` is its topic's (start, end) in the chapter, from
    ct.partition_by_topics -- the same partition the extracting call was shown
    and the same one validation_service audits against, so all three agree on
    where a topic begins.

    ``curriculum_available`` separates "this chapter has a syllabus and this
    concept does not serve it" (a real deduction) from "no syllabus is loaded
    for this subject" (not this concept's fault, so the term is dropped and the
    remaining weights renormalise). Getting that wrong capped every chapter
    without a syllabus -- 83 of the 122 here -- below the flag line.
    """
    name = concept.get("name") or ""
    quote = " ".join(str(concept.get("source_evidence") or "").split()).lower()

    parts: Dict[str, float] = {}

    # 1. The quote is somewhere in the chapter. Recomputed rather than trusting
    #    the flag, so a row loaded back from the database scores the same way.
    verified = bool(concept.get("evidence_verified"))
    if quote and not verified:
        verified = quote in " ".join((md_content or "").split()).lower()
    parts["grounding_chapter"] = 1.0 if verified else 0.0

    # 2. The quote is in the part of the chapter this concept's own topic owns.
    #    Strictly stronger than 1, and the thing prompt rule 11 actually asks
    #    for -- which nothing has ever checked.
    start, end = span
    if verified and quote:
        own_slice = " ".join((md_content or "")[start:end].split()).lower()
        parts["grounding_span"] = 1.0 if quote in own_slice else 0.0
    else:
        parts["grounding_span"] = 0.0

    # 3. The name's own words appear in that span.
    if slice_stems is None:
        slice_stems = ct.stems((md_content or "")[start:end])
    parts["attribution"] = min(1.0, ct.coverage(name, slice_stems) / _ATTRIBUTION_FULL)

    # 4. Nothing else in the chapter is the same idea worded differently.
    parts["distinctness"] = distinctness(name, siblings)

    # 5. The curriculum. A mapping the model cited and that survived code
    #    validation is worth more than a lexical one, which is capped at 0.45 by
    #    curriculum_frame precisely so it cannot masquerade as comprehension.
    #    Set only when there is a syllabus to be measured against: see the
    #    docstring on curriculum_available.
    measurable = curriculum_available or bool(mapped_outcomes) or bool(outcome_stems)
    if measurable and "curriculum_anchor" in (WEIGHTS.get(profile) or {}):
        anchor = 0.0
        if mapped_outcomes:
            anchor = max(float(m.get("match_score") or 0.0) for m in mapped_outcomes)
            # A validated citation is a real alignment; scale it up to full.
            anchor = min(1.0, anchor / 0.9)
        elif outcome_stems:
            anchor = min(1.0, ct.coverage(name, outcome_stems) / _ATTRIBUTION_FULL)
        parts["curriculum_anchor"] = anchor

    return _combine(parts, profile, errors, warnings)


def score_topic(
    topic: Dict[str, Any],
    *,
    md_content: str,
    chapter_stems: set[str] | None = None,
    outline_text: str = "",
    errors: int = 0,
    warnings: int = 0,
) -> Score:
    """Confidence for one topic.

    Simpler than a concept's, because a topic has no parent span to sit inside
    and no siblings it could duplicate without the dedupe having caught it. The
    extra term is the book's own outline: a topic that matches a numbered
    section the chapter printed is as certain as this pipeline gets.
    """
    name = topic.get("name") or topic.get("topic_name") or ""
    quote = " ".join(str(topic.get("source_evidence") or "").split()).lower()

    if chapter_stems is None:
        chapter_stems = ct.stems(md_content)

    verified = bool(topic.get("evidence_verified"))
    if quote and not verified:
        verified = quote in " ".join((md_content or "").split()).lower()

    in_outline = 0.0
    if outline_text and ct.coverage(name, ct.stems(outline_text)) >= 0.5:
        in_outline = 1.0

    parts = {
        "grounding_chapter": 1.0 if verified else 0.0,
        # A topic name generalises its section more often than a concept name
        # does, so this saturates at the same soft bar rather than demanding
        # every word appear.
        "attribution": min(1.0, ct.coverage(name, chapter_stems) / _TOPIC_GROUNDING_FULL),
        "grounding_span": in_outline,
        "distinctness": 1.0,
    }
    return _combine(parts, "content", errors, warnings)


def chapter_confidence(scores: Sequence[Score], *, audit_passed: bool = True) -> float:
    """The roll-up written to chapter_master.extraction_confidence."""
    if not scores:
        return 0.0
    mean = sum(s.value for s in scores) / len(scores)
    if not audit_passed:
        mean *= _FAILED_AUDIT_FACTOR
    return round(max(0.0, min(1.0, mean)), 3)


def rescore_with_audit(
    parts: Dict[str, Any], profile: str, errors: int, warnings: int
) -> Score:
    """Re-apply the penalties to a score whose components are already known.

    The audit can only run once the rows are in the database -- it reads them
    back and measures them against the chapter -- so a concept is necessarily
    scored before its issues are known. Rather than re-measure everything, this
    reuses the stored `raw` weighted mean and applies the penalties to it, which
    is exactly what _combine would have done had the issues been available.

    Keeping the arithmetic in one place matters: a second, slightly different
    penalty formula here is how the number on the row stops meaning what the
    docstring at the top of this module says it means.
    """
    raw = float(parts.get("raw") or 0.0)
    value = max(0.0, min(1.0, raw - (_ERROR_PENALTY * errors) - (_WARNING_PENALTY * warnings)))
    rounded = round(value, 3)

    recorded = dict(parts)
    recorded["errors"] = errors
    recorded["warnings"] = warnings
    return Score(value=rounded, profile=profile, status=band(rounded), parts=recorded)


def issues_by_id(report: Dict[str, Any], key: str) -> Dict[int, Dict[str, int]]:
    """Index an audit report's issues by the row each one is about.

    validate_extraction already tags most issues with a concept_id or topic_id;
    reading those beats re-parsing the human-readable message, which is what a
    caller would otherwise be reduced to.
    """
    out: Dict[int, Dict[str, int]] = {}
    for issue in (report or {}).get("issues", []) or []:
        targets: List[Any] = []
        if issue.get(key) is not None:
            targets.append(issue[key])
        # duplicate_pairs reports a pair under `ids` rather than a single id.
        if key == "concept_id":
            targets.extend(issue.get("ids", []) or [])
        for target in targets:
            try:
                row = out.setdefault(int(target), {"errors": 0, "warnings": 0})
            except (TypeError, ValueError):
                continue
            if issue.get("severity") == "error":
                row["errors"] += 1
            else:
                row["warnings"] += 1
    return out
