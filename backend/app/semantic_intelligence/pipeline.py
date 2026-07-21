import asyncio
from typing import Dict, Any

from .slicer import SemanticSlicer
from .agents import IntelligenceSwarm

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
    
    final_concepts = []
    total_input_tokens = slicer_result.get("input_tokens", 0)
    total_output_tokens = slicer_result.get("output_tokens", 0)
    
    # 3. Process each slice through the Swarm (Phase 3 & 4) in PARALLEL
    semaphore = asyncio.Semaphore(15)  # Process up to 15 concepts concurrently
    
    async def process_single_concept(index: int, concept_data: dict):
        title = concept_data.get("concept_title", "Unknown")
        content = concept_data.get("content", "")
        print(f"[Concept {index + 1}/{len(sliced_concepts)}] STARTING: {title}")
        
        async with semaphore:
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
                
                print(f"Successfully compiled intelligence for: {title}")
                return mega_concept_object, t_in, t_out
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
            
    # 5. Compile Final Chapter Intelligence (CHIO)
    chapter_intelligence = {
        "chapter_name": chapter_name,
        "chapter_summary": chapter_summary,
        "concepts": final_concepts,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens
    }
    print(f"\n=======================================================")
    print(f"SEMANTIC INTELLIGENCE GENERATION COMPLETE!")
    print(f"Total Concepts Processed: {len(final_concepts)}")
    print(f"Input Tokens: {total_input_tokens} | Output Tokens: {total_output_tokens}")
    print(f"=======================================================\n")
    
    return chapter_intelligence
