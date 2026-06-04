#!/usr/bin/env python3
"""Run automatic QA checks for isolated road test pipeline stages."""

from __future__ import annotations

import argparse
from pathlib import Path

from qa_common import (
    check_max,
    check_min,
    check_warn_above,
    check_warn_below,
    pipeline_root_from_script,
    qa_report,
    read_json,
    write_json,
)


def run_raw_roads_qa(root: Path, area_id: str) -> dict:
    rules = read_json(root / "qa" / "qa_rules.json")["raw_roads"]
    analysis_path = root / "reports" / f"{area_id}_raw_analysis.json"
    analysis = read_json(analysis_path)

    feature_count = analysis["feature_count"]
    geom = analysis["geometry"]
    tags = analysis["tags"]
    topology = analysis["topology"]

    checks = [
        check_min(
            "feature_count",
            feature_count,
            rules["min_feature_count"],
            "Raw sample should contain enough road features for meaningful testing.",
        ),
        check_max(
            "empty_geometry",
            geom["empty_geometry"],
            rules["max_empty_geometry"],
            "Raw roads should not contain empty or invalid LineString geometry.",
        ),
        check_max(
            "duplicate_point_features",
            geom["duplicate_point_features"],
            rules["max_duplicate_point_features"],
            "Adjacent duplicate points should be removed before topology repair.",
        ),
        check_max(
            "too_short_features",
            geom["too_short_features"],
            rules["max_too_short_features"],
            f"Features shorter than {rules['too_short_m']}m should be inspected or collapsed.",
            warn=True,
        ),
        check_warn_below(
            "lanes_coverage_pct",
            tags["lanes_coverage_pct"],
            rules["warn_lanes_coverage_pct_below"],
            "Lane tag coverage is below the target for lane_graph generation.",
        ),
        check_warn_below(
            "width_coverage_pct",
            tags["width_coverage_pct"],
            rules["warn_width_coverage_pct_below"],
            "Width tag coverage is low; width fallback rules will be required.",
        ),
        check_warn_below(
            "turn_lanes_coverage_pct",
            tags["turn_lanes_coverage_pct"],
            rules["warn_turn_lanes_coverage_pct_below"],
            "turn:lanes coverage is low; movement inference will be required.",
        ),
        check_warn_below(
            "oneway_coverage_pct",
            tags["oneway_coverage_pct"],
            rules["warn_oneway_coverage_pct_below"],
            "Oneway coverage is low; verify traffic direction assumptions visually.",
        ),
        check_warn_above(
            "dangling_endpoint_ratio",
            topology["dangling_endpoint_ratio"],
            rules["warn_dangling_endpoint_ratio_above"],
            "Many endpoint clusters are dangling; topology repair and bbox-edge classification are needed.",
        ),
        check_warn_above(
            "possible_unsplit_crossings",
            topology["possible_unsplit_crossings"],
            rules["warn_possible_unsplit_crossings_above"],
            "Potential planar crossings without shared nodes were detected.",
        ),
        check_warn_above(
            "low_confidence_endpoint_clusters",
            topology["low_confidence_endpoint_clusters"],
            rules["warn_low_confidence_endpoint_clusters_above"],
            "Endpoint clusters with mixed highway classes require visual review.",
        ),
    ]

    report = qa_report(
        area_id=area_id,
        stage="raw_roads",
        checks=checks,
        metrics={
            "geometry": geom,
            "tags": tags,
            "topology": topology,
            "highway_class_counts": analysis["highway_class_counts"],
        },
        inputs={
            "analysis": str(analysis_path),
            "rules": str(root / "qa" / "qa_rules.json"),
        },
        next_action="Run topology_repair.py, then cook a Houdini debug view for dangling endpoints and possible crossings.",
    )
    output_path = root / "reports" / "qa" / f"{area_id}_raw_roads_qa_report.json"
    write_json(output_path, report)
    return report


