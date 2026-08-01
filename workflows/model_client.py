"""Simplified LLM client wrapper for workflow layer.

Provides:
  - chat(prompt, *, system="", ...)       -> (text, usage)
  - chat_json(prompt, *, system="", ...)  -> (parsed_json, usage)
  - accumulate_usage(tracker, usage)      -> None
"""

from __future__ import annotations

import json
import re

from pipeline.model_client import create_provider

_provider = None
_provider_model = None


def _get_provider():
    global _provider, _provider_model
    if _provider is None:
        _provider, _provider_model = create_provider()
    return _provider, _provider_model


def chat(
    prompt: str,
    *,
    system: str = "",
    model: str | None = None,
    temperature: float = 0.7,
) -> tuple[str, dict]:
    """Send a chat request and return (text_content, usage_dict).

    Args:
        prompt: User message.
        system: Optional system message.
        model: Override the default model.
        temperature: Sampling temperature.

    Returns:
        Tuple of (response_text, usage_dict).
        usage_dict keys: prompt_tokens, completion_tokens, total_tokens.
    """
    provider, default_model = _get_provider()
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    resp = provider.chat(
        messages,
        model=model or default_model,
        temperature=temperature,
    )

    usage = {
        "prompt_tokens": resp.usage.prompt_tokens,
        "completion_tokens": resp.usage.completion_tokens,
        "total_tokens": resp.usage.total_tokens,
    }
    return resp.content, usage


def chat_json(
    prompt: str,
    *,
    system: str = "",
    model: str | None = None,
    temperature: float = 0.3,
) -> tuple[dict, dict]:
    """Chat and parse the response as JSON.

    Args:
        prompt: User message.
        system: Optional system message.
        model: Override the default model.
        temperature: Lower default (0.3) for structured output.

    Returns:
        Tuple of (parsed_json_dict, usage_dict).
        Falls back to {"raw": text} if JSON parsing fails.
    """
    text, usage = chat(prompt, system=system, model=model, temperature=temperature)

    # Try ```json fence
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1)), usage
        except json.JSONDecodeError:
            pass

    # Try bare JSON object
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group()), usage
        except json.JSONDecodeError:
            pass

    # Try full text
    try:
        return json.loads(text.strip()), usage
    except json.JSONDecodeError:
        return {"raw": text}, usage


def accumulate_usage(tracker: dict, usage: dict) -> None:
    """Accumulate token usage into a tracker dict (mutated in place).

    Args:
        tracker: Dict with prompt_tokens/completion_tokens/total_tokens keys.
        usage: Dict from chat() or chat_json() second return value.
    """
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        tracker[key] = tracker.get(key, 0) + usage.get(key, 0)
