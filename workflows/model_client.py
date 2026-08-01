"""Simplified LLM client wrapper for workflow layer.

Provides two convenience functions:
  - chat(system, prompt)  -> (text: str, usage: dict)
  - chat_json(system, prompt) -> dict
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
        _provider._client.timeout = _provider._client.timeout
    return _provider, _provider_model


def chat(
    system: str,
    prompt: str,
    *,
    model: str | None = None,
    temperature: float = 0.7,
) -> tuple[str, dict]:
    """Send a chat request and return (text_content, usage_dict).

    Args:
        system: System message (set as system role).
        prompt: User message.
        model: Override the default model.
        temperature: Sampling temperature.

    Returns:
        Tuple of (response_text, usage_dict with prompt_tokens/completion_tokens/total_tokens).
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
    system: str,
    prompt: str,
    *,
    model: str | None = None,
    temperature: float = 0.3,
) -> dict:
    """Chat and parse the response as JSON.

    Attempts to extract a JSON object from the response (supports ```json fences
    and bare JSON). Falls back to {"raw": text} if parsing fails.

    Args:
        system: System message.
        prompt: User message.
        model: Override the default model.
        temperature: Lower default (0.3) for structured output.

    Returns:
        Parsed JSON dict.
    """
    text, _ = chat(system, prompt, model=model, temperature=temperature)

    # Try ```json fence first
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try bare JSON object
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    # Try full text
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return {"raw": text}
