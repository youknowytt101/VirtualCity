#!/usr/bin/env python3
"""Regularize junction areas before connector-curve generation.

This stage does not change road topology. It publishes a stable engineering
model that later connector solvers can consume:
- junction conflict-zone estimates
- approach entry/exit poses
- short-edge absorption candidates
- movement-level connecting-road intents
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


MIN_ENTRY_TRIM_M = 2.0
MAX_ENTRY_TRIM_M = 18.0
SHORT_EDGE_ABSORB_MIN_M = 3.0
SHORT_EDGE_WIDTH_FACTOR = 1.25
CONFLICT_ZONE_MARGIN_M = 1.5

TURN_MIN_RADIUS_BY_CLASS = {
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


def normalize(v: tuple[float, float]) -> tuple[float, float]:
    length = math.sqrt(v[0] * v[0] + v[1] * v[1])
    if length <= 1e-9:
        return 0.0, 0.0
    return v[0] / length, v[1] / length


def point_along(points: list[tuple[float, float]], amount: float) -> tuple[float, float]:
    if not points:
        return 0.0, 0.0
    if len(points) == 1 or amount <= 0.0:
        return points[0]
    remaining = amount
    for i in range(len(points) - 1):
        a = points[i]
        b = points[i + 1]
        seg_len = distance(a, b)
        if seg_len <= 1e-9:
            continue
        if remaining <= seg_len:
            t = remaining / seg_len
            return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        remaining -= seg_len
    return points[-1]


def edge_points_from_node(edge: dict[str, Any], node_id: str) -> list[tuple[float, float]]:
    points = [(float(p[0]), float(p[1])) for p in edge.get("geometry_xz") or []]
    if edge.get("from_node") == node_id:
        return points
    return list(reversed(points))


def direction_out(edge: dict[str, Any], node_id: str) -> tuple[float, float]:
    points = edge_points_from_node(edge, node_id)
    if len(points) < 2:
        return 0.0, 0.0
    return normalize((points[1][0] - points[0][0], points[1][1] - points[0][1]))


def road_class_min_radius(road_class: str) -> float:
    return TURN_MIN_RADIUS_BY_CLASS.get(str(road_class or "unclassified"), 6.0)


def desired_entry_trim(approach: dict[str, Any]) -> float:
    width = float(approach.get("width_m") or 0.0)
    road_class = str(approach.get("road_class") or approach.get("highway") or "unclassified")
    min_radius = road_class_min_radius(road_class)
    trim = max(
        MIN_ENTRY_TRIM_M,
        width * 0.75 + CONFLICT_ZONE_MARGIN_M,
        min_radius * 0.65,
    )
    return min(MAX_ENTRY_TRIM_M, trim)


def short_edge_absorb_threshold(approach: dict[str, Any]) -> float:
    width = float(approach.get("width_m") or 0.0)
    return max(SHORT_EDGE_ABSORB_MIN_M, width * SHORT_EDGE_WIDTH_FACTOR)


def regularize_approach(
    *,
    junction: dict[str, Any],
    approach: dict[str, Any],
    edge: dict[str, Any],
    nodes_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    node_id = str(junction["node_id"])
    center = (float(junction["center_xz"][0]), float(junction["center_xz"][1]))
    points = edge_points_from_node(edge, node_id)
    edge_length = float(edge.get("length_m") or 0.0)
    desired_trim = desired_entry_trim(approach)
    available_trim = max(0.0, edge_length - 0.5)
    trim = min(desired_trim, available_trim)
    if trim <= 0.0:
        trim = min(edge_length, MIN_ENTRY_TRIM_M)

    tangent = direction_out(edge, node_id)
    entry = point_along(points, trim) if points else (
        center[0] + tangent[0] * trim,
        center[1] + tangent[1] * trim,
    )
    other_node_id = edge.get("to_node") if edge.get("from_node") == node_id else edge.get("from_node")
    other_node = nodes_by_id.get(str(other_node_id), {})
    absorb_threshold = short_edge_absorb_threshold(approach)
    absorption_candidate = edge_length <= absorb_threshold and str(other_node.get("kind") or "") == "connector"

    issues = []
    if trim + 1e-6 < desired_trim:
        issues.append("entry_trim_capacity_limited")
    if absorption_candidate:
        issues.append("short_edge_absorption_candidate")
    if distance(center, entry) < MIN_ENTRY_TRIM_M:
        issues.append("entry_pose_too_close_to_center")

    return {
        "pose_id": f"{junction['junction_id']}_{approach['edge_id']}_entry",
        "junction_id": junction["junction_id"],
        "node_id": node_id,
        "edge_id": approach["edge_id"],
        "approach_id": approach.get("approach_id", ""),
        "role": approach.get("role", ""),
        "road_class": approach.get("road_class", edge.get("road_class", "")),
        "highway": approach.get("highway", edge.get("highway", "")),
        "lanes": int(approach.get("lanes") or edge.get("lanes") or 1),
        "width_m": float(approach.get("width_m") or edge.get("width_m") or 0.0),
        "edge_length_m": round(edge_length, 3),
        "desired_trim_m": round(desired_trim, 3),
        "available_trim_m": round(available_trim, 3),
        "entry_trim_m": round(trim, 3),
        "entry_xz": [round(entry[0], 3), round(entry[1], 3)],
        "center_distance_m": round(distance(center, entry), 3),
        "tangent_out_xz": [round(tangent[0], 6), round(tangent[1], 6)],
        "can_enter_junction": bool(approach.get("can_enter_junction")),
        "can_exit_junction": bool(approach.get("can_exit_junction")),
        "short_edge_absorption": {
            "candidate": absorption_candidate,
            "threshold_m": round(absorb_threshold, 3),
            "other_node_id": str(other_node_id or ""),
            "other_node_kind": str(other_node.get("kind") or ""),
        },
        "issues": issues,
        "status": "warn" if issues else "pass",
    }


def regularize_junctions(
    road_graph: dict[str, Any],
    junction_semantics: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    nodes_by_id = {str(node["node_id"]): node for node in road_graph.get("nodes", [])}
    edges_by_id = {str(edge["edge_id"]): edge for edge in road_graph.get("edges", [])}
    areas = []
    reference_poses = []
    connecting_road_intents = []
    issue_counter: Counter[str] = Counter()
    status_counter: Counter[str] = Counter()

    for junction in junction_semantics.get("junctions", []):
        approaches = []
        center = [round(float(junction["center_xz"][0]), 3), round(float(junction["center_xz"][1]), 3)]
        for approach in junction.get("approaches", []):
            edge = edges_by_id.get(str(approach.get("edge_id")))
            if edge is None:
                issue_counter["missing_approach_edge"] += 1
                continue
            regularized = regularize_approach(
                junction=junction,
                approach=approach,
                edge=edge,
                nodes_by_id=nodes_by_id,
            )
            approaches.append(regularized)
            reference_poses.append(regularized)
            issue_counter.update(regularized["issues"])

        conflict_zone_radius = max((float(item["entry_trim_m"]) for item in approaches), default=0.0)
        conflict_zone_radius = round(conflict_zone_radius + CONFLICT_ZONE_MARGIN_M, 3)
        area_issues = sorted({issue for item in approaches for issue in item["issues"]})
        area_status = "warn" if area_issues else "pass"
        status_counter[area_status] += 1

        pose_by_edge = {item["edge_id"]: item for item in approaches}
        movement_intents = []
        for movement in junction.get("movements", []):
            from_pose = pose_by_edge.get(str(movement.get("from_edge")))
            to_pose = pose_by_edge.get(str(movement.get("to_edge")))
            if from_pose is None or to_pose is None:
                issue_counter["movement_missing_pose"] += 1
                continue
            intent = {
                "intent_id": f"{movement['movement_id']}_connecting_road_intent",
                "junction_id": junction["junction_id"],
                "movement_id": movement["movement_id"],
                "from_edge": movement.get("from_edge", ""),
                "to_edge": movement.get("to_edge", ""),
                "from_pose_id": from_pose["pose_id"],
                "to_pose_id": to_pose["pose_id"],
                "kind": movement.get("kind", ""),
                "allowed": bool(movement.get("allowed")),
                "confidence": float(movement.get("confidence") or 0.0),
                "geometry_status": "pending_connector_solver",
            }
            movement_intents.append(intent)
            connecting_road_intents.append(intent)

        areas.append({
            "junction_id": junction["junction_id"],
            "node_id": junction["node_id"],
            "type": junction.get("type", ""),
            "degree": int(junction.get("degree") or len(approaches)),
            "center_xz": center,
            "conflict_zone_radius_m": conflict_zone_radius,
            "approach_count": len(approaches),
            "movement_intent_count": len(movement_intents),
            "approaches": approaches,
            "connecting_road_intents": movement_intents,
            "issues": area_issues,
            "status": area_status,
        })

    area_doc = {
        "type": "junction_areas",
        "metadata": {
            "area_id": road_graph.get("metadata", {}).get("area_id", ""),
            "schema": "road_test_pipeline.junction_areas.v1",
            "coord_domain": "local_xz_m",
            "source_road_graph": road_graph.get("metadata", {}).get("source", ""),
            "source_junction_semantics": junction_semantics.get("metadata", {}).get("source", ""),
            "note": "Regularized junction conflict zones and approach entry/exit poses for connector solvers.",
        },
        "junction_areas": areas,
    }
    reference_doc = {
        "type": "engineering_reference_lines",
        "metadata": {
            "area_id": road_graph.get("metadata", {}).get("area_id", ""),
            "schema": "road_test_pipeline.engineering_reference_lines.v1",
            "coord_domain": "local_xz_m",
            "source": "junction_area_regularization",
            "note": "This is a pre-connector model: approach poses and movement intents, not final lane geometry.",
        },
        "approach_entry_poses": reference_poses,
        "connecting_road_intents": connecting_road_intents,
    }
    report = {
        "area_id": road_graph.get("metadata", {}).get("area_id", ""),
        "stage": "junction_area_regularization_v1",
        "status": "warn" if issue_counter else "pass",
        "counts": {
            "junction_areas": len(areas),
            "approach_entry_poses": len(reference_poses),
            "connecting_road_intents": len(connecting_road_intents),
            "status_counts": dict(sorted(status_counter.items())),
            "issue_counts": dict(sorted(issue_counter.items())),
        },
        "notes": [
            "This stage publishes regularized junction areas without changing topology.",
            "Short-edge absorption is currently a candidate flag, not a destructive graph edit.",
            "Connector solvers should use these entry poses before fitting circular, clothoid or paramPoly3 curves.",
        ],
    }
    return area_doc, reference_doc, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Regularize junction areas before connector geometry.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--road-graph", default="")
    parser.add_argument("--junction-semantics", default="")
    parser.add_argument("--junction-areas-output", default="")
    parser.add_argument("--engineering-reference-output", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    processed = root / "data" / "processed"
    reports = root / "reports"
    road_graph_path = Path(args.road_graph) if args.road_graph else processed / f"{args.area_id}_road_graph.json"
    junction_semantics_path = Path(args.junction_semantics) if args.junction_semantics else processed / f"{args.area_id}_junction_semantics.json"
    junction_areas_path = Path(args.junction_areas_output) if args.junction_areas_output else processed / f"{args.area_id}_junction_areas.json"
    engineering_reference_path = Path(args.engineering_reference_output) if args.engineering_reference_output else processed / f"{args.area_id}_engineering_reference_lines.json"
    report_path = Path(args.report) if args.report else reports / f"{args.area_id}_junction_area_regularization_report.json"

    road_graph = read_json(road_graph_path)
    junction_semantics = read_json(junction_semantics_path)
    area_doc, reference_doc, report = regularize_junctions(road_graph, junction_semantics)
    report.update({
        "input_road_graph": str(road_graph_path),
        "input_junction_semantics": str(junction_semantics_path),
        "junction_areas_output": str(junction_areas_path),
        "engineering_reference_output": str(engineering_reference_path),
    })
    write_json(junction_areas_path, area_doc)
    write_json(engineering_reference_path, reference_doc)
    write_json(report_path, report)
    print(json.dumps({
        "area_id": args.area_id,
        "status": report["status"],
        "junction_areas": report["counts"]["junction_areas"],
        "approach_entry_poses": report["counts"]["approach_entry_poses"],
        "connecting_road_intents": report["counts"]["connecting_road_intents"],
        "issue_counts": report["counts"]["issue_counts"],
        "outputs": {
            "junction_areas": str(junction_areas_path),
            "engineering_reference_lines": str(engineering_reference_path),
            "report": str(report_path),
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
