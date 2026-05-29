"""
VirtualCity - DEM 地形数据自动下载脚本
========================================
支持多种数据源（按质量排序）：
  1. FABDEM 30m (DTM，已移除建筑和植被) —— GEE，精度最佳
  2. Copernicus GLO-30 (30m DSM)       —— GEE / AWS S3
  3. NASADEM (30m DSM)                 —— GEE
  4. SRTM GL1 (30m DSM)                —— GEE，后备

注意：Copernicus EEA-10 仅覆盖欧洲，东南亚不可用。

用法:
    uv run python download_dem.py [area_name] [--source fabdem|copernicus|nasadem|srtm]

依赖（自动安装）:
    earthengine-api (GEE 数据源需要)
"""

import sys, os, json, zipfile, io, time, math, struct, zlib, csv
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Scripts'))
try:
    import vc_paths
except ImportError:
    vc_paths = None

DATA_ROOT = vc_paths.DATA_ROOT if vc_paths else ROOT / 'RawData'

AREAS = {
    "pattaya_sai6_mvp": {
        "bbox": [100.866, 12.922, 100.882, 12.938],
        "output_tif": str(DATA_ROOT / "DEM" / "pattaya_sai6_mvp_dem_v001.tif"),
        "output_csv": str(DATA_ROOT / "DEM" / "pattaya_sai6_mvp_dem_v001.csv"),
    },
    "pattaya_sai6_mvp_v2": {
        "bbox": [100.860, 12.916, 100.888, 12.944],
        "output_tif": str(DATA_ROOT / "DEM" / "pattaya_sai6_mvp_v2_dem_v001.tif"),
        "output_csv": str(DATA_ROOT / "DEM" / "pattaya_sai6_mvp_v2_dem_v001.csv"),
    },
}

EE_PROJECT = "pty-zone"


def download_copernicus_10m(bbox, output_tif, output_csv):
    """
    Copernicus GLO-10 DEM from AWS S3 (public, no auth).
    Tiles: 1°×1°, named by SW corner.
    """
    west, south, east, north = bbox
    lat0, lon0 = int(math.floor(south)), int(math.floor(west))

    lat_s = f"N{lat0:02d}" if lat0 >= 0 else f"S{abs(lat0):02d}"
    lon_s = f"E{lon0:03d}" if lon0 >= 0 else f"W{abs(lon0):03d}"
    tile = f"Copernicus_DSM_10_{lat_s}_00_{lon_s}_00"
    url = (f"https://copernicus-dem-10m.s3.eu-central-1.amazonaws.com/"
           f"{tile}/DEM/{tile}_DEM.tif")

    print(f"  Copernicus 10m tile: {tile}")
    print(f"  URL: {url}")
    print("  下载中（文件大约 300-800MB）...")

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "VirtualCity/1.0"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = resp.read()
    except Exception as e:
        print(f"  下载失败: {e}")
        return False

    os.makedirs(os.path.dirname(output_tif), exist_ok=True)
    with open(output_tif, "wb") as f:
        f.write(data)
    print(f"  已保存: {output_tif} ({len(data)/1024/1024:.1f} MB)")
    convert_to_csv(output_tif, output_csv, bbox)
    return True


def _init_ee():
    """初始化 Earth Engine，自动安装 + 认证"""
    try:
        import ee
    except ImportError:
        print("安装 earthengine-api...")
        os.system('uv pip install earthengine-api '
                  '--index-url https://mirrors.aliyun.com/pypi/simple/')
        import ee
    print("Earth Engine 认证...")
    try:
        ee.Initialize(project=EE_PROJECT)
    except Exception:
        ee.Authenticate()
        ee.Initialize(project=EE_PROJECT)
    return ee


def download_fabdem(cfg):
    """
    FABDEM V1-2: 全球 30m DTM（已通过 ML 移除建筑和树木高度）
    来源: University of Bristol
    许可: CC BY-NC-SA 4.0（非商用免费，商用需联系 fathom.global）
    GEE: projects/sat-io/open-datasets/FABDEM
    精度: 建成区垂直误差比 COP-GLO-30 好 ~33%，比 NASADEM 好 ~50%
    """
    ee = _init_ee()
    bbox = cfg["bbox"]
    region = ee.Geometry.Rectangle(bbox)

    print("获取 FABDEM 30m DTM（真正裸地高程，已移除建筑和植被）...")
    fabdem = (ee.ImageCollection("projects/sat-io/open-datasets/FABDEM")
              .filterBounds(region)
              .mosaic()
              .clip(region))

    url = fabdem.getDownloadURL({
        "name": "fabdem",
        "bands": ["b1"],
        "region": region,
        "scale": 30,
        "format": "GEO_TIFF",
        "filePerBand": False,
    })

    print("下载中...")
    with urllib.request.urlopen(url, timeout=120) as resp:
        tif_data = resp.read()

    os.makedirs(os.path.dirname(cfg["output_tif"]), exist_ok=True)
    with open(cfg["output_tif"], "wb") as f:
        f.write(tif_data)
    print(f"GeoTIFF 已保存: {cfg['output_tif']} ({len(tif_data)/1024:.0f} KB)")
    convert_to_csv(cfg["output_tif"], cfg["output_csv"], cfg["bbox"])
    print("完成 [OK] — DTM，无需 correct_dem_dtm.py 修正")
    return True


