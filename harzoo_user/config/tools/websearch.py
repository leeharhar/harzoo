"""WebSearch — minimal web search via DuckDuckGo Lite. Zero extra dependencies."""


from __future__ import annotations

import re
import urllib.parse
import urllib.request
from typing import Any

from harzoo.agent.kernel.tool import Tool, ToolResult

TOOL_VERSION = "2026-07-24"

_DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"
_TIMEOUT = 15
_MAX_RESULTS = 10
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"


def _parse_results(html: str, limit: int) -> list[dict[str, str]]:
    """Parse DuckDuckGo Lite HTML for search results (snippets + URLs)."""
    results: list[dict[str, str]] = []
    # Each result row has a class="result-snippet" for the snippet, preceded by a link.
    # DDG Lite structure: <a rel="nofollow" href="...">title</a> ... <td class="result-snippet">...</td>
    # We extract pairs: (url, title) from <a> tags, snippets from class="result-snippet".
    snippet_pattern = re.compile(
        r'<a[^>]*href="([^"]+)"[^>]*rel="nofollow"[^>]*>(.*?)</a>.*?'
        r'class="result-snippet">(.*?)</td>',
        re.DOTALL,
    )
    for url, title, snippet in snippet_pattern.findall(html):
        if len(results) >= limit:
            break
        title = re.sub(r"<[^>]+>", "", title).strip()
        snippet = re.sub(r"<[^>]+>", "", snippet).strip()
        if title:
            results.append({"title": title, "url": url, "snippet": snippet})
    return results


class WebSearchTool(Tool):
    """Search the web via DuckDuckGo Lite. No API key or registration needed."""

    name = "WebSearch"
    description = "Search the web for a query and return relevant snippets with URLs."
    parameters = {
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {
                "type": "integer",
                "description": "Max results (1-10)",
                "default": 5,
            },
        },
        "required": ["query"],
    }

    def execute(self, query: str, max_results: int = 5, **kwargs: Any) -> ToolResult:
        del kwargs
        q = str(query or "").strip()
        if not q:
            return ToolResult.failure("query must not be empty", code="INVALID_ARGUMENTS")
        try:
            limit = max(1, min(_MAX_RESULTS, int(max_results)))
        except (TypeError, ValueError):
            limit = 5

        data = urllib.parse.urlencode({"q": q}).encode()
        req = urllib.request.Request(
            _DDG_LITE_URL,
            data=data,
            headers={
                "User-Agent": _USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            return ToolResult.failure(f"search request failed: {e}", code="NETWORK_ERROR")

        results = _parse_results(html, limit)
        if not results:
            return ToolResult.success(
                {"query": q, "results": [], "count": 0, "note": "no results found"}
            )
        return ToolResult.success(
            {"query": q, "results": results, "count": len(results)}
        )


TOOL = WebSearchTool