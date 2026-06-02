#!/usr/bin/env python3
"""Optimize road centerlines before width extrusion.

The target shape follows the junction sketches: trim raw approach lines back
from the original intersection node, then add short clean connector curves
between neighboring approaches. Surface generation can then extrude these
optimized centerlines by width instead of relying on a large fan patch first.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


MIN_JUNCTION_DEGREE = 3
MIN_TRIM_M = 3.0
MAX_TRIM_M = 9.0
CONNECTOR_SAMPLES = 7
CONNECTOR_CENTER_WEIGHT = 0.65
MIN_CORNER_TURN_DEG = 18.0
MIN_CORNER_ANGLE_DEG = 35.0
CORNER_MIN_CUT_M = 2.0
CORNER_MAX_CUT_M = 12.0
CORNER_WIDTH_FACTOR = 0.85
CORNER_EDGE_LENGTH_FACTOR = 0.38
CORNER_SAMPLES = 9
CORNER_HANDLE_FACTOR = 0.58
JUNCTION_THROUGH_MIN_ANGLE_DEG = 145.0
JUNCTION_T_JUNCTION_THROUGH_MIN_ANGLE_DEG = 120.0
JUNCTION_MOVEMENT_SAMPLES = 9
T_JUNCTION_SAMPLES = 11
T_JUNCTION_THROUGH_HANDLE = 0.36
T_JUNCTION_TURN_HANDLE = 0.52
T_BRANCH_EDGE_CLEARANCE_M = 0.25
T_BRANCH_MAX_TRIM_M = 14.0

ROAD_CLASS_RANK = {
    "motorway": 7,
    "trunk": 6,
    "primary": 5,
    "secondary": 4,
    "tertiary": 3,
    "residential": 2,
    "unclassified": 2,
    "service": 1,
    "living_street": 1,
    "junction": 0,
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def to_lonlat(x: float, z: float, origin_lon: float, origin_lat: float) -> tuple[float, float]:
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(origin_lat))
    return origin_lon + x / m_per_deg_lon, origin_lat + z / m_per_deg_lat


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = a[0] - b[0]
    dz = a[1] - b[1]
    return math.sqrt(dx * dx + dz * dz)


def normalize(v: tuple[float, float]) -> tuple[float, float]:
    length = math.sqrt(v[0] * v[0] + v[1] * v[1])
    if length <= 1e-9:
        return 0.0, 0.0
    return v[0] / length, v[1] / length


def angle_of(v: tuple[float, float]) -> float:
    return math.atan2(v[1], v[0])


def angle_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1]))
    return math.acos(dot)


def edge_points(edge: dict[str, Any]) -> list[tuple[float, float]]:
    return [(float(p[0]), float(p[1])) for p in edge["geometry_xz"]]


def polyline_length(points: list[tuple[float, float]]) -> float:
    return sum(distance(points[i], points[i + 1]) for i in range(len(points) - 1))


def direction_out(edge: dict[str, Any], node_id: str) -> tuple[float, float]:
    pts = edge_points(edge)
    if node_id == edge["from_node"]:
        return normalize((pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]))
    return normalize((pts[-2][0] - pts[-1][0], pts[-2][1] - pts[-1][1]))


def trim_distance(edge: dict[str, Any], node: dict[str, Any], direction: tuple[float, float]) -> float:
    width = float(edge.get("width_m") or 6.0)
    trims = []
    for other_id in node["incident_edges"]:
        if other_id == edge["edge_id"]:
            continue
        trims.append(angle_between(direction, direction_out(node["_edges"][other_id], node["node_id"])))
    min_angle = min(trims) if trims else math.radians(90)
    angle_factor = 1.0 / max(0.45, math.sin(max(math.radians(25), min_angle)))
    return min(MAX_TRIM_M, max(MIN_TRIM_M, width * 0.42 * angle_factor))


def projected_branch_trim_to_through_edge(
    branch_direction: tuple[float, float],
    through_direction: tuple[float, float],
    through_width_m: float,
) -> float:
    sin_theta = abs(branch_direction[0] * through_direction[1] - branch_direction[1] * through_direction[0])
    if sin_theta <= 1e-6:
        return 0.0
    trim = (through_width_m * 0.5 + T_BRANCH_EDGE_CLEARANCE_M) / max(0.35, sin_theta)
    return min(T_BRANCH_MAX_TRIM_M, max(MIN_TRIM_M, trim))


def apply_t_junction_branch_trims(
    nodes: dict[str, dict[str, Any]],
    trim_by_edge_node: dict[tuple[str, str], float],
) -> dict[str, Any]:
    adjustments: list[float] = []
    for node in nodes.values():
        if node.get("degree") != 3:
            continue
        ends = []
        for edge_id in node["incident_edges"]:
            edge = node["_edges"][edge_id]
            ends.append({
                "edge": edge,
                "direction": direction_out(edge, node["node_id"]),
            })
        through_pairs = select_through_pairs(ends)
        if not through_pairs:
            continue
        through_key = next(iter(through_pairs))
        through = [end for end in ends if end["edge"]["edge_id"] in through_key]
        branches = [end for end in ends if end["edge"]["edge_id"] not in through_key]
        if len(through) != 2 or len(branches) != 1:
            continue
        branch = branches[0]
        through_width = max(float(end["edge"].get("width_m") or 0.0) for end in through)
        target_trim = projected_branch_trim_to_through_edge(
            branch["direction"],
            through[0]["direction"],
            through_width,
        )
        key = (branch["edge"]["edge_id"], node["node_id"])
        previous = trim_by_edge_node.get(key, 0.0)
        if target_trim > previous + 1e-6:
            trim_by_edge_node[key] = target_trim
            adjustments.append(target_trim - previous)
    return {
        "t_branch_trim_adjustments": len(adjustments),
        "t_branch_trim_max_delta_m": round(max(adjustments), 3) if adjustments else 0.0,
        "t_branch_trim_avg_delta_m": round(sum(adjustments) / len(adjustments), 3) if adjustments else 0.0,
    }


def corner_trim_distance(edge_a: dict[str, Any], edge_b: dict[str, Any], turn_deg: float) -> float:
    width = max(float(edge_a.get("width_m") or 6.0), float(edge_b.get("width_m") or 6.0))
    angle_gain = min(1.25, max(0.75, turn_deg / 90.0))
    cut = max(CORNER_MIN_CUT_M, width * CORNER_WIDTH_FACTOR * angle_gain)
    cut = min(cut, CORNER_MAX_CUT_M)
    cut = min(cut, float(edge_a["length_m"]) * CORNER_EDGE_LENGTH_FACTOR, float(edge_b["length_m"]) * CORNER_EDGE_LENGTH_FACTOR)
    return max(0.0, cut)


def scale_trims_for_length(
    points: list[tuple[float, float]],
    trim_start: float,
    trim_end: float,
) -> tuple[float, float]:
    length = polyline_length(points)
    if trim_start + trim_end >= length - 0.5:
        scale = max(0.0, (length - 0.5) / max(0.001, trim_start + trim_end))
        trim_start *= scale
        trim_end *= scale
    return trim_start, trim_end


def trim_endpoint(
    points: list[tuple[float, float]],
    trim_start: float,
    trim_end: float,
) -> list[tuple[float, float]]:
    if len(points) < 2:
        return []
    trim_start, trim_end = scale_trims_for_length(points, trim_start, trim_end)

    def trim_from_start(src: list[tuple[float, float]], amount: float) -> list[tuple[float, float]]:
        if amount <= 0.0:
            return src[:]
        remaining = amount
        for i in range(len(src) - 1):
            seg_len = distance(src[i], src[i + 1])
            if remaining <= seg_len:
                d = normalize((src[i + 1][0] - src[i][0], src[i + 1][1] - src[i][1]))
                start = (src[i][0] + d[0] * remaining, src[i][1] + d[1] * remaining)
                return [start] + src[i + 1 :]
            remaining -= seg_len
        return []

    trimmed = trim_from_start(points, trim_start)
    trimmed = list(reversed(trim_from_start(list(reversed(trimmed)), trim_end)))
    return trimmed if len(trimmed) >= 2 and polyline_length(trimmed) > 0.05 else []


def bezier_connector(
    a: tuple[float, float],
    b: tuple[float, float],
    center: tuple[float, float],
) -> list[tuple[float, float]]:
    midpoint = ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)
    control = (
        center[0] * CONNECTOR_CENTER_WEIGHT + midpoint[0] * (1.0 - CONNECTOR_CENTER_WEIGHT),
        center[1] * CONNECTOR_CENTER_WEIGHT + midpoint[1] * (1.0 - CONNECTOR_CENTER_WEIGHT),
    )
    points = []
    for i in range(CONNECTOR_SAMPLES):
        t = i / (CONNECTOR_SAMPLES - 1)
        u = 1.0 - t
        x = u * u * a[0] + 2.0 * u * t * control[0] + t * t * b[0]
        z = u * u * a[1] + 2.0 * u * t * control[1] + t * t * b[1]
        points.append((x, z))
    return points


def quadratic_curve(
    a: tuple[float, float],
    b: tuple[float, float],
    control: tuple[float, float],
    samples: int,
) -> list[tuple[float, float]]:
    points = []
    for i in range(samples):
        t = i / (samples - 1)
        u = 1.0 - t
        x = u * u * a[0] + 2.0 * u * t * control[0] + t * t * b[0]
        z = u * u * a[1] + 2.0 * u * t * control[1] + t * t * b[1]
        points.append((x, z))
    return points


def tangent_corner_curve(
    a: tuple[float, float],
    b: tuple[float, float],
    center: tuple[float, float],
    samples: int,
) -> list[tuple[float, float]]:
    into_corner = normalize((center[0] - a[0], center[1] - a[1]))
    out_of_corner = normalize((b[0] - center[0], b[1] - center[1]))
    chord = distance(a, b)
    handle = min(
        chord * CORNER_HANDLE_FACTOR,
        distance(a, center) * 0.92,
        distance(b, center) * 0.92,
    )
    c1 = (a[0] + into_corner[0] * handle, a[1] + into_corner[1] * handle)
    c2 = (b[0] - out_of_corner[0] * handle, b[1] - out_of_corner[1] * handle)
    points = []
    for i in range(samples):
        t = i / (samples - 1)
        u = 1.0 - t
        x = (
            u * u * u * a[0]
            + 3.0 * u * u * t * c1[0]
            + 3.0 * u * t * t * c2[0]
            + t * t * t * b[0]
        )
        z = (
            u * u * u * a[1]
            + 3.0 * u * u * t * c1[1]
            + 3.0 * u * t * t * c2[1]
            + t * t * t * b[1]
        )
        points.append((x, z))
    return points


def edge_priority(edge: dict[str, Any]) -> float:
    road_class = str(edge.get("road_class") or edge.get("highway") or "unclassified")
    rank = ROAD_CLASS_RANK.get(road_class, ROAD_CLASS_RANK.get(str(edge.get("highway") or ""), 1))
    return rank * 10.0 + float(edge.get("width_m") or 0.0)


def pair_key(a: dict[str, Any], b: dict[str, Any]) -> tuple[str, str]:
    return tuple(sorted((a["edge"]["edge_id"], b["edge"]["edge_id"])))


def select_through_pairs(ends: list[dict[str, Any]]) -> set[tuple[str, str]]:
    min_angle = math.radians(JUNCTION_THROUGH_MIN_ANGLE_DEG)
    if len(ends) == 3:
        min_angle = math.radians(JUNCTION_T_JUNCTION_THROUGH_MIN_ANGLE_DEG)

    candidates = []
    for i, a in enumerate(ends):
        for b in ends[i + 1 :]:
            angle = angle_between(a["direction"], b["direction"])
            if angle < min_angle:
                continue
            opposite_score = 1.0 - abs(math.pi - angle) / math.pi
            priority_score = (edge_priority(a["edge"]) + edge_priority(b["edge"])) * 0.01
            candidates.append((opposite_score + priority_score, angle, a, b))
    candidates.sort(key=lambda item: item[0], reverse=True)

    through: set[tuple[str, str]] = set()
    used_edges: set[str] = set()
    for _score, _angle, a, b in candidates:
        a_id = a["edge"]["edge_id"]
        b_id = b["edge"]["edge_id"]
        if a_id in used_edges or b_id in used_edges:
            continue
        through.add(pair_key(a, b))
        used_edges.update((a_id, b_id))
        if len(through) >= max(1, len(ends) // 2):
            break
    return through


def movement_pairs(ends: list[dict[str, Any]], through_pairs: set[tuple[str, str]]) -> list[tuple[dict[str, Any], dict[str, Any], str]]:
    pairs: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    if len(ends) <= 4:
        for i, a in enumerate(ends):
            for b in ends[i + 1 :]:
                key = pair_key(a, b)
                pairs.append((a, b, "through" if key in through_pairs else "turn"))
        return pairs

    seen = set()
    for i, a in enumerate(ends):
        b = ends[(i + 1) % len(ends)]
        key = pair_key(a, b)
        if key not in seen:
            pairs.append((a, b, "through" if key in through_pairs else "turn"))
            seen.add(key)
    for a in ends:
        for b in ends:
            key = pair_key(a, b)
            if key in through_pairs and key not in seen:
                pairs.append((a, b, "through"))
                seen.add(key)
    return pairs


def tangent_movement_curve(
    a: tuple[float, float],
    b: tuple[float, float],
    direction_a: tuple[float, float],
    direction_b: tuple[float, float],
    movement_kind: str,
) -> list[tuple[float, float]]:
    chord = distance(a, b)
    handle_factor = 0.42 if movement_kind == "through" else 0.62
    handle = chord * handle_factor
    c1 = (a[0] - direction_a[0] * handle, a[1] - direction_a[1] * handle)
    c2 = (b[0] - direction_b[0] * handle, b[1] - direction_b[1] * handle)
    points = []
    for i in range(JUNCTION_MOVEMENT_SAMPLES):
        t = i / (JUNCTION_MOVEMENT_SAMPLES - 1)
        u = 1.0 - t
        x = (
            u * u * u * a[0]
            + 3.0 * u * u * t * c1[0]
            + 3.0 * u * t * t * c2[0]
            + t * t * t * b[0]
        )
        z = (
            u * u * u * a[1]
            + 3.0 * u * u * t * c1[1]
            + 3.0 * u * t * t * c2[1]
            + t * t * t * b[1]
        )
        points.append((x, z))
    return points


def t_junction_curve(
    a: tuple[float, float],
    b: tuple[float, float],
    direction_a: tuple[float, float],
    direction_b: tuple[float, float],
    center: tuple[float, float],
    connector_kind: str,
) -> list[tuple[float, float]]:
    chord = distance(a, b)
    handle_factor = T_JUNCTION_THROUGH_HANDLE if connector_kind == "t_through" else T_JUNCTION_TURN_HANDLE
    handle = min(
        chord * handle_factor,
        distance(a, center) * 0.88,
        distance(b, center) * 0.88,
    )
    c1 = (a[0] - direction_a[0] * handle, a[1] - direction_a[1] * handle)
    c2 = (b[0] - direction_b[0] * handle, b[1] - direction_b[1] * handle)
    points = []
    for i in range(T_JUNCTION_SAMPLES):
        t = i / (T_JUNCTION_SAMPLES - 1)
        u = 1.0 - t
        x = (
            u * u * u * a[0]
            + 3.0 * u * u * t * c1[0]
            + 3.0 * u * t * t * c2[0]
            + t * t * t * b[0]
        )
        z = (
            u * u * u * a[1]
            + 3.0 * u * u * t * c1[1]
            + 3.0 * u * t * t * c2[1]
            + t * t * t * b[1]
        )
        points.append((x, z))
    return points


def t_junction_connector_specs(
    ends: list[dict[str, Any]],
    through_pairs: set[tuple[str, str]],
    center: tuple[float, float],
) -> list[dict[str, Any]]:
    if len(ends) != 3 or not through_pairs:
        return []

    through_key = next(iter(through_pairs))
    through = [end for end in ends if end["edge"]["edge_id"] in through_key]
    branches = [end for end in ends if end["edge"]["edge_id"] not in through_key]
    if len(through) != 2 or len(branches) != 1:
        return []

    branch = branches[0]
    specs = [
        {
            "a": through[0],
            "b": through[1],
            "connector_kind": "t_through",
        }
    ]
    for through_end in through:
        specs.append({
            "a": branch,
            "b": through_end,
            "connector_kind": "t_turn",
        })
    return specs


def feature(
    points: list[tuple[float, float]],
    props: dict[str, Any],
    origin_lon: float,
    origin_lat: float,
) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [round(lon, 8), round(lat, 8)]
                for lon, lat in (to_lonlat(x, z, origin_lon, origin_lat) for x, z in points)
            ],
        },
        "properties": props,
    }


def optimize_centerlines(input_path: Path, output_path: Path, report_path: Path, area_id: str) -> dict[str, Any]:
    graph = read_json(input_path)
    meta = graph["metadata"]
    origin_lon = float(meta["origin_lon"])
    origin_lat = float(meta["origin_lat"])
    edges = {edge["edge_id"]: edge for edge in graph["edges"]}
    nodes = {node["node_id"]: dict(node, _edges=edges) for node in graph["nodes"]}

    trim_by_edge_node: dict[tuple[str, str], float] = {}
    trimmed_endpoint: dict[tuple[str, str], tuple[float, float]] = {}
    corner_nodes: dict[str, dict[str, Any]] = {}
    for node in nodes.values():
        if node["degree"] < MIN_JUNCTION_DEGREE:
            continue
        for edge_id in node["incident_edges"]:
            edge = edges[edge_id]
            d = direction_out(edge, node["node_id"])
            trim = trim_distance(edge, node, d)
            key = (edge_id, node["node_id"])
            trim_by_edge_node[key] = max(trim_by_edge_node.get(key, 0.0), trim)

    t_branch_trim_metrics = apply_t_junction_branch_trims(nodes, trim_by_edge_node)

    for node in nodes.values():
        if node.get("kind") != "connector" or node["degree"] != 2:
            continue
        edge_a_id, edge_b_id = node["incident_edges"]
        edge_a = edges[edge_a_id]
        edge_b = edges[edge_b_id]
        d_a = direction_out(edge_a, node["node_id"])
        d_b = direction_out(edge_b, node["node_id"])
        angle = angle_between(d_a, d_b)
        turn_deg = 180.0 - math.degrees(angle)
        if turn_deg < MIN_CORNER_TURN_DEG or math.degrees(angle) < MIN_CORNER_ANGLE_DEG:
            continue
        cut = corner_trim_distance(edge_a, edge_b, turn_deg)
        if cut < CORNER_MIN_CUT_M:
            continue
        for edge_id in (edge_a_id, edge_b_id):
            key = (edge_id, node["node_id"])
            trim_by_edge_node[key] = max(trim_by_edge_node.get(key, 0.0), cut)
        corner_nodes[node["node_id"]] = {
            "edge_ids": [edge_a_id, edge_b_id],
            "turn_deg": turn_deg,
            "cut_m": cut,
        }

    features: list[dict[str, Any]] = []
    kept_approaches = 0
    dropped_short = 0
    for edge in graph["edges"]:
        points = edge_points(edge)
        start_trim = trim_by_edge_node.get((edge["edge_id"], edge["from_node"]), 0.0)
        end_trim = trim_by_edge_node.get((edge["edge_id"], edge["to_node"]), 0.0)
        start_trim, end_trim = scale_trims_for_length(points, start_trim, end_trim)
        trimmed = trim_endpoint(points, start_trim, end_trim)
        if not trimmed:
            dropped_short += 1
            continue
        if start_trim > 0.0:
            trimmed_endpoint[(edge["edge_id"], edge["from_node"])] = trimmed[0]
        if end_trim > 0.0:
            trimmed_endpoint[(edge["edge_id"], edge["to_node"])] = trimmed[-1]
        kept_approaches += 1
        features.append(feature(trimmed, {
            "vc_part": "optimized_approach_centerline",
            "source_edge_id": edge["edge_id"],
            "source_feature_id": edge.get("source_feature_id", ""),
            "highway": edge["highway"],
            "road_class": edge["road_class"],
            "lanes": edge["lanes"],
            "width_m": edge["width_m"],
            "oneway": edge["oneway"],
        }, origin_lon, origin_lat))

    corner_fillet_count = 0
    corner_turn_degrees: list[float] = []
    for node_id, corner in corner_nodes.items():
        node = nodes[node_id]
        center = (float(node["x"]), float(node["z"]))
        edge_ids = corner["edge_ids"]
        endpoints = [trimmed_endpoint.get((edge_id, node_id)) for edge_id in edge_ids]
        if endpoints[0] is None or endpoints[1] is None:
            continue
        edge_a = edges[edge_ids[0]]
        edge_b = edges[edge_ids[1]]
        width = max(float(edge_a["width_m"]), float(edge_b["width_m"]))
        curve = tangent_corner_curve(endpoints[0], endpoints[1], center, CORNER_SAMPLES)
        features.append(feature(curve, {
            "vc_part": "optimized_corner_fillet",
            "corner_node_id": node_id,
            "corner_id": f"{node_id}_fillet",
            "from_edge_id": edge_ids[0],
            "to_edge_id": edge_ids[1],
            "highway": "corner",
            "road_class": "corner",
            "lanes": max(int(edge_a["lanes"]), int(edge_b["lanes"])),
            "width_m": round(width, 3),
            "turn_angle_deg": round(corner["turn_deg"], 3),
            "cut_m": round(corner["cut_m"], 3),
            "oneway": False,
        }, origin_lon, origin_lat))
        corner_fillet_count += 1
        corner_turn_degrees.append(corner["turn_deg"])

    connector_count = 0
    movement_debug_features: list[dict[str, Any]] = []
    through_movement_count = 0
    turn_movement_count = 0
    t_junction_count = 0
    t_junction_connector_count = 0
    connector_style_counts = Counter()
    connector_degrees = Counter()
    for node in nodes.values():
        if node["degree"] < MIN_JUNCTION_DEGREE:
            continue
        center = (float(node["x"]), float(node["z"]))
        ends = []
        for edge_id in node["incident_edges"]:
            edge = edges[edge_id]
            d = direction_out(edge, node["node_id"])
            endpoint = trimmed_endpoint.get((edge_id, node["node_id"]))
            if endpoint is None:
                continue
            ends.append({
                "edge": edge,
                "direction": d,
                "angle": angle_of(d),
                "endpoint": endpoint,
            })
        ends.sort(key=lambda item: item["angle"])
        if len(ends) < 3:
            continue
        connector_degrees[str(len(ends))] += 1
        through_pairs = select_through_pairs(ends)

        visible_specs = t_junction_connector_specs(ends, through_pairs, center)
        if visible_specs:
            t_junction_count += 1
        else:
            visible_specs = [
                {
                    "a": current,
                    "b": ends[(i + 1) % len(ends)],
                    "connector_kind": "adjacent_fallback",
                }
                for i, current in enumerate(ends)
            ]

        for i, spec in enumerate(visible_specs):
            current = spec["a"]
            nxt = spec["b"]
            connector_kind = spec["connector_kind"]
            width = max(float(current["edge"]["width_m"]), float(nxt["edge"]["width_m"]))
            if connector_kind.startswith("t_"):
                connector = t_junction_curve(
                    current["endpoint"],
                    nxt["endpoint"],
                    current["direction"],
                    nxt["direction"],
                    center,
                    connector_kind,
                )
                t_junction_connector_count += 1
            else:
                connector = bezier_connector(current["endpoint"], nxt["endpoint"], center)
            connector_style_counts[connector_kind] += 1
            features.append(feature(connector, {
                "vc_part": "optimized_junction_connector",
                "junction_node_id": node["node_id"],
                "connector_id": f"{node['node_id']}_c_{i:02d}",
                "connector_kind": connector_kind,
                "from_edge_id": current["edge"]["edge_id"],
                "to_edge_id": nxt["edge"]["edge_id"],
                "highway": "junction",
                "road_class": "junction",
                "lanes": max(int(current["edge"]["lanes"]), int(nxt["edge"]["lanes"])),
                "width_m": round(width, 3),
                "oneway": False,
            }, origin_lon, origin_lat))
            connector_count += 1

        movement_index = 0
        for current, nxt, movement_kind in movement_pairs(ends, through_pairs):
            width = max(float(current["edge"]["width_m"]), float(nxt["edge"]["width_m"]))
            movement = tangent_movement_curve(
                current["endpoint"],
                nxt["endpoint"],
                current["direction"],
                nxt["direction"],
                movement_kind,
            )
            if movement_kind == "through":
                through_movement_count += 1
            else:
                turn_movement_count += 1
            movement_debug_features.append(feature(movement, {
                "vc_part": "junction_movement_debug",
                "junction_node_id": node["node_id"],
                "movement_id": f"{node['node_id']}_m_{movement_index:03d}",
                "movement_kind": movement_kind,
                "from_edge_id": current["edge"]["edge_id"],
                "to_edge_id": nxt["edge"]["edge_id"],
                "highway": "junction",
                "road_class": "junction",
                "lanes": max(int(current["edge"]["lanes"]), int(nxt["edge"]["lanes"])),
                "width_m": round(width, 3),
                "oneway": False,
            }, origin_lon, origin_lat))
            movement_index += 1

    fc = {
        "type": "FeatureCollection",
        "metadata": {
            "area_id": area_id,
            "schema": "road_test_pipeline.optimized_centerlines.v1",
            "coord_domain": "WGS84",
            "origin_lon": origin_lon,
            "origin_lat": origin_lat,
            "source": str(input_path),
            "strategy": "trim approaches first, add curved adjacent-edge junction connectors, then extrude widths",
        },
        "features": features,
    }
    write_json(output_path, fc)
    movement_debug_path = output_path.with_name(f"{area_id}_junction_movements_debug.geojson")
    write_json(movement_debug_path, {
        "type": "FeatureCollection",
        "metadata": {
            "area_id": area_id,
            "schema": "road_test_pipeline.junction_movements_debug.v1",
            "coord_domain": "WGS84",
            "origin_lon": origin_lon,
            "origin_lat": origin_lat,
            "source": str(input_path),
            "display_note": "Debug-only movement layer. Do not mix this into OUT_roads_centerlines.",
        },
        "features": movement_debug_features,
    })
    report = {
        "area_id": area_id,
        "stage": "optimized_centerlines_v1",
        "input": str(input_path),
        "output": str(output_path),
        "movement_debug_output": str(movement_debug_path),
        "counts": {
            "input_edges": len(graph["edges"]),
            "optimized_approaches": kept_approaches,
            "dropped_short_edges": dropped_short,
            "junction_nodes": sum(1 for node in nodes.values() if node["degree"] >= MIN_JUNCTION_DEGREE),
            "junction_connectors": connector_count,
            "t_junctions": t_junction_count,
            "t_junction_connectors": t_junction_connector_count,
            "junction_movement_debug": len(movement_debug_features),
            "junction_through_movements": through_movement_count,
            "junction_turn_movements": turn_movement_count,
            "corner_fillet_nodes": len(corner_nodes),
            "corner_fillets": corner_fillet_count,
            "output_features": len(features),
            **t_branch_trim_metrics,
        },
        "junction_degree_counts": dict(sorted(connector_degrees.items())),
        "junction_connector_style_counts": dict(sorted(connector_style_counts.items())),
        "corner_fillet_metrics": {
            "min_turn_deg": round(min(corner_turn_degrees), 3) if corner_turn_degrees else 0.0,
            "max_turn_deg": round(max(corner_turn_degrees), 3) if corner_turn_degrees else 0.0,
            "avg_turn_deg": round(sum(corner_turn_degrees) / len(corner_turn_degrees), 3) if corner_turn_degrees else 0.0,
            "max_cut_m": CORNER_MAX_CUT_M,
            "width_factor": CORNER_WIDTH_FACTOR,
            "edge_length_factor": CORNER_EDGE_LENGTH_FACTOR,
            "samples": CORNER_SAMPLES,
        },
        "notes": [
            "This stage optimizes centerlines before road width extrusion, matching the sketch-driven junction approach.",
            "Approach lines are clipped near junctions; visible junction connectors stay in the centerline skeleton.",
            "Road-level through/turn movement curves are exported to a separate debug layer so they do not visually cross the road skeleton.",
            "Degree-2 connector bends are locally filleted with stronger tangent-continuous cubic corner curves; endpoints and junction nodes are preserved.",
            "Surface builders should consume this optimized centerline output before using any fan fallback.",
        ],
    }
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Optimize junction centerlines before width extrusion.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--input", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    input_path = Path(args.input) if args.input else root / "data" / "processed" / f"{args.area_id}_road_graph.json"
    output_path = Path(args.output) if args.output else root / "data" / "processed" / f"{args.area_id}_roads_optimized_centerlines.geojson"
    report_path = Path(args.report) if args.report else root / "reports" / f"{args.area_id}_optimized_centerlines_report.json"
    report = optimize_centerlines(input_path, output_path, report_path, args.area_id)
    print(json.dumps({
        "area_id": args.area_id,
        "output": str(output_path),
        "report": str(report_path),
        "counts": report["counts"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
