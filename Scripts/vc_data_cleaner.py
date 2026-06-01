"""
VirtualCity — 2.5D 道路数据清洗与拓扑规范化 (Milestone 1)
======================================================
1. 读取 raw roads.osm (XML)。
2. 进行 2.5D 拓扑清洗：
   - 高度层级隔离（同 layer 允许相交，跨 layer/桥隧隔离不切断）。
   - 窄路优先吸附（Snapping）到宽路几何/节点。
   - 2.5D 交点计算与分割（Intersection Splitting）。
   - 链式合并（Linemerge）同属性碎段。
3. 输出两套产物以完美适配管线：
   - `roads_clean.geojson`: 干净的 2D/2.5D GeoJSON 道路拓扑线（供后续 Graph 生成使用）。
   - `roads.osm`: 高度兼容的 OSM XML（作为 Houdini 旧 osm_import 节点的 100% 降级输入，保证 0-回归风险）。
"""
from __future__ import annotations

import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from collections import defaultdict

from shapely.geometry import Point, LineString, MultiPoint

# 注入本地路径
sys.path.insert(0, str(Path(__file__).parent))
import vc_paths
import vc_geo

# ── 道路优先级（用于窄路吸附到宽路） ─────────────────────────────────────
ROAD_PRIORITY = {
    "motorway": 1,
    "trunk": 1,
    "motorway_link": 1,
    "trunk_link": 1,
    "primary": 2,
    "primary_link": 2,
    "secondary": 3,
    "secondary_link": 3,
    "tertiary": 4,
    "tertiary_link": 4,
    "residential": 5,
    "unclassified": 5,
    "living_street": 5,
    "service": 6,
    "footway": 7,
    "pedestrian": 7,
    "path": 7,
    "cycleway": 7,
    "track": 7,
}

# 只保留这些 highway 类型
HIGHWAY_WHITELIST = set(ROAD_PRIORITY.keys())


