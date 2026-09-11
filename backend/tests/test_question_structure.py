"""Gate check for the deterministic question-structure parser.

The fixture mirrors the real layout of KVS "Ganit Manjary Part 1" Chapter 2,
including the noise that actually breaks naive parsers: inline option runs,
numerals inside worked solutions, and a trailing answer-key block whose
numbering repeats every question number in the chapter.

If this stops reporting 20/5/6/4/3 the parser has regressed, and no LLM
spend should be committed against its output.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.question_structure import analyze_question_structure  # noqa: E402


def _mcq_block(start: int, end: int) -> str:
    out = []
    for n in range(start, end + 1):
        out.append(f"{n}. The degree of the polynomial 5y^3 + y^2 + 2y - 1 is")
        out.append("(a) 1    (b) 2    (c) 3    (d) 0")
        out.append("")
        out.append("Solution: The highest power of the variable y is 3. Hence the degree is 3.")
        out.append("Answer: (c)")
        out.append("")
    return "\n".join(out)


def _ar_block(start: int, end: int) -> str:
    out = []
    for n in range(start, end + 1):
        out.append(f"{n}. Assertion (A): The polynomial 2x + 3 is a linear polynomial.")
        out.append("Reason (R): The highest power of the variable in a linear polynomial is 1.")
        out.append("Answer: (a)")
        out.append("")
    return "\n".join(out)


def _plain_block(start: int, end: int, stem: str) -> str:
    out = []
    for n in range(start, end + 1):
        out.append(f"{n}. {stem}")
        out.append("Solution: Substituting x = 0 we get y = 1, and at x = 2 we get y = 5.")
        out.append("")
    return "\n".join(out)


def _case_block(start: int, end: int) -> str:
    out = []
    for n in range(start, end + 1):
        out.append(f"{n}. Bela has Rs 100 for pocket money. She spends Rs 5 every day.")
        out.append("(i) What amount will be left on the 15th day? (1 mark)")
        out.append("(ii) After how many days will the entire amount be spent? (1 mark)")
        out.append("(iii) Does this situation represent linear growth or decay? (2 marks)")
        out.append("")
    return "\n".join(out)


FIXTURE = "\n".join(
    [
        "# CHAPTER 2",
        "# INTRODUCTION TO LINEAR POLYNOMIALS",
        "",
        "Section A: Multiple Choice Questions",
        "",
        _mcq_block(1, 16),
        "Assertion-Reasoning Questions :",
        "(a) Both (A) and (R) are true and R is the correct explanation of A.",
        "(b) Both A and R are true but R is not the correct explanation of A.",
        "",
        _ar_block(17, 20),
        "Section B: Very Short Answer Type Questions (2 marks each)",
        "",
        _plain_block(21, 25, "Find the degree and the constant term of 4z^3 + 5z^2 - 11."),
        "Section C: Short Answer Type Questions (3 marks each)",
        "",
        _plain_block(26, 31, "Find the values of the linear polynomial 5x - 3 for x = 0, -1 and 2."),
        "Section D: Long Answer Type Questions (5 marks each)",
        "",
        _plain_block(32, 35, "Draw the graph of y = 2x + 1 by taking at least three points."),
        "Section E: Case-Based Questions (4 marks each)",
        "",
        _case_block(36, 38),
        "ANSWERS",
        "",
        # The key repeats every number in the chapter. A parser that does not
        # stop at the answer block will roughly double every section count.
        "\n".join(f"{n}. (b)" for n in range(1, 39)),
    ]
)


def main() -> int:
    result = analyze_question_structure(FIXTURE)
    observed = result["blueprint"]["observed"]
    expected = result["blueprint"]["expected"]

    print("observed :", observed)
    print("expected :", expected)
    print("types    :", result["question_types"])
    print("totals   :", result["totals"])
    print("answerkey:", result["has_answer_key"])
    for warning in result["warnings"]:
        print("  warn:", warning)

    failures: list[str] = []
    for letter, count in expected.items():
        if observed.get(letter) != count:
            failures.append(f"section {letter}: got {observed.get(letter)}, want {count}")

    if result["totals"]["items"] != 38:
        failures.append(f"total items: got {result['totals']['items']}, want 38")
    if result["totals"]["marks"] != 80:
        failures.append(f"total marks: got {result['totals']['marks']}, want 80")
    if not result["has_answer_key"]:
        failures.append("answer key block was not detected")
    if result["question_types"].get("assertion_reason") != 4:
        failures.append(
            f"assertion_reason: got {result['question_types'].get('assertion_reason')}, want 4"
        )
    if result["question_types"].get("mcq") != 16:
        failures.append(f"mcq: got {result['question_types'].get('mcq')}, want 16")

    empty = analyze_question_structure("")
    if empty["totals"]["items"] != 0 or empty["blueprint"]["matches_cbse_pattern"]:
        failures.append("empty input did not return a clean empty result")

    if failures:
        print("\nFAIL")
        for failure in failures:
            print("  -", failure)
        return 1

    print("\nPASS  20/5/6/4/3 = 38 items, 80 marks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
