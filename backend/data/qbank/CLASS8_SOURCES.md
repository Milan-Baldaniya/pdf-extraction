# Class 8 sourcing — verified 2026-09-25

Every URL below was fetched and the file opened. Nothing here is inferred from a
URL pattern, and nothing a search engine merely *claimed* has been recorded as
fact. Where a search result disagreed with the source document, the source
document won and the disagreement is noted.

## VERIFIED — downloaded and readable

### CBSE competency material (Tier D), `data/qbank/mirror/class8/`

Base: `https://cbseacademic.nic.in/cbe/documents/`

| File | Pages | Items | Answers |
|---|---|---|---|
| `SAS_Science-Class-8.pdf` | 135 | 181 | yes, 180 |
| `SAS_Maths-Class-8.pdf` | 115 | 164 | yes, 164 |
| `SAS_English-Class-8.pdf` | 108 | 176 | yes, 176 |
| `Item-Bank---Science-Class-8.pdf` | 85 | ~80 | **NO** |
| `Item-Bank---Maths-Class-8.pdf` | 139 | ~90 | **NO** |
| `Item-Bank---English---Class-8.pdf` | 59 | ~70 | **NO** |

**The three SAS files are the best-tagged source in this project.** Each item
carries, from CBSE itself rather than from our inference:

    Question Code    SAS21M08D1501
    Grade & Chapter  Grade 8 | Introduction to Graph
    Concept|Sub      Graphical Representation | A Line Graph
    Competency       Formulate
    Item Type        Multiple Choice Question
    Full Credit      C. 64
    No Credit        Any other response or missing response

The question code is structured — `SAS21` + `M`/`S` (subject) + `08` (class) +
chapter + item — so chapter assignment is read off the item, not guessed.

**The three Item Banks carry no answer key.** They are British Council CBE
project banks: items with AO1-AO4 marks for a teacher to mark. Under the
answers-only rule they are not ingestible. Decision 2026-09-25: skip them.

**These are 2021 material on the PRE-RATIONALISATION syllabus.** SAS Science
covers 18 chapters; SAS Maths covers 16. The database holds the rationalised
13 and 13. So five Science chapters and three Maths chapters of this material
have no chapter to land in.

### NCERT textbooks, `data/qbank/mirror/class8_2526/`

Base: `https://ncert.nic.in/textbook/pdf/`  — the code's first letter is the
class (`h` = 8), confirmed against [[ncert-pdf-url-codes]].

| Code | Book | Session |
|---|---|---|
| `hecu1ps` | **Curiosity** — Science | First edn July 2025, reprint 2026-27 |
| `hegp1ps` | **Ganita Prakash** Part 1 — Maths | reprint 2026-27 |
| `hegp2ps` | **Ganita Prakash** Part 2 — Maths | reprint 2026-27 |
| `hees1ps` | **Exploring Society** Part 1 — Social Science | First edn July 2025 |
| `hees2ps` | **Exploring Society** Part 2 — Social Science | First edn July 2025 |
| `hesc1ps` | Science Textbook for Class VIII | **2024-25 — the OLD book** |
| `hemh1ps` | Mathematics Textbook for Class VIII | **2024-25 — the OLD book** |

The last two matter: they are the books the database's chapter rows came from,
which is how the three-way split below was confirmed rather than assumed.

## THE THREE-WAY SYLLABUS SPLIT

Class 8 Science exists in three incompatible chapter structures:

1. **18 chapters** — pre-rationalisation. CBSE's 2021 SAS/Item Bank material.
2. **13 chapters** — rationalised 2024-25. **What `chapter_master` holds.**
3. **13 chapters, all new names** — *Curiosity*, 2025-26 onward. Current.

Zero chapter names are shared between (2) and (3). The same break runs through
every Class 8 subject:

| Database subject | Old book | 2025-26 book |
|---|---|---|
| Science (13) | Science for Class VIII | **Curiosity** (13) |
| Mathematics (13) | Mathematics for Class VIII | **Ganita Prakash** (14) |
| English (8) | Honeydew | **Poorvi** |
| English-2 (8) | It So Happened | *(folded into Poorvi?)* |
| Hindi-A (13) | Vasant Bhag 3 | **Malhar** |
| Social Sciences (5) + -2 (8) + -3 (8) = 21 | Geography/Civics/History | **Exploring Society** (15, one book) |

