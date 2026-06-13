"""DeepSeek client wrapper for semantic intelligence generation."""

from __future__ import annotations

import json
import time
from typing import Any
import threading

try:
    from openai import OpenAI, AsyncOpenAI
except ImportError:
    OpenAI = None
    AsyncOpenAI = None

from app.utils.config import settings

_sync_client = None
_async_client = None
_lock = threading.Lock()

def _get_api_key():
    key = settings.deepseek_api_key
    if not key:
        raise ValueError("No DEEPSEEK_API_KEY found in environment")
    return key

def _get_sync_client():
    global _sync_client
    with _lock:
        if _sync_client is None:
            if OpenAI is None:
                raise RuntimeError("openai is not installed. Install backend requirements first.")
            api_key = _get_api_key()
            _sync_client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")
        return _sync_client

def _get_async_client():
    global _async_client
    with _lock:
        if _async_client is None:
            if AsyncOpenAI is None:
                raise RuntimeError("openai is not installed. Install backend requirements first.")
            api_key = _get_api_key()
            _async_client = AsyncOpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")
        return _async_client

def call_deepseek(prompt: str, system_prompt: str = "", response_format: dict | None = None, max_retries: int = 3) -> dict[str, Any]:
    """
    Calls the DeepSeek API synchronously.
    If response_format={"type": "json_object"} is passed, ensures JSON output.
    """
    client = _get_sync_client()
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    for attempt in range(max_retries):
        try:
            kwargs = {
                "model": settings.deepseek_model,
                "messages": messages,
                "temperature": 0.2,
            }
            if response_format:
                kwargs["response_format"] = response_format
                
            response = client.chat.completions.create(**kwargs)
            
            content = response.choices[0].message.content
            
            # If we asked for JSON, parse it
            parsed_data = content
            if response_format and response_format.get("type") == "json_object":
                cleaned_content = content.strip()
                if cleaned_content.startswith("```json"):
                    cleaned_content = cleaned_content[7:]
                elif cleaned_content.startswith("```"):
                    cleaned_content = cleaned_content[3:]
                if cleaned_content.endswith("```"):
                    cleaned_content = cleaned_content[:-3]
                parsed_data = json.loads(cleaned_content.strip())
                
            return {
                "data": parsed_data,
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            }
            
        except json.JSONDecodeError:
            if attempt == max_retries - 1:
                raise
            time.sleep(1)
        except Exception as exc:
            if attempt == max_retries - 1:
                raise RuntimeError(f"DeepSeek API call failed: {exc}") from exc
            time.sleep(1)

    raise RuntimeError("Failed to call DeepSeek")

async def async_call_deepseek(prompt: str, system_prompt: str = "", response_format: dict | None = None, max_retries: int = 3) -> dict[str, Any]:
    """
    Calls the DeepSeek API asynchronously.
    If response_format={"type": "json_object"} is passed, ensures JSON output.
    """
    client = _get_async_client()
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    import asyncio
    for attempt in range(max_retries):
        try:
            kwargs = {
                "model": settings.deepseek_model,
                "messages": messages,
                "temperature": 0.2,
            }
            if response_format:
                kwargs["response_format"] = response_format
                
            response = await client.chat.completions.create(**kwargs)
            
            content = response.choices[0].message.content
            
            parsed_data = content
            if response_format and response_format.get("type") == "json_object":
                cleaned_content = content.strip()
                if cleaned_content.startswith("```json"):
                    cleaned_content = cleaned_content[7:]
                elif cleaned_content.startswith("```"):
                    cleaned_content = cleaned_content[3:]
                if cleaned_content.endswith("```"):
                    cleaned_content = cleaned_content[:-3]
                parsed_data = json.loads(cleaned_content.strip())
                
            return {
                "data": parsed_data,
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            }
            
        except json.JSONDecodeError:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(1)
        except Exception as exc:
            if attempt == max_retries - 1:
                raise RuntimeError(f"DeepSeek API call failed: {exc}") from exc
            await asyncio.sleep(1)

    raise RuntimeError("Failed to call DeepSeek")

async def extract_pdf_metadata(markdown_content: str) -> dict[str, Any]:
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        system_prompt = "You are an expert at identifying educational metadata from a document. Return exactly a JSON object."
        prompt = f"""
Given the following first 3000 characters of a chapter's markdown, extract the standard (class level as an integer), subject (as an integer ID, e.g. 1 for Math, 2 for Science, 3 for History/Social Science, 4 for English, 5 for Generic), and chapter number (as an integer).

Also extract subject_name (e.g. "Science") and class_level (e.g. "Class 10") as strings.

Markdown snippet:
{markdown_content[:3000]}

Return exactly a JSON object with these keys: 
"standard_id": int, "subject_id": int, "chapter_id": int, "subject_name": str, "class_level": str
"""
        import asyncio
        result = await asyncio.to_thread(call_deepseek, prompt, system_prompt, {"type": "json_object"})
        return result["data"]
    except Exception as e:
        logger.warning("Failed to extract metadata via DeepSeek: %s", e)
        return {
            "standard_id": "-",
            "subject_id": "-",
            "chapter_id": "-",
            "subject_name": "-",
            "class_level": "-"
        }
