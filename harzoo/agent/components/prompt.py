"""系统提示词组装：profile 正文、Skills/Subagents 目录、运行环境。

自上而下：Skills 目录 → Subagents 目录 → 运行环境 → assemble_system_prompt。
"""

from __future__ import annotations

import os
import platform
from datetime import date
from collections.abc import Sequence
from pathlib import Path

from harzoo.agent.components.util import load_yaml_front_matter_markdown

# ---------------------------------------------------------------------------
# 子智能体目录（磁盘 YAML front matter → markdown 段落）
# ---------------------------------------------------------------------------

def _collect_catalog_items(
    candidates: Sequence[Path],
    declarations: Sequence[str],
    key: str,
    *,
    ignore_invalid_candidates: bool = False,
) -> list[tuple[str, str]]:
    """按声明名称从 markdown 文件解析 (name, description)。"""

    catalog: dict[str, tuple[str, str]] = {}
    for candidate in candidates:
        if not candidate.is_file():
            continue
        meta_raw, _body = load_yaml_front_matter_markdown(candidate)
        name = str(meta_raw.get("name") or "").strip()
        if not name:
            if ignore_invalid_candidates:
                continue
            raise ValueError(f"{candidate}: missing required 'name'")
        description = " ".join(str(meta_raw.get("description") or "").split()).strip()
        if not description:
            if ignore_invalid_candidates:
                continue
            raise ValueError(f"{candidate}: missing required 'description'")
        catalog[name.lower()] = (name, description)

    items: list[tuple[str, str]] = []
    for declared_name in declarations:
        normalized = declared_name.strip().lower()
        if not normalized:
            raise ValueError(f"front matter '{key}' has an empty declared name")
        if normalized not in catalog:
            raise ValueError(
                f"Declared name '{declared_name}' from '{key}' not found in configured paths"
            )
        items.append(catalog[normalized])
    return items


def _format_catalog_subsection(heading: str, items: Sequence[tuple[str, str]]) -> str:
    """生成一个 ### markdown 块；无条目时返回空字符串。"""

    if not items:
        return ""
    bullet_lines = [
        f"- {name}: {description}" if description else f"- {name}"
        for name, description in sorted(set(items), key=lambda item: item[0].lower())
    ]
    return "\n".join([heading, *bullet_lines])


def build_subagents_section(*, subagent_names: Sequence[str], subagent_paths: list[Path]) -> str:
    """允许的子智能体 markdown 目录；未配置时返回空字符串。"""

    if not subagent_names:
        return ""

    subagent_items = _collect_catalog_items(
        subagent_paths,
        subagent_names,
        "subagent_names",
        ignore_invalid_candidates=True,
    )

    if not subagent_items:
        return ""

    base_section = "## Allowed Subagents"
    subagents_section = _format_catalog_subsection("### Subagents", subagent_items)

    parts = [base_section, subagents_section]

    return "\n".join(p for p in parts if p)


def _collect_all_catalog_items(candidates: Sequence[Path]) -> list[tuple[str, str]]:
    """扫描目录下全部 markdown，解析 (name, description)。"""

    items: list[tuple[str, str]] = []
    seen: set[str] = set()
    for candidate in sorted(candidates, key=lambda p: p.name.lower()):
        if not candidate.is_file():
            continue
        try:
            meta_raw, _body = load_yaml_front_matter_markdown(candidate)
        except ValueError:
            continue
        name = str(meta_raw.get("name") or "").strip()
        if not name:
            continue
        description = " ".join(str(meta_raw.get("description") or "").split()).strip()
        if not description:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append((name, description))
    return items


def build_skills_section(*, skill_manifests: list[Path]) -> str:
    """config/skills 下全部 skill 目录；无 skill 时返回空字符串。"""

    skill_items = _collect_all_catalog_items(skill_manifests)
    if not skill_items:
        return ""

    base_section = (
        "## Skills\n\n"
        "Skills live under config/skills/. When a task matches a skill description, call LoadSkill(name) before proceeding."
    )
    skills_section = _format_catalog_subsection("### Available skills", skill_items)

    parts = [base_section, skills_section]

    return "\n".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# 运行环境（注入给模型的环境信息）
# ---------------------------------------------------------------------------


def _detect_shell_label() -> str:
    system_name = platform.system().lower().strip()
    os_label = {"darwin": "macOS", "windows": "Windows"}.get(system_name, "Linux")
    if system_name == "windows":
        shell = "powershell"
    else:
        shell = Path(os.environ.get("SHELL", "")).name or "bash"
    return f"{shell} ({os_label})"


def build_runtime_environment_section(*, workspace_root: Path) -> str:
    """运行环境信息，位于 ## Runtime Environment 下。"""

    facts = "\n".join(
        (
            f"Workspace: {workspace_root.resolve()}",
            f"Shell: {_detect_shell_label()}",
            f"Date: {date.today().isoformat()}",
            "",
            "Relative paths in file tools resolve against Workspace. "
            "If unsure of a file location, use Glob or Grep first.",
        )
    )
    return f"## Runtime Environment\n\n{facts}"


def assemble_system_prompt(
    *,
    base_prompt: str,
    skill_manifests: list[Path],
    subagent_names: Sequence[str],
    subagent_paths: list[Path],
    workspace_root: Path,
) -> str:
    # 拼接顺序：正文 → Skills 目录 → Subagents 目录 → 运行环境
    base_section = base_prompt
    skills_section = build_skills_section(skill_manifests=skill_manifests)
    catalog_section = build_subagents_section(subagent_names=subagent_names, subagent_paths=subagent_paths)
    runtime_environment_section = build_runtime_environment_section(workspace_root=workspace_root)
    parts = [base_section, skills_section, catalog_section, runtime_environment_section]
    system_prompt = "\n\n".join(part for part in parts if part.strip())
    return system_prompt
