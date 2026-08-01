"""LangGraph node functions for the knowledge pipeline.

Nodes: collect → analyze → organize → review → save
"""

from __future__ import annotations

import json
import re
import ssl
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from workflows.model_client import chat, chat_json, accumulate_usage
from workflows.state import KBState

# ======================================================================
# Node 1: collect_node — GitHub Search API
# ======================================================================

GITHUB_API = "https://api.github.com/search/repositories"
GH_HEADERS = {
    "User-Agent": "knowledge-pipeline/1.0",
    "Accept": "application/vnd.github.v3+json",
}
DEFAULT_QUERIES = [
    "AI agent framework stars:>10",
    "LLM inference optimization",
    "machine learning open source tools",
]
COLLECT_PER_PAGE = 5


def collect_node(state: KBState) -> dict:
    """Fetch AI-related repositories from GitHub Search API."""
    print("[collect_node] Starting collection...")

    queries = state.queries or DEFAULT_QUERIES
    all_items: list[dict] = []
    total_count = 0

    for q in queries:
        encoded = urllib.parse.quote(q)
        url = f"{GITHUB_API}?q={encoded}&sort=stars&order=desc&per_page={COLLECT_PER_PAGE}"
        print(f"[collect_node] Querying: {q}")

        try:
            req = urllib.request.Request(url, headers=GH_HEADERS)
            ctx = ssl.create_default_context()
            try:
                with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                    data = json.loads(resp.read().decode())
            except urllib.error.URLError as e:
                if isinstance(e.reason, ssl.SSLError):
                    ctx = ssl._create_unverified_context()
                    with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                        data = json.loads(resp.read().decode())
                else:
                    raise
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:200] if e.fp else ""
            return {"error": f"GitHub API HTTP {e.code}: {body}"}
        except Exception as e:
            return {"error": f"GitHub API error: {e}"}

        total_count += data.get("total_count", 0)
        for item in data.get("items", []):
            all_items.append({
                "name": item.get("full_name", ""),
                "description": item.get("description") or "",
                "url": item.get("html_url", ""),
                "stars": item.get("stargazers_count", 0),
                "language": item.get("language") or "",
            })
        time.sleep(1)

    print(f"[collect_node] Collected {len(all_items)} items (total {total_count})")
    return {"items": all_items, "total_count": total_count}


# ======================================================================
# Node 2: analyze_node — LLM summary / tags / score
# ======================================================================

ANALYZE_SYSTEM = textwrap.dedent("""\
    你是一个技术项目分析助手。根据给定的 GitHub 项目信息，生成分析结果，仅返回 JSON：

    {
      "summary": "中文项目摘要（≤50字，聚焦核心价值和创新点）",
      "tags": ["分类/子分类", "分类/子分类"],
      "score": <1-10 的整数>
    }

    标签格式：一级分类/二级分类，如 AI/Agent、LLM/推理优化、工具/CLI。
    评分标准：
    - 1-3：玩具项目或文档不全
    - 4-6：有一定实用价值
    - 7-8：优秀开源项目
    - 9-10：突破性创新（每批 ≤2 个）
    仅返回 JSON，不加其他文字。
""")


def analyze_node(state: KBState) -> dict:
    """LLM analysis: generate summary, tags, score for each item."""
    print("[analyze_node] Starting analysis...")

    if state.error:
        return {}

    items = state.items
    if not items:
        return {"articles": []}

    articles: list[dict] = []
    tracker = dict(state.usage_tracker)

    for item in items:
        prompt = (
            f"项目名称：{item['name']}\n"
            f"描述：{item['description']}\n"
            f"语言：{item['language']}\n"
            f"Stars：{item['stars']}"
        )

        try:
            parsed, usage = chat_json(prompt, system=ANALYZE_SYSTEM)
            accumulate_usage(tracker, usage)
        except Exception:
            parsed = {"summary": item["description"][:50], "tags": [], "score": 5}

        articles.append({
            "title": item["name"],
            "source_url": item["url"],
            "summary": parsed.get("summary", "")[:50],
            "tags": parsed.get("tags", []),
            "score": int(parsed.get("score", 5)),
            "stars": item["stars"],
            "language": item["language"],
            "status": "active",
        })

    print(f"[analyze_node] Analyzed {len(articles)} articles")
    return {"articles": articles, "usage_tracker": tracker}


