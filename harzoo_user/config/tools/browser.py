"""Browser Tool — CloakBrowser 人类节拍、双模式观测、可选 xhr 采集。

分区: 1 常量 | 2 会话 | 2b iframe | 3 安全 | 4 观测 | 4b 定位 | 4c xhr 采集 | 5 人类节奏 | 6 节拍执行 | 7 生命周期 | 8 Tool

Agent 编排人的动作；导航与反爬节奏内化。page_text 阅读，snapshot+click 交互。
goto/click 可选 capture=true 采集当次动作触发的 fetch/xhr JSON（如画布 K 线接口）。
需用户配合的登录/验证码等：见 Tool description，停自动化并通知用户。
"""

from __future__ import annotations

import ipaddress
import random
import socket
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator
from urllib.parse import urlparse

from harzoo.agent.kernel.tool import Context, Tool, ToolResult

# === 1. 常量 ===

TOOL_VERSION = "2026-07-23-access-gate-description"
DEFAULT_TIMEOUT_MS = 30_000
_DEFAULT_EXPECT_PAGE_MS = 3_000
_NAV_WAIT_UNTIL = "domcontentloaded"
_SNAPSHOT_SCOPES = frozenset({"body", "dialog", "top_dialog"})
_DIALOG_SELECTOR = '[role="dialog"], [role="alertdialog"]'
_HARD_CAPTURE_MAX_ENTRIES = 100
_MAX_PAGE_TEXT_CHARS = 50_000
_MAX_WAIT_S = 90.0
_PAGE_TEXT_SHORT_HINT_CHARS = 120
_CAPTURE_RESOURCE_TYPES = frozenset({"fetch", "xhr"})
_SKIP_CAPTURE_URL_FRAGMENTS = (
    "category=web_behavior",
    "/upload/web?",
)
_SKIP_CAPTURE_CT_PREFIX = ("image/", "video/", "audio/", "font/")
_SKIP_CAPTURE_CT = frozenset(
    {"application/octet-stream", "application/wasm", "application/pdf", "application/zip"}
)

_LAUNCH = dict(
    headless=False,
    humanize=True,
    human_preset="careful",
    human_config={
        "idle_between_actions": True,
        "idle_between_duration": [0.4, 1.2],
        "typing_delay": 90,
        "mistype_chance": 0.02,
    },
    args=[
        "--fingerprint=42069",
        "--fingerprint-storage-quota=5000",
    ],
)

_ACTIONS = (
    "goto",
    "snapshot",
    "page_text",
    "click",
    "type",
    "press",
    "scroll",
    "back",
    "wait",
    "list_pages",
    "switch_page",
    "sync_active",
    "close_page",
    "list_frames",
    "close",
)

