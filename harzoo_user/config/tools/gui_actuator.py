"""Desktop GUI action executor without internal LLM planning."""


from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

from harzoo.agent.kernel.llm_util import smart_resize
from harzoo.agent.kernel.tool import Tool, ToolResult

TOOL_VERSION = "2026-05-22"

_SUPPORTED_ACTIONS = {
    "key",
    "type",
    "mouse_move",
    "left_click",
    "left_click_drag",
    "right_click",
    "middle_click",
    "double_click",
    "triple_click",
    "scroll",
    "hscroll",
    "wait",
}
_COORDINATE_ACTIONS = {
    "mouse_move",
    "left_click",
    "left_click_drag",
    "right_click",
    "middle_click",
    "double_click",
    "triple_click",
}


class GuiActionExecutor:
    """底层桌面动作执行器，负责把结构化动作转成鼠标键盘操作。"""
    def __init__(self) -> None:
        try:
            import pyautogui  # type: ignore
            import pyperclip  # type: ignore
            from PIL import Image  # type: ignore
        except Exception as e:
            raise RuntimeError("GUI desktop tools require dependencies: pyautogui, pyperclip, Pillow") from e
        self.pyautogui = pyautogui
        self.pyperclip = pyperclip
        self.Image = Image
        self._paste_hotkey = ("command", "v") if sys.platform == "darwin" else ("ctrl", "v")

    def map_coordinate(self, coordinate: list[Any], image_path: Path) -> tuple[int, int]:
        if len(coordinate) != 2:
            raise ValueError("coordinate must contain [x, y]")
        x_raw = float(coordinate[0])
        y_raw = float(coordinate[1])
        width, height = self.Image.open(str(image_path)).size
        resized_h, resized_w = smart_resize(height, width)

        if x_raw <= 1000 and y_raw <= 1000:
            x = int((x_raw / 1000.0) * width)
            y = int((y_raw / 1000.0) * height)
        elif x_raw <= resized_w and y_raw <= resized_h:
            x = int((x_raw / resized_w) * width)
            y = int((y_raw / resized_h) * height)
        else:
            x = int(x_raw)
            y = int(y_raw)

        x = max(0, min(width - 1, x))
        y = max(0, min(height - 1, y))
        return x, y

    def _normalize_keys(self, keys: Any) -> list[str]:
        if isinstance(keys, str):
            items = [keys]
        elif isinstance(keys, list):
            items = [str(k) for k in keys]
        else:
            raise ValueError("keys must be a string or array")
        key_map = {
            "arrowleft": "left",
            "arrowright": "right",
            "arrowup": "up",
            "arrowdown": "down",
        }
        return [key_map.get(k.strip().lower(), k.strip().lower()) for k in items if str(k).strip()]

    def run_action(self, action: str, arguments: dict[str, Any], image_path: Path) -> None:
        a = action.strip().lower()
        if a == "key":
            keys = self._normalize_keys(arguments.get("keys"))
            if not keys:
                raise ValueError("action=key requires keys")
            if len(keys) == 1:
                self.pyautogui.press(keys[0])
            else:
                self.pyautogui.hotkey(*keys)
            return

        if a == "type":
            text = str(arguments.get("text", ""))
            self.pyperclip.copy(text)
            self.pyautogui.hotkey(*self._paste_hotkey)
            return

        if a == "wait":
            wait_s = float(arguments.get("time", 1.0))
            time.sleep(max(0.0, min(wait_s, 30.0)))
            return

        if a in {"scroll", "hscroll"}:
            pixels = int(float(arguments.get("pixels", 0)))
            if a == "hscroll" and hasattr(self.pyautogui, "hscroll"):
                self.pyautogui.hscroll(pixels)
            else:
                self.pyautogui.scroll(pixels)
            return

        if a in _COORDINATE_ACTIONS:
            coord = arguments.get("coordinate")
            if not isinstance(coord, list):
                raise ValueError(f"action={action} requires coordinate")
            x, y = self.map_coordinate(coord, image_path)
            if a == "left_click_drag":
                self.pyautogui.dragTo(x, y, duration=0.35, button="left")
                return

            self.pyautogui.moveTo(x, y)
            if a == "mouse_move":
                return
            if a == "left_click":
                self.pyautogui.click()
                return
            if a == "right_click":
                self.pyautogui.rightClick()
                return
            if a == "middle_click":
                self.pyautogui.middleClick()
                return
            if a == "double_click":
                self.pyautogui.doubleClick()
                return
            if a == "triple_click":
                self.pyautogui.click(clicks=3, interval=0.05)
                return

        raise ValueError(f"Unsupported action: {action}")


