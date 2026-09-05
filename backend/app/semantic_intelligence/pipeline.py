import asyncio
from typing import Any, Dict, List

from .slicer import SemanticSlicer
from .agents import IntelligenceSwarm
from .deepseek_client import DeepSeekUnavailableError
from app.services import chapter_text as ct
from app.utils.config import settings


def _summary_from_topics(chapter_name: str, topic_plan: List[dict]) -> str:
    """Build the chapter summary the four agents need, without an LLM call.

    The Topic Queue already wrote a one-to-two sentence description of every
    topic, so the chapter's own outline is sitting in topic_master. Asking the
    model to write the summary again meant sending the whole chapter a fifth
    time purely to get one paragraph back.
    """
    lines = []
    for order, topic in enumerate(topic_plan, start=1):
        description = str(topic.get("description") or "").strip()
        lines.append(f"{order}. {topic['topic_name']}" + (f" - {description}" if description else ""))
    body = "\n".join(lines)
    return f"'{chapter_name}' teaches the following topics in order:\n{body}" if body else ""


def _slices_from_topics(raw_markdown: str, topic_plan: List[dict]) -> List[dict]:
    """Cut the chapter into one span per topic, carrying that topic's concepts.

    partition_by_topics is a pure function of (chapter text, ordered topic
    names): it anchors each topic to the book's own headings and interpolates
    the rest, and the spans tile the chapter with no gaps and no overlaps. Both
    extraction queues already derive their spans from it, so Semantic
    Intelligence now analyses the identical partition.

    This replaces the Slicer's whole-chapter LLM call. It also removes the
    Slicer's worst failure mode: a quote it could not locate handed that concept
    the ENTIRE chapter as its slice, which was then sent to all four agents.
    A pure function cannot miss a quote.
    """
    names = [t["topic_name"] for t in topic_plan]
    spans = ct.partition_by_topics(raw_markdown, names)
    batch_size = max(1, settings.semantic_max_concepts_per_call)

    slices = []
    for topic, (start, end) in zip(topic_plan, spans):
        concepts = [
            {"name": c["name"], "description": c.get("description", "")}
            for c in topic.get("concepts", [])
            if str(c.get("name") or "").strip()
        ]
        # A topic whose concepts were never generated has nothing to extract
        # into, and the four agents have no list to key their answers to.
        if not concepts:
            print(f"  [SKIP] Topic '{topic['topic_name']}' has no concepts; nothing to extract.")
            continue

        content = raw_markdown[start:end].strip()
        # A very wide topic is split into consecutive batches over the SAME
        # slice. Agent 4 owes 4-6 mark schemes per concept, so an 11-concept
        # topic would ask for around fifty in one reply; a reply that overruns
        # comes back unparseable, is retried three times, is billed all three
        # times and returns nothing. Splitting costs one extra set of prompts
        # and is still far short of one call per concept.
        batches = [concepts[i:i + batch_size] for i in range(0, len(concepts), batch_size)]
        if len(batches) > 1:
            print(f"  [SPLIT] Topic '{topic['topic_name']}' has {len(concepts)} concepts; "
                  f"processing in {len(batches)} batches of at most {batch_size} so the "
                  f"agents are not asked for more than one reply can hold.")
        for number, batch in enumerate(batches, start=1):
            slices.append({
                "title": topic["topic_name"] + (f" (part {number}/{len(batches)})" if len(batches) > 1 else ""),
                "content": content,
                "concepts": batch,
                # Carried so each concept's intelligence can be stamped with the
                # topic it came from. Without it the Chapter -> Topic -> Concept
                # link survives only as concept-name string identity, which is
                # exactly what breaks the moment a name is reworded.
                "topic_id": topic.get("topic_id"),
                "topic_name": topic["topic_name"],
            })
    return slices


def _slices_from_slicer(raw_markdown: str, key_concepts: str) -> tuple[str, List[dict], int, int]:
    """The original path: ask the LLM where to cut, one slice per concept.

    Kept for chapters whose Topic Queue has not run yet, so those still work
    exactly as before.
    """
    slicer = SemanticSlicer()
    print("Phase 2: Slicing Chapter via LLM Quote-Matching...")
    slicer_result = slicer.analyze_and_slice(raw_markdown, key_concepts)
    sliced_concepts = slicer_result.get("concepts", [])

    # A concept whose quotes did not match carries the ENTIRE chapter as its
    # slice, so each one costs roughly a whole extra chapter of input tokens.
    # It is the difference between a cheap run and a very expensive one.
    unsliced = sum(1 for c in sliced_concepts if c.get("content") == raw_markdown.strip())
    if unsliced:
        print(f"  [COST WARNING] {unsliced}/{len(sliced_concepts)} concepts fell back to the "
              f"FULL chapter text ({len(raw_markdown)} chars each) because their quotes could "
              f"not be located. Each such concept sends the whole chapter to all 4 agents "
              f"instead of its own share, so its input cost is ~{len(sliced_concepts)}x what "
              f"a properly sliced concept would cost.")

    slices = [{
        "title": c.get("concept_title", "Unknown"),
        "content": c.get("content", ""),
        "concepts": [{
            "name": c.get("concept_title", "Unknown"),
            "description": c.get("concept_description", ""),
        }],
    } for c in sliced_concepts]

    return (
        slicer_result.get("chapter_summary", ""),
        slices,
        slicer_result.get("input_tokens", 0),
        slicer_result.get("output_tokens", 0),
    )


