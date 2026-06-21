"""TUI 状态控制：事件、输入与状态栏。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from textual.app import App
from textual.containers import ScrollableContainer
from textual.widgets import Static, TextArea

from harzoo.agent.components import QueueoutEventName
from harzoo.agent.kernel.message import user_message
from .processing import (
    IMAGE_PLACEHOLDER_PATTERN,
    build_user_message_content_parts,
    format_user_message_for_chat,
    replace_image_paths_with_placeholders,
    sync_attachments_with_placeholders,
)
from .widgets import AgentActivityLine, AssistantMessage, ErrorMessage, ToolCallRow, UserMessage

EventHandler = Callable[[dict[str, Any], dict[str, Any], ScrollableContainer], None]


class AgentController:
    """控制 TUI 交互与出站事件渲染。"""

    def __init__(self, app: App[None], queue_in: Queue) -> None:
        self.app = app
        self.queue_in = queue_in
        self._tool_row_by_call_id: dict[str, ToolCallRow] = {}
        self._activity_line_widget: AgentActivityLine | None = None
        self._previous_raw_input = ""
        self._pending_image_attachments: list[Path] = []
        self._skip_next_input_change = False
        self._status_model_name = "—"
        self._status_profile_name = "—"
        self._status_max_context_tokens: int | None = None
        self._status_usage_ratio_text = ""
        self._is_waiting_assistant_reply = False
        self._event_handler_by_name: dict[QueueoutEventName, EventHandler] = {
            QueueoutEventName.LLM_READY: self._handle_llm_ready_event,
            QueueoutEventName.THINKING_START: self._handle_thinking_started_event,
            QueueoutEventName.THINKING_END: self._handle_thinking_finished_event,
            QueueoutEventName.ASSISTANT_MESSAGE: self._handle_assistant_message_event,
            QueueoutEventName.CONTEXT_COMPACTED: self._handle_context_compacted_event,
            QueueoutEventName.TOOL_START: self._handle_tool_started_event,
            QueueoutEventName.TOOL_END: self._handle_tool_finished_event,
            QueueoutEventName.ERROR: self._handle_error_event,
        }

    def refresh_status_footer_view(self) -> None:
        """更新底部状态栏（模型 / profile 等）。"""
        footer_parts = [self._status_model_name, self._status_profile_name]
        if self._status_usage_ratio_text:
            footer_parts.append(self._status_usage_ratio_text)
        footer_text = " · ".join(footer_parts)
        footer_widget = self.app.query_one("#status-footer", Static)
        footer_widget.update(footer_text)

    def drain_outbound_events(self, outbound_queue: Queue) -> None:
        """排空出站队列并分派到 UI 处理器。"""
        handled_event_count = 0
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
            handled_event_count += 1

        if handled_event_count:
            self._scroll_chat_to_bottom()

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

    def _apply_path_placeholder_rewrite(self, event: TextArea.Changed, raw_input_value: str) -> bool:
        """将检测到的图片路径改写为占位符并同步附件。"""
        sync_attachments_with_placeholders(raw_input_value, self._pending_image_attachments)
        text_with_placeholders = replace_image_paths_with_placeholders(self._previous_raw_input, raw_input_value, self._pending_image_attachments)
        if text_with_placeholders is None or text_with_placeholders == raw_input_value:
            return False
        event.text_area.text = text_with_placeholders
        return True

    def submit_chat_input(self) -> None:
        """从当前输入构建入站 user_message 载荷。"""
        input_widget = self.app.query_one("#chat-input", TextArea)
        submitted_text = input_widget.text.strip()
        if not submitted_text:
            return
        try:
            if IMAGE_PLACEHOLDER_PATTERN.search(submitted_text):
                parts = build_user_message_content_parts(submitted_text, self._pending_image_attachments)
            else:
                parts = [{"type": "text", "text": submitted_text}]
        except ValueError as error:
            self._get_chat_container().mount(ErrorMessage(str(error)))
            self._scroll_chat_to_bottom()
            return

        input_widget.clear()
        self._reset_input_tracking()
        self._mount_user_message(submitted_text)
        self._is_waiting_assistant_reply = True
        self._scroll_chat_to_bottom()
        self.queue_in.put(user_message(parts))

    def _mount_user_message(self, submitted_text: str) -> None:
        """将格式化后的用户消息挂载到聊天区。"""
        self._get_chat_container().mount(UserMessage(format_user_message_for_chat(submitted_text)))

    def _reset_input_tracking(self) -> None:
        """重置输入追踪与待发送图片附件。"""
        self._previous_raw_input = ""
        self._pending_image_attachments.clear()

    def _get_chat_container(self) -> ScrollableContainer:
        """返回聊天消息容器组件。"""
        return self.app.query_one("#chat", ScrollableContainer)

    def _scroll_chat_to_bottom(self) -> None:
        """滚动聊天区到底部，忽略瞬时 UI 时序错误。"""
        self._get_chat_container().scroll_end(animate=False)

    def _remove_activity_line(self) -> None:
        """移除当前活动行组件（若存在）。"""
        if self._activity_line_widget:
            self._activity_line_widget.remove()
            self._activity_line_widget = None

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
        assistant_text = str(payload.get("content", "")).strip()
        if assistant_text:
            chat_container.mount(AssistantMessage(assistant_text))
        usage_payload = payload.get("usage")
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

    def _handle_tool_started_event(
        self,
        payload: dict[str, Any],
        _: dict[str, Any],
        chat_container: ScrollableContainer,
    ) -> None:
        tool_call_id = str(payload.get("tool_call_id", ""))
        tool_row_widget = ToolCallRow(tool_call_id, str(payload.get("tool_name", "")), str(payload.get("tool_args", "")))
        if self._activity_line_widget:
            chat_container.mount(tool_row_widget, before=self._activity_line_widget)
        else:
            chat_container.mount(tool_row_widget)
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
        chat_container.mount(
            AssistantMessage(
                f"[system] Context compacted at {ratio_percent}% (messages: {before_messages} -> {after_messages})."
            )
        )
