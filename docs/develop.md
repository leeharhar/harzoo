# 开发与扩展

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

