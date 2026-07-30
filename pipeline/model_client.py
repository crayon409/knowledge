"""Unified LLM client supporting DeepSeek, Qwen, and OpenAI via OpenAI-compatible API."""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

PROVIDERS: dict[str, dict[str, str]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "env_key": "DEEPSEEK_API_KEY",
        "price_input": 0.27,    # USD per 1M tokens
        "price_output": 1.10,
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "env_key": "QWEN_API_KEY",
        "price_input": 0.80,
        "price_output": 2.00,
    },
    # "openai": {
    #     "base_url": "https://api.openai.com/v1",
    #     "default_model": "gpt-4o",
    #     "env_key": "OPENAI_API_KEY",
    #     "price_input": 2.50,
    #     "price_output": 10.00,
    # },
}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Usage:
    """Token usage statistics."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """Unified LLM response."""

    content: str
    model: str
    usage: Usage = field(default_factory=Usage)
    finish_reason: str = "stop"
    raw: dict[str, Any] | None = None

    @property
    def cost_usd(self) -> float | None:
        """Estimated cost in USD; None if provider prices are unavailable."""
        return None


# ---------------------------------------------------------------------------
# Abstract provider
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Abstract interface for an LLM provider."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """Send a chat completion request and return the unified response."""
        ...

    @abstractmethod
    def estimate_tokens(self, text: str) -> int:
        """Estimate the number of tokens for the given text."""
        ...

    @abstractmethod
    def calculate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate the estimated USD cost for the given token counts."""
        ...


# ---------------------------------------------------------------------------
# OpenAI-compatible HTTP provider
# ---------------------------------------------------------------------------


class OpenAICompatibleProvider(LLMProvider):
    """Provider that speaks the OpenAI /v1/chat/completions API."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        default_model: str,
        price_input: float = 0.0,
        price_output: float = 0.0,
        *,
        timeout: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._default_model = default_model
        self._price_input = price_input
        self._price_output = price_output
        self._client = httpx.Client(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(timeout),
        )

    # ------------------------------------------------------------------
    # LLMProvider implementation
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        model = model or self._default_model
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        resp = self._client.post("/chat/completions", json=body)
        resp.raise_for_status()
        data = resp.json()

        choice = data["choices"][0]
        usage_raw = data.get("usage", {})

        return LLMResponse(
            content=choice["message"]["content"],
            model=data.get("model", model),
            usage=Usage(
                prompt_tokens=usage_raw.get("prompt_tokens", 0),
                completion_tokens=usage_raw.get("completion_tokens", 0),
                total_tokens=usage_raw.get("total_tokens", 0),
            ),
            finish_reason=choice.get("finish_reason", "stop"),
            raw=data,
        )

    def estimate_tokens(self, text: str) -> int:
        """Rough token estimate: ~1 token per char for CJK, ~0.75 for ASCII."""
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        ascii_chars = len(text) - cjk
        return cjk + int(ascii_chars * 0.75)

    def calculate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        input_cost = prompt_tokens / 1_000_000 * self._price_input
        output_cost = completion_tokens / 1_000_000 * self._price_output
        return round(input_cost + output_cost, 6)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()


# ---------------------------------------------------------------------------
# Retry wrapper
# ---------------------------------------------------------------------------


def chat_with_retry(
    provider: LLMProvider,
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    retries: int = 3,
    base_delay: float = 1.0,
) -> LLMResponse:
    """Call `provider.chat()` with exponential-backoff retries.

    Args:
        provider: An LLMProvider instance.
        messages: Chat messages in OpenAI format.
        model: Override the default model.
        temperature: Sampling temperature (0–2).
        max_tokens: Maximum completion tokens.
        retries: Maximum number of attempts (default 3).
        base_delay: Initial backoff delay in seconds (doubles each retry).

    Returns:
        LLMResponse on success.

    Raises:
        The last `httpx.HTTPError` after all retries are exhausted.
    """
    last_exc: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            return provider.chat(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            status = exc.response.status_code
            if status < 500 and status != 429:
                raise  # client error → don't retry
            logger.warning(
                "attempt %d/%d failed (HTTP %d), retrying in %.1fs",
                attempt, retries, status, base_delay,
            )
        except httpx.RequestError as exc:
            last_exc = exc
            logger.warning(
                "attempt %d/%d failed (%s), retrying in %.1fs",
                attempt, retries, exc, base_delay,
            )

        if attempt < retries:
            time.sleep(base_delay)
            base_delay *= 2

    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


def _get_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def create_provider(
    provider_name: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> tuple[OpenAICompatibleProvider, str]:
    """Factory: create an OpenAICompatibleProvider from env vars.

    Args:
        provider_name: One of ``deepseek`` / ``qwen`` / ``openai``.
            Defaults to ``LLM_PROVIDER`` env var or ``deepseek``.
        api_key: API key. Defaults to the corresponding ``*_API_KEY`` env var.
        model: Model name. Defaults to the provider's ``default_model``.

    Returns:
        A ``(provider, model)`` tuple.
    """
    name = provider_name or _get_env("LLM_PROVIDER", "deepseek")
    if name not in PROVIDERS:
        raise ValueError(
            f"Unknown provider '{name}'. Valid: {', '.join(PROVIDERS)}"
        )

    cfg = PROVIDERS[name]
    key = api_key or _get_env(cfg["env_key"])
    if not key:
        raise ValueError(
            f"API key not set. Set {cfg['env_key']} env var or pass api_key="
        )

    return (
        OpenAICompatibleProvider(
            base_url=cfg["base_url"],
            api_key=key,
            default_model=cfg["default_model"],
            price_input=cfg["price_input"],
            price_output=cfg["price_output"],
        ),
        model or cfg["default_model"],
    )


def quick_chat(
    prompt: str,
    *,
    system: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> LLMResponse:
    """One-call convenience: send a single user message and return the reply.

    Args:
        prompt: User message text.
        system: Optional system message.
        provider: Provider name (``deepseek`` / ``qwen`` / ``openai``).
        model: Model override.

    Returns:
        LLMResponse with content, usage, and cost info.

    Example:
        >>> resp = quick_chat("What is 2+2?")
        >>> print(resp.content)
    """
    p, m = create_provider(provider_name=provider, model=model)
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return chat_with_retry(p, messages, model=m)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s"
    )

    response = quick_chat("用一句话介绍什么是 AI Agent。")
    print(response.content)
