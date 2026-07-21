"""启动智能体引擎线程，返回供 UI 使用的队列。"""

from __future__ import annotations

import threading
from pathlib import Path
from queue import Queue
from typing import Any

import harzoo.agent.components

from harzoo.agent.components.paths import default_user_root, prepare_config_paths
from harzoo.agent.engine import engine


def start(user_root: Path | str | None = None, workspace_root: Path | str | None = None):
    """启动智能体"""

    resolved_user_root = default_user_root() if user_root is None else user_root
    config_paths = prepare_config_paths(resolved_user_root, workspace_root=workspace_root)

    queue_in = Queue()
    queue_out = Queue()
    cancel = threading.Event()

    thread = threading.Thread(target=engine, args=(queue_in, queue_out, config_paths, cancel), daemon=True)
    thread.start()

    return queue_in, queue_out, cancel
