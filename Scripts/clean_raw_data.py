"""
VirtualCity — 原始数据清洗脚本
================================
在 Houdini import 之前对 GeoJSON（建筑）和 OSM（道路）做清洗。

运行方式：
    uv run python clean_raw_data.py              # 使用 active_area.json
    uv run python clean_raw_data.py --dry-run    # 只报告，不写入
    uv run python clean_raw_data.py --report     # 输出 JSON 报告
"""
from __future__ import annotations

import argparse
import json
import math
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any

import sys
sys.path.insert(0, str(Path(__file__).parent))
import vc_paths

# ── 清洗阈值常量 ─────────────────────────────────────────────
MIN_RING_POINTS   = 4      # 多边形最少顶点数（含重复的闭合点）
MIN_AREA_M2       = 5.0    # 建筑最小面积（m²），小于此视为噪声
MAX_HEIGHT_M      = 600.0  # 建筑最大合理高度（m）
FLOOR_HEIGHT_M    = 3.5    # 楼层换算高度（m）
DEDUP_DIST_M      = 3.0    # 近重复建筑中心点距离阈值（m）
HIGHWAY_WHITELIST = {      # 只保留这些道路类型（空 = 保留全部）
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "residential", "service", "unclassified", "living_street",
    "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
    "footway", "pedestrian", "path", "cycleway", "track",
}


# ── 几何工具（纯 Python，无需 shapely）───────────────────────

def _ring_area_m2(coords: list[tuple[float, float]]) -> float:
    """Shoelace 公式计算多边形面积（经纬度坐标 → UTM m²）。"""
    from _utm_lite import wgs84_to_utm, zone_number
    lat_avg = sum(c[1] for c in coords) / len(coords)
    lon_avg = sum(c[0] for c in coords) / len(coords)
    z = zone_number(lon_avg)
    ox, oy, _ = wgs84_to_utm(lat_avg, lon_avg, force_zone=z)
    local = []
    for lon, lat in coords:
        x, y, _ = wgs84_to_utm(lat, lon, force_zone=z)
        local.append((x - ox, y - oy))
    n = len(local)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += local[i][0] * local[j][1]
        area -= local[j][0] * local[i][1]
    return abs(area) * 0.5


def _ring_centroid(coords: list[tuple[float, float]]) -> tuple[float, float]:
    n = len(coords)
    return sum(c[0] for c in coords) / n, sum(c[1] for c in coords) / n


def _dist_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    """两点之间的距离（m），使用 UTM 投影。"""
    from _utm_lite import wgs84_to_utm, zone_number
    z = zone_number((a[0] + b[0]) / 2)
    x1, y1, _ = wgs84_to_utm(a[1], a[0], force_zone=z)
    x2, y2, _ = wgs84_to_utm(b[1], b[0], force_zone=z)
    return math.sqrt((x2 - x1)**2 + (y2 - y1)**2)


def _area_based_height(area_m2: float) -> float:
    """基于建筑面积推算楼层高度（与 procedural_height VEX 保持一致）。"""
    if   area_m2 < 60:    floors = 1
    elif area_m2 < 150:   floors = 2
    elif area_m2 < 400:   floors = 3
    elif area_m2 < 1000:  floors = 4
    elif area_m2 < 3000:  floors = 6
    else:                  floors = 8
    return floors * FLOOR_HEIGHT_M


def _unique_points(ring: list) -> list:
    """去除多边形首尾重复点并去重相邻重复点。"""
    pts = [tuple(c[:2]) for c in ring]
    if pts and pts[0] == pts[-1]:
        pts = pts[:-1]
    out = [pts[0]] if pts else []
    for p in pts[1:]:
        if p != out[-1]:
            out.append(p)
    return out


# ── GeoJSON 建筑清洗 ─────────────────────────────────────────

