"""Switch the host session to another agent profile (model, endpoint, system prompt, tools)."""

from __future__ import annotations

from typing import Any

from harzoo.agent.components.paths import ConfigPaths, resolve_profile_path
from harzoo.agent.kernel.tool import Context, Tool, ToolResult

TOOL_VERSION = "2026-05-22"


class SwitchProfileTool(Tool):
    name = "SwitchProfile"
    description = (
        "Switch the main agent to a different profile (markdown under the agents config directory). "
        "Updates model, API endpoint, system prompt, and the tool list exposed to the model for subsequent turns. "
        "Only available in the main engine session (not inside a nested subtask)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "description": "Profile stem, relative path, or front matter name.",
            },
        },
        "required": ["agent_name"],
    }

    def execute(self, agent_name: str, *, ctx: Context | None = None, **_: Any) -> ToolResult:
        if ctx is None:
            return ToolResult.failure("SwitchProfile requires host Context", code="INVALID_CONTEXT")
        if ctx.emitter is None:
            return ToolResult.failure("SwitchProfile is not available in nested agent runs", code="INVALID_CONTEXT")

        raw = str(agent_name).strip()
        if not raw:
            return ToolResult.failure("agent_name is required", code="INVALID_ARGUMENTS")

        try:
            profile_path = resolve_profile_path(raw, ctx.config_paths)
            ctx.agent.rebind_profile(profile_path, config_paths=ctx.config_paths)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(f"{type(exc).__name__}: {exc}", code="SWITCH_PROFILE_FAILED")

        cfg = ctx.agent.llm.llm_config
        ctx.emitter.emit_llm_ready(
            cfg.model_name,
            profile_path.stem,
            max_context_tokens=cfg.max_context_tokens,
        )
        return ToolResult.success(
            {
                "profile_path": str(profile_path),
                "model_name": cfg.model_name,
                "max_context_tokens": cfg.max_context_tokens,
            }
        )


TOOL = SwitchProfileTool
