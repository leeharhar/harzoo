"""Glob file search tool."""


from __future__ import annotations

from pathlib import Path

from harzoo.agent.kernel.tool import Tool, ToolResult

TOOL_VERSION = "2026-05-22"


def resolve_tool_path(path: str) -> Path:
    """相对路径统一按当前工作目录解析。"""

    p = Path(path).expanduser()
    if p.is_absolute():
        return p.resolve()
    return (Path.cwd() / p).resolve()


class GlobTool(Tool):
    """文件名匹配工具：按 glob 模式查找路径，不做内容检索。"""

    name = "Glob"
    description = "Find files matching a glob pattern."
    parameters = {
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern e.g. **/*.py"},
            "path": {"type": "string", "description": "Directory to search", "default": "."},
        },
        "required": ["pattern"],
    }

    def execute(self, pattern: str, path: str = ".", **kwargs) -> ToolResult:
        """按 glob 模式查找文件；search path 必须是目录。"""

        if not str(pattern).strip():
            return ToolResult.failure("pattern must not be empty", code="INVALID_ARGUMENTS")
        if not str(path).strip():
            return ToolResult.failure("path must not be empty", code="INVALID_ARGUMENTS")
        base = resolve_tool_path(path)
        if not base.exists():
            return ToolResult.failure(
                f"Path not found: {path}",
                code="PATH_NOT_FOUND",
                data={"requested_path": path, "resolved_path": str(base)},
            )
        if not base.is_dir():
            return ToolResult.failure(
                f"Path is not a directory: {path}",
                code="PATH_NOT_ACCESSIBLE",
                data={"requested_path": path, "resolved_path": str(base)},
            )
        pat = str(pattern).strip()
        if "**" in pat:
            prefix, _, suffix = pat.partition("**")
            search_root = (base / prefix.rstrip("/")) if prefix.strip() else base
            if not search_root.is_dir():
                return ToolResult.failure(
                    f"Path is not a directory: {search_root}",
                    code="PATH_NOT_ACCESSIBLE",
                    data={"requested_path": path, "resolved_path": str(search_root), "pattern": pattern},
                )
            recursive_part = suffix.lstrip("/") or "*"
            candidates = search_root.rglob(recursive_part)
        else:
            candidates = base.glob(pat)
        matches = sorted(str(p) for p in candidates if p.is_file())
        return ToolResult.success(
            {
                "matches": matches,
                "count": len(matches),
                "search_path": str(base),
                "requested_path": path,
                "resolved_path": str(base),
                "pattern": pattern,
            }
        )


TOOL = GlobTool
