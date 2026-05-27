"""
VirtualCity — 数据预检脚本
在进入 Houdini 之前运行，确认所有数据文件完整且无已知问题。

用法:
    uv run python Scripts/validate_data.py
"""
import json, os, sys
from vc_paths import load_active_area

OK = "[OK]"
FAIL = "[FAIL]"
WARN = "[WARN]"

def check(label, path, min_bytes=1024, extra=None):
    if not os.path.exists(path):
        print(f"  {FAIL} {label}: 文件不存在 -> {path}")
        return False
    size = os.path.getsize(path)
    if size < min_bytes:
        print(f"  {FAIL} {label}: 文件过小 ({size} bytes) -> {path}")
        return False
    if extra:
        msg = extra(path)
        if msg:
            print(f"  {FAIL} {label}: {msg}")
            return False
    print(f"  {OK} {label}: {size/1024:.1f} KB")
    return True

def check_geojson_geometry(path):
    """D-001: 建筑 GeoJSON 必须有 Polygon 几何 + 真实高度（非全默认 10m）"""
    with open(path, encoding="utf-8") as f:
        fc = json.load(f)
    feats = fc.get("features", [])
    if not feats:
        return "features 为空"
    null_geom = sum(1 for feat in feats if feat.get("geometry") is None)
    if null_geom == len(feats):
        return (f"全部 {null_geom} 个 feature geometry=null — "
                f"此文件只有高度属性，无多边形坐标，不可用于建筑生成（D-001）")
    if null_geom > 0:
        print(f"         {WARN} {null_geom}/{len(feats)} 个 feature geometry=null（已 skip）")
    # 高度有效性检查（D-002）
    heights = [feat.get("properties", {}).get("height", 0) or 0
               for feat in feats if feat.get("geometry") is not None]
    if not heights:
        return "有几何的 feature 均无 height 属性（D-002）"
    avg_h = sum(heights) / len(heights)
    if avg_h == 10.0 and min(heights) == max(heights):
        return f"所有建筑高度均为默认值 10.0m — 高度数据未写入（D-002）"
    if avg_h < 0.5:
        return f"建筑平均高度 {avg_h:.2f}m 过低，数据异常（D-002）"
    print(f"         features={len(feats)}, with_geom={len(feats)-null_geom}, "
          f"height min/avg/max={min(heights):.1f}/{avg_h:.1f}/{max(heights):.1f}m")
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

def check_houdini_ready():
    """H-001: Houdini RPYC 在线 + hip 已加载"""
    try:
        import rpyc
        conn = rpyc.classic.connect('localhost', 18811)
        hou = conn.modules.hou
        hip = hou.hipFile.path()
        conn.close()
        if 'untitled' in hip:
            print(f"  {WARN} Houdini: 已连接但工程文件未加载（recook 会自动加载）")
            return True
        print(f"  {OK} Houdini: 已连接，hip={hip.split('/')[-1]}")
        return True
    except Exception as e:
        print(f"  {WARN} Houdini: 无法连接（{e}）— 仅数据检查")
        return True  # Houdini 未运行不阻断数据检查


def main():
    print(f"\n[VirtualCity 数据预检]")
    cfg = load_active_area(absolute=True)
    print(f"  区域: {cfg['area_id']}\n")

    results = [
        check("OSM 文件",     cfg["osm_file"],       min_bytes=5_000,   extra=check_osm),
        check("建筑 GeoJSON", cfg["buildings_file"], min_bytes=10_000,  extra=check_geojson_geometry),
        check("DEM CSV",      cfg["dem_csv"],        min_bytes=4_000,   extra=check_csv_header),
    ]
    results.append(check_houdini_ready())

    print()
    if all(results):
        print(f"  {OK} 全部通过，可以进入 Houdini。")
    else:
        print(f"  {FAIL} 有检查项未通过，请修复后再运行导出。")
        sys.exit(1)

if __name__ == "__main__":
    main()
