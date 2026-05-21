"""
VirtualCity - DEM 地形数据自动下载脚本
========================================
通过 Google Earth Engine 下载 SRTM 30m DEM 数据，
导出为 GeoTIFF，再转换为 Houdini 可用的 CSV 高程点云。

用法:
    uv run python download_dem.py [area_name]

依赖（自动安装）:
    earthengine-api, numpy, Pillow (可选，用于预览)
"""

import sys, os, json, zipfile, io, time

AREAS = {
    "pattaya_sai6_mvp": {
        "bbox": [100.866, 12.922, 100.882, 12.938],
        "output_tif": r"F:\VirtualCity\原始数据\DEM\pattaya_sai6_mvp_dem_v001.tif",
        "output_csv": r"F:\VirtualCity\原始数据\DEM\pattaya_sai6_mvp_dem_v001.csv",
    },
    "pattaya_sai6_mvp_v2": {
        "bbox": [100.860, 12.916, 100.888, 12.944],
        "output_tif": r"F:\VirtualCity\原始数据\DEM\pattaya_sai6_mvp_v2_dem_v001.tif",
        "output_csv": r"F:\VirtualCity\原始数据\DEM\pattaya_sai6_mvp_v2_dem_v001.csv",
    },
}

EE_PROJECT = "pty-zone"


def run(area_name):
    cfg = AREAS.get(area_name)
    if not cfg:
        print(f"未知区域: {area_name}，可用: {list(AREAS.keys())}")
        sys.exit(1)

    os.makedirs(os.path.dirname(cfg["output_tif"]), exist_ok=True)

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

    bbox = cfg["bbox"]
    region = ee.Geometry.Rectangle(bbox)

    print("获取 SRTM 30m DEM...")
    dem = ee.Image("USGS/SRTMGL1_003").clip(region)

    print("生成下载 URL...")
    url = dem.getDownloadURL({
        "name": "dem",
        "bands": ["elevation"],
        "region": region,
        "scale": 30,
        "format": "GEO_TIFF",
        "filePerBand": False,
    })

    print(f"下载中: {url[:80]}...")
    import urllib.request
    with urllib.request.urlopen(url, timeout=120) as resp:
        tif_data = resp.read()

    with open(cfg["output_tif"], "wb") as f:
        f.write(tif_data)
    print(f"GeoTIFF 已保存: {cfg['output_tif']} ({len(tif_data)/1024:.0f} KB)")

    # 转换为 CSV 高程点云（Houdini 可直接读取）
    print("转换为 CSV 点云...")
    convert_to_csv(cfg["output_tif"], cfg["output_csv"], bbox)
    print(f"CSV 已保存: {cfg['output_csv']}")
    print("完成 ✅")


def convert_to_csv(tif_path, csv_path, bbox):
    """将 GeoTIFF 转为 x,y,z CSV（Houdini 本地坐标系）"""
    try:
        from osgeo import gdal
        use_gdal = True
    except ImportError:
        use_gdal = False

    ORIGIN_LON = (bbox[0] + bbox[2]) / 2
    ORIGIN_LAT = (bbox[1] + bbox[3]) / 2

    import math
    def to_local(lon, lat):
        dx = (lon - ORIGIN_LON) * math.cos(math.radians(ORIGIN_LAT)) * 111319.9
        dy = (lat - ORIGIN_LAT) * 111319.9
        return dx, dy

    if use_gdal:
        ds = gdal.Open(tif_path)
        band = ds.GetRasterBand(1)
        data = band.ReadAsArray()
        gt = ds.GetGeoTransform()
        rows, cols = data.shape

        with open(csv_path, "w") as f:
            f.write("x,y,z\n")
            for r in range(rows):
                for c in range(cols):
                    lon = gt[0] + c * gt[1]
                    lat = gt[3] + r * gt[5]
                    elev = float(data[r, c])
                    if elev < -9000:
                        continue
                    x, z = to_local(lon, lat)
                    f.write(f"{x:.2f},{elev:.2f},{-z:.2f}\n")
    else:
        print("  提示: 未安装 GDAL，仅保存 GeoTIFF，CSV 转换跳过")
        print("  可运行: uv pip install gdal --index-url https://mirrors.aliyun.com/pypi/simple/")


if __name__ == "__main__":
    area = sys.argv[1] if len(sys.argv) > 1 else "pattaya_sai6_mvp_v2"
    print(f"[VirtualCity] 下载 DEM 数据: {area}")
    run(area)
