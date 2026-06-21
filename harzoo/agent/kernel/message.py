"""OpenAI 格式的会话消息与多模态用户输入片段类型。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, TypedDict

if TYPE_CHECKING:
    from harzoo.agent.kernel.tool import ToolResult

class TextPart(TypedDict):
    type: Literal["text"]
    text: str


class ImageUrlPart(TypedDict):
    """作为 API 的 image_url.url 传递（如 https://... 或 data:...）；本地文件用 ImagePathPart。"""

    type: Literal["image_url"]
    image_url: str


class ImagePathPart(TypedDict):
    type: Literal["image_path"]
    image_path: str

UserInputSegments = list[TextPart | ImageUrlPart | ImagePathPart]


def user_message(input_segments: UserInputSegments) -> dict[str, Any]:
    """用户输入消息"""

    return {"role": "user", "content": input_segments}


def tool_message(call_id: str, result: "ToolResult") -> dict[str, Any]:
    """工具调用结果消息"""

    return {"role": "tool", "content": result.to_json(), "tool_call_id": call_id}


def assistant_message(content: str | list[Any] | None = None, tool_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """助手消息，即 LLM 返回内容"""

    item = {"role": "assistant"}
    if content is not None:
        item["content"] = content
    if tool_calls is not None:
        item["tool_calls"] = tool_calls
    return item
