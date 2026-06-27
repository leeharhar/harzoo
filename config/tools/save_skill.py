"""SaveSkill — 创建或更新 config/skills 下的 skill 文件。"""


from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from harzoo.agent.kernel.tool import Context, Tool, ToolResult

TOOL_VERSION = "2026-06-26"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


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


def _slug_from_name(name: str) -> str:
    slug = _SLUG_RE.sub("-", _normalize_skill_name(name)).strip("-")
    return slug or ""


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


def _render_skill_markdown(*, name: str, description: str, body: str) -> str:
    desc = " ".join(description.split())
    return f"---\nname: {name.strip()}\ndescription: {desc}\n---\n\n{body.rstrip()}\n"


class SaveSkillTool(Tool):
    """写入 config/skills/ 下的 skill markdown；与 profile 无关。"""

    name = "SaveSkill"
    description = (
        "Create or update a skill under config/skills/. "
        "Provide name, description, and markdown body (without YAML front matter)."
    )
    parameters = {
        "properties": {
            "name": {"type": "string", "description": "Skill name (stored in front matter)"},
            "description": {"type": "string", "description": "One-line summary for the skills catalog"},
            "body": {"type": "string", "description": "Markdown body only, no --- front matter"},
            "mode": {
                "type": "string",
                "enum": ["create", "replace_body"],
                "description": "create: new skill only; replace_body: update existing skill body",
                "default": "create",
            },
        },
        "required": ["name", "description", "body"],
    }

    def execute(
        self,
        name: str,
        description: str,
        body: str,
        mode: str = "create",
        *,
        ctx: Context | None = None,
        **_: Any,
    ) -> ToolResult:
        if ctx is None:
            return ToolResult.failure("SaveSkill requires Context", code="INVALID_CONTEXT")

        skill_name = str(name or "").strip()
        skill_description = str(description or "").strip()
        skill_body = str(body or "")
        write_mode = str(mode or "create").strip().lower()

        if not skill_name:
            return ToolResult.failure("name must not be empty", code="INVALID_ARGUMENTS")
        if not skill_description:
            return ToolResult.failure("description must not be empty", code="INVALID_ARGUMENTS")
        if not skill_body.strip():
            return ToolResult.failure("body must not be empty", code="INVALID_ARGUMENTS")
        if write_mode not in ("create", "replace_body"):
            return ToolResult.failure("mode must be create or replace_body", code="INVALID_ARGUMENTS")

        slug = _slug_from_name(skill_name)
        if not slug:
            return ToolResult.failure("name must contain at least one alphanumeric character", code="INVALID_ARGUMENTS")

        skills_root = ctx.config_paths.skills_root.resolve()
        skills_root.mkdir(parents=True, exist_ok=True)
        existing = _find_skill_file(skills_root, skill_name)

        if write_mode == "create":
            if existing is not None:
                return ToolResult.failure(
                    f"Skill already exists: {skill_name}",
                    code="SKILL_EXISTS",
                    data={"name": skill_name, "file_path": str(existing)},
                )
            target_path = skills_root / f"{slug}.md"
        else:
            if existing is None:
                return ToolResult.failure(
                    f"Skill not found: {skill_name}",
                    code="SKILL_NOT_FOUND",
                    data={"requested_name": skill_name, "skills_root": str(skills_root)},
                )
            target_path = existing

        content = _render_skill_markdown(name=skill_name, description=skill_description, body=skill_body)
        try:
            target_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return ToolResult.failure(str(exc), code="SKILL_WRITE_ERROR", data={"file_path": str(target_path)})

        return ToolResult.success(
            {
                "name": skill_name,
                "description": skill_description,
                "file_path": str(target_path.resolve()),
                "mode": write_mode,
                "chars_written": len(content),
                "saved": True,
            }
        )


TOOL = SaveSkillTool
