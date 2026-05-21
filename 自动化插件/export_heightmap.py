"""
VirtualCity — DEM CSV → UE5 Landscape 16-bit 高度图 PNG
=========================================================
输出:
  - F:/VirtualCity/Houdini/Export/terrain_heightmap.png  (16-bit 灰度)
  - 控制台打印 UE5 Landscape 导入参数
"""
import json, csv, struct, zlib, math
from pathlib import Path
import numpy as np
from PIL import Image

# ── 读取配置 ──────────────────────────────────────────
CFG = json.loads(Path(r"F:/VirtualCity/配置/active_area.json").read_text(encoding="utf-8"))
CSV_FILE = CFG["dem_csv"]
OUT_PNG  = r"F:/VirtualCity/Houdini/Export/terrain_heightmap.png"

# ── 读取 DEM CSV ──────────────────────────────────────
rows = []
with open(CSV_FILE, encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        # CSV 列: x=本地X(m), y=高程(m), z=本地Z(m)
        rows.append((float(row["x"]), float(row["z"]), float(row["y"])))

# 判断格网尺寸（按 x 和 z 坐标推断列/行数）
lons = sorted(set(r[0] for r in rows))   # x 方向
lats = sorted(set(r[1] for r in rows))   # z 方向
cols = len(lons)
r_rows = len(lats)
print(f"DEM 格网: {cols} × {r_rows} = {len(rows)} 点")

# 整理为二维数组，lat 从大到小（UE5 PNG 从北到南）
elev = {}
for x, z, e in rows:
    elev[(x, z)] = e

h_min = min(elev.values())
h_max = max(elev.values())
h_range = h_max - h_min
print(f"高程范围: {h_min:.1f} ~ {h_max:.1f} m  (range={h_range:.1f} m)")

# ── 上采样到 UE5 兼容尺寸（1009 × 1009） ─────────────
# UE5 Landscape 支持: (n × 63 + 1)，如 505=8×63+1, 1009=16×63+1
TARGET = 1009

# 建原始格网（row=z升序, col=x升序）
lats_desc = sorted(lats)
src_grid = []
for z in lats_desc:
    row_vals = []
    for x in lons:
        row_vals.append(elev.get((x, z), h_min))
    src_grid.append(row_vals)

# PIL BICUBIC 上采样（快速）
arr = np.array(src_grid, dtype=np.float32)
img = Image.fromarray(arr, mode='F')
img_resized = img.resize((TARGET, TARGET), Image.BICUBIC)
upsampled = np.array(img_resized, dtype=np.float32)
upsampled = np.clip(upsampled, h_min, h_max)

# ── 编码为 16-bit ─────────────────────────────────────
# 编码策略: 0m → 32768 (midpoint), h_max → 32768 + (h_max/h_range)*32767
# UE5 height_cm = (pixel - 32768) / 128 × ZScale
# 向量化编码为 16-bit
norm = (upsampled - h_min) / h_range if h_range > 0 else np.zeros_like(upsampled)
pixels_np = np.clip((32768 + norm * 32767).astype(np.int32), 0, 65535)
pixels = pixels_np.flatten().tolist()

# ── 写 16-bit 灰度 PNG ────────────────────────────────
def write_png_16bit(path, width, height, pixels):
    def chunk(name, data):
        c = zlib.crc32(name + data) & 0xffffffff
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", c)

    sig = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack(">IIBBBBB", width, height, 16, 0, 0, 0, 0)
    ihdr = chunk(b'IHDR', ihdr_data)

    raw = b""
    for y in range(height):
        raw += b'\x00'  # filter type None
        for x in range(width):
            raw += struct.pack(">H", pixels[y * width + x])
    compressed = zlib.compress(raw, 6)
    idat = chunk(b'IDAT', compressed)
    iend = chunk(b'IEND', b'')

    with open(path, 'wb') as f:
        f.write(sig + ihdr + idat + iend)

write_png_16bit(OUT_PNG, TARGET, TARGET, pixels)
print(f"\n✅ 高度图已导出: {OUT_PNG}  ({TARGET}×{TARGET} px, 16-bit)")

# ── 同时输出 RGBA8 版本（R=高字节，G=低字节），供 UE5 RenderTarget 更新用 ──
RGBA_PNG = OUT_PNG.replace(".png", "_rgba8.png")

def write_png_rgba8(path, width, height, pixels_16bit):
    px = np.array(pixels_16bit, dtype=np.uint16).reshape(height, width)
    hi = (px >> 8).astype(np.uint8)
    lo = (px & 0xFF).astype(np.uint8)
    zero = np.zeros((height, width), dtype=np.uint8)
    alpha = np.full((height, width), 255, dtype=np.uint8)
    rgba = np.stack([hi, lo, zero, alpha], axis=2)
    raw = b""
    for y in range(height):
        raw += b'\x00' + rgba[y].tobytes()
    compressed = zlib.compress(raw, 6)
    def chunk(name, data):
        c = zlib.crc32(name + data) & 0xffffffff
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", c)
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
    idat = chunk(b'IDAT', compressed)
    iend = chunk(b'IEND', b'')
    with open(path, 'wb') as f:
        f.write(sig + ihdr + idat + iend)

write_png_rgba8(RGBA_PNG, TARGET, TARGET, pixels)
print(f"✅ RGBA8 高度图已导出: {RGBA_PNG}  (R=高字节, G=低字节)")

# ── 计算 UE5 Landscape 导入参数 ───────────────────────
# 实际地形尺寸（米，从 Houdini bbox 测量）
world_x_m = max(lons) - min(lons)
world_z_m = max(lats) - min(lats)

# XY Scale: 每个顶点间距（cm）
xy_scale = (world_x_m * 100) / (TARGET - 1)
xy_scale_y = (world_z_m * 100) / (TARGET - 1)

# Z Scale: h_range m 映射到 pixel range (32767 / 128) units
# height_cm = (pixel - 32768) / 128 × ZScale
# h_range × 100 = 32767 / 128 × ZScale
z_scale = (h_range * 100 * 128) / 32767

# Z offset: h_min 对应 pixel=32768，即高度=0，actor Z 需要偏移 h_min
z_offset_cm = h_min * 100

print("\n── UE5 Landscape 导入参数 ──────────────────────")
print(f"  高度图文件  : {OUT_PNG}")
print(f"  Scale X     : {xy_scale:.1f} cm/vertex  ≈ {xy_scale/100:.2f} m")
print(f"  Scale Y     : {xy_scale_y:.1f} cm/vertex  ≈ {xy_scale_y/100:.2f} m")
print(f"  Scale Z     : {z_scale:.2f}")
print(f"  Actor 位置 Z: {z_offset_cm:.0f} cm  ({h_min:.1f} m)")
print(f"  总尺寸      : {(TARGET-1)*xy_scale/100:.0f} m × {(TARGET-1)*xy_scale/100:.0f} m")
print(f"  高程范围    : {h_min:.1f} ~ {h_max:.1f} m")
