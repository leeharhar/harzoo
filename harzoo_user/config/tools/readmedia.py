"""ReadMedia — read images and PDF documents for multimodal agents."""


from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from harzoo.agent.kernel.tool import Tool, ToolResult, resolve_workspace_path, workspace_root_from

TOOL_VERSION = "2026-06-29"

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"})
PDF_SUFFIXES = frozenset({".pdf"})
MAX_PDF_PAGES = 50
MAX_PDF_TEXT_CHARS = 50_000


def _extract_pdf_text(path: Path, *, max_pages: int) -> tuple[str, int, bool]:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as e:
        raise ImportError("pypdf is required for PDF reading: pip install pypdf") from e
    reader = PdfReader(str(path))
    pages = min(len(reader.pages), max_pages)
    parts: list[str] = []
    for i in range(pages):
        text = reader.pages[i].extract_text() or ""
        parts.append(f"--- Page {i + 1} ---\n{text}")
    full = "\n\n".join(parts)
    truncated = len(full) > MAX_PDF_TEXT_CHARS or len(reader.pages) > max_pages
    if len(full) > MAX_PDF_TEXT_CHARS:
        full = full[:MAX_PDF_TEXT_CHARS]
    return full, len(reader.pages), truncated


class ReadMediaTool(Tool):
    """Read image files (injects vision segment) or extract text from PDFs."""

    name = "ReadMedia"
    description = (
        "Read image files (png, jpg, gif, webp) — injects image for vision models. "
        "Read PDF files — extracts text (requires: pip install pypdf)."
    )
    parameters = {
        "properties": {
            "file_path": {"type": "string", "description": "Path to image or PDF file"},
            "max_pages": {"type": "integer", "description": "Max PDF pages to extract (default 20)", "default": 20},
        },
        "required": ["file_path"],
    }

    def execute(self, file_path: str, max_pages: int = 20, **kwargs: Any) -> ToolResult:
        if not str(file_path).strip():
            return ToolResult.failure("file_path must not be empty", code="INVALID_ARGUMENTS")
        path = resolve_workspace_path(file_path, workspace_root_from(kwargs.get("ctx")))
        if not path.is_file():
            return ToolResult.failure(f"File not found: {file_path}", code="PATH_NOT_FOUND", data={"resolved_path": str(path)})

        suffix = path.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            image_path_str = str(path)
            return ToolResult.success(
                {
                    "file_path": image_path_str,
                    "media_type": "image",
                    "suffix": suffix,
                },
                injected_user_input_segments=[
                    {"type": "text", "text": f"[IMAGE] {path.name}\nsource_path: {image_path_str}"},
                    {"type": "image_path", "image_path": image_path_str},
                ],
            )

        if suffix in PDF_SUFFIXES:
            try:
                n = max(1, min(MAX_PDF_PAGES, int(max_pages)))
            except (TypeError, ValueError):
                return ToolResult.failure("max_pages must be an integer", code="INVALID_ARGUMENTS")
            try:
                text, total_pages, truncated = _extract_pdf_text(path, max_pages=n)
            except ImportError as e:
                return ToolResult.failure(str(e), code="CAPABILITY_UNAVAILABLE")
            except Exception as e:
                return ToolResult.failure(f"{type(e).__name__}: {e}", code="TOOL_EXCEPTION")
            return ToolResult.success(
                {
                    "file_path": str(path),
                    "media_type": "pdf",
                    "total_pages": total_pages,
                    "pages_extracted": min(total_pages, n),
                    "text_truncated": truncated,
                    "text": text,
                }
            )

        return ToolResult.failure(
            f"Unsupported media type: {suffix}. Supported: {sorted(IMAGE_SUFFIXES | PDF_SUFFIXES)}",
            code="UNSUPPORTED_MEDIA",
        )


TOOL = ReadMediaTool
