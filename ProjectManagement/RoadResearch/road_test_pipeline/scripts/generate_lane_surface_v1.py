#!/usr/bin/env python3
"""Generate first-pass lane and turn connection surfaces from lane_graph.json.

This stage promotes validated laneLinks into actual surface polygons, but it
keeps the output separate from the default centerline Houdini display. It is a
geometry experiment, not the final curb/envelope/marking builder.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_LANE_WIDTH_M = 3.2
DEFAULT_JUNCTION_TRIM_M = 8.0


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


def polygon_area(poly: list[tuple[float, float]]) -> float:
    clean = poly[:-1] if len(poly) > 2 and poly[0] == poly[-1] else poly
    if len(clean) < 3:
        return 0.0
    twice_area = 0.0
    for i, point in enumerate(clean):
        nxt = clean[(i + 1) % len(clean)]
        twice_area += point[0] * nxt[1] - nxt[0] * point[1]
    return abs(twice_area) * 0.5


def normalize(v: tuple[float, float]) -> tuple[float, float]:
    length = math.sqrt(v[0] * v[0] + v[1] * v[1])
    if length <= 1e-9:
        return 0.0, 0.0
    return v[0] / length, v[1] / length


def rotate90(v: tuple[float, float]) -> tuple[float, float]:
    return -v[1], v[0]


def as_points(coords: list[list[float]]) -> list[tuple[float, float]]:
    return [(float(point[0]), float(point[1])) for point in coords]


def round_line(points: list[tuple[float, float]]) -> list[list[float]]:
    return [[round(x, 3), round(z, 3)] for x, z in points]


def round_polygon(points: list[tuple[float, float]]) -> list[list[list[float]]]:
    return [round_line(points)]


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


def trim_polyline(
    points: list[tuple[float, float]],
    trim_start_m: float,
    trim_end_m: float,
    locked_start_m: float = 0.0,
    locked_end_m: float = 0.0,
) -> list[tuple[float, float]]:
    if len(points) < 2:
        return []
    length = polyline_length(points)
    if length <= 0.05:
        return []
    trim_start_m, trim_end_m = resolve_trim_distances(
        length,
        trim_start_m,
        trim_end_m,
        locked_start_m,
        locked_end_m,
    )

    def point_at(distance_m: float) -> tuple[float, float]:
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

    start_distance = trim_start_m
    end_distance = max(start_distance + 0.05, length - trim_end_m)
    trimmed = [point_at(start_distance)]
    cursor = 0.0
    for i in range(len(points) - 1):
        seg_len = distance(points[i], points[i + 1])
        next_cursor = cursor + seg_len
        if start_distance < next_cursor and cursor < end_distance:
            if start_distance < next_cursor and points[i] != trimmed[-1] and cursor >= start_distance:
                trimmed.append(points[i])
            if next_cursor <= end_distance:
                trimmed.append(points[i + 1])
        cursor = next_cursor
    end_point = point_at(end_distance)
    if not trimmed or distance(trimmed[-1], end_point) > 0.01:
        trimmed.append(end_point)
    return trimmed if polyline_length(trimmed) > 0.05 else []


def ribbon_polygon(points: list[tuple[float, float]], width_m: float) -> list[tuple[float, float]]:
    return tapered_ribbon_polygon(points, width_m, width_m)


def tapered_ribbon_polygon(points: list[tuple[float, float]], width_start_m: float, width_end_m: float) -> list[tuple[float, float]]:
    if len(points) < 2:
        return []
    factors = station_factors(points)
    left: list[tuple[float, float]] = []
    right: list[tuple[float, float]] = []
    for i, point in enumerate(points):
        if i == 0:
            tangent = normalize((points[1][0] - point[0], points[1][1] - point[1]))
        elif i == len(points) - 1:
            tangent = normalize((point[0] - points[i - 1][0], point[1] - points[i - 1][1]))
        else:
            prev_tangent = normalize((point[0] - points[i - 1][0], point[1] - points[i - 1][1]))
            next_tangent = normalize((points[i + 1][0] - point[0], points[i + 1][1] - point[1]))
            tangent = normalize((prev_tangent[0] + next_tangent[0], prev_tangent[1] + next_tangent[1]))
            if tangent == (0.0, 0.0):
                tangent = next_tangent
        normal = rotate90(tangent)
        half = lerp(width_start_m, width_end_m, factors[i]) * 0.5
        left.append((point[0] + normal[0] * half, point[1] + normal[1] * half))
        right.append((point[0] - normal[0] * half, point[1] - normal[1] * half))
    poly = left + list(reversed(right))
    if poly and poly[0] != poly[-1]:
        poly.append(poly[0])
    return poly


def lane_link_records(lane_graph: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for junction in lane_graph.get("junctions", []):
        for connection in junction.get("connections", []):
            for link in connection.get("lane_links", []):
                item = dict(link)
                item["junction_id"] = junction["junction_id"]
                item["connection_id"] = connection["connection_id"]
                item["connection_turn"] = connection.get("turn", "")
                records.append(item)
    return records


def continuity_link_records(lane_graph: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(link) for link in lane_graph.get("continuity_links", [])]


def lane_trim_roles(lane_links: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    trim_end_lanes = {str(link.get("from_lane") or "") for link in lane_links}
    trim_start_lanes = {str(link.get("to_lane") or "") for link in lane_links}
    trim_end_lanes.discard("")
    trim_start_lanes.discard("")
    return trim_start_lanes, trim_end_lanes


def lane_trim_distances(
    lane_graph: dict[str, Any],
    lane_links: list[dict[str, Any]],
    continuity_links: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, float]], set[str]]:
    trim_m = float(lane_graph.get("metadata", {}).get("junction_trim_m") or DEFAULT_JUNCTION_TRIM_M)
    lanes_by_id = {str(lane.get("lane_id") or ""): lane for lane in lane_graph.get("lanes", [])}
    trim_by_lane: dict[str, dict[str, float]] = {}
    corner_trimmed_lanes: set[str] = set()

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
        from_lane = str(link.get("from_lane") or "")
        to_lane = str(link.get("to_lane") or "")
        update(from_lane, "end", link_trim_value(link, "from_lane_trim_end_m", default_lane_link_trim(from_lane)))
        update(to_lane, "start", link_trim_value(link, "to_lane_trim_start_m", default_lane_link_trim(to_lane)))

    for link in continuity_links:
        from_lane = str(link.get("from_lane") or "")
        to_lane = str(link.get("to_lane") or "")
        from_trim = float(link.get("from_lane_trim_end_m") or 0.0)
        to_trim = float(link.get("to_lane_trim_start_m") or 0.0)
        lock(from_lane, "end", from_trim)
        lock(to_lane, "start", to_trim)
        if from_lane:
            corner_trimmed_lanes.add(from_lane)
        if to_lane:
            corner_trimmed_lanes.add(to_lane)

    return trim_by_lane, corner_trimmed_lanes


def build_features(lane_graph: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    features: list[dict[str, Any]] = []
    lanes_by_id = {str(lane.get("lane_id") or ""): lane for lane in lane_graph.get("lanes", [])}
    lane_links = lane_link_records(lane_graph)
    continuity_links = continuity_link_records(lane_graph)
    metadata = lane_graph.get("metadata", {})
    trim_m = float(metadata.get("junction_trim_m") or DEFAULT_JUNCTION_TRIM_M)
    trim_by_lane, corner_trimmed_lanes = lane_trim_distances(lane_graph, lane_links, continuity_links)

    counts: Counter = Counter()
    area_by_part: Counter = Counter()

    for lane in lane_graph.get("lanes", []):
        lane_id = str(lane.get("lane_id") or "")
        points = as_points(lane.get("centerline_xz") or [])
        if len(points) < 2:
            counts["skipped_short_lane"] += 1
            continue
        lane_trim = trim_by_lane.get(lane_id, {})
        trim_start = float(lane_trim.get("start") or 0.0)
        trim_end = float(lane_trim.get("end") or 0.0)
        trimmed = trim_polyline(
            points,
            trim_start,
            trim_end,
            float(lane_trim.get("locked_start") or 0.0),
            float(lane_trim.get("locked_end") or 0.0),
        )
        if len(trimmed) < 2:
            counts["skipped_trimmed_lane"] += 1
            continue
        width = DEFAULT_LANE_WIDTH_M
        width_start = DEFAULT_LANE_WIDTH_M
        width_end = DEFAULT_LANE_WIDTH_M
        polygon = ribbon_polygon(trimmed, width)
        if not polygon:
            counts["skipped_lane_surface_polygon"] += 1
            continue
        area = polygon_area(polygon)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": round_polygon(polygon)},
            "properties": {
                "vc_part": "lane_surface_v1",
                "lane_id": lane_id,
                "road_id": lane.get("road_id", ""),
                "direction": lane.get("direction", ""),
                "width_m": width,
                "width_start_m": width_start,
                "width_end_m": width_end,
                "road_width_m": float(lane.get("road_width_m") or DEFAULT_LANE_WIDTH_M),
                "road_width_start_m": float(lane.get("road_width_start_m") or lane.get("road_width_m") or DEFAULT_LANE_WIDTH_M),
                "road_width_end_m": float(lane.get("road_width_end_m") or lane.get("road_width_m") or DEFAULT_LANE_WIDTH_M),
                "width_source": "fixed_default",
                "width_confidence": 0.45,
                "trim_start_m": round(trim_start, 3),
                "trim_end_m": round(trim_end, 3),
                "length_m": round(polyline_length(trimmed), 3),
                "area_m2": round(area, 3),
                "source": lane.get("source", "unknown"),
            },
        })
        counts["lane_surfaces"] += 1
        area_by_part["lane_surface_v1"] += area

    for link in lane_links:
        points = as_points(link.get("connecting_curve_xz") or [])
        if len(points) < 2:
            counts["skipped_empty_lane_link_curve"] += 1
            continue
        width = DEFAULT_LANE_WIDTH_M
        width_start = DEFAULT_LANE_WIDTH_M
        width_end = DEFAULT_LANE_WIDTH_M
        polygon = ribbon_polygon(points, width)
        if not polygon:
            counts["skipped_turn_surface_polygon"] += 1
            continue
        area = polygon_area(polygon)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": round_polygon(polygon)},
            "properties": {
                "vc_part": "lane_turn_surface_v1",
                "lane_link_id": link.get("lane_link_id", ""),
                "junction_id": link.get("junction_id", ""),
                "connection_id": link.get("connection_id", ""),
                "from_lane": link.get("from_lane", ""),
                "to_lane": link.get("to_lane", ""),
                "turn": link.get("turn", link.get("connection_turn", "")),
                "confidence": float(link.get("confidence", 0.0)),
                "width_m": width,
                "width_start_m": width_start,
                "width_end_m": width_end,
                "width_source": "fixed_default",
                "width_confidence": 0.45,
                "length_m": round(polyline_length(points), 3),
                "area_m2": round(area, 3),
            },
        })
        counts["lane_turn_surfaces"] += 1
        area_by_part["lane_turn_surface_v1"] += area

    for link in continuity_links:
        points = as_points(link.get("connecting_curve_xz") or [])
        if len(points) < 2:
            counts["skipped_empty_continuity_curve"] += 1
            continue
        width = DEFAULT_LANE_WIDTH_M
        width_start = DEFAULT_LANE_WIDTH_M
        width_end = DEFAULT_LANE_WIDTH_M
        polygon = ribbon_polygon(points, width)
        if not polygon:
            counts["skipped_continuity_surface_polygon"] += 1
            continue
        area = polygon_area(polygon)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": round_polygon(polygon)},
            "properties": {
                "vc_part": "lane_continuity_surface_v1",
                "continuity_link_id": link.get("continuity_link_id", ""),
                "corner_id": link.get("corner_id", ""),
                "corner_node_id": link.get("corner_node_id", ""),
                "from_lane": link.get("from_lane", ""),
                "to_lane": link.get("to_lane", ""),
                "from_road": link.get("from_road", ""),
                "to_road": link.get("to_road", ""),
                "turn": link.get("turn", "corner"),
                "source": link.get("source", "unknown"),
                "width_m": width,
                "width_start_m": width_start,
                "width_end_m": width_end,
                "width_source": "fixed_default",
                "width_confidence": 0.45,
                "length_m": round(polyline_length(points), 3),
                "area_m2": round(area, 3),
            },
        })
        counts["lane_continuity_surfaces"] += 1
        area_by_part["lane_continuity_surface_v1"] += area

    metrics = {
        "trim_start_lane_count": sum(1 for item in trim_by_lane.values() if item.get("start", 0.0) > 0.0),
        "trim_end_lane_count": sum(1 for item in trim_by_lane.values() if item.get("end", 0.0) > 0.0),
        "junction_trim_m": trim_m,
        "approach_centerlines_trimmed": bool(metadata.get("approach_centerlines_trimmed")),
        "corner_continuity_trimmed_lane_count": len(corner_trimmed_lanes),
        "avg_lane_surface_width_m": round(
            sum(float(feature.get("properties", {}).get("width_m", 0.0)) for feature in features if feature.get("properties", {}).get("vc_part") == "lane_surface_v1")
            / max(1, counts["lane_surfaces"]),
            3,
        ),
        "avg_turn_surface_width_m": round(
            sum(float(feature.get("properties", {}).get("width_m", 0.0)) for feature in features if feature.get("properties", {}).get("vc_part") == "lane_turn_surface_v1")
            / max(1, counts["lane_turn_surfaces"]),
            3,
        ),
        "avg_continuity_surface_width_m": round(
            sum(float(feature.get("properties", {}).get("width_m", 0.0)) for feature in features if feature.get("properties", {}).get("vc_part") == "lane_continuity_surface_v1")
            / max(1, counts["lane_continuity_surfaces"]),
            3,
        ),
        "area_by_part_m2": {key: round(value, 3) for key, value in area_by_part.items()},
        "total_area_m2": round(sum(area_by_part.values()), 3),
    }
    return features, {"counts": dict(counts), "metrics": metrics}


def write_geojson(path: Path, area_id: str, lane_graph: dict[str, Any]) -> dict[str, Any]:
    features, stats = build_features(lane_graph)
    write_json(path, {
        "type": "FeatureCollection",
        "metadata": {
            "area_id": area_id,
            "schema": "road_test_pipeline.lane_surfaces_v1",
            "coord_domain": "local_xz_m",
            "source": "lane_graph.json",
            "design_note": "First lane-level surface pass; junction envelope, curbs and markings are deferred.",
        },
        "features": features,
    })
    return stats


def obj_face_indices(vertices: list[tuple[float, float, float]], polygon: list[list[float]], y: float) -> list[int]:
    points = [(float(point[0]), float(point[1])) for point in polygon]
    clean = points[:-1] if len(points) > 2 and points[0] == points[-1] else points
    start = len(vertices) + 1
    for x, z in clean:
        vertices.append((x, y, -z))
    return list(range(start, start + len(clean)))


def write_obj(path: Path, features: list[dict[str, Any]]) -> dict[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    vertices: list[tuple[float, float, float]] = []
    faces_by_group: list[tuple[str, list[int]]] = []
    for feature in features:
        geom = feature.get("geometry") or {}
        if geom.get("type") != "Polygon":
            continue
        props = feature.get("properties") or {}
        group = str(props.get("vc_part") or "surface")
        rings = geom.get("coordinates") or []
        if not rings:
            continue
        face = obj_face_indices(vertices, rings[0], 0.02 if group == "lane_surface_v1" else 0.05)
        faces_by_group.append((group, face))

    with path.open("w", encoding="utf-8") as f:
        f.write("# road_test_pipeline lane surfaces v1 OBJ\n")
        for x, y, z in vertices:
            f.write(f"v {x:.4f} {y:.4f} {z:.4f}\n")
        current_group = None
        for group, face in faces_by_group:
            if group != current_group:
                f.write(f"g {group}\n")
                current_group = group
            f.write("f " + " ".join(str(index) for index in face) + "\n")
    return {
        "obj_vertices": len(vertices),
        "obj_faces": len(faces_by_group),
    }


def bounds_for(features: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    points = []
    for feature in features:
        geom = feature.get("geometry") or {}
        if geom.get("type") != "Polygon":
            continue
        for ring in geom.get("coordinates") or []:
            points.extend((float(point[0]), float(point[1])) for point in ring)
    min_x = min(point[0] for point in points)
    max_x = max(point[0] for point in points)
    min_z = min(point[1] for point in points)
    max_z = max(point[1] for point in points)
    pad = 25.0
    return min_x - pad, min_z - pad, max_x + pad, max_z + pad


def svg_point(point: tuple[float, float], bounds: tuple[float, float, float, float], scale: float, margin: float) -> tuple[float, float]:
    min_x, min_z, _max_x, max_z = bounds
    return margin + (point[0] - min_x) * scale, margin + (max_z - point[1]) * scale


def write_svg(path: Path, area_id: str, features: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bounds = bounds_for(features)
    width_m = bounds[2] - bounds[0]
    height_m = bounds[3] - bounds[1]
    margin = 50
    canvas_w = 1200
    canvas_h = max(800, int(canvas_w * height_m / max(width_m, 1.0)))
    scale = min((canvas_w - margin * 2) / width_m, (canvas_h - margin * 2) / height_m)

    def polygon_points(ring: list[list[float]]) -> str:
        return " ".join(
            f"{x:.2f},{y:.2f}"
            for x, y in (
                svg_point((float(point[0]), float(point[1])), bounds, scale, margin)
                for point in ring
            )
        )

    turn_colors = {
        "left": "#2563EB",
        "right": "#D97706",
        "through": "#059669",
    }
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w}" height="{canvas_h}" viewBox="0 0 {canvas_w} {canvas_h}">',
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        f'<text x="40" y="34" font-family="Arial, Microsoft YaHei" font-size="22" font-weight="700" fill="#111827">{area_id} lane surfaces v1</text>',
        '<text x="40" y="58" font-family="Arial, Microsoft YaHei" font-size="13" fill="#475569">Approach lane surfaces plus laneLink turn surfaces; no junction envelope yet</text>',
    ]
    for feature in features:
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        rings = geom.get("coordinates") or []
        if geom.get("type") != "Polygon" or not rings:
            continue
        part = props.get("vc_part")
        if part == "lane_surface_v1":
            fill = "#CBD5E1"
            opacity = "0.32"
            stroke = "#94A3B8"
        elif part == "lane_continuity_surface_v1":
            fill = "#0F766E"
            opacity = "0.42"
            stroke = fill
        else:
            fill = turn_colors.get(str(props.get("turn") or "through"), "#7C3AED")
            opacity = "0.46"
            stroke = fill
        lines.append(
            f'<polygon points="{polygon_points(rings[0])}" fill="{fill}" fill-opacity="{opacity}" '
            f'stroke="{stroke}" stroke-width="0.5" stroke-opacity="0.72"/>'
        )
    counts = Counter((feature.get("properties") or {}).get("vc_part", "unknown") for feature in features)
    lines.append(f'<text x="40" y="{canvas_h - 50}" font-family="Arial, Microsoft YaHei" font-size="13" fill="#334155">surfaces: {dict(counts)}</text>')
    lines.append("</svg>")
    path.write_text("\n".join(lines), encoding="utf-8")


def generate(area_id: str, root: Path) -> dict[str, Any]:
    lane_graph_path = root / "data" / "processed" / f"{area_id}_lane_graph.json"
    preview = root / "data" / "preview"
    reports = root / "reports"
    lane_graph = read_json(lane_graph_path)

    geojson_path = preview / f"{area_id}_lane_surfaces_v1.geojson"
    obj_path = preview / f"{area_id}_lane_surfaces_v1.obj"
    svg_path = preview / f"{area_id}_lane_surfaces_v1.svg"
    report_path = reports / f"{area_id}_lane_surface_v1_report.json"

    stats = write_geojson(geojson_path, area_id, lane_graph)
    surface_geojson = read_json(geojson_path)
    features = surface_geojson.get("features", [])
    obj_counts = write_obj(obj_path, features)
    write_svg(svg_path, area_id, features)

    counts = {
        "lanes": len(lane_graph.get("lanes", [])),
        "lane_links": len(lane_link_records(lane_graph)),
        "continuity_links": len(continuity_link_records(lane_graph)),
        **stats["counts"],
        **obj_counts,
    }
    report = {
        "area_id": area_id,
        "stage": "lane_surface_v1",
        "input": str(lane_graph_path),
        "outputs": {
            "geojson": str(geojson_path),
            "obj": str(obj_path),
            "svg": str(svg_path),
        },
        "counts": counts,
        "metrics": stats["metrics"],
        "notes": [
            "Approach lane surfaces use optimized trimmed centerlines when available; raw fallback still trims near junctions using laneLink membership.",
            "LaneLink turn surfaces are generated from connector curves.",
            "Continuity surfaces are generated from optimized corner fillet lane links for degree-2 road bends.",
            "Junction envelope, curb, island, sidewalk and marking generation are deferred.",
        ],
    }
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate first-pass lane surfaces from lane_graph.json.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    report = generate(args.area_id, root)
    print(json.dumps({
        "area_id": args.area_id,
        "outputs": report["outputs"],
        "counts": report["counts"],
        "metrics": report["metrics"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
