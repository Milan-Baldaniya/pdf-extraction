"""Resolve the 1,354 live questions whose chapter_id resolves to no chapter_master row.

    python -m scripts.resolve_orphan_chapters --list
    python -m scripts.resolve_orphan_chapters --chapter 893           # report only
    python -m scripts.resolve_orphan_chapters --chapter 893 --apply   # UPDATE
    python -m scripts.resolve_orphan_chapters --audit                 # plan vs database

Scope is the estate: standard_id IN (39,40,41,42,43) -- classes 6-10 of
sub_institute_id 1. Restricted that way the orphan set is exactly 1,354 live
questions across 155 chapter_ids. (Unrestricted, the same LEFT JOIN finds tens
of thousands more across the CBSE-N / Standard-N / E-STD-N tenants and classes
11-12; those are other people's books and are deliberately out of scope here.)

WHY THESE IDS EXIST
-------------------
`lms_chapter_crosswalk` holds a row for every one of the 155 ids, keyed as
`legacy_chapter_id`, with a `decision` and a `new_chapter_id`. So the
supersession was planned. But:

  * `adjudicator_model` and `verifier_model` are NULL on all 805 crosswalk rows
    and `shortlist_mode` is 'authored' -- the plan was hand-authored and never
    model-adjudicated or verified. The confidences are authored guesses, which
    is why every `out_of_syllabus` row carries a flat 0.900 or 0.850.
  * `lms_question_chapter_fix` logs 21,092 questions that a re-chaptering pass
    did move. NOT ONE of our 1,354 appears in it.

So the questions were left pointing at ids whose chapter_master rows were then
deleted. They are invisible to every per-chapter report because those all join
through chapter_master.

The crosswalk was therefore treated here as a hypothesis, not as evidence, and
every chapter below was decided by reading its questions. The crosswalk is
wrong on 116 of the 132 Class 9 Science questions (it calls the whole old
15-chapter book out_of_syllabus when ten of its chapters have a clear NEP
counterpart), wrong on Class 10 Social Sciences 1046, and wrong on Class 8
English 3617.

THE GUARD
---------
Every chapter carries `guard = (n, lo, hi, sha)`: the live question count, the
lowest and highest question id, and a sha256 over the exact comma-joined sorted
id list, all as read when this file was written. The run re-reads the chapter
and refuses the WHOLE cluster if any of the four differs -- so a chapter whose
rows have changed since cannot be acted on from a stale decision.

Chapters whose questions belong to two different source chapters are split by
`subconcept` (see 4649 and 4656 in the plan). A rule's regex must match every
row it claims, and every row must match exactly one rule, or the cluster is
refused.

DUPLICATES
----------
All 1,354 are LMS-native: zero rows in `lms_question_extraction`, so there is
no `verbatim_sha256` to key on, and `g_content_hash` is NULL on all of them.
Duplicates are therefore found by comparing a normalised stem (mojibake
repaired, NFKC, lowercased, punctuation dropped, whitespace collapsed, first
120 chars) against the live questions already in the target chapter. A hit is
retired instead of repointed, so a repoint never creates a second copy.

WHAT IS NOT DONE
----------------
UPDATE only. Retirement is `deleted_at = NOW()`, which is reversible.  No
chapter_master row is created. Question ids never change, so curriculum
mappings (`lms_question_outcome` keys on question_id) and PAL rows stay
attached under either action.

Cross-subject repointing is deliberately NOT done. `q.subject_id` equals the
chapter's `subject_id` on 36,450 of 36,487 healthy estate rows, so moving a
question to a chapter under another subject would need `subject_id` moved too.
That is an editorial call and it is left alone -- see the `leave` entries for
Class 9 Social Sciences, where 8613 Democracy and 8619 Elections are good
content matches but sit under subject 4469 while the questions are 4064.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

STANDARDS = (39, 40, 41, 42, 43)

REPOINT = "repoint"
RETIRE = "retire"
LEAVE = "leave"


class Rule:
    """One decision, optionally scoped to part of a chapter by `pattern`."""

    def __init__(self, action, target=None, why="", field="subconcept", pattern=None):
        self.action = action
        self.target = target
        self.why = why
        self.field = field
        self.pattern = re.compile(pattern, re.I) if pattern else None

    def matches(self, title, subconcept):
        if self.pattern is None:
            return True
        return bool(self.pattern.search(subconcept if self.field == "subconcept" else title))


class Chapter:
    def __init__(self, cluster, was, guard, rules, note=""):
        self.cluster = cluster      # "class / subject", for the operator
        self.was = was              # what the questions actually are
        self.guard = guard          # (n, lo, hi, sha16)
        self.rules = rules
        self.note = note


def _whole(action, target=None, why=""):
    return [Rule(action, target, why)]


# --------------------------------------------------------------------------
# THE PLAN.  Every chapter below was decided by reading its questions; `was`
# records the identification and `why` the reasoning.
# --------------------------------------------------------------------------

C7_ENG = "Class 7 / English"
C6_ENG = "Class 6 / English"
C6_ENG2 = "Class 6 / English-2"
C7_ENG2 = "Class 7 / English-2"
C9_ENG = "Class 9 / English"
C9_SCI = "Class 9 / Science"
C8_ENG = "Class 8 / English"
C8_ENG2 = "Class 8 / English-2"
C8_SAS = "Class 8 / Social Sciences"
C10_ECO = "Class 10 / Economics"
C10_SAS = "Class 10 / Social Sciences"
C10_SAS2 = "Class 10 / Social Sciences-2"
C10_SAS3 = "Class 10 / Social Sciences-3"
C10_HINB = "Class 10 / Hindi-B"
C6_MAT = "Class 6 / Mathematics"
C6_SCI = "Class 6 / Science"
C9_SAS = "Class 9 / Social Sciences"
C9_SAS2 = "Class 9 / Social Sciences-2"
C9_SAS3 = "Class 9 / Social Sciences-3"
C9_ECO = "Class 9 / Economics"
C7_SCI = "Class 7 / Science"

# Honeycomb / An Alien Hand are the superseded Class 7 English books. The live
# Class 7 English is Poorvi (5 chapters, 25925-25929) and it shares no text
# with them -- Poorvi's "Wit and Humour" is Doctor Dolittle, not "Gopal and the
# Hilsa-Fish". Nothing here has an NEP home.
_HONEYCOMB = "Honeycomb (superseded Class 7 English); no text survives into Poorvi"

PLAN: dict[int, Chapter] = {
    # ---------------- Class 7 English: Honeycomb + its poems -> retire ------
    146: Chapter(C7_ENG, "Three Questions (Tolstoy)", (47, 91930, 91976, "156ecae288e473b7"), _whole(RETIRE, why=_HONEYCOMB)),
    147: Chapter(C7_ENG, "Three Questions / A Gift of Chappals", (36, 92009, 92044, "544ff9570bf5171a"), _whole(RETIRE, why=_HONEYCOMB)),
    148: Chapter(C7_ENG, "Gopal and the Hilsa-Fish", (12, 92085, 92096, "95b5a3156f8fc6af"), _whole(RETIRE, why=_HONEYCOMB)),
    149: Chapter(C7_ENG, "The Ashes That Made Trees Bloom", (27, 92121, 92147, "249714bc46146173"), _whole(RETIRE, why=_HONEYCOMB)),
    150: Chapter(C7_ENG, "Quality (Gessler the bootmaker)", (27, 92180, 92206, "1e59621003b9e6e9"), _whole(RETIRE, why=_HONEYCOMB)),
    151: Chapter(C7_ENG, "Expert Detectives (Mr Nath, Maya)", (22, 92230, 92251, "c702df28ccd95dfb"), _whole(RETIRE, why=_HONEYCOMB)),
    152: Chapter(C7_ENG, "The Invention of Vita-Wonk", (24, 92291, 92314, "eef6b8f7047ae956"), _whole(RETIRE, why=_HONEYCOMB)),
    153: Chapter(C7_ENG, "Fire: Friend and Foe", (27, 92352, 92378, "898468fdf3769b99"), _whole(RETIRE, why=_HONEYCOMB)),
    154: Chapter(C7_ENG, "A Bicycle in Good Repair", (26, 92402, 92427, "829d0844fca0484d"), _whole(RETIRE, why=_HONEYCOMB)),
    155: Chapter(C7_ENG, "The Story of Cricket", (33, 92472, 92504, "c8876f5c0c7dee09"), _whole(RETIRE, why=_HONEYCOMB)),
    3602: Chapter(C7_ENG, "The Squirrel (poem)", (9, 92527, 92535, "b11ccdc3e908a98d"), _whole(RETIRE, why=_HONEYCOMB)),
    3603: Chapter(C7_ENG, "The Rebel (poem)", (11, 92539, 92549, "9c441ddc4bbef3e3"), _whole(RETIRE, why=_HONEYCOMB)),
    3604: Chapter(C7_ENG, "The Shed (poem)", (10, 92553, 92562, "3970a90759061d72"), _whole(RETIRE, why=_HONEYCOMB)),
    3605: Chapter(C7_ENG, "Chivvy (poem)", (15, 92567, 92581, "89fa7e408f7d7e56"), _whole(RETIRE, why=_HONEYCOMB)),
    3606: Chapter(C7_ENG, "Trees (poem)", (8, 92583, 92590, "0f230ae92902f4b8"), _whole(RETIRE, why=_HONEYCOMB)),
    3607: Chapter(C7_ENG, "Mystery of the Talking Fan (poem)", (9, 92593, 92601, "0ee767d72cc69acc"), _whole(RETIRE, why=_HONEYCOMB)),
    3608: Chapter(C7_ENG, "Dad and the Cat and the Tree (poem)", (33, 92604, 92636, "8435759c1e86a9c5"), _whole(RETIRE, why=_HONEYCOMB)),
    3609: Chapter(C7_ENG, "Meadow Surprises (poem)", (17, 92643, 92659, "f57f97c8ac2bd91d"), _whole(RETIRE, why=_HONEYCOMB)),
    3610: Chapter(C7_ENG, "Garden Snake (poem)", (9, 92674, 92682, "8221f6d432fccc51"), _whole(RETIRE, why=_HONEYCOMB)),

    # ---------------- Class 6 English: Honeysuckle + its poems -> retire ----
    # Live Class 6 English is Poorvi (29860-29875). Poorvi's "The Kites"
    # (29873) is a DIFFERENT poem from Honeysuckle's "The Kite" -- 29873's
    # questions contain none of Harry Behn's vocabulary (dive/dip/snaps/
    # soars/tailless/sail), they are about a child and what kites symbolise.
    57: Chapter(C6_ENG, "Who Did Patrick's Homework?", (13, 91911, 91923, "3d85b9fb3ac1ad40"), _whole(RETIRE, why="Honeysuckle; not in Poorvi")),
    58: Chapter(C6_ENG, "Taro's Reward", (18, 92060, 92077, "77592bec9e7ee450"), _whole(RETIRE, why="Honeysuckle; not in Poorvi")),
    59: Chapter(C6_ENG, "How the Dog Found Himself a New Master!", (8, 91995, 92002, "36d13480403ce302"), _whole(RETIRE, why="Honeysuckle; not in Poorvi")),
    60: Chapter(C6_ENG, "An Indian-American Woman in Space (Kalpana Chawla)", (8, 92105, 92112, "7be464b5a1d47dca"), _whole(RETIRE, why="Honeysuckle; not in Poorvi")),
    61: Chapter(C6_ENG, "A Different Kind of School (Miss Beam)", (6, 92166, 92171, "2fe7b853794b40c1"), _whole(RETIRE, why="Honeysuckle; not in Poorvi")),
    63: Chapter(C6_ENG, "Fair Play (Jumman Sheikh, Algu Chowdhry)", (15, 92273, 96453, "7c47f55fd401bf47"), _whole(RETIRE, why="Honeysuckle; not in Poorvi")),
    64: Chapter(C6_ENG, "A Game of Chance (Rasheed, the Lucky Shop)", (10, 92335, 92344, "65697556e926b7be"), _whole(RETIRE, why="Honeysuckle; not in Poorvi")),
    65: Chapter(C6_ENG, "Desert Animals", (1, 92394, 92394, "9c1b7881b4e65dd1"), _whole(RETIRE, why="Honeysuckle; not in Poorvi")),
    66: Chapter(C6_ENG, "The Banyan Tree", (16, 92451, 92466, "b32761d724e8174e"), _whole(RETIRE, why="Honeysuckle; not in Poorvi")),
    3552: Chapter(C6_ENG, "The Kite (Harry Behn, poem)", (3, 92536, 92538, "4628ceea1e4edaf5"), _whole(RETIRE, why="Honeysuckle poem; Poorvi's 'The Kites' (29873) is a different poem")),
    3553: Chapter(C6_ENG, "The Quarrel (poem)", (3, 92550, 92552, "1f938a89d74533b2"), _whole(RETIRE, why="Honeysuckle poem; not in Poorvi")),
    3554: Chapter(C6_ENG, "Beauty (poem)", (4, 92563, 92566, "863ae155cc660a85"), _whole(RETIRE, why="Honeysuckle poem; not in Poorvi")),
    3598: Chapter(C6_ENG, "Honeysuckle poem (grown-ups / greens)", (1, 92582, 92582, "a488610acf6e9051"), _whole(RETIRE, why="Honeysuckle poem; not in Poorvi")),
    3599: Chapter(C6_ENG, "The Wonderful Words (poem)", (2, 92591, 92592, "5ced187bbceec05d"), _whole(RETIRE, why="Honeysuckle poem; not in Poorvi")),
    3600: Chapter(C6_ENG, "Vocation (poem)", (2, 92602, 92603, "bb057d9b02269dc5"), _whole(RETIRE, why="Honeysuckle poem; not in Poorvi")),
    3601: Chapter(C6_ENG, "Whatif (poem)", (3, 92640, 92642, "a614950350d23752"), _whole(RETIRE, why="Honeysuckle poem; not in Poorvi")),

    # ---------------- Class 6 English-2: A Pact with the Sun -> retire ------
    # chapter_master holds NO row at all for (standard 39, subject 4435), so
    # there is no target and inventing one is not allowed. Poorvi replaced both
    # Honeysuckle and A Pact with the Sun. Note the ids run the book backwards:
    # 5593 is chapter 10 and 5602 chapter 1.
    5593: Chapter(C6_ENG2, "A Strange Wrestling Match (Vijay Singh, the ghost)", (5, 92467, 92471, "edcf5da604ad8b54"), _whole(RETIRE, why="A Pact with the Sun; no live Class 6 English-2 chapter exists")),
    5594: Chapter(C6_ENG2, "What Happened to the Reptiles (Pambupatti)", (7, 92395, 92401, "5396245108bf1ff8"), _whole(RETIRE, why="A Pact with the Sun; no live Class 6 English-2 chapter exists")),
    5595: Chapter(C6_ENG2, "A Pact with the Sun (Saeeda)", (7, 92345, 92351, "5886566ed1755154"), _whole(RETIRE, why="A Pact with the Sun; no live Class 6 English-2 chapter exists")),
    5596: Chapter(C6_ENG2, "The Wonder Called Sleep", (7, 92284, 92290, "abc24ae74731d07c"), _whole(RETIRE, why="A Pact with the Sun; no live Class 6 English-2 chapter exists")),
    5597: Chapter(C6_ENG2, "The Monkey and the Crocodile", (17, 92223, 92261, "44733324fd7ad7cd"), _whole(RETIRE, why="A Pact with the Sun; no live Class 6 English-2 chapter exists")),
    5598: Chapter(C6_ENG2, "Tansen", (8, 92172, 92179, "5d6287ee00c49dcb"), _whole(RETIRE, why="A Pact with the Sun; no live Class 6 English-2 chapter exists")),
    5599: Chapter(C6_ENG2, "The Old-Clock Shop", (8, 92113, 92120, "012491356b3876fe"), _whole(RETIRE, why="A Pact with the Sun; no live Class 6 English-2 chapter exists")),
    5600: Chapter(C6_ENG2, "The Shepherd's Treasure", (7, 92078, 92084, "e97f3ef92b337cff"), _whole(RETIRE, why="A Pact with the Sun; no live Class 6 English-2 chapter exists")),
    5601: Chapter(C6_ENG2, "The Friendly Mongoose", (6, 92003, 92008, "3b5e66b1e730ca88"), _whole(RETIRE, why="A Pact with the Sun; no live Class 6 English-2 chapter exists")),
    5602: Chapter(C6_ENG2, "A Tale of Two Birds", (6, 91924, 91929, "0aac61350f279962"), _whole(RETIRE, why="A Pact with the Sun; no live Class 6 English-2 chapter exists")),

    # ---------------- Class 7 English-2: An Alien Hand -> retire ------------
    # chapter_master holds NO row for (standard 40, subject 4435).
    5442: Chapter(C7_ENG2, "A Tiger in the House", (18, 92428, 92445, "17a456bf379bbdbb"), _whole(RETIRE, why="An Alien Hand; no live Class 7 English-2 chapter exists")),
    5443: Chapter(C7_ENG2, "The Bear Story", (8, 92379, 92386, "1111a16721e6b9b7"), _whole(RETIRE, why="An Alien Hand; no live Class 7 English-2 chapter exists")),
    5444: Chapter(C7_ENG2, "Chandni (Abbu Khan's goats)", (11, 92315, 92325, "b15f4c067dc12168"), _whole(RETIRE, why="An Alien Hand; no live Class 7 English-2 chapter exists")),
    5446: Chapter(C7_ENG2, "Golu Grows a Nose", (10, 92207, 92216, "9b42e95e33be74a5"), _whole(RETIRE, why="An Alien Hand; no live Class 7 English-2 chapter exists")),
    5447: Chapter(C7_ENG2, "The Cop and the Anthem (Soapy)", (9, 92148, 92156, "f1bee68b9c549600"), _whole(RETIRE, why="An Alien Hand; no live Class 7 English-2 chapter exists")),
    5449: Chapter(C7_ENG2, "Bringing Up Kari", (8, 92045, 92052, "c60e7b2f36ffafa5"), _whole(RETIRE, why="An Alien Hand; no live Class 7 English-2 chapter exists")),
    5450: Chapter(C7_ENG2, "An Alien Hand (Tilloo)", (14, 92505, 92518, "1b549670e76dd332"), _whole(RETIRE, why="An Alien Hand; no live Class 7 English-2 chapter exists")),
    5451: Chapter(C7_ENG2, "The Tiny Teacher (the ant)", (10, 91977, 91986, "9b7aea38c4cccd4a"), _whole(RETIRE, why="An Alien Hand; no live Class 7 English-2 chapter exists")),

    # ---------------- Class 9 English: Beehive / Moments -> retire ----------
    # Live Class 9 English (8622-8638) is the NEP replacement book: How I
    # Taught My Grandmother to Read, The Pot Maker, Winds of Change, Vitamin-M,
    # ... None of the Beehive texts survives into it.
    915: Chapter(C9_ENG, "A Slumber Did My Spirit Seal (Wordsworth)", (12, 84749, 84760, "18c7edbfdb22cf03"), _whole(RETIRE, why="Beehive poem; live Class 9 English is the NEP replacement book")),
    3627: Chapter(C9_ENG, "Kathmandu (the shrines)", (6, 84743, 84748, "f6b53f46ad83e54a"), _whole(RETIRE, why="Beehive; live Class 9 English is the NEP replacement book")),
    3628: Chapter(C9_ENG, "If I Were You (Gerrard and the intruder)", (13, 84761, 84773, "0e10cc5ae1ecf2e2"), _whole(RETIRE, why="Beehive; live Class 9 English is the NEP replacement book")),

    # ---------------- Class 9 Science: the old 15-chapter book --------------
    # The crosswalk calls all 14 out_of_syllabus at a flat 0.900. Ten of them
    # have an unmistakable counterpart in the live NEP book, verified by
    # reading the live chapter's own questions:
    891: Chapter(C9_SCI, "Matter in Our Surroundings (states, Kelvin, sublimation)", (6, 84774, 84779, "1b2ac499fe22e813"),
                 _whole(RETIRE, why="no live chapter covers the three states of matter; 8604's sublimation/evaporation questions are all separation technique (crystallisation, naphthalene/salt/sand), not particle arrangement or the Kelvin scale")),
    892: Chapter(C9_SCI, "Is Matter Around Us Pure (Tyndall, solutions, mass by volume)", (6, 84903, 84908, "ea3c8339ae62ac53"),
                 _whole(REPOINT, 8604, "8604 Exploring Mixtures and their Separation is the same ground: its live questions are m/m and v/v percentage and solubility curves")),
    893: Chapter(C9_SCI, "Atoms and Molecules (Dalton, molecular masses, formulae)", (63, 85057, 85119, "5cd5074341325d60"),
                 _whole(REPOINT, 8614, "8614 Atomic Foundations of Matter carries Law of Conservation of Mass and mass-ratio questions -- same chapter, renamed")),
    894: Chapter(C9_SCI, "Structure of the Atom (Thomson, Rutherford)", (20, 85290, 85309, "6a9f0a9dbfabe38e"),
                 _whole(REPOINT, 8607, "8607 Journey Inside the Atom's live questions are Thomson's plum pudding and Rutherford's gold foil")),
    895: Chapter(C9_SCI, "The Fundamental Unit of Life (raisins, Robert Hooke)", (4, 85460, 85463, "7d74bb063159d1e5"),
                 _whole(REPOINT, 8593, "8593 Cell: The Building Block of Life covers cell wall and the potato osmosis activity")),
    896: Chapter(C9_SCI, "Tissues (tendons, apical meristem, epithelium)", (3, 85591, 85593, "ff31f40dcc8ae1b7"),
                 _whole(REPOINT, 8599, "8599 Tissues in Action covers sclerenchyma and epidermal cuticle")),
    897: Chapter(C9_SCI, "Diversity in Living Organisms (fungi, five kingdoms)", (7, 85875, 85881, "329905265d409e2d"),
                 _whole(REPOINT, 8617, "8617 Patterns in Life: Diversity and Classification covers the cellular-structure criterion, Bryophyta, Pteridophyta")),
    898: Chapter(C9_SCI, "Motion (Joseph jogging, distance vs displacement)", (3, 86092, 86094, "75ba29e42d33ab46"),
                 _whole(REPOINT, 8600, "8600 Describing Motion Around Us is distance/displacement and average velocity")),
    899: Chapter(C9_SCI, "Force and Laws of Motion (insect on the windscreen)", (4, 86410, 86413, "562969d3d2c537d9"),
                 _whole(REPOINT, 8605, "8605 How Forces Affect Motion covers net force, the first law and inertia")),
    900: Chapter(C9_SCI, "Gravitation (g on another planet, free fall)", (2, 86610, 86611, "cb0f301d98ecf90d"),
                 _whole(RETIRE, why="the live book has no Gravitation chapter. 8605 teaches gravity only as a non-contact force and weight=mg; neither question can be answered from it -- 86610 needs g proportional to M/R^2. JUDGEMENT CALL, 2 questions")),
    901: Chapter(C9_SCI, "Work and Energy", (4, 86769, 86772, "24bdc2dd1f9278f7"),
                 _whole(REPOINT, 8606, "8606 Work, Energy, and Simple Machines -- same chapter, extended")),
    902: Chapter(C9_SCI, "Sound (echocardiography, bats)", (2, 86893, 86894, "87c1ba4c4a363787"),
                 _whole(REPOINT, 8615, "8615 Sound Waves: Characteristics and Applications -- same chapter, renamed")),
    903: Chapter(C9_SCI, "Why Do We Fall Ill (dengue, health)", (3, 87053, 87055, "18f866674ab5b026"),
                 _whole(RETIRE, why="no live chapter covers disease; a keyword sweep for dengue/malaria/immunis/pathogen/antibiotic over all 13 live chapters returns 2 incidental hits in 2,674 questions")),
    905: Chapter(C9_SCI, "Improvement in Food Resources (poultry, Aseel/Busra)", (5, 87194, 87198, "79f6180cc5d6a221"),
                 _whole(RETIRE, why="no live chapter covers crop or livestock improvement; 8618's crop hits are food webs, not husbandry")),

    # ---------------- Class 8 English: Honeydew, still the live book --------
    # Live 25863-25870 are Honeydew chapters 1-8. The orphan ids run in the
    # same order, and every one I could identify sat at its own position.
    266: Chapter(C8_ENG, "The Best Christmas Present in the World", (4, 91987, 91990, "11958abf7f61eefd"), _whole(REPOINT, 25863, "Jim's diary after the war; Honeydew ch1")),
    267: Chapter(C8_ENG, "The Tsunami", (4, 92053, 92056, "feb107b8511b6ac7"), _whole(REPOINT, 25864, "Andaman and Nicobar relief work; Honeydew ch2")),
    268: Chapter(C8_ENG, "Glimpses of the Past", (6, 92097, 92102, "9e43cae0ce74e443"), _whole(REPOINT, 25865, "'We must educate our brothers', farmers' grievances; Honeydew ch3")),
    269: Chapter(C8_ENG, "Bepin Choudhury's Lapse of Memory", (6, 92157, 92162, "7641fc0ea8855b19"), _whole(REPOINT, 25866, "names Bepin in the questions; Honeydew ch4")),
    270: Chapter(C8_ENG, "The Summit Within", (4, 92217, 92220, "6c2996041aa09820"), _whole(REPOINT, 25867, "'Mountains are nature's ...', endure/persist; Honeydew ch5")),
    271: Chapter(C8_ENG, "This is Jody's Fawn", (8, 92262, 92269, "bdb70c00820369eb"), _whole(REPOINT, 25868, "Penny and Jody; killing an animal to save a human life; Honeydew ch6")),
    272: Chapter(C8_ENG, "A Visit to Cambridge (grammar exercises only)", (6, 92326, 92331, "e136adce2a59846b"),
                 _whole(REPOINT, 25869, "position 7 in an otherwise exact sequence; all six are grammar drills with no story anchor, so the positional argument carries this one"),
                 note="weakest repoint in this cluster: no topical content, decided on position"),
    273: Chapter(C8_ENG, "A Short Monsoon Diary", (7, 92387, 92393, "58a2d2a42a9d2f06"), _whole(REPOINT, 25870, "monsoon word list, 'Bijju wandered into the garden'; Honeydew ch8")),
    274: Chapter(C8_ENG, "The Great Stone Face (grammar exercises)", (5, 92446, 92450, "d20a0f851cabe1bf"),
                 _whole(RETIRE, why="sits past Honeydew ch8; The Great Stone Face I/II were rationalised out and the live book stops at 8 chapters")),
    275: Chapter(C8_ENG, "The Great Stone Face (the poet, the native valley, the preacher)", (4, 92519, 92522, "d502f90f3bc4a127"),
                 _whole(RETIRE, why="The Great Stone Face was rationalised out of Honeydew")),
    3617: Chapter(C8_ENG, "When I Set Out for Lyonnesse (Hardy, poem)", (3, 92637, 92639, "5a5e571b48f9eece"),
                 _whole(RETIRE, why="Honeydew poem, dropped. The crosswalk's nearest_surviving -> 25869 'A Visit to Cambridge' at 0.75 is wrong: a Hardy poem about Lyonnesse is not the Stephen Hawking interview")),
    3618: Chapter(C8_ENG, "A Short Monsoon Diary (comprehension set)", (14, 92660, 92673, "ea4b5db9ef86386d"),
                 _whole(REPOINT, 25870, "all 14 read as A Short Monsoon Diary -- Chuchundar, Bijju, the cobra lily, tin roofs, the bird count. A second question set for the same chapter as 273, not a duplicate of it"),
                 note="second set landing on 25870; the duplicate check runs over both"),

    # ---------------- Class 8 English-2: It So Happened ---------------------
    # Live 25871-25878 are the rationalised 8 chapters and ALL have 0
    # questions, so repointing here cannot collide. The Open Window and both
    # Comet chapters were dropped.
    5547: Chapter(C8_ENG2, "The Open Window", (3, 92332, 92334, "4df6ebb660a8cef5"),
                  _whole(RETIRE, why="'Is this a mystery story?' plus the irony exercise -- The Open Window, rationalised out of It So Happened")),
    5548: Chapter(C8_ENG2, "The Fight", (3, 92270, 92272, "9dbb53cacc9b50e7"),
                  _whole(REPOINT, 25876, "'Is fighting the only way of resolving differences of opinion?' -- The Fight. The crosswalk left this as needs_review")),
    5549: Chapter(C8_ENG2, "Princess September", (2, 92221, 92222, "4dc9620d09516518"), _whole(REPOINT, 25875, "the unkind sisters and the importance of music")),
    5550: Chapter(C8_ENG2, "The Comet II", (4, 92523, 92526, "6b272c26a1926a40"),
                  _whole(RETIRE, why="'Should a scientist's findings be suppressed?' -- The Comet II, rationalised out")),
    5552: Chapter(C8_ENG2, "The Treasure Within", (3, 92163, 92165, "23e0a3d52b1e2c5b"), _whole(REPOINT, 25874, "the 'unusual learner' who does not do well at school")),
    5553: Chapter(C8_ENG2, "The Selfish Giant", (2, 92103, 92104, "781f0f1744b753f2"), _whole(REPOINT, 25873, "the child with nail marks, the garden, the Giant")),
    5554: Chapter(C8_ENG2, "Children at Work", (3, 92057, 92059, "2e8a3c645696dea8"), _whole(REPOINT, 25872, "Velu and Jaya; 'what one throws away as waste'")),
    5653: Chapter(C8_ENG2, "How the Camel Got His Hump", (4, 91991, 91994, "b2e16d9332febf95"), _whole(REPOINT, 25871, "'Can this story be factually true?', how the world began, active or idle")),

    # ---------------- Class 8 Social Sciences ------------------------------
    979: Chapter(C8_SAS, "Mineral and Power Resources", (52, 110180, 110231, "a1661aeae97fa587"),
                 _whole(RETIRE, why="ferrous minerals, mineral fuels, limestone, inaccessible minerals. Live Class 8 Geography is the rationalised 5-chapter book -- Resources, Land/Soil/Water, Agriculture, Industries, Human Resources -- and Mineral and Power Resources is the chapter that was removed. The crosswalk left this as needs_review"),
                 note="largest single retire that is not a whole book: 52 questions"),

    # ---------------- Class 10 Economics (not NEP-replaced) ----------------
    6248: Chapter(C10_ECO, "Development", (13, 87356, 87368, "03934fd643089d31"), _whole(REPOINT, 23700, "how development is determined, per capita income, the World Bank criterion")),
    6249: Chapter(C10_ECO, "Sectors of the Indian Economy", (24, 87404, 87427, "55915a4a77a6bcea"), _whole(REPOINT, 23701, "service-sector employment, classification by ownership, classify the workers")),
    6250: Chapter(C10_ECO, "Money and Credit", (13, 87441, 87453, "8d6f4ffda79c186a"), _whole(REPOINT, 23702, "double coincidence of wants, banks as intermediaries, the ten-rupee note")),
    6251: Chapter(C10_ECO, "Globalisation and the Indian Economy", (12, 87479, 87490, "0181fad288b260fa"), _whole(REPOINT, 23703, "barriers to foreign trade, MNCs, flexibility in labour laws")),

    # ---------------- Class 10 Social Sciences (Democratic Politics II) ----
    1040: Chapter(C10_SAS, "Federalism", (11, 87390, 87400, "cc5da8539cac13b7"), _whole(REPOINT, 23711, "shade three federal countries; features of Indian federalism")),
    1042: Chapter(C10_SAS, "Gender, Religion and Caste", (12, 87466, 87477, "5ecdd84fc3bfe383"), _whole(REPOINT, 23712, "discrimination against women, communal politics, caste inequalities")),
    1044: Chapter(C10_SAS, "Political Parties", (11, 87511, 87521, "a38b8e74c6f5ff72"), _whole(REPOINT, 23713, "functions of parties, challenges, reforms to strengthen them")),
    1045: Chapter(C10_SAS, "Outcomes of Democracy", (7, 87532, 87538, "0b7bcfb0aaaff3f0"), _whole(REPOINT, 23714, "accountable, responsive and legitimate government; accommodating diversity")),
    1046: Chapter(C10_SAS, "Challenges to Democracy", (7, 87539, 87545, "d9c19777ae1a3ddf"),
                  _whole(RETIRE, why="the cartoons-and-challenges exercise set. Live Class 10 Social Sciences is the rationalised 5-chapter book and Challenges to Democracy is gone. The crosswalk's nearest_surviving -> 23714 at 0.65 would file it under Outcomes of Democracy, a different chapter")),

    # ---------------- Class 10 Social Sciences-2 (Contemporary India II) ---
    6236: Chapter(C10_SAS2, "Resources and Development", (5, 87371, 87375, "2389d7bec377afed"), _whole(REPOINT, 23693, "iron ore as a resource type, replenishable resources")),
    6238: Chapter(C10_SAS2, "Water Resources", (1, 87456, 87456, "0dc270c52da15a3e"), _whole(REPOINT, 23695, "classify each situation as suffering from water scarcity")),
    6239: Chapter(C10_SAS2, "Agriculture", (2, 87493, 87494, "d11f4032e2da95c5"), _whole(REPOINT, 23696, "Intensive Subsistence Farming, rabi crops")),
    6240: Chapter(C10_SAS2, "Minerals and Energy Resources", (2, 87506, 87507, "99208e63148aad8a"), _whole(REPOINT, 23697, "the mineral formed by decomposition of rocks; the mineral crossword")),
    6241: Chapter(C10_SAS2, "Manufacturing Industries", (9, 87523, 87531, "3a19ac6a71a37dea"), _whole(REPOINT, 23698, "limestone as a raw material, integrated steel plants, the public-sector steel agency")),

    # ---------------- Class 10 Social Sciences-3 (India and the Contemporary World II)
    6243: Chapter(C10_SAS3, "The Rise of Nationalism in Europe", (5, 87376, 87380, "e3677a185010114c"), _whole(REPOINT, 23705, "Mazzini, Cavour, the Greek war of independence, Marianne and Germania")),
    6244: Chapter(C10_SAS3, "Nationalism in India", (4, 87431, 87434, "d819753a1bd602f0"), _whole(REPOINT, 23706, "Satyagraha, Jallianwalla Bagh, the Simon Commission")),
    6247: Chapter(C10_SAS3, "Print Culture and the Modern World", (3, 87508, 87510, "ff77ff8c70053aee"), _whole(REPOINT, 23709, "woodblock print after 1295, the Gutenberg Press, Martin Luther")),

    # ---------------- Class 10 Hindi-B -------------------------------------
    6253: Chapter(C10_HINB, "तोप (Veeren Dangwal)", (19, 104437, 104455, "ed5661b83324c55b"),
                  _whole(REPOINT, 23758, "all 19 are about the poem तोप -- its message, why the British army used the cannon, why heirlooms are preserved. 23758 is तोप and already holds 107 questions, so the duplicate check matters here"),
                  note="target already holds 107 questions; duplicates are retired rather than repointed"),

    # ---------------- Class 6 Mathematics: old book -> Ganita Prakash ------
    # These orphans carry clean `concept`/`subconcept` metadata, which is what
    # the split rules below key on.
    43: Chapter(C6_MAT, "Knowing Our Numbers (large numbers, place value)", (7, 96678, 96685, "59d9818eb60b522b"),
                _whole(RETIRE, why="Ganita Prakash 6 has no large-numbers chapter; 'Large Numbers Around Us' is Ganita Prakash 7 ch1, a different class")),
    46: Chapter(C6_MAT, "Basic Geometrical Ideas (curves, polygons, line segments)", (4, 96707, 96713, "afc53a937cd498a5"),
                _whole(LEAVE, why="three of four are point/line/line-segment and would fit 29825 Lines and Angles, but the fourth is a triangle-common-side question and GP6 geometry is redistributed across 29825 and 29831. Editorial call")),
    47: Chapter(C6_MAT, "Understanding Elementary Shapes (triangle classification, quadrilaterals)", (6, 96717, 96723, "e6f4a26ff94c4c66"),
                _whole(LEAVE, why="classifying triangles by side and angle is Ganita Prakash 7 ch7 'A Tale of Three Intersecting Lines', not a GP6 chapter; 29831 Playing with Constructions is about constructing, not classifying. Editorial call")),
    53: Chapter(C6_MAT, "Algebra (the idea of a variable)", (2, 96777, 96783, "3cfabda12d1b7940"),
                _whole(RETIRE, why="Ganita Prakash 6 has no algebra chapter; 'Expressions Using Letter-Numbers' is GP7 ch4")),
    54: Chapter(C6_MAT, "Ratio and Proportion", (4, 96786, 96793, "dc493d3473e5a9b0"),
                _whole(RETIRE, why="Ganita Prakash 6 has no ratio-and-proportion chapter")),
    4646: Chapter(C6_MAT, "Whole Numbers (patterns, additive/multiplicative identity)", (7, 96686, 96694, "e2d39f827b711cbb"),
                  _whole(LEAVE, why="the questions are shopping-bill arithmetic and the identity properties. 29824 Patterns in Mathematics is about pattern sequences and 29826 Number Play about the taller-neighbours rule -- neither is this. Editorial call")),
    4647: Chapter(C6_MAT, "Playing with Numbers (factors and multiples)", (5, 96696, 96705, "07437824e262b8b0"),
                  _whole(REPOINT, 29828, "all five are factors, multiples and co-prime pairs -- 29828 Prime Time")),
    4649: Chapter(C6_MAT, "Integers AND Fractions -- two source chapters in one id", (14, 96726, 96745, "5c4f912104d8a343"),
                  [Rule(REPOINT, 29833, "sea-level elevation, submarine depth, the lift number line -- 29833 The Other Side of Zero",
                        field="subconcept", pattern=r"Positive and Negative Integers|Number Line"),
                   Rule(REPOINT, 29830, "halves of a cross-country distance, sharing a pizza -- 29830 Fractions",
                        field="subconcept", pattern=r"Multiplication and Division of Fraction")],
                  note="SPLIT: the image names give it away -- 'Maths C 6 Q n' on the integer rows and 'Maths C 7 Q n' on the fraction rows. One orphan id holds two source chapters"),
    4650: Chapter(C6_MAT, "Decimals (addition and subtraction)", (7, 96747, 96755, "8cc7fb4d2ec66a84"),
                  _whole(RETIRE, why="Ganita Prakash 6 has no decimals chapter; 'A Peek Beyond the Point' is GP7 ch3")),
    4652: Chapter(C6_MAT, "Data Handling (organisation of data)", (2, 96763, 96765, "1a3bbb8d2454eb26"),
                  _whole(REPOINT, 29827, "organisation of data -- 29827 Data Handling and Presentation")),
    4653: Chapter(C6_MAT, "Mensuration (perimeter and area of a rectangle)", (3, 96769, 96772, "1977cbc39762c267"),
                  _whole(REPOINT, 29829, "area and perimeter of a rectangle -- 29829 Perimeter and Area")),
    4655: Chapter(C6_MAT, "Symmetry (lines of symmetry)", (6, 96795, 96803, "0f23a1d5a883aa66"),
                  _whole(REPOINT, 29832, "all six are lines of symmetry -- 29832 Symmetry")),
    4656: Chapter(C6_MAT, "Symmetry AND circle parts -- two source chapters in one id", (4, 96808, 96814, "9149a1ec691f4d8e"),
                  [Rule(REPOINT, 29832, "lines of symmetry -- 29832 Symmetry",
                        field="subconcept", pattern=r"Line of Symmetry"),
                   Rule(LEAVE, why="chord, radius and concentric circles are Ganita Prakash 6 ch8 'Playing with Constructions' material, but that chapter is about constructing circles rather than naming their parts. Editorial call",
                        field="subconcept", pattern=r"Chord of a Circle|Radius of a circle")],
                  note="SPLIT: two of four are symmetry, two are circle parts"),

    # ---------------- Class 6 Science: old book -> Curiosity ---------------
    26: Chapter(C6_SCI, "Food: Where Does It Come From (plants as food)", (1, 96823, 96823, "df801b00ff6751a4"),
                _whole(REPOINT, 29836, "food sources -- 29836 Mindful Eating: A Path to a Healthy Body opens from the reader's own plate and the week-of-meals table")),
    27: Chapter(C6_SCI, "Components of Food (nutrients)", (2, 96845, 96848, "80d472ccb9844b21"),
                _whole(REPOINT, 29836, "nutrients in plants and animals -- 29836 Mindful Eating")),
    31: Chapter(C6_SCI, "Separation of Substances (filtration, evaporation, solubility)", (5, 96874, 96880, "62b9454dc25c69c2"),
                _whole(REPOINT, 29842, "filtration, evaporation, how much a solvent will dissolve -- 29842 Methods of Separation in Everyday Life")),
    33: Chapter(C6_SCI, "Getting to Know Plants (root, leaf, flower)", (5, 96891, 96900, "3ab846efec4e1f47"),
                _whole(LEAVE, why="29835 Diversity in the Living World does reach leaf venation and root types, but it is built round a habitat walk rather than plant morphology, and Curiosity 6 has no plant-parts chapter. Editorial call")),
    35: Chapter(C6_SCI, "The Living Organisms and their Surroundings", (3, 96916, 96920, "37da32d2890c1b18"),
                _whole(REPOINT, 29843, "response to stimuli, living things around us, aquatic habitats -- 29843 Living Creatures: Exploring their Characteristics")),
    36: Chapter(C6_SCI, "Motion and Measurement of Distances", (4, 96922, 96929, "46b5178db9b67ffa"),
                _whole(REPOINT, 29838, "measurement and types of motion -- 29838 Measurement of Length and Motion")),
    37: Chapter(C6_SCI, "Light, Shadows and Reflections", (4, 96935, 96940, "c851380debdd92e8"),
                _whole(RETIRE, why="Curiosity 6 has no light chapter; 'Light: Shadows and Reflections' is Curiosity 7 ch11, a different class")),
    4657: Chapter(C6_SCI, "Fibre to Fabric (characteristics of fibre)", (1, 96857, 96857, "f7fc84d1420684d2"),
                  _whole(LEAVE, why="one question on fibre characteristics. 29839 Materials Around Us covers material properties generally but Curiosity 6 has no fibre-and-fabric chapter. Too thin to call")),
    4658: Chapter(C6_SCI, "Sorting Materials into Groups (float/sink, solubility, transparency)", (14, 96862, 129476, "488a156826f331a2"),
                  _whole(REPOINT, 29839, "floating and sinking, soluble and insoluble, transparency -- 29839 Materials Around Us is exactly this chapter renamed")),
    4659: Chapter(C6_SCI, "Changes Around Us (reversible and irreversible)", (6, 96881, 96890, "abaaa3c4c8230a67"),
                  _whole(RETIRE, why="Curiosity 6 has no changes chapter; 'Changes Around Us: Physical and Chemical' is Curiosity 7 ch5, a different class")),
    4660: Chapter(C6_SCI, "Body Movements (joints and muscles)", (3, 96903, 96907, "d2040894cb3548a2"),
                  _whole(RETIRE, why="no live Class 6 chapter covers the skeleton or movement")),
    4661: Chapter(C6_SCI, "Electricity and Circuits", (7, 96942, 96950, "9bf7d3a4927b5a8e"),
                  _whole(RETIRE, why="Curiosity 6 has no electricity chapter; 'Electricity: Circuits and their Components' is Curiosity 7 ch3, a different class")),
    4662: Chapter(C6_SCI, "Fun with Magnets", (2, 96952, 96957, "a50d155a572cae39"),
                  _whole(REPOINT, 29837, "magnetic and non-magnetic objects, finding directions -- 29837 Exploring Magnets")),
    4663: Chapter(C6_SCI, "Water (rainwater harvesting, heavy rain)", (3, 96961, 96966, "664cd2a0fc98a012"),
                  _whole(LEAVE, why="splits between 29841 A Journey through States of Water (the water cycle) and 29844 Nature's Treasures (water as a resource); rainwater harvesting sits across both. Editorial call")),
    4664: Chapter(C6_SCI, "Air Around Us (composition, pollution)", (4, 96969, 96976, "19b95b80bfc370b5"),
                  _whole(LEAVE, why="29844 Nature's Treasures treats air as a natural resource but Curiosity 6 has no air chapter, and air pollution is not in its concept list. Editorial call")),
    4665: Chapter(C6_SCI, "Garbage In, Garbage Out (vermicomposting, recycling)", (6, 96979, 96986, "586cbe0f4009ef45"),
                  _whole(RETIRE, why="no live Class 6 chapter covers waste management")),

    # ---------------- Class 9 Social Sciences: cross-subject, left alone ---
    # Read and identified, but every candidate target sits under subject 4469
    # (Social Sciences-2) while these questions are subject 4064. 8613
    # Democracy's key_concepts cover Democracy, Fundamental Rights and
    # Separation of Powers, and 8619 Elections covers the electoral machinery,
    # so 949/951/952/953 have real homes -- but reaching them means moving
    # subject_id too, and that is an editorial decision, not this pass.
    949: Chapter(C9_SAS, "What is Democracy? Why Democracy?", (9, 87345, 87353, "ae801c494da85520"),
                 _whole(LEAVE, why="content matches 8613 Democracy, but 8613 is subject 4469 and these rows are 4064; a cross-subject repoint needs subject_id moved as well")),
    950: Chapter(C9_SAS, "Constitutional Design (South Africa, the Constituent Assembly)", (9, 87381, 87389, "40b794a6cbac406c"),
                 _whole(LEAVE, why="no live chapter covers the making of the Constitution; 8613 Democracy has no Constituent Assembly concept, and the Constitution chapter in the NEP books is Class 7")),
    951: Chapter(C9_SAS, "Electoral Politics", (6, 87435, 87440, "b6e9337e01e5728b"),
                 _whole(LEAVE, why="content matches 8619 Elections, but 8619 is subject 4469 and these rows are 4064")),
    952: Chapter(C9_SAS, "Working of Institutions", (9, 87457, 87465, "58fff6d4c6f59023"),
                 _whole(LEAVE, why="content matches 8613 Democracy's Separation of Powers concept, but that is subject 4469 and these rows are 4064")),
    953: Chapter(C9_SAS, "Democratic Rights", (8, 87496, 87503, "66cd554f51205bcb"),
                 _whole(LEAVE, why="content matches 8613 Democracy's Fundamental Rights concept, but that is subject 4469 and these rows are 4064")),

    # ---------------- Class 9 Social Sciences-2: old Contemporary India I --
    5476: Chapter(C9_SAS2, "Natural Vegetation and Wildlife (map work)", (1, 87522, 87522, "8fc8114de830792b"),
                  _whole(LEAVE, why="India-specific map work; live 8609/8610 are physical-process chapters (plate tectonics, atmospheric layers). The same map exercise also appears under 5477, so the chapter boundaries here are unreliable")),
    5477: Chapter(C9_SAS2, "Climate / vegetation map work", (2, 87504, 87505, "b80e7e84278bf4ac"),
                  _whole(LEAVE, why="same map exercise as 5476 and 5478 -- the questions repeat across chapters, so no chapter boundary can be trusted")),
    5478: Chapter(C9_SAS2, "Drainage / climate map work", (2, 87491, 87492, "76a84f41b8f0c26b"),
                  _whole(LEAVE, why="'Why are rivers important' plus a rainfall map that also sits under 5477")),
    5479: Chapter(C9_SAS2, "Physical Features (Karakoram, Zaskar) / lakes", (2, 87454, 87455, "8a92c65c38464b68"),
                  _whole(LEAVE, why="India-specific relief map work; 8609 Shaping of the Earth's Surface is about tectonic process, not Indian ranges")),
    5480: Chapter(C9_SAS2, "India size and location / physical features", (2, 87428, 87429, "00eca79d49ee1c8a"),
                  _whole(LEAVE, why="the same mountain-ranges map exercise as 5479")),
    5481: Chapter(C9_SAS2, "Pastoralists / map reading", (2, 87369, 87370, "bc252448150b3bb2"),
                  _whole(LEAVE, why="one pastoralism question and the island map exercise that also sits under 5480")),

    # ---------------- Class 9 Economics, Class 9 Social Sciences-3 ---------
    5472: Chapter(C9_ECO, "Food Security in India", (1, 87478, 87478, "43510d0b8bc710b3"),
                  _whole(RETIRE, why="MSP, buffer stock, issue price, fair price shops. The live Class 9 economics chapters are 8620 Problem of Choice (scarcity, opportunity cost) and 8621 The Price Puzzle (demand and supply) -- price theory, not food policy")),
    5474: Chapter(C9_ECO, "People as Resource", (3, 87401, 87403, "cbc4901a52d094a7"),
                  _whole(RETIRE, why="human capital and health in working life; no counterpart in 8620/8621, which are scarcity/choice and demand/supply")),
    5475: Chapter(C9_ECO, "The Story of Village Palampur / Poverty as a Challenge", (2, 87354, 87355, "093d1cf2c5b72c27"),
                  _whole(RETIRE, why="the village census exercise and Savita's loan from Tejpal Singh; no counterpart in 8620/8621")),
    5483: Chapter(C9_SAS3, "Nazism and the Rise of Hitler", (1, 87495, 87495, "6e05ee77e35a0041"),
                  _whole(RETIRE, why="the live Class 9 history chapters are 8611 Early Humans and Beginning of Civilisation and 8612 State and Society up to 1000 CE; twentieth-century Europe is not in the NEP Class 9 book")),
    5485: Chapter(C9_SAS3, "Socialism in Europe and the Russian Revolution", (1, 87430, 87430, "9d84558892f6d5e9"),
                  _whole(RETIRE, why="Kulaks, the Duma, the Liberals, Stalin -- no counterpart in 8611/8612")),

    # ---------------- Class 7 Science --------------------------------------
    8061: Chapter(C7_SCI, "generic 'science in daily life' pair", (2, 149756, 149757, "49326e6c14f911c4"),
                  _whole(LEAVE, why="'how science has improved our daily lives' and 'how science helped understand weather patterns'. 25913 The Ever-Evolving World of Science is a plausible home, but two questions this generic would match almost any intro chapter and there is nothing to anchor on")),
}


# --------------------------------------------------------------------------
# normalisation, for the duplicate check
# --------------------------------------------------------------------------

_MOJIBAKE = re.compile(r"[ÂÃâ][\u0080-¿]")
_NONWORD = re.compile(r"[^0-9a-zऀ-ॿ]+")


def repair(s: str) -> str:
    """Undo the latin1/utf8 double-encoding these LMS-native rows carry."""
    if not s:
        return ""
    if _MOJIBAKE.search(s):
        try:
            return s.encode("latin-1", "strict").decode("utf-8", "strict")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return s
    return s


def stem(s: str, width: int = 120) -> str:
    s = unicodedata.normalize("NFKC", repair(s or "")).lower()
    return _NONWORD.sub(" ", s).strip()[:width]


def fingerprint(ids) -> str:
    return hashlib.sha256(",".join(str(i) for i in ids).encode()).hexdigest()[:16]


# --------------------------------------------------------------------------


def chapter_label(db, cid):
    row = db.execute(text(
        "SELECT c.chapter_name, s.subject_name, st.name FROM chapter_master c "
        "  LEFT JOIN subject s ON s.id=c.subject_id "
        "  LEFT JOIN standard st ON st.id=c.standard_id WHERE c.id=:c"), {"c": cid}).fetchone()
    if not row:
        return f"{cid} <NO chapter_master ROW>"
    return f"{cid}  Class {row[2]} / {row[1]} / {row[0]}"


def do_list(db):
    tally: dict[str, dict[str, int]] = {}
    for cid, ch in PLAN.items():
        n = ch.guard[0]
        bucket = tally.setdefault(ch.cluster, {REPOINT: 0, RETIRE: 0, LEAVE: 0, "chapters": 0})
        bucket["chapters"] += 1
        if len(ch.rules) == 1:
            bucket[ch.rules[0].action] += n
        else:
            bucket["split"] = bucket.get("split", 0) + n
    print(f"\n  {'cluster':<30} {'ch':>3} {'repoint':>8} {'retire':>7} {'leave':>6} {'split':>6}")
    print("  " + "-" * 66)
    tot = {REPOINT: 0, RETIRE: 0, LEAVE: 0, "split": 0, "chapters": 0}
    for cluster in sorted(tally, key=lambda k: -sum(v for x, v in tally[k].items() if x != "chapters")):
        b = tally[cluster]
        print(f"  {cluster:<30} {b['chapters']:>3} {b[REPOINT]:>8} {b[RETIRE]:>7} "
              f"{b[LEAVE]:>6} {b.get('split', 0):>6}")
        for k in tot:
            tot[k] += b.get(k, 0)
    print("  " + "-" * 66)
    print(f"  {'TOTAL':<30} {tot['chapters']:>3} {tot[REPOINT]:>8} {tot[RETIRE]:>7} "
          f"{tot[LEAVE]:>6} {tot['split']:>6}")
    print(f"\n  {sum(v for k, v in tot.items() if k != 'chapters')} questions in "
          f"{tot['chapters']} chapters.  Run one cluster at a time with --chapter <id>.\n")
    return 0


def do_audit(db):
    """Plan vs database: every orphan chapter must be in the plan and agree."""
    rows = db.execute(text(
        "SELECT q.chapter_id, COUNT(*) FROM lms_question_master q "
        "  LEFT JOIN chapter_master c ON c.id=q.chapter_id "
        " WHERE q.deleted_at IS NULL AND q.chapter_id IS NOT NULL AND c.id IS NULL "
        f"   AND q.standard_id IN {STANDARDS} GROUP BY q.chapter_id")).fetchall()
    live = {int(c): int(n) for c, n in rows}
    # A chapter that has been applied has no orphan rows left, which is the
    # goal, not a fault. A chapter whose only decisions were `leave` keeps all
    # of its rows, also expected. Anything else is drift.
    bad = done = left_open = 0
    for cid in sorted(set(live) | set(PLAN)):
        ch = PLAN.get(cid)
        if ch is None:
            print(f"  UNPLANNED  {cid}  {live[cid]} questions -- not in the plan"); bad += 1
            continue
        has_leave = any(r.action == LEAVE for r in ch.rules)
        all_leave = all(r.action == LEAVE for r in ch.rules)
        if cid not in live:
            done += 1
        elif live[cid] == ch.guard[0] and all_leave:
            left_open += live[cid]            # nothing to apply here, by decision
        elif live[cid] == ch.guard[0]:
            print(f"  PENDING    {cid}  {live[cid]} questions, not yet applied")
        elif live[cid] < ch.guard[0] and has_leave:
            # a split chapter, partly applied: the repoint/retire rules ran and
            # the rows belonging to its `leave` rule are what is left behind.
            left_open += live[cid]
            done += 1
        else:
            print(f"  DRIFT      {cid}  planned {ch.guard[0]}, found {live[cid]}"); bad += 1
    print(f"\n  {len(PLAN)} chapters in the plan: {done} fully applied, "
          f"{len(live)} still holding orphan rows ({sum(live.values())} questions, "
          f"{left_open} of them deliberate `leave` decisions).")
    print("  plan and database agree.\n" if not bad else f"  {bad} disagreement(s).\n")
    return 1 if bad else 0


def run_cluster(db, cid, apply):
    ch = PLAN.get(cid)
    if ch is None:
        print(f"  {cid} is not in the plan. --list shows the clusters, --audit checks coverage.")
        return 2

    n_exp, lo_exp, hi_exp, sha_exp = ch.guard
    print(f"\n  chapter_id {cid}   {ch.cluster}")
    print(f"  reads as   {ch.was}")
    if ch.note:
        print(f"  note       {ch.note}")

    rows = db.execute(text(
        "SELECT id, question_title, COALESCE(subconcept,'') FROM lms_question_master "
        " WHERE chapter_id=:c AND deleted_at IS NULL "
        f"   AND standard_id IN {STANDARDS} ORDER BY id"), {"c": cid}).fetchall()
    if not rows:
        print("\n  no live orphan rows left here -- already resolved, or the ids moved.")
        return 0

    ids = [int(r[0]) for r in rows]
    sha = fingerprint(ids)
    ok = (len(ids), ids[0], ids[-1], sha) == (n_exp, lo_exp, hi_exp, sha_exp)
    print(f"\n  guard      recorded {n_exp} rows {lo_exp}-{hi_exp} sha {sha_exp}")
    print(f"             found    {len(ids)} rows {ids[0]}-{ids[-1]} sha {sha}"
          f"   {'OK' if ok else 'MISMATCH'}")
    if not ok:
        print("\n  REFUSING the whole cluster: these are not the rows that were read.\n"
              "  Re-read the chapter and update its entry in PLAN before retrying.")
        return 1

    # every row must match exactly one rule
    assigned, unmatched, ambiguous = [], [], []
    for qid, title, sub in rows:
        hits = [r for r in ch.rules if r.matches(str(title or ""), str(sub or ""))]
        if not hits:
            unmatched.append((qid, title, sub))
        elif len(hits) > 1:
            ambiguous.append((qid, title, sub))
        else:
            assigned.append((int(qid), str(title or ""), str(sub or ""), hits[0]))
    if unmatched or ambiguous:
        for qid, title, sub in (unmatched + ambiguous)[:12]:
            kind = "no rule" if (qid, title, sub) in unmatched else "many rules"
            print(f"      {kind:<10} {qid}  [{sub[:34]}]  {repair(str(title))[:70]}")
        print(f"\n  REFUSING the whole cluster: {len(unmatched)} row(s) match no rule and "
              f"{len(ambiguous)} match more than one.")
        return 1

    # group by rule, print the evidence, resolve duplicates
    plan_rows: list[tuple[int, str, int | None, str]] = []   # qid, action, target, why
    for rule in ch.rules:
        mine = [a for a in assigned if a[3] is rule]
        if not mine:
            continue
        print(f"\n  -> {rule.action.upper()}"
              + (f" to {chapter_label(db, rule.target)}" if rule.target else "")
              + f"   ({len(mine)} question{'s' if len(mine) != 1 else ''})")
        print(f"     because: {rule.why}")
        if rule.pattern:
            print(f"     scoped by {rule.field} =~ /{rule.pattern.pattern}/")
        for qid, title, sub, _ in mine[:6]:
            tag = f"[{sub[:30]}] " if sub else ""
            print(f"       {qid}  {tag}{repair(title)[:88]}")
        if len(mine) > 6:
            print(f"       ... and {len(mine) - 6} more")

        if rule.action != REPOINT:
            for qid, _, _, _ in mine:
                plan_rows.append((qid, rule.action, None, rule.why))
            continue

        existing = db.execute(text(
            "SELECT id, question_title FROM lms_question_master "
            " WHERE chapter_id=:c AND deleted_at IS NULL"), {"c": rule.target}).fetchall()
        seen = {}
        for eid, etitle in existing:
            seen.setdefault(stem(str(etitle or "")), int(eid))
        print(f"     duplicate check against {len(existing)} question(s) already in {rule.target}")
        dups = 0
        for qid, title, _, _ in mine:
            hit = seen.get(stem(title))
            if hit:
                dups += 1
                print(f"       DUPLICATE {qid} == {hit} already there -> retire instead of repoint")
                plan_rows.append((qid, RETIRE, None, f"duplicate of {hit} in chapter {rule.target}"))
            else:
                plan_rows.append((qid, REPOINT, rule.target, rule.why))
        print(f"     {dups} duplicate(s), {len(mine) - dups} to repoint")

    moves = [p for p in plan_rows if p[1] == REPOINT]
    kills = [p for p in plan_rows if p[1] == RETIRE]
    stays = [p for p in plan_rows if p[1] == LEAVE]
    print(f"\n  decision:  repoint {len(moves)}, retire {len(kills)}, leave {len(stays)}")

    if not apply:
        print("  report only -- re-run with --apply\n")
        return 0
    if not moves and not kills:
        print("  nothing to write.\n")
        return 0

    # Log to lms_question_chapter_fix first, using the vocabulary already in
    # that table ('remap' / 'soft_delete'). Without old_chapter_id recorded
    # somewhere a repoint would not be reversible, because the UPDATE
    # overwrites the only copy of it.
    for qid, action, tgt, _ in plan_rows:
        if action == LEAVE:
            continue
        db.execute(text(
            "INSERT INTO lms_question_chapter_fix "
            "       (question_id, old_chapter_id, new_chapter_id, action) "
            "VALUES (:q, :old, :new, :a) "
            "ON DUPLICATE KEY UPDATE old_chapter_id=VALUES(old_chapter_id), "
            "       new_chapter_id=VALUES(new_chapter_id), action=VALUES(action), "
            "       moved_at=CURRENT_TIMESTAMP"),
            {"q": qid, "old": cid, "new": tgt,
             "a": "remap" if action == REPOINT else "soft_delete"})
    print(f"  logged {len(moves) + len(kills)} row(s) to lms_question_chapter_fix")

    by_target: dict[int, list[int]] = {}
    for qid, _, tgt, _ in moves:
        by_target.setdefault(int(tgt), []).append(qid)
    for tgt, qids in by_target.items():
        before = db.execute(text(
            "SELECT COUNT(*) FROM lms_question_master WHERE chapter_id=:c AND deleted_at IS NULL"),
            {"c": tgt}).scalar()
        db.execute(text(
            "UPDATE lms_question_master SET chapter_id=:t "
            " WHERE id IN :ids AND chapter_id=:c AND deleted_at IS NULL"),
            {"t": tgt, "ids": tuple(qids), "c": cid})
        after = db.execute(text(
            "SELECT COUNT(*) FROM lms_question_master WHERE chapter_id=:c AND deleted_at IS NULL"),
            {"c": tgt}).scalar()
        print(f"  repointed {len(qids)} to {tgt}:  {before} -> {after}")
    if kills:
        db.execute(text(
            "UPDATE lms_question_master SET deleted_at=NOW() "
            " WHERE id IN :ids AND chapter_id=:c AND deleted_at IS NULL"),
            {"ids": tuple(q for q, _, _, _ in kills), "c": cid})
        print(f"  retired {len(kills)} (deleted_at set; reversible)")
    db.commit()

    left = db.execute(text(
        "SELECT COUNT(*) FROM lms_question_master WHERE chapter_id=:c AND deleted_at IS NULL"),
        {"c": cid}).scalar()
    print(f"  chapter {cid} now has {left} live orphan row(s)"
          f"{' -- expected, this cluster has leave decisions' if stays else ''}\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chapter", type=int, help="one orphan chapter_id")
    ap.add_argument("--apply", action="store_true", help="write (default is report only)")
    ap.add_argument("--list", action="store_true", help="the plan, by cluster")
    ap.add_argument("--audit", action="store_true", help="plan vs database coverage")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        if a.list:
            return do_list(db)
        if a.audit:
            return do_audit(db)
        if a.chapter is None:
            ap.print_help()
            print("\n  one cluster at a time: --chapter <id>.  --list for the plan.\n")
            return 2
        return run_cluster(db, a.chapter, a.apply)
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
