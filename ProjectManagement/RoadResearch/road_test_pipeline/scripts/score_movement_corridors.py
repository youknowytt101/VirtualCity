#!/usr/bin/env python3
"""Score movement corridor candidates without writing back geometry.

This is L8.6: a non-destructive QA scoring layer. It consumes the staged
movement corridor artifacts and writes a separate scoring artifact; it does not
modify lane_graph, movement_corridor_candidates, compound transactions, or the
clean skeleton.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import optimize_junction_centerlines as oc


SAMPLE_SPACING_M = 1.5
MIN_SAMPLE_COUNT = 5
MAX_SAMPLE_COUNT = 36
SCORING_READY_MIN = 70.0


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def rounded(value: float) -> float:
    return round(float(value), 3)


def point_xz(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, list) or len(value) < 2:
        return None
    return float(value[0]), float(value[1])


def points_xz(values: Any) -> list[tuple[float, float]]:
    if not isinstance(values, list):
        return []
    points: list[tuple[float, float]] = []
    for value in values:
        point = point_xz(value)
        if point is not None:
            points.append(point)
    return points


def sample_polyline(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(points) < 2:
        return points
    length = max(oc.polyline_length(points), 0.001)
    sample_count = max(MIN_SAMPLE_COUNT, min(MAX_SAMPLE_COUNT, int(length / SAMPLE_SPACING_M) + 1))
    samples: list[tuple[float, float]] = []
    targets = [length * index / (sample_count - 1) for index in range(sample_count)]
    segment_start = points[0]
    segment_index = 0
    walked = 0.0
    for target in targets:
        while segment_index < len(points) - 1:
            segment_end = points[segment_index + 1]
            segment_length = oc.distance(segment_start, segment_end)
            if walked + segment_length >= target or segment_length <= 1e-9:
                break
            walked += segment_length
            segment_index += 1
            segment_start = points[segment_index]
        segment_end = points[min(segment_index + 1, len(points) - 1)]
        segment_length = max(oc.distance(segment_start, segment_end), 1e-9)
        t = max(0.0, min(1.0, (target - walked) / segment_length))
        samples.append((
            segment_start[0] + (segment_end[0] - segment_start[0]) * t,
            segment_start[1] + (segment_end[1] - segment_start[1]) * t,
        ))
    return samples


def point_segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    vx = end[0] - start[0]
    vz = end[1] - start[1]
    denom = vx * vx + vz * vz
    if denom <= 1e-9:
        return oc.distance(point, start)
    t = ((point[0] - start[0]) * vx + (point[1] - start[1]) * vz) / denom
    t = max(0.0, min(1.0, t))
    projection = (start[0] + vx * t, start[1] + vz * t)
    return oc.distance(point, projection)


def point_polyline_distance(point: tuple[float, float], line: list[tuple[float, float]]) -> float:
    if not line:
        return 999999.0
    if len(line) == 1:
        return oc.distance(point, line[0])
    return min(point_segment_distance(point, line[index], line[index + 1]) for index in range(len(line) - 1))


def curvature_reversal_count(points: list[tuple[float, float]]) -> int:
    signs: list[int] = []
    for index in range(1, len(points) - 1):
        a = points[index - 1]
        b = points[index]
        c = points[index + 1]
        value = oc.cross((b[0] - a[0], b[1] - a[1]), (c[0] - b[0], c[1] - b[1]))
        if abs(value) > 1e-6:
            signs.append(1 if value > 0.0 else -1)
    return sum(1 for index in range(1, len(signs)) if signs[index] != signs[index - 1])


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


def self_intersects(points: list[tuple[float, float]]) -> bool:
    if len(points) < 4:
        return False
    for first in range(len(points) - 1):
        for second in range(first + 2, len(points) - 1):
            if first == 0 and second == len(points) - 2:
                continue
            if segment_intersection(points[first], points[first + 1], points[second], points[second + 1]):
                return True
    return False


def lane_index(lane_graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for lane in lane_graph.get("lanes", []):
        lane_id = str(lane.get("lane_id") or "")
        if not lane_id:
            continue
        indexed[lane_id] = {
            "lane_id": lane_id,
            "edge_id": str(lane.get("edge_id") or ""),
            "road_class": str(lane.get("road_class") or "residential"),
            "width_m": float(lane.get("width_m") or 3.2),
            "centerline_xz": points_xz(lane.get("centerline_xz") or []),
        }
    return indexed


def design_min_radius(case: dict[str, Any], lanes_by_id: dict[str, dict[str, Any]], corridor_width_m: float) -> float:
    if str(case.get("movement_kind") or "") == "through":
        return 0.0
    classes = []
    for lane_id in (str(case.get("from_lane_id") or ""), str(case.get("to_lane_id") or "")):
        lane = lanes_by_id.get(lane_id)
        if lane:
            classes.append(str(lane.get("road_class") or "residential"))
    class_min = max((oc.JUNCTION_TURN_MIN_RADIUS_BY_CLASS.get(value, 6.0) for value in classes), default=6.0)
    return max(class_min, corridor_width_m * 1.5)


def excluded_lane_sets(case: dict[str, Any]) -> tuple[set[str], set[str]]:
    lane_ids = {
        str(case.get("from_lane_id") or ""),
        str(case.get("to_lane_id") or ""),
        str(case.get("internal_bridge_lane_id") or ""),
    }
    edge_ids = {
        str(case.get("from_edge_id") or ""),
        str(case.get("to_edge_id") or ""),
    }
    for edge_id in case.get("internal_bridge_edge_ids") or []:
        edge_ids.add(str(edge_id))
    lane_ids.discard("")
    edge_ids.discard("")
    return lane_ids, edge_ids


def clearance_to_non_target_lanes(
    samples: list[tuple[float, float]],
    case: dict[str, Any],
    lanes_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    excluded_lanes, excluded_edges = excluded_lane_sets(case)
    min_clearance = 999999.0
    closest_lane_id = ""
    lane_checks = 0
    for lane in lanes_by_id.values():
        if lane["lane_id"] in excluded_lanes or lane["edge_id"] in excluded_edges:
            continue
        line = lane["centerline_xz"]
        if len(line) < 2:
            continue
        lane_checks += 1
        for sample in samples:
            clearance = point_polyline_distance(sample, line)
            if clearance < min_clearance:
                min_clearance = clearance
                closest_lane_id = lane["lane_id"]
    if min_clearance > 999998.0:
        min_clearance = 0.0
    return {
        "min_non_target_lane_clearance_m": rounded(min_clearance),
        "closest_non_target_lane_id": closest_lane_id,
        "non_target_lanes_checked": lane_checks,
    }


def score_candidate(
    *,
    case: dict[str, Any],
    candidate: dict[str, Any],
    source_kind: str,
    lanes_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    points = points_xz(candidate.get("centerline_xz") or [])
    samples = sample_polyline(points)
    corridor_width_m = float(case.get("corridor_width_m") or 4.0)
    envelope_half_width_m = corridor_width_m * 0.5
    clearance_threshold_m = envelope_half_width_m + 0.4
    clearance = clearance_to_non_target_lanes(samples, case, lanes_by_id)
    min_clearance = float(clearance["min_non_target_lane_clearance_m"])

    min_radius_m = float(candidate.get("min_radius_proxy_m") or 0.0)
    if min_radius_m <= 0.0 and len(points) >= 3:
        min_radius_m = oc.polyline_min_radius(points)
    radius_threshold_m = design_min_radius(case, lanes_by_id, corridor_width_m)
    reversals = curvature_reversal_count(points)
    intersects = self_intersects(points)

    issues = [str(issue) for issue in candidate.get("issues") or []]
    scoring_issues: list[str] = []
    if min_clearance < envelope_half_width_m:
        scoring_issues.append("collision_risk_non_target_lane_centerline")
    elif min_clearance < clearance_threshold_m:
        scoring_issues.append("swept_envelope_margin_low")
    if radius_threshold_m > 0.0 and (min_radius_m <= 0.0 or min_radius_m < radius_threshold_m):
        scoring_issues.append("curvature_radius_below_scoring_min")
    if reversals > 0:
        scoring_issues.append("curvature_reversal")
    if intersects:
        scoring_issues.append("self_intersection")

    if min_clearance >= clearance_threshold_m:
        collision_score = 100.0
    elif min_clearance >= envelope_half_width_m:
        collision_score = 72.0 + (min_clearance - envelope_half_width_m) / max(0.001, clearance_threshold_m - envelope_half_width_m) * 28.0
    else:
        collision_score = max(0.0, min_clearance / max(0.001, envelope_half_width_m) * 72.0)

    swept_envelope_score = max(0.0, min(100.0, min_clearance / max(0.001, clearance_threshold_m) * 100.0))

    if radius_threshold_m <= 0.0:
        curvature_score = 100.0 if reversals == 0 else max(55.0, 100.0 - reversals * 12.0)
    elif min_radius_m <= 0.0:
        curvature_score = 35.0
    else:
        curvature_score = max(0.0, min(100.0, min_radius_m / radius_threshold_m * 100.0))
        curvature_score = max(0.0, curvature_score - reversals * 10.0)

    if intersects:
        collision_score = 0.0
        swept_envelope_score = 0.0
        curvature_score = 0.0

    overall_score = collision_score * 0.38 + swept_envelope_score * 0.32 + curvature_score * 0.30
    status = "scored_qa_candidate" if overall_score >= SCORING_READY_MIN and not intersects else "needs_review"

    return {
        "source_kind": source_kind,
        "case_id": str(case.get("corridor_id") or case.get("compound_case_id") or ""),
        "candidate_family": str(candidate.get("family") or ""),
        "status": status,
        "publish_ready": False,
        "overall_score": rounded(overall_score),
        "collision_score": rounded(collision_score),
        "swept_envelope_score": rounded(swept_envelope_score),
        "curvature_score": rounded(curvature_score),
        "metrics": {
            "length_m": rounded(float(candidate.get("length_m") or oc.polyline_length(points))),
            "sample_count": len(samples),
            "corridor_width_m": rounded(corridor_width_m),
            "envelope_half_width_m": rounded(envelope_half_width_m),
            "clearance_threshold_m": rounded(clearance_threshold_m),
            "min_radius_m": rounded(min_radius_m),
            "radius_threshold_m": rounded(radius_threshold_m),
            "curvature_reversal_count": reversals,
            "self_intersection": intersects,
            **clearance,
        },
        "issues": issues,
        "scoring_issues": scoring_issues,
        "score_contract": (
            "qa_score_only_non_destructive（仅质检评分，非破坏式）; not final geometry publish decision"
            "（不是最终几何发布判定）"
        ),
    }


def score_case(case: dict[str, Any], source_kind: str, lanes_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    candidate_scores = [
        score_candidate(case=case, candidate=candidate, source_kind=source_kind, lanes_by_id=lanes_by_id)
        for candidate in case.get("candidates", [])
        if isinstance(candidate, dict)
    ]
    candidate_scores.sort(key=lambda item: float(item["overall_score"]), reverse=True)
    best = candidate_scores[0] if candidate_scores else None
    return {
        "source_kind": source_kind,
        "case_id": str(case.get("corridor_id") or case.get("compound_case_id") or ""),
        "movement_kind": str(case.get("movement_kind") or ""),
        "from_lane_id": str(case.get("from_lane_id") or ""),
        "to_lane_id": str(case.get("to_lane_id") or ""),
        "source_status": str(case.get("status") or ""),
        "source_confidence": float(case.get("confidence") or 0.0),
        "source_best_candidate_family": str(case.get("best_candidate_family") or ""),
        "best_scored_family": str(best["candidate_family"]) if best else "",
        "best_overall_score": float(best["overall_score"]) if best else 0.0,
        "best_status": str(best["status"]) if best else "missing_candidates",
        "candidate_scores": candidate_scores,
        "issues": [str(issue) for issue in case.get("issues") or []],
    }


def score_document(
    *,
    area_id: str,
    lane_graph: dict[str, Any],
    movement_corridors: dict[str, Any],
    compound_transactions: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    lanes_by_id = lane_index(lane_graph)
    cases = [
        score_case(case, "movement_corridor", lanes_by_id)
        for case in movement_corridors.get("cases", [])
    ]
    all_cases = cases
    all_candidates = [candidate for case in all_cases for candidate in case["candidate_scores"]]
    issue_counts = Counter(issue for candidate in all_candidates for issue in candidate["scoring_issues"])
    family_counts = Counter(candidate["candidate_family"] for candidate in all_candidates)
    best_family_counts = Counter(case["best_scored_family"] for case in all_cases if case["best_scored_family"])
    status_counts = Counter(candidate["status"] for candidate in all_candidates)
    scores = [float(candidate["overall_score"]) for candidate in all_candidates]
    ready_cases = sum(1 for case in all_cases if case["best_status"] == "scored_qa_candidate")
    collision_risk_candidates = int(issue_counts.get("collision_risk_non_target_lane_centerline", 0))
    swept_margin_candidates = int(issue_counts.get("swept_envelope_margin_low", 0))
    curvature_risk_candidates = int(issue_counts.get("curvature_radius_below_scoring_min", 0))
    metrics = {
        "cases_scored": len(all_cases),
        "movement_cases_scored": len(cases),
        "candidate_scores": len(all_candidates),
        "reference_errors": 0,
        "scored_candidate_ratio": rounded(len(all_candidates) / max(1, len(all_cases) * 3)),
        "qa_ready_cases": ready_cases,
        "qa_ready_case_ratio": rounded(ready_cases / max(1, len(all_cases))),
        "collision_risk_candidate_ratio": rounded(collision_risk_candidates / max(1, len(all_candidates))),
        "swept_margin_candidate_ratio": rounded(swept_margin_candidates / max(1, len(all_candidates))),
        "curvature_risk_candidate_ratio": rounded(curvature_risk_candidates / max(1, len(all_candidates))),
        "avg_overall_score": rounded(sum(scores) / max(1, len(scores))),
        "min_overall_score": rounded(min(scores) if scores else 0.0),
        "max_overall_score": rounded(max(scores) if scores else 0.0),
        "candidate_family_counts": dict(sorted(family_counts.items())),
        "best_scored_family_counts": dict(sorted(best_family_counts.items())),
        "candidate_status_counts": dict(sorted(status_counts.items())),
        "scoring_issue_counts": dict(sorted(issue_counts.items())),
        "publish_ready_candidates": 0,
        "destructive_writeback_ready": False,
    }
    scoring_doc = {
        "type": "FeatureCollection",
        "metadata": {
            "area_id": area_id,
            "schema": "road_test_pipeline.movement_corridor_scoring.v1",
            "stage": "movement_corridor_scoring",
            "contract": "non_destructive_qa_scoring（非破坏式质检评分）",
        },
        "cases": all_cases,
    }
    report_status = "warn" if issue_counts or ready_cases < len(all_cases) else "pass"
    report = {
        "area_id": area_id,
        "stage": "movement_corridor_scoring_v1",
        "status": report_status,
        "metrics": metrics,
        "next_action": (
            "Review low scoring movement corridors（通行走廊） in the SVG viewer（SVG 查看器） "
            "before any destructive writeback（写入式回写）."
        ),
    }
    return scoring_doc, report


def compact_candidate_score(candidate: dict[str, Any]) -> dict[str, Any]:
    metrics = candidate.get("metrics") or {}
    return {
        "candidate_family": str(candidate.get("candidate_family") or ""),
        "status": str(candidate.get("status") or ""),
        "overall_score": float(candidate.get("overall_score") or 0.0),
        "collision_score": float(candidate.get("collision_score") or 0.0),
        "swept_envelope_score": float(candidate.get("swept_envelope_score") or 0.0),
        "curvature_score": float(candidate.get("curvature_score") or 0.0),
        "min_radius_m": metrics.get("min_radius_m", 0.0),
        "radius_threshold_m": metrics.get("radius_threshold_m", 0.0),
        "min_non_target_lane_clearance_m": metrics.get("min_non_target_lane_clearance_m", 0.0),
        "closest_non_target_lane_id": str(metrics.get("closest_non_target_lane_id") or ""),
        "curvature_reversal_count": metrics.get("curvature_reversal_count", 0),
        "self_intersection": bool(metrics.get("self_intersection", False)),
        "scoring_issues": [str(issue) for issue in candidate.get("scoring_issues") or []],
        "issues": [str(issue) for issue in candidate.get("issues") or []],
    }


def build_viewer_document(scoring_doc: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for case in scoring_doc.get("cases", []):
        compact_scores = [compact_candidate_score(candidate) for candidate in case.get("candidate_scores", [])]
        best_family = str(case.get("best_scored_family") or "")
        best_candidate = next(
            (candidate for candidate in compact_scores if candidate["candidate_family"] == best_family),
            compact_scores[0] if compact_scores else {},
        )
        cases.append({
            "source_kind": str(case.get("source_kind") or ""),
            "case_id": str(case.get("case_id") or ""),
            "movement_kind": str(case.get("movement_kind") or ""),
            "from_lane_id": str(case.get("from_lane_id") or ""),
            "to_lane_id": str(case.get("to_lane_id") or ""),
            "source_status": str(case.get("source_status") or ""),
            "source_confidence": float(case.get("source_confidence") or 0.0),
            "source_best_candidate_family": str(case.get("source_best_candidate_family") or ""),
            "best_scored_family": best_family,
            "best_overall_score": float(case.get("best_overall_score") or 0.0),
            "best_status": str(case.get("best_status") or ""),
            "best_candidate": best_candidate,
            "candidate_scores": compact_scores,
            "issues": [str(issue) for issue in case.get("issues") or []],
        })

    low_score_cases = sorted(cases, key=lambda item: float(item.get("best_overall_score") or 0.0))[:40]
    return {
        "type": "movement_corridor_scoring_viewer",
        "metadata": {
            **scoring_doc.get("metadata", {}),
            "schema": "road_test_pipeline.movement_corridor_scoring_viewer.v1",
            "contract": "viewer_sidecar_for_svg_inspector（SVG 检查器旁路数据）",
        },
        "metrics": report.get("metrics", {}),
        "cases": cases,
        "low_score_cases": [
            {
                "case_id": str(case.get("case_id") or ""),
                "source_kind": str(case.get("source_kind") or ""),
                "movement_kind": str(case.get("movement_kind") or ""),
                "best_overall_score": float(case.get("best_overall_score") or 0.0),
                "best_scored_family": str(case.get("best_scored_family") or ""),
                "best_status": str(case.get("best_status") or ""),
            }
            for case in low_score_cases
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Score movement corridor candidates.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--lane-graph", default="")
    parser.add_argument("--movement-corridors", default="")
    parser.add_argument("--compound-transactions", default="", help="Deprecated no-op; compound corridor scoring is no longer included.")
    parser.add_argument("--output", default="")
    parser.add_argument("--report", default="")
    parser.add_argument("--viewer-output", default="")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    processed = root / "data" / "processed"
    reports = root / "reports"
    lane_graph_path = Path(args.lane_graph) if args.lane_graph else processed / f"{args.area_id}_lane_graph.json"
    movement_corridors_path = (
        Path(args.movement_corridors)
        if args.movement_corridors
        else processed / f"{args.area_id}_movement_corridor_candidates.json"
    )
    output_path = Path(args.output) if args.output else processed / f"{args.area_id}_movement_corridor_scoring.json"
    report_path = Path(args.report) if args.report else reports / f"{args.area_id}_movement_corridor_scoring_report.json"
    viewer_output_path = (
        Path(args.viewer_output)
        if args.viewer_output
        else reports / "visualizations" / f"{args.area_id}_movement_corridor_scoring_viewer.json"
    )

    scoring_doc, report = score_document(
        area_id=args.area_id,
        lane_graph=read_json(lane_graph_path),
        movement_corridors=read_json(movement_corridors_path),
        compound_transactions=None,
    )
    report["inputs"] = {
        "lane_graph": str(lane_graph_path),
        "movement_corridors": str(movement_corridors_path),
    }
    report["outputs"] = {
        "scoring": str(output_path),
        "report": str(report_path),
        "viewer_scoring": str(viewer_output_path),
    }
    viewer_doc = build_viewer_document(scoring_doc, report)
    write_json(output_path, scoring_doc)
    write_json(report_path, report)
    write_json(viewer_output_path, viewer_doc)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
