"""Check three ways that the option marked correct is the right one.

    python -m scripts.audit_answer_keys
    python -m scripts.audit_answer_keys --standard 41 --limit 40
    python -m scripts.audit_answer_keys --check letter_vs_value

Read-only. Nothing is written; this only reports.

A wrong key is the defect that reaches a student most directly and the one no
validator sees. V-02 checks that `correct_option` names an option that exists
and V-04 that an mcq has one at all, but neither can tell that the option named
is the wrong one. A spot check of seven flagged questions found four wrong,
including "Where is the stool temporarily stored before elimination?" -- whose
own inline text says the rectum -- marked as Stomach.

`lms_question_extraction.verbatim_payload` holds the item as it was read, and
for most of the bank that is JSON carrying `options[].is_correct` and an
`answer_text`. `answer_master` stores the options in insertion order with a 0/1
flag and no label. Between them three independent checks are possible, and they
fail for different reasons, so the report keeps them apart:

    FIDELITY      the payload's own is_correct flag against the stored flag.
                  A disagreement is OUR bug -- the loader lost the key.
    LETTER/VALUE  answer_text often prints both, "(c) beautiful". Where the
                  letter points at one option and the text names another, the
                  SOURCE contradicts itself. This is the defect recorded in
                  `qbank-solution-letter-contradicts-its-value`, and keying on
                  the value is what parse_ziet_maths.py settled on.
    VALUE/MARKED  answer_text's value against the option actually marked. This
                  is the one that matters to a student, and it catches cases
                  the other two miss.

WHAT IT CANNOT SEE. Only rows with a sidecar carry a payload, so the 11,572
LMS-native questions are invisible here -- see `qbank-two-kinds-of-question`.
An item whose printed key and stored key are wrong in the same direction also
passes. This narrows the problem; it does not clear the bank.

Nothing here writes. A disagreement is a question to read, not a row to flip:
a source's own solution can be wrong, and only reading the item settles it.
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

# A leading label on answer_text: "(c) beautiful", "c. beautiful", "(ख) ...".
# \u0001 turns up as a separator in the Hindi payloads and is stripped first.
LEAD = re.compile(r"^[\s\u0001]*[\(\[]?\s*([A-Da-dक-घ])\s*[\)\].:\-]\s*")
HINDI = {"क": "A", "ख": "B", "ग": "C", "घ": "D"}
WS = re.compile(r"\s+")
# Strip anything that is not a letter or digit in any script, so that option
# text and answer text compare on content and not on punctuation or spacing.
BARE = re.compile(r"[^0-9a-zऀ-ॿ]+")

CHECKS = ("fidelity", "letter_vs_value", "value_vs_marked")


def norm(s: str) -> str:
    return WS.sub(" ", (s or "").replace("\u0001", " ")).strip()


def bare(s: str) -> str:
    return BARE.sub("", norm(s).lower())


def split_answer(ans: str) -> tuple[int | None, str]:
    """An answer_text into (letter index or None, the remaining value)."""
    a = norm(ans)
    m = LEAD.match(a)
    if not m:
        return None, a
    ch = m.group(1)
    letter = HINDI.get(ch, ch.upper())
    return ord(letter) - 65, a[m.end():].strip()


def usable_value(value: str) -> str | None:
    """The part of an answer_text that actually names an option.

    Three shapes occur, and taking the whole string works for only one:

        "beautiful"                         bare -- use as is
        "Rs 400. a7 = 100 + 6(50) = Rs 400" value first, then the working --
                                            the head before the first stop
        "cos(a+b) = 0 = cos 90, so cos 2b"  working first, answer last --
                                            the tail after the last = or "so"

    Prefix-matching the whole derivation picks whichever option shares its
    opening words, which gave five false positives in eight on the first run.
    Skipping every derivation instead hid two genuine wrong keys in Class 9
    Maths, where the marked option contradicted the source's own arithmetic.
    So each shape is reduced to its answer before matching, and anything that
    still does not reduce is skipped rather than guessed at.
    """
    v = norm(value)
    if is_clean_value(v):
        return v
    head = re.split(r"(?<![0-9])[.;]\s|\s[-–]\s", v, maxsplit=1)[0].strip()
    if head and head != v and is_clean_value(head):
        return head
    tail = re.split(r"(?i)=|\b(?:so|hence|therefore|thus)\b", v)[-1].strip()
    tail = tail.strip(" .,;:")
    if tail and is_clean_value(tail) and len(tail) >= 1:
        return tail
    return None


def is_clean_value(value: str) -> bool:
    """Is this answer_text a bare answer, or a worked solution?

    Many rows store the whole derivation -- "cos(a+b)=0=cos 90 degrees, so ...,
    therefore cos 2b" -- and the option it names is at the END, not the start.
    Prefix-matching such a string picks whichever option happens to share its
    opening words, which produced five false positives out of eight on the
    first run. A derivation gives itself away by working: an equals sign, a
    "so/hence/therefore", or simple length.
    """
    v = norm(value)
    if len(v) > 60 or "=" in v:
        return False
    return not re.search(r"(?i)\b(so|hence|therefore|thus|since|because)\b", v)


def matches(value: str, option: str) -> bool:
    """Does an answer's value name this option? Prefix either way, so a
    truncated option (answer_master.answer is varchar(250)) still matches."""
    v, o = bare(value), bare(option)
    if not v or not o:
        return False
    return v.startswith(o[:max(len(o) // 2, 8)]) or o.startswith(v[:max(len(v) // 2, 8)])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--standard", type=int)
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--check", choices=CHECKS, help="print examples for one only")
    a = ap.parse_args()

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        where = ("c.standard_id = :s" if a.standard
                 else "c.standard_id BETWEEN 39 AND 43")
        p = {"s": a.standard} if a.standard else {}
        rows = db.execute(text(
            f"SELECT q.id, c.standard_id, COALESCE(s.subject_name,'?'), "
            f"       c.chapter_name, q.question_title, e.verbatim_payload "
            f"  FROM lms_question_master q "
            f"  JOIN chapter_master c ON c.id = q.chapter_id "
            f"  LEFT JOIN subject s ON s.id = c.subject_id "
            f"  JOIN lms_question_extraction e ON e.question_id = q.id "
            f" WHERE {where} AND e.verbatim_payload IS NOT NULL "
            f" ORDER BY q.id"), p).fetchall()
        print(f"  {len(rows)} sidecar-backed questions in scope")

        stored: dict[int, list] = {}
        for qid, txt, ok in db.execute(text(
                f"SELECT am.question_id, am.answer, am.correct_answer "
                f"  FROM answer_master am "
                f"  JOIN lms_question_master q ON q.id = am.question_id "
                f"  JOIN chapter_master c ON c.id = q.chapter_id "
                f" WHERE {where} ORDER BY am.question_id, am.id"), p).fetchall():
            stored.setdefault(int(qid), []).append((str(txt or ""), int(ok or 0)))

        seen = {c: 0 for c in CHECKS}
        hits: dict[str, list] = {c: [] for c in CHECKS}
        not_json = no_opts = 0

        for qid, std, subj, chap, stem, payload in rows:
            opt = stored.get(int(qid)) or []
            if len(opt) < 2:
                no_opts += 1
                continue
            marked = [i for i, (_, ok) in enumerate(opt) if ok]
            if len(marked) != 1:
                continue
            mk = marked[0]
            try:
                d = json.loads(str(payload))
            except (ValueError, TypeError):
                not_json += 1
                continue
            if not isinstance(d, dict):
                not_json += 1
                continue

            where_at = (std, subj, chap, stem)
            src = d.get("options")
            if isinstance(src, list) and len(src) == len(opt):
                flagged = [i for i, o in enumerate(src)
                           if isinstance(o, dict) and o.get("is_correct")]
                if len(flagged) == 1:
                    seen["fidelity"] += 1
                    if flagged[0] != mk:
                        hits["fidelity"].append(
                            (qid, *where_at, chr(65 + flagged[0]), chr(65 + mk),
                             norm(str(src[flagged[0]].get("text", ""))),
                             norm(opt[mk][0])))

            ans = d.get("answer_text") or d.get("answer") or ""
            if not isinstance(ans, str) or not norm(ans):
                continue
            idx, value = split_answer(ans)

            use = usable_value(value) if value else None
            if idx is not None and 0 <= idx < len(opt) and use:
                seen["letter_vs_value"] += 1
                if not matches(use, opt[idx][0]):
                    named = [i for i, (t, _) in enumerate(opt)
                             if matches(use, t)]
                    if len(named) == 1:
                        hits["letter_vs_value"].append(
                            (qid, *where_at, chr(65 + idx),
                             chr(65 + named[0]), use, opt[idx][0]))

            if use:
                seen["value_vs_marked"] += 1
                if not matches(use, opt[mk][0]):
                    named = [i for i, (t, _) in enumerate(opt)
                             if matches(use, t)]
                    if len(named) == 1 and named[0] != mk:
                        hits["value_vs_marked"].append(
                            (qid, *where_at, chr(65 + named[0]), chr(65 + mk),
                             use, opt[mk][0]))

        print(f"  skipped: {not_json} payloads not JSON, {no_opts} without options\n")
        for c in CHECKS:
            n, t = len(hits[c]), seen[c]
            pct = f"  ({n * 100.0 / t:.1f}%)" if t else ""
            print(f"  {c:<16} checked {t:>6}   DISAGREE {n}{pct}")

        for c in CHECKS:
            if not hits[c] or (a.check and a.check != c):
                continue
            by: dict[tuple, int] = {}
            for _, std, subj, *_ in hits[c]:
                by[(std, subj)] = by.get((std, subj), 0) + 1
            print(f"\n  === {c}: by class and subject")
            for (std, subj), n in sorted(by.items(), key=lambda kv: -kv[1]):
                print(f"    std {std}  {str(subj)[:30]:<30} {n}")
            print(f"  first {min(a.limit, len(hits[c]))} to read:")
            for (qid, std, subj, chap, stem, want, got,
                 wtxt, gtxt) in hits[c][:a.limit]:
                print(f"\n    qid {qid}  std {std} {str(subj)[:18]} / "
                      f"{str(chap)[:32]}")
                print(f"       stem    {norm(str(stem))[:98]}")
                print(f"       source  ({want}) {norm(wtxt)[:68]}")
                print(f"       marked  ({got}) {norm(gtxt)[:68]}")

        print("\n  Read-only. Nothing was changed.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
