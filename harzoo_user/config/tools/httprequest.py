"""HttpRequest — general HTTP client with SSRF protection."""


from __future__ import annotations

import base64
import ipaddress
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from email.message import Message
from typing import Any
from urllib.parse import urlparse

from harzoo.agent.kernel.tool import Tool, ToolResult

TOOL_VERSION = "2026-06-29"

MAX_BODY_BYTES = 500_000
MAX_RESPONSE_CHARS = 50_000
MAX_REDIRECTS = 5

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
_BLOCKED_HOSTNAMES = frozenset({"localhost", "metadata.google.internal"})


class UrlBlockedError(ValueError):
    pass


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(ip in network for network in _BLOCKED_NETWORKS)


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UrlBlockedError(f"URL scheme not allowed: {parsed.scheme or '(missing)'}")
    host = parsed.hostname
    if not host:
        raise UrlBlockedError("URL must include a hostname")
    host_lower = host.lower().rstrip(".")
    if host_lower in _BLOCKED_HOSTNAMES or host_lower.endswith(".localhost"):
        raise UrlBlockedError(f"Blocked hostname: {host}")
    try:
        ip = ipaddress.ip_address(host_lower.strip("[]"))
    except ValueError:
        ip = None
    if ip is not None:
        if _is_blocked_ip(ip):
            raise UrlBlockedError(f"Blocked IP address: {host}")
        return
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addrinfos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise urllib.error.URLError(f"Could not resolve hostname {host}: {e}") from e
    for _, _, _, _, sockaddr in addrinfos:
        if _is_blocked_ip(ipaddress.ip_address(sockaddr[0])):
            raise UrlBlockedError(f"Blocked IP for hostname {host}: {sockaddr[0]}")


class _SSRFRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, *, max_redirects: int) -> None:
        super().__init__()
        self.max_redirects = max_redirects
        self.redirect_count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        self.redirect_count += 1
        if self.redirect_count > self.max_redirects:
            raise urllib.error.HTTPError(req.full_url, code, f"Exceeded maximum redirects ({self.max_redirects})", headers, fp)
        _validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _parse_charset(content_type: str) -> str:
    message = Message()
    message["content-type"] = content_type
    for key, value in message.get_params()[1:]:
        if key == "charset" and value:
            return value.strip("'\"")
    return "utf-8"


class HttpRequestTool(Tool):
    """Send HTTP requests (GET/POST/PUT/PATCH/DELETE). SSRF-protected; no private network access."""

    name = "HttpRequest"
    description = (
        "Send HTTP requests with method, headers, query params, and JSON or raw body. "
        "Returns status, headers, and response body (text or base64 for binary)."
    )
    parameters = {
        "properties": {
            "url": {"type": "string", "description": "Request URL (http/https)"},
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"],
                "default": "GET",
            },
            "headers": {"type": "object", "description": "Request headers as key-value pairs"},
            "query": {"type": "object", "description": "Query string parameters"},
            "json_body": {"type": "object", "description": "JSON request body (sets Content-Type)"},
            "body": {"type": "string", "description": "Raw request body string"},
            "timeout": {"type": "integer", "description": "Timeout seconds (5-120)", "default": 30},
        },
        "required": ["url"],
    }

    def execute(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        body: str | None = None,
        timeout: int = 30,
        **kwargs: Any,
    ) -> ToolResult:
        del kwargs
        raw_url = str(url or "").strip()
        if not raw_url:
            return ToolResult.failure("url must not be empty", code="INVALID_ARGUMENTS")
        if query:
            sep = "&" if "?" in raw_url else "?"
            raw_url = raw_url + sep + urllib.parse.urlencode({str(k): str(v) for k, v in query.items()})
        try:
            timeout = max(5, min(120, int(timeout)))
        except (TypeError, ValueError):
            return ToolResult.failure("timeout must be an integer", code="INVALID_ARGUMENTS")
        m = str(method or "GET").strip().upper()
        if m not in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"):
            return ToolResult.failure(f"Unsupported method: {method}", code="INVALID_ARGUMENTS")

        try:
            _validate_url(raw_url)
        except UrlBlockedError as e:
            return ToolResult.failure(str(e), code="URL_BLOCKED")

        req_headers = {str(k): str(v) for k, v in (headers or {}).items()}
        data: bytes | None = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
        elif body is not None:
            data = str(body).encode("utf-8")

        if data and len(data) > MAX_BODY_BYTES:
            return ToolResult.failure(f"Request body exceeds {MAX_BODY_BYTES} bytes", code="INVALID_ARGUMENTS")

        try:
            req = urllib.request.Request(raw_url, data=data, headers=req_headers, method=m)
            redirect_handler = _SSRFRedirectHandler(max_redirects=MAX_REDIRECTS)
            opener = urllib.request.build_opener(redirect_handler)
            with opener.open(req, timeout=timeout) as resp:
                raw = resp.read(MAX_BODY_BYTES + 1)
                truncated = len(raw) > MAX_BODY_BYTES
                if truncated:
                    raw = raw[:MAX_BODY_BYTES]
                content_type = resp.headers.get("Content-Type", "")
                charset = _parse_charset(content_type)
                is_text = any(t in content_type.lower() for t in ("json", "text", "xml", "javascript", "html"))
                if is_text:
                    try:
                        text = raw.decode(charset)
                    except (UnicodeDecodeError, LookupError):
                        text = raw.decode("utf-8", errors="replace")
                    if len(text) > MAX_RESPONSE_CHARS:
                        text = text[:MAX_RESPONSE_CHARS]
                        truncated = True
                    body_out: str | dict[str, Any] = text
                    if "json" in content_type.lower():
                        try:
                            body_out = json.loads(text)
                        except json.JSONDecodeError:
                            pass
                else:
                    body_out = base64.b64encode(raw).decode("ascii")
                return ToolResult.success(
                    {
                        "url": raw_url,
                        "method": m,
                        "status_code": resp.status,
                        "headers": dict(resp.headers.items()),
                        "content_type": content_type,
                        "body": body_out,
                        "body_encoding": "text" if is_text else "base64",
                        "truncated": truncated,
                        "redirect_count": redirect_handler.redirect_count,
                    }
                )
        except urllib.error.HTTPError as e:
            err_body = e.read(MAX_BODY_BYTES).decode("utf-8", errors="replace")[:MAX_RESPONSE_CHARS]
            return ToolResult.failure(
                f"HTTP {e.code}: {e.reason}",
                code="HTTP_ERROR",
                data={"status_code": e.code, "body": err_body},
            )
        except urllib.error.URLError as e:
            return ToolResult.failure(str(e.reason), code="NETWORK_ERROR")
        except UrlBlockedError as e:
            return ToolResult.failure(str(e), code="URL_BLOCKED")
        except Exception as e:
            return ToolResult.failure(f"{type(e).__name__}: {e}", code="TOOL_EXCEPTION")


TOOL = HttpRequestTool
