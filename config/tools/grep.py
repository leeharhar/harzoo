"""Regex search in files tool."""


from __future__ import annotations

import re
from pathlib import Path

from harzoo.agent.kernel.tool import Tool, ToolResult

TOOL_VERSION = "2026-05-22"

ENCODING_POLICY = "utf8_only"


def resolve_tool_path(path: str) -> Path:
    """搜索根目录的相对路径统一按当前工作目录解析。"""

    p = Path(path).expanduser()
    if p.is_absolute():
        return p.resolve()
    return (Path.cwd() / p).resolve()


def decode_utf8_only(data: bytes) -> tuple[str, str, bool]:
    """搜索文本统一按 UTF-8 读取；失败用 replace 保证不中断全局搜索。"""

    try:
        return data.decode("utf-8-sig"), "utf-8", False
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace"), "utf-8 (replace)", True


def read_file_text(path: Path) -> tuple[str, str, bool]:
    return decode_utf8_only(path.read_bytes())


def _case_insensitive(kwargs: dict) -> bool:
    if kwargs.get("-i"):
        return True
    if kwargs.get("case_insensitive"):
        return True
    return bool(kwargs.get("i"))


class GrepTool(Tool):
    """正则文本搜索工具，适合定位代码片段，不负责语义理解。"""

    name = "Grep"
    description = "Search for regex pattern in files."
    parameters = {
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern"},
            "path": {"type": "string", "description": "Root path to search", "default": "."},
            "glob": {"type": "string", "description": "File glob filter", "default": "*"},
            "output_mode": {"type": "string", "enum": ["content", "files_with_matches", "count"], "default": "content"},
            "head_limit": {"type": "integer", "description": "Max results", "default": 100},
            "case_insensitive": {"type": "boolean", "description": "Case-insensitive search", "default": False},
            "-i": {"type": "boolean", "description": "Alias for case_insensitive", "default": False},
        },
        "required": ["pattern"],
    }

    def execute(self, pattern: str, path: str = ".", glob: str = "*", output_mode: str = "content", head_limit: int = 100, **kwargs) -> ToolResult:
        """按正则在指定路径搜索文本，可返回内容、文件列表或计数。"""

        try:
            if not str(pattern).strip():
                return ToolResult.failure("pattern must not be empty", code="INVALID_ARGUMENTS")
            if not str(path).strip():
                return ToolResult.failure("path must not be empty", code="INVALID_ARGUMENTS")
            if output_mode not in {"content", "files_with_matches", "count"}:
                return ToolResult.failure("output_mode must be one of: content, files_with_matches, count", code="INVALID_ARGUMENTS")
            if int(head_limit) < 1:
                return ToolResult.failure("head_limit must be >= 1", code="INVALID_ARGUMENTS")
            base = resolve_tool_path(path)
            if not base.exists():
                return ToolResult.failure(f"Path not found: {path}", code="PATH_NOT_FOUND")
            flags = re.IGNORECASE if _case_insensitive(kwargs) else 0
            try:
                cre = re.compile(pattern, flags)
            except re.error:
                return ToolResult.failure(f"Invalid regex: {pattern}", code="INVALID_REGEX")
            files = [base] if base.is_file() else [f for f in base.rglob(glob) if f.is_file()]
            results, file_counts, total_count = [], {}, 0
            files_with_decode_replacements = 0
            for fp in files:
                try:
                    text, _enc, had_replacements = read_file_text(fp)
                    if had_replacements:
                        files_with_decode_replacements += 1
                except OSError:
                    continue
                if output_mode == "count":
                    n = sum(1 for _ in cre.finditer(text))
                    if n:
                        file_counts[str(fp)] = n
                        total_count += n
                elif output_mode == "files_with_matches":
                    if cre.search(text):
                        results.append(str(fp))
                        if len(results) >= head_limit:
                            break
                else:
                    for i, line in enumerate(text.splitlines(), 1):
                        if cre.search(line):
                            results.append(f"{fp}:{i}: {line.strip()}")
                            if len(results) >= head_limit:
                                break
                    if len(results) >= head_limit:
                        break
            if output_mode == "count":
                return ToolResult.success(
                    {
                        "counts": dict(sorted(file_counts.items())) if file_counts else {},
                        "total": total_count,
                        "output_mode": output_mode,
                        "requested_path": path,
                        "resolved_path": str(base),
                        "encoding_policy": ENCODING_POLICY,
                        "files_with_decode_replacements": files_with_decode_replacements,
                    }
                )
            return ToolResult.success(
                {
                    "matches": results,
                    "count": len(results),
                    "output_mode": output_mode,
                    "requested_path": path,
                    "resolved_path": str(base),
                    "encoding_policy": ENCODING_POLICY,
                    "files_with_decode_replacements": files_with_decode_replacements,
                }
            )
        except Exception as e:
            return ToolResult.failure(str(e), code="TOOL_EXCEPTION")


TOOL = GrepTool
