"""智能体 profile 解析与加载。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from harzoo.agent.components.util import load_yaml_front_matter_markdown


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


def load_profile_file(path: Path) -> AgentProfile:
    """加载主智能体 profile markdown 文件。"""

    front_matter, body = load_yaml_front_matter_markdown(path)
    raw_version = front_matter.get("profile_version")
    profile_version = None if raw_version is None else str(raw_version).strip() or None

    return AgentProfile(
        source_path=path.resolve(),
        profile_version=profile_version,
        api_key=str(front_matter["api_key"]).strip(),
        base_url=str(front_matter["base_url"]).strip(),
        model_name=str(front_matter["model_name"]).strip(),
        tool_names=tuple(sorted({p.strip() for p in str(front_matter.get("tool_names") or "").split(",") if p.strip()})),
        skill_names=tuple(sorted({p.strip() for p in str(front_matter.get("skill_names") or "").split(",") if p.strip()})),
        subagent_names=tuple(sorted({p.strip() for p in str(front_matter.get("subagent_names") or "").split(",") if p.strip()})),
        max_context_tokens=None if (_m := front_matter.get("max_context_tokens")) is None else int(_m),
        base_prompt=str(body),
    )
