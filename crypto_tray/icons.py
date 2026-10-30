"""比特币样式的程序图标，托盘、窗口和 exe 共用。"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

_ORANGE = (247, 147, 26, 255)
_WHITE = (255, 255, 255, 255)


def _font(size: int) -> ImageFont.ImageFont:
    pixel = max(8, int(size * 0.56))
    for path in (
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ):
        try:
            return ImageFont.truetype(path, pixel)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_icon(size: int) -> Image.Image:
    """橙色圆底上的白色 B 和两道竖线，小尺寸也能认出是加密货币。"""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = max(0, size // 32)
    draw.ellipse((margin, margin, size - 1 - margin, size - 1 - margin), fill=_ORANGE)

    font = _font(size)
    text = "B"
    box = font.getbbox(text)
    text_w = box[2] - box[0]
    text_h = box[3] - box[1]
    center = size / 2
    draw.text(
        (center - text_w / 2 - box[0], center - text_h / 2 - box[1] - size * 0.02),
        text,
        font=font,
        fill=_WHITE,
    )

    stroke = max(1, round(size * 0.045))
    gap = size * 0.10
    top = size * 0.20
    bottom = size * 0.80
    for offset in (-gap, gap):
        x = center + offset
        draw.line((x, top, x, bottom), fill=_WHITE, width=stroke)
    return image


def save_ico(path: str) -> None:
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    image = draw_icon(256)
    image.save(
        path,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
