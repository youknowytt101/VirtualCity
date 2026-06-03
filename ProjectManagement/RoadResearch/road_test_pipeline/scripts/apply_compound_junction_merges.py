#!/usr/bin/env python3
"""Trial compound junction merge transactions.

This stage is a transactional preview. It consumes compound junction merge
candidates, composes lane-level movements across internal bridge edges, and
emits compound movement corridor candidates. It does not mutate road_graph,
junction_areas, optimized centerlines, clean skeleton, or Houdini geometry.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from solve_movement_corridors import (
    LANE_LEVEL_ANCHOR_SOURCES,
    angle_between_deg,
    candidate_record,
    cubic_bezier,
    distance,
    lane_anchor,
    planned_pose_index,
    pose_index,
    rounded,
)


SAMPLES = 17
TRANSACTION_SOURCE = "compound_junction_merge_trial_transaction"
MAX_COMPOUND_CORRIDOR_LENGTH_M = 80.0


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def lane_index(lane_graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(lane.get("lane_id") or ""): lane for lane in lane_graph.get("lanes", [])}


def lane_edge_id(lanes: dict[str, dict[str, Any]], lane_id: str) -> str:
    return str((lanes.get(lane_id) or {}).get("edge_id") or "")


def round_point(point: tuple[float, float]) -> list[float]:
    return [rounded(point[0]), rounded(point[1])]


def turn_kind_from_tangents(start_tangent: tuple[float, float], end_tangent: tuple[float, float]) -> str:
    delta = angle_between_deg(start_tangent, end_tangent)
    if delta <= 35.0:
        return "through"
    cross = start_tangent[0] * end_tangent[1] - start_tangent[1] * end_tangent[0]
    return "left" if cross > 0.0 else "right"


def link_side_records(
    *,
    candidate: dict[str, Any],
    lane_graph: dict[str, Any],
    lanes: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    bridge_edges = {str(edge_id) for edge_id in candidate.get("bridge_edge_ids") or []}
    member_nodes = {str(node_id) for node_id in candidate.get("member_junction_node_ids") or []}
    incoming_to_bridge: list[dict[str, Any]] = []
    bridge_to_outgoing: list[dict[str, Any]] = []
    reference_errors = 0

    for link in lane_graph.get("lane_links", []):
        if str(link.get("link_kind") or "") != "junction_movement":
            continue
        node_id = str(link.get("node_id") or "")
        if node_id not in member_nodes:
            continue
        from_lane_id = str(link.get("from_lane_id") or "")
        to_lane_id = str(link.get("to_lane_id") or "")
        from_edge = lane_edge_id(lanes, from_lane_id)
        to_edge = lane_edge_id(lanes, to_lane_id)
        if not from_edge or not to_edge:
            reference_errors += 1
            continue
        from_is_bridge = from_edge in bridge_edges
        to_is_bridge = to_edge in bridge_edges
        if from_is_bridge and to_is_bridge:
            continue
        if not from_is_bridge and to_is_bridge:
            incoming_to_bridge.append({"link": link, "bridge_lane_id": to_lane_id, "external_lane_id": from_lane_id})
        elif from_is_bridge and not to_is_bridge:
            bridge_to_outgoing.append({"link": link, "bridge_lane_id": from_lane_id, "external_lane_id": to_lane_id})

    return incoming_to_bridge, bridge_to_outgoing, reference_errors


def compose_trial_case(
    *,
    case_index: int,
    candidate: dict[str, Any],
    entry_record: dict[str, Any],
    exit_record: dict[str, Any],
    lanes: dict[str, dict[str, Any]],
    poses: dict[tuple[str, str], dict[str, Any]],
    planned_poses: dict[tuple[str, str], dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[str]]:
    entry_link = entry_record["link"]
    exit_link = exit_record["link"]
    from_lane = lanes.get(str(entry_link.get("from_lane_id") or ""))
    to_lane = lanes.get(str(exit_link.get("to_lane_id") or ""))
    if not from_lane or not to_lane:
        return None, ["missing_external_lane_reference"]

    entry_node_id = str(entry_link.get("node_id") or "")
    exit_node_id = str(exit_link.get("node_id") or "")
    entry_anchor, start, start_tangent, start_endpoint_issues, entry_anchor_issues = lane_anchor(
        role="entry",
        lane=from_lane,
        node_id=entry_node_id,
        poses=poses,
        planned_poses=planned_poses,
    )
    exit_anchor, end, end_tangent, end_endpoint_issues, exit_anchor_issues = lane_anchor(
        role="exit",
        lane=to_lane,
        node_id=exit_node_id,
        poses=poses,
        planned_poses=planned_poses,
    )

    issues = [
        str(issue)
        for issue in (
            list(entry_link.get("issues") or [])
            + list(exit_link.get("issues") or [])
            + start_endpoint_issues
            + entry_anchor_issues
            + exit_anchor_issues
            + end_endpoint_issues
        )
    ]
    issues.append("compound_junction_merge_trial")
    if str((from_lane.get("sources") or {}).get("turn_lanes") or "") == "missing":
        issues.append("inferred_without_turn_lanes")
    if str((to_lane.get("sources") or {}).get("turn_lanes") or "") == "missing":
        issues.append("outgoing_turn_lanes_missing")

    confidence = min(
        float(entry_link.get("confidence") or 0.0),
        float(exit_link.get("confidence") or 0.0),
        float(from_lane.get("overall_confidence") or 0.0),
        float(to_lane.get("overall_confidence") or 0.0),
    )
    chord = distance(start, end)
    if chord > MAX_COMPOUND_CORRIDOR_LENGTH_M:
        issues.append("compound_corridor_too_long")

    bridge_lane_id = str(entry_record.get("bridge_lane_id") or "")
    if bridge_lane_id != str(exit_record.get("bridge_lane_id") or ""):
        issues.append("bridge_lane_mismatch")
    movement_kind = turn_kind_from_tangents(start_tangent, end_tangent)
    baseline = [start, end]
    bezier = cubic_bezier(start, start_tangent, end, end_tangent, 0.35, samples=SAMPLES)
    param_poly3_proxy = cubic_bezier(start, start_tangent, end, end_tangent, 0.5, samples=SAMPLES)
    candidates = [
        candidate_record(family="compound_topology_straight_baseline", points=baseline, confidence=confidence, base_issues=issues),
        candidate_record(family="compound_bezier_g1_preview", points=bezier, confidence=confidence, base_issues=issues),
        candidate_record(family="compound_param_poly3_hermite_proxy", points=param_poly3_proxy, confidence=confidence, base_issues=issues),
    ]
    best = max(candidates, key=lambda item: float(item["score"]))
    anchor_sources = {
        str(entry_anchor.get("source") or ""),
        str(exit_anchor.get("source") or ""),
    }
    case_status = "trial_candidate"
    if not anchor_sources.issubset(LANE_LEVEL_ANCHOR_SOURCES):
        case_status = "blocked"
        issues.append("missing_lane_level_anchor")
    if best["issues"]:
        case_status = "qa_candidate" if case_status != "blocked" else case_status

    case = {
        "compound_case_id": f"cmc_{case_index:05d}",
        "candidate_id": str(candidate.get("candidate_id") or ""),
        "source": TRANSACTION_SOURCE,
        "entry_lane_link_id": str(entry_link.get("lane_link_id") or ""),
        "exit_lane_link_id": str(exit_link.get("lane_link_id") or ""),
        "internal_bridge_lane_id": bridge_lane_id,
        "internal_bridge_edge_ids": [str(edge_id) for edge_id in candidate.get("bridge_edge_ids") or []],
        "entry_junction_node_id": entry_node_id,
        "exit_junction_node_id": exit_node_id,
        "member_junction_node_ids": [str(node_id) for node_id in candidate.get("member_junction_node_ids") or []],
        "from_lane_id": str(from_lane.get("lane_id") or ""),
        "to_lane_id": str(to_lane.get("lane_id") or ""),
        "from_edge_id": str(from_lane.get("edge_id") or ""),
        "to_edge_id": str(to_lane.get("edge_id") or ""),
        "movement_kind": movement_kind,
        "status": case_status,
        "confidence": rounded(confidence),
        "start_xz": round_point(start),
        "end_xz": round_point(end),
        "start_tangent_xz": round_point(start_tangent),
        "end_tangent_xz": round_point(end_tangent),
        "lane_entry_anchor": entry_anchor,
        "lane_exit_anchor": exit_anchor,
        "chord_length_m": rounded(chord),
        "tangent_delta_deg": rounded(angle_between_deg(start_tangent, end_tangent)),
        "best_candidate_family": str(best["family"]),
        "best_score": float(best["score"]),
        "publish_ready": False,
        "candidates": candidates,
        "issues": sorted(set(issues)),
        "transaction_contract": (
            "Trial-only compound movement（仅试运行复合通行）. Bridge edge anchors（桥接短边锚点） "
            "are removed from the exposed entry/exit contract, but clean skeleton（干净道路骨架） is not modified."
        ),
    }
    return case, []


def apply_compound_merges(
    *,
    area_id: str,
    compound_candidates: dict[str, Any],
    lane_graph: dict[str, Any],
    engineering_reference: dict[str, Any],
    short_edge_absorptions: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    lanes = lane_index(lane_graph)
    poses = pose_index(engineering_reference)
    planned_poses = planned_pose_index(short_edge_absorptions or {})
    transactions: list[dict[str, Any]] = []
    compound_cases: list[dict[str, Any]] = []
    reference_errors = 0
    composition_errors: Counter[str] = Counter()

    for candidate in compound_candidates.get("candidates", []):
        candidate_id = str(candidate.get("candidate_id") or "")
        if str(candidate.get("status") or "") != "transaction_candidate":
            transactions.append({
                "candidate_id": candidate_id,
                "status": "skipped",
                "reason": "candidate_not_transaction_candidate",
                "cases": [],
            })
            continue

        incoming_to_bridge, bridge_to_outgoing, link_reference_errors = link_side_records(
            candidate=candidate,
            lane_graph=lane_graph,
            lanes=lanes,
        )
        reference_errors += link_reference_errors
        candidate_cases: list[dict[str, Any]] = []
        candidate_errors: Counter[str] = Counter()
        for entry_record in incoming_to_bridge:
            for exit_record in bridge_to_outgoing:
                if str(entry_record.get("bridge_lane_id") or "") != str(exit_record.get("bridge_lane_id") or ""):
                    continue
                entry_node = str((entry_record.get("link") or {}).get("node_id") or "")
                exit_node = str((exit_record.get("link") or {}).get("node_id") or "")
                if entry_node == exit_node:
                    continue
                case, errors = compose_trial_case(
                    case_index=len(compound_cases),
                    candidate=candidate,
                    entry_record=entry_record,
                    exit_record=exit_record,
                    lanes=lanes,
                    poses=poses,
                    planned_poses=planned_poses,
                )
                if case is None:
                    candidate_errors.update(errors)
                    composition_errors.update(errors)
                    continue
                candidate_cases.append(case)
                compound_cases.append(case)

        exposed_bridge_cases = [
            case for case in candidate_cases
            if str(case.get("from_edge_id") or "") in set(candidate.get("bridge_edge_ids") or [])
            or str(case.get("to_edge_id") or "") in set(candidate.get("bridge_edge_ids") or [])
        ]
        capacity_limited_cases = [
            case for case in candidate_cases
            if any("entry_trim_capacity_limited" in str(issue) for issue in case.get("issues") or [])
        ]
        expected_cases = int(candidate.get("affected_anchor_records") or 0)
        replacement_ratio = len(candidate_cases) / max(1, expected_cases)
        transaction_issues: list[str] = []
        if not candidate_cases:
            transaction_issues.append("no_compound_cases_generated")
        if exposed_bridge_cases:
            transaction_issues.append("bridge_edge_still_exposed")
        if capacity_limited_cases:
            transaction_issues.append("capacity_limited_anchor_still_exposed")
        if replacement_ratio < 1.0:
            transaction_issues.append("affected_corridor_replacement_incomplete")
        transaction_issues.extend(sorted(candidate_errors))
        status = "accepted_for_staging" if not transaction_issues else "qa_candidate"

        transactions.append({
            "candidate_id": candidate_id,
            "status": status,
            "risk": str(candidate.get("risk") or ""),
            "issues": sorted(set(transaction_issues)),
            "member_junction_node_ids": [str(node_id) for node_id in candidate.get("member_junction_node_ids") or []],
            "bridge_edge_ids": [str(edge_id) for edge_id in candidate.get("bridge_edge_ids") or []],
            "generated_compound_cases": len(candidate_cases),
            "expected_affected_anchor_records": expected_cases,
            "affected_corridor_replacement_ratio": rounded(replacement_ratio),
            "exposed_bridge_edge_cases": len(exposed_bridge_cases),
            "capacity_limited_anchor_cases": len(capacity_limited_cases),
            "compound_case_ids": [str(case.get("compound_case_id") or "") for case in candidate_cases],
            "transaction_contract": (
                "Accepted means accepted for staging preview（暂存预览接受）, not clean skeleton writeback（非干净骨架写回）."
            ),
        })

    status_counts = Counter(str(item.get("status") or "unknown") for item in transactions)
    issue_counts = Counter(str(issue) for item in transactions for issue in item.get("issues") or [])
    case_status_counts = Counter(str(case.get("status") or "unknown") for case in compound_cases)
    case_issue_counts = Counter(str(issue) for case in compound_cases for issue in case.get("issues") or [])
    candidate_family_counts = Counter(
        str(candidate.get("family") or "unknown")
        for case in compound_cases
        for candidate in case.get("candidates", [])
    )
    best_family_counts = Counter(str(case.get("best_candidate_family") or "unknown") for case in compound_cases)
    movement_kind_counts = Counter(str(case.get("movement_kind") or "unknown") for case in compound_cases)
    exposed_bridge_edge_cases = sum(int(item.get("exposed_bridge_edge_cases") or 0) for item in transactions)
    capacity_limited_anchor_cases = sum(int(item.get("capacity_limited_anchor_cases") or 0) for item in transactions)
    expected_affected = sum(int(item.get("expected_affected_anchor_records") or 0) for item in transactions)
    replacement_ratio = len(compound_cases) / max(1, expected_affected)

    output = {
        "type": "compound_junction_merge_transactions",
        "metadata": {
            "area_id": area_id,
            "schema": "road_test_pipeline.compound_junction_merge_transactions.v1",
            "coord_domain": "local_xz_m",
            "contract": (
                "Trial compound junction merge transaction（复合路口合并试运行事务）. "
                "It composes external lane movements across internal bridge edges（内部桥接短边） and emits "
                "compound movement corridor candidates（复合通行走廊候选） without mutating road_graph（道路图） "
                "or clean skeleton（干净道路骨架）."
            ),
        },
        "transactions": transactions,
        "compound_movement_corridor_cases": compound_cases,
    }
    report = {
        "area_id": area_id,
        "stage": "compound_junction_merge_transaction_v1",
        "status": "warn" if issue_counts or case_issue_counts else "pass",
        "counts": {
            "input_candidates": len(compound_candidates.get("candidates", [])),
            "transactions": len(transactions),
            "accepted_for_staging": status_counts.get("accepted_for_staging", 0),
            "compound_movement_corridor_cases": len(compound_cases),
            "expected_affected_anchor_records": expected_affected,
            "affected_corridor_replacement_ratio": rounded(replacement_ratio),
            "reference_errors": reference_errors,
            "composition_error_counts": dict(sorted(composition_errors.items())),
            "transaction_status_counts": dict(sorted(status_counts.items())),
            "transaction_issue_counts": dict(sorted(issue_counts.items())),
            "case_status_counts": dict(sorted(case_status_counts.items())),
            "case_issue_counts": dict(sorted(case_issue_counts.items())),
            "candidate_family_counts": dict(sorted(candidate_family_counts.items())),
            "best_family_counts": dict(sorted(best_family_counts.items())),
            "movement_kind_counts": dict(sorted(movement_kind_counts.items())),
            "exposed_bridge_edge_cases": exposed_bridge_edge_cases,
            "capacity_limited_anchor_cases": capacity_limited_anchor_cases,
        },
        "top_transactions": transactions[:30],
        "next_action": (
            "Use these staged compound movement corridors（暂存复合通行走廊） for SVG review and collision（碰撞） / "
            "swept-envelope（扫掠包络） scoring before any destructive clean skeleton rewrite（写入式干净骨架改写）."
        ),
    }
    return output, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Trial compound junction merge transactions.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--compound-candidates", default="")
    parser.add_argument("--lane-graph", default="")
    parser.add_argument("--engineering-reference", default="")
    parser.add_argument("--short-edge-absorptions", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    processed = root / "data" / "processed"
    reports = root / "reports"
    compound_path = Path(args.compound_candidates) if args.compound_candidates else processed / f"{args.area_id}_compound_junction_merge_candidates.json"
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
    output_path = Path(args.output) if args.output else processed / f"{args.area_id}_compound_junction_merge_transactions.json"
    report_path = Path(args.report) if args.report else reports / f"{args.area_id}_compound_junction_merge_transaction_report.json"

    output, report = apply_compound_merges(
        area_id=args.area_id,
        compound_candidates=read_json(compound_path),
        lane_graph=read_json(lane_graph_path),
        engineering_reference=read_json(engineering_reference_path),
        short_edge_absorptions=read_json(short_edge_absorption_path) if short_edge_absorption_path.exists() else {},
    )
    output["metadata"]["inputs"] = {
        "compound_junction_merge_candidates": str(compound_path),
        "lane_graph": str(lane_graph_path),
        "engineering_reference_lines": str(engineering_reference_path),
        "short_edge_absorption_candidates": str(short_edge_absorption_path) if short_edge_absorption_path.exists() else "",
    }
    report["inputs"] = output["metadata"]["inputs"]
    report["outputs"] = {
        "compound_junction_merge_transactions": str(output_path),
        "report": str(report_path),
    }
    write_json(output_path, output)
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
