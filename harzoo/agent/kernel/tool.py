"""工具基类、逐步执行的 Context 与 ToolResult。"""

from __future__ import annotations  # Context.agent 前向引用

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from harzoo.agent.kernel.message import UserInputSegments

if TYPE_CHECKING:
    from harzoo.agent.agent import Agent
    from harzoo.agent.components.paths import ConfigPaths
    from harzoo.agent.components.queue_out import QueueoutEmitter


@dataclass(slots=True)
class Context:
    state: list[dict[str, Any]]
    agent: Agent
    config_paths: ConfigPaths
    emitter: QueueoutEmitter | None = None


@dataclass(slots=True)
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None
    code: str = "TOOL_OK"
    injected_user_input_segments: UserInputSegments | None = None

    @classmethod
    def success(cls, data: Any = None, *, code: str = "TOOL_OK", injected_user_input_segments: UserInputSegments | None = None) -> ToolResult:
        return cls(ok=True, data=data, error=None, code=code, injected_user_input_segments=injected_user_input_segments)

    @classmethod
    def failure(cls, error: str, *, code: str = "TOOL_ERROR", data: Any = None) -> ToolResult:
        return cls(ok=False, data=data, error=error, code=code)

    def to_json(self) -> str:
        return json.dumps(
            {
                "ok": self.ok,
                "data": self.data,
                "error": self.error,
                "code": self.code,
                "injected_user_input_segments": self.injected_user_input_segments,
            },
            ensure_ascii=False,
            default=str,
        )


class Tool:
    """工具基类"""

    name: str
    description: str
    parameters: dict[str, Any]

    def execute(self, *args: Any, ctx: Context | None = None, **kwargs: Any) -> Any:
        raise NotImplementedError

    def as_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", **self.parameters} if "type" not in self.parameters else self.parameters,
            },
        }
