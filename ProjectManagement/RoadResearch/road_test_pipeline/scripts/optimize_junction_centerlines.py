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
ARC_SAMPLE_DEG = 5.0
ARC_RADIUS_TOLERANCE_M = 0.05
MAX_ARC_RADIUS_M = 10000.0
STRAIGHT_SWEEP_DEG = 2.0
JUNCTION_TURN_MIN_RADIUS_M = 3.0
JUNCTION_TURN_RADIUS_WIDTH_FACTOR = 0.75
JUNCTION_TURN_MIN_RADIUS_BY_CLASS = {
    "service": 3.0,
    "living_street": 3.0,
    "residential": 6.0,
    "unclassified": 6.0,
    "tertiary": 8.0,
    "secondary": 9.0,
    "primary": 12.0,
    "trunk": 15.0,
    "motorway": 20.0,
}
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


def rotate90(v: tuple[float, float]) -> tuple[float, float]:
    return -v[1], v[0]


def dot(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1]


def cross(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[1] - a[1] * b[0]


def sub(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return a[0] - b[0], a[1] - b[1]


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
    locked_trim_keys: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    adjustments: list[float] = []
    locked_skips = 0
    locked_trim_keys = locked_trim_keys or set()
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
        if key in locked_trim_keys:
            locked_skips += 1
            continue
        previous = trim_by_edge_node.get(key, 0.0)
        if target_trim > previous + 1e-6:
            trim_by_edge_node[key] = target_trim
            adjustments.append(target_trim - previous)
    return {
        "t_branch_trim_adjustments": len(adjustments),
        "t_branch_trim_locked_skips": locked_skips,
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


def line_intersection(
    p: tuple[float, float],
    r: tuple[float, float],
    q: tuple[float, float],
    s: tuple[float, float],
) -> tuple[float, float] | None:
    denom = cross(r, s)
    if abs(denom) <= 1e-9:
        return None
    qp = sub(q, p)
    t = cross(qp, s) / denom
    return p[0] + r[0] * t, p[1] + r[1] * t


def straight_arc_metadata(a: tuple[float, float], b: tuple[float, float], reason: str) -> dict[str, Any]:
    return {
        "points": [a, b],
        "geometry": "straight_infinite_radius",
        "fit_status": reason,
        "radius_m": 0.0,
        "center": None,
        "sweep_deg": 0.0,
        "sample_count": 2,
    }


def circular_arc_from_tangents(
    a: tuple[float, float],
    start_tangent: tuple[float, float],
    b: tuple[float, float],
    end_tangent: tuple[float, float],
    min_samples: int,
) -> dict[str, Any]:
    t0 = normalize(start_tangent)
    t1 = normalize(end_tangent)
    if t0 == (0.0, 0.0) or t1 == (0.0, 0.0) or distance(a, b) <= 0.05:
        return straight_arc_metadata(a, b, "degenerate_tangent_or_chord")

    center = line_intersection(a, rotate90(t0), b, rotate90(t1))
    if center is None:
        return straight_arc_metadata(a, b, "parallel_tangent_infinite_radius")

    r0 = distance(center, a)
    r1 = distance(center, b)
    radius = (r0 + r1) * 0.5
    if radius <= 0.05:
        return straight_arc_metadata(a, b, "degenerate_radius")
    if abs(r0 - r1) > max(ARC_RADIUS_TOLERANCE_M, radius * 0.01):
        return straight_arc_metadata(a, b, "incompatible_tangent_endpoints")

    start_angle = math.atan2(a[1] - center[1], a[0] - center[0])
    end_angle = math.atan2(b[1] - center[1], b[0] - center[0])
    radial = normalize((a[0] - center[0], a[1] - center[1]))
    ccw_tangent = rotate90(radial)
    clockwise_tangent = (-ccw_tangent[0], -ccw_tangent[1])
    use_ccw = dot(ccw_tangent, t0) >= dot(clockwise_tangent, t0)
    sweep = end_angle - start_angle
    if use_ccw:
        while sweep < 0.0:
            sweep += math.tau
    else:
        while sweep > 0.0:
            sweep -= math.tau

    sweep_deg = math.degrees(sweep)
    if abs(sweep_deg) <= STRAIGHT_SWEEP_DEG or radius >= MAX_ARC_RADIUS_M:
        return straight_arc_metadata(a, b, "near_straight_infinite_radius")

    samples = max(min_samples, int(math.ceil(abs(sweep_deg) / ARC_SAMPLE_DEG)) + 1)
    points = []
    for i in range(samples):
        t = i / (samples - 1)
        angle = start_angle + sweep * t
        points.append((center[0] + math.cos(angle) * radius, center[1] + math.sin(angle) * radius))

    points[0] = a
    points[-1] = b
    return {
        "points": points,
        "geometry": "circular_arc",
        "fit_status": "exact_tangent_arc",
        "radius_m": radius,
        "center": center,
        "sweep_deg": sweep_deg,
        "sample_count": samples,
    }


def polyline_min_radius(points: list[tuple[float, float]]) -> float:
    radii: list[float] = []
    for i in range(1, len(points) - 1):
        a = points[i - 1]
        b = points[i]
        c = points[i + 1]
        ab = distance(a, b)
        bc = distance(b, c)
        ca = distance(c, a)
        denom = 2.0 * abs(cross((b[0] - a[0], b[1] - a[1]), (c[0] - a[0], c[1] - a[1])))
        if denom <= 1e-9:
            continue
        radius = (ab * bc * ca) / denom
        if radius > 0.0:
            radii.append(radius)
    return min(radii) if radii else 0.0


def bezier_tangent_fallback_arc(
    a: tuple[float, float],
    start_tangent: tuple[float, float],
    b: tuple[float, float],
    end_tangent: tuple[float, float],
    min_samples: int,
    reason: str,
) -> dict[str, Any]:
    t0 = normalize(start_tangent)
    t1 = normalize(end_tangent)
    chord = distance(a, b)
    if t0 == (0.0, 0.0) or t1 == (0.0, 0.0) or chord <= 0.05:
        return straight_arc_metadata(a, b, reason)
    samples = max(min_samples, 11)
    handle = chord * 0.42
    c1 = (a[0] + t0[0] * handle, a[1] + t0[1] * handle)
    c2 = (b[0] - t1[0] * handle, b[1] - t1[1] * handle)
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
    points[0] = a
    points[-1] = b
    return {
        "points": points,
        "geometry": "bezier_tangent_fallback",
        "fit_status": reason,
        "radius_m": polyline_min_radius(points),
        "center": None,
        "sweep_deg": math.degrees(angle_between(t0, t1)),
        "sample_count": samples,
    }


def connector_arc_from_tangents(
    a: tuple[float, float],
    start_tangent: tuple[float, float],
    b: tuple[float, float],
    end_tangent: tuple[float, float],
    min_samples: int,
) -> dict[str, Any]:
    arc = circular_arc_from_tangents(a, start_tangent, b, end_tangent, min_samples)
    if arc["fit_status"] in {
        "incompatible_tangent_endpoints",
        "parallel_tangent_infinite_radius",
        "degenerate_radius",
    }:
        return bezier_tangent_fallback_arc(
            a,
            start_tangent,
            b,
            end_tangent,
            min_samples,
            f"{arc['fit_status']}_bezier_fallback",
        )
    return arc


def arc_properties(arc: dict[str, Any]) -> dict[str, Any]:
    center = arc.get("center")
    design_min_radius = float(arc.get("design_min_radius_m") or 0.0)
    radius = float(arc["radius_m"])
    return {
        "arc_geometry": arc["geometry"],
        "arc_fit_status": arc["fit_status"],
        "arc_radius_m": round(radius, 3),
        "arc_center_x": round(float(center[0]), 3) if center is not None else None,
        "arc_center_z": round(float(center[1]), 3) if center is not None else None,
        "arc_sweep_deg": round(float(arc["sweep_deg"]), 3),
        "arc_sample_count": int(arc["sample_count"]),
        "arc_design_min_radius_m": round(design_min_radius, 3),
        "arc_radius_margin_m": round(radius - design_min_radius, 3) if design_min_radius > 0.0 else 0.0,
    }


def road_class_min_turn_radius(edge: dict[str, Any]) -> float:
    road_class = str(edge.get("road_class") or edge.get("highway") or "unclassified")
    return JUNCTION_TURN_MIN_RADIUS_BY_CLASS.get(road_class, JUNCTION_TURN_MIN_RADIUS_M)


def design_min_radius_for_connector(
    edge_a: dict[str, Any],
    edge_b: dict[str, Any],
    connector_kind: str,
) -> float:
    if connector_kind == "t_through":
        return 0.0
    width = max(float(edge_a.get("width_m") or 0.0), float(edge_b.get("width_m") or 0.0))
    return max(
        JUNCTION_TURN_MIN_RADIUS_M,
        width * JUNCTION_TURN_RADIUS_WIDTH_FACTOR,
        road_class_min_turn_radius(edge_a),
        road_class_min_turn_radius(edge_b),
    )


def enforce_design_min_radius(arc: dict[str, Any], min_radius: float) -> dict[str, Any]:
    arc["design_min_radius_m"] = min_radius
    return arc


def equalize_junction_trims(
    nodes: dict[str, dict[str, Any]],
    edges: dict[str, dict[str, Any]],
    trim_by_edge_node: dict[tuple[str, str], float],
    locked_trim_keys: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    equalized_nodes = 0
    raised = []
    lowered = []
    locked_trim_keys = locked_trim_keys or set()
    locked_node_ids = {
        node["node_id"]
        for node in nodes.values()
        if any((edge_id, node["node_id"]) in locked_trim_keys for edge_id in node.get("incident_edges", []))
    }
    for _iteration in range(4):
        for node in nodes.values():
            if node["degree"] < MIN_JUNCTION_DEGREE:
                continue
            if node["node_id"] in locked_node_ids:
                continue
            values = [trim_by_edge_node.get((edge_id, node["node_id"]), 0.0) for edge_id in node["incident_edges"]]
            if not values:
                continue
            desired_trim = max(values)
            if desired_trim <= 0.0:
                continue

            capacities = []
            for edge_id in node["incident_edges"]:
                edge = edges[edge_id]
                other_node_id = edge["to_node"] if edge["from_node"] == node["node_id"] else edge["from_node"]
                other_trim = trim_by_edge_node.get((edge_id, other_node_id), 0.0)
                capacities.append(max(0.0, float(edge["length_m"]) - 0.5 - other_trim))
            common_trim = min(desired_trim, min(capacities) if capacities else desired_trim)
            if common_trim <= 0.0:
                continue

            changed = False
            for edge_id in node["incident_edges"]:
                key = (edge_id, node["node_id"])
                old = trim_by_edge_node.get(key, 0.0)
                delta = common_trim - old
                if abs(delta) <= 1e-6:
                    continue
                trim_by_edge_node[key] = common_trim
                if delta > 0.0:
                    raised.append(delta)
                else:
                    lowered.append(-delta)
                changed = True
            if changed:
                equalized_nodes += 1
    return {
        "junction_common_trim_nodes": equalized_nodes,
        "junction_common_trim_raised": len(raised),
        "junction_common_trim_lowered": len(lowered),
        "junction_common_trim_max_raise_m": round(max(raised), 3) if raised else 0.0,
        "junction_common_trim_avg_raise_m": round(sum(raised) / len(raised), 3) if raised else 0.0,
        "junction_common_trim_max_lower_m": round(max(lowered), 3) if lowered else 0.0,
        "junction_common_trim_avg_lower_m": round(sum(lowered) / len(lowered), 3) if lowered else 0.0,
        "junction_common_trim_skipped_regularized_nodes": len(locked_node_ids),
    }


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


def read_optional_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return read_json(path)


def junction_area_by_node(junction_areas_doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for area in junction_areas_doc.get("junction_areas", []):
        node_id = str(area.get("node_id") or "")
        if node_id:
            indexed[node_id] = area
    return indexed


def corner_override_key(node_id: str, edge_ids: list[str]) -> tuple[str, tuple[str, str]]:
    a, b = sorted(str(edge_id) for edge_id in edge_ids)
    return node_id, (a, b)


def corner_override_index(overrides_doc: dict[str, Any]) -> tuple[dict[tuple[str, tuple[str, str]], dict[str, Any]], dict[str, Any]]:
    indexed: dict[tuple[str, tuple[str, str]], dict[str, Any]] = {}
    issue_counts: Counter[str] = Counter()
    raw_count = 0
    active_count = 0
    for item in overrides_doc.get("active_corner_optimizations", []):
        raw_count += 1
        if not bool(item.get("enabled", True)):
            issue_counts["disabled"] += 1
            continue
        node_id = str(item.get("node_id") or "")
        edge_ids = [str(item.get("from_edge_id") or ""), str(item.get("to_edge_id") or "")]
        if not node_id or not all(edge_ids):
            issue_counts["missing_node_or_edge_id"] += 1
            continue
        indexed[corner_override_key(node_id, edge_ids)] = item
        active_count += 1
    return indexed, {
        "corner_override_records": raw_count,
        "active_corner_overrides": active_count,
        "corner_override_issue_counts": dict(sorted(issue_counts.items())),
    }


def override_cut_m(override: dict[str, Any], fallback: float, edge_a: dict[str, Any], edge_b: dict[str, Any]) -> float:
    try:
        cut = float(override.get("suggested_cut_m") or override.get("cut_m") or fallback)
    except (TypeError, ValueError):
        cut = fallback
    cut = max(CORNER_MIN_CUT_M, cut)
    cut = min(cut, CORNER_MAX_CUT_M)
    cut = min(cut, float(edge_a["length_m"]) * CORNER_EDGE_LENGTH_FACTOR, float(edge_b["length_m"]) * CORNER_EDGE_LENGTH_FACTOR)
    return max(0.0, cut)


def reference_entry_pose_index(
    engineering_reference_doc: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    edges: dict[str, dict[str, Any]],
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    issue_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    raw_count = 0

    for pose in engineering_reference_doc.get("approach_entry_poses", []):
        raw_count += 1
        edge_id = str(pose.get("edge_id") or "")
        node_id = str(pose.get("node_id") or "")
        if not edge_id or not node_id:
            issue_counts["missing_edge_or_node_id"] += 1
            continue
        if edge_id not in edges:
            issue_counts["missing_graph_edge"] += 1
            continue
        if node_id not in nodes:
            issue_counts["missing_graph_node"] += 1
            continue
        if edge_id not in nodes[node_id].get("incident_edges", []):
            issue_counts["edge_not_incident_to_node"] += 1
            continue
        entry = pose.get("entry_xz") or []
        tangent = pose.get("tangent_out_xz") or []
        if len(entry) < 2 or len(tangent) < 2:
            issue_counts["missing_entry_geometry"] += 1
            continue
        try:
            entry_xz = (float(entry[0]), float(entry[1]))
            tangent_xz = normalize((float(tangent[0]), float(tangent[1])))
            entry_trim_m = max(0.0, float(pose.get("entry_trim_m") or 0.0))
        except (TypeError, ValueError):
            issue_counts["invalid_entry_geometry"] += 1
            continue
        if tangent_xz == (0.0, 0.0):
            issue_counts["zero_tangent"] += 1
            continue
        if entry_trim_m <= 0.0:
            issue_counts["zero_entry_trim"] += 1
            continue
        key = (edge_id, node_id)
        if key in indexed:
            issue_counts["duplicate_entry_pose_key"] += 1
        status_counts[str(pose.get("status") or "unknown")] += 1
        indexed[key] = {
            "pose_id": str(pose.get("pose_id") or ""),
            "junction_id": str(pose.get("junction_id") or ""),
            "edge_id": edge_id,
            "node_id": node_id,
            "entry_trim_m": entry_trim_m,
            "entry_xz": entry_xz,
            "tangent_out_xz": tangent_xz,
            "status": str(pose.get("status") or ""),
            "issues": [str(issue) for issue in (pose.get("issues") or [])],
        }

    return indexed, {
        "engineering_reference_entry_poses": raw_count,
        "regularized_entry_pose_trims": len(indexed),
        "regularized_entry_pose_status_counts": dict(sorted(status_counts.items())),
        "regularized_entry_pose_issue_counts": dict(sorted(issue_counts.items())),
    }


def endpoint_from_trim(
    *,
    edge: dict[str, Any],
    node: dict[str, Any],
    trim_m: float,
    regularized_pose: dict[str, Any] | None,
) -> tuple[tuple[float, float], tuple[float, float], str]:
    direction = direction_out(edge, node["node_id"])
    if regularized_pose is not None:
        regularized_trim = float(regularized_pose["entry_trim_m"])
        if abs(trim_m - regularized_trim) <= 0.05:
            return regularized_pose["entry_xz"], regularized_pose["tangent_out_xz"], "regularized_entry_pose"
        return (
            (float(node["x"]) + direction[0] * trim_m, float(node["z"]) + direction[1] * trim_m),
            direction,
            "regularized_scaled_for_edge_length",
        )
    return (
        (float(node["x"]) + direction[0] * trim_m, float(node["z"]) + direction[1] * trim_m),
        direction,
        "heuristic_trim",
    )


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


def optimize_centerlines(
    input_path: Path,
    output_path: Path,
    report_path: Path,
    area_id: str,
    junction_areas_path: Path | None = None,
    engineering_reference_path: Path | None = None,
    corner_overrides_path: Path | None = None,
) -> dict[str, Any]:
    graph = read_json(input_path)
    meta = graph["metadata"]
    origin_lon = float(meta["origin_lon"])
    origin_lat = float(meta["origin_lat"])
    edges = {edge["edge_id"]: edge for edge in graph["edges"]}
    nodes = {node["node_id"]: dict(node, _edges=edges) for node in graph["nodes"]}
    junction_areas_doc = read_optional_json(junction_areas_path)
    engineering_reference_doc = read_optional_json(engineering_reference_path)
    corner_overrides_doc = read_optional_json(corner_overrides_path)
    area_by_node = junction_area_by_node(junction_areas_doc)
    regularized_entry_by_key, regularization_metrics = reference_entry_pose_index(
        engineering_reference_doc,
        nodes,
        edges,
    )
    active_corner_overrides, corner_override_metrics = corner_override_index(corner_overrides_doc)
    locked_trim_keys = set(regularized_entry_by_key)

    trim_by_edge_node: dict[tuple[str, str], float] = {}
    trimmed_endpoint: dict[tuple[str, str], tuple[float, float]] = {}
    trimmed_tangent: dict[tuple[str, str], tuple[float, float]] = {}
    trimmed_endpoint_source: dict[tuple[str, str], str] = {}
    corner_nodes: dict[str, dict[str, Any]] = {}
    heuristic_trim_keys = 0
    for node in nodes.values():
        if node["degree"] < MIN_JUNCTION_DEGREE:
            continue
        for edge_id in node["incident_edges"]:
            edge = edges[edge_id]
            key = (edge_id, node["node_id"])
            regularized_pose = regularized_entry_by_key.get(key)
            if regularized_pose is not None:
                trim_by_edge_node[key] = max(trim_by_edge_node.get(key, 0.0), float(regularized_pose["entry_trim_m"]))
                continue
            d = direction_out(edge, node["node_id"])
            trim = trim_distance(edge, node, d)
            trim_by_edge_node[key] = max(trim_by_edge_node.get(key, 0.0), trim)
            heuristic_trim_keys += 1

    t_branch_trim_metrics = apply_t_junction_branch_trims(nodes, trim_by_edge_node, locked_trim_keys)

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
        override = active_corner_overrides.get(corner_override_key(node["node_id"], [edge_a_id, edge_b_id]))
        if override is not None:
            cut = override_cut_m(override, cut, edge_a, edge_b)
        if cut < CORNER_MIN_CUT_M:
            continue
        for edge_id in (edge_a_id, edge_b_id):
            key = (edge_id, node["node_id"])
            trim_by_edge_node[key] = max(trim_by_edge_node.get(key, 0.0), cut)
        corner_nodes[node["node_id"]] = {
            "edge_ids": [edge_a_id, edge_b_id],
            "turn_deg": turn_deg,
            "cut_m": cut,
            "optimization_source": "corner_optimization_transaction" if override is not None else "heuristic_degree2_connector_fillet",
            "corner_optimization_id": str((override or {}).get("corner_optimization_id") or ""),
            "corner_optimization_application_id": str((override or {}).get("application_id") or ""),
            "corner_optimization_candidate_id": str((override or {}).get("candidate_id") or ""),
            "corner_optimization_policy": str((override or {}).get("policy") or ""),
        }

    junction_common_trim_metrics = equalize_junction_trims(nodes, edges, trim_by_edge_node, locked_trim_keys)

    features: list[dict[str, Any]] = []
    kept_approaches = 0
    dropped_short = 0
    regularized_endpoint_exact = 0
    regularized_endpoint_scaled = 0
    for edge in graph["edges"]:
        points = edge_points(edge)
        start_key = (edge["edge_id"], edge["from_node"])
        end_key = (edge["edge_id"], edge["to_node"])
        start_trim = trim_by_edge_node.get(start_key, 0.0)
        end_trim = trim_by_edge_node.get(end_key, 0.0)
        start_trim, end_trim = scale_trims_for_length(points, start_trim, end_trim)
        trimmed = trim_endpoint(points, start_trim, end_trim)
        if not trimmed:
            dropped_short += 1
            continue
        if start_trim > 0.0:
            start_node = nodes[edge["from_node"]]
            endpoint, tangent, source = endpoint_from_trim(
                edge=edge,
                node=start_node,
                trim_m=start_trim,
                regularized_pose=regularized_entry_by_key.get(start_key),
            )
            trimmed[0] = endpoint
            trimmed_endpoint[start_key] = trimmed[0]
            trimmed_tangent[start_key] = tangent
            trimmed_endpoint_source[start_key] = source
            if source == "regularized_entry_pose":
                regularized_endpoint_exact += 1
            elif source == "regularized_scaled_for_edge_length":
                regularized_endpoint_scaled += 1
        if end_trim > 0.0:
            end_node = nodes[edge["to_node"]]
            endpoint, tangent, source = endpoint_from_trim(
                edge=edge,
                node=end_node,
                trim_m=end_trim,
                regularized_pose=regularized_entry_by_key.get(end_key),
            )
            trimmed[-1] = endpoint
            trimmed_endpoint[end_key] = trimmed[-1]
            trimmed_tangent[end_key] = tangent
            trimmed_endpoint_source[end_key] = source
            if source == "regularized_entry_pose":
                regularized_endpoint_exact += 1
            elif source == "regularized_scaled_for_edge_length":
                regularized_endpoint_scaled += 1
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
            "start_trim_source": trimmed_endpoint_source.get(start_key, "none"),
            "end_trim_source": trimmed_endpoint_source.get(end_key, "none"),
            "start_entry_pose_id": regularized_entry_by_key.get(start_key, {}).get("pose_id", ""),
            "end_entry_pose_id": regularized_entry_by_key.get(end_key, {}).get("pose_id", ""),
        }, origin_lon, origin_lat))

    corner_fillet_count = 0
    corner_turn_degrees: list[float] = []
    corner_arc_geometry_counts = Counter()
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
        direction_a = trimmed_tangent.get((edge_ids[0], node_id), direction_out(edge_a, node_id))
        direction_b = trimmed_tangent.get((edge_ids[1], node_id), direction_out(edge_b, node_id))
        arc = connector_arc_from_tangents(
            endpoints[0],
            (-direction_a[0], -direction_a[1]),
            endpoints[1],
            direction_b,
            CORNER_SAMPLES,
        )
        corner_arc_geometry_counts[str(arc["geometry"])] += 1
        props = {
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
            "corner_optimization_source": corner["optimization_source"],
            "corner_optimization_id": corner["corner_optimization_id"],
            "corner_optimization_application_id": corner["corner_optimization_application_id"],
            "corner_optimization_candidate_id": corner["corner_optimization_candidate_id"],
            "corner_optimization_policy": corner["corner_optimization_policy"],
            "oneway": False,
        }
        props.update(arc_properties(arc))
        features.append(feature(arc["points"], props, origin_lon, origin_lat))
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
    connector_arc_geometry_counts = Counter()
    connector_arc_fit_status_counts = Counter()
    for node in nodes.values():
        if node["degree"] < MIN_JUNCTION_DEGREE:
            continue
        center = (float(node["x"]), float(node["z"]))
        junction_area = area_by_node.get(node["node_id"], {})
        ends = []
        for edge_id in node["incident_edges"]:
            edge = edges[edge_id]
            d = trimmed_tangent.get((edge_id, node["node_id"]), direction_out(edge, node["node_id"]))
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
            arc = connector_arc_from_tangents(
                current["endpoint"],
                (-current["direction"][0], -current["direction"][1]),
                nxt["endpoint"],
                nxt["direction"],
                T_JUNCTION_SAMPLES if connector_kind.startswith("t_") else CONNECTOR_SAMPLES,
            )
            arc = enforce_design_min_radius(
                arc,
                design_min_radius_for_connector(current["edge"], nxt["edge"], connector_kind),
            )
            connector = arc["points"]
            connector_arc_geometry_counts[str(arc["geometry"])] += 1
            connector_arc_fit_status_counts[str(arc["fit_status"])] += 1
            if connector_kind.startswith("t_"):
                t_junction_connector_count += 1
            connector_style_counts[connector_kind] += 1
            props = {
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
                "regularized_junction_id": str(junction_area.get("junction_id") or ""),
                "junction_area_status": str(junction_area.get("status") or ""),
                "conflict_zone_radius_m": float(junction_area.get("conflict_zone_radius_m") or 0.0),
                "from_trim_source": trimmed_endpoint_source.get((current["edge"]["edge_id"], node["node_id"]), ""),
                "to_trim_source": trimmed_endpoint_source.get((nxt["edge"]["edge_id"], node["node_id"]), ""),
            }
            props.update(arc_properties(arc))
            features.append(feature(connector, props, origin_lon, origin_lat))
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
                "regularized_junction_id": str(junction_area.get("junction_id") or ""),
                "junction_area_status": str(junction_area.get("status") or ""),
                "from_trim_source": trimmed_endpoint_source.get((current["edge"]["edge_id"], node["node_id"]), ""),
                "to_trim_source": trimmed_endpoint_source.get((nxt["edge"]["edge_id"], node["node_id"]), ""),
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
            "source_junction_areas": str(junction_areas_path) if junction_areas_path and junction_areas_path.exists() else "",
            "source_engineering_reference": str(engineering_reference_path) if engineering_reference_path and engineering_reference_path.exists() else "",
            "source_corner_overrides": str(corner_overrides_path) if corner_overrides_path and corner_overrides_path.exists() else "",
            "strategy": "use regularized junction entry poses where available, trim approaches, add tangent circular-arc junction connectors and corner fillets, then extrude widths",
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
            "source_junction_areas": str(junction_areas_path) if junction_areas_path and junction_areas_path.exists() else "",
            "source_engineering_reference": str(engineering_reference_path) if engineering_reference_path and engineering_reference_path.exists() else "",
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
        "regularization_inputs": {
            "junction_areas_path": str(junction_areas_path) if junction_areas_path else "",
            "junction_areas_loaded": bool(junction_areas_doc),
            "junction_area_count": len(junction_areas_doc.get("junction_areas", [])),
            "engineering_reference_path": str(engineering_reference_path) if engineering_reference_path else "",
            "engineering_reference_loaded": bool(engineering_reference_doc),
            **regularization_metrics,
        },
        "counts": {
            "input_edges": len(graph["edges"]),
            "optimized_approaches": kept_approaches,
            "dropped_short_edges": dropped_short,
            "heuristic_junction_trim_keys": heuristic_trim_keys,
            "regularized_junction_nodes": len({node_id for _edge_id, node_id in regularized_entry_by_key}),
            "regularized_endpoint_exact": regularized_endpoint_exact,
            "regularized_endpoint_scaled_for_edge_length": regularized_endpoint_scaled,
            "junction_nodes": sum(1 for node in nodes.values() if node["degree"] >= MIN_JUNCTION_DEGREE),
            "junction_connectors": connector_count,
            "t_junctions": t_junction_count,
            "t_junction_connectors": t_junction_connector_count,
            "junction_movement_debug": len(movement_debug_features),
            "junction_through_movements": through_movement_count,
            "junction_turn_movements": turn_movement_count,
            "corner_fillet_nodes": len(corner_nodes),
            "corner_fillets": corner_fillet_count,
            "corner_transaction_fillets": sum(1 for corner in corner_nodes.values() if corner.get("optimization_source") == "corner_optimization_transaction"),
            "corner_heuristic_fillets": sum(1 for corner in corner_nodes.values() if corner.get("optimization_source") == "heuristic_degree2_connector_fillet"),
            "corner_circular_arcs": corner_arc_geometry_counts.get("circular_arc", 0),
            "corner_bezier_tangent_fallback": corner_arc_geometry_counts.get("bezier_tangent_fallback", 0),
            "corner_straight_infinite_radius": corner_arc_geometry_counts.get("straight_infinite_radius", 0),
            "output_features": len(features),
            **t_branch_trim_metrics,
            **junction_common_trim_metrics,
            **corner_override_metrics,
        },
        "junction_degree_counts": dict(sorted(connector_degrees.items())),
        "junction_connector_style_counts": dict(sorted(connector_style_counts.items())),
        "junction_connector_arc_geometry_counts": dict(sorted(connector_arc_geometry_counts.items())),
        "junction_connector_arc_fit_status_counts": dict(sorted(connector_arc_fit_status_counts.items())),
        "corner_arc_geometry_counts": dict(sorted(corner_arc_geometry_counts.items())),
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
            "Approach lines use regularized junction entry poses when engineering_reference_lines.json is available.",
            "Visible junction connectors stay in the centerline skeleton.",
            "Visible junction connectors and degree-2 corner fillets are sampled from tangent circular arcs where geometry allows it.",
            "If regularized entry poses are not compatible with a single circle, a tangent-continuous Bezier fallback is emitted and remains visible to QA.",
            "Near-straight through connectors are represented as straight infinite-radius arcs.",
            "Road-level through/turn movement curves are exported to a separate debug layer so they do not visually cross the road skeleton.",
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
    parser.add_argument("--junction-areas", default="")
    parser.add_argument("--engineering-reference", default="")
    parser.add_argument("--corner-overrides", default="")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    processed = root / "data" / "processed"
    input_path = Path(args.input) if args.input else root / "data" / "processed" / f"{args.area_id}_road_graph.json"
    output_path = Path(args.output) if args.output else root / "data" / "processed" / f"{args.area_id}_roads_optimized_centerlines.geojson"
    report_path = Path(args.report) if args.report else root / "reports" / f"{args.area_id}_optimized_centerlines_report.json"
    junction_areas_path = Path(args.junction_areas) if args.junction_areas else processed / f"{args.area_id}_junction_areas.json"
    engineering_reference_path = Path(args.engineering_reference) if args.engineering_reference else processed / f"{args.area_id}_engineering_reference_lines.json"
    corner_overrides_path = Path(args.corner_overrides) if args.corner_overrides else processed / f"{args.area_id}_corner_optimization_overrides.json"
    report = optimize_centerlines(
        input_path,
        output_path,
        report_path,
        args.area_id,
        junction_areas_path,
        engineering_reference_path,
        corner_overrides_path,
    )
    print(json.dumps({
        "area_id": args.area_id,
        "output": str(output_path),
        "report": str(report_path),
        "counts": report["counts"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
