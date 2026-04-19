from __future__ import annotations

import asyncio
import logging
import os
import re

logger = logging.getLogger(__name__)

_GEMINI_MODEL = "gemini-2.5-flash"
_TIMEOUT = 12.0

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai
        _client = genai.Client(api_key=api_key)
        logger.info("Gemini client initialized (%s)", _GEMINI_MODEL)
    except Exception as exc:
        logger.warning("Could not initialize Gemini client: %s", exc)
    return _client


def is_llm_available() -> bool:
    return _get_client() is not None


async def call_llm(system_prompt: str, user_prompt: str) -> str | None:
    client = _get_client()
    if client is None:
        return None
    from google.genai import types
    full_prompt = f"{system_prompt}\n\n{user_prompt}"
    config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
    try:
        loop = asyncio.get_event_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: client.models.generate_content(
                    model=_GEMINI_MODEL,
                    contents=full_prompt,
                    config=config,
                ),
            ),
            timeout=_TIMEOUT,
        )
        return response.text
    except asyncio.TimeoutError:
        logger.warning("Gemini call timed out after %ss", _TIMEOUT)
        return None
    except Exception as exc:
        logger.warning("Gemini call failed: %s", exc)
        return None


def extract_xml_tag(text: str, tag: str) -> str | None:
    pattern = rf"<{tag}>(.*?)</{tag}>"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else None
