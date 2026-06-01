"""
VirtualCity — Road Graph 拓扑图生成器 (Milestone 1 - Stage 2)
=============================================================
从 roads_clean.geojson 提取并规范化 Nodes 与 Edges，输出标准的 road_graph.json：
- Nodes: 包含 id, 局部坐标 (x, z, y), 连接的 edges 列表, 度数 (degree)。
- Edges: 包含 id, from/to 节点, 道路等级, 宽度, 车道数, 局部坐标坐标点列 (geometry_coords)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from collections import defaultdict

# 注入本地路径
sys.path.insert(0, str(Path(__file__).parent))
import vc_paths
import vc_geo


def build_road_graph(geojson_path: Path, output_json_path: Path, origin_lon: float, origin_lat: float) -> dict[str, Any]:
    """从清洗后的 GeoJSON 提取完整的图结构并保存"""
    with open(geojson_path, encoding="utf-8") as f:
        fc = json.load(f)

    proj = vc_geo.LocalProjector(origin_lon, origin_lat)
    features = fc.get("features", [])

    nodes_dict = {}  # node_id -> {id, x, z, y, connected_edges}
    edges_list = []

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

        edge_id = f"edge_{props.get('seg_id', idx + 1)}"
        from_node = str(props.get("from_node", ""))
        to_node = str(props.get("to_node", ""))

        edge_item = {
            "id": edge_id,
            "from_node": from_node,
            "to_node": to_node,
            "class": props.get("highway", "residential"),
            "lanes": int(props.get("lanes", 0)),
            "width": float(props.get("width", 0.0)),
            "oneway": props.get("oneway", "no"),
            "bridge": props.get("bridge", "no"),
            "tunnel": props.get("tunnel", "no"),
            "layer": int(props.get("layer", 0)),
            "geometry_coords": local_coords,
        }
        edges_list.append(edge_item)

        # 记录首尾节点的局部坐标
        start_pt = local_coords[0]
        end_pt = local_coords[-1]

        for nid, pt in [(from_node, start_pt), (to_node, end_pt)]:
            if not nid:
                continue
            if nid not in nodes_dict:
                nodes_dict[nid] = {
                    "id": nid,
                    "x": pt[0],
                    "z": pt[1],
                    "y": pt[2],
                    "elevation_source": "pending",
                    "connected_edges": [],
                }

    # 2. 统计节点度数与连接的 Edges
    for edge in edges_list:
        eid = edge["id"]
        fn = edge["from_node"]
        tn = edge["to_node"]
        if fn in nodes_dict:
            nodes_dict[fn]["connected_edges"].append(eid)
        if tn in nodes_dict:
            nodes_dict[tn]["connected_edges"].append(eid)

    # 补全 degree
    nodes_list = []
    for nid, node in sorted(nodes_dict.items()):
        node["degree"] = len(node["connected_edges"])
        nodes_list.append(node)

    graph_data = {
        "schema_version": "v1_2026_06_02",
        "origin_lon": origin_lon,
        "origin_lat": origin_lat,
        "nodes": nodes_list,
        "edges": edges_list,
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
