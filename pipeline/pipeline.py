#!/usr/bin/env python3
"""Five-step knowledge pipeline: collect → analyze → organize → save → generate-static."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from model_client import chat_with_retry, create_provider

logger = logging.getLogger("pipeline")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "knowledge" / "raw"
ARTICLES_DIR = ROOT / "knowledge" / "articles"
RSS_CONFIG = ROOT / "pipeline" / "rss_sources.yaml"
VALIDATE_SCRIPT = ROOT / "hooks" / "validate_json.py"

# ---------------------------------------------------------------------------
# Step 1: Collect
# ---------------------------------------------------------------------------

_GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
_GITHUB_HEADERS = {
    "User-Agent": "knowledge-pipeline/0.1",
    "Accept": "application/vnd.github+json",
}
_AI_KEYWORDS = (
    "ai|llm|agent|gpt|rag|machine.learning|deep.learning|nlp|"
    "transformer|neural|chatbot|embedding|vector|langchain|llama|"
    "copilot|diffusion|generative|moe|finetune|inference|reasoning"
)

_RSS_TITLE = re.compile(r"<title>(?:\<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", re.S)
_RSS_LINK = re.compile(r"<link>(.*?)</link>", re.S)
_RSS_DESC = re.compile(
    r"<description>(?:\<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", re.S
)
_RSS_ITEM = re.compile(r"<item>(.*?)</item>", re.S)


_GITHUB_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2  # seconds; doubles each retry


def _retry_after_seconds(value: str | None, default: float = 60.0) -> float:
    """Parse a Retry-After header (seconds or HTTP-date) into seconds."""
    if not value:
        return default
    try:
        return max(1.0, float(value))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime

        retry_at = parsedate_to_datetime(value)
        wait = (retry_at - datetime.now(timezone.utc)).total_seconds()
        return max(1.0, wait)
    except (TypeError, ValueError, OverflowError):
        return default


def _collect_github(
    client: httpx.Client, limit: int, since_days: int = 7
) -> list[dict]:
    from datetime import timedelta

    since = (
        datetime.now(timezone.utc) - timedelta(days=since_days)
    ).strftime("%Y-%m-%d")
    params = {
        "q": f"created:>={since}",
        "sort": "stars",
        "order": "desc",
        "per_page": min(limit, 100),
    }

    headers = dict(_GITHUB_HEADERS)
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    items: list[dict] = []
    for attempt in range(1, _GITHUB_MAX_RETRIES + 1):
        try:
            resp = client.get(_GITHUB_SEARCH_URL, params=params, headers=headers)
            if resp.status_code in (403, 429):
                wait = _retry_after_seconds(resp.headers.get("Retry-After"))
                logger.warning(
                    "github rate limited (HTTP %d), waiting %.0fs (attempt %d/%d)",
                    resp.status_code, wait, attempt, _GITHUB_MAX_RETRIES,
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            items = resp.json().get("items", [])
            break
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt == _GITHUB_MAX_RETRIES:
                raise
            wait = _RETRY_BASE_DELAY ** attempt
            logger.warning(
                "github fetch failed (%s), retrying in %ds (attempt %d/%d)",
                exc, wait, attempt, _GITHUB_MAX_RETRIES,
            )
            time.sleep(wait)
    else:
        raise RuntimeError(
            f"GitHub Search API failed after {_GITHUB_MAX_RETRIES} attempts"
        )

    results: list[dict] = []
    ai_re = re.compile(_AI_KEYWORDS, re.I)
    for item in items:
        name = item.get("full_name", "")
        desc = item.get("description") or ""
        if "awesome" in name.lower():
            continue
        if not ai_re.search(f"{name} {desc}"):
            continue
        results.append({
            "title": name,
            "url": item["html_url"],
            "source": "github-trending",
            "popularity": item.get("stargazers_count", 0),
            "summary": (desc or "")[:200],
            "language": item.get("language"),
            "topics": item.get("topics", []),
        })

    results.sort(key=lambda r: r["popularity"], reverse=True)
    return results[:limit]


def _collect_rss(client: httpx.Client, limit: int) -> list[dict]:
    """Parse RSS sources from rss_sources.yaml, fetch enabled feeds."""
    if not RSS_CONFIG.is_file():
        logger.warning("RSS config not found: %s", RSS_CONFIG)
        return []

    sources: list[dict] = _load_rss_config()
    enabled = [s for s in sources if s.get("enabled")]
    if not enabled:
        logger.info("No RSS sources enabled")
        return []

    results: list[dict] = []
    for src in enabled[:5]:  # cap concurrent fetches
        name = src["name"]
        url = src["url"]
        try:
            resp = client.get(url, timeout=30.0)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("RSS fetch failed for %s: %s", name, exc)
            continue

        text = resp.text
        for m in _RSS_ITEM.finditer(text):
            block = m.group(1) or ""
            title_m = _RSS_TITLE.search(block)
            link_m = _RSS_LINK.search(block)
            desc_m = _RSS_DESC.search(block)
            title = title_m.group(1).strip() if title_m else ""
            link = link_m.group(1).strip() if link_m else ""
            desc = desc_m.group(1).strip() if desc_m else ""
            if title and link:
                results.append({
                    "title": title,
                    "url": link,
                    "source": "rss",
                    "popularity": 0,
                    "summary": (desc or "")[:200],
                    "language": None,
                    "topics": [],
                })

    results.sort(key=lambda r: len(r["summary"]), reverse=True)
    return results[:limit]


def _load_rss_config() -> list[dict]:
    """Load RSS sources from YAML without external deps."""
    text = RSS_CONFIG.read_text(encoding="utf-8")
    sources: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- name:"):
            current = {"name": stripped.split(":", 1)[1].strip()}
        elif stripped.startswith("url:") and current is not None:
            current["url"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("category:") and current is not None:
            current["category"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("enabled:") and current is not None:
            current["enabled"] = "true" in stripped.lower()
            sources.append(current)
            current = None
    return sources


# ---------------------------------------------------------------------------
# Step 2: Analyze
# ---------------------------------------------------------------------------

_ANALYZE_SYSTEM = """You are a technical analyst. For each item, return a JSON object:
{
  "summary": "refined Chinese summary, ≤50 chars",
  "score": <1-10>,
  "score_reason": "<one line reason>",
  "tags": ["Category/Subcategory", ...]
}
Tags must use "Category/Subcategory" format. Score 9-10 only for truly exceptional breakthroughs.
Return ONLY the JSON object, no markdown fences."""


def _analyze_items(
    items: list[dict], *, dry_run: bool = False
) -> list[dict]:
    if not items:
        return []

    if dry_run:
        logger.info("dry-run: skipping LLM analysis for %d items", len(items))
        return _fake_analysis(items)

    try:
        provider, model = create_provider()
    except ValueError as exc:
        logger.error("Cannot create provider: %s", exc)
        logger.warning("Falling back to fake analysis")
        return _fake_analysis(items)

    analyzed: list[dict] = []
    for i, item in enumerate(items):
        logger.info("analyzing %d/%d: %s", i + 1, len(items), item["title"])
        user_prompt = json.dumps({
            "title": item["title"],
            "url": item["url"],
            "description": item["summary"],
            "topics": item.get("topics", []),
        }, ensure_ascii=False)

        try:
            resp = chat_with_retry(
                provider,
                messages=[
                    {"role": "system", "content": _ANALYZE_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=512,
            )
            content = resp.content.strip()
            # Strip possible markdown fences
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
            analysis = json.loads(content)
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("analysis failed for %s: %s", item["title"], exc)
            analysis = _fake_single_analysis(item)

        analyzed.append({
            **item,
            "summary": str(analysis.get("summary", item["summary"]))[:50],
            "score": int(analysis.get("score", 5)),
            "score_reason": str(analysis.get("score_reason", "")),
            "tags": _normalize_tags(analysis.get("tags", [])),
        })

    return analyzed


def _normalize_tags(tags: list) -> list[str]:
    result: list[str] = []
    for tag in (tags or []):
        if isinstance(tag, str) and "/" in tag:
            result.append(tag)
        elif isinstance(tag, str):
            result.append(f"AI/{tag}")
    return result[:5]


def _fake_single_analysis(item: dict) -> dict:
    return {
        "summary": (item.get("summary") or item.get("title", ""))[:50],
        "score": 5,
        "score_reason": "auto-generated (no LLM)",
        "tags": item.get("topics", [])[:5] or ["AI/未分类"],
    }


def _fake_analysis(items: list[dict]) -> list[dict]:
    return [{**item, **_fake_single_analysis(item)} for item in items]


# ---------------------------------------------------------------------------
# Step 3: Organize
# ---------------------------------------------------------------------------


def _generate_id(source: str, seq: int) -> str:
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    source_code = {
        "github-trending": "github",
        "rss": "rss",
    }.get(source, source[:6])
    return f"{source_code}-{date_part}-{seq:03d}"


def _organize_items(analyzed: list[dict]) -> list[dict]:
    # Load existing articles for dedup
    existing_urls: set[str] = set()
    if ARTICLES_DIR.is_dir():
        for fpath in ARTICLES_DIR.glob("*.json"):
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                url = data.get("source_url", "")
                if url:
                    existing_urls.add(url)
            except (json.JSONDecodeError, OSError):
                pass

    organized: list[dict] = []
    seq = 0
    for item in analyzed:
        if item["url"] in existing_urls:
            logger.info("skip duplicate: %s", item["title"])
            continue
        seq += 1
        organized.append({
            "id": _generate_id(item["source"], seq),
            "title": item["title"],
            "source": item["source"],
            "source_url": item["url"],
            "summary": item.get("summary", ""),
            "stars": item.get("popularity", 0),
            "language": item.get("language"),
            "tags": item.get("tags", []),
            "highlights": [],
            "score": item.get("score"),
            "score_reason": item.get("score_reason", ""),
            "status": "draft",
        })

    return organized


# ---------------------------------------------------------------------------
# Step 4: Save
# ---------------------------------------------------------------------------


def _save_articles(articles: list[dict]) -> int:
    """Save articles as individual JSON files, run validation. Return count."""
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    saved = 0

    for article in articles:
        slug = re.sub(r"[^a-z0-9]+", "-", article["title"].lower()).strip("-")
        filename = f"{date_str}-{article['source']}-{slug}.json"
        fpath = ARTICLES_DIR / filename

        fpath.write_text(
            json.dumps(article, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info("saved: %s", fpath.name)
        saved += 1

    # Run validation on all saved files
    if saved and VALIDATE_SCRIPT.is_file():
        logger.info("running validation...")
        try:
            subprocess.run(
                [sys.executable, str(VALIDATE_SCRIPT), str(ARTICLES_DIR / "*.json")],
                check=False,
            )
        except OSError as exc:
            logger.warning("validation skipped: %s", exc)

    return saved


# ---------------------------------------------------------------------------
# Save raw intermediate
# ---------------------------------------------------------------------------


def _save_raw(filename: str, data: list[dict]) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / filename
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("raw saved: %s", path.name)


# ---------------------------------------------------------------------------
# Step 5: Generate static page
# ---------------------------------------------------------------------------

_GENERATE_SCRIPT = ROOT / "knowledge" / "generate_index.py"


def _generate_static_page() -> None:
    """Run the static page generator to rebuild knowledge/index.html."""
    if not _GENERATE_SCRIPT.is_file():
        logger.warning("Static page generator not found: %s", _GENERATE_SCRIPT)
        return

    logger.info("Running static page generator...")
    try:
        result = subprocess.run(
            [sys.executable, str(_GENERATE_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            logger.info("Static page generated successfully")
        else:
            logger.warning(
                "Static page generator exited with code %d: %s",
                result.returncode,
                result.stderr.strip() or result.stdout.strip(),
            )
    except subprocess.TimeoutExpired:
        logger.warning("Static page generator timed out")
    except OSError as exc:
        logger.warning("Static page generator failed: %s", exc)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def run_pipeline(
    *,
    sources: list[str],
    limit: int = 20,
    dry_run: bool = False,
) -> int:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    client = httpx.Client(
        timeout=30.0,
        transport=httpx.HTTPTransport(retries=3),
    )

    items: list[dict] = []

    # ── Step 1: Collect ──
    if "github" in sources:
        logger.info("=== Step 1: Collect (GitHub) ===")
        gh = _collect_github(client, limit=limit)
        logger.info("collected %d GitHub repos", len(gh))
        items.extend(gh)

    if "rss" in sources:
        logger.info("=== Step 1: Collect (RSS) ===")
        rss = _collect_rss(client, limit=limit)
        logger.info("collected %d RSS items", len(rss))
        items.extend(rss)

    if not items:
        logger.warning("No items collected")
        return 0

    _save_raw(f"github-trending-{date_str}.json", items)

    # ── Step 2: Analyze ──
    logger.info("=== Step 2: Analyze ===")
    analyzed = _analyze_items(items, dry_run=dry_run)
    logger.info("analyzed %d items", len(analyzed))

    # ── Step 3: Organize ──
    logger.info("=== Step 3: Organize ===")
    organized = _organize_items(analyzed)
    logger.info(
        "organized %d items (%d duplicates removed)",
        len(organized), len(analyzed) - len(organized),
    )

    # ── Step 4: Save ──
    if dry_run:
        logger.info("=== Step 4: Save (dry-run) ===")
        for art in organized:
            print(f"  would save: {art['title']}")
        logger.info("would save %d articles", len(organized))
        return 0

    logger.info("=== Step 4: Save ===")
    saved = _save_articles(organized)
    logger.info("saved %d articles", saved)

    # ── Step 5: Generate static page ──
    logger.info("=== Step 5: Generate Static Page ===")
    _generate_static_page()

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Knowledge pipeline")
    parser.add_argument(
        "--sources",
        default="github,rss",
        help="Comma-separated sources: github, rss (default: github,rss)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max items to collect per source (default: 20)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without saving or calling LLM",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    valid = {"github", "rss"}
    sources = [s for s in sources if s in valid]
    if not sources:
        logger.error("No valid sources. Use: %s", ", ".join(valid))
        sys.exit(2)

    sys.exit(run_pipeline(
        sources=sources,
        limit=args.limit,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
