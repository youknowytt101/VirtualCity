#!/usr/bin/env python3
"""Generate lane-level debug geometry from lane_graph.json.

This is not the final road surface builder. It creates narrow lane and
laneLink ribbons so semantic lane connections can be inspected before
committing to full road surfaces, curbs and markings.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


LANE_RIBBON_WIDTH_M = 0.7
LANE_LINK_RIBBON_WIDTH_M = 1.0
DEFAULT_JUNCTION_TRIM_M = 8.0
LANE_LINE_Y = 0.18
LANE_LINK_LINE_Y = 0.26
RIBBON_Y = 0.03


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


def normalize(v: tuple[float, float]) -> tuple[float, float]:
    length = math.sqrt(v[0] * v[0] + v[1] * v[1])
    if length <= 1e-9:
        return 0.0, 0.0
    return v[0] / length, v[1] / length


def rotate90(v: tuple[float, float]) -> tuple[float, float]:
    return -v[1], v[0]


def as_points(coords: list[list[float]]) -> list[tuple[float, float]]:
    return [(float(point[0]), float(point[1])) for point in coords]


def ribbon_polygon(points: list[tuple[float, float]], width_m: float) -> list[tuple[float, float]]:
    if len(points) < 2:
        return []
    half = width_m * 0.5
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
        left.append((point[0] + normal[0] * half, point[1] + normal[1] * half))
        right.append((point[0] - normal[0] * half, point[1] - normal[1] * half))
    polygon = left + list(reversed(right))
    if polygon and polygon[0] != polygon[-1]:
        polygon.append(polygon[0])
    return polygon


def round_line(points: list[tuple[float, float]]) -> list[list[float]]:
    return [[round(x, 3), round(z, 3)] for x, z in points]


def round_polygon(points: list[tuple[float, float]]) -> list[list[list[float]]]:
    return [round_line(points)]


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


def is_micro_seam_continuity(link: dict[str, Any]) -> bool:
    return bool(link.get("micro_seam_absorbed"))


def lane_trim_distances(
    lane_graph: dict[str, Any],
    lane_links: list[dict[str, Any]],
    continuity_links: list[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    trim_m = float(lane_graph.get("metadata", {}).get("junction_trim_m") or DEFAULT_JUNCTION_TRIM_M)
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
        from_lane = str(link.get("from_lane") or "")
        to_lane = str(link.get("to_lane") or "")
        update(from_lane, "end", link_trim_value(link, "from_lane_trim_end_m", default_lane_link_trim(from_lane)))
        update(to_lane, "start", link_trim_value(link, "to_lane_trim_start_m", default_lane_link_trim(to_lane)))

    for link in continuity_links:
        lock(str(link.get("from_lane") or ""), "end", float(link.get("from_lane_trim_end_m") or 0.0))
        lock(str(link.get("to_lane") or ""), "start", float(link.get("to_lane_trim_start_m") or 0.0))

    return trim_by_lane


def trimmed_lane_points(lane: dict[str, Any], trim_by_lane: dict[str, dict[str, float]]) -> list[tuple[float, float]]:
    lane_id = str(lane.get("lane_id") or "")
    raw_points = as_points(lane.get("centerline_xz") or [])
    lane_trim = trim_by_lane.get(lane_id, {})
    return trim_polyline(
        raw_points,
        float(lane_trim.get("start") or 0.0),
        float(lane_trim.get("end") or 0.0),
        float(lane_trim.get("locked_start") or 0.0),
        float(lane_trim.get("locked_end") or 0.0),
    )


def geojson_features(lane_graph: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    features: list[dict[str, Any]] = []
    counts: Counter = Counter()
    lane_links = lane_link_records(lane_graph)
    continuity_links = continuity_link_records(lane_graph)
    trim_by_lane = lane_trim_distances(lane_graph, lane_links, continuity_links)

    for lane in lane_graph.get("lanes", []):
        lane_id = str(lane.get("lane_id") or "")
        points = trimmed_lane_points(lane, trim_by_lane)
        if len(points) < 2:
            counts["skipped_short_lane"] += 1
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": round_line(points)},
            "properties": {
                "vc_part": "lane_debug_centerline",
                "lane_id": lane_id,
                "road_id": lane["road_id"],
                "direction": lane["direction"],
                "source": lane.get("source", "unknown"),
                "width_m": float(lane.get("width_m") or 0.0),
                "width_start_m": float(lane.get("width_start_m") or lane.get("width_m") or 0.0),
                "width_end_m": float(lane.get("width_end_m") or lane.get("width_m") or 0.0),
                "road_width_m": float(lane.get("road_width_m") or 0.0),
                "road_width_start_m": float(lane.get("road_width_start_m") or 0.0),
                "road_width_end_m": float(lane.get("road_width_end_m") or 0.0),
                "width_source": lane.get("width_source", "unknown"),
                "width_confidence": float(lane.get("width_confidence") or 0.0),
                "debug_width_m": LANE_RIBBON_WIDTH_M,
                "length_m": round(polyline_length(points), 3),
            },
        })
        ribbon = ribbon_polygon(points, LANE_RIBBON_WIDTH_M)
        if ribbon:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": round_polygon(ribbon)},
                "properties": {
                    "vc_part": "lane_debug_ribbon",
                    "lane_id": lane_id,
                    "road_id": lane["road_id"],
                    "direction": lane["direction"],
                    "actual_width_m": float(lane.get("width_m") or 0.0),
                    "actual_width_start_m": float(lane.get("width_start_m") or lane.get("width_m") or 0.0),
                    "actual_width_end_m": float(lane.get("width_end_m") or lane.get("width_m") or 0.0),
                    "width_source": lane.get("width_source", "unknown"),
                    "width_confidence": float(lane.get("width_confidence") or 0.0),
                    "debug_width_m": LANE_RIBBON_WIDTH_M,
                },
            })
            counts["lane_ribbons"] += 1
        counts["lane_centerlines"] += 1

    for link in lane_links:
        points = as_points(link.get("connecting_curve_xz") or [])
        if len(points) < 2:
            counts["skipped_empty_lane_link_curve"] += 1
            continue
        properties = {
            "vc_part": "lane_link_debug_curve",
            "lane_link_id": link.get("lane_link_id", ""),
            "junction_id": link["junction_id"],
            "connection_id": link["connection_id"],
            "from_lane": link.get("from_lane", ""),
            "to_lane": link.get("to_lane", ""),
            "turn": link.get("turn", link.get("connection_turn", "")),
            "confidence": float(link.get("confidence", 0.0)),
            "width_m": float(link.get("width_m") or 0.0),
            "width_start_m": float(link.get("width_start_m") or link.get("width_m") or 0.0),
            "width_end_m": float(link.get("width_end_m") or link.get("width_m") or 0.0),
            "width_source": link.get("width_source", "unknown"),
            "width_confidence": float(link.get("width_confidence") or 0.0),
            "debug_width_m": LANE_LINK_RIBBON_WIDTH_M,
            "length_m": round(polyline_length(points), 3),
        }
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": round_line(points)},
            "properties": properties,
        })
        ribbon = ribbon_polygon(points, LANE_LINK_RIBBON_WIDTH_M)
        if ribbon:
            ribbon_props = dict(properties)
            ribbon_props["vc_part"] = "lane_link_debug_ribbon"
            features.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": round_polygon(ribbon)},
                "properties": ribbon_props,
            })
            counts["lane_link_ribbons"] += 1
        counts["lane_link_curves"] += 1

    for link in continuity_links:
        if is_micro_seam_continuity(link):
            counts["skipped_micro_seam_continuity_curve"] += 1
            continue
        points = as_points(link.get("connecting_curve_xz") or [])
        if len(points) < 2:
            counts["skipped_empty_continuity_curve"] += 1
            continue
        properties = {
            "vc_part": "lane_continuity_debug_curve",
            "continuity_link_id": link.get("continuity_link_id", ""),
            "corner_id": link.get("corner_id", ""),
            "corner_node_id": link.get("corner_node_id", ""),
            "from_lane": link.get("from_lane", ""),
            "to_lane": link.get("to_lane", ""),
            "from_road": link.get("from_road", ""),
            "to_road": link.get("to_road", ""),
            "turn": link.get("turn", "corner"),
            "source": link.get("source", "unknown"),
            "width_m": float(link.get("width_m") or 0.0),
            "width_start_m": float(link.get("width_start_m") or link.get("width_m") or 0.0),
            "width_end_m": float(link.get("width_end_m") or link.get("width_m") or 0.0),
            "width_source": link.get("width_source", "unknown"),
            "width_confidence": float(link.get("width_confidence") or 0.0),
            "debug_width_m": LANE_LINK_RIBBON_WIDTH_M,
            "length_m": round(polyline_length(points), 3),
        }
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": round_line(points)},
            "properties": properties,
        })
        ribbon = ribbon_polygon(points, LANE_LINK_RIBBON_WIDTH_M)
        if ribbon:
            ribbon_props = dict(properties)
            ribbon_props["vc_part"] = "lane_continuity_debug_ribbon"
            features.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": round_polygon(ribbon)},
                "properties": ribbon_props,
            })
            counts["lane_continuity_ribbons"] += 1
        counts["lane_continuity_curves"] += 1

    return features, dict(counts)


def write_geojson(path: Path, area_id: str, lane_graph: dict[str, Any]) -> dict[str, int]:
    features, counts = geojson_features(lane_graph)
    write_json(path, {
        "type": "FeatureCollection",
        "metadata": {
            "area_id": area_id,
            "schema": "road_test_pipeline.lane_geometry_debug.v1",
            "coord_domain": "local_xz_m",
            "source": "lane_graph.json",
            "lane_ribbon_width_m": LANE_RIBBON_WIDTH_M,
            "lane_link_ribbon_width_m": LANE_LINK_RIBBON_WIDTH_M,
            "debug_note": "Inspection geometry only; not final road surface.",
        },
        "features": features,
    })
    return counts


def add_obj_line(
    vertices: list[tuple[float, float, float]],
    points: list[tuple[float, float]],
    y: float,
) -> list[int]:
    start = len(vertices) + 1
    for x, z in points:
        vertices.append((x, y, -z))
    return list(range(start, start + len(points)))


def add_obj_face(
    vertices: list[tuple[float, float, float]],
    points: list[tuple[float, float]],
    y: float,
) -> list[int]:
    clean_points = points[:-1] if len(points) > 2 and points[0] == points[-1] else points
    start = len(vertices) + 1
    for x, z in clean_points:
        vertices.append((x, y, -z))
    return list(range(start, start + len(clean_points)))


def write_obj(path: Path, lane_graph: dict[str, Any]) -> dict[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    vertices: list[tuple[float, float, float]] = []
    lines_out: list[tuple[str, list[int]]] = []
    faces_out: list[tuple[str, list[int]]] = []
    lane_links = lane_link_records(lane_graph)
    continuity_links = continuity_link_records(lane_graph)
    trim_by_lane = lane_trim_distances(lane_graph, lane_links, continuity_links)

    for lane in lane_graph.get("lanes", []):
        points = trimmed_lane_points(lane, trim_by_lane)
        if len(points) < 2:
            continue
        line = add_obj_line(vertices, points, LANE_LINE_Y)
        lines_out.append(("lane_debug_centerline", line))
        ribbon = ribbon_polygon(points, LANE_RIBBON_WIDTH_M)
        if ribbon:
            face = add_obj_face(vertices, ribbon, RIBBON_Y)
            faces_out.append(("lane_debug_ribbon", face))

    for link in lane_links:
        points = as_points(link.get("connecting_curve_xz") or [])
        if len(points) < 2:
            continue
        line = add_obj_line(vertices, points, LANE_LINK_LINE_Y)
        lines_out.append(("lane_link_debug_curve", line))
        ribbon = ribbon_polygon(points, LANE_LINK_RIBBON_WIDTH_M)
        if ribbon:
            face = add_obj_face(vertices, ribbon, RIBBON_Y + 0.02)
            faces_out.append(("lane_link_debug_ribbon", face))

    for link in continuity_links:
        if is_micro_seam_continuity(link):
            continue
        points = as_points(link.get("connecting_curve_xz") or [])
        if len(points) < 2:
            continue
        line = add_obj_line(vertices, points, LANE_LINK_LINE_Y)
        lines_out.append(("lane_continuity_debug_curve", line))
        ribbon = ribbon_polygon(points, LANE_LINK_RIBBON_WIDTH_M)
        if ribbon:
            face = add_obj_face(vertices, ribbon, RIBBON_Y + 0.02)
            faces_out.append(("lane_continuity_debug_ribbon", face))

    with path.open("w", encoding="utf-8") as f:
        f.write("# road_test_pipeline lane geometry debug OBJ\n")
        for x, y, z in vertices:
            f.write(f"v {x:.4f} {y:.4f} {z:.4f}\n")
        current_group = None
        for group, line in lines_out:
            if group != current_group:
                f.write(f"g {group}\n")
                current_group = group
            f.write("l " + " ".join(str(index) for index in line) + "\n")
        for group, face in faces_out:
            if group != current_group:
                f.write(f"g {group}\n")
                current_group = group
            f.write("f " + " ".join(str(index) for index in face) + "\n")

    return {
        "obj_vertices": len(vertices),
        "obj_lines": len(lines_out),
        "obj_faces": len(faces_out),
    }


def bounds_for(lines: list[list[tuple[float, float]]]) -> tuple[float, float, float, float]:
    points = [point for line in lines for point in line]
    min_x = min(point[0] for point in points)
    max_x = max(point[0] for point in points)
    min_z = min(point[1] for point in points)
    max_z = max(point[1] for point in points)
    pad = 25.0
    return min_x - pad, min_z - pad, max_x + pad, max_z + pad


def svg_point(point: tuple[float, float], bounds: tuple[float, float, float, float], scale: float, margin: float) -> tuple[float, float]:
    min_x, min_z, _max_x, max_z = bounds
    return margin + (point[0] - min_x) * scale, margin + (max_z - point[1]) * scale


def write_svg(path: Path, area_id: str, lane_graph: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lane_links = lane_link_records(lane_graph)
    continuity_links = continuity_link_records(lane_graph)
    trim_by_lane = lane_trim_distances(lane_graph, lane_links, continuity_links)
    lane_lines = [trimmed_lane_points(lane, trim_by_lane) for lane in lane_graph.get("lanes", [])]
    link_items = [(link, as_points(link.get("connecting_curve_xz") or [])) for link in lane_links]
    continuity_items = [
        (link, as_points(link.get("connecting_curve_xz") or []))
        for link in continuity_links
        if not is_micro_seam_continuity(link)
    ]
    all_lines = (
        [line for line in lane_lines if len(line) >= 2]
        + [line for _link, line in link_items if len(line) >= 2]
        + [line for _link, line in continuity_items if len(line) >= 2]
    )
    bounds = bounds_for(all_lines)
    width_m = bounds[2] - bounds[0]
    height_m = bounds[3] - bounds[1]
    margin = 50
    canvas_w = 1200
    canvas_h = max(800, int(canvas_w * height_m / max(width_m, 1.0)))
    scale = min((canvas_w - margin * 2) / width_m, (canvas_h - margin * 2) / height_m)

    def polyline(points: list[tuple[float, float]]) -> str:
        return " ".join(f"{x:.2f},{y:.2f}" for x, y in (svg_point(point, bounds, scale, margin) for point in points))

    turn_colors = {
        "left": "#2563EB",
        "right": "#D97706",
        "through": "#059669",
    }
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w}" height="{canvas_h}" viewBox="0 0 {canvas_w} {canvas_h}">',
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        f'<text x="40" y="34" font-family="Arial, Microsoft YaHei" font-size="22" font-weight="700" fill="#111827">{area_id} lane geometry debug</text>',
        '<text x="40" y="58" font-family="Arial, Microsoft YaHei" font-size="13" fill="#475569">Lane centerlines and laneLink turn curves; debug geometry only</text>',
    ]
    for points in lane_lines:
        if len(points) < 2:
            continue
        lines.append(
            f'<polyline points="{polyline(points)}" fill="none" stroke="#64748B" '
            'stroke-width="0.8" stroke-linecap="round" stroke-linejoin="round" opacity="0.28"/>'
        )
    for link, points in link_items:
        if len(points) < 2:
            continue
        turn = str(link.get("turn") or link.get("connection_turn") or "through")
        color = turn_colors.get(turn, "#7C3AED")
        lines.append(
            f'<polyline points="{polyline(points)}" fill="none" stroke="{color}" '
            'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" opacity="0.88"/>'
        )
    for _link, points in continuity_items:
        if len(points) < 2:
            continue
        lines.append(
            f'<polyline points="{polyline(points)}" fill="none" stroke="#0F766E" '
            'stroke-width="2.0" stroke-linecap="round" stroke-linejoin="round" opacity="0.82"/>'
        )
    lines.append(f'<text x="40" y="{canvas_h - 50}" font-family="Arial, Microsoft YaHei" font-size="13" fill="#334155">lanes: {len(lane_lines)} | laneLinks: {len(link_items)} | continuity: {len(continuity_items)} | colors: left blue, right amber, through green, continuity teal</text>')
    lines.append("</svg>")
    path.write_text("\n".join(lines), encoding="utf-8")


def generate(area_id: str, root: Path) -> dict[str, Any]:
    lane_graph_path = root / "data" / "processed" / f"{area_id}_lane_graph.json"
    preview = root / "data" / "preview"
    reports = root / "reports"
    lane_graph = read_json(lane_graph_path)

    geojson_path = preview / f"{area_id}_lane_geometry_debug.geojson"
    obj_path = preview / f"{area_id}_lane_geometry_debug.obj"
    svg_path = preview / f"{area_id}_lane_geometry_debug.svg"
    report_path = reports / f"{area_id}_lane_geometry_debug_report.json"

    feature_counts = write_geojson(geojson_path, area_id, lane_graph)
    obj_counts = write_obj(obj_path, lane_graph)
    write_svg(svg_path, area_id, lane_graph)

    lane_links = lane_link_records(lane_graph)
    continuity_links = continuity_link_records(lane_graph)
    link_lengths = [
        polyline_length(as_points(link.get("connecting_curve_xz") or []))
        for link in lane_links
        if len(link.get("connecting_curve_xz") or []) >= 2
    ]
    continuity_lengths = [
        polyline_length(as_points(link.get("connecting_curve_xz") or []))
        for link in continuity_links
        if len(link.get("connecting_curve_xz") or []) >= 2
    ]
    lane_widths = [float(lane.get("width_m", 0.0)) for lane in lane_graph.get("lanes", [])]
    lane_width_confidences = [float(lane.get("width_confidence", 0.0)) for lane in lane_graph.get("lanes", [])]
    turn_counts = Counter(str(link.get("turn") or link.get("connection_turn") or "unknown") for link in lane_links)
    report = {
        "area_id": area_id,
        "stage": "lane_geometry_debug_v1",
        "input": str(lane_graph_path),
        "outputs": {
            "geojson": str(geojson_path),
            "obj": str(obj_path),
            "svg": str(svg_path),
        },
        "counts": {
            "lanes": len(lane_graph.get("lanes", [])),
            "lane_links": len(lane_links),
            "continuity_links": len(continuity_links),
            **feature_counts,
            **obj_counts,
        },
        "turn_counts": dict(sorted(turn_counts.items())),
        "metrics": {
            "empty_lane_link_curves": feature_counts.get("skipped_empty_lane_link_curve", 0),
            "empty_continuity_curves": feature_counts.get("skipped_empty_continuity_curve", 0),
            "avg_lane_link_curve_length_m": round(sum(link_lengths) / max(1, len(link_lengths)), 3),
            "max_lane_link_curve_length_m": round(max(link_lengths), 3) if link_lengths else 0.0,
            "avg_continuity_curve_length_m": round(sum(continuity_lengths) / max(1, len(continuity_lengths)), 3),
            "max_continuity_curve_length_m": round(max(continuity_lengths), 3) if continuity_lengths else 0.0,
            "avg_lane_width_m": round(sum(lane_widths) / max(1, len(lane_widths)), 3),
            "min_lane_width_m": round(min(lane_widths), 3) if lane_widths else 0.0,
            "max_lane_width_m": round(max(lane_widths), 3) if lane_widths else 0.0,
            "avg_width_confidence": round(sum(lane_width_confidences) / max(1, len(lane_width_confidences)), 3),
            "lane_ribbon_width_m": LANE_RIBBON_WIDTH_M,
            "lane_link_ribbon_width_m": LANE_LINK_RIBBON_WIDTH_M,
        },
        "notes": [
            "Debug ribbons are intentionally narrow and are not final lane surfaces.",
            "This layer verifies lane direction and laneLink turn paths before junction surface generation.",
            "Continuity links preserve optimized road-level corner fillets when inspecting lane-level geometry.",
        ],
    }
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate lane-level debug geometry from lane_graph.json.")
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