def clean_buildings(path: Path, dry_run: bool) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        fc = json.load(f)

    features_in = fc.get("features", [])
    total_in = len(features_in)

    kept: list[dict] = []
    stats = {
        "total_in":        total_in,
        "removed_null":    0,
        "removed_degenerate": 0,
        "removed_tiny":    0,
        "removed_duplicate": 0,
        "fixed_height":    0,
        "clamped_height":  0,
        "total_out":       0,
    }

    centroids: list[tuple[float, float]] = []

    for feat in features_in:
        geom = feat.get("geometry")
        props = feat.get("properties") or {}

        # 1. null 几何体
        if geom is None:
            stats["removed_null"] += 1
            continue

        gtype = geom.get("type", "")
        if gtype not in ("Polygon", "MultiPolygon"):
            stats["removed_null"] += 1
            continue

        # 取外环
        if gtype == "Polygon":
            rings = geom.get("coordinates", [])
            outer = rings[0] if rings else []
        else:
            outer = geom["coordinates"][0][0] if geom.get("coordinates") else []

        # 2. 退化多边形（顶点不足）
        pts = _unique_points(outer)
        if len(pts) < 3:
            stats["removed_degenerate"] += 1
            continue

        # 3. 面积过小
        area = _ring_area_m2(pts)
        if area < MIN_AREA_M2:
            stats["removed_tiny"] += 1
            continue

        # 4. 高度清洗
        h = props.get("height")
        try:
            h = float(h) if h is not None else None
        except (TypeError, ValueError):
            h = None

        if h is None or h <= 0:
            # 写 0 让 Houdini procedural_height VEX 唯一负责推算
            # （含 noise 抖动 + bld_class 差异化层高 + 面积启发，比清洗层粗略推算更准）。
            # 此前清洗层用 _area_based_height 填 3.5/7.0/10.5...，会与 Houdini VEX 互相覆盖
            # （VEX 只对 ~10/~8/<=0 触发推算，其它值保留 → 高度来源不可预测）。
            h = 0.0
            stats["fixed_height"] += 1
        elif h > MAX_HEIGHT_M:
            h = min(h, MAX_HEIGHT_M)
            stats["clamped_height"] += 1

        # 5. 近重复去重
        ctr = _ring_centroid(pts)
        is_dup = any(_dist_deg(ctr, c) < DEDUP_DIST_M for c in centroids)
        if is_dup:
            stats["removed_duplicate"] += 1
            continue

        centroids.append(ctr)
        new_feat = {
            "type": "Feature",
            "geometry": feat["geometry"],
            "properties": {**props, "height": h},
        }
        kept.append(new_feat)

    stats["total_out"] = len(kept)

    if not dry_run:
        out_fc = {"type": "FeatureCollection", "features": kept}
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(out_fc, f, ensure_ascii=False, separators=(",", ":"))
        tmp.replace(path)
        print(f"  [buildings] 写入: {path.name}")

    return stats


# ── OSM 道路清洗 ─────────────────────────────────────────────

def clean_osm(path: Path, dry_run: bool) -> dict[str, Any]:
    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        return {"error": str(e)}

    root = tree.getroot()

    # 统计节点
    node_ids = {nd.get("id") for nd in root.findall("node")}

    stats: dict[str, Any] = {
        "total_nodes": len(node_ids),
        "ways_in":     0,
        "ways_removed_short": 0,
        "ways_removed_orphan": 0,
        "ways_removed_type":   0,
        "ways_out":    0,
        "highway_types": {},
    }

    ways_to_remove: list = []
    for way in root.findall("way"):
        stats["ways_in"] += 1
        tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
        hw = tags.get("highway", "")
        nd_refs = [nr.get("ref") for nr in way.findall("nd")]

        # 过短
        if len(nd_refs) < 2:
            stats["ways_removed_short"] += 1
            ways_to_remove.append(way)
            continue

        # 孤儿节点（引用的节点不在文件里）
        orphan = any(r not in node_ids for r in nd_refs)
        if orphan:
            stats["ways_removed_orphan"] += 1
            ways_to_remove.append(way)
            continue

        # 道路类型过滤（如果白名单非空，只保留白名单内的）
        if hw and HIGHWAY_WHITELIST and hw not in HIGHWAY_WHITELIST:
            stats["ways_removed_type"] += 1
            ways_to_remove.append(way)
            continue

        if hw:
            stats["highway_types"][hw] = stats["highway_types"].get(hw, 0) + 1

    for way in ways_to_remove:
        root.remove(way)

    stats["ways_out"] = stats["ways_in"] - len(ways_to_remove)

    if not dry_run and ways_to_remove:
        import tempfile, os
        tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        os.close(tmp_fd)
        tree.write(tmp_path, encoding="unicode", xml_declaration=True)
        Path(tmp_path).replace(path)
        print(f"  [osm]       写入: {path.name}")

    return stats