def run_topology_repair_qa(root: Path, area_id: str) -> dict:
    rules = read_json(root / "qa" / "qa_rules.json")["topology_repair"]
    analysis_path = root / "reports" / f"{area_id}_repaired_analysis.json"
    repair_report_path = root / "reports" / f"{area_id}_repair_report.json"
    analysis = read_json(analysis_path)
    repair_report = read_json(repair_report_path)

    geom = analysis["geometry"]
    topology = analysis["topology"]
    counts = repair_report["counts"]
    repair_op_count = (
        counts.get("endpoint_snaps", 0)
        + counts.get("endpoint_to_edge_snaps", 0)
        + counts.get("intersection_split_insertions", 0)
        + counts.get("duplicate_points_removed", 0)
        + counts.get("raw_shape_vertices_removed", 0)
    )

    checks = [
        check_min(
            "output_edges",
            counts["output_edges"],
            rules["min_output_edges"],
            "Repair should output enough simple edges for road_graph construction.",
        ),
        check_max(
            "empty_geometry",
            geom["empty_geometry"],
            rules["max_empty_geometry"],
            "Repaired roads should not contain empty geometry.",
        ),
        check_max(
            "duplicate_point_features",
            geom["duplicate_point_features"],
            rules["max_duplicate_point_features"],
            "Repaired roads should not contain adjacent duplicate points.",
        ),
        check_max(
            "too_short_features",
            geom["too_short_features"],
            rules["max_too_short_features"],
            "Repaired output should not create too-short edges.",
            warn=True,
        ),
        check_warn_above(
            "dangling_endpoint_ratio",
            topology["dangling_endpoint_ratio"],
            rules["warn_dangling_endpoint_ratio_above"],
            "Dangling endpoints remain high; bbox boundary and dead-end classification should be added next.",
        ),
        check_warn_above(
            "possible_unsplit_crossings",
            topology["possible_unsplit_crossings"],
            rules["warn_possible_unsplit_crossings_above"],
            "Potential road-road crossings remain after repair.",
        ),
    ]

    if topology["dangling_endpoint_ratio"] > rules["warn_no_repair_ops_if_dangling_above"] and repair_op_count == 0:
        checks.append(check_warn_above(
            "repair_ops_when_dangling_high",
            1,
            0,
            "Dangling ratio is high but no repair operations were applied; review thresholds or bbox boundary classification.",
        ))
    else:
        checks.append(check_warn_above(
            "repair_ops_when_dangling_high",
            0,
            0,
            "Repair operations are consistent with current dangling endpoint level.",
        ))

    report = qa_report(
        area_id=area_id,
        stage="topology_repair",
        checks=checks,
        metrics={
            "repair_counts": counts,
            "endpoint_stats_before": repair_report["endpoint_stats_before"],
            "endpoint_stats_after_parent_roads": repair_report.get("endpoint_stats_after_parent_roads", repair_report.get("endpoint_stats_after")),
            "endpoint_stats_after_output_edges": repair_report.get("endpoint_stats_after_output_edges"),
            "geometry": geom,
            "topology": topology,
        },
        inputs={
            "repair_report": str(repair_report_path),
            "analysis": str(analysis_path),
            "rules": str(root / "qa" / "qa_rules.json"),
        },
        next_action="Cook Houdini repaired preview and visually inspect endpoint continuity and road junction joins.",
    )
    output_path = root / "reports" / "qa" / f"{area_id}_topology_repair_qa_report.json"
    write_json(output_path, report)
    return report


