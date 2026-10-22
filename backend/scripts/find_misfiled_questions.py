"""Find questions filed under a chapter they are not about.

    python -m scripts.find_misfiled_questions
    python -m scripts.find_misfiled_questions --standard 41

Read-only. Nothing is moved; this only reports.

Class 8's "Resources" chapter -- Geography -- held 34 questions about the 1857
revolt, while "When People Rebel: 1857 and After" held none. Nothing flagged
it: the chapter reported 76 questions and looked healthy, and the empty
chapter looked like a sourcing gap rather than a filing error.

HOW IT FINDS THEM. Questions arrive in blocks, and a block loaded against the
wrong chapter keeps its own contiguous run of ids. So each chapter is split
into id runs, and the runs are compared on vocabulary. One run that shares
almost no content words with the others is a block that does not belong -- it
was the giveaway in the Class 8 case, where ids 110089-110130 talked about
renewable resources and 110568-110601 about sepoys and Nawabs.

A second, independent check: whether a run's vocabulary matches some OTHER
chapter's name in the same class and subject better than its own. That names
the chapter the block probably belongs to, which the first check cannot.

Both are signals, not verdicts. Every hit needs reading before anything moves.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

STOP = set("""the a an of and or to in is are was were be been for on at by with from as
that this these those it its which what who whom when where how why not no all any some
following given below above each both more most other another such only own same so than
too very can will just should now do does did has have had he she they them his her their
you your we our i me my if then else about into over under again further once here there
when while during before after between out off up down out name names state give explain
describe define write list mention discuss identify choose select correct answer question
option options true false blank fill match column following one two three four five""".split())
NUM = re.compile(r"^\d+$")


def words(t: str) -> Counter:
    ws = re.findall(r"[A-Za-zऀ-ॿ]{3,}", (t or "").lower())
    return Counter(w for w in ws if w not in STOP and not NUM.match(w))


def runs(ids: list[int], gap: int = 150) -> list[list[int]]:
    out, cur = [], [ids[0]]
    for a, b in zip(ids, ids[1:]):
        if b - a > gap:
            out.append(cur); cur = []
        cur.append(b)
    out.append(cur)
    return [r for r in out if r]


def overlap(a: Counter, b: Counter) -> float:
    """Share of the smaller run's top vocabulary that the larger one also uses."""
    ta = {w for w, _ in a.most_common(40)}
    tb = {w for w, _ in b.most_common(40)}
    if not ta or not tb:
        return 1.0
    return len(ta & tb) / min(len(ta), len(tb))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--standard", type=int)
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        where = "c.standard_id = :s" if a.standard else "c.standard_id BETWEEN 39 AND 43"
        rows = db.execute(text(
            f"SELECT c.id, c.standard_id, COALESCE(s.subject_name,'?'), c.chapter_name, "
            f"       q.id, q.question_title "
            f"  FROM chapter_master c "
            f"  LEFT JOIN subject s ON s.id = c.subject_id "
            f"  JOIN lms_question_master q ON q.chapter_id = c.id "
            f" WHERE {where} ORDER BY c.id, q.id"),
            {"s": a.standard} if a.standard else {}).fetchall()
    finally:
        db.close()

    chapters: dict[int, dict] = {}
    for cid, std, subj, cname, qid, title in rows:
        d = chapters.setdefault(int(cid), {"std": int(std), "subj": str(subj),
                                           "name": str(cname), "q": []})
        d["q"].append((int(qid), str(title or "")))

    # chapter-name vocabulary, per (standard, subject), for the second check
    by_subject: dict[tuple, list] = {}
    for cid, d in chapters.items():
        by_subject.setdefault((d["std"], d["subj"]), []).append((cid, d["name"]))

    print(f"  swept {len(chapters)} chapters holding questions\n")
    flagged = 0
    for cid, d in sorted(chapters.items()):
        ids = [q for q, _ in d["q"]]
        if len(ids) < 12:
            continue
        rr = runs(ids)
        if len(rr) < 2:
            continue
        text_of = dict(d["q"])
        vocab = [words(" ".join(text_of[i] for i in r)) for r in rr]
        big = max(range(len(rr)), key=lambda k: len(rr[k]))
        for k, r in enumerate(rr):
            if k == big or len(r) < 5:
                continue
            ov = overlap(vocab[k], vocab[big])
            if ov > 0.12:
                continue
            flagged += 1
            top = ", ".join(w for w, _ in vocab[k].most_common(6))
            print(f"  cid {cid}  {d['subj']} / {d['name'][:40]}")
            print(f"      ids {r[0]}-{r[-1]} ({len(r)} questions) share {ov*100:.0f}% of "
                  f"their vocabulary with the chapter's main block")
            print(f"      they are about: {top}")
            # which chapter in the same subject do they look like?
            best, score = None, 0.0
            for other_cid, other_name in by_subject[(d["std"], d["subj"])]:
                if other_cid == cid:
                    continue
                nv = words(other_name)
                if not nv:
                    continue
                hit = sum(vocab[k][w] for w in nv) / max(sum(vocab[k].values()), 1)
                if hit > score:
                    best, score = (other_cid, other_name), hit
            if best and score > 0.002:
                print(f"      closest other chapter in this subject: "
                      f"{best[0]} {best[1][:44]}")
            print(f"      sample: {text_of[r[0]][:86]}")
            print()
    print(f"  {flagged} block(s) worth reading. None has been moved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
