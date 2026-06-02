#!/usr/bin/env python3
"""Build lane_graph.json and OpenDRIVE-inspired junction connections.

This is the lane-level topology step described in the RoadResearch notes. It
consumes junction_semantics.json, emits lane centerlines, connection records,
laneLinks and tangent-continuous connector curves. It deliberately does not
generate junction surfaces; that stays in the later geometry layer.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_LANE_WIDTH_M = 3.2
JUNCTION_TRIM_M = 8.0
CURVE_SAMPLE_COUNT = 9
SURFACE_STRATEGY_PENDING = "not_generated_layer3_lane_graph_only"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = a[0] - b[0]
    dz = a[1] - b[1]
    return math.sqrt(dx * dx + dz * dz)


def polyline_length(points: list[tuple[float, float]]) -> float:
    return sum(distance(points[i], points[i + 1]) for i in range(len(points) - 1))


def resolve_trim_distances(
    length: float,
    trim_start_m: float,
    trim_end_m: float,
    locked_start_m: float = 0.0,
    locked_end_m: float = 0.0,
) -> tuple[float, float]:
    trim_start_m = max(0.0, trim_start_m)
    trim_end_m = max(0.0, trim_end_m)
    locked_start_m = min(max(0.0, locked_start_m), trim_start_m)
    locked_end_m = min(max(0.0, locked_end_m), trim_end_m)
    trim_total = trim_start_m + trim_end_m
    max_trim_total = max(0.0, length - 0.5)
    if trim_total > max_trim_total and trim_total > 0.0:
        locked_total = locked_start_m + locked_end_m
        if locked_total >= max_trim_total and locked_total > 0.0:
            scale = max_trim_total / locked_total
            return locked_start_m * scale, locked_end_m * scale
        remaining = max_trim_total - locked_total
        start_extra = trim_start_m - locked_start_m
        end_extra = trim_end_m - locked_end_m
        extra_total = start_extra + end_extra
        if extra_total <= 0.0:
            return locked_start_m, locked_end_m
        scale = remaining / extra_total
        return locked_start_m + start_extra * scale, locked_end_m + end_extra * scale
    return trim_start_m, trim_end_m


def point_at_distance(points: list[tuple[float, float]], distance_m: float) -> tuple[float, float]:
    if not points:
        return 0.0, 0.0
    if distance_m <= 0.0:
        return points[0]
    remaining = distance_m
    for i in range(len(points) - 1):
        seg_len = distance(points[i], points[i + 1])
        if seg_len <= 1e-9:
            continue
        if remaining <= seg_len:
            t = remaining / seg_len
            return (
                points[i][0] + (points[i + 1][0] - points[i][0]) * t,
                points[i][1] + (points[i + 1][1] - points[i][1]) * t,
            )
        remaining -= seg_len
    return points[-1]


def tangent_at_distance(points: list[tuple[float, float]], distance_m: float) -> tuple[float, float]:
    if len(points) < 2:
        return 0.0, 0.0
    remaining = max(0.0, distance_m)
    fallback = (0.0, 0.0)
    for i in range(len(points) - 1):
        segment = (points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
        seg_len = math.sqrt(segment[0] * segment[0] + segment[1] * segment[1])
        if seg_len <= 1e-9:
            continue
        fallback = segment[0] / seg_len, segment[1] / seg_len
        if remaining <= seg_len:
            return fallback
        remaining -= seg_len
    return fallback


def trimmed_endpoint_and_tangent(
    points: list[tuple[float, float]],
    side: str,
    trim_start_m: float,
    trim_end_m: float,
    locked_start_m: float = 0.0,
    locked_end_m: float = 0.0,
) -> tuple[tuple[float, float], tuple[float, float]]:
    length = polyline_length(points)
    if length <= 1e-9:
        return points[0], (0.0, 0.0)
    trim_start_m, trim_end_m = resolve_trim_distances(
        length,
        trim_start_m,
        trim_end_m,
        locked_start_m,
        locked_end_m,
    )
    station = trim_start_m if side == "start" else max(0.0, length - trim_end_m)
    return point_at_distance(points, station), tangent_at_distance(points, station)


def station_factors(points: list[tuple[float, float]]) -> list[float]:
    if len(points) < 2:
        return [0.0 for _point in points]
    distances = [0.0]
    for i in range(len(points) - 1):
        distances.append(distances[-1] + distance(points[i], points[i + 1]))
    total = distances[-1]
    if total <= 1e-9:
        return [0.0 for _point in points]
    return [value / total for value in distances]


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def normalize(v: tuple[float, float]) -> tuple[float, float]:
    length = math.sqrt(v[0] * v[0] + v[1] * v[1])
    if length <= 1e-9:
        return 0.0, 0.0
    return v[0] / length, v[1] / length


def rotate90(v: tuple[float, float]) -> tuple[float, float]:
    return -v[1], v[0]


def lonlat_to_xz(lon: float, lat: float, origin_lon: float, origin_lat: float) -> tuple[float, float]:
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(origin_lat))
    return (lon - origin_lon) * m_per_deg_lon, (lat - origin_lat) * m_per_deg_lat


def dot(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1]


def cross(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[1] - a[1] * b[0]


def edge_points(edge: dict[str, Any]) -> list[tuple[float, float]]:
    return [(float(p[0]), float(p[1])) for p in edge["geometry_xz"]]


def geojson_feature_points_xz(feature: dict[str, Any], metadata: dict[str, Any]) -> list[tuple[float, float]]:
    geom = feature.get("geometry") or {}
    if geom.get("type") != "LineString":
        return []
    coords = geom.get("coordinates") or []
    coord_domain = str(metadata.get("coord_domain") or "WGS84")
    if coord_domain == "local_xz_m":
        return [(float(point[0]), float(point[1])) for point in coords]
    origin_lon = float(metadata["origin_lon"])
    origin_lat = float(metadata["origin_lat"])
    return [lonlat_to_xz(float(point[0]), float(point[1]), origin_lon, origin_lat) for point in coords]


def load_optimized_centerline_refs(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {
            "path": "",
            "approaches_by_edge": {},
            "corner_fillets": [],
            "junction_connectors": [],
        }
    fc = read_json(path)
    metadata = fc.get("metadata", {})
    approaches_by_edge: dict[str, list[tuple[float, float]]] = {}
    corner_fillets: list[dict[str, Any]] = []
    for feature in fc.get("features", []):
        props = feature.get("properties") or {}
        part = str(props.get("vc_part") or "")
        points = geojson_feature_points_xz(feature, metadata)
        if len(points) < 2:
            continue
        if part == "optimized_approach_centerline":
            edge_id = str(props.get("source_edge_id") or "")
            if edge_id:
                approaches_by_edge[edge_id] = points
        elif part == "optimized_corner_fillet":
            corner_fillets.append({
                "corner_node_id": str(props.get("corner_node_id") or ""),
                "corner_id": str(props.get("corner_id") or ""),
                "from_edge_id": str(props.get("from_edge_id") or ""),
                "to_edge_id": str(props.get("to_edge_id") or ""),
                "points": points,
                "cut_m": float(props.get("cut_m") or 0.0),
                "turn_angle_deg": float(props.get("turn_angle_deg") or 0.0),
            })
    return {
        "path": str(path),
        "approaches_by_edge": approaches_by_edge,
        "corner_fillets": corner_fillets,
        "junction_connectors": [
            {
                "junction_node_id": str((feature.get("properties") or {}).get("junction_node_id") or ""),
                "connector_id": str((feature.get("properties") or {}).get("connector_id") or ""),
                "connector_kind": str((feature.get("properties") or {}).get("connector_kind") or ""),
                "from_edge_id": str((feature.get("properties") or {}).get("from_edge_id") or ""),
                "to_edge_id": str((feature.get("properties") or {}).get("to_edge_id") or ""),
                "points": geojson_feature_points_xz(feature, metadata),
            }
            for feature in fc.get("features", [])
            if str((feature.get("properties") or {}).get("vc_part") or "") == "optimized_junction_connector"
            and len(geojson_feature_points_xz(feature, metadata)) >= 2
        ],
    }


def edges_with_optimized_approaches(
    edges: list[dict[str, Any]],
    approaches_by_edge: dict[str, list[tuple[float, float]]],
) -> tuple[list[dict[str, Any]], int]:
    updated: list[dict[str, Any]] = []
    replaced = 0
    for edge in edges:
        item = dict(edge)
        points = approaches_by_edge.get(str(edge.get("edge_id") or ""))
        if points and len(points) >= 2:
            item["geometry_xz"] = [[round(x, 3), round(z, 3)] for x, z in points]
            item["centerline_geometry_source"] = "optimized_approach_centerline"
            item["approach_centerline_trimmed"] = True
            replaced += 1
        else:
            item["centerline_geometry_source"] = "road_graph"
            item["approach_centerline_trimmed"] = False
        updated.append(item)
    return updated, replaced


def junction_connector_key(node_id: str, edge_a: str, edge_b: str) -> tuple[str, tuple[str, str]]:
    return node_id, tuple(sorted((edge_a, edge_b)))


def index_junction_connectors(connectors: list[dict[str, Any]]) -> dict[tuple[str, tuple[str, str]], dict[str, Any]]:
    indexed: dict[tuple[str, tuple[str, str]], dict[str, Any]] = {}
    for connector in connectors:
        node_id = str(connector.get("junction_node_id") or "")
        edge_a = str(connector.get("from_edge_id") or "")
        edge_b = str(connector.get("to_edge_id") or "")
        points = connector.get("points") or []
        if not node_id or not edge_a or not edge_b or len(points) < 2:
            continue
        indexed.setdefault(junction_connector_key(node_id, edge_a, edge_b), connector)
    return indexed


def offset_points(points: list[tuple[float, float]], offset: float) -> list[tuple[float, float]]:
    if len(points) < 2:
        return points
    return offset_points_profile(points, offset, offset)


def offset_points_profile(points: list[tuple[float, float]], offset_start: float, offset_end: float) -> list[tuple[float, float]]:
    if len(points) < 2:
        return points
    shifted: list[tuple[float, float]] = []
    factors = station_factors(points)
    for i, point in enumerate(points):
        if i == 0:
            d = normalize((points[1][0] - point[0], points[1][1] - point[1]))
        elif i == len(points) - 1:
            d = normalize((point[0] - points[i - 1][0], point[1] - points[i - 1][1]))
        else:
            d0 = normalize((point[0] - points[i - 1][0], point[1] - points[i - 1][1]))
            d1 = normalize((points[i + 1][0] - point[0], points[i + 1][1] - point[1]))
            d = normalize((d0[0] + d1[0], d0[1] + d1[1]))
            if d == (0.0, 0.0):
                d = d1
        n = rotate90(d)
        offset = lerp(offset_start, offset_end, factors[i])
        shifted.append((point[0] + n[0] * offset, point[1] + n[1] * offset))
    return shifted


def direction_out_of_node(edge: dict[str, Any], node_id: str) -> tuple[float, float]:
    pts = edge_points(edge)
    if node_id == edge["from_node"]:
        return normalize((pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]))
    return normalize((pts[-2][0] - pts[-1][0], pts[-2][1] - pts[-1][1]))


def lane_counts(edge: dict[str, Any]) -> tuple[int, int]:
    lanes = max(1, int(edge.get("lanes") or 1))
    if edge.get("oneway"):
        return lanes, 0
    forward = max(1, math.ceil(lanes / 2))
    backward = max(1, lanes - forward)
    return forward, backward


def lane_offset(index: int, count: int, side: int, lane_width_m: float) -> float:
    return side * ((index + 0.5) - count * 0.5) * lane_width_m


def edge_width_profile(edge: dict[str, Any], generated_lane_count: int) -> dict[str, Any]:
    lane_width = DEFAULT_LANE_WIDTH_M
    road_width = generated_lane_count * lane_width
    return {
        "road_width_m": road_width,
        "road_width_start_m": road_width,
        "road_width_end_m": road_width,
        "lane_width_m": lane_width,
        "lane_width_start_m": lane_width,
        "lane_width_end_m": lane_width,
        "width_source": "fixed_default",
        "width_confidence": 0.45,
    }


def normalize_turn_kind(turn: str) -> str:
    if turn in {"straight", "through", "through_candidate"}:
        return "through"
    if turn in {"left", "right"}:
        return turn
    return "unknown"


def build_lanes(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lanes: list[dict[str, Any]] = []
    for edge in edges:
        pts = edge_points(edge)
        forward_count, backward_count = lane_counts(edge)
        generated_lane_count = forward_count + backward_count
        width_profile = edge_width_profile(edge, generated_lane_count)
        lane_width = float(width_profile["lane_width_m"])
        lane_width_start = float(width_profile["lane_width_start_m"])
        lane_width_end = float(width_profile["lane_width_end_m"])
        for index in range(forward_count):
            offset = lane_offset(index, forward_count, -1, lane_width)
            offset_start = lane_offset(index, forward_count, -1, lane_width_start)
            offset_end = lane_offset(index, forward_count, -1, lane_width_end)
            lane_id = f"{edge['edge_id']}_f_{index + 1}"
            lanes.append({
                "lane_id": lane_id,
                "road_id": edge["edge_id"],
                "direction": "forward",
                "index": index + 1,
                "order_left_to_right": index + 1,
                "lateral_offset_m": round(offset, 3),
                "lateral_offset_start_m": round(offset_start, 3),
                "lateral_offset_end_m": round(offset_end, 3),
                "from_node": edge["from_node"],
                "to_node": edge["to_node"],
                "centerline_xz": [[round(x, 3), round(z, 3)] for x, z in offset_points_profile(pts, offset_start, offset_end)],
                "width_m": round(lane_width, 3),
                "width_start_m": round(float(width_profile["lane_width_start_m"]), 3),
                "width_end_m": round(float(width_profile["lane_width_end_m"]), 3),
                "road_width_m": round(float(width_profile["road_width_m"]), 3),
                "road_width_start_m": round(float(width_profile["road_width_start_m"]), 3),
                "road_width_end_m": round(float(width_profile["road_width_end_m"]), 3),
                "width_source": width_profile["width_source"],
                "width_confidence": round(float(width_profile["width_confidence"]), 3),
                "allowed_turns": ["left", "through", "right"],
                "source": edge.get("lanes_source", "unknown"),
                "centerline_source": edge.get("centerline_geometry_source", "road_graph"),
                "approach_centerline_trimmed": bool(edge.get("approach_centerline_trimmed")),
            })
        for index in range(backward_count):
            offset = lane_offset(index, backward_count, 1, lane_width)
            offset_start = lane_offset(index, backward_count, 1, lane_width_start)
            offset_end = lane_offset(index, backward_count, 1, lane_width_end)
            lane_id = f"{edge['edge_id']}_b_{index + 1}"
            reversed_pts = list(reversed(offset_points_profile(pts, offset_start, offset_end)))
            lanes.append({
                "lane_id": lane_id,
                "road_id": edge["edge_id"],
                "direction": "backward",
                "index": index + 1,
                "order_left_to_right": index + 1,
                "lateral_offset_m": round(offset, 3),
                "lateral_offset_start_m": round(offset_end, 3),
                "lateral_offset_end_m": round(offset_start, 3),
                "from_node": edge["to_node"],
                "to_node": edge["from_node"],
                "centerline_xz": [[round(x, 3), round(z, 3)] for x, z in reversed_pts],
                "width_m": round(lane_width, 3),
                "width_start_m": round(float(width_profile["lane_width_end_m"]), 3),
                "width_end_m": round(float(width_profile["lane_width_start_m"]), 3),
                "road_width_m": round(float(width_profile["road_width_m"]), 3),
                "road_width_start_m": round(float(width_profile["road_width_end_m"]), 3),
                "road_width_end_m": round(float(width_profile["road_width_start_m"]), 3),
                "width_source": width_profile["width_source"],
                "width_confidence": round(float(width_profile["width_confidence"]), 3),
                "allowed_turns": ["left", "through", "right"],
                "source": edge.get("lanes_source", "unknown"),
                "centerline_source": edge.get("centerline_geometry_source", "road_graph"),
                "approach_centerline_trimmed": bool(edge.get("approach_centerline_trimmed")),
            })
    return lanes


def classify_turn(in_dir: tuple[float, float], out_dir: tuple[float, float]) -> str:
    turn_cross = cross(in_dir, out_dir)
    turn_dot = dot(in_dir, out_dir)
    if turn_dot > 0.55:
        return "straight"
    if turn_cross > 0.0:
        return "left"
    return "right"


def trim_point(point: tuple[float, float], direction: tuple[float, float], trim_m: float) -> tuple[float, float]:
    return point[0] + direction[0] * trim_m, point[1] + direction[1] * trim_m


def curve_points(
    start: tuple[float, float],
    start_tangent: tuple[float, float],
    end: tuple[float, float],
    end_tangent: tuple[float, float],
    sample_count: int = CURVE_SAMPLE_COUNT,
) -> list[list[float]]:
    chord = distance(start, end)
    handle = min(chord * 0.45, JUNCTION_TRIM_M * 0.8)
    c1 = (start[0] + start_tangent[0] * handle, start[1] + start_tangent[1] * handle)
    c2 = (end[0] - end_tangent[0] * handle, end[1] - end_tangent[1] * handle)
    curve = []
    sample_count = max(2, sample_count)
    for i in range(sample_count):
        t = i / (sample_count - 1)
        u = 1.0 - t
        x = (
            u * u * u * start[0]
            + 3.0 * u * u * t * c1[0]
            + 3.0 * u * t * t * c2[0]
            + t * t * t * end[0]
        )
        z = (
            u * u * u * start[1]
            + 3.0 * u * u * t * c1[1]
            + 3.0 * u * t * t * c2[1]
            + t * t * t * end[1]
        )
        curve.append([round(x, 3), round(z, 3)])
    return curve


def select_lanes(lanes: list[dict[str, Any]], turn: str, incoming: bool) -> list[dict[str, Any]]:
    if not lanes:
        return []
    ordered = sorted(lanes, key=lambda lane: int(lane["index"]))
    normalized_turn = normalize_turn_kind(turn)
    if normalized_turn == "through":
        return ordered
    if normalized_turn == "left":
        return ordered[:1] if incoming else ordered[: max(1, min(1, len(ordered)))]
    if normalized_turn == "right":
        return ordered[-1:] if incoming else ordered[-1:]
    return ordered[:1]


def match_lane_links(from_lanes: list[dict[str, Any]], to_lanes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not from_lanes or not to_lanes:
        return []
    count = min(len(from_lanes), len(to_lanes))
    return [
        {
            "from_lane": from_lanes[i]["lane_id"],
            "to_lane": to_lanes[i]["lane_id"],
            "from_lane_index": from_lanes[i]["index"],
            "to_lane_index": to_lanes[i]["index"],
            "confidence": 0.45,
            "source": "geometry_inferred",
        }
        for i in range(count)
    ]


def oriented_connector_points(
    connector_ref: dict[str, Any],
    from_lane_endpoint: tuple[float, float],
    to_lane_endpoint: tuple[float, float],
) -> list[tuple[float, float]]:
    points = [(float(p[0]), float(p[1])) for p in connector_ref.get("points", [])]
    if len(points) < 2:
        return []
    forward_gap = distance(points[0], from_lane_endpoint) + distance(points[-1], to_lane_endpoint)
    reverse_gap = distance(points[-1], from_lane_endpoint) + distance(points[0], to_lane_endpoint)
    return points if forward_gap <= reverse_gap else list(reversed(points))


def lane_connection_curve(
    from_lane: dict[str, Any],
    to_lane: dict[str, Any],
    from_trim: dict[str, float] | None = None,
    to_trim: dict[str, float] | None = None,
) -> list[list[float]]:
    from_pts = [(float(p[0]), float(p[1])) for p in from_lane["centerline_xz"]]
    to_pts = [(float(p[0]), float(p[1])) for p in to_lane["centerline_xz"]]
    if len(from_pts) < 2 or len(to_pts) < 2:
        return []
    from_trim = from_trim or {"start": 0.0, "end": JUNCTION_TRIM_M}
    to_trim = to_trim or {"start": JUNCTION_TRIM_M, "end": 0.0}
    start, incoming_tangent = trimmed_endpoint_and_tangent(
        from_pts,
        "end",
        float(from_trim.get("start") or 0.0),
        float(from_trim.get("end") or 0.0),
        float(from_trim.get("locked_start") or 0.0),
        float(from_trim.get("locked_end") or 0.0),
    )
    end, outgoing_tangent = trimmed_endpoint_and_tangent(
        to_pts,
        "start",
        float(to_trim.get("start") or 0.0),
        float(to_trim.get("end") or 0.0),
        float(to_trim.get("locked_start") or 0.0),
        float(to_trim.get("locked_end") or 0.0),
    )
    return curve_points(start, incoming_tangent, end, outgoing_tangent)


def lane_connection_curve_from_connector(
    connector_ref: dict[str, Any],
    from_lane: dict[str, Any],
    to_lane: dict[str, Any],
) -> list[list[float]]:
    from_pts = [(float(p[0]), float(p[1])) for p in from_lane["centerline_xz"]]
    to_pts = [(float(p[0]), float(p[1])) for p in to_lane["centerline_xz"]]
    if len(from_pts) < 2 or len(to_pts) < 2:
        return []
    base_points = oriented_connector_points(connector_ref, from_pts[-1], to_pts[0])
    if len(base_points) < 2:
        return []
    start_offset = lane_endpoint_offset(from_lane, str(connector_ref.get("junction_node_id") or ""), "end")
    end_offset = lane_endpoint_offset(to_lane, str(connector_ref.get("junction_node_id") or ""), "start")
    curve = [
        [round(x, 3), round(z, 3)]
        for x, z in offset_points_profile(base_points, start_offset, end_offset)
    ]
    curve[0] = [round(from_pts[-1][0], 3), round(from_pts[-1][1], 3)]
    curve[-1] = [round(to_pts[0][0], 3), round(to_pts[0][1], 3)]
    return curve


def lane_link_endpoint_trim_metadata(
    curve: list[list[float]],
    from_lane: dict[str, Any],
    to_lane: dict[str, Any],
) -> dict[str, float]:
    if len(curve) < 2:
        return {
            "from_lane_trim_end_m": 0.0,
            "to_lane_trim_start_m": 0.0,
        }
    from_pts = [(float(p[0]), float(p[1])) for p in from_lane["centerline_xz"]]
    to_pts = [(float(p[0]), float(p[1])) for p in to_lane["centerline_xz"]]
    curve_start = (float(curve[0][0]), float(curve[0][1]))
    curve_end = (float(curve[-1][0]), float(curve[-1][1]))
    return {
        "from_lane_trim_end_m": round(distance(from_pts[-1], curve_start), 3),
        "to_lane_trim_start_m": round(distance(to_pts[0], curve_end), 3),
    }


def curve_stats(curve: list[list[float]]) -> dict[str, Any]:
    pts = [(float(p[0]), float(p[1])) for p in curve]
    return {
        "sample_count": len(curve),
        "length_m": round(polyline_length(pts), 3),
    }


def build_lane_link_records(
    from_lanes: list[dict[str, Any]],
    to_lanes: list[dict[str, Any]],
    movement: dict[str, Any],
    junction_id: str,
    connection_index: int,
    connector_ref: dict[str, Any] | None = None,
    approach_centerlines_trimmed: bool = False,
) -> list[dict[str, Any]]:
    lane_links = match_lane_links(from_lanes, to_lanes)
    confidence = float(movement.get("confidence", 0.45))
    for link_index, link in enumerate(lane_links):
        from_lane = next(lane for lane in from_lanes if lane["lane_id"] == link["from_lane"])
        to_lane = next(lane for lane in to_lanes if lane["lane_id"] == link["to_lane"])
        curve = lane_connection_curve_from_connector(connector_ref, from_lane, to_lane) if connector_ref else []
        if curve:
            curve_source = "optimized_junction_connector"
            connector_id = str(connector_ref.get("connector_id") or "")
            connector_kind = str(connector_ref.get("connector_kind") or "")
        else:
            no_trim = {"start": 0.0, "end": 0.0, "locked_start": 0.0, "locked_end": 0.0}
            curve = lane_connection_curve(
                from_lane,
                to_lane,
                no_trim if approach_centerlines_trimmed else None,
                no_trim if approach_centerlines_trimmed else None,
            )
            curve_source = "optimized_approach_endpoint_bezier" if approach_centerlines_trimmed else "junction_lane_endpoint_bezier"
            connector_id = ""
            connector_kind = ""
        stats = curve_stats(curve)
        trim_metadata = lane_link_endpoint_trim_metadata(curve, from_lane, to_lane)
        width_start = float(from_lane.get("width_end_m") or from_lane.get("width_m") or DEFAULT_LANE_WIDTH_M)
        width_end = float(to_lane.get("width_start_m") or to_lane.get("width_m") or DEFAULT_LANE_WIDTH_M)
        width_confidence = min(
            float(from_lane.get("width_confidence", 0.45)),
            float(to_lane.get("width_confidence", 0.45)),
        )
        link["lane_link_id"] = f"{junction_id}_c_{connection_index:03d}_ll_{link_index:02d}"
        link["confidence"] = round(confidence, 3)
        link["source"] = "junction_semantics"
        link["semantic_movement_id"] = movement["movement_id"]
        link["turn"] = movement["kind"]
        link["turn_normalized"] = normalize_turn_kind(str(movement["kind"]))
        link["curve_source"] = curve_source
        link["connector_id"] = connector_id
        link["connector_kind"] = connector_kind
        link["connecting_curve_xz"] = curve
        link["curve_length_m"] = stats["length_m"]
        link["curve_sample_count"] = stats["sample_count"]
        link["from_lane_trim_end_m"] = trim_metadata["from_lane_trim_end_m"]
        link["to_lane_trim_start_m"] = trim_metadata["to_lane_trim_start_m"]
        link["width_m"] = round((width_start + width_end) * 0.5, 3)
        link["width_start_m"] = round(width_start, 3)
        link["width_end_m"] = round(width_end, 3)
        link["from_lane_width_end_m"] = round(width_start, 3)
        link["to_lane_width_start_m"] = round(width_end, 3)
        link["width_source"] = "connected_lane_widths"
        link["width_confidence"] = round(width_confidence, 3)
    return lane_links


def lane_trim_distances(
    lane_graph: dict[str, Any],
    lane_links: list[dict[str, Any]],
    continuity_links: list[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    trim_m = float(lane_graph.get("metadata", {}).get("junction_trim_m") or JUNCTION_TRIM_M)
    lanes_by_id = {str(lane.get("lane_id") or ""): lane for lane in lane_graph.get("lanes", [])}
    trim_by_lane: dict[str, dict[str, float]] = {}

    def update(lane_id: str, side: str, value: float) -> None:
        if not lane_id or value <= 0.0:
            return
        item = trim_by_lane.setdefault(lane_id, {"start": 0.0, "end": 0.0, "locked_start": 0.0, "locked_end": 0.0})
        item[side] = max(item[side], value)

    def lock(lane_id: str, side: str, value: float) -> None:
        if not lane_id or value <= 0.0:
            return
        item = trim_by_lane.setdefault(lane_id, {"start": 0.0, "end": 0.0, "locked_start": 0.0, "locked_end": 0.0})
        item[side] = max(item[side], value)
        item[f"locked_{side}"] = max(item[f"locked_{side}"], value)

    def default_lane_link_trim(lane_id: str) -> float:
        lane = lanes_by_id.get(lane_id)
        if lane is not None and bool(lane.get("approach_centerline_trimmed")):
            return 0.0
        return trim_m

    def link_trim_value(link: dict[str, Any], key: str, default: float) -> float:
        if key not in link or link.get(key) is None:
            return default
        return max(0.0, float(link.get(key) or 0.0))

    for link in lane_links:
        from_lane_id = str(link.get("from_lane") or "")
        to_lane_id = str(link.get("to_lane") or "")
        update(from_lane_id, "end", link_trim_value(link, "from_lane_trim_end_m", default_lane_link_trim(from_lane_id)))
        update(to_lane_id, "start", link_trim_value(link, "to_lane_trim_start_m", default_lane_link_trim(to_lane_id)))

    for link in continuity_links:
        lock(str(link.get("from_lane") or ""), "end", float(link.get("from_lane_trim_end_m") or 0.0))
        lock(str(link.get("to_lane") or ""), "start", float(link.get("to_lane_trim_start_m") or 0.0))

    return trim_by_lane


def refresh_lane_link_curves(
    junctions: list[dict[str, Any]],
    lanes_by_id: dict[str, dict[str, Any]],
    trim_by_lane: dict[str, dict[str, float]],
) -> None:
    for junction in junctions:
        for connection in junction.get("connections", []):
            representative_curve: list[list[float]] = []
            for link in connection.get("lane_links", []):
                from_lane = lanes_by_id.get(str(link.get("from_lane") or ""))
                to_lane = lanes_by_id.get(str(link.get("to_lane") or ""))
                if from_lane is None or to_lane is None:
                    continue
                if str(link.get("curve_source") or "") in {"optimized_junction_connector", "optimized_approach_endpoint_bezier"}:
                    curve = link.get("connecting_curve_xz") or []
                else:
                    curve = lane_connection_curve(
                        from_lane,
                        to_lane,
                        trim_by_lane.get(str(from_lane.get("lane_id") or ""), {"start": 0.0, "end": JUNCTION_TRIM_M}),
                        trim_by_lane.get(str(to_lane.get("lane_id") or ""), {"start": JUNCTION_TRIM_M, "end": 0.0}),
                    )
                stats = curve_stats(curve)
                trim_metadata = lane_link_endpoint_trim_metadata(curve, from_lane, to_lane)
                link["connecting_curve_xz"] = curve
                link["curve_length_m"] = stats["length_m"]
                link["curve_sample_count"] = stats["sample_count"]
                link["from_lane_trim_end_m"] = trim_metadata["from_lane_trim_end_m"]
                link["to_lane_trim_start_m"] = trim_metadata["to_lane_trim_start_m"]
                if not representative_curve:
                    representative_curve = curve
            if representative_curve:
                connection["connecting_curve_xz"] = representative_curve
                connection["curve_length_m"] = curve_stats(representative_curve)["length_m"]


def lane_endpoint_offset(lane: dict[str, Any], node_id: str, role: str) -> float:
    if role == "end":
        return float(lane.get("lateral_offset_end_m") or lane.get("lateral_offset_m") or 0.0)
    if role == "start":
        return float(lane.get("lateral_offset_start_m") or lane.get("lateral_offset_m") or 0.0)
    if lane.get("to_node") == node_id:
        return float(lane.get("lateral_offset_end_m") or lane.get("lateral_offset_m") or 0.0)
    return float(lane.get("lateral_offset_start_m") or lane.get("lateral_offset_m") or 0.0)


def lane_endpoint_width(lane: dict[str, Any], node_id: str, role: str) -> float:
    if role == "end":
        return float(lane.get("width_end_m") or lane.get("width_m") or DEFAULT_LANE_WIDTH_M)
    if role == "start":
        return float(lane.get("width_start_m") or lane.get("width_m") or DEFAULT_LANE_WIDTH_M)
    if lane.get("to_node") == node_id:
        return float(lane.get("width_end_m") or lane.get("width_m") or DEFAULT_LANE_WIDTH_M)
    return float(lane.get("width_start_m") or lane.get("width_m") or DEFAULT_LANE_WIDTH_M)


def match_corner_lanes(incoming_lanes: list[dict[str, Any]], outgoing_lanes: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    incoming = sorted(incoming_lanes, key=lambda lane: int(lane["index"]))
    outgoing = sorted(outgoing_lanes, key=lambda lane: int(lane["index"]))
    count = min(len(incoming), len(outgoing))
    return [(incoming[i], outgoing[i]) for i in range(count)]


def continuity_curve_from_fillet(
    base_points: list[tuple[float, float]],
    start_offset: float,
    end_offset: float,
) -> list[list[float]]:
    if len(base_points) < 2:
        return []
    return [[round(x, 3), round(z, 3)] for x, z in offset_points_profile(base_points, start_offset, end_offset)]


def add_continuity_links_for_direction(
    links: list[dict[str, Any]],
    corner: dict[str, Any],
    base_points: list[tuple[float, float]],
    incoming_lanes: list[dict[str, Any]],
    outgoing_lanes: list[dict[str, Any]],
    node_id: str,
    direction_index: int,
) -> None:
    for link_index, (from_lane, to_lane) in enumerate(match_corner_lanes(incoming_lanes, outgoing_lanes)):
        start_offset = lane_endpoint_offset(from_lane, node_id, "end")
        end_offset = lane_endpoint_offset(to_lane, node_id, "start")
        curve = continuity_curve_from_fillet(base_points, start_offset, end_offset)
        if len(curve) < 2:
            continue
        from_lane_points = [(float(p[0]), float(p[1])) for p in from_lane["centerline_xz"]]
        to_lane_points = [(float(p[0]), float(p[1])) for p in to_lane["centerline_xz"]]
        curve_start = (float(curve[0][0]), float(curve[0][1]))
        curve_end = (float(curve[-1][0]), float(curve[-1][1]))
        stats = curve_stats(curve)
        width_start = lane_endpoint_width(from_lane, node_id, "end")
        width_end = lane_endpoint_width(to_lane, node_id, "start")
        width_confidence = min(
            float(from_lane.get("width_confidence", 0.45)),
            float(to_lane.get("width_confidence", 0.45)),
        )
        links.append({
            "continuity_link_id": f"{corner['corner_node_id']}_cl_{direction_index:02d}_{link_index:02d}",
            "corner_id": corner.get("corner_id", ""),
            "corner_node_id": corner["corner_node_id"],
            "from_road": from_lane["road_id"],
            "to_road": to_lane["road_id"],
            "from_lane": from_lane["lane_id"],
            "to_lane": to_lane["lane_id"],
            "turn": "corner",
            "source": "optimized_corner_fillet",
            "connecting_curve_xz": curve,
            "curve_length_m": stats["length_m"],
            "curve_sample_count": stats["sample_count"],
            "from_lane_trim_end_m": round(distance(from_lane_points[-1], curve_start), 3),
            "to_lane_trim_start_m": round(distance(to_lane_points[0], curve_end), 3),
            "width_m": round((width_start + width_end) * 0.5, 3),
            "width_start_m": round(width_start, 3),
            "width_end_m": round(width_end, 3),
            "width_source": "connected_lane_widths",
            "width_confidence": round(width_confidence, 3),
            "cut_m": round(float(corner.get("cut_m") or 0.0), 3),
            "turn_angle_deg": round(float(corner.get("turn_angle_deg") or 0.0), 3),
        })


def build_continuity_links(lanes: list[dict[str, Any]], corner_fillets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lanes_by_start: dict[tuple[str, str], list[dict[str, Any]]] = {}
    lanes_by_end: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for lane in lanes:
        lanes_by_start.setdefault((str(lane["from_node"]), str(lane["road_id"])), []).append(lane)
        lanes_by_end.setdefault((str(lane["to_node"]), str(lane["road_id"])), []).append(lane)

    links: list[dict[str, Any]] = []
    for corner in corner_fillets:
        node_id = str(corner.get("corner_node_id") or "")
        edge_a = str(corner.get("from_edge_id") or "")
        edge_b = str(corner.get("to_edge_id") or "")
        points = corner.get("points") or []
        if not node_id or not edge_a or not edge_b or len(points) < 2:
            continue
        add_continuity_links_for_direction(
            links,
            corner,
            points,
            lanes_by_end.get((node_id, edge_a), []),
            lanes_by_start.get((node_id, edge_b), []),
            node_id,
            0,
        )
        add_continuity_links_for_direction(
            links,
            corner,
            list(reversed(points)),
            lanes_by_end.get((node_id, edge_b), []),
            lanes_by_start.get((node_id, edge_a), []),
            node_id,
            1,
        )
    return links


def build_approach_lane_records(
    semantic: dict[str, Any],
    incoming_lanes: list[dict[str, Any]],
    outgoing_lanes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records = []
    for approach in semantic.get("approaches", []):
        edge_id = approach["edge_id"]
        incoming_for_edge = sorted(
            (lane for lane in incoming_lanes if lane["road_id"] == edge_id),
            key=lambda lane: int(lane["index"]),
        )
        outgoing_for_edge = sorted(
            (lane for lane in outgoing_lanes if lane["road_id"] == edge_id),
            key=lambda lane: int(lane["index"]),
        )
        records.append({
            "approach_id": approach["approach_id"],
            "edge_id": edge_id,
            "role": approach.get("role", "approach"),
            "direction_out_xz": approach.get("direction_out_xz", []),
            "can_enter_junction": bool(approach.get("can_enter_junction")),
            "can_exit_junction": bool(approach.get("can_exit_junction")),
            "incoming_lane_ids": [lane["lane_id"] for lane in incoming_for_edge],
            "outgoing_lane_ids": [lane["lane_id"] for lane in outgoing_for_edge],
            "incoming_lane_count": len(incoming_for_edge),
            "outgoing_lane_count": len(outgoing_for_edge),
        })
    return records


def build_junctions_from_semantics(
    graph: dict[str, Any],
    lanes: list[dict[str, Any]],
    semantics: dict[str, Any],
    junction_connectors: dict[tuple[str, tuple[str, str]], dict[str, Any]] | None = None,
    approach_centerlines_trimmed: bool = False,
) -> tuple[list[dict[str, Any]], Counter, Counter]:
    nodes = {node["node_id"]: node for node in graph["nodes"]}
    junction_connectors = junction_connectors or {}
    lanes_by_start: dict[str, list[dict[str, Any]]] = {}
    lanes_by_end: dict[str, list[dict[str, Any]]] = {}
    for lane in lanes:
        lanes_by_start.setdefault(lane["from_node"], []).append(lane)
        lanes_by_end.setdefault(lane["to_node"], []).append(lane)

    fallback_counts: Counter = Counter()
    skipped_counts: Counter = Counter()
    junctions: list[dict[str, Any]] = []
    for semantic in semantics.get("junctions", []):
        node_id = semantic["node_id"]
        node = nodes.get(node_id)
        if node is None:
            skipped_counts["missing_node"] += 1
            continue
        center = (float(node["x"]), float(node["z"]))
        incoming_lanes = lanes_by_end.get(node_id, [])
        outgoing_lanes = lanes_by_start.get(node_id, [])
        connections: list[dict[str, Any]] = []
        approach_roles = {approach["edge_id"]: approach["role"] for approach in semantic.get("approaches", [])}
        approach_lanes = build_approach_lane_records(semantic, incoming_lanes, outgoing_lanes)
        for movement in semantic.get("movements", []):
            if not movement.get("allowed"):
                skipped_counts["blocked_movement"] += 1
                continue
            from_edge_id = movement["from_edge"]
            to_edge_id = movement["to_edge"]
            incoming_for_edge = [lane for lane in incoming_lanes if lane["road_id"] == from_edge_id]
            if not incoming_for_edge:
                skipped_counts["missing_incoming_lanes"] += 1
                continue
            outgoing_for_edge = [lane for lane in outgoing_lanes if lane["road_id"] == to_edge_id]
            if not outgoing_for_edge:
                skipped_counts["missing_outgoing_lanes"] += 1
                continue
            turn = movement["kind"]
            from_candidates = select_lanes(incoming_for_edge, turn, incoming=True)
            to_candidates = select_lanes(outgoing_for_edge, turn, incoming=False)
            connection_index = len(connections)
            connector_ref = junction_connectors.get(junction_connector_key(node_id, from_edge_id, to_edge_id))
            lane_links = build_lane_link_records(
                from_candidates,
                to_candidates,
                movement,
                semantic["junction_id"],
                connection_index,
                connector_ref,
                approach_centerlines_trimmed,
            )
            if not lane_links:
                fallback_counts["missing_lane_link"] += 1
                continue
            representative_curve = lane_links[0]["connecting_curve_xz"]
            connections.append({
                "connection_id": f"{semantic['junction_id']}_c_{connection_index:03d}",
                "semantic_movement_id": movement["movement_id"],
                "from_road": from_edge_id,
                "to_road": to_edge_id,
                "from_role": approach_roles.get(from_edge_id, "approach"),
                "to_role": approach_roles.get(to_edge_id, "approach"),
                "turn": turn,
                "turn_normalized": normalize_turn_kind(str(turn)),
                "allowed": True,
                "restriction_source": movement.get("source", "junction_semantics"),
                "connecting_curve_xz": representative_curve,
                "curve_length_m": curve_stats(representative_curve)["length_m"],
                "lane_links": lane_links,
            })
        fallback_counts[SURFACE_STRATEGY_PENDING] += 1
        junctions.append({
            "junction_id": semantic["junction_id"],
            "node_id": node_id,
            "type": semantic["type"],
            "center_xz": [round(center[0], 3), round(center[1], 3)],
            "incident_roads": node["incident_edges"],
            "incoming_lane_ids": [lane["lane_id"] for lane in incoming_lanes],
            "outgoing_lane_ids": [lane["lane_id"] for lane in outgoing_lanes],
            "approach_lanes": approach_lanes,
            "semantic_approaches": semantic.get("approaches", []),
            "semantic_through_pairs": semantic.get("through_pairs", []),
            "envelope_polygon_xz": [],
            "surface_strategy": SURFACE_STRATEGY_PENDING,
            "surface_fallback": "none",
            "envelope_strategy": SURFACE_STRATEGY_PENDING,
            "control": {
                "type": "unknown",
                "stop_lines": [],
                "crosswalks": [],
            },
            "connections": connections,
        })
    return junctions, fallback_counts, skipped_counts


def build_lane_graph(
    input_path: Path,
    semantics_path: Path,
    output_path: Path,
    report_path: Path,
    area_id: str,
    optimized_centerlines_path: Path | None = None,
) -> dict[str, Any]:
    graph = read_json(input_path)
    semantics = read_json(semantics_path)
    optimized_refs = load_optimized_centerline_refs(optimized_centerlines_path)
    lane_edges, optimized_approach_count = edges_with_optimized_approaches(graph["edges"], optimized_refs["approaches_by_edge"])
    approach_centerlines_trimmed = optimized_approach_count > 0
    lanes = build_lanes(lane_edges)
    continuity_links = build_continuity_links(lanes, optimized_refs["corner_fillets"])
    junction_connectors = index_junction_connectors(optimized_refs["junction_connectors"])
    junctions, fallback_counts, skipped_counts = build_junctions_from_semantics(
        graph,
        lanes,
        semantics,
        junction_connectors,
        approach_centerlines_trimmed,
    )
    all_lane_links = [
        link
        for junction in junctions
        for conn in junction["connections"]
        for link in conn["lane_links"]
    ]
    trim_by_lane = lane_trim_distances(
        {"metadata": {"junction_trim_m": JUNCTION_TRIM_M}, "lanes": lanes},
        all_lane_links,
        continuity_links,
    )
    refresh_lane_link_curves(
        junctions,
        {str(lane["lane_id"]): lane for lane in lanes},
        trim_by_lane,
    )
    connection_count = sum(len(junction["connections"]) for junction in junctions)
    all_lane_links = [
        link
        for junction in junctions
        for conn in junction["connections"]
        for link in conn["lane_links"]
    ]
    lane_link_count = len(all_lane_links)
    turn_counts = Counter(conn["turn"] for junction in junctions for conn in junction["connections"])
    junction_type_counts = Counter(junction["type"] for junction in junctions)
    source_counts = Counter(lane["source"] for lane in lanes)
    lane_link_source_counts = Counter(link["source"] for link in all_lane_links)
    lane_link_curve_source_counts = Counter(str(link.get("curve_source", "unknown")) for link in all_lane_links)
    lane_link_connector_kind_counts = Counter(str(link.get("connector_kind") or "none") for link in all_lane_links)
    connection_source_counts = Counter(
        conn["restriction_source"]
        for junction in junctions
        for conn in junction["connections"]
    )
    lane_ids = {lane["lane_id"] for lane in lanes}
    lane_link_reference_errors = sum(
        1
        for link in all_lane_links
        if link["from_lane"] not in lane_ids or link["to_lane"] not in lane_ids
    )
    blocked_lane_links = sum(1 for link in all_lane_links if not link.get("semantic_movement_id"))
    empty_connection_curves = sum(
        1
        for junction in junctions
        for conn in junction["connections"]
        if not conn["connecting_curve_xz"]
    )
    curve_lengths = [float(link.get("curve_length_m", 0.0)) for link in all_lane_links]
    continuity_curve_lengths = [float(link.get("curve_length_m", 0.0)) for link in continuity_links]
    confidences = [float(link.get("confidence", 0.0)) for link in all_lane_links]
    lane_widths = [float(lane.get("width_m", 0.0)) for lane in lanes]
    lane_width_deltas = [
        abs(float(lane.get("width_end_m", lane.get("width_m", 0.0))) - float(lane.get("width_start_m", lane.get("width_m", 0.0))))
        for lane in lanes
    ]
    width_source_counts = Counter(str(lane.get("width_source", "unknown")) for lane in lanes)
    centerline_source_counts = Counter(str(lane.get("centerline_source", "unknown")) for lane in lanes)
    width_confidences = [float(lane.get("width_confidence", 0.0)) for lane in lanes]

    lane_graph = {
        "type": "lane_graph",
        "metadata": {
            "area_id": area_id,
            "schema": "road_test_pipeline.lane_graph.v1",
            "coord_domain": "local_xz_m",
            "source": str(input_path),
            "junction_semantics_source": str(semantics_path),
            "optimized_centerlines_source": optimized_refs["path"],
            "junction_lane_strategy": "optimized_connector_curve_with_endpoint_bezier_fallback",
            "corner_continuity_strategy": "optimized_corner_fillet_only",
            "approach_centerlines_trimmed": approach_centerlines_trimmed,
            "lane_width_m": DEFAULT_LANE_WIDTH_M,
            "width_strategy": "fixed_lane_width",
            "junction_trim_m": JUNCTION_TRIM_M,
            "curve_sample_count": CURVE_SAMPLE_COUNT,
            "design_note": "Semantic-driven junction laneLinks stay separate from degree-2 corner continuity links.",
        },
        "lanes": lanes,
        "continuity_links": continuity_links,
        "junctions": junctions,
    }
    write_json(output_path, lane_graph)

    total_junctions = len(junctions)
    fan_fallback = sum(1 for junction in junctions if junction["envelope_strategy"] == "junction_fan_envelope")
    report = {
        "area_id": area_id,
        "stage": "lane_graph_v1",
        "input": str(input_path),
        "junction_semantics": str(semantics_path),
        "output": str(output_path),
        "counts": {
            "lanes": len(lanes),
            "junctions": total_junctions,
            "approach_lane_records": sum(len(junction["approach_lanes"]) for junction in junctions),
            "connections": connection_count,
            "lane_links": lane_link_count,
            "continuity_links": len(continuity_links),
            "optimized_approach_centerlines": optimized_approach_count,
            "optimized_junction_connectors": len(optimized_refs["junction_connectors"]),
            "optimized_junction_connector_lane_links": lane_link_curve_source_counts.get("optimized_junction_connector", 0),
            "optimized_corner_fillet_links": len(continuity_links),
            "fan_fallback_junctions": fan_fallback,
        },
        "junction_type_counts": dict(sorted(junction_type_counts.items())),
        "turn_counts": dict(sorted(turn_counts.items())),
        "lane_source_counts": dict(sorted(source_counts.items())),
        "lane_centerline_source_counts": dict(sorted(centerline_source_counts.items())),
        "width_source_counts": dict(sorted(width_source_counts.items())),
        "connection_source_counts": dict(sorted(connection_source_counts.items())),
        "lane_link_source_counts": dict(sorted(lane_link_source_counts.items())),
        "lane_link_curve_source_counts": dict(sorted(lane_link_curve_source_counts.items())),
        "lane_link_connector_kind_counts": dict(sorted(lane_link_connector_kind_counts.items())),
        "fallback_counts": dict(sorted(fallback_counts.items())),
        "skipped_counts": dict(sorted(skipped_counts.items())),
        "metrics": {
            "junctions_with_connections_ratio": round(
                sum(1 for junction in junctions if junction["connections"]) / max(1, total_junctions),
                3,
            ),
            "fan_fallback_ratio": round(fan_fallback / max(1, total_junctions), 3),
            "avg_lane_links_per_junction": round(lane_link_count / max(1, total_junctions), 3),
            "lane_link_reference_errors": lane_link_reference_errors,
            "blocked_lane_links": blocked_lane_links,
            "empty_connection_curves": empty_connection_curves,
            "avg_lane_link_confidence": round(sum(confidences) / max(1, len(confidences)), 3),
            "min_lane_link_confidence": round(min(confidences), 3) if confidences else 0.0,
            "avg_curve_length_m": round(sum(curve_lengths) / max(1, len(curve_lengths)), 3),
            "max_curve_length_m": round(max(curve_lengths), 3) if curve_lengths else 0.0,
            "avg_continuity_curve_length_m": round(sum(continuity_curve_lengths) / max(1, len(continuity_curve_lengths)), 3),
            "max_continuity_curve_length_m": round(max(continuity_curve_lengths), 3) if continuity_curve_lengths else 0.0,
            "avg_lane_width_m": round(sum(lane_widths) / max(1, len(lane_widths)), 3),
            "min_lane_width_m": round(min(lane_widths), 3) if lane_widths else 0.0,
            "max_lane_width_m": round(max(lane_widths), 3) if lane_widths else 0.0,
            "avg_lane_width_confidence": round(sum(width_confidences) / max(1, len(width_confidences)), 3),
            "max_lane_width_start_end_delta_m": round(max(lane_width_deltas), 3) if lane_width_deltas else 0.0,
        },
        "notes": [
            "M2/M3 redesign: lane graph now consumes junction_semantics road-level movements.",
            "Lane widths use a fixed default width for this replay state.",
            "Junction laneLinks are generated only for allowed semantic movements and stay independent from road-level optimized junction connectors.",
            "Degree-2 road bends are bridged by continuity_links derived from optimized_corner_fillet curves, not by junction fan patches.",
            "Because the current OSM sample lacks reliable turn restrictions, movement and laneLink confidence is inherited from geometry inference.",
            "No road surface, junction fan polygon or envelope mesh is generated in this layer.",
        ],
    }
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build lane_graph.json and semantic junction model.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--input", default="")
    parser.add_argument("--semantics", default="")
    parser.add_argument("--optimized-centerlines", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    input_path = Path(args.input) if args.input else root / "data" / "processed" / f"{args.area_id}_road_graph.json"
    semantics_path = Path(args.semantics) if args.semantics else root / "data" / "processed" / f"{args.area_id}_junction_semantics.json"
    optimized_centerlines_path = (
        Path(args.optimized_centerlines)
        if args.optimized_centerlines
        else root / "data" / "processed" / f"{args.area_id}_roads_optimized_centerlines.geojson"
    )
    if not optimized_centerlines_path.exists():
        optimized_centerlines_path = None
    output_path = Path(args.output) if args.output else root / "data" / "processed" / f"{args.area_id}_lane_graph.json"
    report_path = Path(args.report) if args.report else root / "reports" / f"{args.area_id}_lane_graph_report.json"

    report = build_lane_graph(input_path, semantics_path, output_path, report_path, args.area_id, optimized_centerlines_path)
    print(json.dumps({
        "area_id": args.area_id,
        "output": str(output_path),
        "report": str(report_path),
        "counts": report["counts"],
        "metrics": report["metrics"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