def run_road_graph_qa(root: Path, area_id: str) -> dict:
    rules = read_json(root / "qa" / "qa_rules.json")["road_graph"]
    graph_path = root / "data" / "processed" / f"{area_id}_road_graph.json"
    graph_report_path = root / "reports" / f"{area_id}_road_graph_report.json"
    graph_report = read_json(graph_report_path)

    counts = graph_report["counts"]
    node_kind_counts = graph_report["node_kind_counts"]
    metrics = graph_report["metrics"]

    checks = [
        check_min(
            "nodes",
            counts["nodes"],
            rules["min_nodes"],
            "Road graph should contain enough nodes for junction and lane graph research.",
        ),
        check_min(
            "edges",
            counts["edges"],
            rules["min_edges"],
            "Road graph should contain enough edges for a useful test sample.",
        ),
        check_min(
            "junction_nodes",
            node_kind_counts.get("junction", 0),
            rules["min_junction_nodes"],
            "Road graph should expose at least one junction node for junction solver iteration.",
        ),
        check_max(
            "skipped_empty_geometry",
            counts["skipped_empty_geometry"],
            rules["max_skipped_empty_geometry"],
            "Road graph builder should not skip repaired features due to empty geometry.",
        ),
        check_max(
            "zero_length_edges",
            counts["zero_length_edges"],
            rules["max_zero_length_edges"],
            "Road graph should not contain zero-length edges.",
        ),
        check_max(
            "orphan_edges",
            counts["orphan_edges"],
            rules["max_orphan_edges"],
            "Road graph edges should connect two distinct graph nodes.",
        ),
        check_warn_above(
            "dead_end_ratio",
            metrics["dead_end_ratio"],
            rules["warn_dead_end_ratio_above"],
            "Internal dead ends remain high after boundary classification; review endpoint clusters visually.",
        ),
        check_warn_above(
            "width_fallback_ratio",
            metrics["width_fallback_ratio"],
            rules["warn_width_fallback_ratio_above"],
            "Many edges use road-class width defaults; better data or local width inference is needed.",
        ),
        check_warn_above(
            "lanes_fallback_ratio",
            metrics["lanes_fallback_ratio"],
            rules["warn_lanes_fallback_ratio_above"],
            "Many edges use lane-count defaults; lane graph will need inference.",
        ),
    ]

    report = qa_report(
        area_id=area_id,
        stage="road_graph",
        checks=checks,
        metrics={
            "counts": counts,
            "node_kind_counts": node_kind_counts,
            "node_degree_counts": graph_report["node_degree_counts"],
            "edge_highway_counts": graph_report["edge_highway_counts"],
            "lanes_source_counts": graph_report["lanes_source_counts"],
            "width_source_counts": graph_report["width_source_counts"],
            "graph_metrics": metrics,
        },
        inputs={
            "road_graph": str(graph_path),
            "road_graph_report": str(graph_report_path),
            "rules": str(root / "qa" / "qa_rules.json"),
        },
        next_action="Use road_graph.json as the contract for junction_solver and lane_graph_builder v1.",
    )
    output_path = root / "reports" / "qa" / f"{area_id}_road_graph_qa_report.json"
    write_json(output_path, report)
    return report


