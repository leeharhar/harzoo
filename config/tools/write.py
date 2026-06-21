"""Write file tool."""


from __future__ import annotations

from pathlib import Path
from typing import Callable

from harzoo.agent.kernel.tool import Tool, ToolResult

TOOL_VERSION = "2026-05-22"


def resolve_tool_path(path: str) -> Path:
    """相对路径基于当前工作目录，和其他文件工具保持一致。"""

    p = Path(path).expanduser()
    if p.is_absolute():
        return p.resolve()
    return (Path.cwd() / p).resolve()


def safe_file_op(fn: Callable) -> Callable:
    def wrapper(self, file_path: str, *args, **kwargs):
        try:
            return fn(self, file_path, *args, **kwargs)
        except FileNotFoundError:
            resolved = str(resolve_tool_path(file_path))
            return ToolResult.failure(
                f"Path not found: {file_path}",
                code="PATH_NOT_FOUND",
                data={"requested_file_path": file_path, "resolved_file_path": resolved},
            )
        except PermissionError as e:
            resolved = str(resolve_tool_path(file_path))
            return ToolResult.failure(
                str(e),
                code="PATH_NOT_ACCESSIBLE",
                data={"requested_file_path": file_path, "resolved_file_path": resolved},
            )
        except Exception as e:
            return ToolResult.failure(str(e), code="TOOL_EXCEPTION")

    return wrapper


class WriteTool(Tool):
    """文件写入工具：按 UTF-8 覆盖写入，可自动创建父目录。"""

    name = "Write"
    description = "Write content to a file. Creates parent directories if needed."
    parameters = {
        "properties": {
            "file_path": {"type": "string", "description": "Path to the file"},
            "content": {"type": "string", "description": "Full file content"},
        },
        "required": ["file_path", "content"],
    }

    @safe_file_op
    def execute(self, file_path: str, content: str, **kwargs) -> ToolResult:
        """整文件覆盖写入内容，不做局部增量修改。"""

        if not str(file_path).strip():
            return ToolResult.failure("file_path must not be empty", code="INVALID_ARGUMENTS")
        p = resolve_tool_path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return ToolResult.success(
            {
                "file_path": str(p),
                "requested_file_path": file_path,
                "resolved_file_path": str(p),
                "chars_written": len(content),
            }
        )


TOOL = WriteTool
