from __future__ import annotations

from queue import Empty, Queue
from typing import Any

from harzoo.agent.agent import Agent
from harzoo.agent.components import QueueoutEmitter
from harzoo.agent.components.paths import ConfigPaths
from harzoo.agent.components.prompt import refresh_context_usage_slot
from harzoo.agent.kernel.message import assistant_message, tool_message, user_message
from harzoo.agent.kernel.tool import Context


def drain_queue_in(queue_in: Queue[dict[str, Any]]) -> list[dict[str, Any]]:
    """辅助函数：从队列中取出所有消息"""

    out = [queue_in.get()]
    while not queue_in.empty():
        try:
            out.append(queue_in.get_nowait())
        except Empty:
            break
    return out


def engine(queue_in: Queue[dict[str, Any]], queue_out: Queue[Any], config_paths: ConfigPaths) -> None:
    """引擎：执行智能体决策和工具调用"""

    emitter = QueueoutEmitter(queue_out)

    # ====== 初始化智能体 ======
    try:
        agent = Agent.from_profile(config_paths.startup_profile_path, config_paths)
        emitter.emit_llm_ready(agent.llm.llm_config.model_name, agent.profile.source_path.stem, max_context_tokens=agent.llm.llm_config.max_context_tokens)
    except Exception as exc:  # noqa: BLE001
        emitter.emit_error(f"{type(exc).__name__}: {exc}"[:8000])
        return

    # ====== 初始化会话状态 ======
    state: list[dict[str, Any]] = []

    while True:
        try:

            # ====== 更新会话状态 ======
            state.extend(drain_queue_in(queue_in))
            if not (state and state[-1].get("role") in ("user", "tool")):
                continue

            ctx = Context(state=state, agent=agent, config_paths=config_paths, emitter=emitter)

            # ====== 决策 ======
            try:
                emitter.emit_thinking_started()
                content, tool_calls, usage = agent.decide(state)
            finally:
                emitter.emit_thinking_finished()

            queue_in.put(assistant_message(content=content, tool_calls=tool_calls))
            emitter.emit_assistant_message(content, usage=usage)

            # ====== 执行工具 ======
            if isinstance(tool_calls, list) and tool_calls:
                for tool_call in tool_calls:
                    call_id, fn = str(tool_call["id"]), tool_call["function"]
                    tool_name, args_str = str(fn["name"]), str(fn["arguments"])
                    emitter.emit_tool_started(tool_name, call_id, args_str)
                    tool_result = agent.execute_tool_call(tool_name, args_str, ctx)
                    emitter.emit_tool_finished(call_id, tool_result)
                    queue_in.put(tool_message(call_id, tool_result))
                    if tool_result.injected_user_input_segments:
                        queue_in.put(user_message(tool_result.injected_user_input_segments))

            if usage:
                agent.llm.llm_config.system_prompt = refresh_context_usage_slot(agent.llm.llm_config.system_prompt, usage_payload=usage, max_context_tokens=agent.llm.llm_config.max_context_tokens)
        except Exception as exc:  # noqa: BLE001
            emitter.emit_error(f"{type(exc).__name__}: {exc}"[:8000])
