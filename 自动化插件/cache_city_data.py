"""
VirtualCity — 城市级数据预缓存脚本
=====================================
一次性下载城市范围的 DEM / OSM / 建筑数据，
后续所有小区域直接从本地裁剪，无需重复联网。

用法:
    uv run python cache_city_data.py --city pattaya --bbox 100.840 12.890 100.920 12.970

已内置城市:
    pattaya   (芭提雅全市, ~8km×8km)

下载内容:
    DEM    : NASADEM 30m (via GEE, 不再每次调 API)
    OSM    : Overpass API highways (一次性, ~200KB)
    建筑   : Overture Maps + Google Open Buildings 合并 (含高度)

缓存位置: <项目根目录>/原始数据/_tiles/
"""
import argparse, json, subprocess, sys, urllib.parse, urllib.request
from pathlib import Path
from vc_paths import DATA_ROOT

SCRIPTS_DIR = Path(__file__).parent
TILES_DIR   = DATA_ROOT / "_tiles"

PRESET_CITIES = {
    "pattaya": [100.840, 12.890, 100.920, 12.970],
}


# ── DEM 下载 ─────────────────────────────────────────────

def download_dem_tile(bbox, city_name):
    tif = TILES_DIR / f"{city_name}_dem.tif"
    csv = TILES_DIR / f"{city_name}_dem.csv"
    if tif.exists():
        print(f"  [DEM] 已有缓存: {tif}")
        return str(tif)

    print(f"  [DEM] 通过 GEE 下载 NASADEM ...")
    import sys as _sys, os, math
    sys.path.insert(0, str(SCRIPTS_DIR))
    import download_dem as _dem

    cfg = {
        "bbox": bbox,
        "output_tif": str(tif),
        "output_csv":  str(csv),
    }
    TILES_DIR.mkdir(parents=True, exist_ok=True)
    _dem.download_gee(cfg, source="nasadem")
    print(f"  [DEM] ✅ 缓存完成: {tif}")
    return str(tif)


# ── OSM 下载 ─────────────────────────────────────────────

def download_osm_tile(bbox, city_name):
    osm = TILES_DIR / f"{city_name}_osm.osm"
    if osm.exists():
        print(f"  [OSM] 已有缓存: {osm}")
        return str(osm)

    west, south, east, north = bbox
    OVERPASS_SERVERS = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]
    s, w, n, e = south, west, north, east
    query = (
        f"[out:xml][timeout:300];\n"
        f"(\n"
        f'  way["highway"]({s},{w},{n},{e});\n'
        f");\n"
        f"out body;\n>;\nout skel qt;\n"
    )
    print(f"  [OSM] 下载城市级道路数据 ...")
    TILES_DIR.mkdir(parents=True, exist_ok=True)
    for server in OVERPASS_SERVERS:
        try:
            data = urllib.parse.urlencode({"data": query}).encode()
            req  = urllib.request.Request(server, data=data,
                                          headers={"User-Agent": "VirtualCity/1.0"})
            with urllib.request.urlopen(req, timeout=300) as resp:
                content = resp.read()
            with open(osm, "wb") as f:
                f.write(content)
            print(f"  [OSM] ✅ 缓存完成: {osm} ({len(content)//1024} KB)")
            return str(osm)
        except Exception as ex:
            print(f"  [OSM] {server} 失败: {ex}")
    print("  [OSM] ❌ 所有 Overpass 节点均失败")
    return None


# ── 建筑下载 ──────────────────────────────────────────────

def download_buildings_tile(bbox, city_name):
    bld = TILES_DIR / f"{city_name}_bld.geojson"
    if bld.exists():
        print(f"  [BLD] 已有缓存: {bld}")
        return str(bld)

    print(f"  [BLD] 下载 Overture + Google Buildings ...")
    TILES_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        "uv", "run", "python", "download_overture_buildings.py",
        "--bbox", str(bbox[0]), str(bbox[1]), str(bbox[2]), str(bbox[3]),
        "--output", str(bld),
    ]
    r = subprocess.run(cmd, cwd=str(SCRIPTS_DIR), capture_output=False)
    if r.returncode != 0 or not bld.exists():
        print("  [BLD] ❌ 建筑下载失败")
        return None
    print(f"  [BLD] ✅ 缓存完成: {bld}")
    return str(bld)


# ── 更新索引 ─────────────────────────────────────────────

def update_index(city_name, bbox, dem_tif, osm_xml, bld_geojson):
    sys.path.insert(0, str(SCRIPTS_DIR))
    import _tile_cache as tc
    idx = tc.load_index()
    idx[city_name] = {
        "bbox":        bbox,
        "dem_tif":     dem_tif     or "",
        "osm_xml":     osm_xml     or "",
        "bld_geojson": bld_geojson or "",
    }
    tc.save_index(idx)
    print(f"\n  ✅ 索引已更新: {city_name}")
    print(f"     bbox: {bbox}")
    print(f"     DEM : {dem_tif}")
    print(f"     OSM : {osm_xml}")
    print(f"     BLD : {bld_geojson}")


# ── 主入口 ───────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", required=True,
                    help="城市名称，如 pattaya（或自定义名称配合 --bbox）")
    ap.add_argument("--bbox", nargs=4, type=float,
                    metavar=("WEST", "SOUTH", "EAST", "NORTH"),
                    help="自定义 bbox（不使用预设城市时必填）")
    ap.add_argument("--skip-dem",  action="store_true")
    ap.add_argument("--skip-osm",  action="store_true")
    ap.add_argument("--skip-bld",  action="store_true")
    ap.add_argument("--force",     action="store_true",
                    help="强制重新下载，忽略已有缓存")
    args = ap.parse_args()

    city_name = args.city
    if args.bbox:
        bbox = args.bbox
    elif city_name in PRESET_CITIES:
        bbox = PRESET_CITIES[city_name]
    else:
        print(f"未知城市 {city_name}，请用 --bbox 指定范围")
        sys.exit(1)

    if args.force:
        for f in TILES_DIR.glob(f"{city_name}_*"):
            f.unlink()
            print(f"  删除旧缓存: {f}")

    print(f"\n{'='*50}")
    print(f"[VirtualCity] 城市级数据预缓存: {city_name}")
    print(f"  bbox: {bbox}")
    print(f"  目标目录: {TILES_DIR}")
    print(f"{'='*50}\n")

    dem = osm = bld = None
    if not args.skip_dem:
        dem = download_dem_tile(bbox, city_name)
    if not args.skip_osm:
        osm = download_osm_tile(bbox, city_name)
    if not args.skip_bld:
        bld = download_buildings_tile(bbox, city_name)

    update_index(city_name, bbox, dem, osm, bld)
    print(f"\n{'='*50}")
    print("✅ 预缓存完成！后续 set_area.py 将自动使用本地数据。")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
