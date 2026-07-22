"""TUI 状态控制：事件、输入与状态栏。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from textual.app import App
from textual.containers import ScrollableContainer
from textual.widget import Widget
from textual.widgets import Static, TextArea

from harzoo.agent.components import QueueoutEventName
from harzoo.agent.kernel.message import user_message
from .logic.commands import dispatch_command
from .logic.processing import (
    IMAGE_PLACEHOLDER_PATTERN,
    build_user_message_content_parts,
    format_user_message_for_chat,
    replace_image_paths_with_placeholders,
    sync_attachments_with_placeholders,
)
from .pickers.command_picker import CommandPicker
from .pickers.file_picker import FilePicker
from .widgets import (
    AgentActivityLine,
    AssistantMessage,
    AssistantTurnBlock,
    ErrorMessage,
    SubtaskToolCallRow,
    SystemMessage,
    ToolCallRow,
    UserMessage,
)

EventHandler = Callable[[dict[str, Any], dict[str, Any], ScrollableContainer], None]


def _location_to_offset(text: str, location: tuple[int, int]) -> int:
    row, col = location
    lines = text.split("\n")
    if row >= len(lines):
        return len(text)
    return sum(len(lines[i]) + 1 for i in range(row)) + min(col, len(lines[row]))


def _offset_to_location(text: str, offset: int) -> tuple[int, int]:
    offset = max(0, min(offset, len(text)))
    row = 0
    col = 0
    for index, char in enumerate(text):
        if index == offset:
            return (row, col)
        if char == "\n":
            row += 1
            col = 0
        else:
            col += 1
    return (row, col)


def _turn_tokens(usage: dict[str, Any]) -> int:
    try:
        total = int(usage.get("total_tokens") or 0)
    except (TypeError, ValueError):
        total = 0
    if total > 0:
        return total
    try:
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, prompt + completion)


def _compact_int(value: int) -> str:
    if value >= 10_000:
        return f"{value // 1000}k"
    if value >= 1_000:
        compact = f"{value / 1000:.1f}k"
        if compact.endswith(".0k"):
            return f"{value // 1000}k"
        return compact
    return str(value)


def _footer_workspace_path(root: Path, *, max_len: int = 36) -> str:
    resolved = root.expanduser().resolve()
    try:
        text = resolved.as_posix()
        home = Path.home().resolve().as_posix()
        if text.startswith(home):
            text = "~" + text[len(home) :]
    except OSError:
        text = str(resolved)
    if len(text) <= max_len:
        return text
    head = (max_len - 1) // 2
    tail = max_len - 1 - head
    return f"{text[:head]}…{text[-tail:]}"


class AgentController:
    """控制 TUI 交互与出站事件渲染。"""

    def __init__(
        self,
        app: App[None],
        queue_in: Queue,
        *,
        workspace_root: Path,
    ) -> None:
        self.app = app
        self.queue_in = queue_in
        self._status_footer_workspace = _footer_workspace_path(workspace_root)
        self._tool_row_by_call_id: dict[str, ToolCallRow] = {}
        self._activity_line_widget: AgentActivityLine | None = None
        self._previous_raw_input = ""
        self._pending_image_attachments: list[Path] = []
        self._mention_start: int | None = None
        self._skip_next_input_change = False
        self._status_model_name = "—"
        self._status_profile_name = "—"
        self._status_max_context_tokens: int | None = None
        self._status_usage_ratio_text = ""
        self._last_turn_tokens = 0
        self._session_total_tokens = 0
        self._is_waiting_assistant_reply = False
        self._current_turn_block: AssistantTurnBlock | None = None
        self._event_handler_by_name: dict[QueueoutEventName, EventHandler] = {
            QueueoutEventName.LLM_READY: self._handle_llm_ready_event,
            QueueoutEventName.THINKING_START: self._handle_thinking_started_event,
            QueueoutEventName.THINKING_END: self._handle_thinking_finished_event,
            QueueoutEventName.ASSISTANT_MESSAGE: self._handle_assistant_message_event,
            QueueoutEventName.SUBTASK_LIVE: self._handle_subtask_live_event,
            QueueoutEventName.SUBTASK_ENTRY: self._handle_subtask_entry_event,
            QueueoutEventName.CONTEXT_COMPACTED: self._handle_context_compacted_event,
            QueueoutEventName.TOOL_START: self._handle_tool_started_event,
            QueueoutEventName.TOOL_END: self._handle_tool_finished_event,
            QueueoutEventName.ERROR: self._handle_error_event,
            QueueoutEventName.SESSION_RESET: self._handle_session_reset_event,
        }

    def refresh_status_footer_view(self) -> None:
        """更新底部状态栏。"""
        footer_parts = [
            self._status_footer_workspace,
            self._status_model_name,
            self._status_profile_name,
        ]
        if self._status_usage_ratio_text:
            footer_parts.append(self._status_usage_ratio_text)
        if self._last_turn_tokens > 0:
            footer_parts.append(_compact_int(self._last_turn_tokens))
        if self._session_total_tokens > 0:
            footer_parts.append(f"Σ{_compact_int(self._session_total_tokens)}")
        footer_text = " · ".join(footer_parts)
        self.app.query_one("#status-footer", Static).update(footer_text)

    def drain_outbound_events(self, outbound_queue: Queue) -> None:
        """排空出站队列并分派到 UI 处理器。"""
        chat_container = self._get_chat_container()
        while True:
            try:
                outbound_event = outbound_queue.get_nowait()
            except Empty:
                break

            event_name_raw = outbound_event.get("name")
            event_name = QueueoutEventName(str(event_name_raw))
            if handler := self._event_handler_by_name.get(event_name):
                handler(outbound_event.get("payload", {}), outbound_event.get("error", {}), chat_container)

    def on_input_changed(self, event: TextArea.Changed) -> None:
        """处理输入变化，含图片路径占位符改写。"""
        if event.text_area.id != "chat-input":
            return

        if self._skip_next_input_change:
            self._skip_next_input_change = False
            self._previous_raw_input = event.text_area.text
            return

        raw_input_value = event.text_area.text
        if self._apply_path_placeholder_rewrite(event, raw_input_value):
            self._skip_next_input_change = True
            return

        self._previous_raw_input = raw_input_value

    def open_command_palette(self) -> None:
        """/：打开命令选择器（唯一命令入口）。"""
        self.dismiss_file_picker()
        cmd_picker = self.app.query_one("#command-picker", CommandPicker)
        current = self._status_profile_name if self._status_profile_name != "—" else ""
        cmd_picker.set_current_profile(current)
        cmd_picker.open_picker()

    def on_at_inserted(self, text_area: TextArea) -> None:
        """@ 键：打开文件选择器。"""
        if text_area.id != "chat-input":
            return

        cmd_picker = self.app.query_one("#command-picker", CommandPicker)
        if cmd_picker.is_open:
            cmd_picker.close_picker()

        self._mention_start = _location_to_offset(text_area.text, text_area.cursor_location) - 1
        self.app.query_one("#file-picker", FilePicker).open_picker()

    def run_picked_command(self, command: str, args: list[str]) -> None:
        """CommandPicker 选中后立即执行。"""
        input_widget = self.app.query_one("#chat-input", TextArea)
        input_widget.clear()
        self._reset_input_tracking()
        dispatch_command(self, command, args)
        self.anchor_chat()

    def _apply_path_placeholder_rewrite(self, event: TextArea.Changed, raw_input_value: str) -> bool:
        """将检测到的图片路径改写为占位符并同步附件。"""
        sync_attachments_with_placeholders(raw_input_value, self._pending_image_attachments)
        text_with_placeholders = replace_image_paths_with_placeholders(self._previous_raw_input, raw_input_value, self._pending_image_attachments)
        if text_with_placeholders is None or text_with_placeholders == raw_input_value:
            return False
        event.text_area.text = text_with_placeholders
        return True

    def emit_system(self, text: str) -> None:
        """挂载灰色系统行。"""
        if not text.strip():
            return
        self._get_chat_container().mount(SystemMessage(text))

    def insert_path_into_input(self, relative_path: str) -> None:
        """将 @ 替换为选中的路径。"""
        input_widget = self.app.query_one("#chat-input", TextArea)
        snippet = relative_path.strip()
        start = self._mention_start
        if not snippet or start is None:
            return

        text = input_widget.text
        if not (0 <= start < len(text) and text[start] == "@"):
            return

        end = _location_to_offset(text, input_widget.cursor_location)
        input_widget.replace(
            f"{snippet} ",
            _offset_to_location(text, start),
            _offset_to_location(text, end),
            maintain_selection_offset=False,
        )

        self._mention_start = None
        self._skip_next_input_change = True
        self._previous_raw_input = input_widget.text
        input_widget.focus()

    def submit_chat_input(self) -> None:
        """从当前输入构建入站 user_message 载荷。"""
        input_widget = self.app.query_one("#chat-input", TextArea)
        submitted_text = input_widget.text.strip()
        if not submitted_text:
            return

        input_widget.clear()
        self._reset_input_tracking()

        try:
            if IMAGE_PLACEHOLDER_PATTERN.search(submitted_text):
                parts = build_user_message_content_parts(submitted_text, self._pending_image_attachments)
            else:
                parts = [{"type": "text", "text": submitted_text}]
        except ValueError as error:
            self._get_chat_container().mount(ErrorMessage(str(error)))
            self.anchor_chat()
            return

        self._mount_user_message(submitted_text)
        self._current_turn_block = None
        self._is_waiting_assistant_reply = True
        self.anchor_chat()
        self.queue_in.put(user_message(parts))

    def _mount_user_message(self, submitted_text: str) -> None:
        """将格式化后的用户消息挂载到聊天区。"""
        self._get_chat_container().mount(UserMessage(format_user_message_for_chat(submitted_text)))

    def dismiss_file_picker(self) -> None:
        """关闭文件选择器并清除 @ 替换位置。"""
        self._mention_start = None
        file_picker = self.app.query_one("#file-picker", FilePicker)
        if file_picker.is_open:
            file_picker.close_picker()

    def _reset_input_tracking(self) -> None:
        """重置输入追踪与待发送图片附件。"""
        self._previous_raw_input = ""
        self._pending_image_attachments.clear()
        self.dismiss_file_picker()

    def _get_chat_container(self) -> ScrollableContainer:
        """返回聊天消息容器组件。"""
        return self.app.query_one("#chat", ScrollableContainer)

    def init_chat_view(self) -> None:
        """启动时消息区滚到顶部。"""
        self._get_chat_container().scroll_home(animate=False, immediate=True)

    def anchor_chat(self) -> None:
        """消息区跟尾（banner 在滚动区外，不受 anchor 影响）。"""
        self._get_chat_container().anchor()

    def _remove_activity_line(self) -> None:
        """移除当前活动行组件（若存在）。"""
        if self._activity_line_widget:
            self._activity_line_widget.remove()
            self._activity_line_widget = None

    def _start_new_turn_block(self, chat_container: ScrollableContainer) -> AssistantTurnBlock:
        """为新一轮 LLM 回复创建灰底块。"""
        turn_block = AssistantTurnBlock()
        self._current_turn_block = turn_block
        if self._activity_line_widget:
            chat_container.mount(turn_block, before=self._activity_line_widget)
        else:
            chat_container.mount(turn_block)
        return turn_block

    def _ensure_turn_block(self, chat_container: ScrollableContainer) -> AssistantTurnBlock:
        """返回当前轮次块；若不存在则新建。"""
        if self._current_turn_block is None:
            return self._start_new_turn_block(chat_container)
        return self._current_turn_block

    def _mount_in_turn(self, chat_container: ScrollableContainer, widget: Widget) -> None:
        """将组件挂载到当前 assistant 轮次块内。"""
        self._ensure_turn_block(chat_container).mount(widget)

    def _handle_thinking_started_event(
        self,
        __: dict[str, Any],
        _: dict[str, Any],
        chat_container: ScrollableContainer,
    ) -> None:
        self._remove_activity_line()
        self._status_usage_ratio_text = ""
        self.refresh_status_footer_view()
        self._activity_line_widget = AgentActivityLine("thinking", model_name=self._status_model_name)
        chat_container.mount(self._activity_line_widget)

    def _handle_llm_ready_event(
        self,
        payload: dict[str, Any],
        _: dict[str, Any],
        __: ScrollableContainer,
    ) -> None:
        model_name = str(payload.get("model_name", "")).strip()
        if model_name:
            self._status_model_name = model_name
        profile_name = str(payload.get("profile_name", "")).strip()
        if profile_name:
            self._status_profile_name = profile_name
        try:
            max_context_tokens = int(payload.get("max_context_tokens"))
        except (TypeError, ValueError):
            max_context_tokens = None
        self._status_max_context_tokens = max_context_tokens if isinstance(max_context_tokens, int) and max_context_tokens > 0 else None
        self._status_usage_ratio_text = ""
        self.refresh_status_footer_view()

    def _handle_thinking_finished_event(
        self,
        _: dict[str, Any],
        __: dict[str, Any],
        ___: ScrollableContainer,
    ) -> None:
        self._remove_activity_line()

    def _handle_assistant_message_event(
        self,
        payload: dict[str, Any],
        _: dict[str, Any],
        chat_container: ScrollableContainer,
    ) -> None:
        self._remove_activity_line()
        turn_block = self._start_new_turn_block(chat_container)
        assistant_text = str(payload.get("content", "")).strip()
        if assistant_text:
            turn_block.mount(AssistantMessage(assistant_text))
        usage_payload = payload.get("usage")
        if isinstance(usage_payload, dict):
            turn_tokens = _turn_tokens(usage_payload)
            if turn_tokens > 0:
                self._last_turn_tokens = turn_tokens
                self._session_total_tokens += turn_tokens
        if isinstance(usage_payload, dict) and self._status_max_context_tokens is not None:
            try:
                prompt_tokens = int(usage_payload.get("prompt_tokens"))
            except (TypeError, ValueError):
                prompt_tokens = None
            if isinstance(prompt_tokens, int) and prompt_tokens > 0:
                ratio_percent = round((prompt_tokens / self._status_max_context_tokens) * 100)
                self._status_usage_ratio_text = f"ctx {ratio_percent}%"
            else:
                self._status_usage_ratio_text = ""
        else:
            self._status_usage_ratio_text = ""
        self.refresh_status_footer_view()
        if self._is_waiting_assistant_reply:
            self._is_waiting_assistant_reply = False

    def _subtask_row(self, host_call_id: str) -> SubtaskToolCallRow | None:
        row = self._tool_row_by_call_id.get(host_call_id)
        return row if isinstance(row, SubtaskToolCallRow) else None

    def _handle_subtask_live_event(
        self,
        payload: dict[str, Any],
        _: dict[str, Any],
        __: ScrollableContainer,
    ) -> None:
        host_call_id = str(payload.get("host_call_id", "")).strip()
        if row := self._subtask_row(host_call_id):
            row.set_live(str(payload.get("label", "")))

    def _handle_subtask_entry_event(
        self,
        payload: dict[str, Any],
        _: dict[str, Any],
        __: ScrollableContainer,
    ) -> None:
        host_call_id = str(payload.get("host_call_id", "")).strip()
        if row := self._subtask_row(host_call_id):
            row.append_line(str(payload.get("line", "")))

    def _handle_tool_started_event(
        self,
        payload: dict[str, Any],
        _: dict[str, Any],
        chat_container: ScrollableContainer,
    ) -> None:
        tool_call_id = str(payload.get("tool_call_id", ""))
        tool_name = str(payload.get("tool_name", ""))
        tool_args = str(payload.get("tool_args", ""))
        if tool_name == "SubtaskAgent":
            tool_row_widget: ToolCallRow = SubtaskToolCallRow(tool_call_id, tool_name, tool_args)
        else:
            tool_row_widget = ToolCallRow(tool_call_id, tool_name, tool_args)
        self._mount_in_turn(chat_container, tool_row_widget)
        if tool_call_id:
            self._tool_row_by_call_id[tool_call_id] = tool_row_widget

    def _handle_tool_finished_event(
        self,
        payload: dict[str, Any],
        _: dict[str, Any],
        __: ScrollableContainer,
    ) -> None:
        tool_call_id = str(payload.get("tool_call_id", ""))
        if tool_row_widget := self._tool_row_by_call_id.pop(tool_call_id, None):
            tool_row_widget.mark_completed(bool(payload.get("ok")), str(payload.get("tool_result", "")))

    def _handle_session_reset_event(
        self,
        _: dict[str, Any],
        __: dict[str, Any],
        ___: ScrollableContainer,
    ) -> None:
        self._clear_chat_ui()
        self.emit_system("会话已清空。")
        self.anchor_chat()

    def _clear_chat_ui(self) -> None:
        """清空消息滚动区并重置 UI 会话状态（顶栏 banner 保留）。"""
        chat_container = self._get_chat_container()
        for child in list(chat_container.children):
            child.remove()
        self._tool_row_by_call_id.clear()
        self._remove_activity_line()
        self._current_turn_block = None
        self._is_waiting_assistant_reply = False
        self._last_turn_tokens = 0
        self._session_total_tokens = 0
        self._status_usage_ratio_text = ""
        self.refresh_status_footer_view()

    def _handle_error_event(
        self,
        payload: dict[str, Any],
        error: dict[str, Any],
        chat_container: ScrollableContainer,
    ) -> None:
        if self._is_waiting_assistant_reply:
            self._is_waiting_assistant_reply = False
        message_text = str(error.get("message") or payload.get("message", "Error"))
        chat_container.mount(ErrorMessage(message_text))

    def _handle_context_compacted_event(
        self,
        payload: dict[str, Any],
        _: dict[str, Any],
        chat_container: ScrollableContainer,
    ) -> None:
        try:
            prompt_tokens = int(payload.get("prompt_tokens"))
            max_context_tokens = int(payload.get("max_context_tokens"))
            before_messages = int(payload.get("before_messages"))
            after_messages = int(payload.get("after_messages"))
        except (TypeError, ValueError):
            return
        ratio_percent = round((prompt_tokens / max_context_tokens) * 100) if max_context_tokens > 0 else 0
        turn_block = self._start_new_turn_block(chat_container)
        turn_block.mount(
            AssistantMessage(
                f"[system] Context compacted at {ratio_percent}% (messages: {before_messages} -> {after_messages})."
            )
        )
