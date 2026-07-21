from __future__ import annotations

from pathlib import Path

from harzoo.agent.components.paths import default_user_root
from harzoo.agent.start import start
from harzoo.tui import run_tui


def main() -> None:
    """程序入口"""

    user_root = default_user_root()
    workspace_root = Path.cwd()

    queue_in, queue_out, cancel = start(user_root, workspace_root=workspace_root)

    run_tui(
        queue_in=queue_in,
        queue_out=queue_out,
        cancel=cancel,
        workspace_root=workspace_root,
        user_root=user_root,
    )


if __name__ == "__main__":
    main()
