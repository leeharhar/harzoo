# Harzoo

Harzoo is a small, flexible, and transparent Python AI framework. 

Just 1300 lines of code, you can read and own it.

You can build your own AI. 

## Documentation

```text
www.harzoo.com
```

## Quick Start

1. **Install from source**

   ```bash
   git clone https://github.com/leeharhar/harzoo.git
   ```

   ```bash
   cd harzoo
   ```

   ```bash
   pip install -e .
   ```

2. **Configure**

   Edit files under the project `config/` directory:

   ```text
   config/
   ├── config.json
   ├── profiles/
   └── tools/
   ```

   - Update API settings (`api_key`, `base_url`, `model_name`) in your profile under `profiles/`.
   - Set `startup_profile` in `config.json` to your profile file.

3. **Run**

   Opens the terminal UI:

   ```bash
   harzoo
   ```

## Python Examples

### High-level

```python
from pathlib import Path

import harzoo
from harzoo import start
from harzoo.agent.kernel.message import user_message

config_dir = Path(harzoo.__file__).resolve().parents[1] / "config"
queue_in, queue_out = start(config_dir)

user_message = user_message([{"type": "text", "text": "Hello"}])
queue_in.put(user_message)

print(queue_out.get())
```

### Low-level

```python
from pathlib import Path

import harzoo
from harzoo import Agent
from harzoo.agent.components.paths import prepare_config_paths
from harzoo.agent.kernel.message import assistant_message, tool_message, user_message
from harzoo.agent.kernel.tool import Context

config_dir = Path(harzoo.__file__).resolve().parents[1] / "config"
paths = prepare_config_paths(config_dir)
agent = Agent.from_profile(paths.startup_profile_path, paths)

state = []

user_message = user_message([{"type": "text", "text": "Hello"}])
state.append(user_message)

while state and state[-1].get("role") in ("user", "tool"):
    ctx = Context(state=state, agent=agent, config_paths=paths)
    content, tool_calls, _ = agent.decide(state)
    state.append(assistant_message(content=content, tool_calls=tool_calls))
    if tool_calls:
        for tc in tool_calls:
            fn = tc["function"]
            result = agent.execute_tool_call(str(fn["name"]), str(fn["arguments"]), ctx)
            tool_message = tool_message(str(tc["id"]), result)
            state.append(tool_message)

print(state[-1])
```

## License

MIT
