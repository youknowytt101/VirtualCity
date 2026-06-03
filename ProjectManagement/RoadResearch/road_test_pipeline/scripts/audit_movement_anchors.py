#!/usr/bin/env python3
"""Classify remaining capacity-limited movement anchors.

This is a non-destructive QA stage. It explains why any lane-level movement
anchor still sits closer to the junction than its desired entry trim after
transaction-ready short-edge absorption candidates have already been previewed
as planned virtual anchors.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PLANNED_ANCHOR_SOURCE = "junction_zone_expansion_planned_pose_lateral_offset"
ENGINEERING_ANCHOR_SOURCE = "engineering_entry_pose_lateral_offset"
CAPACITY_LIMIT_ISSUE = "entry_trim_capacity_limited"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def rounded(value: float) -> float:
    return round(float(value), 3)


def build_approach_index(junction_areas: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for area in junction_areas.get("junction_areas", []):
        node_id = str(area.get("node_id") or "")
        for approach in area.get("approaches", []):
            edge_id = str(approach.get("edge_id") or "")
            if node_id and edge_id:
                indexed[(node_id, edge_id)] = {
                    **approach,
                    "junction_id": str(area.get("junction_id") or ""),
                    "junction_node_id": node_id,
                }
    return indexed


def build_absorption_index(short_edge_absorptions: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for candidate in short_edge_absorptions.get("candidates", []):
        node_id = str(candidate.get("junction_node_id") or "")
        edge_id = str(candidate.get("short_edge_id") or "")
        if node_id and edge_id:
            indexed[(node_id, edge_id)] = candidate
    return indexed


def other_node_for_edge(edge: dict[str, Any] | None, node_id: str) -> str:
    if not edge:
        return ""
    if str(edge.get("from_node") or "") == node_id:
        return str(edge.get("to_node") or "")
    if str(edge.get("to_node") or "") == node_id:
        return str(edge.get("from_node") or "")
    return ""


def anchor_has_capacity_limit(anchor: dict[str, Any]) -> bool:
    return any(CAPACITY_LIMIT_ISSUE in str(issue) for issue in anchor.get("issues") or [])


def classify_remaining_anchor(
    *,
    anchor: dict[str, Any],
    case: dict[str, Any],
    approach: dict[str, Any] | None,
    absorption: dict[str, Any] | None,
    edge: dict[str, Any] | None,
    other_node: dict[str, Any] | None,
) -> tuple[str, str, list[str]]:
    if str(anchor.get("source") or "") == PLANNED_ANCHOR_SOURCE:
        return "already_planned_virtual_anchor", "none", []

    if absorption is not None:
        status = str(absorption.get("status") or "")
        issues = [str(issue) for issue in absorption.get("issues") or []]
        if status == "transaction_ready":
            return "transaction_ready_not_previewed", "investigate", issues
        if "low_trim_recovery" in issues:
            return "low_value_short_edge_absorption", "defer", issues
        return "blocked_or_qa_short_edge_absorption", "review", issues

    other_kind = str((other_node or {}).get("kind") or "")
    road_class = str((approach or {}).get("road_class") or (edge or {}).get("road_class") or "")
    edge_length = float((approach or {}).get("edge_length_m") or (edge or {}).get("length_m") or 0.0)
    desired_trim = float((approach or {}).get("desired_trim_m") or 0.0)
    trim_deficit = max(0.0, desired_trim - float(anchor.get("entry_trim_m") or 0.0))

    if other_kind == "junction":
        return (
            "adjacent_junction_short_link",
            "compound_junction_merge",
            [
                "not_short_edge_absorption_candidate",
                "other_node_is_junction",
                "candidate_for_compound_junction_merge",
            ],
        )
    if other_kind == "dead_end":
        priority = "keep_qa" if road_class == "service" else "review"
        return (
            "dead_end_stub_capacity_limited",
            priority,
            [
                "not_short_edge_absorption_candidate",
                "other_node_is_dead_end",
                "do_not_invent_extension_for_dead_end_stub",
            ],
        )
    if edge_length > 0.0 and desired_trim > 0.0 and trim_deficit <= 0.5:
        return (
            "minor_capacity_deficit",
            "defer",
            [
                "trim_deficit_below_half_meter",
                "no_short_edge_absorption_candidate",
            ],
        )
    return (
        "unclassified_capacity_limited_anchor",
        "review",
        [
            "no_short_edge_absorption_candidate",
            f"other_node_kind_{other_kind or 'unknown'}",
        ],
    )


def audit_remaining_anchors(
    *,
    area_id: str,
    movement_corridors: dict[str, Any],
    junction_areas: dict[str, Any],
    road_graph: dict[str, Any],
    short_edge_absorptions: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    approaches = build_approach_index(junction_areas)
    absorptions = build_absorption_index(short_edge_absorptions)
    edges = {str(edge.get("edge_id") or ""): edge for edge in road_graph.get("edges", [])}
    nodes = {str(node.get("node_id") or ""): node for node in road_graph.get("nodes", [])}

    anchor_records: list[dict[str, Any]] = []
    planned_anchor_count = 0
    capacity_limited_count = 0
    classification_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    unique_approaches: dict[tuple[str, str], dict[str, Any]] = {}
    corridors_by_class: dict[str, set[str]] = defaultdict(set)

    for case in movement_corridors.get("cases", []):
        node_id = str(case.get("node_id") or "")
        for anchor_key in ("lane_entry_anchor", "lane_exit_anchor"):
            anchor = case.get(anchor_key) or {}
            if not isinstance(anchor, dict):
                continue
            if str(anchor.get("source") or "") == PLANNED_ANCHOR_SOURCE:
                planned_anchor_count += 1
                continue
            if str(anchor.get("source") or "") != ENGINEERING_ANCHOR_SOURCE:
                continue
            if not anchor_has_capacity_limit(anchor):
                continue

            capacity_limited_count += 1
            edge_id = str(anchor.get("edge_id") or "")
            approach_key = (node_id, edge_id)
            approach = approaches.get(approach_key)
            absorption = absorptions.get(approach_key)
            edge = edges.get(edge_id)
            other_node_id = other_node_for_edge(edge, node_id)
            other_node = nodes.get(other_node_id)
            classification, action, reasons = classify_remaining_anchor(
                anchor=anchor,
                case=case,
                approach=approach,
                absorption=absorption,
                edge=edge,
                other_node=other_node,
            )
            classification_counts[classification] += 1
            action_counts[action] += 1
            corridors_by_class[classification].add(str(case.get("corridor_id") or ""))

            desired_trim = float((approach or {}).get("desired_trim_m") or 0.0)
            entry_trim = float(anchor.get("entry_trim_m") or 0.0)
            record = {
                "corridor_id": str(case.get("corridor_id") or ""),
                "lane_link_id": str(case.get("lane_link_id") or ""),
                "movement_kind": str(case.get("movement_kind") or ""),
                "anchor_role": str(anchor.get("role") or anchor_key),
                "anchor_source": str(anchor.get("source") or ""),
                "junction_id": str((approach or {}).get("junction_id") or case.get("junction_id") or ""),
                "junction_node_id": node_id,
                "edge_id": edge_id,
                "road_class": str((approach or {}).get("road_class") or (edge or {}).get("road_class") or ""),
                "edge_length_m": rounded(float((approach or {}).get("edge_length_m") or (edge or {}).get("length_m") or 0.0)),
                "desired_trim_m": rounded(desired_trim),
                "entry_trim_m": rounded(entry_trim),
                "trim_deficit_m": rounded(max(0.0, desired_trim - entry_trim)),
                "other_node_id": other_node_id,
                "other_node_kind": str((other_node or {}).get("kind") or ""),
                "short_edge_absorption_candidate_id": str((absorption or {}).get("candidate_id") or ""),
                "short_edge_absorption_status": str((absorption or {}).get("status") or ""),
                "short_edge_absorption_issues": [str(issue) for issue in (absorption or {}).get("issues") or []],
                "classification": classification,
                "recommended_action": action,
                "reasons": sorted(set(reasons)),
                "anchor_issues": [str(issue) for issue in anchor.get("issues") or []],
            }
            anchor_records.append(record)
            unique_approaches.setdefault(approach_key, {
                "junction_node_id": node_id,
                "edge_id": edge_id,
                "classification": classification,
                "recommended_action": action,
                "road_class": record["road_class"],
                "edge_length_m": record["edge_length_m"],
                "desired_trim_m": record["desired_trim_m"],
                "entry_trim_m": record["entry_trim_m"],
                "trim_deficit_m": record["trim_deficit_m"],
                "other_node_kind": record["other_node_kind"],
                "short_edge_absorption_status": record["short_edge_absorption_status"],
                "short_edge_absorption_issues": record["short_edge_absorption_issues"],
                "corridor_count": 0,
            })
            unique_approaches[approach_key]["corridor_count"] += 1

    unique_records = sorted(
        unique_approaches.values(),
        key=lambda item: (
            str(item["recommended_action"]),
            str(item["classification"]),
            str(item["junction_node_id"]),
            str(item["edge_id"]),
        ),
    )
    anchor_records.sort(
        key=lambda item: (
            str(item["recommended_action"]),
            str(item["classification"]),
            str(item["junction_node_id"]),
            str(item["edge_id"]),
            str(item["corridor_id"]),
        ),
    )

    audit = {
        "type": "movement_anchor_gap_audit",
        "metadata": {
            "area_id": area_id,
            "schema": "road_test_pipeline.movement_anchor_gap_audit.v1",
            "coord_domain": "local_xz_m",
            "contract": (
                "Non-destructive QA（非破坏式质检） for remaining capacity-limited lane-level movement anchors（车道级通行锚点）. "
                "It classifies why anchors remain close after transaction-ready short-edge absorption（事务就绪短边吸收） "
                "has been previewed as planned virtual anchors（规划虚拟锚点）."
            ),
        },
        "remaining_anchor_records": anchor_records,
        "unique_remaining_approaches": unique_records,
    }
    report = {
        "area_id": area_id,
        "stage": "movement_anchor_gap_audit_v1",
        "status": "warn" if anchor_records else "pass",
        "counts": {
            "movement_corridor_cases": len(movement_corridors.get("cases", [])),
            "planned_virtual_anchors": planned_anchor_count,
            "remaining_capacity_limited_anchors": capacity_limited_count,
            "unique_remaining_approaches": len(unique_records),
            "classification_counts": dict(sorted(classification_counts.items())),
            "recommended_action_counts": dict(sorted(action_counts.items())),
            "corridor_counts_by_classification": {
                key: len(value)
                for key, value in sorted(corridors_by_class.items())
            },
        },
        "top_remaining_approaches": unique_records[:30],
        "next_action": (
            "Do not force these anchors through short-edge absorption. "
            "compound_junction_merge（复合路口合并） cases need a separate transaction family; "
            "dead_end_stub_capacity_limited（死端短支路退让受限） should stay low-priority QA unless a better source proves the stub continues."
        ),
    }
    return audit, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit remaining movement corridor anchor gaps.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--movement-corridors", default="")
    parser.add_argument("--junction-areas", default="")
    parser.add_argument("--road-graph", default="")
    parser.add_argument("--short-edge-absorptions", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    processed = root / "data" / "processed"
    reports = root / "reports"
    movement_path = Path(args.movement_corridors) if args.movement_corridors else processed / f"{args.area_id}_movement_corridor_candidates.json"
    junction_areas_path = Path(args.junction_areas) if args.junction_areas else processed / f"{args.area_id}_junction_areas.json"
    road_graph_path = Path(args.road_graph) if args.road_graph else processed / f"{args.area_id}_road_graph.json"
    short_edge_path = Path(args.short_edge_absorptions) if args.short_edge_absorptions else processed / f"{args.area_id}_short_edge_absorption_candidates.json"
    output_path = Path(args.output) if args.output else processed / f"{args.area_id}_movement_anchor_gap_audit.json"
    report_path = Path(args.report) if args.report else reports / f"{args.area_id}_movement_anchor_gap_audit_report.json"

    audit, report = audit_remaining_anchors(
        area_id=args.area_id,
        movement_corridors=read_json(movement_path),
        junction_areas=read_json(junction_areas_path),
        road_graph=read_json(road_graph_path),
        short_edge_absorptions=read_json(short_edge_path) if short_edge_path.exists() else {},
    )
    audit["metadata"]["inputs"] = {
        "movement_corridors": str(movement_path),
        "junction_areas": str(junction_areas_path),
        "road_graph": str(road_graph_path),
        "short_edge_absorption_candidates": str(short_edge_path) if short_edge_path.exists() else "",
    }
    report["inputs"] = audit["metadata"]["inputs"]
    report["outputs"] = {"audit": str(output_path), "report": str(report_path)}
    write_json(output_path, audit)
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
