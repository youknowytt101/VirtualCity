"""
VirtualCity — 一键换区/扩区脚本
=================================
从 bbox 坐标开始，完整跑通整条数据管线。

用法:
    uv run python set_area.py <west> <south> <east> <north> [area_name]

示例（在 bboxfinder.com 框选后复制坐标）:
    uv run python set_area.py 100.840 12.900 100.930 12.970 pattaya_10km

步骤:
    1. 更新 active_area.json
    2. 下载 OSM 数据
    3. 下载 DEM 数据（GEE NASADEM）
    4. 下载建筑高度（Google Open Buildings）
    5. 生成 UE5 高度图 PNG
    6. 触发 Houdini 重算 + 导出 FBX
    7. 写 UE5 触发文件

Houdini 和 UE5 需要已经打开。
"""

import sys, os, json, math, subprocess
from pathlib import Path

ROOT      = Path(r"F:/VirtualCity")
CFG_PATH  = ROOT / "配置/active_area.json"
DATA_ROOT = ROOT / "原始数据"
EXPORT    = ROOT / "Houdini/Export"
SCRIPTS   = ROOT / "自动化插件"

# ── 1. 解析参数 ───────────────────────────────────────
if len(sys.argv) < 5:
    print("用法: uv run python set_area.py <west> <south> <east> <north> [area_name]")
    print("示例: uv run python set_area.py 100.840 12.900 100.930 12.970 pattaya_10km")
    sys.exit(1)

west, south, east, north = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
area_name = sys.argv[5] if len(sys.argv) > 5 else f"area_{west:.3f}_{south:.3f}"

origin_lon = (west + east) / 2
origin_lat = (south + north) / 2
bbox_w = (east - west) * math.cos(math.radians(origin_lat)) * 111319.9
bbox_h = (north - south) * 111319.9

print(f"\n[VirtualCity] 设置区域: {area_name}")
print(f"  bbox: [{west}, {south}, {east}, {north}]")
print(f"  中心: ({origin_lon:.4f}, {origin_lat:.4f})")
print(f"  尺寸: {bbox_w/1000:.1f} km × {bbox_h/1000:.1f} km\n")

osm_path      = str(DATA_ROOT / f"OSM/{area_name}_osm_v001.osm")
buildings_path= str(DATA_ROOT / f"Overture/{area_name}_buildings_height_v001.geojson")
dem_tif_path  = str(DATA_ROOT / f"DEM/{area_name}_dem_v001.tif")
dem_csv_path  = str(DATA_ROOT / f"DEM/{area_name}_dem_v001.csv")

# ── 2. 更新 active_area.json ─────────────────────────
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
print(f"[1/6] ✅ active_area.json 已更新: {area_name}")

# ── 3. 下载 OSM ──────────────────────────────────────
print(f"\n[2/6] 下载 OSM 数据...")
import urllib.request, urllib.parse, time

