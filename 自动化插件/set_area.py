"""
VirtualCity — 一键换区/扩区脚本
=================================
从 bbox 坐标开始，完整跑通整条数据管线。

用法:
    uv run python 自动化插件/set_area.py <west> <south> <east> <north> [area_name]

示例（在 bboxfinder.com 框选后复制坐标）:
    uv run python 自动化插件/set_area.py 100.840 12.900 100.930 12.970 pattaya_new

步骤（5 步）:
    1. 更新 active_area.json
    2. 下载 OSM 数据
    3. 下载 DEM 数据
    4. 下载建筑高度（Google Open Buildings，需 GEE 登录）
    5. validate_data.py 验证 → Houdini recook + 更新裁剪节点
    ⚠ 导出（export_and_import.py）需用户确认视口后手动运行

Houdini 必须已打开。UE5 可稍后打开。
"""

import sys, os, json, math, subprocess, time
from pathlib import Path

ROOT      = Path(r"F:/VirtualCity")
CFG_PATH  = ROOT / "配置/active_area.json"
DATA_ROOT = ROOT / "原始数据"
SCRIPTS   = ROOT / "自动化插件"
HIP       = str(ROOT / "Houdini/Hip/VC_pattaya_sai6_mvp_citygen_v001.hip")

# ── 0. 解析参数 ───────────────────────────────────────
if len(sys.argv) < 5:
    print("用法: uv run python 自动化插件/set_area.py <west> <south> <east> <north> [area_name]")
    print("示例: uv run python 自动化插件/set_area.py 100.840 12.900 100.930 12.970 pattaya_new")
    sys.exit(1)

west, south, east, north = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
area_name = sys.argv[5] if len(sys.argv) > 5 else f"area_{west:.3f}_{south:.3f}"

origin_lon = (west + east) / 2
origin_lat = (south + north) / 2
bbox_w = (east - west) * math.cos(math.radians(origin_lat)) * 111319.9
bbox_h = (north - south) * 111319.9

print(f"\n{'='*50}")
print(f"[VirtualCity] 设置区域: {area_name}")
print(f"  bbox: [{west}, {south}, {east}, {north}]")
print(f"  中心: ({origin_lon:.4f}, {origin_lat:.4f})")
print(f"  尺寸: {bbox_w/1000:.1f} km × {bbox_h/1000:.1f} km")
print(f"{'='*50}\n")

osm_path       = str(DATA_ROOT / f"OSM/{area_name}_osm_v001.osm")
buildings_path = str(DATA_ROOT / f"Overture/{area_name}_buildings_height_v001.geojson")
dem_tif_path   = str(DATA_ROOT / f"DEM/{area_name}_dem_v001.tif")
dem_csv_path   = str(DATA_ROOT / f"DEM/{area_name}_dem_v001.csv")

# ── 1. 更新 active_area.json ─────────────────────────
cfg = {
    "area_id":        area_name,
    "osm_file":       osm_path.replace("\\", "/"),
    "buildings_file": buildings_path.replace("\\", "/"),
    "dem_csv":        dem_csv_path.replace("\\", "/"),
    "origin_lon":     origin_lon,
    "origin_lat":     origin_lat,
    "_note":          "切换区域只改此文件，不改 Houdini 节点代码"
}
CFG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"[1/5] ✅ active_area.json 已更新: {area_name}")

# ── 2. 下载 OSM ──────────────────────────────────────
print(f"\n[2/5] 下载 OSM 数据...")
import urllib.request, urllib.parse

OVERPASS_SERVERS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
s, w, n, e = south, west, north, east
query = (
    f"[out:xml][timeout:180];\n"
    f"(\n"
    f'  way["building"]({s},{w},{n},{e});\n'
    f'  way["highway"]({s},{w},{n},{e});\n'
    f'  relation["building"]({s},{w},{n},{e});\n'
    f");\n"
    f"out body;\n>;\nout skel qt;\n"
)
Path(osm_path).parent.mkdir(parents=True, exist_ok=True)
osm_ok = False
for server in OVERPASS_SERVERS:
    try:
        data = urllib.parse.urlencode({"data": query}).encode()
        req  = urllib.request.Request(server, data=data,
                                      headers={"User-Agent": "VirtualCity/1.0"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            content = resp.read()
        with open(osm_path, "wb") as f:
            f.write(content)
        print(f"  ✅ OSM: {len(content)//1024} KB → {osm_path}")
        osm_ok = True
        break
    except Exception as ex:
        print(f"  ⚠ {server}: {ex}")
        time.sleep(3)
if not osm_ok:
    print("  ❌ OSM 下载失败，请检查网络后重试")
    sys.exit(1)

# ── 3. 下载 DEM ──────────────────────────────────────
print(f"\n[3/5] 下载 DEM 数据...")
try:
    sys.path.insert(0, str(SCRIPTS))
    import download_dem as _dem
    Path(dem_csv_path).parent.mkdir(parents=True, exist_ok=True)
    bbox = [west, south, east, north]
    ok = _dem.download_copernicus_10m(bbox, dem_tif_path, dem_csv_path)
    if not ok:
        _dem.download_gee({"bbox": bbox, "output_tif": dem_tif_path,
                           "output_csv": dem_csv_path}, source="nasadem")
    print(f"  ✅ DEM 完成")
except Exception as ex:
    print(f"  ❌ DEM 下载失败: {ex}")
    sys.exit(1)

# ── 4. 下载建筑高度 ──────────────────────────────────
print(f"\n[4/5] 下载建筑高度（Google Open Buildings，需 GEE 认证）...")
Path(buildings_path).parent.mkdir(parents=True, exist_ok=True)
bld_script = str(SCRIPTS / "download_building_heights.py")
bld_cmd = [
    sys.executable, bld_script,
    "--bbox", str(west), str(south), str(east), str(north),
    "--output", buildings_path,
]
result = subprocess.run(bld_cmd, capture_output=False)
if result.returncode != 0 or not Path(buildings_path).exists():
    print(f"  ❌ 建筑高度下载失败（returncode={result.returncode}）")
    sys.exit(1)
print(f"  ✅ 建筑高度完成")

# ── 5. 验证 + Houdini recook ─────────────────────────
print(f"\n[5/5] 数据验证 + Houdini 重算...")

# 5a. validate_data.py
vld = subprocess.run([sys.executable, str(SCRIPTS / "validate_data.py")],
                     capture_output=False)
if vld.returncode != 0:
    print("\n  ❌ 数据验证未通过，中止流程，请修复后重新运行")
    sys.exit(1)

# 5b. Houdini recook + 修复 SOP + 重建裁剪节点
# 注意：必须从 SCRIPTS 目录运行（pyproject.toml 在那里，rpyc==4.1.0 才可用）
print("\n  ♻ Houdini 重算中（_recook_new_area.py）...")
recook = subprocess.run(
    ["uv", "run", "python", "_recook_new_area.py"],
    cwd=str(SCRIPTS),
    capture_output=False,
)
if recook.returncode != 0:
    print("\n  ❌ Houdini 重算失败，中止流程")
    sys.exit(1)

# ── 完成：等待用户确认 ────────────────────────────────
print(f"""
{'='*50}
✅ 数据下载和 Houdini 重算完成: {area_name}
{'='*50}

⚠  下一步（需人工确认）：
   1. 在 Houdini 视口选中 OUT_city，按 D 检查：
      - 建筑是否在地形上
      - 道路是否正常
      - 无异常水片或空洞
   2. 确认视口正常后，运行导出：
      uv run python 自动化插件/export_and_import.py
""")
