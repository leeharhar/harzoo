"""CompactContext — 会话太长时，由 Agent 自己调用来「腾地方」。

策略（三句话）
--------------
1. **大段 tool 输出（日志、文件正文、网页）**：删掉正文，只留简短摘要（路径、命令、前几行）。
2. **最近几轮对话 + 你正在做的任务**：尽量原样保留。
3. **压缩前用 [PIN]...[/PIN] 写下不能忘的事**（规则、待办、路径）；工具会钉在摘要里。

用法：Self state 里 context 偏高，或刚跑完很大的 Shell/Read 时，Agent 调用
CompactContext()，无需参数。若返回 compact_again，可再压一次。

说明：Engine 不会自动压缩；压完后旧日志不能复原，需要时再 Read/Grep 查。
常量与实现细节见本文件下方代码。
"""


from __future__ import annotations

import copy
import json
import re
from typing import Any

from harzoo.agent.kernel.llm import LLM
from harzoo.agent.kernel.message import assistant_message, tool_message, user_message
from harzoo.agent.kernel.tool import Context, Tool, ToolResult

TOOL_VERSION = "2026-06-26"

_SUMMARY_HEADER = "[CONTEXT_SUMMARY]"
_PIN_BLOCK_RE = re.compile(r"\[PIN\]([\s\S]*?)\[/PIN\]", re.IGNORECASE)
_GENERATION_RE = re.compile(r"^\[CONTEXT_SUMMARY\]\s*v(\d+)", re.IGNORECASE)

# 策略常量（实现用，一般无需改）
_KEEP_TURN_COUNT = 2
_STUB_PREVIEW_CHARS = 200
_STUB_PREVIEW_LINES = 15
_ASSISTANT_MAX_CHARS = 800
_FOLD_TRANSCRIPT_MAX_CHARS = 8_000
_SUMMARY_MAX_TOKENS = 800
_LLM_MERGE_USAGE_PCT = 75.0
_RECOMMEND_AGAIN_THRESHOLD_PCT = 65.0


def _message_text(msg: dict[str, Any]) -> str:
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(part.get("text", "")) for part in content if part.get("type") == "text")
    return str(content or "")


def _estimate_chars(state: list[dict[str, Any]]) -> int:
    return sum(len(json.dumps(msg, ensure_ascii=False, default=str)) for msg in state)


def _estimate_usage_pct(state: list[dict[str, Any]], max_context_tokens: int | None) -> float:
    cap = max(int(max_context_tokens or 0), 1)
    return min(100.0, (_estimate_chars(state) / 4) / cap * 100.0)


def _find_last_user_index(state: list[dict[str, Any]]) -> int:
    for idx in range(len(state) - 1, -1, -1):
        if state[idx].get("role") == "user":
            return idx
    return -1


