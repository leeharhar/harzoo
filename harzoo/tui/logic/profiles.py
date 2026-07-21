"""TUI F1 profile 列表：仅展示，不做路径解析。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class ProfileEntry:
    stem: str
    name: str
    description: str


def _meta_from_path(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not raw.startswith("---"):
        return {}
    closing = raw.find("\n---\n", 3)
    if closing == -1:
        return {}
    try:
        loaded = yaml.safe_load(raw[3:closing].strip())
    except yaml.YAMLError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _entry_from_path(path: Path) -> ProfileEntry:
    meta = _meta_from_path(path)
    return ProfileEntry(
        stem=path.stem,
        name=str(meta.get("name") or "").strip(),
        description=str(meta.get("description") or "").strip(),
    )


def list_profile_entries(profiles_root: Path) -> list[ProfileEntry]:
    """列出 profiles 目录下全部 .md 角色。"""
    entries: list[ProfileEntry] = []
    for path in sorted(profiles_root.glob("*.md")):
        if path.is_file():
            entries.append(_entry_from_path(path))
    return entries
