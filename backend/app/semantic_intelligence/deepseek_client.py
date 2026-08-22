"""LLM client for semantic intelligence generation.

The module name is historical: it now speaks to whichever provider
LLM_PROVIDER selects. DeepSeek and Gemini both expose an OpenAI-compatible
chat-completions API, so a single code path drives both and the eight modules
importing call_deepseek / async_call_deepseek need no change.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import threading
import time
from typing import Any

try:
    from openai import OpenAI, AsyncOpenAI
except ImportError:
    OpenAI = None
    AsyncOpenAI = None

from app.utils.config import settings


class DeepSeekUnavailableError(RuntimeError):
    """The configured LLM cannot serve any request with the current credentials.

    Billing, authentication and unknown-model failures resolve identically for
    every call in a run, so they must never be retried and must never be
    swallowed by a caller's fallback: an extraction of empty arrays is
    indistinguishable from a chapter that genuinely contained nothing.
    """


# Provider-neutral alias for new code; the old name stays for existing imports.
LLMUnavailableError = DeepSeekUnavailableError


_PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "key_env": "DEEPSEEK_API_KEY",
        "help_url": "https://platform.deepseek.com/top_up",
    },
    # Gemini's OpenAI-compatibility layer, chosen over google-generativeai so
    # the retry, JSON-parsing and error-classification logic below stays shared.
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_env": "GEMINI_API_KEY",
        "help_url": "https://aistudio.google.com/apikey",
    },
}


def _provider() -> str:
    name = (settings.llm_provider or "deepseek").strip().lower()
    if name not in _PROVIDERS:
        raise DeepSeekUnavailableError(
            f"LLM_PROVIDER={name!r} is not supported. Use one of: {', '.join(sorted(_PROVIDERS))}."
        )
    return name


def _model(provider: str) -> str:
    return settings.gemini_model if provider == "gemini" else settings.deepseek_model


def _configured_keys(provider: str) -> list[str]:
    """Every credential configured for this provider, in preference order.

    Gemini's free tier allows only a few requests per minute while the swarm
    fires up to 15 concepts x 4 agents, so a pool of GEMINI_API_KEY2..N lets a
    run rotate past a rate-limited key instead of stalling on it.
    """
    primary = (settings.gemini_api_key if provider == "gemini" else settings.deepseek_api_key) or ""
    keys = [primary.strip()] if primary.strip() else []
    if provider == "gemini":
        for i in range(2, 33):
            extra = (os.getenv(f"GEMINI_API_KEY{i}") or "").strip()
            if extra and extra not in keys:
                keys.append(extra)
    return keys


# Credentials proven permanently dead, remembered for the life of the process.
# Without this every call would re-try each revoked key before reaching a good
# one, which matters when stale keys are left sitting in .env.
_dead_keys: dict[str, str] = {}


def _retire(key: str, reason: str) -> None:
    with _lock:
        _dead_keys[key] = reason


def _provider_keys(provider: str) -> list[str]:
    """The credentials still worth trying."""
    cfg = _PROVIDERS[provider]
    configured = _configured_keys(provider)
    if not configured:
        raise DeepSeekUnavailableError(
            f"LLM_PROVIDER={provider!r} but no {cfg['key_env']} is set. "
            f"Add it to backend/.env - get one at {cfg['help_url']}."
        )

    live = [k for k in configured if k not in _dead_keys]
    if not live:
        reasons = "; ".join(sorted({_dead_keys[k] for k in configured}))
        raise DeepSeekUnavailableError(
            f"All {len(configured)} configured {cfg['key_env']} credential(s) have "
            f"failed permanently: {reasons}"
        )
    return live


_clients: dict[tuple[str, str, bool], Any] = {}
_lock = threading.Lock()


def _client(provider: str, key: str, is_async: bool):
    cache_key = (provider, key, is_async)
    with _lock:
        cached = _clients.get(cache_key)
        if cached is None:
            ctor = AsyncOpenAI if is_async else OpenAI
            if ctor is None:
                raise RuntimeError("openai is not installed. Install backend requirements first.")
            cached = ctor(api_key=key, base_url=_PROVIDERS[provider]["base_url"])
            _clients[cache_key] = cached
        return cached


# Permanent failures. 429 and 5xx are transient and stay on the retry path.
_UNAVAILABLE_HINTS = {
    401: "the API key is missing, invalid or revoked",
    402: "the account has no credit left (HTTP 402 Insufficient Balance)",
    403: "the API key is not permitted to use this model, or has been blocked",
    404: "the configured model does not exist",
}


def _status_of(exc: Exception) -> int | None:
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return status


def _unavailable_reason(exc: Exception, provider: str) -> str | None:
    """Return a readable reason if exc means no call will ever succeed."""
    status = _status_of(exc)
    hint = _UNAVAILABLE_HINTS.get(status)
    # Gemini reports an invalid key as 400, not 401, so without this it would be
    # retried three times as a transient fault. The wording differs between the
    # native endpoint and the OpenAI-compatible one, hence several markers.
    if hint is None and status == 400 and any(
        marker in str(exc).lower()
        for marker in ("api key not valid", "pass a valid api key", "api_key_invalid",
                       "invalid api key", "api key expired")
    ):
        hint = _UNAVAILABLE_HINTS[401]
    if hint is None:
        return None
    cfg = _PROVIDERS[provider]
    return (
        f"{provider} is unavailable: {hint} "
        f"(model={_model(provider)!r}, key={cfg['key_env']}, HTTP {status}). See {cfg['help_url']}."
    )


def _rate_limited(exc: Exception) -> bool:
    return _status_of(exc) == 429


# What to do about a failed call.
_RETRY = "retry"          # transient fault: back off and try again
_NEXT_KEY = "next_key"    # this credential is throttled or dead: rotate
_FATAL = "fatal"          # nothing can succeed, whatever the key: stop now
_EXHAUSTED = "exhausted"  # this was the last usable key: stop and say so


def _classify(exc: Exception, provider: str, live_after: int) -> tuple[str, str | None]:
    """Decide how to handle exc.

    live_after is how many usable keys would remain if this one were retired.
    A dead key is only terminal once it is the last one standing, so a pool
    keeps working when a single key is revoked or out of quota.
    """
    if isinstance(exc, json.JSONDecodeError):
        return _RETRY, None

    reason = _unavailable_reason(exc, provider)
    if reason:
        # A wrong model name resolves identically on every key, so there is
        # nothing to rotate to and no point blaming the pool.
        if _status_of(exc) == 404:
            return _FATAL, reason
        return (_EXHAUSTED if live_after <= 0 else _NEXT_KEY), reason

    if _rate_limited(exc) and live_after > 0:
        return _NEXT_KEY, None
    return _RETRY, None


def _request(provider: str, messages: list, response_format: dict | None) -> dict:
    kwargs = {"model": _model(provider), "messages": messages, "temperature": 0.2}
    if response_format:
        kwargs["response_format"] = response_format
    return kwargs


def _messages(prompt: str, system_prompt: str) -> list:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    return messages


def _parse(response, response_format: dict | None) -> dict[str, Any]:
    content = response.choices[0].message.content
    if content is None:
        # Gemini returns a null message when a safety filter trips. Treated as
        # transient so the retry loop gets another go.
        raise ValueError("the model returned an empty message (possibly a safety block)")

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


# Round-robin start point, so concurrent swarm calls spread across the pool
# instead of all hammering the first key.
_rotation = itertools.count()


def _raise_last(provider: str, last_exc: Exception | None):
    if isinstance(last_exc, json.JSONDecodeError):
        raise last_exc
    raise RuntimeError(f"{provider} API call failed: {last_exc}") from last_exc


def _exhausted(reason: str, keys: list[str], exc: Exception):
    """Raise with the whole picture when the last usable key gives out."""
    if len(keys) > 1:
        reason = f"{reason} All {len(keys)} usable keys failed."
    raise DeepSeekUnavailableError(reason) from exc


def call_deepseek(prompt: str, system_prompt: str = "", response_format: dict | None = None, max_retries: int = 3) -> dict[str, Any]:
    """
    Calls the configured LLM synchronously.
    If response_format={"type": "json_object"} is passed, ensures JSON output.
    """
    provider = _provider()
    keys = _provider_keys(provider)
    messages = _messages(prompt, system_prompt)
    start = next(_rotation)
    dead: dict[str, str] = {}
    last_exc: Exception | None = None

    for attempt in range(max_retries):
        for offset in range(len(keys)):
            key = keys[(start + offset) % len(keys)]
            if key in dead:
                continue
            try:
                client = _client(provider, key, is_async=False)
                response = client.chat.completions.create(**_request(provider, messages, response_format))
                return _parse(response, response_format)
            except Exception as exc:
                last_exc = exc
                action, reason = _classify(exc, provider, len(keys) - len(dead) - 1)
                if action == _FATAL:
                    raise DeepSeekUnavailableError(reason) from exc
                if action == _EXHAUSTED:
                    _retire(key, reason)
                    _exhausted(reason, keys, exc)
                if action == _NEXT_KEY:
                    # A revoked key is retired for good; a merely throttled one
                    # is left in the pool and retried on the next pass.
                    if reason:
                        dead[key] = reason
                        _retire(key, reason)
                    continue
                break
        if attempt < max_retries - 1:
            time.sleep(1)

    _raise_last(provider, last_exc)


async def async_call_deepseek(prompt: str, system_prompt: str = "", response_format: dict | None = None, max_retries: int = 3) -> dict[str, Any]:
    """
    Calls the configured LLM asynchronously.
    If response_format={"type": "json_object"} is passed, ensures JSON output.
    """
    provider = _provider()
    keys = _provider_keys(provider)
    messages = _messages(prompt, system_prompt)
    start = next(_rotation)
    dead: dict[str, str] = {}
    last_exc: Exception | None = None

    for attempt in range(max_retries):
        for offset in range(len(keys)):
            key = keys[(start + offset) % len(keys)]
            if key in dead:
                continue
            try:
                client = _client(provider, key, is_async=True)
                response = await client.chat.completions.create(**_request(provider, messages, response_format))
                return _parse(response, response_format)
            except Exception as exc:
                last_exc = exc
                action, reason = _classify(exc, provider, len(keys) - len(dead) - 1)
                if action == _FATAL:
                    raise DeepSeekUnavailableError(reason) from exc
                if action == _EXHAUSTED:
                    _retire(key, reason)
                    _exhausted(reason, keys, exc)
                if action == _NEXT_KEY:
                    if reason:
                        dead[key] = reason
                        _retire(key, reason)
                    continue
                break
        if attempt < max_retries - 1:
            await asyncio.sleep(1)

    _raise_last(provider, last_exc)


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
        result = await asyncio.to_thread(call_deepseek, prompt, system_prompt, {"type": "json_object"})
        return result["data"]
    except Exception as e:
        logger.warning("Failed to extract metadata via LLM: %s", e)
        return {
            "standard_id": "-",
            "subject_id": "-",
            "chapter_id": "-",
            "subject_name": "-",
            "class_level": "-"
        }