def _split_turns(state: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    turns: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for msg in state:
        if msg.get("role") == "user" and current:
            turns.append(current)
            current = []
        current.append(msg)
    if current:
        turns.append(current)
    return turns


def _validate_message_chain(state: list[dict[str, Any]]) -> bool:
    pending_call_ids: set[str] = set()
    for msg in state:
        role = msg.get("role")
        if role == "assistant":
            for tool_call in msg.get("tool_calls") or []:
                pending_call_ids.add(str(tool_call["id"]))
        elif role == "tool":
            call_id = str(msg.get("tool_call_id", ""))
            if call_id not in pending_call_ids:
                return False
            pending_call_ids.discard(call_id)
        elif role == "user" and pending_call_ids:
            return False
    return not pending_call_ids


def _partition_state(
    state: list[dict[str, Any]],
    *,
    keep_turns: int = _KEEP_TURN_COUNT,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    if not state:
        return [], [], 0

    last_user_idx = _find_last_user_index(state)
    if last_user_idx < 0:
        return [], list(state), 0

    protected = state[last_user_idx:]
    before_protected = state[:last_user_idx]
    if not before_protected:
        return [], protected, len(protected)

    turns_before = _split_turns(before_protected)
    turn_count = min(keep_turns, len(turns_before))
    while turn_count <= len(turns_before):
        tail_turns = turns_before[-turn_count:] if turn_count > 0 else []
        tail = [msg for turn in tail_turns for msg in turn]
        candidate = tail + protected
        if _validate_message_chain(candidate):
            head_turns = turns_before[:-turn_count] if turn_count > 0 else turns_before
            head = [msg for turn in head_turns for msg in turn]
            return head, candidate, len(protected)
        turn_count += 1

    return [], list(state), len(protected)


def _collect_pins(state: list[dict[str, Any]]) -> list[str]:
    """从 assistant 消息的 [PIN]...[/PIN] 块收集必留信息。"""
    pins: list[str] = []
    seen: set[str] = set()
    for msg in state:
        if msg.get("role") != "assistant":
            continue
        for match in _PIN_BLOCK_RE.finditer(_message_text(msg)):
            block = match.group(1).strip()
            for line in block.splitlines():
                item = line.strip().lstrip("-•*").strip()
                if item and item not in seen:
                    seen.add(item)
                    pins.append(item)
    return pins


def _preview_text(value: str, *, max_chars: int = _STUB_PREVIEW_CHARS) -> str:
    text = value.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"...[{len(text) - max_chars} more chars]"


def _tool_payload_to_stub(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    dropped = 0
    data = payload.get("data")
    if not isinstance(data, dict):
        raw = json.dumps(payload, ensure_ascii=False, default=str)
        dropped = max(0, len(raw) - _STUB_PREVIEW_CHARS)
        return {"kind": "tool_stub", "tool": "Unknown", "preview": _preview_text(raw)}, dropped

    if "stdout" in data or "shell_used" in data:
        stdout = str(data.get("stdout") or "")
        stderr = str(data.get("stderr") or "")
        dropped = len(stdout) + len(stderr)
        return (
            {
                "kind": "tool_stub",
                "tool": "Shell",
                "exit_code": data.get("exit_code"),
                "cmd": data.get("command"),
                "stdout_chars": len(stdout),
                "stderr_chars": len(stderr),
                "preview": _preview_text(stdout or stderr),
            },
            dropped,
        )

    if "resolved_file_path" in data or ("text" in data and "file_path" in data):
        text = str(data.get("text") or "")
        dropped = len(text)
        lines = text.splitlines()
        return (
            {
                "kind": "tool_stub",
                "tool": "Read",
                "path": data.get("resolved_file_path") or data.get("file_path"),
                "lines": data.get("line_count", len(lines)),
                "preview_lines": lines[:_STUB_PREVIEW_LINES],
            },
            dropped,
        )

    if "matches" in data or "counts" in data:
        matches = data.get("matches")
        if isinstance(matches, list):
            preview = matches[:3]
            dropped = sum(len(str(item)) for item in matches[3:])
        else:
            preview = data.get("counts")
            dropped = 0
        return (
            {
                "kind": "tool_stub",
                "tool": "Grep",
                "count": data.get("count") or data.get("total"),
                "pattern_meta": data.get("requested_path") or data.get("resolved_path"),
                "preview": preview,
            },
            dropped,
        )

    if "url" in data and "text" in data:
        text = str(data.get("text") or "")
        dropped = len(text)
        return (
            {
                "kind": "tool_stub",
                "tool": "WebFetch",
                "url": data.get("url"),
                "text_chars": len(text),
                "preview": _preview_text(text),
            },
            dropped,
        )

    raw = json.dumps(data, ensure_ascii=False, default=str)
    dropped = max(0, len(raw) - _STUB_PREVIEW_CHARS)
    return {"kind": "tool_stub", "tool": "Tool", "preview": _preview_text(raw), "meta": {k: data[k] for k in list(data)[:5]}}, dropped


def _tool_content_to_stub(content: str) -> tuple[str, int]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        dropped = max(0, len(content) - _STUB_PREVIEW_CHARS)
        stub = {"kind": "tool_stub", "tool": "Tool", "preview": _preview_text(content)}
        return json.dumps(stub, ensure_ascii=False), dropped

    if not isinstance(payload, dict):
        dropped = max(0, len(content) - _STUB_PREVIEW_CHARS)
        return json.dumps({"kind": "tool_stub", "preview": _preview_text(content)}, ensure_ascii=False), dropped

    stub, dropped = _tool_payload_to_stub(payload)
    return json.dumps(stub, ensure_ascii=False), dropped


def _dedupe_key_for_stub(stub_json: str) -> str | None:
    try:
        stub = json.loads(stub_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(stub, dict):
        return None
    tool = stub.get("tool")
    if tool == "Read":
        return f"read:{stub.get('path')}"
    if tool == "Shell":
        return f"shell:{stub.get('cmd')}"
    return None


def _normalize_user_message(msg: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(msg)
    content = normalized.get("content")
    if not isinstance(content, list):
        return normalized
    parts: list[Any] = []
    for part in content:
        if part.get("type") in ("image_path", "image_url"):
            parts.append({"type": "text", "text": "[image omitted]"})
        else:
            parts.append(part)
    normalized["content"] = parts
    return normalized


def _normalize_assistant_message(msg: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(msg)
    text = _message_text(normalized)
    if len(text) > _ASSISTANT_MAX_CHARS:
        normalized = assistant_message(content=text[:_ASSISTANT_MAX_CHARS] + f"...[{len(text) - _ASSISTANT_MAX_CHARS} more chars]")
        if normalized.get("tool_calls"):
            normalized["tool_calls"] = msg.get("tool_calls")
    return normalized


def _tool_result_from_stub_json(stub_content: str) -> ToolResult:
    try:
        data = json.loads(stub_content)
    except json.JSONDecodeError:
        data = {"preview": stub_content}
    return ToolResult.success(data)


def _process_messages_for_tail(
    messages: list[dict[str, Any]],
    *,
    stub_tools: bool,
    stats: dict[str, Any],
) -> list[dict[str, Any]]:
    latest_stub_by_key: dict[str, str] = {}
    ordered: list[tuple[str | None, dict[str, Any]]] = []

    for msg in messages:
        role = msg.get("role")
        if role == "tool" and stub_tools:
            content = str(msg.get("content", ""))
            stub_content, dropped = _tool_content_to_stub(content)
            stats["stubbed_tools"] = int(stats.get("stubbed_tools", 0)) + 1
            stats["dropped_chars"] = int(stats.get("dropped_chars", 0)) + dropped
            key = _dedupe_key_for_stub(stub_content)
            if key:
                latest_stub_by_key[key] = stub_content
                ordered.append((key, tool_message(str(msg.get("tool_call_id", "")), _tool_result_from_stub_json(stub_content))))
            else:
                ordered.append((None, tool_message(str(msg.get("tool_call_id", "")), _tool_result_from_stub_json(stub_content))))
            continue
        if role == "user":
            ordered.append((None, _normalize_user_message(msg)))
        elif role == "assistant":
            ordered.append((None, _normalize_assistant_message(msg)))
        else:
            ordered.append((None, copy.deepcopy(msg)))

    if not stub_tools:
        return [item for _, item in ordered]

    seen_keys: set[str] = set()
    result: list[dict[str, Any]] = []
    for key, msg in reversed(ordered):
        if key and key in seen_keys:
            stats["deduped_tools"] = int(stats.get("deduped_tools", 0)) + 1
            continue
        if key:
            seen_keys.add(key)
        result.append(msg)
    result.reverse()
    return result


def _extract_prior_summary(head: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    if not head:
        return None, head
    text = _message_text(head[0])
    if not text.startswith(_SUMMARY_HEADER):
        return None, head
    body = text[len(_SUMMARY_HEADER) :].lstrip()
    if body.lower().startswith("v") and "\n" in body:
        body = body.split("\n", 1)[1]
    return body.strip() or None, head[1:]


def _parse_generation(text: str) -> int:
    match = _GENERATION_RE.match(text.strip())
    if match:
        return max(1, int(match.group(1)))
    return 1


def _next_summary_generation(state: list[dict[str, Any]]) -> int:
    generation = 0
    for msg in state:
        text = _message_text(msg)
        if text.startswith(_SUMMARY_HEADER):
            generation = max(generation, _parse_generation(text))
    return max(1, generation + 1)


def _messages_to_transcript(messages: list[dict[str, Any]], *, stub_tools: bool, stats: dict[str, Any]) -> str:
    latest_stub_by_key: dict[str, str] = {}
    lines_by_key: dict[str | None, str] = {}
    order: list[str | None] = []

    for msg in messages:
        role = msg.get("role")
        if role == "user":
            text = _message_text(msg)
            if text.startswith(_SUMMARY_HEADER):
                continue
            key: str | None = None
            line = f"U: {text[:500]}"
        elif role == "assistant":
            key = None
            text = _message_text(msg)[:_ASSISTANT_MAX_CHARS]
            tool_calls = msg.get("tool_calls") or []
            if tool_calls:
                names = [str(call.get("function", {}).get("name", "")) for call in tool_calls]
                line = f"A: {text or '(tool call)'} [{', '.join(name for name in names if name)}]"
            else:
                line = f"A: {text}"
        elif role == "tool":
            content = str(msg.get("content", ""))
            if stub_tools:
                stub_content, dropped = _tool_content_to_stub(content)
                stats["stubbed_tools"] = int(stats.get("stubbed_tools", 0)) + 1
                stats["dropped_chars"] = int(stats.get("dropped_chars", 0)) + dropped
                key = _dedupe_key_for_stub(stub_content)
                if key and key in latest_stub_by_key:
                    stats["deduped_tools"] = int(stats.get("deduped_tools", 0)) + 1
                    continue
                if key:
                    latest_stub_by_key[key] = stub_content
                line = f"T: {stub_content}"
            else:
                key = None
                line = f"T: {content[:_STUB_PREVIEW_CHARS]}"
        else:
            continue

        if key not in lines_by_key:
            order.append(key)
        lines_by_key[key] = line

    return "\n".join(lines_by_key[key] for key in order if key in lines_by_key)


def _parse_summary_json(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return {"narrative": text}


def _merge_pins(summary: dict[str, Any], pins: list[str]) -> dict[str, Any]:
    if not pins:
        return summary
    merged = dict(summary)
    existing = merged.get("constraints")
    if isinstance(existing, list):
        constraints = [str(item) for item in existing]
    elif isinstance(existing, str) and existing.strip():
        constraints = [existing.strip()]
    else:
        constraints = []
    for pin in pins:
        if pin not in constraints:
            constraints.append(pin)
    merged["constraints"] = constraints
    merged["pins"] = pins
    return merged


def _mechanical_summary(prior_summary: str | None, pins: list[str], transcript: str) -> str:
    summary = _merge_pins(_parse_summary_json(prior_summary), pins)
    if transcript.strip():
        archived = summary.get("archived_transcript")
        if isinstance(archived, str) and archived.strip():
            summary["archived_transcript"] = archived.rstrip() + "\n" + transcript
        else:
            summary["archived_transcript"] = transcript
    return json.dumps(summary, ensure_ascii=False, indent=2)


def _should_llm_merge(
    *,
    transcript: str,
    prior_summary: str | None,
    usage_before_pct: float,
) -> bool:
    if prior_summary and transcript.strip():
        return True
    if len(transcript) >= _FOLD_TRANSCRIPT_MAX_CHARS:
        return True
    return usage_before_pct >= _LLM_MERGE_USAGE_PCT and len(transcript) > 0


def _llm_merge_summary(
    *,
    prior_summary: str | None,
    pins: list[str],
    transcript: str,
    llm: LLM,
) -> str:
    user_content = (
        "Merge into JSON with keys goal, done, decisions, constraints, todo, open_questions, files.\n"
        "Use facts only; mark uncertain items as unknown. Output JSON only.\n\n"
    )
    if prior_summary:
        user_content += f"[PRIOR_SUMMARY]\n{prior_summary}\n\n"
    if pins:
        user_content += "[PINS]\n" + "\n".join(f"- {pin}" for pin in pins) + "\n\n"
    user_content += f"[FOLDED_HISTORY]\n{transcript}"

    response = llm.client.chat.completions.create(
        model=llm.llm_config.model_name,
        messages=[
            {"role": "system", "content": "You are a precise conversation summarizer."},
            {"role": "user", "content": user_content},
        ],
        max_tokens=_SUMMARY_MAX_TOKENS,
        temperature=0,
    )
    text = str(response.choices[0].message.content or "").strip()
    merged = _merge_pins(_parse_summary_json(text), pins)
    return json.dumps(merged, ensure_ascii=False, indent=2)


def _build_summary_message(summary_text: str, generation: int) -> dict[str, Any]:
    return user_message([{"type": "text", "text": f"{_SUMMARY_HEADER} v{generation}\n{summary_text}"}])


class CompactContextTool(Tool):
    """Agent 自主调用的会话压缩工具；策略见文件顶部说明。"""

    name = "CompactContext"
    description = (
        "Free context when usage is high or after large Shell/Read output. No arguments. "
        "Wrap must-keep facts in [PIN]...[/PIN] before calling. "
        "If recommendation is compact_again, call once more."
    )
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    def execute(self, *, ctx: Context | None = None, **_: Any) -> ToolResult:
        """执行压缩；策略见文件顶部说明。"""
        if ctx is None:
            return ToolResult.failure("CompactContext requires Context", code="INVALID_CONTEXT")
        if not isinstance(ctx.agent.llm, LLM):
            return ToolResult.failure("CompactContext requires host LLM", code="INVALID_CONTEXT")

        state = ctx.state
        llm_config = ctx.agent.llm.llm_config
        max_context_tokens = llm_config.max_context_tokens if llm_config is not None else None
        max_int = max(int(max_context_tokens or 0), 1)
        usage_before = _estimate_usage_pct(state, max_context_tokens)

        head, tail, protected_count = _partition_state(state)
        if not head:
            return ToolResult.failure("Nothing to compact", code="INVALID_STATE")

        before_count = len(state)
        stats: dict[str, Any] = {"stubbed_tools": 0, "deduped_tools": 0, "dropped_chars": 0, "pins_kept": 0, "llm_summarize_used": False}
        pins = _collect_pins(state)
        stats["pins_kept"] = len(pins)

        prior_summary, head_rest = _extract_prior_summary(head)
        transcript = _messages_to_transcript(head_rest, stub_tools=True, stats=stats)

        protected_count = min(protected_count, len(tail))
        tail_prefix = tail[:-protected_count] if protected_count > 0 else tail
        tail_protected = tail[-protected_count:] if protected_count > 0 else []
        processed_tail = _process_messages_for_tail(tail_prefix, stub_tools=True, stats=stats) + _process_messages_for_tail(
            tail_protected, stub_tools=False, stats=stats
        )

        llm_used = _should_llm_merge(transcript=transcript, prior_summary=prior_summary, usage_before_pct=usage_before)
        if llm_used:
            try:
                merged = _llm_merge_summary(prior_summary=prior_summary, pins=pins, transcript=transcript, llm=ctx.agent.llm)
            except Exception as exc:  # noqa: BLE001
                return ToolResult.failure(
                    f"Summarization failed: {type(exc).__name__}: {exc}",
                    code="COMPACT_FAILED",
                )
            if not merged:
                return ToolResult.failure("Summarizer returned empty text", code="COMPACT_FAILED")
            stats["llm_summarize_used"] = True
            summary_text = merged
        else:
            summary_text = _mechanical_summary(prior_summary, pins, transcript)

        compacted = [_build_summary_message(summary_text, _next_summary_generation(state))] + processed_tail

        if not _validate_message_chain(compacted):
            return ToolResult.failure("Invalid message chain after compact", code="COMPACT_FAILED")

        state.clear()
        state.extend(compacted)

        usage_after = _estimate_usage_pct(state, max_context_tokens)
        recommendation = "compact_again" if usage_after >= _RECOMMEND_AGAIN_THRESHOLD_PCT else "continue"

        if ctx.emitter is not None:
            ctx.emitter.emit_context_compacted(
                prompt_tokens=int(round(usage_after / 100.0 * max_int)),
                max_context_tokens=max_int,
                before_messages=before_count,
                after_messages=len(state),
            )

        return ToolResult.success(
            {
                "ok": True,
                "usage_before_est_pct": round(usage_before, 1),
                "usage_after_est_pct": round(usage_after, 1),
                "recommendation": recommendation,
                "stats": stats,
            }
        )


TOOL = CompactContextTool