def run_lane_graph_qa(root: Path, area_id: str) -> dict:
    rules = read_json(root / "qa" / "qa_rules.json")["lane_graph"]
    lane_graph_path = root / "data" / "processed" / f"{area_id}_lane_graph.json"
    lane_report_path = root / "reports" / f"{area_id}_lane_graph_report.json"
    lane_report = read_json(lane_report_path)

    counts = lane_report["counts"]
    metrics = lane_report["metrics"]

    checks = [
        check_min(
            "lanes",
            counts["lanes"],
            rules["min_lanes"],
            "Lane graph should expose enough directed lane records for junction connection research.",
        ),
        check_min(
            "junctions",
            counts["junctions"],
            rules["min_junctions"],
            "Lane graph should include junction models derived from road_graph junction nodes.",
        ),
        check_min(
            "connections",
            counts["connections"],
            rules["min_connections"],
            "Semantic junctions should infer at least one road-level movement.",
        ),
        check_min(
            "lane_links",
            counts["lane_links"],
            rules["min_lane_links"],
            "Allowed movements should produce laneLinks for downstream movement corridor research.",
        ),
        check_max(
            "lane_link_reference_errors",
            metrics.get("lane_link_reference_errors", 0),
            rules["max_lane_link_reference_errors"],
            "Every laneLink from_lane and to_lane should reference an existing lane.",
        ),
        check_max(
            "blocked_lane_links",
            metrics.get("blocked_lane_links", 0),
            rules["max_blocked_lane_links"],
            "Blocked or disallowed semantic movements must not produce laneLinks.",
        ),
        check_max(
            "empty_connection_curves",
            metrics.get("empty_connection_curves", 0),
            rules["max_empty_connection_curves"],
            "Topology-only lane graph should not claim missing final connection curves as published geometry.",
        ),
        check_warn_above(
            "fan_fallback_ratio",
            metrics["fan_fallback_ratio"],
            rules["warn_fan_fallback_ratio_above"],
            "Layer 3 should avoid junction fan fallback; lane-boundary envelopes belong to the later geometry layer.",
        ),
        check_warn_below(
            "avg_lane_links_per_junction",
            metrics["avg_lane_links_per_junction"],
            rules["warn_avg_lane_links_per_junction_below"],
            "LaneLink density is low; review oneway, lane count and movement inference.",
        ),
    ]

    report = qa_report(
        area_id=area_id,
        stage="lane_graph",
        checks=checks,
        metrics={
            "counts": counts,
            "turn_counts": lane_report["turn_counts"],
            "lane_source_counts": lane_report["lane_source_counts"],
            "traffic_direction_policy_counts": lane_report.get("traffic_direction_policy_counts", {}),
            "connection_source_counts": lane_report.get("connection_source_counts", {}),
            "lane_link_source_counts": lane_report.get("lane_link_source_counts", {}),
            "fallback_counts": lane_report["fallback_counts"],
            "lane_graph_metrics": metrics,
        },
        inputs={
            "lane_graph": str(lane_graph_path),
            "lane_graph_report": str(lane_report_path),
            "rules": str(root / "qa" / "qa_rules.json"),
        },
        next_action="Use lane_graph as the topology contract for movement corridor solver; do not treat offset previews as final lane geometry.",
    )
    output_path = root / "reports" / "qa" / f"{area_id}_lane_graph_qa_report.json"
    write_json(output_path, report)
    return report


def run_movement_corridor_qa(root: Path, area_id: str) -> dict:
    rules = read_json(root / "qa" / "qa_rules.json")["movement_corridor"]
    candidates_path = root / "data" / "processed" / f"{area_id}_movement_corridor_candidates.json"
    report_path = root / "reports" / f"{area_id}_movement_corridor_report.json"
    corridor_report = read_json(report_path)
    counts = corridor_report["counts"]
    metrics = corridor_report["metrics"]
    candidate_issue_counts = counts.get("candidate_issue_counts", {})

    checks = [
        check_min(
            "corridor_cases",
            counts["corridor_cases"],
            rules["min_corridor_cases"],
            "Movement corridor solver should emit lane-level corridor cases from junction laneLinks.",
        ),
        check_min(
            "candidate_curves",
            counts["candidate_curves"],
            rules["min_candidate_curves"],
            "Movement corridor solver should emit at least one candidate curve.",
        ),
        check_max(
            "reference_errors",
            counts["reference_errors"],
            rules["max_reference_errors"],
            "Every movement corridor must reference existing from/to lanes.",
        ),
        check_max(
            "missing_anchor_poses",
            counts.get("missing_anchor_poses", 0),
            rules["max_missing_anchor_poses"],
            "Every junction movement should resolve entry/exit poses before using centerline preview fallback.",
        ),
        check_max(
            "empty_candidate_geometry",
            candidate_issue_counts.get("empty_candidate_geometry", 0),
            rules["max_empty_candidate_geometry"],
            "Movement corridor candidates should not contain empty geometry previews.",
        ),
        check_warn_above(
            "anchor_fallback_ratio",
            metrics.get("anchor_fallback_ratio", 0.0),
            rules["warn_anchor_fallback_ratio_above"],
            "Movement corridor endpoints are falling back to centerline_xz previews instead of lane-level anchors.",
        ),
        check_warn_below(
            "fully_anchored_case_ratio",
            metrics.get("fully_anchored_case_ratio", 0.0),
            rules["warn_fully_anchored_case_ratio_below"],
            "Most movement corridors should have both lane_entry_anchor and lane_exit_anchor resolved.",
        ),
        check_warn_above(
            "low_confidence_ratio",
            metrics["low_confidence_ratio"],
            rules["warn_low_confidence_ratio_above"],
            "Many movement corridors are low-confidence; review missing turn:lanes and inferred laneLinks.",
        ),
        check_warn_below(
            "ready_ratio",
            metrics["ready_ratio"],
            rules["warn_ready_ratio_below"],
            "Few movement corridors are ready for geometry solving; more source evidence or better inference is needed.",
        ),
    ]

    report = qa_report(
        area_id=area_id,
        stage="movement_corridor",
        checks=checks,
        metrics={
            "counts": counts,
            "solver_metrics": metrics,
        },
        inputs={
            "movement_corridor_candidates": str(candidates_path),
            "movement_corridor_report": str(report_path),
            "rules": str(root / "qa" / "qa_rules.json"),
        },
        next_action=(
            "Add collision（碰撞） and swept envelope（扫掠包络） scoring, then run only "
            "transaction-ready（事务就绪） destructive transactions（写入式事务）."
        ),
    )
    output_path = root / "reports" / "qa" / f"{area_id}_movement_corridor_qa_report.json"
    write_json(output_path, report)
    return report


