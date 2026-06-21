"""系统提示词组装：profile 正文、Skills/Subagents 目录、运行环境、Self state 段。

自上而下：Skills 目录 → Subagents 目录 → 运行环境 → 上下文用量槽 → assemble_system_prompt。
"""

from __future__ import annotations

import platform
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

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


def build_skills_section(*, skill_names: Sequence[str], skill_manifests: list[Path]) -> str:
    """允许的 skill markdown 目录；未配置时返回空字符串。"""

    if not skill_names:
        return ""

    skill_items = _collect_catalog_items(skill_manifests, skill_names, "skill_names")

    if not skill_items:
        return ""

    base_section = "## Allowed Skills\n\nWhen a task matches a skill's description, call LoadSkill before proceeding."
    skills_section = _format_catalog_subsection("### Skills", skill_items)

    parts = [base_section, skills_section]

    return "\n".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# 运行环境（注入给模型的环境信息）
# ---------------------------------------------------------------------------


def build_runtime_environment_section() -> str:
    """运行环境信息（操作系统），位于 ## Runtime Environment 下。"""

    base_section = "## Runtime Environment"
    system_name = platform.system().lower().strip()
    os_name = {"windows": "windows", "darwin": "macos"}.get(system_name, "linux")
    shell_type = "powershell" if os_name == "windows" else "bash"
    facts_section = "\n".join(
        (
            f"- os_name: {os_name}",
            f"- shell_type: {shell_type}",
        )
    )

    parts = [base_section, facts_section]

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Self state：CONTEXT_USAGE_SLOT 之间的可刷新槽位（每轮由引擎更新）
# ---------------------------------------------------------------------------

CONTEXT_USAGE_SLOT_START = "<<HARZOO_TOKEN>>"
CONTEXT_USAGE_SLOT_END = "<</HARZOO_TOKEN>>"
_CONTEXT_USAGE_SLOT_BLOCK = re.compile(re.escape(CONTEXT_USAGE_SLOT_START) + r"[\s\S]*?" + re.escape(CONTEXT_USAGE_SLOT_END), re.MULTILINE)

def _context_usage_bullet(pct: float) -> str:
    return f"- Context usage (approx.): {pct:.1f}% of max. Above ~75%, use CompactContext to compress."


def build_self_state_section() -> str:
    base_section = "## Self state"
    token_section = "\n".join((CONTEXT_USAGE_SLOT_START, _context_usage_bullet(0.0), CONTEXT_USAGE_SLOT_END))

    parts = [base_section, token_section]

    return "\n".join(parts)


def refresh_context_usage_slot(system_prompt: str, *, usage_payload: dict[str, Any] | None, max_context_tokens: int | None) -> str:
    pt = int((usage_payload or {}).get("prompt_tokens") or 0)
    cap = int(max_context_tokens or 0)
    pct = min(100.0, 100.0 * pt / cap) if cap > 0 else 0.0
    repl = "\n".join((CONTEXT_USAGE_SLOT_START, _context_usage_bullet(pct), CONTEXT_USAGE_SLOT_END))
    return _CONTEXT_USAGE_SLOT_BLOCK.sub(repl, system_prompt, count=1)


# ---------------------------------------------------------------------------
# 完整系统提示词（assemble_system_prompt）
# ---------------------------------------------------------------------------

def assemble_system_prompt(
    *,
    base_prompt: str,
    skill_names: Sequence[str],
    skill_manifests: list[Path],
    subagent_names: Sequence[str],
    subagent_paths: list[Path],
) -> str:
    # 拼接顺序：正文 → Skills 目录 → Subagents 目录 → 运行环境 → Self state
    base_section = base_prompt
    skills_section = build_skills_section(skill_names=skill_names, skill_manifests=skill_manifests)
    catalog_section = build_subagents_section(subagent_names=subagent_names, subagent_paths=subagent_paths)
    runtime_environment_section = build_runtime_environment_section()
    self_state_section = build_self_state_section()
    parts = [base_section, skills_section, catalog_section, runtime_environment_section, self_state_section]
    system_prompt = "\n\n".join(part for part in parts if part.strip())
    return system_prompt
