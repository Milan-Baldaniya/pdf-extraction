"""Empty the Class 9 Hindi-A dumping ground, chapter 8633 " पद".

    python -m scripts.refile_c9hindi_8633            # report only
    python -m scripts.refile_c9hindi_8633 --apply    # UPDATE

Chapter 8633 is Raidas's two `पद`. It holds 257 questions and only 70 of
them are about the पद. The other 187 are the whole tail of one NODIA
question bank (`document_extractions` 674, "NODIA Class 9 Hindi R-1 Question
Bank 2026") that the loader dropped into a single chapter: the source item
JSON, `scripts/nodia_qb_items/c9_hindi/ch08.json`, labels every one of its
257 items `"chapter": "पद"`, so nothing downstream could have known better.

Of those 187, 82 are lesson questions that have a home chapter in this same
subject, and 105 are genuinely chapter-free -- unseen गद्यांश/काव्यांश
comprehension, a व्याकरण drill set, and निबंध/संवाद/सूचना-लेखन prompts.
Those 105 stay. A question about संज्ञा-भेद is not wrong under "पद"; a
question about हीरा and मोती is.

THE SPLIT IS BY CONTIGUOUS ID BLOCK, and the blocks run in book order
because the ids were handed out in the order the items were parsed:

    751802 - 751876   75  unseen passages, व्याकरण, two generic activities
    751877 - 751878    2  दो बैलों की कथा                      -> 8626
    751879 - 751888   10  क्या लिखूँ?                          -> 8627
    751889 - 751912   24  ऐसी भी बातें होती हैं                -> 8629
    751913 - 751915    3  आखिरी चट्टान तक                      -> 8630
    751916 - 751944   29  मैं और मेरा देश                      -> 8632
    751945 - 752014   70  रैदास के पद                          stays (the chapter)
    752015 - 752028   14  राम-लक्ष्मण-परशुराम संवाद            -> 8639
    752029 - 752058   30  निबंध / संवाद / सूचना-लेखन prompts   stays

Every row was read before this script was written. Three boundaries are NOT
where an earlier item-by-item pass reported them, and the corrections matter:

  * 751875-751876 (items 74-75) are a pair of generic activity prompts --
    what to do if you lose your way, and where your classroom's fire exit
    is. They name no lesson at all, so they stay. The earlier pass did not
    account for them.
  * The लता मंगेशकर interview ends at 751912 (item 111), not 751914. Items
    112-113 are the "share such an experience of your own" activity whose
    model answer runs straight into the आखिरी चट्टान तक क्रिया-विशेषण
    exercise ("मैं दूर तक भारत के स्थल-भाग की आखिरी चट्टान को देखता रहा"),
    so they belong with 114 in 8630, not in 8629.
  * 751916 (item 115) is an उपसर्ग/प्रत्यय exercise anchored on "मेरी
    मनुष्यता में अब कोई अपूर्णता नहीं रही" -- the opening of मैं और मेरा
    देश, and its answer is प्रभाकर's birthplace. It belongs to 8632, not to
    आखिरी चट्टान तक.

The move is an UPDATE of `chapter_id`. Nothing is inserted, nothing is
deleted, and no chapter row is created -- all six targets already exist. It
is reversible by running the same UPDATEs in reverse.

`lms_question_outcome.chapter_id` is updated alongside, because that table
carries its own copy of the chapter. The question ids do not change, so
every curriculum mapping stays attached to its question and stays valid.
`lms_question_extraction` has no chapter column and needs nothing.
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

FROM_CHAPTER = 8633

# The whole chapter, so a row that has appeared or vanished is caught before
# any range is trusted.
ALL_LO, ALL_HI, ALL_N = 751802, 752058, 257


def norm(s: object) -> str:
    """Devanagari comes out of MariaDB in whichever composition the OCR left
    it in: 'ज़' is sometimes U+095B and sometimes ज + U+093C, and the two do
    not compare equal. Fold both sides to NFKC before matching, or an anchor
    silently stops matching text that reads identically."""
    return unicodedata.normalize("NFKC", " ".join(str(s or "").split()))


def rx(pattern: str) -> re.Pattern[str]:
    """Anchor every alternative to a word start. Without this, "लता" matches
    inside सफलता, व्याकुलता and कुशलता, and two राम-लक्ष्मण-परशुराम rows get
    refused for reading as the Lata Mangeshkar interview. There is no
    trailing guard on purpose, so "बैल" still matches बैलों."""
    return re.compile(r"(?<![ऀ-ॿ])(?:" + norm(pattern) + r")")


# A signature that can only come from one lesson. Used negatively: a row on
# its way to 8626 must not read as तुलसीदास, and so on. "राम" is deliberately
# absent -- Raidas says राम in both of his पद.
EXCLUSIVE = {
    8626: r"हीरा और मोती|काँजीहाउस|काँजीहौस|झूरी",
    8627: r"मानटेन|खुसरो|गार्डिनर|बख्शी",
    8629: r"लता|मंगेशकर|यतींद्र|नौशाद|गंधर्व",
    8630: r"कन्याकुमारी|विवेकानंद|आखिरी चट्टान",
    8632: r"प्रभाकर|कन्हैयालाल|रामतीर्थ|लाजपत",
    8639: r"परशुराम|परसुधर|तुलसीदास|लखन",
    # Not a move target: the two blocks that stay, so that a shift which
    # pushed पद or the लेखन prompts into a range is refused too.
    FROM_CHAPTER: r"रैदास|प्रभुजी|संकेत-बिंदु",
}

# lo, hi, count, target chapter, what the block is, what every row must read as
BLOCKS = [
    (751877, 751878, 2, 8626, "दो बैलों की कथा",
     r"हीरा|मोती|काँजीहाउस|काँजीहौस|बैल|झूरी"),
    (751879, 751888, 10, 8627, "क्या लिखूँ?",
     # 751881 is the तरुण/वृद्ध comparison and 751886 the ढोल quotation;
     # neither says "निबंध", but both are verbatim from this essay.
     r"निबंध|मानटेन|खुसरो|गार्डिनर|बख्शी|तरुण|वृद्ध|ढोल"),
    (751889, 751912, 24, 8629, "ऐसी भी बातें होती हैं",
     # The interview's own activity set: गुड़ी पड़वा, नवरात्र, the राग
     # glossary, the festival songs, and the AI voice-fraud discussion --
     # placed there because the lesson is about a singer's voice.
     r"लता|मंगेशकर|यतींद्र|नौशाद|गंधर्व|गुड़ी|नवरात्र|महाराष्ट्र|रेकॉर्डिंग|"
     r"गीत|गायन|गाना|गाने|राग|संगीत|फ़िल्म|फिल्म|आवाज|होली|रंग-पंचमी|"
     r"दीवाली|तुकाराम|त्योहार|पिताजी"),
    (751913, 751915, 3, 8630, "आखिरी चट्टान तक",
     r"चट्टान|क्षितिज|नारियल|समुद्र|तट|रेत|लहर|कन्याकुमारी|विवेकानंद|"
     r"यात्रा|पानी-पानी|ढलान|पहाड़ी"),
    (751916, 751944, 29, 8632, "मैं और मेरा देश",
     r"प्रभाकर|कन्हैयालाल|लेखक|देश|नागरिक|रामतीर्थ|जापान|लाजपत|भूकंप|"
     r"दीवार|दरार|निबंध|अपूर्णता|मनुष्यता|सहारनपुर|शल्य"),
    (752015, 752028, 14, 8639, "राम-लक्ष्मण-परशुराम संवाद",
     r"परशुराम|परसुधर|लखन|लक्ष्मण|राम|तुलसीदास|जनक|सीता|स्वयंवर|सुनयना|"
     r"धनुष|तिपुरारि|रघुबीर|अवधी|सभा|काव्य-अंश|पद सरोज"),
]

# The chapter's real content. Nothing moves out of it; it is checked first,
# because if these 70 no longer read as रैदास then the ids have shifted and
# no range below can be trusted either.
ANCHOR = (751945, 752014, 70,
          r"रैदास|प्रभुजी|तोरौ|तोरि|जोरौ|हरि|ईश्वर|चंदन|चकोर|सुहागा|राम रट|"
          r"तीरथ|अंदेसा|जोति|पद|भक्त|आराध्य|भक्ति|जहँ जहँ")

# A title that carries no lesson word of its own. The model answer is read
# instead, and only for these ids, so the fallback cannot quietly widen.
# 751913 is "share such an experience of your own"; its model answer runs on
# into this lesson's क्रिया-विशेषण exercise, which quotes the lesson by name.
# Pinned to its target as well as its id, so the fallback cannot excuse the
# same row inside some other block.
ANSWER_EVIDENCE = {
    751913: (8630, r"आखिरी चट्टान"),
}


def model_answer(raw: object) -> str:
    try:
        return str(json.loads(str(raw or "{}")).get("model_answer") or "")
    except (ValueError, TypeError):
        return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-file Class 9 Hindi-A chapter 8633")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        targets = sorted({b[3] for b in BLOCKS})
        names: dict[int, str] = {}
        for cid in [FROM_CHAPTER] + targets:
            row = db.execute(text(
                "SELECT c.chapter_name, s.subject_name FROM chapter_master c "
                "  JOIN subject s ON s.id=c.subject_id WHERE c.id=:c"),
                {"c": cid}).fetchone()
            if row is None:
                print(f"  chapter {cid} does not exist -- REFUSING. This script "
                      f"never creates a chapter row.")
                return 1
            names[cid] = str(row[0]).strip()
            print(f"  {cid:6d}  {row[1]} / {names[cid]}")

        rows = db.execute(text(
            "SELECT id, question_title, answer FROM lms_question_master "
            " WHERE chapter_id=:c ORDER BY id"), {"c": FROM_CHAPTER}).fetchall()
        by_id = {int(r[0]): r for r in rows}
        print(f"\n  chapter {FROM_CHAPTER} holds {len(rows)} questions")
        if not rows:
            print("  nothing to move -- already done")
            return 0
        if (len(rows), int(rows[0][0]), int(rows[-1][0])) != (ALL_N, ALL_LO, ALL_HI):
            print(f"  REFUSING: expected {ALL_N} rows {ALL_LO}..{ALL_HI}, found "
                  f"{len(rows)} rows {rows[0][0]}..{rows[-1][0]}. The chapter has "
                  f"changed since this script was written; re-read it.")
            return 1

        refused: list[str] = []

        def check(lo: int, hi: int, count: int, target: int, label: str,
                  pattern: str) -> list[int]:
            """Re-read every row in the range and confirm it reads as `label`."""
            want = rx(pattern)
            ids = [i for i in by_id if lo <= i <= hi]
            if len(ids) != count:
                refused.append(f"{label}: expected {count} rows in "
                               f"{lo}..{hi}, found {len(ids)}")
                return []
            foreign = [(t, rx(p)) for t, p in EXCLUSIVE.items() if t != target]
            for qid in ids:
                title = norm(by_id[qid][1])
                if not want.search(title):
                    for_target, fallback = ANSWER_EVIDENCE.get(qid, (None, ""))
                    if for_target == target and rx(fallback).search(
                            norm(model_answer(by_id[qid][2]))):
                        continue
                    refused.append(f"{label}: {qid} does not read as this "
                                   f"chapter -- {title[:90]}")
                    continue
                for other, frx in foreign:
                    hit = frx.search(title)
                    if hit:
                        refused.append(f"{label}: {qid} reads as chapter "
                                       f"{other} ('{hit.group(0)}') -- "
                                       f"{title[:80]}")
            return ids

        print(f"\n  re-reading the chapter that stays:")
        a_lo, a_hi, a_n, a_pat = ANCHOR
        kept = check(a_lo, a_hi, a_n, FROM_CHAPTER, "रैदास के पद (stays)", a_pat)
        print(f"    {a_lo}..{a_hi}   {len(kept):3d} rows read as रैदास's पद")

        print(f"\n  re-reading the blocks to move:")
        plan: list[tuple[int, str, list[int]]] = []
        for lo, hi, count, target, label, pattern in BLOCKS:
            ids = check(lo, hi, count, target, label, pattern)
            plan.append((target, label, ids))
            print(f"    {lo}..{hi}  {len(ids):3d} -> {target}  {label}")

        if refused:
            print(f"\n  REFUSING to move anything. {len(refused)} row(s) do not "
                  f"read as the chapter they are claimed for:")
            for line in refused:
                print(f"      {line}")
            print("\n  Nothing has been moved. Re-read these rows and correct the "
                  "ranges before retrying -- refusing is the right outcome when "
                  "the data has shifted.")
            return 1

        moved = sum(len(ids) for _, _, ids in plan)
        stays = ALL_N - moved
        print(f"\n  {moved} questions move, {stays} stay in {FROM_CHAPTER} "
              f"({len(kept)} रैदास + {stays - len(kept)} chapter-free)")

        def counts() -> dict[int, tuple[int, int]]:
            out = {}
            for cid in [FROM_CHAPTER] + targets:
                q = db.execute(text(
                    "SELECT COUNT(*) FROM lms_question_master WHERE chapter_id=:c"),
                    {"c": cid}).scalar()
                o = db.execute(text(
                    "SELECT COUNT(*) FROM lms_question_outcome WHERE chapter_id=:c"),
                    {"c": cid}).scalar()
                out[cid] = (int(q or 0), int(o or 0))
            return out

        gain = {cid: 0 for cid in [FROM_CHAPTER] + targets}
        for target, _, ids in plan:
            gain[target] += len(ids)
            gain[FROM_CHAPTER] -= len(ids)

        before = counts()
        print(f"\n  {'chapter':>8}  {'questions':>18}  {'outcome rows':>14}  name")
        for cid in [FROM_CHAPTER] + targets:
            q, o = before[cid]
            print(f"  {cid:>8}  {q:>7} -> {q + gain[cid]:<8}  {o:>13}  "
                  f"{names[cid]}")

        if not a.apply:
            print("\n  report only -- re-run with --apply")
            return 0

        for target, label, ids in plan:
            lo, hi = min(ids), max(ids)
            r1 = db.execute(text(
                "UPDATE lms_question_master SET chapter_id=:to "
                " WHERE chapter_id=:frm AND id BETWEEN :lo AND :hi"),
                {"to": target, "frm": FROM_CHAPTER, "lo": lo, "hi": hi})
            # The outcome table keeps its own copy of the chapter; move it with
            # the question so the two cannot disagree. question_id is untouched,
            # so the mapping itself survives.
            r2 = db.execute(text(
                "UPDATE lms_question_outcome SET chapter_id=:to "
                " WHERE chapter_id=:frm AND question_id BETWEEN :lo AND :hi"),
                {"to": target, "frm": FROM_CHAPTER, "lo": lo, "hi": hi})
            print(f"    {target}  {label[:34]:<34} "
                  f"{r1.rowcount} questions, {r2.rowcount} outcome rows")
        db.commit()

        after = counts()
        print(f"\n  after:")
        for cid in [FROM_CHAPTER] + targets:
            print(f"  {cid:>8}  {after[cid][0]:>7} questions, "
                  f"{after[cid][1]:>4} outcome rows  {names[cid]}")
        bad = [c for c in [FROM_CHAPTER] + targets
               if after[c][0] != before[c][0] + gain[c]]
        if bad:
            print(f"\n  WARNING: {bad} did not land on the expected count.")
            return 1
        print(f"\n  moved {moved}. Chapter {FROM_CHAPTER} is now "
              f"{after[FROM_CHAPTER][0]} questions: {len(kept)} on रैदास's पद "
              f"and {after[FROM_CHAPTER][0] - len(kept)} chapter-free "
              f"comprehension, व्याकरण and लेखन items.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
