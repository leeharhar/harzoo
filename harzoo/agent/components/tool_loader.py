"""从 harzoo_user/config/tools 发现并加载工具插件。

harzoo_user/config/tools 约定：每个工具单文件、自包含；只依赖 harzoo.agent.kernel.tool（及 stdlib 等）。
勿在 harzoo/agent/components 为工具抽共享模块，勿跨 tools 文件 import。
Skill 在 harzoo_user/config/skills/，与 profile 无关。
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from harzoo.agent.components.util import ConfigError
from harzoo.agent.kernel.tool import Tool

# 同进程内每个工具文件只 exec 一次，模块级状态（如 Browser._SESSION）得以保留。
_PROCESS_MODULE_CACHE: dict[Path, Any] = {}


def load_tools_from_disk(tools_root: Path, tool_names: Sequence[str]) -> list[Tool]:
    """从磁盘加载工具；单个失败不中断后续 name，全部试完后若有失败则抛出 ConfigError。"""

    root = tools_root.resolve()
    cache: dict[Path, Any] = {}
    name_to_path: dict[str, Path] = {}

    for path in sorted(p for p in root.glob("*.py") if not p.stem.startswith(("_", ".")) and p.stem != "__init__"):
        try:
            for tool_cls in _tool_classes(_load_module(path, cache), str(path)):
                name_to_path[tool_cls.name] = path
        except Exception:
            continue

    names = list(dict.fromkeys(tool_names))
    if not names:
        return []

    errors: list[str] = []
    tools: list[Tool] = []
    loaded_names: list[str] = []

    for name in names:
        path = name_to_path.get(name)
        if path is None:
            errors.append(f"Tool {name!r} not found under {root} (profile tool_names must use Tool.name, not filename)")
            continue
        try:
            matched = False
            for tool_cls in _tool_classes(_load_module(path, cache), str(path)):
                if tool_cls.name != name:
                    continue
                tools.append(tool_cls())
                loaded_names.append(name)
                matched = True
                break
            if not matched:
                errors.append(f"Tool {name!r} not found: no Tool with name={name!r} in {path.name}")
        except Exception as exc:
            errors.append(f"Tool {name!r} failed to load from {path.name}: {type(exc).__name__}: {exc}")

    if errors:
        message = "Tool load failed:\n" + "\n".join(errors)
        if loaded_names:
            message += f"\nLoaded: {', '.join(loaded_names)}"
        raise ConfigError(message)

    return tools


def _load_module(path: Path, cache: dict[Path, Any]) -> Any:
    """加载工具模块；同一进程内每个文件只 exec 一次。"""

    resolved = path.resolve()
    if resolved in cache:
        return cache[resolved]
    if resolved in _PROCESS_MODULE_CACHE:
        cache[resolved] = _PROCESS_MODULE_CACHE[resolved]
        return _PROCESS_MODULE_CACHE[resolved]

    name = f"_harzoo_tool.{path.stem}"
    existing = sys.modules.get(name)
    if existing is not None:
        _PROCESS_MODULE_CACHE[resolved] = existing
        cache[resolved] = existing
        return existing

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load tool module: {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    _PROCESS_MODULE_CACHE[resolved] = mod
    cache[resolved] = mod
    return mod


def _tool_classes(mod: Any, module_name: str) -> list[type[Tool]]:
    """获取工具类"""

    if hasattr(mod, "TOOLS"):
        raw = getattr(mod, "TOOLS")
    elif hasattr(mod, "TOOL"):
        raw = [getattr(mod, "TOOL")]
    else:
        raise ValueError(f"{module_name} must define TOOL or TOOLS")
    if inspect.isclass(raw):
        candidates = [raw]
    else:
        try:
            candidates = list(raw)
        except TypeError as e:
            raise TypeError(f"{module_name} TOOLS must be iterable of Tool subclasses") from e
    if not candidates:
        raise ValueError(f"{module_name} TOOL/TOOLS cannot be empty")
    classes: list[type[Tool]] = []
    for candidate in candidates:
        if not inspect.isclass(candidate):
            raise TypeError(f"{module_name} has non-class candidate in TOOL/TOOLS: {candidate!r}")
        if not issubclass(candidate, Tool):
            raise TypeError(f"{module_name} candidate {candidate.__name__} must subclass Tool")
        if inspect.isabstract(candidate):
            raise TypeError(f"{module_name} candidate {candidate.__name__} cannot be abstract")
        classes.append(candidate)
    return classes
