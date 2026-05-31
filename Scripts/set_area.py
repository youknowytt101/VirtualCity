"""
VirtualCity — 一键换区/扩区脚本
=================================
从 bbox 坐标开始，完整跑通整条数据管线。

用法 A — 完整 bbox（bboxfinder.com 框选后复制）:
    uv run python Scripts/set_area.py <west> <south> <east> <north> [area_name]
    例: uv run python Scripts/set_area.py 100.840 12.900 100.930 12.970 pattaya_new

用法 B — 中心点 + 半径（Google Maps 截图 → 复制 URL 中心坐标）:
    uv run python Scripts/set_area.py --center <lon> <lat> <radius_km> [area_name]
    例: uv run python Scripts/set_area.py --center 100.889 12.942 3.0 north_pattaya

用法 C — 直接粘贴 Google Maps URL（自动解析中心 + 用默认 3km 半径）:
    uv run python Scripts/set_area.py --url "https://www.google.com/maps/@12.942,100.889,14z" [area_name]
    例: uv run python Scripts/set_area.py --url "https://maps.google.com/maps/@12.955,100.877,15z" north_pattaya

Google Maps URL 获取方式:
    在 Google Maps 浏览到目标区域 → 复制浏览器地址栏 URL → 粘贴到 --url 参数
    URL 格式: .../@<lat>,<lon>,<zoom>z...

步骤（5 步）:
    1. 更新 active_area.json
    2. 下载 OSM 数据
    3. 下载 DEM 数据
    4. 下载建筑高度
    5. validate_data.py 验证 → Houdini recook + 更新裁剪节点
    [WARN] 导出（export_and_import.py）需用户确认视口后手动运行

Houdini 必须已打开。UE5 可稍后打开。
"""

import sys, os, json, math, subprocess, time, re, atexit
from pathlib import Path
from vc_paths import ROOT, DATA_ROOT, SCRIPTS, HIP, project_relative, write_active_area
from vc_geo import bbox_size_m
import data_cleaning_cache as dcc
import pipeline_state

HIP = str(HIP)

ACQUISITION_PROFILE = dcc.CURRENT_ACQUISITION_PROFILE

# ── 0. 解析参数（支持三种用法）─────────────────────────
def _center_to_bbox(lon: float, lat: float, radius_km: float):
    """从中心点和半径(km)计算 bbox [west, south, east, north]。"""
    delta_lat = radius_km / 111.32
    delta_lon = radius_km / (111.32 * math.cos(math.radians(lat)))
    return lon - delta_lon, lat - delta_lat, lon + delta_lon, lat + delta_lat

def _parse_google_maps_url(url: str):
    """从 Google Maps URL 解析中心坐标，返回 (lat, lon, zoom) 或 None。"""
    # 匹配 /@lat,lon,zoom z 格式
    m = re.search(r'/@(-?\d+\.\d+),(-?\d+\.\d+),([\d.]+)z', url)
    if m:
        return float(m.group(1)), float(m.group(2)), float(m.group(3))
    # 匹配 ?ll=lat,lon 格式
    m = re.search(r'[?&]ll=(-?\d+\.\d+),(-?\d+\.\d+)', url)
    if m:
        return float(m.group(1)), float(m.group(2)), 14.0
    # 匹配 ?q=lat,lon 格式
    m = re.search(r'[?&]q=(-?\d+\.\d+),(-?\d+\.\d+)', url)
    if m:
        return float(m.group(1)), float(m.group(2)), 14.0
    return None

def _zoom_to_radius_km(zoom: float) -> float:
    """根据 Google Maps zoom 级别估算合理的区域半径(km)。"""
    # zoom 15 ≈ 1km, zoom 14 ≈ 2km, zoom 13 ≈ 4km, zoom 12 ≈ 8km
    return max(1.0, min(10.0, 2 ** (15 - zoom)))

if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)

if sys.argv[1] == '--center':
    if len(sys.argv) < 5:
        print("用法: set_area.py --center <lon> <lat> <radius_km> [area_name]")
        sys.exit(1)
    _lon, _lat, _r = float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
    west, south, east, north = _center_to_bbox(_lon, _lat, _r)
    area_name = sys.argv[5] if len(sys.argv) > 5 else f"area_{_lon:.3f}_{_lat:.3f}"
    print(f"  [--center] lon={_lon} lat={_lat} radius={_r}km → bbox=[{west:.4f},{south:.4f},{east:.4f},{north:.4f}]")

