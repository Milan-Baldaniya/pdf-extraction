"""Build the CBSE Class 6 chapter sheet, by ACTUAL chapter name.

    python -m scripts.make_class6_sheet

Why the naming matters: Class 7 Mathematics is stored in this estate as
"Ganita Prakash - Chapter 1" through "- Chapter 15", and all 68 Class 8
chapters are placeholders of the same kind - a book title plus a number. That
tells a learner nothing, gives the concept mapper nothing to match on, and has
to be undone by hand later. Class 10 is stored properly ("Real Numbers",
"Polynomials"). Class 6 follows Class 10.

The book title and the chapter number are still carried, but in their OWN
columns, where they cannot be mistaken for the chapter's name.

Every chapter list below was checked against a published source rather than
written from memory; SOURCES records where each came from.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(r"C:\Users\MILAN\Downloads\Class6_CBSE_Chapters.xlsx")

STANDARD_ID = 39          # Class 6, sub_institute_id 1 (CBSE)
STANDARD_NAME = "Class 6"

# subject_id values reused from the classes that already exist, so the sheet
# imports against the same subjects rather than creating duplicates.
SUBJECTS = [
    ("Mathematics",     3976, "Ganita Prakash"),
    ("Science",         3975, "Curiosity"),
    ("Social Sciences", 4064, "Exploring Society: India and Beyond"),
    ("English",         3978, "Poorvi"),
    ("Hindi-A",         3977, "Malhar"),
]

# subject -> [(chapter number, chapter name, unit/theme, note)]
CHAPTERS: dict[str, list[tuple[int, str, str, str]]] = {
    "Mathematics": [
        (1,  "Patterns in Mathematics", "", ""),
        (2,  "Lines and Angles", "", ""),
        (3,  "Number Play", "", ""),
        (4,  "Data Handling and Presentation", "", ""),
        (5,  "Prime Time", "", ""),
        (6,  "Perimeter and Area", "", ""),
        (7,  "Fractions", "", ""),
        (8,  "Playing with Constructions", "", ""),
        (9,  "Symmetry", "", ""),
        (10, "The Other Side of Zero", "", ""),
    ],
    "Science": [
        (1,  "The Wonderful World of Science", "", ""),
        (2,  "Diversity in the Living World", "", ""),
        (3,  "Mindful Eating: A Path to a Healthy Body", "", ""),
        (4,  "Exploring Magnets", "", ""),
        (5,  "Measurement of Length and Motion", "", ""),
        (6,  "Materials Around Us", "", ""),
        (7,  "Temperature and its Measurement", "", ""),
        (8,  "A Journey through States of Water", "", ""),
        (9,  "Methods of Separation in Everyday Life", "", ""),
        (10, "Living Creatures: Exploring their Characteristics", "", ""),
        (11, "Nature's Treasures", "", ""),
        (12, "Beyond Earth", "", ""),
    ],
    "Social Sciences": [
        (1,  "Locating Places on the Earth",
         "Theme A - India and the World: Land and the People", "Geography"),
        (2,  "Oceans and Continents",
         "Theme A - India and the World: Land and the People", "Geography"),
        (3,  "Landforms and Life",
         "Theme A - India and the World: Land and the People", "Geography"),
        (4,  "Timeline and Sources of History",
         "Theme B - Tapestry of the Past", "History"),
        (5,  "India, That Is Bharat",
         "Theme B - Tapestry of the Past", "History"),
        (6,  "The Beginnings of Indian Civilisation",
         "Theme B - Tapestry of the Past", "History"),
        (7,  "India's Cultural Roots",
         "Theme C - Our Cultural Heritage and Knowledge Traditions", "History"),
        (8,  "Unity in Diversity, or 'Many in the One'",
         "Theme C - Our Cultural Heritage and Knowledge Traditions", "History"),
        (9,  "Family and Community",
         "Theme D - Governance and Democracy", "Civics"),
        (10, "Grassroots Democracy - Part 1: Governance",
         "Theme D - Governance and Democracy", "Civics"),
        (11, "Grassroots Democracy - Part 2: Local Government in Rural Areas",
         "Theme D - Governance and Democracy", "Civics"),
        (12, "Grassroots Democracy - Part 3: Local Government in Urban Areas",
         "Theme D - Governance and Democracy", "Civics"),
        (13, "The Value of Work",
         "Theme E - Economic Life Around Us", "Economics"),
        (14, "Economic Activities Around Us",
         "Theme E - Economic Life Around Us", "Economics"),
    ],
    "English": [
        (1,  "A Bottle of Dew", "Unit 1 - Fables and Folk Tales", ""),
        (2,  "The Raven and the Fox", "Unit 1 - Fables and Folk Tales", ""),
        (3,  "Rama to the Rescue", "Unit 1 - Fables and Folk Tales", ""),
        (4,  "The Unlikely Best Friends", "Unit 2 - Friendship", ""),
        (5,  "A Friend's Prayer", "Unit 2 - Friendship", ""),
        (6,  "The Chair", "Unit 2 - Friendship", ""),
        (7,  "Neem Baba", "Unit 3 - Nurturing Nature", ""),
        (8,  "What a Bird Thought", "Unit 3 - Nurturing Nature", ""),
        (9,  "Spices that Heal Us", "Unit 3 - Nurturing Nature", ""),
        (10, "Change of Heart", "Unit 4 - Sports and Wellness", ""),
        (11, "The Winner", "Unit 4 - Sports and Wellness", ""),
        (12, "Yoga - A Way of Life", "Unit 4 - Sports and Wellness", ""),
        (13, "Hamara Bharat - Incredible India!",
         "Unit 5 - Culture and Tradition", ""),
        (14, "The Kites", "Unit 5 - Culture and Tradition", ""),
        (15, "Ila Sachani: Embroidering Dreams with Her Feet",
         "Unit 5 - Culture and Tradition", ""),
        (16, "National War Memorial", "Unit 5 - Culture and Tradition", ""),
    ],
    # Titles in Devanagari, as the book prints them, matching how Class 10
    # Hindi-A is already stored. The bracketed genre the book gives each piece
    # is kept in the note column, not glued onto the name.
    "Hindi-A": [
        (1,  "\u092e\u093e\u0924\u0943\u092d\u0942\u092e\u093f", "", "\u0915\u0935\u093f\u0924\u093e"),
        (2,  "\u0917\u094b\u0932", "", "\u0938\u0902\u0938\u094d\u092e\u0930\u0923"),
        (3,  "\u092a\u0939\u0932\u0940 \u092c\u0942\u0901\u0926", "", "\u0915\u0935\u093f\u0924\u093e"),
        (4,  "\u0939\u093e\u0930 \u0915\u0940 \u091c\u0940\u0924", "", "\u0915\u0939\u093e\u0928\u0940"),
        (5,  "\u0930\u0939\u0940\u092e \u0915\u0947 \u0926\u094b\u0939\u0947", "", "\u0926\u094b\u0939\u0947"),
        (6,  "\u092e\u0947\u0930\u0940 \u092e\u093e\u0901", "", "\u0906\u0924\u094d\u092e\u0915\u0925\u093e"),
        (7,  "\u091c\u0932\u093e\u0924\u0947 \u091a\u0932\u094b", "", "\u0915\u0935\u093f\u0924\u093e"),
        (8,  "\u0938\u0924\u094d\u0930\u093f\u092f\u093e \u0914\u0930 \u092c\u093f\u0939\u0942 \u0928\u0943\u0924\u094d\u092f", "", "\u0928\u093f\u092c\u0902\u0927"),
        (9,  "\u092e\u0948\u092f\u093e \u092e\u0948\u0902 \u0928\u0939\u093f\u0902 \u092e\u093e\u0916\u0928 \u0916\u093e\u092f\u094b", "", "\u092a\u0926"),
        (10, "\u092a\u0930\u0940\u0915\u094d\u0937\u093e", "", "\u0915\u0935\u093f\u0924\u093e"),
        (11, "\u091a\u0947\u0924\u0915 \u0915\u0940 \u0935\u0940\u0930\u0924\u093e", "", "\u0915\u0935\u093f\u0924\u093e"),
        (12, "\u0939\u093f\u0902\u0926 \u092e\u0939\u093e\u0938\u093e\u0917\u0930 \u092e\u0947\u0902 \u091b\u094b\u091f\u093e-\u0938\u093e \u0939\u093f\u0902\u0926\u0941\u0938\u094d\u0924\u093e\u0928", "", "\u092f\u093e\u0924\u094d\u0930\u093e \u0935\u0943\u0924\u093e\u0902\u0924"),
        (13, "\u092a\u0947\u0921\u093c \u0915\u0940 \u092c\u093e\u0924", "", "\u0928\u093f\u092c\u0902\u0927"),
    ],
}

SOURCES = {
    "Mathematics":
        "NCERT Ganita Prakash Class 6 contents (tiwariacademy.com class-6-maths-syllabus)",
    "Science":
        "NCERT Curiosity Class 6. Chapters 10 and 12 were confirmed individually "
        "(allen.in, tiwariacademy.com) after a search result mixed in the pre-2024 "
        "book's 'Motion and Measurement of Distances' and 'Electricity and Circuits'",
    "Social Sciences":
        "NCERT Exploring Society: India and Beyond Class 6, 14 chapters in 5 themes "
        "(tiwariacademy.com, learncbse.in)",
    "English":
        "NCERT Poorvi Class 6, 16 chapters in 5 units (tiwariacademy.com, ncertbooks.net)",
    "Hindi-A":
        "NCERT Malhar Class 6, 13 chapters in Devanagari (studyrankers.com)",
}

HEADERS = ["Standard", "Standard ID", "Subject", "Subject ID", "Chapter No",
           "Chapter Name", "Book", "Unit / Theme", "Note", "Sort Order"]

# The headers the LIVE importer parses, in public/excel_upload/bulk_chapter_data.php.
# It keys each row by the header text, so these must be exact - including the
# "ChapteDesc" typo, which is in the shipped code and in SampleChapterUpload.xlsx.
# Everything else (syear, grade, standard, subject, sub_institute_id, user_id)
# comes from the upload form, not the file, so there is one sheet per subject.
IMPORT_HEADERS = ["ChapterName", "ChapteDesc", "Availability", "ShowHide", "SortOrder"]

NOTES = [
    "",
    "WHY THE CHAPTER NAME COLUMN LOOKS LIKE THIS",
    "Class 7 Mathematics is stored as 'Ganita Prakash - Chapter 1' ... '- Chapter 15', and all 68",
    "Class 8 chapters are placeholders of the same kind: a book title plus a number. Class 10 is",
    "stored properly ('Real Numbers', 'Polynomials'). This sheet follows Class 10. The book title",
    "and the chapter number are still here, in their own columns, where they cannot be mistaken",
    "for the chapter's name.",
    "",
    "NOT IN THIS SHEET",
    "Topics and concepts. This is the chapter layer only. Class 9 and Class 10 also carry topics",
    "and concepts beneath each chapter; that is a separate and much larger job.",
    "",
    "BEFORE IMPORTING",
    "Class 6 (standard_id 39, sub_institute_id 1) currently has ZERO chapters, so nothing here",
    "overwrites existing data. The subject IDs are the ones classes 7-10 already use, so an import",
    "should attach to those subjects rather than create new ones - worth confirming on the way in.",
]


def main() -> int:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Class 6 Chapters"

    head_fill = PatternFill("solid", fgColor="1F4E79")
    head_font = Font(bold=True, color="FFFFFF", size=11)
    name_font = Font(bold=True)
    thin = Side(style="thin", color="D0D7DE")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    band = PatternFill("solid", fgColor="F2F6FA")

    ws.append(HEADERS)
    for c in range(1, len(HEADERS) + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill, cell.font = head_fill, head_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
    ws.freeze_panes = "A2"

    row = 2
    per_subject = []
    for index, (subject, subject_id, book) in enumerate(SUBJECTS):
        chapters = CHAPTERS[subject]
        per_subject.append((subject, len(chapters)))
        for number, name, unit, note in chapters:
            ws.append([STANDARD_NAME, STANDARD_ID, subject, subject_id, number,
                       name, book, unit, note, number])
            for c in range(1, len(HEADERS) + 1):
                cell = ws.cell(row=row, column=c)
                cell.border = border
                cell.alignment = Alignment(vertical="center",
                                           wrap_text=c in (6, 8))
                if index % 2 == 1:
                    cell.fill = band
            ws.cell(row=row, column=6).font = name_font    # the chapter name
            row += 1

    for i, width in enumerate((10, 11, 17, 10, 10, 52, 36, 46, 16, 11), start=1):
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}{row - 1}"

    # ---- second sheet: where each list came from, and what is NOT here ----
    src = wb.create_sheet("Sources & Notes")
    src.append(["Subject", "Book", "Chapters", "Source checked"])
    for c in range(1, 5):
        cell = src.cell(row=1, column=c)
        cell.fill, cell.font = head_fill, head_font
        cell.border = border

    r = 2
    for subject, _subject_id, book in SUBJECTS:
        src.append([subject, book, len(CHAPTERS[subject]), SOURCES[subject]])
        for c in range(1, 5):
            src.cell(row=r, column=c).alignment = Alignment(vertical="top",
                                                            wrap_text=True)
            src.cell(row=r, column=c).border = border
        r += 1

    for i, width in enumerate((17, 36, 10, 95), start=1):
        src.column_dimensions[get_column_letter(i)].width = width

    r += 1
    for line in NOTES:
        src.cell(row=r, column=1, value=line)
        if line and line == line.upper():
            src.cell(row=r, column=1).font = Font(bold=True)
        r += 1

    # ---- one ready-to-upload sheet per subject, in the importer's own format ----
    for subject, subject_id, _book in SUBJECTS:
        tab = wb.create_sheet(f"Import {subject}"[:31])
        tab.append(IMPORT_HEADERS)
        for c in range(1, len(IMPORT_HEADERS) + 1):
            cell = tab.cell(row=1, column=c)
            cell.fill, cell.font = head_fill, head_font
            cell.border = border
        rr = 2
        for number, name, unit, _note in CHAPTERS[subject]:
            # chapter_desc carries the unit/theme where the book has one; it is
            # the only free-text column the importer accepts.
            tab.append([name, unit, 1, 1, number])
            for c in range(1, len(IMPORT_HEADERS) + 1):
                tab.cell(row=rr, column=c).border = border
                tab.cell(row=rr, column=c).alignment = Alignment(vertical="center",
                                                                  wrap_text=c == 1)
            rr += 1
        for i, width in enumerate((52, 46, 13, 11, 11), start=1):
            tab.column_dimensions[get_column_letter(i)].width = width
        tab.freeze_panes = "A2"
        note = tab.cell(row=rr + 1, column=1,
                        value=f"Upload through LMS > bulk chapter upload with "
                              f"Standard = Class 6 (id {STANDARD_ID}) and "
                              f"Subject = {subject} (id {subject_id}). "
                              f"The importer takes those from the form, not from this file, "
                              f"and skips a chapter whose name already exists for that class.")
        note.font = Font(italic=True, size=9)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)

    total = sum(n for _, n in per_subject)
    print(f"wrote {OUT}")
    for subject, n in per_subject:
        print(f"   {subject:<18} {n:>3} chapters")
    print(f"   {'TOTAL':<18} {total:>3} chapters across {len(per_subject)} subjects")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
