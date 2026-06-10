import os
import google.generativeai as genai
from typing import List, Dict
from dotenv import load_dotenv

# Import the Pydantic schema we built in Phase 1
from .schemas import ChapterSlices, TopicSlice

# Load env variables to ensure we have our Multi-Agent keys
load_dotenv()

# ==========================================
# PHASE 2: THE SLICER ENGINE
# ==========================================
class SemanticSlicer:
    def __init__(self):
        # Explicitly bind this engine to the SLICER API Key to bypass rate limits
        slicer_key = os.getenv("GEMINI_API_KEY_SLICER")
        if not slicer_key:
            # Fallback to default key if slicer key is not yet set by user
            slicer_key = os.getenv("GEMINI_API_KEY")
            
        genai.configure(api_key=slicer_key)
        
        # We use flash for slicing as it is extremely fast and handles large context windows easily
        self.model = genai.GenerativeModel("gemini-1.5-flash")

    def analyze_and_slice(self, raw_chapter_markdown: str) -> Dict:
        """
        Takes raw chapter markdown, uses the LLM to find logical topics, 
        and then physically cuts the text using Python string matching.
        Returns a dict with 'chapter_summary' and 'topics'.
        """
        
        prompt = """
        You are an expert curriculum parser. Read the following textbook chapter.
        Divide the chapter into logical, cohesive educational 'Topics'.
        
        1. Write a brief chapter_summary.
        2. For each topic, provide:
           - topic_title: The name of the topic.
           - topic_summary: A 1-2 sentence overview of the topic.
           - topic_description: A detailed description of the topic's core concept.
           - start_quote: The exact first 5 to 7 words of the topic as they appear in the text.
           - end_quote: The exact last 5 to 7 words of the topic as they appear in the text.
        
        Do not modify the quotes. They must perfectly match the source text so a Python script can find them.
        """

        # We enforce Structured Outputs using response_schema to guarantee formatting
        response = self.model.generate_content(
            contents=[prompt, raw_chapter_markdown],
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                response_schema=ChapterSlices,
                temperature=0.1 # Very low temperature for highly deterministic quote extraction
            )
        )

        # Gemini returns strict JSON mapping to our Pydantic model
        import json
        llm_output = json.loads(response.text)
        
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
                print(f"Warning: Could not perfectly match quotes for topic '{title}'. Fallback needed.")
                
        return {
            "chapter_summary": llm_output.get("chapter_summary", ""),
            "topics": sliced_topics
        }
