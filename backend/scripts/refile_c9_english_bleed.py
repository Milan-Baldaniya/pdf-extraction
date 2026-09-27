"""Undo the one-chapter lag in the Class 9 English (Kaveri prose) question bank.

    python -m scripts.refile_c9_english_bleed            # report only
    python -m scripts.refile_c9_english_bleed --apply    # UPDATE

Eight extractions (613-620) were cut one chapter early, so each chapter's
block OPENS with the tail of the previous chapter:

    613 -> 8622  How I Taught My Grandmother to Read
    614 -> 8623  The Pot Maker
    615 -> 8624  Winds of Change
    616 -> 8634  Vitamin-M
    617 -> 8635  The World of Limitless Possibilities
    618 -> 8636  Twin Melodies
    619 -> 8637  Carrier of Words
    620 -> 8638  Follow That Dream

Every id below was read -- question stem AND the `model_answer` inside the
`answer` JSON -- before this script was written. The boundaries are where the
previous chapter's content stops:

    8623 items  1-2     ->  8622   (a Kashi Yatre MCQ; the wedding extract)
    8624 items  1-13    ->  8623   (Arenla, Sentila, the village council)
    8634 items  1-11    ->  8624   (pankhas, zardozi, fan artisans)
    8635 items  1-21    ->  8634   (Ravi tailing Grandpa)
    8636 items  1-9     ->  8635   (Dr Deepa Malik, the Paralympics)
    8637 items  1-27    ->  8636   (Shruti, Nabin, the fusion band)
    8638 items 1-25, 29, 35-37 -> 8637   (Khetaram, the Gramin Dak Sewak)

Two cases do not follow "the first N rows":

  * 8638 is NON-CONTIGUOUS. Follow That Dream resumes at item 26, then four
    more Khetaram items (29, 35, 36, 37) are interleaved further down. Blocks
    are therefore explicit id lists, never ranges.

  * 8622 leaks FORWARD, not back. Extraction 613 picked up The Pot Maker's
    "Reflect and Respond" opener (the vocations pictures, handmade versus
    machine-made) as items 94-96, with Grandmother content on both sides of
    it. Those three move on to 8623.

Nothing is inserted and nothing is deleted; `chapter_id` is UPDATEd in
`lms_question_master` and in `lms_question_outcome`. Question ids do not
change, so curriculum mappings stay attached and stay valid -- they were
matched on content, not on chapter.

THE GUARD. Every row is re-read at run time and must read as the TARGET
chapter's content, either by matching that chapter's keyword pattern or by
still carrying its pinned snippet (used for the handful of stub MCQs whose
whole text is "What natural disaster is the region highly prone to?" /
"(a) Famines" and names nothing). If any row fails, NOTHING is written: a
failure means the ids have moved and the list above no longer describes the
data.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

CHAPTERS = [8622, 8623, 8624, 8634, 8635, 8636, 8637, 8638]

NAMES = {
    8622: "How I Taught My Grandmother to Read",
    8623: "The Pot Maker",
    8624: "Winds of Change",
    8634: "Vitamin-M",
    8635: "The World of Limitless Possibilities",
    8636: "Twin Melodies",
    8637: "Carrier of Words",
    8638: "Follow That Dream",
}

# What each chapter's own content looks like. Applied to the question stem
# and the model answer together.
CONTENT = {
    8622: re.compile(
        r"(?i)grandmother|krishtakka|kashi\s*yatre|triveni|karmaveera|sudha\s*murty|"
        r"kannada|dassara|saraswati\s*puja|age\s*bar|serial|magazine"),
    8623: re.compile(
        r"(?i)sentila|arenla|onula|mesoba|pot\s*mak|pottery|\bpots?\b|\bclay\b|"
        r"potter|village\s*(council|elder)|handloom|weav|bamboo\s*cylinder|spatula|"
        # items 94-96 of extraction 613: the chapter's picture-based opener,
        # which names no character and never says "pot".
        r"handmade|machine-\s*made|handicraft|artisan|vocation|manual\s*lab"),
    8624: re.compile(
        r"(?i)pankha|punkha|hand\s*fan|\bfans?\b|fan\s*mak|zardozi|appliqu|"
        r"sola\b|winds\s*of\s*change|craft|artisan|handicraft"),
    8634: re.compile(
        r"(?i)\bravi\b|grandpa|grandfather|vitamin\s*-?\s*m|vidya|banyan|"
        r"tea\s*stall|bus\s*stop|\bcap\b|detective|elderly|ageing|aging|"
        r"forget|memory|ice\s*cream|banana"),
    8635: re.compile(
        r"(?i)deepa\s*malik|dr\.?\s*malik|sheetal\s*devi|para-?\s*(athlet|sport|archer)|"
        r"paralymp|disabilit|disabled|differently-?abled|wheelchair|shot-?put|"
        r"arjuna|padma\s*shri|khel\s*ratna|tumour|tumor|limitless"),
    8636: re.compile(
        r"(?i)shruti|nabin|leela|iqbal|avinash|\bpeter\b|sameer|twin\s*melod|"
        r"fusion|violin|tabla|harmonium|classical\s*music|\bplay\b|playwright|"
        r"generation\s*gap|warm\s*hug|aside\b"),
    8637: re.compile(
        r"(?i)khetaram|gramin\s*dak|\bgds\b|post\s*office|postman|postal|"
        r"india\s*post|somarad|\bmail\b|mailbag|envelope|ashubh|jaggery|"
        r"thar\b|desert|sandstorm|sand\s*dune|bajra|money\s*order|famine|"
        r"unsung\s*hero|telegram|stamp"),
    8638: re.compile(
        r"(?i)\bming\b|follow\s*that\s*dream|abdul\s*kalam|dreamscape|"
        r"dreamer|achiever|burning\s*conviction|madalasa|aspiration|"
        r"\bdreams?\b"),
}

# Rows whose entire text names nothing chapter-specific. The pinned snippet is
# the text as it was read; if the ids shift, it stops matching and the run is
# refused. Matched against the normalised stem + model answer.
PINNED = {
    # Extraction 613 item 94: The Pot Maker's picture-based opener. Its
    # neighbours 734890/734891 are the handmade-versus-machine-made pair.
    734889: "what is common among these pictures",
    # Extraction 619 item 12: a theme MCQ sitting inside the Twin Melodies
    # run between 735371 (generational gap) and 735373 (the title's metaphor).
    735372: "balance personal passions with traditional duties",
}

# from_chapter -> to_chapter, with the exact ids. Explicit lists, so a
# non-contiguous block needs no special case.
BLOCKS = [
    # Extraction 613 ran one page past its chapter: The Pot Maker's opener.
    {"frm": 8622, "to": 8623, "ids": [734889, 734890, 734891]},
    {"frm": 8623, "to": 8622, "ids": [734900, 734901]},
    {"frm": 8624, "to": 8623, "ids": list(range(734989, 735001 + 1))},
    {"frm": 8634, "to": 8624, "ids": list(range(735080, 735090 + 1))},
    {"frm": 8635, "to": 8634, "ids": list(range(735175, 735195 + 1))},
    {"frm": 8636, "to": 8635, "ids": list(range(735282, 735290 + 1))},
    {"frm": 8637, "to": 8636, "ids": list(range(735361, 735387 + 1))},
    {"frm": 8638, "to": 8637,
     "ids": list(range(735465, 735489 + 1)) + [735493, 735499, 735500, 735501]},
]


def haystack(title: str | None, answer: str | None) -> str:
    """The stem plus the model answer, whitespace-normalised.

    A two-column page puts a neighbouring column's text into the stem and the
    matching answer into a different row, so neither field alone is enough to
    say what a row is about.
    """
    parts = [str(title or "")]
    try:
        payload = json.loads(answer or "{}")
    except Exception:
        payload = {}
    if isinstance(payload, dict):
        parts.append(str(payload.get("model_answer") or ""))
        for opt in payload.get("options") or []:
            if isinstance(opt, dict):
                parts.append(str(opt.get("text") or ""))
    else:
        parts.append(str(answer or ""))
    return " ".join(" ".join(parts).split())


def counts(db) -> dict[int, int]:
    return {
        c: db.execute(
            text("SELECT COUNT(*) FROM lms_question_master WHERE chapter_id=:c"),
            {"c": c}).scalar()
        for c in CHAPTERS
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Refile the Class 9 English bleed")
    ap.add_argument("--apply", action="store_true", help="write; default is report only")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        before = counts(db)
        print("  before")
        for c in CHAPTERS:
            print(f"    {c}  {before[c]:4d}  {NAMES[c]}")

        planned: list[tuple[int, int, int]] = []   # (qid, frm, to)
        refused: list[str] = []
        misplaced: list[str] = []

        for blk in BLOCKS:
            frm, to, ids = blk["frm"], blk["to"], blk["ids"]
            rows = db.execute(text(
                "SELECT id, chapter_id, question_title, answer "
                "  FROM lms_question_master WHERE id IN :ids ORDER BY id"),
                {"ids": tuple(ids)}).fetchall()
            found = {r[0] for r in rows}
            print(f"\n  {frm} {NAMES[frm]}  ->  {to} {NAMES[to]}   "
                  f"({len(ids)} ids, {len(rows)} present)")
            for missing in sorted(set(ids) - found):
                refused.append(f"{missing}: row no longer exists")

            pat = CONTENT[to]
            for qid, chapter_id, title, answer in rows:
                hay = haystack(title, answer)
                if chapter_id == to:
                    misplaced.append(f"{qid}: already in {to} -- nothing to do")
                    continue
                if chapter_id != frm:
                    refused.append(
                        f"{qid}: sits in chapter {chapter_id}, expected {frm}")
                    continue
                pin = PINNED.get(qid)
                if pin and pin in hay.lower():
                    why = "pinned"
                elif pat.search(hay):
                    why = "keyword"
                else:
                    refused.append(
                        f"{qid}: does not read as {to} {NAMES[to]} -- {hay[:110]}")
                    continue
                planned.append((qid, frm, to))
                print(f"      {qid}  [{why:7s}] {hay[:96]}")

        if misplaced:
            print("\n  already moved:")
            for line in misplaced:
                print(f"      {line}")

        if refused:
            print(f"\n  REFUSING the whole run -- {len(refused)} row(s) failed the "
                  f"guard.\n  Nothing has been written. Re-read these and rebuild "
                  f"BLOCKS before retrying:")
            for line in refused:
                print(f"      {line}")
            return 1

        if not planned:
            print("\n  nothing to move -- already done")
            return 0

        after = dict(before)
        for _, frm, to in planned:
            after[frm] -= 1
            after[to] += 1
        print(f"\n  {len(planned)} question(s) would move")
        print("  after")
        for c in CHAPTERS:
            delta = after[c] - before[c]
            print(f"    {c}  {before[c]:4d} -> {after[c]:4d}  ({delta:+d})  {NAMES[c]}")

        if not a.apply:
            print("\n  report only -- re-run with --apply")
            return 0

        moved_q = moved_o = 0
        for qid, frm, to in planned:
            moved_q += db.execute(text(
                "UPDATE lms_question_master SET chapter_id=:to "
                " WHERE id=:q AND chapter_id=:frm"),
                {"to": to, "q": qid, "frm": frm}).rowcount
            moved_o += db.execute(text(
                "UPDATE lms_question_outcome SET chapter_id=:to "
                " WHERE question_id=:q AND chapter_id=:frm"),
                {"to": to, "q": qid, "frm": frm}).rowcount
        db.commit()

        final = counts(db)
        print(f"\n  moved {moved_q} question rows and {moved_o} "
              f"lms_question_outcome rows")
        for c in CHAPTERS:
            print(f"    {c}  {before[c]:4d} -> {final[c]:4d}  "
                  f"({final[c] - before[c]:+d})  {NAMES[c]}")
        bad = db.execute(text(
            "SELECT COUNT(*) FROM lms_question_outcome o "
            "  JOIN lms_question_master q ON q.id=o.question_id "
            " WHERE q.chapter_id IN :ids AND (o.chapter_id IS NULL "
            "       OR o.chapter_id<>q.chapter_id)"),
            {"ids": tuple(CHAPTERS)}).scalar()
        print(f"    outcome rows disagreeing with their question's chapter: {bad}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
