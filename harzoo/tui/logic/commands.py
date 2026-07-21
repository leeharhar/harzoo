"""TUI 命令：由命令选择器经 dispatch_command 调用。"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from harzoo.agent.control import control_message

if TYPE_CHECKING:
    from ..controller import AgentController

CommandHandler = Callable[["AgentController", list[str]], None]


def _cmd_stop(controller: AgentController, _: list[str]) -> None:
    controller.app._cancel.set()
    controller.emit_system("已请求停止，本步完成后不再继续。")


def _cmd_quit(controller: AgentController, _: list[str]) -> None:
    controller.app.exit()


def _cmd_new(controller: AgentController, _: list[str]) -> None:
    controller.queue_in.put(control_message("reset"))


def _cmd_profile(controller: AgentController, args: list[str]) -> None:
    stem = (args[0] if args else "").strip()
    if not stem:
        return
    controller.queue_in.put(control_message("switch_profile", query=stem))
    controller.emit_system(f"切换至 {stem}")


COMMANDS: dict[str, CommandHandler] = {
    "stop": _cmd_stop,
    "quit": _cmd_quit,
    "new": _cmd_new,
    "profile": _cmd_profile,
}


def dispatch_command(controller: AgentController, command: str, args: list[str]) -> None:
    if handler := COMMANDS.get(command):
        handler(controller, args)
