#!/usr/bin/env python3
"""Plan LaneForge lane-count propagation candidates around upgraded junctions.

This is a proposal layer. It does not edit active overrides. The output is a
versioned plan that later rules, reviewers, or AI agents can accept/reject.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


SYSTEM_NAME = "LaneForge"
PLAN_SCHEMA = "lane_upgrade_system.propagation_plan.v2"
REPORT_SCHEMA = "lane_upgrade_system.propagation_report.v2"
DEFAULT_SHORT_EDGE_THRESHOLD_M = 35.0
PATH_POLICY = "pipeline_root_relative_paths_v1"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)


def next_versioned_path(directory: Path, prefix: str) -> tuple[str, Path]:
    highest = 0
    if directory.exists():
        for path in directory.glob(f"{prefix}v*.json"):
            match = re.match(rf"^{re.escape(prefix)}v(\d+)$", path.stem)
            if match:
                highest = max(highest, int(match.group(1)))
    version = f"v{highest + 1:04d}"
    return version, directory / f"{prefix}{version}.json"


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def edge_indexes(road_graph: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    edge_by_id = {str(edge.get("edge_id") or ""): edge for edge in road_graph.get("edges", [])}
    node_by_id = {str(node.get("node_id") or ""): node for node in road_graph.get("nodes", [])}
    return edge_by_id, node_by_id


def junctions_by_node(junction_semantics: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(junction.get("node_id") or ""): junction
        for junction in junction_semantics.get("junctions", [])
        if str(junction.get("node_id") or "")
    }


def active_upgrades(active_overrides: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in active_overrides.get("active_upgrades", [])
        if bool(item.get("enabled", True)) and str(item.get("road_id") or "")
    ]


def endpoint_junction_nodes(edge: dict[str, Any], node_by_id: dict[str, dict[str, Any]]) -> list[str]:
    nodes: list[str] = []
    for node_id in [str(edge.get("from_node") or ""), str(edge.get("to_node") or "")]:
        if str((node_by_id.get(node_id) or {}).get("kind") or "") == "junction":
            nodes.append(node_id)
    return nodes


def through_partner(junction: dict[str, Any], source_road_id: str) -> str:
    for pair in junction.get("through_pairs", []):
        edge_a = str(pair.get("edge_a") or "")
        edge_b = str(pair.get("edge_b") or "")
        if edge_a == source_road_id:
            return edge_b
        if edge_b == source_road_id:
            return edge_a
    return ""


def approach_by_edge(junction: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(approach.get("edge_id") or ""): approach
        for approach in junction.get("approaches", [])
        if str(approach.get("edge_id") or "")
    }


def rule_for_candidate(
    *,
    source_edge: dict[str, Any],
    candidate_edge: dict[str, Any],
    source_approach: dict[str, Any],
    candidate_approach: dict[str, Any],
    through_edge_id: str,
    short_edge_threshold_m: float,
) -> dict[str, Any]:
    candidate_road_id = str(candidate_edge.get("edge_id") or "")
    length_m = float(candidate_edge.get("length_m") or 0.0)
    same_class = str(source_edge.get("road_class") or "") == str(candidate_edge.get("road_class") or "")
    source_role = str(source_approach.get("role") or "")
    candidate_role = str(candidate_approach.get("role") or "")

    if candidate_road_id and candidate_road_id == through_edge_id:
        return {
            "rule_id": "through_pair_lane_count_continuity_v2",
            "confidence": 0.84,
            "reason": "Candidate is the geometric through continuation of the upgraded road at this junction.",
        }
    if 0.0 < length_m <= short_edge_threshold_m:
        return {
            "rule_id": "short_edge_absorption_lane_count_v2",
            "confidence": 0.76,
            "reason": f"Candidate edge length {length_m:.3f}m is under the short-edge threshold.",
        }
    if same_class and source_role == candidate_role and "through" in source_role:
        return {
            "rule_id": "same_role_same_class_junction_balance_v2",
            "confidence": 0.66,
            "reason": "Candidate shares road class and approach role with the upgraded road.",
        }
    if same_class:
        return {
            "rule_id": "same_class_adjacent_approach_review_v2",
            "confidence": 0.54,
            "reason": "Candidate shares road class at the same upgraded endpoint junction.",
        }
    return {
        "rule_id": "adjacent_junction_context_review_v2",
        "confidence": 0.42,
        "reason": "Candidate is adjacent to the upgraded endpoint junction and needs review.",
    }


def recommended_status(current_lanes: int, target_lanes: int, confidence: float) -> str:
    if current_lanes >= target_lanes:
        return "already_satisfies_target"
    if confidence >= 0.74:
        return "candidate_high_confidence"
    if confidence >= 0.54:
        return "candidate_review"
    return "context_review"


def build_candidates(
    *,
    active: list[dict[str, Any]],
    edge_by_id: dict[str, dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
    semantic_by_node: dict[str, dict[str, Any]],
    short_edge_threshold_m: float,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    active_road_ids = {str(item.get("road_id") or "") for item in active}

    for upgrade in active:
        source_road_id = str(upgrade.get("road_id") or "")
        source_edge = edge_by_id.get(source_road_id)
        if not source_edge:
            continue
        target_lanes = int_value(upgrade.get("target_physical_lane_count"), 0)
        if target_lanes <= 0:
            continue
        affected = upgrade.get("affected_scope") or {}
        junction_node_ids = [
            str(node_id)
            for node_id in affected.get("adjacent_junction_node_ids", [])
            if str(node_id)
        ] or endpoint_junction_nodes(source_edge, node_by_id)

        for junction_node_id in junction_node_ids:
            junction = semantic_by_node.get(junction_node_id)
            if not junction:
                continue
            approaches = approach_by_edge(junction)
            source_approach = approaches.get(source_road_id, {})
            through_edge_id = through_partner(junction, source_road_id)
            for candidate_road_id, candidate_approach in approaches.items():
                if candidate_road_id == source_road_id or candidate_road_id in active_road_ids:
                    continue
                key = (source_road_id, junction_node_id, candidate_road_id)
                if key in seen:
                    continue
                seen.add(key)
                candidate_edge = edge_by_id.get(candidate_road_id)
                if not candidate_edge:
                    continue
                current_lanes = int_value(candidate_edge.get("lanes"), 1)
                rule = rule_for_candidate(
                    source_edge=source_edge,
                    candidate_edge=candidate_edge,
                    source_approach=source_approach,
                    candidate_approach=candidate_approach,
                    through_edge_id=through_edge_id,
                    short_edge_threshold_m=short_edge_threshold_m,
                )
                status = recommended_status(current_lanes, target_lanes, float(rule["confidence"]))
                candidates.append({
                    "candidate_id": f"prop_{len(candidates):04d}",
                    "source_upgrade_id": str(upgrade.get("upgrade_id") or upgrade.get("transaction_id") or ""),
                    "source_road_id": source_road_id,
                    "source_canonical_road_id": str(source_edge.get("canonical_road_id") or upgrade.get("canonical_road_id") or ""),
                    "candidate_road_id": candidate_road_id,
                    "candidate_canonical_road_id": str(candidate_edge.get("canonical_road_id") or ""),
                    "junction_id": str(junction.get("junction_id") or ""),
                    "junction_node_id": junction_node_id,
                    "junction_type": str(junction.get("type") or ""),
                    "rule_id": rule["rule_id"],
                    "confidence": round(float(rule["confidence"]), 3),
                    "status": status,
                    "recommended_action": "proposal_only_no_active_override",
                    "current_physical_lane_count": current_lanes,
                    "proposed_target_physical_lane_count": target_lanes,
                    "candidate_length_m": round(float(candidate_edge.get("length_m") or 0.0), 3),
                    "candidate_road_class": str(candidate_edge.get("road_class") or ""),
                    "source_road_class": str(source_edge.get("road_class") or ""),
                    "source_approach_role": str(source_approach.get("role") or ""),
                    "candidate_approach_role": str(candidate_approach.get("role") or ""),
                    "through_partner_of_source": through_edge_id,
                    "rationale": rule["reason"],
                })
    return candidates


def plan_propagation(
    *,
    area_id: str,
    root: Path,
    road_graph_path: Path,
    junction_semantics_path: Path,
    active_overrides_path: Path,
    output_path: Path | None,
    report_path: Path,
    short_edge_threshold_m: float,
) -> dict[str, Any]:
    road_graph = read_json(road_graph_path)
    junction_semantics = read_json(junction_semantics_path)
    active_overrides = read_json(active_overrides_path) if active_overrides_path.exists() else {"active_upgrades": []}
    edge_by_id, node_by_id = edge_indexes(road_graph)
    semantic_by_node = junctions_by_node(junction_semantics)
    active = active_upgrades(active_overrides)
    candidates = build_candidates(
        active=active,
        edge_by_id=edge_by_id,
        node_by_id=node_by_id,
        semantic_by_node=semantic_by_node,
        short_edge_threshold_m=short_edge_threshold_m,
    )

    if output_path is None:
        plan_dir = root / "data" / "lane_upgrade_system" / "propagation"
        version, output_path = next_versioned_path(plan_dir, f"{area_id}_lane_upgrade_propagation_plan_")
    else:
        match = re.search(r"_v(\d+)\.json$", output_path.name)
        version = f"v{match.group(1)}" if match else "manual"

    status_counts = Counter(str(candidate.get("status") or "") for candidate in candidates)
    rule_counts = Counter(str(candidate.get("rule_id") or "") for candidate in candidates)
    plan = {
        "type": "lane_upgrade_propagation_plan",
        "metadata": {
            "area_id": area_id,
            "schema": PLAN_SCHEMA,
            "system": SYSTEM_NAME,
            "version": version,
            "path_policy": PATH_POLICY,
            "policy": "proposal_only_no_active_override",
            "short_edge_threshold_m": short_edge_threshold_m,
        },
        "active_upgrades": active,
        "candidates": candidates,
    }
    report = {
        "area_id": area_id,
        "stage": "lane_upgrade_propagation_v2",
        "schema": REPORT_SCHEMA,
        "path_policy": PATH_POLICY,
        "status": "pass",
        "inputs": {
            "road_graph": rel(road_graph_path, root),
            "junction_semantics": rel(junction_semantics_path, root),
            "active_overrides": rel(active_overrides_path, root),
        },
        "outputs": {
            "plan": rel(output_path, root),
            "report": rel(report_path, root),
        },
        "counts": {
            "active_upgrades": len(active),
            "candidates": len(candidates),
            "high_confidence_candidates": status_counts.get("candidate_high_confidence", 0),
            "review_candidates": status_counts.get("candidate_review", 0),
            "context_review_candidates": status_counts.get("context_review", 0),
            "already_satisfies_target": status_counts.get("already_satisfies_target", 0),
        },
        "status_counts": dict(sorted(status_counts.items())),
        "rule_counts": dict(sorted(rule_counts.items())),
        "note": "Propagation v2 is proposal-only; no active overrides are modified by this stage.",
    }
    write_json(output_path, plan)
    write_json(report_path, report)
    latest = {
        "area_id": area_id,
        "system": SYSTEM_NAME,
        "latest_plan_version": version,
        "path_policy": PATH_POLICY,
        "latest_plan": rel(output_path, root),
        "latest_report": rel(report_path, root),
    }
    write_json(output_path.parent / f"{area_id}_latest.json", latest)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan LaneForge lane-count propagation candidates.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--road-graph", default="")
    parser.add_argument("--junction-semantics", default="")
    parser.add_argument("--active-overrides", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--report", default="")
    parser.add_argument("--short-edge-threshold-m", type=float, default=DEFAULT_SHORT_EDGE_THRESHOLD_M)
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    processed = root / "data" / "processed"
    reports = root / "reports"
    road_graph_path = Path(args.road_graph) if args.road_graph else processed / f"{args.area_id}_road_graph.json"
    junction_semantics_path = (
        Path(args.junction_semantics)
        if args.junction_semantics
        else processed / f"{args.area_id}_junction_semantics.json"
    )
    active_overrides_path = (
        Path(args.active_overrides)
        if args.active_overrides
        else processed / f"{args.area_id}_lane_upgrade_overrides.json"
    )
    output_path = Path(args.output) if args.output else None
    report_path = Path(args.report) if args.report else reports / f"{args.area_id}_lane_upgrade_propagation_report.json"
    report = plan_propagation(
        area_id=args.area_id,
        root=root,
        road_graph_path=road_graph_path,
        junction_semantics_path=junction_semantics_path,
        active_overrides_path=active_overrides_path,
        output_path=output_path,
        report_path=report_path,
        short_edge_threshold_m=args.short_edge_threshold_m,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
