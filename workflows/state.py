"""LangGraph-compatible KBState for the knowledge pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class KBState:
    """State shared across pipeline nodes.

    Fields are initialized with sensible defaults so LangGraph can
    merge partial updates from node return dicts.
    """

    queries: list[str] = field(default_factory=list)
    """Search queries for the collect phase."""

    items: list[dict] = field(default_factory=list)
    """Raw items fetched from GitHub Search API."""

    articles: list[dict] = field(default_factory=list)
    """Processed articles with summary / tags / score / source_url."""

    iteration: int = 0
    """Review iteration counter (0-based)."""

    feedback: str = ""
    """Supervisor feedback for the current iteration."""

    passed: bool = False
    """Whether the most recent review passed."""

    usage_tracker: dict[str, int] = field(
        default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    )
    """Accumulated token usage across all LLM calls."""

    error: str | None = None
    """Error message if a node fails (prevents downstream execution)."""

    total_count: int = 0
    """Total count from GitHub Search API."""

    saved_count: int = 0
    """Number of articles saved in the final step."""
