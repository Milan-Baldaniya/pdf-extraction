"""One parser for the NODIA "QB 2026" chapter-wise banks, driven by a registry.

    python -m scripts.parse_nodia_qb --book c6_social
    python -m scripts.parse_nodia_qb --book c7_social      # regression check

These books share a house style and differ in the details that matter most,
so each is declared in `BOOKS` rather than given its own parser. The details
that differ, and that silently destroy a run when assumed:

  ANSWER MARKER      Class 7 Social Science prints `AAns` -- a doubled first
                     letter the text layer keeps, as in "NNCERT EXERCIS".
                     Class 6 Social Science prints `Ans :` and holds no
                     `AAns` at all. Parsed with the other book's marker,
                     either one yields nothing and reports no error.
  PARTS              Class 7 is printed in two parts whose chapter numbers
                     RESTART, so "CHAP 1" names two different chapters and
                     the part is what disambiguates. Class 6 has one part.
  FOLIO OFFSET       measured at run time, never assumed.

Everything else is shared, and each rule below was learned from a real
failure:

  * Chapter comes from the printed folio range, not the running header.
  * FOUR LABELLED OPTIONS PLUS AN ANSWER THAT NAMES ONE IS AN MCQ, whatever
    the section banner says -- one Class 7 chapter prints no MULTIPLE CHOICE
    heading at all and reported zero against sixty in its siblings.
  * The key comes from the answer's VALUE, not its letter. A printed letter
    can name a different option than the value beside it, and `V-02` cannot
    see the difference.
  * Banners are letter-spaced ("MULT IPL E CHOICE QUESTIO"), so they are
    matched with whitespace removed, and must be short and capitalised or a
    prose sentence about multiple-choice questions re-types the chapter.
  * A one-word answer is a complete answer.
  * pdf.tube advertisement pages sit INSIDE chapter ranges and are dropped.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import fitz  # noqa: E402

from scripts.devlys_to_unicode import convert as _devlys  # noqa: E402

fitz.TOOLS.mupdf_display_errors(False)

MIRROR = Path(__file__).resolve().parents[1] / "data" / "qbank" / "mirror" / "pdftube"
SOURCE_URL = "https://pdf.tube/School/CBSE/"

# Shared by every Hindi book: the marker is उत्तर once transliterated,
# and questions number "6-" while answers sub-point "1.".
MARK_HINDI = ("(?m)^\s*(?:उत्त\s*र|mmÙkj|mÙkj)"
              "\s*[%:।ः]?\s*")
QSTART_HINDI = "(?m)^[ \t]*(\d{1,3})\s*[-–]\s*"

# THE SAME FAMILY, PRINTED THE OTHER WAY ROUND. Every string below is built
# from \u escapes on purpose: Devanagari pasted into a source file can be
# normalised on the way in, after which the pattern still LOOKS right and
# silently stops matching -- see [[devanagari-anchors-need-unicode-escapes]].
_UTTA = "उत्त"      # उत्त
_RA = "र"                          # र
_ADHYAY = "अध्याय"   # अध्याय
_PRISHTH = "पृष्ठ"        # पृष्ठ

# THE ANSWER LABEL OPENS WITH A DINGBAT. pdf.tube sets the "उत्तर ः" label
# with a Wingdings bullet, and the text layer keeps that glyph as U+0001, so
# the line really reads "\x01उत्त र ः". U+0001 is not whitespace, so the
# `^\s*` anchor in MARK_HINDI never reaches the word: of Class 10 Hindi-B's
# 3,681 marker lines 3,441 begin with the bullet, and MARK_HINDI matched TEN
# in the whole 607-page book. The parse returned 2 items and reported no
# error. Class 10 Hindi-A is printed the same way -- 3,053 occurrences, 27
# of them anchorable -- so it is under-parsed by the same fault.
MARK_HINDI_BULLET = (rf"(?m)^[\s\x01]*(?:{_UTTA}\s*{_RA}|mmÙkj|mÙkj)"
                     rf"\s*[%:।ः]?\s*")

# AND IT NUMBERS QUESTIONS "1." NOT "1-". Hindi-A sub-points its answers with
# "1." and so must key its questions on the dash; Hindi-B does the opposite,
# and measured over the whole book the TAB is what separates the two: 4,011
# lines open "N.<tab>" and only 11 open "N." without one. Keyed on the dash
# this book yields 743 false starts and misses 4,011 real ones.
#
# The leading class absorbs the span reader's hang marker (`QMARK`, defined
# further down) WITHOUT NAMING IT. Anchored on one control character this
# pattern breaks the day that character changes: it was \x1d, which
# `str.splitlines()` treats as a line break and `_blob` therefore ate, and
# it is now \x1f, which survives and sits between the anchor and the digit.
# Either way the TAB is what identifies a question here, so the marker is
# tolerated rather than required.
QSTART_HINDI_DOT = "(?m)^[ \t\x1c-\x1f]*(\\d{1,3})\\.\t[ \t]*"


BOOKS: dict[str, dict] = {
    "c10_hindi_a": {
        "file": "c10_Hindi_A_QB_2026.pdf",
        "standard_id": 43, "standard": 10, "publisher": "nodia",
        "transliterate": True,
        # SET IN TWO LEGACY FONTS, AND ONLY ONE OF THEM CONVERTS. The body
        # is DevLys-010 on most pages and SHREE-DEV7-0714E on the rest, and
        # the two are mixed WITHIN a page -- folio 173 carries questions 24
        # to 31 in DevLys and question 32 in SHREE. Run through the DevLys
        # table a SHREE span yields "र्वटउव्त H$े श्लक्ष्ट©", which is
        # Devanagari-shaped nonsense that loads without complaint. So the
        # page is rebuilt span by span, each span read with its own font,
        # and a SHREE span that is not plain ASCII is replaced by U+FFFD;
        # any item still holding one is dropped at the end.
        "page_text": "spans",
        # ATTRIBUTED ON THE RUNNING HEADER, WHICH PRINTS THE CHAPTER NAME.
        # Not on the folio: the book interleaves, and folio 175 opens
        # बालगोबिन भगत while folio 177 is still नेताजी का चश्मा question
        # 41. Any contiguous folio range therefore files one chapter's
        # questions under its neighbour. See `_page_chapter`.
        "attribute_by": "banner",
        "marker": MARK_HINDI,
        # QUESTIONS HANG AT THE COLUMN EDGE, SUB-POINTS ARE INDENTED, and
        # both are numbered "N.". `_page_text_spans` marks the hanging ones
        # with \x1f so the two cannot be confused; keyed on "N." alone,
        # every answer that lists its points is truncated at its own "1.".
        # BOTH SEPARATORS ARE IN USE and neither section is small: 795
        # questions are numbered "57." and 270 "2-", the second kind being
        # the whole of the प्रश्नोत्तर and गद्यांश sections. Keyed on the
        # dot alone, नेताजी का चश्मा loses its entire MCQ section.
        "qstart": "(?m)^\x1f(\\d{1,3})\\s*[.\\-–]\\s*",
        "option_labels": "कखगघ",
        # The choices wrap in this two-column setting, and their second line
        # carries no label -- read one line to an option, the tail stays
        # behind and is swept into the question: 63 of 1,155 stems went on
        # after their own question mark. See `_options_wrapped`.
        "wrapped_options": True,
        "subject_of_part": {1: "Hindi-A"},
        "title": "NODIA Class 10 Hindi-A Question Bank 2026",
        "textbook": "क्षितिज भाग 2",
        # THE DATABASE ORDERS POETRY BEFORE PROSE AND THE BOOK THE
        # REVERSE, so the printed folios cross over: database chapters 1-6
        # are the book's काव्य खंड in the 280s upward, and 7-12 its
        # गद्य खंड from 153. Taken in printed order, every chapter would
        # be six places out. The folios below are for the record only --
        # nothing reads them.
        #
        # `banner_of` is the name as the RUNNING HEADER prints it, which is
        # not the database name (no poet) and not always the contents
        # name. It is matched EXACTLY, never as a substring: the book's
        # व्याकरण section has a chapter called "पद परिचय" 160 folios
        # before the काव्य chapter called "पद", and a substring match
        # anchors पद in the grammar section.
        "chapters": [
            (1, 1, "सूरदास – पद", 283, 297),
            (1, 2, "तुलसीदास – राम-लक्ष्मण-परशुराम संवाद", 298, 321),
            (1, 3, "जयशंकर प्रसाद – आत्मकथ्य", 322, 336),
            (1, 4, "निराला – उत्साह, अट नहीं रही", 337, 350),
            (1, 5, "नागार्जुन – यह दंतुरित मुसकान, फसल", 351, 369),
            (1, 6, "मंगलेश डबराल – संगतकार", 370, 385),
            (1, 7, "स्वयं प्रकाश – नेताजी का चश्मा", 153, 174),
            (1, 8, "रामवृक्ष बेनीपुरी – बालगोबिन भगत", 175, 195),
            (1, 9, "यशपाल – लखनवी अंदाज़", 196, 214),
            (1, 10, "मन्नू भंडारी – एक कहानी यह भी", 215, 242),
            (1, 11, "यतींद्र मिश्र – नौबतखाने में इबादत", 243, 265),
            (1, 12, "भदंत आनंद कौसल्यायन – संस्कृति", 266, 282),
        ],
        "banner_of": {
            1: "पद",
            2: "राम-लक्ष्मण-परशुराम संवाद",
            3: "आत्मकथ्य",
            4: "उत्साह, अट नहीं रही है",
            5: "यह दंतुरित मुसकान, फसल",
            6: "संगतकार",
            7: "नेताजी का चश्मा",
            8: "बालगोबिन भगत",
            9: "लखनवी अंदाज",
            10: "एक कहानी ये भी",
            11: "नौबतखाने में इबादत",
            12: "संस्कृति",
        },
        # The book's other sections, named here so that a page of theirs
        # ENDS the carry-forward instead of inheriting the chapter above
        # it. Class 9 Hindi doubled its last chapter by carrying 18 pages
        # of composition exercises forward into it.
        "not_chapters": [
            "अपठित गद्यांश", "अपठित पद्यांश",
            "रचना के आधार पर वाक्य भेद", "वाच्य", "पद परिचय", "अलंकार",
            "पत्र-लेखन", "स्ववृत्त-लेखन", "ई-मेल लेखन", "विज्ञापन-लेखन",
            "संदेश-लेखन",
            "माता का अँचल", "साना-साना हाथ जोडि़", "मैं क्यों लिखता हूँ",
        ],
    },
    "c10_hindi_b": {
        "file": "c10_Hindi_B_QB_2026.pdf",
        "standard_id": 43, "standard": 10, "publisher": "nodia",
        "transliterate": True,
        # Read span by span, because the body is set in TWO legacy fonts.
        # 74 of the 607 pages are dominated by SHREE-DEV7-0714E, which the
        # DevLys table turns into "श्उ±ह र्उव§र्डउ द दंवमउर्" -- Devanagari
        # -shaped and meaningless. Those are the व्याकरण and रचनात्मक
        # लेखन sections, which the database does not hold anyway; the
        # spans that matter are the QUESTION NUMBERS, which this book sets
        # in SHREE bold on every page. They are ASCII and survive as they
        # stand, so the literature chapters read correctly.
        "page_text": "spans",
        # ATTRIBUTED ON THE CHAPTER NAME ITS OWN PAGE PRINTS. The book runs
        # six sections -- अपठित, व्याकरण, काव्य, गद्य, संचयन, रचनात्मक
        # लेखन -- and EVERY ONE RESTARTS AT अध्याय 1, so "अध्याय 2" names
        # a different chapter in each. Only the name disambiguates, and
        # only the name keeps the four non-literature sections out.
        "attribute_by": "banner",
        # THE ANSWER LABEL CARRIES A DINGBAT; see MARK_HINDI_BULLET. Under
        # the span reader the control character is already stripped, but
        # the marker tolerates it either way so a plain-text run of this
        # book is not silently empty.
        "marker": MARK_HINDI_BULLET,
        "qstart": QSTART_HINDI_DOT,
        "option_labels": "कखगघ",
        "subject_of_part": {1: "Hindi-B"},
        "title": "NODIA Class 10 Hindi-B Question Bank 2026",
        "textbook": "स्पर्श भाग 2",
        # THE BOOK'S OWN WORDING, WHICH IS WHAT THE RUNNING HEADER PRINTS,
        # and it is not the database's: the database names each chapter
        # after its author ("मीरा – पद"), the header after the text alone
        # ("पद"). Two of these differ from the database spelling by a
        # nukta or by where it sits -- the header prints बडे़ with the
        # nukta AFTER the matra, and फिदा without one at all -- so the
        # value below is the printed form, byte for byte.
        "banner_of": {
            1: "साखी",
            2: "पद",
            3: "मनुष्यता",
            4: "पर्वत प्रदेश में पावस",
            5: "तोप",
            6: "कर चले हम फिदा",
            7: "आत्मत्राण",
            8: "बडे़ भाई साहब",
            9: "डायरी का एक पन्ना",
            10: "तताँरा-वामीरो कथा",
            11: "तीसरी कसम के शिल्पकार शैलेंद्र",
            12: "अब कहाँ दूसरे के दुख से दुखी होने वाले",
            13: "पतझर में टूटी पत्तियाँ",
            14: "कारतूस",
        },
        # Sections the database does not hold. Listed so that a header this
        # parser has never seen is distinguishable from one deliberately
        # excluded: an unknown banner ENDS the carry-forward either way,
        # but a new one should be noticed rather than assumed to be prose.
        # "पदबंध" is why the match is on the WHOLE printed name and not on
        # a prefix: it contains "पद", which is chapter 2, and a substring
        # test hands eight pages of grammar to मीरा.
        "not_chapters": [
            "अपठित गद्यांश", "पदबंध", "रचना के आधार पर वाक्य रूपांतरण",
            "समास", "मुहावरे",
            "हरिहर काका", "सपनों के-से दिन", "टोपी शुक्ला",
            "अनुच्छेद-लेखन", "पत्र-लेखन (औपचारिक)", "सूचना-लेखन",
            "विज्ञापन-लेखन", "लघुकथा-लेखन", "ई-मेल लेखन",
        ],
        # Folios are for the record only -- nothing reads them for
        # attribution. Database 1-7 are the book's काव्य खंड and 8-14 its
        # गद्य खंड, which the book prints in the opposite order.
        "chapters": [
            (1, 1, "साखी", 326, 348),
            (1, 2, "पद (मीरा)", 348, 365),
            (1, 3, "मनुष्यता", 366, 387),
            (1, 4, "पर्वत प्रदेश में पावस", 388, 405),
            (1, 5, "तोप", 406, 419),
            (1, 6, "कर चले हम फ़िदा", 420, 435),
            (1, 7, "आत्मत्राण", 436, 451),
            (1, 8, "बड़े भाई साहब", 170, 191),
            (1, 9, "डायरी का एक पन्ना", 192, 209),
            (1, 10, "तताँरा-वामीरो कथा", 210, 233),
            (1, 11, "तीसरी कसम के शिल्पकार शैलेंद्र", 234, 257),
            (1, 12, "अब कहाँ दूसरे के दुख", 258, 283),
            (1, 13, "पतझर में टूटी पत्तियाँ", 284, 305),
            (1, 14, "कारतूस", 306, 324),
        ],
    },
    "c9_hindi": {
        "file": "c9_CBSE_9th_Hindi_R1.pdf",
        "standard_id": 42, "standard": 9, "publisher": "nodia",
        # The marker is printed in a legacy font encoding on most pages
        # -- "mmUkj%" is how the text layer renders उत्तर: -- and in
        # proper Unicode on the rest. 1,776 of the first, 382 of the
        # second. Either alone loses most of the book.
        "marker": r"(?m)^\s*(?:mmÙkj|उत्तर)\s*[%:।]?\s*",
        # QUESTIONS ARE NUMBERED "6-", ANSWERS SUB-POINT WITH "1.".
        # Sharing one pattern, the first sub-point of every answer reads
        # as the next question and truncates the answer to nothing.
        "qstart": r"(?m)^[ 	]*(\d{1,3})\s*[-–]\s*",
        "option_labels": "कखगघ",
        "subject_of_part": {1: "Hindi-A"},
        "title": "NODIA Class 9 Hindi R-1 Question Bank 2026",
        "textbook": "गंगा (NEP-2020)",
        # Only the खंड-ग literature section. The अपठित, व्याकरण and
        # रचनात्मक लेखन sections are not chapters the database holds.
        "chapters": [
            (1, 1, "दो बैलों की कथा", 81, 109),
            (1, 2, "क्या लिखूँ?", 110, 134),
            (1, 3, "संवादहीन", 135, 160),
            (1, 4, "ऐसी भी बातें होती हैं", 161, 186),
            (1, 5, "आखिरी चट्टान तक", 187, 210),
            (1, 6, "रीढ़ की हड्डी", 211, 231),
            (1, 7, "मैं और मेरा देश", 232, 257),
            (1, 8, "पद", 258, 273),
            (1, 9, "राम-लक्ष्मण-परशुराम संवाद", 274, 297),
            (1, 10, "भारति, जय, विजयकरे!", 298, 316),
            (1, 11, "झाँसी की रानी", 317, 349),
            (1, 12, "घर की याद", 350, 381),
        ],
    },
    "c6_science": {
        "file": "c6_Science_QB_2026.pdf",
        "standard_id": 39, "standard": 6, "publisher": "nodia",
        "marker": r"(?m)^\s*Ans\b\s*[:.]?\s*",
        "subject_of_part": {1: "Science"},
        "title": "NODIA Class 6 Science Question Bank 2026",
        "textbook": "Curiosity (NEP-2020)",
        # THE ODD FOLIOS SHIP SHUFFLED -- see `_reading_order`.
        "reorder_pages": True,
        # Chapter 1 is an overview of the other eleven and quotes their
        # titles -- see `_page_chapter_head`.
        "attribute_by": "head",
        # A 40-character option column, so most choices run onto a second
        # line -- see `_options_wrapped`.
        "wrapped_options": True,
        # Both running heads, the publisher's mark and the three adverts
        # printed in the page margins. Left in, they run on into any answer
        # that straddles a page break: 74 answers carried "NODIA", 71 a
        # "PAGE nnn CBSE CLASS 6TH SCIENCE CHAPTERWISE QB", and 41 a
        # "Click Here to Buy book on Amazon" mid-sentence.
        "furniture": (r"(?i)^\s*(?:"
                      r"PAGE\s+\d+"
                      r"|CBSE\s+CLASS\s+\d+\s*TH\s+SCIENCE\s+CHAPTERWISE\s+QB"
                      r"|CH\s*\d{1,2}\s*:.*"
                      r"|NODIA"
                      r"|www\.nodia\.in"
                      r"|Click\s+Here\s+to\s+Buy.*"
                      r"|Downloaded\s+from\s+www\.pdf\.tube"
                      r"|Scan\s+QR\s+Code.*"
                      r")\s*$"),
        # THE BOOK IS NOT IN CHAPTER ORDER: pdf page 178 is headed CH 7 and
        # follows a CH 8 page, 203 is CH 8 after CH 9, and 258 is CH 10 after
        # CH 11. A folio offset would also not save it -- the offset runs from
        # +1 at chapter 1 to +31 at chapter 12 because pdf.tube inserts advert
        # blocks (10 pages after folio 6, 11 more after folio 46).
        # Every page here carries EITHER a "CH n : TITLE" running head (148
        # pages) OR a "PAGE n" folio (132 pages), and across the whole book
        # the two never disagree, so title-first with a folio fallback
        # attributes every content page. The remaining 38 are adverts and
        # blanks and hold no answer marker.
        # Titles are the book's own contents wording, which is what the head
        # prints; the database drops the space before the colon in chapters 3
        # and 10, and _squash folds both to the same letters.
        "chapters": [
            (1, 1, "The Wonderful World of Science", 5, 16),
            (1, 2, "Diversity in the Living World", 17, 46),
            (1, 3, "Mindful Eating : A Path to a Healthy Body", 47, 71),
            (1, 4, "Exploring Magnets", 72, 92),
            (1, 5, "Measurement of Length and Motion", 93, 113),
            (1, 6, "Materials Around Us", 114, 134),
            (1, 7, "Temperature and its Measurement", 135, 154),
            (1, 8, "A Journey through States of Water", 155, 174),
            (1, 9, "Methods of Separation in Everyday Life", 175, 197),
            (1, 10, "Living Creatures : Exploring their Characteristics", 198, 222),
            (1, 11, "Nature's Treasures", 223, 246),
            (1, 12, "Beyond Earth", 247, 268),
        ],
    },
    "c6_social": {
        "file": "c6_Social_Science_QB_2026.pdf",
        "standard_id": 39, "standard": 6, "publisher": "nodia",
        "marker": r"(?m)^\s*Ans\b\s*[:.]?\s*",
        "subject_of_part": {1: "Social Sciences"},
        "title": "NODIA Class 6 Social Science Question Bank 2026",
        "textbook": "Exploring Society: India and Beyond (NEP-2020)",
        "chapters": [
            (1, 1, "Locating Places on the Earth", 5, 19),
            (1, 2, "Oceans and Continents", 20, 35),
            (1, 3, "Landforms and Life", 36, 50),
            (1, 4, "Timeline and Sources of History", 51, 67),
            (1, 5, "India, That Is Bharat", 68, 83),
            (1, 6, "The Beginnings of Indian Civilisation", 84, 101),
            (1, 7, "India's Cultural Roots", 102, 119),
            (1, 8, "Unity in Diversity, or 'Many in the One'", 120, 138),
            (1, 9, "Family and Community", 139, 157),
            # The book's own wording, which is what the running header
            # prints. These three share a long prefix, so a short key
            # matches all of them: at 22 characters chapter 10 took one
            # page, 11 took ten, and 12 swallowed 276.
            (1, 10, "Grass roots Democracy Governance", 158, 175),
            (1, 11, "Grass roots Democracy Local Government in Rural Areas", 176, 195),
            (1, 12, "Grass roots Democracy Local Government in Urban Areas", 196, 215),
            (1, 13, "The Value of Work", 216, 233),
            (1, 14, "Economic Activities Around Us", 234, 250),
        ],
    },
    "c10_english": {
        "file": "c10_English_QB_2026.pdf",
        "standard_id": 43, "standard": 10, "publisher": "nodia",
        "marker": r"(?m)^\s*Ans\b\s*[:.]?\s*",
        "subject_of_part": {1: "English"},
        "title": "NODIA Class 10 English Question Bank 2026",
        "textbook": "First Flight",
        # Only Section C, First Flight prose. The Reading, Writing and
        # Grammar sections that open the book are not chapters the
        # database holds, and their own "CHAP 1" would collide.
        "chapters": [
            (1, 1, "A Letter to God", 208, 225),
            (1, 2, "Nelson Mandela - Long Walk to Freedom", 226, 244),
            (1, 3, "Two Stories About Flying", 245, 267),
            (1, 4, "From the Diary of Anne Frank", 268, 285),
            (1, 5, "Glimpses of India", 286, 313),
            (1, 6, "Mijbil the Otter", 314, 331),
            (1, 7, "Madam Rides the Bus", 332, 348),
            (1, 8, "The Sermon at Benares", 349, 363),
            (1, 9, "The Proposal", 364, 381),
        ],
    },
    # THE SAME FILE AS `c10_english`, THE OTHER HALF OF IT. One 644-page PDF
    # holds Reading, Writing, Grammar, First Flight prose, First Flight poetry
    # and the Footprints Without Feet supplementary reader; the prose half is
    # already in the bank as subject "English" and must not be disturbed, so
    # this entry declares its own folio range and its own subject and nothing
    # is shared but the file.
    "c10_english2": {
        "file": "c10_English_QB_2026.pdf",
        "standard_id": 43, "standard": 10, "publisher": "nodia",
        "marker": r"(?m)^\s*Ans\b\s*[:.]?\s*",
        "subject_of_part": {1: "English-2"},
        "title": "NODIA Class 10 English Question Bank 2026",
        "textbook": "Footprints Without Feet",
        # Read from each page's own top margin, with nothing inherited: the
        # supplementary reader and the poetry section interleave page for
        # page. See `_page_chapter_head_strict`.
        "attribute_by": "head_strict",
        # The unnumbered pages ship shuffled -- see `_reading_order_slots`.
        # The printed folios are clean (59 in this span, no inversion), which
        # is exactly why the backbone can place the rest.
        "reorder_pages": "slots",
        # The choices are set in a narrow two-column measure and 185 of the
        # 2,028 option lines run onto a second one.
        "wrapped_options": True,
        # The section headings are Title Case here, not shouted -- see
        # BANNERS_TITLE.
        "title_banners": True,
        # THE SHARED STRIP IS CASE-SENSITIVE AND THIS BOOK SHOUTS. `_blob`
        # tests `^\s*page\s+\d+\s*$` and `"Chapterwise QB" in ln`; the page
        # prints "PAGE  479" and "CBSE CHAPTERWISE QB CLASS 10 ENGLISH", so
        # neither is seen and both run on into whatever answer straddles the
        # page break. In the First Flight half already loaded that is 46
        # answers carrying "NODIA CBSE CHAPTERWISE QB CLASS 10 ENGLISH PAGE
        # 217" mid-sentence, 27 carrying "Click Here to Buy book on Amazon"
        # and 31 "Downloaded from www.pdf.tube".
        #
        # THE YEAR TAG IS SET BARE, on the line after "Ans :" and with no
        # board name to key on -- just "2020", or "2014, 2010", or "2007
        # (DB), 2007 (OD)". `_TAG` wants a CBSE or an NCERT in front of the
        # digits and finds none, so the year becomes the first word of the
        # answer: 780 of the First Flight half's 960 answers begin with one
        # ("2021 (b) top of a hill"). All 710 of them in this half sit
        # directly under an answer marker and nowhere else, so the bare line
        # can be dropped outright.
        "furniture": (r"(?i)^\s*(?:"
                      r"PAGE\s+\d+"
                      r"|CBSE\s+CHAPTERWISE\s+QB\s+CLASS\s+\d+\s+ENGLISH"
                      r"|CH\s*\d{1,2}\s*:.*"
                      r"|NODIA"
                      r"|www\.nodia\.in"
                      r"|Click\s+Here\s+to\s+Buy.*"
                      r"|Downloaded\s+from\s+www\.pdf\.tube"
                      r"|Scan\s+QR\s+Code.*"
                      # The stray full stop in "2015., 2011" is the book's,
                      # and without it that one answer keeps its whole tag.
                      r"|(?:19|20)\d{2}\.?(?:\s*\([A-Za-z.]+\))?"
                      r"(?:\s*[,;]\s*(?:19|20)\d{2}\.?"
                      r"(?:\s*\([A-Za-z.]+\))?)*"
                      r")\s*$"),
        # The folios the CONTENTS gives, which is what the numbered pages
        # print and what places the unnumbered ones. The titles are the
        # book's own running-head wording; chapter 9's differs from the
        # contents only in its capitals, which `_squash` folds away.
        "chapters": [
            (1, 1, "A Triumph of Surgery", 481, 493),
            (1, 2, "The Thief's Story", 494, 506),
            (1, 3, "The Midnight Visitor", 507, 519),
            (1, 4, "A Question of Trust", 520, 530),
            (1, 5, "Footprints without Feet", 531, 543),
            (1, 6, "The Making of a Scientist", 544, 556),
            (1, 7, "The Necklace", 557, 569),
            (1, 8, "Bholi", 570, 583),
            (1, 9, "The Book That Saved The Earth", 584, 596),
        ],
    },
    "c7_science": {
        "file": "c7_Science_QB_2026.pdf",
        "standard_id": 40, "standard": 7, "publisher": "nodia",
        "marker": r"(?m)^\s*Ans\b\s*[:.]?\s*",
        "subject_of_part": {1: "Science"},
        "title": "NODIA Class 7 Science Question Bank 2026",
        "textbook": "Curiosity (NEP-2020)",
        # The book's own contents wording, which is what the running header
        # prints. Chapter 11 is "Light - Shadows and Reflections" in the
        # database and "Light - Shadows and Re(fl)ections" in the text layer,
        # where the fl is a single ligature glyph that squashes away; the key
        # shortens past it.
        "chapters": [
            (1, 1, "The Ever-Evolving World of Science", 5, 11),
            (1, 2, "Exploring Substances : Acidic, Basic and Neutral", 12, 34),
            (1, 3, "Electricity Circuits and their Components", 35, 64),
            (1, 4, "The World of Metals and Non-metals", 65, 89),
            (1, 5, "Changes Around Us Physical and Chemical", 90, 114),
            (1, 6, "Adolescence A Stage of Growth and Change", 115, 137),
            (1, 7, "Heat Transfer in Nature", 138, 162),
            (1, 8, "Measurement of Time and Motion", 163, 185),
            (1, 9, "Life Processes in Animals", 186, 207),
            (1, 10, "Life Processes in Plants", 208, 233),
            (1, 11, "Light Shadows and Reflections", 234, 261),
            (1, 12, "Earth, Moon and the Sun", 262, 284),
        ],
    },
    "c7_social": {
        "file": "c7_Social_Science_QB_2026.pdf",
        "standard_id": 40, "standard": 7, "publisher": "nodia",
        "marker": r"(?m)^\s*A?Ans\b\s*",
        "subject_of_part": {1: "Social Sciences", 2: "Social Sciences-2"},
        "title": "NODIA Class 7 Social Science Question Bank 2026",
        "textbook": "Exploring Society: India and Beyond (NEP-2020)",
        "chapters": [
            (1, 1, "Geographical Diversity of India", 7, 30),
            (1, 2, "Understanding the Weather", 31, 54),
            (1, 3, "Climates of India", 55, 80),
            (1, 4, "New Beginnings: Cities and States", 81, 104),
            (1, 5, "The Rise of Empires", 105, 129),
            (1, 6, "The Age of Reorganisation", 130, 155),
            (1, 7, "The Gupta Era: An Age of Tireless Creativity", 156, 180),
            (1, 8, "How the Land Becomes Sacred", 181, 205),
            (1, 9, "From the Rulers to the Ruled: Types of Governments", 206, 230),
            (1, 10, "The Constitution of India: An Introduction", 231, 256),
            (1, 11, "From Barter to Money", 257, 281),
            (1, 12, "Understanding Markets", 282, 306),
            (2, 1, "The Story of Indian Farming", 307, 331),
            (2, 2, "India and Her Neighbours", 332, 352),
            (2, 3, "Empires and Kingdoms: 6th to 10th Centuries", 353, 377),
            (2, 4, "Turning Tides: 11th and 12th Centuries", 378, 401),
            (2, 5, "India, a Home to Many", 402, 425),
            (2, 6, "The State, the Government, and You", 426, 451),
            (2, 7, "Infrastructure: Engine of India's Development", 452, 478),
            (2, 8, "Banks and the Magic of Finance", 479, 503),
        ],
    },
}

_QSTART = re.compile(r"(?m)^[ \t]*(\d{1,3})\s*\.\s*(?=\S|$)")
_OPT_LINE = re.compile(r"(?m)^[ \t]*\(\s*([A-Da-d])\s*\)[ \t]*(.+?)[ \t]*$")
_OPT_ANY = re.compile(r"\(\s*([A-Da-d])\s*\)\s*([^()]{1,200}?)(?=\s*\(\s*[A-Da-d]\s*\)|\s*$)")
_LEAD = re.compile(r"(?i)^\s*\(?\s*([A-Da-d])\s*\)?[.\s]*")

BANNERS = [
    ("MULTIPLECHOICE", "mcq"), ("ASSERTIONREASON", "assertion_reason"),
    ("CASESTUDY", "case_study"), ("CASEBASED", "case_study"),
    ("VERYSHORT", "very_short"), ("SHORTANSWER", "short"),
    ("LONGANSWER", "long"), ("NCERTEXERCIS", "short"),
    ("COMPETENCYBASED", "short"),
]

# The same headings in the Hindi books, which `BANNERS` cannot reach because
# `_is_banner` asks for capitals and Devanagari has no case -- so every Hindi
# question in the estate is filed as "short" whatever the page says.
#
# THEY ARE LETTER-SPACED AND THE SPACING SURVIVES CONVERSION. The page prints
# "दीघ र् उत्तर ीय प्रश्" for दीर्घ उत्तरीय प्रश्न and "अि त ल? ाु उत्त रीय
# प्रश्" for अति लघु उत्तरीय, so these are matched with the spacing squashed
# out and against the mangled form as well as the clean one. LONGEST FIRST:
# अतिलघु contains लघु, and checked the other way round every very-short
# section is filed as short.
BANNERS_HI = [
    ("बहुविकल्प", "mcq"),
    ("अितलाुउत्तरीय", "very_short"), ("अतिलघुउत्तरीय", "very_short"),
    ("दीघर्उत्तरीय", "long"), ("दीर्घउत्तरीय", "long"),
    ("लघुउत्तरीय", "short"), ("लाुउत्तरीय", "short"),
    ("गद्यांशोंपरआधारित", "case_study"), ("निम्नलिखितगद्यांश", "case_study"),
    ("काव्यांशोंपरआधारित", "case_study"), ("निम्नलिखितकाव्यांश", "case_study"),
    ("पाठ्यपुस्तकके", "short"), ("अन्यमहत्वपूर्ण", "short"),
    ("रचनाऔरअभिव्यक्ति", "short"),
]


def _squash(s: str) -> str:
    """Fold to comparable letters, KEEPING Devanagari.

    A-Z only turns every Hindi chapter title into the empty string, so no
    page can be attributed by title and the book falls back to a folio
    header these particular ones do not print in Latin.
    """
    return re.sub(r"[^A-Zऀ-ॿ]", "", (s or "").upper())


def _norm(t: str) -> str:
    """Fold to comparable characters, KEEPING non-Latin scripts.

    An ASCII-only class silently erases Devanagari: every Hindi stem folds to
    the empty string, so the dedupe sees one question repeated and the answer
    key never matches its option. Class 9 Hindi lost 599 of 1,180 items to a
    "printed twice" that was really "both normalised to nothing".
    """
    return re.sub(r"[^0-9a-zऀ-ॿঀ-৿਀-੿]", "",
                  (t or "").lower())


def _is_ad(text: str, content=None) -> bool:
    """A pdf.tube advertisement page, as opposed to a page of the book.

    "Ans" IS AN ENGLISH BOOK'S ANSWER MARKER AND NOTHING ELSE. Every page
    of these files carries a pdf.tube footer, so the footer alone cannot
    decide; what separates an advertisement from a chapter page is that the
    chapter page answers something. Keyed on the Latin word, a Hindi book
    has no page that answers anything -- its marker is उत्तर -- and every
    content page bearing the footer is dropped as an advertisement. On
    Class 10 Hindi-B that is 161 pages flagged, 119 of them holding real
    questions, lost with no failure to see.

    So the caller passes `content`: a predicate that is true of a page
    holding this book's own marker or question numbering. The real
    advertisements ("CBSE CLASS 12 ... Order the Hard copy from Amazon")
    hold neither and are still dropped.
    """
    if "pdf.tube" not in text:
        return False
    if content is not None:
        return not content(text)
    return "Ans" not in text


# "उत्तर ः", which the page letter-spaces to "उत्त र ः". It opens an answer,
# never a section, and is short enough to be taken for a heading.
_ANSWER_HI = re.compile(r"^\s*उत्त\s*र\s*[%:।ः]?\s*$")


# THE SAME HEADINGS SET IN TITLE CASE, which `BANNERS` cannot reach because
# `_is_banner` asks for 75% capitals. Class 10 English prints "Multiple Choice
# Type Questions" and "Long Answer Type Questions", not the shouted form its
# siblings use, so every question in the book is filed as "short" whatever the
# page says: the First Flight half already in the bank holds 558 "short" and
# not one "long" or "case_study".
#
# MATCHED ON THE WHOLE LINE, not as a substring. The shared list tests
# containment, which is safe for a shouted heading because prose is not
# shouted; these are ordinary Title Case and a sentence that merely mentions
# "the long answer type questions below" would re-type everything after it.
# A book opts in through `title_banners`, so no loaded book changes.
BANNERS_TITLE = [
    ("MULTIPLECHOICETYPEQUESTIONS", "mcq"),
    ("ASSERTIONREASONQUESTIONS", "assertion_reason"),
    ("VERYSHORTANSWERTYPEQUESTIONS", "very_short"),
    ("SHORTANSWERTYPEQUESTIONS", "short"),
    ("LONGANSWERTYPEQUESTIONS", "long"),
    ("EXTRACTBASEDQUESTIONS", "case_study"),
    ("CASEBASEDQUESTIONS", "case_study"),
    ("NCERTTEXTBOOKQUESTIONS", "short"),
    ("OTHERIMPORTANTQUESTIONS", "short"),
]


def _is_banner(line: str, extra: list | None = None) -> str:
    s = line.strip().lstrip(QMARK).strip()
    if not (6 <= len(s) <= 58):
        return ""
    sq = _squash(s)
    # A Devanagari heading, which has no case to test. Checked before the
    # capitals rule, which no Hindi line can ever pass.
    if any("ऀ" <= c <= "ॿ" for c in s):
        # An answer or a stem is not a heading, however short it is.
        if _ANSWER_HI.match(s):
            return ""
        for key, f in BANNERS_HI:
            if key in sq:
                return f
        return ""
    # Title Case headings, matched whole. Checked before the capitals rule so
    # that a numbered one -- "6. NCERT TEXTBOOK QUESTIONS" -- is read here
    # rather than falling through to a containment test that misses it.
    if extra:
        for key, f in extra:
            if sq == key:
                return f
    letters = [c for c in s if c.isalpha()]
    if not letters or sum(c.isupper() for c in letters) / len(letters) < 0.75:
        return ""
    for key, f in BANNERS:
        if key in sq:
            return f
    return "skip" if "MATCHINGTYPE" in sq else ""


def _form_at(body: str, pos: int, default: str = "short",
             extra: list | None = None) -> str:
    form = default
    for line in body[:pos].splitlines():
        f = _is_banner(line, extra)
        if f:
            form = f
    return form


def _label_set(cfg) -> tuple[str, dict]:
    """The option letters this book prints, and how they map to A-D.

    Hindi marks its choices (क)(ख)(ग)(घ), not (A)(B)(C)(D) -- 6,000 of
    them in Class 9 Hindi R-1. Matched only against Latin letters, every
    multiple-choice question in the book reads as a plain short answer.
    `answer_master` stores option ORDER and a correct flag, never the
    printed letter, so folding to A-D loses nothing.
    """
    labs = cfg.get("option_labels") or "ABCD"
    table = {}
    for i, ch in enumerate(labs):
        table[ch] = "ABCD"[i]
        table[ch.lower()] = "ABCD"[i]
    return "".join(sorted(set(labs + labs.lower()))), table


def _options(block: str, labs: str = "A-Da-d", table: dict | None = None) -> list[dict]:
    table = table or {}
    line_re = re.compile(rf"(?m)^[ 	]*\(\s*([{labs}])\s*\)[ 	]*(.+?)[ 	]*$")
    any_re = re.compile(rf"\(\s*([{labs}])\s*\)\s*([^()]{{1,200}}?)"
                        rf"(?=\s*\(\s*[{labs}]\s*\)|\s*$)")
    opts: dict[str, str] = {}
    for m in line_re.finditer(block):
        lab = table.get(m.group(1), m.group(1).upper())
        txt = " ".join(m.group(2).split()).strip(" .,;")
        if txt and lab not in opts:
            opts[lab] = txt[:240]
    if sorted(opts) != ["A", "B", "C", "D"]:
        opts = {}
        for lab0, txt in any_re.findall(" ".join(block.split())):
            lab = table.get(lab0, lab0.upper())
            txt = " ".join(txt.split()).strip(" .,;")
            if txt and lab not in opts:
                opts[lab] = txt[:240]
    return ([{"label": k, "text": opts[k]} for k in sorted(opts)]
            if sorted(opts) == ["A", "B", "C", "D"] else [])


def _options_wrapped(block: str, labs: str = "A-Da-d",
                     table: dict | None = None) -> tuple[list[dict], set]:
    """Options that WRAP onto the following line, and the lines they use up.

    `_options` reads an option as one line, which is right for a book that
    prints each choice on its own line and wrong for a narrow two-column one.
    Class 6 Science sets its choices in a 40-character column, so most of them
    run on:

        (C) A way of thinking, observing, and doing
        things to understand the world.

    Read line by line, option C is "A way of thinking, observing, and doing"
    and the rest is not an option line, so it stays behind and is swept into
    the stem -- which then reads "What is science? about the universe. any
    specific questions. things to understand the world.", the tails of three
    choices stuck to the question. 455 of the 570 measurable keys were cut
    short this way and 276 stems polluted, and every one of them loads: the
    key still matches, because it matches on a prefix.

    So a line that does not open a new choice continues the one before it, and
    the caller is told which lines were consumed so it can keep them out of the
    stem. Nothing is appended before the first choice, and nothing after the
    block's four are complete -- otherwise a two-column page that prints the
    next question beside the options would append that question to (D).
    """
    table = table or {}
    line_re = re.compile(rf"^[ \t]*\(\s*([{labs}])\s*\)[ \t]*(.*?)[ \t]*$")
    opts: dict[str, str] = {}
    used: set[int] = set()
    cur: str | None = None
    for idx, ln in enumerate(block.splitlines()):
        m = line_re.match(ln)
        if m:
            lab = table.get(m.group(1), m.group(1).upper())
            if lab in opts:
                cur = None
                continue
            opts[lab] = " ".join(m.group(2).split())
            used.add(idx)
            cur = lab
        elif cur and ln.strip() and sorted(opts) != ["A", "B", "C", "D"]:
            opts[cur] = (opts[cur] + " " + " ".join(ln.split())).strip()
            used.add(idx)
        elif cur and ln.strip() and cur == "D":
            # (D) is last, so its own run-on is the only thing that can
            # follow a complete set -- but only until the line after it.
            opts[cur] = (opts[cur] + " " + " ".join(ln.split())).strip()
            used.add(idx)
            cur = None
    out = {k: v.strip(" .,;")[:240] for k, v in opts.items() if v.strip(" .,;")}
    if sorted(out) != ["A", "B", "C", "D"]:
        return [], set()
    return [{"label": k, "text": out[k]} for k in sorted(out)], used


def _key(opts: list[dict], answer: str, lead_re=None, table=None) -> str:
    if not opts:
        return ""
    lead_re = lead_re or _LEAD
    table = table or {}
    body = _norm(lead_re.sub("", answer)[:120])
    hit = [o["label"] for o in opts if _norm(o["text"]) and _norm(o["text"])[:40] in body]
    if len(hit) == 1:
        return hit[0]
    m = lead_re.match(answer)
    lab = table.get(m.group(1), m.group(1).upper()) if m else ""
    return lab if lab in {o["label"] for o in opts} else ""


# "page N" in the English books; "पृष्ठ N" once a Hindi one is
# transliterated.
_FOLIO = re.compile("(?im)^\s*(?:page|पृष्ठ)\s+(\d{1,4})\s*$")


def _folio_map(doc, seed: int) -> list:
    """printed folio -> PDF page index, read from each page's own header.

    THERE IS NO CONSTANT OFFSET. pdf.tube inserts advertisement pages into
    the PDF that the printed numbering knows nothing about, so the gap grows
    as you go: in Class 6 Social Science chapter 1 begins at folio 5 on PDF
    page 21, and chapter 2 at folio 20 on PDF page 32 -- +16 and +12, which
    no single offset reconciles. Measured as a constant, chapter 1 returned
    13 items against 88 to 129 in its siblings.

    Every content page states its own folio in the running header ("PAGE 6"),
    so the mapping is read rather than computed.

    THE HEADER IS NOT ON EVERY PAGE -- only 248 of Class 7's 547 carry a
    readable one. So the folios that ARE read are used as anchors and carried
    forward: a page with no header belongs to the last folio seen before it.
    Keyed on readable headers alone, more than half the book is dropped and
    the Class 7 total falls from 2,545 to 1,210.

    Returns one entry per PDF page: the folio it belongs to, or None before
    the first header is seen.
    """
    out: list[int | None] = []
    # Seeded with the first chapter's opening folio so that its pages, which
    # precede the book's first readable header, are not orphaned. Front
    # matter is swept in with them and costs nothing: a cover or a contents
    # page carries no answer marker and so yields no item.
    last: int | None = seed
    for i in range(doc.page_count):
        try:
            head = "\n".join((doc[i].get_text() or "").splitlines()[:4])
        except Exception:
            head = ""
        m = _FOLIO.search(head)
        if m:
            last = int(m.group(1))
        out.append(last)
    return out


def _page_text(doc, i: int, tl: bool) -> str:
    """One page's text, transliterated first where the book is legacy-set."""
    try:
        raw = doc[i].get_text() or ""
    except Exception:
        return ""
    return _devlys(raw) if tl else raw


