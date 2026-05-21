"""
VirtualCity — 数据预检脚本
在进入 Houdini 之前运行，确认所有数据文件完整且无已知问题。

用法:
    uv run python 自动化插件/validate_data.py
"""
import json, os, sys

CFG_FILE = r"F:/VirtualCity/配置/active_area.json"

def check(label, path, min_bytes=1024, extra=None):
    if not os.path.exists(path):
        print(f"  [FAIL] {label}: 文件不存在 → {path}")
        return False
    size = os.path.getsize(path)
    if size < min_bytes:
        print(f"  [FAIL] {label}: 文件过小 ({size} bytes) → {path}")
        return False
    if extra:
        msg = extra(path)
        if msg:
            print(f"  [FAIL] {label}: {msg}")
            return False
    print(f"  [ OK ] {label}: {size/1024:.1f} KB")
    return True

def check_geojson_geometry(path):
    with open(path, encoding="utf-8") as f:
        fc = json.load(f)
    feats = fc.get("features", [])
    null_geom = sum(1 for feat in feats if feat.get("geometry") is None)
    if null_geom == len(feats):
        return f"全部 {null_geom} 个 feature geometry=null（D-001 bug）"
    if null_geom > 0:
        print(f"         ⚠ 警告: {null_geom}/{len(feats)} 个 feature geometry=null（已 skip）")
    has_h = sum(1 for feat in feats if feat.get("properties", {}).get("height"))
    print(f"         features={len(feats)}, with_height={has_h}, null_geom={null_geom}")
    return None

def check_osm(path):
    with open(path, encoding="utf-8") as f:
        content = f.read(4096)
    if "<osm" not in content:
        return "不是有效的 OSM XML 文件"
    return None

def check_csv_header(path):
    with open(path) as f:
        header = f.readline().strip()
    if "x" not in header or "y" not in header:
        return f"CSV 缺少 x/y 列，header={header}"
    return None

def main():
    print(f"\n[VirtualCity 数据预检]")
    with open(CFG_FILE, encoding="utf-8") as f:
        cfg = json.load(f)
    print(f"  区域: {cfg['area_id']}\n")

    results = [
        check("OSM 文件",       cfg["osm_file"],       min_bytes=50_000, extra=check_osm),
        check("建筑 GeoJSON",   cfg["buildings_file"], min_bytes=100_000, extra=check_geojson_geometry),
        check("DEM CSV",        cfg["dem_csv"],        min_bytes=10_000,  extra=check_csv_header),
    ]

    print()
    if all(results):
        print("  ✅ 全部通过，可以进入 Houdini。")
    else:
        print("  ❌ 有文件未通过，请先修复再进 Houdini。")
        sys.exit(1)

if __name__ == "__main__":
    main()
