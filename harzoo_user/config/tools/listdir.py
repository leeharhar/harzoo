"""ListDir — browse directory contents."""


from __future__ import annotations

from pathlib import Path
from typing import Any

from harzoo.agent.kernel.tool import Tool, ToolResult, resolve_workspace_path, workspace_root_from

TOOL_VERSION = "2026-06-29"


class ListDirTool(Tool):
    """List files and directories under a path."""

    name = "ListDir"
    description = "List directory entries with name, type, size, and modified time."
    parameters = {
        "properties": {
            "path": {"type": "string", "description": "Directory path (default: current directory)", "default": "."},
            "depth": {"type": "integer", "description": "Tree depth (1 = immediate children only, max 5)", "default": 1},
            "include_hidden": {"type": "boolean", "description": "Include dotfiles", "default": False},
        },
        "required": [],
    }

    def _entry(self, p: Path) -> dict[str, Any]:
        try:
            stat = p.stat()
            return {
                "name": p.name,
                "path": str(p.resolve()),
                "type": "directory" if p.is_dir() else "file",
                "size_bytes": stat.st_size if p.is_file() else None,
                "modified_at": stat.st_mtime,
            }
        except OSError as e:
            return {"name": p.name, "path": str(p), "type": "unknown", "error": str(e)}

    def _walk(self, root: Path, *, depth: int, include_hidden: bool) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        if depth <= 0:
            return entries
        try:
            children = sorted(root.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except PermissionError as e:
            return [{"name": root.name, "path": str(root), "type": "directory", "error": str(e)}]
        for child in children:
            if not include_hidden and child.name.startswith("."):
                continue
            item = self._entry(child)
            if child.is_dir() and depth > 1:
                item["children"] = self._walk(child, depth=depth - 1, include_hidden=include_hidden)
            entries.append(item)
        return entries

    def execute(self, path: str = ".", depth: int = 1, include_hidden: bool = False, **kwargs: Any) -> ToolResult:
        root = workspace_root_from(kwargs.get("ctx"))
        base = resolve_workspace_path(str(path or ".").strip() or ".", root)
        if not base.exists():
            return ToolResult.failure(f"Path not found: {path}", code="PATH_NOT_FOUND", data={"resolved_path": str(base)})
        if not base.is_dir():
            return ToolResult.failure(f"Path is not a directory: {path}", code="PATH_NOT_ACCESSIBLE", data={"resolved_path": str(base)})
        try:
            depth = max(1, min(5, int(depth)))
        except (TypeError, ValueError):
            return ToolResult.failure("depth must be an integer", code="INVALID_ARGUMENTS")
        entries = self._walk(base, depth=depth, include_hidden=bool(include_hidden))
        return ToolResult.success(
            {
                "path": str(base),
                "depth": depth,
                "entry_count": len(entries),
                "entries": entries,
            }
        )


TOOL = ListDirTool
