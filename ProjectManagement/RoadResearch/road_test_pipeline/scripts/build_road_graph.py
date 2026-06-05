#!/usr/bin/env python3
"""Build a stable road_graph.json from canonical or repaired road edges."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


WIDTH_DEFAULTS = {
    "motorway": 28.0,
    "trunk": 22.0,
    "primary": 16.0,
    "secondary": 12.0,
    "tertiary": 9.0,
    "residential": 6.0,
    "unclassified": 6.0,
    "service": 4.0,
    "living_street": 4.0,
}

LANE_DEFAULTS = {
    "motorway": 4,
    "trunk": 3,
    "primary": 2,
    "secondary": 2,
    "tertiary": 2,
    "residential": 2,
    "unclassified": 2,
    "service": 1,
    "living_street": 1,
}

NODE_EPS_M = 0.35
BBOX_EDGE_MARGIN_M = 5.0


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def local_projector_from_metadata(fc: dict[str, Any]) -> tuple[float, float]:
    meta = fc.get("metadata") or {}
    origin_lon = meta.get("origin_lon")
    origin_lat = meta.get("origin_lat")
    if origin_lon is not None and origin_lat is not None:
        return float(origin_lon), float(origin_lat)

    bbox = meta.get("bbox_swen")
    if bbox and len(bbox) == 4:
        south, west, north, east = [float(v) for v in bbox]
        return (west + east) * 0.5, (south + north) * 0.5

    coords = []
    for feat in fc.get("features", []):
        geom = feat.get("geometry") or {}
        if geom.get("type") == "LineString":
            coords.extend(geom.get("coordinates") or [])
    if not coords:
        return 0.0, 0.0
    lon = sum(float(c[0]) for c in coords) / len(coords)
    lat = sum(float(c[1]) for c in coords) / len(coords)
    return lon, lat


def to_local(lon: float, lat: float, origin_lon: float, origin_lat: float) -> tuple[float, float]:
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(origin_lat))
    return (lon - origin_lon) * m_per_deg_lon, (lat - origin_lat) * m_per_deg_lat


def to_lonlat(x: float, z: float, origin_lon: float, origin_lat: float) -> tuple[float, float]:
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(origin_lat))
    return origin_lon + x / m_per_deg_lon, origin_lat + z / m_per_deg_lat


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = a[0] - b[0]
    dz = a[1] - b[1]
    return math.sqrt(dx * dx + dz * dz)


def polyline_length(points: list[tuple[float, float]]) -> float:
    return sum(distance(points[i], points[i + 1]) for i in range(len(points) - 1))


def node_key(point: tuple[float, float], eps: float = NODE_EPS_M) -> tuple[int, int]:
    return round(point[0] / eps), round(point[1] / eps)


def parse_lanes(value: Any, highway: str) -> tuple[int, str]:
    try:
        text = str(value or "").split(";")[0].split("|")[0].strip()
        if text:
            lanes = int(float(text))
            if lanes > 0:
                return lanes, "tag"
    except Exception:
        pass
    return LANE_DEFAULTS.get(highway, 1), "default"


def parse_width(value: Any, highway: str, lanes: int) -> tuple[float, str]:
    try:
        text = str(value or "").lower().replace("meters", "").replace("meter", "").replace("m", "").strip()
        if text:
            width = float(text)
            if width > 0:
                return width, "tag"
    except Exception:
        pass
    return WIDTH_DEFAULTS.get(highway, max(4.0, lanes * 3.2)), "default"


def parse_oneway(value: Any) -> tuple[bool, str]:
    text = str(value or "").strip().lower()
    if text in {"yes", "true", "1"}:
        return True, "forward"
    if text == "-1":
        return True, "reverse"
    if text in {"no", "false", "0"}:
        return False, "bidirectional"
    return False, "unknown"


def feature_points(feat: dict[str, Any], origin_lon: float, origin_lat: float) -> list[tuple[float, float]]:
    geom = feat.get("geometry") or {}
    if geom.get("type") != "LineString":
        return []
    points = []
    for coord in geom.get("coordinates") or []:
        if len(coord) < 2:
            continue
        points.append(to_local(float(coord[0]), float(coord[1]), origin_lon, origin_lat))
    return points


def local_bbox_from_metadata(
    fc: dict[str, Any],
    origin_lon: float,
    origin_lat: float,
) -> tuple[float, float, float, float] | None:
    bbox = (fc.get("metadata") or {}).get("bbox_swen")
    if not bbox or len(bbox) != 4:
        return None
    south, west, north, east = [float(v) for v in bbox]
    west_x, south_z = to_local(west, south, origin_lon, origin_lat)
    east_x, north_z = to_local(east, north, origin_lon, origin_lat)
    return (
        min(west_x, east_x),
        min(south_z, north_z),
        max(west_x, east_x),
        max(south_z, north_z),
    )


def is_near_bbox_edge(
    point: tuple[float, float],
    bbox: tuple[float, float, float, float] | None,
    margin_m: float = BBOX_EDGE_MARGIN_M,
) -> bool:
    if bbox is None:
        return False
    min_x, min_z, max_x, max_z = bbox
    x, z = point
    if x < min_x - margin_m or x > max_x + margin_m or z < min_z - margin_m or z > max_z + margin_m:
        return False
    return (
        abs(x - min_x) <= margin_m
        or abs(x - max_x) <= margin_m
        or abs(z - min_z) <= margin_m
        or abs(z - max_z) <= margin_m
    )


def node_kind(degree: int, is_bbox_boundary: bool) -> str:
    if degree >= 3:
        return "junction"
    if degree == 2:
        return "connector"
    if is_bbox_boundary:
        return "boundary"
    return "dead_end"


def build_graph(input_path: Path, output_path: Path, report_path: Path, area_id: str) -> dict[str, Any]:
    fc = read_json(input_path)
    origin_lon, origin_lat = local_projector_from_metadata(fc)
    local_bbox = local_bbox_from_metadata(fc, origin_lon, origin_lat)

    node_points: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
    raw_edges: list[dict[str, Any]] = []
    skipped_empty_geometry = 0
    zero_length_edges = 0
    closed_loop_edges_split = 0

    for index, feat in enumerate(fc.get("features", [])):
        props = feat.get("properties") or {}
        points = feature_points(feat, origin_lon, origin_lat)
        if len(points) < 2:
            skipped_empty_geometry += 1
            continue

        highway = str(props.get("highway") or "unknown")
        lanes, lanes_source = parse_lanes(props.get("lanes"), highway)
        width_m, width_source = parse_width(props.get("width_m"), highway, lanes)
        oneway, oneway_direction = parse_oneway(props.get("oneway"))
        base_source_feature_id = str(props.get("source_feature_id") or index)

        point_parts: list[tuple[list[tuple[float, float]], str]] = [(points, "")]
        if node_key(points[0]) == node_key(points[-1]) and len(points) > 2:
            split_index = max(range(1, len(points) - 1), key=lambda i: distance(points[0], points[i]))
            part_a = points[: split_index + 1]
            part_b = points[split_index:]
            if len(part_a) >= 2 and len(part_b) >= 2:
                point_parts = [(part_a, "closed_loop_a"), (part_b, "closed_loop_b")]
                closed_loop_edges_split += 1

        for part_points, loop_role in point_parts:
            length_m = polyline_length(part_points)
            if length_m <= 0.05:
                zero_length_edges += 1
                continue

            start_key = node_key(part_points[0])
            end_key = node_key(part_points[-1])
            node_points[start_key].append(part_points[0])
            node_points[end_key].append(part_points[-1])
            source_feature_id = (
                f"{base_source_feature_id}_{loop_role}" if loop_role else base_source_feature_id
            )

            raw_edges.append({
                "index": index,
                "start_key": start_key,
                "end_key": end_key,
                "points": part_points,
                "length_m": length_m,
                "source_feature_id": source_feature_id,
                "closed_loop_split_role": loop_role,
                "closed_loop_source_feature_id": base_source_feature_id if loop_role else "",
                "canonical_road_id": str(props.get("canonical_road_id") or ""),
                "road_chain_id": str(props.get("road_chain_id") or ""),
                "road_chain_source_ids": props.get("road_chain_source_ids") or [],
                "road_chain_fragment_index": props.get("road_chain_fragment_index", ""),
                "road_chain_fragment_count": props.get("road_chain_fragment_count", ""),
                "road_chain_role": props.get("road_chain_role", ""),
                "source_feature_ids": props.get("source_feature_ids") or [],
                "repaired_source_feature_ids": props.get("repaired_source_feature_ids") or [],
                "repair_parent_ids": props.get("repair_parent_ids") or [],
                "repair_parent_id": props.get("repair_parent_id", ""),
                "repair_edge_id": props.get("repair_edge_id", ""),
                "repair_edge_ids": props.get("repair_edge_ids") or [],
                "canonical_edge_count": props.get("canonical_edge_count", ""),
                "canonical_ops": props.get("canonical_ops") or [],
                "attribute_conflicts": props.get("attribute_conflicts") or {},
                "highway": highway,
                "road_class": str(props.get("road_class") or highway),
                "name": props.get("name", ""),
                "lanes": lanes,
                "lanes_source": lanes_source,
                "width_m": width_m,
                "width_source": width_source,
                "oneway": oneway,
                "oneway_direction": oneway_direction,
                "source_provider": props.get("source_provider", ""),
                "provider_tags": props.get("provider_tags") or {},
            })

    node_ids: dict[tuple[int, int], str] = {}
    nodes: list[dict[str, Any]] = []
    incident_edges_by_node: dict[tuple[int, int], list[str]] = defaultdict(list)

    for i, key in enumerate(sorted(node_points.keys())):
        node_ids[key] = f"n_{i:04d}"

    edges: list[dict[str, Any]] = []
    for i, raw in enumerate(raw_edges):
        edge_id = f"e_{i:04d}"
        from_node = node_ids[raw["start_key"]]
        to_node = node_ids[raw["end_key"]]
        incident_edges_by_node[raw["start_key"]].append(edge_id)
        incident_edges_by_node[raw["end_key"]].append(edge_id)

        geometry_lonlat = [
            [round(lon, 8), round(lat, 8)]
            for lon, lat in (to_lonlat(x, z, origin_lon, origin_lat) for x, z in raw["points"])
        ]
        edges.append({
            "edge_id": edge_id,
            "from_node": from_node,
            "to_node": to_node,
            "source_feature_id": raw["source_feature_id"],
            "closed_loop_split_role": raw["closed_loop_split_role"],
            "closed_loop_source_feature_id": raw["closed_loop_source_feature_id"],
            "canonical_road_id": raw["canonical_road_id"],
            "road_chain_id": raw["road_chain_id"],
            "road_chain_source_ids": raw["road_chain_source_ids"],
            "road_chain_fragment_index": raw["road_chain_fragment_index"],
            "road_chain_fragment_count": raw["road_chain_fragment_count"],
            "road_chain_role": raw["road_chain_role"],
            "source_feature_ids": raw["source_feature_ids"],
            "repaired_source_feature_ids": raw["repaired_source_feature_ids"],
            "repair_parent_ids": raw["repair_parent_ids"],
            "repair_parent_id": raw["repair_parent_id"],
            "repair_edge_id": raw["repair_edge_id"],
            "repair_edge_ids": raw["repair_edge_ids"],
            "canonical_edge_count": raw["canonical_edge_count"],
            "canonical_ops": raw["canonical_ops"],
            "attribute_conflicts": raw["attribute_conflicts"],
            "source_provider": raw["source_provider"],
            "road_class": raw["road_class"],
            "highway": raw["highway"],
            "name": raw["name"],
            "lanes": raw["lanes"],
            "lanes_source": raw["lanes_source"],
            "width_m": round(raw["width_m"], 3),
            "width_source": raw["width_source"],
            "half_width_m": round(raw["width_m"] * 0.5, 3),
            "oneway": raw["oneway"],
            "oneway_direction": raw["oneway_direction"],
            "length_m": round(raw["length_m"], 3),
            "geometry_xz": [[round(x, 3), round(z, 3)] for x, z in raw["points"]],
            "geometry_lonlat": geometry_lonlat,
            "provider_tags": raw["provider_tags"],
        })

    for key in sorted(node_points.keys()):
        points = node_points[key]
        x = sum(p[0] for p in points) / len(points)
        z = sum(p[1] for p in points) / len(points)
        lon, lat = to_lonlat(x, z, origin_lon, origin_lat)
        incident_edges = sorted(incident_edges_by_node[key])
        degree = len(incident_edges)
        is_boundary = is_near_bbox_edge((x, z), local_bbox)
        nodes.append({
            "node_id": node_ids[key],
            "x": round(x, 3),
            "z": round(z, 3),
            "lon": round(lon, 8),
            "lat": round(lat, 8),
            "degree": degree,
            "kind": node_kind(degree, is_boundary),
            "is_bbox_boundary": is_boundary,
            "incident_edges": incident_edges,
        })

    node_kind_counts = Counter(node["kind"] for node in nodes)
    degree_counts = Counter(str(node["degree"]) for node in nodes)
    highway_counts = Counter(edge["highway"] for edge in edges)
    lanes_source_counts = Counter(edge["lanes_source"] for edge in edges)
    width_source_counts = Counter(edge["width_source"] for edge in edges)

    orphan_edges = sum(1 for edge in edges if edge["from_node"] == edge["to_node"])
    graph = {
        "type": "road_graph",
        "metadata": {
            "area_id": area_id,
            "schema": "road_test_pipeline.road_graph.v1",
            "coord_domain": "local_xz_m",
            "axes": "x east, z north",
            "source": str(input_path),
            "origin_lon": origin_lon,
            "origin_lat": origin_lat,
            "node_eps_m": NODE_EPS_M,
            "bbox_edge_margin_m": BBOX_EDGE_MARGIN_M,
        },
        "nodes": nodes,
        "edges": edges,
    }
    write_json(output_path, graph)

    node_count = len(nodes)
    edge_count = len(edges)
    report = {
        "area_id": area_id,
        "stage": "road_graph_v1",
        "input": str(input_path),
        "output": str(output_path),
        "counts": {
            "input_features": len(fc.get("features", [])),
            "nodes": node_count,
            "edges": edge_count,
            "skipped_empty_geometry": skipped_empty_geometry,
            "zero_length_edges": zero_length_edges,
            "closed_loop_edges_split": closed_loop_edges_split,
            "orphan_edges": orphan_edges,
        },
        "node_kind_counts": dict(sorted(node_kind_counts.items())),
        "node_degree_counts": dict(sorted(degree_counts.items(), key=lambda item: int(item[0]))),
        "edge_highway_counts": dict(highway_counts.most_common()),
        "lanes_source_counts": dict(sorted(lanes_source_counts.items())),
        "width_source_counts": dict(sorted(width_source_counts.items())),
        "metrics": {
            "dead_end_ratio": round(node_kind_counts.get("dead_end", 0) / max(1, node_count), 3),
            "boundary_ratio": round(node_kind_counts.get("boundary", 0) / max(1, node_count), 3),
            "junction_ratio": round(node_kind_counts.get("junction", 0) / max(1, node_count), 3),
            "width_fallback_ratio": round(width_source_counts.get("default", 0) / max(1, edge_count), 3),
            "lanes_fallback_ratio": round(lanes_source_counts.get("default", 0) / max(1, edge_count), 3),
            "total_length_m": round(sum(edge["length_m"] for edge in edges), 3),
        },
        "notes": [
            "Road graph is built from repaired simple edges and keeps source OSM tags for traceability.",
            "Node kinds are boundary-aware so bbox exits are not treated as internal dead ends.",
            "Width and lanes fall back to road class defaults when OSM tags are missing.",
        ],
    }
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build road_graph.json from canonical or repaired roads.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--input", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    processed = root / "data" / "processed"
    canonical_path = processed / f"{args.area_id}_roads_canonical.geojson"
    repaired_path = processed / f"{args.area_id}_roads_repaired.geojson"
    input_path = Path(args.input) if args.input else canonical_path if canonical_path.exists() else repaired_path
    output_path = Path(args.output) if args.output else root / "data" / "processed" / f"{args.area_id}_road_graph.json"
    report_path = Path(args.report) if args.report else root / "reports" / f"{args.area_id}_road_graph_report.json"

    report = build_graph(input_path, output_path, report_path, args.area_id)
    print(json.dumps({
        "area_id": args.area_id,
        "output": str(output_path),
        "report": str(report_path),
        "counts": report["counts"],
        "node_kind_counts": report["node_kind_counts"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
