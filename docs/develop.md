<div class="doc-title" markdown="0">
  <h1>开发与扩展</h1>
  <div class="landing-meta" markdown="0">
    <a
      class="github-link"
      href="https://github.com/leeharhar/harzoo"
      target="_blank"
      rel="noopener"
      title="View source on GitHub"
      aria-label="View source on GitHub"
    >
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="20" height="20" aria-hidden="true">
        <path
          fill="currentColor"
          d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"
        />
      </svg>
    </a>
    <a
      class="landing-meta-license"
      href="https://github.com/leeharhar/harzoo/blob/main/LICENSE"
      target="_blank"
      rel="noopener"
    >
      Open source · MIT License
    </a>
    <a
      class="github-link gitee-link"
      href="https://gitee.com/leeharhar/harzoo"
      target="_blank"
      rel="noopener"
      title="View source on Gitee"
      aria-label="View source on Gitee"
    >
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
        <rect x="1.5" y="1.5" width="21" height="21" rx="4" fill="#C71D23" />
        <text x="12" y="16" text-anchor="middle" font-size="12" font-family="Arial, sans-serif" font-weight="700" fill="#FFFFFF">G</text>
      </svg>
    </a>
  </div>
</div>

Harzoo 是一个简单的、灵活的、开源的由大语言模型驱动的AI框架，由Python语言实现，你几乎可以对源代码进行任意想法的使用与改造。

## 高级封装用法

```python
from pathlib import Path

from harzoo import start
from harzoo.agent.kernel.message import user_message

# 准备配置目录
config_root='./config' 
TODO: 准备配置目录

# 准备配置文件
TODO: 将配置文件放到配置目录

# 启动智能体
queue_in, queue_out = start(config_root)

# 发送 用户输入
queue_in.put(user_message([{"type": "text", "text": "你好"}]))

# 打印 智能体的输出
while True:
    print(queue_out.get())
```

```text
双队列架构：
                                    ┌──────────────┐                     
                --------->----------│   queue_in   │--------->------- 
               │                    └──────────────┘                 │        
               │                                                     │         
           tui/web ui/script等                                     agent                      
               │                                                     │
               │                    ┌──────────────┐                 │
                ---------<----------│  queue_out   │--------->-------                        
                                    └──────────────┘                         
```

## 低级封装用法

```python
from pathlib import Path

from harzoo import Agent
from harzoo.agent.components.paths import prepare_config_paths
from harzoo.agent.kernel.message import assistant_message, tool_message, user_message
from harzoo.agent.kernel.tool import Context

# 准备配置目录
config_root='./config' 
TODO: 准备配置目录

# 准备配置文件
TODO: 将配置文件放到配置目录

# 获取配置文件路径
paths = prepare_config_paths(config_root)

# 初始化 智能体
agent = Agent.from_profile(paths.startup_profile_path, paths)

# 初始化 state
state = []

# 新增用户输入，更新 state
state.append(user_message([{"type": "text", "text": "上海今天天气怎么样？"}]))

while state and state[-1].get("role") in ("user", "tool"):
    ctx = Context(state=state, agent=agent, config_paths=paths)

    # 决策
    content, tool_calls, _usage = agent.decide(state)

    # 新增llm输出，更新 state
    state.append(assistant_message(content=content, tool_calls=tool_calls))

    
    if isinstance(tool_calls, list) and tool_calls:
        for tool_call in tool_calls:
            call_id, fn = str(tool_call["id"]), tool_call["function"]
            tool_name, args_str = str(fn["name"]), str(fn["arguments"])

            # 执行 tool
            result = agent.execute_tool_call(tool_name, args_str, ctx)

            # 新增tool的执行结果，更新 state
            state.append(tool_message(call_id, result))

            # 新增tool的临时注入，更新 state
            if result.injected_user_input_segments:
                state.append(user_message(result.injected_user_input_segments))
```

```text
单步状态机循环架构：state ----> [llm + prompt] --> tool --> next state
```