Social Science is the sharpest change: three subjects and 21 chapters collapse
into one book of 15.

## VERIFIED CHAPTER LISTS (from each book's own contents page)

### Curiosity — Science, 13 chapters
1. Exploring the Investigative World of Science
2. The Invisible Living World: Beyond Our Naked Eye
3. Health: The Ultimate Treasure
4. Electricity: Magnetic and Heating Effects
5. Exploring Forces
6. Pressure, Winds, Storms, and Cyclones
7. Particulate Nature of Matter
8. Nature of Matter: Elements, Compounds, and Mixtures
9. The Amazing World of Solutes, Solvents, and Solutions
10. Light: Mirrors and Lenses
11. Keeping Time with the Skies
12. How Nature Works in Harmony
13. Our Home: Earth, a Unique Life Sustaining Planet

### Ganita Prakash — Maths, 14 chapters in two parts
**Part 2 restarts numbering at 1.** A web search claimed Part 2 was
"chapters 8-14"; the book itself numbers them 1-7. The source won.

Part 1: 1 A Square and A Cube · 2 Power Play · 3 A Story of Numbers ·
4 Quadrilaterals · 5 Number Play · 6 We Distribute, Yet Things Multiply ·
7 Proportional Reasoning-1

Part 2: 1 Fractions in Disguise · 2 The Baudhayana-Pythagoras Theorem ·
3 Proportional Reasoning-2 · 4 Exploring Some Geometric Themes ·
5 Tales by Dots and Lines · 6 Algebra Play · 7 Area

### Exploring Society: India and Beyond — Social Science, 15 chapters
Part 1: 1 Natural Resources and Their Use · 2 Reshaping India's Political Map ·
3 The Rise of the Marathas · 4 The Colonial Era in India · 5 Universal Franchise
and India's Electoral System · 6 The Parliamentary System: Legislature and
Executive · 7 Factors of Production

Part 2: 1 World Geography: Some Glimpses · 2 India's Long Road to Independence ·
3 A Journey Through Indian Architecture · 4 The Role of the Judiciary in Our
Society · 5 Citizenship: Rights and Duties · 6 Dynamics of Population ·
7 India's Urban Landscape · 8 Cultural Currents: 13th to 17th Centuries

A search result put "Governance and Democracy" under Theme C; the book says
Theme D. Theme attribution from search results is unreliable — take themes off
the contents page, not off a summary.

## REJECTED / UNRESOLVED

| Candidate | Result |
|---|---|
| `kv-library.blogspot.com/p/list-of-kendriya-vidyalaya-regional.html` | Fetched. Directory of 31 KVS regional-office and ZIET sites. **No Q&A content.** |
| KVS Student Support Material for Class 8 | **Does not exist.** SSM is published for Classes IX-XII only. Confirmed across several KV school sites. Stop looking. |
| NCERT English (Poorvi) code | `hepv1ps`, `hepo1ps`, `hepo2ps`, `heen1ps`, `hepu1ps` all 404. Unresolved — get from NCERT's own dropdown or ePathshala, do not keep guessing. |
| NCERT Hindi (Malhar) code | `heml1ps`, `hemh1ps` (turned out to be old Maths), `hehi1ps`, `hemn1ps`, `hehm1ps` all 404. Unresolved. |
| `ncert.nic.in/textbook.php` | Fetched. Chapter list is behind a JS dropdown; the HTML alone carries no book codes. |

NCERT resets connections intermittently — `hees2ps` failed once with code 000
and succeeded on retry. A failure there is not a 404; retry before concluding
the file is absent. See [[ncert-download-truncation-looks-corrupt]].

## VOLUME REALITY AGAINST THE 500/CHAPTER GOAL

Class 8 is 76 chapters. 500 each is **38,000 questions**. The bank holds 4,686.

The six CBSE files add ~521 answered items over ~34 chapters — about **15 per
chapter**, and only for Maths, Science and English. Hindi and the three Social
Science subjects get nothing; CBSE never published SAS for them.

500/chapter is not reachable from verified sources and is not close. Realistic
ceilings, consistent with [[qbank-breadth-first-not-500]]:

