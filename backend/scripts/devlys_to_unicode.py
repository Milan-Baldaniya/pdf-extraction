"""Convert DevLys / Kruti Dev legacy Devanagari to Unicode.

    python -m scripts.devlys_to_unicode --selftest
    python -m scripts.devlys_to_unicode --file <pdf> --page 50

Class 10 Hindi A and B extract as `fganh&v d{kk 10` -- zero per cent
Devanagari by codepoint, and unreadable. That is not damage: the pages are set
in DevLys-010 and DevLys-040, legacy fonts whose bytes are Latin characters
standing for Devanagari glyphs. `fganh` is हिंदी. The text layer is intact and
merely mis-encoded, so this is a transliteration and not an OCR problem -- see
[[devanagari-pdf-renders-fine-text-layer-lies]] for the case where it really
is one.

TWO THINGS MAKE THIS MORE THAN A LOOKUP.

  ORDER MATTERS. The mapping is applied longest sequence first, because
  "dks" is को while "d" alone is क and "ks" alone is ो. Applied shortest
  first, every long form is destroyed by its own prefix.

  THE SHORT-I MATRA MOVES. Legacy encodings print ि BEFORE the consonant it
  attaches to, matching how it is drawn; Unicode stores it AFTER. So
  "fganh" is f+g+a+n+h -> ि+ह+ं+द+ी, and the ि has to hop over the
  consonant cluster to its right. Left unmoved, every word containing a
  short i is wrong, and wrong in a way that still looks like Devanagari.

This is a wide mapping and it will not be perfect on every conjunct. Run
`--selftest` before trusting a run: it checks known strings from the book's
own cover, where the expected Unicode is not in doubt.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# DevLys-010 / Kruti Dev 010. Longest keys are applied first; the table below
# is deliberately written with the multi-character forms grouped so that a
# missing long form is visible as a gap rather than silently shadowed.
MAP: dict[str, str] = {
    # conjuncts and two-or-more character forms
    "ksa": "ों", "kas": "ों", "haZ": "िर्", "�": "",
    # "=" alone is त्र; "=k" is त्रा, so mapping "=k" to त्र swallows the
    # ा and छात्रों becomes छात्रें.
    "{k": "क्ष", "=": "त्र", "K": "ज्ञ", "|": "द्य", "}": "द्व",
    # "Ùk" is the त्त ligature and must beat bare "Ù"; read the other way
    # round, उत्तर comes out as उत्तार -- still Devanagari, still wrong.
    "Ùk": "त्त", "Ù": "त्त",
    # Half forms. "è" is ध् and "’" is श्; without them अध्याय and प्रश्न
    # keep a Latin character in the middle of a Devanagari word.
    "è": "ध्", "’": "श्", "‘": "श्",
    "Nk": "छा", "'k": "श", "\"k": "ष", "\"": "ष्", "*": "'",
    "vks": "ओ", "vkS": "औ", "vk": "आ", "v": "अ",
    "bZ": "ई", "b": "इ", "mQ": "ऊ", "m": "उ", ",s": "ऐ", ",": "ए",
    "_": "ऋ", "v‚": "ऑ", "‚": "ॉ",
    "d": "क", "[k": "ख", "x": "ग", "?k": "घ", "³": "ङ",
    "p": "च", "N": "छ", "t": "ज", ">": "झ", "¥": "ञ",
    "V": "ट", "B": "ठ", "M": "ड", "<": "ढ", ".k": "ण",
    "r": "त", "Fk": "थ", "n": "द", "/k": "ध", "u": "न",
    "i": "प", "Q": "फ", "c": "ब", "Hk": "भ", "e": "म",
    ";": "य", "j": "र", "y": "ल", "o": "व",
    "l": "स", "g": "ह", "G": "ळ",
    "k": "ा", "h": "ी", "q": "ु", "w": "ू", "`": "ृ",
    "s": "े", "S": "ै", "ks": "ो", "kS": "ौ",
    "a": "ं", "%": "ः", "¡": "ँ", "~": "्",
    "ƒ": "फ़", "T": "ज़", "Ø": "क्र", "ØQ": "क्र",
    "ç": "प्र", "Ç": "प्र", "æ": "द्र", "Ï": "क्त",
    # Half consonants, which carry no vowel of their own. Unmapped, each
    # leaves a Latin letter standing in the middle of a Devanagari word --
    # "Oयापार" for व्यापार, "जनसं[या" for जनसंख्या.
    # "I" is deliberately NOT mapped. It is प्ल inside a word, but this book
    # numbers its statements I, II, III, and converting those turns "I, II
    # and III are correct" into "प्ल, प्लप्ल and प्लप्लप्ल". A wrong option
    # label is worse than a rare missing conjunct.
    # More half consonants, each found by reading converted headers back:
    # "वाDय" for वाक्य, "वाPय" for वाच्य, "निEनलिखित" for निम्नलिखित,
    # "मUनू" for मन्नू, "शिYपकार" for शिल्पकार, "आत्मकFय" for आत्मकथ्य,
    # "संस्Ñति" for संस्कृति, "ल{मण" for लक्ष्मण, "कैIटन" for कैप्टन.
    "D": "क्", "P": "च्", "E": "म्", "U": "न्", "Y": "ल्",
    "F": "थ्", "Ñ": "कृ", "{": "क्ष्", "I": "प्", "J": "श्र",
    "O": "व्", "C": "ब्", "L": "स्", "[": "ख्",
    "/": "ध्", "èk": "ध", "Ò": "भ्", "'": "श्", "Ý": "फ्", "R": "त्",
    ":": "रू", "A": "।", "]": ",",
    "i~": "प्", "Ë": "ड्ड", "ä": "क्त", "í": "द्द", ")": "द्ध",
    # Reph, ra-kar and nukta -- marks rather than letters.
    "Z": "र्", "z": "्र", "+": "़", "È": "ीं", "Ã": "ई", "ƒ": "फ़",
    "&": "-", "¼": "(", "½": ")", "¡": "ँ",
    "É": "क्क", "Ä": "ट्ट", "Ë": "ड्ड",
    "1": "1", "2": "2", "3": "3", "4": "4", "5": "5",
    "6": "6", "7": "7", "8": "8", "9": "9", "0": "0",
}

# The short-i matra, which is printed before its consonant and stored after.
_SHORT_I = "ि"
_CONSONANT = "क-हक़-य़"
_HALANT = "्"
# ि + (consonant + optional halant + consonant ...) -> cluster + ि
_MOVE_I = re.compile(rf"{_SHORT_I}((?:[{_CONSONANT}]{_HALANT})*[{_CONSONANT}])")
# consonant + its matra + reph  ->  reph + consonant + matra
_MOVE_REPH = re.compile(rf"([{_CONSONANT}])([ा-ौ]?)र्")

_KEYS = sorted(MAP, key=len, reverse=True)
_PATTERN = re.compile("|".join(re.escape(k) for k in _KEYS))


_ROMAN = re.compile(r"(?<![A-Za-z])(?:i{1,3}v?|iv|vi{0,3}|ix|xi{0,3}|I{1,3}V?|IV|VI{0,3}|IX|XI{0,3})"
                    r"(?=[.)\s\]])")
# A run of three or more capitals with no lowercase among them is a Latin
# acronym, not legacy Devanagari: CBSE, NODIA, PYQ. Legacy words mix cases
# ("LekVZ" is स्मार्ट), so this does not catch them. Left converted, the
# running header reads "ब्ठैम् कक्षा 10".
_ACRONYM = re.compile(r"(?<![A-Za-z])[A-Z]{3,}(?![a-z])")


def convert(text: str) -> str:
    """Legacy bytes to Unicode, longest match first, then move the matras."""
    if not text:
        return text
    # ROMAN NUMERALS ARE LATIN AND MUST SURVIVE. "i" is प and "v" is अ, so
    # an option list numbered i, ii, iii converts to प, पप, पपप -- the
    # labels a reader needs in order to answer. They are set aside first.
    held: list[str] = []

    def _hold(m):
        held.append(m.group(0))
        return f"\x00{len(held) - 1}\x00"

    out = _ACRONYM.sub(_hold, text)
    out = _ROMAN.sub(_hold, out)
    out = _PATTERN.sub(lambda m: MAP[m.group(0)], out)
    # "f" is the short i and survives the table as a bare marker.
    out = out.replace("f", _SHORT_I)
    # ONCE, NOT REPEATEDLY. Looped, the matra hops the next consonant too:
    # प्रौद्योगिकी comes out as प्रौद्योगकिी and शिक्षा as शक्षिा -- each
    # still Devanagari, each a different word.
    out = _MOVE_I.sub(r"\1" + _SHORT_I, out)
    # THE REPH MOVES THE OTHER WAY. Legacy prints र् after the consonant it
    # sits above; Unicode stores it before. Left alone, स्मार्ट comes out
    # स्माटर् and कोर्सेस comes out कोसेर्स.
    out = _MOVE_REPH.sub(r"र्\1\2", out)
    return re.sub(r"\x00(\d+)\x00", lambda m: held[int(m.group(1))], out)


CASES = [
    ("fganh", "हिंदी"),
    ("d{kk", "कक्षा"),
    ("mÙkj", "उत्तर"),
    ("ç’u", "प्रश्न"),
    ("vè;k;", "अध्याय"),
]


def selftest() -> int:
    print("  DevLys -> Unicode, against strings whose meaning is not in doubt\n")
    print(f"  {'legacy':<14} {'got':<20} {'expected':<20} verdict")
    print("  " + "-" * 66)
    bad = 0
    for src, want in CASES:
        got = convert(src)
        ok = got == want
        bad += 0 if ok else 1
        print(f"  {src:<14} {got:<20} {want:<20} {'ok' if ok else 'MISMATCH'}")
    print(f"\n  {len(CASES) - bad}/{len(CASES)} exact")
    if bad:
        print("  A mismatch here means the table is wrong for that form. Do not\n"
              "  load a book on a failing selftest -- the output still looks like\n"
              "  Devanagari and the error is invisible downstream.")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--file")
    ap.add_argument("--page", type=int, default=50)
    a = ap.parse_args()
    if a.file:
        import fitz
        fitz.TOOLS.mupdf_display_errors(False)
        doc = fitz.open(a.file)
        raw = doc[a.page - 1].get_text() or ""
        doc.close()
        print("--- raw:\n" + " ".join(raw.split())[:600])
        print("\n--- converted:\n" + " ".join(convert(raw).split())[:600])
        return 0
    return selftest()


if __name__ == "__main__":
    raise SystemExit(main())
