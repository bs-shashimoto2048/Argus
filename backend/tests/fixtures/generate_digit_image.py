"""OCR/YOLOのSmoke Test用に、単純な数字画像を生成するヘルパー。

フォント指定に依存するため、環境によって描画結果の見た目が変わりうる。
そのため呼び出し側のテストは`optional_inference`マーカーで隔離すること。
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def generate_digit_image(text: str = "002560", width: int = 320, height: int = 120) -> np.ndarray:
    """白背景に黒文字で`text`を描画したBGR numpy配列(OpenCV互換)を返す。"""
    image = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)
    font = _load_font(height)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width, text_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    position = (max(0, (width - text_width) // 2), max(0, (height - text_height) // 2))
    draw.text(position, text, fill=(0, 0, 0), font=font)
    array = np.array(image)
    return array[:, :, ::-1].copy()  # RGB -> BGR


def _load_font(height: int) -> ImageFont.ImageFont:
    size = int(height * 0.7)
    for name in ("arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()
