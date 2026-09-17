"""Gate check for the concept generation stage, with no LLM and no database.

generate_concepts() is deliberately free of both: it takes the chapter, the
topics, the budget and the curriculum frame as arguments, and returns the
results for its caller to persist. That makes the part of the pipeline most
worth testing -- prompt assembly, quota enforcement, curriculum mapping and
scoring -- testable offline, which is the point.

The scenario below is the failure this whole change exists to prevent: the model
returns far more concepts than the chapter can teach, including several that are
not in the chapter at all, and the code has to cut it back to the budget without
throwing away the real ones.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import concept_service  # noqa: E402
from app.services.concept_budget import chapter_budget  # noqa: E402
from app.services.curriculum_frame import CurriculumFrame, Outcome  # noqa: E402

TOPIC_A = "Adding and subtracting integers"
TOPIC_B = "Multiplying and dividing integers"

MD = (
    f"# {TOPIC_A}\n"
    + "Adding integers with different signs means you subtract the smaller magnitude "
      "from the larger and keep the sign of the larger. Subtracting a negative integer "
      "is the same as adding its opposite. A number line shows this movement. " * 30
    + f"\n# {TOPIC_B}\n"
    + "The sign rule for integer division follows directly from multiplication: a "
      "negative divided by a positive is negative, and two negatives give a positive. "
      "Multiplying two negative integers gives a positive result. " * 30
)

TOPICS = [
    {"id": 1, "name": TOPIC_A, "description": "Adding and subtracting.", "estimated_minutes": 30},
    {"id": 2, "name": TOPIC_B, "description": "Multiplying and dividing.", "estimated_minutes": 30},
]

FRAME = CurriculumFrame(
    chapter_id=99,
    curriculum_id=7,
    learning_outcomes=[
        Outcome(id=901, code="C-1.1-LO-1", type="learning_outcome",
                description="Add and subtract integers with different signs", parent_id=800),
        Outcome(id=902, code="C-1.1-LO-2", type="learning_outcome",
                description="Apply the sign rule when multiplying and dividing integers",
                parent_id=800),
        Outcome(id=903, code="C-1.1-LO-3", type="learning_outcome",
                description="Represent integer operations on a number line", parent_id=800),
        Outcome(id=904, code="C-1.1-LO-4", type="learning_outcome",
                description="Order and compare integers", parent_id=800),
    ],
    competencies=[
        Outcome(id=800, code="C1.1", type="competency",
                description="Operates fluently with integers", parent_id=700),
    ],
    goals=[Outcome(id=700, code="CG1", type="goal", description="Number sense")],
)


def _reply(per_topic: int, junk: int) -> dict:
    """A model answer with `junk` concepts that are nowhere in the chapter."""
    real_a = [
        ("Adding integers with different signs", "Adding integers with different signs means you subtract"),
        ("Subtracting a negative integer", "Subtracting a negative integer is the same as adding"),
        ("Integer addition on a number line", "A number line shows this movement"),
    ]
    real_b = [
        ("Sign rule for integer division", "a negative divided by a positive is negative"),
        ("Multiplying two negative integers", "Multiplying two negative integers gives a positive result"),
    ]

    def block(name, real):
        concepts = []
        for concept_name, quote in real[:per_topic]:
            concepts.append({
                "name": concept_name,
                "description": f"{concept_name}.",
                "estimated_mastery_minutes": 10,
                "source_evidence": quote,
                "curriculum_codes": ["C-1.1-LO-1"] if "Adding" in concept_name else [],
            })
        for i in range(junk):
            concepts.append({
                "name": f"Quantum chromodynamics {i}",
                "description": "Not taught in this chapter at all.",
                "estimated_mastery_minutes": 10,
                "source_evidence": "no such sentence exists anywhere in this chapter",
                "curriculum_codes": ["C-99.9"],   # an invented code
            })
        return {"topic_name": name, "concepts": concepts}

    return {"topics": [block(TOPIC_A, real_a), block(TOPIC_B, real_b)]}


class _Stub:
    """Stands in for async_call_deepseek, capturing the prompt it was given."""

    def __init__(self, payload):
        self.payload = payload
        self.prompt = ""

    async def __call__(self, prompt, system_prompt="", response_format=None, max_retries=3):
        self.prompt = prompt
        return {"data": self.payload, "input_tokens": 100, "output_tokens": 50}


def _run(payload, budget, frame=FRAME):
    stub = _Stub(payload)
    original = concept_service.async_call_deepseek
    concept_service.async_call_deepseek = stub
    try:
        result = asyncio.run(concept_service.generate_concepts(
            extraction_id=1,
            md_content=MD,
            all_topics=TOPICS,
            budget=budget,
            frame=frame,
            chapter_name="Integers",
        ))
    finally:
        concept_service.async_call_deepseek = original
    return result, stub


def _check(failures, label, got, want):
    if got != want:
        failures.append(f"{label}: got {got!r}, want {want!r}")


def test_prompt_carries_budget_and_curriculum(failures: list[str]) -> None:
    budget = chapter_budget(topic_count=2, spans=[(0, len(MD) // 2), (len(MD) // 2, len(MD))],
                            lo_count=FRAME.lo_count)
    _, stub = _run(_reply(2, 0), budget)

    if "[Concepts:" not in stub.prompt:
        failures.append("the per-topic concept allowance never reached the prompt")
    if "C-1.1-LO-1" not in stub.prompt:
        failures.append("the curriculum outcomes never reached the prompt")
    if "CG1 (Curricular Goal)" not in stub.prompt:
        failures.append("the curricular goal never reached the prompt")
    if "{min_concepts}" in stub.prompt or "{target_concepts}" in stub.prompt:
        failures.append("a prompt placeholder was left unsubstituted")
    if "mastery_threshold" in stub.prompt:
        failures.append(
            "generation still asks for mastery_threshold; that belongs to the "
            "enrichment stage now"
        )


def test_quota_is_enforced(failures: list[str]) -> None:
    """The model returns 16; the budget allows 8. The junk goes, the real stays."""
    budget = chapter_budget(topic_count=2, spans=[(0, len(MD) // 2), (len(MD) // 2, len(MD))],
                            lo_count=FRAME.lo_count)
    result, _ = _run(_reply(3, 5), budget)

    kept = [c["name"] for r in result["results"] for c in r["concepts"]]
    if any(name.startswith("Quantum") for name in kept):
        failures.append(f"ungrounded junk survived the trim: {kept}")
    for required in ("Adding integers with different signs", "Sign rule for integer division"):
        if required not in kept:
            failures.append(f"a grounded concept was trimmed: {required}")

    if len(kept) > budget.ceiling:
        failures.append(f"{len(kept)} concepts kept, above the ceiling of {budget.ceiling}")
    if not result["trimmed"]:
        failures.append("nothing was reported as trimmed from a 16-concept reply")
    for entry in result["trimmed"]:
        if entry.get("keep_score") is None:
            failures.append("a trimmed concept carried no score to explain it")

    _check(failures, "grounded count", result["grounded_concepts"], len(kept))
    _check(failures, "ungrounded count", result["ungrounded_concepts"], 0)


def test_curriculum_mapping(failures: list[str]) -> None:
    budget = chapter_budget(topic_count=2, spans=[(0, len(MD) // 2), (len(MD) // 2, len(MD))],
                            lo_count=FRAME.lo_count)
    result, _ = _run(_reply(3, 0), budget)

    every = [c for r in result["results"] for c in r["concepts"]]
    codes = {m["outcome_code"] for c in every for m in c["curriculum_mappings"]}
    if "C-99.9" in codes:
        failures.append("an invented curriculum code was written through")
    if not codes:
        failures.append("no concept mapped to any curriculum outcome")
    if not (codes & {"C-1.1-LO-1", "C-1.1-LO-2", "C-1.1-LO-3", "C1.1"}):
        failures.append(f"mappings do not reference this chapter's outcomes: {codes}")

    cited = next((c for c in every if c["name"] == "Adding integers with different signs"), None)
    if cited:
        sources = {m["match_source"] for m in cited["curriculum_mappings"]}
        if "llm" not in sources:
            failures.append("a validly cited code was not recorded as an llm match")

    for concept in every:
        if concept.get("confidence") is None:
            failures.append(f"{concept['name']} was persisted without a confidence")
        if concept.get("confidence_profile") != "curriculum":
            failures.append(
                f"{concept['name']} scored under {concept.get('confidence_profile')!r}; "
                f"a chapter with 4 outcomes should use the curriculum profile"
            )


def test_no_curriculum_still_works(failures: list[str]) -> None:
    """The common case: 83 of 122 chapters have no syllabus loaded."""
    budget = chapter_budget(topic_count=2, spans=[(0, len(MD) // 2), (len(MD) // 2, len(MD))])
    result, stub = _run(_reply(3, 0), budget, frame=CurriculumFrame())

    if "no curriculum" not in stub.prompt:
        failures.append("the prompt did not tell the model that no curriculum is loaded")

    every = [c for r in result["results"] for c in r["concepts"]]
    for concept in every:
        if concept.get("confidence_profile") != "content":
            failures.append(
                f"{concept['name']} used the {concept.get('confidence_profile')!r} profile "
                f"with no curriculum loaded"
            )
        if concept["curriculum_mappings"]:
            failures.append(f"{concept['name']} mapped to an outcome that does not exist")
    best = max(c["confidence"] for c in every)
    if best < 0.8:
        failures.append(
            f"the best concept in a curriculum-less chapter reached only {best}; "
            f"such chapters must still be able to score as accepted"
        )


def test_minutes_still_add_up(failures: list[str]) -> None:
    budget = chapter_budget(topic_count=2, spans=[(0, len(MD) // 2), (len(MD) // 2, len(MD))],
                            lo_count=FRAME.lo_count)
    result, _ = _run(_reply(3, 4), budget)
    for entry in result["results"]:
        total = sum(c["estimated_mastery_minutes"] for c in entry["concepts"])
        if abs(total - entry["topic_minutes"]) > 2:
            failures.append(
                f"{entry['topic_name']}: concepts sum to {total} min against a "
                f"{entry['topic_minutes']} min budget"
            )


def main() -> int:
    failures: list[str] = []
    for test in (test_prompt_carries_budget_and_curriculum, test_quota_is_enforced,
                 test_curriculum_mapping, test_no_curriculum_still_works,
                 test_minutes_still_add_up):
        try:
            test(failures)
        except Exception as exc:
            failures.append(f"{test.__name__} raised {type(exc).__name__}: {exc}")

    if failures:
        print("\nFAIL")
        for failure in failures:
            print("  -", failure)
        return 1

    print("\nPASS  16 concepts offered, budget enforced, junk and invented codes dropped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