_BLOCKED_NETS = (
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
_BLOCKED_HOSTS = frozenset({"localhost", "metadata.google.internal"})

# === 2. 会话（模块级单例；tool_loader 保证同进程不重复 exec 本文件）===

_SESSION: dict[str, Any] = {"ctx": None, "page": None}


def _is_page_alive(page: Any | None) -> bool:
    if page is None:
        return False
    try:
        return not page.is_closed()
    except Exception:
        return False


def _teardown_session() -> None:
    """关窗并停止 Playwright driver（CloakBrowser ctx.close → pw.stop）。"""
    ctx = _SESSION.get("ctx")
    if ctx is not None:
        try:
            ctx.close()
        except Exception:
            pass
    _SESSION["ctx"] = None
    _SESSION["page"] = None


def _browser_context() -> Any | None:
    return _SESSION.get("ctx")


def _safe_title(page: Any) -> str:
    try:
        return page.title()
    except Exception:
        return ""


_FOCUS_DETECT_JS = "() => document.visibilityState === 'visible' && document.hasFocus()"
_VISIBLE_JS = "() => document.visibilityState === 'visible'"


@dataclass(frozen=True)
class PageCatalog:
    """多 tab 清单与焦点：agent 工作 tab + 浏览器前台 tab（只读检测，不自动切）。"""

    @staticmethod
    def all() -> list[Any]:
        ctx = _browser_context()
        if ctx is None:
            return []
        try:
            return [p for p in ctx.pages if _is_page_alive(p)]
        except Exception:
            return []

    @staticmethod
    def count() -> int:
        return len(PageCatalog.all())

    @staticmethod
    def agent() -> Any | None:
        page = _SESSION.get("page")
        return page if _is_page_alive(page) else None

    @staticmethod
    def index(page: Any) -> int:
        try:
            return PageCatalog.all().index(page)
        except ValueError:
            return -1

    @staticmethod
    def agent_index() -> int:
        agent = PageCatalog.agent()
        return PageCatalog.index(agent) if agent is not None else -1

    @staticmethod
    def _eval_bool(page: Any, script: str) -> bool:
        try:
            return bool(page.evaluate(script))
        except Exception:
            return False

    @classmethod
    def detect_focused_index(cls) -> int | None:
        pages = cls.all()
        if not pages:
            return None
        if len(pages) == 1:
            return 0
        focused = [i for i, p in enumerate(pages) if cls._eval_bool(p, _FOCUS_DETECT_JS)]
        if len(focused) == 1:
            return focused[0]
        visible = [i for i, p in enumerate(pages) if cls._eval_bool(p, _VISIBLE_JS)]
        if len(visible) == 1:
            return visible[0]
        if focused:
            return focused[0]
        if visible:
            return visible[0]
        return None

    @classmethod
    def tab_summary(cls) -> dict[str, Any]:
        pages = cls.all()
        agent_idx = cls.agent_index()
        if len(pages) <= 1:
            focused_idx: int | None = 0 if pages else None
        else:
            focused_idx = cls.detect_focused_index()
        return {
            "agent_page_index": agent_idx,
            "focused_page_index": focused_idx,
            "page_count": len(pages),
        }

    @classmethod
    def list_info(cls) -> list[dict[str, Any]]:
        agent = PageCatalog.agent()
        summary = cls.tab_summary()
        focused_idx = summary["focused_page_index"]
        items: list[dict[str, Any]] = []
        for index, page in enumerate(cls.all()):
            items.append(
                {
                    "index": index,
                    "url": page.url,
                    "title": _safe_title(page),
                    "agent": page is agent,
                    "focused": focused_idx is not None and index == focused_idx,
                }
            )
        return items

    @classmethod
    def drift_hint(cls) -> str | None:
        summary = cls.tab_summary()
        agent_idx = summary["agent_page_index"]
        focused_idx = summary["focused_page_index"]
        page_count = summary["page_count"]
        if page_count <= 1:
            return None
        if focused_idx is not None and agent_idx >= 0 and agent_idx != focused_idx:
            return (
                f"focused tab ({focused_idx}) differs from agent tab ({agent_idx}) — "
                "switch_page(page_index=N) or sync_active"
            )
        if focused_idx is not None and agent_idx < 0:
            return f"sync_active to align agent tab with focused tab ({focused_idx})"
        return "multi-tab — operate agent tab only; list_pages for tab map"

    @staticmethod
    def resolve(index: int) -> Any | ToolResult:
        pages = PageCatalog.all()
        if index < 0 or index >= len(pages):
            return ToolResult.failure(
                f"page_index out of range: {index}",
                code="INVALID_ARGUMENTS",
                data={"pages": PageCatalog.list_info(), **PageCatalog.tab_summary()},
            )
        return pages[index]

    @staticmethod
    def activate(page: Any, timeout_ms: int) -> None:
        page.bring_to_front()
        page.set_default_timeout(timeout_ms)
        _SESSION["page"] = page

    @classmethod
    def sync_focused(cls, timeout_ms: int) -> ToolResult:
        focused_idx = cls.detect_focused_index()
        if focused_idx is None:
            return ToolResult.failure(
                "could not detect focused tab",
                code="NOT_FOUND",
                data={"pages": cls.list_info(), **cls.tab_summary()},
            )
        target = cls.resolve(focused_idx)
        if isinstance(target, ToolResult):
            return target
        cls.activate(target, timeout_ms)
        return ToolResult.success(
            {
                "synced_to": focused_idx,
                "url": target.url,
                "title": _safe_title(target),
                "pages": cls.list_info(),
                **cls.tab_summary(),
                **cls.context_fields(target),
            }
        )

    @staticmethod
    def context_fields(page: Any) -> dict[str, int]:
        return {"page_index": PageCatalog.index(page), "page_count": PageCatalog.count()}


def _ensure_active_page() -> None:
    """Active page 失效时切到其他 tab；全无 tab 时才 teardown。"""
    if _SESSION.get("ctx") is None and _SESSION.get("page") is None:
        return
    if _is_page_alive(_SESSION.get("page")):
        return
    pages = PageCatalog.all()
    if pages:
        _SESSION["page"] = pages[-1]
        return
    _teardown_session()


def _ensure_closed_if_stale() -> None:
    _ensure_active_page()


def _page(ctx: Context, timeout_ms: int) -> Any | ToolResult:
    """获取可复用的 Playwright page；不存在则启动 CloakBrowser 持久化上下文。"""
    _ensure_closed_if_stale()
    page = _SESSION.get("page")
    if _is_page_alive(page):
        page.set_default_timeout(timeout_ms)
        return page

    bctx = _browser_context()
    if bctx is not None:
        try:
            page = bctx.new_page()
            page.set_default_timeout(timeout_ms)
            _SESSION["page"] = page
            return page
        except Exception:
            _teardown_session()

    try:
        from cloakbrowser import launch_persistent_context
    except ImportError as e:
        return ToolResult.failure(
            f"pip install cloakbrowser ({e})",
            code="MISSING_DEPENDENCY",
            data={"next_actions": ["pip install -e '.[browser]'"]},
        )

    profile = ctx.config_paths.data_root / "browser" / "profile"
    profile.mkdir(parents=True, exist_ok=True)
    try:
        bctx = launch_persistent_context(str(profile), **_LAUNCH)
        page = bctx.new_page()
        page.set_default_timeout(timeout_ms)
        _SESSION["ctx"], _SESSION["page"] = bctx, page
        return page
    except Exception as e:
        _teardown_session()
        return ToolResult.failure(f"launch failed: {e}", code="BROWSER_LAUNCH_FAILED")


# === 2b. iframe 只读 ===

_IFRAME_READ_HINT = (
    "iframes detected — list_frames, then page_text(frame_index=N) to read; "
    "click/type stay on main frame"
)


@dataclass(frozen=True)
class FrameCatalog:
    """当前 page 内 frame 枚举与只读访问；无 session state。"""

    page: Any

    def all(self) -> list[Any]:
        try:
            return list(self.page.frames)
        except Exception:
            return []

    @property
    def count(self) -> int:
        return len(self.all())

    def has_embedded(self) -> bool:
        return self.count > 1

    def is_main(self, frame: Any) -> bool:
        try:
            return frame == self.page.main_frame
        except Exception:
            return False

    def list_info(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for index, frame in enumerate(self.all()):
            url, name = "", ""
            try:
                url = frame.url
            except Exception:
                pass
            try:
                name = frame.name or ""
            except Exception:
                pass
            items.append(
                {"index": index, "url": url, "name": name, "is_main": self.is_main(frame)}
            )
        return items

    def resolve(self, index: int) -> Any | ToolResult:
        frames = self.all()
        if index < 0 or index >= len(frames):
            return ToolResult.failure(
                f"frame_index out of range: {index}",
                code="INVALID_ARGUMENTS",
                data={"frames": self.list_info()},
            )
        return frames[index]

    def read_hint(self) -> str | None:
        return _IFRAME_READ_HINT if self.has_embedded() else None

    def body_locator(self, index: int | None = None) -> Any | ToolResult:
        if index is None:
            return self.page.locator("body")
        frame = self.resolve(index)
        if isinstance(frame, ToolResult):
            return frame
        return frame.locator("body")

    def refs_allowed(self, index: int | None) -> bool:
        if index is None:
            return True
        frame = self.resolve(index)
        if isinstance(frame, ToolResult):
            return False
        return self.is_main(frame)

    @staticmethod
    def parse_index(kw: dict[str, Any], *, required: bool = False) -> int | None | ToolResult:
        raw = kw.get("frame_index")
        if raw is None:
            if required:
                return ToolResult.failure("frame_index required", code="INVALID_ARGUMENTS")
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return ToolResult.failure("frame_index must be int", code="INVALID_ARGUMENTS")

    @staticmethod
    def guard_interact(kw: dict[str, Any], role: str) -> ToolResult | None:
        if kw.get("frame_index") is None:
            return None
        return ToolResult.failure(
            f"{role} is main frame only — omit frame_index; "
            "use page_text(frame_index=N) or snapshot(frame_index=N) to read iframes",
            code="INVALID_ARGUMENTS",
        )


def _frames(page: Any) -> FrameCatalog:
    return FrameCatalog(page)


# === 3. 安全 ===


def _blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(ip in n for n in _BLOCKED_NETS)


def _validate_url(url: str) -> None:
    """校验 URL 协议与目标地址，阻止 SSRF（含 DNS 解析后复查）。"""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise ValueError(f"scheme not allowed: {p.scheme or '(missing)'}")
    host = (p.hostname or "").lower().rstrip(".")
    if not host or host in _BLOCKED_HOSTS or host.endswith(".localhost"):
        raise ValueError(f"blocked hostname: {host or '(missing)'}")
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
        if _blocked_ip(ip):
            raise ValueError(f"blocked IP: {host}")
        return
    except ValueError as e:
        if "blocked" in str(e).lower():
            raise
    port = p.port or (443 if p.scheme == "https" else 80)
    for _, _, _, _, sa in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
        if _blocked_ip(ipaddress.ip_address(sa[0])):
            raise ValueError(f"blocked IP for {host}: {sa[0]}")


# === 4. 观测 ===

_ARIA_AI: bool | None = None


@dataclass(frozen=True)
class Observation:
    text: str
    source: str
    refs_available: bool
    chars: int
    truncated: bool = False


def _probe_aria_ai(page: Any) -> bool:
    """Playwright>=1.59 aria_snapshot(mode=ai) 与 aria-ref 是否可用。"""
    global _ARIA_AI
    if _ARIA_AI is not None:
        return _ARIA_AI
    try:
        snap = page.locator("body").aria_snapshot(mode="ai")
        _ARIA_AI = "[ref=e" in (snap or "")
    except TypeError:
        _ARIA_AI = False
    return _ARIA_AI


def _observe(
    page: Any,
    *,
    cap: int | None = None,
    scope: str = "body",
    frame_index: int | None = None,
) -> Observation | ToolResult:
    """aria_snapshot(mode=ai)；无 ref 支持则失败。iframe 只读时 refs_available=false。"""
    if scope not in _SNAPSHOT_SCOPES:
        return ToolResult.failure(
            f"scope must be one of {sorted(_SNAPSHOT_SCOPES)}",
            code="INVALID_ARGUMENTS",
        )
    if not _probe_aria_ai(page):
        return ToolResult.failure(
            "snapshot requires playwright>=1.59 aria_snapshot(mode=ai)",
            code="UNSUPPORTED",
        )
    catalog = _frames(page)
    if frame_index is not None:
        if scope != "body":
            return ToolResult.failure(
                "frame_index with scope supports body only",
                code="INVALID_ARGUMENTS",
            )
        root = catalog.body_locator(frame_index)
        if isinstance(root, ToolResult):
            return root
        source = "aria_ai_frame"
        refs_available = catalog.refs_allowed(frame_index)
    elif scope == "body":
        root = page.locator("body")
        source = "aria_ai"
        refs_available = True
    else:
        dialogs = page.locator(_DIALOG_SELECTOR)
        try:
            count = dialogs.count()
        except Exception:
            count = 0
        if count == 0:
            return ToolResult.failure(
                "no dialog on page",
                code="NOT_FOUND",
                data={"hint": "wait(seconds) then snapshot again"},
            )
        root = dialogs.last if scope == "top_dialog" else dialogs.first
        source = "aria_ai_dialog"
        refs_available = True
    raw = (root.aria_snapshot(mode="ai") or "").strip()
    truncated = cap is not None and len(raw) > cap
    text = (raw[:cap] + "\n...[truncated]") if truncated else raw
    return Observation(
        text=text,
        source=source,
        refs_available=refs_available,
        chars=len(text),
        truncated=truncated,
    )


def _snapshot_scope(page: Any) -> str:
    """有 modal 时优先 top_dialog，否则 body。"""
    if _count_dialogs(page) > 0:
        return "top_dialog"
    return "body"


def _count_dialogs(page: Any) -> int:
    try:
        return page.locator(_DIALOG_SELECTOR).count()
    except Exception:
        return 0


def _page_text_short_hint(char_count: int) -> str | None:
    if char_count >= _PAGE_TEXT_SHORT_HINT_CHARS:
        return None
    return (
        "observation short — if still loading, wait then page_text; "
        "if login/captcha/verification, stop and tell the user (see Browser tool description)"
    )


def _page_text(page: Any, *, frame_index: int | None = None) -> tuple[str, bool] | ToolResult:
    """可见纯文本，供内容提取；frame_index 指定 iframe（只读）。"""
    root = _frames(page).body_locator(frame_index)
    if isinstance(root, ToolResult):
        return root
    try:
        text = (root.inner_text() or "").strip()
    except Exception as e:
        return ToolResult.failure(f"page_text failed: {e}", code="ACTION_FAILED")
    truncated = len(text) > _MAX_PAGE_TEXT_CHARS
    if truncated:
        text = text[:_MAX_PAGE_TEXT_CHARS] + "\n...[truncated]"
    return text, truncated


# === 4b. 定位 ===


@dataclass(frozen=True)
class Target:
    locator: Any
    label: str


def _normalize_ref(raw: Any) -> str:
    s = str(raw or "").strip()
    if s.startswith("ref="):
        s = s[4:].strip()
    return s if s.startswith("e") and s[1:].isdigit() else ""


def _resolve_ref(page: Any, kw: dict[str, Any], *, role: str) -> Target | ToolResult:
    """click/type 仅接受 snapshot 中的 ref。"""
    ref = _normalize_ref(kw.get("ref"))
    if not ref:
        return ToolResult.failure(f"{role} needs ref from snapshot", code="INVALID_ARGUMENTS")
    if not _probe_aria_ai(page):
        return ToolResult.failure(
            "ref requires playwright>=1.59 aria-ref support",
            code="UNSUPPORTED",
        )
    return Target(page.locator(f"aria-ref={ref}"), ref)


def _ref_failure(action: str, exc: Exception) -> ToolResult:
    return ToolResult.failure(
        f"{action} ref failed: {exc}. Page may have changed — snapshot again.",
        code="REF_STALE",
    )


def _is_timeout_error(exc: Exception) -> bool:
    return type(exc).__name__ == "TimeoutError" or "timeout" in str(exc).lower()


def _page_ids(pages: list[Any]) -> set[int]:
    return {id(p) for p in pages}


def _compute_page_delta(page: Any, *, url_before: str, pages_before: set[int]) -> dict[str, Any]:
    pages_after = PageCatalog.all()
    opened = [i for i, p in enumerate(pages_after) if id(p) not in pages_before]
    return {
        "opened": opened,
        "url_changed": page.url != url_before,
        "url_before": url_before,
        "url_after": page.url,
    }


def _click_hint(page_delta: dict[str, Any], dialogs_visible: int) -> str | None:
    opened = page_delta.get("opened") or []
    if opened:
        idx = opened[0]
        suffix = f" (+{len(opened) - 1} more)" if len(opened) > 1 else ""
        return f"{len(opened)} new tab(s) — list_pages then switch_page(page_index={idx}){suffix}"
    if dialogs_visible:
        return "dialog visible — snapshot again"
    return None


def _click_with_page_watch(page: Any, click_fn: Callable[[], None]) -> None:
    """执行 click，并在窗口内等待可能打开的新 tab。"""
    ctx = page.context
    try:
        with ctx.expect_page(timeout=_DEFAULT_EXPECT_PAGE_MS):
            click_fn()
    except Exception as e:
        if _is_timeout_error(e):
            return
        raise


# === 4c. xhr 采集（goto/click + capture=true）===


def _parse_capture(raw: Any) -> tuple[bool, int | None]:
    """false=关；true=全量；int=最多保留 N 条。"""
    if raw is None or raw is False:
        return False, None
    if raw is True:
        return True, None
    if isinstance(raw, int):
        if raw <= 0:
            return False, None
        return True, min(raw, _HARD_CAPTURE_MAX_ENTRIES)
    raise ValueError("capture must be boolean or integer max entry count (1–100)")


def _response_headers(response: Any) -> dict[str, str]:
    headers = response.headers
    return headers if isinstance(headers, dict) else {}


def _capture_content_type(headers: dict[str, str]) -> str:
    raw = headers.get("content-type") or headers.get("Content-Type") or ""
    return raw.split(";", 1)[0].strip().lower()


def _network_response_capturable(response: Any) -> bool:
    if response.request.resource_type not in _CAPTURE_RESOURCE_TYPES:
        return False
    if response.status >= 400:
        return False
    url = response.url
    if any(fragment in url for fragment in _SKIP_CAPTURE_URL_FRAGMENTS):
        return False
    content_type = _capture_content_type(_response_headers(response))
    if content_type in _SKIP_CAPTURE_CT:
        return False
    if content_type.startswith(_SKIP_CAPTURE_CT_PREFIX):
        return False
    return True


def _read_capture_bodies(pending: list[Any], *, limit: int | None = None) -> list[dict[str, Any]]:
    items = pending if limit is None else pending[-limit:]
    captures: list[dict[str, Any]] = []
    for response in items:
        try:
            body = response.body().decode("utf-8", errors="replace")
            content_type = _capture_content_type(_response_headers(response))
            if not body:
                continue
            captures.append(
                {
                    "url": response.url,
                    "status": response.status,
                    "content_type": content_type or None,
                    "resource_type": response.request.resource_type,
                    "body": body,
                }
            )
        except Exception:
            continue
    return captures


@contextmanager
def _listen_action(page: Any, *, enabled: bool) -> Iterator[list[Any]]:
    if not enabled:
        yield []
        return
    pending: list[Any] = []

    def on_response(response: Any) -> None:
        try:
            if _network_response_capturable(response):
                pending.append(response)
        except Exception:
            return

    page.on("response", on_response)
    try:
        yield pending
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass


# === 5. 人类节奏 ===


@dataclass(frozen=True)
class BeatProfile:
    pre: str  # nav | aim | micro | none
    post: str  # read | settle | micro | none
    post_range: tuple[float, float]
    scroll_after: bool = False


@dataclass(frozen=True)
class HumanRhythmConfig:
    pre_interact: tuple[float, float] = (0.8, 2.0)
    pre_micro: tuple[float, float] = (0.3, 0.8)
    interaction_gap: tuple[float, float] = (1.5, 4.0)
    nav_gap: tuple[float, float] = (1.0, 3.0)
    field_gap: tuple[float, float] = (0.5, 2.0)
    goto_cooldown: float = 30.0
    actions_per_min: int = 8
    gotos_per_min: int = 3
    rate_window: float = 60.0


BEAT_PROFILES: dict[str, BeatProfile] = {
    "goto": BeatProfile("nav", "read", (3.0, 6.0), scroll_after=True),
    "click": BeatProfile("aim", "settle", (3.0, 8.0), scroll_after=True),
    "back": BeatProfile("nav", "read", (1.5, 4.0), scroll_after=True),
    "type": BeatProfile("aim", "micro", (0.3, 1.0)),
    "press": BeatProfile("aim", "micro", (0.5, 1.5)),
    "scroll": BeatProfile("none", "micro", (0.2, 0.8)),
    "snapshot": BeatProfile("micro", "none", (0.0, 0.0)),
    "page_text": BeatProfile("micro", "none", (0.0, 0.0)),
    "wait": BeatProfile("none", "none", (0.0, 0.0)),
    "list_pages": BeatProfile("micro", "none", (0.0, 0.0)),
    "switch_page": BeatProfile("micro", "none", (0.0, 0.0)),
    "sync_active": BeatProfile("micro", "none", (0.0, 0.0)),
    "close_page": BeatProfile("micro", "none", (0.0, 0.0)),
    "list_frames": BeatProfile("micro", "none", (0.0, 0.0)),
}

_NAV_ACTIONS = frozenset({"goto", "back"})
_INTERACTION_ACTIONS = frozenset(
    {"click", "type", "press", "scroll", "snapshot", "page_text", "wait"}
)
_BEAT_ACTIONS = _NAV_ACTIONS | _INTERACTION_ACTIONS


class HumanRhythm:
    def __init__(self, cfg: HumanRhythmConfig | None = None) -> None:
        self.cfg = cfg or HumanRhythmConfig()
        self._last_ts = 0.0
        self._domains: dict[str, dict[str, Any]] = {}

    def reset(self) -> None:
        self._last_ts = 0.0
        self._domains = {}

    @staticmethod
    def host(url: str) -> str:
        return (urlparse(url).hostname or "").lower().rstrip(".")

    @classmethod
    def page_host(cls, page: Any) -> str:
        return cls.host(page.url)

    def before(
        self,
        action: str,
        page: Any,
        profile: BeatProfile,
        *,
        url: str | None = None,
    ) -> dict[str, float]:
        host = self.host(url) if url else self.page_host(page)
        meta: dict[str, float] = {}
        if domain_s := self._enforce_rate_limit(host, action):
            meta["paced_domain_s"] = round(domain_s, 2)
        if gap_s := self._enforce_min_gap(action):
            meta["paced_gap_s"] = round(gap_s, 2)
        if profile.pre == "aim":
            meta["pre_interact_s"] = round(self._simulate_aim(page), 2)
        elif profile.pre == "micro":
            meta["pre_micro_s"] = round(self._sleep_range(*self.cfg.pre_micro), 2)
        return meta

    def after(self, page: Any, profile: BeatProfile) -> dict[str, float]:
        meta: dict[str, float] = {}
        if profile.post in ("read", "settle"):
            meta[f"{profile.post}_s"] = round(
                self._simulate_reading(page, *profile.post_range, scroll=profile.scroll_after),
                2,
            )
        elif profile.post == "micro" and profile.post_range[1] > 0:
            meta["micro_s"] = round(self._sleep_range(*profile.post_range), 2)
        return meta

    def field_pause(self) -> dict[str, float]:
        return {"field_gap_s": round(self._sleep_range(*self.cfg.field_gap), 2)}

    def mark(self, action: str, host: str) -> None:
        now = time.monotonic()
        self._last_ts = now
        if not host:
            return
        state = self._domain_state(host)
        if action == "goto":
            state["gotos"].append(now)
            state["last_goto"] = now
        elif action in _INTERACTION_ACTIONS:
            state["acts"].append(now)

    def _domain_state(self, host: str) -> dict[str, Any]:
        if host not in self._domains:
            self._domains[host] = {"gotos": deque(), "acts": deque(), "last_goto": 0.0}
        return self._domains[host]

    @staticmethod
    def _sleep_range(lo: float, hi: float) -> float:
        if hi <= 0:
            return 0.0
        s = random.uniform(lo, hi)
        time.sleep(s)
        return s

    def _prune_window(self, q: deque, now: float) -> None:
        while q and q[0] < now - self.cfg.rate_window:
            q.popleft()

    def _sleep_for_rate_slot(self, q: deque, limit: int, now: float) -> float:
        slept = 0.0
        while len(q) >= limit:
            wait = q[0] + self.cfg.rate_window - now
            if wait > 0:
                time.sleep(wait)
                slept += wait
                now = time.monotonic()
            self._prune_window(q, now)
        return slept

    def _enforce_rate_limit(self, host: str, action: str) -> float:
        if not host:
            return 0.0
        cfg = self.cfg
        state = self._domain_state(host)
        now = time.monotonic()
        self._prune_window(state["gotos"], now)
        self._prune_window(state["acts"], now)
        slept = 0.0
        if action == "goto":
            since = now - state["last_goto"]
            if state["last_goto"] and since < cfg.goto_cooldown:
                time.sleep(cfg.goto_cooldown - since)
                slept += cfg.goto_cooldown - since
                now = time.monotonic()
            slept += self._sleep_for_rate_slot(state["gotos"], cfg.gotos_per_min, now)
        if action in _INTERACTION_ACTIONS:
            slept += self._sleep_for_rate_slot(state["acts"], cfg.actions_per_min, now)
        return slept

    def _enforce_min_gap(self, action: str) -> float:
        if action not in _BEAT_ACTIONS:
            return 0.0
        cfg = self.cfg
        lo, hi = cfg.nav_gap if action in _NAV_ACTIONS else cfg.interaction_gap
        if not self._last_ts:
            return 0.0
        need = random.uniform(lo, hi)
        elapsed = time.monotonic() - self._last_ts
        if elapsed >= need:
            return 0.0
        time.sleep(need - elapsed)
        return need - elapsed

    def _simulate_reading(
        self, page: Any, lo: float, hi: float, *, scroll: bool
    ) -> float:
        total = self._sleep_range(lo, hi)
        if scroll:
            for _ in range(random.randint(1, 2)):
                page.mouse.wheel(0, random.randint(150, 600))
                total += self._sleep_range(0.3, 1.0)
        return total

    def _simulate_aim(self, page: Any) -> float:
        page.mouse.wheel(0, random.randint(80, 280))
        return self._sleep_range(*self.cfg.pre_interact)


_RHYTHM = HumanRhythm()


# === 6. 节拍执行 ===


@dataclass
class BeatResult:
    pacing: dict[str, float]
    captures: list[dict[str, Any]] | None = None

    def apply_to(self, result: dict[str, Any]) -> None:
        result["pacing"] = self.pacing
        if not self.captures:
            return
        result["captures"] = self.captures
        result["capture_count"] = len(self.captures)


def _human_beat(
    page: Any,
    *,
    action: str,
    host: str,
    do: Callable[[], None],
    profile: BeatProfile,
    capture_override: Any = None,
    url: str | None = None,
) -> BeatResult:
    """一次人类节拍：节奏前置 → do → 节奏后置；可选 xhr 采集。"""
    try:
        capture_on, capture_limit = _parse_capture(capture_override)
    except ValueError as e:
        raise ValueError(str(e)) from e

    pacing: dict[str, float] = {}
    with _listen_action(page, enabled=capture_on) as pending:
        pacing.update(_RHYTHM.before(action, page, profile, url=url))
        do()
        pacing.update(_RHYTHM.after(page, profile))

    _RHYTHM.mark(action, host)
    captures = _read_capture_bodies(pending, limit=capture_limit) if capture_on else None
    return BeatResult(pacing=pacing, captures=captures)


# === 7. 生命周期 ===


def _close() -> None:
    """关闭浏览器窗口并停止 Playwright driver，重置人类节奏。"""
    _teardown_session()
    _RHYTHM.reset()


# === 8. Tool ===


def _browser_action_variant(action: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "const": action},
            **properties,
        },
        "required": ["action", *required],
        "additionalProperties": False,
    }


