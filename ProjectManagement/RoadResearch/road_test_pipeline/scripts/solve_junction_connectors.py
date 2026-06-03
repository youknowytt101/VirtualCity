#!/usr/bin/env python3
"""Generate and score junction connector geometry candidates.

This is a solver staging layer, not a destructive geometry replacement stage.
It reads the current L6 clean skeleton connectors and regularized entry poses,
then emits candidate curves and scores for the cases that still need a stronger
connector solver.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import optimize_junction_centerlines as oc


SAMPLES = 17
PUBLISH_SCORE_MIN = 72.0
MAX_TANGENT_ERROR_DEG = 10.0
MAX_ENDPOINT_ERROR_M = 0.05
ENDPOINT_TOO_CLOSE_M = 2.0
ENDPOINT_TOO_FAR_M = 30.0


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def to_local(lon: float, lat: float, origin_lon: float, origin_lat: float) -> tuple[float, float]:
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(origin_lat))
    return (float(lon) - origin_lon) * m_per_deg_lon, (float(lat) - origin_lat) * m_per_deg_lat


def round_point(point: tuple[float, float]) -> list[float]:
    return [round(float(point[0]), 3), round(float(point[1]), 3)]


def rounded(value: float) -> float:
    return round(float(value), 3)


def feature_points_xz(feature: dict[str, Any], origin_lon: float, origin_lat: float) -> list[tuple[float, float]]:
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    return [to_local(float(lon), float(lat), origin_lon, origin_lat) for lon, lat in coords]


def pose_index(engineering_reference: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for pose in engineering_reference.get("approach_entry_poses", []):
        edge_id = str(pose.get("edge_id") or "")
        node_id = str(pose.get("node_id") or "")
        entry = pose.get("entry_xz") or []
        tangent = pose.get("tangent_out_xz") or []
        if not edge_id or not node_id or len(entry) < 2 or len(tangent) < 2:
            continue
        indexed[(edge_id, node_id)] = {
            "pose_id": str(pose.get("pose_id") or ""),
            "entry_xz": (float(entry[0]), float(entry[1])),
            "tangent_out_xz": oc.normalize((float(tangent[0]), float(tangent[1]))),
            "entry_trim_m": float(pose.get("entry_trim_m") or 0.0),
            "status": str(pose.get("status") or ""),
            "issues": [str(issue) for issue in pose.get("issues") or []],
        }
    return indexed


def fallback_tangent(points: list[tuple[float, float]], at_end: bool) -> tuple[float, float]:
    if len(points) < 2:
        return 0.0, 0.0
    if at_end:
        return oc.normalize((points[-1][0] - points[-2][0], points[-1][1] - points[-2][1]))
    return oc.normalize((points[1][0] - points[0][0], points[1][1] - points[0][1]))


def expected_tangents(
    props: dict[str, Any],
    points: list[tuple[float, float]],
    poses: dict[tuple[str, str], dict[str, Any]],
) -> tuple[tuple[float, float], tuple[float, float], dict[str, str]]:
    node_id = str(props.get("junction_node_id") or "")
    from_edge = str(props.get("from_edge_id") or "")
    to_edge = str(props.get("to_edge_id") or "")
    from_pose = poses.get((from_edge, node_id))
    to_pose = poses.get((to_edge, node_id))

    if from_pose:
        start_tangent = (-from_pose["tangent_out_xz"][0], -from_pose["tangent_out_xz"][1])
        from_pose_id = from_pose["pose_id"]
    else:
        start_tangent = fallback_tangent(points, at_end=False)
        from_pose_id = ""

    if to_pose:
        end_tangent = to_pose["tangent_out_xz"]
        to_pose_id = to_pose["pose_id"]
    else:
        end_tangent = fallback_tangent(points, at_end=True)
        to_pose_id = ""

    return start_tangent, end_tangent, {
        "from_pose_id": from_pose_id,
        "to_pose_id": to_pose_id,
    }


def cubic_bezier(
    start: tuple[float, float],
    start_tangent: tuple[float, float],
    end: tuple[float, float],
    end_tangent: tuple[float, float],
    handle_start: float,
    handle_end: float,
    samples: int = SAMPLES,
) -> list[tuple[float, float]]:
    c1 = (start[0] + start_tangent[0] * handle_start, start[1] + start_tangent[1] * handle_start)
    c2 = (end[0] - end_tangent[0] * handle_end, end[1] - end_tangent[1] * handle_end)
    points = []
    for i in range(samples):
        t = i / (samples - 1)
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
        points.append((x, z))
    points[0] = start
    points[-1] = end
    return points


def two_segment_g1(
    start: tuple[float, float],
    start_tangent: tuple[float, float],
    end: tuple[float, float],
    end_tangent: tuple[float, float],
    center: tuple[float, float],
    pull: float,
) -> list[tuple[float, float]]:
    chord_mid = ((start[0] + end[0]) * 0.5, (start[1] + end[1]) * 0.5)
    mid = (
        chord_mid[0] * (1.0 - pull) + center[0] * pull,
        chord_mid[1] * (1.0 - pull) + center[1] * pull,
    )
    mid_tangent = oc.normalize((end_tangent[0] + start_tangent[0], end_tangent[1] + start_tangent[1]))
    if mid_tangent == (0.0, 0.0):
        mid_tangent = oc.normalize((end[0] - start[0], end[1] - start[1]))
    if mid_tangent == (0.0, 0.0):
        return [start, end]

    first_len = oc.distance(start, mid)
    second_len = oc.distance(mid, end)
    first = cubic_bezier(start, start_tangent, mid, mid_tangent, first_len * 0.42, first_len * 0.42, 9)
    second = cubic_bezier(mid, mid_tangent, end, end_tangent, second_len * 0.42, second_len * 0.42, 9)
    return first[:-1] + second


def segment_intersection(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    def orient(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> float:
        return oc.cross((q[0] - p[0], q[1] - p[1]), (r[0] - p[0], r[1] - p[1]))

    o1 = orient(a, b, c)
    o2 = orient(a, b, d)
    o3 = orient(c, d, a)
    o4 = orient(c, d, b)
    return o1 * o2 < -1e-9 and o3 * o4 < -1e-9


def has_self_intersection(points: list[tuple[float, float]]) -> bool:
    if len(points) < 4:
        return False
    for i in range(len(points) - 1):
        for j in range(i + 2, len(points) - 1):
            if i == 0 and j == len(points) - 2:
                continue
            if segment_intersection(points[i], points[i + 1], points[j], points[j + 1]):
                return True
    return False


def curvature_reversal_count(points: list[tuple[float, float]]) -> int:
    signs = []
    for i in range(1, len(points) - 1):
        a = points[i - 1]
        b = points[i]
        c = points[i + 1]
        value = oc.cross((b[0] - a[0], b[1] - a[1]), (c[0] - b[0], c[1] - b[1]))
        if abs(value) > 1e-6:
            signs.append(1 if value > 0.0 else -1)
    reversals = 0
    for i in range(1, len(signs)):
        if signs[i] != signs[i - 1]:
            reversals += 1
    return reversals


def tangent_error_deg(actual: tuple[float, float], expected: tuple[float, float]) -> float:
    if actual == (0.0, 0.0) or expected == (0.0, 0.0):
        return 180.0
    return abs(math.degrees(oc.angle_between(actual, expected)))


def candidate_metrics(
    points: list[tuple[float, float]],
    start: tuple[float, float],
    start_tangent: tuple[float, float],
    end: tuple[float, float],
    end_tangent: tuple[float, float],
    center: tuple[float, float],
    design_min_radius: float,
) -> dict[str, Any]:
    start_error = oc.distance(points[0], start) if points else 999.0
    end_error = oc.distance(points[-1], end) if points else 999.0
    start_actual = fallback_tangent(points, at_end=False)
    end_actual = fallback_tangent(points, at_end=True)
    start_tangent_error = tangent_error_deg(start_actual, start_tangent)
    end_tangent_error = tangent_error_deg(end_actual, end_tangent)
    min_radius = oc.polyline_min_radius(points)
    min_center_distance = min((oc.distance(point, center) for point in points), default=0.0)
    max_center_distance = max((oc.distance(point, center) for point in points), default=0.0)
    chord = max(oc.distance(start, end), 0.001)
    length = oc.polyline_length(points)
    margin = min_radius - design_min_radius if design_min_radius > 0.0 and min_radius > 0.0 else 0.0
    return {
        "endpoint_error_m": rounded(start_error + end_error),
        "start_tangent_error_deg": rounded(start_tangent_error),
        "end_tangent_error_deg": rounded(end_tangent_error),
        "max_tangent_error_deg": rounded(max(start_tangent_error, end_tangent_error)),
        "min_radius_m": rounded(min_radius),
        "design_min_radius_m": rounded(design_min_radius),
        "radius_margin_m": rounded(margin),
        "length_m": rounded(length),
        "length_to_chord_ratio": rounded(length / chord),
        "min_center_distance_m": rounded(min_center_distance),
        "max_center_distance_m": rounded(max_center_distance),
        "curvature_reversal_count": curvature_reversal_count(points),
        "self_intersection": has_self_intersection(points),
        "sample_count": len(points),
    }


def score_candidate(metrics: dict[str, Any], connector_kind: str) -> tuple[float, str, list[str]]:
    issues: list[str] = []
    score = 100.0
    design_min = float(metrics["design_min_radius_m"])
    min_radius = float(metrics["min_radius_m"])
    endpoint_error = float(metrics["endpoint_error_m"])
    tangent_error = float(metrics["max_tangent_error_deg"])

    if endpoint_error > MAX_ENDPOINT_ERROR_M:
        issues.append("endpoint_error")
        score -= min(45.0, endpoint_error * 30.0)
    if tangent_error > MAX_TANGENT_ERROR_DEG:
        issues.append("tangent_error")
        score -= min(40.0, (tangent_error - MAX_TANGENT_ERROR_DEG) * 1.5)
    if connector_kind not in {"t_through", "through"} and design_min > 0.0:
        if min_radius <= 0.0:
            issues.append("unknown_radius")
            score -= 45.0
        elif min_radius + 1e-6 < design_min:
            issues.append("radius_below_design_min")
            score -= min(65.0, (design_min - min_radius) / design_min * 70.0)
    if float(metrics["min_center_distance_m"]) < ENDPOINT_TOO_CLOSE_M:
        issues.append("center_intrusion")
        score -= 18.0
    if float(metrics["max_center_distance_m"]) > ENDPOINT_TOO_FAR_M:
        issues.append("outside_junction_area")
        score -= 12.0
    if int(metrics["curvature_reversal_count"]) > 0:
        issues.append("curvature_reversal")
        score -= min(24.0, int(metrics["curvature_reversal_count"]) * 8.0)
    if bool(metrics["self_intersection"]):
        issues.append("self_intersection")
        score -= 100.0
    if float(metrics["length_to_chord_ratio"]) > 2.2:
        issues.append("excessive_length")
        score -= 15.0

    score = max(0.0, min(100.0, score))
    status = "publishable_candidate" if score >= PUBLISH_SCORE_MIN and not issues else "needs_work"
    return rounded(score), status, issues


def make_candidate(
    candidate_id: str,
    family: str,
    points: list[tuple[float, float]],
    start: tuple[float, float],
    start_tangent: tuple[float, float],
    end: tuple[float, float],
    end_tangent: tuple[float, float],
    center: tuple[float, float],
    design_min_radius: float,
    connector_kind: str,
    note: str,
) -> dict[str, Any]:
    metrics = candidate_metrics(points, start, start_tangent, end, end_tangent, center, design_min_radius)
    score, status, issues = score_candidate(metrics, connector_kind)
    return {
        "candidate_id": candidate_id,
        "family": family,
        "status": status,
        "score": score,
        "issues": issues,
        "metrics": metrics,
        "note": note,
        "points_xz": [round_point(point) for point in points],
    }


def trim_candidate_points(candidates: list[dict[str, Any]], keep_ids: set[str]) -> None:
    for candidate in candidates:
        if candidate["candidate_id"] in keep_ids:
            candidate["points_retained"] = True
            continue
        candidate.pop("points_xz", None)
        candidate["points_retained"] = False
        candidate["points_note"] = "Omitted from artifact; metrics retained. Re-run solver to regenerate samples."


def candidate_set_for_connector(
    feature: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    poses: dict[tuple[str, str], dict[str, Any]],
    origin_lon: float,
    origin_lat: float,
) -> dict[str, Any] | None:
    props = feature.get("properties") or {}
    if props.get("vc_part") != "optimized_junction_connector":
        return None
    node_id = str(props.get("junction_node_id") or "")
    node = nodes.get(node_id)
    current_points = feature_points_xz(feature, origin_lon, origin_lat)
    if node is None or len(current_points) < 2:
        return None

    center = (float(node["x"]), float(node["z"]))
    start = current_points[0]
    end = current_points[-1]
    connector_id = str(props.get("connector_id") or "")
    connector_kind = str(props.get("connector_kind") or "unknown")
    design_min = float(props.get("arc_design_min_radius_m") or 0.0)
    start_tangent, end_tangent, pose_refs = expected_tangents(props, current_points, poses)

    current_issues = []
    if str(props.get("arc_geometry") or "") == "bezier_tangent_fallback":
        current_issues.append("current_bezier_tangent_fallback")
    if "incompatible" in str(props.get("arc_fit_status") or ""):
        current_issues.append("single_arc_incompatible")
    if design_min > 0.0 and float(props.get("arc_radius_margin_m") or 0.0) < 0.0:
        current_issues.append("radius_below_design_min")

    candidates = [
        make_candidate(
            f"{connector_id}_current",
            "current_geometry",
            current_points,
            start,
            start_tangent,
            end,
            end_tangent,
            center,
            design_min,
            connector_kind,
            "Existing L6 connector geometry.",
        )
    ]

    circular = oc.circular_arc_from_tangents(start, start_tangent, end, end_tangent, SAMPLES)
    candidates.append(make_candidate(
        f"{connector_id}_circular",
        "circular_arc_exact",
        circular["points"],
        start,
        start_tangent,
        end,
        end_tangent,
        center,
        design_min,
        connector_kind,
        str(circular["fit_status"]),
    ))

    chord = oc.distance(start, end)
    for factor in (0.28, 0.42, 0.62, 0.86, 1.15):
        candidates.append(make_candidate(
            f"{connector_id}_parampoly3_{factor:.2f}",
            "param_poly3_hermite",
            cubic_bezier(start, start_tangent, end, end_tangent, chord * factor, chord * factor),
            start,
            start_tangent,
            end,
            end_tangent,
            center,
            design_min,
            connector_kind,
            f"Hermite cubic candidate with handle factor {factor:.2f}.",
        ))

    for pull in (0.0, 0.25, 0.45):
        candidates.append(make_candidate(
            f"{connector_id}_biarc_proxy_{pull:.2f}",
            "biarc_g1_proxy",
            two_segment_g1(start, start_tangent, end, end_tangent, center, pull),
            start,
            start_tangent,
            end,
            end_tangent,
            center,
            design_min,
            connector_kind,
            f"Two-segment G1 proxy; use as a future clothoid/biarc fitting target, pull={pull:.2f}.",
        ))

    candidates.sort(key=lambda item: (float(item["score"]), float(item["metrics"]["radius_margin_m"])), reverse=True)
    best = candidates[0]
    current_candidate = next(candidate for candidate in candidates if candidate["family"] == "current_geometry")
    replacement_candidates = [candidate for candidate in candidates if candidate["family"] != "current_geometry"]
    best_replacement = replacement_candidates[0] if replacement_candidates else None
    accepted_transaction = str(props.get("connector_replacement_transaction") or "") == "accepted_trial"
    needs_solver = bool(current_issues) or current_candidate["status"] != "publishable_candidate"
    if accepted_transaction and not current_issues:
        needs_solver = False
    replacement_ready = bool(
        needs_solver
        and best_replacement is not None
        and best_replacement["status"] == "publishable_candidate"
    )
    keep_candidate_points = {
        current_candidate["candidate_id"],
        best["candidate_id"],
        *(candidate["candidate_id"] for candidate in candidates[:3]),
    }
    if best_replacement is not None:
        keep_candidate_points.add(best_replacement["candidate_id"])
    trim_candidate_points(candidates, keep_candidate_points)
    return {
        "connector_id": connector_id,
        "junction_node_id": node_id,
        "connector_kind": connector_kind,
        "from_edge_id": str(props.get("from_edge_id") or ""),
        "to_edge_id": str(props.get("to_edge_id") or ""),
        "current_arc_geometry": str(props.get("arc_geometry") or ""),
        "current_arc_fit_status": str(props.get("arc_fit_status") or ""),
        "current_arc_radius_m": float(props.get("arc_radius_m") or 0.0),
        "current_design_min_radius_m": design_min,
        "current_radius_margin_m": float(props.get("arc_radius_margin_m") or 0.0),
        "current_issues": current_issues,
        "pose_refs": pose_refs,
        "start_xz": round_point(start),
        "end_xz": round_point(end),
        "current_candidate_status": current_candidate["status"],
        "current_candidate_score": current_candidate["score"],
        "current_candidate_issues": sorted(set(current_issues + current_candidate["issues"])),
        "best_candidate_id": best["candidate_id"],
        "best_family": best["family"],
        "best_status": best["status"],
        "best_score": best["score"],
        "best_issues": best["issues"],
        "best_metrics": best["metrics"],
        "best_replacement_candidate_id": best_replacement["candidate_id"] if best_replacement else "",
        "best_replacement_family": best_replacement["family"] if best_replacement else "",
        "best_replacement_status": best_replacement["status"] if best_replacement else "",
        "best_replacement_score": best_replacement["score"] if best_replacement else 0.0,
        "best_replacement_issues": best_replacement["issues"] if best_replacement else [],
        "best_replacement_metrics": best_replacement["metrics"] if best_replacement else {},
        "needs_solver": needs_solver,
        "replacement_ready": replacement_ready,
        "candidates": candidates,
    }


def solve_connectors(
    *,
    area_id: str,
    road_graph_path: Path,
    optimized_path: Path,
    engineering_reference_path: Path,
    candidates_output_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    road_graph = read_json(road_graph_path)
    optimized = read_json(optimized_path)
    engineering_reference = read_json(engineering_reference_path)
    meta = optimized.get("metadata") or road_graph.get("metadata") or {}
    origin_lon = float(meta["origin_lon"])
    origin_lat = float(meta["origin_lat"])
    nodes = {str(node["node_id"]): node for node in road_graph.get("nodes", [])}
    poses = pose_index(engineering_reference)

    cases = []
    for feature in optimized.get("features", []):
        case = candidate_set_for_connector(feature, nodes, poses, origin_lon, origin_lat)
        if case is not None:
            cases.append(case)

    solver_cases = [case for case in cases if case["needs_solver"]]
    unresolved_solver_cases = [case for case in solver_cases if not case["replacement_ready"]]
    candidate_family_counts = Counter()
    best_family_counts = Counter()
    best_replacement_family_counts = Counter()
    best_status_counts = Counter()
    best_replacement_status_counts = Counter()
    current_issue_counts = Counter()
    current_scored_issue_counts = Counter()
    best_issue_counts = Counter()
    best_replacement_issue_counts = Counter()
    replacement_ready = 0
    publishable_best = 0
    publishable_replacements = 0

    for case in cases:
        best_family_counts[case["best_family"]] += 1
        best_replacement_family_counts[case["best_replacement_family"]] += 1
        best_status_counts[case["best_status"]] += 1
        best_replacement_status_counts[case["best_replacement_status"]] += 1
        for issue in case["current_issues"]:
            current_issue_counts[issue] += 1
        for issue in case["current_candidate_issues"]:
            current_scored_issue_counts[issue] += 1
        for issue in case["best_issues"]:
            best_issue_counts[issue] += 1
        for issue in case["best_replacement_issues"]:
            best_replacement_issue_counts[issue] += 1
        if case["replacement_ready"]:
            replacement_ready += 1
        if case["best_status"] == "publishable_candidate":
            publishable_best += 1
        if case["best_replacement_status"] == "publishable_candidate":
            publishable_replacements += 1
        for candidate in case["candidates"]:
            candidate_family_counts[candidate["family"]] += 1

    candidate_doc = {
        "type": "junction_connector_candidates",
        "metadata": {
            "area_id": area_id,
            "schema": "road_test_pipeline.junction_connector_candidates.v1",
            "coord_domain": "local_xz_m",
            "source_road_graph": str(road_graph_path),
            "source_optimized_centerlines": str(optimized_path),
            "source_engineering_reference": str(engineering_reference_path),
            "note": "Candidate curves and scores only; this stage does not replace clean skeleton geometry.",
        },
        "cases": cases,
    }
    write_json(candidates_output_path, candidate_doc)

    worst_cases = sorted(
        unresolved_solver_cases,
        key=lambda item: (
            item["replacement_ready"],
            float(item["best_replacement_score"]),
            float(item["best_replacement_metrics"].get("radius_margin_m") or 0.0),
        ),
    )[:30]
    report = {
        "area_id": area_id,
        "stage": "junction_connector_solver_v2_candidates",
        "status": "warn" if unresolved_solver_cases else "pass",
        "inputs": {
            "road_graph": str(road_graph_path),
            "optimized_centerlines": str(optimized_path),
            "engineering_reference": str(engineering_reference_path),
        },
        "outputs": {
            "candidates": str(candidates_output_path),
            "report": str(report_path),
        },
        "counts": {
            "connectors": len(cases),
            "solver_cases": len(solver_cases),
            "unresolved_solver_cases": len(unresolved_solver_cases),
            "publishable_best_candidates": publishable_best,
            "publishable_replacement_candidates": publishable_replacements,
            "replacement_ready_candidates": replacement_ready,
            "candidate_family_counts": dict(sorted(candidate_family_counts.items())),
            "best_family_counts": dict(sorted(best_family_counts.items())),
            "best_replacement_family_counts": dict(sorted(best_replacement_family_counts.items())),
            "best_status_counts": dict(sorted(best_status_counts.items())),
            "best_replacement_status_counts": dict(sorted(best_replacement_status_counts.items())),
            "current_issue_counts": dict(sorted(current_issue_counts.items())),
            "current_scored_issue_counts": dict(sorted(current_scored_issue_counts.items())),
            "best_issue_counts": dict(sorted(best_issue_counts.items())),
            "best_replacement_issue_counts": dict(sorted(best_replacement_issue_counts.items())),
        },
        "thresholds": {
            "publish_score_min": PUBLISH_SCORE_MIN,
            "max_tangent_error_deg": MAX_TANGENT_ERROR_DEG,
            "max_endpoint_error_m": MAX_ENDPOINT_ERROR_M,
        },
        "worst_cases": [
            {
                "connector_id": case["connector_id"],
                "junction_node_id": case["junction_node_id"],
                "connector_kind": case["connector_kind"],
                "from_edge_id": case["from_edge_id"],
                "to_edge_id": case["to_edge_id"],
                "current_candidate_score": case["current_candidate_score"],
                "current_candidate_issues": case["current_candidate_issues"],
                "best_family": case["best_family"],
                "best_status": case["best_status"],
                "best_score": case["best_score"],
                "best_issues": case["best_issues"],
                "best_metrics": case["best_metrics"],
                "best_replacement_family": case["best_replacement_family"],
                "best_replacement_status": case["best_replacement_status"],
                "best_replacement_score": case["best_replacement_score"],
                "best_replacement_issues": case["best_replacement_issues"],
                "best_replacement_metrics": case["best_replacement_metrics"],
                "replacement_ready": case["replacement_ready"],
            }
            for case in worst_cases
        ],
        "next_action": (
            "Use publishable replacement candidates only after a separate replacement pass and QA. "
            "Cases still failing radius or trim spread need short-edge absorption or a real clothoid/paramPoly3 fit."
        ),
    }
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate scored junction connector candidate curves.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--road-graph", default="")
    parser.add_argument("--optimized-centerlines", default="")
    parser.add_argument("--engineering-reference", default="")
    parser.add_argument("--candidates-output", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    processed = root / "data" / "processed"
    reports = root / "reports"
    road_graph_path = Path(args.road_graph) if args.road_graph else processed / f"{args.area_id}_road_graph.json"
    optimized_path = Path(args.optimized_centerlines) if args.optimized_centerlines else processed / f"{args.area_id}_roads_optimized_centerlines.geojson"
    engineering_reference_path = (
        Path(args.engineering_reference)
        if args.engineering_reference
        else processed / f"{args.area_id}_engineering_reference_lines.json"
    )
    candidates_output_path = (
        Path(args.candidates_output)
        if args.candidates_output
        else processed / f"{args.area_id}_junction_connector_candidates.json"
    )
    report_path = Path(args.report) if args.report else reports / f"{args.area_id}_junction_connector_solver_report.json"

    report = solve_connectors(
        area_id=args.area_id,
        road_graph_path=road_graph_path,
        optimized_path=optimized_path,
        engineering_reference_path=engineering_reference_path,
        candidates_output_path=candidates_output_path,
        report_path=report_path,
    )
    print(json.dumps({
        "area_id": args.area_id,
        "status": report["status"],
        "counts": report["counts"],
        "outputs": report["outputs"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