def run_compound_junction_merge_qa(root: Path, area_id: str) -> dict:
    rules = read_json(root / "qa" / "qa_rules.json")["compound_junction_merge"]
    candidates_path = root / "data" / "processed" / f"{area_id}_compound_junction_merge_candidates.json"
    report_path = root / "reports" / f"{area_id}_compound_junction_merge_report.json"
    planner_report = read_json(report_path)
    counts = planner_report["counts"]
    status_counts = counts.get("status_counts", {})
    risk_counts = counts.get("risk_counts", {})
    eligible_anchor_records = int(counts.get("eligible_anchor_records", 0))
    affected_anchor_records = int(counts.get("affected_anchor_records", 0))
    candidates = int(counts.get("candidates", 0))
    transaction_candidates = int(counts.get("transaction_candidates", 0))
    affected_anchor_coverage_ratio = (
        affected_anchor_records / eligible_anchor_records
        if eligible_anchor_records
        else 1.0
    )
    transaction_candidate_ratio = (
        transaction_candidates / candidates
        if candidates
        else 1.0
    )

    checks = [
        check_max(
            "reference_errors",
            counts.get("reference_errors", 0),
            rules["max_reference_errors"],
            "Compound junction merge planner should not lose references to audited anchors or bridge edges.",
        ),
        check_max(
            "blocked_candidates",
            status_counts.get("blocked", 0),
            rules["max_blocked_candidates"],
            "Blocked compound junction merge candidates need manual review before any transaction design.",
        ),
        check_warn_above(
            "high_risk_candidates",
            risk_counts.get("high", 0),
            rules["warn_high_risk_candidates_above"],
            "High-risk compound junction merges should not be auto-promoted.",
        ),
        check_warn_below(
            "affected_anchor_coverage_ratio",
            affected_anchor_coverage_ratio,
            rules["warn_affected_anchor_coverage_ratio_below"],
            "Every eligible adjacent-junction anchor should be explained by a compound merge candidate.",
        ),
        check_warn_below(
            "transaction_candidate_ratio",
            transaction_candidate_ratio,
            rules["warn_transaction_candidate_ratio_below"],
            "Few compound merge candidates are transaction candidates; review merge thresholds.",
        ),
    ]

    report = qa_report(
        area_id=area_id,
        stage="compound_junction_merge",
        checks=checks,
        metrics={
            "counts": counts,
            "affected_anchor_coverage_ratio": round(affected_anchor_coverage_ratio, 3),
            "transaction_candidate_ratio": round(transaction_candidate_ratio, 3),
        },
        inputs={
            "compound_junction_merge_candidates": str(candidates_path),
            "compound_junction_merge_report": str(report_path),
            "rules": str(root / "qa" / "qa_rules.json"),
        },
        next_action=(
            "Use transaction_candidate（事务候选） compound junction merges（复合路口合并） for trial transaction（试运行事务） "
            "only; regenerate entry poses（入口姿态） and movement corridors（通行走廊） before accepting any rewrite."
        ),
    )
    output_path = root / "reports" / "qa" / f"{area_id}_compound_junction_merge_qa_report.json"
    write_json(output_path, report)
    return report