def merge_roads(path: Path, tolerance_m: float = 1.0, dry_run: bool = False) -> dict[str, Any]:
    """Weld near-matching road endpoints and merge degree-2 road chains in-place.

    This is intentionally conservative for the experiment stage: only roads with
    the same important tags are chained, and chains stop at endpoints used by
    anything other than exactly two matching road ends.
    """
    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        return {"error": str(e), "merged": 0}

    root = tree.getroot()
    node_elems = {nd.get("id"): nd for nd in root.findall("node")}
    nodes: dict[str, tuple[float, float]] = {}
    for nid, elem in node_elems.items():
        if nid is None:
            continue
        try:
            nodes[nid] = (float(elem.get("lon")), float(elem.get("lat")))
        except (TypeError, ValueError):
            continue

    def _way_tags(way: ET.Element) -> dict[str, str]:
        return {t.get("k"): t.get("v") for t in way.findall("tag") if t.get("k")}

    def _merge_key(tags: dict[str, str]) -> tuple[str, ...]:
        return (
            tags.get("highway", ""),
            tags.get("lanes", ""),
            tags.get("width", ""),
            tags.get("oneway", ""),
            tags.get("bridge", ""),
            tags.get("tunnel", ""),
            tags.get("layer", ""),
            tags.get("surface", ""),
        )

    candidates: list[dict[str, Any]] = []
    endpoint_records: list[tuple[str, float, float]] = []
    for way in root.findall("way"):
        tags = _way_tags(way)
        if not tags.get("highway"):
            continue
        refs = [nr.get("ref") for nr in way.findall("nd") if nr.get("ref")]
        if len(refs) < 2 or refs[0] not in nodes or refs[-1] not in nodes:
            continue
        item = {
            "elem": way,
            "tags": tags,
            "key": _merge_key(tags),
            "refs": refs,
            "active": True,
        }
        candidates.append(item)
        for ref in (refs[0], refs[-1]):
            endpoint_records.append((ref, *nodes[ref]))

    if not candidates:
        return {"ways_in": 0, "ways_out": 0, "merged": 0, "welded_endpoints": 0}

    # Endpoint clustering in local UTM metres.
    from _utm_lite import wgs84_to_utm, zone_number
    avg_lon = sum(p[1] for p in endpoint_records) / len(endpoint_records)
    avg_lat = sum(p[2] for p in endpoint_records) / len(endpoint_records)
    zone = zone_number(avg_lon)

    parent = list(range(len(endpoint_records)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    cell = max(tolerance_m, 0.01)
    xy: list[tuple[float, float]] = []
    for i, (_nid, lon, lat) in enumerate(endpoint_records):
        x, y, _ = wgs84_to_utm(lat, lon, force_zone=zone)
        xy.append((x, y))
        gx, gy = int(math.floor(x / cell)), int(math.floor(y / cell))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in grid.get((gx + dx, gy + dy), []):
                    ox, oy = xy[j]
                    if math.hypot(x - ox, y - oy) <= tolerance_m:
                        union(i, j)
        grid[(gx, gy)].append(i)

    cluster_members: dict[int, list[int]] = defaultdict(list)
    for i in range(len(endpoint_records)):
        cluster_members[find(i)].append(i)

    endpoint_repr: dict[str, str] = {}
    for members in cluster_members.values():
        # Prefer the lowest numeric id if possible; otherwise first seen.
        ids = [endpoint_records[i][0] for i in members]
        try:
            rep = min(ids, key=lambda v: int(v))
        except ValueError:
            rep = ids[0]
        for nid in ids:
            endpoint_repr[nid] = rep

    welded = 0
    for item in candidates:
        refs = list(item["refs"])
        for idx in (0, len(refs) - 1):
            rep = endpoint_repr.get(refs[idx], refs[idx])
            if rep != refs[idx]:
                welded += 1
                refs[idx] = rep
        item["refs"] = refs

    groups: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for i, item in enumerate(candidates):
        groups[item["key"]].append(i)

    def _oneway(tags: dict[str, str]) -> bool:
        return str(tags.get("oneway", "")).lower() in {"yes", "1", "true", "-1"}

    def _concat_refs(a: list[str], b: list[str], side_a: str, side_b: str,
                     can_reverse_b: bool) -> list[str] | None:
        if side_a == "end" and side_b == "start":
            return a + b[1:]
        if side_a == "start" and side_b == "end":
            return b + a[1:]
        if side_a == "end" and side_b == "end" and can_reverse_b:
            return a + list(reversed(b[:-1]))
        if side_a == "start" and side_b == "start" and can_reverse_b:
            return list(reversed(b)) + a[1:]
        return None

    merged = 0
    for idxs in groups.values():
        changed = True
        while changed:
            changed = False
            endpoint_map: dict[str, list[tuple[int, str]]] = defaultdict(list)
            for idx in idxs:
                item = candidates[idx]
                if not item["active"]:
                    continue
                refs = item["refs"]
                if len(refs) < 2 or refs[0] == refs[-1]:
                    continue
                endpoint_map[refs[0]].append((idx, "start"))
                endpoint_map[refs[-1]].append((idx, "end"))

            for endpoint, uses in endpoint_map.items():
                if len(uses) != 2:
                    continue
                (ai, aside), (bi, bside) = uses
                if ai == bi:
                    continue
                a = candidates[ai]
                b = candidates[bi]
                if not a["active"] or not b["active"]:
                    continue
                can_reverse_b = not _oneway(a["tags"]) and not _oneway(b["tags"])
                new_refs = _concat_refs(a["refs"], b["refs"], aside, bside, can_reverse_b)
                if not new_refs or len(new_refs) < 2:
                    continue
                a["refs"] = new_refs
                b["active"] = False
                merged += 1
                changed = True
                break

    inactive_elems = {item["elem"] for item in candidates if not item["active"]}
    for item in candidates:
        if not item["active"]:
            continue
        way = item["elem"]
        for nd in list(way.findall("nd")):
            way.remove(nd)
        for offset, ref in enumerate(item["refs"]):
            way.insert(offset, ET.Element("nd", {"ref": ref}))

    if not dry_run:
        for elem in inactive_elems:
            root.remove(elem)
        import tempfile, os
        tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        os.close(tmp_fd)
        tree.write(tmp_path, encoding="unicode", xml_declaration=True)
        Path(tmp_path).replace(path)

    ways_in = len(candidates)
    ways_out = ways_in - len(inactive_elems)
    return {
        "ways_in": ways_in,
        "ways_out": ways_out,
        "merged": merged,
        "welded_endpoints": welded,
        "endpoint_clusters": len(cluster_members),
        "tolerance_m": tolerance_m,
    }


# ── 主函数 ───────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="VirtualCity 原始数据清洗")
    ap.add_argument("--dry-run",  action="store_true", help="只报告，不写入文件")
    ap.add_argument("--report",   action="store_true", help="同时输出 JSON 报告")
    ap.add_argument("--no-osm",   action="store_true", help="跳过 OSM 清洗")
    args = ap.parse_args()

    cfg = vc_paths.load_active_area(absolute=True)
    area_id = cfg.get("area_id", "unknown")
    print(f"\n[VirtualCity 数据清洗] 区域: {area_id}")
    if args.dry_run:
        print("  [DRY-RUN] 不写入文件")

    report: dict[str, Any] = {"area_id": area_id}

    # ── 建筑 GeoJSON ──
    bld_path = Path(cfg.get("buildings_file", ""))
    if bld_path.exists():
        print(f"\n  建筑文件: {bld_path.name}")
        bst = clean_buildings(bld_path, args.dry_run)
        removed = bst["total_in"] - bst["total_out"]
        print(f"  输入: {bst['total_in']}  ->  输出: {bst['total_out']}  (移除 {removed})")
        print(f"    null/非多边形:  {bst['removed_null']}")
        print(f"    退化多边形:    {bst['removed_degenerate']}")
        print(f"    面积<{MIN_AREA_M2}m2: {bst['removed_tiny']}")
        print(f"    近重复:        {bst['removed_duplicate']}")
        print(f"    高度已修复:    {bst['fixed_height']}")
        print(f"    高度已截断:    {bst['clamped_height']}")
        report["buildings"] = bst
    else:
        print(f"  ⚠ 建筑文件不存在: {bld_path}")

    # ── OSM ──
    if not args.no_osm:
        osm_path = Path(cfg.get("osm_file", ""))
        if osm_path.exists():
            print(f"\n  OSM 文件: {osm_path.name}")
            ost = clean_osm(osm_path, args.dry_run)
            if "error" in ost:
                print(f"  ❌ XML 解析失败: {ost['error']}")
            else:
                removed_w = ost["ways_in"] - ost["ways_out"]
                print(f"  节点: {ost['total_nodes']}  道路: {ost['ways_in']} -> {ost['ways_out']}  (移除 {removed_w})")
                print(f"    过短:         {ost['ways_removed_short']}")
                print(f"    孤儿节点:     {ost['ways_removed_orphan']}")
                print(f"    类型过滤:     {ost['ways_removed_type']}")
                types_sorted = sorted(ost["highway_types"].items(), key=lambda x: -x[1])
                print(f"    保留道路类型: {dict(types_sorted[:8])}")
            report["osm"] = ost
        else:
            print(f"  ⚠ OSM 文件不存在: {osm_path}")

    # ── 报告输出 ──
    if args.report:
        report_path = vc_paths.CONFIG / f"clean_report_{area_id}.json"
        with open(report_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n  报告已写入: {report_path}")

    print("\n[OK] 清洗完成\n")
    return report


if __name__ == "__main__":
    main()
