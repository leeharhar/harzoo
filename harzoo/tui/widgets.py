"""聊天、工具与状态相关的 Textual 组件。"""

from __future__ import annotations

import time
from typing import Literal

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.events import Click, Key
from textual.message import Message
from textual.widgets import Button, Markdown, Static
from textual.widgets import TextArea

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _summarize_tool_arguments(arguments_text: str, max_len: int = 144) -> str:
    single_line_arguments = arguments_text.replace("\n", " ").strip()
    return single_line_arguments if len(single_line_arguments) <= max_len else single_line_arguments[: max_len - 1] + "…"


class CopyableMessage(Container):
    """聊天消息：可选中 + Ctrl+C；双击复制整条 `_copy_text`。"""

    def __init__(self, copy_text: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._copy_text = copy_text

    def get_selection(self, selection) -> tuple[str, str] | None:
        """Container 默认可选文本是 CSS 类名；改为返回消息正文。"""
        if not self._copy_text:
            return None
        return selection.extract(self._copy_text), "\n"

    async def _on_click(self, event: Click) -> None:
        if event.chain == 2 and self in event.widget.ancestors_with_self:
            if text := self._copy_text.strip():
                self.app.copy_to_clipboard(text)
                self.app.clear_selection()
                self.notify("已复制", timeout=1.5)
                event.stop()
                return
        await super()._on_click(event)


class ChatInputTextArea(TextArea):
    """聊天输入框：Enter 发送，Shift+Enter 换行。"""

    class Submitted(Message):
        """用户在此组件提交输入时发出。"""

        bubble = True

        def __init__(self, text_area: "ChatInputTextArea") -> None:
            self.text_area = text_area
            super().__init__()

    def on_key(self, event: Key) -> None:
        key = str(event.key).lower()
        if key not in {"enter", "shift+enter"}:
            return
        event.stop()
        event.prevent_default()
        if key == "shift+enter":
            self.insert("\n")
            return
        self.post_message(self.Submitted(self))


class BannerMessage(Container):
    DEFAULT_CSS = """
    BannerMessage {
        width: 100%;
        height: auto;
        padding: 1 2;
        margin: 0 0 1 0;
        background: $primary 15%;
        text-align: center;
    }
    """

    def __init__(self, text: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._text = text

    def compose(self) -> ComposeResult:
        yield Static(self._text, markup=False)


class UserMessage(CopyableMessage):
    DEFAULT_CSS = """
    UserMessage {
        width: 100%;
        height: auto;
        background: $surface;
        padding: 1 2 1 2;
        margin: 0 0 1 0;
        color: limegreen;
    }"""

    def compose(self) -> ComposeResult:
        yield Static(self._copy_text, markup=False)


class AssistantMessage(CopyableMessage):
    DEFAULT_CSS = """
    AssistantMessage {
        width: 100%;
        height: auto;
        margin: 1 0 0 0;
    }
    /* Textual's MarkdownFence defaults to black 10% in dark mode, which blends into the chat. */
    AssistantMessage MarkdownFence {
        background: $boost;
        border: none;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Markdown(self._copy_text)


class ToolCallRow(Vertical):
    DEFAULT_CSS = """
    ToolCallRow {
        width: 100%;
        height: auto;
        margin: 0 2 1 1;
    }
    ToolCallRow .tool-summary {
        height: 1;
        align: left middle;
    }
    ToolCallRow .tool-status {
        width: 3;
        height: 1;
        min-height: 1;
        max-height: 1;
        text-align: center;
        content-align: center middle;
    }
    ToolCallRow .tool-status.status-running { color: $warning; }
    ToolCallRow .tool-status.status-ok { color: $success; }
    ToolCallRow .tool-status.status-error { color: $error; }
    ToolCallRow .tool-name {
        width: auto;
        height: 1;
        text-style: bold;
        color: $text-muted;
        content-align: left middle;
    }
    ToolCallRow .tool-sep {
        width: auto;
        height: 1;
        color: $text-muted 75%;
        content-align: center middle;
    }
    ToolCallRow .tool-args {
        width: 1fr;
        height: 1;
        color: $text-muted;
        overflow: hidden;
        content-align: left middle;
    }
    ToolCallRow Button.tool-expand {
        width: 3;
        height: 1;
        min-height: 1;
        max-height: 1;
        min-width: 3;
        max-width: 3;
        border: none;
        background: transparent;
        padding: 0;
        margin: 0;
        color: $text-muted;
        text-align: center;
        content-align: center middle;
    }
    ToolCallRow Button.tool-expand:hover { background: $boost; }
    ToolCallRow Button.tool-expand:disabled {
        color: $text-muted;
        background: transparent;
    }
    ToolCallRow .tool-result-body {
        display: none;
        height: auto;
        margin-top: 1;
        padding: 2;
        background: $boost;
        color: $text-muted;
    }
    ToolCallRow .tool-result-body.is-expanded { display: block; }
    """

    def __init__(self, tool_call_id: str, tool_name: str, tool_args: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.tool_call_id = tool_call_id
        self._tool_display_name = tool_name
        self._tool_arguments_text = tool_args
        self._tool_result_text = ""
        self._is_result_expanded = False

    def compose(self) -> ComposeResult:
        with Horizontal(classes="tool-summary"):
            yield Static("◐", classes="tool-status status-running", markup=False)
            yield Static(self._tool_display_name, classes="tool-name", markup=False)
            yield Static(" · ", classes="tool-sep", markup=False)
            yield Static(
                _summarize_tool_arguments(self._tool_arguments_text),
                classes="tool-args",
                markup=False,
            )
            yield Button("▶", classes="tool-expand", disabled=True, variant="default", compact=True, flat=True)
        yield Static("", classes="tool-result-body", markup=False)

    def mark_completed(self, is_success: bool, tool_result: object) -> None:
        status_widget = self.query_one(".tool-status", Static)
        status_widget.remove_class("status-running")
        status_widget.add_class("status-ok" if is_success else "status-error")
        status_widget.update("✓" if is_success else "✗")
        self._tool_result_text = str(tool_result)
        self.query_one(".tool-result-body", Static).update(self._tool_result_text)
        toggle_button = self.query_one(".tool-expand", Button)
        toggle_button.disabled = False
        toggle_button.tooltip = "展开工具输出"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        toggle_button = self.query_one(".tool-expand", Button)
        result_body_widget = self.query_one(".tool-result-body", Static)
        if event.button is not toggle_button or toggle_button.disabled:
            return
        self._is_result_expanded = not self._is_result_expanded
        if self._is_result_expanded:
            result_body_widget.add_class("is-expanded")
            toggle_button.label = "▼"
            toggle_button.tooltip = "收起工具输出"
        else:
            result_body_widget.remove_class("is-expanded")
            toggle_button.label = "▶"
            toggle_button.tooltip = "展开工具输出"


class AgentActivityLine(Static):
    DEFAULT_CSS = """
    AgentActivityLine {
        height: 1;
        margin: 1 0 0 1;
        color: #b8a020;
    }
    """

    def __init__(
        self,
        mode: Literal["thinking", "tools"],
        *,
        model_name: str = "",
        **kwargs,
    ) -> None:
        super().__init__("", markup=False, **kwargs)
        self._activity_mode = mode
        self._model_display_name = (model_name or "model").strip() or "model"
        self._started_at_monotonic = time.monotonic()
        self._spinner_frame_index = 0

    def on_mount(self) -> None:
        self._refresh_line()
        self.set_interval(0.1, self._refresh_line)

    def _refresh_line(self) -> None:
        self._spinner_frame_index = (self._spinner_frame_index + 1) % len(_SPINNER_FRAMES)
        spinner_char = _SPINNER_FRAMES[self._spinner_frame_index]
        elapsed_seconds = time.monotonic() - self._started_at_monotonic
        status_label = f"{self._model_display_name} thinking" if self._activity_mode == "thinking" else "tool running"
        self.update(f" {status_label}  {spinner_char}  {elapsed_seconds:.1f}s")


class ErrorMessage(CopyableMessage):
    DEFAULT_CSS = """
    ErrorMessage {
        width: 100%;
        height: auto;
        margin: 1 0;
        padding: 1;
        background: $error 15%;
        border-left: heavy $error;
    }
    ErrorMessage Static {
        color: $error;
        width: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(self._copy_text, markup=False)
