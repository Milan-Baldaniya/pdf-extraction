"""Form classification against the stems that actually broke it.

Every case here is a real question from the Class 10 Science bank, or a
minimal reduction of one. The hard part is not recognising a "Prove that" --
it is telling apart two things that look identical in the stored text:

    84850  "Give the characteristic tests for the following gases :
             (a) CO2 (b) SO2 (c) O2 (d) H2"          SUB-PARTS -- answer all
    84816  "The following reaction is an example of ...
             (i) displacement (ii) combustion ..."    OPTIONS -- choose one

Getting that wrong in the `mcq` direction is the expensive one: an editor save
on a question wrongly typed `mcq` treats its sub-parts as options and strips
the rest, which is the same class of bug as the `true_false` misclassification
found in the Laravel bank. So `question_type_master` and the stored option rows
are treated as facts, and the stem is only ever evidence.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.question_type_backfill import (  # noqa: E402
    MARKS_BY_FORM,
    classify_form,
)

# (expected form, question_type_master says multiple, stored option count, stem)
CASES: list[tuple[str, bool, int, str]] = [
    # --- sub-parts, NOT options -------------------------------------------
    ("long", False, 0,
     "Give the characteristic tests for the following gases :"
     "(a) CO2(b) SO2(c) O2(d) H2"),
    ("long", False, 0,
     "Explain the following(a) Reactivity of Al decreases if it is dipped in "
     "cone. HNO3(b) Carbon cannot reduce the oxides of Na or Mg.(c) NaCl is "
     "not a conductor in solid state but conducts when molten"),
    ("long", False, 0,
     "(a) Name the enzyme present in saliva. Why is it important ?"
     "(b) What is emulsification ?(c) Name the substance that is oxidised "
     "in the body during respiration"),
    ("short", False, 0,
     "Write the balanced equation for (a) burning of magnesium "
     "(b) heating of limestone."),

    # --- options embedded in the stem, no option rows stored --------------
    ("mcq", False, 0,
     "The following reaction is an example of a 4NH3(g) + SO2(g) -> 4NO(g) + "
     "6H2O(g) (i) displacement reaction(ii) combustion reaction"
     "(iii) redox reaction(iv) neutralisation"),
    ("mcq", False, 0,
     "Which one of the following is not one of the direct conclusions drawn "
     "from Mendel's experiment? (a) foo (b) bar (c) baz (d) qux"),
    ("mcq", False, 0,
     "Silver articles become black on prolonged exposure to air. This is due "
     "to the formation of(a) Ag2S(b) AgNO3(c) Ag2O(d) AgCl"),
    ("mcq", False, 0,
     "The colour of the gas evolved on heating lead nitrate is "
     "(a) brown (b) green (c) colourless (d) yellow"),

    # --- a stored MCQ stays an MCQ whatever its verb says -----------------
    ("mcq", True, 4, "Calculate the power of a lens of focal length 25 cm."),
    ("mcq", True, 2, "Rusting of iron needs both air and water. True or False?"),
    ("mcq", True, 4,
     "10 g of substance A reacts completely with 5 g of substance B. What is "
     "the total mass of the products formed?"),

    # --- the structural forms ---------------------------------------------
    ("assertion_reason", False, 0,
     "Assertion (A): A student observes bubbles forming. "
     "Reason (R): Carbon dioxide dissolves under pressure."),
    ("match_following", False, 0,
     "Match the following columns : Column-I (a) Quick lime Column-II (i) CaO"),
    ("fill_blank", False, 0, "The chemical formula of quick lime is ________."),
    ("true_false", False, 0,
     "State whether the following statement is true or false : "
     "Rusting needs both air and water."),
    ("proof", False, 0,
     "Prove that the sum of the angles of a triangle is 180 degrees."),
    ("construction", False, 0,
     "Draw a ray diagram to show the formation of image by a concave mirror."),
    ("numerical", False, 0,
     "Calculate the resistance of a wire of length 2 m and area 0.5 sq mm."),
    ("case_study_parent", False, 0,
     "Read the following passage and answer the questions that follow. "
     "Rusting of iron is a slow process."),

    # --- length buckets ---------------------------------------------------
    ("very_short", False, 0, "Name the component of food not digested in stomach."),
    ("very_short", False, 0,
     "Name the gas that can be used for the storage of fresh sample of chips "
     "for a long time."),

    # OCR debris must not inflate a nine-word question into a long answer:
    # stem 87042 is followed by a dozen stray soft-hyphen glyphs.
    ("very_short", False, 0,
     "Why is the tungsten used almost exclusively for filament of electric "
     "lamps ?­ ­ ­ ­ ­ ­ ­ ­ ­ "
     "­ ­ ­ ­ ­ ­"),
]


def test_classify_form() -> None:
    failures = []
    for want, is_mcq, options, stem in CASES:
        got = classify_form(stem, is_mcq=is_mcq, has_options=bool(options))
        if got != want:
            failures.append(f"want={want!r} got={got!r}: {stem[:80]!r}")
    assert not failures, "\n".join(failures)


def test_no_subpart_list_is_typed_mcq() -> None:
    """The expensive direction: a sub-part list must never become an MCQ."""
    for want, is_mcq, options, stem in CASES:
        if want in ("short", "long") and not is_mcq and not options:
            assert classify_form(stem, is_mcq=False, has_options=False) != "mcq", stem[:80]


def test_every_form_has_marks() -> None:
    forms = {c[0] for c in CASES}
    missing = forms - set(MARKS_BY_FORM)
    assert not missing, f"no marks defined for {missing}"


if __name__ == "__main__":
    test_classify_form()
    test_no_subpart_list_is_typed_mcq()
    test_every_form_has_marks()
    print(f"ok - {len(CASES)} cases")