# --- the span-aware reader, for books set in more than one legacy font ----
#
# Two column origins, in points, measured off the page and not assumed.
_COLS = (45.0, 297.0)
_COL_SPLIT = 290.0          # anything left of this is the left-hand column
_HANG = 4.0                 # how close to a column origin a line must start
# Marks a line that HANGS at a column origin, which is how this family sets a
# question number. Answer sub-points are indented 18pt and are not marked.
#
# IT MUST NOT BE A CHARACTER `str.splitlines()` BREAKS ON. That method splits
# on \x0b \x0c \x1c \x1d \x1e and \x85 as well as newline, so the obvious
# choice of \x1d GROUP SEPARATOR is silently eaten the first time the page is
# split into lines: every marked line becomes two, the marker vanishes, and
# the book parses to nothing with no error anywhere. \x1f is not a boundary.
QMARK = "\x1f"
# A DECORATIVE GLYPH SITS AT U+0001 AND PRECEDES EVERY ANSWER MARKER.
# It is not whitespace, so "^\s*उत्तर" does not match the line it opens:
# left in, 119 of Class 10 Hindi-A's 123 answer markers are invisible and
# the book parses to nothing at all, with no error and no dropped-item
# count to show for it. Stripped here rather than in the marker, because
# it is equally in the way of the option labels and the question numbers.
# \x85,   and   go with them: `str.splitlines()` breaks on all
# three, so one left in a span silently splits a question across two lines.
_CTRL = re.compile("[\x00-\x08\x0b-\x1f\x7f\x85  ]")
# Stands in for a span in a legacy font there is no table for. Whatever else
# happens to it downstream, an item holding one of these is never loaded.
BAD = "�"


