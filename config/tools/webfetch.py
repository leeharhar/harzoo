"""Web fetch tool implementation."""


from __future__ import annotations

import re
import urllib.error
import urllib.request
from typing import Any

from harzoo.agent.kernel.tool import Tool, ToolResult

TOOL_VERSION = "2026-05-22"

ENCODING_POLICY = "header_charset_then_utf8_replace"


def _extract_text(html: str) -> str:
    """轻量提取策略：通过正则剥离常见标签，追求可读文本而非完整 DOM 还原。"""

    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    html = re.sub(r"<(nav|footer|aside)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<br[^>]*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<p[^>]*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<li[^>]*>", "\n- ", html, flags=re.IGNORECASE)
    html = re.sub(r"<h[1-6][^>]*>", "\n\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<[^>]+>", "", html)
    html = re.sub(r"[ \t]+", " ", html)
    html = re.sub(r"\n\s*\n+", "\n\n", html)
    return html.strip()


class WebFetchTool(Tool):
    """从网页抓取可读文本，适合检索资料，不适合需要浏览器交互的场景。"""

    name = "WebFetch"
    description = "Fetch and extract text content from a URL. Returns readable text from web pages."
    parameters = {
        "properties": {
            "url": {"type": "string", "description": "URL to fetch (http:// or https://)"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 30, max 120)"},
        },
        "required": ["url"],
    }

    def execute(self, url: str, timeout: int = 30, **kwargs: Any) -> ToolResult:
        """抓取 URL 并提取可读文本，仅支持 http/https。"""

        if not str(url).strip():
            return ToolResult.failure("url must not be empty", code="INVALID_ARGUMENTS")
        try:
            timeout = int(timeout)
        except (TypeError, ValueError):
            return ToolResult.failure("timeout must be an integer", code="INVALID_ARGUMENTS")
        timeout = max(5, min(120, timeout))

        # 特殊限制：timeout 被夹紧在 5~120 秒，避免极端值拖垮会话体验。
        if not url.lower().startswith(("http://", "https://")):
            return ToolResult.failure("URL must start with http:// or https://", code="INVALID_ARGUMENTS")
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml,text/plain",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content_type = resp.headers.get("Content-Type", "")

                # 限制：最多读取 500KB，防止超大页面占满上下文。
                raw = resp.read(500_000)
                charset = "utf-8"
                if "charset=" in content_type:
                    charset = content_type.split("charset=")[-1].split(";")[0].strip()
                encoding_used = charset
                had_replacements = False
                try:
                    html = raw.decode(charset)
                except (UnicodeDecodeError, LookupError):
                    html = raw.decode("utf-8", errors="replace")
                    encoding_used = "utf-8 (replace)"
                    had_replacements = True
                normalized_url = url.lower().split("?", 1)[0]
                is_html = "text/html" in content_type.lower() or normalized_url.endswith((".html", ".htm"))
                if is_html:
                    text = _extract_text(html)
                else:
                    text = html
                return ToolResult.success(
                    {

                        # 限制：最终返回文本最多 50_000 字符，超出会被截断。
                        "text": text[:50_000] or "(no content)",
                        "url": url,
                        "content_type": content_type,
                        "encoding_policy": ENCODING_POLICY,
                        "encoding_used": encoding_used,
                        "had_replacements": had_replacements,
                    }
                )
        except urllib.error.HTTPError as e:
            return ToolResult.failure(f"HTTP {e.code} - {e.reason}", code="HTTP_ERROR")
        except urllib.error.URLError as e:
            return ToolResult.failure(f"{e.reason}", code="NETWORK_ERROR")
        except Exception as e:
            return ToolResult.failure(f"{type(e).__name__}: {e}", code="TOOL_EXCEPTION")


TOOL = WebFetchTool
