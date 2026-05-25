"""
VirtualCity - Google Open Buildings 高度数据一键下载脚本
========================================================
功能：从 Google Earth Engine 直接下载带真实高度的建筑 GeoJSON，无需经过 Google Drive。

依赖：
    uv run --with earthengine-api python download_building_heights.py

首次运行会打开浏览器做一次性 OAuth 授权，授权后凭据本地缓存，后续无需再次登录。

用法：
    cd <项目根目录>
    uv run --with earthengine-api python Scripts/download_building_heights.py

    # 指定区域和年份（可选）
    uv run --with earthengine-api python Scripts/download_building_heights.py --area pattaya_sai6_mvp --year 2023
"""

import argparse, json, os, sys, urllib.request
from vc_paths import DATA_ROOT

# ── 区域配置 ──────────────────────────────────────────────────────────────────
AREAS = {
    "pattaya_sai6_mvp": {
        "bbox": [100.866, 12.922, 100.882, 12.938],
        "output": (DATA_ROOT / "Overture/pattaya_sai6_buildings_height_v001.geojson").as_posix(),
    },
    "pattaya_sai6_mvp_v2": {
        "bbox": [100.860, 12.916, 100.888, 12.944],  # 3km × 3km
        "output": (DATA_ROOT / "Overture/pattaya_sai6_mvp_v2_buildings_height_v001.geojson").as_posix(),
    },
}

EE_PROJECT = "pty-zone"
EE_YEAR    = 2023
PRESENCE_THRESHOLD = 0.5
BUILDING_RESOLUTION = 4  # metres (effective resolution of Open Buildings 2.5D)


def parse_args():
    p = argparse.ArgumentParser(description="Download building heights from Google Open Buildings 2.5D")
    p.add_argument("--area", default=None, choices=list(AREAS.keys()),
                   help="预设区域名（与 --bbox 二选一）")
    p.add_argument("--bbox", nargs=4, type=float, metavar=("WEST","SOUTH","EAST","NORTH"),
                   help="直接输入坐标，不用预设区域")
    p.add_argument("--output", default=None, help="输出 GeoJSON 路径（与 --bbox 配合使用）")
    p.add_argument("--year", type=int, default=EE_YEAR)
    p.add_argument("--reauth", action="store_true", help="Force re-authentication")
    return p.parse_args()


def authenticate(reauth=False):
    import ee
    if reauth:
        ee.Authenticate(force=True)
    else:
        try:
            ee.Initialize(project=EE_PROJECT)
            return
        except Exception:
            ee.Authenticate()
    ee.Initialize(project=EE_PROJECT)


def fetch_buildings(bbox, year, presence_threshold, resolution):
    import ee

    geometry = ee.Geometry.Rectangle(bbox)

    # Open Buildings 2.5D Temporal
    ob2d = (
        ee.ImageCollection("GOOGLE/Research/open-buildings-temporal/v1")
        .filter(ee.Filter.date(f"{year}-01-01", f"{year}-12-31"))
        .filter(ee.Filter.bounds(geometry))
        .select(["building_presence", "building_height"])
        .mean()
    )
    projection = ob2d.select("building_height").projection()

    # Building polygons v3
    polygons = ee.FeatureCollection("GOOGLE/Research/open-buildings/v3/polygons").filter(
        ee.Filter.bounds(geometry)
    )

    # Zonal stats: mean height per polygon
    with_height = ob2d.reduceRegions(
        collection=polygons,
        reducer=ee.Reducer.mean(),
        scale=resolution,
        tileScale=16,
    ).filter(ee.Filter.gt("building_presence", presence_threshold))

    # Select and rename fields (no transform - keep WGS84 for geometry)
    exported = with_height.map(lambda f: ee.Feature(
        f.geometry(),
        {
            'area':     f.get('area_in_meters'),
            'height':   f.get('building_height'),
            'presence': f.get('building_presence'),
        }
    ))

    print(f"  Building count: {exported.size().getInfo()}")
    return exported


def download_geojson(fc, out_path):
    """直接从 EE 下载 FeatureCollection 为 GeoJSON，无需 Google Drive。"""
    import ee

    url = fc.getDownloadURL(filetype="GeoJSON")
    print(f"  Downloading from EE direct URL...")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    tmp = out_path + ".tmp"
    urllib.request.urlretrieve(url, tmp)

    # EE 直接下载返回的是 zip，解压取 .geojson
    import zipfile, shutil
    if zipfile.is_zipfile(tmp):
        with zipfile.ZipFile(tmp) as z:
            names = [n for n in z.namelist() if n.endswith(".geojson") or n.endswith(".json")]
            if not names:
                raise RuntimeError(f"No GeoJSON found in zip: {z.namelist()}")
            with z.open(names[0]) as src, open(out_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
        os.remove(tmp)
    else:
        os.replace(tmp, out_path)

    # 验证
    with open(out_path, encoding="utf-8") as f:
        fc_local = json.load(f)
    n = len(fc_local.get("features", []))
    has_h = sum(1 for feat in fc_local["features"] if feat["properties"].get("height") not in (None, ""))
    has_g = sum(1 for feat in fc_local["features"] if feat.get("geometry") is not None)
    print(f"  Saved {n} features, {has_h} with height ({100*has_h//n}%), {has_g} with geometry → {out_path}")
    if has_g == 0:
        raise RuntimeError("All features have null geometry! Check EE export settings.")


def main():
    args = parse_args()

    if args.bbox:
        west, south, east, north = args.bbox
        out = args.output or (DATA_ROOT / f"Overture/custom_{west:.3f}_{south:.3f}_buildings.geojson").as_posix()
        cfg = {"bbox": [west, south, east, north], "output": out}
        area_label = f"bbox [{west},{south},{east},{north}]"
    elif args.area:
        cfg = AREAS[args.area]
        area_label = args.area
    else:
        cfg = AREAS["pattaya_sai6_mvp"]
        area_label = "pattaya_sai6_mvp"

    print(f"[download_building_heights] area={area_label}, year={args.year}")
    print("  Authenticating with Google Earth Engine...")
    authenticate(reauth=args.reauth)

    print("  Fetching building polygons + heights...")
    fc = fetch_buildings(cfg["bbox"], args.year, PRESENCE_THRESHOLD, BUILDING_RESOLUTION)

    download_geojson(fc, cfg["output"])
    print("  Done.")


if __name__ == "__main__":
    main()
