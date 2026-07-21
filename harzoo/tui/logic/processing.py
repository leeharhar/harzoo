"""输入处理：占位符、路径替换与消息载荷组装。"""

from __future__ import annotations

import mimetypes
import re
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import unquote, urlparse

from harzoo.agent.kernel.message import UserInputSegments

# 占位符中文件名前的中点（U+00B7）
IMAGE_PLACEHOLDER_PATTERN = re.compile(r"\[img·(?P<name>[^\]]+)\]")

_QUOTED_IMAGE_PATH_PATTERN = re.compile(
    r'"([A-Za-z]:[/\\][^"]*?\.(?:png|jpe?g|gif|webp|bmp))"',
    re.IGNORECASE,
)
_UNQUOTED_IMAGE_PATH_PATTERN = re.compile(
    r'\b([A-Za-z]:[/\\](?:[^\\/:*?"<>|\r\n]+[/\\])*[^\\/:*?"<>|\r\n]+\.(?:png|jpe?g|gif|webp|bmp))\b',
    re.IGNORECASE,
)
_FILE_URI_IMAGE_PATTERN = re.compile(
    r"(?i)file:///([A-Za-z]:[^?\s\"]+\.(?:png|jpe?g|gif|webp|bmp))",
)
_IMAGE_FILE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def _find_placeholder_spans(text: str) -> list[tuple[int, int]]:
    return [(match.start(), match.end()) for match in IMAGE_PLACEHOLDER_PATTERN.finditer(text)]


def _normalize_text_part(text_part: str) -> str | None:
    normalized_text = " ".join(text_part.split())
    return normalized_text if normalized_text else None


def format_user_message_for_chat(user_input: str) -> str:
    """聊天区展示用：将内部占位符转为 [Image 文件名]。"""

    def _replace_placeholder(match: re.Match[str]) -> str:
        return f"[Image {match.group('name').strip()}]"

    return IMAGE_PLACEHOLDER_PATTERN.sub(_replace_placeholder, user_input).strip()


def _spans_overlap(start_index: int, end_index: int, spans: list[tuple[int, int]]) -> bool:
    return any(not (end_index <= span_start or start_index >= span_end) for span_start, span_end in spans)


def _is_image_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.suffix.lower() in _IMAGE_FILE_SUFFIXES:
        return True
    guessed_mime_type, _ = mimetypes.guess_type(str(path))
    return bool(guessed_mime_type and guessed_mime_type.startswith("image/"))


def _resolve_image_path(maybe_path_text: str) -> Path | None:
    normalized_path_text = maybe_path_text.strip().strip('"')
    if not normalized_path_text:
        return None
    if normalized_path_text.lower().startswith("file:"):
        parsed_uri = urlparse(normalized_path_text)
        if parsed_uri.scheme != "file":
            return None
        uri_path = unquote((parsed_uri.path or "").replace("\\", "/"))
        if uri_path.startswith("/") and len(uri_path) > 2 and uri_path[2] == ":":
            uri_path = uri_path[1:]
        normalized_path_text = uri_path
    try:
        resolved_path = Path(normalized_path_text).expanduser().resolve()
    except OSError:
        return None
    return resolved_path if _is_image_file(resolved_path) else None


def _is_match_blocked(
    match_start: int,
    match_end: int,
    placeholder_spans: list[tuple[int, int]],
    claimed_spans: list[tuple[int, int]],
) -> bool:
    return _spans_overlap(match_start, match_end, placeholder_spans) or any(not (match_end <= span_start or match_start >= span_end) for span_start, span_end in claimed_spans)


