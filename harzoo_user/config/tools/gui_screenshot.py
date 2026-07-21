"""Desktop screenshot tool for GUI observation."""


from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from harzoo.agent.kernel.tool import Tool, ToolResult

TOOL_VERSION = "2026-05-22"


class GuiScreenshotTool(Tool):
    """桌面截图工具，用于给模型提供当前 GUI 观察信息。"""

    name = "GuiScreenshot"
    description = "Capture desktop screenshot for GUI observation and planning."
    parameters = {"type": "object", "properties": {"output_dir": {"type": "string", "description": "Optional output directory."}, "filename": {"type": "string", "description": "Optional file name (png)."}}}

    def _check_gui_capability(self) -> ToolResult | None:
        """检查当前系统是否具备桌面截图能力。"""

        if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            return ToolResult.failure(
                "GUI desktop session is unavailable on Linux (missing DISPLAY/WAYLAND_DISPLAY).",
                code="CAPABILITY_UNAVAILABLE",
                data={
                    "os_name": "linux",
                    "next_actions": [
                        "Run in a desktop session, or",
                        "Use Browser/WebFetch tools in headless/server environments.",
                    ],
                },
            )
        return None

    def execute(self, output_dir: str | None = None, filename: str | None = None, **kwargs: Any) -> ToolResult:
        del kwargs
        capability_error = self._check_gui_capability()
        if capability_error is not None:
            return capability_error
        out_dir = Path(output_dir).expanduser().resolve() if output_dir else Path(tempfile.mkdtemp(prefix="gui_screenshot_"))
        out_dir.mkdir(parents=True, exist_ok=True)
        fname = (filename or f"screenshot_{int(time.time() * 1000)}.png").strip()
        if not fname: fname = f"screenshot_{int(time.time() * 1000)}.png"
        if not fname.lower().endswith(".png"): fname = f"{fname}.png"
        image_path = out_dir / fname
        try:
            import pyautogui  # type: ignore
        except Exception as e:
            return ToolResult.failure(
                f"GUI screenshot tool requires dependency: pyautogui ({e})",
                code="MISSING_DEPENDENCY",
                data={"next_actions": ["Install dependency: pip install pyautogui Pillow"]},
            )
        try:
            pyautogui.screenshot().save(str(image_path))
        except Exception as e:
            return ToolResult.failure(f"Failed to capture screenshot: {e}", code="ACTION_EXECUTION_FAILED")
        image_path_str = str(image_path)
        return ToolResult.success(
            {"captured": True, "image_path": image_path_str},
            injected_user_input_segments=[{"type": "text", "text": f"[OBSERVATION_FROM_IMAGE_TOOL] Current observation image.\nsource_path: {image_path_str}"}, {"type": "image_path", "image_path": image_path_str}],
        )


TOOL = GuiScreenshotTool