elif sys.argv[1] == '--url':
    if len(sys.argv) < 3:
        print("用法: set_area.py --url \"<google_maps_url>\" [area_name]")
        sys.exit(1)
    _parsed = _parse_google_maps_url(sys.argv[2])
    if not _parsed:
        print(f"  [ERR] 无法从 URL 解析坐标: {sys.argv[2]}")
        print("  URL 应包含 /@lat,lon,zoomz 格式，例如: https://www.google.com/maps/@12.942,100.889,14z")
        sys.exit(1)
    _lat, _lon, _zoom = _parsed
    _r = _zoom_to_radius_km(_zoom)
    west, south, east, north = _center_to_bbox(_lon, _lat, _r)
    area_name = sys.argv[3] if len(sys.argv) > 3 else f"area_{_lon:.3f}_{_lat:.3f}"
    print(f"  [--url] lat={_lat} lon={_lon} zoom={_zoom} → radius={_r:.1f}km → bbox=[{west:.4f},{south:.4f},{east:.4f},{north:.4f}]")

elif len(sys.argv) >= 5 and sys.argv[1] not in ('--help', '-h'):
    west, south, east, north = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
    area_name = sys.argv[5] if len(sys.argv) > 5 else f"area_{west:.3f}_{south:.3f}"

else:
    print(__doc__)
    sys.exit(1)

origin_lon = (west + east) / 2
origin_lat = (south + north) / 2
bbox_w, bbox_h = bbox_size_m([west, south, east, north])

print(f"\n{'='*50}")
print(f"[VirtualCity] 设置区域: {area_name}")
print(f"  bbox: [{west}, {south}, {east}, {north}]")
print(f"  中心: ({origin_lon:.4f}, {origin_lat:.4f})")
print(f"  尺寸: {bbox_w/1000:.1f} km × {bbox_h/1000:.1f} km")
print(f"{'='*50}\n")

osm_path       = str(DATA_ROOT / f"OSM/{area_name}_osm_v001.osm")
buildings_path = str(DATA_ROOT / f"Overture/{area_name}_buildings_overture_v001.geojson")
dem_tif_path   = str(DATA_ROOT / f"DEM/{area_name}_dem_v001.tif")
dem_csv_path   = str(DATA_ROOT / f"DEM/{area_name}_dem_v001.csv")
bbox_req       = [west, south, east, north]

# ── 1. 更新 active_area.json ─────────────────────────
cfg = {
    "area_id":        area_name,
    "bbox":           bbox_req,
    "osm_file":       project_relative(osm_path),
    "buildings_file": project_relative(buildings_path),
    "dem_csv":        project_relative(dem_csv_path),
    "dem_source":     "fabdem",
    "sources":        ACQUISITION_PROFILE,
    "origin_lon":     origin_lon,
    "origin_lat":     origin_lat,
    "bbox_size_m":    {"width": bbox_w, "height": bbox_h},
    "_note":          "切换区域只改此文件，不改 Houdini 节点代码"
}
RUN_ID = pipeline_state.new_run_id(area_name)
cfg["run_id"] = RUN_ID
pipeline_state.create_run(cfg, source="set_area", run_id=RUN_ID)
write_active_area(cfg, relative=True)
pipeline_state.update_run(RUN_ID, phase="active_area_written", message="active_area.json updated")
print(f"[1/5] [OK] active_area.json 已更新: {area_name}")
print(f"[RUN] run_id={RUN_ID}")
_RUN_FINALIZED = False


def _mark_unhandled_exit() -> None:
    if _RUN_FINALIZED:
        return
    try:
        pipeline_state.fail_run(RUN_ID, phase="aborted",
                                message="set_area.py exited before pipeline completion")
    except Exception:
        pass


atexit.register(_mark_unhandled_exit)


def _phase(name: str, message: str = "") -> None:
    pipeline_state.update_run(RUN_ID, phase=name, message=message)


