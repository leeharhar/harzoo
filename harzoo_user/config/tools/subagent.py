"""Synchronous subtask agent tool (single-call delegated execution)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harzoo.agent.agent import Agent
from harzoo.agent.components.paths import ConfigPaths, resolve_profile_path
from harzoo.agent.components.context_compact import compact_context_state
from harzoo.agent.components.util import load_yaml_front_matter_markdown
from harzoo.agent.kernel.message import assistant_message, tool_message, user_message
from harzoo.agent.kernel.tool import Context, Tool, ToolResult

TOOL_VERSION = "2026-07-22"

# Host LLM must not tune subtask depth; fixed cap avoids premature max_turns_reached on Browser flows.
_DEFAULT_SUBTASK_MAX_TURNS = 110

_SUMMARY_MAX_LEN = 144
_LIVE_DETAIL_MAX_LEN = 80


def _summarize_line(text: str, max_len: int = _SUMMARY_MAX_LEN) -> str:
    single = text.replace("\n", " ").strip()
    return single if len(single) <= max_len else single[: max_len - 1] + "…"


def _format_subagent_assistant_entry(display_name: str, content: str) -> str:
    return f"◦ {display_name} › {_summarize_line(content)}"


def _format_subagent_tool_entry(display_name: str, tool_name: str, args_str: str, *, running: bool, ok: bool | None = None) -> str:
    if running:
        status = "◐"
    elif ok:
        status = "✓"
    else:
        status = "✗"
    args_part = _summarize_line(args_str)
    return f"{status} {display_name} › {tool_name} · {args_part}" if args_part else f"{status} {display_name} › {tool_name}"


def _format_subtask_live(display_name: str, round_n: int, detail: str) -> str:
    detail_part = _summarize_line(detail, _LIVE_DETAIL_MAX_LEN)
    return f"◐ {display_name} · round {round_n} · {detail_part}" if detail_part else f"◐ {display_name} · round {round_n}"


def _extract_assistant_text(content: object) -> str:
    """从 LLM 返回的 content 中提取可展示的纯文本。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        # 多段内容（如 [{"type":"text","text":"..."}]）拼接为单行
        parts: list[str] = []
        for segment in content:
            if not isinstance(segment, dict) or segment.get("type") != "text":
                continue
            text = segment.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        return " ".join(parts).strip()
    # 兜底：未知类型转字符串
    return str(content).strip()


def _extract_final_assistant_content(state: list[dict[str, Any]]) -> Any:
    for item in reversed(state):
        if item.get("role") == "assistant":
            return item.get("content")
    return None


