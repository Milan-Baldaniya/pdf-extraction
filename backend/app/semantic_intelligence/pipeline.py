import asyncio
from typing import Dict, Any

from .slicer import SemanticSlicer
from .agents import IntelligenceSwarm
from .deepseek_client import DeepSeekUnavailableError
from app.utils.config import settings

async def generate_chapter_intelligence(chapter_name: str, raw_markdown: str, key_concepts: str = "No predefined key concepts.", official_outcomes: str = "", subject_name: str = "", class_level: str = "") -> Dict[str, Any]:
    """
    Phase 4: The Core Orchestrator
    This function brings together the Slicer and the Micro-Agent Swarm.
    It guarantees 0% laziness by managing memory chunks and rate limits perfectly.
    """
    print(f"\n=======================================================")
    print(f"STARTING SEMANTIC INTELLIGENCE PIPELINE")
    print(f"Chapter: {chapter_name}")
    print(f"=======================================================\n")
    
    # 1. Initialize Engines
    slicer = SemanticSlicer()
    swarm = IntelligenceSwarm()
    
    # 2. Slice the Chapter (Phase 2)
    print("Phase 2: Slicing Chapter via LLM Quote-Matching...")
    slicer_result = slicer.analyze_and_slice(raw_markdown, key_concepts)
    chapter_summary = slicer_result.get("chapter_summary", "Auto-generated educational intelligence graph.")
    sliced_concepts = slicer_result.get("concepts", [])
    
    print(f"Slicer identified {len(sliced_concepts)} semantic concepts.\n")
    
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

    final_concepts = []
    total_input_tokens = slicer_result.get("input_tokens", 0)
    total_output_tokens = slicer_result.get("output_tokens", 0)

    # 3. Process each slice through the Swarm (Phase 3 & 4) in PARALLEL.
    #    Each concept fires up to 4 agent calls, so requests in flight are ~4x
    #    this number. Providers settle billing on completion, which is how a
    #    wide fan-out can overshoot a balance into the negative.
    semaphore = asyncio.Semaphore(max(1, settings.semantic_max_concurrency))

    budget = settings.semantic_max_tokens_per_chapter
    spent = {"tokens": total_input_tokens + total_output_tokens}
    over_budget = asyncio.Event()

    async def process_single_concept(index: int, concept_data: dict):
        title = concept_data.get("concept_title", "Unknown")
        content = concept_data.get("content", "")
        # Checked before queueing and again after acquiring the slot, so a run
        # that blows its ceiling stops launching work instead of spending on.
        if over_budget.is_set():
            return None, 0, 0
        print(f"[Concept {index + 1}/{len(sliced_concepts)}] STARTING: {title}")

        async with semaphore:
            if over_budget.is_set():
                return None, 0, 0
            try:
                # Execute the Sequential Chain Swarm
                mega_concept_object, t_in, t_out = await swarm.process_topic_slice(
                    text_slice=content,
                    chapter_name=chapter_name,
                    chapter_summary=chapter_summary,
                    concept_name=title,
                    official_outcomes=official_outcomes,
                    subject_name=subject_name,
                    class_level=class_level
                )
                
                # Overwrite the generated concept meta with the Slicer's titles just to be consistent
                if "concept" not in mega_concept_object or not mega_concept_object["concept"]:
                    mega_concept_object["concept"] = {}
                mega_concept_object["concept"]["concept_name"] = title
                
                spent["tokens"] += t_in + t_out
                if budget and spent["tokens"] > budget:
                    over_budget.set()
                    print(f"  [BUDGET] {spent['tokens']} tokens spent on this chapter, past the "
                          f"{budget} ceiling. No further concepts will be started; whatever has "
                          f"already been generated is kept and saved.")

                print(f"Successfully compiled intelligence for: {title} "
                      f"({t_in + t_out} tokens; {spent['tokens']} so far)")
                return mega_concept_object, t_in, t_out
            except DeepSeekUnavailableError:
                # Not a per-concept problem; every remaining concept will fail
                # the same way. Abort so the caller reports the real cause.
                raise
            except Exception as e:
                import traceback
                with open("error_log.txt", "a", encoding="utf-8") as f:
                    f.write(f"Error processing concept '{title}': {str(e)}\n{traceback.format_exc()}\n")
                print(f"Error processing concept '{title}': {str(e)}")
                return None, 0, 0

    # Run all concepts through the swarm simultaneously
    results = await asyncio.gather(*[process_single_concept(i, c) for i, c in enumerate(sliced_concepts)])
    
    for concept_obj, t_in, t_out in results:
        if concept_obj:
            final_concepts.append(concept_obj)
            total_input_tokens += t_in
            total_output_tokens += t_out
            
    # A run where the swarm produced nothing for any slice is a failure, not an
    # empty chapter. Returning it would persist a row of empty arrays that the
    # UI renders as all-null fields with no indication anything went wrong.
    if sliced_concepts and not final_concepts:
        raise RuntimeError(
            f"Semantic intelligence produced no concepts for '{chapter_name}': all "
            f"{len(sliced_concepts)} slices failed in the agent swarm. See error_log.txt "
            f"for the per-concept tracebacks."
        )

    # 5. Compile Final Chapter Intelligence (CHIO)
    chapter_intelligence = {
        "chapter_name": chapter_name,
        "chapter_summary": chapter_summary,
        "concepts": final_concepts,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "budget_exceeded": over_budget.is_set(),
        "concepts_attempted": len(sliced_concepts)
    }
    billed = total_input_tokens + total_output_tokens
    print(f"\n=======================================================")
    print(f"SEMANTIC INTELLIGENCE GENERATION COMPLETE!")
    print(f"Total Concepts Processed: {len(final_concepts)}/{len(sliced_concepts)}")
    print(f"Input Tokens: {total_input_tokens} | Output Tokens: {total_output_tokens}")
    print(f"TOTAL BILLED TOKENS: {billed}")
    if final_concepts:
        print(f"  ~{billed // len(final_concepts)} tokens per concept "
              f"(note: on a reasoning model most output tokens are hidden chain-of-thought)")
    if over_budget.is_set():
        print(f"STOPPED EARLY: hit the {budget}-token ceiling "
              f"(SEMANTIC_MAX_TOKENS_PER_CHAPTER). Raise it to finish this chapter.")
    print(f"=======================================================\n")
    
    return chapter_intelligence
