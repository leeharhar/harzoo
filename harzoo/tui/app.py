"""智能体 Textual TUI 应用。"""

from __future__ import annotations

import subprocess
import sys
from queue import Queue

from textual.app import App, ComposeResult
from textual.containers import Container, ScrollableContainer
from textual.widgets import Static, TextArea

from .controller import AgentController
from .widgets import BannerMessage, ChatInputTextArea

BANNER = r"""
╔══════════════════════════════════════════════════════════════╗
║   🎮 HARZOO AGENT v0.1.0      │      www.harzoo.com           ║
║──────────────────────────────────────────────────────────────║
║        🤖 Beep Boop... Your Wish Is My Command! (◕‿◕)         ║
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
    Screen { layout: vertical; }
    #chat {
        height: 1fr;
        padding: 0 1;
        scrollbar-gutter: auto;
        scrollbar-size-vertical: 0;
        scrollbar-size-horizontal: 0;
    }
    #input {
        height: auto;
        min-height: 2;
        padding: 1 2;
    }
    #status-footer {
        width: 1fr;
        height: 1;
        text-align: right;
        margin-top: 1;
        padding-right: 6;
        color: $text-muted;
    }
    #input TextArea {
        width: 1fr;
        height: auto;
        min-height: 1;
        max-height: 8;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    def __init__(self, queue_in: Queue, queue_out: Queue, **kwargs) -> None:
        super().__init__(**kwargs)
        self.queue_out = queue_out
        self.controller = AgentController(app=self, queue_in=queue_in)

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="chat"):
            yield BannerMessage(BANNER, id="banner")
        with Container(id="input"):
            yield ChatInputTextArea(
                text="",
                soft_wrap=True,
                show_line_numbers=False,
                tab_behavior="focus",
                placeholder="Ask the agent… (Enter send, Shift+Enter newline)",
                id="chat-input",
            )
            yield Static("", id="status-footer", markup=False)

    def on_mount(self) -> None:
        self.set_interval(0.03, lambda: self.controller.drain_outbound_events(self.queue_out))
        self.controller.refresh_status_footer_view()

    def copy_to_clipboard(self, text: str) -> None:
        self._clipboard = text
        if _try_pbcopy(text):
            return
        super().copy_to_clipboard(text)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self.controller.on_input_changed(event)

    def on_chat_input_text_area_submitted(self, _: ChatInputTextArea.Submitted) -> None:
        self.controller.submit_chat_input()

    def action_quit(self) -> None:
        self.exit()


def run_tui(queue_in: Queue, queue_out: Queue) -> None:
    """启动 TUI 应用。"""
    AgentApp(queue_in=queue_in, queue_out=queue_out).run()
