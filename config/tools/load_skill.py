"""LoadSkill — 按 name 加载 config/skills 下的 skill 正文并注入上下文。"""


from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from harzoo.agent.kernel.tool import Context, Tool, ToolResult

TOOL_VERSION = "2026-06-26"


def _load_yaml_front_matter_markdown(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        raise ValueError(f"{path}: file must start with --- front matter")
    closing = raw.find("\n---\n", 3)
    if closing == -1:
        raise ValueError(f"{path}: missing closing --- for front matter")
    front_matter, body = raw[3:closing].strip(), raw[closing + 5 :].lstrip("\n").rstrip("\n")
    loaded = yaml.safe_load(front_matter)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: front matter must be a YAML mapping")
    return loaded, body


def _normalize_skill_name(name: str) -> str:
    return name.strip().lower()


def _find_skill_file(skills_root: Path, skill_name: str) -> Path | None:
    target = _normalize_skill_name(skill_name)
    if not target:
        return None
    for path in sorted(skills_root.glob("*.md")):
        if not path.is_file():
            continue
        try:
            meta, _body = _load_yaml_front_matter_markdown(path)
        except ValueError:
            continue
        declared = str(meta.get("name") or "").strip()
        if declared and _normalize_skill_name(declared) == target:
            return path.resolve()
    return None


def _format_skill_injection(canonical_name: str, body: str) -> str:
    return f"[SKILL: {canonical_name}]\n{body.rstrip()}\n[/SKILL]"


class LoadSkillTool(Tool):
    """按 name 加载 config/skills 下的 skill；正文注入后续对话上下文。"""

    name = "LoadSkill"
    description = (
        "Load a skill by name from config/skills/. "
        "Injects skill body into context for subsequent turns."
    )
    parameters = {
        "properties": {
            "name": {"type": "string", "description": "Skill name as listed under Skills in system prompt"},
        },
        "required": ["name"],
    }

    def execute(self, name: str, *, ctx: Context | None = None, **_: Any) -> ToolResult:
        if ctx is None:
            return ToolResult.failure("LoadSkill requires Context", code="INVALID_CONTEXT")

        skill_name = str(name or "").strip()
        if not skill_name:
            return ToolResult.failure("name must not be empty", code="INVALID_ARGUMENTS")

        skills_root = ctx.config_paths.skills_root.resolve()
        skill_path = _find_skill_file(skills_root, skill_name)
        if skill_path is None:
            return ToolResult.failure(
                f"Skill file not found for name: {skill_name}",
                code="SKILL_NOT_FOUND",
                data={"requested_name": skill_name, "skills_root": str(skills_root)},
            )

        try:
            meta, body = _load_yaml_front_matter_markdown(skill_path)
        except ValueError as exc:
            return ToolResult.failure(str(exc), code="SKILL_READ_ERROR", data={"file_path": str(skill_path)})

        canonical_name = str(meta.get("name") or skill_name).strip() or skill_name
        description = " ".join(str(meta.get("description") or "").split()).strip()
        injection_text = _format_skill_injection(canonical_name, body)

        return ToolResult.success(
            {
                "name": canonical_name,
                "description": description,
                "file_path": str(skill_path),
                "chars_loaded": len(body),
                "loaded": True,
            },
            injected_user_input_segments=[{"type": "text", "text": injection_text}],
        )


TOOL = LoadSkillTool
