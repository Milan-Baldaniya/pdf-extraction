"""One descriptor per printed question bank.

Everything that differs between books lives here, so adding a book is a data
change rather than another copy of the pipeline. Before this there were two
near-identical extractor modules, each exporting a module-level SUBJECT_ID that
four other scripts imported - which made a book whose chapters span several
subjects impossible to express.

The Social Science book is exactly that case: one volume covering History,
Geography, Political Science and Economics, which this estate stores as four
separate subjects. So `subject_id` belongs to the CHAPTER, not to the book.

Page ranges are the printed (folio) page numbers as given in the book's own
CONTENTS. They are resolved to physical PDF pages by scripts.folio_map, because
these books interleave full-page adverts and therefore have no constant offset -
the Maths book's `PAGE_OFFSET = -1` is wrong here at nearly every page.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

DOWNLOADS = Path(r"C:\Users\MILAN\Downloads")
QA = DOWNLOADS / "std 10 Q&A"


@dataclass(frozen=True)
class Chapter:
    number: int
    first_page: int          # printed page, inclusive
    last_page: int           # printed page, inclusive
    title: str               # as printed in the book
    chapter_id: int          # chapter_master.id it is filed under
    subject_id: int          # the subject that chapter belongs to


@dataclass(frozen=True)
class Book:
    key: str
    prefix: str              # part-file prefix, e.g. "sch" -> parts/sch01_obj.json
    pdf: Path
    split_dir: Path
    standard: int
    standard_id: int
    tenant: int
    board: str
    syear: int
    subject_name: str        # for the extraction row's label only
    answer_marker: re.Pattern
    folio: re.Pattern        # pulls the printed page number out of a page header
    sections: dict           # printed banner -> (slug, form, marks)
    chapters: list[Chapter]
    # The typeface a QUESTION number is set in. Social Science answers are full
    # of numbered lists ("1. Cotton", "2. Jowar and Bajra") set in Euclid 11pt,
    # while question numbers are Impact 8pt. Matching "^\d+\." alone reports a
    # page's questions as "111..1" and makes page ordering impossible.
    question_font: str | None = None
    banner: re.Pattern = field(
        default_factory=lambda: re.compile(r"CHAPTER\s+CHAPTER\s+(\d+)", re.I))

    def chapter(self, number: int) -> Chapter:
        for c in self.chapters:
            if c.number == number:
                return c
        raise KeyError(f"{self.key}: no chapter {number}")

    @property
    def numbers(self) -> list[int]:
        return [c.number for c in self.chapters]


# The five banners this book prints. Note the SINGULAR "QUESTION" - the Maths
# book used plural, and matching on the Maths vocabulary finds nothing here.
# SUMMARY is a prose recap, not questions, and is deliberately absent so that
# no reader is ever pointed at it.
SST_SECTIONS = {
    "MULTIPLE CHOICE QUESTION": ("mcq", "mcq", 1),
    "VERY SHORT QUESTION": ("vshort", "very_short", 1),
    "SHORT ANSWER QUESTION": ("short", "short", 3),
    "LONG ANSWER QUESTION": ("long", "long", 5),
    "CASE BASED QUESTION": ("case", "case_study", 4),
}

SST10 = Book(
    key="sst10",
    prefix="sch",
    pdf=(QA / "Social Science -CBSE 10-20260921T100527Z-1-001"
            / "Social Science -CBSE 10" / "CBSE 10th Social Science (1).pdf"),
    split_dir=DOWNLOADS / "sst10_split",
    standard=10,
    standard_id=43,
    tenant=1,
    board="CBSE",
    syear=2026,
    subject_name="Social Science",
    answer_marker=re.compile(r"(?<![A-Za-z])Ans\s*:"),
    folio=re.compile(r"PAGE\s+(\d{1,3})"),
    sections=SST_SECTIONS,
    question_font="Impact",
    chapters=[
        # History -> subject 4470 "Social Sciences-3".
        # The database also holds 23708 The Age of Industrialisation, which this
        # book does not cover; it keeps whatever questions it already has.
        Chapter(1,   27,  68, "The Rise of Nationalism In Europe",   23705, 4470),
        Chapter(2,   69, 108, "Nationalism In India",                23706, 4470),
        Chapter(3,  109, 134, "Making of a Global World",            23707, 4470),
        Chapter(4,  135, 164, "Print Culture and the Modern World",  23709, 4470),
        # Geography -> 4469 "Social Sciences-2".
        # 23699 Lifelines of National Economy is not in this book.
        Chapter(5,  165, 194, "Resources and Development",           23693, 4469),
        Chapter(6,  195, 218, "Forest and Wildlife Resources",       23694, 4469),
        Chapter(7,  219, 252, "Water Resources",                     23695, 4469),
        Chapter(8,  253, 292, "Agriculture",                         23696, 4469),
        Chapter(9,  293, 320, "Mineral and Energy Resources",        23697, 4469),
        Chapter(10, 321, 358, "Manufacturing Industries",            23698, 4469),
        # Political Science -> 4064 "Social Sciences".
        Chapter(11, 359, 382, "Power-sharing",                       23710, 4064),
        Chapter(12, 383, 412, "Federalism",                          23711, 4064),
        Chapter(13, 413, 438, "Gender, Religion and Caste",          23712, 4064),
        Chapter(14, 439, 464, "Political Parties",                   23713, 4064),
        Chapter(15, 465, 492, "Outcome of Democracy",                23714, 4064),
        # Economics -> 4472 "Economics".
        # 23704 Consumer Rights is not in this book.
        Chapter(16, 493, 522, "Development",                         23700, 4472),
        Chapter(17, 523, 554, "Sectors of the Indian Economy",       23701, 4472),
        Chapter(18, 555, 586, "Money and Credit",                    23702, 4472),
        Chapter(19, 587, 618, "Globalization and the Indian Economy", 23703, 4472),
        # Chapter 20 "Map Work" (619-648) is deliberately absent: there is no
        # chapter_master row for it, and the user chose to report rather than
        # create missing chapters.
    ],
)

BOOKS: dict[str, Book] = {b.key: b for b in (SST10,)}


def get(key: str) -> Book:
    if key not in BOOKS:
        raise SystemExit(f"unknown book {key!r}; known: {', '.join(sorted(BOOKS))}")
    return BOOKS[key]