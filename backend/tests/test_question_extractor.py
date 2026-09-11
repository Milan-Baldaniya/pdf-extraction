"""Item-level extraction check against real KVS Chapter 2 content.

The text below is transcribed from "Ganit Manjary Part 1", Chapter 2
(Introduction to Linear Polynomials) — the same layout the pipeline will
meet in production: options printed several to a line, an inline
`Solution:` / `Answer: (c)` pair under each MCQ, an Assertion-Reason block
with its own option legend, and Section E case studies whose sub-parts
carry their own per-part marks.

What this asserts is the contract the downstream DeepSeek pass depends on:
every item found, every MCQ carrying a correct option, marks resolved per
section, and case-study parents recognised as compound.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.question_extractor import extract_questions  # noqa: E402

FIXTURE = """## Page 3

# Section A: Multiple Choice Questions

1. The degree of the polynomial 5y3 + y2 + 2y - 1 is
(a) 1 (b) 2 (c) 3 (d) 0

Solution: The highest power of the variable y is 3. Hence the degree is 3.
Answer: (c)

2. The coefficient of x2 in the polynomial x4 - 3x3 + 6x2 - 2x + 7 is
(a) -3 (b) 6 (c) -2 (d) 7

Solution: The term containing x2 is 6x2. Therefore the coefficient is 6.
Answer: (b)

3. Which of the following is a linear polynomial?
(a) x2 + 5x + 1 (b) 3z + 7 (c) 5y3 + y2 - 8 (d) x4 - 3x3

Solution: A linear polynomial has degree 1. Only 3z + 7 has degree 1.
Answer: (b)

4. The constant term in the polynomial 9x3 + 5x2 - 8x - 10 is
(a) 9 (b) 5 (c) -8 (d) -10

Solution: The term independent of the variable is -10.
Answer: (d)

5. The value of the linear polynomial 5x - 3 when x = 2 is
(a) 7 (b) 13 (c) -1 (d) 10

Solution: 5(2) - 3 = 10 - 3 = 7.
Answer: (a)

## Page 4

6. If the number of square tiles at stage n is given by 2n - 1, then the number of tiles at stage 15 is
(a) 29 (b) 30 (c) 31 (d) 28

Solution: 2 x 15 - 1 = 30 - 1 = 29.
Answer: (a)

7. The expression 200 + 50m represents the total cost for m matches. This is an example of
(a) quadratic polynomial (b) linear polynomial (c) cubic polynomial (d) constant polynomial

Solution: The degree of 200 + 50m is 1. Hence it is a linear polynomial.
Answer: (b)

8. In the equation y = 2x + 1, the slope is
(a) 1 (b) 2 (c) -2 (d) 0

Solution: In the form y = ax + b, a is the slope. Here a = 2.
Answer: (b)

# Assertion-Reasoning Questions

(a) Both (A) and (R) are true and R is the correct explanation of A.
(b) Both A and R are true but R is not the correct explanation of A.
(c) A is true but R is false.
(d) A is false but R is true.

17. Assertion (A): The polynomial 2x + 3 is a linear polynomial.
Reason (R): The highest power of the variable in a linear polynomial is 1.

Solution: Both A and R are true and R correctly explains A.
Answer: (a)

18. Assertion (A): The graph of y = -3x has a negative slope.
Reason (R): Linear decay is represented by a straight line with positive slope.

Solution: A is true (slope = -3 < 0). R is false because linear decay has negative slope.
Answer: (c)

## Page 5

# Section B: Very Short Answer Type Questions (2 marks each)

21. Find the degree and the constant term of the polynomial 4z3 + 5z2 - 11.

Solution: Degree = highest power of z = 3. Constant term = -11.

22. Write any one polynomial each of degree 1, 2 and 3.

Solution: Degree 1: 3x + 5; Degree 2: x2 - 4x + 7; Degree 3: 2y3 + y - 1.

23. Evaluate the linear polynomial 5x - 3 at x = -1.

Solution: 5(-1) - 3 = -5 - 3 = -8.

# Section C: Short Answer Type Questions (3 marks each)

26. Find the values of the linear polynomial 5x - 3 for x = 0, x = -1 and x = 2.

Solution: for x = 0, 5(0) - 3 = -3. For x = -1, 5(-1) - 3 = -8. For x = 2, 5(2) - 3 = 7.

27. Draw the graph of the linear polynomial p(x) = x - 2 and find its zero from the graph.

Solution: Plotting the points (0, -2) and (2, 0) and joining them gives a straight line.

# Section D: Long Answer Type Questions (5 marks each)

32. Write a polynomial of degree 3 in x whose coefficient of x2 is -7.

Solution: One possible polynomial: x3 - 7x2 + 2x + 5.

33. A positive number is 5 times another number. If 21 is added to both the numbers, then one of
the new numbers becomes twice the other new number. Find the numbers.

Solution: Let the smaller number be x. Then 5x + 21 = 2(x + 21), so 3x = 21 and x = 7.

