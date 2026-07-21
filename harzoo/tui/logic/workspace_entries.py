"""Workspace 目录浏览：列出当前层目录与文件（供 @ 文件选择器使用）。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

BrowseKind = Literal["parent", "current_dir", "dir", "file"]

IGNORE_DIR_NAMES = frozenset({
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
})

IGNORE_PATH_PREFIXES = (
    "harzoo_user/data/browser/",
    "config/data/browser/",
)


@dataclass(frozen=True, slots=True)
class BrowseEntry:
    kind: BrowseKind
    name: str
    relative_path: str


def _normalize_rel(relative: str) -> str:
    return relative.strip().strip("/").replace("\\", "/")


def _relative_to_workspace(path: Path, workspace_root: Path) -> str:
    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _is_ignored_dir(relative_path: str) -> bool:
    normalized = _normalize_rel(relative_path)
    if not normalized:
        return False
    if any(normalized.startswith(prefix) for prefix in IGNORE_PATH_PREFIXES):
        return True
    return normalized.split("/")[0] in IGNORE_DIR_NAMES or Path(normalized).name in IGNORE_DIR_NAMES


def parent_rel(current_rel: str) -> str:
    """返回上一级目录的相对路径；已在根时返回空字符串。"""
    normalized = _normalize_rel(current_rel)
    if not normalized:
        return ""
    parent = Path(normalized).parent
    return "" if str(parent) in {".", ""} else parent.as_posix()


def list_browse_entries(workspace_root: Path, current_rel: str = "") -> list[BrowseEntry]:
    """列出 workspace 当前一层：`..`、选当前目录 `./`、子目录与文件。"""
    root = workspace_root.resolve()
    normalized = _normalize_rel(current_rel)
    current_dir = root if not normalized else (root / normalized).resolve()

    if not current_dir.is_dir():
        return []

    entries: list[BrowseEntry] = []

    if normalized:
        entries.append(BrowseEntry(kind="parent", name="..", relative_path=parent_rel(normalized)))

    child_dirs: list[BrowseEntry] = []
    child_files: list[BrowseEntry] = []

    try:
        children = sorted(current_dir.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return entries

    for child in children:
        try:
            if not child.exists():
                continue
        except OSError:
            continue

        rel = _relative_to_workspace(child, root)
        if child.is_dir():
            if _is_ignored_dir(rel):
                continue
            child_dirs.append(BrowseEntry(kind="dir", name=child.name, relative_path=rel))
        elif child.is_file():
            child_files.append(BrowseEntry(kind="file", name=child.name, relative_path=rel))

    entries.extend(child_dirs)
    entries.extend(child_files)

    path = f"{normalized}/" if normalized else "."
    current = BrowseEntry(kind="current_dir", name="", relative_path=path)
    if entries and entries[0].kind == "parent":
        return [entries[0], current, *entries[1:]]
    return [current, *entries]
