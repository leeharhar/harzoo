"""Markdown 与 YAML front matter 解析辅助。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """用户配置错误。"""


def load_yaml_front_matter_markdown(path: Path) -> tuple[dict[str, Any], str]:
    """加载带 YAML front matter 的 markdown 文件"""

    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        raise ValueError(f"{path}: file must start with --- front matter")
    closing = raw.find("\n---\n", 3)
    if closing == -1:
        raise ValueError(f"{path}: missing closing --- for front matter")
    front_matter, body = raw[3:closing].strip(), raw[closing + 5 :].lstrip("\n").rstrip("\n")
    loaded = yaml.safe_load(front_matter)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: front matter must be a YAML mapping")
    return loaded, body