class GuiActuatorTool(Tool):
    """桌面操作工具，执行点击/输入/快捷键等 GUI 动作。"""

    name = "GuiActuator"
    description = "Execute desktop mouse and keyboard actions from explicit arguments."
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": sorted(_SUPPORTED_ACTIONS)},
            "keys": {
                "description": "Required for action=key. Supports string or list.",
                "anyOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ],
            },
            "text": {"type": "string", "description": "Required for action=type."},
            "coordinate": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
                "description": "2D coordinate for mouse actions.",
            },
            "pixels": {"type": "number", "description": "Required by action=scroll/hscroll."},
            "time": {"type": "number", "description": "Wait seconds for action=wait."},
            "screenshot_path": {
                "type": "string",
                "description": "Screenshot path for coordinate mapping on coordinate actions.",
            },
        },
        "required": ["action"],
    }
    risk_level = "high"
    side_effect = True
    idempotent = False

    def _check_gui_capability(self) -> ToolResult | None:
        """检查当前系统是否具备桌面 GUI 控制能力。"""

        if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            return ToolResult.failure(
                "GUI desktop session is unavailable on Linux (missing DISPLAY/WAYLAND_DISPLAY).",
                code="CAPABILITY_UNAVAILABLE",
                data={
                    "os_name": "linux",
                    "next_actions": [
                        "Run in a desktop session for GUI actions, or",
                        "Use Shell/Browser tools in headless/server environments.",
                    ],
                },
            )
        return None

    def _resolve_context_screenshot(
        self,
        screenshot_path: str | None,
        action: str,
    ) -> Path:
        if action not in _COORDINATE_ACTIONS:
            return Path.cwd()
        if not screenshot_path or not str(screenshot_path).strip():
            raise ValueError(f"action={action} requires screenshot_path")
        p = Path(screenshot_path).expanduser().resolve()
        if not p.is_file():
            raise ValueError(f"screenshot_path not found: {p}")
        return p

    def execute(
        self,
        action: str,
        keys: str | list[str] | None = None,
        text: str | None = None,
        coordinate: list[float] | None = None,
        pixels: float | None = None,
        time: float | None = None,
        screenshot_path: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        del kwargs
        capability_error = self._check_gui_capability()
        if capability_error is not None:
            return capability_error
        action_name = str(action).strip().lower()
        if action_name not in _SUPPORTED_ACTIONS:
            return ToolResult.failure(f"Unsupported action: {action}", code="INVALID_ARGUMENTS")

        try:
            executor = GuiActionExecutor()
        except RuntimeError as e:
            return ToolResult.failure(
                str(e),
                code="MISSING_DEPENDENCY",
                data={"next_actions": ["Install dependencies: pip install pyautogui pyperclip Pillow"]},
            )

        args = {"action": action_name}
        if keys is not None:
            args["keys"] = keys
        if text is not None:
            args["text"] = text
        if coordinate is not None:
            args["coordinate"] = list(coordinate)
        if pixels is not None:
            args["pixels"] = pixels
        if time is not None:
            args["time"] = time

        try:
            context_image = self._resolve_context_screenshot(screenshot_path, action_name)
            executor.run_action(action_name, args, context_image)
        except ValueError as e:
            return ToolResult.failure(str(e), code="INVALID_ARGUMENTS")
        except Exception as e:
            return ToolResult.failure(f"Failed to execute action '{action_name}': {e}", code="ACTION_EXECUTION_FAILED")

        return ToolResult.success(
            {
                "action": action_name,
                "arguments": args,
                "context_screenshot": str(context_image) if action_name in _COORDINATE_ACTIONS else None,
            }
        )


TOOL = GuiActuatorTool
