"""Write file tool."""


from __future__ import annotations

from typing import Callable

from harzoo.agent.kernel.tool import Tool, ToolResult, resolve_workspace_path, workspace_root_from

TOOL_VERSION = "2026-05-22"


def safe_file_op(fn: Callable) -> Callable:
    def wrapper(self, file_path: str, *args, **kwargs):
        root = workspace_root_from(kwargs.get("ctx"))
        try:
            return fn(self, file_path, *args, **kwargs)
        except FileNotFoundError:
            resolved = str(resolve_workspace_path(file_path, root))
            return ToolResult.failure(
                f"Path not found: {file_path}",
                code="PATH_NOT_FOUND",
                data={"requested_file_path": file_path, "resolved_file_path": resolved},
            )
        except PermissionError as e:
            resolved = str(resolve_workspace_path(file_path, root))
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
    description = "Write content to a file. Paths are relative to workspace root unless absolute."
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
        root = workspace_root_from(kwargs.get("ctx"))
        p = resolve_workspace_path(file_path, root)
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
