"""Switch the host session to another agent profile (model, endpoint, system prompt, tools)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from harzoo.agent.components.paths import ConfigPaths, list_subagent_paths
from harzoo.agent.components.util import load_yaml_front_matter_markdown
from harzoo.agent.kernel.tool import Context, Tool, ToolResult

TOOL_VERSION = "2026-05-22"


def _profile_search_candidates(paths: ConfigPaths) -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []
    for candidate in (
        paths.startup_profile_path,
        *sorted({p.resolve() for p in paths.profiles_root.glob("*.md") if p.is_file()}),
        *list_subagent_paths(paths),
    ):
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            ordered.append(resolved)
    return ordered


def resolve_profile_path(raw: str, paths: ConfigPaths) -> Path:
    """将用户输入解析为 profile 文件路径。"""
    if not str(raw).strip():
        return paths.startup_profile_path.resolve()

    text = str(raw).strip()
    expanded = Path(text).expanduser()

    if expanded.is_absolute():
        resolved = expanded.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Profile not found: {resolved}")
        if resolved.suffix.lower() != ".md":
            raise ValueError(f"Profile must be a markdown file: {resolved}")
        return resolved

    under_profiles = (paths.profiles_root / expanded).resolve()
    if under_profiles.is_file():
        return under_profiles
    if under_profiles.suffix.lower() != ".md":
        with_suffix = under_profiles.with_suffix(".md")
        if with_suffix.is_file():
            return with_suffix.resolve()

    stem = expanded.stem if expanded.suffix else text
    direct = paths.profiles_root / f"{stem}.md"
    if direct.is_file():
        return direct.resolve()

    for candidate in list_subagent_paths(paths):
        if candidate.stem == stem or candidate.name == f"{stem}.md":
            return candidate.resolve()

    normalized = text.lower()
    for candidate in _profile_search_candidates(paths):
        try:
            meta, _ = load_yaml_front_matter_markdown(candidate)
        except (OSError, ValueError):
            continue
        name = str(meta.get("name") or "").strip().lower()
        if name == normalized:
            return candidate.resolve()

    raise FileNotFoundError(
        f"Agent profile {text!r} not found under {paths.profiles_root} (searched profiles directory)"
    )


class SwitchProfileTool(Tool):
    """主 profile 切换工具：切换模型、提示词与工具集合。"""

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
                "description": (
                    "Profile file stem or path: e.g. `coder`, `coder.md`, or an absolute path to a profile markdown file."
                ),
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

        if ctx.emitter is not None:
            cfg = ctx.agent.llm.llm_config
            ctx.emitter.emit_llm_ready(
                cfg.model_name,
                profile_path.stem,
                max_context_tokens=cfg.max_context_tokens,
            )

        return ToolResult.success(
            {
                "profile_path": str(profile_path),
                "model_name": ctx.agent.llm.llm_config.model_name,
                "max_context_tokens": ctx.agent.llm.llm_config.max_context_tokens,
            }
        )


TOOL = SwitchProfileTool