def _browser_tool_parameters() -> dict[str, Any]:
    ref_prop = {
        "ref": {
            "type": "string",
            "description": "Element ref from snapshot [ref=eN], e.g. e12.",
        }
    }
    frame_prop = {
        "frame_index": {
            "type": "integer",
            "description": "Optional iframe index from list_frames (read-only).",
        }
    }
    page_index_prop = {
        "page_index": {
            "type": "integer",
            "description": "Tab index from list_pages (0-based).",
        }
    }
    capture_prop = {
        "capture": {
            "description": (
                "goto/click only: record fetch/xhr JSON during this action (default false). "
                "Use true when chart/K-line data lives in API responses (e.g. after clicking 日K/周K). "
                "Integer = keep at most N recent entries."
            ),
            "oneOf": [
                {"type": "boolean"},
                {"type": "integer", "minimum": 1, "maximum": _HARD_CAPTURE_MAX_ENTRIES},
            ],
        }
    }
    return {
        "oneOf": [
            _browser_action_variant(
                "goto",
                {"url": {"type": "string", "description": "http(s) URL."}, **capture_prop},
                ["url"],
            ),
            _browser_action_variant("back", {}, []),
            _browser_action_variant("page_text", frame_prop, []),
            _browser_action_variant("snapshot", frame_prop, []),
            _browser_action_variant("click", {**ref_prop, **capture_prop}, ["ref"]),
            _browser_action_variant(
                "type",
                {
                    **ref_prop,
                    "value": {"type": "string", "description": "Text to type."},
                },
                ["ref", "value"],
            ),
            _browser_action_variant(
                "press",
                {"key": {"type": "string", "description": "Key name, e.g. Enter."}},
                ["key"],
            ),
            _browser_action_variant("scroll", {}, []),
            _browser_action_variant(
                "wait",
                {
                    "seconds": {
                        "type": "number",
                        "description": f"Seconds to wait (max {_MAX_WAIT_S:g}).",
                    }
                },
                ["seconds"],
            ),
            _browser_action_variant("list_pages", {}, []),
            _browser_action_variant("switch_page", page_index_prop, ["page_index"]),
            _browser_action_variant("sync_active", {}, []),
            _browser_action_variant("close_page", page_index_prop, ["page_index"]),
            _browser_action_variant("list_frames", {}, []),
            _browser_action_variant("close", {}, []),
        ]
    }