class Road2D5Cleaner:
    def __init__(self, origin_lon: float, origin_lat: float):
        self.proj = vc_geo.LocalProjector(origin_lon, origin_lat)
        self.origin_lon = origin_lon
        self.origin_lat = origin_lat

    def _to_wgs84(self, x: float, z: float) -> tuple[float, float]:
        """数据域局部坐标 (x, z) -> WGS84 (lon, lat)"""
        import _utm_lite as _utm
        easting = x + self.proj._ox
        northing = z + self.proj._oy
        lat, lon = _utm.utm_to_wgs84(easting, northing, self.proj.zone, northern=(self.origin_lat >= 0))
        return lon, lat

    def _parse_osm(self, osm_path: Path) -> tuple[dict[str, tuple[float, float]], list[dict[str, Any]]]:
        """解析原始 OSM XML"""
        tree = ET.parse(osm_path)
        root = tree.getroot()

        # 1. 提取所有节点
        raw_nodes = {}
        for nd in root.findall("node"):
            nid = nd.get("id")
            if nid:
                raw_nodes[nid] = (float(nd.get("lon")), float(nd.get("lat")))

        # 2. 提取所有有效 ways
        raw_ways = []
        for way in root.findall("way"):
            tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
            hw = tags.get("highway", "")
            if not hw or hw not in HIGHWAY_WHITELIST:
                continue

            nd_refs = [nr.get("ref") for nr in way.findall("nd") if nr.get("ref")]
            if len(nd_refs) < 2:
                continue

            # 过滤掉不存在的节点引用
            valid_nd_refs = [r for r in nd_refs if r in raw_nodes]
            if len(valid_nd_refs) < 2:
                continue

            # 提取 2.5D 层级 (layer)
            # 默认 0；有 bridge=yes 且缺 layer 则默认 1；有 tunnel=yes 且缺 layer 则默认 -1
            layer_val = 0
            if "layer" in tags:
                try:
                    layer_val = int(tags["layer"])
                except ValueError:
                    pass
            elif tags.get("bridge") in ("yes", "true", "1"):
                layer_val = 1
            elif tags.get("tunnel") in ("yes", "true", "1"):
                layer_val = -1

            # 标准化 lanes 和 width 默认值
            lanes = 0
            if "lanes" in tags:
                try:
                    lanes = int(tags["lanes"])
                except ValueError:
                    pass

            width = 0.0
            if "width" in tags:
                try:
                    width = float(tags["width"])
                except ValueError:
                    pass

            way_item = {
                "id": way.get("id"),
                "nodes": valid_nd_refs,
                "highway": hw,
                "lanes": lanes,
                "width": width,
                "oneway": tags.get("oneway", "no"),
                "bridge": tags.get("bridge", "no"),
                "tunnel": tags.get("tunnel", "no"),
                "layer": layer_val,
                "surface": tags.get("surface", "asphalt"),
                "maxspeed": tags.get("maxspeed", "0"),
                "tags": tags,
            }
            raw_ways.append(way_item)

        return raw_nodes, raw_ways

    def _split_line_at_distances(self, line: LineString, distances: list[float]) -> list[LineString]:
        """在指定的投影累积距离处对 LineString 进行切割"""
        if not distances:
            return [line]
        coords = list(line.coords)
        segments = []
        curr_dist = 0.0
        curr_segment = [coords[0]]

        distances = sorted(set(distances))
        dist_idx = 0

        for i in range(len(coords) - 1):
            p1 = coords[i]
            p2 = coords[i + 1]
            seg_len = math.hypot(p2[0] - p1[0], p2[1] - p1[1])

            while dist_idx < len(distances) and curr_dist <= distances[dist_idx] < curr_dist + seg_len:
                split_dist = distances[dist_idx]
                t = (split_dist - curr_dist) / seg_len if seg_len > 0 else 0.0
                split_pt = (p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t)

                # 避免插入零长度段
                if math.hypot(split_pt[0] - curr_segment[-1][0], split_pt[1] - curr_segment[-1][1]) > 1e-4:
                    curr_segment.append(split_pt)
                segments.append(LineString(curr_segment))
                curr_segment = [split_pt]
                curr_dist = split_dist
                dist_idx += 1

            # 避免插入零长度段
            if math.hypot(p2[0] - curr_segment[-1][0], p2[1] - curr_segment[-1][1]) > 1e-4:
                curr_segment.append(p2)
            curr_dist += seg_len

        if len(curr_segment) > 1:
            segments.append(LineString(curr_segment))
        return segments

    def clean(self, osm_path: Path, geojson_out: Path, osm_out: Path, tolerance_m: float = 1.0) -> dict[str, Any]:
        """核心 2.5D 清洗逻辑"""
        raw_nodes, raw_ways = self._parse_osm(osm_path)

        # 1. 转换坐标到平面局部 Cartesian (x, z)，并构建 shapely LineString
        ways_by_layer = defaultdict(list)
        for way in raw_ways:
            local_pts = [self.proj.to_local(raw_nodes[nid][0], raw_nodes[nid][1]) for nid in way["nodes"]]
            # 去除重复连续折点
            cleaned_local_pts = [local_pts[0]]
            for pt in local_pts[1:]:
                if math.hypot(pt[0] - cleaned_local_pts[-1][0], pt[1] - cleaned_local_pts[-1][1]) > 1e-3:
                    cleaned_local_pts.append(pt)
            if len(cleaned_local_pts) < 2:
                continue
            way["line"] = LineString(cleaned_local_pts)
            way["priority"] = ROAD_PRIORITY.get(way["highway"], 9)
            ways_by_layer[way["layer"]].append(way)

        stats = {
            "ways_in": len(raw_ways),
            "snapped_endpoints": 0,
            "intersection_splits": 0,
            "ways_out": 0,
            "merged_chains": 0,
        }

        all_cleaned_ways = []

        # 2. 按 layer 分层清洗，实现隔离
        for layer_val, layer_ways in ways_by_layer.items():
            if not layer_ways:
                continue

            # A. 2.5D 端点 Snapping (窄路优先吸附到宽路)
            snapped_any = True
            snap_iterations = 0
            while snapped_any and snap_iterations < 3:
                snapped_any = False
                snap_iterations += 1

                for i, way in enumerate(layer_ways):
                    line = way["line"]
                    coords = list(line.coords)
                    p_start, p_end = Point(coords[0]), Point(coords[-1])
                    p_priority = way["priority"]

                    for p_node, is_start in [(p_start, True), (p_end, False)]:
                        best_snap_pt = None
                        best_dist = float("inf")

                        # 寻找匹配的其它路进行吸附
                        for j, other_way in enumerate(layer_ways):
                            if i == j:
                                continue
                            # 窄路优先吸附到等宽或更宽的路
                            if other_way["priority"] > p_priority:
                                continue

                            other_line = other_way["line"]
                            dist = p_node.distance(other_line)
                            if 0 < dist <= tolerance_m:
                                # 寻找最近点
                                proj_dist = other_line.project(p_node)
                                snap_pt = other_line.interpolate(proj_dist)
                                if dist < best_dist:
                                    best_dist = dist
                                    best_snap_pt = snap_pt

                        if best_snap_pt is not None:
                            # 更新 A 的几何
                            new_coords = list(coords)
                            snap_coord = (best_snap_pt.x, best_snap_pt.y)
                            if is_start:
                                new_coords[0] = snap_coord
                            else:
                                new_coords[-1] = snap_coord
                            way["line"] = LineString(new_coords)
                            snapped_any = True
                            stats["snapped_endpoints"] += 1

            # B. 2.5D 交点分割 (Intersection Splitting)
            split_points_per_way = defaultdict(list)
            for i in range(len(layer_ways)):
                for j in range(i + 1, len(layer_ways)):
                    way_a = layer_ways[i]
                    way_b = layer_ways[j]
                    line_a = way_a["line"]
                    line_b = way_b["line"]

                    if line_a.intersects(line_b):
                        inter = line_a.intersection(line_b)
                        if inter.is_empty:
                            continue
                        pts = []
                        if isinstance(inter, Point):
                            pts.append(inter)
                        elif isinstance(inter, MultiPoint):
                            pts.extend(inter.geoms)

                        for pt in pts:
                            proj_a = line_a.project(pt)
                            proj_b = line_b.project(pt)
                            # 只有在内部时才记录分割
                            if 0.05 < proj_a < line_a.length - 0.05:
                                split_points_per_way[i].append(proj_a)
                            if 0.05 < proj_b < line_b.length - 0.05:
                                split_points_per_way[j].append(proj_b)

            # C. 物理分割
            split_layer_ways = []
            for idx, way in enumerate(layer_ways):
                dists = split_points_per_way.get(idx, [])
                if dists:
                    segments = self._split_line_at_distances(way["line"], dists)
                    stats["intersection_splits"] += len(segments) - 1
                    for seg in segments:
                        sub_way = dict(way)
                        sub_way["line"] = seg
                        split_layer_ways.append(sub_way)
                else:
                    split_layer_ways.append(way)

            # D. 端点焊接 (Node Welding, 1cm Grid)
            # 给每条线的端点分配唯一 Node ID，以便进行 Linemerge 和输出 OSM XML
            node_coords = {}  # (x, z) -> node_id
            node_counter = 1

            def _get_node_id(pt):
                nonlocal node_counter
                k = (round(pt[0] * 100), round(pt[1] * 100))  # 1cm 精确度焊接
                if k in node_coords:
                    return node_coords[k]
                nid = f"wld_{layer_val}_{node_counter}"
                node_coords[k] = nid
                node_counter += 1
                return nid

            for way in split_layer_ways:
                coords = list(way["line"].coords)
                way["node_start"] = _get_node_id(coords[0])
                way["node_end"] = _get_node_id(coords[-1])

            # E. 链式合并 (Linemerge)
            # 在同一层内，如果两个 edge 具有完全相同的属性，且在度为 2 的节点相遇，将其合并。
            def _merge_key(w):
                return (
                    w["highway"],
                    w["lanes"],
                    w["width"],
                    w["oneway"],
                    w["bridge"],
                    w["tunnel"],
                    w["layer"],
                    w["surface"],
                    w["maxspeed"],
                )

            # 统计度数
            node_degree = defaultdict(int)
            for way in split_layer_ways:
                node_degree[way["node_start"]] += 1
                node_degree[way["node_end"]] += 1

            # 尝试合并循环
            merged_any = True
            while merged_any:
                merged_any = False
                # 重建端点连接映射
                node_connections = defaultdict(list)
                for w_idx, way in enumerate(split_layer_ways):
                    if not way.get("active", True):
                        continue
                    node_connections[way["node_start"]].append((w_idx, "start"))
                    node_connections[way["node_end"]].append((w_idx, "end"))

                for node_id, conns in node_connections.items():
                    if len(conns) != 2 or node_degree[node_id] != 2:
                        continue
                    (ai, aside), (bi, bside) = conns
                    way_a = split_layer_ways[ai]
                    way_b = split_layer_ways[bi]

                    # 仅当两路标签完全一致时才合并
                    if _merge_key(way_a) != _merge_key(way_b):
                        continue

                    # 判断是否单行线
                    is_oneway = way_a["oneway"] in ("yes", "true", "1")

                    # 连接坐标
                    coords_a = list(way_a["line"].coords)
                    coords_b = list(way_b["line"].coords)

                    # 拼接
                    if aside == "end" and bside == "start":
                        new_coords = coords_a + coords_b[1:]
                        new_start, new_end = way_a["node_start"], way_b["node_end"]
                    elif aside == "start" and bside == "end":
                        new_coords = coords_b + coords_a[1:]
                        new_start, new_end = way_b["node_start"], way_a["node_end"]
                    elif aside == "end" and bside == "end" and not is_oneway:
                        new_coords = coords_a + list(reversed(coords_b[:-1]))
                        new_start, new_end = way_a["node_start"], way_b["node_start"]
                    elif aside == "start" and bside == "start" and not is_oneway:
                        new_coords = list(reversed(coords_b)) + coords_a[1:]
                        new_start, new_end = way_b["node_end"], way_a["node_end"]
                    else:
                        continue

                    way_a["line"] = LineString(new_coords)
                    way_a["node_start"] = new_start
                    way_a["node_end"] = new_end
                    way_b["active"] = False
                    node_degree[node_id] = 0  # 合并点度数归 0
                    merged_any = True
                    stats["merged_chains"] += 1
                    break

            # 收集结果
            for way in split_layer_ways:
                if way.get("active", True):
                    all_cleaned_ways.append(way)

        stats["ways_out"] = len(all_cleaned_ways)

        # ── 输出两套产物 ─────────────────────────────────────────────

        # 1. 保存为 GeoJSON
        geojson_features = []
        for idx, way in enumerate(all_cleaned_ways):
            local_coords = list(way["line"].coords)
            wgs84_coords = [self._to_wgs84(pt[0], pt[1]) for pt in local_coords]

            properties = {
                "highway": way["highway"],
                "lanes": way["lanes"],
                "width": way["width"],
                "oneway": way["oneway"],
                "bridge": way["bridge"],
                "tunnel": way["tunnel"],
                "layer": way["layer"],
                "surface": way["surface"],
                "maxspeed": way["maxspeed"],
                "seg_id": idx + 1,
                "from_node": way["node_start"],
                "to_node": way["node_end"],
            }

            feat = {
                "type": "Feature",
                "id": way["id"] or f"cl_way_{idx+1}",
                "geometry": {
                    "type": "LineString",
                    "coordinates": wgs84_coords,
                },
                "properties": properties,
            }
            geojson_features.append(feat)

        geojson_out.parent.mkdir(parents=True, exist_ok=True)
        with open(geojson_out, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"type": "FeatureCollection", "features": geojson_features}, f, ensure_ascii=False, indent=2)
        print(f"  [2.5D Cleaner] 写入 GeoJSON: {vc_paths.project_relative(geojson_out)}")

        # 2. 保存为 OSM XML
        # 建立全局 node pool
        osm_nodes = {}  # name -> (lon, lat)
        osm_ways_list = []

        for idx, way in enumerate(all_cleaned_ways):
            local_coords = list(way["line"].coords)
            wgs84_coords = [self._to_wgs84(pt[0], pt[1]) for pt in local_coords]

            # 分配中间顶点节点 ID
            way_node_ids = []
            for i, pt in enumerate(wgs84_coords):
                if i == 0:
                    nid = way["node_start"]
                elif i == len(wgs84_coords) - 1:
                    nid = way["node_end"]
                else:
                    nid = f"cl_nd_mid_{idx+1}_{i}"
                osm_nodes[nid] = pt
                way_node_ids.append(nid)

            osm_ways_list.append({
                "id": way["id"] or f"cl_way_{idx+1}",
                "nodes": way_node_ids,
                "tags": way["tags"]
            })

        osm_root = ET.Element("osm", {"version": "0.6", "generator": "VirtualCity 2.5D Cleaner"})
        
        # 写入节点
        for nid, (lon, lat) in sorted(osm_nodes.items()):
            ET.SubElement(osm_root, "node", {
                "id": nid,
                "lat": f"{lat:.7f}",
                "lon": f"{lon:.7f}",
                "version": "1"
            })

        # 写入道路
        for way in osm_ways_list:
            w_elem = ET.SubElement(osm_root, "way", {
                "id": way["id"],
                "version": "1"
            })
            for ref in way["nodes"]:
                ET.SubElement(w_elem, "nd", {"ref": ref})
            for k, v in sorted(way["tags"].items()):
                ET.SubElement(w_elem, "tag", {"k": k, "v": v})

        osm_out.parent.mkdir(parents=True, exist_ok=True)
        tree = ET.ElementTree(osm_root)
        
        # 自定义写入临时文件后覆盖
        import tempfile, os
        tmp_fd, tmp_path = tempfile.mkstemp(dir=osm_out.parent, suffix=".tmp")
        os.close(tmp_fd)
        tree.write(tmp_path, encoding="utf-8", xml_declaration=True)
        Path(tmp_path).replace(osm_out)
        print(f"  [2.5D Cleaner] 写入 OSM XML: {vc_paths.project_relative(osm_out)}")

        return stats
