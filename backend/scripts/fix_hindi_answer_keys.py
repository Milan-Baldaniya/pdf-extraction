"""Correct answer keys and model answers found wrong during the concept pass.

    python -m scripts.fix_hindi_answer_keys            # report only
    python -m scripts.fix_hindi_answer_keys --apply

Eight agents reading Classes 6-7 Hindi and Class 6 English chapter by chapter
reported items whose stored key contradicts the chapter's own text. Each is
re-read here against evidence that lives **inside this estate** -- the passage
printed with the question, another question in the same chapter, or the
chapter's own concept description -- not against outside knowledge.

WHY THE GUARD IS STRUCTURAL, NOT TEXTUAL. `answer_master` has no stored label
and no stable order beyond `id`, so "the third option" is not addressable. It is
also Devanagari, and Devanagari does not survive being written into a payload
and compared: NFC *decomposes* ड़ and ढ़, `\\W` strips the matras, and a string
pasted through one normalisation silently stops matching the database's. This
estate has lost anchors that way before. So every guard below is over **option
ids** -- integers -- plus the exact ordered id list of the question's options.
If a row was inserted, deleted or reordered, the list changes and the run stops.

THE EVIDENCE, one line each:

  761420  ch29879  'हार की जीत' is a कहानी by सुदर्शन; the key said आत्मकथा.
  761540  ch29881  'मेरी माँ' is Ram Prasad Bismil on his own mother -- 761544
                   and 761546 in the same chapter name him and call him a
                   क्रांतिकारी writing his own life. So आत्मकथा. The key said
                   यात्रावृत्तांत, which nothing in the chapter supports.
  761392  ch29878  concept 32444, written from the textbook's कवि-परिचय, gives
                   गोपालकृष्ण कौल as 1923-2007. The key said 1924; 1923 is on
                   offer.
  762501  ch25934  the passage printed IN THE STEM says "नानीजी ने उनके सिर पर
                   हाथ फेरा और उनके सिरहाने खड़ी हो गईं". The key said
                   खिड़की के पास.
  761388  ch29878  "नीले नयनों-सा यह अंबर, काली पुतली से ये जलधर" -- जलधर is
                   the cloud, so काली पुतली is बादल. The key said बारिश की बूँदें.
  762932  ch25939  Meera's pad is "बरसै बदरिया सावन की". The key said वैशाख;
                   सावन is on offer.

  761394  ch29878  RETIRED. पावस means वर्षा ऋतु and the options are
                   पवित्र / पानी / पास / परी -- the right answer is absent, so
                   the item cannot be answered correctly by anyone.

  761560  ch29882  RESTORED, having first been retired here. Its option list
                   prints "तूफ़ान से" TWICE, no option is flagged, and the model
                   answer reads "मनुष्यों से" -- a value the set does not
                   contain. That looked unrecoverable, so the first version of
                   this script retired it. It is recoverable: **concept 32511's
                   description, written from the textbook, records that
                   question's own option set as तूफ़ान से / मनुष्यों से /
                   दीपकों से / तिमिर से**. So the duplicate is the extraction
                   dropping the second option, the missing text is known rather
                   than guessed, and the item becomes sound again. The script
                   clears its `deleted_at`, writes the missing option, and flags
                   it. Restoring beats retiring whenever the source says what
                   was lost.

  761511  ch29880  model answer rewritten. It read "'तलवार' शब्द तलवार का
                   प्रतीक है" -- a tautology that answers nothing.
  759492  ch29875  model answer rewritten. It gave January 2019; the National
                   War Memorial was inaugurated on 25 February 2019.

DELIBERATELY NOT TOUCHED, and why -- both were reported as wrong keys:

  761533  ch29881  "माताजी ने गृहकार्य की शिक्षा किससे प्राप्त की?" is keyed
                   सहेलियों से, and the chapter's सहेलियाँ taught her to READ,
                   not to keep house. But 761547's answer says only that she
                   "लगन से जल्द ही गृहकार्य सीख लिया" after her marriage, naming
                   no teacher, so the evidence cannot choose between
                   'परिवार से' and 'दादी जी की छोटी बहन से'. Wrong key, unknown
                   right answer: it needs the textbook page, not a guess.
  759035  ch29868  "Which spice regulates blood sugar levels?" is keyed
                   Cinnamon, and the lesson credits methi/fenugreek, which is
                   not among the options. But cinnamon is a defensible answer
                   to the question as asked. Flagged, not changed.
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

# question_id, chapter, the FULL ordered option-id list as read, the id that is
# flagged now and is wrong, the id that must be flagged instead, and why.
REKEY = [
    (761420, 29879, [612210, 612211, 612212, 612213], 612212, 612211,
     "'हार की जीत' is a story (कहानी), not an autobiography"),
    (761540, 29881, [612298, 612299, 612300, 612301], 612300, 612299,
     "Bismil writing on his own mother is आत्मकथा, not a travelogue"),
    (761392, 29878, [612182, 612183, 612184, 612185], 612183, 612184,
     "concept 32444 gives Kaul's dates as 1923-2007"),
    (762501, 25934, [613545, 613546, 613547, 613548], 613546, 613547,
     "the stem's own passage says she stood at his सिरहाने"),
    (761388, 29878, [612166, 612167, 612168, 612169], 612166, 612169,
     "जलधर is the cloud, so the काली पुतली of the sky's eye is बादल"),
    (762932, 25939, [614233, 614234, 614235, 614236], 614234, 614235,
     "Meera's pad is बरसै बदरिया सावन की"),
]

# question_id, chapter, the option-id list as read, how many of them are flagged
# now, and why the item cannot be repaired by re-keying.
RETIRE = [
    (761394, 29878, [612190, 612191, 612192, 612193], 1,
     "पावस is वर्षा ऋतु; none of पवित्र/पानी/पास/परी is that"),
]

# An option whose text the extraction lost, where the source records what it
# was. question_id, chapter, option-id list, the id that DUPLICATES another,
# the id it duplicates, the text it should hold, and where that text comes from.
#
# The guard compares the two options' stored strings to EACH OTHER rather than
# to a literal. Devanagari written into this file would have to survive one
# normalisation to reach the comparison and another to reach the database --
# and NFC decomposes ज़/फ़/ड़, so "तूफ़ान" here need not equal "तूफ़ान" there.
# Comparing two database values sidesteps that entirely.
RESTORE = [
    (761560, 29882, [612314, 612315, 612316, 612317], 612315, 612314,
     "मनुष्यों से",
     "concept 32511 records this question's own options as "
     "तूफ़ान से / मनुष्यों से / दीपकों से / तिमिर से"),
]

# question_id, a marker that must still be in the model answer, and the
# replacement. The Hindi marker is built from escapes so that no normalisation
# sits between this file and the comparison.
TAUT = "तलवार"          # तलवार
REWRITE = [
    (761511, 29880, TAUT, 2,
     "‘तलवार’ शब्द बड़े या शक्तिशाली का प्रतीक है, और ‘सुई’ छोटे का। रहीम कहते हैं — "
     "‘रहिमन देखि बड़ेन को, लघु न दीजिए डारि। जहाँ काम आवे सुई, कहा करे तरवारि॥’ "
     "अर्थात् बड़ों को देखकर छोटों को त्याग नहीं देना चाहिए, क्योंकि जहाँ सुई का "
     "काम होता है वहाँ तलवार कुछ नहीं कर सकती। इस दोहे में तलवार बड़प्पन और शक्ति "
     "का, तथा सुई छोटेपन के भीतर छिपी अपनी विशेष उपयोगिता का प्रतीक है।"),
    (759492, 29875, "January 2019", 1,
     "The National War Memorial was built by the Government of India and "
     "inaugurated on 25 February 2019. It stands near India Gate in New Delhi "
     "and honours the soldiers who have died in service since Independence."),
]


def opt_ids(db, qid: int) -> list:
    return [int(i) for i, in db.execute(text(
        "SELECT id FROM answer_master WHERE question_id = :q ORDER BY id"),
        {"q": qid}).fetchall()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        refused: list[str] = []
        plan_k, plan_r, plan_w, plan_s = [], [], [], []

        print("  RE-KEY -- the right value is among the options\n")
        for qid, ch, ids, wrong, right, why in REKEY:
            row = db.execute(text(
                "SELECT chapter_id, deleted_at FROM lms_question_master "
                " WHERE id = :q"), {"q": qid}).fetchone()
            if not row or row[1] is not None or int(row[0]) != ch:
                refused.append(f"{qid} is missing, retired, or has moved chapter")
                continue
            have = opt_ids(db, qid)
            if have != ids:
                refused.append(f"{qid}: option ids are {have}, expected {ids} "
                               f"-- a row was added, removed or reordered")
                continue
            flagged = [int(i) for i, in db.execute(text(
                "SELECT id FROM answer_master WHERE question_id = :q "
                "  AND correct_answer = 1"), {"q": qid}).fetchall()]
            if flagged == [right]:
                print(f"   {qid}  already correct, skipping")
                continue
            if flagged != [wrong]:
                refused.append(f"{qid}: expected option {wrong} to be the only "
                               f"flagged one, found {flagged}")
                continue
            plan_k.append((qid, wrong, right))
            print(f"   {qid}  ch{ch}  flag moves {wrong} -> {right}")
            print(f"          {why}")

        print("\n  RETIRE -- the right value is not among the options\n")
        for qid, ch, ids, nflag, why in RETIRE:
            row = db.execute(text(
                "SELECT chapter_id, deleted_at FROM lms_question_master "
                " WHERE id = :q"), {"q": qid}).fetchone()
            if not row or int(row[0]) != ch:
                refused.append(f"{qid} is missing or has moved chapter")
                continue
            if row[1] is not None:
                print(f"   {qid}  already retired, skipping")
                continue
            have = opt_ids(db, qid)
            if have != ids:
                refused.append(f"{qid}: option ids are {have}, expected {ids}")
                continue
            n = db.execute(text(
                "SELECT COUNT(*) FROM answer_master WHERE question_id = :q "
                "  AND correct_answer = 1"), {"q": qid}).scalar()
            if int(n) != nflag:
                refused.append(f"{qid}: expected {nflag} flagged option(s), "
                               f"found {n}")
                continue
            plan_r.append(qid)
            print(f"   {qid}  ch{ch}  {why}")

        print("\n  RESTORE -- an option the extraction lost, which the source "
              "records\n")
        for qid, ch, ids, dup, same_as, want, why in RESTORE:
            row = db.execute(text(
                "SELECT chapter_id FROM lms_question_master WHERE id = :q"),
                {"q": qid}).fetchone()
            if not row or int(row[0]) != ch:
                refused.append(f"{qid} is missing or has moved chapter")
                continue
            have = opt_ids(db, qid)
            if have != ids:
                refused.append(f"{qid}: option ids are {have}, expected {ids}")
                continue
            a_dup, a_same = (db.execute(text(
                "SELECT answer FROM answer_master WHERE id = :i"),
                {"i": i}).scalar() for i in (dup, same_as))
            if str(a_dup) == want:
                print(f"   {qid}  already restored, skipping")
                continue
            if " ".join(str(a_dup).split()) != " ".join(str(a_same).split()):
                refused.append(f"{qid}: option {dup} no longer duplicates "
                               f"option {same_as}, so the lost option is not "
                               f"the one this expects")
                continue
            n = db.execute(text(
                "SELECT COUNT(*) FROM answer_master WHERE question_id = :q "
                "  AND correct_answer = 1"), {"q": qid}).scalar()
            if int(n):
                refused.append(f"{qid}: an option is already flagged ({n}); "
                               f"this expects none")
                continue
            plan_s.append((qid, dup, want))
            print(f"   {qid}  ch{ch}  option {dup} duplicates {same_as}; "
                  f"restoring its text and flagging it")
            print(f"          {why}")

        print("\n  REWRITE THE MODEL ANSWER\n")
        for qid, ch, marker, times, new in REWRITE:
            cur = db.execute(text(
                "SELECT COALESCE(hint_text,'') FROM lms_question_master "
                " WHERE id = :q AND chapter_id = :c AND deleted_at IS NULL"),
                {"q": qid, "c": ch}).scalar()
            if cur is None:
                refused.append(f"{qid} is missing, retired, or has moved chapter")
                continue
            flat = " ".join(str(cur).split())
            if flat == " ".join(new.split()):
                print(f"   {qid}  already rewritten, skipping")
                continue
            if flat.count(marker) < times:
                refused.append(f"{qid}: the model answer no longer shows the "
                               f"defect ({times}x marker) -- it may already be "
                               f"corrected")
                continue
            plan_w.append((qid, new))
            print(f"   {qid}  ch{ch}  {len(flat)} chars -> {len(new)} chars")

        if refused:
            print(f"\n  REFUSED -- {len(refused)} row(s) are not in the state "
                  f"this script expects:")
            for m in refused:
                print(f"    ! {m}")
            print("  Nothing has been written.")
            return 1

        print(f"\n  {len(plan_k)} to re-key, {len(plan_r)} to retire, "
              f"{len(plan_s)} to restore, {len(plan_w)} answer(s) to rewrite")
        print("  NOT touched, by decision: 761533 (wrong key, right answer not "
              "established)\n  and 759035 (lesson and general usage disagree). "
              "See the docstring.")
        if not a.apply:
            print("\n  report only -- re-run with --apply")
            return 0

        for qid, wrong, right in plan_k:
            db.execute(text("UPDATE answer_master SET correct_answer = 0 "
                            " WHERE id = :i"), {"i": wrong})
            db.execute(text("UPDATE answer_master SET correct_answer = 1 "
                            " WHERE id = :i"), {"i": right})
        for qid in plan_r:
            db.execute(text("UPDATE lms_question_master SET deleted_at = NOW() "
                            " WHERE id = :q AND deleted_at IS NULL"), {"q": qid})
        for qid, dup, want in plan_s:
            db.execute(text("UPDATE answer_master SET answer = :a, "
                            "       correct_answer = 1 WHERE id = :i"),
                       {"a": want, "i": dup})
            db.execute(text("UPDATE lms_question_master SET deleted_at = NULL "
                            " WHERE id = :q"), {"q": qid})
        for qid, new in plan_w:
            db.execute(text("UPDATE lms_question_master SET hint_text = :h "
                            " WHERE id = :q"), {"h": new, "q": qid})
        db.commit()
        print(f"\n  re-keyed {len(plan_k)}, retired {len(plan_r)}, restored "
              f"{len(plan_s)}, rewrote {len(plan_w)} model answer(s)")
        print("  All three are reversible: the flag moves back, deleted_at "
              "clears, and the\n  replaced answers are quoted in this file's "
              "docstring.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
