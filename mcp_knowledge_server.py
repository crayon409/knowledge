#!/usr/bin/env python3
"""
MCP Server for searching a local knowledge base (knowledge/articles/*.json).

Protocol: JSON-RPC 2.0 over stdio.
"""

import json
import sys
from pathlib import Path
from typing import Any

ARTICLES_DIR = Path(__file__).resolve().parent / "knowledge" / "articles"

# ---------------------------------------------------------------------------
# Article loading
# ---------------------------------------------------------------------------


def _load_articles() -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []
    if not ARTICLES_DIR.is_dir():
        return articles

    for fpath in sorted(ARTICLES_DIR.glob("*.json")):
        try:
            with open(fpath, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                articles.append(data)
        except (json.JSONDecodeError, OSError):
            _log(f"skipped unreadable file: {fpath.name}")

    return articles


def _find_by_id(articles: list[dict[str, Any]], article_id: str) -> dict[str, Any] | None:
    for a in articles:
        if a.get("id") == article_id:
            return a
    return None


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


def _tool_search_articles(
    articles: list[dict[str, Any]], keyword: str, limit: int = 5
) -> dict[str, Any]:
    keyword_lower = keyword.lower()
    matches: list[dict[str, Any]] = []

    for a in articles:
        title = (a.get("title") or "").lower()
        summary = (a.get("summary") or "").lower()
        if keyword_lower in title or keyword_lower in summary:
            matches.append({
                "id": a.get("id"),
                "title": a.get("title"),
                "summary": a.get("summary"),
                "score": a.get("score"),
                "tags": a.get("tags", []),
            })

    matches.sort(key=lambda m: m.get("score") or 0, reverse=True)
    result = matches[: min(limit, 20)]

    return {
        "keyword": keyword,
        "total_hits": len(matches),
        "returned": len(result),
        "articles": result,
    }


def _tool_get_article(
    articles: list[dict[str, Any]], article_id: str
) -> dict[str, Any]:
    article = _find_by_id(articles, article_id)
    if article is None:
        return {
            "found": False,
            "article_id": article_id,
            "message": f"article '{article_id}' not found",
        }
    return {"found": True, "article": article}


def _tool_knowledge_stats(
    articles: list[dict[str, Any]],
) -> dict[str, Any]:
    total = len(articles)

    # source distribution
    sources: dict[str, int] = {}
    for a in articles:
        src = a.get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1

    # top tags
    tag_counts: dict[str, int] = {}
    for a in articles:
        for tag in a.get("tags", []):
            if isinstance(tag, str):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
    top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # score distribution
    scores: list[int] = []
    for a in articles:
        s = a.get("score")
        if isinstance(s, (int, float)):
            scores.append(int(s))
    avg_score = round(sum(scores) / len(scores), 1) if scores else None

    # status breakdown
    statuses: dict[str, int] = {}
    for a in articles:
        st = a.get("status", "unknown")
        statuses[st] = statuses.get(st, 0) + 1

    return {
        "total_articles": total,
        "sources": sources,
        "top_tags": [{"tag": t, "count": c} for t, c in top_tags],
        "score": {
            "average": avg_score,
            "min": min(scores) if scores else None,
            "max": max(scores) if scores else None,
        },
        "statuses": statuses,
    }


# ---------------------------------------------------------------------------
# MCP / JSON-RPC dispatch
# ---------------------------------------------------------------------------


TOOLS = [
    {
        "name": "search_articles",
        "description": "Search local knowledge articles by keyword in title and summary.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Search keyword (case-insensitive)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 5, max 20)",
                    "default": 5,
                },
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "get_article",
        "description": "Retrieve a single knowledge article by its id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "article_id": {
                    "type": "string",
                    "description": "The article id (e.g. github-20260326-001)",
                },
            },
            "required": ["article_id"],
        },
    },
    {
        "name": "knowledge_stats",
        "description": "Return summary statistics about the local knowledge base.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


def _handle_initialize(params: dict[str, Any], request_id: Any) -> dict[str, Any]:
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {},
        },
        "serverInfo": {
            "name": "knowledge-base-mcp",
            "version": "0.1.0",
        },
    }


def _handle_tools_list(_params: dict[str, Any], _request_id: Any) -> dict[str, Any]:
    return {"tools": TOOLS}


def _handle_tools_call(params: dict[str, Any], request_id: Any) -> dict[str, Any]:
    articles = _load_articles()
    name = params.get("name", "")
    arguments = params.get("arguments", {})

    if name == "search_articles":
        keyword = str(arguments.get("keyword", "")).strip()
        if not keyword:
            return {"content": [{"type": "text", "text": "Error: 'keyword' is required and must be non-empty."}], "isError": True}
        limit = min(int(arguments.get("limit", 5)), 20)
        result = _tool_search_articles(articles, keyword, limit)
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]}

    elif name == "get_article":
        article_id = str(arguments.get("article_id", "")).strip()
        if not article_id:
            return {"content": [{"type": "text", "text": "Error: 'article_id' is required."}], "isError": True}
        result = _tool_get_article(articles, article_id)
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]}

    elif name == "knowledge_stats":
        result = _tool_knowledge_stats(articles)
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]}

    else:
        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}


METHODS = {
    "initialize": _handle_initialize,
    "tools/list": _handle_tools_list,
    "tools/call": _handle_tools_call,
}

ERROR_PARSE = -32700
ERROR_METHOD = -32601


def _build_response(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _build_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


def _log(msg: str) -> None:
    print(f"[knowledge-mcp] {msg}", file=sys.stderr, flush=True)


def _read_message() -> dict[str, Any] | None:
    line = sys.stdin.readline()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _send_message(msg: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    _log("server started")

    for raw in sys.stdin:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            _build_error(None, ERROR_PARSE, "Parse error")
            continue

        request_id = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params", {})

        # notification — no response
        if request_id is None:
            continue

        if method not in METHODS:
            _send_message(_build_error(request_id, ERROR_METHOD, f"Method not found: {method}"))
            continue

        try:
            result = METHODS[method](params, request_id)
            _send_message(_build_response(request_id, result))
        except Exception as exc:
            _log(f"error handling {method}: {exc}")
            _send_message(_build_error(request_id, -32603, str(exc)))

    _log("server stopped")


if __name__ == "__main__":
    main()
