"""Two-layer intent router for workflow queries.

Layer 1: Keyword fast matching (zero LLM cost)
Layer 2: LLM classification fallback (ambiguous queries)

Intents: github_search | knowledge_query | general_chat
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from workflows.model_client import chat, chat_json

# ======================================================================
# Layer 1: Keyword-based fast classification
# ======================================================================


def _keyword_classify(query: str) -> str | None:
    """Fast keyword matching. Returns intent name or None if ambiguous."""
    q = query.strip()

    # --- github_search patterns ---
    gh_patterns = [
        r'(?:github|gh)\s*(?:搜|找|查)',
        r'(?:搜|找|查)\s*(?:github|gh)\b',
        r'(?:搜|找|查).{0,8}(?:仓库|repo|库|项目).{0,8}(?:github|gh|开源)',
        r'(?:github|gh|开源).{0,8}(?:仓库|repo|库|项目).{0,8}(?:搜|找|查)',
        r'(?:搜|找|查).{0,8}开源.?(?:项目|框架|库|工具|代码)',
        r'(?:stars?|star数|多少星).*github',
        r'github.*(?:热门|最新|趋势|trend|排行)',
        r'(?:帮我|帮助).{0,4}(?:搜|找|查).{0,8}(?:github|开源)',
        r'(?:看看|有没有).{0,4}(?:github|gh).*(?:项目|repo|库|框架)',
        r'在\s*github',
        r'(?:搜|找|查).*在\s*github',
    ]
    for pat in gh_patterns:
        if re.search(pat, q, re.IGNORECASE):
            return "github_search"

    # --- knowledge_query patterns ---
    kb_patterns = [
        r'(?:知识库|knowledge\s*base).{0,6}(?:搜|找|查|检索|查询)',
        r'(?:搜|找|查|检索|查询).{0,6}(?:知识库|knowledge\s*base)',
        r'(?:文章|记录|存了|收录).{0,6}(?:搜|找|查|检索)',
        r'(?:搜|找|查|检索).{0,6}(?:文章|记录)',
        r'(?:之前|以前|历史|上次).{0,8}(?:记录|存|写过|说过|提到)',
        r'(?:记录|存|写过|提到).{0,6}(?:过|了|的吗|吗)',
        r'(?:本地|内部|自己|这里|我们这).{0,6}(?:搜|找|查|检索)',
        r'(?:还记得|记得|记不记得)',
        r'(?:存了|收录了|记录了).{0,4}(?:吗|什么|哪些)',
        r'(?:知识库|里面|里边).{0,4}(?:有|有什么|多少)',
    ]
    for pat in kb_patterns:
        if re.search(pat, q, re.IGNORECASE):
            return "knowledge_query"

    return None  # ambiguous, fall through to LLM


# ======================================================================
# Layer 2: LLM-based classification
# ======================================================================

INTENT_SYSTEM = (
    "你是一个意图分类器。分析用户输入，判断意图，仅返回 JSON。\n"
    "三种意图：\n"
    "- github_search：用户想在 GitHub 搜索开源项目/仓库\n"
    "- knowledge_query：用户想查询本地知识库中已收录的文章/记录\n"
    "- general_chat：其他所有情况（闲聊、提问、讨论等）\n\n"
    '返回格式：{"intent": "<intent_name>"}'
)

VALID_INTENTS = {"github_search", "knowledge_query", "general_chat"}


def _llm_classify(query: str) -> str:
    """LLM-based fallback classifier using chat_json()."""
    try:
        result, _ = chat_json(f"用户输入：{query}", system=INTENT_SYSTEM)
        intent = (result.get("intent") or "").strip().lower()
        if intent in VALID_INTENTS:
            return intent
    except Exception:
        pass
    return "general_chat"


# ======================================================================
# Handler: github_search
# ======================================================================

GITHUB_API = "https://api.github.com/search/repositories"
GH_HEADERS = {
    "User-Agent": "knowledge-router/1.0",
    "Accept": "application/vnd.github.v3+json",
}


def handle_github_search(query: str) -> str:
    """Search GitHub repositories via Search API."""
    terms = _extract_search_terms(query)
    if not terms:
        return "请提供要搜索的关键词，如：搜索 GitHub 上的 LLM Agent 项目"

    params = urllib.parse.urlencode({
        "q": terms,
        "sort": "stars",
        "order": "desc",
        "per_page": "5",
    })
    url = f"{GITHUB_API}?{params}"

    try:
        req = urllib.request.Request(url, headers=GH_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        if e.fp:
            body = e.read().decode()[:200]
        return f"GitHub API 请求失败 (HTTP {e.code})：{body}"
    except Exception as e:
        return f"GitHub 搜索异常：{e}"

    items = data.get("items", [])
    if not items:
        return f'未在 GitHub 上找到与「{terms}」相关的项目。'

    total = data.get("total_count", 0)
    lines = [
        f'GitHub 搜索「{terms}」结果（共 {total} 个，显示前 5）：'
    ]
    for i, item in enumerate(items, 1):
        name = item.get("full_name", "unknown")
        stars = item.get("stargazers_count", 0)
        desc = (item.get("description") or "无描述")[:120]
        url_ = item.get("html_url", "")
        lang = item.get("language") or ""
        parts = [f"\n{i}. {name}  ⭐{stars}"]
        if lang:
            parts.append(f"  [{lang}]")
        parts.append(f"\n   {desc}\n   {url_}")
        lines.append("".join(parts))

    return "\n".join(lines)


_NOISE_WORDS = [
    "搜索", "搜一下", "搜一搜", "帮我搜", "帮我搜索", "帮我找",
    "找一下", "查找", "查一下", "帮我查", "查查", "帮我看看",
    "看看", "看一看", "有没有", "有哪些", "有什么",
    "一下", "帮我", "你帮我", "你能帮我", "可以帮我",
    "github", "GitHub", "GH",
]


def _extract_search_terms(query: str) -> str:
    """Strip intent-signalling words, leave only real search terms."""
    q = query
    for w in _NOISE_WORDS:
        q = re.sub(r'\b' + re.escape(w) + r'\b', '', q, flags=re.IGNORECASE)
    q = re.sub(r"\s+", " ", q).strip()
    q = re.sub(r"^[\s，,。；;：:！!？?]+|[\s，,。；;：:！!？?]+$", "", q)
    return q or query.strip()


# ======================================================================
# Handler: knowledge_query
# ======================================================================

ARTICLES_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "articles"


def handle_knowledge_query(query: str) -> str:
    """Query local knowledge articles with keyword search."""
    articles = _load_articles()
    if not articles:
        return "知识库暂无文章，请先运行采集流水线。"

    terms = _tokenize(query)
    if not terms:
        newest = articles[0].get("title", "未知")
        return f"知识库共 {len(articles)} 篇文章，请提供关键词筛选。\n最新收录：{newest}"

    scored = []
    for art in articles:
        s = _score_article(art, terms)
        if s > 0:
            scored.append((s, art))

    scored.sort(key=lambda x: x[0], reverse=True)

    if not scored:
        return f'知识库中未找到与「{query}」相关的文章，试试换个关键词？'

    lines = [f'知识库检索「{query}」（匹配 {len(scored)} 篇，显示前 5）：']
    for idx, (score, art) in enumerate(scored[:5], 1):
        title = art.get("title", "无标题")
        summary = art.get("summary", "")
        tags = ", ".join(art.get("tags", []))
        url = art.get("source_url", "")
        lines.append(f"\n{idx}. {title}  (相关度: {score})")
        if summary:
            lines.append(f"   {summary}")
        if tags:
            lines.append(f"   标签：{tags}")
        if url:
            lines.append(f"   {url}")

    return "\n".join(lines)


def _load_articles() -> list[dict]:
    """Load all JSON articles from knowledge/articles/ (cached)."""
    if _load_articles._cache is not None:
        return _load_articles._cache

    if not ARTICLES_DIR.exists():
        _load_articles._cache = []
        return []

    articles: list[dict] = []
    for fp in sorted(ARTICLES_DIR.glob("*.json")):
        try:
            art = json.loads(fp.read_text(encoding="utf-8"))
            art["_file"] = fp.name
            articles.append(art)
        except (json.JSONDecodeError, OSError):
            continue

    _load_articles._cache = articles
    return articles


_load_articles._cache = None


def _tokenize(text: str) -> list[str]:
    """Simple tokenizer: individual CJK chars + ASCII word sequences."""
    tokens: list[str] = []
    for ch in text:
        cp = ord(ch)
        if (
            0x4E00 <= cp <= 0x9FFF
            or 0x3040 <= cp <= 0x30FF
            or 0xAC00 <= cp <= 0xD7AF
        ):
            tokens.append(ch)
    for m in re.finditer(r"[a-zA-Z0-9]+", text):
        tokens.append(m.group().lower())
    return list(dict.fromkeys(tokens))


def _score_article(article: dict, terms: list[str]) -> int:
    """Score article against terms: title ×3, summary ×2, tags ×1."""
    fields = [
        ((article.get("title") or "").lower(), 3),
        ((article.get("summary") or "").lower(), 2),
        (" ".join(article.get("tags") or []).lower(), 1),
    ]
    score = 0
    for term in terms:
        tl = term.lower()
        for field, weight in fields:
            if tl in field:
                score += weight
    return score


# ======================================================================
# Handler: general_chat
# ======================================================================

GENERAL_SYSTEM = "你是技术助手，精通 AI/LLM/Agent 等领域。请用中文简洁专业地回答。"


def handle_general_chat(query: str) -> str:
    """Handle general chat via LLM."""
    try:
        text, _ = chat(query, system=GENERAL_SYSTEM)
        return text.strip()
    except Exception as e:
        return f"LLM 调用失败：{e}"


# ======================================================================
# Dispatcher
# ======================================================================

HANDLERS = {
    "github_search": handle_github_search,
    "knowledge_query": handle_knowledge_query,
    "general_chat": handle_general_chat,
}


def route(query: str) -> str:
    """Unified entry point: two-layer classification → handler dispatch."""
    q = query.strip()
    if not q:
        return "请输入要查询的内容。"

    intent = _keyword_classify(q)
    if intent is None:
        intent = _llm_classify(q)

    handler = HANDLERS.get(intent, handle_general_chat)
    return handler(q)


# ======================================================================
# CLI smoke test
# ======================================================================

if __name__ == "__main__":
    TEST_QUERIES = [
        "帮我搜一下 GitHub 上 Stars 最高的 AI Agent 项目",
        "开源 RAG 框架有哪些推荐？",
        "知识库里有没有关于 DeepSeek 的记录",
        "之前你存过的那个 MCP Server 是什么",
        "Python 协程和线程有什么区别",
    ]

    for q in TEST_QUERIES:
        intent = _keyword_classify(q)
        label = intent if intent else "ambiguous → LLM fallback"
        print(f"[{label}] {q}")
        if intent:
            output = route(q)
            print(f"  → {output[:200]}...\n")
