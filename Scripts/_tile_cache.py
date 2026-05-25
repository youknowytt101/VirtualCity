"""
VirtualCity — 本地 Tile 缓存工具
===================================
供 download_dem.py / download_overture_buildings.py / set_area.py 调用。

缓存目录: <项目根目录>/RawData/_tiles/
索引文件: <项目根目录>/RawData/_tiles/_index.json

索引格式:
{
  "pattaya_city": {
    "bbox": [west, south, east, north],
    "dem_tif":    "_tiles/pattaya_city_dem.tif",
    "osm_xml":    "_tiles/pattaya_city_osm.osm",
    "bld_geojson":"_tiles/pattaya_city_bld.geojson"
  }
}
"""
import json, math, os, tempfile
from pathlib import Path
from vc_paths import DATA_ROOT, resolve_project_path

TILES_DIR  = DATA_ROOT / "_tiles"
INDEX_FILE = TILES_DIR / "_index.json"


# ── 索引操作 ──────────────────────────────────────────────

def load_index():
    if not INDEX_FILE.exists():
        return {}
    with open(INDEX_FILE, encoding="utf-8") as f:
        return json.load(f)

def save_index(idx):
    TILES_DIR.mkdir(parents=True, exist_ok=True)
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(idx, f, indent=2, ensure_ascii=False)

def find_covering_tile(bbox):
    """返回完整覆盖 bbox 的 tile entry，找不到返回 None。"""
    w, s, e, n = bbox
    for name, entry in load_index().items():
        tw, ts, te, tn = entry["bbox"]
        if tw <= w and ts <= s and te >= e and tn >= n:
            # 验证文件存在
            keys = ["dem_tif", "osm_xml", "bld_geojson"]
            if all(resolve_project_path(entry.get(k, "")).exists() for k in keys):
                return entry
    return None


# ── DEM 裁剪 ─────────────────────────────────────────────

def crop_dem(tile_entry, bbox, output_tif, output_csv):
    """从缓存 tile 裁剪出 bbox 范围的 DEM TIF + CSV。返回 True/False。"""
    try:
        import rasterio
        from rasterio.windows import from_bounds
    except ImportError:
        return False

    src_tif = resolve_project_path(tile_entry["dem_tif"])
    if not Path(src_tif).exists():
        return False

    try:
        with rasterio.open(src_tif) as src:
            w, s, e, n = bbox
            window = from_bounds(w, s, e, n, src.transform)
            data   = src.read(1, window=window)
            wtrans = src.window_transform(window)
            profile = src.profile.copy()

        profile.update({
            "width":     data.shape[1],
            "height":    data.shape[0],
            "transform": wtrans,
        })
        Path(output_tif).parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(output_tif, "w", **profile) as dst:
            dst.write(data, 1)

        print(f"  [tile cache] DEM 裁剪: {data.shape[0]}×{data.shape[1]} 点")
        return True
    except Exception as ex:
        print(f"  [tile cache] DEM 裁剪失败: {ex}")
        return False


# ── OSM 过滤 ─────────────────────────────────────────────

def filter_osm(tile_entry, bbox, output_osm, margin=0.001):
    """从缓存 OSM XML 按 bbox 过滤 highway ways。返回 True/False。"""
    import xml.etree.ElementTree as ET

    src_osm = resolve_project_path(tile_entry["osm_xml"])
    if not Path(src_osm).exists():
        return False

    w, s, e, n = bbox
    w -= margin; s -= margin; e += margin; n += margin  # 扩边防截断

    try:
        tree = ET.parse(src_osm)
        root = tree.getroot()

        # 收集 bbox 内的 node id
        node_coords = {}
        for nd in root.findall("node"):
            lat = float(nd.get("lat", 0))
            lon = float(nd.get("lon", 0))
            if s <= lat <= n and w <= lon <= e:
                node_coords[nd.get("id")] = (lon, lat)

        # 过滤 highway ways（至少有一个 node 在 bbox 内）
        kept_ways = []
        used_nodes = set()
        for way in root.findall("way"):
            tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
            if not tags.get("highway"):
                continue
            refs = [nr.get("ref") for nr in way.findall("nd")]
            if any(r in node_coords for r in refs):
                kept_ways.append(way)
                used_nodes.update(refs)

        # 写输出 OSM XML
        new_root = ET.Element("osm", version="0.6")
        for nd in root.findall("node"):
            if nd.get("id") in used_nodes:
                new_root.append(nd)
        for way in kept_ways:
            new_root.append(way)

        Path(output_osm).parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(new_root).write(output_osm, encoding="utf-8",
                                       xml_declaration=True)
        sz = Path(output_osm).stat().st_size
        print(f"  [tile cache] OSM 过滤: {len(kept_ways)} roads, {sz//1024} KB")
        return True
    except Exception as ex:
        print(f"  [tile cache] OSM 过滤失败: {ex}")
        return False


# ── 建筑过滤 ─────────────────────────────────────────────

def filter_buildings(tile_entry, bbox, output_geojson):
    """从缓存建筑 GeoJSON 按 bbox 过滤。返回 True/False。"""
    try:
        from shapely.geometry import shape
        from shapely.geometry import box as sbox
    except ImportError:
        return False

    src = resolve_project_path(tile_entry["bld_geojson"])
    if not Path(src).exists():
        return False

    try:
        with open(src, encoding="utf-8") as f:
            fc = json.load(f)

        region = sbox(*bbox)
        filtered = [
            feat for feat in fc.get("features", [])
            if feat.get("geometry") and
               shape(feat["geometry"]).centroid.within(region)
        ]

        Path(output_geojson).parent.mkdir(parents=True, exist_ok=True)
        with open(output_geojson, "w", encoding="utf-8") as f:
            json.dump({"type": "FeatureCollection", "features": filtered},
                      f, ensure_ascii=False)

        print(f"  [tile cache] 建筑过滤: {len(filtered)} 栋")
        return True
    except Exception as ex:
        print(f"  [tile cache] 建筑过滤失败: {ex}")
        return False