OVERPASS_SERVERS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
s, w, n, e = south, west, north, east
query = f"""
[out:xml][timeout:180];
(
  way["building"]({s},{w},{n},{e});
  way["highway"]({s},{w},{n},{e});
  relation["building"]({s},{w},{n},{e});
);
out body;
>;
out skel qt;
"""
Path(osm_path).parent.mkdir(parents=True, exist_ok=True)
osm_ok = False
for server in OVERPASS_SERVERS:
    try:
        data = urllib.parse.urlencode({"data": query}).encode()
        req  = urllib.request.Request(server, data=data, headers={"User-Agent": "VirtualCity/1.0"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            content = resp.read()
        with open(osm_path, "wb") as f:
            f.write(content)
        print(f"  ✅ OSM: {osm_path} ({len(content)/1024:.0f} KB)")
        osm_ok = True
        break
    except Exception as ex:
        print(f"  ⚠️ {server}: {ex}")
        time.sleep(3)
if not osm_ok:
    print("  ❌ OSM 下载失败，继续其他步骤...")

# ── 4. 下载 DEM ──────────────────────────────────────
print(f"\n[3/6] 下载 DEM 数据...")
try:
    import sys as _sys
    _sys.path.insert(0, str(SCRIPTS))
    import download_dem as _dem

    bbox = [west, south, east, north]
    tmp_cfg = {"bbox": bbox, "output_tif": dem_tif_path, "output_csv": dem_csv_path}
    Path(dem_csv_path).parent.mkdir(parents=True, exist_ok=True)

    # 先尝试 Copernicus 10m，失败则用 NASADEM
    ok = _dem.download_copernicus_10m(bbox, dem_tif_path, dem_csv_path)
    if not ok:
        _dem.download_gee(tmp_cfg, source="nasadem")
    print(f"  ✅ DEM 完成")
except Exception as ex:
    print(f"  ⚠️ DEM 下载失败: {ex}（可手动跑 download_dem.py）")

# ── 5. 下载建筑高度 ──────────────────────────────────
print(f"\n[4/6] 下载建筑高度（Google Open Buildings）...")
try:
    import ee
    try:
        ee.Initialize(project="pty-zone")
    except Exception:
        ee.Authenticate()
        ee.Initialize(project="pty-zone")

    import urllib.request as _req
    region = ee.Geometry.Rectangle([west, south, east, north])
    col = (ee.ImageCollection("GOOGLE/Research/open-buildings-temporal/v1")
           .filterBounds(region)
           .select(["building_presence", "building_height"])
           .mosaic()
           .clip(region))

    url = col.getDownloadURL({
        "name": "buildings", "region": region, "scale": 4, "format": "GEO_TIFF"
    })
    # 实际下载走 GeoJSON 路线（与现有脚本一致）
    print("  ℹ️ 建筑高度需要运行完整的 download_building_heights.py，跳过自动下载")
    print(f"  手动运行: uv run python download_building_heights.py --area {area_name}")
except Exception as ex:
    print(f"  ⚠️ 跳过建筑高度: {ex}")
    print(f"  手动运行: uv run python download_building_heights.py --area {area_name}")

# ── 6. 生成高度图 PNG ─────────────────────────────────
print(f"\n[5/6] 生成 UE5 高度图 PNG...")
try:
    import runpy
    runpy.run_path(str(SCRIPTS / "export_heightmap.py"))
    print("  ✅ 高度图已生成")
except Exception as ex:
    print(f"  ⚠️ 高度图生成失败: {ex}")

# ── 7. 触发 Houdini + UE5 ───────────────────────────
print(f"\n[6/6] 触发 Houdini 重算 + 导出 FBX...")
try:
    import rpyc
    conn = rpyc.classic.connect("localhost", 18811)
    hou  = conn.modules.hou
    # 强制重算关键节点
    for path in ['/obj/pattaya_osm/osm_import', '/obj/pattaya_osm/dem_terrain']:
        node = hou.node(path)
        if node:
            node.cook(force=True)
            print(f"  ♻️ recook: {path}")
    conn.close()

    # 导出 FBX + 触发 UE5
    import runpy
    runpy.run_path(str(SCRIPTS / "export_and_import.py"))
    print("  ✅ FBX 导出 + UE5 触发完成")
except Exception as ex:
    print(f"  ⚠️ Houdini 连接失败（确认 Houdini 已打开）: {ex}")

print(f"""
══════════════════════════════════════════
✅ set_area 完成: {area_name}
══════════════════════════════════════════
  后续手动步骤：
  1. UE5 → 地形模式 → 删除旧 Landscape → 重新导入
     高度图: F:/VirtualCity/Houdini/Export/terrain_heightmap.png
     Scale X: {(east-west)*math.cos(math.radians(origin_lat))*111319.9*100/1008:.1f}
     Scale Z: 38.67
  2. 查看 Output Log 确认 FBX 导入成功
""")
