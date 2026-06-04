#!/usr/bin/env python3
"""Plan corner optimization candidates without mutating road geometry.

This stage is a proposal layer in the road upgrade system. It finds sharp
degree-2 connector corners and sharp interior bends in optimized approach
centerlines, then writes structured candidates for QA and SVG review.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA = "road_upgrade_system.corner_optimization_candidates.v1"
REPORT_SCHEMA = "road_upgrade_system.corner_optimization_report.v1"
MIN_CONNECTOR_TURN_DEG = 18.0
MIN_INTERIOR_TURN_DEG = 28.0
MIN_SEGMENT_M = 1.0
MAX_CONTEXT_M = 18.0
LOW_RISK_MAX_JUNCTION_DISTANCE_M = 4.0


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_optional_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return read_json(path)


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def normalize(v: tuple[float, float]) -> tuple[float, float]:
    length = math.hypot(v[0], v[1])
    if length <= 1e-9:
        return 0.0, 0.0
    return v[0] / length, v[1] / length


def angle_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1]))
    return math.degrees(math.acos(dot))


def polyline_length(points: list[tuple[float, float]]) -> float:
    return sum(distance(points[i], points[i + 1]) for i in range(len(points) - 1))


def edge_points(edge: dict[str, Any]) -> list[tuple[float, float]]:
    return [(float(point[0]), float(point[1])) for point in edge.get("geometry_xz") or [] if len(point) >= 2]


def direction_out(edge: dict[str, Any], node_id: str) -> tuple[float, float]:
    points = edge_points(edge)
    if len(points) < 2:
        return 0.0, 0.0
    if node_id == str(edge.get("from_node") or ""):
        return normalize((points[1][0] - points[0][0], points[1][1] - points[0][1]))
    return normalize((points[-2][0] - points[-1][0], points[-2][1] - points[-1][1]))


def point_along_from_node(edge: dict[str, Any], node_id: str, amount_m: float) -> tuple[float, float] | None:
    points = edge_points(edge)
    if len(points) < 2:
        return None
    if node_id != str(edge.get("from_node") or ""):
        points = list(reversed(points))
    remaining = max(0.0, amount_m)
    for index in range(len(points) - 1):
        segment = distance(points[index], points[index + 1])
        if segment <= 1e-9:
            continue
        if remaining <= segment:
            t = remaining / segment
            return (
                points[index][0] + (points[index + 1][0] - points[index][0]) * t,
                points[index][1] + (points[index + 1][1] - points[index][1]) * t,
            )
        remaining -= segment
    return points[-1]


def suggested_cut_m(width_m: float, turn_deg: float, segment_a_m: float, segment_b_m: float) -> float:
    angle_gain = min(1.25, max(0.65, turn_deg / 90.0))
    cut = max(1.5, width_m * 0.75 * angle_gain)
    cut = min(cut, 10.0, segment_a_m * 0.38, segment_b_m * 0.38)
    return max(0.0, cut)


def suggested_radius_m(width_m: float, turn_deg: float) -> float:
    if turn_deg <= 0.0:
        return 0.0
    base = max(3.0, width_m * 0.8)
    return round(base * min(1.8, max(0.75, turn_deg / 70.0)), 3)


def risk_for_candidate(
    *,
    turn_deg: float,
    near_junction: bool,
    shortest_segment_m: float,
    candidate_type: str,
) -> tuple[str, str]:
    if near_junction:
        return "high", "proposal_only_review_near_junction"
    if shortest_segment_m < 4.0:
        return "medium", "proposal_only_review_short_context"
    if candidate_type == "degree2_connector_corner" and turn_deg >= 18.0:
        return "low", "candidate_for_auto_fillet_after_review"
    if turn_deg >= 55.0:
        return "medium", "proposal_only_review_sharp_internal_bend"
    return "low", "candidate_for_smoothing_after_review"


def local_projector_from_metadata(fc: dict[str, Any]) -> tuple[float, float]:
    meta = fc.get("metadata") or {}
    return float(meta.get("origin_lon") or 0.0), float(meta.get("origin_lat") or 0.0)


def to_local(lon: float, lat: float, origin_lon: float, origin_lat: float) -> tuple[float, float]:
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(origin_lat))
    return (lon - origin_lon) * m_per_deg_lon, (lat - origin_lat) * m_per_deg_lat


def feature_points_xz(feature: dict[str, Any], origin_lon: float, origin_lat: float) -> list[tuple[float, float]]:
    geom = feature.get("geometry") or {}
    if str(geom.get("type") or "") != "LineString":
        return []
    points: list[tuple[float, float]] = []
    for coord in geom.get("coordinates") or []:
        if len(coord) < 2:
            continue
        points.append(to_local(float(coord[0]), float(coord[1]), origin_lon, origin_lat))
    return points


def nearest_junction_distance(point: tuple[float, float], nodes: list[dict[str, Any]]) -> float:
    junction_points = [
        (float(node.get("x") or 0.0), float(node.get("z") or 0.0))
        for node in nodes
        if str(node.get("kind") or "") == "junction"
    ]
    if not junction_points:
        return float("inf")
    return min(distance(point, junction) for junction in junction_points)


def corner_match_key(candidate: dict[str, Any]) -> tuple[str, tuple[str, str]]:
    node_id = str(candidate.get("node_id") or "")
    edge_ids = [str(candidate.get("from_edge_id") or ""), str(candidate.get("to_edge_id") or "")]
    a, b = sorted(edge_ids)
    return node_id, (a, b)


def internal_bend_match_key(candidate: dict[str, Any]) -> tuple[str, int]:
    try:
        point_index = int(candidate.get("point_index"))
    except (TypeError, ValueError):
        point_index = -1
    return str(candidate.get("source_edge_id") or ""), point_index


def active_corner_override_index(
    overrides_doc: dict[str, Any],
) -> tuple[dict[tuple[str, tuple[str, str]], dict[str, Any]], dict[tuple[str, int], dict[str, Any]]]:
    degree2_indexed: dict[tuple[str, tuple[str, str]], dict[str, Any]] = {}
    internal_indexed: dict[tuple[str, int], dict[str, Any]] = {}
    for item in overrides_doc.get("active_corner_optimizations", []):
        if not bool(item.get("enabled", True)):
            continue
        candidate_type = str(item.get("candidate_type") or "")
        if candidate_type == "internal_centerline_bend":
            try:
                point_index = int(item.get("point_index"))
            except (TypeError, ValueError):
                point_index = -1
            source_edge_id = str(item.get("source_edge_id") or "")
            if not source_edge_id or point_index < 1:
                continue
            internal_indexed[(source_edge_id, point_index)] = item
            continue
        node_id = str(item.get("node_id") or "")
        edge_ids = [str(item.get("from_edge_id") or ""), str(item.get("to_edge_id") or "")]
        if not node_id or not all(edge_ids):
            continue
        a, b = sorted(edge_ids)
        degree2_indexed[(node_id, (a, b))] = item
    return degree2_indexed, internal_indexed


def annotate_active_corner_overrides(candidates: list[dict[str, Any]], overrides_doc: dict[str, Any]) -> int:
    degree2_active, internal_active = active_corner_override_index(overrides_doc)
    applied = 0
    for candidate in candidates:
        candidate_type = str(candidate.get("candidate_type") or "")
        if candidate_type == "degree2_connector_corner":
            override = degree2_active.get(corner_match_key(candidate))
        elif candidate_type == "internal_centerline_bend":
            override = internal_active.get(internal_bend_match_key(candidate))
        else:
            override = None
        if override is None:
            continue
        candidate["status"] = "accepted_active"
        candidate["recommended_action"] = "active_geometry_transaction"
        candidate["corner_optimization_id"] = str(override.get("corner_optimization_id") or "")
        candidate["corner_optimization_application_id"] = str(override.get("application_id") or "")
        candidate["corner_optimization_policy"] = str(override.get("policy") or "")
        applied += 1
    return applied


def active_corner_override_counts(overrides_doc: dict[str, Any]) -> dict[str, int]:
    degree2_active, internal_active = active_corner_override_index(overrides_doc)
    return {
        "degree2_connector_corner": len(degree2_active),
        "internal_centerline_bend": len(internal_active),
        "total": len(degree2_active) + len(internal_active),
    }


def active_override_candidate_ids(overrides_doc: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for item in overrides_doc.get("active_corner_optimizations", []):
        if not bool(item.get("enabled", True)):
            continue
        candidate_id = str(item.get("candidate_id") or "")
        if candidate_id:
            ids.add(candidate_id)
    return ids


def next_candidate_id(index: int) -> str:
    return f"corner_{index:04d}"


def stabilize_candidate_ids(candidates: list[dict[str, Any]], overrides_doc: dict[str, Any]) -> int:
    active_ids = active_override_candidate_ids(overrides_doc)
    used: set[str] = set()
    next_index = 0
    reassignments = 0
    for candidate in candidates:
        old_id = str(candidate.get("candidate_id") or "")
        keep_active_id = (
            old_id
            and old_id in active_ids
            and str(candidate.get("status") or "") == "accepted_active"
            and old_id not in used
        )
        if keep_active_id:
            used.add(old_id)
            continue
        while True:
            candidate_id = next_candidate_id(next_index)
            next_index += 1
            if candidate_id in used or candidate_id in active_ids:
                continue
            break
        if old_id != candidate_id:
            candidate["candidate_id_reassigned_from"] = old_id
            candidate["candidate_id_reassignment_reason"] = "avoid_active_corner_override_candidate_id_reuse"
            reassignments += 1
        candidate["candidate_id"] = candidate_id
        used.add(candidate_id)
    return reassignments


def add_degree2_connector_candidates(
    *,
    candidates: list[dict[str, Any]],
    road_graph: dict[str, Any],
) -> None:
    edge_by_id = {str(edge.get("edge_id") or ""): edge for edge in road_graph.get("edges", [])}
    for node in road_graph.get("nodes", []):
        node_id = str(node.get("node_id") or "")
        incident = [str(edge_id) for edge_id in node.get("incident_edges", []) if str(edge_id) in edge_by_id]
        if int(node.get("degree") or len(incident)) != 2 or len(incident) != 2:
            continue
        edge_a = edge_by_id[incident[0]]
        edge_b = edge_by_id[incident[1]]
        direction_a = direction_out(edge_a, node_id)
        direction_b = direction_out(edge_b, node_id)
        interior_angle = angle_between(direction_a, direction_b)
        turn_deg = 180.0 - interior_angle
        if turn_deg < MIN_CONNECTOR_TURN_DEG:
            continue
        center = (float(node.get("x") or 0.0), float(node.get("z") or 0.0))
        len_a = float(edge_a.get("length_m") or polyline_length(edge_points(edge_a)))
        len_b = float(edge_b.get("length_m") or polyline_length(edge_points(edge_b)))
        width_m = max(float(edge_a.get("width_m") or 6.0), float(edge_b.get("width_m") or 6.0))
        context_a = point_along_from_node(edge_a, node_id, min(MAX_CONTEXT_M, max(1.0, len_a * 0.5)))
        context_b = point_along_from_node(edge_b, node_id, min(MAX_CONTEXT_M, max(1.0, len_b * 0.5)))
        if context_a is None or context_b is None:
            continue
        near_junction = str(node.get("kind") or "") == "junction"
        risk, action = risk_for_candidate(
            turn_deg=turn_deg,
            near_junction=near_junction,
            shortest_segment_m=min(len_a, len_b),
            candidate_type="degree2_connector_corner",
        )
        candidate_id = f"corner_{len(candidates):04d}"
        candidates.append({
            "candidate_id": candidate_id,
            "candidate_type": "degree2_connector_corner",
            "status": "candidate_review",
            "risk_level": risk,
            "recommended_action": action,
            "node_id": node_id,
            "node_kind": str(node.get("kind") or ""),
            "from_edge_id": str(edge_a.get("edge_id") or ""),
            "to_edge_id": str(edge_b.get("edge_id") or ""),
            "from_canonical_road_id": str(edge_a.get("canonical_road_id") or ""),
            "to_canonical_road_id": str(edge_b.get("canonical_road_id") or ""),
            "road_class": str(edge_a.get("road_class") or edge_b.get("road_class") or ""),
            "turn_angle_deg": round(turn_deg, 3),
            "interior_angle_deg": round(interior_angle, 3),
            "suggested_cut_m": round(suggested_cut_m(width_m, turn_deg, len_a, len_b), 3),
            "suggested_radius_m": suggested_radius_m(width_m, turn_deg),
            "nearest_junction_distance_m": 0.0 if near_junction else round(nearest_junction_distance(center, road_graph.get("nodes", [])), 3),
            "center_xz": [round(center[0], 3), round(center[1], 3)],
            "context_polyline_xz": [
                [round(context_a[0], 3), round(context_a[1], 3)],
                [round(center[0], 3), round(center[1], 3)],
                [round(context_b[0], 3), round(context_b[1], 3)],
            ],
            "rationale": "Degree-2 connector node creates a visible road-corner bend.",
        })


def add_internal_bend_candidates(
    *,
    candidates: list[dict[str, Any]],
    optimized_centerlines: dict[str, Any],
    road_graph: dict[str, Any],
) -> None:
    origin_lon, origin_lat = local_projector_from_metadata(optimized_centerlines)
    nodes = road_graph.get("nodes", [])
    for feature in optimized_centerlines.get("features", []):
        props = feature.get("properties") or {}
        if str(props.get("vc_part") or "") != "optimized_approach_centerline":
            continue
        points = feature_points_xz(feature, origin_lon, origin_lat)
        if len(points) < 3:
            continue
        source_edge_id = str(props.get("source_edge_id") or "")
        for index in range(1, len(points) - 1):
            previous = points[index - 1]
            center = points[index]
            nxt = points[index + 1]
            seg_a = distance(previous, center)
            seg_b = distance(center, nxt)
            if seg_a < MIN_SEGMENT_M or seg_b < MIN_SEGMENT_M:
                continue
            direction_a = normalize((previous[0] - center[0], previous[1] - center[1]))
            direction_b = normalize((nxt[0] - center[0], nxt[1] - center[1]))
            interior_angle = angle_between(direction_a, direction_b)
            turn_deg = 180.0 - interior_angle
            if turn_deg < MIN_INTERIOR_TURN_DEG:
                continue
            nearest_junction = nearest_junction_distance(center, nodes)
            near_junction = nearest_junction <= LOW_RISK_MAX_JUNCTION_DISTANCE_M
            width_m = float(props.get("width_m") or 6.0)
            risk, action = risk_for_candidate(
                turn_deg=turn_deg,
                near_junction=near_junction,
                shortest_segment_m=min(seg_a, seg_b),
                candidate_type="internal_centerline_bend",
            )
            candidate_id = f"corner_{len(candidates):04d}"
            candidates.append({
                "candidate_id": candidate_id,
                "candidate_type": "internal_centerline_bend",
                "status": "candidate_review",
                "risk_level": risk,
                "recommended_action": action,
                "source_edge_id": source_edge_id,
                "canonical_road_id": str(props.get("source_feature_id") or ""),
                "road_class": str(props.get("road_class") or props.get("highway") or ""),
                "point_index": index,
                "turn_angle_deg": round(turn_deg, 3),
                "interior_angle_deg": round(interior_angle, 3),
                "suggested_cut_m": round(suggested_cut_m(width_m, turn_deg, seg_a, seg_b), 3),
                "suggested_radius_m": suggested_radius_m(width_m, turn_deg),
                "nearest_junction_distance_m": round(nearest_junction, 3) if math.isfinite(nearest_junction) else 0.0,
                "center_xz": [round(center[0], 3), round(center[1], 3)],
                "context_polyline_xz": [
                    [round(previous[0], 3), round(previous[1], 3)],
                    [round(center[0], 3), round(center[1], 3)],
                    [round(nxt[0], 3), round(nxt[1], 3)],
                ],
                "rationale": "Optimized approach centerline still contains a sharp interior bend.",
            })


def plan_corner_optimization(
    *,
    area_id: str,
    road_graph_path: Path,
    optimized_centerlines_path: Path,
    corner_overrides_path: Path | None = None,
    output_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    road_graph = read_json(road_graph_path)
    optimized_centerlines = read_json(optimized_centerlines_path)
    corner_overrides = read_optional_json(corner_overrides_path)
    candidates: list[dict[str, Any]] = []
    add_degree2_connector_candidates(candidates=candidates, road_graph=road_graph)
    add_internal_bend_candidates(
        candidates=candidates,
        optimized_centerlines=optimized_centerlines,
        road_graph=road_graph,
    )
    active_applied = annotate_active_corner_overrides(candidates, corner_overrides)
    candidate_id_reassignments = stabilize_candidate_ids(candidates, corner_overrides)
    active_override_counts = active_corner_override_counts(corner_overrides)
    type_counts = Counter(str(candidate.get("candidate_type") or "") for candidate in candidates)
    risk_counts = Counter(str(candidate.get("risk_level") or "") for candidate in candidates)
    status_counts = Counter(str(candidate.get("status") or "") for candidate in candidates)
    report = {
        "area_id": area_id,
        "stage": "corner_optimization_candidates_v1",
        "schema": REPORT_SCHEMA,
        "status": "pass",
        "inputs": {
            "road_graph": str(road_graph_path),
            "optimized_centerlines": str(optimized_centerlines_path),
            "corner_overrides": str(corner_overrides_path) if corner_overrides_path and corner_overrides_path.exists() else "",
        },
        "outputs": {
            "candidates": str(output_path),
            "report": str(report_path),
        },
        "counts": {
            "candidates": len(candidates),
            "degree2_connector_corner": type_counts.get("degree2_connector_corner", 0),
            "internal_centerline_bend": type_counts.get("internal_centerline_bend", 0),
            "low_risk": risk_counts.get("low", 0),
            "medium_risk": risk_counts.get("medium", 0),
            "high_risk": risk_counts.get("high", 0),
            "accepted_active": active_override_counts["total"],
            "accepted_active_candidates": active_applied,
            "accepted_active_overrides": active_override_counts["total"],
            "active_degree2_corner_overrides": active_override_counts["degree2_connector_corner"],
            "active_internal_bend_overrides": active_override_counts["internal_centerline_bend"],
            "candidate_id_reassignments": candidate_id_reassignments,
        },
        "type_counts": dict(sorted(type_counts.items())),
        "risk_counts": dict(sorted(risk_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "note": "Corner optimization candidates are proposal records; accepted_active counts active geometry transactions, including internal bends that no longer appear as candidates after smoothing.",
    }
    payload = {
        "type": "corner_optimization_candidates",
        "metadata": {
            "area_id": area_id,
            "schema": SCHEMA,
            "policy": "proposal_only_no_geometry_mutation",
            "source_road_graph": str(road_graph_path),
            "source_optimized_centerlines": str(optimized_centerlines_path),
            "source_corner_overrides": str(corner_overrides_path) if corner_overrides_path and corner_overrides_path.exists() else "",
        },
        "candidates": candidates,
    }
    write_json(output_path, payload)
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan road corner optimization candidates.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--road-graph", default="")
    parser.add_argument("--optimized-centerlines", default="")
    parser.add_argument("--corner-overrides", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    processed = root / "data" / "processed"
    reports = root / "reports"
    road_graph_path = Path(args.road_graph) if args.road_graph else processed / f"{args.area_id}_road_graph.json"
    optimized_centerlines_path = (
        Path(args.optimized_centerlines)
        if args.optimized_centerlines
        else processed / f"{args.area_id}_roads_optimized_centerlines.geojson"
    )
    output_path = Path(args.output) if args.output else processed / f"{args.area_id}_corner_optimization_candidates.json"
    report_path = Path(args.report) if args.report else reports / f"{args.area_id}_corner_optimization_report.json"
    corner_overrides_path = Path(args.corner_overrides) if args.corner_overrides else processed / f"{args.area_id}_corner_optimization_overrides.json"
    report = plan_corner_optimization(
        area_id=args.area_id,
        road_graph_path=road_graph_path,
        optimized_centerlines_path=optimized_centerlines_path,
        corner_overrides_path=corner_overrides_path,
        output_path=output_path,
        report_path=report_path,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