def download_gee(cfg, source="nasadem"):
    """Google Earth Engine 下载 NASADEM 或 SRTM（均为 DSM，需后续 DTM 修正）"""
    ee = _init_ee()

    bbox = cfg["bbox"]
    region = ee.Geometry.Rectangle(bbox)

    if source == "nasadem":
        print("获取 NASADEM 30m DEM（DSM，含建筑和植被高度）...")
        dem = ee.Image("NASA/NASADEM_HGT/001").select("elevation").clip(region)
    else:
        print("获取 SRTM 30m DEM（DSM）...")
        dem = ee.Image("USGS/SRTMGL1_003").clip(region)

    url = dem.getDownloadURL({
        "name": "dem", "bands": ["elevation"], "region": region,
        "scale": 30, "format": "GEO_TIFF", "filePerBand": False,
    })

    print(f"下载中...")
    with urllib.request.urlopen(url, timeout=120) as resp:
        tif_data = resp.read()

    os.makedirs(os.path.dirname(cfg["output_tif"]), exist_ok=True)
    with open(cfg["output_tif"], "wb") as f:
        f.write(tif_data)
    print(f"GeoTIFF 已保存: {cfg['output_tif']} ({len(tif_data)/1024:.0f} KB)")
    convert_to_csv(cfg["output_tif"], cfg["output_csv"], bbox)
    print("完成 [OK]")


def run(area_name, source="fabdem"):
    cfg = AREAS.get(area_name)
    if not cfg:
        print(f"未知区域: {area_name}，可用: {list(AREAS.keys())}")
        sys.exit(1)

    print(f"[VirtualCity] 下载 DEM: {area_name}  source={source}")

    if source == "fabdem":
        try:
            download_fabdem(cfg)
        except Exception as e:
            print(f"  FABDEM 失败: {e}，回退到 NASADEM...")
            download_gee(cfg, source="nasadem")
    elif source == "copernicus":
        ok = download_copernicus_10m(cfg["bbox"], cfg["output_tif"], cfg["output_csv"])
        if not ok:
            print("  Copernicus 失败，回退到 NASADEM...")
            download_gee(cfg, source="nasadem")
    elif source == "nasadem":
        download_gee(cfg, source="nasadem")
    else:
        download_gee(cfg, source="srtm")


def convert_to_csv(tif_path, csv_path, bbox):
    """将 GeoTIFF 转为 x,y,z CSV（Houdini 本地坐标系），使用 rasterio"""
    try:
        import rasterio
        import numpy as np
    except ImportError:
        print("  安装 rasterio...")
        os.system("uv pip install rasterio numpy "
                  "--index-url https://mirrors.aliyun.com/pypi/simple/")
        import rasterio
        import numpy as np

    ORIGIN_LON = (bbox[0] + bbox[2]) / 2
    ORIGIN_LAT = (bbox[1] + bbox[3]) / 2

    # 坐标一律走 vc_geo（全项目唯一坐标权威），z 翻转也只在 vc_geo 内发生。
    import vc_geo
    _proj = vc_geo.LocalProjector(ORIGIN_LON, ORIGIN_LAT)

    print(f"  转换 {tif_path} → CSV...")
    with rasterio.open(tif_path) as ds:
        data = ds.read(1).astype(float)
        transform = ds.transform
        rows_n, cols_n = data.shape

    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    count = 0
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        f.write("x,y,z,row,col\n")
        for r in range(rows_n):
            for c in range(cols_n):
                elev = data[r, c]
                if elev < -9000:
                    continue
                lon = transform.c + c * transform.a
                lat = transform.f + r * transform.e
                x, z = _proj.to_local(lon, lat)
                hx, hz = vc_geo.local_xz_to_houdini_xz(x, z)
                f.write(f"{hx:.2f},{elev:.2f},{hz:.2f},{r},{c}\n")
                count += 1
    print(f"  [OK] CSV 已保存: {csv_path}  ({rows_n}×{cols_n}={count} 点)")


if __name__ == "__main__":
    area   = sys.argv[1] if len(sys.argv) > 1 else "pattaya_sai6_mvp_v2"
    source = sys.argv[2] if len(sys.argv) > 2 else "fabdem"
    run(area, source)
