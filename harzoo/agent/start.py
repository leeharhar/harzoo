"""启动智能体引擎线程，返回供 UI 使用的队列。"""

from __future__ import annotations

import threading
from pathlib import Path
from queue import Queue
from typing import Any

import harzoo.agent.components

from harzoo.agent.components.paths import prepare_config_paths
from harzoo.agent.engine import engine


def start(config_root: Path | str):
    """启动智能体"""

    config_paths = prepare_config_paths(config_root)

    queue_in = Queue()
    queue_out = Queue()

    thread = threading.Thread(target=engine, args=(queue_in, queue_out, config_paths), daemon=True)
    thread.start()

    return queue_in, queue_out
