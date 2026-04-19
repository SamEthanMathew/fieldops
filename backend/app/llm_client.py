from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import logging
import os
import re
import time
from contextlib import contextmanager
from typing import Any, Callable

from .models import CircuitBreakerStatus

logger = logging.getLogger(__name__)

_GEMINI_MODEL = "gemini-2.5-flash"
_TIMEOUT = 10.0
_FAIL_COUNT = 0
_CIRCUIT_OPEN = False
_CIRCUIT_OPEN_UNTIL = 0.0

_client = None
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="gemini")
_LLM_CONTEXT: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("llm_context", default=None)
_INPUT_COST_PER_1K = 0.00015
_OUTPUT_COST_PER_1K = 0.00060


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


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@contextmanager
def llm_capture(agent_name: str, recorder: Callable[[str, dict[str, Any]], None] | None = None):
    token = _LLM_CONTEXT.set({"agent_name": agent_name.upper(), "recorder": recorder})
    try:
        yield
    finally:
        _LLM_CONTEXT.reset(token)


def _record_event(
    *,
    success: bool,
    duration_ms: float,
    prompt: str,
    response_text: str | None,
    error: str | None,
) -> None:
    ctx = _LLM_CONTEXT.get()
    if not ctx:
        return
    recorder = ctx.get("recorder")
    if recorder is None:
        return
    input_tokens = _estimate_tokens(prompt)
    output_tokens = _estimate_tokens(response_text or "")
    cost = round((input_tokens / 1000) * _INPUT_COST_PER_1K + (output_tokens / 1000) * _OUTPUT_COST_PER_1K, 6)
    recorder(
        ctx.get("agent_name", "UNKNOWN"),
        {
            "success": success,
            "duration_ms": round(duration_ms, 2),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost,
            "error": error,
            "circuit_breaker": get_circuit_breaker_status().model_dump(mode="json"),
        },
    )


def _invoke_gemini(full_prompt: str) -> tuple[str | None, str | None]:
    """Synchronous Gemini call — safe to run in any thread."""
    global _FAIL_COUNT, _CIRCUIT_OPEN, _CIRCUIT_OPEN_UNTIL

    if _CIRCUIT_OPEN:
        if time.monotonic() < _CIRCUIT_OPEN_UNTIL:
            return None, "circuit_open"
        _CIRCUIT_OPEN = False
        _FAIL_COUNT = 0
        logger.info("Gemini circuit breaker reset")

    client = _get_client()
    if client is None:
        return None, "client_unavailable"

    from google.genai import types
    config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
    try:
        response = client.models.generate_content(
            model=_GEMINI_MODEL,
            contents=full_prompt,
            config=config,
        )
        _FAIL_COUNT = 0
        return response.text, None
    except Exception as exc:
        _FAIL_COUNT += 1
        logger.warning("Gemini call failed (%d): %s", _FAIL_COUNT, exc)
        if _FAIL_COUNT >= 3:
            _CIRCUIT_OPEN = True
            _CIRCUIT_OPEN_UNTIL = time.monotonic() + 30.0
            logger.warning("Gemini circuit breaker opened for 30s")
        return None, str(exc)


async def call_llm(system_prompt: str, user_prompt: str) -> str | None:
    """Async wrapper — schedules the blocking Gemini call on the bounded executor."""
    client = _get_client()
    if client is None:
        prompt = f"{system_prompt}\n\n{user_prompt}"
        _record_event(success=False, duration_ms=0.0, prompt=prompt, response_text=None, error="client_unavailable")
        return None
    full_prompt = f"{system_prompt}\n\n{user_prompt}"
    started_at = time.perf_counter()
    try:
        loop = asyncio.get_running_loop()
        response_text, error = await asyncio.wait_for(
            loop.run_in_executor(_executor, _invoke_gemini, full_prompt),
            timeout=_TIMEOUT,
        )
        duration_ms = (time.perf_counter() - started_at) * 1000
        _record_event(
            success=response_text is not None,
            duration_ms=duration_ms,
            prompt=full_prompt,
            response_text=response_text,
            error=error,
        )
        return response_text
    except asyncio.TimeoutError:
        logger.warning("Gemini call timed out after %ss", _TIMEOUT)
        _record_event(success=False, duration_ms=(time.perf_counter() - started_at) * 1000, prompt=full_prompt, response_text=None, error="timeout")
        return None
    except Exception as exc:
        logger.warning("Gemini async call failed: %s", exc)
        _record_event(success=False, duration_ms=(time.perf_counter() - started_at) * 1000, prompt=full_prompt, response_text=None, error=str(exc))
        return None


def call_llm_sync(system_prompt: str, user_prompt: str, timeout: float = _TIMEOUT) -> str | None:
    """Synchronous wrapper for use from non-async contexts (thread pool)."""
    full_prompt = f"{system_prompt}\n\n{user_prompt}"
    future = _executor.submit(_invoke_gemini, full_prompt)
    started_at = time.perf_counter()
    try:
        response_text, error = future.result(timeout=timeout)
        _record_event(
            success=response_text is not None,
            duration_ms=(time.perf_counter() - started_at) * 1000,
            prompt=full_prompt,
            response_text=response_text,
            error=error,
        )
        return response_text
    except concurrent.futures.TimeoutError:
        logger.warning("Gemini sync call timed out after %ss", timeout)
        _record_event(success=False, duration_ms=(time.perf_counter() - started_at) * 1000, prompt=full_prompt, response_text=None, error="timeout")
        return None
    except Exception as exc:
        logger.warning("Gemini sync call failed: %s", exc)
        _record_event(success=False, duration_ms=(time.perf_counter() - started_at) * 1000, prompt=full_prompt, response_text=None, error=str(exc))
        return None


def get_circuit_breaker_status() -> CircuitBreakerStatus:
    retry_after = 0.0
    if _CIRCUIT_OPEN:
        retry_after = max(0.0, _CIRCUIT_OPEN_UNTIL - time.monotonic())
    return CircuitBreakerStatus(
        available=is_llm_available(),
        circuit_open=_CIRCUIT_OPEN,
        fail_count=_FAIL_COUNT,
        retry_after_seconds=round(retry_after, 2),
        model=_GEMINI_MODEL,
    )


def extract_xml_tag(text: str, tag: str) -> str | None:
    pattern = rf"<{tag}>(.*?)</{tag}>"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else None
