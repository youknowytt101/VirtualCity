"""
VirtualCity — DEM CSV → UE5 Landscape 16-bit 高度图 PNG
=========================================================
输出:
  - F:/VirtualCity/Houdini/Export/terrain_heightmap.png  (16-bit 灰度)
  - 控制台打印 UE5 Landscape 导入参数
"""
import json, csv, struct, zlib, math
from pathlib import Path

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

def cubic_weight(t):
    """Catmull-Rom 双三次权重"""
    t = abs(t)
    if t < 1:
        return 1.5*t**3 - 2.5*t**2 + 1
    elif t < 2:
        return -0.5*t**3 + 2.5*t**2 - 4*t + 2
    return 0.0

def bicubic(grid, src_cols, src_rows, tx, ty):
    x = tx * (src_cols - 1) / (TARGET - 1)
    y = ty * (src_rows - 1) / (TARGET - 1)
    x0, y0 = int(x), int(y)
    result = 0.0
    for dy in range(-1, 3):
        wy = cubic_weight(y - (y0 + dy))
        for dx in range(-1, 3):
            wx = cubic_weight(x - (x0 + dx))
            xi = max(0, min(src_cols - 1, x0 + dx))
            yi = max(0, min(src_rows - 1, y0 + dy))
            result += wx * wy * grid[yi][xi]
    return result

# 建原始格网（row=lat降序, col=lon升序）
lats_desc = sorted(lats)   # z 从小到大，与 UE5 Y 轴方向一致
src_grid = []
for z in lats_desc:
    row_vals = []
    for x in lons:
        row_vals.append(elev.get((x, z), h_min))
    src_grid.append(row_vals)

# ── 编码为 16-bit ─────────────────────────────────────
# 编码策略: 0m → 32768 (midpoint), h_max → 32768 + (h_max/h_range)*32767
# UE5 height_cm = (pixel - 32768) / 128 × ZScale
pixels = []
for ty in range(TARGET):
    for tx in range(TARGET):
        h = bicubic(src_grid, cols, r_rows, tx, ty)
        # 归一化到 [0, 1]，h_min → 0, h_max → 1
        norm = (h - h_min) / h_range if h_range > 0 else 0.0
        # 编码：0m 在 pixel=32768，最大高度在 pixel=65535
        pixel = int(32768 + norm * 32767)
        pixel = max(0, min(65535, pixel))
        pixels.append(pixel)

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
