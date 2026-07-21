"""GenerateImage — text-to-image via configurable API providers."""


from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from harzoo.agent.kernel.tool import Tool, ToolResult, resolve_workspace_path, workspace_root_from

TOOL_VERSION = "2026-06-29"


def _openai_generate(prompt: str, *, api_key: str, base_url: str, model: str, size: str) -> bytes:
    url = base_url.rstrip("/") + "/images/generations"
    payload = json.dumps({"model": model, "prompt": prompt, "n": 1, "size": size, "response_format": "b64_json"}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    b64 = data["data"][0]["b64_json"]
    return base64.b64decode(b64)


class GenerateImageTool(Tool):
    """Generate images from text prompts. Uses OpenAI-compatible API (IMAGE_API_KEY, IMAGE_BASE_URL)."""

    name = "GenerateImage"
    description = (
        "Generate images from text prompts. "
        "Set IMAGE_API_KEY, IMAGE_BASE_URL (default OpenAI), IMAGE_MODEL (default dall-e-3)."
    )
    parameters = {
        "properties": {
            "prompt": {"type": "string", "description": "Image generation prompt"},
            "output_path": {"type": "string", "description": "Save path for generated PNG"},
            "size": {"type": "string", "enum": ["1024x1024", "1792x1024", "1024x1792"], "default": "1024x1024"},
        },
        "required": ["prompt"],
    }

    def execute(self, prompt: str, output_path: str | None = None, size: str = "1024x1024", **kwargs: Any) -> ToolResult:
        root = workspace_root_from(kwargs.get("ctx"))
        p = str(prompt or "").strip()
        if not p:
            return ToolResult.failure("prompt must not be empty", code="INVALID_ARGUMENTS")
        api_key = os.environ.get("IMAGE_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return ToolResult.failure("IMAGE_API_KEY or OPENAI_API_KEY required", code="MISSING_API_KEY")
        base_url = os.environ.get("IMAGE_BASE_URL", "https://api.openai.com/v1")
        model = os.environ.get("IMAGE_MODEL", "dall-e-3")
        out = resolve_workspace_path(output_path, root) if output_path else root / "generated_image.png"
        try:
            image_bytes = _openai_generate(p, api_key=api_key, base_url=base_url, model=model, size=str(size or "1024x1024"))
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")[:2000]
            return ToolResult.failure(f"HTTP {e.code}: {err}", code="HTTP_ERROR")
        except urllib.error.URLError as e:
            return ToolResult.failure(str(e.reason), code="NETWORK_ERROR")
        except Exception as e:
            return ToolResult.failure(f"{type(e).__name__}: {e}", code="TOOL_EXCEPTION")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(image_bytes)
        image_path_str = str(out.resolve())
        return ToolResult.success(
            {"prompt": p, "output_path": image_path_str, "size": size, "bytes": len(image_bytes)},
            injected_user_input_segments=[
                {"type": "text", "text": f"[GENERATED IMAGE]\npath: {image_path_str}\nprompt: {p}"},
                {"type": "image_path", "image_path": image_path_str},
            ],
        )


TOOL = GenerateImageTool
