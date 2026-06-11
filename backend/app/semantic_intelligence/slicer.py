import os
import google.generativeai as genai
from typing import List, Dict
import time
from google.api_core.exceptions import ResourceExhausted
from dotenv import load_dotenv

# Import the Pydantic schema we built in Phase 1
from .schemas import ChapterSlices, TopicSlice

# Load env variables to ensure we have our Multi-Agent keys (with override so live updates work)
load_dotenv(override=True)

# ==========================================
# PHASE 2: THE SLICER ENGINE
# ==========================================
class SemanticSlicer:
    def __init__(self):
        # Always reload the keys dynamically so if the user edits .env we catch it instantly!
        load_dotenv(override=True)
        k_main = os.getenv("GEMINI_API_KEY_SLICER")
        self.keys = [k_main] if k_main else []
        
        # We use flash for slicing as it follows strict JSON schemas much better
        self.model = genai.GenerativeModel("gemini-2.5-flash")

    def analyze_and_slice(self, raw_chapter_markdown: str, key_concepts: str = "No predefined key concepts.") -> Dict:
        """
        Takes raw chapter markdown, uses the LLM to find logical topics, 
        and then physically cuts the text using Python string matching.
        Returns a dict with 'chapter_summary' and 'topics'.
        """
        
        prompt = f"""
        You are an expert curriculum parser. Read the following textbook chapter.
        
        We have already identified the primary 'Key Concepts' for this chapter:
        {key_concepts}
        
        Your objective is to divide the chapter into logical, cohesive educational 'Topics' that perfectly align with and represent these Key Concepts.
        The hierarchy MUST be: Chapter -> Key Concept -> Topic of Concept.
        
        1. Write a brief chapter_summary.
        2. For each topic you extract, provide:
           - topic_title: The name of the topic. Ensure it maps logically to one of the provided Key Concepts.
           - topic_summary: A 1-2 sentence overview of the topic.
           - topic_description: A detailed description of the topic's core concept.
           - start_quote: The exact first 5 to 7 words of the topic as they appear in the text.
           - end_quote: The exact last 5 to 7 words of the topic as they appear in the text.
        
        Do not modify the quotes. They must perfectly match the source text so a Python script can find them.
        """
        
        last_error = None
        response_text = None
        max_retries = 3
        
        for key in self.keys:
            genai.configure(api_key=key)
            print(f"[SLICER] Trying API Key ending in ...{key[-4:]}")
            
            for attempt in range(max_retries):
                try:
                    # We enforce Structured Outputs using response_schema to guarantee formatting
                    response = self.model.generate_content(
                        contents=[prompt, raw_chapter_markdown],
                        generation_config=genai.GenerationConfig(
                            response_mime_type="application/json",
                            response_schema=ChapterSlices,
                            temperature=0.1 # Very low temperature for highly deterministic quote extraction
                        )
                    )
                    response_text = response.text
                    break
                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    print(f"[WARNING] [SLICER] API Error on key ...{key[-4:]} (Attempt {attempt+1}/{max_retries}): {err_str}")
                    
                    if "403" in err_str or "API key not valid" in err_str or "401" in err_str:
                        break # Skip to next key
                    elif "429" in err_str or "quota" in err_str.lower() or isinstance(e, ResourceExhausted):
                        if attempt < max_retries - 1:
                            print(f"[SLICER] Rate limit hit. Pausing 60 seconds to reset RPM limit...")
                            time.sleep(60)
                        else:
                            break # Exceeded max retries
                    else:
                        time.sleep(2) # Transient error, try same key again
                        
            if response_text:
                break # Successfully got response, stop trying keys
                
        if not response_text:
            print(f"CRITICAL WARNING: Slicer failed across all keys. Last error: {last_error}")
            return {
                "chapter_summary": "Auto-generated intelligence.",
                "topics": [{
                    "topic_title": "Core Concepts",
                    "topic_summary": "Main chapter concepts.",
                    "topic_description": "Comprehensive coverage.",
                    "content": raw_chapter_markdown.strip()
                }]
            }

        # Gemini returns strict JSON mapping to our Pydantic model
        import json
        try:
            llm_output = json.loads(response_text)
        except json.JSONDecodeError as e:
            print(f"CRITICAL WARNING: Slicer returned invalid/truncated JSON: {e}")
            return {
                "chapter_summary": "Auto-generated intelligence.",
                "topics": [{
                    "topic_title": "Core Concepts",
                    "topic_summary": "Main chapter concepts.",
                    "topic_description": "Comprehensive coverage.",
                    "content": raw_chapter_markdown.strip()
                }]
            }
        
        # Now, Python physically slices the text based on the quotes
        sliced_topics = []
        for topic in llm_output.get("topics", []):
            start_quote = topic.get("start_quote", "")
            end_quote = topic.get("end_quote", "")
            title = topic.get("topic_title", "Unknown Topic")
            
            # Find exact character indices in the raw markdown
            start_idx = raw_chapter_markdown.find(start_quote)
            
            # Find where the end quote starts, then add its length to get the true end of the topic
            end_quote_start_idx = raw_chapter_markdown.find(end_quote, start_idx) 
            end_idx = end_quote_start_idx + len(end_quote) if end_quote_start_idx != -1 else -1
            
            if start_idx != -1 and end_idx != -1:
                # Perfect text cut! No markdown dependency.
                exact_text_slice = raw_chapter_markdown[start_idx:end_idx]
                sliced_topics.append({
                    "topic_title": title,
                    "topic_summary": topic.get("topic_summary", ""),
                    "topic_description": topic.get("topic_description", ""),
                    "content": exact_text_slice.strip()
                })
            else:
                print(f"Warning: Could not perfectly match quotes for topic '{title}'. Falling back to full chapter text.")
                sliced_topics.append({
                    "topic_title": title,
                    "topic_summary": topic.get("topic_summary", ""),
                    "topic_description": topic.get("topic_description", ""),
                    "content": raw_chapter_markdown.strip() # Fallback to full text so the swarm still runs
                })
                
        # CRITICAL FALLBACK: If the LLM completely failed to output ANY topics,
        # we create a single "mega-topic" covering the entire chapter so the 
        # intelligence swarm can still process the text!
        if not sliced_topics:
            print("Warning: LLM returned empty topics array. Falling back to single mega-topic.")
            sliced_topics.append({
                "topic_title": "Core Concepts",
                "topic_summary": llm_output.get("chapter_summary", "Main chapter concepts."),
                "topic_description": "Comprehensive coverage of the chapter.",
                "content": raw_chapter_markdown.strip()
            })
                
        return {
            "chapter_summary": llm_output.get("chapter_summary", ""),
            "topics": sliced_topics
        }
