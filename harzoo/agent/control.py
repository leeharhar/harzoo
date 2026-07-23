"""TUI control 消息：Engine 侧会话突变（reset / switch_profile）。"""

from __future__ import annotations

from typing import Any

from harzoo.agent.agent import Agent
from harzoo.agent.components import QueueoutEmitter
from harzoo.agent.components.paths import ConfigPaths, resolve_profile_path


def control_message(action: str, **payload: Any) -> dict[str, Any]:
    return {"role": "control", "action": action, **payload}


def handle_control(
    ctrl: dict[str, Any],
    *,
    agent: Agent,
    state: list[dict[str, Any]],
    emitter: QueueoutEmitter,
    config_paths: ConfigPaths,
) -> None:
    action = str(ctrl.get("action", "")).strip()
    if action == "reset":
        state.clear()
        emitter.emit_session_reset()
        return

    if action == "switch_profile":
        query = str(ctrl.get("query", "")).strip()
        if not query:
            emitter.emit_error("switch_profile requires a non-empty query")
            return
        try:
            profile_path = resolve_profile_path(query, config_paths)
            agent.rebind_profile(profile_path, config_paths=config_paths)
        except Exception as exc:  # noqa: BLE001
            emitter.emit_error(f"{type(exc).__name__}: {exc}"[:8000])
            return
        cfg = agent.llm.llm_config
        emitter.emit_llm_ready(
            cfg.model_name,
            profile_path.stem,
            max_context_tokens=cfg.max_context_tokens,
        )
        return

    emitter.emit_error(f"Unknown control action: {action!r}")
