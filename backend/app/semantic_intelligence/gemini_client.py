"""Gemini client wrapper for semantic intelligence generation."""

from __future__ import annotations

import json
import time
from typing import Any

from app.utils.config import settings

try:
    import google.generativeai as genai
except ImportError:
    genai = None


import threading

_model = None
_current_key_index = 0
_lock = threading.Lock()

def _get_api_keys():
    keys = [
        settings.gemini_api_key,
        settings.gemini_api_key2,
        settings.gemini_api_key3,
        settings.gemini_api_key4,
        settings.gemini_api_key5,
        settings.gemini_api_key6,
        settings.gemini_api_key7,
        settings.gemini_api_key8,
    ]
    return [k for k in keys if k]

def _get_model():
    global _model, _current_key_index
    with _lock:
        if _model is None:
            keys = _get_api_keys()
            if not keys:
                raise ValueError("No GEMINI_API_KEY found in environment")
            api_key = keys[_current_key_index % len(keys)]
            genai.configure(api_key=api_key)
            _model = genai.GenerativeModel(settings.gemini_model)
        return _model

def _switch_api_key(failed_model):
    global _current_key_index, _model
    with _lock:
        # If another thread already switched the key, just return True
        if _model is not failed_model:
            return True
            
        keys = _get_api_keys()
        if len(keys) > 1:
            _current_key_index += 1
            print(f"Switched to Gemini API key #{( _current_key_index % len(keys) ) + 1}")
            api_key = keys[_current_key_index % len(keys)]
            genai.configure(api_key=api_key)
            _model = genai.GenerativeModel(settings.gemini_model)
            return True
        return False

def call_gemini(prompt: str, max_retries: int = 15) -> dict[str, Any]:
    if genai is None:
        raise RuntimeError(
            "google-generativeai is not installed. Install backend requirements first."
        )

    generation_config = genai.types.GenerationConfig(
        temperature=0.2,
        response_mime_type="application/json",
        frequency_penalty=0.0,
        presence_penalty=0.0
    )

    actual_max_retries = 2

    for attempt in range(actual_max_retries):
        current_model = _get_model()
        try:
            response = current_model.generate_content(
                prompt,
                generation_config=generation_config,
            )
            parsed_dict = json.loads(response.text)

            input_tokens = 0
            output_tokens = 0
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                input_tokens = response.usage_metadata.prompt_token_count
                output_tokens = response.usage_metadata.candidates_token_count

            return {
                "data": parsed_dict,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
        except json.JSONDecodeError:
            if attempt == actual_max_retries - 1:
                raise
            time.sleep(1)
        except Exception as exc:
            if attempt == actual_max_retries - 1:
                raise RuntimeError(f"Gemini API call failed: {exc}") from exc
            time.sleep(1)

    raise RuntimeError("Failed to call Gemini")

async def extract_pdf_metadata(markdown_content: str) -> dict[str, Any]:
    import asyncio
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        prompt = f"""
You are an expert at identifying educational metadata from a document. 
Given the following first 3000 characters of a chapter's markdown, extract the standard (class level as an integer), subject (as an integer ID, e.g. 1 for Math, 2 for Science, 3 for History/Social Science, 4 for English, 5 for Generic), and chapter number (as an integer).

Also extract subject_name (e.g. "Science") and class_level (e.g. "Class 10") as strings.

Markdown snippet:
{markdown_content[:3000]}

Return exactly a JSON object with these keys: 
"standard_id": int, "subject_id": int, "chapter_id": int, "subject_name": str, "class_level": str
"""
        result = await asyncio.to_thread(call_gemini, prompt)
        return result["data"]
    except Exception as e:
        logger.warning("Failed to extract metadata via Gemini: %s", e)
        return {
            "standard_id": "-",
            "subject_id": "-",
            "chapter_id": "-",
            "subject_name": "-",
            "class_level": "-"
        }
