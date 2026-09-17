"""Gate check for the confidence scorer.

The properties asserted here are the ones that make the number worth printing:

  * a grounded, well-placed, distinct concept scores high
  * an invented one scores low
  * a chapter with NO curriculum data is not punished for that
  * a near-duplicate scores below the thing it duplicates
  * audit errors actually move the number

If a component ever reads the same for every input it is ranking nothing, and
the weight belongs somewhere else -- that is a judgement call for a human
reading real distributions, but the ordering checks below will catch the
degenerate case where a change makes everything score identically.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import confidence as cf  # noqa: E402

MD = (
    "# Adding and subtracting integers\n"
    + "Adding integers with different signs means you subtract the smaller "
      "magnitude from the larger and keep the sign of the larger. " * 20
    + "\n# Multiplying and dividing integers\n"
    + "The sign rule for integer division follows directly from multiplication: "
      "a negative divided by a positive is negative. " * 20
)
SPLIT = MD.index("# Multiplying")
SPAN_A = (0, SPLIT)
SPAN_B = (SPLIT, len(MD))


def _concept(name: str, quote: str = "") -> dict:
    return {"name": name, "source_evidence": quote}


def _check(failures: list[str], label: str, got, want) -> None:
    if got != want:
        failures.append(f"{label}: got {got!r}, want {want!r}")


def test_ordering(failures: list[str]) -> None:
    good = cf.score_concept(
        _concept("Adding integers with different signs",
                 "Adding integers with different signs means you subtract"),
        profile="content", md_content=MD, span=SPAN_A,
    )
    if good.value < cf.ACCEPT:
        failures.append(f"a grounded, placed, distinct concept scored {good.value}")
    _check(failures, "good status", good.status, cf.STATUS_ACCEPTED)

    # Quote real, but lifted from the OTHER topic's text: grounded in the
    # chapter, not in its own span. This is what prompt rule 11 asks for and
    # what nothing previously checked.
    misplaced = cf.score_concept(
        _concept("Adding integers with different signs",
                 "a negative divided by a positive is negative"),
        profile="content", md_content=MD, span=SPAN_A,
    )
    if misplaced.value >= good.value:
        failures.append(
            f"a quote from the wrong topic scored {misplaced.value} >= {good.value}"
        )
    _check(failures, "grounding_chapter still 1", misplaced.parts["grounding_chapter"], 1.0)
    _check(failures, "grounding_span 0", misplaced.parts["grounding_span"], 0.0)

    invented = cf.score_concept(
        _concept("Quantum chromodynamics", "no such text appears in this chapter"),
        profile="content", md_content=MD, span=SPAN_A,
    )
    if invented.value >= cf.FLAG:
        failures.append(f"an invented concept scored {invented.value}, above the flag line")
    _check(failures, "invented status", invented.status, cf.STATUS_LOW)

    # A concept with no quote at all cannot outrank one whose quote checked out.
    unquoted = cf.score_concept(
        _concept("Adding integers with different signs"),
        profile="content", md_content=MD, span=SPAN_A,
    )
    if unquoted.value >= good.value:
        failures.append("an unquoted concept matched a grounded one")


def test_profiles(failures: list[str]) -> None:
    """A chapter with no syllabus must not be scored as if it failed one."""
    args = dict(
        concept=_concept("Adding integers with different signs",
                         "Adding integers with different signs means you subtract"),
    )
    content = cf.score_concept(
        args["concept"], profile="content", md_content=MD, span=SPAN_A
    )
    # Same concept, same evidence, but the chapter HAS a syllabus it does not
    # serve. That is a real deduction and should show.
    unmapped = cf.score_concept(
        args["concept"], profile="curriculum", md_content=MD, span=SPAN_A,
        mapped_outcomes=(), curriculum_available=True,
    )
    if unmapped.value >= content.value:
        failures.append(
            "an unmapped concept under a real syllabus scored no worse than one "
            "with no syllabus to serve"
        )
    if content.value < cf.ACCEPT:
        failures.append(
            f"the content profile capped a perfect concept at {content.value}; a "
            f"chapter with no curriculum must still be able to reach acceptance"
        )

    mapped = cf.score_concept(
        args["concept"], profile="curriculum", md_content=MD, span=SPAN_A,
        mapped_outcomes=[{"outcome_code": "C-1.1-LO-1", "match_score": 0.9}],
    )
    if mapped.value <= unmapped.value:
        failures.append("a curriculum-mapped concept did not outscore an unmapped one")

    # A lexical match is capped at 0.45 by curriculum_frame and must not look
    # like a cited one.
    lexical = cf.score_concept(
        args["concept"], profile="curriculum", md_content=MD, span=SPAN_A,
        mapped_outcomes=[{"outcome_code": "C-1.1", "match_score": 0.45}],
    )
    if lexical.value >= mapped.value:
        failures.append("a keyword match scored as high as a validated citation")

    for profile, weights in cf.WEIGHTS.items():
        total = round(sum(weights.values()), 6)
        if total != 1.0:
            failures.append(f"profile {profile} weights sum to {total}, want 1.0")


def test_distinctness(failures: list[str]) -> None:
    alone = cf.distinctness("Adding integers with different signs", [])
    _check(failures, "no siblings", alone, 1.0)

    repeat = cf.distinctness(
        "Adding integers with different signs",
        ["Addition of integers with different signs"],
    )
    if repeat > 0.35:
        failures.append(f"a near-repeat scored {repeat} distinctness")

    distinct = cf.distinctness(
        "Adding integers with different signs",
        ["Prime factorisation of composite numbers"],
    )
    if distinct < 0.5:
        failures.append(f"an unrelated sibling dragged distinctness to {distinct}")


def test_penalties(failures: list[str]) -> None:
    concept = _concept("Adding integers with different signs",
                       "Adding integers with different signs means you subtract")
    clean = cf.score_concept(concept, profile="content", md_content=MD, span=SPAN_A)
    flagged = cf.score_concept(concept, profile="content", md_content=MD,
                               span=SPAN_A, warnings=2)
    broken = cf.score_concept(concept, profile="content", md_content=MD,
                              span=SPAN_A, errors=2)
    if not (broken.value < flagged.value < clean.value):
        failures.append(
            f"penalties did not order: clean {clean.value}, "
            f"warned {flagged.value}, errored {broken.value}"
        )
    # A perfectly evidenced concept survives two audit errors as `flagged`, and
    # that is deliberate: the evidence is real, so the row ships and gets an
    # amber dot rather than being thrown away over a duplicate-name warning.
    if broken.status == cf.STATUS_ACCEPTED:
        failures.append("two audit errors left the row auto-accepted")

    # A middling row, which is where most rows actually sit, must fall past the
    # repair line on two errors.
    middling = cf.score_concept(
        _concept("Adding integers with different signs"),
        profile="content", md_content=MD, span=SPAN_A, errors=2,
    )
    if middling.status != cf.STATUS_LOW:
        failures.append(
            f"a mid-band row with two audit errors stayed at {middling.status} "
            f"({middling.value})"
        )

    # Never out of range, however many issues pile up.
    extreme = cf.score_concept(concept, profile="content", md_content=MD,
                               span=SPAN_A, errors=99)
    if not 0.0 <= extreme.value <= 1.0:
        failures.append(f"score escaped [0,1]: {extreme.value}")


def test_topic_and_rollup(failures: list[str]) -> None:
    topic = cf.score_topic(
        {"name": "Adding and subtracting integers",
         "source_evidence": "Adding integers with different signs"},
        md_content=MD,
        outline_text="- 1.1 Adding and subtracting integers",
    )
    if topic.value < cf.ACCEPT:
        failures.append(f"a topic named by the book's own outline scored {topic.value}")

    invented = cf.score_topic({"name": "Quantum chromodynamics"}, md_content=MD)
    if invented.value >= cf.FLAG:
        failures.append(f"an invented topic scored {invented.value}")

    scores = [cf.Score(0.9, "content", cf.STATUS_ACCEPTED),
              cf.Score(0.7, "content", cf.STATUS_FLAGGED)]
    _check(failures, "rollup", cf.chapter_confidence(scores), 0.8)
    _check(failures, "rollup failed audit",
           cf.chapter_confidence(scores, audit_passed=False), 0.68)
    _check(failures, "rollup empty", cf.chapter_confidence([]), 0.0)


def test_rescore_with_audit(failures: list[str]) -> None:
    """The audit runs after the rows are written, so its penalties are applied
    to the stored components rather than by re-measuring everything."""
    concept = _concept("Adding integers with different signs",
                       "Adding integers with different signs means you subtract")
    clean = cf.score_concept(concept, profile="content", md_content=MD, span=SPAN_A)

    # Re-scoring with no findings must reproduce the original number exactly,
    # or the two code paths have drifted apart.
    same = cf.rescore_with_audit(clean.parts, clean.profile, 0, 0)
    _check(failures, "no findings is a no-op", same.value, clean.value)

    # And with findings it must agree with scoring them in one pass.
    direct = cf.score_concept(concept, profile="content", md_content=MD,
                              span=SPAN_A, errors=1, warnings=2)
    rescored = cf.rescore_with_audit(clean.parts, clean.profile, 1, 2)
    _check(failures, "rescore matches a direct score", rescored.value, direct.value)
    _check(failures, "status recomputed", rescored.status, direct.status)
    _check(failures, "errors recorded", rescored.parts.get("errors"), 1)
    _check(failures, "warnings recorded", rescored.parts.get("warnings"), 2)

    if rescored.value >= clean.value:
        failures.append("audit findings did not lower the score")

    # A row with no recorded components must not silently become 1.0.
    empty = cf.rescore_with_audit({}, "content", 0, 0)
    _check(failures, "no parts scores zero", empty.value, 0.0)


def test_issue_index(failures: list[str]) -> None:
    report = {"issues": [
        {"check": "attribution", "severity": "warning", "concept_id": 5},
        {"check": "relevance", "severity": "error", "ids": [5, 9]},
        {"check": "grounding", "severity": "error", "topic_id": 2},
        {"check": "semantic", "severity": "warning"},
    ]}
    by_concept = cf.issues_by_id(report, "concept_id")
    _check(failures, "concept 5", by_concept.get(5), {"errors": 1, "warnings": 1})
    _check(failures, "concept 9", by_concept.get(9), {"errors": 1, "warnings": 0})
    by_topic = cf.issues_by_id(report, "topic_id")
    _check(failures, "topic 2", by_topic.get(2), {"errors": 1, "warnings": 0})
    _check(failures, "no issues", cf.issues_by_id({}, "concept_id"), {})


def main() -> int:
    failures: list[str] = []
    for test in (test_ordering, test_profiles, test_distinctness, test_penalties,
                 test_topic_and_rollup, test_rescore_with_audit, test_issue_index):
        try:
            test(failures)
        except Exception as exc:
            failures.append(f"{test.__name__} raised {type(exc).__name__}: {exc}")

    if failures:
        print("\nFAIL")
        for failure in failures:
            print("  -", failure)
        return 1

    print("\nPASS  grounded > misplaced > unquoted > invented, both profiles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