# ======================================================================
# Node 3: organize_node — filter / dedup / LLM fixes
# ======================================================================

FIX_SYSTEM = textwrap.dedent("""\
    你是内容编辑助手。根据审核反馈修正技术文章分析结果，仅返回 JSON：

    {
      "summary": "修正后的中文摘要（≤50字）",
      "tags": ["修正后的标签"],
      "score": <修正后的 1-10 整数评分>
    }
""")


def organize_node(state: KBState) -> dict:
    """Filter low-score (<6), dedup by URL, apply LLM fixes if feedback exists."""
    print("[organize_node] Organizing...")

    if state.error:
        return {}

    articles = state.articles
    if not articles:
        return {"articles": []}

    # Step 1: filter score < 6
    filtered = [a for a in articles if a.get("score", 0) >= 6]
    dropped = len(articles) - len(filtered)
    if dropped:
        print(f"[organize_node] Dropped {dropped} low-score articles (score < 6)")

    # Step 2: deduplicate by source_url
    seen: set[str] = set()
    deduped: list[dict] = []
    for a in filtered:
        url = a.get("source_url", "")
        if url and url in seen:
            continue
        seen.add(url)
        deduped.append(a)
    dup_count = len(filtered) - len(deduped)
    if dup_count:
        print(f"[organize_node] Removed {dup_count} duplicates")

    # Step 3: LLM fixes when iteration > 0 and feedback exists
    tracker = dict(state.usage_tracker)
    if state.iteration > 0 and state.feedback:
        print(f"[organize_node] Applying LLM fixes (iteration {state.iteration})...")
        for art in deduped:
            prompt = (
                f"当前文章：\n"
                f"标题：{art['title']}\n"
                f"摘要：{art['summary']}\n"
                f"标签：{', '.join(art['tags'])}\n"
                f"评分：{art['score']}\n\n"
                f"审核反馈：{state.feedback}\n"
                f"请根据反馈修正摘要、标签和评分。"
            )
            try:
                parsed, usage = chat_json(prompt, system=FIX_SYSTEM)
                accumulate_usage(tracker, usage)
                art["summary"] = parsed.get("summary", art["summary"])[:50]
                art["tags"] = parsed.get("tags", art["tags"])
                art["score"] = int(parsed.get("score", art["score"]))
            except Exception:
                pass

    print(f"[organize_node] Final count: {len(deduped)}")
    return {"articles": deduped, "usage_tracker": tracker}


# ======================================================================
# Node 4: review_node — quality review (4 dimensions)
# ======================================================================

REVIEW_SYSTEM = textwrap.dedent("""\
    你是一位严格的质量审核员。审核一批技术文章的分析质量，从四个维度评分（1-10）：

    - summary_quality：摘要是否准确简洁（≤50字）、聚焦核心价值
    - tag_accuracy：标签格式是否正确（分类/子分类）、是否匹配内容
    - classification_reasonableness：分类层级是否合理
    - consistency：评分与内容质量是否一致

    overall_score = 四维度平均分，passed = overall_score >= 7

    仅返回 JSON：
    {
      "passed": true/false,
      "overall_score": <float>,
      "feedback": "不通过时的改进建议（通过时为空字符串）",
      "scores": {
        "summary_quality": <int>,
        "tag_accuracy": <int>,
        "classification_reasonableness": <int>,
        "consistency": <int>
      }
    }
""")


