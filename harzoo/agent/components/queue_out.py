"""输出队列 queue_out 协议常量与发送器。"""

from __future__ import annotations

from enum import StrEnum
from queue import Queue
from typing import Any

from harzoo.agent.kernel.tool import ToolResult


class QueueoutEventName(StrEnum):
    LLM_READY = "llm_ready"
    THINKING_START = "thinking_start"
    THINKING_END = "thinking_end"
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    ASSISTANT_MESSAGE = "assistant_message"
    SUBTASK_LIVE = "subtask_live"
    SUBTASK_ENTRY = "subtask_entry"
    CONTEXT_COMPACTED = "context_compacted"
    SESSION_RESET = "session_reset"
    ERROR = "error"


class QueueoutEmitter:
    """负责将数据消息发送到输出队列"""

    def __init__(self, queue_out: Queue[dict[str, Any]] | None = None):
        self._queue_out = queue_out

    def _emit(self, name: QueueoutEventName, payload: dict[str, Any], *, error: dict[str, Any] | None = None) -> None:
        if not self._queue_out:
            return
        msg = {"name": name, "payload": payload}
        if error:
            msg["error"] = dict(error)
        self._queue_out.put(msg)

    def emit_llm_ready(self, model_name: str, profile: str, *, max_context_tokens: int | None = None) -> None:
        payload = {"model_name": model_name, "profile_name": profile}
        if max_context_tokens is not None:
            payload["max_context_tokens"] = int(max_context_tokens)
        self._emit(QueueoutEventName.LLM_READY, payload)

    def emit_thinking_started(self) -> None:
        self._emit(QueueoutEventName.THINKING_START, {})

    def emit_thinking_finished(self) -> None:
        self._emit(QueueoutEventName.THINKING_END, {})

    def emit_tool_started(self, tool_name: str, call_id: str, args: str) -> None:
        self._emit(QueueoutEventName.TOOL_START, {"tool_name": tool_name, "tool_call_id": call_id, "tool_args": args})

    def emit_tool_finished(self, call_id: str, tool_result: ToolResult) -> None:
        self._emit(QueueoutEventName.TOOL_END, {"tool_call_id": call_id, "tool_result": tool_result.to_json(), "ok": tool_result.ok})

    def emit_assistant_message(self, content: object, *, usage: object = None) -> None:
        payload = {"content": str(content)}
        if isinstance(usage, dict):
            payload["usage"] = {"prompt_tokens": int(usage.get("prompt_tokens", 0)), "completion_tokens": int(usage.get("completion_tokens", 0)), "total_tokens": int(usage.get("total_tokens", 0)), "latency_ms": int(usage.get("latency_ms", 0))}
        self._emit(QueueoutEventName.ASSISTANT_MESSAGE, payload)

    def emit_subtask_live(self, host_call_id: str, label: str) -> None:
        host_id = str(host_call_id).strip()
        text = str(label).strip()
        if not host_id or not text:
            return
        self._emit(QueueoutEventName.SUBTASK_LIVE, {"host_call_id": host_id, "label": text})

    def emit_subtask_entry(self, host_call_id: str, line: str) -> None:
        host_id = str(host_call_id).strip()
        text = str(line).strip()
        if not host_id or not text:
            return
        self._emit(QueueoutEventName.SUBTASK_ENTRY, {"host_call_id": host_id, "line": text})

    def emit_context_compacted(self, *, prompt_tokens: int, max_context_tokens: int, before_messages: int, after_messages: int) -> None:
        self._emit(QueueoutEventName.CONTEXT_COMPACTED, {"prompt_tokens": int(prompt_tokens), "max_context_tokens": int(max_context_tokens), "before_messages": int(before_messages), "after_messages": int(after_messages)})

    def emit_session_reset(self) -> None:
        self._emit(QueueoutEventName.SESSION_RESET, {})

    def emit_error(self, message: str, *, retriable: bool = False, details: dict[str, Any] | None = None) -> None:
        self._emit(QueueoutEventName.ERROR, {"message": message}, error={"message": message, "retriable": retriable, "details": details or {}})
