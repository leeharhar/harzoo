"""智能体 profile 解析与加载。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from harzoo.agent.components.util import load_yaml_front_matter_markdown


def resolve_placeholder(raw: str, placeholder_values: dict[str, str]) -> str:
    """若整段值等于 placeholder_values 的键，则替换；否则原样返回。"""

    text = str(raw).strip()
    if text in placeholder_values:
        return str(placeholder_values[text]).strip()
    return text


@dataclass(frozen=True, slots=True)
class AgentProfile:
    """智能体 markdown profile 的 YAML 头与正文（尚未绑定工具或拼接提示词）。"""

    source_path: Path
    profile_version: str | None
    api_key: str
    base_url: str
    model_name: str
    tool_names: tuple[str, ...]
    skill_names: tuple[str, ...]
    subagent_names: tuple[str, ...]
    max_context_tokens: int | None
    base_prompt: str


def load_profile_file(
    path: Path,
    *,
    placeholder_values: dict[str, str] | None = None,
) -> AgentProfile:
    """加载主智能体 profile markdown 文件。"""

    placeholders = placeholder_values or {}
    front_matter, body = load_yaml_front_matter_markdown(path)
    raw_version = front_matter.get("profile_version")
    profile_version = None if raw_version is None else str(raw_version).strip() or None

    raw_max_context = front_matter.get("max_context_tokens")
    if raw_max_context is None:
        max_context_tokens: int | None = None
    else:
        resolved_max = resolve_placeholder(str(raw_max_context), placeholders)
        max_context_tokens = None if not resolved_max else int(resolved_max)

    return AgentProfile(
        source_path=path.resolve(),
        profile_version=profile_version,
        api_key=resolve_placeholder(str(front_matter["api_key"]), placeholders),
        base_url=resolve_placeholder(str(front_matter["base_url"]), placeholders),
        model_name=resolve_placeholder(str(front_matter["model_name"]), placeholders),
        tool_names=tuple(sorted({p.strip() for p in str(front_matter.get("tool_names") or "").split(",") if p.strip()})),
        skill_names=tuple(sorted({p.strip() for p in str(front_matter.get("skill_names") or "").split(",") if p.strip()})),
        subagent_names=tuple(sorted({p.strip() for p in str(front_matter.get("subagent_names") or "").split(",") if p.strip()})),
        max_context_tokens=max_context_tokens,
        base_prompt=str(body),
    )
