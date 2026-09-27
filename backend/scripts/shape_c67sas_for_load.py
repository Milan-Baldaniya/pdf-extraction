"""Curate CBSE SAS Class 6/7 Maths items onto the NEP Ganita Prakash chapters.

    python -m scripts.shape_c67sas_for_load --grade 6
    python -m scripts.shape_c67sas_for_load --grade 7 --verbose

Reads `scripts/c67sas_items/drafts/c{6,7}_maths_sas.json` (written by
`scripts.parse_sas_items`) and writes one `chNN.json` per NEP chapter under
`scripts/c67sas_items/load/c{6,7}/`, in the shape `load_nodia_items` expects.

WHY A REMAP. CBSE tagged these items to the SUPERSEDED Class 6/7 Maths books
(Knowing Our Numbers, Whole Numbers, ... / Integers, Exponents and Power, ...).
Our chapter rows follow Ganita Prakash. The tag is per chapter, so the decision
is one editorial call per old chapter rather than per item, and CHAPTER_MAP
below is that decision, with its reason recorded next to it.

WHY SO FEW ITEMS SURVIVE. The remap is the easy part. Two things cost far more:

  figures   The SAS format prints a shared stimulus -- a bar graph, a pictograph,
            a labelled diagram, a football field -- above a cluster of two to
            five items. Where the values a learner needs live in that image, the
            text layer carries nothing, and an item loaded without it cannot be
            answered. `figure_required` exists, but resolving it needs an
            `asset_manifest` entry with a CDN-reachable `stored_url`, and
            `check_figure_resolution` is explicit that a figure pointing at this
            machine is as unusable as a missing one. Those items are skipped.
  notation  Fractions flatten and print the denominator first, and superscripts
            vanish, so "0.8 x 4 10-" was once "0.8 x 10^-4". Where a stem's or
            an option's maths cannot be read as printed, the item is skipped.

KEEP is therefore an allow-list, not a filter: every code in it was read against
the PDF. FIXES records the per-item repairs, each one a thing the text layer got
wrong rather than an editorial change to what CBSE asked.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

ROOT = Path(__file__).resolve().parent / "c67sas_items"
DRAFTS = ROOT / "drafts"
LOAD = ROOT / "load"
FIGURES = Path(__file__).resolve().parents[1] / "output" / "sas_figures"

# ITEMS THAT NEED A SECOND FIGURE. `extract_sas_figures` gives each item the
# figure of its own cluster, which is right for all but two: the third and fifth
# Data Handling items ask for values off JIYA'S BAR GRAPH, printed a page earlier
# with the first cluster, while their own cluster's picture is the pictograph of
# dots they must read it against. Both are needed, so both are attached.
EXTRA_FIGURES = {
    "SAS21M06D0903": ["SAS21M06D0901"],
    "SAS21M06D0905": ["SAS21M06D0901"],
}

STANDARD = {6: 39, 7: 40}
SOURCE_URL = "https://cbseacademic.nic.in/cbe/documents/"
PUBLISHER = "cbse"

# --------------------------------------------------------------------------
# THE REMAP. old SAS chapter -> a destination, or None to decline. A destination
# is either a Ganita Prakash sort_order in the ITEM'S OWN grade, or a
# (grade, sort_order) pair when NEP moved the topic to another grade.
#
# The rule applied throughout: map only where the NEP chapter TEACHES what the
# item TESTS. Where Ganita Prakash reframes the material instead of renaming it,
# the pair is declined -- a question filed under a chapter that frames it
# differently loads clean and is invisible afterwards, which is worse than the
# gap it papers over.
#
# CROSS-GRADE MOVES. NEP did not only rename chapters, it re-sequenced topics
# between Class 6 and Class 7, and four of the old Class 6 chapters teach what a
# Class 7 Ganita Prakash chapter now teaches: multiplication and division of
# fractions, letter-number algebra, the commutative property, and decimals.
# Moving those items up a grade is the same kind of claim as renaming a chapter
# -- the NEP chapter still teaches exactly what the item tests -- so they are
# mapped, marked `cross_grade` in the shaped file and recorded in the
# extraction's `extraction_metadata` so the decision stays visible.
#
# A CHAPTER-LEVEL DEFAULT IS NOT ALWAYS ENOUGH. CBSE's own concept tag is coarse:
# all ten Class 6 "Fractions" items are tagged "Multiplication and Division of
# Fraction" and four of them are really about what an equal share IS, which is
# Class 6 ch7 and not Class 7 ch8. So the value here is the DEFAULT reading and
# KEEP carries the per-item destination, which governs.
# --------------------------------------------------------------------------
CHAPTER_MAP: dict[int, dict[str, tuple[int | None, str]]] = {
    6: {
        "Playing with Numbers": (5, "GP6 ch5 Prime Time IS factors, multiples, "
            "primes, co-primes, prime factorisation and divisibility. All ten "
            "items are factor/multiple/common-multiple word problems; the two "
            "HCF-flavoured ones are the Idli-Vada and Jump Jackpot framing."),
        "Integers": (10, "GP6 ch10 The Other Side of Zero IS integers, and its "
            "sections are built on exactly this item set's framing: Bela's "
            "Building of Fun and The Mineshaft for above/below a datum, "
            "Inverses, and unmarked number lines."),
        "Symmetry": (9, "GP6 ch9 Symmetry covers lines of symmetry, reflection "
            "and rotational symmetry. Same topic -- but nine of the ten items "
            "need their figure."),
        "Data Handling": (4, "GP6 ch4 Data Handling and Presentation IS "
            "organising data, tally marks, pictographs and bar graphs. The "
            "topic matches exactly and NOT ONE item survives: every one reads "
            "its answer off Jiya's bar graph or Shobhit's pictograph."),
        "Mensuration": (6, "GP6 ch6 Perimeter and Area IS perimeter and area of "
            "rectangles and squares. Same topic, and all ten items take their "
            "dimensions from the football-field figure, so none can load."),
        "Whole Numbers": (None, "DECLINED. GP6 ch3 Number Play is supercells, "
            "palindromes, Kaprekar, Collatz, parity and estimation. These items "
            "are shop-bill arithmetic and the associative property -- the old "
            "chapter's content, not the new chapter's."),
        "Knowing Our Numbers": (None, "DECLINED. NEP moved large numbers up to "
            "Class 7 ch1 Large Numbers Around Us, so the move itself would be "
            "sound -- but every large-number item here reads its figures out of "
            "a multi-column fare or fees table whose headers the text layer "
            "interleaves with its values, and the only item that survives the "
            "reading is a prime-factorisation question that belongs in Class 6 "
            "ch5. See KEEP."),
        "Fractions": (7, "SPLIT. GP6 ch7 Fractions is equal shares, fractional "
            "units, equivalence and addition; NEP moved multiplication and "
            "division to Class 7 ch8 Working with Fractions. CBSE tags all ten "
            "items 'Multiplication and Division of Fraction' and several are "
            "really about what an equal share is, so the default is ch7 in the "
            "item's own grade and KEEP sends the one true multiplication item "
            "across to Class 7 ch8."),
        "Decimals": ((7, 3), "CROSS-GRADE. GP6 has no decimals chapter at all. "
            "Class 7 ch3 A Peek Beyond the Point has Decimal Place Value, Units "
            "of Measurement, Locating and Comparing Decimals and Addition and "
            "Subtraction of Decimals -- which is this chapter, section for "
            "section."),
        "Algebra": ((7, 4), "CROSS-GRADE. GP6 has no algebra chapter; NEP "
            "introduces letter-numbers in Class 7 ch4 Expressions Using "
            "Letter-Numbers, whose sections The Notion of Letter-Numbers, "
            "Omission of the Multiplication Symbol and Pick Patterns and Reveal "
            "Relationships are exactly what these items test. The one item on "
            "the commutative property goes to ch2 Arithmetic Expressions "
            "instead, whose Swapping and Grouping Terms owns it."),
        "Ratio and Proportion": (None, "DECLINED. No Ganita Prakash chapter in "
            "EITHER grade covers ratio, proportion or the unitary method. A "
            "true syllabus gap, not a naming problem."),
        "Basic Geometrical Ideas": (None, "DECLINED. GP6 ch2 Lines and Angles is "
            "points, lines, rays, angles and the protractor. It carries no open "
            "and closed curves, no polygons and no shape classification, which "
            "is what all ten items test."),
        "Understanding Elementary Shapes": (None, "DECLINED, same reason: "
            "classification of triangles, quadrilaterals and 3D shapes are "
            "absent from GP6 ch2."),
        "Practical Geometry": (None, "DECLINED. GP6 ch8 Playing with "
            "Constructions is ruler-and-compass work -- copying a picture, "
            "squares and rectangles, rotated copies, points equidistant from "
            "two points. These items ask for PROPERTIES of chords and angle "
            "bisectors, and the only two readable without a figure test decimal "
            "division and circle arithmetic instead of construction."),
    },
    7: {
        "Integers": (10, "GP7 ch10 Operations with Integers, whose first "
            "section is A Quick Recap of Integers. The three loadable items "
            "compare and subtract negative temperatures."),
        "Fractions and Decimals": (8, "GP7 ch8 Working with Fractions has "
            "Multiplication of Fractions, Division of Fractions and Some "
            "Problems Involving Fractions as its own section names. Every item "
            "is tagged Multiplication and Division of Fraction."),
        "Simple Equations": (15, "GP7 ch15 Finding the Unknown is Find the "
            "Unknowns and Solving Equations Systematically. Exact match."),
        "Algebraic Expressions": (4, "GP7 ch4 Expressions Using Letter-Numbers "
            "covers letter-numbers, terms, coefficients, like and unlike terms "
            "and simplification -- item for item what this chapter tests."),
        "The Triangle and its Properties": (7, "GP7 ch7 A Tale of Three "
            "Intersecting Lines covers Constructing a Triangle When its Sides "
            "are Given -- which is where the triangle inequality lives -- plus "
            "altitudes, medians and Types of Triangles."),
        "Congruence of Triangles": (9, "GP7 ch9 Geometric Twins is the "
            "congruence chapter: its sections are Congruence of Triangles, The "
            "SAS Condition, The ASA Condition and The RHS Condition. Note it is "
            "NOT the symmetry chapter its name suggests."),
        "Data Handling": (13, "GP7 ch13 Connecting the Dots has Representative "
            "Values, The Arithmetic Mean and Outliers and the Median. All ten "
            "items are tagged Measures of Central Tendency."),
        "Lines and Angles": (5, "GP7 ch5 Parallel and Intersecting Lines has "
            "Transversals, Corresponding Angles and Alternate Angles. The "
            "cleanest pair in either grade -- and all ten items read their "
            "angles off a diagram, so none can load."),
        "Practical Geometry": (None, "DECLINED. The old chapter splits: "
            "construction of triangles belongs to GP7 ch7 and construction of "
            "angles to ch14 Constructions and Tilings. Defensible, but a "
            "construction item is a drawing instruction and not one of the ten "
            "is readable without its figure, so there is nothing to place."),
        "Comparing Quantities": (None, "DECLINED. Ganita Prakash 7 has no "
            "percentage, ratio or simple-interest chapter. Nine readable items "
            "with nowhere to go -- a real gap in our chapter rows, worth "
            "raising separately."),
        "Rational Numbers": (None, "DECLINED. No rational-numbers chapter in "
            "GP7; NEP moved the topic to Class 8."),
        "Exponents and Power": (None, "DECLINED. No exponents chapter in GP7 "
            "either. GP7 ch1 touches powers of ten for large numbers, but these "
            "items are scientific notation with negative indices and seven of "
            "ten have lost the superscript that carried the meaning."),
        "Area and Perimeter": (None, "DECLINED. GP7 has no area chapter, and "
            "these items include the area and circumference of a circle and the "
            "area of a parallelogram, none of which GP6 ch6 teaches. All ten "
            "need their figure in any case."),
        "Symmetry": (None, "DECLINED. GP7 has no symmetry chapter -- ch9 "
            "Geometric Twins is congruence, confirmed from its own topic rows. "
            "All ten items need a figure regardless."),
        "Visualising Solid Shapes": (None, "DECLINED. No solid-shapes chapter "
            "in GP7."),
        "Visualising Solid Objects": (None, "DECLINED -- CBSE's own spelling "
            "variant of Visualising Solid Shapes, for one item."),
    },
}

# --------------------------------------------------------------------------
# THE ALLOW-LIST: code -> destination, a chapter in the item's own grade or a
# (grade, chapter) pair. Every code here was read against the PDF, and every key
# was worked through by hand -- that is how three broken CBSE items were caught
# (see BROKEN below). A code absent from a mapped chapter was read and rejected;
# the --verbose run prints why.
# --------------------------------------------------------------------------
KEEP: dict[int, dict[str, int | tuple[int, int]]] = {
    6: {
        # ch5 Prime Time
        "SAS21M06N0301": 5, "SAS21M06N0302": 5, "SAS21M06N0303": 5,
        "SAS21M06N0304": 5, "SAS21M06N0305": 5, "SAS21M06N0306": 5,
        "SAS21M06N0307": 5, "SAS21M06N0308": 5, "SAS21M06N0309": 5,
        "SAS21M06N0310": 5,
        # ch5 Prime Time, from "Knowing Our Numbers": 105 students into equal
        # sections of 20 to 40. CBSE's own Full Credit says "Finds prime factors
        # of 105", so the item is prime factorisation wherever it was filed.
        "SAS21M06Q0109": 5,
        # ch7 Fractions -- what an equal share IS, not multiplying fractions.
        # Three friends and "three equal halves"; dividing a pizza into sixths.
        "SAS21M06N0707": 7, "SAS21M06N0710": 7,
        # ch4 Data Handling and Presentation. EVERY ONE OF THESE NEEDS ITS
        # FIGURE, and has one: the bar graph, the dot pictograph and the tally
        # table were rendered by `extract_sas_figures` and each crop was looked
        # at. D0904's four OPTIONS are pictures, so it stays out, and D0907 is
        # broken (see BROKEN).
        "SAS21M06D0901": 4, "SAS21M06D0902": 4, "SAS21M06D0903": 4,
        "SAS21M06D0905": 4, "SAS21M06D0906": 4, "SAS21M06D0908": 4,
        "SAS21M06D0909": 4, "SAS21M06D0910": 4,
        # ch9 Symmetry
        "SAS21M06S1310": 9,
        # ch10 The Other Side of Zero
        "SAS21M06N0601": 10, "SAS21M06N0602": 10, "SAS21M06N0603": 10,
        "SAS21M06N0604": 10, "SAS21M06N0605": 10, "SAS21M06N0606": 10,
        # ---- CROSS-GRADE: Class 6 items on Class 7 chapters ----
        # ch2 Arithmetic Expressions: the commutative property of addition,
        # which is that chapter's Swapping and Grouping Terms.
        "SAS21M06C1107": (7, 2),
        # ch3 A Peek Beyond the Point: adding, subtracting and comparing
        # decimals, and 160.3 cm as 160 cm + 3 mm, which is its Units of
        # Measurement section exactly.
        "SAS21M06N0806": (7, 3), "SAS21M06N0807": (7, 3),
        "SAS21M06N0808": (7, 3), "SAS21M06N0809": (7, 3),
        "SAS21M06N0810": (7, 3),
        # ch4 Expressions Using Letter-Numbers: a cost written as 20a, an
        # expression for 15 storybooks, a letter for an unknown handful of
        # seeds, and 4n patches for n repeats of a four-patch block.
        "SAS21M06C1101": (7, 4), "SAS21M06C1103": (7, 4),
        "SAS21M06C1105": (7, 4), "SAS21M06C1106": (7, 4),
        "SAS21M06C1109": (7, 4),
        # ch8 Working with Fractions: one quarter of an hour in minutes, which
        # is a fraction of a quantity and so ch8 rather than ch7.
        "SAS21M06N0704": (7, 8),
    },
    7: {
        # ch4 Expressions Using Letter-Numbers
        "SAS21M07C1202": 4, "SAS21M07C1206": 4, "SAS21M07C1207": 4,
        "SAS21M07C1208": 4, "SAS21M07C1209": 4, "SAS21M07C1210": 4,
        # ch5 Parallel and Intersecting Lines. All ten read their angles off a
        # diagram and all ten now have it: the swing frame, the see-saw and the
        # three lines through P, each crop checked against the item's key.
        "SAS21M07S0501": 5, "SAS21M07S0502": 5, "SAS21M07S0503": 5,
        "SAS21M07S0504": 5, "SAS21M07S0505": 5, "SAS21M07S0506": 5,
        "SAS21M07S0507": 5, "SAS21M07S0508": 5, "SAS21M07S0509": 5,
        "SAS21M07S0510": 5,
        # ch7 A Tale of Three Intersecting Lines
        "SAS21M07S0601": 7, "SAS21M07S0602": 7, "SAS21M07S0603": 7,
        "SAS21M07S0604": 7,
        # ch8 Working with Fractions
        "SAS21M07Q0203": 8, "SAS21M07Q0204": 8, "SAS21M07Q0205": 8,
        "SAS21M07Q0208": 8, "SAS21M07Q0209": 8,
        # ch9 Geometric Twins
        "SAS21M07S0702": 9, "SAS21M07S0705": 9,
        # ch10 Operations with Integers
        "SAS21M07Q0108": 10, "SAS21M07Q0109": 10, "SAS21M07Q0110": 10,
        # ch13 Connecting the Dots
        "SAS21M07D0306": 13, "SAS21M07D0307": 13, "SAS21M07D0308": 13,
        # ch15 Finding the Unknown
        "SAS21M07C0401": 15, "SAS21M07C0402": 15, "SAS21M07C0403": 15,
        "SAS21M07C0404": 15, "SAS21M07C0405": 15, "SAS21M07C0406": 15,
        "SAS21M07C0407": 15,
    },
}

# ITEMS CBSE PRINTED WRONG. Each was checked against the page image, not just
# the text layer, and each is internally contradictory ON THE PAGE. They are
# recorded rather than silently dropped because a later reader will otherwise
# rediscover them and assume the parser is at fault.
BROKEN = {
    "SAS21M06C1102": "the stem asks for the earnings on TEN comic books and "
        "every option, and the key 20a + 40, describes twenty",
    "SAS21M06C1104": "the stimulus says a colouring book costs Rs 10 more than "
        "a storybook, which costs Rs 5 more than a comic book, so a Rs 50 "
        "colouring book means a Rs 35 comic book -- not one of the four options. "
        "The key, 40, is only right if the colouring book is Rs 10 more than the "
        "COMIC book, which is not what the page says",
    "SAS21M06D0907": "the options are shoe sizes 4, 7, 8 and 9 and the key is "
        "'B. Size 6'. The rendered tally table settles it: size 6 sold 15 pairs "
        "and is the mode, so CBSE's ANSWER is right and its OPTION LIST is "
        "missing the answer",
}

# Per-item repairs. `drop_context` throws away an inherited stimulus that the
# item does not need: the parser carries a scenario forward across a cluster,
# which is right for the items that share it and leaves a stale paragraph above
# the ones that do not. `stem_from_context` is for the one item whose code block
# printed BELOW its question, so the question text arrived as the context.
FIXES: dict[str, dict] = {
    "SAS21M06N0303": {"strip_prefix": "How did ",
                      "note": "CBSE's own stem opens with a dangling 'How did'"},
    "SAS21M06N0305": {"drop_context": True},
    "SAS21M06N0306": {"drop_context": True},
    "SAS21M06N0307": {"drop_context": True},
    "SAS21M06N0308": {"drop_context": True},
    "SAS21M06N0309": {"drop_context": True},
    "SAS21M06N0310": {"drop_context": True},
    "SAS21M06N0606": {"drop_context": True},
    "SAS21M06S1310": {"drop_context": True},
    # 105 students into equal sections -- nothing to do with the school
    # transport fees table it was printed under.
    "SAS21M06Q0109": {"drop_context": True},
    # Self-contained decimal questions that inherited the car air-conditioner
    # scenario belonging to the items above them.
    "SAS21M06N0809": {"drop_context": True},
    "SAS21M06N0810": {"drop_context": True},
    # Sarah's bookstall is the Algebra chapter's opening scenario and is carried
    # forward correctly onto C1101 and C1103, which are about her books. It is
    # stale on everything after them.
    "SAS21M06C1105": {"drop_context": True},
    "SAS21M06C1107": {"drop_context": True},
    # C1106 asks what happens when Garima adds "some more" seeds, and the
    # feeder, the handful and the seven eaten birds are all in C1105's stem
    # because CBSE printed the scenario there. Without them the item cannot be
    # read at all, so C1105's own printed sentence is restored as its context --
    # the same repair as D0307 and D0308.
    "SAS21M06C1106": {"context": "Garima puts a handful of seeds into an empty "
                                 "bird feeder. A bird comes and eats 7 of them."},
    "SAS21M07Q0203": {"drop_context": True},
    "SAS21M07D0306": {"drop_context": True},
    # Items 7 and 8 ask about "Mary's scores" and CBSE printed that list inside
    # item 6's stem rather than in a stimulus block of its own, so the parser
    # had no block to carry forward. Restoring it is the same thing the shared
    # stimulus does everywhere else in this load, and without it neither item
    # can be answered at all.
    "SAS21M07D0307": {"context": "Mary played 10 HC matches. She scored 45, 36, "
                                 "50, 27, 36, 52, 50, 43, 50 and 47 points in them."},

    # The only item in either book whose option labels printed without the
    # punctuation the option regex needs ("A Increases by 1.13", not "A."), so
    # all four options stayed inside the stem and it loaded as a written answer
    # while its key named an option. The text is unchanged; only the structure
    # the page already had is recovered, so it is still verbatim.
    "SAS21M07D0308": {"split_options": True,
                      "context": "Mary played 10 HC matches. She scored 45, 36, "
                                 "50, 27, 36, 52, 50, 43, 50 and 47 points in them."},
    "SAS21M07C0405": {"drop_context": True},
    "SAS21M07C0406": {"drop_context": True},
    "SAS21M07C0407": {"stem_from_context": True},
    "SAS21M07S0604": {"drop_context": True},
    "SAS21M07S0705": {"drop_context": True},
    "SAS21M07C1202": {"drop_context": True},
}

# Four option labels run into the tail of a stem, with no punctuation after the
# letter for `OPTION` in the parser to see.
UNPUNCTUATED_OPTIONS = re.compile(
    r"\bA\s+(?P<a>.+?)\s+B\s+(?P<b>.+?)\s+C\s+(?P<c>.+?)\s+D\s+(?P<d>.+?)\s*$")

# A LONE ONE- OR TWO-DIGIT TOKEN between a full stop and a capital is the
# printed item number, which sits in the left margin and lands mid-stem when the
# block merges. Anchoring on the sentence boundary is what keeps it from eating
# a real number: "8 - 8 = 0 Which of the following" has no full stop before it.
ITEM_NUMBER = re.compile(r"(?<=[.?!”])\s+\d{1,2}(?=\s+[A-Z“]|\s*$)")

# CBSE writes both its bullet lists and its list of acceptable responses with
# U+0178 as the bullet glyph. In a stem it separates the clauses of a scenario,
# so it reads as a semicolon; in the Full Credit field it separates alternative
# acceptable answers, so it reads as a pipe.
BULLET = re.compile(r"\s*Ÿ\s*")


def fold(s: str) -> str:
    """Make a string safe for `lms_question_master.answer`, which is utf8mb3.

    A four-byte character -- anything at U+10000 or above, which for maths means
    the Mathematical Alphanumeric Symbols -- makes MariaDB reject the whole row
    with `Incorrect string value: '\\xF0\\x9D...'`, and the writer's retry loop
    cannot recover from it. NFKC turns the mathematical italics into plain
    ASCII letters; anything still outside the BMP afterwards is dropped rather
    than allowed to cost a chapter.
    """
    if not s:
        return s
    if any(ord(c) > 0xFFFF for c in s):
        s = unicodedata.normalize("NFKC", s)
    return "".join(c for c in s if ord(c) <= 0xFFFF)


def clean_stem(s: str, chapter_label: str = "") -> str:
    s = ITEM_NUMBER.sub("", s)
    # A bullet list flattened into one line: the first bullet introduces the
    # list, so it reads as a colon, and the rest separate its members.
    seen = [0]

    def _bullet(_m: re.Match) -> str:
        seen[0] += 1
        return ": " if seen[0] == 1 else "; "

    s = BULLET.sub(_bullet, s)
    s = " ".join(s.split()).strip()
    # The chapter divider page prints the old book's chapter name, and that
    # block lands at the head of the first stimulus of the chapter.
    if chapter_label and s.startswith(chapter_label):
        s = s[len(chapter_label):].lstrip(" :-–")
    return re.sub(r"\s*[;:]\s*(?=[.;,])", "", s).strip(" ;:")


def clean_answer(s: str) -> str:
    """CBSE's Full Credit field, as one readable line."""
    s = BULLET.sub(" | ", s)
    s = re.sub(r"\s*\|\s*(\|\s*)+", " | ", s).strip(" |").strip()
    return " ".join(s.split())


