"""@ 路径选择器：浏览 workspace，选中文件或当前目录并插入相对路径。"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from ..logic.workspace_entries import BrowseEntry, list_browse_entries, parent_rel


def _entry_label(entry: BrowseEntry) -> str:
    if entry.kind == "parent":
        return ".."
    if entry.kind == "current_dir":
        return "./"
    if entry.kind == "dir":
        return f"{entry.name}/"
    return entry.name


class FilePicker(Vertical):
    """Workspace 路径选择：目录下钻，选中文件或当前目录插入相对路径。"""

    class PathSelected(Message):
        bubble = True

        def __init__(self, relative_path: str) -> None:
            self.relative_path = relative_path
            super().__init__()

    def __init__(self, *, workspace_root: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._workspace_root = workspace_root.resolve()
        self._current_rel = ""
        self._entries: list[BrowseEntry] = []

    def compose(self) -> ComposeResult:
        yield OptionList(id="file-picker-options", compact=True)

    def open_picker(self) -> None:
        self._current_rel = ""
        self.add_class("is-open")
        self._refresh()

    def close_picker(self) -> None:
        self.remove_class("is-open")
        self._current_rel = ""
        self._entries = []

    @property
    def is_open(self) -> bool:
        return self.has_class("is-open")

    def go_up(self) -> bool:
        """上一级；已在根目录时返回 False。"""
        if not self._current_rel:
            return False
        self._current_rel = parent_rel(self._current_rel)
        self._refresh()
        return True

    def _refresh(self) -> None:
        self._entries = list_browse_entries(self._workspace_root, self._current_rel)
        options = self.query_one("#file-picker-options", OptionList)
        options.clear_options()
        if not self._entries:
            options.add_option(Option("（空目录）", id="_empty", disabled=True))
        else:
            for index, entry in enumerate(self._entries):
                options.add_option(Option(_entry_label(entry), id=str(index)))
        options.highlighted = 0
        options.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "file-picker-options":
            return
        index = event.option_index
        if index is None or index < 0 or index >= len(self._entries):
            return
        entry = self._entries[index]
        if entry.kind == "parent":
            self.go_up()
            return
        if entry.kind == "dir":
            self._current_rel = entry.relative_path
            self._refresh()
            return
        self.close_picker()
        self.post_message(self.PathSelected(entry.relative_path))
