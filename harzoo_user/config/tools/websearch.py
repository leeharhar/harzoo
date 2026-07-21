"""WebSearch — search the web via configurable providers."""


from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from typing import Any

from harzoo.agent.kernel.tool import Tool, ToolResult

TOOL_VERSION = "2026-06-29"

MAX_RESULTS = 10
MAX_SNIPPET_CHARS = 500


def _truncate(text: str, limit: int = MAX_SNIPPET_CHARS) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _search_duckduckgo(query: str, *, max_results: int) -> list[dict[str, str]]:
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; HarzooWebSearch/1.0)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    results: list[dict[str, str]] = []
    for block in re.findall(r'<a rel="nofollow" class="result__a" href="([^"]+)"[^>]*>(.*?)</a>', html, flags=re.DOTALL):
        if len(results) >= max_results:
            break
        link, title_html = block
        title = unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
        if not title:
            continue
        results.append({"title": title, "url": unescape(link), "snippet": ""})
    for i, snip in enumerate(re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', html, flags=re.DOTALL)):
        if i >= len(results):
            break
        results[i]["snippet"] = _truncate(unescape(re.sub(r"<[^>]+>", "", snip)))
    return results


def _search_serper(query: str, *, api_key: str, max_results: int) -> list[dict[str, str]]:
    payload = json.dumps({"q": query, "num": max_results}).encode("utf-8")
    req = urllib.request.Request(
        "https://google.serper.dev/search",
        data=payload,
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    organic = data.get("organic") or []
    return [
        {
            "title": str(item.get("title") or ""),
            "url": str(item.get("link") or ""),
            "snippet": _truncate(str(item.get("snippet") or "")),
        }
        for item in organic[:max_results]
        if item.get("link")
    ]


def _search_tavily(query: str, *, api_key: str, max_results: int) -> list[dict[str, str]]:
    payload = json.dumps({"api_key": api_key, "query": query, "max_results": max_results}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return [
        {
            "title": str(item.get("title") or ""),
            "url": str(item.get("url") or ""),
            "snippet": _truncate(str(item.get("content") or "")),
        }
        for item in (data.get("results") or [])[:max_results]
        if item.get("url")
    ]


class WebSearchTool(Tool):
    """Search the web. Provider: duckduckgo (default), serper, or tavily (needs WEBSEARCH_API_KEY)."""

    name = "WebSearch"
    description = (
        "Search the web and return titles, URLs, and snippets. "
        "Set WEBSEARCH_PROVIDER (duckduckgo|serper|tavily) and WEBSEARCH_API_KEY for paid APIs."
    )
    parameters = {
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "description": "Max results (1-10)", "default": 5},
            "provider": {
                "type": "string",
                "enum": ["duckduckgo", "serper", "tavily"],
                "description": "Override WEBSEARCH_PROVIDER env var",
            },
        },
        "required": ["query"],
    }

    def execute(self, query: str, max_results: int = 5, provider: str | None = None, **kwargs: Any) -> ToolResult:
        del kwargs
        q = str(query or "").strip()
        if not q:
            return ToolResult.failure("query must not be empty", code="INVALID_ARGUMENTS")
        try:
            n = max(1, min(MAX_RESULTS, int(max_results)))
        except (TypeError, ValueError):
            return ToolResult.failure("max_results must be an integer", code="INVALID_ARGUMENTS")

        prov = (provider or os.environ.get("WEBSEARCH_PROVIDER") or "duckduckgo").strip().lower()
        api_key = os.environ.get("WEBSEARCH_API_KEY", "").strip()

        try:
            if prov == "duckduckgo":
                results = _search_duckduckgo(q, max_results=n)
            elif prov == "serper":
                if not api_key:
                    return ToolResult.failure("WEBSEARCH_API_KEY required for serper", code="MISSING_API_KEY")
                results = _search_serper(q, api_key=api_key, max_results=n)
            elif prov == "tavily":
                if not api_key:
                    return ToolResult.failure("WEBSEARCH_API_KEY required for tavily", code="MISSING_API_KEY")
                results = _search_tavily(q, api_key=api_key, max_results=n)
            else:
                return ToolResult.failure(f"Unknown provider: {prov}", code="INVALID_ARGUMENTS")
        except urllib.error.HTTPError as e:
            return ToolResult.failure(f"HTTP {e.code}: {e.reason}", code="HTTP_ERROR")
        except urllib.error.URLError as e:
            return ToolResult.failure(str(e.reason), code="NETWORK_ERROR")
        except Exception as e:
            return ToolResult.failure(f"{type(e).__name__}: {e}", code="TOOL_EXCEPTION")

        return ToolResult.success({"query": q, "provider": prov, "count": len(results), "results": results})


TOOL = WebSearchTool
