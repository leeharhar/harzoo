"""/ 命令选择器：命令列表 → profile 角色列表。"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from ..logic.profiles import ProfileEntry, list_profile_entries

SLASH_COMMANDS = (
    ("profile", "切换角色"),
    ("new", "清空会话"),
    ("stop", "停止任务"),
)
COMMAND_NAMES = {name for name, _ in SLASH_COMMANDS}


class CommandPickerStep(Enum):
    COMMANDS = "commands"
    PROFILES = "profiles"


class CommandPicker(Vertical):
    """/ 弹出：全量命令 → 可选 profile 列表。"""

    class CommandSelected(Message):
        bubble = True

        def __init__(self, command: str, args: list[str]) -> None:
            self.command = command
            self.args = args
            super().__init__()

    def __init__(self, *, profiles_root: Path, current_profile: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._profiles_root = profiles_root
        self._current_profile = current_profile
        self._step = CommandPickerStep.COMMANDS
        self._profiles: list[ProfileEntry] = []

    def compose(self) -> ComposeResult:
        yield OptionList(id="command-picker-options", compact=True)

    def set_current_profile(self, profile_name: str) -> None:
        self._current_profile = profile_name.strip()

    def open_picker(self) -> None:
        self._step = CommandPickerStep.COMMANDS
        self._profiles = []
        self.add_class("is-open")
        self._fill_options(
            (Option(f"{name:<10} {desc}", id=name) for name, desc in SLASH_COMMANDS),
        )

    def close_picker(self) -> None:
        self.remove_class("is-open")
        self._step = CommandPickerStep.COMMANDS
        self._profiles = []

    @property
    def is_open(self) -> bool:
        return self.has_class("is-open")

    def _fill_options(self, options: list[Option] | tuple[Option, ...]) -> None:
        widget = self.query_one("#command-picker-options", OptionList)
        widget.clear_options()
        for option in options:
            widget.add_option(option)
        widget.highlighted = 0
        widget.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "command-picker-options":
            return
        option_id = str(event.option_id or "")
        if self._step is CommandPickerStep.COMMANDS:
            if option_id == "profile":
                self._show_profiles()
                return
            if option_id in COMMAND_NAMES:
                self.close_picker()
                self.post_message(self.CommandSelected(option_id, []))
            return

        index = event.option_index
        if index is None or index < 0 or index >= len(self._profiles):
            return
        stem = self._profiles[index].stem
        self.close_picker()
        self.post_message(self.CommandSelected("profile", [stem]))

    def _show_profiles(self) -> None:
        self._step = CommandPickerStep.PROFILES
        self._profiles = list_profile_entries(self._profiles_root)
        current = self._current_profile
        if not self._profiles:
            self._fill_options([Option("（无角色）", id="_empty", disabled=True)])
            return
        self._fill_options(
            Option(
                f"{entry.stem}  {entry.description or entry.name or entry.stem}"
                f"{' (current)' if entry.stem == current else ''}",
                id=str(index),
            )
            for index, entry in enumerate(self._profiles)
        )
