"""编程智能体入口。"""

from __future__ import annotations

from pathlib import Path

from harzoo.agent.start import start
from harzoo.tui import run_tui


def main() -> None:
    """程序入口"""

    config_root = (Path(__file__).resolve().parents[1] / "config").resolve()

    queue_in, queue_out = start(config_root)

    run_tui(queue_in=queue_in, queue_out=queue_out)


if __name__ == "__main__":
    main()
