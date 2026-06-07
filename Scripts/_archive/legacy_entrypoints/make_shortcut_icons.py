#!/usr/bin/env python3
"""Generate local Windows shortcut icons for VirtualCity.

The icons are pure stdlib-generated ICO files so the root .lnk shortcuts can
look like first-class tools without depending on design apps or Pillow.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "Scripts" / "icons"
SCALE = 4
SIZE = 256


class Canvas:
    def __init__(self, size: int = SIZE, scale: int = SCALE):
        self.size = size
        self.scale = scale
        self.w = size * scale
        self.h = size * scale
        self.pixels = bytearray([0, 0, 0, 0] * self.w * self.h)

    def _blend_px(self, x: int, y: int, color: tuple[int, int, int, int]) -> None:
        if x < 0 or y < 0 or x >= self.w or y >= self.h:
            return
        r, g, b, a = color
        if a <= 0:
            return
        idx = (y * self.w + x) * 4
        if a >= 255:
            self.pixels[idx : idx + 4] = bytes((r, g, b, 255))
            return
        inv = 255 - a
        self.pixels[idx] = (r * a + self.pixels[idx] * inv) // 255
        self.pixels[idx + 1] = (g * a + self.pixels[idx + 1] * inv) // 255
        self.pixels[idx + 2] = (b * a + self.pixels[idx + 2] * inv) // 255
        self.pixels[idx + 3] = min(255, a + self.pixels[idx + 3] * inv // 255)

    def _s(self, value: float) -> int:
        return int(round(value * self.scale))

    def rounded_rect(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        radius: float,
        color: tuple[int, int, int, int],
    ) -> None:
        sx0, sy0, sx1, sy1, sr = map(self._s, (x0, y0, x1, y1, radius))
        for y in range(sy0, sy1):
            for x in range(sx0, sx1):
                dx = max(sx0 + sr - x, 0, x - (sx1 - sr - 1))
                dy = max(sy0 + sr - y, 0, y - (sy1 - sr - 1))
                if dx * dx + dy * dy <= sr * sr:
                    self._blend_px(x, y, color)

    def gradient_rounded_rect(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        radius: float,
        top: tuple[int, int, int],
        bottom: tuple[int, int, int],
    ) -> None:
        sx0, sy0, sx1, sy1, sr = map(self._s, (x0, y0, x1, y1, radius))
        height = max(1, sy1 - sy0)
        for y in range(sy0, sy1):
            t = (y - sy0) / height
            color = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3)) + (255,)
            for x in range(sx0, sx1):
                dx = max(sx0 + sr - x, 0, x - (sx1 - sr - 1))
                dy = max(sy0 + sr - y, 0, y - (sy1 - sr - 1))
                if dx * dx + dy * dy <= sr * sr:
                    self._blend_px(x, y, color)

    def line(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        width: float,
        color: tuple[int, int, int, int],
    ) -> None:
        sx0, sy0, sx1, sy1, sw = map(self._s, (x0, y0, x1, y1, width))
        pad = sw + 2
        minx, maxx = min(sx0, sx1) - pad, max(sx0, sx1) + pad
        miny, maxy = min(sy0, sy1) - pad, max(sy0, sy1) + pad
        vx, vy = sx1 - sx0, sy1 - sy0
        denom = max(1, vx * vx + vy * vy)
        radius = sw / 2
        for y in range(miny, maxy + 1):
            for x in range(minx, maxx + 1):
                t = max(0, min(1, ((x - sx0) * vx + (y - sy0) * vy) / denom))
                px, py = sx0 + t * vx, sy0 + t * vy
                if math.hypot(x - px, y - py) <= radius:
                    self._blend_px(x, y, color)

    def circle(self, cx: float, cy: float, radius: float, color: tuple[int, int, int, int]) -> None:
        scx, scy, sr = map(self._s, (cx, cy, radius))
        for y in range(scy - sr, scy + sr + 1):
            for x in range(scx - sr, scx + sr + 1):
                if (x - scx) ** 2 + (y - scy) ** 2 <= sr * sr:
                    self._blend_px(x, y, color)

    def polygon(self, points: list[tuple[float, float]], color: tuple[int, int, int, int]) -> None:
        pts = [(self._s(x), self._s(y)) for x, y in points]
        minx, maxx = min(x for x, _ in pts), max(x for x, _ in pts)
        miny, maxy = min(y for _, y in pts), max(y for _, y in pts)
        for y in range(miny, maxy + 1):
            for x in range(minx, maxx + 1):
                inside = False
                j = len(pts) - 1
                for i, (xi, yi) in enumerate(pts):
                    xj, yj = pts[j]
                    if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / max(1, yj - yi) + xi):
                        inside = not inside
                    j = i
                if inside:
                    self._blend_px(x, y, color)

    def arc_arrow(
        self,
        cx: float,
        cy: float,
        radius: float,
        start_deg: float,
        end_deg: float,
        width: float,
        color: tuple[int, int, int, int],
    ) -> None:
        steps = 42
        last = None
        for i in range(steps + 1):
            t = i / steps
            a = math.radians(start_deg * (1 - t) + end_deg * t)
            point = (cx + math.cos(a) * radius, cy + math.sin(a) * radius)
            if last:
                self.line(last[0], last[1], point[0], point[1], width, color)
            last = point
        a = math.radians(end_deg)
        tip = (cx + math.cos(a) * radius, cy + math.sin(a) * radius)
        tangent = a + math.pi / 2
        self.polygon(
            [
                tip,
                (tip[0] - math.cos(a) * 17 + math.cos(tangent) * 9, tip[1] - math.sin(a) * 17 + math.sin(tangent) * 9),
                (tip[0] - math.cos(a) * 17 - math.cos(tangent) * 9, tip[1] - math.sin(a) * 17 - math.sin(tangent) * 9),
            ],
            color,
        )

    def downsample(self) -> bytes:
        out = bytearray()
        s = self.scale
        for y in range(self.size):
            for x in range(self.size):
                acc = [0, 0, 0, 0]
                for yy in range(s):
                    for xx in range(s):
                        idx = ((y * s + yy) * self.w + (x * s + xx)) * 4
                        for i in range(4):
                            acc[i] += self.pixels[idx + i]
                area = s * s
                out.extend(v // area for v in acc)
        return bytes(out)


def png_bytes(width: int, height: int, rgba: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    rows = bytearray()
    stride = width * 4
    for y in range(height):
        rows.append(0)
        rows.extend(rgba[y * stride : (y + 1) * stride])
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )


def ico_bytes(png: bytes, size: int = SIZE) -> bytes:
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0 if size == 256 else size, 0 if size == 256 else size, 0, 0, 1, 32, len(png), 22)
    return header + entry + png


def add_card_shadow(canvas: Canvas, x0: int, y0: int, x1: int, y1: int, radius: int) -> None:
    canvas.rounded_rect(x0 + 4, y0 + 6, x1 + 4, y1 + 6, radius, (2, 6, 23, 60))


def make_console_icon() -> bytes:
    c = Canvas()
    c.gradient_rounded_rect(14, 14, 242, 242, 44, (14, 165, 233), (30, 58, 138))
    c.circle(205, 42, 42, (255, 255, 255, 24))
    c.circle(48, 214, 54, (8, 47, 73, 92))
    add_card_shadow(c, 45, 50, 211, 176, 18)
    c.rounded_rect(45, 50, 211, 176, 18, (248, 250, 252, 255))
    c.rounded_rect(45, 50, 211, 72, 18, (226, 232, 240, 255))
    c.circle(61, 61, 4, (239, 68, 68, 255))
    c.circle(75, 61, 4, (245, 158, 11, 255))
    c.circle(89, 61, 4, (34, 197, 94, 255))
    for x in (78, 112, 146, 180):
        c.line(x, 84, x, 162, 2, (203, 213, 225, 255))
    for y in (96, 118, 140):
        c.line(62, y, 194, y, 2, (203, 213, 225, 255))
    c.line(74, 148, 117, 119, 6, (37, 99, 235, 210))
    c.line(117, 119, 163, 127, 6, (37, 99, 235, 210))
    c.line(163, 127, 188, 91, 6, (37, 99, 235, 210))
    c.rounded_rect(95, 88, 179, 144, 10, (14, 165, 233, 44))
    c.line(95, 88, 179, 88, 5, (8, 145, 178, 255))
    c.line(179, 88, 179, 144, 5, (8, 145, 178, 255))
    c.line(179, 144, 95, 144, 5, (8, 145, 178, 255))
    c.line(95, 144, 95, 88, 5, (8, 145, 178, 255))
    c.polygon([(160, 155), (205, 200), (184, 206), (174, 228), (151, 160)], (15, 23, 42, 210))
    c.polygon([(163, 153), (207, 196), (186, 200), (176, 221), (155, 160)], (250, 204, 21, 255))
    return ico_bytes(png_bytes(SIZE, SIZE, c.downsample()))


def make_reset_icon() -> bytes:
    c = Canvas()
    c.gradient_rounded_rect(14, 14, 242, 242, 44, (15, 23, 42), (17, 94, 89))
    c.circle(208, 48, 36, (45, 212, 191, 38))
    c.circle(48, 210, 50, (56, 189, 248, 36))
    add_card_shadow(c, 57, 124, 199, 183, 16)
    c.rounded_rect(57, 124, 199, 183, 16, (248, 250, 252, 255))
    c.rounded_rect(70, 138, 185, 151, 5, (148, 163, 184, 255))
    c.rounded_rect(70, 160, 185, 173, 5, (148, 163, 184, 255))
    c.circle(83, 144, 4, (20, 184, 166, 255))
    c.circle(83, 166, 4, (14, 165, 233, 255))
    c.arc_arrow(128, 116, 62, 210, 16, 12, (45, 212, 191, 255))
    c.arc_arrow(128, 116, 62, 30, 196, 12, (96, 165, 250, 255))
    c.rounded_rect(103, 87, 153, 137, 14, (15, 23, 42, 225))
    c.circle(128, 112, 17, (248, 250, 252, 255))
    c.circle(128, 112, 7, (20, 184, 166, 255))
    c.line(128, 88, 128, 77, 7, (15, 23, 42, 225))
    c.line(128, 147, 128, 136, 7, (15, 23, 42, 225))
    c.line(104, 112, 93, 112, 7, (15, 23, 42, 225))
    c.line(163, 112, 152, 112, 7, (15, 23, 42, 225))
    c.circle(199, 184, 27, (34, 197, 94, 255))
    c.line(187, 184, 197, 194, 6, (255, 255, 255, 255))
    c.line(197, 194, 213, 174, 6, (255, 255, 255, 255))
    return ico_bytes(png_bytes(SIZE, SIZE, c.downsample()))


def main() -> int:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    (ICON_DIR / "virtualcity_console.ico").write_bytes(make_console_icon())
    (ICON_DIR / "virtualcity_reset.ico").write_bytes(make_reset_icon())
    print(f"Wrote {ICON_DIR / 'virtualcity_console.ico'}")
    print(f"Wrote {ICON_DIR / 'virtualcity_reset.ico'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