def _abort(phase: str, message: str) -> None:
    global _RUN_FINALIZED
    pipeline_state.fail_run(RUN_ID, phase=phase, message=message)
    _RUN_FINALIZED = True
    print(f"  [ERR] {message}")
    raise SystemExit(1)

raw_outputs = {
    "roads": osm_path,
    "dem": dem_csv_path,
    "buildings": buildings_path,
}
clip_manifest = dcc.restore_clip_cache(
    bbox_req,
    raw_outputs,
    source_signature=ACQUISITION_PROFILE,
)
if clip_manifest:
    cfg["dem_source"] = clip_manifest.get("dem_source", cfg.get("dem_source", "fabdem"))
    cfg["cache"] = {
        "clip": {
            "status": "hit",
            "key": clip_manifest.get("key"),
            "bbox": clip_manifest.get("bbox"),
            "restored_at": clip_manifest.get("restored_at"),
        }
    }
    write_active_area(cfg, relative=True)
    print(f"  [clip-cache] 命中 {clip_manifest.get('key')}，已恢复 OSM/DEM/建筑原始裁切")

# ── 2. OSM：优先本地缓存裁剪 → 备用 Overpass 下载 ──
print(f"\n[2/5] 获取 OSM 数据...")
import urllib.request, urllib.parse
sys.path.insert(0, str(SCRIPTS))
import _tile_cache as _tc

if clip_manifest:
    print(f"  [clip-cache] OSM 已恢复，跳过 Overpass")
    _tile = {"clip_cache": clip_manifest.get("key")}
else:
    _tile = _tc.find_covering_tile(bbox_req)
if _tile and not clip_manifest:
    print(f"  [本地缓存] 命中, 裁剪 OSM...")
    if not _tc.filter_osm(_tile, bbox_req, osm_path):
        _tile = None