# Section E: Case-Based Questions

36. Bela has Rs 100 for pocket money. She spends Rs 5 every day. The amount on the nth day is
given by 100 - 5n.
(i) What amount will be left on the 15th day? (1 mark)
(ii) After how many days will the entire amount be spent? (1 mark)
(iii) Does this situation represent linear growth or linear decay? Justify by finding the slope of
the corresponding line. (2 marks)

Solution: (i) 100 - 5 x 15 = 25. (ii) 5n = 100 so n = 20 days. (iii) Linear decay; slope -5.

37. The relation between temperature in Celsius and Fahrenheit is given by C = a F + b. Ice melts
at 0 C = 32 F and water boils at 100 C = 212 F.
(i) Find the value of a. (1 mark)
(ii) Find the value of b. (1 mark)
(iii) Write the complete linear relationship and find the Celsius temperature when Fahrenheit is
68 F. (2 marks)

Solution: (i) a = 5/9. (ii) b = -160/9. (iii) C = (5/9)(F - 32); at 68 F, C = 20.
"""


def main() -> int:
    result = extract_questions(
        FIXTURE,
        attribution="KVS RO Agra, Ganit Manjary Pt.1, 2026-27",
        licence="KVS website reuse policy",
    )
    items = result["items"]
    by_section: dict[str, int] = {}
    by_form: dict[str, int] = {}
    for it in items:
        by_section[it["exam_section"]] = by_section.get(it["exam_section"], 0) + 1
        by_form[it["item_form"]] = by_form.get(it["item_form"], 0) + 1

    print("items parsed :", len(items))
    print("by section   :", dict(sorted(by_section.items())))
    print("by form      :", dict(sorted(by_form.items())))
    for w in result["warnings"]:
        print("  warn:", w)

    mcqs = [i for i in items if i["item_form"] == "mcq"]
    ars = [i for i in items if i["item_form"] == "assertion_reason"]
    cases = [i for i in items if i["item_form"] == "case_study_parent"]

    print()
    print("MCQ with 4 options   :", sum(1 for i in mcqs if len(i["options"]) == 4), "/", len(mcqs))
    print("MCQ with correct opt :", sum(1 for i in mcqs if i["correct_option"]), "/", len(mcqs))
    print("MCQ with solution    :", sum(1 for i in mcqs if i["answer_text"]), "/", len(mcqs))
    print("A-R with both fields :", sum(1 for i in ars if i["assertion"] and i["reason"]), "/", len(ars))
    print("case parents         :", len(cases), "sub-parts:", [len(i["sub_part_labels"]) for i in cases])
    print("distinct hashes      :", len({i["verbatim_sha256"] for i in items}), "/", len(items))
    print("pages resolved       :", sum(1 for i in items if i["source_page"]), "/", len(items))

    if mcqs:
        s = mcqs[0]
        print()
        print("sample MCQ:")
        print("   stem   :", s["stem"][:70])
        print("   options:", [(o["label"], o["text"][:16], o["is_correct"]) for o in s["options"]])
        print("   correct:", s["correct_option"], "| marks:", s["marks"], "| page:", s["source_page"])

    failures: list[str] = []
    # 8 MCQ + 2 assertion-reason (both Section A) + 3 VSA + 2 SA + 2 LA + 2 case = 19
    if len(items) != 19:
        failures.append(f"expected 19 items in this excerpt, got {len(items)}")
    if len(mcqs) != 8:
        failures.append(f"expected 8 MCQs, got {len(mcqs)}")
    if any(len(i["options"]) != 4 for i in mcqs):
        failures.append("some MCQ did not parse exactly 4 options")
    if any(not i["correct_option"] for i in mcqs):
        failures.append("some MCQ has no correct option")
    if len(ars) != 2:
        failures.append(f"expected 2 assertion-reason items, got {len(ars)}")
    if any(not (i["assertion"] and i["reason"]) for i in ars):
        failures.append("assertion/reason not split into separate fields")
    if len(cases) != 2:
        failures.append(f"expected 2 case-study parents, got {len(cases)}")
    if any(len(i["sub_part_labels"]) != 3 for i in cases):
        failures.append("case-study sub-parts not detected")
    if any(i["marks"] != 4 for i in cases):
        failures.append(f"case marks should total 4, got {[i['marks'] for i in cases]}")
    sec_b = [i for i in items if i["exam_section"] == "B"]
    if sec_b and any(i["marks"] != 2 for i in sec_b):
        failures.append("Section B marks not 2")
    sec_d = [i for i in items if i["exam_section"] == "D"]
    if sec_d and any(i["marks"] != 5 for i in sec_d):
        failures.append("Section D marks not 5")
    if len({i["verbatim_sha256"] for i in items}) != len(items):
        failures.append("duplicate content hashes across distinct items")
    if any(i["attribution"] is None for i in items):
        failures.append("attribution not stamped on every item")

    if failures:
        print("\nFAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("\nPASS  all items structured with answers, marks and relationships")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