def _collect_image_path_matches(
    text: str,
    placeholder_spans: list[tuple[int, int]],
) -> list[tuple[int, int, str]]:
    claimed_spans = []
    matched_path_spans = []

    for match in _FILE_URI_IMAGE_PATTERN.finditer(text):
        span_start, span_end = match.start(), match.end()
        if _is_match_blocked(span_start, span_end, placeholder_spans, claimed_spans):
            continue
        claimed_spans.append((span_start, span_end))
        matched_path_spans.append((span_start, span_end, match.group(0)))

    for path_pattern in (_QUOTED_IMAGE_PATH_PATTERN, _UNQUOTED_IMAGE_PATH_PATTERN):
        for match in path_pattern.finditer(text):
            span_start, span_end = match.start(), match.end()
            if _is_match_blocked(span_start, span_end, placeholder_spans, claimed_spans):
                continue
            claimed_spans.append((span_start, span_end))
            matched_path_spans.append((span_start, span_end, match.group(1)))

    matched_path_spans.sort(key=lambda item: item[0])
    return matched_path_spans


def replace_image_paths_with_placeholders(
    previous_text: str,
    current_text: str,
    image_attachments: list[Path],
) -> str | None:
    """将可识别的图片路径替换为 [img·文件名]，按从左到右顺序追加附件。"""
    if previous_text == current_text:
        return None
    matched_path_spans = _collect_image_path_matches(
        current_text,
        _find_placeholder_spans(current_text),
    )
    if not matched_path_spans:
        return None

    resolved_image_spans = []
    for span_start, span_end, matched_path_text in matched_path_spans:
        resolved_path = _resolve_image_path(matched_path_text)
        if resolved_path is not None:
            resolved_image_spans.append((span_start, span_end, resolved_path))
    if not resolved_image_spans:
        return None

    text_with_placeholders = current_text
    for span_start, span_end, resolved_path in sorted(
        resolved_image_spans,
        key=lambda item: item[0],
        reverse=True,
    ):
        text_with_placeholders = text_with_placeholders[:span_start] + f"[img·{resolved_path.name}]" + text_with_placeholders[span_end:]
    for _, _, resolved_path in sorted(resolved_image_spans, key=lambda item: item[0]):
        image_attachments.append(resolved_path)
    return text_with_placeholders


def sync_attachments_with_placeholders(
    user_input: str,
    image_attachments: list[Path],
) -> None:
    """按 [img·name] 占位符顺序同步附件列表。"""
    placeholder_names = [match.group("name").strip() for match in IMAGE_PLACEHOLDER_PATTERN.finditer(user_input)]
    attachments_by_name = defaultdict(deque)
    for attachment_path in image_attachments:
        attachments_by_name[attachment_path.name].append(attachment_path)

    synchronized_attachments = []
    for placeholder_name in placeholder_names:
        attachment_queue = attachments_by_name.get(placeholder_name)
        if not attachment_queue:
            image_attachments.clear()
            return
        synchronized_attachments.append(attachment_queue.popleft())
    image_attachments[:] = synchronized_attachments


def build_user_message_content_parts(
    user_input: str,
    image_attachments: list[Path],
) -> UserInputSegments:
    """组装 user_message 的 content 片段，交替 text 与 image_path。"""
    content_parts: UserInputSegments = []
    text_cursor = 0
    attachment_index = 0
    for placeholder_match in IMAGE_PLACEHOLDER_PATTERN.finditer(user_input):
        prefix_text = user_input[text_cursor : placeholder_match.start()]
        normalized_text = _normalize_text_part(prefix_text)
        if normalized_text is not None:
            content_parts.append({"type": "text", "text": normalized_text})

        placeholder_name = placeholder_match.group("name").strip()
        if attachment_index >= len(image_attachments):
            raise ValueError(f"Missing image attachment for placeholder [img·{placeholder_name}]")
        attachment_path = image_attachments[attachment_index]
        if attachment_path.name != placeholder_name:
            raise ValueError(f"Placeholder [img·{placeholder_name}] does not match attachment " f"{attachment_path.name!r}")

        attachment_index += 1
        content_parts.append({"type": "image_path", "image_path": str(attachment_path.resolve())})
        text_cursor = placeholder_match.end()

    remaining_text = user_input[text_cursor:]
    normalized_remaining_text = _normalize_text_part(remaining_text)
    if normalized_remaining_text is not None:
        content_parts.append({"type": "text", "text": normalized_remaining_text})
    if attachment_index != len(image_attachments):
        raise ValueError("Extra image attachments not referenced in the input line")
    return content_parts
