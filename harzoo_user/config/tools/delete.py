"""Delete — remove files or directories."""


from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from harzoo.agent.kernel.tool import Tool, ToolResult, resolve_workspace_path, workspace_root_from

TOOL_VERSION = "2026-06-29"


class DeleteTool(Tool):
    """Delete a file or directory (recursive for directories)."""

    name = "Delete"
    description = "Delete a file or directory. Directories are removed recursively."
    parameters = {
        "properties": {
            "path": {"type": "string", "description": "File or directory path to delete"},
            "recursive": {"type": "boolean", "description": "Allow deleting non-empty directories", "default": True},
        },
        "required": ["path"],
    }

    def execute(self, path: str, recursive: bool = True, **kwargs: Any) -> ToolResult:
        if not str(path).strip():
            return ToolResult.failure("path must not be empty", code="INVALID_ARGUMENTS")
        target = resolve_workspace_path(path, workspace_root_from(kwargs.get("ctx")))
        if not target.exists():
            return ToolResult.failure(f"Path not found: {path}", code="PATH_NOT_FOUND", data={"resolved_path": str(target)})
        was_dir = target.is_dir()
        try:
            if was_dir:
                if recursive:
                    shutil.rmtree(target)
                else:
                    target.rmdir()
            else:
                target.unlink()
        except OSError as e:
            return ToolResult.failure(str(e), code="DELETE_FAILED", data={"resolved_path": str(target)})
        return ToolResult.success({"deleted": True, "path": str(target), "type": "directory" if was_dir else "file"})


TOOL = DeleteTool
