"""Deterministic chapter-markdown analysis shared by the Topic and Concept queues.

Everything here is pure text work -- no LLM, no database. The Topic Queue uses
it to describe a chapter's own structure to the model, and both queues use
partition_by_topics to cut the chapter into one span per topic.

It lives in its own module because both services need the identical notion of
"a section" and "a name". The Topic Queue and the Concept Queue run in separate
requests, and they agree on where a topic's text begins and ends only because
each derives it from the same pure function over the same persisted inputs.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List

# A topic span shorter than this is a sign the chapter was split too finely --
# a real teaching unit carries more text than this. Not enforced, only reported.
MIN_TOPIC_SPAN_CHARS = 800

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", re.MULTILINE)

# Indic vowel signs and the virama are combining marks, and str.isalnum() is
# False for them -- so a plain \w+ split shreds "प्रकाश" into "प रक श" and would
# collapse genuinely different Hindi words onto one key. Marks are kept.
_MARK_CATEGORIES = {"Mn", "Mc", "Me"}

_STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "in", "on", "to", "for", "is", "are",
    "was", "were", "be", "by", "with", "as", "at", "from", "its", "it", "this",
    "that", "these", "those", "how", "what", "why", "we", "you", "their",
}


def tokenise(value: str) -> List[str]:
    cleaned = "".join(
        ch if (ch.isalnum() or unicodedata.category(ch) in _MARK_CATEGORIES) else " "
        for ch in (value or "").lower()
    )
    return cleaned.split()


def tokens(value: str) -> List[str]:
    return [t for t in tokenise(value) if t not in _STOPWORDS]


def normalise_name(value: str) -> str:
    """Collapse a name to a display-order comparison key."""
    return " ".join(tokenise(value))


def match_key(value: str) -> str:
    """The natural key an upsert matches an existing row on.

    Stopwords are dropped, plurals folded, and the rest sorted, so the same
    teaching unit keeps its row across re-runs even when the model rewords it:
    "Integers and number line" and "Integers and the Number Line" are the same
    topic, and normalise_name calls them different because it keeps "the".

    That difference is not cosmetic. A missed match INSERTS a second row and
    hides the first, so every concept hanging off the original is stranded on a
    hidden parent -- and topic_master ids are referenced by content_master,
    lms_question_master and lms_lesson_plan, which would then point at rows the
    ERP no longer lists. One re-run of chapter 147 churned all 17 topic ids this
    way.
    """
    return " ".join(sorted(singular(t) for t in tokens(value)))


# MinerU marks page breaks as headings, and routinely promotes an entire
# opening paragraph to a single "# ..." line. Neither is a section title, and
# the prompts tell the model to prefer headings, so both have to be kept out of
# the outline or they become the topic names it copies.
_PAGE_HEADING_RE = re.compile(r"^page\s*[-#]?\s*\d+$", re.IGNORECASE)
MAX_HEADING_CHARS = 90


# Layout furniture MinerU promotes to a heading. None of it names a teaching
# unit, and rule 6 tells the model to prefer headings -- so left in the outline
# these become the topic names it copies ("Continued", "Tip A triathlon is a
# competition in which people swim", "19 2 11").
_HEADING_NOISE_RE = re.compile(
    r"^(?:continued|contents?|note|tip|key ?words?|activity|worked example"
    r"|summary(?: checklist)?|exercises?|glossary|answers?|project)\b[\s:.-]*",
    re.IGNORECASE,
)


def _is_real_heading(title: str) -> bool:
    if not title or len(title) > MAX_HEADING_CHARS or _PAGE_HEADING_RE.match(title):
        return False
    if _HEADING_NOISE_RE.match(title):
        return False
    # "19 2 11" and "- Integers": a title needs at least two real words, or one
    # long one, before it can stand as a topic name.
    words = [w for w in tokens(title) if len(w) >= 3 and not w.isdigit()]
    return len(words) >= 2 or any(len(w) >= 6 for w in words)


# MinerU rarely promotes a textbook's section title to a markdown heading -- it
# swallows it into the surrounding paragraph -- but the numbering survives
# verbatim ("9.1 REFLECTION OF LIGHT", "1.1 Adding and subtracting integers").
# Those numbers are the real outline; markdown headings alone leave the model
# nothing to anchor topic names to.
_NUMBERED_CANDIDATE_RE = re.compile(
    r"(?<![\w.])(\d{1,2}\.\d{1,2}(?:\.\d{1,2})?)\s+([A-Z][^\n]{4,110})"
)

# Two independent ways a candidate proves it is a real section title, because
# the two textbook families in this corpus style them differently:
#
#   NCERT      "9.1 REFLECTION OF LIGHT"          -- all caps
#   Cambridge  "1.1 Adding and subtracting integers In this section you will .."
#              -- title case, but always followed by the section-opener phrase
#
# Title case alone is not enough: exercise and worked-example numbering looks
# identical ("1.1 Work out: -4+6", "Worked example 1.8 a Find the HCF"), and
# accepting it turns every exercise into a section boundary.
_SECTION_OPENER_RE = re.compile(r"\bin this (?:section|unit|chapter)\b", re.IGNORECASE)
_ALL_CAPS_TITLE_RE = re.compile(r"^[A-Z][A-Z0-9 ,\-'()/&]{4,70}$")

# Callout boxes and exercise labels that carry the same numbering as a title.
_SECTION_NOISE = {"CAUTION", "ACTIVITY", "NOTE", "EXAMPLE", "EXERCISE", "QUESTION"}


def _trim_title(words: List[str]) -> str | None:
    # A title runs straight into the next sentence, whose capitalised first
    # letter gets swept into the match ("9.1 REFLECTION OF LIGHT A").
    while words and len(words[-1]) == 1:
        words.pop()
    if not words or words[0].upper() in _SECTION_NOISE:
        return None
    # Rejects numeric false positives such as "0.5 A X 600".
    if not any(len(w) >= 4 and w.isalpha() for w in words):
        return None
    return " ".join(words)


# The section-opener phrase follows the title immediately. Searching the whole
# candidate lets a passing "as we will study in this chapter" hundreds of
# characters later be read as the opener, which then returns everything before
# it -- a whole paragraph -- as the title.
_OPENER_SEARCH_CHARS = 120


def _clean_section_title(raw: str) -> str | None:
    """A confirmed section title, or None if this candidate is not one."""
    raw = raw.strip()

    # Cambridge form: the title is whatever precedes the section-opener phrase.
    opener = _SECTION_OPENER_RE.search(raw[:_OPENER_SEARCH_CHARS])
    if opener:
        return _trim_title(raw[: opener.start()].split())

    # NCERT form: all caps, and only as much of the line as stays all caps.
    words, capped = raw.split(), []
    for word in words:
        if word.upper() != word:
            break
        capped.append(word)
    candidate = " ".join(capped)
    if _ALL_CAPS_TITLE_RE.match(candidate):
        return _trim_title(capped)
    return None


def numbered_sections(md_content: str) -> List[Dict[str, Any]]:
    """Numbered section titles found in the body text, with their offsets.

    `depth` is how many parts the number has. NCERT numbers two levels deep --
    "1.1 CHEMICAL EQUATIONS" holds "1.1.1 Writing a Chemical Equation" -- and
    only the depth-2 entries are chapter topics. Both depths are returned; it is
    up to the caller to say which it wants (split_sections wants every boundary,
    topic_outline wants only the topic level).
    """
    found = []
    for match in _NUMBERED_CANDIDATE_RE.finditer(md_content or ""):
        title = _clean_section_title(match.group(2))
        if title:
            number = match.group(1)
            found.append({
                "number": number,
                "title": title,
                "start": match.start(),
                "depth": number.count(".") + 1,
            })
    return found


def heading_outline(md_content: str, limit: int = 150) -> str:
    """The chapter's real headings, in document order.

    Fed to the LLM as naming candidates so it maps onto the book's own
    sub-headings instead of inventing names.
    """
    entries = []
    for match in _HEADING_RE.finditer(md_content or ""):
        title = match.group(2).strip()
        if _is_real_heading(title):
            entries.append((match.start(), f"{'  ' * (len(match.group(1)) - 1)}- {title}"))
    for section in numbered_sections(md_content):
        entries.append((section["start"], f"- {section['number']} {section['title']}"))

    entries.sort(key=lambda e: e[0])
    lines, seen = [], set()
    for _, line in entries:
        key = normalise_name(line)
        if key and key not in seen:
            seen.add(key)
            lines.append(line)
        if len(lines) >= limit:
            break
    return "\n".join(lines) if lines else "(no usable headings found in this chapter)"


# Enough numbered sections to trust them as the chapter's own topic list. Two is
# too few to tell a real outline from a stray pair of matches -- chapter 149
# yields exactly two and its real structure is wider than that.
_TRUSTED_OUTLINE_MIN = 3

# A heading that already carries the book's section number, e.g. "## 1.1 CHEMICAL
# EQUATIONS". MinerU promotes NCERT's section titles to markdown headings but
# leaves Cambridge's inline, so the two families arrive by different routes and
# both have to be read: numbered_sections() scans body text and finds only 2 of
# NCERT chapter 1's sections, while its headings carry the full set.
_NUMBERED_HEADING_RE = re.compile(r"^(\d{1,2}\.\d{1,2}(?:\.\d{1,2})?)[ \t]+(.+)$")


# Past this a "heading" is a title with the following sentence swept into it:
# "1.1 INTRODUCTION A system of coordinates is a structured way to ...". Real
# section titles are short, so anything longer gets trimmed and anything shorter
# is left exactly as the book wrote it.
_TITLE_BLEED_CHARS = 60


# Last-resort length for a title nothing else could cut. Rule 7 of the topic
# prompt asks for 2 to 8 words, so this matches what a topic name may be.
_TITLE_MAX_WORDS = 8


def _trim_bleed(title: str) -> str:
    """Cut a run-on heading back to the title the book actually printed.

    MinerU can promote an entire opening paragraph to a single heading -- one
    chapter yielded a 2,088-character "1.1" -- so nothing here may assume the
    input is heading-sized.
    """
    if len(title) <= _TITLE_BLEED_CHARS:
        return title

    # NCERT sets titles in caps, so the caps run is the title. Bounded, because
    # the recogniser is meant for heading-length input.
    cleaned = _clean_section_title(title[:_OPENER_SEARCH_CHARS * 2]) or title
    if len(cleaned) <= _TITLE_BLEED_CHARS:
        return cleaned

    # Otherwise the sentence that follows starts with a capital, and the title
    # is everything before it: "Introduction | We are one of the oldest ...",
    # "Adding and subtracting integers | In this section you will ...".
    words = cleaned.split()
    for index in range(1, min(len(words), _TITLE_MAX_WORDS + 1)):
        if words[index][:1].isupper():
            return " ".join(words[:index])
    return " ".join(words[:_TITLE_MAX_WORDS])


def _numbered_headings(md_content: str) -> List[Dict[str, Any]]:
    """Markdown headings that begin with a section number."""
    found = []
    for match in _HEADING_RE.finditer(md_content or ""):
        numbered = _NUMBERED_HEADING_RE.match(match.group(2).strip())
        if not numbered:
            continue
        title = _trim_bleed(numbered.group(2).strip())
        # The number proves this is a section title, so _is_real_heading's
        # word-count guard is unnecessary here -- but a numbered callout box is
        # still not a section.
        if not title or title.split()[0].upper() in _SECTION_NOISE:
            continue
        number = numbered.group(1)
        found.append({
            "number": number,
            "title": title[:MAX_HEADING_CHARS],
            "start": match.start(),
            "depth": number.count(".") + 1,
        })
    return found


def topic_outline(md_content: str) -> tuple[str, bool]:
    """The chapter's own topic-level outline, and whether it can be trusted.

    Returns (text, is_authoritative). When the book numbers its sections, those
    numbers ARE the chapter's topics and the caller can tell the model to use
    them verbatim. Only depth-2 numbers count: NCERT's "1.1.1" entries sit
    *inside* "1.1" and listing them invites the model to split a topic in three.

    Roughly half this corpus (Hindi, Sanskrit, English, Social Science) has no
    usable structure at all, which is why this is a hint and never the answer.
    """
    candidates = numbered_sections(md_content) + _numbered_headings(md_content)
    sections = sorted((s for s in candidates if s["depth"] == 2), key=lambda s: s["start"])

    if len(sections) >= _TRUSTED_OUTLINE_MIN:
        seen_numbers, seen_names, lines = set(), set(), []
        for section in sections:
            # Both routes can surface the same section, and a running header can
            # repeat its title, so dedupe on the number and the wording alike.
            key = normalise_name(section["title"])
            if section["number"] in seen_numbers or (key and key in seen_names):
                continue
            seen_numbers.add(section["number"])
            seen_names.add(key)
            lines.append(f"- {section['number']} {section['title']}")
        if len(lines) >= _TRUSTED_OUTLINE_MIN:
            return "\n".join(lines), True

    outline = heading_outline(md_content, limit=40)
    if outline.startswith("(no usable"):
        return "(this chapter has no headings or numbered sections)", False
    return outline, False


# Blocks that revise or preview material taught elsewhere in the chapter rather
# than teaching anything new. Left in, the model reads an end-of-unit revision
# exercise as fresh content and emits a second, differently-worded copy of a
# topic it already extracted from the teaching section -- which is exactly how
# one 6-section chapter produced 25 topics instead of 16.
_REVISION_MARKERS = re.compile(
    r"\b(?:getting started|check your progress|summary checklist"
    r"|(?:unit |chapter )?(?:review|revision) exercises?)\b",
    re.IGNORECASE,
)

# Searched in the opening of the block rather than anchored at character zero:
# MinerU mangles the first word often enough that anchoring misses real markers
# ("# ntegers Getting started - Put these numbers in order"). Keeping the window
# short still stops a passing mention mid-section from retiring a teaching block.
_REVISION_WINDOW = 90


def _section_kind(text: str) -> str:
    head = " ".join((text or "").split())[:_REVISION_WINDOW]
    return "revision" if _REVISION_MARKERS.search(head) else "teaching"


def split_sections(md_content: str) -> List[Dict[str, Any]]:
    """Cut the markdown into (title, kind, text) blocks.

    Both markdown headings and inline numbered section titles are boundaries.
    Without the latter the only boundaries MinerU leaves are "## Page 7"
    markers, which cut the chapter by page rather than by subject.

    A boundary whose heading text is not a plausible title still splits the
    text, but contributes no title: MinerU routinely promotes a whole paragraph
    to "# ...", and using that as the section title makes score_section match
    topics on a paragraph prefix instead of on a real heading.
    """
    md_content = md_content or ""
    boundaries: List[tuple[int, str]] = []
    for m in _HEADING_RE.finditer(md_content):
        title = m.group(2).strip()
        boundaries.append((m.start(), title if _is_real_heading(title) else ""))
    boundaries += [(s["start"], s["title"]) for s in numbered_sections(md_content)]

    if not boundaries:
        return [{"title": "", "kind": _section_kind(md_content), "text": md_content}]

    boundaries.sort(key=lambda b: (b[0], not b[1]))
    # Two boundaries at the same spot (a numbered title right under a heading)
    # would create an empty block; the sort above keeps the titled one.
    deduped = [boundaries[0]]
    for start, title in boundaries[1:]:
        if start > deduped[-1][0]:
            deduped.append((start, title))

    spans: List[tuple[str, str]] = []
    if deduped[0][0] > 0:
        spans.append(("", md_content[: deduped[0][0]]))
    for i, (start, title) in enumerate(deduped):
        end = deduped[i + 1][0] if i + 1 < len(deduped) else len(md_content)
        spans.append((title, md_content[start:end]))

    # A revision block runs until the next titled section, so the marker's kind
    # carries forward across the untitled page-break blocks that follow it.
    sections: List[Dict[str, Any]] = []
    kind = "teaching"
    for title, text in spans:
        own = _section_kind(text)
        if own == "revision":
            kind = "revision"
        elif title:
            kind = "teaching"
        sections.append({"title": title, "kind": kind, "text": text})
    return sections


def anchors(md_content: str) -> List[Dict[str, Any]]:
    """Every structural landmark in the chapter, in document order.

    Both markdown headings and inline numbered section titles, because MinerU
    promotes one book's section titles to headings and swallows the other's into
    the body text. Used to locate where a named topic begins.
    """
    found: List[Dict[str, Any]] = []
    for match in _HEADING_RE.finditer(md_content or ""):
        title = match.group(2).strip()
        if _is_real_heading(title):
            found.append({"start": match.start(), "title": title})
    for section in numbered_sections(md_content):
        found.append({"start": section["start"], "title": section["title"]})
    found.sort(key=lambda a: a["start"])
    return found


# How much of a topic's name must appear in an anchor's title before that anchor
# is accepted as the topic's home. Below this the match is coincidence: half a
# chapter's headings share a word with any given topic.
_ANCHOR_MATCH_MIN = 0.5


def partition_by_topics(md_content: str, topic_names: List[str]) -> List[tuple[int, int]]:
    """Cut a chapter into exactly one contiguous span per topic, in order.

    Returns [(start, end), ...] aligned to topic_names. The spans tile the whole
    chapter: no gaps, no overlaps, nothing dropped.

    This is deliberately a pure function of (chapter text, ordered topic names).
    Both queues call it -- the Topic Queue to report what it produced, the
    Concept Queue to rebuild the same spans in a later request -- and because
    both inputs are persisted, the two always agree without anything extra being
    stored. That is the whole reason spans are derived rather than saved.

    Topics are anchored to the book's own headings where the wording matches;
    the rest are interpolated between the ones that did anchor, so a chapter with
    no headings at all still yields an even, ordered partition.
    """
    md = md_content or ""
    count = len(topic_names)
    if count == 0:
        return []
    if count == 1 or not md:
        return [(0, len(md))] + [(len(md), len(md))] * (count - 1)

    found = anchors(md)

    # Anchor each topic to the best-matching heading at or after the previous
    # topic's anchor, so the assignment can never run backwards through the book.
    resolved: Dict[int, int] = {}
    cursor = 0
    for index, name in enumerate(topic_names):
        want = set(tokens(name))
        if not want:
            continue
        best_offset = best_score = None
        best_at = cursor
        for position in range(cursor, len(found)):
            got = set(tokens(found[position]["title"]))
            if not got:
                continue
            score = len(want & got) / len(want)
            if best_score is None or score > best_score:
                best_offset, best_score, best_at = found[position]["start"], score, position
        if best_offset is not None and best_score >= _ANCHOR_MATCH_MIN:
            resolved[index] = best_offset
            cursor = best_at + 1

    # Interpolate everything that did not anchor, between the ones that did.
    # The sentinels make the first and last stretch fall out of the same loop.
    # Pinning index 0 to the start of the chapter keeps an unanchored chapter --
    # prose, where nothing matches -- splitting into even shares rather than
    # handing the first topic a double one.
    points: Dict[int, int] = {-1: 0, 0: 0, count: len(md), **resolved}
    for low, high in zip(sorted(points)[:-1], sorted(points)[1:]):
        if high - low <= 1:
            continue
        step = (points[high] - points[low]) / (high - low)
        for missing in range(low + 1, high):
            points[missing] = int(points[low] + step * (missing - low))

    # The first topic owns everything before it, so an introduction that precedes
    # the first heading is taught by someone rather than silently dropped.
    starts = [0]
    for index in range(1, count):
        starts.append(max(starts[-1], min(points[index], len(md))))

    return [(starts[i], starts[i + 1] if i + 1 < count else len(md)) for i in range(count)]


# Two names describe the same unit when the shorter one's content words are
# almost entirely contained in the longer one. Exact-string matching is far too
# weak here: "Lowest Common Multiple Definition" and "Lowest common multiple
# (LCM)" normalise to different keys and both survive, and so do "Multiples of a
# number" and "Listing Multiples of a Number".
_DUPLICATE_CONTAINMENT = 0.8

# Scaffolding the model wraps around a subject rather than part of the subject.
# "Lowest Common Multiple Definition" and "Lowest common multiple (LCM)" are one
# concept; "Multiplying ... integers" and "Dividing ... integers" are two. Both
# pairs share three of four words, so no threshold separates them -- only
# ignoring the scaffolding does, because what is left then differs by a word
# that actually names the subject.
_SCAFFOLD_WORDS = {
    "definition", "definitions", "defining", "meaning", "concept", "concepts",
    "introduction", "intro", "overview", "basics", "understanding", "understand",
    "identifying", "identify", "listing", "list", "finding", "find", "using",
    "use", "applying", "apply", "means", "method", "methods", "approach",
    "example", "examples", "general", "basic", "simple", "learner", "learners",
}


def singular(word: str) -> str:
    """Enough stemming to stop "Square number" and "Square numbers" counting as
    different subjects. English plurals only -- Devanagari and other scripts in
    this corpus do not inflect with a trailing ASCII s, so they pass through."""
    if len(word) > 3 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _subject_tokens(value: str) -> set[str]:
    picked = {singular(t) for t in tokens(value) if t not in _SCAFFOLD_WORDS}
    # A name made entirely of scaffolding still has to compare as something.
    return picked or {singular(t) for t in tokens(value)}


# Words that narrow a subject to a specific case, or name the operation being
# performed on it, rather than restating it. When one name carries one and the
# other does not, they are two units however much else they share:
#
#   "Common multiples"          vs "Lowest common multiple"
#   "Integers and number line"  vs "Adding integers using a number line"
#
# Both pairs differ by a single word, and in both that word is the whole point
# of the second name. Without this the shorter, more general name swallows the
# longer one -- which is how "Adding integers" disappeared from chapter 147.
#
# Note the deliberate split from _SCAFFOLD_WORDS: "listing", "finding" and
# "identifying" are generic and get ignored, while "adding", "dividing" and
# "rounding" name the mathematics and get respected.
_DISCRIMINATOR_WORDS = {
    # qualifiers
    "lowest", "highest", "greatest", "least", "smallest", "largest", "minimum",
    "maximum", "prime", "composite", "positive", "negative", "odd", "even",
    "proper", "improper", "ascending", "descending", "consecutive", "inverse",
    # operations
    "adding", "addition", "add", "subtracting", "subtraction", "subtract",
    "multiplying", "multiplication", "multiply", "dividing", "division",
    "divide", "estimating", "estimation", "estimate", "evaluating", "evaluate",
    "calculating", "calculate", "rounding", "round",
    "comparing", "ordering", "simplifying", "converting", "solving",
    "factorising", "factorizing", "squaring", "cubing",
}


def is_duplicate_name(candidate: str, existing: str) -> bool:
    a, b = _subject_tokens(candidate), _subject_tokens(existing)
    if not a or not b:
        return False
    if (a ^ b) & _DISCRIMINATOR_WORDS:
        return False
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    # A single shared word is a topic area, not a duplicate ("Square numbers"
    # vs "Square roots"), so one-token names must match outright.
    if len(short) < 2:
        return short == long_
    return len(short & long_) / len(short) >= _DUPLICATE_CONTAINMENT


def dedupe_by_name(
    groups: List[Dict[str, Any]],
    items_key: str,
    name_key: str,
    keep_at_least_one: bool = False,
) -> int:
    """Drop later repeats of a name across ordered groups; return how many went.

    Groups must already be in chapter order, so the earliest occurrence -- the
    place the book introduces the idea -- is the one that survives.

    With keep_at_least_one, a group never ends up empty. A group stripped bare
    is worse than a near-duplicate: in the topic -> concept hierarchy it leaves
    a topic with no concepts under it, which is what happened to "Missing number
    multiplication and division" on chapter 147.
    """
    seen: List[str] = []
    dropped = 0
    for group in groups:
        kept: List[Dict[str, Any]] = []
        for item in group[items_key]:
            name = item.get(name_key) or ""
            key = normalise_name(name)
            if not key:
                dropped += 1
                continue
            if any(is_duplicate_name(name, other) for other in seen):
                dropped += 1
                continue
            seen.append(name)
            kept.append(item)
        if not kept and keep_at_least_one and group[items_key]:
            # Give the group back its best candidate rather than orphaning it.
            kept = [group[items_key][0]]
            dropped -= 1
        group[items_key] = kept
    return dropped


def score_section(section: Dict[str, Any], target_tokens: set[str]) -> float:
    """Overlap between a target name and a section. The heading counts for more
    than the body: a section whose title names the target is almost always its
    home, while body overlap alone is common across a chapter."""
    if not target_tokens:
        return 0.0
    # Truncated for the same reason the outline filters: a paragraph-length
    # "heading" would otherwise out-score every genuine section title.
    title_tokens = set(tokens(section["title"][:MAX_HEADING_CHARS]))
    body_tokens = set(tokens(section["text"][:4000]))
    title_hit = len(target_tokens & title_tokens) / len(target_tokens)
    body_hit = len(target_tokens & body_tokens) / len(target_tokens)
    return (title_hit * 3.0) + body_hit


def safe_int(value: Any, default: int | None = None) -> int | None:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if value is None:
        return default
    match = re.search(r"-?\d+", str(value))
    return int(match.group()) if match else default


def normalise_minutes(items: List[Dict[str, Any]], key: str, budget: int | None) -> None:
    """Scale a list's minutes so they sum to the parent's budget.

    The prompts ask for this, but models are unreliable at making a list of
    integers add up, so the arithmetic is enforced here rather than trusted.
    """
    if not items or not budget or budget <= 0:
        return

    raw = [item[key] for item in items]
    total = sum(raw)
    if total <= 0:
        return

    scaled = [max(1, round(value * budget / total)) for value in raw]
    drift = budget - sum(scaled)
    if drift:
        # Absorb the rounding remainder into the longest item.
        largest = scaled.index(max(scaled))
        scaled[largest] = max(1, scaled[largest] + drift)

    for item, minutes in zip(items, scaled):
        item[key] = minutes


def verify_grounding(items: List[Dict[str, Any]], source_text: str) -> None:
    """Flag whether each item's source_evidence quote really is in the source."""
    haystack = " ".join((source_text or "").split()).lower()
    for item in items:
        quote = " ".join(item.get("source_evidence", "").split()).lower()
        item["evidence_verified"] = bool(quote) and quote in haystack
