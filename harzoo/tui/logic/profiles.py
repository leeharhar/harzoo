"""TUI profile 列表：stem 列宽与 description 摘要。"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from harzoo.agent.components.paths import list_profile_markdown_files
from harzoo.agent.components.util import load_yaml_front_matter_markdown

_BLURB_SEP_RE = re.compile(r"[,，.。\-—–:：;；]+")


@dataclass(frozen=True, slots=True)
class ProfileEntry:
    stem: str
    name: str
    description: str


def _char_display_width(ch: str) -> int:
    eaw = unicodedata.east_asian_width(ch)
    if eaw in ("F", "W"):
        return 2
    if eaw == "A" and "\u4e00" <= ch <= "\u9fff":
        return 2
    return 1


def display_width(text: str) -> int:
    return sum(_char_display_width(ch) for ch in text)


def profile_list_blurb(text: str) -> str:
    """TUI 右侧摘要：第一个分隔符（, ， . 。 - — 等）左侧文本。"""

    compact = " ".join(text.split()).strip()
    if not compact:
        return ""
    return _BLURB_SEP_RE.split(compact, maxsplit=1)[0].strip()


def pad_display(text: str, target_width: int) -> str:
    gap = target_width - display_width(text)
    if gap <= 0:
        return text
    return text + (" " * gap)


_LABEL_MIN_DISPLAY_WIDTH = 40
_LABEL_EXTRA_PAD = 8


def format_profile_option_line(
    entry: ProfileEntry,
    *,
    label_column_width: int,
) -> str:
    desc = entry.description or entry.name or entry.stem
    return f"{pad_display(entry.stem, label_column_width)} {desc}"


def profile_label_column_width(entries: Sequence[ProfileEntry]) -> int:
    if not entries:
        return _LABEL_MIN_DISPLAY_WIDTH
    content = max(display_width(entry.stem) for entry in entries)
    return max(_LABEL_MIN_DISPLAY_WIDTH, content + _LABEL_EXTRA_PAD)


def _entry_from_path(path: Path) -> ProfileEntry | None:
    try:
        meta, _ = load_yaml_front_matter_markdown(path)
    except (OSError, ValueError):
        return None
    description = str(meta.get("description") or "").strip()
    return ProfileEntry(
        stem=path.stem,
        name=str(meta.get("name") or "").strip(),
        description=profile_list_blurb(description),
    )


def list_profile_entries(profiles_root: Path) -> list[ProfileEntry]:
    return [
        entry
        for path in list_profile_markdown_files(profiles_root.resolve())
        if (entry := _entry_from_path(path))
    ]
