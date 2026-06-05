#!/usr/bin/env python3
"""Export lane_graph.json and movement corridors to an SVG visualization.

The SVG is a human QA view only. The source of truth remains the structured
JSON artifacts: lane_graph.json and movement_corridor_candidates.json.
"""

from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
from typing import Any


ANCHOR_MARKER_RADIUS_PX = 0.55
ANCHOR_MARKER_STROKE_WIDTH_PX = 0.12
DEFAULT_REVIEW_WIDTH_PX = 3200
DEFAULT_MAX_HEIGHT_PX = 9000


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def points_from_lanes(lane_graph: dict[str, Any]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for centerline in lane_graph.get("physical_lane_centerlines") or []:
        for point in centerline.get("centerline_xz") or []:
            if len(point) >= 2:
                points.append((float(point[0]), float(point[1])))
    for lane in lane_graph.get("lanes", []):
        for point in lane.get("centerline_xz") or []:
            if len(point) >= 2:
                points.append((float(point[0]), float(point[1])))
    for link in lane_graph.get("continuity_links", []):
        for point in link.get("connecting_curve_xz") or []:
            if len(point) >= 2:
                points.append((float(point[0]), float(point[1])))
    return points


def lane_link_records(lane_graph: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = [dict(link) for link in lane_graph.get("lane_links", [])]
    for junction in lane_graph.get("junctions", []):
        for connection in junction.get("connections", []):
            for link in connection.get("lane_links", []):
                item = dict(link)
                item.setdefault("junction_id", junction.get("junction_id", ""))
                item.setdefault("node_id", junction.get("node_id", ""))
                item.setdefault("connection_id", connection.get("connection_id", ""))
                item.setdefault("connection_turn", connection.get("turn", ""))
                records.append(item)
    return records


def points_from_lane_links(links: list[dict[str, Any]]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for link in links:
        for point in link.get("connecting_curve_xz") or []:
            if len(point) >= 2:
                points.append((float(point[0]), float(point[1])))
    return points


def points_from_movement_corridors(movement_corridors: dict[str, Any] | None) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    if not movement_corridors:
        return points
    for case in movement_corridors.get("cases", []):
        for anchor_key in ("lane_entry_anchor", "lane_exit_anchor"):
            anchor = case.get(anchor_key) or {}
            point = anchor.get("point_xz") or []
            if len(point) >= 2:
                points.append((float(point[0]), float(point[1])))
        for candidate in case.get("candidates", []):
            for point in candidate.get("centerline_xz") or []:
                if len(point) >= 2:
                    points.append((float(point[0]), float(point[1])))
    return points


def local_projector_from_metadata(fc: dict[str, Any]) -> tuple[float, float]:
    meta = fc.get("metadata") or {}
    origin_lon = meta.get("origin_lon")
    origin_lat = meta.get("origin_lat")
    if origin_lon is not None and origin_lat is not None:
        return float(origin_lon), float(origin_lat)

    bbox = meta.get("bbox_swen")
    if bbox and len(bbox) == 4:
        south, west, north, east = [float(value) for value in bbox]
        return (west + east) * 0.5, (south + north) * 0.5

    coords: list[list[float]] = []
    for feature in fc.get("features", []):
        geom = feature.get("geometry") or {}
        if geom.get("type") == "LineString":
            coords.extend(geom.get("coordinates") or [])
        elif geom.get("type") == "MultiLineString":
            for line in geom.get("coordinates") or []:
                coords.extend(line)
    if not coords:
        return 0.0, 0.0
    valid_coords = [coord for coord in coords if len(coord) >= 2]
    if not valid_coords:
        return 0.0, 0.0
    lon = sum(float(coord[0]) for coord in valid_coords) / len(valid_coords)
    lat = sum(float(coord[1]) for coord in valid_coords) / len(valid_coords)
    return lon, lat


def to_local(lon: float, lat: float, origin_lon: float, origin_lat: float) -> tuple[float, float]:
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(origin_lat))
    return (lon - origin_lon) * m_per_deg_lon, (lat - origin_lat) * m_per_deg_lat


def raw_road_feature_lines(feature: dict[str, Any]) -> list[list[list[float]]]:
    geom = feature.get("geometry") or {}
    geom_type = str(geom.get("type") or "")
    if geom_type == "LineString":
        return [geom.get("coordinates") or []]
    if geom_type == "MultiLineString":
        return [line for line in geom.get("coordinates") or [] if isinstance(line, list)]
    return []


def raw_road_local_lines(raw_roads: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not raw_roads:
        return []
    origin_lon, origin_lat = local_projector_from_metadata(raw_roads)
    lines: list[dict[str, Any]] = []
    for index, feature in enumerate(raw_roads.get("features", [])):
        props = feature.get("properties") or {}
        source_id = str(props.get("source_feature_id") or props.get("id") or f"raw_{index:04d}")
        for part_index, coords in enumerate(raw_road_feature_lines(feature)):
            points: list[list[float]] = []
            for coord in coords:
                if len(coord) < 2:
                    continue
                x, z = to_local(float(coord[0]), float(coord[1]), origin_lon, origin_lat)
                points.append([x, z])
            if len(points) < 2:
                continue
            lines.append({
                "raw_road_id": f"{source_id}:{part_index}",
                "source_feature_id": source_id,
                "part_index": part_index,
                "highway": str(props.get("highway") or ""),
                "name": str(props.get("name") or ""),
                "lanes": str(props.get("lanes") or ""),
                "oneway": str(props.get("oneway") or ""),
                "points": points,
            })
    return lines


def joined(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if str(item))
    if value is None:
        return ""
    return str(value)


def road_graph_edge_ids_by_canonical(road_graph: dict[str, Any] | None) -> dict[str, str]:
    if not road_graph:
        return {}
    mapping: dict[str, str] = {}
    for edge in road_graph.get("edges", []):
        edge_id = str(edge.get("edge_id") or "")
        canonical_road_id = str(edge.get("canonical_road_id") or edge.get("source_feature_id") or "")
        if edge_id and canonical_road_id:
            mapping[canonical_road_id] = edge_id
    return mapping


def road_layer_local_lines(
    roads: dict[str, Any] | None,
    fallback_prefix: str,
    road_graph_edge_by_canonical: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if not roads:
        return []
    edge_by_canonical = road_graph_edge_by_canonical or {}
    origin_lon, origin_lat = local_projector_from_metadata(roads)
    lines: list[dict[str, Any]] = []
    for index, feature in enumerate(roads.get("features", [])):
        props = feature.get("properties") or {}
        canonical_road_id = str(props.get("canonical_road_id") or "")
        source_id = str(
            canonical_road_id
            or props.get("source_feature_id")
            or props.get("repair_edge_id")
            or props.get("id")
            or f"{fallback_prefix}_{index:04d}"
        )
        road_graph_edge_id = str(props.get("road_graph_edge_id") or edge_by_canonical.get(canonical_road_id, ""))
        for part_index, coords in enumerate(raw_road_feature_lines(feature)):
            points: list[list[float]] = []
            for coord in coords:
                if len(coord) < 2:
                    continue
                x, z = to_local(float(coord[0]), float(coord[1]), origin_lon, origin_lat)
                points.append([x, z])
            if len(points) < 2:
                continue
            lines.append({
                "road_id": f"{source_id}:{part_index}",
                "road_graph_edge_id": road_graph_edge_id,
                "source_feature_id": str(props.get("source_feature_id") or source_id),
                "canonical_road_id": canonical_road_id,
                "part_index": part_index,
                "highway": str(props.get("highway") or ""),
                "road_class": str(props.get("road_class") or props.get("highway") or ""),
                "name": str(props.get("name") or ""),
                "lanes": str(props.get("lanes") or ""),
                "width_m": str(props.get("width_m") or ""),
                "oneway": str(props.get("oneway") or ""),
                "canonical_edge_count": str(props.get("canonical_edge_count") or ""),
                "canonical_length_m": str(props.get("canonical_length_m") or ""),
                "canonical_ops": joined(props.get("canonical_ops")),
                "repair_ops": joined(props.get("repair_ops")),
                "repair_edge_ids": joined(props.get("repair_edge_ids") or props.get("repair_edge_id")),
                "source_feature_ids": joined(props.get("source_feature_ids")),
                "repaired_source_feature_ids": joined(props.get("repaired_source_feature_ids")),
                "points": points,
            })
    return lines


def points_from_raw_roads(raw_roads: dict[str, Any] | None) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for line in raw_road_local_lines(raw_roads):
        for point in line["points"]:
            points.append((float(point[0]), float(point[1])))
    return points


def points_from_road_layer(roads: dict[str, Any] | None, fallback_prefix: str) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for line in road_layer_local_lines(roads, fallback_prefix):
        for point in line["points"]:
            points.append((float(point[0]), float(point[1])))
    return points


def points_from_raw_topology_diagnostics(raw_topology_diagnostics: dict[str, Any] | None) -> list[tuple[float, float]]:
    if not raw_topology_diagnostics:
        return []
    points: list[tuple[float, float]] = []
    for vertex in raw_topology_diagnostics.get("vertices", []):
        x = vertex.get("x")
        z = vertex.get("z")
        if x is not None and z is not None:
            points.append((float(x), float(z)))
    for crossing in raw_topology_diagnostics.get("unsplit_crossings", []):
        x = crossing.get("x")
        z = crossing.get("z")
        if x is not None and z is not None:
            points.append((float(x), float(z)))
    return points


def points_from_corner_candidates(corner_candidates: dict[str, Any] | None) -> list[tuple[float, float]]:
    if not corner_candidates:
        return []
    points: list[tuple[float, float]] = []
    for candidate in corner_candidates.get("candidates", []):
        for point in candidate.get("context_polyline_xz") or []:
            if len(point) >= 2:
                points.append((float(point[0]), float(point[1])))
        center = candidate.get("center_xz") or []
        if len(center) >= 2:
            points.append((float(center[0]), float(center[1])))
    return points


def lane_by_id(lane_graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(lane.get("lane_id") or ""): lane for lane in lane_graph.get("lanes", [])}


def scale_transform(
    points: list[tuple[float, float]],
    *,
    width_px: int,
    max_height_px: int,
    padding_px: int,
) -> tuple[int, int, Any]:
    if not points:
        return width_px, width_px, lambda x, z: (padding_px, padding_px)
    min_x = min(point[0] for point in points)
    max_x = max(point[0] for point in points)
    min_z = min(point[1] for point in points)
    max_z = max(point[1] for point in points)
    span_x = max(1.0, max_x - min_x)
    span_z = max(1.0, max_z - min_z)
    drawable_w = max(100, width_px - padding_px * 2)
    scale = drawable_w / span_x
    height_px = int(span_z * scale + padding_px * 2)
    height_px = max(720, min(max_height_px, height_px))
    drawable_h = max(100, height_px - padding_px * 2)
    scale = min(drawable_w / span_x, drawable_h / span_z)

    def transform(x: float, z: float) -> tuple[float, float]:
        sx = padding_px + (x - min_x) * scale
        sy = padding_px + (max_z - z) * scale
        return round(sx, 2), round(sy, 2)

    return width_px, height_px, transform


def polyline(points: list[list[float]], transform: Any) -> str:
    return " ".join(
        f"{transform(float(point[0]), float(point[1]))[0]},{transform(float(point[0]), float(point[1]))[1]}"
        for point in points
        if len(point) >= 2
    )


def polygon_points(points: list[tuple[float, float]], transform: Any) -> str:
    return " ".join(
        f"{transform(float(point[0]), float(point[1]))[0]},{transform(float(point[0]), float(point[1]))[1]}"
        for point in points
        if len(point) >= 2
    )


def normalize(vector: tuple[float, float]) -> tuple[float, float]:
    length = math.sqrt(vector[0] * vector[0] + vector[1] * vector[1])
    if length <= 1e-9:
        return 0.0, 0.0
    return vector[0] / length, vector[1] / length


def rotate90(vector: tuple[float, float]) -> tuple[float, float]:
    return -vector[1], vector[0]


def as_xz_points(points: list[list[float]]) -> list[tuple[float, float]]:
    return [(float(point[0]), float(point[1])) for point in points if len(point) >= 2]


def ribbon_polygon(points: list[tuple[float, float]], width_m: float) -> list[tuple[float, float]]:
    if len(points) < 2:
        return []
    left: list[tuple[float, float]] = []
    right: list[tuple[float, float]] = []
    half_width = max(0.1, width_m) * 0.5
    for index, point in enumerate(points):
        if index == 0:
            tangent = normalize((points[1][0] - point[0], points[1][1] - point[1]))
        elif index == len(points) - 1:
            tangent = normalize((point[0] - points[index - 1][0], point[1] - points[index - 1][1]))
        else:
            previous_tangent = normalize((point[0] - points[index - 1][0], point[1] - points[index - 1][1]))
            next_tangent = normalize((points[index + 1][0] - point[0], points[index + 1][1] - point[1]))
            tangent = normalize((previous_tangent[0] + next_tangent[0], previous_tangent[1] + next_tangent[1]))
            if tangent == (0.0, 0.0):
                tangent = next_tangent
        normal = rotate90(tangent)
        left.append((point[0] + normal[0] * half_width, point[1] + normal[1] * half_width))
        right.append((point[0] - normal[0] * half_width, point[1] - normal[1] * half_width))
    polygon = left + list(reversed(right))
    if polygon and polygon[0] != polygon[-1]:
        polygon.append(polygon[0])
    return polygon


def svg_title(value: str) -> str:
    return f"<title>{html.escape(value)}</title>"


def svg_attrs(values: dict[str, Any]) -> str:
    attrs: list[str] = []
    for key, value in values.items():
        if value is None or value == "":
            continue
        attr_key = key.replace("_", "-")
        attr_value = html.escape(str(value), quote=True)
        attrs.append(f'data-vc-{attr_key}="{attr_value}"')
    return " ".join(attrs)


def endpoint(lane: dict[str, Any], side: str) -> tuple[float, float] | None:
    points = lane.get("centerline_xz") or []
    if not points:
        return None
    point = points[-1] if side == "end" else points[0]
    if len(point) < 2:
        return None
    return float(point[0]), float(point[1])


def movement_corridor_scoring_index(scoring: dict[str, Any] | None) -> dict[str, dict[str, Any]] | None:
    if not scoring:
        return None
    index: dict[str, dict[str, Any]] = {}
    for case in scoring.get("cases", []):
        case_id = str(case.get("case_id") or case.get("corridor_id") or case.get("compound_case_id") or "")
        if case_id:
            index[case_id] = case
    return index


def movement_case_id(case: dict[str, Any]) -> str:
    return str(case.get("corridor_id") or case.get("compound_case_id") or case.get("case_id") or "")


def candidate_for_visual(
    case: dict[str, Any],
    scoring_case: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    candidates = [candidate for candidate in case.get("candidates", []) if isinstance(candidate, dict)]
    if not candidates:
        return None
    if scoring_case:
        best_family = str(scoring_case.get("best_scored_family") or "")
        for candidate in candidates:
            if str(candidate.get("family") or "") == best_family:
                return candidate
    movement_kind = str(case.get("movement_kind") or "")
    if movement_kind == "through":
        preferred = ("topology_straight_baseline", "compound_topology_straight_baseline")
    else:
        preferred = ("bezier_g1_preview", "compound_bezier_g1_preview")
    for family in preferred:
        for candidate in candidates:
            if str(candidate.get("family") or "") == family:
                return candidate
    return candidates[0]


def movement_case_lines(
    *,
    movement_corridors: dict[str, Any],
    movement_scoring_by_case: dict[str, dict[str, Any]] | None,
    transform: Any,
    max_cases: int,
) -> tuple[list[str], list[str], dict[str, Any]]:
    corridor_lines: list[str] = []
    anchor_marks: list[str] = []
    rendered = 0
    source_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}
    issue_counts: dict[str, int] = {}
    skip_counts: dict[str, int] = {}
    scoring_status_counts: dict[str, int] = {}

    for case in movement_corridors.get("cases", []):
        if rendered >= max_cases:
            break
        scoring_case = movement_scoring_by_case.get(movement_case_id(case)) if movement_scoring_by_case else None
        if scoring_case:
            status = str(scoring_case.get("best_status") or "unknown")
            scoring_status_counts[status] = scoring_status_counts.get(status, 0) + 1
        candidate = candidate_for_visual(case, scoring_case)
        if candidate is None:
            continue
        points = candidate.get("centerline_xz") or []
        if len(points) < 2:
            continue

        family = str(candidate.get("family") or "unknown")
        family_counts[family] = family_counts.get(family, 0) + 1
        for issue in candidate.get("issues") or []:
            issue = str(issue)
            issue_counts[issue] = issue_counts.get(issue, 0) + 1

        confidence = float(case.get("confidence") or 0.0)
        movement_kind = str(case.get("movement_kind") or "unknown")
        color = {
            "through": "#0ea5e9",
            "left": "#f97316",
            "right": "#a855f7",
        }.get(movement_kind, "#f59e0b")
        opacity = 0.18 + min(0.34, confidence * 0.38)
        width = 0.72 if confidence < 0.5 else 0.95
        tooltip = (
            f"corridor_id={case.get('corridor_id', '')}; "
            f"movement={movement_kind}; family={family}; confidence={confidence:.3f}"
        )
        attrs = svg_attrs({
            "kind": "movement_corridor",
            "source": "movement_corridor_candidates.json",
            "id": case.get("corridor_id", ""),
            "corridor_id": case.get("corridor_id", ""),
            "from_lane_id": case.get("from_lane_id", ""),
            "to_lane_id": case.get("to_lane_id", ""),
            "movement": movement_kind,
            "family": family,
            "confidence": f"{confidence:.3f}",
            "issues": ", ".join(str(issue) for issue in candidate.get("issues") or []),
        })
        corridor_lines.append(
            f'<polyline {attrs} points="{polyline(points, transform)}" fill="none" '
            f'stroke="{color}" stroke-width="{width}" stroke-opacity="{opacity:.2f}" '
            f'stroke-linecap="round" stroke-linejoin="round">{svg_title(tooltip)}</polyline>'
        )

        for anchor_key, fill in (("lane_entry_anchor", "#22c55e"), ("lane_exit_anchor", "#ef4444")):
            anchor = case.get(anchor_key) or {}
            point = anchor.get("point_xz") or []
            if len(point) < 2:
                continue
            source = str(anchor.get("source") or "unknown")
            source_counts[source] = source_counts.get(source, 0) + 1
            sx, sy = transform(float(point[0]), float(point[1]))
            tooltip = (
                f"{anchor_key}; lane={anchor.get('lane_id', '')}; edge={anchor.get('edge_id', '')}; "
                f"source={source}; trim={anchor.get('entry_trim_m', '')}"
            )
            attrs = svg_attrs({
                "kind": "movement_anchor",
                "source": "movement_corridor_candidates.json",
                "id": f"{case.get('corridor_id', '')}:{anchor_key}",
                "corridor_id": case.get("corridor_id", ""),
                "anchor_key": anchor_key,
                "lane_id": anchor.get("lane_id", ""),
                "edge_id": anchor.get("edge_id", ""),
                "anchor_source": source,
                "trim_m": anchor.get("entry_trim_m", ""),
            })
            anchor_marks.append(
                f'<circle {attrs} cx="{sx}" cy="{sy}" r="{ANCHOR_MARKER_RADIUS_PX}" fill="{fill}" fill-opacity="0.76" '
                f'stroke="#0f172a" stroke-width="{ANCHOR_MARKER_STROKE_WIDTH_PX}">{svg_title(tooltip)}</circle>'
            )
        rendered += 1

    metrics = {
        "movement_corridors_rendered": rendered,
        "anchor_markers_rendered": len(anchor_marks),
        "anchor_source_counts": dict(sorted(source_counts.items())),
        "visual_candidate_family_counts": dict(sorted(family_counts.items())),
        "visual_candidate_issue_counts": dict(sorted(issue_counts.items())),
        "movement_corridors_skipped": sum(skip_counts.values()),
        "movement_corridor_skip_reason_counts": dict(sorted(skip_counts.items())),
        "movement_corridor_scoring_status_counts": dict(sorted(scoring_status_counts.items())),
    }
    return corridor_lines, anchor_marks, metrics


def lane_link_preview_lines(
    *,
    links: list[dict[str, Any]],
    lanes_by_id: dict[str, dict[str, Any]],
    transform: Any,
    max_links: int,
) -> tuple[list[str], int]:
    link_lines: list[str] = []
    rendered_links = 0
    for link in links:
        if rendered_links >= max_links:
            break
        from_lane_id = str(link.get("from_lane") or link.get("from_lane_id") or "")
        to_lane_id = str(link.get("to_lane") or link.get("to_lane_id") or "")
        points = link.get("connecting_curve_xz") or []
        if len(points) < 2:
            if str(link.get("link_kind") or "") != "junction_movement":
                continue
            from_lane = lanes_by_id.get(from_lane_id)
            to_lane = lanes_by_id.get(to_lane_id)
            if not from_lane or not to_lane:
                continue
            start = endpoint(from_lane, "end")
            end = endpoint(to_lane, "start")
            if start is None or end is None:
                continue
            points = [[start[0], start[1]], [end[0], end[1]]]
        confidence = float(link.get("confidence") or 0.0)
        opacity = 0.34 + min(0.42, confidence * 0.38)
        turn = str(link.get("turn") or link.get("connection_turn") or "unknown")
        color = {
            "through": "#0ea5e9",
            "left": "#f97316",
            "right": "#a855f7",
        }.get(turn, "#f59e0b")
        link_id = str(link.get("lane_link_id") or link.get("link_id") or "")
        tooltip = (
            f"lane_link={link_id}; from={from_lane_id}; to={to_lane_id}; "
            f"turn={turn}; source={link.get('source', '')}; curve={link.get('curve_source', '')}"
        )
        attrs = svg_attrs({
            "kind": "lane_link_preview",
            "source": "lane_graph.junction_lane_links",
            "id": link_id,
            "lane_link_id": link_id,
            "junction_id": link.get("junction_id", ""),
            "connection_id": link.get("connection_id", ""),
            "from_lane_id": from_lane_id,
            "to_lane_id": to_lane_id,
            "turn": turn,
            "curve_source": link.get("curve_source", ""),
            "confidence": f"{confidence:.3f}",
        })
        link_lines.append(
            f'<polyline {attrs} points="{polyline(points, transform)}" fill="none" '
            f'stroke="{color}" stroke-width="1.15" stroke-opacity="{opacity:.2f}" '
            f'stroke-linecap="round" stroke-linejoin="round">{svg_title(tooltip)}</polyline>'
        )
        rendered_links += 1
    return link_lines, rendered_links


def continuity_link_lines(
    *,
    links: list[dict[str, Any]],
    transform: Any,
) -> tuple[list[str], dict[str, Any]]:
    lines: list[str] = []
    source_counts: dict[str, int] = {}
    rendered = 0
    skipped_micro_seams = 0
    for link in links:
        if bool(link.get("micro_seam_absorbed")):
            skipped_micro_seams += 1
            continue
        points = link.get("connecting_curve_xz") or []
        if len(points) < 2:
            continue
        source = str(link.get("source") or "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
        color = "#059669" if source == "degree2_connector_through_continuity_v1" else "#0ea5e9"
        dasharray = "2 2" if source == "degree2_connector_through_continuity_v1" else ""
        tooltip = (
            f"continuity={link.get('continuity_link_id', '')}; "
            f"from={link.get('from_lane', '')}; to={link.get('to_lane', '')}; "
            f"source={source}; style={link.get('rounding_style_id', '')}; "
            f"gap={link.get('endpoint_gap_m', '')}; turn={link.get('turn_angle_deg', '')}"
        )
        attrs = svg_attrs({
            "kind": "continuity_link",
            "source": "lane_graph.json",
            "id": link.get("continuity_link_id", ""),
            "continuity_link_id": link.get("continuity_link_id", ""),
            "from_lane_id": link.get("from_lane", ""),
            "to_lane_id": link.get("to_lane", ""),
            "from_road": link.get("from_road", ""),
            "to_road": link.get("to_road", ""),
            "corner_node_id": link.get("corner_node_id", ""),
            "link_source": source,
            "turn": link.get("turn", ""),
            "turn_angle_deg": link.get("turn_angle_deg", ""),
            "endpoint_gap_m": link.get("endpoint_gap_m", ""),
            "rounding_style_id": link.get("rounding_style_id", ""),
            "rounding_curve_family": link.get("rounding_curve_family", ""),
            "rounding_application": link.get("rounding_application", ""),
            "lane_level_radius_regularized": link.get("lane_level_radius_regularized", ""),
            "lane_level_curve_min_radius_m": link.get("lane_level_curve_min_radius_m", ""),
            "lane_level_observed_min_radius_m": link.get("lane_level_observed_min_radius_m", ""),
            "lane_level_from_extra_trim_m": link.get("lane_level_from_extra_trim_m", ""),
            "lane_level_to_extra_trim_m": link.get("lane_level_to_extra_trim_m", ""),
            "lane_level_radius_regularization_skip_reason": link.get("lane_level_radius_regularization_skip_reason", ""),
            "micro_seam_absorbed": link.get("micro_seam_absorbed", ""),
            "micro_seam_policy": link.get("micro_seam_policy", ""),
            "original_endpoint_gap_m": link.get("original_endpoint_gap_m", ""),
            "same_physical_lane_continuity": link.get("same_physical_lane_continuity", ""),
            "physical_lane_group_id": link.get("physical_lane_group_id", ""),
            "physical_lane_group_policy": link.get("physical_lane_group_policy", ""),
            "physical_lane_group_member_count": link.get("physical_lane_group_member_count", ""),
        })
        dash = f' stroke-dasharray="{dasharray}"' if dasharray else ""
        lines.append(
            f'<polyline {attrs} points="{polyline(points, transform)}" fill="none" '
            f'stroke="{color}" stroke-width="2.2" stroke-opacity="0.78"{dash} '
            f'stroke-linecap="round" stroke-linejoin="round">{svg_title(tooltip)}</polyline>'
        )
        rendered += 1
    return lines, {
        "continuity_links_rendered": rendered,
        "continuity_micro_seams_skipped": skipped_micro_seams,
        "continuity_link_source_counts": dict(sorted(source_counts.items())),
    }


def raw_road_lines(
    *,
    raw_roads: dict[str, Any],
    transform: Any,
    max_raw_roads: int,
) -> tuple[list[str], list[str], dict[str, Any]]:
    lines: list[str] = []
    point_marks: list[str] = []
    class_counts: dict[str, int] = {}
    endpoint_count = 0
    internal_vertex_count = 0
    rendered = 0
    for raw_line in raw_road_local_lines(raw_roads):
        if rendered >= max_raw_roads:
            break
        points = raw_line["points"]
        if len(points) < 2:
            continue
        highway = str(raw_line.get("highway") or "unknown")
        class_counts[highway] = class_counts.get(highway, 0) + 1
        name = str(raw_line.get("name") or "")
        tooltip = (
            f"raw_road={raw_line.get('source_feature_id', '')}; highway={highway}; "
            f"name={name}; lanes={raw_line.get('lanes', '')}; oneway={raw_line.get('oneway', '')}"
        )
        attrs = svg_attrs({
            "kind": "raw_road",
            "layer": "raw_roads",
            "source": "roads_raw.geojson",
            "id": raw_line.get("raw_road_id", ""),
            "source_feature_id": raw_line.get("source_feature_id", ""),
            "part_index": raw_line.get("part_index", ""),
            "highway": highway,
            "road_name": name,
            "lanes": raw_line.get("lanes", ""),
            "oneway": raw_line.get("oneway", ""),
        })
        lines.append(
            f'<polyline {attrs} points="{polyline(points, transform)}" fill="none" '
            f'stroke="#000000" stroke-width="0.55" stroke-opacity="1" '
            f'stroke-linecap="butt" stroke-linejoin="miter">{svg_title(tooltip)}</polyline>'
        )

        for vertex_index, point in enumerate(points):
            if vertex_index == 0:
                vertex_role = "start"
                kind = "raw_road_endpoint"
                radius = 1.45
                endpoint_count += 1
            elif vertex_index == len(points) - 1:
                vertex_role = "end"
                kind = "raw_road_endpoint"
                radius = 1.45
                endpoint_count += 1
            else:
                vertex_role = "internal"
                kind = "raw_road_vertex"
                radius = 0.95
                internal_vertex_count += 1
            sx, sy = transform(float(point[0]), float(point[1]))
            point_tooltip = (
                f"raw_vertex={vertex_role}; index={vertex_index}; raw_road={raw_line.get('source_feature_id', '')}; "
                f"highway={highway}; name={name}; lanes={raw_line.get('lanes', '')}; "
                f"oneway={raw_line.get('oneway', '')}"
            )
            point_attrs = svg_attrs({
                "kind": kind,
                "layer": "raw_roads",
                "source": "roads_raw.geojson",
                "id": f"{raw_line.get('raw_road_id', '')}:v{vertex_index:03d}",
                "source_feature_id": raw_line.get("source_feature_id", ""),
                "part_index": raw_line.get("part_index", ""),
                "endpoint_role": vertex_role if vertex_role in {"start", "end"} else "",
                "vertex_role": vertex_role,
                "vertex_index": vertex_index,
                "highway": highway,
                "road_name": name,
                "lanes": raw_line.get("lanes", ""),
                "oneway": raw_line.get("oneway", ""),
                "point_xz": f"{float(point[0]):.3f}, {float(point[1]):.3f}",
            })
            point_marks.append(
                f'<circle {point_attrs} cx="{sx}" cy="{sy}" r="{radius}" fill="#000000" fill-opacity="1" '
                f'stroke="#ffffff" stroke-width="0.28">{svg_title(point_tooltip)}</circle>'
            )
        rendered += 1
    return lines, point_marks, {
        "raw_roads_rendered": rendered,
        "raw_road_endpoint_markers_rendered": endpoint_count,
        "raw_road_internal_vertex_markers_rendered": internal_vertex_count,
        "raw_road_vertex_markers_rendered": len(point_marks),
        "raw_road_class_counts": dict(sorted(class_counts.items())),
    }


def road_overlay_lines(
    *,
    roads: dict[str, Any],
    transform: Any,
    layer: str,
    kind: str,
    source_label: str,
    fallback_prefix: str,
    stroke: str,
    stroke_width: float,
    stroke_opacity: float,
    dasharray: str = "",
    max_roads: int,
    road_graph_edge_by_canonical: dict[str, str] | None = None,
) -> tuple[list[str], dict[str, Any]]:
    lines: list[str] = []
    class_counts: dict[str, int] = {}
    rendered = 0
    total_source_edges = 0
    mapped_road_graph_edges = 0
    for road_line in road_layer_local_lines(roads, fallback_prefix, road_graph_edge_by_canonical):
        if rendered >= max_roads:
            break
        points = road_line["points"]
        if len(points) < 2:
            continue
        highway = str(road_line.get("highway") or "unknown")
        class_counts[highway] = class_counts.get(highway, 0) + 1
        try:
            total_source_edges += int(road_line.get("canonical_edge_count") or 0)
        except ValueError:
            pass
        name = str(road_line.get("name") or "")
        road_graph_edge_id = str(road_line.get("road_graph_edge_id") or "")
        if road_graph_edge_id:
            mapped_road_graph_edges += 1
        tooltip = (
            f"{kind}={road_line.get('road_id', '')}; highway={highway}; name={name}; "
            f"canonical={road_line.get('canonical_road_id', '')}; source={road_line.get('source_feature_id', '')}; "
            f"road_graph_edge={road_graph_edge_id}; edges={road_line.get('canonical_edge_count', '')}"
        )
        attrs = svg_attrs({
            "kind": kind,
            "layer": layer,
            "source": source_label,
            "id": road_line.get("road_id", ""),
            "road_graph_edge_id": road_graph_edge_id,
            "source_feature_id": road_line.get("source_feature_id", ""),
            "canonical_road_id": road_line.get("canonical_road_id", ""),
            "part_index": road_line.get("part_index", ""),
            "highway": highway,
            "road_class": road_line.get("road_class", ""),
            "road_name": name,
            "lanes": road_line.get("lanes", ""),
            "width_m": road_line.get("width_m", ""),
            "oneway": road_line.get("oneway", ""),
            "canonical_edge_count": road_line.get("canonical_edge_count", ""),
            "canonical_length_m": road_line.get("canonical_length_m", ""),
            "canonical_ops": road_line.get("canonical_ops", ""),
            "repair_ops": road_line.get("repair_ops", ""),
            "repair_edge_ids": road_line.get("repair_edge_ids", ""),
            "source_feature_ids": road_line.get("source_feature_ids", ""),
            "repaired_source_feature_ids": road_line.get("repaired_source_feature_ids", ""),
        })
        dash = f' stroke-dasharray="{html.escape(dasharray, quote=True)}"' if dasharray else ""
        lines.append(
            f'<polyline {attrs} points="{polyline(points, transform)}" fill="none" '
            f'stroke="{stroke}" stroke-width="{stroke_width}" stroke-opacity="{stroke_opacity:.2f}"{dash} '
            f'stroke-linecap="round" stroke-linejoin="round">{svg_title(tooltip)}</polyline>'
        )
        rendered += 1
    return lines, {
        f"{layer}_rendered": rendered,
        f"{layer}_class_counts": dict(sorted(class_counts.items())),
        f"{layer}_source_edge_count_sum": total_source_edges,
        f"{layer}_road_graph_edge_mapped": mapped_road_graph_edges,
    }


def raw_topology_issue_markers(
    *,
    raw_topology_diagnostics: dict[str, Any],
    transform: Any,
    max_issues: int,
) -> tuple[list[str], dict[str, Any]]:
    markers: list[str] = []
    classification_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}

    for vertex in raw_topology_diagnostics.get("vertices", []):
        if len(markers) >= max_issues:
            break
        severity = str(vertex.get("severity") or "info")
        if severity == "info":
            continue
        classification = str(vertex.get("classification") or "unknown")
        classification_counts[classification] = classification_counts.get(classification, 0) + 1
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        color = {
            "dangling_endpoint": "#ef4444",
            "internal_vertex_near_other_edge": "#2563eb",
            "internal_vertex_on_other_edge": "#7c3aed",
            "bbox_boundary_endpoint": "#64748b",
        }.get(classification, "#f97316")
        sx, sy = transform(float(vertex.get("x") or 0.0), float(vertex.get("z") or 0.0))
        issues = vertex.get("issues") or []
        issue_types = ", ".join(str(issue.get("issue_type") or "") for issue in issues if isinstance(issue, dict))
        tooltip = (
            f"raw_topology_issue={classification}; severity={severity}; "
            f"raw_road={vertex.get('source_feature_id', '')}; point_index={vertex.get('point_index', '')}; "
            f"issues={issue_types}"
        )
        attrs = svg_attrs({
            "kind": "raw_topology_issue",
            "layer": "raw_roads",
            "source": "raw_topology_diagnostics.json",
            "id": vertex.get("diagnostic_id", ""),
            "diagnostic_id": vertex.get("diagnostic_id", ""),
            "source_feature_id": vertex.get("source_feature_id", ""),
            "point_index": vertex.get("point_index", ""),
            "vertex_role": vertex.get("vertex_role", ""),
            "classification": classification,
            "severity": severity,
            "issue_type": issue_types,
            "highway": vertex.get("highway", ""),
            "road_name": vertex.get("name", ""),
            "point_xz": f"{float(vertex.get('x') or 0.0):.3f}, {float(vertex.get('z') or 0.0):.3f}",
        })
        markers.append(
            f'<circle {attrs} cx="{sx}" cy="{sy}" r="3.4" fill="{color}" fill-opacity="0.86" '
            f'stroke="#ffffff" stroke-width="0.65">{svg_title(tooltip)}</circle>'
        )

    for crossing in raw_topology_diagnostics.get("unsplit_crossings", []):
        if len(markers) >= max_issues:
            break
        severity = str(crossing.get("severity") or "review")
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        classification_counts["unsplit_crossing"] = classification_counts.get("unsplit_crossing", 0) + 1
        sx, sy = transform(float(crossing.get("x") or 0.0), float(crossing.get("z") or 0.0))
        attrs = svg_attrs({
            "kind": "raw_topology_issue",
            "layer": "raw_roads",
            "source": "raw_topology_diagnostics.json",
            "id": crossing.get("issue_id", ""),
            "diagnostic_id": crossing.get("issue_id", ""),
            "classification": "unsplit_crossing",
            "severity": severity,
            "issue_type": "unsplit_crossing",
            "point_xz": f"{float(crossing.get('x') or 0.0):.3f}, {float(crossing.get('z') or 0.0):.3f}",
        })
        tooltip = f"raw_topology_issue=unsplit_crossing; severity={severity}"
        markers.append(
            f'<circle {attrs} cx="{sx}" cy="{sy}" r="3.8" fill="#7c3aed" fill-opacity="0.90" '
            f'stroke="#ffffff" stroke-width="0.7">{svg_title(tooltip)}</circle>'
        )

    return markers, {
        "raw_topology_issue_markers_rendered": len(markers),
        "raw_topology_issue_classification_counts": dict(sorted(classification_counts.items())),
        "raw_topology_issue_severity_counts": dict(sorted(severity_counts.items())),
    }


def corner_candidate_marks(
    *,
    corner_candidates: dict[str, Any],
    transform: Any,
) -> tuple[list[str], dict[str, Any]]:
    marks: list[str] = []
    type_counts: dict[str, int] = {}
    risk_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}

    for candidate in corner_candidates.get("candidates", []):
        candidate_id = str(candidate.get("candidate_id") or "")
        center = candidate.get("center_xz") or []
        context = candidate.get("context_polyline_xz") or []
        if not candidate_id or len(center) < 2:
            continue
        candidate_type = str(candidate.get("candidate_type") or "unknown")
        risk = str(candidate.get("risk_level") or "unknown")
        status = str(candidate.get("status") or "unknown")
        type_counts[candidate_type] = type_counts.get(candidate_type, 0) + 1
        risk_counts[risk] = risk_counts.get(risk, 0) + 1
        status_counts[status] = status_counts.get(status, 0) + 1
        color = "#0ea5e9" if status == "accepted_active" else {
            "low": "#22c55e",
            "medium": "#f59e0b",
            "high": "#ef4444",
        }.get(risk, "#64748b")
        sx, sy = transform(float(center[0]), float(center[1]))
        tooltip = (
            f"corner_candidate={candidate_id}; type={candidate_type}; risk={risk}; "
            f"turn={candidate.get('turn_angle_deg', '')}; radius={candidate.get('suggested_radius_m', '')}"
        )
        attrs = svg_attrs({
            "kind": "corner_candidate",
            "layer": "corner_optimization",
            "source": "corner_optimization_candidates.json",
            "id": candidate_id,
            "corner_id": candidate_id,
            "candidate_type": candidate_type,
            "risk_level": risk,
            "status": candidate.get("status", ""),
            "recommended_action": candidate.get("recommended_action", ""),
            "corner_optimization_id": candidate.get("corner_optimization_id", ""),
            "corner_optimization_application_id": candidate.get("corner_optimization_application_id", ""),
            "corner_optimization_policy": candidate.get("corner_optimization_policy", ""),
            "node_id": candidate.get("node_id", ""),
            "source_edge_id": candidate.get("source_edge_id", ""),
            "from_edge_id": candidate.get("from_edge_id", ""),
            "to_edge_id": candidate.get("to_edge_id", ""),
            "canonical_road_id": candidate.get("canonical_road_id", ""),
            "from_canonical_road_id": candidate.get("from_canonical_road_id", ""),
            "to_canonical_road_id": candidate.get("to_canonical_road_id", ""),
            "road_class": candidate.get("road_class", ""),
            "point_index": candidate.get("point_index", ""),
            "turn_angle_deg": candidate.get("turn_angle_deg", ""),
            "interior_angle_deg": candidate.get("interior_angle_deg", ""),
            "suggested_cut_m": candidate.get("suggested_cut_m", ""),
            "suggested_radius_m": candidate.get("suggested_radius_m", ""),
            "nearest_junction_distance_m": candidate.get("nearest_junction_distance_m", ""),
            "point_xz": f"{float(center[0]):.3f}, {float(center[1]):.3f}",
            "issues": candidate.get("rationale", ""),
        })
        if len(context) >= 2:
            marks.append(
                f'<polyline {attrs} points="{polyline(context, transform)}" fill="none" '
                f'stroke="{color}" stroke-width="1.45" stroke-opacity="0.72" stroke-dasharray="5 3" '
                f'stroke-linecap="round" stroke-linejoin="round">{svg_title(tooltip)}</polyline>'
            )
        marks.append(
            f'<circle {attrs} cx="{sx}" cy="{sy}" r="4.2" fill="{color}" fill-opacity="0.92" '
            f'stroke="#111827" stroke-width="0.75">{svg_title(tooltip)}</circle>'
        )

    return marks, {
        "corner_candidates_rendered": len([mark for mark in marks if mark.startswith("<circle")]),
        "corner_candidate_type_counts": dict(sorted(type_counts.items())),
        "corner_candidate_risk_counts": dict(sorted(risk_counts.items())),
        "corner_candidate_status_counts": dict(sorted(status_counts.items())),
    }


def centerline_buffer_preview_polygons(
    *,
    lanes: list[dict[str, Any]],
    physical_lane_centerlines: list[dict[str, Any]],
    continuity_links: list[dict[str, Any]],
    movement_corridors: dict[str, Any] | None,
    movement_scoring_by_case: dict[str, dict[str, Any]] | None,
    lane_links: list[dict[str, Any]],
    lanes_by_id: dict[str, dict[str, Any]],
    transform: Any,
    max_links: int,
) -> tuple[list[str], dict[str, Any]]:
    polygons: list[str] = []
    source_counts: dict[str, int] = {}
    skip_counts: dict[str, int] = {}

    def append_polygon(
        *,
        source: str,
        record_id: str,
        points: list[tuple[float, float]],
        width_m: float,
        lane_id: str = "",
        from_lane_id: str = "",
        to_lane_id: str = "",
        movement: str = "",
        physical_lane_group_id: str = "",
        physical_lane_group_lanes: str = "",
    ) -> None:
        polygon = ribbon_polygon(points, width_m)
        if len(polygon) < 4:
            return
        source_counts[source] = source_counts.get(source, 0) + 1
        attrs = svg_attrs({
            "kind": "centerline_buffer_preview",
            "layer": "centerline_buffer_preview",
            "source": source,
            "id": record_id,
            "buffer_source": source,
            "lane_id": lane_id,
            "from_lane_id": from_lane_id,
            "to_lane_id": to_lane_id,
            "movement": movement,
            "width_m": round(width_m, 3),
            "physical_lane_group_id": physical_lane_group_id,
            "physical_lane_group_lanes": physical_lane_group_lanes,
        })
        tooltip = (
            f"centerline_buffer_preview={record_id}; source={source}; width_m={width_m:.3f}; "
            "policy=centerline_buffer_preview_v1"
        )
        polygons.append(
            f'<polygon {attrs} points="{polygon_points(polygon, transform)}" '
            'fill="#b7bcc4" fill-opacity="1" stroke="#8f96a1" stroke-width="0.45" '
            f'stroke-opacity="0.62" pointer-events="none">{svg_title(tooltip)}</polygon>'
        )

    grouped_lane_ids: set[str] = set()
    for centerline in physical_lane_centerlines:
        centerline_id = str(centerline.get("centerline_id") or "")
        lane_ids = [str(lane_id) for lane_id in centerline.get("source_lane_ids") or []]
        points = as_xz_points(centerline.get("centerline_xz") or [])
        append_polygon(
            source=str(centerline.get("source") or "physical_lane_centerline"),
            record_id=centerline_id,
            points=points,
            width_m=float(centerline.get("width_m") or 3.2),
            lane_id=", ".join(lane_ids),
            physical_lane_group_id=str(centerline.get("physical_lane_group_id") or ""),
            physical_lane_group_lanes=", ".join(lane_ids),
        )
        grouped_lane_ids.update(lane_ids)

    for lane in lanes:
        lane_id = str(lane.get("lane_id") or "")
        if lane_id in grouped_lane_ids:
            continue
        points = as_xz_points(lane.get("centerline_xz") or [])
        width_m = float(lane.get("width_m") or 3.2)
        append_polygon(
            source="lane_centerline",
            record_id=lane_id,
            points=points,
            width_m=width_m,
            lane_id=lane_id,
        )

    for link in continuity_links:
        if bool(link.get("micro_seam_absorbed")):
            continue
        link_id = str(link.get("continuity_link_id") or "")
        points = as_xz_points(link.get("connecting_curve_xz") or [])
        append_polygon(
            source="continuity_curve",
            record_id=link_id,
            points=points,
            width_m=float(link.get("width_m") or 3.2),
            from_lane_id=str(link.get("from_lane") or ""),
            to_lane_id=str(link.get("to_lane") or ""),
            movement=str(link.get("turn") or ""),
        )

    rendered_links = 0
    if lane_links:
        for link in lane_links:
            if rendered_links >= max_links:
                break
            from_lane_id = str(link.get("from_lane") or link.get("from_lane_id") or "")
            to_lane_id = str(link.get("to_lane") or link.get("to_lane_id") or "")
            points = as_xz_points(link.get("connecting_curve_xz") or [])
            if len(points) < 2:
                from_lane = lanes_by_id.get(from_lane_id)
                to_lane = lanes_by_id.get(to_lane_id)
                if not from_lane or not to_lane:
                    continue
                start = endpoint(from_lane, "end")
                end = endpoint(to_lane, "start")
                if not start or not end:
                    continue
                points = [start, end]
            append_polygon(
                source="lane_link_centerline",
                record_id=str(link.get("lane_link_id") or link.get("link_id") or ""),
                points=points,
                width_m=float(link.get("width_m") or 3.2),
                from_lane_id=from_lane_id,
                to_lane_id=to_lane_id,
                movement=str(link.get("turn") or link.get("connection_turn") or ""),
            )
            rendered_links += 1
    elif movement_corridors:
        for case in movement_corridors.get("cases", []):
            if rendered_links >= max_links:
                break
            scoring_case = movement_scoring_by_case.get(movement_case_id(case)) if movement_scoring_by_case else None
            candidate = candidate_for_visual(case, scoring_case)
            if candidate is None:
                continue
            points = as_xz_points(candidate.get("centerline_xz") or [])
            append_polygon(
                source="movement_corridor_centerline",
                record_id=str(case.get("corridor_id") or ""),
                points=points,
                width_m=float(case.get("width_m") or 3.2),
                from_lane_id=str(case.get("from_lane_id") or ""),
                to_lane_id=str(case.get("to_lane_id") or ""),
                movement=str(case.get("movement_kind") or ""),
            )
            rendered_links += 1
    else:
        for link in lane_links:
            if rendered_links >= max_links:
                break
            if str(link.get("link_kind") or "") != "junction_movement":
                continue
            from_lane = lanes_by_id.get(str(link.get("from_lane_id") or ""))
            to_lane = lanes_by_id.get(str(link.get("to_lane_id") or ""))
            if not from_lane or not to_lane:
                continue
            start = endpoint(from_lane, "end")
            end = endpoint(to_lane, "start")
            if not start or not end:
                continue
            append_polygon(
                source="lane_link_endpoint_preview",
                record_id=str(link.get("link_id") or ""),
                points=[start, end],
                width_m=3.2,
                from_lane_id=str(link.get("from_lane_id") or ""),
                to_lane_id=str(link.get("to_lane_id") or ""),
                movement=str(link.get("turn") or ""),
            )
            rendered_links += 1

    return polygons, {
        "centerline_buffer_preview_polygons": len(polygons),
        "centerline_buffer_preview_source_counts": dict(sorted(source_counts.items())),
        "centerline_buffer_preview_skipped_movement_corridors": sum(skip_counts.values()),
        "centerline_buffer_preview_skip_reason_counts": dict(sorted(skip_counts.items())),
    }


def build_svg(
    *,
    lane_graph: dict[str, Any],
    movement_corridors: dict[str, Any] | None,
    compound_transactions: dict[str, Any] | None,
    raw_roads: dict[str, Any] | None,
    repaired_roads: dict[str, Any] | None,
    canonical_roads: dict[str, Any] | None,
    road_graph: dict[str, Any] | None,
    raw_topology_diagnostics: dict[str, Any] | None,
    area_id: str,
    width_px: int,
    max_height_px: int,
    max_lane_links: int,
    max_raw_roads: int,
    max_raw_topology_issues: int,
    corner_candidates: dict[str, Any] | None = None,
    movement_corridor_scoring: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    lanes = lane_graph.get("lanes", [])
    links = lane_link_records(lane_graph)
    continuity_links = lane_graph.get("continuity_links", [])
    lanes_by_id = lane_by_id(lane_graph)
    movement_scoring_by_case = movement_corridor_scoring_index(movement_corridor_scoring)
    road_graph_edge_by_canonical = road_graph_edge_ids_by_canonical(road_graph)
    movement_corridors_for_scale = None if links else movement_corridors
    all_points = (
        points_from_lanes(lane_graph)
        + points_from_lane_links(links)
        + points_from_movement_corridors(movement_corridors_for_scale)
        + points_from_raw_roads(raw_roads)
        + points_from_road_layer(repaired_roads, "repaired")
        + points_from_road_layer(canonical_roads, "canonical")
        + points_from_raw_topology_diagnostics(raw_topology_diagnostics)
        + points_from_corner_candidates(corner_candidates)
    )
    svg_w, svg_h, transform = scale_transform(
        all_points,
        width_px=width_px,
        max_height_px=max_height_px,
        padding_px=96,
    )

    lane_casing_lines: list[str] = []
    lane_lines: list[str] = []
    physical_lane_centerlines = lane_graph.get("physical_lane_centerlines") or []
    visible_centerlines = physical_lane_centerlines or lanes
    visible_centerline_source = "lane_graph.physical_lane_centerlines" if physical_lane_centerlines else "lane_graph.lanes"
    for lane in visible_centerlines:
        points = lane.get("centerline_xz") or []
        if len(points) < 2:
            continue
        direction = str(lane.get("direction") or "")
        source_lane_ids = [str(value) for value in lane.get("source_lane_ids") or [] if str(value)]
        road_ids = [str(value) for value in lane.get("road_ids") or [] if str(value)]
        lane_id = str(lane.get("centerline_id") or lane.get("lane_id") or "")
        road_id = ", ".join(road_ids) or str(lane.get("road_id") or lane.get("edge_id") or "")
        kind = "physical_lane_centerline" if physical_lane_centerlines else "lane"
        color = "#0f766e" if direction == "forward" else "#6d28d9"
        confidence = float(lane.get("overall_confidence") or 0.0)
        opacity = 0.48 + min(0.40, confidence * 0.42)
        width = 1.05 if confidence < 0.5 else 1.35
        casing_width = 3.25 if confidence < 0.5 else 3.85
        points_attr = polyline(points, transform)
        smoothing = lane.get("derived_centerline_smoothing") or {}
        smoothing_profiles = ", ".join(
            f"{key}:{value}"
            for key, value in sorted((smoothing.get("profile_counts") or {}).items())
        )
        physical_group_links = ", ".join(
            f"{record.get('linked_lane_id', '')}@{record.get('node_id', '')}"
            for record in lane.get("physical_lane_group_links") or []
        )
        tooltip = (
            f"lane={lane_id}; road={road_id}; "
            f"direction={direction}; confidence={confidence:.3f}; "
            f"policy={lane.get('traffic_direction_policy', '')}; "
            f"upgrade={lane.get('lane_upgrade_id', '')}; target={lane.get('lane_upgrade_target_physical_lane_count', '')}; "
            f"physical_group={lane.get('physical_lane_group_id', '')}; "
            f"smoothing={lane.get('centerline_derivation_policy', '')}; style={smoothing.get('rounding_style_id', '')}"
        )
        attrs = svg_attrs({
            "kind": kind,
            "source": visible_centerline_source,
            "id": lane_id,
            "lane_id": lane_id,
            "centerline_id": lane.get("centerline_id", ""),
            "source_lane_ids": ", ".join(source_lane_ids),
            "road_id": road_id,
            "edge_id": road_id,
            "direction": direction,
            "lane_index": lane.get("index", ""),
            "confidence": f"{confidence:.3f}",
            "policy": lane.get("traffic_direction_policy", ""),
            "lane_upgrade_id": lane.get("lane_upgrade_id", ""),
            "lane_upgrade_target_physical_lane_count": lane.get("lane_upgrade_target_physical_lane_count", ""),
            "lane_upgrade_distribution_policy": lane.get("lane_upgrade_distribution_policy", ""),
            "lane_source": lane.get("source", ""),
            "physical_lane_shared": lane.get("physical_lane_shared", ""),
            "physical_lane_group_id": lane.get("physical_lane_group_id", ""),
            "physical_lane_group_policy": lane.get("physical_lane_group_policy", ""),
            "physical_lane_group_member_count": lane.get("physical_lane_group_member_count", ""),
            "physical_lane_group_links": physical_group_links,
            "physical_lane_group_lanes": ", ".join(source_lane_ids),
            "road_width_m": lane.get("road_width_m", ""),
            "centerline_derivation_policy": lane.get("centerline_derivation_policy", ""),
            "centerline_derived_from": lane.get("centerline_derived_from", ""),
            "centerline_smoothing_bends": smoothing.get("smoothed_bends", ""),
            "centerline_smoothing_profiles": smoothing_profiles,
            "centerline_smoothing_max_derivation_offset_m": smoothing.get("max_derivation_offset_m", ""),
            "centerline_smoothing_rounding_style_id": smoothing.get("rounding_style_id", ""),
            "centerline_smoothing_curve_family": smoothing.get("curve_family", ""),
            "source_observation_lanes": (lane.get("source_observation") or {}).get("lanes", ""),
            "source_observation_lanes_source": (lane.get("source_observation") or {}).get("lanes_source", ""),
            "issues": ", ".join(str(issue) for issue in lane.get("issues") or []),
        })
        lane_casing_lines.append(
            f'<polyline {attrs} points="{points_attr}" fill="none" stroke="#d8e6e2" stroke-width="{casing_width}" '
            f'stroke-opacity="0.72" stroke-linecap="round" stroke-linejoin="round" />'
        )
        lane_lines.append(
            f'<polyline {attrs} points="{points_attr}" fill="none" '
            f'stroke="{color}" stroke-width="{width}" stroke-opacity="{opacity:.2f}" '
            f'stroke-linecap="round" stroke-linejoin="round">{svg_title(tooltip)}</polyline>'
        )

    continuity_lines, continuity_metrics = continuity_link_lines(
        links=continuity_links,
        transform=transform,
    )

    if links:
        link_lines, rendered_links = lane_link_preview_lines(
            links=links,
            lanes_by_id=lanes_by_id,
            transform=transform,
            max_links=max_lane_links,
        )
        anchor_marks = []
        movement_metrics = {
            "movement_corridors_rendered": 0,
            "anchor_markers_rendered": 0,
            "anchor_source_counts": {},
            "visual_candidate_family_counts": {},
            "visual_candidate_issue_counts": {},
            "movement_corridors_skipped": 0,
            "movement_corridor_skip_reason_counts": {},
            "movement_corridor_scoring_status_counts": {},
        }
        link_source = "lane_graph_junction_lane_links"
    elif movement_corridors:
        link_lines, anchor_marks, movement_metrics = movement_case_lines(
            movement_corridors=movement_corridors,
            movement_scoring_by_case=movement_scoring_by_case,
            transform=transform,
            max_cases=max_lane_links,
        )
        rendered_links = int(movement_metrics["movement_corridors_rendered"])
        link_source = "movement_corridor_anchors"
    else:
        link_lines = []
        anchor_marks = []
        rendered_links = 0
        movement_metrics = {
            "movement_corridors_rendered": 0,
            "anchor_markers_rendered": 0,
            "anchor_source_counts": {},
            "visual_candidate_family_counts": {},
            "visual_candidate_issue_counts": {},
            "movement_corridors_skipped": 0,
            "movement_corridor_skip_reason_counts": {},
            "movement_corridor_scoring_status_counts": {},
        }
        link_source = "missing"

    if raw_roads:
        raw_lines, raw_endpoint_marks, raw_metrics = raw_road_lines(
            raw_roads=raw_roads,
            transform=transform,
            max_raw_roads=max_raw_roads,
        )
    else:
        raw_lines = []
        raw_endpoint_marks = []
        raw_metrics = {
            "raw_roads_rendered": 0,
            "raw_road_endpoint_markers_rendered": 0,
            "raw_road_internal_vertex_markers_rendered": 0,
            "raw_road_vertex_markers_rendered": 0,
            "raw_road_class_counts": {},
        }

    if raw_topology_diagnostics:
        raw_issue_marks, raw_issue_metrics = raw_topology_issue_markers(
            raw_topology_diagnostics=raw_topology_diagnostics,
            transform=transform,
            max_issues=max_raw_topology_issues,
        )
    else:
        raw_issue_marks = []
        raw_issue_metrics = {
            "raw_topology_issue_markers_rendered": 0,
            "raw_topology_issue_classification_counts": {},
            "raw_topology_issue_severity_counts": {},
        }

    if corner_candidates:
        corner_marks, corner_metrics = corner_candidate_marks(
            corner_candidates=corner_candidates,
            transform=transform,
        )
    else:
        corner_marks = []
        corner_metrics = {
            "corner_candidates_rendered": 0,
            "corner_candidate_type_counts": {},
            "corner_candidate_risk_counts": {},
            "corner_candidate_status_counts": {},
        }

    centerline_buffer_polygons, centerline_buffer_metrics = centerline_buffer_preview_polygons(
        lanes=lanes,
        physical_lane_centerlines=physical_lane_centerlines,
        continuity_links=continuity_links,
        movement_corridors=movement_corridors,
        movement_scoring_by_case=movement_scoring_by_case,
        lane_links=links,
        lanes_by_id=lanes_by_id,
        transform=transform,
        max_links=max_lane_links,
    )

    title = html.escape(f"{area_id} lane graph (车道拓扑图) visualization")
    if repaired_roads:
        repaired_lines, repaired_metrics = road_overlay_lines(
            roads=repaired_roads,
            transform=transform,
            layer="repaired_roads",
            kind="repaired_road",
            source_label="roads_repaired.geojson",
            fallback_prefix="repaired",
            stroke="#2563eb",
            stroke_width=0.95,
            stroke_opacity=0.82,
            dasharray="5 3",
            max_roads=max_raw_roads,
        )
    else:
        repaired_lines = []
        repaired_metrics = {
            "repaired_roads_rendered": 0,
            "repaired_roads_class_counts": {},
            "repaired_roads_source_edge_count_sum": 0,
            "repaired_roads_road_graph_edge_mapped": 0,
        }

    if canonical_roads:
        canonical_lines, canonical_metrics = road_overlay_lines(
            roads=canonical_roads,
            transform=transform,
            layer="canonical_roads",
            kind="canonical_road",
            source_label="roads_canonical.geojson",
            fallback_prefix="canonical",
            stroke="#e11d48",
            stroke_width=1.35,
            stroke_opacity=0.88,
            max_roads=max_raw_roads,
            road_graph_edge_by_canonical=road_graph_edge_by_canonical,
        )
    else:
        canonical_lines = []
        canonical_metrics = {
            "canonical_roads_rendered": 0,
            "canonical_roads_class_counts": {},
            "canonical_roads_source_edge_count_sum": 0,
            "canonical_roads_road_graph_edge_mapped": 0,
        }

    subtitle = html.escape(
        "SVG is visualization（可视化） only; JSON artifacts remain source truth（源数据真值）. "
        f"Link source: {link_source}."
    )
    svg = "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w}" height="{svg_h}" viewBox="0 0 {svg_w} {svg_h}">',
        '<rect width="100%" height="100%" fill="#f8fafc" />',
        f'<text x="24" y="28" font-family="Arial, sans-serif" font-size="18" fill="#111827">{title}</text>',
        f'<text x="24" y="49" font-family="Arial, sans-serif" font-size="12" fill="#475569">{subtitle}</text>',
        '<g id="repaired-roads" data-vc-layer="repaired_roads" style="display:none">',
        *repaired_lines,
        '</g>',
        '<g id="canonical-roads" data-vc-layer="canonical_roads" style="display:none">',
        *canonical_lines,
        '</g>',
        '<g id="lane-road-casing">',
        *lane_casing_lines,
        '</g>',
        '<g id="lanes">',
        *lane_lines,
        '</g>',
        '<g id="lane-continuity-links">',
        *continuity_lines,
        '</g>',
        '<g id="lane-links">',
        *link_lines,
        '</g>',
        '<g id="raw-roads" data-vc-layer="raw_roads" style="display:none">',
        *raw_lines,
        *raw_endpoint_marks,
        *raw_issue_marks,
        '</g>',
        '<g id="corner-optimization-candidates" data-vc-layer="corner_optimization">',
        *corner_marks,
        '</g>',
        '<g id="movement-anchors">',
        *anchor_marks,
        '</g>',
        '<g id="centerline-buffer-preview" data-vc-layer="centerline_buffer_preview" style="display:none">',
        *centerline_buffer_polygons,
        '</g>',
        '<g id="legend" font-family="Arial, sans-serif" font-size="12" fill="#334155">',
        '<rect x="24" y="64" width="360" height="258" fill="#ffffff" stroke="#cbd5e1" />',
        '<line x1="40" y1="86" x2="84" y2="86" stroke="#0f766e" stroke-width="2" /><text x="94" y="90">forward lane（正向车道）</text>',
        '<line x1="40" y1="106" x2="84" y2="106" stroke="#6d28d9" stroke-width="2" /><text x="94" y="110">backward lane（反向车道）</text>',
        '<line x1="40" y1="126" x2="84" y2="126" stroke="#059669" stroke-width="2.2" stroke-dasharray="2 2" /><text x="94" y="130">direct continuity（直接连续）</text>',
        '<line x1="40" y1="146" x2="84" y2="146" stroke="#f97316" stroke-width="2" /><text x="94" y="150">turn corridor preview（转向走廊预览）</text>',
        '<line x1="40" y1="166" x2="84" y2="166" stroke="#0ea5e9" stroke-width="2" /><text x="94" y="170">through corridor preview（直行走廊预览）</text>',
        '<circle cx="47" cy="185" r="3" fill="#22c55e" stroke="#111827" stroke-width="0.5" /><text x="94" y="189">entry / exit anchors（入口 / 出口锚点）</text>',
        '<rect x="40" y="202" width="44" height="10" fill="#b7bcc4" fill-opacity="1" stroke="#8f96a1" stroke-width="0.5" /><text x="94" y="212">centerline buffer preview（车道线扩展预览）</text>',
        '<line x1="40" y1="226" x2="84" y2="226" stroke="#000000" stroke-width="1" /><text x="94" y="230">raw road data（原始道路数据）</text>',
        '<circle cx="47" cy="246" r="3" fill="#000000" stroke="#ffffff" stroke-width="0.7" /><text x="94" y="250">raw vertices（原始全部断点）</text>',
        '<circle cx="47" cy="262" r="3" fill="#ef4444" stroke="#ffffff" stroke-width="0.7" /><text x="94" y="266">topology issue（拓扑问题）</text>',
        '<line x1="40" y1="282" x2="84" y2="282" stroke="#2563eb" stroke-width="1.4" stroke-dasharray="5 3" /><text x="94" y="286">repaired roads</text>',
        '<line x1="40" y1="302" x2="84" y2="302" stroke="#e11d48" stroke-width="1.8" /><text x="94" y="306">canonical roads</text>',
        '</g>',
        '</svg>',
    ])
    report = {
        "area_id": area_id,
        "stage": "lane_graph_svg_visualization",
        "status": "pass",
        "counts": {
            "lanes": len(lanes),
            "physical_lane_centerlines": len(physical_lane_centerlines),
            "visible_lane_centerlines": len(visible_centerlines),
            "lane_links_total": len(links),
            "continuity_links_total": len(continuity_links),
            "junction_connections_rendered": rendered_links,
            **continuity_metrics,
            **movement_metrics,
            **raw_metrics,
            **raw_issue_metrics,
            **corner_metrics,
            **repaired_metrics,
            **canonical_metrics,
            **centerline_buffer_metrics,
        },
        "style": {
            "svg_width_px": svg_w,
            "svg_height_px": svg_h,
            "anchor_marker_radius_px": ANCHOR_MARKER_RADIUS_PX,
            "anchor_marker_stroke_width_px": ANCHOR_MARKER_STROKE_WIDTH_PX,
            "lane_casing": "enabled（已启用）",
            "visual_mode": "review_drawing（审图线稿）",
            "raw_roads_overlay": (
                "thin_black_solid_with_all_vertex_markers_hidden_by_default"
                "（细黑实线 + 全部原始顶点/断点标记，默认隐藏）"
            ) if raw_roads else "missing（缺失）",
            "raw_topology_issue_overlay": "enabled_when_diagnostics_exist（诊断存在时启用）" if raw_topology_diagnostics else "missing（缺失）",
            "repaired_roads_overlay": "blue_dashed_hidden_by_default" if repaired_roads else "missing",
            "canonical_roads_overlay": "rose_solid_hidden_by_default" if canonical_roads else "missing",
            "centerline_buffer_preview_overlay": "uniform_gray_hidden_by_default",
            "movement_corridor_preview_gate": "fallback_when_no_lane_graph_junction_lane_links",
        },
        "link_source": link_source,
        "final_lane_link_precedence": "lane_graph_junction_lane_links_before_movement_corridor_candidates",
        "note": (
            "SVG visualization（可视化） only. lane_graph.json and movement_corridor_candidates.json "
            "are structured artifacts（结构化产物）. "
            "Corridor curves are preview candidates（候选预览）, not final lane geometry（最终车道几何）."
        ),
    }
    return svg, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Export lane_graph.json to SVG visualization.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--lane-graph", default="")
    parser.add_argument("--movement-corridors", default="", help="Optional movement_corridor_candidates.json. Defaults to processed/<area_id> file if present.")
    parser.add_argument("--movement-corridor-scoring", default="", help="Optional movement_corridor_scoring.json used to gate corridor preview rendering.")
    parser.add_argument("--compound-transactions", default="", help="Deprecated no-op; compound corridor overlay is no longer rendered.")
    parser.add_argument("--raw-roads", default="", help="Optional roads_raw.geojson overlay. Defaults to processed/<area_id> file if present.")
    parser.add_argument("--repaired-roads", default="", help="Optional roads_repaired.geojson overlay. Defaults to processed/<area_id> file if present.")
    parser.add_argument("--canonical-roads", default="", help="Optional roads_canonical.geojson overlay. Defaults to processed/<area_id> file if present.")
    parser.add_argument("--road-graph", default="", help="Optional road_graph.json used to map canonical roads to road graph edge ids.")
    parser.add_argument("--raw-topology-diagnostics", default="", help="Optional raw_topology_diagnostics.json issue overlay.")
    parser.add_argument("--corner-candidates", default="", help="Optional corner_optimization_candidates.json overlay.")
    parser.add_argument("--no-movement-corridors", action="store_true", help="Do not auto-load movement corridor overlay.")
    parser.add_argument("--no-movement-corridor-scoring", action="store_true", help="Do not auto-load movement corridor scoring gate.")
    parser.add_argument("--no-compound-transactions", action="store_true", help="Deprecated no-op; compound corridor overlay is no longer rendered.")
    parser.add_argument("--no-raw-roads", action="store_true", help="Do not auto-load raw road source overlay.")
    parser.add_argument("--no-repaired-roads", action="store_true", help="Do not auto-load repaired road overlay.")
    parser.add_argument("--no-canonical-roads", action="store_true", help="Do not auto-load canonical road overlay.")
    parser.add_argument("--no-raw-topology-diagnostics", action="store_true", help="Do not auto-load raw topology diagnostics overlay.")
    parser.add_argument("--no-corner-candidates", action="store_true", help="Do not auto-load corner optimization candidate overlay.")
    parser.add_argument("--output", default="")
    parser.add_argument("--report", default="")
    parser.add_argument("--width-px", type=int, default=DEFAULT_REVIEW_WIDTH_PX)
    parser.add_argument("--max-height-px", type=int, default=DEFAULT_MAX_HEIGHT_PX)
    parser.add_argument("--max-lane-links", type=int, default=900)
    parser.add_argument("--max-raw-roads", type=int, default=1200)
    parser.add_argument("--max-raw-topology-issues", type=int, default=600)
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    processed = root / "data" / "processed"
    reports = root / "reports"
    lane_graph_path = Path(args.lane_graph) if args.lane_graph else processed / f"{args.area_id}_lane_graph.json"
    movement_corridors_path = (
        None
        if args.no_movement_corridors
        else Path(args.movement_corridors)
        if args.movement_corridors
        else processed / f"{args.area_id}_movement_corridor_candidates.json"
    )
    movement_corridors = read_json(movement_corridors_path) if movement_corridors_path and movement_corridors_path.exists() else None
    movement_corridor_scoring_path = (
        None
        if args.no_movement_corridor_scoring
        else Path(args.movement_corridor_scoring)
        if args.movement_corridor_scoring
        else processed / f"{args.area_id}_movement_corridor_scoring.json"
    )
    movement_corridor_scoring = (
        read_json(movement_corridor_scoring_path)
        if movement_corridor_scoring_path and movement_corridor_scoring_path.exists()
        else None
    )
    compound_transactions_path = None
    compound_transactions = None
    raw_roads_path = (
        None
        if args.no_raw_roads
        else Path(args.raw_roads)
        if args.raw_roads
        else processed / f"{args.area_id}_roads_raw.geojson"
    )
    raw_roads = read_json(raw_roads_path) if raw_roads_path and raw_roads_path.exists() else None
    repaired_roads_path = (
        None
        if args.no_repaired_roads
        else Path(args.repaired_roads)
        if args.repaired_roads
        else processed / f"{args.area_id}_roads_repaired.geojson"
    )
    repaired_roads = read_json(repaired_roads_path) if repaired_roads_path and repaired_roads_path.exists() else None
    canonical_roads_path = (
        None
        if args.no_canonical_roads
        else Path(args.canonical_roads)
        if args.canonical_roads
        else processed / f"{args.area_id}_roads_canonical.geojson"
    )
    canonical_roads = read_json(canonical_roads_path) if canonical_roads_path and canonical_roads_path.exists() else None
    road_graph_path = Path(args.road_graph) if args.road_graph else processed / f"{args.area_id}_road_graph.json"
    road_graph = read_json(road_graph_path) if road_graph_path.exists() else None
    raw_topology_diagnostics_path = (
        None
        if args.no_raw_topology_diagnostics
        else Path(args.raw_topology_diagnostics)
        if args.raw_topology_diagnostics
        else processed / f"{args.area_id}_raw_topology_diagnostics.json"
    )
    raw_topology_diagnostics = (
        read_json(raw_topology_diagnostics_path)
        if raw_topology_diagnostics_path and raw_topology_diagnostics_path.exists()
        else None
    )
    corner_candidates_path = (
        None
        if args.no_corner_candidates
        else Path(args.corner_candidates)
        if args.corner_candidates
        else processed / f"{args.area_id}_corner_optimization_candidates.json"
    )
    corner_candidates = (
        read_json(corner_candidates_path)
        if corner_candidates_path and corner_candidates_path.exists()
        else None
    )
    output_path = Path(args.output) if args.output else reports / "visualizations" / f"{args.area_id}_lane_graph_topology.svg"
    report_path = Path(args.report) if args.report else reports / f"{args.area_id}_lane_graph_svg_report.json"

    svg, report = build_svg(
        lane_graph=read_json(lane_graph_path),
        movement_corridors=movement_corridors,
        compound_transactions=compound_transactions,
        raw_roads=raw_roads,
        repaired_roads=repaired_roads,
        canonical_roads=canonical_roads,
        road_graph=road_graph,
        raw_topology_diagnostics=raw_topology_diagnostics,
        area_id=args.area_id,
        width_px=args.width_px,
        max_height_px=args.max_height_px,
        max_lane_links=args.max_lane_links,
        max_raw_roads=args.max_raw_roads,
        max_raw_topology_issues=args.max_raw_topology_issues,
        corner_candidates=corner_candidates,
        movement_corridor_scoring=movement_corridor_scoring,
    )
    report["inputs"] = {
        "lane_graph": rel(lane_graph_path, root),
        "movement_corridors": rel(movement_corridors_path, root) if movement_corridors_path and movement_corridors is not None else "",
        "movement_corridor_scoring": rel(movement_corridor_scoring_path, root) if movement_corridor_scoring_path and movement_corridor_scoring is not None else "",
        "raw_roads": rel(raw_roads_path, root) if raw_roads_path and raw_roads is not None else "",
        "repaired_roads": rel(repaired_roads_path, root) if repaired_roads_path and repaired_roads is not None else "",
        "canonical_roads": rel(canonical_roads_path, root) if canonical_roads_path and canonical_roads is not None else "",
        "road_graph": rel(road_graph_path, root) if road_graph is not None else "",
        "raw_topology_diagnostics": rel(raw_topology_diagnostics_path, root) if raw_topology_diagnostics_path and raw_topology_diagnostics is not None else "",
        "corner_candidates": rel(corner_candidates_path, root) if corner_candidates_path and corner_candidates is not None else "",
    }
    report["outputs"] = {"svg": rel(output_path, root), "report": rel(report_path, root)}
    write_text(output_path, svg)
    write_json(report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
