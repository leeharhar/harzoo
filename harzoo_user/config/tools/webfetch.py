"""Web fetch tool implementation."""


from __future__ import annotations

import ipaddress
import re
import socket
import urllib.error
import urllib.request
from email.message import Message
from typing import Any
from urllib.parse import urlparse

from harzoo.agent.kernel.tool import Tool, ToolResult

TOOL_VERSION = "2026-06-29"

ENCODING_POLICY = "header_charset_then_utf8_replace"
MAX_RAW_BYTES = 500_000
MAX_TEXT_CHARS = 50_000
MAX_REDIRECTS = 5

# SSRF 防护：禁止访问内网/本地/metadata 等私有地址段（IPv4 + IPv6）。
_BLOCKED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)
# 字面 hostname 黑名单，补充 IP 段规则覆盖不到的特殊主机名。
_BLOCKED_HOSTNAMES = frozenset({"localhost", "metadata.google.internal"})


class FetchUrlBlockedError(ValueError):
    """Raised when a URL targets a blocked host or resolves to a private address."""


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(ip in network for network in _BLOCKED_NETWORKS)


def _validate_fetch_url(url: str) -> None:
    """拒绝非法 scheme、内网主机，以及 DNS 解析到私有地址的目标（防 SSRF / DNS rebinding）。"""

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise FetchUrlBlockedError(f"URL scheme not allowed: {parsed.scheme or '(missing)'}")
    host = parsed.hostname
    if not host:
        raise FetchUrlBlockedError("URL must include a hostname")

    host_lower = host.lower().rstrip(".")
    if host_lower in _BLOCKED_HOSTNAMES or host_lower.endswith(".localhost"):
        raise FetchUrlBlockedError(f"Blocked hostname: {host}")

    try:
        ip = ipaddress.ip_address(host_lower.strip("[]"))
    except ValueError:
        ip = None
    if ip is not None:
        if _is_blocked_ip(ip):
            raise FetchUrlBlockedError(f"Blocked IP address: {host}")
        return

    # 域名先解析再校验：任一 A/AAAA 记录落在内网段即拒绝。
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addrinfos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise urllib.error.URLError(f"Could not resolve hostname {host}: {e}") from e
    for _, _, _, _, sockaddr in addrinfos:
        resolved_ip = ipaddress.ip_address(sockaddr[0])
        if _is_blocked_ip(resolved_ip):
            raise FetchUrlBlockedError(f"Blocked IP address for hostname {host}: {sockaddr[0]}")


class _SSRFRedirectHandler(urllib.request.HTTPRedirectHandler):
    """限制重定向次数，并在每次跳转前重新校验目标 URL，防止 302 绕过内网拦截。"""

    def __init__(self, *, max_redirects: int) -> None:
        super().__init__()
        self.max_redirects = max_redirects
        self.redirect_count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        self.redirect_count += 1
        if self.redirect_count > self.max_redirects:
            raise urllib.error.HTTPError(
                req.full_url,
                code,
                f"Exceeded maximum redirects ({self.max_redirects})",
                headers,
                fp,
            )
        _validate_fetch_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _build_opener() -> tuple[urllib.request.OpenerDirector, _SSRFRedirectHandler]:
    redirect_handler = _SSRFRedirectHandler(max_redirects=MAX_REDIRECTS)
    opener = urllib.request.build_opener(redirect_handler)
    return opener, redirect_handler


def _parse_charset(content_type: str) -> str:
    message = Message()
    message["content-type"] = content_type
    params = message.get_params()[1:]
    for key, value in params:
        if key == "charset" and value:
            return value.strip("'\"")
    return "utf-8"


def _truncate_text(value: str, *, limit: int = MAX_TEXT_CHARS) -> tuple[str, bool]:
    """返回 (文本, 是否截断)，便于 Agent 区分完整内容与裁剪结果。"""

    if len(value) <= limit:
        return value, False
    return value[:limit], True


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

        url = str(url).strip()
        if not url:
            return ToolResult.failure("url must not be empty", code="INVALID_ARGUMENTS")
        try:
            timeout = int(timeout)
        except (TypeError, ValueError):
            return ToolResult.failure("timeout must be an integer", code="INVALID_ARGUMENTS")
        timeout = max(5, min(120, timeout))

        if not url.lower().startswith(("http://", "https://")):
            return ToolResult.failure("URL must start with http:// or https://", code="INVALID_ARGUMENTS")
        # 请求前校验一次；重定向链上由 _SSRFRedirectHandler 再次校验。
        try:
            _validate_fetch_url(url)
        except FetchUrlBlockedError as e:
            return ToolResult.failure(str(e), code="URL_BLOCKED")

        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml,text/plain",
                },
            )
            opener, redirect_handler = _build_opener()
            with opener.open(req, timeout=timeout) as resp:
                content_type = resp.headers.get("Content-Type", "")

                # 限制：最多读取 500KB，防止超大页面占满上下文。
                raw = resp.read(MAX_RAW_BYTES + 1)
                raw_truncated = len(raw) > MAX_RAW_BYTES
                if raw_truncated:
                    raw = raw[:MAX_RAW_BYTES]

                charset = _parse_charset(content_type)
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
                text_chars = len(text)
                text, text_truncated = _truncate_text(text)
                return ToolResult.success(
                    {
                        "text": text or "(no content)",
                        "url": url,
                        "content_type": content_type,
                        "encoding_policy": ENCODING_POLICY,
                        "encoding_used": encoding_used,
                        "had_replacements": had_replacements,
                        # 截断透明化：告知 Agent 原始响应与最终文本是否被裁剪。
                        "raw_bytes_read": len(raw),
                        "raw_truncated": raw_truncated,
                        "text_chars": text_chars,
                        "text_truncated": text_truncated,
                        "redirect_count": redirect_handler.redirect_count,
                        "max_redirects": MAX_REDIRECTS,
                    }
                )
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and "Exceeded maximum redirects" in str(e.reason):
                return ToolResult.failure(str(e.reason), code="TOO_MANY_REDIRECTS")
            return ToolResult.failure(f"HTTP {e.code} - {e.reason}", code="HTTP_ERROR")
        except urllib.error.URLError as e:
            return ToolResult.failure(f"{e.reason}", code="NETWORK_ERROR")
        except FetchUrlBlockedError as e:
            return ToolResult.failure(str(e), code="URL_BLOCKED")
        except Exception as e:
            return ToolResult.failure(f"{type(e).__name__}: {e}", code="TOOL_EXCEPTION")


TOOL = WebFetchTool
