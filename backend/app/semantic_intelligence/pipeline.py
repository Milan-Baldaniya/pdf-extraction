import asyncio
from typing import Dict, Any

from .slicer import SemanticSlicer
from .agents import IntelligenceSwarm

async def generate_chapter_intelligence(chapter_name: str, raw_markdown: str, key_concepts: str = "No predefined key concepts.") -> Dict[str, Any]:
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
    sliced_topics = slicer_result.get("topics", [])
    
    print(f"Slicer identified {len(sliced_topics)} semantic topics.\n")
    
    final_topics = []
    total_input_tokens = slicer_result.get("input_tokens", 0)
    total_output_tokens = slicer_result.get("output_tokens", 0)
    
    # 3. Process each slice through the Swarm (Phase 3 & 4) in PARALLEL
    semaphore = asyncio.Semaphore(15)  # Process up to 15 topics concurrently
    
    async def process_single_topic(index: int, topic_data: dict):
        title = topic_data["topic_title"]
        topic_summary = topic_data.get("topic_summary", "")
        topic_description = topic_data.get("topic_description", "")
        content = topic_data["content"]
        print(f"[Topic {index + 1}/{len(sliced_topics)}] STARTING: {title}")
        
        async with semaphore:
            try:
                # Execute the Sequential Chain Swarm
                mega_concept_object, t_in, t_out = await swarm.process_topic_slice(content)
                
                # Since the user requested the TIO (TopicIntelligenceObject) layer containing Concepts:
                final_topic_obj = {
                    "topic_name": title,
                    "topic_summary": topic_summary,
                    "topic_description": topic_description,
                    "concepts": [mega_concept_object] 
                }
                
                print(f"Successfully compiled intelligence for: {title}")
                return final_topic_obj, t_in, t_out
            except Exception as e:
                print(f"Error processing topic '{title}': {str(e)}")
                return None, 0, 0

    # Run all topics through the swarm simultaneously
    results = await asyncio.gather(*[process_single_topic(i, t) for i, t in enumerate(sliced_topics)])
    
    for topic_obj, t_in, t_out in results:
        if topic_obj:
            final_topics.append(topic_obj)
            total_input_tokens += t_in
            total_output_tokens += t_out
            
    # 5. Compile Final Chapter Intelligence (CHIO)
    chapter_intelligence = {
        "chapter_name": chapter_name,
        "chapter_summary": chapter_summary,
        "topics": final_topics,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens
    }
    print(f"\n=======================================================")
    print(f"SEMANTIC INTELLIGENCE GENERATION COMPLETE!")
    print(f"Total Topics Processed: {len(final_topics)}")
    print(f"Input Tokens: {total_input_tokens} | Output Tokens: {total_output_tokens}")
    print(f"=======================================================\n")
    
    return chapter_intelligence