async def generate_chapter_intelligence(chapter_name: str, raw_markdown: str, key_concepts: str = "No predefined key concepts.", official_outcomes: str = "", subject_name: str = "", class_level: str = "", topic_plan: List[dict] | None = None) -> Dict[str, Any]:
    """
    Phase 4: The Core Orchestrator.

    Fans the agent swarm out over the chapter's TOPICS, each call returning
    intelligence for every concept that topic teaches. The swarm's cost is
    per CALL, not per word - ~9,000 tokens of role prompt and JSON schema ride
    on every one regardless of how little text is inside - so the number of
    slices, and nothing else, sets what a chapter costs.

    `topic_plan` is [{topic_name, description, concepts: [{name, description}]}].
    Without it the original per-concept slicer path runs unchanged.
    """
    print(f"\n=======================================================")
    print(f"STARTING SEMANTIC INTELLIGENCE PIPELINE")
    print(f"Chapter: {chapter_name}")
    print(f"=======================================================\n")

    swarm = IntelligenceSwarm()

    if topic_plan:
        print(f"Phase 2: Slicing chapter by its {len(topic_plan)} topics (no LLM call)...")
        chapter_summary = _summary_from_topics(chapter_name, topic_plan)
        slices = _slices_from_topics(raw_markdown, topic_plan)
        slicer_in = slicer_out = 0
        expected_concepts = sum(len(s["concepts"]) for s in slices)
        print(f"{len(topic_plan)} topics -> {len(slices)} slice(s) covering {expected_concepts} "
              f"concepts = {len(slices) * 4} agent calls "
              f"(one call per concept would have been {expected_concepts * 4}).\n")
    else:
        chapter_summary, slices, slicer_in, slicer_out = _slices_from_slicer(raw_markdown, key_concepts)
        expected_concepts = len(slices)
        print(f"Slicer identified {len(slices)} semantic concepts.\n")

    if not chapter_summary:
        chapter_summary = "Auto-generated educational intelligence graph."

    final_concepts: List[dict] = []
    total_input_tokens = slicer_in
    total_output_tokens = slicer_out

    # Each slice fires 4 agent calls, so requests in flight are ~4x this number.
    # Providers settle billing on completion, which is how a wide fan-out can
    # overshoot a balance into the negative.
    semaphore = asyncio.Semaphore(max(1, settings.semantic_max_concurrency))

    budget = settings.semantic_max_tokens_per_chapter
    spent = {"tokens": total_input_tokens + total_output_tokens}
    over_budget = asyncio.Event()
    # A provider fault (no balance, revoked key, unknown model) resolves the
    # same way for every remaining slice, so once one slice sees it, no slice
    # still waiting on the semaphore is allowed to start.
    #
    # Slices already IN FLIGHT are deliberately left alone. Their agent calls
    # are already paid for, and cancelling them would discard exactly the work
    # this is here to preserve; a fault that stops a run is classified terminal
    # in deepseek_client, so a doomed in-flight slice fails on its next call
    # without retrying rather than spending on. They cannot outlive the run
    # either - gather below awaits every task, which is what stops the orphaned,
    # still-billing tasks the bare gather used to leave behind.
    aborted = asyncio.Event()
    abort_reason: dict = {}

    async def process_single_slice(index: int, slice_data: dict):
        title = slice_data["title"]
        content = slice_data["content"]
        concepts = slice_data["concepts"]
        # Checked before queueing and again after acquiring the slot, so a run
        # that blows its ceiling stops launching work instead of spending on.
        if over_budget.is_set() or aborted.is_set():
            return [], 0, 0
        print(f"[Slice {index + 1}/{len(slices)}] STARTING: {title} ({len(concepts)} concept(s))")

        async with semaphore:
            if over_budget.is_set() or aborted.is_set():
                return [], 0, 0
            try:
                concept_objects, t_in, t_out = await swarm.process_topic_slice(
                    text_slice=content,
                    chapter_name=chapter_name,
                    chapter_summary=chapter_summary,
                    topic_name=title,
                    concepts=concepts,
                    official_outcomes=official_outcomes,
                    subject_name=subject_name,
                    class_level=class_level
                )

                # Stamp every concept with the topic that produced it, so the
                # hierarchy is recorded rather than re-derived by name matching
                # downstream. The slicer fallback has no topic, and leaves None.
                for concept_object in concept_objects:
                    concept_object["topic_id"] = slice_data.get("topic_id")
                    concept_object["topic_name"] = slice_data.get("topic_name") or title

                spent["tokens"] += t_in + t_out
                if budget and spent["tokens"] > budget:
                    over_budget.set()
                    print(f"  [BUDGET] {spent['tokens']} tokens spent on this chapter, past the "
                          f"{budget} ceiling. No further slices will be started; whatever has "
                          f"already been generated is kept and saved.")

                print(f"Successfully compiled intelligence for: {title} "
                      f"({len(concept_objects)} concept(s), {t_in + t_out} tokens; "
                      f"{spent['tokens']} so far)")
                return concept_objects, t_in, t_out
            except DeepSeekUnavailableError as exc:
                # Every remaining slice will fail identically, so stop any that
                # have not started. Whatever finished is still returned and
                # saved: binning it is what turned a mid-run "insufficient
                # balance" into a chapter that cost money and produced nothing.
                if not aborted.is_set():
                    abort_reason["error"] = exc
                    aborted.set()
                    print(f"  [ABORT] {exc}")
                    print(f"  [ABORT] No further slices will be started. Slices already running "
                          f"are left to finish - their calls are paid for - and everything "
                          f"compiled so far is kept and saved.")
                return [], 0, 0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                import traceback
                with open("error_log.txt", "a", encoding="utf-8") as f:
                    f.write(f"Error processing slice '{title}': {str(e)}\n{traceback.format_exc()}\n")
                print(f"Error processing slice '{title}': {str(e)}")
                return [], 0, 0

    # return_exceptions is what keeps one dead credential from discarding every
    # slice that already succeeded. It also makes gather await every task, so
    # nothing survives this call still running and still billing.
    results = await asyncio.gather(
        *[process_single_slice(i, s) for i, s in enumerate(slices)],
        return_exceptions=True,
    )

    for result in results:
        if isinstance(result, BaseException):
            continue
        concept_objects, t_in, t_out = result
        final_concepts.extend(concept_objects)
        total_input_tokens += t_in
        total_output_tokens += t_out

    # A run where the swarm produced nothing for any slice is a failure, not an
    # empty chapter. Returning it would persist a row of empty arrays that the
    # UI renders as all-null fields with no indication anything went wrong.
    if slices and not final_concepts:
        if abort_reason.get("error"):
            raise abort_reason["error"]
        raise RuntimeError(
            f"Semantic intelligence produced no concepts for '{chapter_name}': all "
            f"{len(slices)} slices failed in the agent swarm. See error_log.txt "
            f"for the per-slice tracebacks."
        )

    # 5. Compile Final Chapter Intelligence (CHIO)
    chapter_intelligence = {
        "chapter_name": chapter_name,
        "chapter_summary": chapter_summary,
        "concepts": final_concepts,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "budget_exceeded": over_budget.is_set(),
        "aborted": bool(abort_reason.get("error")),
        "abort_reason": str(abort_reason["error"]) if abort_reason.get("error") else None,
        "concepts_attempted": expected_concepts,
        "slices_attempted": len(slices),
    }
    billed = total_input_tokens + total_output_tokens
    print(f"\n=======================================================")
    print(f"SEMANTIC INTELLIGENCE GENERATION COMPLETE!")
    print(f"Total Concepts Processed: {len(final_concepts)}/{expected_concepts} "
          f"across {len(slices)} slice(s)")
    print(f"Input Tokens: {total_input_tokens} | Output Tokens: {total_output_tokens}")
    print(f"TOTAL BILLED TOKENS: {billed}")
    if final_concepts:
        print(f"  ~{billed // len(final_concepts)} tokens per concept "
              f"(note: on a reasoning model most output tokens are hidden chain-of-thought)")
    if over_budget.is_set():
        print(f"STOPPED EARLY: hit the {budget}-token ceiling "
              f"(SEMANTIC_MAX_TOKENS_PER_CHAPTER). Raise it to finish this chapter.")
    if abort_reason.get("error"):
        print(f"STOPPED EARLY: {abort_reason['error']}")
        print(f"  Partial intelligence IS being saved. Re-run with force=true once fixed.")
    print(f"=======================================================\n")

    return chapter_intelligence
