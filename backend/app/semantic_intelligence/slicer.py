import os
import time
import json
from typing import List, Dict

# Import the Pydantic schema we built in Phase 1
from .schemas import ChapterSlices, ConceptSlice

from .deepseek_client import call_deepseek

# ==========================================
# PHASE 2: THE SLICER ENGINE
# ==========================================
class SemanticSlicer:
    def __init__(self):
        pass

    def analyze_and_slice(self, raw_chapter_markdown: str, key_concepts: str = "No predefined key concepts.") -> Dict:
        """
        Takes raw chapter markdown, uses the LLM to find logical concepts, 
        and then physically cuts the text using Python string matching.
        Returns a dict with 'chapter_summary' and 'concepts'.
        """
        
        system_prompt = f"""You are an expert curriculum parser. Respond ONLY with valid JSON matching exactly this schema:
{ChapterSlices.model_json_schema()}"""

        prompt = f"""
        Read the following textbook chapter.
        
        We have already identified the primary 'Key Concepts' for this chapter:
        {key_concepts}
        
        Your objective is to divide the chapter into logical, cohesive educational 'Concepts' that perfectly align with and represent these Key Concepts.
        
        1. Write a brief chapter_summary.
        2. For each concept you extract, provide:
           - concept_title: The name of the concept.
           - concept_summary: A 1-2 sentence overview of the concept.
           - concept_description: A detailed description of the core concept.
           - start_quote: The exact first 5 to 7 words of the concept as they appear in the text.
           - end_quote: The exact last 5 to 7 words of the concept as they appear in the text.
        
        Do not modify the quotes. They must perfectly match the source text so a Python script can find them.
        
        Chapter Content:
        {raw_chapter_markdown}
        """
        
        try:
            result = call_deepseek(prompt, system_prompt=system_prompt, response_format={"type": "json_object"}, max_retries=3)
            llm_output = result["data"]
            input_tokens = result.get("input_tokens", 0)
            output_tokens = result.get("output_tokens", 0)
        except Exception as e:
            print(f"CRITICAL WARNING: Slicer failed. Last error: {e}")
            return {
                "chapter_summary": "Auto-generated intelligence.",
                "concepts": [{
                    "concept_title": "Core Concepts",
                    "concept_summary": "Main chapter concepts.",
                    "concept_description": "Comprehensive coverage.",
                    "content": raw_chapter_markdown.strip()
                }],
                "input_tokens": 0,
                "output_tokens": 0
            }

        # Now, Python physically slices the text based on the quotes
        sliced_concepts = []
        for concept in llm_output.get("concepts", []):
            start_quote = concept.get("start_quote", "")
            end_quote = concept.get("end_quote", "")
            title = concept.get("concept_title", "Unknown Concept")
            
            # Find exact character indices in the raw markdown
            start_idx = raw_chapter_markdown.find(start_quote)
            
            # Find where the end quote starts, then add its length to get the true end of the topic
            end_quote_start_idx = raw_chapter_markdown.find(end_quote, start_idx) 
            end_idx = end_quote_start_idx + len(end_quote) if end_quote_start_idx != -1 else -1
            
            if start_idx != -1 and end_idx != -1:
                # Perfect text cut! No markdown dependency.
                exact_text_slice = raw_chapter_markdown[start_idx:end_idx]
                sliced_concepts.append({
                    "concept_title": title,
                    "concept_summary": concept.get("concept_summary", ""),
                    "concept_description": concept.get("concept_description", ""),
                    "content": exact_text_slice.strip()
                })
            else:
                print(f"Warning: Could not perfectly match quotes for concept '{title}'. Falling back to full chapter text.")
                sliced_concepts.append({
                    "concept_title": title,
                    "concept_summary": concept.get("concept_summary", ""),
                    "concept_description": concept.get("concept_description", ""),
                    "content": raw_chapter_markdown.strip() # Fallback to full text so the swarm still runs
                })
                
        # CRITICAL FALLBACK: If the LLM completely failed to output ANY concepts,
        # we create a single "mega-concept" covering the entire chapter so the 
        # intelligence swarm can still process the text!
        if not sliced_concepts:
            print("Warning: LLM returned empty concepts array. Falling back to single mega-concept.")
            sliced_concepts.append({
                "concept_title": "Core Concepts",
                "concept_summary": llm_output.get("chapter_summary", "Main chapter concepts."),
                "concept_description": "Comprehensive coverage of the chapter.",
                "content": raw_chapter_markdown.strip()
            })
                
        return {
            "chapter_summary": llm_output.get("chapter_summary", ""),
            "concepts": sliced_concepts,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens
        }
