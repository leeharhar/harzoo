"""智能体 Textual TUI 应用。"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from queue import Queue

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer, VerticalGroup
from textual.widgets import Static, TextArea

from harzoo.agent.components.paths import prepare_config_paths

from .controller import AgentController
from .pickers import CommandPicker, FilePicker
from .widgets import BannerMessage, ChatInputTextArea

BANNER = r"""
╔══════════════════════════════════════════════════════════════╗
║                          🤖 Harzoo 🎮                        ║
║──────────────────────────────────────────────────────────────║
║           Ctrl+W Commands ·  Ctrl+Q Quit                     ║
║           Ctrl+C Copy     ·  Ctrl+V (Cmd+V) Paste            ║
║           Double-click Copy full text                        ║
╚══════════════════════════════════════════════════════════════╝
""".strip("\n")


def _try_pbcopy(text: str) -> bool:
    if sys.platform != "darwin":
        return False
    try:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


class AgentApp(App[None]):
    """主 TUI 应用。"""

    CSS = """
    Screen {
        layout: vertical;
        padding: 0 1 1 1;
    }
    #banner {
        height: auto;
        width: 100%;
        margin: 0 0 1 0;
    }
    #chat {
        height: 1fr;
        padding: 0 0 1 0;
        scrollbar-gutter: auto;
        scrollbar-size-vertical: 0;
        scrollbar-size-horizontal: 0;
    }
    #input {
        height: auto;
        width: 1fr;
        background: $background;
        padding: 1 0 0 0;
    }
    #status-footer {
        width: 100%;
        height: 1;
        text-align: right;
        margin-top: 1;
        color: $text-muted;
    }
    ToastRack {
        margin-bottom: 6;
        margin-right: 1;
    }
    #command-picker, #file-picker {
        display: none;
        width: 1fr;
        height: auto;
        margin-bottom: 1;
        padding: 1 1;
        background: $panel;
    }
    #command-picker.is-open, #file-picker.is-open {
        display: block;
    }
    #command-picker-options, #file-picker-options {
        padding: 0 1;
        background: $panel;
    }
    #command-picker-options:focus, #file-picker-options:focus {
        border: none;
        background: $panel;
        background-tint: transparent;
    }
    #command-picker-options > .option-list--option,
    #file-picker-options > .option-list--option {
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Close"),
        Binding(
            "ctrl+w",
            "open_command_palette",
            "Commands",
            priority=True,
        ),
    ]

    def __init__(
        self,
        queue_in: Queue,
        queue_out: Queue,
        cancel: threading.Event,
        *,
        workspace_root: Path,
        user_root: Path,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.queue_out = queue_out
        self._cancel = cancel
        self._workspace_root = workspace_root.resolve()
        self._profiles_root = prepare_config_paths(
            user_root, workspace_root=workspace_root
        ).profiles_root
        self.controller = AgentController(
            app=self,
            queue_in=queue_in,
            workspace_root=self._workspace_root,
        )

    def compose(self) -> ComposeResult:
        yield BannerMessage(BANNER, id="banner")
        yield ScrollableContainer(id="chat")
        with VerticalGroup(id="input"):
            yield CommandPicker(
                profiles_root=self._profiles_root,
                id="command-picker",
            )
            yield FilePicker(
                workspace_root=self._workspace_root,
                id="file-picker",
            )
            yield ChatInputTextArea(
                text="",
                soft_wrap=True,
                show_line_numbers=False,
                tab_behavior="focus",
                highlight_cursor_line=False,
                placeholder="Input your idea ...  (@ attach file)",
                id="chat-input",
            )
            yield Static("", id="status-footer", markup=False)

    def on_mount(self) -> None:
        self.controller.init_chat_view()
        self.set_interval(0.03, lambda: self.controller.drain_outbound_events(self.queue_out))
        self.controller.refresh_status_footer_view()

    def copy_to_clipboard(self, text: str) -> None:
        self._clipboard = text
        if _try_pbcopy(text):
            return
        super().copy_to_clipboard(text)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self.controller.on_input_changed(event)

    def on_chat_input_text_area_at_inserted(self, event: ChatInputTextArea.AtInserted) -> None:
        self.controller.on_at_inserted(event.text_area)

    def on_chat_input_text_area_submitted(self, _: ChatInputTextArea.Submitted) -> None:
        self._cancel.clear()
        self.controller.submit_chat_input()

    def on_command_picker_command_selected(self, event: CommandPicker.CommandSelected) -> None:
        self.controller.run_picked_command(event.command, event.args)

    def on_file_picker_path_selected(self, event: FilePicker.PathSelected) -> None:
        self.controller.insert_path_into_input(event.relative_path)

    def action_open_command_palette(self) -> None:
        cmd_picker = self.query_one("#command-picker", CommandPicker)
        if cmd_picker.is_open:
            cmd_picker.close_picker()
            self.query_one("#chat-input", ChatInputTextArea).focus()
            return
        self.controller.open_command_palette()

    def action_cancel(self) -> None:
        cmd_picker = self.query_one("#command-picker", CommandPicker)
        if cmd_picker.is_open:
            cmd_picker.close_picker()
            self.query_one("#chat-input", ChatInputTextArea).focus()
            return
        picker = self.query_one("#file-picker", FilePicker)
        if picker.is_open:
            if picker.go_up():
                return
            self.controller.dismiss_file_picker()
            self.query_one("#chat-input", ChatInputTextArea).focus()
            return


def run_tui(
    queue_in: Queue,
    queue_out: Queue,
    cancel: threading.Event,
    *,
    workspace_root: Path | None = None,
    user_root: Path | None = None,
) -> None:
    """启动 TUI 应用。"""
    resolved_workspace = (workspace_root or Path.cwd()).resolve()
    if user_root is None:
        from harzoo.agent.components.paths import default_user_root

        user_root = default_user_root()
    AgentApp(
        queue_in=queue_in,
        queue_out=queue_out,
        cancel=cancel,
        workspace_root=resolved_workspace,
        user_root=user_root,
    ).run()
