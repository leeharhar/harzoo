"""LLM 多模态输入的图片处理（缩放规则、data URL）。"""

from __future__ import annotations

import base64
import copy
import math
from io import BytesIO
from pathlib import Path
from typing import Any


def smart_resize(height: int, width: int, factor: int = 16, min_pixels: int = 3136, max_pixels: int = 1003520 * 200, max_long_side: int = 8192) -> tuple[int, int]:
    """自动调整图片尺寸，避免超出模型上下文 token 上限"""

    def _round_by_factor(number: float, f: int) -> int:
        return int(round(number / f) * f)

    def _ceil_by_factor(number: float, f: int) -> int:
        return int(math.ceil(number / f) * f)

    def _floor_by_factor(number: float, f: int) -> int:
        return int(math.floor(number / f) * f)

    if height < 2 or width < 2:
        raise ValueError("image width/height must be >= 2")
    if max(height, width) / min(height, width) > 200:
        raise ValueError("image aspect ratio too large")

    if max(height, width) > max_long_side:
        beta = max(height, width) / max_long_side
        height, width = int(height / beta), int(width / beta)

    h_bar = _round_by_factor(height, factor)
    w_bar = _round_by_factor(width, factor)

    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = _floor_by_factor(height / beta, factor)
        w_bar = _floor_by_factor(width / beta, factor)
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = _ceil_by_factor(height * beta, factor)
        w_bar = _ceil_by_factor(width * beta, factor)

    return h_bar, w_bar


def image_path_to_resized_png_data_url(path: str | Path) -> str:
    """将本地图片路径转为缩放后的 data URL，供 LLM API 使用"""

    try:
        from PIL import Image  # type: ignore
    except Exception as e:
        raise ValueError("Image preprocessing requires Pillow") from e

    image_path = Path(path).expanduser().resolve()
    with Image.open(str(image_path)) as image:
        width, height = image.size
        resized_h, resized_w = smart_resize(height, width)
        if (resized_w, resized_h) != (width, height):
            image = image.resize((resized_w, resized_h))
        with BytesIO() as buffer:
            image.save(buffer, format="PNG")
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def normalize_user_image_part_for_api(part: dict[str, Any]) -> dict[str, Any]:
    """消息形状转换"""

    ptype = part.get("type")
    if ptype == "image_path":
        local_path = Path(part["image_path"]).expanduser().resolve()
        return {
            "type": "image_url",
            "image_url": {"url": image_path_to_resized_png_data_url(local_path)},
        }
    if ptype == "image_url":
        return {"type": "image_url", "image_url": {"url": part["image_url"]}}
    raise ValueError(f"Invalid part type: {ptype!r}")


def preprocess_chat_state_for_api(state: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """预处理会话状态，重点处理图片消息"""

    normalized_state = copy.deepcopy(state)

    # 获取最后一条用户消息的索引
    last_user_idx = next((idx for idx in range(len(normalized_state) - 1, -1, -1) if normalized_state[idx].get("role") == "user"), -1)
    
    # 若没有用户消息, 则直接返回
    if last_user_idx < 0:
        return normalized_state

    # 遍历会话状态
    for idx, message in enumerate(normalized_state):

        content = message.get("content")

        # 若内容不是列表, 则直接跳过
        if not isinstance(content, list):
            continue

        # 对图片信息进行标准化
        normalized_parts: list[Any] = []
        for part in content:
            ptype = part.get("type")

            # 若类型为图片消息, 则预处理
            if ptype in ("image_url", "image_path"):
                # 若不是最后一条用户消息, 则直接跳过, 即删除该图片消息
                if idx != last_user_idx:
                    continue
                # 预处理图片信息
                normalized_parts.append(normalize_user_image_part_for_api(part))
                continue

            # 若类型为其他消息, 则直接添加
            normalized_parts.append(part)
        message["content"] = normalized_parts
    return normalized_state