def _key(text_value: str) -> str:
    return re.sub(r"[^0-9a-z]", "", (text_value or "").lower())


def correct_letter(answer: str, options: list[dict]) -> tuple[str | None, str | None]:
    """The key letter, and a note where the letter and the value disagree.

    Keyed on the VALUE, not the letter: the SAS books print at least one item
    whose letter names one option while the text quotes another, and no
    validator downstream can see the difference.
    """
    if not options:
        return None, None
    m = re.match(r"\s*(?:Option\s*)?([A-D])[.)]?\s*(.*)", answer or "", re.S)
    if not m:
        return None, "no key letter in the Full Credit field"
    letter, value = m.group(1), _key(m.group(2))
    by_letter = {o["label"]: _key(o["text"]) for o in options}
    if not value:
        return letter, None
    named = by_letter.get(letter, "")
    if value and named and (value in named or named in value):
        return letter, None
    matches = [k for k, v in by_letter.items() if v and (value in v or v in value)]
    if len(matches) == 1 and matches[0] != letter:
        return matches[0], (f"key printed {letter} but quotes option "
                            f"{matches[0]}'s text; keyed on the value")
    return letter, "key letter and key text do not agree with any one option"


def load_figures() -> tuple[dict[str, list[str]], list[dict]]:
    """(item code -> image file names, every asset entry) from the crop runs."""
    by_code: dict[str, list[str]] = {}
    assets: list[dict] = []
    seen: set[str] = set()
    for index in sorted(FIGURES.glob("*/_manifest.json")):
        data = json.loads(index.read_text(encoding="utf-8"))
        for asset in data["assets"]:
            if asset["file_name"] not in seen:
                seen.add(asset["file_name"])
                assets.append(asset)
        by_code.update(data["items"])
    for code, others in EXTRA_FIGURES.items():
        if code in by_code:
            extra = [n for other in others for n in by_code.get(other, [])]
            by_code[code] = list(dict.fromkeys(by_code[code] + extra))
    return by_code, assets


