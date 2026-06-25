"""生成 WorldBuilder 应用图标（多分辨率 .ico）。

可复现：改了配色/造型重跑即可。
    uv run python icons/make_icon.py

造型：深蓝圆角瓦片 + 城市天际线剪影（一座青色高楼点睛），
笔触粗、留白足，保证缩到 16px 仍清晰可辨。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 256
RADIUS = 52
BG_TOP = (24, 38, 66)      # 深蓝
BG_BOTTOM = (45, 74, 124)  # 稍亮的蓝
CITY = (232, 238, 247)     # 近白
ACCENT = (79, 209, 197)    # 青色高楼
OUT = Path(__file__).resolve().parent / "worldbuilder.ico"


def _rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius, fill=255)
    return mask


def _gradient(size: int) -> Image.Image:
    grad = Image.new("RGB", (size, size))
    px = grad.load()
    for y in range(size):
        t = y / (size - 1)
        r = round(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
        g = round(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
        b = round(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
        for x in range(size):
            px[x, y] = (r, g, b)
    return grad


def render(size: int = SIZE) -> Image.Image:
    tile = _gradient(size).convert("RGBA")
    tile.putalpha(_rounded_mask(size, RADIUS))
    d = ImageDraw.Draw(tile)

    # 天际线：底对齐的一排楼，宽度/高度按比例。最高一座用青色点睛。
    base = size * 0.80
    # (left, top) 比例，统一宽度
    bw = size * 0.135
    gap = size * 0.045
    start = size * 0.165
    heights = [0.46, 0.30, 0.62, 0.38]  # 第三座最高 -> 青色
    x = start
    for i, h in enumerate(heights):
        top = base - size * h
        color = ACCENT if i == 2 else CITY
        d.rounded_rectangle((x, top, x + bw, base), radius=size * 0.018, fill=color)
        x += bw + gap

    # 地基线，强化"建造"语义
    d.rounded_rectangle((start, base, x - gap, base + size * 0.035),
                        radius=size * 0.014, fill=CITY)
    return tile


def main() -> int:
    master = render(SIZE)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    master.save(OUT, format="ICO", sizes=sizes)
    print(f"[icon] wrote {OUT} ({', '.join(f'{w}x{h}' for w, h in sizes)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
