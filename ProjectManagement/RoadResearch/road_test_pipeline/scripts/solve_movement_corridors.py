#!/usr/bin/env python3
"""Generate lane-level movement corridor candidates from lane_graph.json.

This is a non-destructive staging solver. It emits candidate corridors for
lane-level junction reconstruction, but it does not replace clean skeleton
geometry and does not publish final lane surfaces.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


SAMPLES = 17
MIN_CORRIDOR_LENGTH_M = 0.5
MAX_CORRIDOR_LENGTH_M = 60.0
LOW_CONFIDENCE_THRESHOLD = 0.5
READY_CONFIDENCE_THRESHOLD = 0.55
ANCHOR_CONFIDENCE_CAP = 0.72
FALLBACK_ANCHOR_CONFIDENCE_CAP = 0.35
PLANNED_ANCHOR_SOURCE = "junction_zone_expansion_planned_pose_lateral_offset"
ENGINEERING_ANCHOR_SOURCE = "engineering_entry_pose_lateral_offset"
LANE_LEVEL_ANCHOR_SOURCES = {ENGINEERING_ANCHOR_SOURCE, PLANNED_ANCHOR_SOURCE}
PLANNED_ANCHOR_MIN_RECOVERY_M = 0.25


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def cross(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[1] - a[1] * b[0]


def dot(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1]


def angle_between_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    a = normalize(a)
    b = normalize(b)
    if a == (0.0, 0.0) or b == (0.0, 0.0):
        return 180.0
    return math.degrees(math.acos(max(-1.0, min(1.0, dot(a, b)))))


def polyline_length(points: list[tuple[float, float]]) -> float:
    return sum(distance(points[index], points[index + 1]) for index in range(len(points) - 1))


def round_point(point: tuple[float, float]) -> list[float]:
    return [rounded(point[0]), rounded(point[1])]


def left_normal(tangent: tuple[float, float]) -> tuple[float, float]:
    tangent = normalize(tangent)
    return -tangent[1], tangent[0]


def lane_points(lane: dict[str, Any]) -> list[tuple[float, float]]:
    return [
        (float(point[0]), float(point[1]))
        for point in lane.get("centerline_xz") or []
        if len(point) >= 2
    ]


def endpoint_and_tangent(lane: dict[str, Any], side: str) -> tuple[tuple[float, float], tuple[float, float], list[str]]:
    points = lane_points(lane)
    issues: list[str] = []
    if not points:
        return (0.0, 0.0), (0.0, 0.0), ["missing_lane_centerline"]
    if len(points) == 1:
        return points[0], (0.0, 0.0), ["single_point_lane_centerline"]
    if side == "end":
        tangent = normalize((points[-1][0] - points[-2][0], points[-1][1] - points[-2][1]))
        return points[-1], tangent, issues
    tangent = normalize((points[1][0] - points[0][0], points[1][1] - points[0][1]))
    return points[0], tangent, issues


def pose_index(engineering_reference: dict[str, Any] | None) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    if not engineering_reference:
        return indexed
    for pose in engineering_reference.get("approach_entry_poses", []):
        edge_id = str(pose.get("edge_id") or "")
        node_id = str(pose.get("node_id") or "")
        entry = pose.get("entry_xz") or []
        tangent = pose.get("tangent_out_xz") or []
        if not edge_id or not node_id or len(entry) < 2 or len(tangent) < 2:
            continue
        indexed[(edge_id, node_id)] = {
            "pose_id": str(pose.get("pose_id") or ""),
            "junction_id": str(pose.get("junction_id") or ""),
            "node_id": node_id,
            "edge_id": edge_id,
            "entry_xz": (float(entry[0]), float(entry[1])),
            "tangent_out_xz": normalize((float(tangent[0]), float(tangent[1]))),
            "entry_trim_m": float(pose.get("entry_trim_m") or 0.0),
            "can_enter_junction": bool(pose.get("can_enter_junction")),
            "can_exit_junction": bool(pose.get("can_exit_junction")),
            "status": str(pose.get("status") or ""),
            "issues": [str(issue) for issue in pose.get("issues") or []],
        }
    return indexed


def planned_pose_index(short_edge_absorptions: dict[str, Any] | None) -> dict[tuple[str, str], dict[str, Any]]:
    """Index non-destructive planned entry poses from transaction-ready short-edge absorptions."""
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    if not short_edge_absorptions:
        return indexed
    for candidate in short_edge_absorptions.get("candidates", []):
        if str(candidate.get("status") or "") != "transaction_ready":
            continue
        if candidate.get("issues"):
            continue
        node_id = str(candidate.get("junction_node_id") or "")
        edge_id = str(candidate.get("short_edge_id") or "")
        planned = candidate.get("planned_entry_pose") or {}
        entry = planned.get("entry_xz") or []
        tangent = planned.get("tangent_out_xz") or []
        if not node_id or not edge_id or len(entry) < 2 or len(tangent) < 2:
            continue
        current = candidate.get("current_entry_pose") or {}
        current_trim = float(current.get("entry_trim_m") or 0.0)
        planned_trim = float(planned.get("entry_trim_m") or 0.0)
        if planned_trim <= current_trim + PLANNED_ANCHOR_MIN_RECOVERY_M:
            continue
        indexed[(edge_id, node_id)] = {
            "candidate_id": str(candidate.get("candidate_id") or ""),
            "status": str(candidate.get("status") or ""),
            "risk": str(candidate.get("risk") or ""),
            "entry_xz": (float(entry[0]), float(entry[1])),
            "tangent_out_xz": normalize((float(tangent[0]), float(tangent[1]))),
            "entry_trim_m": planned_trim,
            "current_entry_trim_m": current_trim,
            "trim_recovery_m": float((candidate.get("metrics") or {}).get("trim_recovery_m") or 0.0),
            "path_edge_ids": [str(edge_id) for edge_id in candidate.get("path_edge_ids") or []],
            "successor_edge_ids": [str(edge_id) for edge_id in candidate.get("successor_edge_ids") or []],
        }
    return indexed


def lane_anchor(
    *,
    role: str,
    lane: dict[str, Any],
    node_id: str,
    poses: dict[tuple[str, str], dict[str, Any]],
    planned_poses: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], tuple[float, float], tuple[float, float], list[str], list[str]]:
    lane_id = str(lane.get("lane_id") or "")
    edge_id = str(lane.get("edge_id") or "")
    lateral_offset_m = float(lane.get("lateral_offset_m") or 0.0)
    pose = poses.get((edge_id, node_id))
    planned_pose = (planned_poses or {}).get((edge_id, node_id))
    issue_prefix = "entry_anchor" if role == "entry" else "exit_anchor"

    if pose is not None:
        pose_for_anchor = pose
        source = ENGINEERING_ANCHOR_SOURCE
        virtualization: dict[str, Any] | None = None
        if planned_pose is not None:
            pose_for_anchor = {**pose}
            pose_for_anchor["entry_xz"] = planned_pose["entry_xz"]
            pose_for_anchor["tangent_out_xz"] = planned_pose["tangent_out_xz"]
            pose_for_anchor["entry_trim_m"] = planned_pose["entry_trim_m"]
            source = PLANNED_ANCHOR_SOURCE
            virtualization = {
                "candidate_id": str(planned_pose.get("candidate_id") or ""),
                "status": str(planned_pose.get("status") or ""),
                "risk": str(planned_pose.get("risk") or ""),
                "base_pose_source": ENGINEERING_ANCHOR_SOURCE,
                "base_entry_trim_m": rounded(float(pose.get("entry_trim_m") or 0.0)),
                "base_entry_xz": round_point(pose["entry_xz"]),
                "base_pose_issues": [str(issue) for issue in pose.get("issues") or []],
                "trim_recovery_m": rounded(float(planned_pose.get("trim_recovery_m") or 0.0)),
                "path_edge_ids": [str(edge_id) for edge_id in planned_pose.get("path_edge_ids") or []],
                "successor_edge_ids": [str(edge_id) for edge_id in planned_pose.get("successor_edge_ids") or []],
                "contract": (
                    "Non-destructive planned anchor（非破坏式规划锚点） from transaction-ready "
                    "junction-zone expansion（路口影响区扩张） candidate; clean skeleton（干净道路骨架） is not modified."
                ),
            }

        outward_tangent = pose_for_anchor["tangent_out_xz"]
        travel_tangent = (-outward_tangent[0], -outward_tangent[1]) if role == "entry" else outward_tangent
        travel_tangent = normalize(travel_tangent)
        normal = left_normal(travel_tangent)
        point = (
            pose_for_anchor["entry_xz"][0] + normal[0] * lateral_offset_m,
            pose_for_anchor["entry_xz"][1] + normal[1] * lateral_offset_m,
        )
        issues = [] if virtualization is not None else [f"{issue_prefix}_{issue}" for issue in pose.get("issues") or []]
        if role == "entry" and not pose.get("can_enter_junction"):
            issues.append("entry_anchor_pose_cannot_enter_junction")
        if role == "exit" and not pose.get("can_exit_junction"):
            issues.append("exit_anchor_pose_cannot_exit_junction")
        confidence = min(float(lane.get("overall_confidence") or 0.0), ANCHOR_CONFIDENCE_CAP)
        if issues:
            confidence = min(confidence, LOW_CONFIDENCE_THRESHOLD)
        anchor = {
            "anchor_id": f"{lane_id}_{node_id}_{role}_anchor",
            "role": role,
            "source": source,
            "lane_id": lane_id,
            "edge_id": edge_id,
            "node_id": node_id,
            "pose_id": str(pose.get("pose_id") or ""),
            "point_xz": round_point(point),
            "tangent_xz": round_point(travel_tangent),
            "lateral_offset_m": rounded(lateral_offset_m),
            "entry_trim_m": rounded(float(pose_for_anchor.get("entry_trim_m") or 0.0)),
            "confidence": rounded(confidence),
            "issues": sorted(set(issues)),
        }
        if virtualization is not None:
            anchor["virtualization"] = virtualization
        return anchor, point, travel_tangent, [], issues

    fallback_side = "end" if role == "entry" else "start"
    point, tangent, endpoint_issues = endpoint_and_tangent(lane, fallback_side)
    issues = [f"missing_{role}_pose", f"{issue_prefix}_centerline_xz_preview_fallback"]
    issues.extend(f"{issue_prefix}_{issue}" for issue in endpoint_issues)
    confidence = min(float(lane.get("overall_confidence") or 0.0), FALLBACK_ANCHOR_CONFIDENCE_CAP)
    anchor = {
        "anchor_id": f"{lane_id}_{node_id}_{role}_anchor",
        "role": role,
        "source": "centerline_xz_preview_fallback",
        "lane_id": lane_id,
        "edge_id": edge_id,
        "node_id": node_id,
        "pose_id": "",
        "point_xz": round_point(point),
        "tangent_xz": round_point(tangent),
        "lateral_offset_m": rounded(lateral_offset_m),
        "entry_trim_m": None,
        "confidence": rounded(confidence),
        "issues": sorted(set(issues)),
    }
    return anchor, point, tangent, endpoint_issues, issues


def cubic_bezier(
    start: tuple[float, float],
    start_tangent: tuple[float, float],
    end: tuple[float, float],
    end_tangent: tuple[float, float],
    handle_scale: float,
    samples: int = SAMPLES,
) -> list[tuple[float, float]]:
    chord = distance(start, end)
    handle = max(0.25, chord * handle_scale)
    c1 = (start[0] + start_tangent[0] * handle, start[1] + start_tangent[1] * handle)
    c2 = (end[0] - end_tangent[0] * handle, end[1] - end_tangent[1] * handle)
    points: list[tuple[float, float]] = []
    for index in range(samples):
        t = index / (samples - 1)
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


def segment_intersection(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    def orient(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> float:
        return cross((q[0] - p[0], q[1] - p[1]), (r[0] - p[0], r[1] - p[1]))

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


def min_radius_proxy(points: list[tuple[float, float]]) -> float:
    best = math.inf
    for index in range(1, len(points) - 1):
        a = points[index - 1]
        b = points[index]
        c = points[index + 1]
        ab = distance(a, b)
        bc = distance(b, c)
        ca = distance(c, a)
        area2 = abs(cross((b[0] - a[0], b[1] - a[1]), (c[0] - a[0], c[1] - a[1])))
        if area2 <= 1e-9 or ab <= 1e-9 or bc <= 1e-9 or ca <= 1e-9:
            continue
        radius = (ab * bc * ca) / (2.0 * area2)
        best = min(best, radius)
    return best


def candidate_record(
    *,
    family: str,
    points: list[tuple[float, float]],
    confidence: float,
    base_issues: list[str],
) -> dict[str, Any]:
    issues = list(base_issues)
    length = polyline_length(points)
    if len(points) < 2:
        issues.append("empty_candidate_geometry")
    if length < MIN_CORRIDOR_LENGTH_M:
        issues.append("corridor_too_short")
    if length > MAX_CORRIDOR_LENGTH_M:
        issues.append("corridor_too_long")
    if has_self_intersection(points):
        issues.append("self_intersection")
    radius = min_radius_proxy(points)
    if radius != math.inf and radius < 3.0:
        issues.append("radius_proxy_below_lane_min")

    score = confidence * 100.0
    score -= 20.0 if "inferred_without_turn_lanes" in issues else 0.0
    score -= 12.0 if "low_confidence_lane_link" in issues else 0.0
    score -= 30.0 if "self_intersection" in issues else 0.0
    score -= 18.0 if "corridor_too_short" in issues or "corridor_too_long" in issues else 0.0
    score = max(0.0, min(100.0, score))
    return {
        "family": family,
        "status": "qa_candidate" if issues else "geometry_candidate",
        "score": rounded(score),
        "score_contract": "preview_score_only_without_collision_or_swept_envelope（仅预览评分，未包含碰撞或扫掠包络）",
        "publish_ready": False,
        "length_m": rounded(length),
        "min_radius_proxy_m": None if radius == math.inf else rounded(radius),
        "centerline_xz": [round_point(point) for point in points],
        "issues": sorted(set(issues)),
        "note": "Candidate preview（候选预览） only; not final lane geometry（最终车道几何）.",
    }


def lane_index(lane_graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(lane.get("lane_id") or ""): lane for lane in lane_graph.get("lanes", [])}


def link_case(
    *,
    link: dict[str, Any],
    from_lane: dict[str, Any],
    to_lane: dict[str, Any],
    poses: dict[tuple[str, str], dict[str, Any]],
    planned_poses: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    node_id = str(link.get("node_id") or "")
    entry_anchor, start, start_tangent, start_issues, entry_anchor_issues = lane_anchor(
        role="entry",
        lane=from_lane,
        node_id=node_id,
        poses=poses,
        planned_poses=planned_poses,
    )
    exit_anchor, end, end_tangent, end_issues, exit_anchor_issues = lane_anchor(
        role="exit",
        lane=to_lane,
        node_id=node_id,
        poses=poses,
        planned_poses=planned_poses,
    )
    confidence = min(
        float(link.get("confidence") or 0.0),
        float(from_lane.get("overall_confidence") or 0.0),
        float(to_lane.get("overall_confidence") or 0.0),
    )
    issues = list(
        start_issues
        + end_issues
        + entry_anchor_issues
        + exit_anchor_issues
        + [str(issue) for issue in link.get("issues") or []]
    )
    if confidence < LOW_CONFIDENCE_THRESHOLD:
        issues.append("low_confidence_lane_link")
    if str(from_lane.get("sources", {}).get("turn_lanes") or "") == "missing":
        issues.append("inferred_without_turn_lanes")
    if str(to_lane.get("sources", {}).get("turn_lanes") or "") == "missing":
        issues.append("outgoing_turn_lanes_missing")
    from_direction_policy = str(from_lane.get("traffic_direction_policy") or "unknown")
    to_direction_policy = str(to_lane.get("traffic_direction_policy") or "unknown")
    if "ambiguous_direction" in {from_direction_policy, to_direction_policy}:
        issues.append("ambiguous_direction_policy")

    chord = distance(start, end)
    tangent_delta = angle_between_deg(start_tangent, end_tangent)
    max_lane_width = max(float(from_lane.get("width_m") or 0.0), float(to_lane.get("width_m") or 0.0))
    corridor_width = max_lane_width + 0.8

    baseline = [start, end]
    bezier = cubic_bezier(start, start_tangent, end, end_tangent, 0.35)
    param_poly3_proxy = cubic_bezier(start, start_tangent, end, end_tangent, 0.5)
    candidates = [
        candidate_record(family="topology_straight_baseline", points=baseline, confidence=confidence, base_issues=issues),
        candidate_record(family="bezier_g1_preview", points=bezier, confidence=confidence, base_issues=issues),
        candidate_record(family="param_poly3_hermite_proxy", points=param_poly3_proxy, confidence=confidence, base_issues=issues),
    ]
    best = max(candidates, key=lambda item: float(item["score"]))
    case_status = "ready_for_geometry_solver"
    if confidence < READY_CONFIDENCE_THRESHOLD or best["issues"]:
        case_status = "qa_candidate"
    if start_issues or end_issues:
        case_status = "blocked"

    return {
        "corridor_id": "",
        "lane_link_id": str(link.get("lane_link_id") or ""),
        "junction_id": str(link.get("junction_id") or ""),
        "node_id": node_id,
        "from_lane_id": str(from_lane.get("lane_id") or ""),
        "to_lane_id": str(to_lane.get("lane_id") or ""),
        "from_edge_id": str(from_lane.get("edge_id") or ""),
        "to_edge_id": str(to_lane.get("edge_id") or ""),
        "movement_kind": str(link.get("movement_kind") or "unknown"),
        "traffic_direction_policies": {
            "from_lane": from_direction_policy,
            "to_lane": to_direction_policy,
        },
        "status": case_status,
        "confidence": rounded(confidence),
        "start_xz": round_point(start),
        "end_xz": round_point(end),
        "start_tangent_xz": round_point(start_tangent),
        "end_tangent_xz": round_point(end_tangent),
        "lane_entry_anchor": entry_anchor,
        "lane_exit_anchor": exit_anchor,
        "chord_length_m": rounded(chord),
        "tangent_delta_deg": rounded(tangent_delta),
        "corridor_width_m": rounded(corridor_width),
        "swept_envelope_model": "lane_width_plus_margin_estimate（车道宽度加余量估计）",
        "best_candidate_family": str(best["family"]),
        "best_score": float(best["score"]),
        "candidate_selection_contract": (
            "best_candidate_family（最佳候选曲线族） is preview-only（仅预览） until "
            "collision（碰撞）, swept envelope（扫掠包络） and curvature scoring（曲率评分） are added."
        ),
        "publish_ready": False,
        "candidates": candidates,
        "issues": sorted(set(issues)),
    }


def solve_movement_corridors(
    *,
    area_id: str,
    lane_graph: dict[str, Any],
    engineering_reference: dict[str, Any] | None = None,
    short_edge_absorptions: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    lanes = lane_index(lane_graph)
    poses = pose_index(engineering_reference)
    planned_poses = planned_pose_index(short_edge_absorptions)
    cases: list[dict[str, Any]] = []
    reference_errors = 0
    skipped_non_junction_links = 0

    for link in lane_graph.get("lane_links", []):
        if str(link.get("link_kind") or "") != "junction_movement":
            skipped_non_junction_links += 1
            continue
        from_lane = lanes.get(str(link.get("from_lane_id") or ""))
        to_lane = lanes.get(str(link.get("to_lane_id") or ""))
        if not from_lane or not to_lane:
            reference_errors += 1
            continue
        case = link_case(
            link=link,
            from_lane=from_lane,
            to_lane=to_lane,
            poses=poses,
            planned_poses=planned_poses,
        )
        case["corridor_id"] = f"mc_{len(cases):05d}"
        cases.append(case)

    status_counts = Counter(str(case.get("status") or "unknown") for case in cases)
    movement_counts = Counter(str(case.get("movement_kind") or "unknown") for case in cases)
    candidate_family_counts = Counter(
        str(candidate.get("family") or "unknown")
        for case in cases
        for candidate in case.get("candidates", [])
    )
    best_family_counts = Counter(str(case.get("best_candidate_family") or "unknown") for case in cases)
    direction_policy_pair_counts = Counter(
        f"{case.get('traffic_direction_policies', {}).get('from_lane', 'unknown')}->{case.get('traffic_direction_policies', {}).get('to_lane', 'unknown')}"
        for case in cases
    )
    issue_counts = Counter(
        str(issue)
        for case in cases
        for issue in case.get("issues", [])
    )
    candidate_issue_counts = Counter(
        str(issue)
        for case in cases
        for candidate in case.get("candidates", [])
        for issue in candidate.get("issues", [])
    )
    anchors = [
        anchor
        for case in cases
        for anchor in (case.get("lane_entry_anchor"), case.get("lane_exit_anchor"))
        if isinstance(anchor, dict)
    ]
    anchor_source_counts = Counter(str(anchor.get("source") or "unknown") for anchor in anchors)
    anchor_issue_counts = Counter(
        str(issue)
        for anchor in anchors
        for issue in anchor.get("issues", [])
    )
    anchor_confidences = [float(anchor.get("confidence") or 0.0) for anchor in anchors]
    anchored_cases = sum(
        1
        for case in cases
        if str((case.get("lane_entry_anchor") or {}).get("source") or "") in LANE_LEVEL_ANCHOR_SOURCES
        and str((case.get("lane_exit_anchor") or {}).get("source") or "") in LANE_LEVEL_ANCHOR_SOURCES
    )
    planned_virtual_anchor_source = anchor_source_counts.get(PLANNED_ANCHOR_SOURCE, 0)
    planned_virtual_anchor_cases = sum(
        1
        for case in cases
        if str((case.get("lane_entry_anchor") or {}).get("source") or "") == PLANNED_ANCHOR_SOURCE
        or str((case.get("lane_exit_anchor") or {}).get("source") or "") == PLANNED_ANCHOR_SOURCE
    )
    fallback_anchors = anchor_source_counts.get("centerline_xz_preview_fallback", 0)
    missing_anchor_poses = anchor_issue_counts.get("missing_entry_pose", 0) + anchor_issue_counts.get("missing_exit_pose", 0)
    confidences = [float(case.get("confidence") or 0.0) for case in cases]
    low_confidence_cases = sum(1 for value in confidences if value < LOW_CONFIDENCE_THRESHOLD)
    ready_cases = status_counts.get("ready_for_geometry_solver", 0)

    output = {
        "type": "movement_corridor_candidates",
        "metadata": {
            "area_id": area_id,
            "schema": "road_test_pipeline.movement_corridor_candidates.v1",
            "source": "lane_graph（车道拓扑图） + engineering_reference_lines（工程参考线）",
            "contract": (
                "Non-destructive movement corridor candidates（非破坏式通行走廊候选）. "
                "Candidate endpoints use lane-level entry/exit anchors（车道级入口/出口锚点） when "
                "engineering entry poses（工程入口姿态） are available. Do not treat candidate "
                "centerlines or best_candidate_family（最佳候选曲线族） as final lane geometry（最终车道几何）."
            ),
        },
        "cases": cases,
    }
    report = {
        "area_id": area_id,
        "stage": "movement_corridor_solver_v1",
        "status": "warn" if issue_counts or reference_errors else "pass",
        "counts": {
            "junction_lane_links": len(cases) + reference_errors,
            "corridor_cases": len(cases),
            "candidate_curves": sum(len(case.get("candidates", [])) for case in cases),
            "ready_for_geometry_solver": ready_cases,
            "reference_errors": reference_errors,
            "skipped_non_junction_lane_links": skipped_non_junction_links,
            "status_counts": dict(sorted(status_counts.items())),
            "movement_kind_counts": dict(sorted(movement_counts.items())),
            "candidate_family_counts": dict(sorted(candidate_family_counts.items())),
            "best_family_counts": dict(sorted(best_family_counts.items())),
            "traffic_direction_policy_pair_counts": dict(sorted(direction_policy_pair_counts.items())),
            "approach_entry_poses_indexed": len(poses),
            "short_edge_absorption_planned_poses_indexed": len(planned_poses),
            "anchor_source_counts": dict(sorted(anchor_source_counts.items())),
            "anchor_issue_counts": dict(sorted(anchor_issue_counts.items())),
            "fully_anchored_cases": anchored_cases,
            "planned_virtual_anchors": planned_virtual_anchor_source,
            "planned_virtual_anchor_cases": planned_virtual_anchor_cases,
            "fallback_anchors": fallback_anchors,
            "missing_anchor_poses": missing_anchor_poses,
            "issue_counts": dict(sorted(issue_counts.items())),
            "candidate_issue_counts": dict(sorted(candidate_issue_counts.items())),
            "publish_ready_cases": 0,
        },
        "metrics": {
            "avg_confidence": rounded(sum(confidences) / max(1, len(confidences))),
            "min_confidence": rounded(min(confidences)) if confidences else 0.0,
            "low_confidence_ratio": rounded(low_confidence_cases / max(1, len(confidences))),
            "ready_ratio": rounded(ready_cases / max(1, len(cases))),
            "avg_anchor_confidence": rounded(sum(anchor_confidences) / max(1, len(anchor_confidences))),
            "fully_anchored_case_ratio": rounded(anchored_cases / max(1, len(cases))),
            "anchor_fallback_ratio": rounded(fallback_anchors / max(1, len(anchors))),
            "planned_virtual_anchor_ratio": rounded(planned_virtual_anchor_source / max(1, len(anchors))),
        },
        "next_action": (
            "Next add collision（碰撞） and swept envelope（扫掠包络） scoring, then promote only "
            "transaction-ready（事务就绪） junction-zone expansion（路口影响区扩张） candidates through "
            "a replacement transaction（替换事务）."
        ),
        "candidate_selection_contract": (
            "best_candidate_family（最佳候选曲线族） is diagnostic preview（诊断预览） only; "
            "do not publish it until collision（碰撞）, swept envelope（扫掠包络） and curvature scoring（曲率评分） exist."
        ),
    }
    return output, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Solve lane-level movement corridor candidates from lane_graph.json.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--lane-graph", default="")
    parser.add_argument("--engineering-reference", default="")
    parser.add_argument("--short-edge-absorptions", default="", help="Optional short_edge_absorption_candidates.json used for non-destructive planned anchors.")
    parser.add_argument("--output", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    processed = root / "data" / "processed"
    reports = root / "reports"
    lane_graph_path = Path(args.lane_graph) if args.lane_graph else processed / f"{args.area_id}_lane_graph.json"
    engineering_reference_path = (
        Path(args.engineering_reference)
        if args.engineering_reference
        else processed / f"{args.area_id}_engineering_reference_lines.json"
    )
    short_edge_absorption_path = (
        Path(args.short_edge_absorptions)
        if args.short_edge_absorptions
        else processed / f"{args.area_id}_short_edge_absorption_candidates.json"
    )
    output_path = Path(args.output) if args.output else processed / f"{args.area_id}_movement_corridor_candidates.json"
    report_path = Path(args.report) if args.report else reports / f"{args.area_id}_movement_corridor_report.json"

    engineering_reference = read_json(engineering_reference_path) if engineering_reference_path.exists() else {}
    short_edge_absorptions = read_json(short_edge_absorption_path) if short_edge_absorption_path.exists() else {}
    output, report = solve_movement_corridors(
        area_id=args.area_id,
        lane_graph=read_json(lane_graph_path),
        engineering_reference=engineering_reference,
        short_edge_absorptions=short_edge_absorptions,
    )
    output["metadata"]["inputs"] = {
        "lane_graph": str(lane_graph_path),
        "engineering_reference_lines": str(engineering_reference_path),
        "short_edge_absorption_candidates": str(short_edge_absorption_path) if short_edge_absorption_path.exists() else "",
    }
    report["inputs"] = output["metadata"]["inputs"]
    report["outputs"] = {"movement_corridor_candidates": str(output_path), "report": str(report_path)}
    write_json(output_path, output)
    write_json(report_path, report)
    print(json.dumps({
        "area_id": args.area_id,
        "status": report["status"],
        "counts": report["counts"],
        "metrics": report["metrics"],
        "outputs": report["outputs"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
