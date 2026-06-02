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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run auto QA for a road test stage.")
    parser.add_argument("--stage", required=True, choices=["raw_roads", "topology_repair"])
    parser.add_argument("--area-id", default="pattaya_central_500m")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    if args.stage == "raw_roads":
        report = run_raw_roads_qa(root, args.area_id)
    elif args.stage == "topology_repair":
        report = run_topology_repair_qa(root, args.area_id)
    else:
        raise ValueError(args.stage)

    print(f"{args.stage} QA status: {report['status']}")
    for check in report["checks"]:
        print(f"[{check['status']}] {check['id']}: {check['value']} / {check['threshold']}")
    return 0 if report["status"] != "fail" else 2


if __name__ == "__main__":
    raise SystemExit(main())