def build(item: dict, fix: dict, figures: dict[str, list[str]] | None = None) -> dict:
    context = fix.get("context")
    if context is None:
        context = "" if fix.get("drop_context") else (item.get("context") or "")
    stem = item["stem"]
    if fix.get("stem_from_context"):
        stem, context = item.get("context") or "", ""
    if fix.get("strip_prefix") and stem.startswith(fix["strip_prefix"]):
        stem = stem[len(fix["strip_prefix"]):]
    label = item["chapter_label"]
    stem = clean_stem(stem, label)
    if context:
        stem = clean_stem(context, label) + " " + stem

    options = [{"label": o["label"], "text": fold(" ".join(o["text"].split()))}
               for o in item["options"]]
    if fix.get("split_options"):
        m = UNPUNCTUATED_OPTIONS.search(stem)
        if not m:
            raise SystemExit(f"{item['code']}: split_options found no A/B/C/D run")
        options = [{"label": k.upper(), "text": fold(m.group(k))} for k in "abcd"]
        stem = stem[:m.start()].strip()
    answer = clean_answer(fold(item["answer"]))
    letter, note = correct_letter(answer, options)
    out = {
        "number": item["code"],
        "form": "mcq" if len(options) == 4 else item["form"],
        "stem": fold(stem),
        "options": options,
        "answer": answer,
        # CBSE's competency name is not a Bloom level and the closed set would
        # reject it, so it is left for the tagger rather than guessed at.
        "reproduction": "verbatim",
    }
    if letter:
        out["correct_option"] = letter
    if note:
        out["_note"] = note
    images = (figures or {}).get(item["code"])
    if images:
        # figure_required WITHOUT images fails validator V-07, and images that
        # do not resolve against the extraction's asset_manifest fail silently,
        # which is why check_figure_resolution is run after every load.
        out["images"] = images
        out["figure_required"] = True
    return out