def review_node(state: KBState) -> dict:
    """Review article batch quality. Force-pass when iteration >= 2."""
    print("[review_node] Reviewing...")

    if state.error:
        return {}

    articles = state.articles
    iteration = state.iteration

    if iteration >= 2:
        print(f"[review_node] iteration={iteration} → force pass")
        return {"passed": True, "feedback": "", "iteration": iteration + 1}

    if not articles:
        return {"passed": True, "feedback": "", "iteration": iteration + 1}

    batch_text = "\n\n".join(
        f"[{i}] {a['title']}\n"
        f"摘要：{a['summary']}\n"
        f"标签：{', '.join(a['tags'])}\n"
        f"评分：{a['score']}"
        for i, a in enumerate(articles, 1)
    )

    review_result, usage = chat_json(
        f"请审核以下 {len(articles)} 篇文章：\n\n{batch_text}",
        system=REVIEW_SYSTEM,
    )

    passed = review_result.get("passed", False)
    feedback = review_result.get("feedback", "")
    overall = review_result.get("overall_score", 0)

    tracker = dict(state.usage_tracker)
    accumulate_usage(tracker, usage)

    print(
        f"[review_node] Passed={passed}, Overall={overall}, "
        f"Feedback={'yes' if feedback else 'no'}"
    )

    return {
        "passed": passed,
        "feedback": feedback,
        "iteration": iteration + 1,
        "usage_tracker": tracker,
        "_review_scores": review_result.get("scores", {}),
    }


# ======================================================================
# Node 5: save_node — persist articles + update index.json
# ======================================================================

ARTICLES_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "articles"
INDEX_PATH = ARTICLES_DIR / "index.json"


def save_node(state: KBState) -> dict:
    """Persist articles to JSON files and update index.json."""
    print("[save_node] Saving articles...")

    if state.error:
        return {}

    articles = state.articles
    if not articles:
        print("[save_node] No articles to save")
        return {"saved_count": 0}

    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    saved = 0
    index_entries: list[dict] = _load_index()

    for art in articles:
        slug = _make_slug(art.get("title", ""))
        filename = f"{today}-workflow-{slug}.json"

        record = {
            "id": f"{today}-workflow-{saved + 1:03d}",
            "title": art.get("title", ""),
            "source": "workflow",
            "source_url": art.get("source_url", ""),
            "summary": art.get("summary", ""),
            "stars": art.get("stars", 0),
            "language": art.get("language", ""),
            "tags": art.get("tags", []),
            "score": art.get("score", 0),
            "status": art.get("status", "active"),
        }

        filepath = ARTICLES_DIR / filename
        filepath.write_text(
            json.dumps(record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        index_entries.append({
            "id": record["id"],
            "title": record["title"],
            "summary": record["summary"],
            "tags": record["tags"],
            "source_url": record["source_url"],
        })
        saved += 1

    INDEX_PATH.write_text(
        json.dumps(index_entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[save_node] Saved {saved} articles to {ARTICLES_DIR}")
    return {"saved_count": saved}


def _make_slug(title: str) -> str:
    """Generate a URL-safe slug from a title."""
    slug = title.lower().strip()
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", slug)
    slug = slug.strip("-")[:60]
    return slug or "untitled"


def _load_index() -> list[dict]:
    """Load existing index.json or return empty list."""
    if INDEX_PATH.exists():
        try:
            return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return []


# ======================================================================
# Smoke test
# ======================================================================

if __name__ == "__main__":
    s = KBState()

    updates = collect_node(s)
    print(f"\ncollect → items={len(updates.get('items', []))}, error={updates.get('error')}")
    if updates.get("error"):
        print(f"ERROR: {updates['error']}")
        exit(1)
    for k, v in updates.items():
        setattr(s, k, v)

    updates = analyze_node(s)
    print(f"analyze → articles={len(updates.get('articles', []))}")
    for k, v in updates.items():
        setattr(s, k, v)

    updates = organize_node(s)
    print(f"organize → articles={len(updates.get('articles', []))}")
    for k, v in updates.items():
        setattr(s, k, v)

    updates = review_node(s)
    print(f"review → passed={updates.get('passed')}, feedback={bool(updates.get('feedback'))}")
    for k, v in updates.items():
        setattr(s, k, v)

    if not s.passed and s.iteration < 2:
        s.feedback = updates.get("feedback", "")
        print(f"\n--- Retry (iteration {s.iteration}) ---")
        for k, v in organize_node(s).items():
            setattr(s, k, v)
        for k, v in review_node(s).items():
            setattr(s, k, v)
        print(f"review#2 → passed={s.passed}")

    updates = save_node(s)
    print(f"save → saved_count={updates.get('saved_count')}")
    print(f"\nTotal tokens: {s.usage_tracker}")