if not _tile:
    OVERPASS_SERVERS = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]
    s, w, n, e = south, west, north, east
    query = (
        f"[out:xml][timeout:180];\n"
        f"(\n"
        f'  way["highway"]({s},{w},{n},{e});\n'
        f'  way["building"]({s},{w},{n},{e});\n'
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
            print(f"  [OK] OSM: {len(content)//1024} KB → {osm_path}")
            osm_ok = True
            break
        except Exception as ex:
            print(f"  [WARN] {server}: {ex}")
            time.sleep(3)
    if not osm_ok:
        _abort("acquire_osm", "OSM 下载失败，请先运行 cache_city_data.py 预缓存后重试")
_phase("acquire_osm", "OSM acquisition completed")

# ── 3. DEM：优先 FABDEM DTM → 本地缓存 → NASADEM 兜底 ─────────
print(f"\n[3/5] 获取 DEM 数据...")
try:
    import download_dem as _dem
    Path(dem_csv_path).parent.mkdir(parents=True, exist_ok=True)
    bbox = [west, south, east, north]
    dem_cfg = {"bbox": bbox, "output_tif": dem_tif_path, "output_csv": dem_csv_path}
    dem_ok = bool(clip_manifest)
    dem_source = clip_manifest.get("dem_source", "fabdem") if clip_manifest else "fabdem"
    if clip_manifest:
        print(f"  [clip-cache] DEM 已恢复，跳过 FABDEM/GEE")

    # 优先尝试 FABDEM DTM（真正裸地，无需 correct_dem_dtm.py）
    if not dem_ok:
        try:
            _dem.download_fabdem(dem_cfg)
            dem_ok = True
        except Exception as e:
            print(f"  [WARN] FABDEM 失败: {e}")

    # 兜底：本地缓存裁剪
    if not dem_ok:
        _tile2 = _tc.find_covering_tile(bbox)
        if _tile2:
            print(f"  [本地缓存] 命中, 裁剪 DEM...")
            dem_ok = _tc.crop_dem(_tile2, bbox, dem_tif_path, dem_csv_path)
            if dem_ok:
                _dem.convert_to_csv(dem_tif_path, dem_csv_path, bbox)
                dem_source = "nasadem"  # 本地缓存通常是 NASADEM

    # 兜底：GEE NASADEM
    if not dem_ok:
        _dem.download_gee(dem_cfg, source="nasadem")
        dem_source = "nasadem"

    # 记录 DEM 来源，供下游决定是否需要 DTM 修正
    cfg["dem_source"] = dem_source
    write_active_area(cfg, relative=True)
    print(f"  [OK] DEM 完成 (source={dem_source})")
except Exception as ex:
    _abort("acquire_dem", f"DEM 下载失败: {ex}")
_phase("acquire_dem", f"DEM acquisition completed (source={cfg.get('dem_source', 'unknown')})")

# ── 4. 建筑：优先本地缓存过滤→备用 Overture 下载 ──
print(f"\n[4/5] 获取建筑数据...")
Path(buildings_path).parent.mkdir(parents=True, exist_ok=True)
bld_ok = bool(clip_manifest)
if clip_manifest:
    print(f"  [clip-cache] 建筑已恢复，跳过 Overture")

_tile3 = None if clip_manifest else _tc.find_covering_tile([west, south, east, north])
if _tile3:
    print(f"  [本地缓存] 命中, 过滤建筑...")
    bld_ok = _tc.filter_buildings(_tile3, [west, south, east, north], buildings_path)

if not bld_ok:
    bld_cmd = [
        "uv", "run", "python", "download_overture_buildings.py",
        "--bbox", str(west), str(south), str(east), str(north),
        "--output", buildings_path,
    ]
    result = subprocess.run(bld_cmd, capture_output=False, cwd=str(SCRIPTS))
    if result.returncode != 0 or not Path(buildings_path).exists():
        _abort("acquire_buildings", f"Overture 建筑下载失败（returncode={result.returncode}）")
print(f"  [OK] 建筑完成")
_phase("acquire_buildings", "building acquisition completed")

if not clip_manifest:
    clip_manifest = dcc.write_clip_cache(
        bbox_req,
        cfg,
        raw_outputs,
        source_signature=ACQUISITION_PROFILE,
        source_note="set_area acquisition",
    )
    if clip_manifest:
        cfg["cache"] = {
            "clip": {
                "status": "stored",
                "key": clip_manifest.get("key"),
                "bbox": clip_manifest.get("bbox"),
            }
        }
        write_active_area(cfg, relative=True)
        print(f"  [clip-cache] 已写入 {clip_manifest.get('key')}")

# ── 5. 数据精炼 + 验证 + Houdini recook ──────────────
print(f"\n[5/6] 数据精炼（清洗 + 补全 + QA）...")
_phase("refine_data", "data refinement started")

# 5a. refine_data.py — 统一数据精炼管线
refine_result = subprocess.run(
    [sys.executable, str(SCRIPTS / "refine_data.py"), "--skip-probe"],
    cwd=str(SCRIPTS),
    capture_output=False,
)
if refine_result.returncode != 0:
    _abort("refine_data", "数据精炼未通过，中止流程")
_phase("refine_data_completed", "data refinement completed")

# ── 6. Houdini recook ────────────────────────────────
print(f"\n[6/6] Houdini 重算...")
_phase("houdini_recook", "Houdini recook started")

# 注意：必须从 SCRIPTS 目录运行（pyproject.toml 在那里，rpyc==4.1.0 才可用）
print("\n  [RECOOK] Houdini 重算中（_recook_new_area.py）...")
recook = subprocess.run(
    ["uv", "run", "python", "-u", "_recook_new_area.py"],
    cwd=str(SCRIPTS),
    capture_output=False,
)
if recook.returncode != 0:
    _abort("houdini_recook", "Houdini 重算失败，中止流程")
pipeline_state.complete_run(RUN_ID, phase="pipeline_completed", message="data acquisition, refinement, and Houdini recook completed")
_RUN_FINALIZED = True

# ── 完成：等待用户确认 ────────────────────────────────
print(f"""
{'='*50}
[OK] 数据下载和 Houdini 重算完成: {area_name}
{'='*50}

[WARN]  下一步（需人工确认）：
   1. 在 Houdini 视口选中 OUT_city，按 D 检查：
      - 建筑是否在地形上
      - 道路是否正常
      - 无异常水片或空洞
   2. 确认视口正常后，运行导出：
      uv run python Scripts/export_and_import.py
""")
