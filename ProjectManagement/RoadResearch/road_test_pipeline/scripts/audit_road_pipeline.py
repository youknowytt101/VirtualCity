#!/usr/bin/env python3
"""Audit the road_test_pipeline contracts across data, semantics and preview.

This is a lightweight regression gate for the research pipeline. It checks the
contracts that matter while the default output remains centerline-only.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


JUNCTION_TYPES = {"T", "cross", "Y", "offset", "complex"}
FINAL_LANE_CENTERLINE_LOW_RADIUS_MIN_M = 4.0
FINAL_LANE_CENTERLINE_LOW_RADIUS_MAX_SAMPLE_SEGMENT_M = 1.0
FINAL_LANE_CENTERLINE_LOW_RADIUS_MAX_RUN_SPAN_M = 4.0
UPGRADED_INTERNAL_BEND_MIN_TARGET_LANES = 3
UPGRADED_INTERNAL_BEND_MIN_TURN_DEG = 55.0
COMPOUND_ALTERNATING_BEND_GUARD_STATUS = "skipped_compound_alternating_bend_guard"
ENDPOINT_CONTRACT_MAX_GAP_M = 0.50
SURFACE_LENGTH_CONTRACT_MAX_DELTA_M = 0.05
QA_WARNING_SEVERITY_POLICY_ID = "qa_warning_severity_tiers_v1"
QA_WARNING_TIERS = ("publishable_warn", "manual_review_required", "blocker")
QA_GATE_STATUS_ORDER = {
    "pass": 0,
    "publishable_warn": 1,
    "manual_review_required": 2,
    "blocker": 3,
}

QA_WARNING_RULES: dict[tuple[str, str], dict[str, Any]] = {
    ("topology_repair", "dangling_endpoint_ratio"): {
        "tier": "manual_review_required",
        "blocker_above": 0.45,
        "reason": "Topology still has enough dangling endpoints that autonomous production should stop for review.",
    },
    ("road_graph", "dead_end_ratio"): {
        "tier": "manual_review_required",
        "blocker_above": 0.50,
        "reason": "Road graph contains a high dead-end ratio; review endpoint classification before unattended production.",
    },
    ("road_graph", "width_fallback_ratio"): {
        "tier": "manual_review_required",
        "reason": "All or most road widths are inferred from defaults; output is publishable for research but needs semantic review.",
    },
    ("road_graph", "lanes_fallback_ratio"): {
        "tier": "manual_review_required",
        "blocker_above": 0.95,
        "reason": "Lane-count defaults dominate the road graph; production output needs review before use.",
    },
    ("lane_graph", "fan_fallback_ratio"): {
        "tier": "manual_review_required",
        "blocker_above": 0.95,
        "reason": "Lane graph still depends heavily on fallback fan connections.",
    },
    ("lane_graph", "avg_lane_links_per_junction"): {
        "tier": "manual_review_required",
        "reason": "Junction lane connectivity is sparse enough to require manual review.",
    },
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return read_json(path)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def make_check(check_id: str, ok: bool, message: str, value: Any = None, warn: bool = False) -> dict[str, Any]:
    status = "pass" if ok else "warn" if warn else "fail"
    return {
        "id": check_id,
        "status": status,
        "value": value,
        "message": message,
    }


def worst_status(checks: list[dict[str, Any]]) -> str:
    order = {"pass": 0, "warn": 1, "fail": 2}
    status = "pass"
    for check in checks:
        if order[check["status"]] > order[status]:
            status = check["status"]
    return status


def as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def classify_warning_tier(stage: str, check: dict[str, Any]) -> tuple[str, str]:
    status = str(check.get("status") or "")
    if status == "fail":
        return "blocker", "QA check failed."
    if status != "warn":
        return "", ""

    rule = QA_WARNING_RULES.get((stage, str(check.get("id") or "")), {})
    tier = str(rule.get("tier") or "publishable_warn")
    reason = str(rule.get("reason") or "Warning is publishable for research and should be tracked.")
    value = as_float(check.get("value"))
    blocker_above = as_float(rule.get("blocker_above"))
    blocker_below = as_float(rule.get("blocker_below"))
    if value is not None and blocker_above is not None and value > blocker_above:
        return "blocker", reason
    if value is not None and blocker_below is not None and value < blocker_below:
        return "blocker", reason
    return tier, reason


def make_gate_entry(stage: str, check: dict[str, Any], tier: str, reason: str) -> dict[str, Any]:
    return {
        "stage": stage,
        "check_id": str(check.get("id") or ""),
        "source_status": str(check.get("status") or ""),
        "tier": tier,
        "value": check.get("value"),
        "threshold": check.get("threshold"),
        "message": check.get("message", ""),
        "reason": reason,
    }


def build_qa_warning_gate(
    *,
    stage_reports: dict[str, dict[str, Any]],
    audit_checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for stage, report in stage_reports.items():
        for check in report.get("checks", []):
            tier, reason = classify_warning_tier(stage, check)
            if tier:
                entries.append(make_gate_entry(stage, check, tier, reason))
        if report.get("status") == "fail" and not any(check.get("status") == "fail" for check in report.get("checks", [])):
            entries.append({
                "stage": stage,
                "check_id": "stage_status",
                "source_status": "fail",
                "tier": "blocker",
                "value": report.get("status"),
                "threshold": "not_fail",
                "message": "Stage QA report status is fail.",
                "reason": "Stage QA failed without an individual failed check in the report.",
            })

    for check in audit_checks or []:
        status = str(check.get("status") or "")
        if status not in {"warn", "fail"}:
            continue
        tier = "blocker" if status == "fail" else "manual_review_required"
        reason = "Pipeline audit contract warning requires review."
        if status == "fail":
            reason = "Pipeline audit contract failed."
        entries.append(make_gate_entry("pipeline_audit", check, tier, reason))

    summary = {tier: 0 for tier in QA_WARNING_TIERS}
    gate_status = "pass"
    for entry in entries:
        tier = str(entry.get("tier") or "publishable_warn")
        summary[tier] = summary.get(tier, 0) + 1
        if QA_GATE_STATUS_ORDER[tier] > QA_GATE_STATUS_ORDER[gate_status]:
            gate_status = tier

    return {
        "policy_id": QA_WARNING_SEVERITY_POLICY_ID,
        "status": gate_status,
        "summary": summary,
        "entries": entries,
        "publish_decision": {
            "research_publish_allowed": gate_status != "blocker",
            "autonomous_production_allowed": gate_status in {"pass", "publishable_warn"},
            "manual_review_required": gate_status == "manual_review_required",
            "blocker": gate_status == "blocker",
        },
    }


def geometry_type_counts(fc: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for feature in fc.get("features", []):
        geom_type = str((feature.get("geometry") or {}).get("type") or "missing")
        counts[geom_type] = counts.get(geom_type, 0) + 1
    return counts


def line_coordinate_count(fc: dict[str, Any]) -> int:
    total = 0
    for feature in fc.get("features", []):
        geom = feature.get("geometry") or {}
        if geom.get("type") == "LineString":
            total += len(geom.get("coordinates") or [])
    return total


def source_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if value is None or value == "":
        return []
    return [str(value)]


def min_numeric_id(values: Any) -> int:
    numeric: list[int] = []
    for value in source_list(values):
        try:
            numeric.append(int(value))
        except ValueError:
            continue
    return min(numeric) if numeric else 1_000_000_000


def road_identity_key(edge: dict[str, Any]) -> str:
    chain_id = str(edge.get("road_chain_id") or "")
    if chain_id:
        return chain_id
    source_ids = source_list(edge.get("source_feature_ids"))
    if source_ids:
        return "source:" + "|".join(sorted(source_ids))
    return ""


def edge_endpoints(edge: dict[str, Any]) -> tuple[tuple[float, float], tuple[float, float]] | None:
    points = as_points(edge.get("geometry_xz") or [])
    if len(points) < 2:
        return None
    return points[0], points[-1]


def endpoint_gap(edge_a: dict[str, Any], edge_b: dict[str, Any]) -> float | None:
    endpoints_a = edge_endpoints(edge_a)
    endpoints_b = edge_endpoints(edge_b)
    if endpoints_a is None or endpoints_b is None:
        return None
    return min(distance(a, b) for a in endpoints_a for b in endpoints_b)


def road_identity_fragmentation(
    road_graph: dict[str, Any],
    *,
    max_touch_gap_m: float = 0.01,
    sample_limit: int = 20,
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in road_graph.get("edges", []):
        key = road_identity_key(edge)
        if key:
            groups[key].append(edge)

    fragmented = []
    touching_fragmented = 0
    max_fragments = 1
    for key, edges in sorted(groups.items()):
        if len(edges) <= 1:
            continue
        ordered = sorted(
            edges,
            key=lambda edge: (
                min_numeric_id(edge.get("repair_edge_ids")),
                str(edge.get("canonical_road_id") or edge.get("edge_id") or ""),
            ),
        )
        gaps = [
            gap
            for gap in (endpoint_gap(ordered[index], ordered[index + 1]) for index in range(len(ordered) - 1))
            if gap is not None
        ]
        max_gap = max(gaps) if gaps else 0.0
        if max_gap <= max_touch_gap_m:
            touching_fragmented += 1
        max_fragments = max(max_fragments, len(ordered))
        fragmented.append({
            "road_identity_key": key,
            "canonical_road_ids": [str(edge.get("canonical_road_id") or "") for edge in ordered],
            "edge_ids": [str(edge.get("edge_id") or "") for edge in ordered],
            "fragment_count": len(ordered),
            "max_adjacent_endpoint_gap_m": round(max_gap, 3),
            "touching_fragments": max_gap <= max_touch_gap_m,
        })

    return {
        "policy": "road_identity_fragmentation_tracking_v1",
        "max_touch_gap_m": max_touch_gap_m,
        "road_identity_groups": len(groups),
        "fragmented_road_identities": len(fragmented),
        "touching_fragmented_road_identities": touching_fragmented,
        "max_fragments_per_identity": max_fragments,
        "samples": fragmented[:sample_limit],
    }


def as_points(points: list[Any]) -> list[tuple[float, float]]:
    return [(float(point[0]), float(point[1])) for point in points]


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = a[0] - b[0]
    dz = a[1] - b[1]
    return (dx * dx + dz * dz) ** 0.5


def polyline_length(points: list[tuple[float, float]]) -> float:
    return sum(distance(points[i], points[i + 1]) for i in range(len(points) - 1))


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


def low_radius_sampled_arc_issues(
    centerlines: list[dict[str, Any]],
    *,
    min_radius_m: float = FINAL_LANE_CENTERLINE_LOW_RADIUS_MIN_M,
    max_sample_segment_m: float = FINAL_LANE_CENTERLINE_LOW_RADIUS_MAX_SAMPLE_SEGMENT_M,
    max_run_span_m: float = FINAL_LANE_CENTERLINE_LOW_RADIUS_MAX_RUN_SPAN_M,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for centerline in centerlines:
        points = as_points(centerline.get("centerline_xz") or [])
        if len(points) < 5:
            continue
        segment_lengths = [distance(points[index], points[index + 1]) for index in range(len(points) - 1)]
        bad_indices: list[tuple[int, float]] = []
        for index in range(1, len(points) - 1):
            if max(segment_lengths[index - 1], segment_lengths[index]) > max_sample_segment_m:
                continue
            radius = circumradius_or_inf(points[index - 1], points[index], points[index + 1])
            if radius < min_radius_m:
                bad_indices.append((index, radius))
        if not bad_indices:
            continue

        groups: list[list[tuple[int, float]]] = []
        current: list[tuple[int, float]] = []
        for item in bad_indices:
            index = item[0]
            if not current or index == current[-1][0] + 1:
                current.append(item)
            else:
                groups.append(current)
                current = [item]
        if current:
            groups.append(current)

        for group in groups:
            if len(group) < 2:
                continue
            start_index = max(1, group[0][0] - 1)
            end_index = min(len(points) - 2, group[-1][0] + 1)
            span = distance(points[start_index], points[end_index])
            if span > max_run_span_m:
                continue
            issues.append({
                "centerline_id": str(
                    centerline.get("centerline_id")
                    or centerline.get("physical_lane_id")
                    or centerline.get("lane_id")
                    or ""
                ),
                "lane_ids": list(centerline.get("source_lane_ids") or centerline.get("lane_ids") or []),
                "start_index": start_index,
                "end_index": end_index,
                "span_m": round(span, 3),
                "min_radius_m": round(min(radius for _index, radius in group), 3),
                "threshold_m": min_radius_m,
            })
    return issues


def compound_alternating_bend_guard_skips(optimized_report: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    by_edge = optimized_report.get("internal_bend_smoothing_by_edge") or {}
    for edge_id, records in sorted(by_edge.items()):
        for record in records or []:
            if str(record.get("status") or "") != COMPOUND_ALTERNATING_BEND_GUARD_STATUS:
                continue
            guard = record.get("compound_alternating_bend") or {}
            issues.append({
                "edge_id": str(edge_id),
                "candidate_id": str(record.get("candidate_id") or ""),
                "point_index": int(record.get("point_index") or 0),
                "guard_policy": str(record.get("guard_policy") or guard.get("policy") or ""),
                "significant_turn_count": int(guard.get("significant_turn_count") or 0),
                "sign_change_count": int(guard.get("sign_change_count") or 0),
                "turns": list(guard.get("turns") or [])[:8],
            })
    return issues


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


def trimmed_endpoint(
    lane: dict[str, Any],
    side: str,
    trim: dict[str, float],
) -> tuple[float, float] | None:
    points = as_points(lane.get("centerline_xz") or [])
    if len(points) < 2:
        return None
    length = polyline_length(points)
    trim_start_m, trim_end_m = resolve_trim_distances(
        length,
        float(trim.get("start") or 0.0),
        float(trim.get("end") or 0.0),
        float(trim.get("locked_start") or 0.0),
        float(trim.get("locked_end") or 0.0),
    )
    station = trim_start_m if side == "start" else max(0.0, length - trim_end_m)
    return point_at_distance(points, station)


def lane_trim_distances(
    lane_graph: dict[str, Any],
    lane_links: list[dict[str, Any]],
    continuity_links: list[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    trim_m = float(lane_graph.get("metadata", {}).get("junction_trim_m") or 8.0)
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


def lane_curve_gap_metrics(
    lane_graph: dict[str, Any],
    lane_links: list[dict[str, Any]],
    continuity_links: list[dict[str, Any]],
) -> dict[str, Any]:
    lanes_by_id = {str(lane.get("lane_id") or ""): lane for lane in lane_graph.get("lanes", [])}
    trim_by_lane = lane_trim_distances(lane_graph, lane_links, continuity_links)
    max_lane_link_start_gap = 0.0
    max_lane_link_end_gap = 0.0
    max_continuity_start_gap = 0.0
    max_continuity_end_gap = 0.0

    for link in lane_links:
        curve = as_points(link.get("connecting_curve_xz") or [])
        from_lane = lanes_by_id.get(str(link.get("from_lane") or ""))
        to_lane = lanes_by_id.get(str(link.get("to_lane") or ""))
        if len(curve) < 2 or from_lane is None or to_lane is None:
            continue
        from_endpoint = trimmed_endpoint(from_lane, "end", trim_by_lane.get(str(link.get("from_lane") or ""), {}))
        to_endpoint = trimmed_endpoint(to_lane, "start", trim_by_lane.get(str(link.get("to_lane") or ""), {}))
        if from_endpoint is not None:
            max_lane_link_start_gap = max(max_lane_link_start_gap, distance(from_endpoint, curve[0]))
        if to_endpoint is not None:
            max_lane_link_end_gap = max(max_lane_link_end_gap, distance(to_endpoint, curve[-1]))

    for link in continuity_links:
        curve = as_points(link.get("connecting_curve_xz") or [])
        from_lane = lanes_by_id.get(str(link.get("from_lane") or ""))
        to_lane = lanes_by_id.get(str(link.get("to_lane") or ""))
        if len(curve) < 2 or from_lane is None or to_lane is None:
            continue
        from_endpoint = trimmed_endpoint(from_lane, "end", trim_by_lane.get(str(link.get("from_lane") or ""), {}))
        to_endpoint = trimmed_endpoint(to_lane, "start", trim_by_lane.get(str(link.get("to_lane") or ""), {}))
        if from_endpoint is not None:
            max_continuity_start_gap = max(max_continuity_start_gap, distance(from_endpoint, curve[0]))
        if to_endpoint is not None:
            max_continuity_end_gap = max(max_continuity_end_gap, distance(to_endpoint, curve[-1]))

    return {
        "max_lane_link_start_gap_m": round(max_lane_link_start_gap, 6),
        "max_lane_link_end_gap_m": round(max_lane_link_end_gap, 6),
        "max_continuity_start_gap_m": round(max_continuity_start_gap, 6),
        "max_continuity_end_gap_m": round(max_continuity_end_gap, 6),
    }


def normalized_movement_lane_id(lane_id: str) -> str:
    parts = str(lane_id or "").split("_")
    if len(parts) >= 5 and parts[0] == "ln" and parts[-2] in {"f", "b"}:
        edge_id = "_".join(parts[1:-2])
        return f"{edge_id}_{parts[-2]}_1"
    return str(lane_id or "")


def candidate_for_endpoint_audit(case: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [candidate for candidate in case.get("candidates") or [] if isinstance(candidate, dict)]
    if not candidates:
        return None
    best_family = str(case.get("best_candidate_family") or "")
    for candidate in candidates:
        if str(candidate.get("family") or "") == best_family:
            return candidate
    return candidates[0]


def movement_corridor_endpoint_contract(
    lane_links: list[dict[str, Any]],
    movement_corridors: dict[str, Any] | None,
    *,
    max_gap_m: float = ENDPOINT_CONTRACT_MAX_GAP_M,
    sample_limit: int = 20,
) -> dict[str, Any]:
    links_by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for link in lane_links:
        key = (
            str(link.get("from_lane") or ""),
            str(link.get("to_lane") or ""),
            str(link.get("turn") or link.get("connection_turn") or ""),
        )
        links_by_key.setdefault(key, []).append(link)

    cases = list((movement_corridors or {}).get("cases") or [])
    max_start_gap = 0.0
    max_end_gap = 0.0
    comparable_cases = 0
    stale_cases: list[dict[str, Any]] = []
    missing_final_lane_link = 0
    missing_candidate_geometry = 0

    for case in cases:
        candidate = candidate_for_endpoint_audit(case)
        points = as_points((candidate or {}).get("centerline_xz") or [])
        if len(points) < 2:
            missing_candidate_geometry += 1
            continue
        from_lane = normalized_movement_lane_id(str(case.get("from_lane_id") or ""))
        to_lane = normalized_movement_lane_id(str(case.get("to_lane_id") or ""))
        turn = str(case.get("movement_kind") or "")
        matches = links_by_key.get((from_lane, to_lane, turn), [])
        if not matches:
            missing_final_lane_link += 1
            continue

        best_start_gap = float("inf")
        best_end_gap = float("inf")
        best_link_id = ""
        for link in matches:
            curve = as_points(link.get("connecting_curve_xz") or [])
            if len(curve) < 2:
                continue
            start_gap = distance(points[0], curve[0])
            end_gap = distance(points[-1], curve[-1])
            if max(start_gap, end_gap) < max(best_start_gap, best_end_gap):
                best_start_gap = start_gap
                best_end_gap = end_gap
                best_link_id = str(link.get("lane_link_id") or "")
        if best_start_gap == float("inf") or best_end_gap == float("inf"):
            missing_final_lane_link += 1
            continue

        comparable_cases += 1
        max_start_gap = max(max_start_gap, best_start_gap)
        max_end_gap = max(max_end_gap, best_end_gap)
        if max(best_start_gap, best_end_gap) > max_gap_m:
            stale_cases.append({
                "corridor_id": str(case.get("corridor_id") or ""),
                "lane_link_id": best_link_id,
                "from_lane_id": str(case.get("from_lane_id") or ""),
                "to_lane_id": str(case.get("to_lane_id") or ""),
                "normalized_from_lane_id": from_lane,
                "normalized_to_lane_id": to_lane,
                "movement_kind": turn,
                "candidate_family": str((candidate or {}).get("family") or ""),
                "start_gap_m": round(best_start_gap, 3),
                "end_gap_m": round(best_end_gap, 3),
                "max_gap_m": round(max(best_start_gap, best_end_gap), 3),
            })

    return {
        "policy": "movement_corridor_final_lane_link_endpoint_contract_v1",
        "max_allowed_gap_m": max_gap_m,
        "corridor_cases": len(cases),
        "comparable_cases": comparable_cases,
        "missing_final_lane_link": missing_final_lane_link,
        "missing_candidate_geometry": missing_candidate_geometry,
        "stale_cases": len(stale_cases),
        "max_start_gap_m": round(max_start_gap, 3),
        "max_end_gap_m": round(max_end_gap, 3),
        "max_endpoint_gap_m": round(max(max_start_gap, max_end_gap), 3),
        "stale_case_samples": stale_cases[:sample_limit],
    }


def lane_turn_surface_contract(
    lane_links: list[dict[str, Any]],
    lane_surface_geojson: dict[str, Any],
    *,
    max_length_delta_m: float = SURFACE_LENGTH_CONTRACT_MAX_DELTA_M,
    sample_limit: int = 20,
) -> dict[str, Any]:
    surfaces_by_link_id: dict[str, dict[str, Any]] = {}
    for feature in lane_surface_geojson.get("features", []):
        props = feature.get("properties") or {}
        if props.get("vc_part") != "lane_turn_surface_v1":
            continue
        link_id = str(props.get("lane_link_id") or "")
        if link_id:
            surfaces_by_link_id[link_id] = props

    missing_surfaces: list[str] = []
    length_mismatches: list[dict[str, Any]] = []
    max_length_delta = 0.0
    checked = 0
    for link in lane_links:
        link_id = str(link.get("lane_link_id") or "")
        props = surfaces_by_link_id.get(link_id)
        if props is None:
            missing_surfaces.append(link_id)
            continue
        curve_length = polyline_length(as_points(link.get("connecting_curve_xz") or []))
        surface_length = float(props.get("length_m") or 0.0)
        delta = abs(curve_length - surface_length)
        max_length_delta = max(max_length_delta, delta)
        checked += 1
        if delta > max_length_delta_m:
            length_mismatches.append({
                "lane_link_id": link_id,
                "curve_length_m": round(curve_length, 3),
                "surface_length_m": round(surface_length, 3),
                "delta_m": round(delta, 3),
            })

    return {
        "policy": "lane_turn_surface_final_lane_link_contract_v1",
        "max_allowed_length_delta_m": max_length_delta_m,
        "lane_links": len(lane_links),
        "turn_surfaces": len(surfaces_by_link_id),
        "checked_surfaces": checked,
        "missing_surfaces": len(missing_surfaces),
        "length_mismatches": len(length_mismatches),
        "max_length_delta_m": round(max_length_delta, 3),
        "missing_surface_samples": missing_surfaces[:sample_limit],
        "length_mismatch_samples": length_mismatches[:sample_limit],
    }


def active_upgraded_road_ids(
    lane_upgrade_overrides: dict[str, Any],
    *,
    min_target_lanes: int = UPGRADED_INTERNAL_BEND_MIN_TARGET_LANES,
) -> set[str]:
    road_ids: set[str] = set()
    for item in lane_upgrade_overrides.get("active_upgrades", []):
        if not bool(item.get("enabled", True)):
            continue
        try:
            target_lanes = int(item.get("target_physical_lane_count") or 0)
        except (TypeError, ValueError):
            target_lanes = 0
        if target_lanes < min_target_lanes:
            continue
        road_id = str(item.get("road_id") or "")
        if road_id:
            road_ids.add(road_id)
    return road_ids


def unresolved_upgraded_internal_bends(
    corner_candidates: dict[str, Any],
    upgraded_road_ids: set[str],
    *,
    min_turn_deg: float = UPGRADED_INTERNAL_BEND_MIN_TURN_DEG,
    sample_limit: int = 20,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    for candidate in corner_candidates.get("candidates", []):
        if str(candidate.get("candidate_type") or "") != "internal_centerline_bend":
            continue
        if str(candidate.get("status") or "") == "accepted_active":
            continue
        source_edge_id = str(candidate.get("source_edge_id") or "")
        if source_edge_id not in upgraded_road_ids:
            continue
        turn_deg = as_float(candidate.get("turn_angle_deg")) or 0.0
        if turn_deg < min_turn_deg:
            continue
        issues.append({
            "candidate_id": str(candidate.get("candidate_id") or ""),
            "source_edge_id": source_edge_id,
            "canonical_road_id": str(candidate.get("canonical_road_id") or ""),
            "point_index": candidate.get("point_index"),
            "turn_angle_deg": round(turn_deg, 3),
            "risk_level": str(candidate.get("risk_level") or ""),
            "recommended_action": str(candidate.get("recommended_action") or ""),
            "nearest_junction_distance_m": candidate.get("nearest_junction_distance_m"),
        })

    return {
        "policy": "upgraded_road_internal_bend_review_gate_v1",
        "min_target_physical_lane_count": UPGRADED_INTERNAL_BEND_MIN_TARGET_LANES,
        "min_turn_angle_deg": min_turn_deg,
        "active_upgraded_roads": len(upgraded_road_ids),
        "issue_count": len(issues),
        "issues": issues[:sample_limit],
    }


def audit(root: Path, area_id: str, output_path: Path) -> dict[str, Any]:
    processed = root / "data" / "processed"
    preview_dir = root / "data" / "preview"
    reports = root / "reports"
    qa_reports = reports / "qa"

    paths = {
        "raw_roads": processed / f"{area_id}_roads_raw.geojson",
        "repaired_roads": processed / f"{area_id}_roads_repaired.geojson",
        "road_graph": processed / f"{area_id}_road_graph.json",
        "junction_semantics": processed / f"{area_id}_junction_semantics.json",
        "optimized_centerlines": processed / f"{area_id}_roads_optimized_centerlines.geojson",
        "optimized_centerlines_report": reports / f"{area_id}_optimized_centerlines_report.json",
        "lane_graph": processed / f"{area_id}_lane_graph.json",
        "preview_geojson": preview_dir / f"{area_id}_roads_preview_surfaces.geojson",
        "preview_obj": preview_dir / f"{area_id}_roads_preview.obj",
        "preview_svg": preview_dir / f"{area_id}_roads_preview.svg",
        "lane_geometry_debug_geojson": preview_dir / f"{area_id}_lane_geometry_debug.geojson",
        "lane_geometry_debug_obj": preview_dir / f"{area_id}_lane_geometry_debug.obj",
        "lane_geometry_debug_svg": preview_dir / f"{area_id}_lane_geometry_debug.svg",
        "lane_geometry_debug_report": reports / f"{area_id}_lane_geometry_debug_report.json",
        "lane_surface_v1_geojson": preview_dir / f"{area_id}_lane_surfaces_v1.geojson",
        "lane_surface_v1_obj": preview_dir / f"{area_id}_lane_surfaces_v1.obj",
        "lane_surface_v1_svg": preview_dir / f"{area_id}_lane_surfaces_v1.svg",
        "lane_surface_v1_report": reports / f"{area_id}_lane_surface_v1_report.json",
        "topology_qa": qa_reports / f"{area_id}_topology_repair_qa_report.json",
        "road_graph_qa": qa_reports / f"{area_id}_road_graph_qa_report.json",
        "lane_graph_qa": qa_reports / f"{area_id}_lane_graph_qa_report.json",
    }

    checks: list[dict[str, Any]] = []
    missing = [name for name, path in paths.items() if not path.exists()]
    checks.append(make_check(
        "required_outputs_exist",
        not missing,
        "All required stage outputs should exist for reproducible review.",
        missing,
    ))
    if missing:
        qa_gate = build_qa_warning_gate(stage_reports={}, audit_checks=checks)
        report = {
            "area_id": area_id,
            "stage": "pipeline_audit",
            "status": "fail",
            "checks": checks,
            "qa_gate": qa_gate,
        }
        write_json(output_path, report)
        return report

    road_graph = read_json(paths["road_graph"])
    semantics = read_json(paths["junction_semantics"])
    optimized = read_json(paths["optimized_centerlines"])
    optimized_report = read_json(paths["optimized_centerlines_report"])
    lane_graph = read_json(paths["lane_graph"])
    lane_upgrade_overrides = read_optional_json(processed / f"{area_id}_lane_upgrade_overrides.json")
    corner_candidates = read_optional_json(processed / f"{area_id}_corner_optimization_candidates.json")
    movement_corridors_path = processed / f"{area_id}_movement_corridor_candidates.json"
    movement_corridors = read_json(movement_corridors_path) if movement_corridors_path.exists() else None
    preview = read_json(paths["preview_geojson"])
    lane_surface_geojson = read_json(paths["lane_surface_v1_geojson"])
    lane_debug_report = read_json(paths["lane_geometry_debug_report"])
    lane_surface_report = read_json(paths["lane_surface_v1_report"])
    topology_qa = read_json(paths["topology_qa"])
    road_graph_qa = read_json(paths["road_graph_qa"])
    lane_graph_qa = read_json(paths["lane_graph_qa"])

    road_counts = {
        "nodes": len(road_graph.get("nodes", [])),
        "edges": len(road_graph.get("edges", [])),
    }
    checks.append(make_check(
        "road_graph_nonempty",
        road_counts["nodes"] > 0 and road_counts["edges"] > 0,
        "Road graph should expose non-empty nodes and edges.",
        road_counts,
    ))
    identity_fragmentation = road_identity_fragmentation(road_graph)
    checks.append(make_check(
        "road_identity_fragmentation_tracked",
        int(identity_fragmentation.get("touching_fragmented_road_identities") or 0) == 0,
        "Continuous source-road identity should stay visible when topology requires multiple road graph edges.",
        identity_fragmentation,
        warn=True,
    ))

    semantic_types = {junction.get("type") for junction in semantics.get("junctions", [])}
    checks.append(make_check(
        "junction_type_contract",
        semantic_types.issubset(JUNCTION_TYPES),
        "Junction semantics must stay within T/cross/Y/offset/complex.",
        sorted(semantic_types),
    ))

    allowed = {
        movement["movement_id"]
        for junction in semantics.get("junctions", [])
        for movement in junction.get("movements", [])
        if movement.get("allowed")
    }
    blocked = {
        movement["movement_id"]
        for junction in semantics.get("junctions", [])
        for movement in junction.get("movements", [])
        if not movement.get("allowed")
    }
    connection_ids = {
        connection["semantic_movement_id"]
        for junction in lane_graph.get("junctions", [])
        for connection in junction.get("connections", [])
    }
    checks.append(make_check(
        "allowed_movements_have_connections",
        allowed == connection_ids,
        "Every allowed semantic movement should become exactly one lane-level connection.",
        {
            "allowed": len(allowed),
            "connections": len(connection_ids),
            "missing": sorted(allowed - connection_ids)[:20],
            "extra": sorted(connection_ids - allowed)[:20],
        },
    ))
    checks.append(make_check(
        "blocked_movements_have_no_connections",
        not (blocked & connection_ids),
        "Blocked or one-way-disallowed movements must not create lane connections.",
        sorted(blocked & connection_ids)[:20],
    ))

    lane_ids = {lane["lane_id"] for lane in lane_graph.get("lanes", [])}
    lane_links = [
        link
        for junction in lane_graph.get("junctions", [])
        for connection in junction.get("connections", [])
        for link in connection.get("lane_links", [])
    ]
    continuity_links = list(lane_graph.get("continuity_links", []))
    micro_seam_continuity_links = [
        link
        for link in continuity_links
        if bool(link.get("micro_seam_absorbed"))
    ]
    continuity_geometry_links = [
        link
        for link in continuity_links
        if not bool(link.get("micro_seam_absorbed"))
    ]
    bad_refs = [
        link.get("lane_link_id", "")
        for link in lane_links
        if link.get("from_lane") not in lane_ids or link.get("to_lane") not in lane_ids
    ]
    bad_continuity_refs = [
        link.get("continuity_link_id", "")
        for link in continuity_links
        if link.get("from_lane") not in lane_ids or link.get("to_lane") not in lane_ids
    ]
    empty_curves = [
        link.get("lane_link_id", "")
        for link in lane_links
        if not link.get("connecting_curve_xz")
    ]
    empty_continuity_curves = [
        link.get("continuity_link_id", "")
        for link in continuity_links
        if not link.get("connecting_curve_xz")
    ]
    checks.append(make_check(
        "lane_link_references_valid",
        not bad_refs,
        "Every laneLink should reference existing from/to lanes.",
        bad_refs[:20],
    ))
    checks.append(make_check(
        "lane_link_curves_nonempty",
        not empty_curves,
        "Every laneLink should carry a connector curve.",
        empty_curves[:20],
    ))
    checks.append(make_check(
        "continuity_link_references_valid",
        not bad_continuity_refs,
        "Every corner continuity link should reference existing from/to lanes.",
        bad_continuity_refs[:20],
    ))
    checks.append(make_check(
        "continuity_link_curves_nonempty",
        not empty_continuity_curves,
        "Every corner continuity link should carry an optimized fillet curve.",
        empty_continuity_curves[:20],
    ))
    gap_metrics = lane_curve_gap_metrics(lane_graph, lane_links, continuity_links)
    max_curve_trim_gap = max(float(value) for value in gap_metrics.values())
    checks.append(make_check(
        "lane_curves_match_trimmed_lane_endpoints",
        max_curve_trim_gap <= 0.01,
        "LaneLink and corner continuity curves should start/end at the same trimmed lane endpoints used by lane surfaces.",
        gap_metrics,
    ))
    movement_endpoint_contract = movement_corridor_endpoint_contract(lane_links, movement_corridors)
    checks.append(make_check(
        "movement_corridors_match_final_lane_link_endpoints",
        movement_corridors is None or int(movement_endpoint_contract.get("stale_cases") or 0) == 0,
        "Movement corridor candidates should not drift from final laneLink endpoints; stale candidates are QA-only and must not drive final display or geometry.",
        movement_endpoint_contract,
        warn=True,
    ))

    fan_fallback_junctions = [
        junction["junction_id"]
        for junction in lane_graph.get("junctions", [])
        if junction.get("envelope_strategy") == "junction_fan_envelope"
    ]
    checks.append(make_check(
        "no_fan_fallback_in_layer3",
        not fan_fallback_junctions,
        "Layer 3 should remain semantic/lane-level and not rely on junction fan fallback.",
        fan_fallback_junctions[:20],
    ))

    optimized_types = geometry_type_counts(optimized)
    preview_types = geometry_type_counts(preview)
    optimized_coord_count = line_coordinate_count(optimized)
    preview_coord_count = line_coordinate_count(preview)
    optimized_corner_fillet_count = sum(
        1
        for feature in optimized.get("features", [])
        if (feature.get("properties") or {}).get("vc_part") == "optimized_corner_fillet"
    )
    optimized_junction_connector_count = sum(
        1
        for feature in optimized.get("features", [])
        if (feature.get("properties") or {}).get("vc_part") == "optimized_junction_connector"
    )
    lane_link_curve_source_counts: dict[str, int] = {}
    for link in lane_links:
        source = str(link.get("curve_source") or "unknown")
        lane_link_curve_source_counts[source] = lane_link_curve_source_counts.get(source, 0) + 1
    checks.append(make_check(
        "optimized_centerlines_are_lines",
        set(optimized_types) == {"LineString"},
        "Optimized centerline output should contain only LineString features.",
        optimized_types,
    ))
    checks.append(make_check(
        "preview_preserves_centerline_samples",
        preview_coord_count >= optimized_coord_count,
        "Standalone preview should preserve all optimized centerline sample points; extra render samples are allowed.",
        {
            "optimized_points": optimized_coord_count,
            "preview_points": preview_coord_count,
        },
    ))
    checks.append(make_check(
        "preview_has_no_polygons",
        set(preview_types) == {"LineString"},
        "Preview GeoJSON should be centerline-only while surfaces are deferred.",
        preview_types,
    ))
    checks.append(make_check(
        "optimized_corner_fillets_have_lane_continuity",
        optimized_corner_fillet_count == 0 or len(continuity_links) > 0,
        "Lane graph should preserve road-level rounded corner fillets as continuity links.",
        {
            "optimized_corner_fillets": optimized_corner_fillet_count,
            "continuity_links": len(continuity_links),
        },
    ))
    checks.append(make_check(
        "junction_lane_links_are_semantic_not_optimized_connectors",
        lane_link_curve_source_counts.get("optimized_junction_connector", 0) == 0
        and lane_link_curve_source_counts.get("optimized_approach_endpoint_bezier", 0) == 0,
        "T/cross/Y/merge junction laneLinks should stay on the semantic lane movement branch; optimized road connectors are reserved for the centerline skeleton.",
        {
            "optimized_junction_connectors": optimized_junction_connector_count,
            "lane_link_curve_source_counts": lane_link_curve_source_counts,
        },
    ))
    compound_guard_skips = compound_alternating_bend_guard_skips(optimized_report)
    checks.append(make_check(
        "compound_alternating_bends_are_tracked",
        not compound_guard_skips,
        "Compound alternating source/reference bends should be tracked for whole-edge review instead of accepting point-level internal bend smoothing.",
        {
            "issues": compound_guard_skips[:20],
            "issue_count": len(compound_guard_skips),
            "guard_status": COMPOUND_ALTERNATING_BEND_GUARD_STATUS,
        },
        warn=True,
    ))
    upgraded_bend_contract = unresolved_upgraded_internal_bends(
        corner_candidates,
        active_upgraded_road_ids(lane_upgrade_overrides),
    )
    checks.append(make_check(
        "upgraded_roads_no_unresolved_sharp_internal_bends",
        int(upgraded_bend_contract.get("issue_count") or 0) == 0,
        "Roads upgraded to 3+ physical lanes should not publish unresolved sharp internal centerline bends; accept reviewed smoothing or reduce the upgrade before packaging.",
        upgraded_bend_contract,
        warn=True,
    ))

    obj_lines = paths["preview_obj"].read_text(encoding="utf-8").splitlines()
    obj_vertex_count = sum(1 for line in obj_lines if line.startswith("v "))
    obj_face_count = sum(1 for line in obj_lines if line.startswith("f "))
    obj_line_count = sum(1 for line in obj_lines if line.startswith("l "))
    checks.append(make_check(
        "preview_obj_centerline_only",
        obj_face_count == 0 and obj_line_count == len(preview.get("features", [])),
        "Preview OBJ should contain line elements only, with no faces.",
        {
            "vertices": obj_vertex_count,
            "line_elements": obj_line_count,
            "faces": obj_face_count,
        },
    ))

    lane_debug_counts = lane_debug_report.get("counts", {})
    physical_lane_centerlines = lane_graph.get("physical_lane_centerlines") or []
    final_centerlines = physical_lane_centerlines if physical_lane_centerlines else lane_graph.get("lanes", [])
    low_radius_issues = low_radius_sampled_arc_issues(final_centerlines)
    checks.append(make_check(
        "final_lane_centerlines_no_low_radius_sampled_arc_runs",
        not low_radius_issues,
        "Final physical lane centerlines should not contain short low-radius sampled arc runs that create visible kink artifacts.",
        {
            "issues": low_radius_issues[:20],
            "issue_count": len(low_radius_issues),
            "min_radius_m": FINAL_LANE_CENTERLINE_LOW_RADIUS_MIN_M,
            "max_sample_segment_m": FINAL_LANE_CENTERLINE_LOW_RADIUS_MAX_SAMPLE_SEGMENT_M,
            "max_run_span_m": FINAL_LANE_CENTERLINE_LOW_RADIUS_MAX_RUN_SPAN_M,
        },
    ))
    expected_debug_centerlines = len(physical_lane_centerlines) if physical_lane_centerlines else len(lane_graph.get("lanes", []))
    actual_debug_centerlines = lane_debug_counts.get("debug_centerlines", lane_debug_counts.get("lane_centerlines"))
    lane_debug_metrics = lane_debug_report.get("metrics", {})
    expected_debug_centerline_source = "physical_lane_centerlines" if physical_lane_centerlines else "lanes"
    checks.append(make_check(
        "lane_debug_geometry_matches_lane_graph",
        lane_debug_counts.get("lanes") == len(lane_graph.get("lanes", []))
        and lane_debug_counts.get("physical_lane_centerlines", 0) == len(physical_lane_centerlines)
        and actual_debug_centerlines == expected_debug_centerlines
        and lane_debug_counts.get("lane_links") == len(lane_links)
        and lane_debug_counts.get("lane_link_curves") == len(lane_links)
        and lane_debug_counts.get("lane_link_ribbons") == len(lane_links)
        and lane_debug_counts.get("continuity_links", 0) == len(continuity_links)
        and lane_debug_counts.get("lane_continuity_curves", 0) == len(continuity_geometry_links)
        and lane_debug_counts.get("lane_continuity_ribbons", 0) == len(continuity_geometry_links)
        and lane_debug_counts.get("skipped_micro_seam_continuity_curve", 0) == len(micro_seam_continuity_links),
        "Lane debug geometry should expose the final physical centerline contract, every laneLink and every non-micro continuity curve/ribbon.",
        {
            "debug_counts": lane_debug_counts,
            "lane_graph_lanes": len(lane_graph.get("lanes", [])),
            "lane_graph_physical_lane_centerlines": len(physical_lane_centerlines),
            "expected_debug_centerlines": expected_debug_centerlines,
            "actual_debug_centerlines": actual_debug_centerlines,
            "debug_centerline_source": lane_debug_metrics.get("lane_geometry_debug_centerline_source"),
            "lane_graph_lane_links": len(lane_links),
            "lane_graph_continuity_links": len(continuity_links),
            "lane_graph_micro_seam_continuity_links": len(micro_seam_continuity_links),
            "lane_graph_rendered_continuity_links": len(continuity_geometry_links),
        },
    ))
    checks.append(make_check(
        "lane_debug_centerline_source_matches_contract",
        str(lane_debug_metrics.get("lane_geometry_debug_centerline_source") or "") == expected_debug_centerline_source,
        "Lane debug geometry should declare the same centerline source used by final lane surfaces and packages.",
        {
            "expected": expected_debug_centerline_source,
            "actual": lane_debug_metrics.get("lane_geometry_debug_centerline_source"),
        },
    ))
    checks.append(make_check(
        "lane_debug_curves_nonempty",
        int(lane_debug_metrics.get("empty_lane_link_curves", 0)) == 0
        and int(lane_debug_metrics.get("empty_continuity_curves", 0)) == 0,
        "Lane debug geometry should not contain empty laneLink or continuity curves.",
        {
            "empty_lane_link_curves": lane_debug_metrics.get("empty_lane_link_curves", 0),
            "empty_continuity_curves": lane_debug_metrics.get("empty_continuity_curves", 0),
        },
    ))
    lane_debug_obj_lines = paths["lane_geometry_debug_obj"].read_text(encoding="utf-8").splitlines()
    lane_debug_obj_stats = {
        "vertices": sum(1 for line in lane_debug_obj_lines if line.startswith("v ")),
        "line_elements": sum(1 for line in lane_debug_obj_lines if line.startswith("l ")),
        "faces": sum(1 for line in lane_debug_obj_lines if line.startswith("f ")),
    }
    checks.append(make_check(
        "lane_debug_obj_has_lines_and_faces",
        lane_debug_obj_stats["line_elements"] > 0 and lane_debug_obj_stats["faces"] > 0,
        "Lane debug OBJ should contain both centerline curves and narrow debug ribbon faces.",
        lane_debug_obj_stats,
    ))

    lane_surface_counts = lane_surface_report.get("counts", {})
    turn_surface_contract = lane_turn_surface_contract(lane_links, lane_surface_geojson)
    checks.append(make_check(
        "lane_turn_surfaces_match_final_lane_links",
        int(turn_surface_contract.get("missing_surfaces") or 0) == 0
        and int(turn_surface_contract.get("length_mismatches") or 0) == 0,
        "Lane turn surfaces should be generated from the final laneLink curves and retain their laneLink ids and curve lengths.",
        turn_surface_contract,
    ))
    expected_lane_surfaces = len(physical_lane_centerlines) if physical_lane_centerlines else len(lane_graph.get("lanes", []))
    junctions_with_lane_links = sum(
        1
        for junction in lane_graph.get("junctions", [])
        if any(
            connection.get("lane_links")
            for connection in junction.get("connections", [])
        )
    )
    checks.append(make_check(
        "lane_surface_v1_matches_lane_graph",
        lane_surface_counts.get("lane_surfaces") == expected_lane_surfaces
        and lane_surface_counts.get("lane_turn_surfaces") == len(lane_links)
        and lane_surface_counts.get("lane_continuity_surfaces", 0) == len(continuity_geometry_links)
        and lane_surface_counts.get("skipped_micro_seam_continuity_surface", 0) == len(micro_seam_continuity_links)
        and lane_surface_counts.get("junction_envelope_surfaces", 0) == junctions_with_lane_links,
        "Lane surface v1 should generate physical lane centerline, turn, non-micro continuity and junction envelope surfaces from the lane graph.",
        {
            "surface_counts": lane_surface_counts,
            "lane_graph_lanes": len(lane_graph.get("lanes", [])),
            "lane_graph_physical_lane_centerlines": len(physical_lane_centerlines),
            "expected_lane_surfaces": expected_lane_surfaces,
            "lane_graph_lane_links": len(lane_links),
            "lane_graph_continuity_links": len(continuity_links),
            "lane_graph_micro_seam_continuity_links": len(micro_seam_continuity_links),
            "lane_graph_surface_continuity_links": len(continuity_geometry_links),
            "junctions_with_lane_links": junctions_with_lane_links,
        },
    ))
    lane_surface_metrics = lane_surface_report.get("metrics", {})
    checks.append(make_check(
        "junction_envelope_surfaces_have_area",
        lane_surface_counts.get("junction_envelope_surfaces", 0) == junctions_with_lane_links
        and float(lane_surface_metrics.get("avg_junction_envelope_area_m2") or 0.0) > 0.0
        and float(lane_surface_metrics.get("max_junction_envelope_area_m2") or 0.0) > 0.0,
        "Every junction with laneLinks should publish a non-empty conservative envelope surface.",
        {
            "junction_envelope_surfaces": lane_surface_counts.get("junction_envelope_surfaces", 0),
            "junctions_with_lane_links": junctions_with_lane_links,
            "avg_junction_envelope_area_m2": lane_surface_metrics.get("avg_junction_envelope_area_m2", 0.0),
            "max_junction_envelope_area_m2": lane_surface_metrics.get("max_junction_envelope_area_m2", 0.0),
        },
    ))
    lane_surface_obj_lines = paths["lane_surface_v1_obj"].read_text(encoding="utf-8").splitlines()
    lane_surface_obj_stats = {
        "vertices": sum(1 for line in lane_surface_obj_lines if line.startswith("v ")),
        "faces": sum(1 for line in lane_surface_obj_lines if line.startswith("f ")),
    }
    checks.append(make_check(
        "lane_surface_v1_obj_has_faces",
        lane_surface_obj_stats["faces"] == lane_surface_counts.get("obj_faces", 0)
        and lane_surface_obj_stats["faces"] > 0,
        "Lane surface v1 OBJ should contain surface faces.",
        lane_surface_obj_stats,
    ))

    houdini_build = (root / "scripts" / "houdini_build_road_test.py").read_text(encoding="utf-8")
    houdini_open = (root / "scripts" / "houdini_cook_open_session.py").read_text(encoding="utf-8")
    houdini_contract_ok = all(
        token in script
        for script in (houdini_build, houdini_open)
        for token in (
            "resolve_latest_houdini_package",
            "python_import_standard_lanes",
            "standard_lanes_path",
            "standard_junctions_path",
            "standard_lane_surfaces_path",
            "OUT_roads_centerlines",
            "OUT_lane_connections_debug",
            "OUT_lane_surfaces_v1",
            "out_node.setInput(0, centerline_node)",
            "out_node.setDisplayFlag(True)",
        )
    )
    checks.append(make_check(
        "houdini_default_output_manifest_driven",
        houdini_contract_ok,
        "Houdini default output should resolve the latest LaneForge package manifest and read package standard outputs only.",
        houdini_contract_ok,
    ))

    qa_statuses = {
        "topology_repair": topology_qa.get("status"),
        "road_graph": road_graph_qa.get("status"),
        "lane_graph": lane_graph_qa.get("status"),
    }
    checks.append(make_check(
        "qa_reports_have_no_failures",
        all(status != "fail" for status in qa_statuses.values()),
        "Stage QA reports should have no failures; warnings are tiered by the QA publish gate.",
        qa_statuses,
    ))
    qa_gate = build_qa_warning_gate(
        stage_reports={
            "topology_repair": topology_qa,
            "road_graph": road_graph_qa,
            "lane_graph": lane_graph_qa,
        },
        audit_checks=checks,
    )

    metrics = {
        "road_graph": road_counts,
        "road_identity_fragmentation": identity_fragmentation,
        "junctions": len(semantics.get("junctions", [])),
        "allowed_movements": len(allowed),
        "blocked_movements": len(blocked),
        "lanes": len(lane_graph.get("lanes", [])),
        "lane_connections": len(connection_ids),
        "lane_links": len(lane_links),
        "continuity_links": len(continuity_links),
        "micro_seam_continuity_links": len(micro_seam_continuity_links),
        "surface_continuity_links": len(continuity_geometry_links),
        "lane_curve_gap_metrics": gap_metrics,
        "lane_link_curve_source_counts": lane_link_curve_source_counts,
        "optimized_features": len(optimized.get("features", [])),
        "optimized_corner_fillets": optimized_corner_fillet_count,
        "optimized_junction_connectors": optimized_junction_connector_count,
        "compound_alternating_bend_guard_skips": len(compound_guard_skips),
        "unresolved_upgraded_internal_bends": int(upgraded_bend_contract.get("issue_count") or 0),
        "optimized_points": optimized_coord_count,
        "preview_points": preview_coord_count,
        "preview_obj_vertices": obj_vertex_count,
        "lane_debug_obj_vertices": lane_debug_obj_stats["vertices"],
        "lane_debug_obj_faces": lane_debug_obj_stats["faces"],
        "lane_surface_v1_obj_vertices": lane_surface_obj_stats["vertices"],
        "lane_surface_v1_obj_faces": lane_surface_obj_stats["faces"],
        "junction_envelope_surfaces": lane_surface_counts.get("junction_envelope_surfaces", 0),
        "qa_statuses": qa_statuses,
        "qa_gate_status": qa_gate.get("status"),
        "qa_warning_summary": qa_gate.get("summary", {}),
    }
    report = {
        "area_id": area_id,
        "stage": "pipeline_audit",
        "status": worst_status(checks),
        "checks": checks,
        "qa_warning_severity_policy": {
            "policy_id": QA_WARNING_SEVERITY_POLICY_ID,
            "tiers": list(QA_WARNING_TIERS),
            "default_warn_tier": "publishable_warn",
        },
        "qa_gate": qa_gate,
        "metrics": metrics,
        "inputs": {name: str(path) for name, path in paths.items()},
        "next_action": "Use this audit as the automated gate before curb, island, marking and swept-envelope geometry.",
    }
    write_json(output_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit road_test_pipeline stage contracts.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    output_path = Path(args.output) if args.output else root / "reports" / f"{args.area_id}_pipeline_audit_report.json"
    report = audit(root, args.area_id, output_path)
    print(json.dumps({
        "area_id": args.area_id,
        "status": report["status"],
        "qa_gate_status": (report.get("qa_gate") or {}).get("status"),
        "qa_warning_summary": (report.get("qa_gate") or {}).get("summary", {}),
        "output": str(output_path),
        "metrics": report.get("metrics", {}),
        "failed_or_warn_checks": [
            check
            for check in report["checks"]
            if check["status"] != "pass"
        ],
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] != "fail" else 2


if __name__ == "__main__":
    raise SystemExit(main())
