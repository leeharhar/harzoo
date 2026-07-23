"""聊天、工具与状态相关的 Textual 组件。"""

from __future__ import annotations

import time
from typing import Literal

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.events import Click, Key
from textual.message import Message
from textual.widgets import Button, Markdown, Static, TextArea

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _normalize_tool_arguments_for_display(arguments_text: str) -> str:
    """压成单行摘要：去掉 \\r 等控制字符，避免 Static 单行渲染提前截断。"""
    text = arguments_text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    text = text.replace("\u2028", " ").replace("\u2029", " ")
    text = "".join(" " if ord(ch) < 32 else ch for ch in text)
    return " ".join(text.split())


def _summarize_tool_arguments(arguments_text: str, max_len: int = 144) -> str:
    single_line_arguments = _normalize_tool_arguments_for_display(arguments_text)
    return single_line_arguments if len(single_line_arguments) <= max_len else single_line_arguments[: max_len - 1] + "…"


def _strip_subtask_live_status_prefix(label: str) -> str:
    """去掉 subagent live 行前缀 ◐/✓/✗，详情由右侧 Static 展示。"""
    text = label.strip()
    if not text:
        return ""
    if text[0] in "◐✓✗":
        return text[1:].lstrip()
    return text


def _subtask_entry_replaces_running_tool_line(previous: str, new: str) -> bool:
    """子工具完成行与上一行 ◐ 行除状态符外相同则替换，避免 timeline 重复。"""
    if not previous.startswith("◐") or not new or new[0] not in "✓✗":
        return False
    return previous[1:] == new[1:]


def _tool_call_summary_copy_text(tool_name: str, tool_args: str) -> str:
    """工具摘要块 copy_text：工具名 + 完整参数。"""
    name = tool_name.strip()
    args = tool_args.strip()
    if not name and not args:
        return ""
    return f"{name} · {args}" if args else name


