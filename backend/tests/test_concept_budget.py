"""Gate check for the concept budget and its enforcement.

The expectations below are anchored to chapters that really exist in this
database, with the counts they really produced under the old length-driven
formula. They are the regression the whole module was written to prevent:

    ext 175   61,151 chars, 6 topics   ->  37 concepts   (budget said 49-110)
    ext 174   35,437 chars, 5 topics   ->  31 concepts
    ext 173   42,867 chars, 6 topics   ->  33 concepts
    ext 170   30,590 chars, 4 topics   ->  25 concepts

(Those are DISTINCT names. The stored row counts are double, because 16
chapters hold every concept twice -- a separate bug, fixed by the upsert in
concept_service, not by the budget.)

If any of these starts landing above its ceiling again, the count is being
driven by document length once more and no LLM spend should be committed
against it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.concept_budget import (  # noqa: E402
    MAX_PER_TOPIC,
    MIN_PER_TOPIC,
    QUALITY_BAR,
    chapter_budget,
    distribute,
    enforce_quota,
)


def _check(failures: list[str], label: str, got, want) -> None:
    if got != want:
        failures.append(f"{label}: got {got!r}, want {want!r}")


def _between(failures: list[str], label: str, got: int, low: int, high: int) -> None:
    if not low <= got <= high:
        failures.append(f"{label}: got {got}, want {low}-{high}")


def test_real_chapters(failures: list[str]) -> None:
    """The four measured chapters, with no curriculum data and no periods."""
    # ext 175 - the worst case. Six topics, nothing but structure to go on.
    b = chapter_budget(topic_count=6, chapter_chars=61151)
    _check(failures, "175 source", b.source, "topics")
    _check(failures, "175 target", b.target, 18)
    _check(failures, "175 ceiling", b.ceiling, 24)
    _between(failures, "175 band low", b.low, 14, 15)
    _between(failures, "175 band high", b.high, 21, 22)

    # The point of the whole module: a chapter twice as long gets the same
    # budget, because length is not an input.
    short = chapter_budget(topic_count=6, chapter_chars=12000)
    _check(failures, "length independence", short.target, b.target)

    # ext 172 - three topics.
    b = chapter_budget(topic_count=3, chapter_chars=25323)
    _check(failures, "172 target", b.target, 9)
    _between(failures, "172 band", b.high, 10, 12)

    # ext 170 - four topics, produced 50 under the old formula.
    b = chapter_budget(topic_count=4, chapter_chars=30590)
    _check(failures, "170 target", b.target, 12)
    if b.ceiling > 16:
        failures.append(f"170 ceiling: got {b.ceiling}, want <= 16")


def test_curriculum_anchors(failures: list[str]) -> None:
    """Curriculum signals outrank periods, and periods outrank structure."""
    # NCERT Class 10 Science: 16 chapter-mapped learning outcomes, 13 periods.
    b = chapter_budget(topic_count=6, lo_count=16, periods=13, chapter_chars=40000)
    _check(failures, "LO source", b.source, "learning_outcomes")
    _check(failures, "LO target", b.target, 20)
    if b.warnings:
        failures.append(f"LO/period agreement should be quiet, got {b.warnings}")

    # Chapter 8617 - 26 outcomes. The raw anchor is 32 (1.25 * 26 = 32.5, and
    # round() is banker's, which is fine for a budget); the ceiling wins.
    b = chapter_budget(topic_count=7, lo_count=26)
    _check(failures, "8617 source", b.source, "learning_outcomes")
    _check(failures, "8617 target", b.target, 28)
    _check(failures, "8617 signals.anchor_raw", b.signals["anchor_raw"], 32)

    # Competencies only, no outcomes.
    b = chapter_budget(topic_count=6, competency_count=5)
    _check(failures, "competency source", b.source, "competencies")
    _check(failures, "competency target", b.target, 15)

    # Periods only.
    b = chapter_budget(topic_count=6, periods=11)
    _check(failures, "period source", b.source, "periods")
    _check(failures, "period target", b.target, 22)

    # Three outcomes is below the trust threshold; fall through to periods.
    b = chapter_budget(topic_count=6, lo_count=3, periods=10)
    _check(failures, "thin LO falls through", b.source, "periods")

    # A half-parsed outcome table disagreeing with the timetable is reported.
    b = chapter_budget(topic_count=6, lo_count=4, periods=20)
    if not b.warnings:
        failures.append("LO=4 vs periods=20 should warn about a partial table")


def test_bounds(failures: list[str]) -> None:
    """No chapter escapes the structural floor or the absolute ceiling."""
    # A normal chapter cannot exceed the absolute ceiling however strong the
    # curriculum signal is. Ten topics is the most the topic stage will produce.
    b = chapter_budget(topic_count=10, lo_count=200)
    if b.target > 30:
        failures.append(f"absolute ceiling breached: {b.target}")

    # Past 15 topics the per-topic floor alone exceeds the cap. The floor wins
    # -- a childless topic is a broken hierarchy, the cap is a judgement -- and
    # the conflict is reported rather than hidden.
    b = chapter_budget(topic_count=20, lo_count=200)
    _check(failures, "20-topic floor wins", b.target, 40)
    if not any("split below the topic level" in w for w in b.warnings):
        failures.append("20 topics breached the cap without saying so")

    # A one-topic chapter must not get a ceiling below its floor.
    b = chapter_budget(topic_count=1)
    if b.ceiling < b.floor:
        failures.append(f"ceiling {b.ceiling} below floor {b.floor}")
    if b.target < b.floor:
        failures.append(f"target {b.target} below floor {b.floor}")

    # Zero topics must not divide by zero.
    b = chapter_budget(topic_count=0)
    if b.target < 1:
        failures.append("zero topics produced an unusable budget")


def test_distribute(failures: list[str]) -> None:
    """Length decides the split across topics, and only the split."""
    spans = [(0, 18000), (18000, 30000), (30000, 40000),
             (40000, 49000), (49000, 56000), (56000, 61151)]
    quota = distribute(24, spans)
    _check(failures, "quota sums", sum(quota), 24)
    _check(failures, "quota length", len(quota), 6)
    if min(quota) < MIN_PER_TOPIC:
        failures.append(f"quota below the per-topic floor: {quota}")
    if max(quota) > MAX_PER_TOPIC:
        failures.append(f"quota above the per-topic ceiling: {quota}")
    if quota[0] < quota[-1]:
        failures.append(f"largest span did not get the largest share: {quota}")

    # Bounds beat the target when they conflict: six topics cannot share 8
    # concepts at a minimum of 2 each.
    tight = distribute(8, spans)
    _check(failures, "bounds win over target", sum(tight), 12)

    _check(failures, "no spans", distribute(10, []), [])


def _concept(name: str, grounded: bool) -> dict:
    return {"name": name, "evidence_verified": grounded}


def test_enforce_quota(failures: list[str]) -> None:
    """The trim removes weak evidence, never a grounded concept for being over."""
    md = (
        "# Adding and subtracting integers\n"
        + ("Adding integers with different signs means you subtract. " * 60)
        + "\n# Multiplying and dividing integers\n"
        + ("The sign rule for integer division follows from multiplication. " * 60)
    )
    results = [
        {
            "topic_id": 1,
            "topic_name": "Adding and subtracting integers",
            "concepts": [
                _concept("Adding integers with different signs", True),
                _concept("Subtracting a negative integer", True),
                _concept("Integer addition on a number line", True),
                _concept("Quantum chromodynamics", False),
                _concept("Unrelated invented idea", False),
                _concept("Another invented idea", False),
                _concept("A third invented idea", False),
            ],
        },
        {
            "topic_id": 2,
            "topic_name": "Multiplying and dividing integers",
            "concepts": [
                _concept("Sign rule for integer division", True),
                _concept("Multiplying two negative integers", True),
            ],
        },
    ]

    budget = chapter_budget(topic_count=2, chapter_chars=len(md))
    budget.quota = [3, 3]
    dropped = enforce_quota(results, budget, md_content=md)

    kept_one = [c["name"] for c in results[0]["concepts"]]
    if "Quantum chromodynamics" in kept_one:
        failures.append("an ungrounded, unrelated concept survived the trim")
    for name in ("Adding integers with different signs",
                 "Subtracting a negative integer",
                 "Integer addition on a number line"):
        if name not in kept_one:
            failures.append(f"grounded concept '{name}' was trimmed")

    if len(results[1]["concepts"]) != 2:
        failures.append("a topic already at its floor was trimmed further")

    if not dropped:
        failures.append("nothing was dropped from a clearly over-budget topic")
    for entry in dropped:
        # The count ceiling applies to everyone; the evidence floor must never
        # be what removes a concept the chapter demonstrably supports.
        if entry["evidence_verified"] and entry["reason"].startswith("not supported"):
            failures.append(f"the evidence floor removed a grounded concept: {entry['name']}")
        if entry.get("keep_score") is None:
            failures.append("a dropped concept carried no score to explain it")

    # The hard ceiling always applies, whatever the scores.
    many = [{
        "topic_id": 1,
        "topic_name": "Adding and subtracting integers",
        "concepts": [_concept(f"Adding integers with different signs {i}", True)
                     for i in range(12)],
    }]
    ceiling_budget = chapter_budget(topic_count=1, chapter_chars=len(md))
    ceiling_budget.quota = [MAX_PER_TOPIC]
    enforce_quota(many, ceiling_budget, md_content=md)
    if len(many[0]["concepts"]) > MAX_PER_TOPIC:
        failures.append(
            f"hard ceiling not applied: {len(many[0]['concepts'])} > {MAX_PER_TOPIC}"
        )

    # Well-grounded concepts are kept up to the allowance plus one -- the
    # prompt asks for "N or N-1 or N+1", so N+1 is honoured rather than cut
    # back to N. Beyond that the count ceiling applies to everyone; without it
    # there is no cap at all, which is the bug this module exists to fix.
    good = [{
        "topic_id": 1,
        "topic_name": "Adding and subtracting integers",
        "concepts": [_concept(f"Adding integers with different signs {i}", True)
                     for i in range(5)],
    }]
    good_budget = chapter_budget(topic_count=1, chapter_chars=len(md))
    good_budget.quota = [3]
    good_dropped = enforce_quota(good, good_budget, md_content=md)
    if len(good[0]["concepts"]) != 4:
        failures.append(
            f"an allowance of 3 should keep 4 well-grounded concepts, kept "
            f"{len(good[0]['concepts'])}"
        )
    for entry in good_dropped:
        if entry["reason"].startswith("not supported"):
            failures.append("a grounded concept was dropped as unsupported")

    # An unevidenced concept is dropped even when the topic is UNDER its
    # allowance: padding to a number is exactly what the allowance prevents.
    padded = [{
        "topic_id": 1,
        "topic_name": "Adding and subtracting integers",
        "concepts": [_concept("Adding integers with different signs", True),
                     _concept("Subtracting a negative integer", True),
                     _concept("Integer addition on a number line", True),
                     _concept("Entirely invented idea", False)],
    }]
    padded_budget = chapter_budget(topic_count=1, chapter_chars=len(md))
    padded_budget.quota = [5]
    enforce_quota(padded, padded_budget, md_content=md)
    if any(c["name"] == "Entirely invented idea" for c in padded[0]["concepts"]):
        failures.append("an unevidenced concept was kept to fill an unmet allowance")

    if QUALITY_BAR >= 2.0:
        failures.append(
            f"QUALITY_BAR is {QUALITY_BAR}; at or above the grounding weight it "
            f"would start trimming grounded concepts"
        )

    _check(failures, "empty input", enforce_quota([], budget, md_content=md), [])


def main() -> int:
    failures: list[str] = []
    for test in (test_real_chapters, test_curriculum_anchors, test_bounds,
                 test_distribute, test_enforce_quota):
        try:
            test(failures)
        except Exception as exc:  # a crash is a failure, not a stack trace
            failures.append(f"{test.__name__} raised {type(exc).__name__}: {exc}")

    if failures:
        print("\nFAIL")
        for failure in failures:
            print("  -", failure)
        return 1

    print("\nPASS  ext 175: 6 topics -> target 18 (band 14-22), was 37 distinct")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
