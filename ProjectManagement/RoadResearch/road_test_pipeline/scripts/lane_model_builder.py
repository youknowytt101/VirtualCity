#!/usr/bin/env python3
"""Build lane_graph.json and OpenDRIVE-inspired junction connections.

This is the lane-level topology step described in the RoadResearch notes. It
consumes junction_semantics.json, emits lane centerlines, connection records,
laneLinks and tangent-continuous connector curves. It deliberately does not
generate junction surfaces; that stays in the later geometry layer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_LANE_WIDTH_M = 3.2
JUNCTION_TRIM_M = 8.0
CURVE_SAMPLE_COUNT = 9
SURFACE_STRATEGY_PENDING = "not_generated_layer3_lane_graph_only"
TEMPORARY_LANE_POLICY_ID = "temporary_all_roads_bidirectional_two_lane_v1"
TEMPORARY_TRAFFIC_SIDE = "left"
LANE_UPGRADE_GEOMETRY_APPLICATION_POLICY = "defer_lane_upgrade_overrides_keep_all_roads_bidirectional_two_lane_v1"
SELECTED_LANE_UPGRADE_GEOMETRY_APPLICATION_POLICY = "apply_selected_lane_upgrade_overrides_to_geometry_v1"
ALL_LANE_UPGRADE_GEOMETRY_APPLICATION_POLICY = "apply_all_lane_upgrade_overrides_to_geometry_v1"
LANE_UPGRADE_SYSTEM_ID = "LaneForge"
LANE_UPGRADE_OVERRIDE_SCHEMA = "lane_upgrade_system.active_overrides.v1"
LANE_BUNDLE_CENTERLINE_SMOOTHING_POLICY = "lane_bundle_centerline_smoothing_v1"
DERIVED_LANE_CENTERLINE_SMOOTHING_POLICY = "derived_lane_centerline_smoothing_v1"
DERIVED_SMOOTHING_MICRO_PROFILE = "micro_bend"
DERIVED_SMOOTHING_HARD_PROFILE = "hard_bend_lane_level_rounding"
DERIVED_SMOOTHING_MIN_ANGLE_DEG = 0.5
DERIVED_SMOOTHING_MAX_ANGLE_DEG = 3.0
DERIVED_SMOOTHING_MIN_SOURCE_OFFSET_M = 0.05
DERIVED_SMOOTHING_MAX_SOURCE_OFFSET_M = 0.75
DERIVED_SMOOTHING_MIN_SEGMENT_M = 8.0
DERIVED_SMOOTHING_CUT_RATIO = 0.45
DERIVED_SMOOTHING_MAX_CUT_M = 24.0
DERIVED_SMOOTHING_SAMPLE_COUNT = 5
DERIVED_SMOOTHING_MAX_DERIVATION_OFFSET_M = 0.35
DERIVED_HARD_SMOOTHING_MIN_ANGLE_DEG = 12.0
DERIVED_HARD_SMOOTHING_MAX_ANGLE_DEG = 120.0
DERIVED_HARD_SMOOTHING_MIN_SEGMENT_M = 1.5
DERIVED_HARD_SMOOTHING_SOURCE_OFFSET_POLICY = "diagnostic_only_local_derivation_limited"
DERIVED_HARD_SMOOTHING_CUT_RATIO = 0.32
DERIVED_HARD_SMOOTHING_MAX_CUT_M = 9.0
DERIVED_HARD_SMOOTHING_SAMPLE_COUNT = 9
DERIVED_HARD_SMOOTHING_MAX_DERIVATION_OFFSET_M = 2.6
DERIVED_HARD_SMOOTHING_LOW_RADIUS_MAX_CUT_RATIO = 0.90
DERIVED_SMOOTHING_WINDOW_OVERLAP_EPSILON_M = 0.05
UNIFIED_LANE_GEOMETRY_ROUNDING_STYLE_ID = "unified_lane_geometry_rounding_style_v1"
UNIFIED_ROUNDING_PRIMARY_CURVE_FAMILY = "tangent_circular_arc"
UNIFIED_ROUNDING_STRAIGHT_CURVE_FAMILY = "straight_infinite_radius"
UNIFIED_ROUNDING_SAMPLE_STRATEGY = "arc_angle_limited_min_profile_samples"
UNIFIED_ROUNDING_SAMPLE_ANGLE_DEG = 5.0
UNIFIED_ROUNDING_RADIUS_TOLERANCE_M = 0.05
UNIFIED_ROUNDING_MAX_ARC_RADIUS_M = 10000.0
UNIFIED_ROUNDING_STRAIGHT_SWEEP_DEG = 0.1
LANE_LEVEL_CONTINUITY_MIN_RADIUS_M = DEFAULT_LANE_WIDTH_M
LANE_LEVEL_CONTINUITY_MIN_RADIUS_EPSILON_M = 0.15
LANE_LEVEL_CONTINUITY_MAX_EXTRA_TRIM_M = 8.0
DIRECT_CONNECTOR_CONTINUITY_POLICY = "degree2_connector_through_continuity_v1"
DIRECT_CONNECTOR_MICRO_SEAM_POLICY = "degree2_connector_micro_seam_endpoint_snap_v1"
DIRECT_CONNECTOR_PHYSICAL_LANE_GROUP_POLICY = "degree2_connector_physical_lane_group_v1"
DIRECT_CONNECTOR_MAX_TURN_DEG = 18.0
DIRECT_CONNECTOR_MAX_ENDPOINT_GAP_M = 2.0
DIRECT_CONNECTOR_MICRO_SEAM_SNAP_M = 0.10
DIRECT_CONNECTOR_PHYSICAL_LANE_MAX_TURN_DEG = 5.0
DIRECT_CONNECTOR_PHYSICAL_LANE_MAX_ENDPOINT_GAP_M = DIRECT_CONNECTOR_MICRO_SEAM_SNAP_M
LANE_CENTERLINE_MICRO_SEGMENT_CLEANUP_POLICY = "lane_centerline_micro_segment_cleanup_v1"
LANE_CENTERLINE_MICRO_SEGMENT_M = 0.5
LANE_CENTERLINE_MICRO_RUN_MAX_SPAN_M = 1.25
LANE_CENTERLINE_LOW_RADIUS_SAMPLED_ARC_CLEANUP_POLICY = "lane_centerline_low_radius_sampled_arc_cleanup_v1"
LANE_CENTERLINE_LOW_RADIUS_SAMPLE_SEGMENT_M = 1.0
LANE_CENTERLINE_LOW_RADIUS_RUN_MAX_SPAN_M = 4.0
LANE_CENTERLINE_LOW_RADIUS_MIN_RADIUS_M = DEFAULT_LANE_WIDTH_M * 1.5


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


def nearest_station_on_polyline(points: list[tuple[float, float]], query: tuple[float, float]) -> float:
    if len(points) < 2:
        return 0.0
    best_distance = float("inf")
    best_station = 0.0
    station = 0.0
    for i in range(len(points) - 1):
        ax, az = points[i]
        bx, bz = points[i + 1]
        vx = bx - ax
        vz = bz - az
        seg_len_sq = vx * vx + vz * vz
        if seg_len_sq <= 1e-12:
            continue
        t = max(0.0, min(1.0, ((query[0] - ax) * vx + (query[1] - az) * vz) / seg_len_sq))
        px = ax + vx * t
        pz = az + vz * t
        d = distance(query, (px, pz))
        seg_len = math.sqrt(seg_len_sq)
        if d < best_distance:
            best_distance = d
            best_station = station + seg_len * t
        station += seg_len
    return best_station


def longitudinal_trim_to_point(
    points: list[tuple[float, float]],
    side: str,
    point: tuple[float, float],
) -> float:
    station = nearest_station_on_polyline(points, point)
    if side == "end":
        return max(0.0, polyline_length(points) - station)
    return max(0.0, station)


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


def line_intersection(
    p: tuple[float, float],
    r: tuple[float, float],
    q: tuple[float, float],
    s: tuple[float, float],
) -> tuple[float, float] | None:
    denom = cross(r, s)
    if abs(denom) <= 1e-9:
        return None
    qp = (q[0] - p[0], q[1] - p[1])
    t = cross(qp, s) / denom
    return p[0] + r[0] * t, p[1] + r[1] * t


def angle_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    a_len = math.sqrt(a[0] * a[0] + a[1] * a[1])
    b_len = math.sqrt(b[0] * b[0] + b[1] * b[1])
    if a_len <= 1e-9 or b_len <= 1e-9:
        return 0.0
    value = max(-1.0, min(1.0, dot(a, b) / (a_len * b_len)))
    return math.degrees(math.acos(value))


def point_segment_distance(
    point: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    vx = b[0] - a[0]
    vz = b[1] - a[1]
    seg_len_sq = vx * vx + vz * vz
    if seg_len_sq <= 1e-12:
        return distance(point, a)
    t = max(0.0, min(1.0, ((point[0] - a[0]) * vx + (point[1] - a[1]) * vz) / seg_len_sq))
    projected = (a[0] + vx * t, a[1] + vz * t)
    return distance(point, projected)


def point_polyline_distance(point: tuple[float, float], points: list[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    return min(point_segment_distance(point, points[i], points[i + 1]) for i in range(len(points) - 1))


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
                "rounding_style_id": str(props.get("rounding_style_id") or UNIFIED_LANE_GEOMETRY_ROUNDING_STYLE_ID),
                "rounding_curve_family": str(props.get("rounding_curve_family") or props.get("arc_geometry") or UNIFIED_ROUNDING_PRIMARY_CURVE_FAMILY),
                "rounding_sample_strategy": str(props.get("rounding_sample_strategy") or UNIFIED_ROUNDING_SAMPLE_STRATEGY),
                "arc_geometry": str(props.get("arc_geometry") or ""),
                "arc_fit_status": str(props.get("arc_fit_status") or ""),
                "arc_radius_m": float(props.get("arc_radius_m") or 0.0),
                "arc_sweep_deg": float(props.get("arc_sweep_deg") or 0.0),
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


def load_lane_upgrade_overrides(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {
            "path": "",
            "schema": LANE_UPGRADE_OVERRIDE_SCHEMA,
            "active_upgrades_by_road": {},
            "ignored": [],
        }
    data = read_json(path)
    active_by_road: dict[str, dict[str, Any]] = {}
    ignored: list[dict[str, Any]] = []
    for index, item in enumerate(data.get("active_upgrades", [])):
        road_id = str(item.get("road_id") or item.get("edge_id") or "")
        try:
            target = int(item.get("target_physical_lane_count") or item.get("target_lane_count") or 0)
        except (TypeError, ValueError):
            target = 0
        enabled = bool(item.get("enabled", True))
        if not enabled or not road_id or target < 1 or target > 4:
            ignored.append({
                "index": index,
                "road_id": road_id,
                "target_physical_lane_count": target,
                "reason": "disabled_or_invalid_road_id_or_target_lane_count",
            })
            continue
        active_by_road[road_id] = {
            "upgrade_id": str(item.get("upgrade_id") or item.get("transaction_id") or f"lane_upgrade_{index:04d}"),
            "road_id": road_id,
            "target_physical_lane_count": target,
            "distribution_policy": str(item.get("distribution_policy") or "balanced_bidirectional_left_traffic_v1"),
            "source": str(item.get("source") or "manual_lane_upgrade_override"),
            "reason": str(item.get("reason") or ""),
            "version": str(item.get("version") or ""),
        }
    return {
        "path": str(path),
        "schema": str((data.get("metadata") or {}).get("schema") or data.get("schema") or LANE_UPGRADE_OVERRIDE_SCHEMA),
        "active_upgrades_by_road": active_by_road,
        "ignored": ignored,
    }


def apply_lane_upgrade_overrides(
    edges: list[dict[str, Any]],
    active_upgrades_by_road: dict[str, dict[str, Any]],
    *,
    apply_to_geometry: bool = False,
    apply_road_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    updated: list[dict[str, Any]] = []
    applied: list[str] = []
    deferred: list[str] = []
    missing = set(active_upgrades_by_road)
    selected_road_ids = {str(road_id) for road_id in (apply_road_ids or set()) if str(road_id)}
    for edge in edges:
        item = dict(edge)
        edge_id = str(edge.get("edge_id") or "")
        upgrade = active_upgrades_by_road.get(edge_id)
        if upgrade:
            should_apply = apply_to_geometry or edge_id in selected_road_ids
            if should_apply:
                item["lane_upgrade"] = dict(upgrade)
                applied.append(edge_id)
            else:
                deferred.append(edge_id)
            missing.discard(edge_id)
        elif edge_id in selected_road_ids:
            missing.add(edge_id)
        updated.append(item)
    if apply_to_geometry:
        policy = ALL_LANE_UPGRADE_GEOMETRY_APPLICATION_POLICY
    elif selected_road_ids:
        policy = SELECTED_LANE_UPGRADE_GEOMETRY_APPLICATION_POLICY
    else:
        policy = LANE_UPGRADE_GEOMETRY_APPLICATION_POLICY
    return updated, {
        "applied_road_ids": sorted(applied),
        "deferred_road_ids": sorted(deferred),
        "missing_road_ids": sorted(missing),
        "requested_apply_road_ids": sorted(selected_road_ids),
        "geometry_application_policy": policy,
    }


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
    factors = station_factors(points)
    offsets = [lerp(offset_start, offset_end, factor) for factor in factors]
    shifted_segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for i in range(len(points) - 1):
        direction = normalize((points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1]))
        if direction == (0.0, 0.0):
            shifted_segments.append((points[i], points[i + 1]))
            continue
        normal = rotate90(direction)
        shifted_segments.append((
            (points[i][0] + normal[0] * offsets[i], points[i][1] + normal[1] * offsets[i]),
            (points[i + 1][0] + normal[0] * offsets[i + 1], points[i + 1][1] + normal[1] * offsets[i + 1]),
        ))

    shifted: list[tuple[float, float]] = [shifted_segments[0][0]]
    for i in range(1, len(points) - 1):
        prev_a, prev_b = shifted_segments[i - 1]
        next_a, next_b = shifted_segments[i]
        prev_dir = (prev_b[0] - prev_a[0], prev_b[1] - prev_a[1])
        next_dir = (next_b[0] - next_a[0], next_b[1] - next_a[1])
        intersection = line_intersection(prev_a, prev_dir, next_a, next_dir)
        if intersection is None:
            intersection = ((prev_b[0] + next_a[0]) * 0.5, (prev_b[1] + next_a[1]) * 0.5)
        max_miter_m = max(20.0, abs(offsets[i]) * 8.0)
        if distance(points[i], intersection) > max_miter_m:
            intersection = ((prev_b[0] + next_a[0]) * 0.5, (prev_b[1] + next_a[1]) * 0.5)
        shifted.append(intersection)
    shifted.append(shifted_segments[-1][1])
    return shifted


def direction_out_of_node(edge: dict[str, Any], node_id: str) -> tuple[float, float]:
    pts = edge_points(edge)
    if node_id == edge["from_node"]:
        return normalize((pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]))
    return normalize((pts[-2][0] - pts[-1][0], pts[-2][1] - pts[-1][1]))


def lane_counts(edge: dict[str, Any]) -> tuple[int, int]:
    upgrade = edge.get("lane_upgrade") or {}
    target = int(upgrade.get("target_physical_lane_count") or 0)
    if target > 0:
        target = max(1, min(4, target))
        if target == 1:
            return 1, 1
        forward = (target + 1) // 2
        backward = target - forward
        return max(1, forward), max(1, backward)
    return 1, 1


def edge_has_shared_single_lane_upgrade(edge: dict[str, Any]) -> bool:
    upgrade = edge.get("lane_upgrade") or {}
    return int(upgrade.get("target_physical_lane_count") or 0) == 1


def directional_lane_offset(
    direction: str,
    index: int,
    lane_width_m: float,
    *,
    shared_single_lane: bool = False,
) -> float:
    if shared_single_lane:
        return 0.0
    sign = 1.0 if TEMPORARY_TRAFFIC_SIDE == "left" else -1.0
    if direction == "forward":
        return sign * (index + 0.5) * lane_width_m
    return -sign * (index + 0.5) * lane_width_m


def lane_offset(index: int, count: int, side: int, lane_width_m: float) -> float:
    return side * ((index + 0.5) - count * 0.5) * lane_width_m


def edge_width_profile(edge: dict[str, Any], generated_lane_count: int) -> dict[str, Any]:
    lane_width = DEFAULT_LANE_WIDTH_M
    upgrade = edge.get("lane_upgrade") or {}
    physical_lane_count = int(upgrade.get("target_physical_lane_count") or generated_lane_count)
    physical_lane_count = max(1, physical_lane_count)
    road_width = physical_lane_count * lane_width
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


def lane_source(edge: dict[str, Any]) -> str:
    if edge.get("lane_upgrade"):
        return "lane_upgrade_system_manual_override"
    return "temporary_bidirectional_two_lane_policy"


def lane_policy_issues(edge: dict[str, Any]) -> list[str]:
    issues = ["source_direction_overridden_by_temporary_bidirectional_policy"]
    upgrade = edge.get("lane_upgrade") or {}
    if upgrade:
        issues.append("lane_count_set_by_lane_upgrade_transaction")
        if int(upgrade.get("target_physical_lane_count") or 0) == 1:
            issues.append("single_physical_lane_represented_as_bidirectional_shared_lane")
    return issues


def lane_upgrade_fields(edge: dict[str, Any]) -> dict[str, Any]:
    upgrade = edge.get("lane_upgrade") or {}
    if not upgrade:
        return {
            "lane_upgrade_id": "",
            "lane_upgrade_target_physical_lane_count": 0,
            "lane_upgrade_distribution_policy": "",
            "physical_lane_shared": False,
        }
    return {
        "lane_upgrade_id": str(upgrade.get("upgrade_id") or ""),
        "lane_upgrade_target_physical_lane_count": int(upgrade.get("target_physical_lane_count") or 0),
        "lane_upgrade_distribution_policy": str(upgrade.get("distribution_policy") or ""),
        "physical_lane_shared": edge_has_shared_single_lane_upgrade(edge),
    }


def lane_geometry_rounding_style_config() -> dict[str, Any]:
    return {
        "style_id": UNIFIED_LANE_GEOMETRY_ROUNDING_STYLE_ID,
        "primary_curve_family": UNIFIED_ROUNDING_PRIMARY_CURVE_FAMILY,
        "straight_curve_family": UNIFIED_ROUNDING_STRAIGHT_CURVE_FAMILY,
        "sample_strategy": UNIFIED_ROUNDING_SAMPLE_STRATEGY,
        "sample_angle_deg": UNIFIED_ROUNDING_SAMPLE_ANGLE_DEG,
        "lane_level_straight_sweep_deg": UNIFIED_ROUNDING_STRAIGHT_SWEEP_DEG,
        "lane_level_continuity_min_radius_m": LANE_LEVEL_CONTINUITY_MIN_RADIUS_M,
        "lane_level_continuity_regularization": "enabled_for_offset_corner_fillets_below_min_radius",
        "min_samples": {
            "optimized_corner_fillet": DERIVED_HARD_SMOOTHING_SAMPLE_COUNT,
            DERIVED_SMOOTHING_MICRO_PROFILE: DERIVED_SMOOTHING_SAMPLE_COUNT,
            DERIVED_SMOOTHING_HARD_PROFILE: DERIVED_HARD_SMOOTHING_SAMPLE_COUNT,
        },
        "endpoint_lock": "preserve_lane_endpoints_and_trim_local_bend_windows",
        "semantic_boundary": "geometry_style_only_no_traffic_semantics_inference",
        "truth_layers_unchanged": ["raw", "repaired", "canonical", "road_graph"],
    }


def smoothing_policy_config() -> dict[str, Any]:
    return {
        "policy": DERIVED_LANE_CENTERLINE_SMOOTHING_POLICY,
        "rounding_style_id": UNIFIED_LANE_GEOMETRY_ROUNDING_STYLE_ID,
        "rounding_style": lane_geometry_rounding_style_config(),
        "curve_family": UNIFIED_ROUNDING_PRIMARY_CURVE_FAMILY,
        "sample_strategy": UNIFIED_ROUNDING_SAMPLE_STRATEGY,
        "sample_angle_deg": UNIFIED_ROUNDING_SAMPLE_ANGLE_DEG,
        "profiles": [DERIVED_SMOOTHING_MICRO_PROFILE, DERIVED_SMOOTHING_HARD_PROFILE],
        "lane_bundle_centerline_smoothing_policy": LANE_BUNDLE_CENTERLINE_SMOOTHING_POLICY,
        "lane_bundle_min_base_radius_policy": "max_abs_lane_offset_plus_lane_min_radius",
        "min_angle_deg": DERIVED_SMOOTHING_MIN_ANGLE_DEG,
        "max_angle_deg": DERIVED_SMOOTHING_MAX_ANGLE_DEG,
        "min_source_offset_m": DERIVED_SMOOTHING_MIN_SOURCE_OFFSET_M,
        "max_source_offset_m": DERIVED_SMOOTHING_MAX_SOURCE_OFFSET_M,
        "min_adjacent_segment_m": DERIVED_SMOOTHING_MIN_SEGMENT_M,
        "cut_ratio": DERIVED_SMOOTHING_CUT_RATIO,
        "max_cut_m": DERIVED_SMOOTHING_MAX_CUT_M,
        "sample_count": DERIVED_SMOOTHING_SAMPLE_COUNT,
        "max_derivation_offset_m": DERIVED_SMOOTHING_MAX_DERIVATION_OFFSET_M,
        "hard_bend_min_angle_deg": DERIVED_HARD_SMOOTHING_MIN_ANGLE_DEG,
        "hard_bend_max_angle_deg": DERIVED_HARD_SMOOTHING_MAX_ANGLE_DEG,
        "hard_bend_min_adjacent_segment_m": DERIVED_HARD_SMOOTHING_MIN_SEGMENT_M,
        "hard_bend_source_offset_policy": DERIVED_HARD_SMOOTHING_SOURCE_OFFSET_POLICY,
        "hard_bend_cut_ratio": DERIVED_HARD_SMOOTHING_CUT_RATIO,
        "hard_bend_max_cut_m": DERIVED_HARD_SMOOTHING_MAX_CUT_M,
        "hard_bend_sample_count": DERIVED_HARD_SMOOTHING_SAMPLE_COUNT,
        "hard_bend_max_derivation_offset_m": DERIVED_HARD_SMOOTHING_MAX_DERIVATION_OFFSET_M,
        "hard_bend_min_arc_radius_m": LANE_CENTERLINE_LOW_RADIUS_MIN_RADIUS_M,
        "hard_bend_low_radius_max_cut_ratio": DERIVED_HARD_SMOOTHING_LOW_RADIUS_MAX_CUT_RATIO,
        "hard_bend_low_radius_fallback": "straight_chord_when_min_radius_arc_is_infeasible",
        "short_connector_hard_bend_smoothing": "enabled_when_local_derivation_offset_stays_within_limit",
        "adjacent_bend_chain_smoothing": "enabled_with_non_overlapping_cut_windows",
        "low_radius_sampled_arc_cleanup": "enabled_before_derived_bend_rounding",
        "truth_layers_unchanged": ["raw", "repaired", "canonical", "road_graph"],
    }


def small_bend_metrics(
    prev_point: tuple[float, float],
    point: tuple[float, float],
    next_point: tuple[float, float],
) -> dict[str, float]:
    prev_vector = (point[0] - prev_point[0], point[1] - prev_point[1])
    next_vector = (next_point[0] - point[0], next_point[1] - point[1])
    prev_len = distance(prev_point, point)
    next_len = distance(point, next_point)
    angle_deg = angle_between(prev_vector, next_vector)
    source_offset = point_segment_distance(point, prev_point, next_point)
    return {
        "angle_deg": angle_deg,
        "source_offset_m": source_offset,
        "prev_segment_m": prev_len,
        "next_segment_m": next_len,
    }


def smoothing_profile_or_skip_reason(metrics: dict[str, float]) -> tuple[str, str]:
    if metrics["angle_deg"] < DERIVED_SMOOTHING_MIN_ANGLE_DEG:
        return "", "below_angle_threshold"
    if metrics["source_offset_m"] < DERIVED_SMOOTHING_MIN_SOURCE_OFFSET_M:
        return "", "below_source_offset_threshold"
    has_micro_length = (
        metrics["prev_segment_m"] >= DERIVED_SMOOTHING_MIN_SEGMENT_M
        and metrics["next_segment_m"] >= DERIVED_SMOOTHING_MIN_SEGMENT_M
    )
    if (
        has_micro_length
        and
        metrics["angle_deg"] <= DERIVED_SMOOTHING_MAX_ANGLE_DEG
        and metrics["source_offset_m"] <= DERIVED_SMOOTHING_MAX_SOURCE_OFFSET_M
    ):
        return DERIVED_SMOOTHING_MICRO_PROFILE, ""
    if metrics["angle_deg"] < DERIVED_HARD_SMOOTHING_MIN_ANGLE_DEG:
        return "", "above_angle_threshold"
    if metrics["angle_deg"] > DERIVED_HARD_SMOOTHING_MAX_ANGLE_DEG:
        return "", "above_angle_threshold"
    if (
        metrics["prev_segment_m"] < DERIVED_HARD_SMOOTHING_MIN_SEGMENT_M
        or metrics["next_segment_m"] < DERIVED_HARD_SMOOTHING_MIN_SEGMENT_M
    ):
        return "", "short_adjacent_segment"
    return DERIVED_SMOOTHING_HARD_PROFILE, ""


def collapse_micro_segment_runs(
    points: list[tuple[float, float]],
    *,
    min_segment_m: float = LANE_CENTERLINE_MICRO_SEGMENT_M,
    max_run_span_m: float = LANE_CENTERLINE_MICRO_RUN_MAX_SPAN_M,
) -> tuple[list[tuple[float, float]], dict[str, Any]]:
    if len(points) < 4:
        return points, {
            "policy": LANE_CENTERLINE_MICRO_SEGMENT_CLEANUP_POLICY,
            "runs_collapsed": 0,
            "removed_points": 0,
            "max_run_span_m": 0.0,
        }

    segment_lengths = [distance(points[index], points[index + 1]) for index in range(len(points) - 1)]
    cleaned: list[tuple[float, float]] = []
    runs_collapsed = 0
    removed_points = 0
    max_observed_span = 0.0
    index = 0
    while index < len(points):
        if index >= len(points) - 1:
            cleaned.append(points[index])
            break

        if segment_lengths[index] < min_segment_m:
            start_index = index
            end_index = index + 1
            while end_index < len(points) - 1 and segment_lengths[end_index] < min_segment_m:
                end_index += 1
            run_segments = end_index - start_index
            span = distance(points[start_index], points[end_index])
            touches_endpoint = start_index == 0 or end_index == len(points) - 1
            if run_segments >= 2 and span <= max_run_span_m and not touches_endpoint:
                run_points = points[start_index : end_index + 1]
                representative = (
                    sum(point[0] for point in run_points) / len(run_points),
                    sum(point[1] for point in run_points) / len(run_points),
                )
                cleaned.append(representative)
                runs_collapsed += 1
                removed_points += len(run_points) - 1
                max_observed_span = max(max_observed_span, span)
                index = end_index + 1
                continue

        cleaned.append(points[index])
        index += 1

    return cleaned, {
        "policy": LANE_CENTERLINE_MICRO_SEGMENT_CLEANUP_POLICY,
        "runs_collapsed": runs_collapsed,
        "removed_points": removed_points,
        "max_run_span_m": round(max_observed_span, 6),
        "min_segment_m": min_segment_m,
        "max_run_span_threshold_m": max_run_span_m,
    }


def circumradius_or_inf(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> float:
    side_a = distance(b, c)
    side_b = distance(a, c)
    side_c = distance(a, b)
    area_twice = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
    if area_twice <= 1e-9:
        return float("inf")
    return side_a * side_b * side_c / (2.0 * area_twice)


def collapse_low_radius_sampled_arc_runs(
    points: list[tuple[float, float]],
    *,
    max_sample_segment_m: float = LANE_CENTERLINE_LOW_RADIUS_SAMPLE_SEGMENT_M,
    max_run_span_m: float = LANE_CENTERLINE_LOW_RADIUS_RUN_MAX_SPAN_M,
    min_radius_m: float = LANE_CENTERLINE_LOW_RADIUS_MIN_RADIUS_M,
) -> tuple[list[tuple[float, float]], dict[str, Any]]:
    if len(points) < 5:
        return points, {
            "policy": LANE_CENTERLINE_LOW_RADIUS_SAMPLED_ARC_CLEANUP_POLICY,
            "runs_collapsed": 0,
            "removed_points": 0,
            "max_run_span_m": 0.0,
            "min_radius_m": min_radius_m,
        }

    segment_lengths = [distance(points[index], points[index + 1]) for index in range(len(points) - 1)]
    bad_indices: list[int] = []
    min_observed_radius = float("inf")
    for index in range(1, len(points) - 1):
        if max(segment_lengths[index - 1], segment_lengths[index]) > max_sample_segment_m:
            continue
        radius = circumradius_or_inf(points[index - 1], points[index], points[index + 1])
        if radius < min_radius_m:
            bad_indices.append(index)
            min_observed_radius = min(min_observed_radius, radius)

    if not bad_indices:
        return points, {
            "policy": LANE_CENTERLINE_LOW_RADIUS_SAMPLED_ARC_CLEANUP_POLICY,
            "runs_collapsed": 0,
            "removed_points": 0,
            "max_run_span_m": 0.0,
            "min_radius_m": min_radius_m,
        }

    groups: list[list[int]] = []
    current: list[int] = []
    for index in bad_indices:
        if not current or index == current[-1] + 1:
            current.append(index)
        else:
            groups.append(current)
            current = [index]
    if current:
        groups.append(current)

    collapse_ranges: list[tuple[int, int]] = []
    max_observed_span = 0.0
    for group in groups:
        if len(group) < 2:
            continue
        start_index = max(1, group[0] - 1)
        end_index = min(len(points) - 2, group[-1] + 1)
        span = distance(points[start_index], points[end_index])
        if span > max_run_span_m:
            continue
        collapse_ranges.append((start_index, end_index))
        max_observed_span = max(max_observed_span, span)

    if not collapse_ranges:
        return points, {
            "policy": LANE_CENTERLINE_LOW_RADIUS_SAMPLED_ARC_CLEANUP_POLICY,
            "runs_collapsed": 0,
            "removed_points": 0,
            "max_run_span_m": 0.0,
            "min_radius_m": min_radius_m,
            "min_observed_radius_m": round(min_observed_radius, 6) if min_observed_radius < float("inf") else 0.0,
        }

    cleaned: list[tuple[float, float]] = []
    removed_points = 0
    range_index = 0
    index = 0
    while index < len(points):
        if range_index < len(collapse_ranges) and index == collapse_ranges[range_index][0]:
            start_index, end_index = collapse_ranges[range_index]
            run_points = points[start_index : end_index + 1]
            representative = (
                sum(point[0] for point in run_points) / len(run_points),
                sum(point[1] for point in run_points) / len(run_points),
            )
            cleaned.append(representative)
            removed_points += len(run_points) - 1
            index = end_index + 1
            range_index += 1
            continue
        cleaned.append(points[index])
        index += 1

    original_min_radius = polyline_min_radius_m(points)
    cleaned_min_radius = polyline_min_radius_m(cleaned)
    if (
        original_min_radius > 0.0
        and cleaned_min_radius > 0.0
        and cleaned_min_radius + 1e-6 < original_min_radius
    ):
        return points, {
            "policy": LANE_CENTERLINE_LOW_RADIUS_SAMPLED_ARC_CLEANUP_POLICY,
            "runs_collapsed": 0,
            "removed_points": 0,
            "max_run_span_m": 0.0,
            "min_radius_m": min_radius_m,
            "min_observed_radius_m": round(min_observed_radius, 6) if min_observed_radius < float("inf") else 0.0,
            "cleanup_rejected_reason": "cleanup_would_reduce_min_radius",
            "rejected_runs": len(collapse_ranges),
            "rejected_removed_points": removed_points,
            "rejected_min_radius_m": round(cleaned_min_radius, 6),
            "source_min_radius_m": round(original_min_radius, 6),
            "max_sample_segment_m": max_sample_segment_m,
            "max_run_span_threshold_m": max_run_span_m,
        }

    return cleaned, {
        "policy": LANE_CENTERLINE_LOW_RADIUS_SAMPLED_ARC_CLEANUP_POLICY,
        "runs_collapsed": len(collapse_ranges),
        "removed_points": removed_points,
        "max_run_span_m": round(max_observed_span, 6),
        "min_radius_m": min_radius_m,
        "min_observed_radius_m": round(min_observed_radius, 6) if min_observed_radius < float("inf") else 0.0,
        "max_sample_segment_m": max_sample_segment_m,
        "max_run_span_threshold_m": max_run_span_m,
    }


def point_lerp(a: tuple[float, float], b: tuple[float, float], t: float) -> tuple[float, float]:
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def straight_rounding_curve_record(
    a: tuple[float, float],
    b: tuple[float, float],
    reason: str,
) -> dict[str, Any]:
    return {
        "points": [a, b],
        "curve_family": UNIFIED_ROUNDING_STRAIGHT_CURVE_FAMILY,
        "arc_geometry": UNIFIED_ROUNDING_STRAIGHT_CURVE_FAMILY,
        "arc_fit_status": reason,
        "arc_radius_m": 0.0,
        "arc_center": None,
        "arc_sweep_deg": 0.0,
        "sample_count": 2,
    }


def tangent_circular_arc_record(
    a: tuple[float, float],
    start_tangent: tuple[float, float],
    b: tuple[float, float],
    end_tangent: tuple[float, float],
    min_samples: int,
) -> dict[str, Any]:
    t0 = normalize(start_tangent)
    t1 = normalize(end_tangent)
    if t0 == (0.0, 0.0) or t1 == (0.0, 0.0) or distance(a, b) <= 0.05:
        return straight_rounding_curve_record(a, b, "degenerate_tangent_or_chord")

    center = line_intersection(a, rotate90(t0), b, rotate90(t1))
    if center is None:
        return straight_rounding_curve_record(a, b, "parallel_tangent_infinite_radius")

    r0 = distance(center, a)
    r1 = distance(center, b)
    radius = (r0 + r1) * 0.5
    if radius <= 0.05:
        return straight_rounding_curve_record(a, b, "degenerate_radius")
    if abs(r0 - r1) > max(UNIFIED_ROUNDING_RADIUS_TOLERANCE_M, radius * 0.01):
        return straight_rounding_curve_record(a, b, "incompatible_tangent_endpoints")

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
    if abs(sweep_deg) <= UNIFIED_ROUNDING_STRAIGHT_SWEEP_DEG or radius >= UNIFIED_ROUNDING_MAX_ARC_RADIUS_M:
        return straight_rounding_curve_record(a, b, "near_straight_infinite_radius")

    sample_count = max(min_samples, int(math.ceil(abs(sweep_deg) / UNIFIED_ROUNDING_SAMPLE_ANGLE_DEG)) + 1)
    points: list[tuple[float, float]] = []
    for index in range(sample_count):
        t = index / (sample_count - 1)
        angle = start_angle + sweep * t
        points.append((center[0] + math.cos(angle) * radius, center[1] + math.sin(angle) * radius))

    points[0] = a
    points[-1] = b
    return {
        "points": points,
        "curve_family": UNIFIED_ROUNDING_PRIMARY_CURVE_FAMILY,
        "arc_geometry": "circular_arc",
        "arc_fit_status": "exact_tangent_arc",
        "arc_radius_m": radius,
        "arc_center": center,
        "arc_sweep_deg": sweep_deg,
        "sample_count": sample_count,
    }


def derived_smoothing_curve_record(
    prev_point: tuple[float, float],
    point: tuple[float, float],
    next_point: tuple[float, float],
    profile: str = DERIVED_SMOOTHING_MICRO_PROFILE,
    cut_m: float | None = None,
    min_arc_radius_m: float = LANE_CENTERLINE_LOW_RADIUS_MIN_RADIUS_M,
) -> dict[str, Any]:
    prev_len = distance(prev_point, point)
    next_len = distance(point, next_point)
    if prev_len <= 1e-9 or next_len <= 1e-9:
        record = straight_rounding_curve_record(point, point, "degenerate_adjacent_segment")
        record["points"] = [point]
        return record

    if profile == DERIVED_SMOOTHING_HARD_PROFILE:
        cut_ratio = DERIVED_HARD_SMOOTHING_CUT_RATIO
        max_cut_m = DERIVED_HARD_SMOOTHING_MAX_CUT_M
        sample_count = max(3, DERIVED_HARD_SMOOTHING_SAMPLE_COUNT)
    else:
        cut_ratio = DERIVED_SMOOTHING_CUT_RATIO
        max_cut_m = DERIVED_SMOOTHING_MAX_CUT_M
        sample_count = max(3, DERIVED_SMOOTHING_SAMPLE_COUNT)
    resolved_cut_m = min(prev_len * cut_ratio, next_len * cut_ratio, max_cut_m) if cut_m is None else cut_m
    if resolved_cut_m <= 1e-6:
        record = straight_rounding_curve_record(point, point, "degenerate_cut")
        record["points"] = [point]
        return record

    start = point_lerp(point, prev_point, resolved_cut_m / prev_len)
    end = point_lerp(point, next_point, resolved_cut_m / next_len)
    low_radius_metadata: dict[str, Any] = {}
    record = tangent_circular_arc_record(
        start,
        (point[0] - prev_point[0], point[1] - prev_point[1]),
        end,
        (next_point[0] - point[0], next_point[1] - point[1]),
        sample_count,
    )
    if (
        profile == DERIVED_SMOOTHING_HARD_PROFILE
        and str(record.get("curve_family") or "") == UNIFIED_ROUNDING_PRIMARY_CURVE_FAMILY
        and 0.0 < float(record.get("arc_radius_m") or 0.0) < min_arc_radius_m
    ):
        turn_angle = angle_between(
            (point[0] - prev_point[0], point[1] - prev_point[1]),
            (next_point[0] - point[0], next_point[1] - point[1]),
        )
        desired_cut_m = min_arc_radius_m * math.tan(math.radians(turn_angle * 0.5))
        max_regularized_cut_m = min(
            prev_len * DERIVED_HARD_SMOOTHING_LOW_RADIUS_MAX_CUT_RATIO,
            next_len * DERIVED_HARD_SMOOTHING_LOW_RADIUS_MAX_CUT_RATIO,
            max_cut_m,
        )
        low_radius_metadata = {
            "low_radius_arc_policy": "hard_bend_min_radius_guard_v1",
            "low_radius_arc_original_radius_m": float(record.get("arc_radius_m") or 0.0),
            "low_radius_arc_min_radius_m": min_arc_radius_m,
            "low_radius_arc_desired_cut_m": desired_cut_m,
            "low_radius_arc_max_regularized_cut_m": max_regularized_cut_m,
        }
        if desired_cut_m <= max_regularized_cut_m and desired_cut_m > resolved_cut_m:
            resolved_cut_m = desired_cut_m
            start = point_lerp(point, prev_point, resolved_cut_m / prev_len)
            end = point_lerp(point, next_point, resolved_cut_m / next_len)
            record = tangent_circular_arc_record(
                start,
                (point[0] - prev_point[0], point[1] - prev_point[1]),
                end,
                (next_point[0] - point[0], next_point[1] - point[1]),
                sample_count,
            )
            low_radius_metadata["low_radius_arc_action"] = "increased_cut_to_min_radius"
            low_radius_metadata["low_radius_arc_regularized"] = True
        else:
            record = straight_rounding_curve_record(start, end, "low_radius_arc_regularization_unavailable")
            low_radius_metadata["low_radius_arc_action"] = "straight_chord_fallback"
            low_radius_metadata["low_radius_arc_regularized"] = False
    record.update({
        "rounding_style_id": UNIFIED_LANE_GEOMETRY_ROUNDING_STYLE_ID,
        "profile": profile,
        "cut_m": resolved_cut_m,
        "sample_strategy": UNIFIED_ROUNDING_SAMPLE_STRATEGY,
        **low_radius_metadata,
    })
    return record


def derived_smoothing_curve(
    prev_point: tuple[float, float],
    point: tuple[float, float],
    next_point: tuple[float, float],
    profile: str = DERIVED_SMOOTHING_MICRO_PROFILE,
) -> list[tuple[float, float]]:
    return list(derived_smoothing_curve_record(prev_point, point, next_point, profile).get("points") or [point])


def select_non_overlapping_bend_records(
    points: list[tuple[float, float]],
    bend_records: dict[int, dict[str, Any]],
    skipped: Counter,
) -> dict[int, dict[str, Any]]:
    if len(bend_records) <= 1:
        return bend_records

    stations = [0.0]
    for index in range(len(points) - 1):
        stations.append(stations[-1] + distance(points[index], points[index + 1]))

    candidates: list[dict[str, Any]] = []
    for index, record in bend_records.items():
        cut_m = max(0.0, float(record.get("cut_m") or 0.0))
        profile_priority = 2 if str(record.get("profile") or "") == DERIVED_SMOOTHING_HARD_PROFILE else 1
        candidates.append({
            "index": index,
            "start_station": max(stations[index - 1], stations[index] - cut_m),
            "end_station": min(stations[index + 1], stations[index] + cut_m),
            "profile_priority": profile_priority,
            "source_offset_m": float(record.get("source_offset_m") or 0.0),
            "angle_deg": float(record.get("angle_deg") or 0.0),
            "cut_m": cut_m,
        })

    candidates.sort(
        key=lambda item: (
            item["profile_priority"],
            item["source_offset_m"],
            item["angle_deg"],
            item["cut_m"],
            -item["index"],
        ),
        reverse=True,
    )

    selected: list[dict[str, Any]] = []
    for candidate in candidates:
        overlaps = any(
            candidate["start_station"] < existing["end_station"] - DERIVED_SMOOTHING_WINDOW_OVERLAP_EPSILON_M
            and candidate["end_station"] > existing["start_station"] + DERIVED_SMOOTHING_WINDOW_OVERLAP_EPSILON_M
            for existing in selected
        )
        if overlaps:
            skipped["overlapping_bend_window"] += 1
            continue
        selected.append(candidate)

    return {candidate["index"]: bend_records[candidate["index"]] for candidate in sorted(selected, key=lambda item: item["index"])}


def smooth_lane_centerline_points(points: list[tuple[float, float]]) -> tuple[list[tuple[float, float]], dict[str, Any]]:
    return smooth_lane_centerline_points_with_policy(points)


def smooth_lane_centerline_points_with_policy(
    points: list[tuple[float, float]],
    *,
    min_arc_radius_m: float = LANE_CENTERLINE_LOW_RADIUS_MIN_RADIUS_M,
) -> tuple[list[tuple[float, float]], dict[str, Any]]:
    source_point_count = len(points)
    points, cleanup_stats = collapse_micro_segment_runs(points)
    points, low_radius_cleanup_stats = collapse_low_radius_sampled_arc_runs(points, min_radius_m=min_arc_radius_m)
    skipped: Counter = Counter()
    profile_counts: Counter = Counter()
    curve_family_counts: Counter = Counter()
    arc_fit_status_counts: Counter = Counter()
    bend_records: dict[int, dict[str, Any]] = {}
    max_derivation_offset = 0.0
    max_source_offset = 0.0
    max_angle = 0.0
    derivation_limit_adjustments = 0

    if len(points) < 3:
        skipped["too_few_points"] += 1
        return points, {
            "smoothed_bends": 0,
            "inserted_sample_points": 0,
            "source_point_count": source_point_count,
            "cleaned_source_point_count": len(points),
            "max_derivation_offset_m": 0.0,
            "max_source_bend_offset_m": 0.0,
            "max_smoothed_angle_deg": 0.0,
            "profile_counts": {},
            "curve_family_counts": {},
            "arc_fit_status_counts": {},
            "derivation_limit_adjustments": 0,
            "micro_segment_cleanup": cleanup_stats,
            "low_radius_sampled_arc_cleanup": low_radius_cleanup_stats,
            "skipped_bends": dict(skipped),
        }

    for index in range(1, len(points) - 1):
        prev_point = points[index - 1]
        point = points[index]
        next_point = points[index + 1]
        metrics = small_bend_metrics(prev_point, point, next_point)
        profile, reason = smoothing_profile_or_skip_reason(metrics)
        if reason:
            skipped[reason] += 1
            continue
        derivation_limit = (
            DERIVED_HARD_SMOOTHING_MAX_DERIVATION_OFFSET_M
            if profile == DERIVED_SMOOTHING_HARD_PROFILE
            else DERIVED_SMOOTHING_MAX_DERIVATION_OFFSET_M
        )
        curve_record = derived_smoothing_curve_record(
            prev_point,
            point,
            next_point,
            profile,
            min_arc_radius_m=min_arc_radius_m,
        )
        curve = list(curve_record.get("points") or [])
        if len(curve) < 2:
            skipped["degenerate_derived_curve"] += 1
            continue
        local_polyline = [prev_point, point, next_point]
        derivation_offset = max(point_polyline_distance(curve_point, local_polyline) for curve_point in curve)
        derivation_limit_adjusted = False
        if derivation_offset > derivation_limit and derivation_offset > 1e-9:
            adjusted_cut_m = float(curve_record.get("cut_m") or 0.0) * (derivation_limit / derivation_offset) * 0.98
            if adjusted_cut_m > 0.05:
                adjusted_record = derived_smoothing_curve_record(
                    prev_point,
                    point,
                    next_point,
                    profile,
                    cut_m=adjusted_cut_m,
                    min_arc_radius_m=min_arc_radius_m,
                )
                adjusted_curve = list(adjusted_record.get("points") or [])
                if len(adjusted_curve) >= 2:
                    adjusted_offset = max(
                        point_polyline_distance(curve_point, local_polyline)
                        for curve_point in adjusted_curve
                    )
                    curve_record = adjusted_record
                    curve = adjusted_curve
                    derivation_offset = adjusted_offset
                    derivation_limit_adjusted = True
        if derivation_offset > derivation_limit:
            skipped["derived_offset_exceeds_limit"] += 1
            continue
        curve_family = str(curve_record.get("curve_family") or "unknown")
        arc_fit_status = str(curve_record.get("arc_fit_status") or "unknown")
        bend_records[index] = {
            "curve": curve,
            "profile": profile,
            "curve_family": curve_family,
            "arc_fit_status": arc_fit_status,
            "angle_deg": metrics["angle_deg"],
            "source_offset_m": metrics["source_offset_m"],
            "derivation_offset_m": derivation_offset,
            "cut_m": float(curve_record.get("cut_m") or 0.0),
            "arc_radius_m": float(curve_record.get("arc_radius_m") or 0.0),
            "arc_sweep_deg": float(curve_record.get("arc_sweep_deg") or 0.0),
            "derivation_limit_adjusted": derivation_limit_adjusted,
        }

    bend_records = select_non_overlapping_bend_records(points, bend_records, skipped)
    for record in bend_records.values():
        profile = str(record.get("profile") or "unknown")
        curve_family = str(record.get("curve_family") or "unknown")
        arc_fit_status = str(record.get("arc_fit_status") or "unknown")
        profile_counts[profile] += 1
        curve_family_counts[curve_family] += 1
        arc_fit_status_counts[arc_fit_status] += 1
        max_derivation_offset = max(max_derivation_offset, float(record.get("derivation_offset_m") or 0.0))
        max_source_offset = max(max_source_offset, float(record.get("source_offset_m") or 0.0))
        max_angle = max(max_angle, float(record.get("angle_deg") or 0.0))
        if bool(record.get("derivation_limit_adjusted")):
            derivation_limit_adjustments += 1

    if not bend_records:
        return points, {
            "smoothed_bends": 0,
            "inserted_sample_points": 0,
            "source_point_count": source_point_count,
            "cleaned_source_point_count": len(points),
            "max_derivation_offset_m": 0.0,
            "max_source_bend_offset_m": 0.0,
            "max_smoothed_angle_deg": 0.0,
            "profile_counts": {},
            "curve_family_counts": {},
            "arc_fit_status_counts": {},
            "derivation_limit_adjustments": derivation_limit_adjustments,
            "micro_segment_cleanup": cleanup_stats,
            "low_radius_sampled_arc_cleanup": low_radius_cleanup_stats,
            "skipped_bends": dict(skipped),
        }

    smoothed: list[tuple[float, float]] = [points[0]]
    for index in range(1, len(points) - 1):
        record = bend_records.get(index)
        if record is None:
            smoothed.append(points[index])
            continue
        curve = record["curve"]
        if distance(smoothed[-1], curve[0]) > 0.001:
            smoothed.append(curve[0])
        smoothed.extend(curve[1:])
    smoothed.append(points[-1])
    return smoothed, {
        "smoothed_bends": len(bend_records),
        "inserted_sample_points": max(0, len(smoothed) - len(points)),
        "source_point_count": source_point_count,
        "cleaned_source_point_count": len(points),
        "max_derivation_offset_m": round(max_derivation_offset, 6),
        "max_source_bend_offset_m": round(max_source_offset, 6),
        "max_smoothed_angle_deg": round(max_angle, 6),
        "profile_counts": dict(sorted(profile_counts.items())),
        "curve_family_counts": dict(sorted(curve_family_counts.items())),
        "arc_fit_status_counts": dict(sorted(arc_fit_status_counts.items())),
        "derivation_limit_adjustments": derivation_limit_adjustments,
        "micro_segment_cleanup": cleanup_stats,
        "low_radius_sampled_arc_cleanup": low_radius_cleanup_stats,
        "skipped_bends": dict(skipped),
    }


def apply_derived_lane_centerline_smoothing(lanes: list[dict[str, Any]]) -> dict[str, Any]:
    skipped_bends: Counter = Counter()
    profile_counts: Counter = Counter()
    curve_family_counts: Counter = Counter()
    arc_fit_status_counts: Counter = Counter()
    skipped_road_ids_by_reason: dict[str, set[str]] = {}
    smoothed_road_ids: set[str] = set()
    smoothed_lane_ids: list[str] = []
    source_points = 0
    derived_points = 0
    smoothed_bends = 0
    inserted_sample_points = 0
    max_derivation_offset = 0.0
    max_source_bend_offset = 0.0
    max_smoothed_angle = 0.0
    derivation_limit_adjustments = 0
    micro_cleanup_lanes = 0
    micro_cleanup_runs = 0
    micro_cleanup_removed_points = 0
    micro_cleanup_max_run_span = 0.0
    low_radius_cleanup_lanes = 0
    low_radius_cleanup_runs = 0
    low_radius_cleanup_removed_points = 0
    low_radius_cleanup_max_run_span = 0.0
    low_radius_cleanup_min_observed_radius = float("inf")
    lane_bundle_managed_lanes = 0

    for lane in lanes:
        lane_id = str(lane.get("lane_id") or "")
        road_id = str(lane.get("road_id") or "")
        points = [(float(point[0]), float(point[1])) for point in lane.get("centerline_xz") or []]
        source_points += len(points)
        if LANE_BUNDLE_CENTERLINE_SMOOTHING_POLICY in str(lane.get("centerline_source") or ""):
            derived_points += len(points)
            lane_bundle_managed_lanes += 1
            continue
        smoothed, lane_stats = smooth_lane_centerline_points(points)
        derived_points += len(smoothed)
        cleanup = lane_stats.get("micro_segment_cleanup") or {}
        cleanup_removed = int(cleanup.get("removed_points") or 0)
        if cleanup_removed > 0:
            micro_cleanup_lanes += 1
            micro_cleanup_runs += int(cleanup.get("runs_collapsed") or 0)
            micro_cleanup_removed_points += cleanup_removed
            micro_cleanup_max_run_span = max(micro_cleanup_max_run_span, float(cleanup.get("max_run_span_m") or 0.0))
        low_radius_cleanup = lane_stats.get("low_radius_sampled_arc_cleanup") or {}
        low_radius_removed = int(low_radius_cleanup.get("removed_points") or 0)
        if low_radius_removed > 0:
            low_radius_cleanup_lanes += 1
            low_radius_cleanup_runs += int(low_radius_cleanup.get("runs_collapsed") or 0)
            low_radius_cleanup_removed_points += low_radius_removed
            low_radius_cleanup_max_run_span = max(
                low_radius_cleanup_max_run_span,
                float(low_radius_cleanup.get("max_run_span_m") or 0.0),
            )
            observed_radius = float(low_radius_cleanup.get("min_observed_radius_m") or 0.0)
            if observed_radius > 0.0:
                low_radius_cleanup_min_observed_radius = min(
                    low_radius_cleanup_min_observed_radius,
                    observed_radius,
                )
        for reason, count in (lane_stats.get("skipped_bends") or {}).items():
            skipped_bends[str(reason)] += int(count)
            if road_id:
                skipped_road_ids_by_reason.setdefault(str(reason), set()).add(road_id)
        for profile, count in (lane_stats.get("profile_counts") or {}).items():
            profile_counts[str(profile)] += int(count)
        for curve_family, count in (lane_stats.get("curve_family_counts") or {}).items():
            curve_family_counts[str(curve_family)] += int(count)
        for fit_status, count in (lane_stats.get("arc_fit_status_counts") or {}).items():
            arc_fit_status_counts[str(fit_status)] += int(count)
        derivation_limit_adjustments += int(lane_stats.get("derivation_limit_adjustments") or 0)
        geometry_changed = int(lane_stats.get("smoothed_bends") or 0) > 0 or cleanup_removed > 0 or low_radius_removed > 0
        if not geometry_changed:
            continue
        lane["centerline_xz"] = [[round(x, 3), round(z, 3)] for x, z in smoothed]
        lane["centerline_derivation_policy"] = DERIVED_LANE_CENTERLINE_SMOOTHING_POLICY
        lane["centerline_derived_from"] = str(lane.get("centerline_source") or "unknown")
        lane["derived_centerline_smoothing"] = {
            "policy": DERIVED_LANE_CENTERLINE_SMOOTHING_POLICY,
            "rounding_style_id": UNIFIED_LANE_GEOMETRY_ROUNDING_STYLE_ID,
            "curve_family": UNIFIED_ROUNDING_PRIMARY_CURVE_FAMILY,
            "sample_strategy": UNIFIED_ROUNDING_SAMPLE_STRATEGY,
            "source_point_count": int(lane_stats.get("source_point_count") or len(points)),
            "cleaned_source_point_count": int(lane_stats.get("cleaned_source_point_count") or len(points)),
            "derived_point_count": len(smoothed),
            "smoothed_bends": int(lane_stats["smoothed_bends"]),
            "inserted_sample_points": int(lane_stats["inserted_sample_points"]),
            "max_derivation_offset_m": round(float(lane_stats["max_derivation_offset_m"]), 3),
            "max_source_bend_offset_m": round(float(lane_stats["max_source_bend_offset_m"]), 3),
            "max_smoothed_angle_deg": round(float(lane_stats["max_smoothed_angle_deg"]), 3),
            "profile_counts": dict(sorted((lane_stats.get("profile_counts") or {}).items())),
            "curve_family_counts": dict(sorted((lane_stats.get("curve_family_counts") or {}).items())),
            "arc_fit_status_counts": dict(sorted((lane_stats.get("arc_fit_status_counts") or {}).items())),
            "derivation_limit_adjustments": int(lane_stats.get("derivation_limit_adjustments") or 0),
            "micro_segment_cleanup": cleanup,
            "low_radius_sampled_arc_cleanup": low_radius_cleanup,
        }
        smoothed_lane_ids.append(lane_id)
        if road_id:
            smoothed_road_ids.add(road_id)
        smoothed_bends += int(lane_stats["smoothed_bends"])
        inserted_sample_points += int(lane_stats["inserted_sample_points"])
        max_derivation_offset = max(max_derivation_offset, float(lane_stats["max_derivation_offset_m"]))
        max_source_bend_offset = max(max_source_bend_offset, float(lane_stats["max_source_bend_offset_m"]))
        max_smoothed_angle = max(max_smoothed_angle, float(lane_stats["max_smoothed_angle_deg"]))

    return {
        **smoothing_policy_config(),
        "lanes_evaluated": len(lanes),
        "smoothed_lane_count": len(smoothed_lane_ids),
        "smoothed_bend_count": smoothed_bends,
        "inserted_sample_points": inserted_sample_points,
        "source_point_count": source_points,
        "derived_point_count": derived_points,
        "max_derivation_offset_m": round(max_derivation_offset, 3),
        "max_source_bend_offset_m": round(max_source_bend_offset, 3),
        "max_smoothed_angle_deg": round(max_smoothed_angle, 3),
        "profile_counts": dict(sorted(profile_counts.items())),
        "curve_family_counts": dict(sorted(curve_family_counts.items())),
        "arc_fit_status_counts": dict(sorted(arc_fit_status_counts.items())),
        "derivation_limit_adjustments": derivation_limit_adjustments,
        "lane_bundle_managed_lanes": lane_bundle_managed_lanes,
        "micro_segment_cleanup": {
            "policy": LANE_CENTERLINE_MICRO_SEGMENT_CLEANUP_POLICY,
            "lanes_cleaned": micro_cleanup_lanes,
            "runs_collapsed": micro_cleanup_runs,
            "removed_points": micro_cleanup_removed_points,
            "max_run_span_m": round(micro_cleanup_max_run_span, 3),
            "min_segment_m": LANE_CENTERLINE_MICRO_SEGMENT_M,
            "max_run_span_threshold_m": LANE_CENTERLINE_MICRO_RUN_MAX_SPAN_M,
        },
        "low_radius_sampled_arc_cleanup": {
            "policy": LANE_CENTERLINE_LOW_RADIUS_SAMPLED_ARC_CLEANUP_POLICY,
            "lanes_cleaned": low_radius_cleanup_lanes,
            "runs_collapsed": low_radius_cleanup_runs,
            "removed_points": low_radius_cleanup_removed_points,
            "max_run_span_m": round(low_radius_cleanup_max_run_span, 3),
            "min_radius_m": LANE_CENTERLINE_LOW_RADIUS_MIN_RADIUS_M,
            "min_observed_radius_m": (
                round(low_radius_cleanup_min_observed_radius, 3)
                if low_radius_cleanup_min_observed_radius < float("inf")
                else 0.0
            ),
            "max_sample_segment_m": LANE_CENTERLINE_LOW_RADIUS_SAMPLE_SEGMENT_M,
            "max_run_span_threshold_m": LANE_CENTERLINE_LOW_RADIUS_RUN_MAX_SPAN_M,
        },
        "smoothed_lane_ids": smoothed_lane_ids,
        "smoothed_road_ids": sorted(smoothed_road_ids),
        "skipped_bends": dict(sorted(skipped_bends.items())),
        "skipped_road_ids_by_reason": {
            reason: sorted(road_ids)
            for reason, road_ids in sorted(skipped_road_ids_by_reason.items())
        },
    }


def lane_bundle_max_abs_offset(edge: dict[str, Any]) -> float:
    forward_count, backward_count = lane_counts(edge)
    generated_lane_count = forward_count + backward_count
    width_profile = edge_width_profile(edge, generated_lane_count)
    lane_width_start = float(width_profile["lane_width_start_m"])
    lane_width_end = float(width_profile["lane_width_end_m"])
    shared_single_lane = edge_has_shared_single_lane_upgrade(edge)
    offsets: list[float] = []
    for index in range(forward_count):
        offsets.extend([
            directional_lane_offset("forward", index, lane_width_start, shared_single_lane=shared_single_lane),
            directional_lane_offset("forward", index, lane_width_end, shared_single_lane=shared_single_lane),
        ])
    for index in range(backward_count):
        offsets.extend([
            directional_lane_offset("backward", index, lane_width_start, shared_single_lane=shared_single_lane),
            directional_lane_offset("backward", index, lane_width_end, shared_single_lane=shared_single_lane),
        ])
    return max((abs(offset) for offset in offsets), default=0.0)


def apply_lane_bundle_centerline_smoothing(edges: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    updated: list[dict[str, Any]] = []
    smoothed_edge_ids: list[str] = []
    profile_counts: Counter = Counter()
    curve_family_counts: Counter = Counter()
    arc_fit_status_counts: Counter = Counter()
    skipped_bends: Counter = Counter()
    max_abs_lane_offset = 0.0
    max_min_arc_radius = 0.0
    smoothed_bends = 0
    inserted_sample_points = 0
    low_radius_cleanup_edges = 0
    low_radius_cleanup_removed_points = 0

    for edge in edges:
        item = dict(edge)
        edge_id = str(edge.get("edge_id") or "")
        points = edge_points(edge)
        abs_offset = lane_bundle_max_abs_offset(edge)
        min_arc_radius = LANE_CENTERLINE_LOW_RADIUS_MIN_RADIUS_M + abs_offset
        smoothed, stats = smooth_lane_centerline_points_with_policy(
            points,
            min_arc_radius_m=min_arc_radius,
        )
        for profile, count in (stats.get("profile_counts") or {}).items():
            profile_counts[str(profile)] += int(count)
        for curve_family, count in (stats.get("curve_family_counts") or {}).items():
            curve_family_counts[str(curve_family)] += int(count)
        for fit_status, count in (stats.get("arc_fit_status_counts") or {}).items():
            arc_fit_status_counts[str(fit_status)] += int(count)
        for reason, count in (stats.get("skipped_bends") or {}).items():
            skipped_bends[str(reason)] += int(count)
        cleanup = stats.get("low_radius_sampled_arc_cleanup") or {}
        cleanup_removed = int(cleanup.get("removed_points") or 0)
        if cleanup_removed > 0:
            low_radius_cleanup_edges += 1
            low_radius_cleanup_removed_points += cleanup_removed
        geometry_changed = int(stats.get("smoothed_bends") or 0) > 0 or cleanup_removed > 0
        if geometry_changed:
            item["geometry_xz"] = [[round(x, 3), round(z, 3)] for x, z in smoothed]
            item["lane_bundle_centerline_smoothing"] = {
                "policy": LANE_BUNDLE_CENTERLINE_SMOOTHING_POLICY,
                "source_point_count": int(stats.get("source_point_count") or len(points)),
                "cleaned_source_point_count": int(stats.get("cleaned_source_point_count") or len(points)),
                "derived_point_count": len(smoothed),
                "max_abs_lane_offset_m": round(abs_offset, 3),
                "min_arc_radius_m": round(min_arc_radius, 3),
                "smoothed_bends": int(stats.get("smoothed_bends") or 0),
                "inserted_sample_points": int(stats.get("inserted_sample_points") or 0),
                "profile_counts": dict(sorted((stats.get("profile_counts") or {}).items())),
                "curve_family_counts": dict(sorted((stats.get("curve_family_counts") or {}).items())),
                "arc_fit_status_counts": dict(sorted((stats.get("arc_fit_status_counts") or {}).items())),
                "micro_segment_cleanup": stats.get("micro_segment_cleanup") or {},
                "low_radius_sampled_arc_cleanup": cleanup,
            }
            item["centerline_geometry_source"] = (
                f"{str(edge.get('centerline_geometry_source') or 'road_graph')}+{LANE_BUNDLE_CENTERLINE_SMOOTHING_POLICY}"
            )
            smoothed_edge_ids.append(edge_id)
            smoothed_bends += int(stats.get("smoothed_bends") or 0)
            inserted_sample_points += int(stats.get("inserted_sample_points") or 0)
        max_abs_lane_offset = max(max_abs_lane_offset, abs_offset)
        max_min_arc_radius = max(max_min_arc_radius, min_arc_radius)
        updated.append(item)

    return updated, {
        "policy": LANE_BUNDLE_CENTERLINE_SMOOTHING_POLICY,
        "edges_evaluated": len(edges),
        "smoothed_edge_count": len(smoothed_edge_ids),
        "smoothed_edge_ids": smoothed_edge_ids,
        "smoothed_bend_count": smoothed_bends,
        "inserted_sample_points": inserted_sample_points,
        "max_abs_lane_offset_m": round(max_abs_lane_offset, 3),
        "max_min_arc_radius_m": round(max_min_arc_radius, 3),
        "profile_counts": dict(sorted(profile_counts.items())),
        "curve_family_counts": dict(sorted(curve_family_counts.items())),
        "arc_fit_status_counts": dict(sorted(arc_fit_status_counts.items())),
        "low_radius_sampled_arc_cleanup": {
            "edges_cleaned": low_radius_cleanup_edges,
            "removed_points": low_radius_cleanup_removed_points,
        },
        "skipped_bends": dict(sorted(skipped_bends.items())),
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
        shared_single_lane = edge_has_shared_single_lane_upgrade(edge)
        for index in range(forward_count):
            offset = directional_lane_offset("forward", index, lane_width, shared_single_lane=shared_single_lane)
            offset_start = directional_lane_offset("forward", index, lane_width_start, shared_single_lane=shared_single_lane)
            offset_end = directional_lane_offset("forward", index, lane_width_end, shared_single_lane=shared_single_lane)
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
                "source": lane_source(edge),
                "source_observation": {
                    "lanes": max(1, int(edge.get("lanes") or 1)),
                    "lanes_source": str(edge.get("lanes_source") or "unknown"),
                    "oneway": bool(edge.get("oneway")),
                    "oneway_direction": str(edge.get("oneway_direction") or "unknown"),
                },
                "traffic_policy": TEMPORARY_LANE_POLICY_ID,
                "traffic_side_assumption": TEMPORARY_TRAFFIC_SIDE,
                "policy_issues": lane_policy_issues(edge),
                "centerline_source": edge.get("centerline_geometry_source", "road_graph"),
                "approach_centerline_trimmed": bool(edge.get("approach_centerline_trimmed")),
                **lane_upgrade_fields(edge),
            })
        for index in range(backward_count):
            offset = directional_lane_offset("backward", index, lane_width, shared_single_lane=shared_single_lane)
            offset_start = directional_lane_offset("backward", index, lane_width_start, shared_single_lane=shared_single_lane)
            offset_end = directional_lane_offset("backward", index, lane_width_end, shared_single_lane=shared_single_lane)
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
                "source": lane_source(edge),
                "source_observation": {
                    "lanes": max(1, int(edge.get("lanes") or 1)),
                    "lanes_source": str(edge.get("lanes_source") or "unknown"),
                    "oneway": bool(edge.get("oneway")),
                    "oneway_direction": str(edge.get("oneway_direction") or "unknown"),
                },
                "traffic_policy": TEMPORARY_LANE_POLICY_ID,
                "traffic_side_assumption": TEMPORARY_TRAFFIC_SIDE,
                "policy_issues": lane_policy_issues(edge),
                "centerline_source": edge.get("centerline_geometry_source", "road_graph"),
                "approach_centerline_trimmed": bool(edge.get("approach_centerline_trimmed")),
                **lane_upgrade_fields(edge),
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


def default_lane_link_trim_m(lane: dict[str, Any]) -> float:
    if bool(lane.get("approach_centerline_trimmed")):
        return 0.0
    if "optimized_approach_centerline" in str(lane.get("centerline_source") or ""):
        return 0.0
    return JUNCTION_TRIM_M


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
    from_trim = from_trim or {"start": 0.0, "end": default_lane_link_trim_m(from_lane)}
    to_trim = to_trim or {"start": default_lane_link_trim_m(to_lane), "end": 0.0}
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
        "from_lane_trim_end_m": round(longitudinal_trim_to_point(from_pts, "end", curve_start), 3),
        "to_lane_trim_start_m": round(longitudinal_trim_to_point(to_pts, "start", curve_end), 3),
    }


def curve_stats(curve: list[list[float]]) -> dict[str, Any]:
    pts = [(float(p[0]), float(p[1])) for p in curve]
    return {
        "sample_count": len(curve),
        "length_m": round(polyline_length(pts), 3),
    }


def radius_from_three_points(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> float | None:
    ab = distance(a, b)
    bc = distance(b, c)
    ca = distance(c, a)
    denom = 2.0 * abs(cross((b[0] - a[0], b[1] - a[1]), (c[0] - a[0], c[1] - a[1])))
    if denom <= 1e-9:
        return None
    return (ab * bc * ca) / denom


def polyline_min_radius_m(points: list[tuple[float, float]]) -> float:
    radii: list[float] = []
    for index in range(1, len(points) - 1):
        radius = radius_from_three_points(points[index - 1], points[index], points[index + 1])
        if radius is not None and radius > 0.0:
            radii.append(radius)
    return min(radii) if radii else 0.0


def polyline_station_slice(
    points: list[tuple[float, float]],
    start_station_m: float,
    end_station_m: float,
) -> list[tuple[float, float]]:
    if len(points) < 2:
        return points
    total = polyline_length(points)
    start_station_m = min(max(0.0, start_station_m), total)
    end_station_m = min(max(start_station_m, end_station_m), total)
    if end_station_m - start_station_m <= 0.05:
        return []

    sliced: list[tuple[float, float]] = [point_at_distance(points, start_station_m)]
    station = 0.0
    for index in range(len(points) - 1):
        seg_len = distance(points[index], points[index + 1])
        next_station = station + seg_len
        if start_station_m < next_station and station < end_station_m:
            if start_station_m + 0.001 < next_station < end_station_m - 0.001:
                candidate = points[index + 1]
                if distance(sliced[-1], candidate) > 0.001:
                    sliced.append(candidate)
        station = next_station
    end_point = point_at_distance(points, end_station_m)
    if not sliced or distance(sliced[-1], end_point) > 0.001:
        sliced.append(end_point)
    return sliced


def set_lane_centerline_points(
    lane: dict[str, Any],
    points: list[tuple[float, float]],
    metadata: dict[str, Any],
) -> None:
    lane["centerline_xz"] = [[round(x, 3), round(z, 3)] for x, z in points]
    endpoint_records = lane.setdefault("centerline_endpoint_rounding", [])
    endpoint_records.append(metadata)
    smoothing = lane.get("derived_centerline_smoothing")
    if isinstance(smoothing, dict):
        smoothing["derived_point_count"] = len(lane["centerline_xz"])


def replace_lane_centerline_slice(
    lane: dict[str, Any],
    start_station_m: float,
    end_station_m: float,
    metadata: dict[str, Any],
) -> bool:
    points = [(float(point[0]), float(point[1])) for point in lane.get("centerline_xz") or []]
    sliced = polyline_station_slice(points, start_station_m, end_station_m)
    if len(sliced) < 2:
        return False
    set_lane_centerline_points(lane, sliced, metadata)
    return True


def build_lane_link_records(
    from_lanes: list[dict[str, Any]],
    to_lanes: list[dict[str, Any]],
    movement: dict[str, Any],
    junction_id: str,
    connection_index: int,
) -> list[dict[str, Any]]:
    lane_links = match_lane_links(from_lanes, to_lanes)
    confidence = float(movement.get("confidence", 0.45))
    for link_index, link in enumerate(lane_links):
        from_lane = next(lane for lane in from_lanes if lane["lane_id"] == link["from_lane"])
        to_lane = next(lane for lane in to_lanes if lane["lane_id"] == link["to_lane"])
        curve = lane_connection_curve(from_lane, to_lane)
        curve_source = "junction_lane_endpoint_bezier"
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
        link["connector_id"] = ""
        link["connector_kind"] = ""
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
        if lane is not None:
            return default_lane_link_trim_m(lane)
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
                        trim_by_lane.get(
                            str(from_lane.get("lane_id") or ""),
                            {"start": 0.0, "end": default_lane_link_trim_m(from_lane)},
                        ),
                        trim_by_lane.get(
                            str(to_lane.get("lane_id") or ""),
                            {"start": default_lane_link_trim_m(to_lane), "end": 0.0},
                        ),
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


def regularize_continuity_curve_lane_radius(
    curve: list[list[float]],
    from_lane: dict[str, Any],
    to_lane: dict[str, Any],
    corner: dict[str, Any],
) -> tuple[list[list[float]], dict[str, Any]]:
    curve_points = [(float(point[0]), float(point[1])) for point in curve]
    current_radius = polyline_min_radius_m(curve_points)
    metadata: dict[str, Any] = {
        "lane_level_radius_regularized": False,
        "lane_level_min_radius_m": LANE_LEVEL_CONTINUITY_MIN_RADIUS_M,
        "lane_level_observed_min_radius_m": round(current_radius, 3) if current_radius > 0.0 else 0.0,
    }
    if (
        len(curve_points) < 3
        or current_radius <= 0.0
        or current_radius >= LANE_LEVEL_CONTINUITY_MIN_RADIUS_M - LANE_LEVEL_CONTINUITY_MIN_RADIUS_EPSILON_M
    ):
        return curve, metadata

    from_points = [(float(point[0]), float(point[1])) for point in from_lane.get("centerline_xz") or []]
    to_points = [(float(point[0]), float(point[1])) for point in to_lane.get("centerline_xz") or []]
    if len(from_points) < 2 or len(to_points) < 2 or from_lane.get("lane_id") == to_lane.get("lane_id"):
        metadata["lane_level_radius_regularization_skip_reason"] = "insufficient_lane_points"
        return curve, metadata

    from_length = polyline_length(from_points)
    to_length = polyline_length(to_points)
    if from_length <= 0.5 or to_length <= 0.5:
        metadata["lane_level_radius_regularization_skip_reason"] = "short_lane"
        return curve, metadata

    from_endpoint = from_points[-1]
    to_endpoint = to_points[0]
    from_tangent = tangent_at_distance(from_points, from_length)
    to_tangent = tangent_at_distance(to_points, 0.0)
    if from_tangent == (0.0, 0.0) or to_tangent == (0.0, 0.0):
        metadata["lane_level_radius_regularization_skip_reason"] = "zero_tangent"
        return curve, metadata

    virtual_corner = line_intersection(from_endpoint, from_tangent, to_endpoint, to_tangent)
    if virtual_corner is None:
        metadata["lane_level_radius_regularization_skip_reason"] = "parallel_lane_tangents"
        return curve, metadata

    from_cut = dot((virtual_corner[0] - from_endpoint[0], virtual_corner[1] - from_endpoint[1]), from_tangent)
    to_cut = -dot((virtual_corner[0] - to_endpoint[0], virtual_corner[1] - to_endpoint[1]), to_tangent)
    if from_cut <= 0.0 or to_cut <= 0.0:
        metadata["lane_level_radius_regularization_skip_reason"] = "virtual_corner_behind_endpoint"
        return curve, metadata

    turn_angle = angle_between(from_tangent, to_tangent)
    if turn_angle <= 5.0 or turn_angle >= 150.0:
        metadata["lane_level_radius_regularization_skip_reason"] = "turn_angle_out_of_range"
        return curve, metadata

    target_cut = LANE_LEVEL_CONTINUITY_MIN_RADIUS_M * math.tan(math.radians(turn_angle * 0.5))
    desired_from_extra = max(0.0, target_cut - from_cut)
    desired_to_extra = max(0.0, target_cut - to_cut)
    if desired_from_extra <= 0.001 and desired_to_extra <= 0.001:
        metadata["lane_level_radius_regularization_skip_reason"] = "already_meets_virtual_cut"
        return curve, metadata

    max_from_extra = min(LANE_LEVEL_CONTINUITY_MAX_EXTRA_TRIM_M, max(0.0, from_length - 0.5))
    max_to_extra = min(LANE_LEVEL_CONTINUITY_MAX_EXTRA_TRIM_M, max(0.0, to_length - 0.5))
    from_extra = min(desired_from_extra, max_from_extra)
    to_extra = min(desired_to_extra, max_to_extra)
    if from_extra <= 0.001 and to_extra <= 0.001:
        metadata["lane_level_radius_regularization_skip_reason"] = "no_trim_capacity"
        return curve, metadata

    start_station = max(0.0, from_length - from_extra)
    end_station = min(to_length, to_extra)
    new_from_points = polyline_station_slice(from_points, 0.0, start_station)
    new_to_points = polyline_station_slice(to_points, end_station, to_length)
    if len(new_from_points) < 2 or len(new_to_points) < 2:
        metadata["lane_level_radius_regularization_skip_reason"] = "trim_would_collapse_lane"
        return curve, metadata

    start = point_at_distance(from_points, start_station)
    end = point_at_distance(to_points, end_station)
    arc = tangent_circular_arc_record(
        start,
        tangent_at_distance(from_points, start_station),
        end,
        tangent_at_distance(to_points, end_station),
        DERIVED_HARD_SMOOTHING_SAMPLE_COUNT,
    )
    if str(arc.get("curve_family") or "") != UNIFIED_ROUNDING_PRIMARY_CURVE_FAMILY:
        metadata["lane_level_radius_regularization_skip_reason"] = str(arc.get("arc_fit_status") or "arc_fit_failed")
        return curve, metadata

    regularized_points = [(float(x), float(z)) for x, z in (arc.get("points") or [])]
    regularized_radius = polyline_min_radius_m(regularized_points)
    if regularized_radius <= current_radius + LANE_LEVEL_CONTINUITY_MIN_RADIUS_EPSILON_M:
        metadata["lane_level_radius_regularization_skip_reason"] = "regularized_radius_not_better"
        return curve, metadata

    set_lane_centerline_points(
        from_lane,
        new_from_points,
        {
            "policy": "lane_level_continuity_min_radius_regularization_v1",
            "side": "end",
            "continuity_link_corner_node_id": str(corner.get("corner_node_id") or ""),
            "trim_m": round(from_extra, 3),
        },
    )
    set_lane_centerline_points(
        to_lane,
        new_to_points,
        {
            "policy": "lane_level_continuity_min_radius_regularization_v1",
            "side": "start",
            "continuity_link_corner_node_id": str(corner.get("corner_node_id") or ""),
            "trim_m": round(to_extra, 3),
        },
    )
    regularized_curve = [[round(x, 3), round(z, 3)] for x, z in regularized_points]
    metadata.update({
        "lane_level_radius_regularized": True,
        "lane_level_regularization_policy": "lane_level_continuity_min_radius_regularization_v1",
        "lane_level_target_radius_m": LANE_LEVEL_CONTINUITY_MIN_RADIUS_M,
        "lane_level_regularized_min_radius_m": round(regularized_radius, 3),
        "lane_level_from_extra_trim_m": round(from_extra, 3),
        "lane_level_to_extra_trim_m": round(to_extra, 3),
        "lane_level_turn_angle_deg": round(turn_angle, 3),
        "lane_level_arc_radius_m": round(float(arc.get("arc_radius_m") or 0.0), 3),
        "lane_level_arc_sweep_deg": round(float(arc.get("arc_sweep_deg") or 0.0), 3),
        "lane_level_arc_fit_status": str(arc.get("arc_fit_status") or ""),
        "lane_level_trim_limited_by_capacity": (
            from_extra + 0.001 < desired_from_extra
            or to_extra + 0.001 < desired_to_extra
        ),
    })
    return regularized_curve, metadata


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
        offset_sign = -1.0 if direction_index == 1 else 1.0
        start_offset = lane_endpoint_offset(from_lane, node_id, "end") * offset_sign
        end_offset = lane_endpoint_offset(to_lane, node_id, "start") * offset_sign
        curve = continuity_curve_from_fillet(base_points, start_offset, end_offset)
        if len(curve) < 2:
            continue
        from_lane_points = [(float(p[0]), float(p[1])) for p in from_lane["centerline_xz"]]
        to_lane_points = [(float(p[0]), float(p[1])) for p in to_lane["centerline_xz"]]
        curve[0] = [round(from_lane_points[-1][0], 3), round(from_lane_points[-1][1], 3)]
        curve[-1] = [round(to_lane_points[0][0], 3), round(to_lane_points[0][1], 3)]
        curve, lane_radius_metadata = regularize_continuity_curve_lane_radius(
            curve,
            from_lane,
            to_lane,
            corner,
        )
        from_lane_points = [(float(p[0]), float(p[1])) for p in from_lane["centerline_xz"]]
        to_lane_points = [(float(p[0]), float(p[1])) for p in to_lane["centerline_xz"]]
        curve[0] = [round(from_lane_points[-1][0], 3), round(from_lane_points[-1][1], 3)]
        curve[-1] = [round(to_lane_points[0][0], 3), round(to_lane_points[0][1], 3)]
        curve_start = (float(curve[0][0]), float(curve[0][1]))
        curve_end = (float(curve[-1][0]), float(curve[-1][1]))
        stats = curve_stats(curve)
        curve_min_radius = polyline_min_radius_m([(float(p[0]), float(p[1])) for p in curve])
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
            "rounding_style_id": str(corner.get("rounding_style_id") or UNIFIED_LANE_GEOMETRY_ROUNDING_STYLE_ID),
            "rounding_curve_family": str(corner.get("rounding_curve_family") or UNIFIED_ROUNDING_PRIMARY_CURVE_FAMILY),
            "rounding_sample_strategy": str(corner.get("rounding_sample_strategy") or UNIFIED_ROUNDING_SAMPLE_STRATEGY),
            "rounding_application": "offset_from_optimized_corner_fillet",
            "connecting_curve_xz": curve,
            "curve_length_m": stats["length_m"],
            "curve_sample_count": stats["sample_count"],
            "from_lane_trim_end_m": round(longitudinal_trim_to_point(from_lane_points, "end", curve_start), 3),
            "to_lane_trim_start_m": round(longitudinal_trim_to_point(to_lane_points, "start", curve_end), 3),
            "width_m": round((width_start + width_end) * 0.5, 3),
            "width_start_m": round(width_start, 3),
            "width_end_m": round(width_end, 3),
            "width_source": "connected_lane_widths",
            "width_confidence": round(width_confidence, 3),
            "cut_m": round(float(corner.get("cut_m") or 0.0), 3),
            "turn_angle_deg": round(float(corner.get("turn_angle_deg") or 0.0), 3),
            "lane_level_min_radius_m": LANE_LEVEL_CONTINUITY_MIN_RADIUS_M,
            "lane_level_curve_min_radius_m": round(curve_min_radius, 3) if curve_min_radius > 0.0 else 0.0,
            **lane_radius_metadata,
            "arc_geometry": str(corner.get("arc_geometry") or ""),
            "arc_fit_status": str(corner.get("arc_fit_status") or ""),
            "arc_radius_m": round(float(corner.get("arc_radius_m") or 0.0), 3),
            "arc_sweep_deg": round(float(corner.get("arc_sweep_deg") or 0.0), 3),
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


def edge_turn_deg_at_connector(
    node_id: str,
    edge_a: dict[str, Any],
    edge_b: dict[str, Any],
) -> float:
    points_a = edge_points(edge_a)
    points_b = edge_points(edge_b)
    if len(points_a) < 2 or len(points_b) < 2:
        return 180.0
    if node_id == str(edge_a.get("from_node") or ""):
        dir_a = normalize((points_a[1][0] - points_a[0][0], points_a[1][1] - points_a[0][1]))
    else:
        dir_a = normalize((points_a[-2][0] - points_a[-1][0], points_a[-2][1] - points_a[-1][1]))
    if node_id == str(edge_b.get("from_node") or ""):
        dir_b = normalize((points_b[1][0] - points_b[0][0], points_b[1][1] - points_b[0][1]))
    else:
        dir_b = normalize((points_b[-2][0] - points_b[-1][0], points_b[-2][1] - points_b[-1][1]))
    return 180.0 - angle_between(dir_a, dir_b)


def direct_continuity_curve(from_lane: dict[str, Any], to_lane: dict[str, Any]) -> list[list[float]]:
    from_points = [(float(p[0]), float(p[1])) for p in from_lane.get("centerline_xz") or []]
    to_points = [(float(p[0]), float(p[1])) for p in to_lane.get("centerline_xz") or []]
    if not from_points or not to_points:
        return []
    start = from_points[-1]
    end = to_points[0]
    if distance(start, end) <= 0.001:
        return [[round(start[0], 3), round(start[1], 3)], [round(end[0], 3), round(end[1], 3)]]
    mid = ((start[0] + end[0]) * 0.5, (start[1] + end[1]) * 0.5)
    return [
        [round(start[0], 3), round(start[1], 3)],
        [round(mid[0], 3), round(mid[1], 3)],
        [round(end[0], 3), round(end[1], 3)],
    ]


def append_endpoint_snap_record(
    lane: dict[str, Any],
    *,
    side: str,
    node_id: str,
    linked_lane_id: str,
    seam_point: list[float],
    original_endpoint_gap_m: float,
) -> None:
    lane["centerline_endpoint_snap_policy"] = DIRECT_CONNECTOR_MICRO_SEAM_POLICY
    snaps = lane.setdefault("centerline_endpoint_snaps", [])
    snaps.append({
        "policy": DIRECT_CONNECTOR_MICRO_SEAM_POLICY,
        "side": side,
        "node_id": node_id,
        "linked_lane_id": linked_lane_id,
        "seam_point_xz": seam_point,
        "original_endpoint_gap_m": round(original_endpoint_gap_m, 3),
    })


def snap_direct_connector_micro_seam(
    *,
    node_id: str,
    from_lane: dict[str, Any],
    to_lane: dict[str, Any],
    original_endpoint_gap_m: float,
) -> list[float]:
    from_points = from_lane.get("centerline_xz") or []
    to_points = to_lane.get("centerline_xz") or []
    start = (float(from_points[-1][0]), float(from_points[-1][1]))
    end = (float(to_points[0][0]), float(to_points[0][1]))
    seam_point = [round((start[0] + end[0]) * 0.5, 3), round((start[1] + end[1]) * 0.5, 3)]
    from_points[-1] = list(seam_point)
    to_points[0] = list(seam_point)
    append_endpoint_snap_record(
        from_lane,
        side="end",
        node_id=node_id,
        linked_lane_id=str(to_lane.get("lane_id") or ""),
        seam_point=seam_point,
        original_endpoint_gap_m=original_endpoint_gap_m,
    )
    append_endpoint_snap_record(
        to_lane,
        side="start",
        node_id=node_id,
        linked_lane_id=str(from_lane.get("lane_id") or ""),
        seam_point=seam_point,
        original_endpoint_gap_m=original_endpoint_gap_m,
    )
    return seam_point


def direct_connector_physical_lane_group_candidate(link: dict[str, Any]) -> bool:
    if str(link.get("source") or "") != DIRECT_CONNECTOR_CONTINUITY_POLICY:
        return False
    turn_deg = float(link.get("turn_angle_deg") or 0.0)
    endpoint_gap_m = float(link.get("endpoint_gap_m") or 0.0)
    original_endpoint_gap_m = float(link.get("original_endpoint_gap_m") or endpoint_gap_m)
    return (
        turn_deg <= DIRECT_CONNECTOR_PHYSICAL_LANE_MAX_TURN_DEG
        and endpoint_gap_m <= 0.001
        and original_endpoint_gap_m <= DIRECT_CONNECTOR_PHYSICAL_LANE_MAX_ENDPOINT_GAP_M
    )


def physical_lane_group_id(lane_ids: list[str]) -> str:
    key = "|".join(sorted(lane_ids))
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return f"plg_{digest}"


def append_physical_lane_group_link(
    lane: dict[str, Any],
    *,
    group_id: str,
    side: str,
    node_id: str,
    linked_lane_id: str,
    link: dict[str, Any],
) -> None:
    records = lane.setdefault("physical_lane_group_links", [])
    records.append({
        "policy": DIRECT_CONNECTOR_PHYSICAL_LANE_GROUP_POLICY,
        "physical_lane_group_id": group_id,
        "side": side,
        "node_id": node_id,
        "linked_lane_id": linked_lane_id,
        "continuity_link_id": str(link.get("continuity_link_id") or ""),
        "turn_angle_deg": link.get("turn_angle_deg", 0.0),
        "endpoint_gap_m": link.get("endpoint_gap_m", 0.0),
        "original_endpoint_gap_m": link.get("original_endpoint_gap_m", 0.0),
        "micro_seam_absorbed": bool(link.get("micro_seam_absorbed")),
    })


def annotate_direct_connector_physical_lane_groups(
    lanes: list[dict[str, Any]],
    links: list[dict[str, Any]],
) -> dict[str, Any]:
    lanes_by_id = {str(lane.get("lane_id") or ""): lane for lane in lanes if lane.get("lane_id")}
    parent: dict[str, str] = {}

    def find(lane_id: str) -> str:
        parent.setdefault(lane_id, lane_id)
        while parent[lane_id] != lane_id:
            parent[lane_id] = parent[parent[lane_id]]
            lane_id = parent[lane_id]
        return lane_id

    def union(a: str, b: str) -> None:
        root_a = find(a)
        root_b = find(b)
        if root_a == root_b:
            return
        if root_b < root_a:
            root_a, root_b = root_b, root_a
        parent[root_b] = root_a

    candidate_links: list[dict[str, Any]] = []
    skipped = Counter()
    for link in links:
        if not direct_connector_physical_lane_group_candidate(link):
            skipped["not_same_physical_lane_candidate"] += 1
            continue
        from_lane_id = str(link.get("from_lane") or "")
        to_lane_id = str(link.get("to_lane") or "")
        if from_lane_id not in lanes_by_id or to_lane_id not in lanes_by_id:
            skipped["missing_lane_reference"] += 1
            continue
        union(from_lane_id, to_lane_id)
        candidate_links.append(link)

    components: dict[str, list[str]] = {}
    for lane_id in parent:
        components.setdefault(find(lane_id), []).append(lane_id)
    group_by_lane: dict[str, tuple[str, list[str]]] = {}
    for members in components.values():
        if len(members) < 2:
            continue
        sorted_members = sorted(members)
        group_id = physical_lane_group_id(sorted_members)
        for lane_id in sorted_members:
            group_by_lane[lane_id] = (group_id, sorted_members)

    for lane_id, (group_id, members) in group_by_lane.items():
        lane = lanes_by_id[lane_id]
        lane["physical_lane_group_id"] = group_id
        lane["physical_lane_group_policy"] = DIRECT_CONNECTOR_PHYSICAL_LANE_GROUP_POLICY
        lane["physical_lane_group_member_count"] = len(members)
        lane["physical_lane_group_members"] = members

    grouped_links = 0
    for link in candidate_links:
        from_lane_id = str(link.get("from_lane") or "")
        to_lane_id = str(link.get("to_lane") or "")
        group = group_by_lane.get(from_lane_id)
        if not group or group != group_by_lane.get(to_lane_id):
            continue
        group_id, members = group
        link["same_physical_lane_continuity"] = True
        link["physical_lane_group_id"] = group_id
        link["physical_lane_group_policy"] = DIRECT_CONNECTOR_PHYSICAL_LANE_GROUP_POLICY
        link["physical_lane_group_member_count"] = len(members)
        append_physical_lane_group_link(
            lanes_by_id[from_lane_id],
            group_id=group_id,
            side="end",
            node_id=str(link.get("corner_node_id") or ""),
            linked_lane_id=to_lane_id,
            link=link,
        )
        append_physical_lane_group_link(
            lanes_by_id[to_lane_id],
            group_id=group_id,
            side="start",
            node_id=str(link.get("corner_node_id") or ""),
            linked_lane_id=from_lane_id,
            link=link,
        )
        grouped_links += 1

    group_ids = sorted({group_id for group_id, _members in group_by_lane.values()})
    return {
        "policy": DIRECT_CONNECTOR_PHYSICAL_LANE_GROUP_POLICY,
        "max_turn_deg": DIRECT_CONNECTOR_PHYSICAL_LANE_MAX_TURN_DEG,
        "max_endpoint_gap_m": DIRECT_CONNECTOR_PHYSICAL_LANE_MAX_ENDPOINT_GAP_M,
        "candidate_links": len(candidate_links),
        "links_grouped": grouped_links,
        "groups_created": len(group_ids),
        "lanes_grouped": len(group_by_lane),
        "group_ids": group_ids,
        "skipped": dict(sorted(skipped.items())),
    }


def physical_lane_group_sequences(
    lanes: list[dict[str, Any]],
    continuity_links: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lanes_by_id = {str(lane.get("lane_id") or ""): lane for lane in lanes if lane.get("lane_id")}
    group_members: dict[str, set[str]] = {}
    for lane in lanes:
        group_id = str(lane.get("physical_lane_group_id") or "")
        if group_id:
            group_members.setdefault(group_id, set()).add(str(lane.get("lane_id") or ""))

    next_by_group: dict[str, dict[str, str]] = {}
    prev_by_group: dict[str, dict[str, str]] = {}
    link_ids_by_pair: dict[tuple[str, str], str] = {}
    for link in continuity_links:
        if not bool(link.get("same_physical_lane_continuity")):
            continue
        group_id = str(link.get("physical_lane_group_id") or "")
        from_lane_id = str(link.get("from_lane") or "")
        to_lane_id = str(link.get("to_lane") or "")
        if not group_id or from_lane_id not in lanes_by_id or to_lane_id not in lanes_by_id:
            continue
        group_members.setdefault(group_id, set()).update([from_lane_id, to_lane_id])
        next_by_group.setdefault(group_id, {})[from_lane_id] = to_lane_id
        prev_by_group.setdefault(group_id, {})[to_lane_id] = from_lane_id
        link_ids_by_pair[(from_lane_id, to_lane_id)] = str(link.get("continuity_link_id") or "")

    sequences: list[dict[str, Any]] = []
    for group_id, member_set in sorted(group_members.items()):
        members = sorted(lane_id for lane_id in member_set if lane_id in lanes_by_id)
        if len(members) < 2:
            continue
        next_by_lane = next_by_group.get(group_id, {})
        prev_by_lane = prev_by_group.get(group_id, {})
        starts = sorted(lane_id for lane_id in members if lane_id not in prev_by_lane)
        starts = starts or members[:1]
        visited: set[str] = set()
        for start_lane_id in starts:
            lane_ids: list[str] = []
            continuity_link_ids: list[str] = []
            lane_id = start_lane_id
            while lane_id and lane_id in member_set and lane_id not in visited:
                visited.add(lane_id)
                lane_ids.append(lane_id)
                next_lane_id = next_by_lane.get(lane_id, "")
                if next_lane_id:
                    continuity_link_id = link_ids_by_pair.get((lane_id, next_lane_id), "")
                    if continuity_link_id:
                        continuity_link_ids.append(continuity_link_id)
                lane_id = next_lane_id
            if len(lane_ids) >= 2:
                sequences.append({
                    "group_id": group_id,
                    "lane_ids": lane_ids,
                    "continuity_link_ids": continuity_link_ids,
                    "sequence_status": "ordered_from_continuity_links",
                })
        for lane_id in members:
            if lane_id not in visited:
                sequences.append({
                    "group_id": group_id,
                    "lane_ids": [lane_id],
                    "continuity_link_ids": [],
                    "sequence_status": "unlinked_group_member",
                })
    return sequences


def joined_lane_centerline_points(lane_ids: list[str], lanes_by_id: dict[str, dict[str, Any]]) -> list[list[float]]:
    points: list[tuple[float, float]] = []
    for lane_id in lane_ids:
        lane_points = [
            (float(point[0]), float(point[1]))
            for point in (lanes_by_id.get(lane_id) or {}).get("centerline_xz") or []
            if len(point) >= 2
        ]
        if not lane_points:
            continue
        if points and distance(points[-1], lane_points[0]) <= 0.01:
            points.extend(lane_points[1:])
        else:
            points.extend(lane_points)
    return [[round(x, 3), round(z, 3)] for x, z in points]


def build_physical_lane_centerlines(
    lanes: list[dict[str, Any]],
    continuity_links: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    lanes_by_id = {str(lane.get("lane_id") or ""): lane for lane in lanes if lane.get("lane_id")}
    centerlines: list[dict[str, Any]] = []
    grouped_lane_ids: set[str] = set()

    for sequence in physical_lane_group_sequences(lanes, continuity_links):
        lane_ids = [str(lane_id) for lane_id in sequence.get("lane_ids") or []]
        if len(lane_ids) < 2:
            continue
        points = joined_lane_centerline_points(lane_ids, lanes_by_id)
        if len(points) < 2:
            continue
        source_lanes = [lanes_by_id[lane_id] for lane_id in lane_ids]
        widths = [float(lane.get("width_m") or DEFAULT_LANE_WIDTH_M) for lane in source_lanes]
        directions = sorted({str(lane.get("direction") or "") for lane in source_lanes if str(lane.get("direction") or "")})
        centerlines.append({
            "centerline_id": str(sequence.get("group_id") or ""),
            "source": "physical_lane_group_centerline_v1",
            "source_policy": DIRECT_CONNECTOR_PHYSICAL_LANE_GROUP_POLICY,
            "physical_lane_group_id": str(sequence.get("group_id") or ""),
            "physical_lane_group_policy": DIRECT_CONNECTOR_PHYSICAL_LANE_GROUP_POLICY,
            "source_lane_ids": lane_ids,
            "continuity_link_ids": list(sequence.get("continuity_link_ids") or []),
            "road_ids": [str(lane.get("road_id") or "") for lane in source_lanes],
            "direction": directions[0] if len(directions) == 1 else "mixed",
            "member_count": len(lane_ids),
            "centerline_xz": points,
            "width_m": round(sum(widths) / max(1, len(widths)), 3),
            "width_source": "source_lane_widths",
            "sequence_status": str(sequence.get("sequence_status") or ""),
        })
        grouped_lane_ids.update(lane_ids)

    for lane in lanes:
        lane_id = str(lane.get("lane_id") or "")
        if not lane_id or lane_id in grouped_lane_ids:
            continue
        points = [
            [round(float(point[0]), 3), round(float(point[1]), 3)]
            for point in lane.get("centerline_xz") or []
            if len(point) >= 2
        ]
        if len(points) < 2:
            continue
        centerlines.append({
            "centerline_id": lane_id,
            "source": "lane_centerline",
            "source_policy": "single_lane_segment_passthrough",
            "physical_lane_group_id": "",
            "physical_lane_group_policy": "",
            "source_lane_ids": [lane_id],
            "continuity_link_ids": [],
            "road_ids": [str(lane.get("road_id") or "")],
            "direction": str(lane.get("direction") or ""),
            "member_count": 1,
            "centerline_xz": points,
            "width_m": round(float(lane.get("width_m") or DEFAULT_LANE_WIDTH_M), 3),
            "width_source": str(lane.get("width_source") or "source_lane_width"),
            "sequence_status": "single_lane_segment",
        })

    stats = {
        "policy": "physical_lane_centerlines_v1",
        "group_policy": DIRECT_CONNECTOR_PHYSICAL_LANE_GROUP_POLICY,
        "centerlines": len(centerlines),
        "grouped_centerlines": sum(1 for centerline in centerlines if centerline["member_count"] > 1),
        "standalone_centerlines": sum(1 for centerline in centerlines if centerline["member_count"] == 1),
        "source_lane_segments_grouped": len(grouped_lane_ids),
    }
    return centerlines, stats


def add_direct_connector_links_for_direction(
    links: list[dict[str, Any]],
    *,
    node_id: str,
    edge_a_id: str,
    edge_b_id: str,
    incoming_lanes: list[dict[str, Any]],
    outgoing_lanes: list[dict[str, Any]],
    direction_index: int,
    turn_deg: float,
) -> None:
    for link_index, (from_lane, to_lane) in enumerate(match_corner_lanes(incoming_lanes, outgoing_lanes)):
        from_points = [(float(p[0]), float(p[1])) for p in from_lane.get("centerline_xz") or []]
        to_points = [(float(p[0]), float(p[1])) for p in to_lane.get("centerline_xz") or []]
        if not from_points or not to_points:
            continue
        endpoint_gap_m = distance(from_points[-1], to_points[0])
        if endpoint_gap_m > DIRECT_CONNECTOR_MAX_ENDPOINT_GAP_M:
            continue
        original_endpoint_gap_m = endpoint_gap_m
        micro_seam_absorbed = 0.0 < endpoint_gap_m <= DIRECT_CONNECTOR_MICRO_SEAM_SNAP_M
        if micro_seam_absorbed:
            seam_point = snap_direct_connector_micro_seam(
                node_id=node_id,
                from_lane=from_lane,
                to_lane=to_lane,
                original_endpoint_gap_m=original_endpoint_gap_m,
            )
            endpoint_gap_m = 0.0
            curve = [list(seam_point), list(seam_point)]
        else:
            curve = direct_continuity_curve(from_lane, to_lane)
        if len(curve) < 2:
            continue
        width_start = lane_endpoint_width(from_lane, node_id, "end")
        width_end = lane_endpoint_width(to_lane, node_id, "start")
        width_confidence = min(
            float(from_lane.get("width_confidence", 0.45)),
            float(to_lane.get("width_confidence", 0.45)),
        )
        stats = curve_stats(curve)
        links.append({
            "continuity_link_id": f"{node_id}_through_cl_{direction_index:02d}_{link_index:02d}",
            "corner_id": "",
            "corner_node_id": node_id,
            "from_road": from_lane["road_id"],
            "to_road": to_lane["road_id"],
            "from_lane": from_lane["lane_id"],
            "to_lane": to_lane["lane_id"],
            "turn": "through",
            "source": DIRECT_CONNECTOR_CONTINUITY_POLICY,
            "rounding_style_id": UNIFIED_LANE_GEOMETRY_ROUNDING_STYLE_ID,
            "rounding_curve_family": UNIFIED_ROUNDING_STRAIGHT_CURVE_FAMILY,
            "rounding_sample_strategy": "endpoint_snapped_micro_seam" if micro_seam_absorbed else "endpoint_locked_through_connector",
            "rounding_application": DIRECT_CONNECTOR_CONTINUITY_POLICY,
            "connecting_curve_xz": curve,
            "curve_length_m": stats["length_m"],
            "curve_sample_count": stats["sample_count"],
            "from_lane_trim_end_m": 0.0,
            "to_lane_trim_start_m": 0.0,
            "width_m": round((width_start + width_end) * 0.5, 3),
            "width_start_m": round(width_start, 3),
            "width_end_m": round(width_end, 3),
            "width_source": "connected_lane_widths",
            "width_confidence": round(width_confidence, 3),
            "turn_angle_deg": round(turn_deg, 3),
            "endpoint_gap_m": round(endpoint_gap_m, 3),
            "original_endpoint_gap_m": round(original_endpoint_gap_m, 3),
            "micro_seam_absorbed": micro_seam_absorbed,
            "micro_seam_policy": DIRECT_CONNECTOR_MICRO_SEAM_POLICY if micro_seam_absorbed else "",
            "micro_seam_snap_threshold_m": DIRECT_CONNECTOR_MICRO_SEAM_SNAP_M,
            "policy": DIRECT_CONNECTOR_CONTINUITY_POLICY,
            "edge_pair": [edge_a_id, edge_b_id],
        })


def build_direct_connector_continuity_links(
    *,
    graph: dict[str, Any],
    lanes: list[dict[str, Any]],
    corner_fillets: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    lanes_by_start: dict[tuple[str, str], list[dict[str, Any]]] = {}
    lanes_by_end: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for lane in lanes:
        lanes_by_start.setdefault((str(lane["from_node"]), str(lane["road_id"])), []).append(lane)
        lanes_by_end.setdefault((str(lane["to_node"]), str(lane["road_id"])), []).append(lane)

    edges = {str(edge.get("edge_id") or ""): edge for edge in graph.get("edges", [])}
    covered = {
        (
            str(corner.get("corner_node_id") or ""),
            tuple(sorted([str(corner.get("from_edge_id") or ""), str(corner.get("to_edge_id") or "")])),
        )
        for corner in corner_fillets
    }
    links: list[dict[str, Any]] = []
    skipped = Counter()
    nodes_considered = 0
    nodes_linked: set[str] = set()
    max_endpoint_gap = 0.0
    max_turn = 0.0
    for node in graph.get("nodes", []):
        node_id = str(node.get("node_id") or "")
        if str(node.get("kind") or "") != "connector" or int(node.get("degree") or 0) != 2:
            continue
        incident = [str(edge_id) for edge_id in node.get("incident_edges") or [] if str(edge_id) in edges]
        if len(incident) != 2:
            skipped["missing_incident_edge"] += 1
            continue
        pair_key = (node_id, tuple(sorted(incident)))
        if pair_key in covered:
            skipped["covered_by_corner_fillet"] += 1
            continue
        edge_a_id, edge_b_id = incident
        turn_deg = edge_turn_deg_at_connector(node_id, edges[edge_a_id], edges[edge_b_id])
        max_turn = max(max_turn, turn_deg)
        if turn_deg > DIRECT_CONNECTOR_MAX_TURN_DEG:
            skipped["above_turn_threshold"] += 1
            continue
        before = len(links)
        add_direct_connector_links_for_direction(
            links,
            node_id=node_id,
            edge_a_id=edge_a_id,
            edge_b_id=edge_b_id,
            incoming_lanes=lanes_by_end.get((node_id, edge_a_id), []),
            outgoing_lanes=lanes_by_start.get((node_id, edge_b_id), []),
            direction_index=0,
            turn_deg=turn_deg,
        )
        add_direct_connector_links_for_direction(
            links,
            node_id=node_id,
            edge_a_id=edge_b_id,
            edge_b_id=edge_a_id,
            incoming_lanes=lanes_by_end.get((node_id, edge_b_id), []),
            outgoing_lanes=lanes_by_start.get((node_id, edge_a_id), []),
            direction_index=1,
            turn_deg=turn_deg,
        )
        added = links[before:]
        nodes_considered += 1
        if not added:
            skipped["no_lane_pair_with_close_endpoints"] += 1
            continue
        nodes_linked.add(node_id)
        for link in added:
            max_endpoint_gap = max(max_endpoint_gap, float(link.get("endpoint_gap_m") or 0.0))

    physical_lane_group_stats = annotate_direct_connector_physical_lane_groups(lanes, links)
    stats = {
        "policy": DIRECT_CONNECTOR_CONTINUITY_POLICY,
        "micro_seam_policy": DIRECT_CONNECTOR_MICRO_SEAM_POLICY,
        "physical_lane_group_policy": DIRECT_CONNECTOR_PHYSICAL_LANE_GROUP_POLICY,
        "rounding_style_id": UNIFIED_LANE_GEOMETRY_ROUNDING_STYLE_ID,
        "rounding_curve_family": UNIFIED_ROUNDING_STRAIGHT_CURVE_FAMILY,
        "max_turn_deg": DIRECT_CONNECTOR_MAX_TURN_DEG,
        "max_endpoint_gap_m": DIRECT_CONNECTOR_MAX_ENDPOINT_GAP_M,
        "micro_seam_snap_threshold_m": DIRECT_CONNECTOR_MICRO_SEAM_SNAP_M,
        "physical_lane_grouping": physical_lane_group_stats,
        "connector_nodes_considered": nodes_considered,
        "connector_nodes_linked": len(nodes_linked),
        "links_created": len(links),
        "micro_seams_absorbed": sum(1 for link in links if bool(link.get("micro_seam_absorbed"))),
        "same_physical_lane_links": physical_lane_group_stats["links_grouped"],
        "physical_lane_groups_created": physical_lane_group_stats["groups_created"],
        "physical_lane_grouped_lanes": physical_lane_group_stats["lanes_grouped"],
        "max_created_endpoint_gap_m": round(max_endpoint_gap, 3),
        "max_observed_turn_deg": round(max_turn, 3),
        "skipped": dict(sorted(skipped.items())),
    }
    return links, stats


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
) -> tuple[list[dict[str, Any]], Counter, Counter]:
    nodes = {node["node_id"]: node for node in graph["nodes"]}
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
            lane_links = build_lane_link_records(
                from_candidates,
                to_candidates,
                movement,
                semantic["junction_id"],
                connection_index,
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
    lane_upgrades_path: Path | None = None,
    lane_upgrade_apply_road_ids: set[str] | None = None,
    apply_all_lane_upgrades: bool = False,
) -> dict[str, Any]:
    graph = read_json(input_path)
    semantics = read_json(semantics_path)
    optimized_refs = load_optimized_centerline_refs(optimized_centerlines_path)
    lane_upgrade_refs = load_lane_upgrade_overrides(lane_upgrades_path)
    optimized_approach_count = len(optimized_refs["approaches_by_edge"])
    lane_edges, optimized_approaches_applied = edges_with_optimized_approaches(
        graph["edges"],
        optimized_refs["approaches_by_edge"],
    )
    lane_edges, lane_upgrade_stats = apply_lane_upgrade_overrides(
        lane_edges,
        lane_upgrade_refs["active_upgrades_by_road"],
        apply_to_geometry=apply_all_lane_upgrades,
        apply_road_ids=lane_upgrade_apply_road_ids,
    )
    lane_edges, lane_bundle_smoothing_stats = apply_lane_bundle_centerline_smoothing(lane_edges)
    approach_centerlines_trimmed = optimized_approaches_applied > 0
    lanes = build_lanes(lane_edges)
    derived_smoothing_stats = apply_derived_lane_centerline_smoothing(lanes)
    corner_continuity_links = build_continuity_links(lanes, optimized_refs["corner_fillets"])
    direct_connector_links, direct_connector_continuity_stats = build_direct_connector_continuity_links(
        graph=graph,
        lanes=lanes,
        corner_fillets=optimized_refs["corner_fillets"],
    )
    continuity_links = corner_continuity_links + direct_connector_links
    physical_lane_centerlines, physical_lane_centerline_stats = build_physical_lane_centerlines(
        lanes,
        continuity_links,
    )
    junctions, fallback_counts, skipped_counts = build_junctions_from_semantics(
        graph,
        lanes,
        semantics,
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
    continuity_link_source_counts = Counter(str(link.get("source", "unknown")) for link in continuity_links)
    continuity_rounding_style_counts = Counter(str(link.get("rounding_style_id") or "none") for link in continuity_links)
    continuity_rounding_curve_family_counts = Counter(str(link.get("rounding_curve_family") or "none") for link in continuity_links)
    lane_level_radius_regularized_links = sum(1 for link in continuity_links if bool(link.get("lane_level_radius_regularized")))
    optimized_corner_continuity_radii = [
        float(link.get("lane_level_curve_min_radius_m") or 0.0)
        for link in continuity_links
        if str(link.get("source") or "") == "optimized_corner_fillet" and float(link.get("lane_level_curve_min_radius_m") or 0.0) > 0.0
    ]
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
    centerline_derivation_counts = Counter(str(lane.get("centerline_derivation_policy") or "none") for lane in lanes)
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
            "lane_upgrade_system": LANE_UPGRADE_SYSTEM_ID,
            "lane_upgrade_overrides_source": lane_upgrade_refs["path"],
            "lane_upgrade_override_schema": lane_upgrade_refs["schema"],
            "lane_upgrade_geometry_application_policy": lane_upgrade_stats["geometry_application_policy"],
            "lane_upgrade_deferred_road_ids": lane_upgrade_stats["deferred_road_ids"],
            "junction_lane_strategy": "semantic_lane_endpoint_bezier",
            "corner_continuity_strategy": "optimized_corner_fillet_and_direct_degree2_connector_through",
            "physical_lane_centerlines": physical_lane_centerline_stats,
            "lane_geometry_rounding_style": lane_geometry_rounding_style_config(),
            "direct_connector_continuity": direct_connector_continuity_stats,
            "lane_bundle_centerline_smoothing": lane_bundle_smoothing_stats,
            "temporary_lane_policy": TEMPORARY_LANE_POLICY_ID,
            "traffic_side_assumption": TEMPORARY_TRAFFIC_SIDE,
            "traffic_direction_strategy": "force_every_edge_bidirectional_two_lane",
            "approach_centerlines_trimmed": approach_centerlines_trimmed,
            "derived_lane_centerline_smoothing": derived_smoothing_stats,
            "lane_width_m": DEFAULT_LANE_WIDTH_M,
            "width_strategy": "fixed_lane_width",
            "junction_trim_m": JUNCTION_TRIM_M,
            "curve_sample_count": CURVE_SAMPLE_COUNT,
            "design_note": "Semantic-driven junction laneLinks stay separate from degree-2 corner continuity links.",
        },
        "lanes": lanes,
        "physical_lane_centerlines": physical_lane_centerlines,
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
            "physical_lane_centerlines": len(physical_lane_centerlines),
            "physical_lane_group_centerlines": physical_lane_centerline_stats["grouped_centerlines"],
            "standalone_physical_lane_centerlines": physical_lane_centerline_stats["standalone_centerlines"],
            "junctions": total_junctions,
            "approach_lane_records": sum(len(junction["approach_lanes"]) for junction in junctions),
            "connections": connection_count,
            "lane_links": lane_link_count,
            "continuity_links": len(continuity_links),
            "optimized_approach_centerlines": optimized_approach_count,
            "optimized_approach_centerlines_applied": optimized_approaches_applied,
            "optimized_junction_connectors": len(optimized_refs["junction_connectors"]),
            "optimized_junction_connector_lane_links": 0,
            "optimized_corner_fillet_links": len(corner_continuity_links),
            "direct_connector_continuity_links": len(direct_connector_links),
            "same_physical_lane_continuity_links": direct_connector_continuity_stats["same_physical_lane_links"],
            "physical_lane_groups_created": direct_connector_continuity_stats["physical_lane_groups_created"],
            "physical_lane_grouped_lanes": direct_connector_continuity_stats["physical_lane_grouped_lanes"],
            "active_lane_upgrades": len(lane_upgrade_refs["active_upgrades_by_road"]),
            "active_lane_upgrades_applied": len(lane_upgrade_stats["applied_road_ids"]),
            "active_lane_upgrades_deferred": len(lane_upgrade_stats["deferred_road_ids"]),
            "active_lane_upgrades_missing_roads": len(lane_upgrade_stats["missing_road_ids"]),
            "active_lane_upgrades_ignored": len(lane_upgrade_refs["ignored"]),
            "lane_bundle_centerline_smoothed_edges": lane_bundle_smoothing_stats["smoothed_edge_count"],
            "lane_bundle_centerline_smoothed_bends": lane_bundle_smoothing_stats["smoothed_bend_count"],
            "derived_lane_centerline_smoothed_lanes": derived_smoothing_stats["smoothed_lane_count"],
            "derived_lane_centerline_smoothed_bends": derived_smoothing_stats["smoothed_bend_count"],
            "derived_lane_centerline_inserted_sample_points": derived_smoothing_stats["inserted_sample_points"],
            "lane_level_radius_regularized_continuity_links": lane_level_radius_regularized_links,
            "fan_fallback_junctions": fan_fallback,
        },
        "lane_bundle_centerline_smoothing": lane_bundle_smoothing_stats,
        "derived_lane_centerline_smoothing": derived_smoothing_stats,
        "physical_lane_centerlines": physical_lane_centerline_stats,
        "direct_connector_continuity": direct_connector_continuity_stats,
        "lane_upgrade_system": {
            "system": LANE_UPGRADE_SYSTEM_ID,
            "overrides_source": lane_upgrade_refs["path"],
            "geometry_application_policy": lane_upgrade_stats["geometry_application_policy"],
            "applied_road_ids": lane_upgrade_stats["applied_road_ids"],
            "deferred_road_ids": lane_upgrade_stats["deferred_road_ids"],
            "missing_road_ids": lane_upgrade_stats["missing_road_ids"],
            "ignored": lane_upgrade_refs["ignored"],
            "distribution_policy": "balanced_bidirectional_left_traffic_v1",
            "note": "Manual lane upgrades are applied to geometry according to geometry_application_policy; source map, canonical and road_graph truth layers remain unchanged.",
        },
        "junction_type_counts": dict(sorted(junction_type_counts.items())),
        "turn_counts": dict(sorted(turn_counts.items())),
        "lane_source_counts": dict(sorted(source_counts.items())),
        "lane_centerline_source_counts": dict(sorted(centerline_source_counts.items())),
        "lane_centerline_derivation_counts": dict(sorted(centerline_derivation_counts.items())),
        "width_source_counts": dict(sorted(width_source_counts.items())),
        "connection_source_counts": dict(sorted(connection_source_counts.items())),
        "lane_link_source_counts": dict(sorted(lane_link_source_counts.items())),
        "lane_link_curve_source_counts": dict(sorted(lane_link_curve_source_counts.items())),
        "lane_link_connector_kind_counts": dict(sorted(lane_link_connector_kind_counts.items())),
        "continuity_link_source_counts": dict(sorted(continuity_link_source_counts.items())),
        "continuity_rounding_style_counts": dict(sorted(continuity_rounding_style_counts.items())),
        "continuity_rounding_curve_family_counts": dict(sorted(continuity_rounding_curve_family_counts.items())),
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
            "lane_bundle_centerline_smoothed_edges": lane_bundle_smoothing_stats["smoothed_edge_count"],
            "lane_bundle_centerline_smoothed_bends": lane_bundle_smoothing_stats["smoothed_bend_count"],
            "lane_bundle_centerline_max_min_arc_radius_m": lane_bundle_smoothing_stats["max_min_arc_radius_m"],
            "derived_lane_centerline_smoothed_lanes": derived_smoothing_stats["smoothed_lane_count"],
            "derived_lane_centerline_smoothed_bends": derived_smoothing_stats["smoothed_bend_count"],
            "derived_lane_centerline_inserted_sample_points": derived_smoothing_stats["inserted_sample_points"],
            "derived_lane_centerline_max_derivation_offset_m": derived_smoothing_stats["max_derivation_offset_m"],
            "derived_lane_centerline_max_source_bend_offset_m": derived_smoothing_stats["max_source_bend_offset_m"],
            "derived_lane_centerline_smoothing_curve_family_counts": derived_smoothing_stats.get("curve_family_counts", {}),
            "derived_lane_centerline_smoothing_arc_fit_status_counts": derived_smoothing_stats.get("arc_fit_status_counts", {}),
            "continuity_rounding_style_counts": dict(sorted(continuity_rounding_style_counts.items())),
            "continuity_rounding_curve_family_counts": dict(sorted(continuity_rounding_curve_family_counts.items())),
            "lane_level_radius_regularized_continuity_links": lane_level_radius_regularized_links,
            "physical_lane_centerlines": len(physical_lane_centerlines),
            "physical_lane_group_centerlines": physical_lane_centerline_stats["grouped_centerlines"],
            "standalone_physical_lane_centerlines": physical_lane_centerline_stats["standalone_centerlines"],
            "same_physical_lane_continuity_links": direct_connector_continuity_stats["same_physical_lane_links"],
            "physical_lane_groups_created": direct_connector_continuity_stats["physical_lane_groups_created"],
            "physical_lane_grouped_lanes": direct_connector_continuity_stats["physical_lane_grouped_lanes"],
            "min_optimized_corner_continuity_radius_m": round(min(optimized_corner_continuity_radii), 3) if optimized_corner_continuity_radii else 0.0,
        },
        "notes": [
            "M2/M3 redesign: lane graph now consumes junction_semantics road-level movements.",
            "Temporary policy: every source road is generated as bidirectional two-lane geometry, including source one-way roads.",
            "LaneForge lane upgrades can override the generated physical lane count per road through versioned transactions.",
            "Derived lane centerline smoothing only adds low-offset samples to lane_graph/lane_surface outputs; raw/repaired/canonical/road_graph truth layers are unchanged.",
            "physical_lane_centerlines is the clean continuous lane centerline contract; lanes remain source road-edge lane segments.",
            "Final lane centerline smoothing and continuity links declare unified_lane_geometry_rounding_style_v1 for consistent downstream road styling.",
            "Lane widths use a fixed default width for this replay state.",
            "Junction laneLinks are generated only for allowed semantic movements and stay independent from road-level optimized junction connectors.",
            "Degree-2 road bends are bridged by optimized_corner_fillet continuity links; near-straight degree-2 connectors get direct through continuity links.",
            "Near-straight degree-2 direct connector links with endpoint gaps inside the micro-seam threshold are annotated as derived physical lane groups without merging road truth layers.",
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
    parser.add_argument("--lane-upgrades", default="")
    parser.add_argument(
        "--apply-lane-upgrade-road-id",
        action="append",
        default=[],
        help="Apply an active lane upgrade to geometry for this explicit road id. Can be repeated.",
    )
    parser.add_argument(
        "--apply-all-lane-upgrades",
        action="store_true",
        help="Apply all active lane upgrades to geometry. Use only for controlled review.",
    )
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
    lane_upgrades_path = (
        Path(args.lane_upgrades)
        if args.lane_upgrades
        else root / "data" / "processed" / f"{args.area_id}_lane_upgrade_overrides.json"
    )
    if not lane_upgrades_path.exists():
        lane_upgrades_path = None
    output_path = Path(args.output) if args.output else root / "data" / "processed" / f"{args.area_id}_lane_graph.json"
    report_path = Path(args.report) if args.report else root / "reports" / f"{args.area_id}_lane_graph_report.json"

    report = build_lane_graph(
        input_path,
        semantics_path,
        output_path,
        report_path,
        args.area_id,
        optimized_centerlines_path,
        lane_upgrades_path,
        set(args.apply_lane_upgrade_road_id or []),
        args.apply_all_lane_upgrades,
    )
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
