"""绑定 profile 的智能体：决策（LLM）与工具执行。"""

from __future__ import annotations

from pathlib import Path

from harzoo.agent.components.paths import ConfigPaths, list_skill_manifests, list_subagent_paths
from harzoo.agent.components.profile import AgentProfile, load_profile_file
from harzoo.agent.components.prompt import assemble_system_prompt
from harzoo.agent.components.tool_hub import ToolHub
from harzoo.agent.kernel.llm import LLM, LLMConfig
from harzoo.agent.kernel.tool import Context, ToolResult


class Agent:
    """拥有大脑和四肢的智能体"""

    def __init__(self, *, profile: AgentProfile, llm: LLM, tools: ToolHub) -> None:
        self.profile = profile
        self.llm = llm
        self.tools = tools

    def decide(self, state: list[dict]) -> tuple[object, list[dict] | None, dict | None]:
        """决策"""

        return self.llm(state)

    def execute_tool_call(self, tool_name: str, args_str: str, ctx: Context) -> ToolResult:
        """执行工具"""

        return self.tools.tool_executor(tool_name, args_str, ctx)

    @classmethod
    def from_profile(cls, profile_path: Path, config_paths: ConfigPaths) -> Agent:
        """从配置文件初始化智能体"""

        profile = load_profile_file(profile_path)
        tools = ToolHub(config_paths.tools_root, profile.tool_names)
        llm = LLM(cls._make_llm_config(profile, config_paths, tools))
        return cls(profile=profile, llm=llm, tools=tools)

    def rebind_profile(self, profile_path: Path, *, config_paths: ConfigPaths) -> None:
        """切换配置文件；校验失败时不修改当前 agent。"""

        profile = load_profile_file(profile_path)
        tools = ToolHub(config_paths.tools_root, profile.tool_names)
        llm = LLM(self._make_llm_config(profile, config_paths, tools))
        self.profile = profile
        self.tools = tools
        self.llm = llm

    @staticmethod
    def _make_llm_config(profile: AgentProfile, config_paths: ConfigPaths, tools: ToolHub) -> LLMConfig:
        system_prompt = assemble_system_prompt(
            base_prompt=profile.base_prompt,
            skill_names=profile.skill_names,
            skill_manifests=list_skill_manifests(config_paths),
            subagent_names=profile.subagent_names,
            subagent_paths=list_subagent_paths(config_paths),
        )
        loaded = tools.list_tools()
        schema = tools.get_schemas(loaded) if loaded else None
        return LLMConfig(
            api_key=profile.api_key,
            base_url=profile.base_url,
            model_name=profile.model_name,
            system_prompt=system_prompt,
            tools_schema=schema or None,
            max_context_tokens=profile.max_context_tokens,
        )

    def __repr__(self) -> str:
        return f"Agent(profile={self.profile.source_path.stem!r}, model={self.llm.llm_config.model_name!r}, tools={self.tools.list_tools()!r})"