def resolve(grade: int, db) -> dict[int, dict]:
    """sort_order -> {chapter_id, chapter_name} for this grade's Maths rows."""
    rows = db.execute(text(
        "SELECT c.id, c.sort_order, c.chapter_name FROM chapter_master c "
        "  JOIN subject s ON s.id = c.subject_id "
        " WHERE c.standard_id = :s AND s.subject_name = 'Mathematics' "
        " ORDER BY c.sort_order"), {"s": STANDARD[grade]}).fetchall()
    return {r[1]: {"chapter_id": r[0], "chapter_name": r[2]} for r in rows}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grade", type=int, required=True, choices=(6, 7))
    ap.add_argument("--verbose", action="store_true",
                    help="list the declined chapters and the dropped items")
    a = ap.parse_args()
    grade = a.grade

    draft = json.loads((DRAFTS / f"c{grade}_maths_sas.json").read_text(encoding="utf-8"))
    cmap = CHAPTER_MAP[grade]
    keep = KEEP[grade]

    unknown = {i["chapter_label"] for i in draft["items"]} - set(cmap)
    if unknown:
        raise SystemExit(f"old chapters with no decision recorded: {sorted(unknown)}")
    codes = {i["code"] for i in draft["items"]}
    stray = set(keep) - codes
    if stray:
        raise SystemExit(f"KEEP names codes the draft does not hold: {sorted(stray)}")
    both = set(keep) & set(BROKEN)
    if both:
        raise SystemExit(f"KEEP names items recorded as BROKEN: {sorted(both)}")

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        chapters = {g: resolve(g, db) for g in STANDARD}
    finally:
        db.close()

    figures, assets = load_figures()
    needs_figure = [c for c in keep if c in figures]
    without = [c for c in keep if c in figures and not figures[c]]
    if without:
        raise SystemExit(f"KEEP names items whose figure was not rendered: {without}")

    # (destination grade, chapter) -> items
    by_dest: dict[tuple[int, int], list[dict]] = {}
    dropped: dict[str, list[str]] = {}
    for item in draft["items"]:
        dest = keep.get(item["code"])
        if dest is None:
            dropped.setdefault(item["chapter_label"], []).append(item["code"])
            continue
        target = dest if isinstance(dest, tuple) else (grade, dest)
        by_dest.setdefault(target, []).append(
            build(item, FIXES.get(item["code"], {}), figures))

    for dest_grade in sorted({g for g, _ in by_dest} | {grade}):
        out_dir = LOAD / (f"c{grade}" if dest_grade == grade
                          else f"c{grade}_to_c{dest_grade}")
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob("ch*.json"):
            old.unlink()

    print(f"Class {grade} Mathematics  {len(draft['items'])} SAS items read\n")
    print(f"{'dest':<6} {'ch':<4} {'chapter':<38} {'items':>5}  from")
    print("-" * 96)
    total = 0
    for dest_grade, order in sorted(by_dest):
        ch = chapters[dest_grade][order]
        items = by_dest[(dest_grade, order)]
        cross = dest_grade != grade
        out_dir = LOAD / (f"c{grade}" if not cross else f"c{grade}_to_c{dest_grade}")
        sources = sorted({i["chapter_label"] for i in draft["items"]
                          if i["code"] in keep
                          and (keep[i["code"]] if isinstance(keep[i["code"]], tuple)
                               else (grade, keep[i["code"]])) == (dest_grade, order)})
        (out_dir / f"ch{order:02d}.json").write_text(json.dumps(
            {"chapter": order, "chapter_id": ch["chapter_id"],
             "extraction_id": None, "source": draft["source"],
             "source_url": SOURCE_URL + draft["source"],
             "source_grade": grade, "target_grade": dest_grade,
             "standard_id": STANDARD[dest_grade], "cross_grade": cross,
             "old_chapters": sources,
             # Only the assets this chapter's items actually name. The manifest
             # is what `write_question_bank` resolves `images` against, so an
             # entry missing here means the figure is dropped with no trace.
             "assets": [x for x in assets
                        if any(x["file_name"] in (i.get("images") or [])
                               for i in items)],
             "items": items},
            indent=1, ensure_ascii=False), encoding="utf-8")
        label = f"C{dest_grade}" + ("*" if cross else "")
        print(f"{label:<6} {order:<4} {ch['chapter_name']:<38} "
              f"{len(items):>5}  {', '.join(sources)}")
        total += len(items)
    print("-" * 96)
    print(f"{'':<6} {'':<4} {'':<38} {total:>5}  * = cross-grade, NEP moved the "
          f"topic")

    placed = set(by_dest)
    empty = set()
    for lbl, (dest, _why) in cmap.items():
        if dest is None:
            continue
        target = dest if isinstance(dest, tuple) else (grade, dest)
        if target not in placed:
            empty.add(target)
    if empty:
        print(f"\nmapped but nothing loadable: "
              f"{', '.join(f'C{g} ch{c}' for g, c in sorted(empty))} "
              f"-- every item needs its figure")
    if BROKEN:
        print("\nITEMS CBSE PRINTED WRONG, not loaded")
        for code, why in sorted(BROKEN.items()):
            if code in codes:
                print(f"  {code}: {why}")
    if a.verbose:
        print("\nDECLINED old chapters")
        for lbl, (order, reason) in sorted(cmap.items()):
            if order is None:
                print(f"  {lbl}\n      {reason}")
        print("\nITEMS DROPPED from mapped chapters")
        for lbl in sorted(dropped):
            if cmap[lbl][0] is not None:
                print(f"  {lbl}: {len(dropped[lbl])} -> {' '.join(dropped[lbl])}")
    notes = [(i["number"], i["_note"]) for v in by_dest.values() for i in v
             if i.get("_note")]
    if notes:
        print("\nKEY NOTES")
        for code, note in notes:
            print(f"  {code}: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