def _span_text(sp) -> str:
    """One span, read with ITS OWN font rather than the page's dominant one.

    A page here is not in one encoding. Folio 173 of Class 10 Hindi-A sets
    questions 24 to 31 in DevLys-010 and question 32 in SHREE-DEV7-0714E,
    and there is no SHREE table -- run through the DevLys one it yields
    "र्वटउव्त H$े श्लक्ष्ट©", which is Devanagari-shaped and meaningless.
    Skipping the whole page would also throw away questions 24 to 31, so
    the bad spans are marked instead and the items holding them dropped.

    DIGITS ARE NOT AFFECTED. Both fonts encode 0-9 and ASCII punctuation as
    themselves, and the question NUMBER is set in SHREE bold throughout, so
    a SHREE span of digits and punctuation is kept as it stands.

    A SHREE SPAN OF ASCII *LETTERS* IS NOT ENGLISH. "H$s{OE&" is कीजिए and
    "nmR> Ho$ AmYma na ~VmBE" is पाठ के आधार पर बताइए -- the encoding puts
    Devanagari on the Latin letters, so a plain `isascii()` test keeps them
    and they land mid-sentence inside otherwise good Hindi: 147 spans in a
    one-page-in-three sample, every one of them nonsense.
    """
    fn = sp.get("font") or ""
    t = _CTRL.sub("", sp.get("text") or "")
    if "DevLys" in fn or "KrutiDev" in fn:
        return _devlys(t)
    if "SHREE" in fn:
        return t if t.isascii() and not any(c.isalpha() for c in t) else BAD
    return t


