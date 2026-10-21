"""Move Class 6 English's 126 concepts off five placeholder rows onto the real chapters.

    python -m scripts.rehome_c6_english_concepts            # report only
    python -m scripts.rehome_c6_english_concepts --apply     # UPDATE

`chapter_master` holds 21 rows for Class 6 English (standard 39, subject 3978):

    29860-29875   the 16 real chapters (A Bottle of Dew ... National War
                  Memorial). 671 questions, ZERO concepts.
    29889-29893   five placeholders, `Poorvi Unit 1 - Fables and Folk Tales`
                  ... `Unit 5`. ZERO questions, ALL 126 concepts. They also
                  share sort_order 1-5 with the real chapters.

So every question in Class 6 English is unlinkable, and every concept is
unreachable, for want of one column. `load_question_concepts` refuses a concept
that does not belong to the question's chapter -- correctly -- so nothing can be
paired until the concepts sit where the questions are.

HOW EACH CONCEPT WAS PLACED. Not by name, and not by arithmetic. Every one of
the 126 `description` fields was read. Each placeholder's concepts are a
sequence through that unit's three or four texts, and each lesson's run has the
same shape: pre-reading, then the text in two to four passes, then Let us think
and reflect, then Let us learn (the grammar and vocabulary work, which is always
built out of that lesson's own sentences), then Let us listen / speak / write /
explore. The description names the lesson's characters, its glosses and its
exercises, so the boundaries are unambiguous -- 33053 opens "The second lesson
opens with five pre-reading tasks", 33059 defines a spice, 33107 introduces
Pranav M. Balasubramaniam. `unit_id` on the real chapter rows fixes which three
or four chapters a unit's concepts may go to:

    Unit 1 = 198 -> 29860-29862   Unit 4 = 201 -> 29869-29871
    Unit 2 = 199 -> 29863-29865   Unit 5 = 202 -> 29872-29875
    Unit 3 = 200 -> 29866-29868

FOUR CONCEPTS ARE NOT MOVED, and this is a finding rather than a shortfall.
Every unit prints its listening transcripts together at the *back of the unit*,
outside any lesson, and the extractor turned each of those blocks into one or
two concepts. Where such a concept covers a single lesson's transcript it does
describe that chapter, and it moves (33067, Peepal Baba, is Neem Baba's
listening text; 33117, gakkad bharta, is Kalakritiyon ka Bharat's). Where it
covers two or three lessons' transcripts at once it describes the unit's closing
block and no one chapter, so it stays:

    33044  Leopard, Park Bench, New School      all three of unit 2's
    33068  Paro, and Tulsi Tea                  units 3's second and third
    33090  Xydium, and a Grandfather at 65      unit 4's first and second
    33118  Uttarayan, and the Chain Stitch      unit 5's second and third

No question in the bank reaches any transcript content -- "Paro", "tulsi",
"Xydium", "Uttarayan" and "chain stitch" appear in no stem in chapters
29860-29875 -- so nothing is lost by leaving them where the book prints them.

TWO CONCEPTS STRADDLE A LESSON BOUNDARY and were placed on the lesson their
name and their substance belong to:

    33018  closes Rama to the Rescue with Let us write and Let us explore, then
           mentions the three transcripts in its last sentence  -> 29862
    33100  gives the Ek Bharat, Shreshtha Bharat closing page of lesson 1 and
           then The Kites' pre-reading -> 29873, because it is The Kites' first
           pre-reading concept (its name is the poem's first line) and the
           programme is already described in full by 33092, which is lesson 1's.

THE GUARD re-reads all 126 rows at run time and refuses the whole run unless
every one of them still sits on the placeholder this mapping was written
against. A concept that has moved since -- by a later pass, or by a half-applied
run of this script -- means the reading is stale, and applying the rest of it
would be writing over someone else's decision. Nothing is written from a file
that fails, in the same all-or-nothing spirit as `load_question_concepts`.

Only `lms_concept.chapter_id` is touched. Nothing is inserted and nothing is
deleted, and the placeholder rows themselves are left alone -- retiring them is
a separate decision, and they still carry sort_order 1-5 against the real
chapters, which is its own defect.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

STANDARD, SUBJECT = 39, 3978
PLACEHOLDERS = (29889, 29890, 29891, 29892, 29893)

# unit -> (placeholder, {chapter_id: [concept_id, ...]})
PLAN: dict[int, tuple[int, dict[int, list[int]]]] = {
    1: (29889, {
        # A Bottle of Dew -- pre-reading, the story in three passes, Let us
        # think and reflect in two, then homophones / connectors / s-and-z /
        # the writing and Blue Java tasks.
        29860: [32993, 32994, 32995, 32996, 32997, 32998, 32999, 33000,
                33001, 33002],
        # The Raven and the Fox -- Reynard, the four stanzas, the word match,
        # the two extracts, the opposites table, the crow's own account.
        29861: [33003, 33004, 33005, 33006, 33007, 33008],
        # Rama to the Rescue -- the kotwal play: what rescue means, thaanedar,
        # the panels, the two extracts, apostrophes, present progressive,
        # adverbs, exclamatory vs interrogative, the announcement, the retelling.
        29862: [33009, 33010, 33011, 33012, 33013, 33014, 33015, 33016,
                33017, 33018],
    }),
    2: (29890, {
        # The Unlikely Best Friends -- Gajaraj and Buntee, then un-/in-/dis-/
        # mis-, the three past forms, the verb-choice passage, neither/nor.
        29863: [33019, 33020, 33021, 33022, 33023, 33024, 33025, 33026,
                33027, 33028],
        # A Friend's Prayer -- which sentence is a prayer, Jill Wolf's twelve
        # lines, the two extracts on judgement, the qualities puzzle, the park.
        29864: [33029, 33030, 33031, 33032, 33033],
        # The Chair -- the word grid, grandpa's bet, the invisible chair,
        # who held him up, root words, suffixes, adjective-noun pairs,
        # Monika, Mario's three messages, the four age groups.
        29865: [33034, 33035, 33036, 33037, 33038, 33039, 33040, 33041,
                33042, 33043],
    }),
    3: (29891, {
        # Neem Baba -- the dialogue with the tree, its names, its medicinal and
        # agricultural uses, compound words, personification, Azadirachta
        # indica; and 33067, the Peepal Baba transcript, which is this
        # lesson's listening text and no other's.
        29866: [33045, 33046, 33047, 33048, 33049, 33050, 33051, 33052,
                33067],
        # What a Bird Thought -- the four homes, the pictures, the two
        # extracts, the new stanza, how a baby and a fish see.
        29867: [33053, 33054, 33055, 33056, 33057, 33058],
        # Spices that Heal Us -- what a spice is, the ten-row table, Daadi's
        # letter in two passes, modals, the tulsi fact sheet, ginger and
        # honey, the riddles.
        29868: [33059, 33060, 33061, 33062, 33063, 33064, 33065, 33066],
    }),
    4: (29892, {
        # Change of Heart -- Prabhat and Surya, the cheated scoreboard, the
        # observation, past perfect twice, the coach's note-taking table,
        # the diary page and the two bio-sketches.
        29869: [33069, 33070, 33071, 33072, 33073, 33074, 33075, 33076,
                33077, 33078],
        # The Winner -- the creek poem: evenings, trees creep close,
        # repetition and personification, the four sport riddles.
        29870: [33079, 33080, 33081, 33082],
        # Yoga - A Way of Life -- yuj, Patanjali, the benefits, WHO mYoga and
        # the Hatha Yoga Pradipika, practice/practise, advice/advise, the
        # seals and International Yoga Day.
        29871: [33083, 33084, 33085, 33086, 33087, 33088, 33089],
    }),
    5: (29893, {
        # Hamara Bharat - Incredible India! -- the opening passage, Ek Bharat
        # Shreshtha Bharat, the four crafts (Aipan, Dhokra, coconut shell,
        # Kondapalli), sequence words, present tense, Madhubani; and 33117,
        # the gakkad bharta transcript, which is this lesson's listening text.
        29872: [33091, 33092, 33093, 33094, 33095, 33096, 33097, 33098,
                33099, 33117],
        # The Kites -- pre-reading, the poem, the eleven true-or-false, simile,
        # rhyme and alliteration, the parts of a kite, the movement verbs.
        29873: [33100, 33101, 33102, 33103, 33104, 33105, 33106],
        # Ila Sachani -- Pranav, the tiny room, Amreli, the Surat exhibition,
        # the nine paragraphs, unlike other children, synonyms and antonyms,
        # much/many, the rising tone.
        29874: [33107, 33108, 33109, 33110, 33111, 33112, 33113, 33114,
                33115],
        # National War Memorial -- the whole of the book's shortest lesson is
        # one concept, because the lesson is one poem and three instructions,
        # none of them a comprehension question.
        29875: [33116],
    }),
}

# Concepts that describe the unit's closing transcript block rather than any one
# lesson in it. Left on the placeholder deliberately; see the module docstring.
KEEP = {
    33044: (29890, "all three of unit 2's listening transcripts -- the leopard "
                   "and the cow, the park bench, and Monika's notes -- read as "
                   "one restatement of the unit's theme"),
    33068: (29891, "unit 3's second and third transcripts together: the Paro "
                   "poem (What a Bird Thought) and the tulsi passage (Spices "
                   "that Heal Us)"),
    33090: (29892, "unit 4's two transcripts together: the coach's "
                   "announcement (Change of Heart) and the girl's grandfather "
                   "(Yoga - A Way of Life)"),
    33118: (29893, "unit 5's second and third transcripts together: the Kite "
                   "Festival (The Kites) and Kathiawar embroidery (Ila "
                   "Sachani)"),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--quiet", action="store_true",
                    help="print counts only, not the full mapping")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        names = {int(i): str(n) for i, n in db.execute(text(
            "SELECT id, chapter_name FROM chapter_master "
            " WHERE standard_id = :s AND subject_id = :j"),
            {"s": STANDARD, "j": SUBJECT}).fetchall()}
        units = {int(i): int(u or 0) for i, u in db.execute(text(
            "SELECT id, unit_id FROM chapter_master "
            " WHERE standard_id = :s AND subject_id = :j"),
            {"s": STANDARD, "j": SUBJECT}).fetchall()}

        # ---- the guard: re-read every concept this mapping speaks for -------
        live = {int(i): (int(c or 0), str(n)) for i, c, n in db.execute(text(
            "SELECT id, chapter_id, name FROM lms_concept "
            " WHERE chapter_id IN :p OR id IN :k"),
            {"p": PLACEHOLDERS, "k": tuple(
                [c for _, (_, m) in PLAN.items() for cs in m.values() for c in cs]
                + list(KEEP))}).fetchall()}

        claimed: dict[int, int] = {}          # concept -> destination chapter
        for unit, (ph, mapping) in PLAN.items():
            for ch, cons in mapping.items():
                for c in cons:
                    claimed[c] = ch
        expected_home = {c: ph for _, (ph, m) in PLAN.items()
                         for cs in m.values() for c in cs}
        expected_home.update({c: ph for c, (ph, _) in KEEP.items()})

        problems: list[str] = []
        for c, ph in sorted(expected_home.items()):
            if c not in live:
                problems.append(f"concept {c} does not exist")
                continue
            at, nm = live[c]
            if at != ph:
                problems.append(f"concept {c} ({nm}) sits on {at}, not on the "
                                f"placeholder {ph} this mapping was written "
                                f"against")
        # and nothing may be left behind unaccounted for
        for c, (at, nm) in sorted(live.items()):
            if at in PLACEHOLDERS and c not in expected_home:
                problems.append(f"concept {c} ({nm}) is on placeholder {at} "
                                f"and this mapping does not mention it")
        # a destination must be a real chapter of the same unit
        for c, ch in sorted(claimed.items()):
            ph = expected_home[c]
            if ch not in names:
                problems.append(f"concept {c} -> {ch}, which is not a Class 6 "
                                f"English chapter")
            elif units.get(ch) != units.get(ph):
                problems.append(f"concept {c} -> {ch} (unit {units.get(ch)}) "
                                f"from placeholder {ph} (unit {units.get(ph)})")

        n_plan = sum(len(cs) for _, (_, m) in PLAN.items() for cs in m.values())
        print(f"  Class 6 English, standard {STANDARD} subject {SUBJECT}")
        print(f"  {len(live)} concept(s) read back, {n_plan} to move, "
              f"{len(KEEP)} left on a placeholder on purpose, "
              f"{len(problems)} problem(s)\n")
        if problems:
            for p in problems[:20]:
                print(f"    ! {p}")
            print(f"\n  REFUSING the whole run -- nothing written. The reading "
                  f"behind this\n  mapping is stale; re-read those concepts "
                  f"before retrying.")
            return 1

        if not a.quiet:
            for unit in sorted(PLAN):
                ph, mapping = PLAN[unit]
                print(f"  ---- unit {unit}: {names.get(ph, '?')}  "
                      f"(placeholder {ph}, unit_id {units.get(ph)})")
                for ch in sorted(mapping):
                    nq = db.execute(text(
                        "SELECT COUNT(*) FROM lms_question_master "
                        " WHERE chapter_id = :c AND deleted_at IS NULL"),
                        {"c": ch}).scalar()
                    print(f"    -> {ch}  {names.get(ch, '?')[:44]:<44} "
                          f"{len(mapping[ch]):>2} concept(s), {nq} question(s)")
                    for c in mapping[ch]:
                        print(f"         {c}  {live[c][1]}")
                for c, (kph, why) in KEEP.items():
                    if kph == ph:
                        print(f"    .. stays on {ph}: {c}  {live[c][1]}")
                        print(f"         {why}")
                print()

        after = {}
        for ch in sorted(names):
            if ch in PLACEHOLDERS:
                after[ch] = sum(1 for c, (kph, _) in KEEP.items() if kph == ch)
            else:
                after[ch] = sum(len(m.get(ch, ()))
                                for _, (_, m) in PLAN.items())
        print(f"  {'cid':>7} {'chapter':<46} {'concepts now':>12} {'after':>7}")
        for ch in sorted(names):
            now = sum(1 for _, (at, _) in live.items() if at == ch)
            print(f"  {ch:>7} {names[ch][:46]:<46} {now:>12} {after[ch]:>7}"
                  + ("   <- placeholder" if ch in PLACEHOLDERS else ""))

        if not a.apply:
            print("\n  report only -- argue with the mapping above, then "
                  "re-run with --apply")
            return 0

        for c, ch in claimed.items():
            db.execute(text("UPDATE lms_concept SET chapter_id = :ch "
                            " WHERE id = :c AND chapter_id = :ph"),
                       {"ch": ch, "c": c, "ph": expected_home[c]})
        db.commit()

        print(f"\n  moved {len(claimed)}. reading back:")
        bad = 0
        for c, ch in sorted(claimed.items()):
            at = db.execute(text("SELECT chapter_id FROM lms_concept "
                                 " WHERE id = :c"), {"c": c}).scalar()
            if int(at or 0) != ch:
                print(f"    ! concept {c} is on {at}, wanted {ch}")
                bad += 1
        for ch in PLACEHOLDERS:
            n = db.execute(text("SELECT COUNT(*) FROM lms_concept "
                                " WHERE chapter_id = :c"), {"c": ch}).scalar()
            want = sum(1 for _, (kph, _) in KEEP.items() if kph == ch)
            flag = "" if int(n) == want else f"   ! expected {want}"
            print(f"    placeholder {ch}: {n} concept(s) left{flag}")
        return 1 if bad else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
