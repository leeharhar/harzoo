"""In-file text replace tool."""


from __future__ import annotations

from pathlib import Path
from typing import Callable

from harzoo.agent.kernel.tool import Tool, ToolResult

TOOL_VERSION = "2026-05-22"

ENCODING_POLICY = "utf8_only"


def resolve_tool_path(path: str) -> Path:
    """相对路径统一按当前工作目录解析。"""

    p = Path(path).expanduser()
    if p.is_absolute():
        return p.resolve()
    return (Path.cwd() / p).resolve()


def decode_utf8_only(data: bytes) -> tuple[str, str, bool]:
    """编辑前先按 UTF-8 读取；若发生 replace，视为非标准 UTF-8 文件。"""

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


class EditTool(Tool):
    """精确替换工具：old_string 必须完全匹配，适合可控小范围修改。"""

    name = "Edit"
    description = "Replace exact text in a file. old_string must match exactly."
    parameters = {
        "properties": {
            "file_path": {"type": "string", "description": "Path to the file"},
            "old_string": {"type": "string", "description": "Exact text to find"},
            "new_string": {"type": "string", "description": "Replacement text"},
            "replace_all": {"type": "boolean", "description": "Replace all occurrences", "default": False},
        },
        "required": ["file_path", "old_string", "new_string"],
    }

    @safe_file_op
    def execute(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False, **kwargs) -> ToolResult:
        """按精确匹配执行文本替换；old_string 不能为空。"""

        if not str(file_path).strip():
            return ToolResult.failure("file_path must not be empty", code="INVALID_ARGUMENTS")
        if old_string == "":
            return ToolResult.failure("old_string must not be empty", code="INVALID_ARGUMENTS")
        p = resolve_tool_path(file_path)
        text, encoding_used, had_replacements = read_file_text(p)
        if had_replacements:
            # 限制：在 utf8_only 策略下，疑似非 UTF-8 文件直接拒绝编辑，避免破坏内容。
            return ToolResult.failure(
                "File is not valid UTF-8 under utf8_only policy; edit aborted to avoid corrupting content",
                code="UNSUPPORTED_ENCODING",
                data={
                    "file_path": str(p),
                    "requested_file_path": file_path,
                    "resolved_file_path": str(p),
                    "encoding_policy": ENCODING_POLICY,
                },
            )
        if old_string not in text:
            return ToolResult.failure("old_string not found in file", code="TEXT_NOT_FOUND")
        p.write_text(text.replace(old_string, new_string, -1 if replace_all else 1), encoding="utf-8")
        return ToolResult.success(
            {
                "file_path": str(p),
                "requested_file_path": file_path,
                "resolved_file_path": str(p),
                "replace_all": bool(replace_all),
                "applied": True,
                "encoding_used": encoding_used,
                "encoding_policy": ENCODING_POLICY,
            }
        )


TOOL = EditTool
