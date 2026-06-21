"""Summarize older conversation turns and shrink in-memory state (model-invoked)."""


from __future__ import annotations

import json
from typing import Any

from harzoo.agent.kernel.llm import LLM
from harzoo.agent.kernel.tool import Context
from harzoo.agent.kernel.message import assistant_message
from harzoo.agent.kernel.tool import Tool, ToolResult

TOOL_VERSION = "2026-05-22"

_SUMMARY_HEADER = "[CONTEXT_SUMMARY]"
_DEFAULT_KEEP_TAIL = 8


def _summarize_history(history: list[dict[str, Any]], llm: LLM) -> str:
    if not history:
        return ""
    summary_prompt = (
        "Summarize the prior conversation history for future continuation.\n"
        "Output plain text with these sections:\n"
        "- goal\n"
        "- done\n"
        "- decisions\n"
        "- constraints\n"
        "- todo\n"
        "- open_questions\n"
        "Rules: only use facts present in input; do not invent details; mark uncertain items as unknown."
    )
    response = llm.client.chat.completions.create(
        model=llm.llm_config.model_name,
        messages=[
            {"role": "system", "content": "You are a precise conversation summarizer."},
            {
                "role": "user",
                "content": f"{summary_prompt}\n\nHistory JSON:\n{json.dumps(history, ensure_ascii=True)}",
            },
        ],
    )
    content = response.choices[0].message.content
    return str(content or "").strip()


class CompactContextTool(Tool):
    """上下文压缩工具：总结旧消息并保留最近若干轮，减少上下文占用。"""

    name = "CompactContext"
    description = (
        "Summarize older messages in the current session into one assistant summary block and keep the "
        f"last few messages verbatim (default {_DEFAULT_KEEP_TAIL}). Use when the context window is tight."
    )
    parameters = {
        "type": "object",
        "properties": {
            "keep_tail": {
                "type": "integer",
                "description": f"Recent messages to keep verbatim (2–32, default {_DEFAULT_KEEP_TAIL}).",
                "minimum": 2,
                "maximum": 32,
            },
        },
    }

    def execute(self, keep_tail: int | None = None, *, ctx: Context | None = None, **_: Any) -> ToolResult:
        """压缩历史上下文并保留最近若干轮消息。"""

        if ctx is None:
            return ToolResult.failure("CompactContext requires Context", code="INVALID_CONTEXT")
        if not isinstance(ctx.agent.llm, LLM):
            return ToolResult.failure("CompactContext requires host LLM", code="INVALID_CONTEXT")

        try:
            kt = _DEFAULT_KEEP_TAIL if keep_tail is None else int(keep_tail)
        except (TypeError, ValueError):
            kt = _DEFAULT_KEEP_TAIL
        # 特殊限制：keep_tail 强制夹紧到 2~32，避免压缩过度或收益过低。
        kt = max(2, min(32, kt))

        state = ctx.state
        if len(state) <= kt + 1:
            return ToolResult.failure("Not enough messages to compact", code="INVALID_STATE")

        history_head = state[:-kt]
        recent_tail = state[-kt:]
        before_count = len(state)

        # 限制：摘要质量依赖模型，不保证逐字可追溯；仅用于上下文压缩续聊。
        try:
            summary_text = _summarize_history(history_head, ctx.agent.llm)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(
                f"Summarization failed: {type(exc).__name__}: {exc}",
                code="COMPACT_FAILED",
            )
        if not summary_text:
            return ToolResult.failure("Summarizer returned empty text", code="COMPACT_FAILED")

        compacted = [assistant_message(content=f"{_SUMMARY_HEADER}\n{summary_text}")]
        compacted.extend(recent_tail)
        state.clear()
        state.extend(compacted)

        llm_config = ctx.agent.llm.llm_config
        max_tok = llm_config.max_context_tokens if llm_config is not None else None
        max_int = int(max_tok) if max_tok is not None and int(max_tok) > 0 else 1
        if ctx.emitter is not None:
            ctx.emitter.emit_context_compacted(
                prompt_tokens=0,
                max_context_tokens=max_int,
                before_messages=before_count,
                after_messages=len(state),
            )

        return ToolResult.success(
            {
                "before_messages": before_count,
                "after_messages": len(state),
                "keep_tail": kt,
            }
        )


TOOL = CompactContextTool