class BrowserTool(Tool):
    name = "Browser"
    description = (
        "Human-paced visible Chromium: one action per call. Read with page_text; interact via snapshot → click/type by ref. "
        "K-line/chart JSON: click(ref, capture=true) or goto(url, capture=true). After goto, use page_text; "
        "if content looks still loading, wait then page_text again. "
        "If the page requires the user (login, OTP/SMS, captcha, or human verification): stop all browser automation—"
        "no retries, no typing secrets, no bypass clicks. Tell the user to finish in the open browser window, "
        "then sync_active and page_text to confirm before continuing. In a subtask, stop collecting and state clearly "
        "what the user must do; do not fabricate data. Follow hints in tool results. Pacing is automatic."
    )
    parameters = _browser_tool_parameters()

    _ACT_HANDLERS: dict[str, str] = {
        "goto": "_act_goto",
        "snapshot": "_act_snapshot",
        "page_text": "_act_page_text",
        "click": "_act_click",
        "type": "_act_type",
        "press": "_act_press",
        "scroll": "_act_scroll",
        "back": "_act_back",
        "wait": "_act_wait",
        "list_pages": "_act_list_pages",
        "switch_page": "_act_switch_page",
        "sync_active": "_act_sync_active",
        "close_page": "_act_close_page",
        "list_frames": "_act_list_frames",
    }

    def execute(self, action: str, ctx: Context | None = None, **kw: Any) -> ToolResult:
        if ctx is None:
            return ToolResult.failure("missing context", code="MISSING_CONTEXT")

        action = str(action).strip().lower()
        if action not in _ACTIONS:
            return ToolResult.failure(f"unknown action: {action}", code="INVALID_ARGUMENTS")

        timeout = DEFAULT_TIMEOUT_MS

        if action == "close":
            _close()
            return ToolResult.success({"closed": True})

        page = _page(ctx, timeout)
        if isinstance(page, ToolResult):
            return page

        try:
            return self._dispatch(page, action, kw)
        except ValueError as e:
            msg = str(e)
            code = "URL_BLOCKED" if "blocked" in msg.lower() or "scheme not allowed" in msg else "INVALID_ARGUMENTS"
            return ToolResult.failure(msg, code=code)
        except Exception as e:
            return ToolResult.failure(f"{type(e).__name__}: {e}", code="ACTION_FAILED")

    def _dispatch(self, page: Any, action: str, kw: dict[str, Any]) -> ToolResult:
        handler_name = self._ACT_HANDLERS.get(action)
        if not handler_name:
            return ToolResult.failure(f"unhandled: {action}", code="TOOL_EXCEPTION")
        return getattr(self, handler_name)(page, kw)

    def _run_beat(
        self,
        page: Any,
        action: str,
        do: Callable[[], None],
        *,
        host: str | None = None,
        url: str | None = None,
        capture_override: Any = None,
        include_title: bool = False,
        **fields: Any,
    ) -> ToolResult:
        try:
            beat = _human_beat(
                page,
                action=action,
                host=host or _RHYTHM.page_host(page),
                profile=BEAT_PROFILES[action],
                url=url,
                capture_override=capture_override,
                do=do,
            )
        except ValueError as e:
            return ToolResult.failure(str(e), code="INVALID_ARGUMENTS")
        result: dict[str, Any] = {"url": page.url, **PageCatalog.context_fields(page), **fields}
        if include_title:
            result["title"] = _safe_title(page)
        beat.apply_to(result)
        return ToolResult.success(result)

    def _act_goto(self, page: Any, kw: dict[str, Any]) -> ToolResult:
        url = str(kw.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            return ToolResult.failure("goto needs http(s) url", code="INVALID_ARGUMENTS")
        _validate_url(url)
        return self._run_beat(
            page,
            "goto",
            lambda: page.goto(url, wait_until=_NAV_WAIT_UNTIL),
            host=_RHYTHM.host(url),
            url=url,
            capture_override=kw.get("capture"),
            include_title=True,
        )

    def _act_snapshot(self, page: Any, kw: dict[str, Any]) -> ToolResult:
        scope = _snapshot_scope(page)
        frame_index = FrameCatalog.parse_index(kw)
        if isinstance(frame_index, ToolResult):
            return frame_index
        obs_holder: list[Observation] = []
        fail_holder: list[ToolResult] = []
        catalog = _frames(page)

        def do() -> None:
            result = _observe(page, scope=scope, frame_index=frame_index)
            if isinstance(result, ToolResult):
                fail_holder.append(result)
                raise RuntimeError("snapshot failed")
            obs_holder.append(result)

        try:
            beat = _human_beat(
                page,
                action="snapshot",
                host=_RHYTHM.page_host(page),
                profile=BEAT_PROFILES["snapshot"],
                do=do,
            )
        except RuntimeError:
            if fail_holder:
                return fail_holder[0]
            return ToolResult.failure("snapshot failed", code="ACTION_FAILED")
        obs = obs_holder[0]
        result_fields: dict[str, Any] = {
            "title": _safe_title(page),
            "scope": scope,
            "frame_count": catalog.count,
            "observation": obs.text,
            "observation_source": obs.source,
            "observation_chars": obs.chars,
            "refs_available": obs.refs_available,
        }
        if frame_index is not None:
            result_fields["frame_index"] = frame_index
            if not obs.refs_available:
                result_fields["frame_readonly"] = True
        elif hint := catalog.read_hint():
            result_fields["hint"] = hint
        return self._run_beat_result(page, beat, **result_fields)

    def _act_page_text(self, page: Any, kw: dict[str, Any]) -> ToolResult:
        frame_index = FrameCatalog.parse_index(kw)
        if isinstance(frame_index, ToolResult):
            return frame_index
        observation = ""
        truncated = False
        fail: ToolResult | None = None

        def do() -> None:
            nonlocal observation, truncated, fail
            result = _page_text(page, frame_index=frame_index)
            if isinstance(result, ToolResult):
                fail = result
                raise RuntimeError("page_text failed")
            observation, truncated = result

        try:
            beat = _human_beat(
                page,
                action="page_text",
                host=_RHYTHM.page_host(page),
                profile=BEAT_PROFILES["page_text"],
                do=do,
            )
        except RuntimeError:
            if fail is not None:
                return fail
            return ToolResult.failure("page_text failed", code="ACTION_FAILED")
        fields: dict[str, Any] = {
            "title": _safe_title(page),
            "frame_count": _frames(page).count,
            "observation": observation,
            "observation_source": "inner_text",
            "observation_chars": len(observation),
            "observation_truncated": truncated,
        }
        if frame_index is not None:
            fields["frame_index"] = frame_index
        if hint := _page_text_short_hint(len(observation)):
            fields["hint"] = hint
        return self._run_beat_result(page, beat, **fields)

    def _act_click(self, page: Any, kw: dict[str, Any]) -> ToolResult:
        if err := FrameCatalog.guard_interact(kw, "click"):
            return err
        target = _resolve_ref(page, kw, role="click")
        if isinstance(target, ToolResult):
            return target
        url_before = page.url
        pages_before = _page_ids(PageCatalog.all())
        try:
            result = self._run_beat(
                page,
                "click",
                lambda: _click_with_page_watch(
                    page,
                    lambda: target.locator.click(),
                ),
                capture_override=kw.get("capture"),
                clicked=target.label,
            )
        except Exception as e:
            return _ref_failure("click", e)
        if result.ok and isinstance(result.data, dict):
            page_delta = _compute_page_delta(
                page, url_before=url_before, pages_before=pages_before
            )
            dialogs_visible = _count_dialogs(page)
            result.data["page_delta"] = page_delta
            result.data["dialogs_visible"] = dialogs_visible
            hint = _click_hint(page_delta, dialogs_visible)
            if hint:
                result.data["hint"] = hint
        return result

    def _act_type(self, page: Any, kw: dict[str, Any]) -> ToolResult:
        if err := FrameCatalog.guard_interact(kw, "type"):
            return err
        if kw.get("value") is None:
            return ToolResult.failure("type needs value (content to type)", code="INVALID_ARGUMENTS")
        target = _resolve_ref(page, kw, role="type")
        if isinstance(target, ToolResult):
            return target
        content = str(kw["value"])
        field_pacing: dict[str, float] = {}

        def do() -> None:
            target.locator.click()
            field_pacing.update(_RHYTHM.field_pause())
            target.locator.type(content)

        try:
            beat = _human_beat(
                page,
                action="type",
                host=_RHYTHM.page_host(page),
                profile=BEAT_PROFILES["type"],
                do=do,
            )
        except Exception as e:
            return _ref_failure("type", e)
        beat.pacing.update(field_pacing)
        return self._run_beat_result(page, beat, typed=target.label, value=content)

    def _act_press(self, page: Any, kw: dict[str, Any]) -> ToolResult:
        key = str(kw.get("key") or "").strip()
        if not key:
            return ToolResult.failure("press needs key", code="INVALID_ARGUMENTS")
        return self._run_beat(
            page,
            "press",
            lambda: page.keyboard.press(key),
            pressed=key,
        )

    def _act_scroll(self, page: Any, kw: dict[str, Any]) -> ToolResult:
        dy = 300
        return self._run_beat(
            page,
            "scroll",
            lambda: page.mouse.wheel(0, dy),
            scrolled=dy,
        )

    def _act_back(self, page: Any, kw: dict[str, Any]) -> ToolResult:
        return self._run_beat(
            page,
            "back",
            lambda: page.go_back(wait_until=_NAV_WAIT_UNTIL),
            include_title=True,
        )

    def _act_wait(self, page: Any, kw: dict[str, Any]) -> ToolResult:
        s = max(0.0, min(_MAX_WAIT_S, float(kw.get("seconds") or 1.0)))
        return self._run_beat(
            page,
            "wait",
            lambda: time.sleep(s),
            waited=s,
        )

    def _act_list_pages(self, page: Any, kw: dict[str, Any]) -> ToolResult:
        result: dict[str, Any] = {
            "pages": PageCatalog.list_info(),
            **PageCatalog.tab_summary(),
            **PageCatalog.context_fields(page),
        }
        if hint := PageCatalog.drift_hint():
            result["hint"] = hint
        return ToolResult.success(result)

    def _act_list_frames(self, page: Any, kw: dict[str, Any]) -> ToolResult:
        catalog = _frames(page)
        result: dict[str, Any] = {
            "frames": catalog.list_info(),
            "frame_count": catalog.count,
            **PageCatalog.context_fields(page),
        }
        if hint := catalog.read_hint():
            result["hint"] = hint
        return ToolResult.success(result)

    def _act_sync_active(self, page: Any, kw: dict[str, Any]) -> ToolResult:
        return PageCatalog.sync_focused(DEFAULT_TIMEOUT_MS)

    def _act_switch_page(self, page: Any, kw: dict[str, Any]) -> ToolResult:
        if kw.get("page_index") is None:
            return ToolResult.failure(
                "switch_page needs page_index",
                code="INVALID_ARGUMENTS",
                data={"pages": PageCatalog.list_info(), **PageCatalog.tab_summary()},
            )
        try:
            index = int(kw["page_index"])
        except (TypeError, ValueError):
            return ToolResult.failure(
                "page_index must be int",
                code="INVALID_ARGUMENTS",
                data={"pages": PageCatalog.list_info(), **PageCatalog.tab_summary()},
            )
        target = PageCatalog.resolve(index)
        if isinstance(target, ToolResult):
            return target
        PageCatalog.activate(target, DEFAULT_TIMEOUT_MS)
        result: dict[str, Any] = {
            "switched_to": index,
            "url": target.url,
            "title": _safe_title(target),
            "pages": PageCatalog.list_info(),
            **PageCatalog.tab_summary(),
            **PageCatalog.context_fields(target),
        }
        return ToolResult.success(result)

    def _act_close_page(self, page: Any, kw: dict[str, Any]) -> ToolResult:
        if kw.get("page_index") is None:
            return ToolResult.failure(
                "close_page needs page_index",
                code="INVALID_ARGUMENTS",
                data={"pages": PageCatalog.list_info(), **PageCatalog.tab_summary()},
            )
        try:
            index = int(kw["page_index"])
        except (TypeError, ValueError):
            return ToolResult.failure(
                "page_index must be int",
                code="INVALID_ARGUMENTS",
                data={"pages": PageCatalog.list_info(), **PageCatalog.tab_summary()},
            )
        target = PageCatalog.resolve(index)
        if isinstance(target, ToolResult):
            return target
        was_agent = target is PageCatalog.agent()
        target.close()
        remaining = PageCatalog.all()
        if was_agent:
            _SESSION["page"] = remaining[-1] if remaining else None
            if not remaining:
                _SESSION["ctx"] = None
        agent = PageCatalog.agent()
        ctx_fields = (
            PageCatalog.context_fields(agent)
            if agent is not None
            else {"page_index": -1, "page_count": PageCatalog.count()}
        )
        return ToolResult.success(
            {
                "closed": index,
                "pages": PageCatalog.list_info(),
                **PageCatalog.tab_summary(),
                **ctx_fields,
            }
        )

    def _run_beat_result(self, page: Any, beat: BeatResult, **fields: Any) -> ToolResult:
        result: dict[str, Any] = {"url": page.url, **PageCatalog.context_fields(page), **fields}
        beat.apply_to(result)
        return ToolResult.success(result)


TOOL = BrowserTool