# THE NOTES HEADINGS ARE NUMBERED TOO, and they hang at the column edge
# exactly as the questions do: "1- लेखक परिचय", "3- पाठ का सार". What tells
# them apart is the face -- the headings are set in DevLys-090Wide and the
# questions in DevLys-010 or SHREE bold. Taken for questions, each one
# truncates the answer above it and then claims that answer as its own.
_NOTE_FACE = "090Wide"
# Below this the page carries only the seller's footer; the last line of the
# right-hand column sits at about 738 on a full page.
_FOOT_Y = 750.0


def _page_text_spans(doc, i: int) -> str:
    """One page in COLUMN reading order, each span read by its own font.

    THE PAGE IS SET IN TWO COLUMNS and the reading order is not the y order:
    taken top to bottom the left column's question 8 is followed by the right
    column's question 12, and a question can land inside another question's
    options. Lines are therefore bucketed by column first and sorted within
    it -- see [[qbank-two-column-scatters-sections]].
    """
    try:
        d = doc[i].get_text("dict")
    except Exception:
        return ""
    lines = []
    for b in d.get("blocks", []):
        if b.get("type") != 0:
            continue
        for ln in b.get("lines", []):
            spans = ln.get("spans", [])
            if not spans:
                continue
            x, y = ln["bbox"][0], ln["bbox"][1]
            # THE SELLER'S FOOTER IS NOT PART OF THE ANSWER. "Downloaded from
            # www.pdf.tube" and "Click Here to Buy book on Flipkart" sit at
            # y=769, below every column, and in reading order they fall
            # inside whichever answer was running when the page ended: 311
            # stray Latin letters across the book, inside Hindi sentences.
            if y > _FOOT_Y:
                continue
            txt = "".join(_span_text(sp) for sp in spans)
            if not txt.strip():
                continue
            hang = (any(abs(x - c) < _HANG for c in _COLS)
                    and _NOTE_FACE not in (spans[0].get("font") or ""))
            lines.append((0 if x < _COL_SPLIT else 1, round(y, 1), x,
                          (QMARK if hang else "") + txt))
    lines.sort(key=lambda t: t[:3])
    return "\n".join(t[3] for t in lines)