- Science / Maths: 250-350, and only with commercial chapter-wise books
- English / Hindi / Social Science: under 200

Closing the rest would mean roughly 33,000 generated questions for Class 8
alone, which is the one thing ruled out. The honest goal is every chapter
reaching its sources' real ceiling, fully mapped.

---

# SCERT Haryana — verified 2026-09-25

`https://scertharyana.gov.in/competency-bank-question-bank/` is real and its
links resolve. 15 PDFs downloaded to `data/qbank/mirror/scert_haryana/`, 60 MB.
Built with Educational Initiatives (Ei) and mapped to state learning outcomes.

**All eleven 2025-26 files carry a marking scheme** — a "Q No. / Rubric /
Marks" table near the end reading `Correct Answer: C`, about 50 per file.
Cleanly parseable.

| Session | Files | Classes | Subjects | Questions each |
|---|---|---|---|---|
| 2025-26 | 11 | 6, 7, 8 | Hindi, English, Science, Maths (no Class 8 Maths) | ~50 |
| 2024 | 4 | 6, 7 | English, Maths, Science | 500-1000 |

## Why this is smaller than it looks

- **~50 questions per SUBJECT, not per chapter.** Class 6 Science has 12
  chapters, so 50 items is about **4 per chapter**.
- **Organised by competency, not by chapter.** Items are indexed as
  `SCI801 -> Q5, Q9, Q27, Q33`. Assigning them to chapters means reading each
  one; there is no chapter field to key on.
- **Hindi-medium for Science, Maths and Hindi**, and the Devanagari text layer
  is corrupted in the familiar way — `वनम्नविवखत` for `निम्नलिखित`. See
  [[ocr-devanagari-lookalike-breaks-quote-anchors]] and
  [[devanagari-anchors-need-unicode-escapes]]. The English files are clean.
- **The big 2024 Maths bank has no answer key.** 116 pages, ~1,000 Hindi MCQs,
  nothing to mark them against. Checked page by page, not assumed.

Real yield: roughly **550 answered items across 11 subject-files**, which is
about 4 per chapter once spread over Classes 6-8. Worth having, especially for
Classes 6 and 7 which are at zero, but it does not move a chapter toward 500.

# WHERE 500 PER CHAPTER IS ACTUALLY REACHABLE

Measured across all 396 Class 6-10 chapters:

| Band | Chapters | Share |
|---|---|---|
| **>= 500 (target met)** | **7** | 1.8% |
| 350-499 | 6 | 1.5% |
| 250-349 | 2 | 0.5% |
| 100-249 | 33 | 8.3% |
| 1-99 | 105 | 26.5% |
| zero | 243 | 61.4% |

**Six of the seven chapters at 500+ are Class 10 Science**, and the whole
subject averages 567 per chapter. Nothing else comes close: Class 9 Science is
190, Class 8 Science 148, Class 10 Maths 146.

The reason is visible in the source counts. Class 10 Science is the only
subject fed by **two large independent bodies of questions** — 2,926 read out
of the Nodia book and 4,442 already native to the LMS. Everything with one
source sits at 50-150.

So the rule is arithmetic, not effort:

    one commercial chapter-wise book   150-250 per chapter
    + a second independent book        150-250
    + LMS-native                        50-340
    + NCERT Exemplar (Science/Maths)     40-60
    + NCERT textbook exercises           15-25
    + CBSE SAS                          ~10
    + SCERT Haryana                      ~4
    ------------------------------------------------
    = 500 needs THREE OR FOUR stacked sources on the same chapter.

Government sources are excellent provenance and poor volume. CBSE SAS, SCERT
and the textbook exercises together contribute under 40 per chapter. They
cannot carry a 500 target and were never meant to — they are sample item banks.

**Volume comes only from commercial chapter-wise books.** That is what took
Class 10 Science past 500, and it is the only lever that will do it again.

Languages and Social Science have no Exemplar and far fewer commercial banks,
so their realistic ceiling stays near 250-300 whatever is done.

## Anomaly to investigate

Class 8 Science chapter 2 (Microorganisms) holds **966 questions** against
70-88 in each of its twelve siblings — 50% of the subject in one chapter, and
all 966 stems are distinct so it is not duplication. That looks like a bulk
load that defaulted to one chapter_id rather than genuine depth.