def _extract_tool_errors(state: list[dict[str, Any]]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for item in state:
        if item.get("role") != "tool":
            continue
        raw = item.get("content")
        if not isinstance(raw, str):
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if payload.get("ok"):
            continue
        errors.append(
            {
                "code": str(payload.get("code") or "TOOL_FAILED"),
                "error": str(payload.get("error") or ""),
            }
        )
    return errors


def _extract_report_md_from_state(state: list[dict[str, Any]]) -> str:
    """Prefer report_md from Submit* tool results over raw assistant text."""
    for item in reversed(state):
        if item.get("role") != "tool":
            continue
        raw = item.get("content")
        if not isinstance(raw, str):
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not payload.get("ok"):
            continue
        data = payload.get("data")
        if isinstance(data, dict):
            report_md = data.get("report_md")
            if isinstance(report_md, str) and report_md.strip():
                return report_md.strip()
    return ""


def _resolve_display_agent_name(agent: Agent, requested: str | None) -> str:
    if requested and str(requested).strip():
        return str(requested).strip()
    try:
        meta, _ = load_yaml_front_matter_markdown(agent.profile.source_path)
        name = str(meta.get("name") or "").strip()
        if name:
            return name
    except (OSError, ValueError):
        pass
    return agent.profile.source_path.stem


class SubtaskAgentTool(Tool):
    """子任务委派工具：用子 profile 同步执行任务并回收最终结果。"""

    name = "SubtaskAgent"
    description = (
        "Run a delegated subtask with a dedicated profile in a synchronous nested "
        "agent loop, then return the final assistant output."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task_description": {"type": "string", "description": "Subtask prompt for the delegated agent"},
            "agent_name": {
                "type": "string",
                "description": "Subtask profile name/path. Defaults to the active default profile.",
            },
            "show_progress": {
                "type": "boolean",
                "description": "When true, stream sub-agent assistant replies and tool calls to the TUI.",
                "default": True,
            },
        },
        "required": ["task_description"],
    }

    def execute(
        self,
        task_description: str,
        agent_name: str | None = None,
        show_progress: bool = True,
        *,
        ctx: Context | None = None,
        **_: Any,
    ) -> ToolResult:
        task_text = str(task_description).strip()
        if not task_text:
            return ToolResult.failure("task_description is required", code="INVALID_ARGUMENTS")
        if ctx is None:
            return ToolResult.failure("SubtaskAgent requires host Context", code="INVALID_CONTEXT")

        capped_turns = _DEFAULT_SUBTASK_MAX_TURNS

        try:
            paths = ctx.config_paths
            profile_path = resolve_profile_path(agent_name or "", paths)
            child = Agent.from_profile(profile_path, paths)
            display_name = _resolve_display_agent_name(child, agent_name)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(
                f"Failed to initialize subtask agent: {type(exc).__name__}: {exc}",
                code="SUBTASK_INIT_FAILED",
            )

        sub_state: list[dict[str, Any]] = [user_message([{"type": "text", "text": task_text}])]
        host_call_id = ctx.host_tool_call_id
        sub_ctx = Context(
            state=sub_state,
            agent=child,
            config_paths=paths,
            emitter=ctx.emitter,
            host_tool_call_id=host_call_id,
        )
        emit_to_tui = bool(show_progress) and ctx.emitter is not None and bool(host_call_id)
        rounds = 0

        if emit_to_tui:
            ctx.emitter.emit_subtask_live(host_call_id, _format_subtask_live(display_name, 1, "starting…"))

        try:
            while rounds < capped_turns and sub_state and sub_state[-1].get("role") in ("user", "tool"):
                rounds += 1
                delta: list[dict[str, Any]] = []
                content, tool_calls, usage = child.decide(sub_state)
                prompt_tokens = int(usage.get("prompt_tokens") or 0) if isinstance(usage, dict) else 0
                max_ctx = child.llm.llm_config.max_context_tokens
                if prompt_tokens > 0 and max_ctx is not None and int(max_ctx) > 0 and prompt_tokens * 100 >= int(max_ctx) * 80:
                    compact_context_state(sub_state, llm=child.llm, max_context_tokens=max_ctx)
                delta.append(assistant_message(content=content, tool_calls=tool_calls))
                assistant_text = _extract_assistant_text(content)
                if assistant_text and emit_to_tui:
                    ctx.emitter.emit_subtask_entry(host_call_id, _format_subagent_assistant_entry(display_name, assistant_text))
                    ctx.emitter.emit_subtask_live(
                        host_call_id,
                        _format_subtask_live(display_name, rounds, assistant_text),
                    )
                elif emit_to_tui:
                    ctx.emitter.emit_subtask_live(host_call_id, _format_subtask_live(display_name, rounds, "thinking…"))
                if isinstance(tool_calls, list) and tool_calls:
                    for tool_call in tool_calls:
                        call_id, fn = str(tool_call["id"]), tool_call["function"]
                        tool_name, args_str = str(fn["name"]), str(fn["arguments"])
                        if emit_to_tui:
                            ctx.emitter.emit_subtask_entry(
                                host_call_id,
                                _format_subagent_tool_entry(display_name, tool_name, args_str, running=True),
                            )
                            ctx.emitter.emit_subtask_live(
                                host_call_id,
                                _format_subtask_live(display_name, rounds, f"{tool_name} · {args_str}"),
                            )
                        tool_result = child.execute_tool_call(tool_name, args_str, sub_ctx)
                        if emit_to_tui:
                            ctx.emitter.emit_subtask_entry(
                                host_call_id,
                                _format_subagent_tool_entry(
                                    display_name,
                                    tool_name,
                                    args_str,
                                    running=False,
                                    ok=tool_result.ok,
                                ),
                            )
                        delta.append(tool_message(call_id, tool_result))
                        if tool_result.injected_user_input_segments:
                            delta.append(user_message(tool_result.injected_user_input_segments))
                if not delta:
                    break
                sub_state.extend(delta)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(
                f"Subtask execution failed: {type(exc).__name__}: {exc}",
                code="SUBTASK_EXECUTION_FAILED",
            )

        final_output = _extract_final_assistant_content(sub_state)
        report_md = _extract_report_md_from_state(sub_state)
        tool_errors = _extract_tool_errors(sub_state)
        if not report_md and isinstance(final_output, str):
            report_md = final_output.strip()

        result_data = {
            "agent_name": display_name,
            "final_output": final_output,
            "report_md": report_md,
            "tool_errors": tool_errors,
            "rounds_used": rounds,
            "stopped_reason": "max_turns_reached"
            if rounds >= capped_turns and sub_state and sub_state[-1].get("role") in ("user", "tool")
            else "completed",
        }
        return ToolResult.success(result_data)


TOOL = SubtaskAgentTool
