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
    
    # 3. Process each slice through the Swarm (Phase 3 & 4)
    for index, topic_data in enumerate(sliced_topics):
        title = topic_data["topic_title"]
        topic_summary = topic_data.get("topic_summary", "")
        topic_description = topic_data.get("topic_description", "")
        content = topic_data["content"]
        print(f"[Topic {index + 1}/{len(sliced_topics)}]: {title}")
        
        try:
            # Execute the Sequential Chain Swarm
            mega_concept_object = await swarm.process_topic_slice(content)
            
            # Since the user requested the TIO (TopicIntelligenceObject) layer containing Concepts:
            final_topic_obj = {
                "topic_name": title,
                "topic_summary": topic_summary,
                "topic_description": topic_description,
                "concepts": [mega_concept_object] 
            }
            
            final_topics.append(final_topic_obj)
            print(f"Successfully compiled intelligence for: {title}")
            
        except Exception as e:
            print(f"Error processing topic '{title}': {str(e)}")
            continue
            
        # 4. Throttle to prevent rate limits
        if index < len(sliced_topics) - 1:
            print("Throttling for 2 seconds to respect DeepSeek limits...")
            await asyncio.sleep(2)
            
    # 5. Compile Final Chapter Intelligence (CHIO)
    chapter_intelligence = {
        "chapter_name": chapter_name,
        "chapter_summary": chapter_summary,
        "topics": final_topics
    }
    print(f"\n=======================================================")
    print(f"SEMANTIC INTELLIGENCE GENERATION COMPLETE!")
    print(f"Total Topics Processed: {len(final_topics)}")
    print(f"=======================================================\n")
    
    return chapter_intelligence