def run_compound_junction_merge_transaction_qa(root: Path, area_id: str) -> dict:
    rules = read_json(root / "qa" / "qa_rules.json")["compound_junction_merge_transaction"]
    transactions_path = root / "data" / "processed" / f"{area_id}_compound_junction_merge_transactions.json"
    report_path = root / "reports" / f"{area_id}_compound_junction_merge_transaction_report.json"
    transaction_report = read_json(report_path)
    counts = transaction_report["counts"]
    transactions = int(counts.get("transactions", 0))
    accepted = int(counts.get("accepted_for_staging", 0))
    accepted_ratio = accepted / max(1, transactions)
    replacement_ratio = float(counts.get("affected_corridor_replacement_ratio") or 0.0)

    checks = [
        check_max(
            "reference_errors",
            counts.get("reference_errors", 0),
            rules["max_reference_errors"],
            "Compound merge transaction should not lose lane, link, or pose references.",
        ),
        check_max(
            "exposed_bridge_edge_cases",
            counts.get("exposed_bridge_edge_cases", 0),
            rules["max_exposed_bridge_edge_cases"],
            "Trial compound corridors should expose only external edges, not internal bridge edges.",
        ),
        check_max(
            "capacity_limited_anchor_cases",
            counts.get("capacity_limited_anchor_cases", 0),
            rules["max_capacity_limited_anchor_cases"],
            "Trial compound corridors should remove capacity-limited bridge-edge anchors from the exposed contract.",
        ),
        check_warn_below(
            "accepted_transaction_ratio",
            accepted_ratio,
            rules["warn_accepted_transaction_ratio_below"],
            "Not every compound merge transaction was accepted for staging preview.",
        ),
        check_warn_below(
            "affected_corridor_replacement_ratio",
            replacement_ratio,
            rules["warn_affected_corridor_replacement_ratio_below"],
            "Trial compound corridors do not cover all previously affected close-anchor corridors.",
        ),
    ]

    report = qa_report(
        area_id=area_id,
        stage="compound_junction_merge_transaction",
        checks=checks,
        metrics={
            "counts": counts,
            "accepted_transaction_ratio": round(accepted_ratio, 3),
            "affected_corridor_replacement_ratio": round(replacement_ratio, 3),
        },
        inputs={
            "compound_junction_merge_transactions": str(transactions_path),
            "compound_junction_merge_transaction_report": str(report_path),
            "rules": str(root / "qa" / "qa_rules.json"),
        },
        next_action=(
            "Use staged compound movement corridors（暂存复合通行走廊） for SVG review and collision（碰撞） / "
            "swept-envelope（扫掠包络） scoring before any destructive writeback（写入式回写）."
        ),
    )
    output_path = root / "reports" / "qa" / f"{area_id}_compound_junction_merge_transaction_qa_report.json"
    write_json(output_path, report)
    return report


