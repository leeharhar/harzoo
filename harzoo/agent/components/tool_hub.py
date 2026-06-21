"""进程内工具注册中心：加载、schema、执行。"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from harzoo.agent.components.tool_loader import load_tools_from_disk
from harzoo.agent.kernel.tool import Context, ToolResult


class ToolHub:
    """工具注册中心, 负责工具的加载、注册、执行"""

    def __init__(self, tools_root: Path, tool_names: Sequence[str]) -> None:
        self._tools_root = tools_root.resolve()
        self._schemas: dict[str, dict[str, Any]] = {}
        self._handlers: dict[str, Callable[[dict[str, Any], Context], Any]] = {}
        self._load(tool_names)

    def _load(self, tool_names: Sequence[str]) -> None:
        """加载工具"""

        tools = load_tools_from_disk(self._tools_root, tool_names)
        for tool in tools:
            self._handlers[tool.name] = lambda args, ctx, t=tool: t.execute(**args, ctx=ctx)
            self._schemas[tool.name] = tool.as_openai_schema()

    def tool_executor(self, tool_name: str, tool_args: str, ctx: Context) -> ToolResult:
        """执行工具"""

        try:
            parsed_args = json.loads(tool_args)
            if not isinstance(parsed_args, dict):
                raise ValueError("Tool arguments must decode to JSON object")
        except (json.JSONDecodeError, ValueError) as e:
            return ToolResult.failure(str(e), code="INVALID_ARGUMENTS")
        parsed_args.pop("ctx", None)
        handler = self._handlers.get(tool_name)
        if handler is None:
            return ToolResult.failure(f"Unknown tool: {tool_name}", code="UNKNOWN_TOOL")
        raw = handler(parsed_args, ctx)
        if isinstance(raw, ToolResult):
            return raw
        return ToolResult.failure(f"Tool returned unsupported result type: {type(raw).__name__}", code="INVALID_TOOL_RESULT")

    def get_schemas(self, names: Sequence[str] | None = None) -> list[dict[str, Any]]:
        """获取工具的 OpenAI schema"""

        if names is None:
            return list(self._schemas.values())
        missing = [name for name in names if name not in self._schemas]
        if missing:
            raise ValueError(f"Unknown tool names: {missing}")
        return [self._schemas[name] for name in names]

    def list_tools(self) -> list[str]:
        return list(self._handlers.keys())