class CopyBlock(Container):
    """双击复制本块 `copy_text` 全文。"""

    DEFAULT_CSS = """
    CopyBlock {
        width: 100%;
        height: auto;
    }
    """

    def __init__(self, copy_text: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._copy_text = copy_text

    def set_copy_text(self, text: str) -> None:
        self._copy_text = text

    async def _on_click(self, event: Click) -> None:
        if event.chain == 2 and self in event.widget.ancestors_with_self:
            text = self._copy_text.strip()
            if text:
                self.app.copy_to_clipboard(text)
                self.app.clear_selection()
                self.notify("已复制", timeout=1.5)
                event.stop()
                return
        await super()._on_click(event)


class SystemMessage(CopyBlock):
    """系统反馈：命令结果与提示。"""

    DEFAULT_CSS = """
    SystemMessage {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        padding: 0 2;
    }
    SystemMessage Static {
        width: 100%;
        height: auto;
        color: $text-muted;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(self._copy_text, markup=False)


class ChatInputTextArea(TextArea):
    """聊天输入框：Enter 发送，Shift+Enter 换行。"""

    DEFAULT_CSS = """
    ChatInputTextArea {
        width: 1fr;
        height: auto;
        min-height: 1;
        max-height: 8;
        padding: 0 1;
        background: $panel;
        border: solid $border-blurred;
        scrollbar-size-vertical: 0;
        scrollbar-size-horizontal: 0;
    }
    ChatInputTextArea:focus {
        border: solid $border;
    }
    """

    class Submitted(Message):
        """用户在此组件提交输入时发出。"""

        bubble = True

        def __init__(self, text_area: "ChatInputTextArea") -> None:
            self.text_area = text_area
            super().__init__()

    class AtInserted(Message):
        """用户按下 @ 并插入字符后发出。"""

        bubble = True

        def __init__(self, text_area: "ChatInputTextArea") -> None:
            self.text_area = text_area
            super().__init__()

    class CommandPaletteRequested(Message):
        """输入框为空时按下 / 并插入字符后发出。"""

        bubble = True

        def __init__(self, text_area: "ChatInputTextArea") -> None:
            self.text_area = text_area
            super().__init__()

    def on_key(self, event: Key) -> None:
        key = str(event.key).lower()
        if key == "at":
            event.stop()
            event.prevent_default()
            self.insert("@")
            self.post_message(self.AtInserted(self))
            return
        if key == "slash":
            if self.text:
                return
            event.stop()
            event.prevent_default()
            self.insert("/")
            self.post_message(self.CommandPaletteRequested(self))
            return
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
        margin: 0;
        background: $primary 15%;
        align-horizontal: center;
    }
    BannerMessage Static {
        width: auto;
        height: auto;
    }
    """

    def __init__(self, text: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._text = text

    def compose(self) -> ComposeResult:
        yield Static(self._text, markup=False)


class UserMessage(CopyBlock):
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


class AssistantTurnBlock(Vertical):
    """一轮 LLM 回复：assistant 正文 + 本轮工具调用，灰底块与用户消息对称。"""

    DEFAULT_CSS = """
    AssistantTurnBlock {
        width: 100%;
        height: auto;
        background: $surface;
        padding: 1 2 1 2;
        margin: 0 0 1 0;
    }
    AssistantTurnBlock AssistantMessage {
        width: 100%;
        height: auto;
        margin: 0;
    }
    AssistantTurnBlock AssistantMessage Markdown {
        padding: 0;
    }
    AssistantTurnBlock ToolCallRow {
        margin: 0 0 1 0;
    }
    AssistantTurnBlock SubtaskToolCallRow {
        margin: 0 0 1 0;
    }
    AssistantTurnBlock ToolCallRow:last-child {
        margin-bottom: 0;
    }
    AssistantTurnBlock SubtaskToolCallRow:last-child {
        margin-bottom: 0;
    }
    """


class AssistantMessage(CopyBlock):
    DEFAULT_CSS = """
    AssistantMessage {
        width: 100%;
        height: auto;
    }
    /* Textual's MarkdownFence defaults to black 10% in dark mode, which blends into the chat. */
    AssistantMessage MarkdownFence {
        background: $boost;
        border: none;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Markdown(self._copy_text, open_links=False)


class ToolCallRow(Vertical):
    DEFAULT_CSS = """
    ToolCallRow, SubtaskToolCallRow {
        width: 100%;
        height: auto;
        margin: 0 2 1 1;
    }
    ToolCallRow .tool-summary, SubtaskToolCallRow .tool-summary {
        height: 1;
        align: left middle;
    }
    ToolCallRow .tool-status, SubtaskToolCallRow .tool-status {
        width: 3;
        height: 1;
        min-height: 1;
        max-height: 1;
        text-align: center;
        content-align: center middle;
    }
    ToolCallRow .tool-status.status-running, SubtaskToolCallRow .tool-status.status-running { color: $warning; }
    ToolCallRow .tool-status.status-ok, SubtaskToolCallRow .tool-status.status-ok { color: $success; }
    ToolCallRow .tool-status.status-error, SubtaskToolCallRow .tool-status.status-error { color: $error; }
    ToolCallRow .tool-name, SubtaskToolCallRow .tool-name {
        width: auto;
        height: 1;
        text-style: bold;
        color: $text-muted;
        content-align: left middle;
    }
    ToolCallRow .tool-sep, SubtaskToolCallRow .tool-sep {
        width: auto;
        height: 1;
        color: $text-muted 75%;
        content-align: center middle;
    }
    ToolCallRow .tool-args, SubtaskToolCallRow .tool-args {
        width: 1fr;
        height: 1;
        color: $text-muted;
        overflow: hidden;
        content-align: left middle;
    }
    ToolCallRow Button.tool-expand, SubtaskToolCallRow Button.tool-expand {
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
    ToolCallRow Button.tool-expand:hover, SubtaskToolCallRow Button.tool-expand:hover { background: $boost; }
    ToolCallRow Button.tool-expand:disabled, SubtaskToolCallRow Button.tool-expand:disabled {
        color: $text-muted;
        background: transparent;
    }
    ToolCallRow CopyBlock.tool-result-copy,
    SubtaskToolCallRow CopyBlock.tool-result-copy {
        display: none;
        height: auto;
        margin: 1 0 0 3;
        padding: 1 2;
        background: $boost;
        color: $text-muted;
        width: 100%;
    }
    ToolCallRow CopyBlock.tool-result-copy.is-expanded,
    SubtaskToolCallRow CopyBlock.tool-result-copy.is-expanded {
        display: block;
    }
    ToolCallRow CopyBlock.tool-result-copy Static.tool-result-body,
    SubtaskToolCallRow CopyBlock.tool-result-copy Static.tool-result-body {
        width: 100%;
        height: auto;
    }
    """

    def __init__(self, tool_call_id: str, tool_name: str, tool_args: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.tool_call_id = tool_call_id
        self._tool_display_name = tool_name
        self._tool_arguments_text = tool_args
        self._tool_result_text = ""
        self._is_result_expanded = False

    def _compose_tool_summary(self) -> ComposeResult:
        with Horizontal(classes="tool-summary"):
            yield Static("◐", classes="tool-status status-running", markup=False)
            yield Static(self._tool_display_name, classes="tool-name", markup=False)
            yield Static(" · ", classes="tool-sep", markup=False)
            yield Static(
                _summarize_tool_arguments(self._tool_arguments_text),
                classes="tool-args",
                markup=False,
            )
            yield Button(
                "▶",
                classes="tool-expand",
                disabled=self._tool_expand_initially_disabled(),
                variant="default",
                compact=True,
                flat=True,
            )

    def _tool_expand_initially_disabled(self) -> bool:
        return True

    def _result_copy_block(self) -> CopyBlock:
        return self.query_one(".tool-result-copy", CopyBlock)

    def _set_tool_result_text(self, text: str) -> None:
        self._tool_result_text = text
        self.query_one(".tool-result-body", Static).update(text)
        self._result_copy_block().set_copy_text(text)

    def _set_result_expanded(self, is_expanded: bool) -> None:
        if is_expanded:
            self._result_copy_block().add_class("is-expanded")
        else:
            self._result_copy_block().remove_class("is-expanded")

    def _compose_tool_tail(self) -> ComposeResult:
        with CopyBlock("", classes="tool-result-copy"):
            yield Static("", classes="tool-result-body", markup=False)

    def compose(self) -> ComposeResult:
        summary_copy = _tool_call_summary_copy_text(self._tool_display_name, self._tool_arguments_text)
        with CopyBlock(summary_copy, classes="tool-summary-copy"):
            yield from self._compose_tool_summary()
        yield from self._compose_tool_tail()

    def _sync_extra_expand(self, is_expanded: bool) -> None:
        """子类在展开/收起时同步额外区域（Subtask 为 execution panel）。"""

    def mark_completed(self, is_success: bool, tool_result: object) -> None:
        status_widget = self.query_one(".tool-status", Static)
        status_widget.remove_class("status-running")
        status_widget.add_class("status-ok" if is_success else "status-error")
        status_widget.update("✓" if is_success else "✗")
        self._set_tool_result_text(str(tool_result))
        toggle_button = self.query_one(".tool-expand", Button)
        toggle_button.disabled = False
        toggle_button.tooltip = "展开工具输出"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        toggle_button = self.query_one(".tool-expand", Button)
        if event.button is not toggle_button or toggle_button.disabled:
            return
        self._is_result_expanded = not self._is_result_expanded
        self._set_result_expanded(self._is_result_expanded)
        self._sync_expand_button(toggle_button, self._is_result_expanded)
        self._sync_extra_expand(self._is_result_expanded)

    def _sync_expand_button(self, toggle_button: Button, is_expanded: bool) -> None:
        if is_expanded:
            toggle_button.label = "▼"
            toggle_button.tooltip = "收起工具输出"
        else:
            toggle_button.label = "▶"
            toggle_button.tooltip = "展开工具输出"


class SubtaskToolCallRow(ToolCallRow):
    """SubtaskAgent：在 ToolCallRow 上增加 live 行与 execution panel。"""

    DEFAULT_CSS = """
    SubtaskToolCallRow .tool-summary {
        margin-bottom: 1;
    }
    SubtaskToolCallRow Horizontal.subtask-live {
        height: 1;
        width: 100%;
        margin: 0 0 1 3;
        display: none;
    }
    SubtaskToolCallRow Horizontal.subtask-live.is-visible {
        display: block;
    }
    SubtaskToolCallRow .subtask-live-spinner {
        width: 3;
        height: 1;
        min-height: 1;
        max-height: 1;
        color: $warning;
        text-align: center;
        content-align: center middle;
    }
    SubtaskToolCallRow .subtask-live-detail {
        width: 1fr;
        height: 1;
        color: $text-muted;
        overflow: hidden;
        content-align: left middle;
    }
    SubtaskToolCallRow CopyBlock.subtask-panel-copy {
        display: none;
        width: 100%;
        height: auto;
        margin: 1 0 0 3;
        padding: 1 2;
        background: $boost;
        color: $text-muted;
    }
    SubtaskToolCallRow CopyBlock.subtask-panel-copy.is-expanded {
        display: block;
    }
    SubtaskToolCallRow CopyBlock.subtask-panel-copy Static.subtask-panel {
        width: 100%;
        height: auto;
    }
    """

    def __init__(self, tool_call_id: str, tool_name: str, tool_args: str, **kwargs) -> None:
        super().__init__(tool_call_id, tool_name, tool_args, **kwargs)
        self._timeline_lines: list[str] = []
        self._live_spinner_frame_index = 0
        self._live_spinner_timer = None

    def _tool_expand_initially_disabled(self) -> bool:
        return False

    def _compose_tool_tail(self) -> ComposeResult:
        with Horizontal(classes="subtask-live"):
            yield Static(_SPINNER_FRAMES[0], classes="subtask-live-spinner", markup=False)
            yield Static("", classes="subtask-live-detail", markup=False)
        with CopyBlock("", classes="subtask-panel-copy"):
            yield Static("", classes="subtask-panel", markup=False)
        with CopyBlock("", classes="tool-result-copy"):
            yield Static("", classes="tool-result-body", markup=False)

    def on_unmount(self) -> None:
        self._stop_live_spinner()

    def _stop_live_spinner(self) -> None:
        if self._live_spinner_timer is not None:
            self._live_spinner_timer.stop()
            self._live_spinner_timer = None

    def _refresh_live_spinner(self) -> None:
        self._live_spinner_frame_index = (self._live_spinner_frame_index + 1) % len(_SPINNER_FRAMES)
        self.query_one(".subtask-live-spinner", Static).update(_SPINNER_FRAMES[self._live_spinner_frame_index])

    def _start_live_spinner(self) -> None:
        self._stop_live_spinner()
        self._live_spinner_frame_index = 0
        self._refresh_live_spinner()
        self._live_spinner_timer = self.set_interval(0.1, self._refresh_live_spinner)

    def _panel_copy_block(self) -> CopyBlock:
        return self.query_one(".subtask-panel-copy", CopyBlock)

    def _apply_result_body_expand(self) -> None:
        self._set_result_expanded(self._is_result_expanded and bool(self._tool_result_text.strip()))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        toggle_button = self.query_one(".tool-expand", Button)
        if event.button is not toggle_button or toggle_button.disabled:
            return
        self._is_result_expanded = not self._is_result_expanded
        self._sync_expand_button(toggle_button, self._is_result_expanded)
        self._apply_result_body_expand()
        self._sync_extra_expand(self._is_result_expanded)
        # Textual also invokes ToolCallRow.on_button_pressed; prevent double toggle.
        event.prevent_default()

    def _sync_extra_expand(self, is_expanded: bool) -> None:
        if is_expanded:
            self._panel_copy_block().add_class("is-expanded")
        else:
            self._panel_copy_block().remove_class("is-expanded")

    def set_live(self, label: str) -> None:
        text = label.strip()
        if not text:
            return
        detail = _strip_subtask_live_status_prefix(text)
        self.query_one(".subtask-live-detail", Static).update(detail)
        self.query_one(".subtask-live", Horizontal).add_class("is-visible")
        self._start_live_spinner()

    def clear_live(self) -> None:
        self._stop_live_spinner()
        self.query_one(".subtask-live-detail", Static).update("")
        self.query_one(".subtask-live-spinner", Static).update(_SPINNER_FRAMES[0])
        self.query_one(".subtask-live", Horizontal).remove_class("is-visible")

    def _refresh_subtask_panel(self) -> None:
        panel_text = "\n".join(self._timeline_lines)
        self.query_one(".subtask-panel", Static).update(panel_text)
        self._panel_copy_block().set_copy_text(panel_text)

    def append_line(self, line: str) -> None:
        entry = line.strip()
        if not entry:
            return
        if self._timeline_lines and _subtask_entry_replaces_running_tool_line(self._timeline_lines[-1], entry):
            self._timeline_lines[-1] = entry
        else:
            self._timeline_lines.append(entry)
        self._refresh_subtask_panel()

    def mark_completed(self, is_success: bool, tool_result: object) -> None:
        self.clear_live()
        super().mark_completed(is_success, tool_result)
        self._apply_result_body_expand()


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


class ErrorMessage(CopyBlock):
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
