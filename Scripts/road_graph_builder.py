"""
VirtualCity — Road Graph 拓扑图生成器 (Milestone 1 - Stage 2)
=============================================================
从 roads_clean.geojson 提取并规范化 Nodes 与 Edges，输出标准的 road_graph.json：
- Nodes: 包含 id, 局部坐标 (x, z, y), 连接的 edges 列表, 度数 (degree)。
- Edges: 包含 id, from/to 节点, 道路等级, 宽度, 车道数, 局部坐标坐标点列 (geometry_coords)。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any
from collections import defaultdict

# 注入本地路径
sys.path.insert(0, str(Path(__file__).parent))
import vc_paths
import vc_geo


HIGHWAY_DEFAULT_WIDTHS = {
    "motorway": 15.0,
    "trunk": 15.0,
    "primary": 10.5,
    "secondary": 10.5,
    "tertiary": 8.0,
    "residential": 6.0,
    "unclassified": 6.0,
    "living_street": 6.0,
    "service": 4.0,
    "footway": 2.0,
    "path": 2.0,
    "pedestrian": 2.0,
}

MAJOR_ROAD_CLASSES = {"motorway", "trunk"}


def _edge_length_m(coords: list[list[float]]) -> float:
    length = 0.0
    for a, b in zip(coords, coords[1:]):
        dx = float(b[0]) - float(a[0])
        dz = float(b[1]) - float(a[1])
        length += math.hypot(dx, dz)
    return length


def _effective_width_m(highway: str, width: float, lanes: int) -> float:
    if width > 0.0:
        return width
    base = HIGHWAY_DEFAULT_WIDTHS.get(highway, 6.0)
    if lanes > 0:
        base = max(base, lanes * 3.2)
    return base


def _node_direction(edge: dict[str, Any], node_id: str) -> tuple[float, float] | None:
    coords = edge.get("geometry_coords") or []
    if len(coords) < 2:
        return None

    if node_id == edge.get("from_node"):
        a, b = coords[0], coords[1]
    elif node_id == edge.get("to_node"):
        a, b = coords[-1], coords[-2]
    else:
        return None

    dx = float(b[0]) - float(a[0])
    dz = float(b[1]) - float(a[1])
    mag = math.hypot(dx, dz)
    if mag <= 1.0e-6:
        return None
    return (dx / mag, dz / mag)


def _angle_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1]))
    return math.acos(dot)


def _junction_style(incident_edges: list[dict[str, Any]]) -> str:
    if len(incident_edges) < 3:
        return "None"
    classes = {str(edge.get("class", "")) for edge in incident_edges}
    if "roundabout" in classes:
        return "Roundabout"
    if classes & MAJOR_ROAD_CLASSES:
        return "Freeway"

    half_widths = sorted((float(edge.get("half_width_m", 0.0)) for edge in incident_edges), reverse=True)
    if len(half_widths) >= 2 and half_widths[1] > 0.0 and half_widths[0] / half_widths[1] >= 1.5:
        return "Junction"
    return "Crossing"


def _junction_radius_m(style: str) -> float:
    if style == "Freeway":
        return 20.0
    if style == "Junction":
        return 5.0
    if style == "Roundabout":
        return 4.0
    if style == "Crossing":
        return 6.0
    return 0.0


def _clip_margin_m(edge: dict[str, Any], node_id: str, incident_edges: list[dict[str, Any]], style: str) -> float:
    if style == "None" or len(incident_edges) < 3:
        return 0.0

    own_dir = _node_direction(edge, node_id)
    if own_dir is None:
        return 0.0

    neighbor_dirs = [
        direction
        for other in incident_edges
        if other is not edge
        for direction in [_node_direction(other, node_id)]
        if direction is not None
    ]
    if not neighbor_dirs:
        return 0.0

    min_angle = min(_angle_between(own_dir, other_dir) for other_dir in neighbor_dirs)
    sin_theta = max(0.25, math.sin(max(math.radians(10.0), min_angle)))
    sorted_half_widths = sorted((float(item.get("half_width_m", 0.0)) for item in incident_edges), reverse=True)
    max_half_width = sorted_half_widths[0] if sorted_half_widths else float(edge.get("half_width_m", 0.0))

    # Junction 模式下主路保持连续：主路边用次大宽度估算入口影响，支路仍按最大宽度避让。
    if style == "Junction" and sorted_half_widths:
        own_half_width = float(edge.get("half_width_m", 0.0))
        if math.isclose(own_half_width, sorted_half_widths[0], rel_tol=0.05, abs_tol=0.25):
            max_half_width = sorted_half_widths[1] if len(sorted_half_widths) > 1 else max_half_width

    return max_half_width / (2.0 * sin_theta) + _junction_radius_m(style)


def _nodes_from_edges(edges_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes_dict: dict[str, dict[str, Any]] = {}
    for edge in edges_list:
        endpoints = (
            (str(edge.get("from_node", "")), (edge.get("geometry_coords") or [None])[0]),
            (str(edge.get("to_node", "")), (edge.get("geometry_coords") or [None])[-1]),
        )
        for node_id, pt in endpoints:
            if not node_id or pt is None:
                continue
            if node_id not in nodes_dict:
                nodes_dict[node_id] = {
                    "id": node_id,
                    "x": float(pt[0]),
                    "z": float(pt[1]),
                    "y": float(pt[2]),
                    "elevation_source": "pending",
                    "connected_edges": [],
                }

    for edge in edges_list:
        eid = edge["id"]
        fn = edge.get("from_node", "")
        tn = edge.get("to_node", "")
        if fn in nodes_dict:
            nodes_dict[fn]["connected_edges"].append(eid)
        if tn in nodes_dict and tn != fn:
            nodes_dict[tn]["connected_edges"].append(eid)

    nodes_list = []
    for _nid, node in sorted(nodes_dict.items()):
        node["degree"] = len(node["connected_edges"])
        nodes_list.append(node)
    return nodes_list


def _annotate_junction_conflicts(nodes_list: list[dict[str, Any]], edges_list: list[dict[str, Any]]) -> dict[str, Any]:
    edges_by_id = {edge["id"]: edge for edge in edges_list}
    for node in nodes_list:
        incident_edges = [edges_by_id[eid] for eid in node["connected_edges"] if eid in edges_by_id]
        node["junction_style"] = _junction_style(incident_edges)

    nodes_by_id = {node["id"]: node for node in nodes_list}
    short_conflict_edges = 0
    max_conflict_ratio = 0.0
    for edge in edges_list:
        from_node_data = nodes_by_id.get(edge["from_node"], {})
        to_node_data = nodes_by_id.get(edge["to_node"], {})
        from_incident = [edges_by_id[eid] for eid in from_node_data.get("connected_edges", []) if eid in edges_by_id]
        to_incident = [edges_by_id[eid] for eid in to_node_data.get("connected_edges", []) if eid in edges_by_id]

        from_style = str(from_node_data.get("junction_style", "None"))
        to_style = str(to_node_data.get("junction_style", "None"))
        clip_from = _clip_margin_m(edge, edge["from_node"], from_incident, from_style)
        clip_to = _clip_margin_m(edge, edge["to_node"], to_incident, to_style)
        length_m = float(edge.get("length_m", 0.0))
        conflict_ratio = (clip_from + clip_to) / length_m if length_m > 0.0 else 0.0
        conflict = length_m > 0.0 and (clip_from + clip_to) > length_m

        edge["junction_style_from"] = from_style
        edge["junction_style_to"] = to_style
        edge["clip_margin_from_m"] = round(clip_from, 3)
        edge["clip_margin_to_m"] = round(clip_to, 3)
        edge["conflict_ratio"] = round(conflict_ratio, 3)
        edge["conflict_short_edge"] = conflict
        if conflict:
            short_conflict_edges += 1
            max_conflict_ratio = max(max_conflict_ratio, conflict_ratio)

    return {
        "short_conflict_edges": short_conflict_edges,
        "max_conflict_ratio": round(max_conflict_ratio, 3),
    }


class _DisjointSet:
    def __init__(self, values: list[str]):
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent.setdefault(value, value)
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, a: str, b: str) -> None:
        ra = self.find(a)
        rb = self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _collapse_conflicting_short_edges(nodes_list: list[dict[str, Any]], edges_list: list[dict[str, Any]]) -> dict[str, Any]:
    node_ids = [node["id"] for node in nodes_list]
    dsu = _DisjointSet(node_ids)
    collapsed_edge_ids = []
    for edge in edges_list:
        if not edge.get("conflict_short_edge"):
            continue
        fn = str(edge.get("from_node", ""))
        tn = str(edge.get("to_node", ""))
        if not fn or not tn or fn == tn:
            continue
        if edge.get("junction_style_from") == "None" and edge.get("junction_style_to") == "None":
            continue
        dsu.union(fn, tn)
        collapsed_edge_ids.append(edge["id"])

    if not collapsed_edge_ids:
        return {
            "edges": edges_list,
            "collapsed_conflict_edges": 0,
            "collapsed_node_groups": 0,
        }

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes_list:
        groups[dsu.find(node["id"])].append(node)

    collapsed_groups = {root: group for root, group in groups.items() if len(group) > 1}
    merged_node_coords: dict[str, tuple[float, float, float]] = {}
    remap: dict[str, str] = {}
    for root, group in groups.items():
        if len(group) > 1:
            merged_id = "merged_" + "_".join(sorted(node["id"] for node in group))
        else:
            merged_id = group[0]["id"]
        x = sum(float(node["x"]) for node in group) / len(group)
        z = sum(float(node["z"]) for node in group) / len(group)
        y = sum(float(node["y"]) for node in group) / len(group)
        merged_node_coords[merged_id] = (round(x, 4), round(z, 4), round(y, 4))
        for node in group:
            remap[node["id"]] = merged_id

    collapsed_ids = set(collapsed_edge_ids)
    out_edges = []
    for edge in edges_list:
        if edge["id"] in collapsed_ids:
            continue
        fn = remap.get(str(edge.get("from_node", "")), str(edge.get("from_node", "")))
        tn = remap.get(str(edge.get("to_node", "")), str(edge.get("to_node", "")))
        if fn and tn and fn == tn:
            continue

        new_edge = dict(edge)
        new_edge["from_node"] = fn
        new_edge["to_node"] = tn
        new_edge["collapsed_from_conflict"] = False
        coords = [list(pt) for pt in (edge.get("geometry_coords") or [])]
        if coords and fn in merged_node_coords:
            coords[0] = list(merged_node_coords[fn])
        if coords and tn in merged_node_coords:
            coords[-1] = list(merged_node_coords[tn])
        new_edge["geometry_coords"] = coords
        new_edge["length_m"] = round(_edge_length_m(coords), 3)
        out_edges.append(new_edge)

    return {
        "edges": out_edges,
        "collapsed_conflict_edges": len(collapsed_edge_ids),
        "collapsed_node_groups": len(collapsed_groups),
    }


ENABLE_CONFLICT_COLLAPSE = True  # collapse short edges that would be over-trimmed


def build_road_graph(geojson_path: Path, output_json_path: Path, origin_lon: float, origin_lat: float) -> dict[str, Any]:
    """从清洗后的 GeoJSON 提取完整的图结构并保存"""
    with open(geojson_path, encoding="utf-8") as f:
        fc = json.load(f)

    proj = vc_geo.LocalProjector(origin_lon, origin_lat)
    features = fc.get("features", [])

    edges_list = []
    MIN_EDGE_LENGTH_M = 0.2  # 过滤极短的边（< 20cm），防止 Houdini 细碎片

    # 1. 建立 Edges 列表，并预收集 Nodes 坐标
    for idx, feat in enumerate(features):
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})
        
        if geom.get("type") != "LineString":
            continue

        wgs84_coords = geom.get("coordinates", [])
        if len(wgs84_coords) < 2:
            continue

        # 投影到局部坐标
        local_coords = []
        for lon, lat in wgs84_coords:
            x, z = proj.to_local(lon, lat)
            local_coords.append([round(x, 4), round(z, 4), 0.0])  # y 默认 0.0

        edge_length = _edge_length_m(local_coords)
        # 过滤极短的边
        if edge_length < MIN_EDGE_LENGTH_M:
            continue

        edge_id = f"edge_{props.get('seg_id', idx + 1)}"
        from_node = str(props.get("from_node", ""))
        to_node = str(props.get("to_node", ""))
        highway = props.get("highway", "residential")
        lanes = int(props.get("lanes", 0))
        width = float(props.get("width", 0.0))
        width_m = _effective_width_m(str(highway), width, lanes)

        edge_item = {
            "id": edge_id,
            "from_node": from_node,
            "to_node": to_node,
            "class": highway,
            "lanes": lanes,
            "width": width,
            "width_m": round(width_m, 3),
            "half_width_m": round(width_m * 0.5, 3),
            "oneway": props.get("oneway", "no"),
            "bridge": props.get("bridge", "no"),
            "tunnel": props.get("tunnel", "no"),
            "layer": int(props.get("layer", 0)),
            "geometry_coords": local_coords,
            "length_m": round(edge_length, 3),
        }
        edges_list.append(edge_item)

    nodes_list = _nodes_from_edges(edges_list)
    pre_collapse_qa = _annotate_junction_conflicts(nodes_list, edges_list)

    total_collapsed_edges = 0
    total_collapsed_groups = 0
    collapse_iterations = 0
    post_collapse_qa = pre_collapse_qa

    if ENABLE_CONFLICT_COLLAPSE:
        for _ in range(8):
            collapse_result = _collapse_conflicting_short_edges(nodes_list, edges_list)
            if collapse_result["collapsed_conflict_edges"] <= 0:
                break
            edges_list = collapse_result["edges"]
            total_collapsed_edges += collapse_result["collapsed_conflict_edges"]
            total_collapsed_groups += collapse_result["collapsed_node_groups"]
            collapse_iterations += 1
            nodes_list = _nodes_from_edges(edges_list)
            post_collapse_qa = _annotate_junction_conflicts(nodes_list, edges_list)
        else:
            post_collapse_qa = _annotate_junction_conflicts(nodes_list, edges_list)

    post_collapse_qa = {
        **post_collapse_qa,
        "short_conflict_edges_precollapse": pre_collapse_qa.get("short_conflict_edges", 0),
        "max_conflict_ratio_precollapse": pre_collapse_qa.get("max_conflict_ratio", 0.0),
        "collapsed_conflict_edges": total_collapsed_edges,
        "collapsed_node_groups": total_collapsed_groups,
        "collapse_iterations": collapse_iterations,
        "conflict_collapse_enabled": ENABLE_CONFLICT_COLLAPSE,
    }

    graph_data = {
        "schema_version": "v1_2026_06_02_graph_collapse",
        "origin_lon": origin_lon,
        "origin_lat": origin_lat,
        "nodes": nodes_list,
        "edges": edges_list,
        "qa": {
            **post_collapse_qa,
        },
    }

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_json_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(graph_data, f, ensure_ascii=False, indent=2)
    print(f"  [Road Graph] 写入拓扑数据库: {vc_paths.project_relative(output_json_path)} (Nodes: {len(nodes_list)}, Edges: {len(edges_list)})")

    return graph_data


if __name__ == "__main__":
    # 允许独立测试
    cfg = vc_paths.load_active_area(absolute=True)
    area_id = cfg["area_id"]
    cl_dir = vc_paths.CLEANED / area_id
    geojson_path = cl_dir / "roads_clean.geojson"
    out_json = cl_dir / "road_graph.json"
    if geojson_path.exists():
        build_road_graph(geojson_path, out_json, cfg["origin_lon"], cfg["origin_lat"])
    else:
        print(f"  ❌ 未找到 {geojson_path.name}，请先运行 refine_data.py")
