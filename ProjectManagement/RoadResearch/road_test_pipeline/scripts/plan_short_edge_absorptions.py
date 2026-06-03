#!/usr/bin/env python3
"""Plan junction-zone expansion candidates from short-edge absorption flags.

This stage is intentionally non-destructive. It treats short-edge absorption as
a subset of junction-zone expansion and emits auditable transaction candidates
that a later graph/geometry rewrite pass can apply.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


MAX_CHAIN_EDGES = 4
MAX_CHAIN_ANGLE_DEG = 25.0
LOW_RISK_ANGLE_DEG = 5.0
MIN_TRIM_RECOVERY_M = 0.5
PATH_END_RESERVE_M = 0.5


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_optional_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return read_json(path)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def rounded(value: float) -> float:
    return round(float(value), 3)


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = a[0] - b[0]
    dz = a[1] - b[1]
    return math.sqrt(dx * dx + dz * dz)


def normalize(v: tuple[float, float]) -> tuple[float, float]:
    length = math.sqrt(v[0] * v[0] + v[1] * v[1])
    if length <= 1e-9:
        return 0.0, 0.0
    return v[0] / length, v[1] / length


def angle_between_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    if a == (0.0, 0.0) or b == (0.0, 0.0):
        return 180.0
    dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1]))
    return math.degrees(math.acos(dot))


def edge_points_from_node(edge: dict[str, Any], node_id: str) -> list[tuple[float, float]]:
    points = [(float(p[0]), float(p[1])) for p in edge.get("geometry_xz") or []]
    if edge.get("from_node") == node_id:
        return points
    return list(reversed(points))


def other_node_id(edge: dict[str, Any], node_id: str) -> str:
    if str(edge.get("from_node")) == node_id:
        return str(edge.get("to_node") or "")
    if str(edge.get("to_node")) == node_id:
        return str(edge.get("from_node") or "")
    return ""


def direction_from_node(edge: dict[str, Any], node_id: str) -> tuple[float, float]:
    points = edge_points_from_node(edge, node_id)
    if len(points) < 2:
        return 0.0, 0.0
    return normalize((points[1][0] - points[0][0], points[1][1] - points[0][1]))


def concat_path_points(
    path_edges: list[dict[str, Any]],
    start_node_id: str,
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    current_node_id = start_node_id
    for edge in path_edges:
        edge_points = edge_points_from_node(edge, current_node_id)
        if not edge_points:
            break
        if points and distance(points[-1], edge_points[0]) <= 0.001:
            points.extend(edge_points[1:])
        else:
            points.extend(edge_points)
        current_node_id = other_node_id(edge, current_node_id)
        if not current_node_id:
            break
    return points


def point_along(points: list[tuple[float, float]], amount: float) -> tuple[float, float]:
    if not points:
        return 0.0, 0.0
    if len(points) == 1 or amount <= 0.0:
        return points[0]
    remaining = amount
    for index in range(len(points) - 1):
        a = points[index]
        b = points[index + 1]
        seg_len = distance(a, b)
        if seg_len <= 1e-9:
            continue
        if remaining <= seg_len:
            t = remaining / seg_len
            return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        remaining -= seg_len
    return points[-1]


def tangent_at_distance(points: list[tuple[float, float]], amount: float) -> tuple[float, float]:
    if len(points) < 2:
        return 0.0, 0.0
    remaining = max(0.0, amount)
    for index in range(len(points) - 1):
        a = points[index]
        b = points[index + 1]
        seg_len = distance(a, b)
        if seg_len <= 1e-9:
            continue
        if remaining <= seg_len:
            return normalize((b[0] - a[0], b[1] - a[1]))
        remaining -= seg_len
    return normalize((points[-1][0] - points[-2][0], points[-1][1] - points[-2][1]))


def connector_case_index(candidate_doc: dict[str, Any]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    indexed: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for case in candidate_doc.get("cases", []):
        junction_node_id = str(case.get("junction_node_id") or "")
        for edge_key in ("from_edge_id", "to_edge_id"):
            edge_id = str(case.get(edge_key) or "")
            if junction_node_id and edge_id:
                indexed[(junction_node_id, edge_id)].append(case)
    return indexed


def build_absorption_path(
    *,
    start_node_id: str,
    short_edge_id: str,
    desired_trim_m: float,
    edges: dict[str, dict[str, Any]],
    nodes: dict[str, dict[str, Any]],
) -> tuple[list[str], str, list[str], float]:
    issues: list[str] = []
    path_edge_ids: list[str] = []
    current_edge_id = short_edge_id
    current_node_id = start_node_id
    previous_direction: tuple[float, float] | None = None
    max_angle = 0.0

    for _ in range(MAX_CHAIN_EDGES):
        edge = edges.get(current_edge_id)
        if edge is None:
            issues.append("missing_path_edge")
            break
        if current_edge_id in path_edge_ids:
            issues.append("cycle_in_absorption_path")
            break
        if current_node_id not in {str(edge.get("from_node")), str(edge.get("to_node"))}:
            issues.append("path_edge_not_incident_to_current_node")
            break

        direction = direction_from_node(edge, current_node_id)
        if previous_direction is not None:
            turn = angle_between_deg(previous_direction, direction)
            max_angle = max(max_angle, turn)
            if turn > MAX_CHAIN_ANGLE_DEG:
                issues.append("chain_angle_too_large")
                break
        path_edge_ids.append(current_edge_id)
        previous_direction = direction

        accumulated = sum(float(edges[edge_id].get("length_m") or 0.0) for edge_id in path_edge_ids)
        next_node_id = other_node_id(edge, current_node_id)
        next_node = nodes.get(next_node_id, {})
        if accumulated >= desired_trim_m + PATH_END_RESERVE_M:
            return path_edge_ids, next_node_id, issues, max_angle
        if str(next_node.get("kind") or "") != "connector" or int(next_node.get("degree") or 0) != 2:
            return path_edge_ids, next_node_id, issues, max_angle

        incident = [str(edge_id) for edge_id in next_node.get("incident_edges", []) if str(edge_id) != current_edge_id]
        if len(incident) != 1:
            issues.append("connector_node_not_simple_chain")
            return path_edge_ids, next_node_id, issues, max_angle
        current_node_id = next_node_id
        current_edge_id = incident[0]

    if len(path_edge_ids) >= MAX_CHAIN_EDGES:
        issues.append("max_chain_edges_reached")
    final_node_id = current_node_id
    if path_edge_ids:
        final_node_id = other_node_id(edges[path_edge_ids[-1]], current_node_id)
    return path_edge_ids, final_node_id, issues, max_angle


def classify_candidate(
    *,
    blockers: list[str],
    trim_recovery_m: float,
    remaining_deficit_m: float,
    max_chain_angle_deg: float,
    affected_unresolved_connectors: int,
) -> tuple[str, str, list[str]]:
    issues: list[str] = []
    if trim_recovery_m < MIN_TRIM_RECOVERY_M:
        issues.append("low_trim_recovery")
    if affected_unresolved_connectors <= 0:
        issues.append("no_unresolved_connector_dependency")
    if remaining_deficit_m > 0.25:
        issues.append("remaining_trim_deficit")

    if blockers:
        return "blocked", "high", sorted(set(blockers + issues))
    if issues:
        risk = "medium" if max_chain_angle_deg <= MAX_CHAIN_ANGLE_DEG else "high"
        return "qa_candidate", risk, sorted(set(issues))
    risk = "low" if max_chain_angle_deg <= LOW_RISK_ANGLE_DEG else "medium"
    return "transaction_ready", risk, []


def plan_absorptions(
    *,
    area_id: str,
    road_graph: dict[str, Any],
    junction_areas: dict[str, Any],
    connector_candidates: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    nodes = {str(node["node_id"]): node for node in road_graph.get("nodes", [])}
    edges = {str(edge["edge_id"]): edge for edge in road_graph.get("edges", [])}
    connector_cases = connector_case_index(connector_candidates or {})

    candidates: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    issue_counts: Counter[str] = Counter()
    risk_counts: Counter[str] = Counter()
    affected_connector_ids: set[str] = set()
    affected_unresolved_connector_ids: set[str] = set()

    for area in junction_areas.get("junction_areas", []):
        junction_node_id = str(area.get("node_id") or "")
        center_raw = area.get("center_xz") or [0.0, 0.0]
        center = (float(center_raw[0]), float(center_raw[1]))
        for approach in area.get("approaches", []):
            absorption = approach.get("short_edge_absorption") or {}
            if not absorption.get("candidate"):
                continue

            short_edge_id = str(approach.get("edge_id") or "")
            connector_node_id = str(absorption.get("other_node_id") or "")
            desired_trim = float(approach.get("desired_trim_m") or 0.0)
            current_trim = float(approach.get("entry_trim_m") or 0.0)
            blockers: list[str] = []

            short_edge = edges.get(short_edge_id)
            connector_node = nodes.get(connector_node_id)
            if short_edge is None:
                blockers.append("missing_short_edge")
            if not junction_node_id or junction_node_id not in nodes:
                blockers.append("missing_junction_node")
            if connector_node is None:
                blockers.append("missing_connector_node")
            elif str(connector_node.get("kind") or "") != "connector" or int(connector_node.get("degree") or 0) != 2:
                blockers.append("other_node_not_degree2_connector")
            if short_edge is not None and connector_node_id:
                actual_other = other_node_id(short_edge, junction_node_id)
                if actual_other != connector_node_id:
                    blockers.append("short_edge_not_between_junction_and_connector")

            path_edge_ids: list[str] = []
            terminal_node_id = connector_node_id
            path_issues: list[str] = []
            max_chain_angle = 0.0
            if not blockers:
                path_edge_ids, terminal_node_id, path_issues, max_chain_angle = build_absorption_path(
                    start_node_id=junction_node_id,
                    short_edge_id=short_edge_id,
                    desired_trim_m=desired_trim,
                    edges=edges,
                    nodes=nodes,
                )
                blockers.extend(path_issues)

            path_edges = [edges[edge_id] for edge_id in path_edge_ids if edge_id in edges]
            path_points = concat_path_points(path_edges, junction_node_id) if path_edges else []
            path_length = sum(float(edge.get("length_m") or 0.0) for edge in path_edges)
            available_after = max(0.0, path_length - PATH_END_RESERVE_M)
            planned_trim = min(desired_trim, available_after) if desired_trim > 0.0 else current_trim
            planned_entry = point_along(path_points, planned_trim) if path_points else tuple(approach.get("entry_xz") or center)
            planned_tangent = tangent_at_distance(path_points, planned_trim) if path_points else (0.0, 0.0)
            trim_recovery = max(0.0, planned_trim - current_trim)
            remaining_deficit = max(0.0, desired_trim - planned_trim)

            affected_cases = connector_cases.get((junction_node_id, short_edge_id), [])
            unresolved_cases = [
                case for case in affected_cases
                if bool(case.get("needs_solver")) and not bool(case.get("replacement_ready"))
            ]
            for case in affected_cases:
                connector_id = str(case.get("connector_id") or "")
                if connector_id:
                    affected_connector_ids.add(connector_id)
            for case in unresolved_cases:
                connector_id = str(case.get("connector_id") or "")
                if connector_id:
                    affected_unresolved_connector_ids.add(connector_id)

            status, risk, candidate_issues = classify_candidate(
                blockers=blockers,
                trim_recovery_m=trim_recovery,
                remaining_deficit_m=remaining_deficit,
                max_chain_angle_deg=max_chain_angle,
                affected_unresolved_connectors=len(unresolved_cases),
            )
            status_counts[status] += 1
            risk_counts[risk] += 1
            issue_counts.update(candidate_issues)

            successor_edge_ids = path_edge_ids[1:]
            candidate = {
                "candidate_id": f"{junction_node_id}_{short_edge_id}_short_edge_absorption",
                "status": status,
                "risk": risk,
                "issues": candidate_issues,
                "junction_id": str(area.get("junction_id") or ""),
                "junction_node_id": junction_node_id,
                "short_edge_id": short_edge_id,
                "absorbed_connector_node_id": connector_node_id,
                "terminal_node_id": terminal_node_id,
                "terminal_node_kind": str((nodes.get(terminal_node_id) or {}).get("kind") or ""),
                "path_edge_ids": path_edge_ids,
                "successor_edge_ids": successor_edge_ids,
                "affected_connector_ids": sorted({str(case.get("connector_id") or "") for case in affected_cases if case.get("connector_id")}),
                "affected_unresolved_connector_ids": sorted({
                    str(case.get("connector_id") or "") for case in unresolved_cases if case.get("connector_id")
                }),
                "current_entry_pose": {
                    "pose_id": str(approach.get("pose_id") or ""),
                    "entry_trim_m": rounded(current_trim),
                    "entry_xz": [rounded(v) for v in (approach.get("entry_xz") or [0.0, 0.0])[:2]],
                    "center_distance_m": rounded(float(approach.get("center_distance_m") or 0.0)),
                    "issues": [str(issue) for issue in approach.get("issues") or []],
                },
                "planned_entry_pose": {
                    "entry_trim_m": rounded(planned_trim),
                    "entry_xz": [rounded(planned_entry[0]), rounded(planned_entry[1])],
                    "center_distance_m": rounded(distance(center, planned_entry)),
                    "tangent_out_xz": [round(planned_tangent[0], 6), round(planned_tangent[1], 6)],
                },
                "metrics": {
                    "desired_trim_m": rounded(desired_trim),
                    "current_trim_m": rounded(current_trim),
                    "available_after_absorption_m": rounded(available_after),
                    "planned_trim_m": rounded(planned_trim),
                    "trim_recovery_m": rounded(trim_recovery),
                    "remaining_trim_deficit_m": rounded(remaining_deficit),
                    "path_length_m": rounded(path_length),
                    "path_edge_count": len(path_edge_ids),
                    "max_chain_angle_deg": rounded(max_chain_angle),
                    "affected_connectors": len(affected_cases),
                    "affected_unresolved_connectors": len(unresolved_cases),
                },
                "note": (
                    "Candidate only. A later transaction should rewrite the junction approach/entry pose "
                    "and re-run optimize centerlines, connector solver, replacement, and junction geometry audit."
                ),
            }
            candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            item["status"] != "transaction_ready",
            -float(item["metrics"]["affected_unresolved_connectors"]),
            -float(item["metrics"]["trim_recovery_m"]),
            float(item["metrics"]["max_chain_angle_deg"]),
        )
    )

    candidate_doc = {
        "type": "short_edge_absorption_candidates",
        "metadata": {
            "area_id": area_id,
            "schema": "road_test_pipeline.short_edge_absorption_candidates.v1",
            "planning_domain": "junction-zone expansion（路口影响区扩张）",
            "coord_domain": "local_xz_m",
            "source_road_graph": road_graph.get("metadata", {}).get("source", ""),
            "source_junction_areas": junction_areas.get("metadata", {}).get("source_junction_semantics", ""),
            "note": (
                "Planner output only. short-edge absorption（短边吸收） is treated as a "
                "junction-zone expansion（路口影响区扩张） candidate; no graph, centerline, or Houdini geometry is modified here."
            ),
        },
        "candidates": candidates,
    }
    report = {
        "area_id": area_id,
        "stage": "junction_zone_expansion_planner_v1",
        "status": "warn" if status_counts.get("transaction_ready", 0) else "blocked" if candidates else "pass",
        "counts": {
            "short_edge_absorption_flags": len(candidates),
            "status_counts": dict(sorted(status_counts.items())),
            "risk_counts": dict(sorted(risk_counts.items())),
            "issue_counts": dict(sorted(issue_counts.items())),
            "affected_connectors": len(affected_connector_ids),
            "affected_unresolved_connectors": len(affected_unresolved_connector_ids),
            "total_trim_recovery_m": rounded(sum(float(item["metrics"]["trim_recovery_m"]) for item in candidates)),
            "max_trim_recovery_m": rounded(max((float(item["metrics"]["trim_recovery_m"]) for item in candidates), default=0.0)),
        },
        "thresholds": {
            "max_chain_edges": MAX_CHAIN_EDGES,
            "max_chain_angle_deg": MAX_CHAIN_ANGLE_DEG,
            "low_risk_angle_deg": LOW_RISK_ANGLE_DEG,
            "min_trim_recovery_m": MIN_TRIM_RECOVERY_M,
            "path_end_reserve_m": PATH_END_RESERVE_M,
        },
        "top_candidates": candidates[:30],
        "next_action": (
            "Build the destructive junction-zone expansion transaction from transaction_ready candidates only. "
            "The transaction must regenerate engineering reference lines / optimized centerlines and pass "
            "junction_geometry_audit without protected issue regression."
        ),
    }
    return candidate_doc, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan short-edge absorption transactions.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--road-graph", default="")
    parser.add_argument("--junction-areas", default="")
    parser.add_argument("--connector-candidates", default="")
    parser.add_argument("--candidates-output", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    processed = root / "data" / "processed"
    reports = root / "reports"
    road_graph_path = Path(args.road_graph) if args.road_graph else processed / f"{args.area_id}_road_graph.json"
    junction_areas_path = Path(args.junction_areas) if args.junction_areas else processed / f"{args.area_id}_junction_areas.json"
    connector_candidates_path = (
        Path(args.connector_candidates)
        if args.connector_candidates
        else processed / f"{args.area_id}_junction_connector_candidates.json"
    )
    candidates_output_path = (
        Path(args.candidates_output)
        if args.candidates_output
        else processed / f"{args.area_id}_short_edge_absorption_candidates.json"
    )
    report_path = Path(args.report) if args.report else reports / f"{args.area_id}_short_edge_absorption_report.json"

    candidate_doc, report = plan_absorptions(
        area_id=args.area_id,
        road_graph=read_json(road_graph_path),
        junction_areas=read_json(junction_areas_path),
        connector_candidates=read_optional_json(connector_candidates_path),
    )
    candidate_doc["metadata"].update({
        "source_road_graph": str(road_graph_path),
        "source_junction_areas": str(junction_areas_path),
        "source_connector_candidates": str(connector_candidates_path) if connector_candidates_path.exists() else "",
    })
    report["inputs"] = {
        "road_graph": str(road_graph_path),
        "junction_areas": str(junction_areas_path),
        "connector_candidates": str(connector_candidates_path) if connector_candidates_path.exists() else "",
    }
    report["outputs"] = {
        "candidates": str(candidates_output_path),
        "report": str(report_path),
    }
    write_json(candidates_output_path, candidate_doc)
    write_json(report_path, report)
    print(json.dumps({
        "area_id": args.area_id,
        "status": report["status"],
        "counts": report["counts"],
        "outputs": report["outputs"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
