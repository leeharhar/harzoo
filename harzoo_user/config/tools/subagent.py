"""Synchronous subtask agent tool (delegated execution + optional session resume)."""

from __future__ import annotations

import json
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from harzoo.agent.agent import Agent
from harzoo.agent.components.paths import ConfigPaths, resolve_profile_path
from harzoo.agent.components.context_compact import compact_context_state
from harzoo.agent.components.util import load_yaml_front_matter_markdown
from harzoo.agent.kernel.message import assistant_message, tool_message, user_message
from harzoo.agent.kernel.tool import Context, Tool, ToolResult

TOOL_VERSION = "2026-07-24"

# Host LLM must not tune subtask depth; fixed cap avoids premature max_turns_reached on Browser flows.
_DEFAULT_SUBTASK_MAX_TURNS = 110

# Session memory: resume the same child state across host SubtaskAgent calls.
_MAX_FOLLOWUPS = 50
_MAX_SESSIONS = 16

_SUMMARY_MAX_LEN = 144
_LIVE_DETAIL_MAX_LEN = 80


@dataclass
class _SubtaskSession:
    profile_key: str
    agent: Agent
    state: list[dict[str, Any]]
    followups_used: int = 0


# session_id -> session (OrderedDict for simple FIFO eviction)
_SESSIONS: OrderedDict[str, _SubtaskSession] = OrderedDict()


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


def _profile_key(profile_path: Any) -> str:
    return str(profile_path.resolve()) if hasattr(profile_path, "resolve") else str(profile_path)


def _put_session(session_id: str, session: _SubtaskSession) -> None:
    if session_id in _SESSIONS:
        _SESSIONS.move_to_end(session_id)
        _SESSIONS[session_id] = session
        return
    while len(_SESSIONS) >= _MAX_SESSIONS:
        _SESSIONS.popitem(last=False)
    _SESSIONS[session_id] = session


def _drop_session(session_id: str) -> None:
    _SESSIONS.pop(session_id, None)


def _run_subtask_loop(
    *,
    child: Agent,
    sub_state: list[dict[str, Any]],
    paths: ConfigPaths,
    ctx: Context,
    display_name: str,
    show_progress: bool,
) -> tuple[int, str]:
    """Run nested decide/execute until assistant stop or turn cap. Returns (rounds, stopped_reason)."""
    capped_turns = _DEFAULT_SUBTASK_MAX_TURNS
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

    stopped_reason = (
        "max_turns_reached"
        if rounds >= capped_turns and sub_state and sub_state[-1].get("role") in ("user", "tool")
        else "completed"
    )
    return rounds, stopped_reason


class SubtaskAgentTool(Tool):
    """子任务委派工具：用子 profile 同步执行；可用 session_id 续跑同一子会话。"""

    name = "SubtaskAgent"
    description = (
        "Run a delegated subtask with a dedicated profile in a nested agent loop, "
        "then return the final assistant output. "
        "Pass session_id from a previous call to continue the same child conversation; "
        "pass close=true to discard the session after this turn. "
        "At most 3 follow-ups per session."
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
            "session_id": {
                "type": "string",
                "description": "Resume a prior subtask session. Omit to start a new session.",
            },
            "close": {
                "type": "boolean",
                "description": "If true, discard the session after this turn.",
                "default": False,
            },
        },
        "required": ["task_description"],
    }

    def execute(
        self,
        task_description: str,
        agent_name: str | None = None,
        show_progress: bool = True,
        session_id: str | None = None,
        close: bool = False,
        *,
        ctx: Context | None = None,
        **_: Any,
    ) -> ToolResult:
        task_text = str(task_description).strip()
        if not task_text:
            return ToolResult.failure("task_description is required", code="INVALID_ARGUMENTS")
        if ctx is None:
            return ToolResult.failure("SubtaskAgent requires host Context", code="INVALID_CONTEXT")

        paths = ctx.config_paths
        raw_session_id = str(session_id).strip() if session_id is not None else ""
        want_close = bool(close)

        try:
            if raw_session_id:
                session = _SESSIONS.get(raw_session_id)
                if session is None:
                    return ToolResult.failure(
                        f"Unknown session_id: {raw_session_id}",
                        code="SESSION_NOT_FOUND",
                    )
                if session.followups_used >= _MAX_FOLLOWUPS:
                    _drop_session(raw_session_id)
                    return ToolResult.failure(
                        f"Session follow-up limit reached ({_MAX_FOLLOWUPS}); start a new session.",
                        code="SESSION_FOLLOWUP_LIMIT",
                    )
                if agent_name and str(agent_name).strip():
                    profile_path = resolve_profile_path(agent_name, paths)
                    if _profile_key(profile_path) != session.profile_key:
                        return ToolResult.failure(
                            "agent_name does not match the session profile",
                            code="SESSION_AGENT_MISMATCH",
                        )
                child = session.agent
                sub_state = session.state
                sub_state.append(user_message([{"type": "text", "text": task_text}]))
                session.followups_used += 1
                active_id = raw_session_id
                followups_used = session.followups_used
            else:
                profile_path = resolve_profile_path(agent_name or "", paths)
                child = Agent.from_profile(profile_path, paths)
                sub_state = [user_message([{"type": "text", "text": task_text}])]
                active_id = uuid.uuid4().hex[:12]
                followups_used = 0
                session = _SubtaskSession(
                    profile_key=_profile_key(profile_path),
                    agent=child,
                    state=sub_state,
                    followups_used=0,
                )

            display_name = _resolve_display_agent_name(child, agent_name)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(
                f"Failed to initialize subtask agent: {type(exc).__name__}: {exc}",
                code="SUBTASK_INIT_FAILED",
            )

        try:
            rounds, stopped_reason = _run_subtask_loop(
                child=child,
                sub_state=sub_state,
                paths=paths,
                ctx=ctx,
                display_name=display_name,
                show_progress=show_progress,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(
                f"Subtask execution failed: {type(exc).__name__}: {exc}",
                code="SUBTASK_EXECUTION_FAILED",
            )

        # Persist or drop session memory
        hit_followup_cap = followups_used >= _MAX_FOLLOWUPS
        session_closed = want_close or hit_followup_cap
        if session_closed:
            _drop_session(active_id)
        else:
            session.state = sub_state
            session.followups_used = followups_used
            _put_session(active_id, session)

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
            "stopped_reason": stopped_reason,
            "session_id": active_id,
            "session_closed": session_closed,
            "followups_used": followups_used,
            "followups_remaining": max(0, _MAX_FOLLOWUPS - followups_used),
        }
        return ToolResult.success(result_data)


TOOL = SubtaskAgentTool