_WORD_HI = re.compile(r"[ऀ-ॿ]{3,}")


def _content_owner(pages: list[str], banner: list[str], margin: float = 2.0,
                   window: int = 4):
    """Attribute the pages that carry no header, on their own words.

    HALF THE BOOK HAS NO HEADER TO READ. Only the recto pages name their
    chapter; the verso pages print "पृष्ठ N" and the book's title. Carrying
    the last name forward is wrong here, because the file interleaves: folio
    148 is अलंकार, folio 149 नेताजी का चश्मा, folio 150 अलंकार again, so a
    carried name crosses into the next section roughly as often as not.

    What each page does carry is its own subject matter, and these are
    literature chapters about named texts -- हालदार and चश्मा, बालगोबिन and
    भगत, उद्धव and गोपी. So a vocabulary is harvested from the pages that DO
    name their chapter, weighted towards words peculiar to one of them, and
    every other page is scored against it.

    A PAGE IS LEFT UNATTRIBUTED UNLESS ONE SECTION CLEARLY WINS. Measured
    leave-one-out against the 235 pages whose true section is printed on
    them, a 2x margin decided 175 and got 175 right; at 1.3x it decided 212
    and got four wrong. A page in the wrong chapter is worse than a page in
    none, so the margin is set where the measurement was clean.

    AND ONLY AGAINST THE SECTIONS PRINTED NEAR IT. The words alone will
    reach across the whole book: a passage set in the अपठित गद्यांश section
    at folio 19 is taken verbatim from नेताजी का चश्मा, and on its
    vocabulary it wins that chapter outright 150 folios early. A page may
    therefore only join a section whose own header appears within `window`
    pages of it, which is where the interleaving happens and nowhere else.
    """
    vocab: dict[str, Counter] = {}
    for i, b in enumerate(banner):
        if b:
            vocab.setdefault(b, Counter()).update(_WORD_HI.findall(pages[i]))
    if not vocab:
        return [None] * len(pages), (0, 0)
    df: Counter = Counter()
    for v in vocab.values():
        df.update(set(v))
    n = len(vocab)

    def near(i: int) -> set[str]:
        """The sections whose own header is printed within `window` pages."""
        return {banner[j] for j in range(max(0, i - window),
                                         min(len(banner), i + window + 1))
                if banner[j]}

    def rank(text: str, at: int, without: int | None = None):
        """Section scores for one page. `without` removes that page's own
        words from its section first, so a page cannot vouch for itself."""
        t = Counter(_WORD_HI.findall(text))
        held = (Counter(_WORD_HI.findall(pages[without]))
                if without is not None else Counter())
        here = near(at)
        out = []
        for s, v in vocab.items():
            if s not in here:
                continue
            if without is not None and banner[without] == s:
                v = v - held
            out.append((sum(min(c, 3) * (n / df[w])
                            for w, c in t.items() if v.get(w)), s))
        out.sort(reverse=True)
        return out

    def decide(r):
        if not r or r[0][0] <= 0:
            return None
        runner = r[1][0] if len(r) > 1 else 0.0
        return r[0][1] if r[0][0] >= margin * max(runner, 1e-9) else None

    # The same rule applied to the pages whose answer is printed on them, so
    # the run reports its own accuracy instead of asking to be trusted.
    ok = bad = 0
    for i, b in enumerate(banner):
        if not b or not pages[i].strip():
            continue
        # `without=i` takes this page's own words out of its section's
        # vocabulary, so it cannot vouch for itself. The window is left as
        # it is: a headerless page has its own section in its window too,
        # for the same reason -- the two kinds of page alternate.
        got = decide(rank(pages[i], at=i, without=i))
        if got is None:
            continue
        ok += got == b
        bad += got != b

    out: list[str | None] = []
    for i, b in enumerate(banner):
        if b or not pages[i].strip():
            out.append(None)
            continue
        out.append(decide(rank(pages[i], at=i)))
    return out, (ok, bad)


# The running header, which prints "अध्याय N ः <नाम>" on every recto page.
_HEAD_Y = 60.0              # the header band; below it is the page's body
_BANNER_HI = re.compile(r"अध्याय\s*(\d{1,3})\s*[ः:%]\s*(.+)")


def _page_banner(doc, i: int) -> str:
    """The chapter name in this page's RUNNING HEADER, or "".

    Read from the header band alone. Searched over the whole page it also
    finds the contents, which lists every chapter in the book and would
    attribute the front matter to whichever one it named last.
    """
    try:
        d = doc[i].get_text("dict")
    except Exception:
        return ""
    found = ""
    for b in d.get("blocks", []):
        if b.get("type") != 0:
            continue
        for ln in b.get("lines", []):
            if ln["bbox"][1] >= _HEAD_Y:
                continue
            txt = _devlys("".join(sp.get("text", "") for sp in ln.get("spans", [])))
            m = _BANNER_HI.search(txt)
            if m:
                found = " ".join(m.group(2).split())
    return found


def _page_chapter_banner(doc, cfg) -> tuple[list, dict]:
    """Attribute every page on the chapter name its own header prints.

    THE BOOK INTERLEAVES. Folio 175 opens बालगोबिन भगत and folio 177 is
    still नेताजी का चश्मा question 41; folio 195 is लखनवी अंदाज and folio
    197 is back in बालगोबिन भगत. A contiguous folio range therefore hands
    one chapter's questions to its neighbour, silently and with no failure
    to see -- [[pdftube-no-constant-folio-offset]].

    ONLY THE RECTO PAGES CARRY THE CHAPTER NAME; the verso pages print
    "पृष्ठ N" and the book's title instead. THE LAST NAME IS NOT CARRIED
    FORWARD INTO THEM. It looks safe on a stretch of one chapter and is
    wrong wherever the file interleaves: folio 148 is अलंकार, folio 149 is
    नेताजी का चश्मा and folio 150 is अलंकार again, so the name carried into
    folio 150 is the wrong one. Those pages are attributed on their own
    words instead, by `_content_owner`, and left out where the words do not
    decide.

    A header naming a section the database does not hold -- अपठित, व्याकरण,
    रचनात्मक लेखन, कृतिका -- is recorded like any other, so that its pages
    are scored against it and cannot be mistaken for a chapter we do hold.
    """
    want = {_squash(v): (1, k) for k, v in (cfg.get("banner_of") or {}).items()}
    pages = [_page_text_spans(doc, i) for i in range(doc.page_count)]
    banner = [_page_banner(doc, i) for i in range(doc.page_count)]
    guessed, (ok, bad) = _content_owner(pages, banner)

    out: list = []
    seen: dict[str, int] = {}
    named = 0
    for i in range(doc.page_count):
        if banner[i]:
            seen[banner[i]] = seen.get(banner[i], 0) + 1
            named += 1
        name = banner[i] or guessed[i] or ""
        out.append(want.get(_squash(name)) if name else None)
    return out, {"headers": seen, "named_pages": named,
                 "by_words": sum(1 for g in guessed if g),
                 "holdout_ok": ok, "holdout_bad": bad}


