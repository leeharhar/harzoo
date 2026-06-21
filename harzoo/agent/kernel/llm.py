"""OpenAI 兼容的 LLM 客户端。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from openai import OpenAI

from harzoo.agent.kernel.llm_util import preprocess_chat_state_for_api


@dataclass
class LLMConfig:
    api_key: str
    base_url: str
    model_name: str
    system_prompt: str
    tools_schema: list[dict[str, Any]] | None = None
    max_context_tokens: int | None = None


class LLM:
    """LLM客户端, 请求LLM API"""

    def __init__(self, llm_config: LLMConfig):
        self.llm_config = llm_config
        self.client = OpenAI(api_key=llm_config.api_key, base_url=llm_config.base_url)

    def __call__(self, state: list[dict]) -> tuple[str | list[Any] | None, list[dict[str, Any]] | None, dict[str, int] | None]:

        # ===== 预处理会话状态（图片仅保留最后一条用户消息） =====
        normalized_state = preprocess_chat_state_for_api(state)

        # ===== 追加系统提示词，组装 API messages =====
        messages = [{"role": "system", "content": self.llm_config.system_prompt}] + normalized_state

        # ===== 准备 API 参数 =====
        kwargs = {"model": self.llm_config.model_name, "messages": messages}
        ts = self.llm_config.tools_schema
        if ts:
            kwargs["tools"] = ts

        # ===== 请求 API =====
        response = self.client.chat.completions.create(**kwargs)

        # ===== 处理 API 返回 =====
        msg = response.choices[0].message
        tool_calls = [call.to_dict() for call in msg.tool_calls] if msg.tool_calls else None
        usage = response.usage
        usage_payload = {"prompt_tokens": max(0, int(usage.prompt_tokens)), "completion_tokens": max(0, int(usage.completion_tokens)), "total_tokens": max(0, int(usage.total_tokens)), "latency_ms": 0} if usage else None
        return msg.content, tool_calls, usage_payload
