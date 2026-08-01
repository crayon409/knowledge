"""LangGraph-compatible KBState for the knowledge pipeline.

Uses TypedDict so LangGraph can merge partial node return dicts.
"""

from __future__ import annotations

from typing import TypedDict


class KBState(TypedDict, total=False):
    """Shared state across pipeline nodes (report-style communication).

    Each field is a structured summary, not raw data.  Nodes return
    partial dicts containing only the keys they modify; LangGraph
    merges updates automatically.
    """

    queries: list[str]
    """Input: search queries for the GitHub collect phase, e.g. ["AI agent"]."""

    sources: list[dict]
    """Collect output: raw items from GitHub Search API.

    Each dict: {name, description, url, stars, language}.
    """

    analyses: list[dict]
    """Analyze output: LLM-enriched results per source item.

    Each dict inherits source fields plus: {title, summary, tags, score}.
    Ready for organize to filter / dedup / fix.
    """

    articles: list[dict]
    """Organize output: final formatted knowledge entries (filtered, deduped).

    Each dict: {title, source_url, summary, tags, score, stars, language, status}.
    Consumed by review_node and save_node.
    """

    review_feedback: str
    """Review output: supervisor feedback for the current iteration.

    Empty string means no issues found (passed).
    """

    review_passed: bool
    """Review output: whether the last review passed (overall_score >= 7)."""

    iteration: int
    """Current review-loop iteration (0-based).  Force-pass when >= 2."""

    cost_tracker: dict[str, int]
    """Accumulated LLM token usage across all calls.

    Keys: prompt_tokens, completion_tokens, total_tokens.
    """

    error: str | None
    """Fatal error message.  When set, downstream nodes should no-op."""

    total_count: int
    """Collect metric: total match count from GitHub Search API."""

    saved_count: int
    """Save metric: number of articles persisted in the final step."""


def new_state(**overrides) -> KBState:
    """Create an initial KBState with sensible defaults.

    Usage:
        initial = new_state(queries=["AI agent"])
        app.invoke(initial)
    """
    defaults: KBState = {
        "queries": [],
        "sources": [],
        "analyses": [],
        "articles": [],
        "iteration": 0,
        "review_feedback": "",
        "review_passed": False,
        "cost_tracker": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "error": None,
        "total_count": 0,
        "saved_count": 0,
    }
    return {**defaults, **overrides}  # type: ignore[return-value]