# The running head an odd folio prints: "CH 8 : A JOURNEY THROUGH STATES OF
# WATER". Anchored, and with the colon required, so the contents' "CHAP 1."
# cannot match it.
_HEAD_CH = re.compile(r"(?im)^\s*CH\s*(\d{1,2})\s*:")


def _page_chapter_head(doc, chapters) -> list[tuple[int, int] | None]:
    """Attribute every page on its RUNNING HEAD ALONE, folio first.

    `_page_chapter` looks for a chapter title anywhere on the page, which is
    right for a book whose head abbreviates but wrong for one whose FIRST
    CHAPTER IS ABOUT THE OTHER CHAPTERS. Class 6 Science opens with "The
    Wonderful World of Science", whose summary runs through what the book will
    cover -- "there are many different materials like paper, metal, plastic" --
    and whose exercise asks the reader to match a topic to a chapter. So folio
    10, which is question 21 of chapter 1, contains the exact letters of
    "Materials Around Us" and nothing else, and was attributed to chapter 6;
    folio 12 likewise went to chapter 12 on "Beyond Earth". Those are the two
    shortest titles in the book, 17 and 11 letters, and no shortening rule can
    help: they are already printed in full.

    Here every page states its own place in its top margin and the two never
    disagree across the book -- an even folio prints "PAGE n" and an odd one
    "CH n : TITLE" -- so the head is read and the body ignored:

      a printed folio decides, through the contents' chapter ranges;
      else the head's own "CH n :" decides, checked against that chapter's
      title so a renumbering cannot pass unnoticed;
      else the page inherits the one before it (adverts and blanks).

    THE NUMBER IS READ, NOT THE TITLE ALONE. The CONTENTS page opens "CONTENTS
    / CHAP 1. / The Wonderful World of Science / 5-16", so its first lines
    contain chapter 1's title exactly and nothing else -- matched on the title
    it joins chapter 1, and being a page with no question numbers it then takes
    the chapter's first folio and pushes every real page one slot late.
    "CHAP 1." does not match `CH\\s*\\d\\s*:`, and the running head does.
    """
    by_number = {c[1]: (c[0], c[1]) for c in chapters}
    title_of = {c[1]: _squash(c[2]) for c in chapters}
    out: list[tuple[int, int] | None] = []
    last: tuple[int, int] | None = None
    for i in range(doc.page_count):
        head = "\n".join((doc[i].get_text() or "").splitlines()[:4])
        m = _FOLIO.search(head)
        if m:
            f = int(m.group(1))
            own = [(c[0], c[1]) for c in chapters if c[3] <= f <= c[4]]
            last = own[0] if len(own) == 1 else last
        else:
            h = _HEAD_CH.search(head)
            if h and int(h.group(1)) in by_number:
                n = int(h.group(1))
                if title_of[n] and title_of[n] in _squash(head):
                    last = by_number[n]
        out.append(last)
    return out


# The same running head read for its TITLE as well as its number.
_HEAD_CH_T = re.compile(r"(?im)^\s*CH\s*(\d{1,2})\s*:\s*(.+?)\s*$")


def _page_chapter_head_strict(doc, chapters) -> list[tuple[int, int] | None]:
    """Attribute a page ONLY on what that page itself prints, never inherited.

    For a section that shares its PDF with other sections. Class 10 English is
    one file holding Reading, Writing, Grammar, First Flight prose, First
    Flight poetry and the Footprints supplementary reader, and only the last
    is wanted here. Every content page states its place in its top margin --
    an odd folio prints "PAGE n", an even one "CH n : TITLE" -- and across
    pages 520-642 not one content page prints neither.

    `_page_chapter_head` CARRIES THE LAST CHAPTER FORWARD, which is right for
    a book that is entirely ours and wrong for a section of one. The poetry
    chapters interleave with the supplementary reader page for page: pdf 520
    is headed "CH 1 : A Triumph of Surgery" and pdf 521 is folio 479, which is
    still For Anne Gregory. Inherited, folio 479 joins A Triumph of Surgery
    and takes a poem's questions into a prose chapter. So nothing is
    inherited: a page we cannot place is left out.

    THE NUMBER ALONE IS NOT ENOUGH, because each section restarts at CH 1. The
    poetry section has its own "CH 5 : The Ball Poem" and "CH 9 : The Tale of
    Custard the Dragon", so the printed TITLE has to agree as well -- matched
    whole, not as a prefix, and folded through `_squash` so that "The Book
    that Saved the Earth" and "The Book That Saved The Earth" are one name.
    """
    by_number = {c[1]: (c[0], c[1]) for c in chapters}
    title_of = {c[1]: _squash(c[2]) for c in chapters}
    out: list[tuple[int, int] | None] = []
    for i in range(doc.page_count):
        head = "\n".join((doc[i].get_text() or "").splitlines()[:4])
        m = _FOLIO.search(head)
        h = _HEAD_CH_T.search(head)
        if m:
            f = int(m.group(1))
            own = [(c[0], c[1]) for c in chapters if c[3] <= f <= c[4]]
            out.append(own[0] if len(own) == 1 else None)
        elif h and int(h.group(1)) in by_number:
            n = int(h.group(1))
            t = _squash(h.group(2))
            out.append(by_number[n] if t and t == title_of[n] else None)
        else:
            out.append(None)
    return out


# --- placing the pages the file ships out of order ------------------------
_OPT_START = re.compile(r"^\(\s*[A-Da-d]\s*\)")
_ANS_START = re.compile(r"^Ans\b\s*[:.]?\s*$|^Ans\b\s*[:.]")
_QN_START = re.compile(r"^(\d{1,3})\.\s")
_SEC_HEAD = re.compile(r"^(\d{1,2})\.\s+[A-Z][A-Z' &\-]{3,40}$")
_SENT_END = re.compile("[.?!:;][\"')’”]?$")
_SENT_CONT = re.compile("^[a-z’'(,;]")


class _Flow:
    """The few features of a page that say what may follow it."""

    __slots__ = ("head", "tail", "firstq", "lastq", "pending", "opens_ans",
                 "secs")

    def __init__(self, lines: list[str]):
        self.head = lines[0] if lines else ""
        self.tail = lines[-1] if lines else ""
        qs = [(k, int(m.group(1))) for k, ln in enumerate(lines)
              if (m := _QN_START.match(ln)) and not _SEC_HEAD.match(ln)]
        self.firstq = qs[0][1] if qs else None
        self.lastq = qs[-1][1] if qs else None
        last_ans = max((k for k, ln in enumerate(lines)
                        if _ANS_START.match(ln)), default=-1)
        self.pending = any(k > last_ans for k, _ in qs)
        self.opens_ans = bool(lines and _ANS_START.match(lines[0]))
        self.secs = [int(m.group(1)) for ln in lines
                     if (m := _SEC_HEAD.match(ln))]


def _flow(a: "_Flow", b: "_Flow") -> float:
    """How well page b reads as the page after page a.

    Four independent signals, each learned from a boundary this book actually
    prints. None of them is decisive alone and the sentence test is the
    weakest: "Her queries were whether" is followed by "Tricki's cushions were
    being turned regularly", a perfect continuation whose next word is a
    capitalised name, so an open sentence meeting a capital is penalised only
    lightly and the question numbering is what usually decides.
    """
    s = 0.0
    if a.tail and b.head:
        a_open = not _SENT_END.search(a.tail)
        b_cont = bool(_SENT_CONT.match(b.head))
        if a_open and b_cont:
            s += 3
        elif not a_open and not b_cont:
            s += 1
        else:
            s -= 3
    if a.lastq is not None and b.firstq is not None:
        d = b.firstq - a.lastq
        if d == 1:                      # question n, then question n+1
            s += 5
        elif d == 0:                    # one question spread over the break
            s += 1
        elif d < 0:                     # a section restarting is possible
            s -= 2
        else:
            s -= 1
    if a.pending and b.opens_ans:       # the question's answer is overleaf
        s += 4
    elif a.pending or b.opens_ans:
        s -= 2
    if a.secs and b.secs:
        s += 2 if b.secs[0] == a.secs[-1] + 1 else -1
    return s


def _flow_lines(raw: str) -> list[str]:
    """The page's own words, with the running heads and the seller's footer
    taken out -- they are the same on every page and would drown the signal."""
    out = []
    for ln in raw.splitlines():
        s = " ".join(ln.split())
        if not s or s == "NODIA" or "CHAPTERWISE QB" in s:
            continue
        if _FOLIO.match(s) or _HEAD_CH_T.match(s):
            continue
        if s.startswith("Click Here to Buy") or s.startswith("Downloaded from"):
            continue
        out.append(s)
    return out


# 8! is 40,320 orderings, which is a second; 9! is nine seconds and 12! is a
# week. No chapter of this book has more than seven pages to place, and a book
# that did would fall back rather than hang.
_PERM_CAP = 8


def _reading_order_slots(doc, chapters, owner) -> dict[int, int]:
    """PDF page index -> printed folio, for a file whose UNNUMBERED pages are
    shuffled.

    Class 10 English alternates: an ODD folio prints "PAGE n" and the EVEN
    folio beside it prints "CH n : TITLE" and no number. The numbered pages
    are a complete, strictly increasing backbone -- 59 of them across the
    supplementary reader, with no inversion -- and the unnumbered ones ship
    scrambled. pdf 532 is folio 496 and pdf 536 is folio 494, so the chapter
    opens three pages into the file; pdf 570 is folio 518, sitting among
    chapter 4's pages, eleven pages from where it belongs.

    ATTRIBUTION SURVIVES THIS because every page names its own chapter.
    CONCATENATION DOES NOT, and that is what corrupts answers: 41 of the 121
    pages end on a question whose answer is overleaf, so with the pages in
    file order those questions bind to a stranger's answer and load clean --
    four options, a key that names one, nothing to catch.
    Compare [[qbank-split-document-block-boundaries]].

    Between two consecutive backbone folios there is EXACTLY ONE missing
    folio, so this is not a sort but a perfect matching: each unnumbered page
    of a chapter goes in one of the chapter's gaps, and the arrangement chosen
    is the one whose page boundaries read best (`_flow`). The chapters are
    small enough to settle by exhaustion.

    `_reading_order` cannot do this job here. It ranks pages on their HIGHEST
    question number, which works for a book numbered continuously through a
    chapter and not for this one: every chapter runs its multiple-choice
    questions 1 to 40 and then RESTARTS at 1 for the short answers and again
    for the long, so a page of long answers numbered 1 to 9 ranks before a
    page of multiple-choice questions numbered 24 to 38 that comes ten folios
    earlier.
    """
    import itertools

    text = {}
    folio: dict[int, int] = {}
    for i in range(doc.page_count):
        if owner[i] is None:
            continue
        raw = doc[i].get_text() or ""
        text[i] = _Flow(_flow_lines(raw))
        m = _FOLIO.search("\n".join(raw.splitlines()[:4]))
        if m:
            folio[i] = int(m.group(1))

    out = dict(folio)
    report: list[str] = []
    for part, so, name, lo, hi in chapters:
        mine = [i for i, o in enumerate(owner) if o == (part, so)]
        known = sorted((folio[i], i) for i in mine if i in folio)
        loose = sorted(i for i in mine if i not in folio)
        if not known or not loose:
            continue
        gaps: list[tuple[int, int | None, int | None]] = []
        prev_f, prev_i = lo - 1, None
        for f, i in known:
            for g in range(prev_f + 1, f):
                gaps.append((g, prev_i, i))
            prev_f, prev_i = f, i
        for g in range(prev_f + 1, hi + 1):
            gaps.append((g, prev_i, None))
        if len(loose) != len(gaps) or len(loose) > _PERM_CAP:
            # Fall back to file order rather than leaving the pages unplaced,
            # which would sort them to the end of the chapter -- worse than
            # the order the file already has.
            report.append(f"    ch {so}: {len(loose)} unnumbered page(s) for "
                          f"{len(gaps)} gap(s) -- left in file order")
            for g, p in zip((g for g, _, _ in gaps), loose):
                out[p] = g
            continue
        best, chosen = None, None
        for perm in itertools.permutations(loose):
            tot = 0.0
            for (g, a, c), p in zip(gaps, perm):
                if a is not None:
                    tot += _flow(text[a], text[p])
                if c is not None:
                    tot += _flow(text[p], text[c])
            if best is None or tot > best:
                best, chosen = tot, perm
        moved = sum(1 for a, b in zip(loose, chosen) if a != b)
        report.append(f"    ch {so}: {len(known)} numbered, {len(loose)} placed "
                      f"({moved} not in file order), fit {best:+.0f}")
        for (g, _, _), p in zip(gaps, chosen):
            out[p] = g
    _reading_order_slots.report = report
    return out


