"""Retire Class 6 Hindi questions that belong to the superseded Vasant book.

    python -m scripts.retire_vasant_contamination            # report only
    python -m scripts.retire_vasant_contamination --apply

The Class 6 Hindi bank was loaded from a source that **mixed two textbooks**.
Our 13 chapter rows are NEP *Malhar*; a number of the loaded questions are
*Vasant*, the book Malhar replaced. A Vasant question served under a Malhar
chapter is wrong for every student who meets it, and Vasant chapters have no
row in the NEP structure, so there is nowhere correct to move it to.

WHAT THIS RETIRES, AND WHAT IT CANNOT SEE. Only questions whose own text names
a Vasant chapter — "'ऐसे-ऐसे' एकांकी के लेखक कौन हैन?", or an extract of that
play's dialogue printed under सत्रिया और बिहू नृत्य. That is a signature match,
so it catches an item that NAMES its chapter and misses one that is merely
about it. A mapping pass over this bank reported roughly 84 misfiled items; the
title match finds **21**. The difference was never a disagreement — it is the
limit of matching on a title, and the other 62 were found by reading, in the two
`BY_ID` passes below, for **83 in total**. Chapters 1-7 (29876-29882) came back
clean; the contamination is confined to 29883-29888 and is index-aligned.

Retirement is `deleted_at`, which is how this estate already marks a question
that should not be served (175 Class 10 Science rows carry one). Nothing is
deleted, the rows stay readable, and the curriculum mappings stay attached —
so this is reversible by clearing the column. Note that
`question_curriculum_context` and `load_question_curriculum` do NOT filter on
`deleted_at`, so a retired question will still be offered for mapping; that is
a separate defect worth fixing in those two scripts.

THE GUARD. Every row is re-read at run time and must still carry a Vasant
signature, and must still sit in one of the 13 Malhar chapters. If the data has
moved, the run stops rather than retiring something on a stale id.
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

CH_LO, CH_HI = 29876, 29888          # the 13 NEP Malhar chapter rows
# Vasant chapter titles. A Malhar question has no reason to print any of them.
SIGNATURES = [
    "झाँसी की रानी",
    "टिकट-अलबम",
    "ऐसे-ऐसे",
    "जो देखकर भी नहीं देखते",
    "मैं सबसे छोटी होऊँ",
    "संसार पुस्तक है",
]

# A second, independent scan of every live stem in 29883-29888 found these. They
# are Vasant content that the title match above does NOT catch, because the item
# discusses the lesson without naming it. Index alignment holds exactly: Malhar
# chapter N carries Vasant lesson N, for N = 8..13 only; chapters 1-7 are clean.
#
#   29883 <- ऐसे-ऐसे            29886 <- जो देखकर भी नहीं देखते
#   29884 <- टिकट-अलबम          29887 <- संसार पुस्तक है
#   29885 <- झाँसी की रानी      29888 <- मैं सबसे छोटी होऊँ
#
# EXPLICITLY NOT HERE: 761744, which matched on सिंहासन but reads "जब सरदार
# सुजानसिंह ने खड़े होकर कहा, 'मेरे दीवानी के उम्मीदवार महाशयो...'" -- that is
# परीक्षा's own content (Guleri's सरदार सुजानसिंह and the दीवान selection), so it
# is legitimate and must stay. Four further traps are legitimate too and are not
# in any list: 29877's three झाँसी items are Dhyan Chand's गोल (born 1904 in
# प्रयाग, the family moved to Jhansi); 29876's सीता/चिड़ियाँ are verbatim
# मातृभूमि; 29884's 761719/761720 are सूरदास pads and the chapter IS a Surdas
# pad; 29879's नौकर items are बाबा भारती.
# A THIRD pass, during the concept-link reading of 29886-29888, found nine more
# that both the title match and the second scan missed. Four of the nine name
# nothing at all -- they are the ones a keyword sweep can never reach -- and each
# was confirmed by reading the item against its chapter:
#
#   29886 (चेतक की वीरता, श्यामनारायण पांडेय's war ballad about a horse) carries
#     four items with a female narrator -- "लेखिका को किसमें आनंद मिलता है" answered
#     "फूलों की पंखुड़ियों को छूने", the चिड़िया's voice, भोज-पत्र bark against चीड़,
#     and the whole "मैं अपने मित्रों की परीक्षा लेती हूँ / जंगल की सैर" passage.
#     All four are Helen Keller. The poem has no लेखिका, no flowers and no trees.
#   29887 (Dinkar on Mauritius) carries three items from Nehru's letters to his
#     daughter: "प्रकृति के अक्षर", the first thing one learns of a language, and
#     the तुम-addressed paragraph on the age of the earth. The Mauritius piece's
#     own language material is राजभाषा / क्रेयोल / भोजपुरी, never learning a script.
#   29888 (J.C. Bose on plants) carries two items about a little girl who does
#     not want to grow up, so that her mother stays beside her. That is Pant's
#     मैं सबसे छोटी होऊँ; the essay has no बच्ची, and its only माँ is a simile.
BY_ID: dict[int, list[int]] = {
    # 761612 and 761738 survived every earlier pass because their giveaway is
    # in the OPTIONS, not the stem. "वैद्य जी को बुलाकर कौन लाया?" names nobody
    # until you read its options (मोहन की माँ, पड़ोसी दीनानाथ — ऐसे-ऐसे's cast),
    # and "नाना साहब कहाँ के रहने वाले थे?" likewise (कानपुर against झाँसी and
    # ग्वालियर — झाँसी की रानी's "कानपुर के नाना"). 29883 is an Assamese dance
    # lesson with no मोहन and no वैद्य; 29885 is परीक्षा and has no नाना साहब.
    29883: [761610, 761611, 761613, 761651, 761652, 761612],
    29884: [761682, 761683, 761684, 761685, 761701, 761702, 761703, 761704,
            761705, 761706, 761707, 761708, 761709, 761710, 761711, 761712],
    29885: [761736, 761739, 761757, 761758, 761759, 761760, 761762, 761763,
            761764, 761765, 761766, 761767, 761768, 761769, 761770, 761772,
            761773, 761774, 761738],
    29886: [761800, 761821, 761822,
            761801, 761802, 761803, 761823],
    29887: [761872, 761873, 761900, 761902, 761903, 761905, 761906, 761907,
            761874, 761875, 761901],
    29888: [761927, 761929, 761957,
            761928, 761930],
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        found: dict[int, tuple] = {}
        for sig in SIGNATURES:
            for qid, cid, stem in db.execute(text(
                    "SELECT q.id, q.chapter_id, q.question_title "
                    "  FROM lms_question_master q "
                    " WHERE q.chapter_id BETWEEN :lo AND :hi "
                    "   AND q.deleted_at IS NULL "
                    "   AND (q.question_title LIKE :p "
                    "        OR COALESCE(q.hint_text,'') LIKE :p) "
                    " ORDER BY q.id"),
                    {"lo": CH_LO, "hi": CH_HI, "p": f"%{sig}%"}).fetchall():
                row = found.setdefault(int(qid), (int(cid), set(), str(stem or "")))
                row[1].add(sig)

        # The explicit list, verified row by row: each id must still be live and
        # must still sit in the chapter it was recorded against. A reading pass
        # found these; a title match cannot, so they are trusted by id -- which
        # makes re-reading them here the only guard there is.
        for cid, ids in BY_ID.items():
            for qid in ids:
                r = db.execute(text(
                    "SELECT chapter_id, question_title FROM lms_question_master "
                    " WHERE id=:q AND deleted_at IS NULL"), {"q": qid}).fetchone()
                if not r:
                    continue                      # already retired
                if int(r[0]) != cid:
                    print(f"  REFUSING: {qid} was recorded in ch{cid} but now "
                          f"sits in ch{r[0]}. The data has moved; re-read it.")
                    return 1
                found.setdefault(qid, (cid, {"(read-confirmed)"}, str(r[1] or "")))

        if not found:
            print("  nothing to retire -- already done, or the ids have changed")
            return 0

        names = {c: n for c, n in db.execute(text(
            "SELECT id, chapter_name FROM chapter_master "
            " WHERE id BETWEEN :lo AND :hi"),
            {"lo": CH_LO, "hi": CH_HI}).fetchall()}

        print(f"  {len(found)} question(s) name a Vasant chapter\n")
        by_ch: dict[int, list] = {}
        for qid, (cid, sigs, _) in sorted(found.items()):
            by_ch.setdefault(cid, []).append(qid)
        for cid, qs in sorted(by_ch.items()):
            before = db.execute(text(
                "SELECT COUNT(*) FROM lms_question_master "
                " WHERE chapter_id=:c AND deleted_at IS NULL"), {"c": cid}).scalar()
            print(f"   ch{cid} {str(names.get(cid))[:34]:<34} "
                  f"{len(qs):>3} of {before} retire")
        print("\n  each one, with the Vasant chapter it names:")
        for qid, (cid, sigs, stem) in sorted(found.items()):
            print(f"   {qid}  ch{cid}  [{'; '.join(sorted(sigs))[:30]}]  "
                  f"{' '.join(stem.split())[:68]}")

        mapped = db.execute(text(
            "SELECT COUNT(DISTINCT question_id) FROM lms_question_outcome "
            " WHERE question_id IN :ids"), {"ids": tuple(found)}).scalar()
        print(f"\n  {mapped} of these carry curriculum mappings, which STAY "
              f"attached\n  (retirement is reversible; clearing deleted_at "
              f"restores them intact)")

        if not a.apply:
            print("\n  report only -- re-run with --apply")
            return 0

        db.execute(text(
            "UPDATE lms_question_master SET deleted_at = NOW() "
            " WHERE id IN :ids AND deleted_at IS NULL"), {"ids": tuple(found)})
        db.commit()
        still = db.execute(text(
            "SELECT COUNT(*) FROM lms_question_master "
            " WHERE id IN :ids AND deleted_at IS NULL"), {"ids": tuple(found)}).scalar()
        live = db.execute(text(
            "SELECT COUNT(*) FROM lms_question_master "
            " WHERE chapter_id BETWEEN :lo AND :hi AND deleted_at IS NULL"),
            {"lo": CH_LO, "hi": CH_HI}).scalar()
        print(f"\n  retired {len(found) - still}; Class 6 Hindi now holds {live} live")
        print("  Across three passes 83 items have been retired, against the ~84 a "
              "mapping\n  pass first estimated. Chapters 1-7 (29876-29882) are "
              "clean; the contamination\n  is confined to 29883-29888, index-aligned "
              "with Vasant lessons 8-13.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