def run_movement_corridor_scoring_qa(root: Path, area_id: str) -> dict:
    rules = read_json(root / "qa" / "qa_rules.json")["movement_corridor_scoring"]
    scoring_path = root / "data" / "processed" / f"{area_id}_movement_corridor_scoring.json"
    report_path = root / "reports" / f"{area_id}_movement_corridor_scoring_report.json"
    scoring_report = read_json(report_path)
    metrics = scoring_report["metrics"]

    checks = [
        check_min(
            "cases_scored",
            metrics.get("cases_scored", 0),
            rules["min_cases_scored"],
            "Movement corridor scoring should score staged movement corridor cases.",
        ),
        check_min(
            "candidate_scores",
            metrics.get("candidate_scores", 0),
            rules["min_candidate_scores"],
            "Movement corridor scoring should emit candidate-level scores.",
        ),
        check_max(
            "reference_errors",
            metrics.get("reference_errors", 0),
            rules["max_reference_errors"],
            "Movement corridor scoring should preserve all lane and candidate references.",
        ),
        check_warn_below(
            "scored_candidate_ratio",
            metrics.get("scored_candidate_ratio", 0.0),
            rules["warn_scored_candidate_ratio_below"],
            "Every candidate curve should receive QA scores before visual review.",
        ),
        check_warn_below(
            "qa_ready_case_ratio",
            metrics.get("qa_ready_case_ratio", 0.0),
            rules["warn_qa_ready_case_ratio_below"],
            "Few corridor cases have a best candidate above the QA scoring threshold.",
        ),
        check_warn_above(
            "collision_risk_candidate_ratio",
            metrics.get("collision_risk_candidate_ratio", 0.0),
            rules["warn_collision_risk_candidate_ratio_above"],
            "Most corridor candidates are collision-risk candidates; review scoring thresholds and SVG locations.",
        ),
    ]

    report = qa_report(
        area_id=area_id,
        stage="movement_corridor_scoring",
        checks=checks,
        metrics=metrics,
        inputs={
            "movement_corridor_scoring": str(scoring_path),
            "movement_corridor_scoring_report": str(report_path),
            "rules": str(root / "qa" / "qa_rules.json"),
        },
        next_action=(
            "Use Inspector（检查器） in the SVG viewer（SVG 查看器） to review low-score corridors（低分通行走廊） "
            "before destructive writeback（写入式回写）."
        ),
    )
    output_path = root / "reports" / "qa" / f"{area_id}_movement_corridor_scoring_qa_report.json"
    write_json(output_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run auto QA for a road test stage.")
    parser.add_argument(
        "--stage",
        required=True,
        choices=[
            "raw_roads",
            "topology_repair",
            "road_graph",
            "lane_graph",
            "movement_corridor",
            "movement_corridor_scoring",
            "compound_junction_merge",
            "compound_junction_merge_transaction",
        ],
    )
    parser.add_argument("--area-id", default="pattaya_central_500m")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    if args.stage == "raw_roads":
        report = run_raw_roads_qa(root, args.area_id)
    elif args.stage == "topology_repair":
        report = run_topology_repair_qa(root, args.area_id)
    elif args.stage == "road_graph":
        report = run_road_graph_qa(root, args.area_id)
    elif args.stage == "lane_graph":
        report = run_lane_graph_qa(root, args.area_id)
    elif args.stage == "movement_corridor":
        report = run_movement_corridor_qa(root, args.area_id)
    elif args.stage == "movement_corridor_scoring":
        report = run_movement_corridor_scoring_qa(root, args.area_id)
    elif args.stage == "compound_junction_merge":
        report = run_compound_junction_merge_qa(root, args.area_id)
    elif args.stage == "compound_junction_merge_transaction":
        report = run_compound_junction_merge_transaction_qa(root, args.area_id)
    else:
        raise ValueError(args.stage)

    print(f"{args.stage} QA status: {report['status']}")
    for check in report["checks"]:
        print(f"[{check['status']}] {check['id']}: {check['value']} / {check['threshold']}")
    return 0 if report["status"] != "fail" else 2


if __name__ == "__main__":
    raise SystemExit(main())