def _page_chapter(doc, chapters, tl: bool = False,
                  by_folio: bool = False) -> list[tuple[int, int] | None]:
    """Which chapter each PDF page belongs to, read from its own header.

    THE BOOK IS NOT IN CHAPTER ORDER, so no contiguous span can be right.
    Class 7 Science page 210 is headed "CH 9 : LIFE PROCESSES IN ANIMALS"
    and page 212 is headed "CH 8 : MEASUREMENT OF TIME AND MOTION" --
    chapter 8 resumes after chapter 9 has begun. Given a span, chapter 9
    collected seven of chapter 8's questions about average speed, and
    chapter 11 collected chapter 10's about whether non-green parts of a
    plant respire. Compare [[qbank-two-column-scatters-sections]].

    So every page is attributed on its own header, and a page without one
    inherits the page before it. Two details the header forces:

      IT ABBREVIATES. The contents prints "Empires and Kingdoms: 6th to
      10th Centuries"; the header prints "Empires and Kingdom :" -- so the
      key shortens until it matches.

      SIBLINGS SHARE A PREFIX. Class 6's three "Grassroots Democracy"
      chapters agree for 22 characters, so the longest key is tried first
      and the registry carries the book's own wording.

    A page naming three or more chapters is the contents, not a chapter.
    """
    titles = [_squash(c[2]) for c in chapters]
    pages = [_page_text(doc, i, tl) for i in range(doc.page_count)]
    sq = [_squash(t) for t in pages]

    # The shortest key that identifies each chapter uniquely across the book.
    # THE LONGEST KEY THAT STILL MATCHES, not the shortest that is unique.
    # Shortened too far, "Electricity Circuits and their Components" becomes
    # "ELECTRICIT" and claims every page in the metals chapter that mentions
    # electricity -- chapter 3 took 232 questions and chapter 4 was left 52.
    # SOME BOOKS CANNOT BE ATTRIBUTED BY TITLE. Class 10 Hindi-A has a
    # chapter called पद, and its grammar section has one called
    # पद परिचय 160 folios earlier -- the short title matches the long
    # one and anchors the chapter in the wrong section. Those books print
    # पृष्ठ N on every page instead, so the folio alone decides.
    keys: list[str] = ["" for _ in titles]
    if not by_folio:
        for k, t in enumerate(titles):
            chosen = t
            for width in (len(t), 30, 22, 18, 15, 12, 10):
                cand = t[:width]
                if not cand:
                    break
                others = [u[:width] for j, u in enumerate(titles) if j != k]
                if cand not in others and any(cand in s for s in sq):
                    chosen = cand
                    break
            keys[k] = chosen

    out: list[tuple[int, int] | None] = []
    last: tuple[int, int] | None = None
    for i in range(doc.page_count):
        raw = pages[i]
        hits = [k for k, key in enumerate(keys) if key and key in sq[i]]
        if len(hits) >= 3:            # the contents page
            out.append(last)
            continue
        if len(hits) == 1:
            last = (chapters[hits[0]][0], chapters[hits[0]][1])
        else:
            # NO TITLE HEADER: fall back to the folio this page prints, and
            # the range the contents gives each chapter. Carrying the last
            # chapter forward is wrong where the book interleaves -- pages
            # 211, 213 and 214 of Class 7 Science hold chapter 8 but follow
            # a page headed chapter 9, and inherited it, taking seven
            # questions about average speed into Life Processes in Animals.
            m = _FOLIO.search("\n".join(raw.splitlines()[:4]))
            if m:
                f = int(m.group(1))
                owner = [(c[0], c[1]) for c in chapters if c[3] <= f <= c[4]]
                # A folio past the last chapter is a section the database
                # does not hold -- Class 9 Hindi prints 18 pages of
                # composition exercises after folio 381, and carried
                # forward they doubled the last chapter.
                last = owner[0] if len(owner) == 1 else None
        out.append(last)
    return out


_QNUM_LINE = re.compile(r"(?m)^[ \t]*(\d{1,3})\s*\.(?:\s*$|\s+\S)")


def _reading_order(doc, chapters, owner) -> dict[int, int]:
    """PDF page index -> the folio it really carries, for a book shipped out of
    printed order.

    THE FILE'S PAGE ORDER IS NOT THE BOOK'S READING ORDER. In Class 6 Science
    the ODD folios are shuffled -- chapter 7's pdf pages 178, 180 and 182 carry
    folios 153, 151 and 149, exactly reversed, and pdf 175 carries folio 155,
    the opening page of the NEXT chapter, from the middle of this one.

    Attribution survives this, because every page is read on its own running
    head. CONCATENATION DOES NOT, and that is what corrupts answers. Folio 149
    ends with question 60, "What is the typical temperature range of a school
    laboratory thermometer?", and folio 150 opens with its answer, "The range
    is typically from -10 to 110 C". Taken in file order folio 150 comes first,
    so that answer binds to the last question on folio 148 instead -- a
    matching-type exercise about thermometer care -- and question 60 collects
    the answer after it. Both rows load clean: four options, a key that names
    one, nothing for a validator to catch.
    Compare [[qbank-split-document-block-boundaries]].

    The two margins alternate: an EVEN folio prints "PAGE n" and the ODD folio
    before it prints "CH n : TITLE" and no number at all. So the even pages are
    a complete, correctly ordered backbone (132 of them here, folios 6 to 268,
    strictly increasing), and only the odd pages have to be placed.

    They are placed on their QUESTION NUMBERS, which run continuously through a
    chapter -- on the HIGHEST number a page carries, which is the one statistic
    the book's two quirks leave alone. The matching-type exercise restarts at 1
    in the middle of the sequence, and an answer sets its points out as "1. 2.
    3.", so a page's first number and its median both understate it: folio 9
    carries question 18 and then a matching exercise numbered 1 to 4, whose
    median of 3 sorts it before folio 7 and its questions 6 to 11. Neither
    restart can raise the maximum, because both begin again from 1 far below the
    running question number.

    This reproduces, for every page checked, the order the text itself proves:
    folio 149 ends mid-answer "(d) 1-B, 2-C, 3-A, 4-D" and folio 148 ends with
    that question's options; folio 151 ends "warm water and the other in cold
    water, then" and folio 152 opens "place both in lukewarm water".

    A page with no question numbers -- a chapter's SUMMARY opening -- sorts to
    the front on 0 and keeps its file order, which is where the summary belongs.

    ONLY REAL PAGES TAKE A FOLIO. An advert or a blank must not, or it consumes
    a slot and shifts every page after it: chapter 1 has six odd folios and ten
    adverts sitting inside its range, and counted in they took all six and left
    the chapter's own pages unplaced. They are told apart by length -- the
    shortest page the book itself numbers is 694 characters and the longest
    advert 476. `_is_ad` cannot do this job here, because it also calls three
    chapter-opening SUMMARY pages adverts: they carry the pdf.tube footer and,
    having no questions, no answer marker either.
    """
    rng = {(c[0], c[1]): (c[3], c[4]) for c in chapters}
    folio: dict[int, int] = {}
    loose: dict[tuple, list] = {}
    for i in range(doc.page_count):
        raw = doc[i].get_text() or ""
        m = _FOLIO.search("\n".join(raw.splitlines()[:4]))
        if m:
            folio[i] = int(m.group(1))
        elif owner[i] and len(raw) >= 600:
            q = [int(x) for x in _QNUM_LINE.findall(raw)]
            loose.setdefault(owner[i], []).append((max(q) if q else 0, i))

    for key, pages in loose.items():
        lo, hi = rng[key]
        taken = {f for i, f in folio.items() if owner[i] == key}
        free = [f for f in range(lo, hi + 1) if f not in taken]
        # Sorted on the median question number, ties and question-less pages
        # broken by file order.
        for (_med, i), f in zip(sorted(pages), free):
            folio[i] = f
    return folio


# Furniture that sits between the questions and would otherwise be read as
# part of one: the two running heads, the publisher's mark, and the board and
# year each question is tagged with. The year tag is set on its own line
# BESIDE the answer marker, so left in it becomes the first words of every
# answer in the book.
#
# THE YEAR TAG NAMES SEVERAL YEARS AT ONCE -- "CBSE 2016, 2015, 2014" for a
# question that was set three times -- so one \d{4} leaves the rest of the
# list standing, and it is the rest that ends up inside the stem.
# \d{4,5} because the book mis-sets one of them as "CBSE 20010, 2009", and
# on four digits the stray zero and the second year stay in the stem.
_TAG = (r"(?:CBSE|NCERT|Board|SQP|Delhi|OD|Foreign|Comptt\.?)"
        r"(?:[\s,]*\d{4,5})+[A-Za-z, ]*")
_FURNITURE = re.compile(
    r"^(?:\x1f)?\s*(?:"
    r"पृष्ठ\s*\d+"
    r"|अध्याय\s*\d+\s*[ः:%].*"
    r"|CBSE\s+कक्षा.*"
    r"|" + _TAG +
    r"|w*\.?nodia\.[a-z.]*"
    r"|NODIA"
    r")\s*$")
# The same tag set flush against the end of a question, after a tab, where
# dropping the whole line would drop the question with it.
_TAG_TAIL = re.compile(r"[ \t]*" + _TAG + r"\s*$")


def _blob(doc, pages, tl: bool = False, spans: bool = False,
          content=None, extra=None) -> tuple[str, int]:
    out, skipped = [], 0
    for p in pages:
        raw = _page_text_spans(doc, p) if spans else _page_text(doc, p, tl)
        if _is_ad(raw, content):
            skipped += 1
            continue
        for ln in raw.splitlines():
            if re.match(r"^\s*page\s+\d+\s*$", ln) or "Chapterwise QB" in ln:
                continue
            if spans and _FURNITURE.match(ln):
                continue
            if extra and extra.match(ln):
                continue
            if spans:
                # The tag is not always on a line of its own: set after a
                # tab it closes the question, and dropping the line would
                # drop the question with it.
                ln = _TAG_TAIL.sub("", ln)
                if not ln.strip():
                    continue
            out.append(ln)
    return "\n".join(out), skipped


