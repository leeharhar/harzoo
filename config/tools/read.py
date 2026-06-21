"""Read file tool."""


from __future__ import annotations

from pathlib import Path
from typing import Callable

from harzoo.agent.kernel.tool import Tool, ToolResult

TOOL_VERSION = "2026-05-22"

ENCODING_POLICY = "utf8_only"


def resolve_tool_path(path: str) -> Path:
    """相对路径统一按当前工作目录解析，避免不同工具的路径语义不一致。"""

    p = Path(path).expanduser()
    if p.is_absolute():
        return p.resolve()
    return (Path.cwd() / p).resolve()


def decode_utf8_only(data: bytes) -> tuple[str, str, bool]:
    """读取策略：只走 UTF-8；失败则 replace，保证工具稳定返回文本。"""

    try:
        return data.decode("utf-8-sig"), "utf-8", False
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace"), "utf-8 (replace)", True


def read_file_text(path: Path) -> tuple[str, str, bool]:
    return decode_utf8_only(path.read_bytes())


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


class ReadTool(Tool):
    """文件读取工具，支持按行窗口读取，避免一次返回超长内容。"""

    name = "Read"
    description = "Read file contents. Paths are relative to workspace unless absolute."
    parameters = {
        "properties": {
            "file_path": {"type": "string", "description": "Path to the file"},
            "offset": {"type": "integer", "description": "1-based line number to start from"},
            "limit": {"type": "integer", "description": "Maximum lines to read"},
        },
        "required": ["file_path"],
    }

    @safe_file_op
    def execute(self, file_path: str, offset: int | None = None, limit: int | None = None, **kwargs) -> ToolResult:
        """读取文件内容，可按 offset/limit 做行级窗口裁剪。"""

        if not str(file_path).strip():
            return ToolResult.failure("file_path must not be empty", code="INVALID_ARGUMENTS")
        if offset is not None and int(offset) < 1:
            return ToolResult.failure("offset must be >= 1", code="INVALID_ARGUMENTS")
        if limit is not None and int(limit) < 1:
            return ToolResult.failure("limit must be >= 1", code="INVALID_ARGUMENTS")
        p = resolve_tool_path(file_path)
        raw, encoding_used, had_replacements = read_file_text(p)
        lines = raw.splitlines()
        if offset is not None:
            lines = lines[max(0, offset - 1) :]
        if limit is not None:
            lines = lines[:limit]
        return ToolResult.success(
            {
                "text": "\n".join(lines),
                "file_path": str(p),
                "requested_file_path": file_path,
                "resolved_file_path": str(p),
                "line_count": len(lines),
                "encoding_used": encoding_used,
                "had_replacements": had_replacements,
                "encoding_policy": ENCODING_POLICY,
            }
        )


TOOL = ReadTool