def build(book: str) -> dict:
    cfg = BOOKS[book]
    ans_re = re.compile(cfg["marker"])
    qstart = re.compile(cfg.get("qstart") or _QSTART.pattern)
    labs, table = _label_set(cfg)
    lead_re = re.compile(rf"^\s*\(?\s*([{labs}])\s*\)?[.\s]*")
    opt_line_re = re.compile(rf"(?m)^[ 	]*\(\s*[{labs}]\s*\)")
    opt_any_re = re.compile(rf"\(\s*[{labs}]\s*\)[^()]{{0,200}}?"
                            rf"(?=\s*\(\s*[{labs}]\s*\)|\s*$)")

    def _has_content(page_text: str) -> bool:
        """True of a page that answers or asks something, in THIS book's
        notation. What tells a chapter page from an advertisement."""
        return bool(ans_re.search(page_text) or qstart.search(page_text))

    doc = fitz.open(MIRROR / cfg["file"])
    doc_pages = doc.page_count
    tl = bool(cfg.get("transliterate"))
    spans = cfg.get("page_text") == "spans"
    banners: dict[str, int] = {}
    if cfg.get("attribute_by") == "banner":
        owner, banners = _page_chapter_banner(doc, cfg)
    elif cfg.get("attribute_by") == "head":
        owner = _page_chapter_head(doc, cfg["chapters"])
    elif cfg.get("attribute_by") == "head_strict":
        owner = _page_chapter_head_strict(doc, cfg["chapters"])
    else:
        owner = _page_chapter(doc, cfg["chapters"], tl,
                              bool(cfg.get("attribute_by") == "folio"))
    # Pages the span reader cannot read: those where the untabled font
    # carries the body. Counted, not silently lost.
    unreadable = []
    if spans:
        for i, o in enumerate(owner):
            if o is None:
                continue
            t = _page_text_spans(doc, i)
            body = [c for c in t if not c.isascii()]
            if body and sum(c == BAD for c in body) / len(body) > 0.5:
                unreadable.append(i)
    items, dropped, ads = [], {}, 0
    # THE SHARED STRIP IS CASE-SENSITIVE and this book shouts: it prints
    # "PAGE  148" and "CBSE CLASS 6TH SCIENCE  CHAPTERWISE QB", so neither
    # `^\s*page\s+\d+\s*$` nor the "Chapterwise QB" test sees them and both
    # run on into whatever answer straddles the page break. Rather than
    # loosen a rule six loaded books depend on, each book may declare its own
    # furniture.
    furniture = re.compile(cfg["furniture"]) if cfg.get("furniture") else None
    wrapped = bool(cfg.get("wrapped_options"))
    # Sorted into the book's reading order where the file ships pages
    # transposed; a no-op for a book whose order is already right. "slots"
    # is for a file with a complete printed backbone to place them against.
    reorder = cfg.get("reorder_pages")
    order_note: list[str] = []
    if reorder == "slots":
        order = _reading_order_slots(doc, cfg["chapters"], owner)
        order_note = list(getattr(_reading_order_slots, "report", []))
    elif reorder:
        order = _reading_order(doc, cfg["chapters"], owner)
    else:
        order = {}
    title_banners = BANNERS_TITLE if cfg.get("title_banners") else None

    for part, so, name, lo, hi in cfg["chapters"]:
        mine = [i for i, o in enumerate(owner) if o == (part, so)]
        if order:
            mine.sort(key=lambda i: (order.get(i, 10 ** 6), i))
        body, skipped = _blob(doc, mine, tl, spans, _has_content, furniture)
        ads += skipped
        qpos = [m.start() for m in qstart.finditer(body)]
        apos = list(ans_re.finditer(body))
        for k, a in enumerate(apos):
            before = [q for q in qpos if q < a.start()]
            if not before:
                continue
            start = before[-1]
            nxt_ans = apos[k + 1].start() if k + 1 < len(apos) else len(body)
            stop = min([q for q in qpos if a.end() < q <= nxt_ans] or [nxt_ans])
            raw_stem = body[start:a.start()]
            # TWO ANSWERS UNDER ONE QUESTION NUMBER. The book sometimes sets
            # two questions and two answers against a single number, and
            # sometimes a number simply fails to print. Either way the second
            # answer's stem reaches back past the first answer and carries it:
            # "24. लक्ष्मण के कुल में ...? उत्तर ः लक्ष्मण के कुल में देवता,
            # ब्राह्मण ...", a whole answer standing inside a question. It
            # also walks the answer marker into option (D) of whatever
            # follows. 39 of Class 10 Hindi-A's 1,749, and each one loads
            # clean -- four options, a key that names one.
            if ans_re.search(raw_stem):
                dropped["a second answer under one question number"] = \
                    dropped.get("a second answer under one question number", 0) + 1
                continue
            # THE SECTION BANNER SITS BETWEEN THE LAST ANSWER OF ONE SECTION
            # AND THE FIRST QUESTION OF THE NEXT, so it falls inside the
            # answer's span and is printed at the end of it: "A 'whys'
            # person. SHORT ANSWER QUESTION". It cannot be stripped in
            # `_blob`, because `_form_at` reads these same lines to type the
            # questions that follow.
            answer = " ".join(" ".join(
                ln for ln in body[a.end():stop].splitlines()
                if not _is_banner(ln, title_banners)).split())
            form = _form_at(body, start, extra=title_banners)
            if form == "skip":
                dropped["matching-type exercise"] = dropped.get("matching-type exercise", 0) + 1
                continue
            used: set = set()
            if wrapped:
                opts, used = _options_wrapped(raw_stem, labs, table)
                if not opts:                      # fall back to one line each
                    opts = _options(raw_stem, labs, table)
            else:
                opts = _options(raw_stem, labs, table)
            # Strip the options and the leading number with THIS book's
            # patterns. Using the Latin ones, a Hindi stem keeps its own
            # four choices and its "1-" inside the question text. Where the
            # choices wrap, their continuation lines go too -- they are not
            # part of the question.
            stem_lines = [ln for n, ln in enumerate(raw_stem.splitlines())
                          if n not in used
                          and not (opts and opt_line_re.match(ln))]
            stem = "\n".join(stem_lines)
            stem = qstart.sub("", stem, count=1)
            stem = " ".join(re.sub(r"^\s*\d{1,3}\s*[.\-–]\s*", "", stem).split())
            if opts:
                stem = opt_any_re.sub(" ", stem)
                stem = " ".join(stem.split())
            correct = _key(opts, answer, lead_re, table) if opts else ""
            if opts and correct:
                form = "mcq"
            elif opts:
                dropped["four options but the answer names none"] = \
                    dropped.get("four options but the answer names none", 0) + 1
                continue
            elif form in ("mcq", "assertion_reason"):
                form = "very_short"
            # SET IN A FONT THERE IS NO TABLE FOR. Loaded, the stem reads
            # "र्वटउव्त H$े श्लक्ष्ट© Hँ$हत Wत?" -- Devanagari-shaped, not
            # Hindi, and no validator can tell the difference.
            if BAD in stem or BAD in answer or any(BAD in o["text"] for o in opts):
                dropped["set in SHREE-DEV7, which has no table"] = \
                    dropped.get("set in SHREE-DEV7, which has no table", 0) + 1
                continue
            # A FULL OPTION SET IS ITSELF THE EVIDENCE. The five-word floor
            # catches a fragment left behind by a bad split, but "What is
            # science?" is three words, and with four parsed choices and a key
            # that names one it is a whole question. It only became short once
            # the wrapped choices stopped being swept into it -- before that,
            # the option tails padded it past the floor and it passed for the
            # wrong reason. Twenty-six such questions were dropped.
            floor = 3 if (opts and correct) else 5
            if len(stem.split()) < floor:
                dropped["stem under 5 words"] = dropped.get("stem under 5 words", 0) + 1
                continue
            if not answer.strip():
                dropped["no answer at all"] = dropped.get("no answer at all", 0) + 1
                continue
            items.append({
                "part": part, "chapter_number": so, "chapter": name,
                "number": len(items) + 1, "form": form, "stem": stem,
                "options": opts, "correct_option": correct,
                "answer": answer[:4000], "concept": "", "needs_reading": True,
            })
    doc.close()

    seen, unique = set(), []
    for it in items:
        k = (it["part"], it["chapter_number"],
             _norm(it["stem"] + "".join(o["text"] for o in it["options"]))[:160])
        if k in seen:
            dropped["printed twice"] = dropped.get("printed twice", 0) + 1
            continue
        seen.add(k)
        unique.append(it)
    return {"cfg": cfg, "items": unique, "dropped": dropped,
            "folios": len({o for o in owner if o}), "pages": doc_pages,
            "raw": len(items), "banners": banners, "unreadable": unreadable,
            "attributed": sum(1 for o in owner if o), "order": order_note}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--book", choices=sorted(BOOKS), required=True)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "nodia_qb_items" / "drafts"))
    a = ap.parse_args()
    r = build(a.book)
    cfg = r["cfg"]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{a.book}.json").write_text(json.dumps(
        {"book": a.book, "source": cfg["file"], "source_url": SOURCE_URL,
         "publisher": cfg["publisher"], "textbook": cfg["textbook"],
         "session": "2026-27", "validation_status": "sourced_verbatim",
         "items": r["items"]}, indent=1, ensure_ascii=False), encoding="utf-8")

    forms = ("mcq", "very_short", "short", "long", "case_study")
    print(f"{a.book} -- {cfg['file']}")
    print(f"  {r['folios']} chapters attributed page by page from the running header, "
          f"over {r['pages']} PDF pages\n")
    print(f"  {'pt':>2} {'ch':>3} {'chapter':<48} " + " ".join(f"{f[:10]:>10}" for f in forms) + f" {'total':>6}")
    print("  " + "-" * 122)
    for part, so, name, lo, hi in cfg["chapters"]:
        ks = [i for i in r["items"] if i["part"] == part and i["chapter_number"] == so]
        print(f"  {part:>2} {so:>3} {name[:48]:<48} "
              + " ".join(f"{sum(1 for i in ks if i['form']==f):>10}" for f in forms)
              + f" {len(ks):>6}")
    print("  " + "-" * 122)
    print(f"  {'':>2} {'':>3} {'total':<48} "
          + " ".join(f"{sum(1 for i in r['items'] if i['form']==f):>10}" for f in forms)
          + f" {len(r['items']):>6}\n")
    print("  dropped:")
    for why, n in sorted(r["dropped"].items(), key=lambda x: -x[1]):
        print(f"      {n:>4}  {why}")

    if r.get("order"):
        print(f"\n  reading order rebuilt ({r['attributed']} pages attributed, "
              f"nothing inherited):")
        for line in r["order"]:
            print(line)

    if r.get("banners"):
        b = r["banners"]
        known = set((cfg.get("banner_of") or {}).values())
        ok, bad = b.get("holdout_ok", 0), b.get("holdout_bad", 0)
        print(f"\n  attribution: {r['attributed']} of {r['pages']} pages, "
              f"{b.get('named_pages', 0)} from a running header and "
              f"{b.get('by_words', 0)} more from their own words")
        print(f"    the word rule, measured leave-one-out against the "
              f"{b.get('named_pages', 0)} pages whose header names them: "
              f"decided {ok + bad}, correct {ok}, WRONG {bad}")
        print("\n  running headers seen:")
        for name, n in sorted(b.get("headers", {}).items(), key=lambda x: -x[1]):
            print(f"      {n:>4}  {name}"
                  + ("" if name in known else "   <- not a chapter we hold"))
    if r.get("unreadable"):
        print(f"\n  {len(r['unreadable'])} attributed page(s) are set mostly in a "
              f"font with no table and yield nothing:")
        print("      " + ", ".join(str(p) for p in r["unreadable"][:40])
              + (" ..." if len(r["unreadable"]) > 40 else ""))
    print(f"\ndrafts in {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
