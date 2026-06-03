#!/usr/bin/env python3
"""Plan compound junction merge candidates from anchor-gap audit output.

This stage is intentionally non-destructive. It groups adjacent junction short
links that still cause capacity-limited movement anchors after planned
short-edge absorption previews. The output is a transaction planning artifact,
not a clean skeleton rewrite.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


TARGET_CLASSIFICATION = "adjacent_junction_short_link"
TARGET_ACTION = "compound_junction_merge"
MAX_COMPOUND_BRIDGE_LENGTH_M = 8.0
MIN_EXTERNAL_APPROACHES = 2
RISK_ORDER = {
    "low": 0,
    "medium": 1,
    "high": 2,
}
STATUS_ORDER = {
    "transaction_candidate": 0,
    "qa_candidate": 1,
    "blocked": 2,
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def rounded(value: float) -> float:
    return round(float(value), 3)


def point_from_node(node: dict[str, Any] | None) -> tuple[float, float]:
    if not node:
        return 0.0, 0.0
    return float(node.get("x") or 0.0), float(node.get("z") or 0.0)


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = a[0] - b[0]
    dz = a[1] - b[1]
    return math.sqrt(dx * dx + dz * dz)


def centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    if not points:
        return 0.0, 0.0
    return sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points)


def other_node_for_edge(edge: dict[str, Any] | None, node_id: str) -> str:
    if not edge:
        return ""
    if str(edge.get("from_node") or "") == node_id:
        return str(edge.get("to_node") or "")
    if str(edge.get("to_node") or "") == node_id:
        return str(edge.get("from_node") or "")
    return ""


def build_junction_area_index(junction_areas: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(area.get("node_id") or ""): area
        for area in junction_areas.get("junction_areas", [])
        if str(area.get("node_id") or "")
    }


def build_approach_index(junction_areas: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for area in junction_areas.get("junction_areas", []):
        node_id = str(area.get("node_id") or "")
        for approach in area.get("approaches", []):
            edge_id = str(approach.get("edge_id") or "")
            if node_id and edge_id:
                indexed[(node_id, edge_id)] = approach
    return indexed


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self.parent.setdefault(item, item)
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, a: str, b: str) -> None:
        root_a = self.find(a)
        root_b = self.find(b)
        if root_a != root_b:
            self.parent[root_b] = root_a


def eligible_anchor_records(audit: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        record
        for record in audit.get("remaining_anchor_records", [])
        if str(record.get("classification") or "") == TARGET_CLASSIFICATION
        and str(record.get("recommended_action") or "") == TARGET_ACTION
    ]


def avg(values: list[float]) -> float:
    return sum(values) / max(1, len(values))


def bridge_edge_record(
    *,
    edge_id: str,
    records: list[dict[str, Any]],
    edge: dict[str, Any] | None,
    nodes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    from_node = str((edge or {}).get("from_node") or "")
    to_node = str((edge or {}).get("to_node") or "")
    trim_deficits = [float(record.get("trim_deficit_m") or 0.0) for record in records]
    desired_trims = [float(record.get("desired_trim_m") or 0.0) for record in records]
    entry_trims = [float(record.get("entry_trim_m") or 0.0) for record in records]
    return {
        "edge_id": edge_id,
        "from_node": from_node,
        "to_node": to_node,
        "from_node_kind": str((nodes.get(from_node) or {}).get("kind") or ""),
        "to_node_kind": str((nodes.get(to_node) or {}).get("kind") or ""),
        "road_class": str((edge or {}).get("road_class") or (records[0].get("road_class") if records else "") or ""),
        "name": str((edge or {}).get("name") or ""),
        "length_m": rounded(float((edge or {}).get("length_m") or (records[0].get("edge_length_m") if records else 0.0) or 0.0)),
        "anchor_record_count": len(records),
        "corridor_ids": sorted({str(record.get("corridor_id") or "") for record in records if record.get("corridor_id")}),
        "lane_link_ids": sorted({str(record.get("lane_link_id") or "") for record in records if record.get("lane_link_id")}),
        "avg_desired_trim_m": rounded(avg(desired_trims)),
        "avg_entry_trim_m": rounded(avg(entry_trims)),
        "avg_trim_deficit_m": rounded(avg(trim_deficits)),
        "max_trim_deficit_m": rounded(max(trim_deficits, default=0.0)),
    }


def classify_candidate(
    *,
    issues: list[str],
    max_bridge_length_m: float,
    bridge_count: int,
) -> tuple[str, str]:
    blocking = {
        "missing_bridge_edge",
        "bridge_edge_missing_endpoint",
        "bridge_edge_not_between_junction_nodes",
        "no_compound_bridge_edges",
    }
    if any(issue in blocking for issue in issues):
        return "blocked", "high"
    if issues:
        risk = "medium" if max_bridge_length_m <= MAX_COMPOUND_BRIDGE_LENGTH_M else "high"
        return "qa_candidate", risk
    if bridge_count > 1:
        return "transaction_candidate", "medium"
    return "transaction_candidate", "low"


def component_candidate(
    *,
    candidate_index: int,
    area_id: str,
    component_nodes: set[str],
    component_bridge_edge_ids: list[str],
    records_by_edge: dict[str, list[dict[str, Any]]],
    nodes: dict[str, dict[str, Any]],
    edges: dict[str, dict[str, Any]],
    junction_area_by_node: dict[str, dict[str, Any]],
    approaches: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    member_nodes = sorted(component_nodes)
    bridge_edge_ids = sorted(component_bridge_edge_ids)
    issues: list[str] = []

    if not bridge_edge_ids:
        issues.append("no_compound_bridge_edges")
    bridge_records: list[dict[str, Any]] = []
    affected_records: list[dict[str, Any]] = []
    for edge_id in bridge_edge_ids:
        edge = edges.get(edge_id)
        records = records_by_edge.get(edge_id, [])
        affected_records.extend(records)
        if edge is None:
            issues.append("missing_bridge_edge")
        else:
            endpoints = [str(edge.get("from_node") or ""), str(edge.get("to_node") or "")]
            if not endpoints[0] or not endpoints[1]:
                issues.append("bridge_edge_missing_endpoint")
            endpoint_kinds = [str((nodes.get(node_id) or {}).get("kind") or "") for node_id in endpoints]
            if endpoint_kinds != ["junction", "junction"]:
                issues.append("bridge_edge_not_between_junction_nodes")
        bridge_records.append(bridge_edge_record(edge_id=edge_id, records=records, edge=edge, nodes=nodes))

    for node_id in member_nodes:
        node_kind = str((nodes.get(node_id) or {}).get("kind") or "")
        if node_kind != "junction":
            issues.append("member_node_not_junction")
        if node_id not in junction_area_by_node:
            issues.append("missing_junction_area_for_member")

    bridge_set = set(bridge_edge_ids)
    external_edge_ids = sorted({
        str(edge_id)
        for node_id in member_nodes
        for edge_id in (nodes.get(node_id) or {}).get("incident_edges", [])
        if str(edge_id) not in bridge_set
    })
    if len(external_edge_ids) < MIN_EXTERNAL_APPROACHES:
        issues.append("too_few_external_approaches")

    node_points = [point_from_node(nodes.get(node_id)) for node_id in member_nodes]
    center = centroid(node_points)
    member_junctions: list[dict[str, Any]] = []
    merged_radius = 0.0
    for node_id in member_nodes:
        area = junction_area_by_node.get(node_id) or {}
        node_point = point_from_node(nodes.get(node_id))
        area_center_raw = area.get("center_xz") or [node_point[0], node_point[1]]
        area_center = (float(area_center_raw[0]), float(area_center_raw[1]))
        area_radius = float(area.get("conflict_zone_radius_m") or 0.0)
        merged_radius = max(merged_radius, distance(center, area_center) + area_radius)
        member_junctions.append({
            "junction_id": str(area.get("junction_id") or ""),
            "junction_node_id": node_id,
            "degree": int((nodes.get(node_id) or {}).get("degree") or area.get("degree") or 0),
            "center_xz": [rounded(area_center[0]), rounded(area_center[1])],
            "conflict_zone_radius_m": rounded(area_radius),
        })

    external_approaches: list[dict[str, Any]] = []
    for edge_id in external_edge_ids:
        edge = edges.get(edge_id) or {}
        attached_members = [
            node_id
            for node_id in member_nodes
            if edge_id in [str(item) for item in (nodes.get(node_id) or {}).get("incident_edges", [])]
        ]
        for node_id in attached_members:
            approach = approaches.get((node_id, edge_id)) or {}
            external_approaches.append({
                "junction_node_id": node_id,
                "edge_id": edge_id,
                "other_node_id": other_node_for_edge(edge, node_id),
                "road_class": str(approach.get("road_class") or edge.get("road_class") or ""),
                "edge_length_m": rounded(float(approach.get("edge_length_m") or edge.get("length_m") or 0.0)),
                "desired_trim_m": rounded(float(approach.get("desired_trim_m") or 0.0)),
                "entry_trim_m": rounded(float(approach.get("entry_trim_m") or 0.0)),
                "status": str(approach.get("status") or ""),
                "issues": [str(issue) for issue in approach.get("issues") or []],
            })

    max_bridge_length = max((float(record["length_m"]) for record in bridge_records), default=0.0)
    status, risk = classify_candidate(
        issues=sorted(set(issues)),
        max_bridge_length_m=max_bridge_length,
        bridge_count=len(bridge_records),
    )
    affected_corridor_ids = sorted({str(record.get("corridor_id") or "") for record in affected_records if record.get("corridor_id")})
    affected_lane_link_ids = sorted({str(record.get("lane_link_id") or "") for record in affected_records if record.get("lane_link_id")})

    candidate_id = f"{area_id}_compound_merge_{candidate_index:03d}"
    return {
        "candidate_id": candidate_id,
        "status": status,
        "risk": risk,
        "issues": sorted(set(issues)),
        "transaction_family": "compound_junction_merge（复合路口合并）",
        "member_junction_node_ids": member_nodes,
        "member_junctions": member_junctions,
        "bridge_edge_ids": bridge_edge_ids,
        "bridge_edges": bridge_records,
        "external_approach_edge_ids": external_edge_ids,
        "external_approaches": external_approaches,
        "planned_compound_zone": {
            "center_xz": [rounded(center[0]), rounded(center[1])],
            "conflict_zone_radius_m": rounded(merged_radius),
            "model": "union_of_member_junction_zones（成员路口影响区并集）",
        },
        "affected_anchor_records": len(affected_records),
        "affected_corridor_ids": affected_corridor_ids,
        "affected_lane_link_ids": affected_lane_link_ids,
        "predicted_benefit": {
            "capacity_limited_anchors_explained": len(affected_records),
            "unique_corridors_explained": len(affected_corridor_ids),
            "avg_bridge_length_m": rounded(avg([float(record["length_m"]) for record in bridge_records])),
            "max_bridge_length_m": rounded(max_bridge_length),
            "avg_trim_deficit_m": rounded(avg([float(record.get("trim_deficit_m") or 0.0) for record in affected_records])),
        },
        "transaction_contract": (
            "Candidate only（仅候选）. A later destructive transaction（写入式事务） must trial-merge the "
            "member junction zones（成员路口影响区）, regenerate entry poses（入口姿态） and movement corridors（通行走廊）, "
            "then rollback（回滚） if protected QA（保护质量门禁） regresses."
        ),
    }


def plan_compound_junction_merges(
    *,
    area_id: str,
    movement_anchor_gap_audit: dict[str, Any],
    junction_areas: dict[str, Any],
    road_graph: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    nodes = {str(node.get("node_id") or ""): node for node in road_graph.get("nodes", [])}
    edges = {str(edge.get("edge_id") or ""): edge for edge in road_graph.get("edges", [])}
    junction_area_by_node = build_junction_area_index(junction_areas)
    approaches = build_approach_index(junction_areas)
    target_records = eligible_anchor_records(movement_anchor_gap_audit)
    ignored_classifications = Counter(
        str(record.get("classification") or "unknown")
        for record in movement_anchor_gap_audit.get("remaining_anchor_records", [])
        if record not in target_records
    )

    records_by_edge: dict[str, list[dict[str, Any]]] = defaultdict(list)
    reference_errors = 0
    for record in target_records:
        edge_id = str(record.get("edge_id") or "")
        if not edge_id:
            reference_errors += 1
            continue
        records_by_edge[edge_id].append(record)

    union_find = UnionFind()
    invalid_edge_ids: list[str] = []
    edge_endpoints: dict[str, tuple[str, str]] = {}
    for edge_id in sorted(records_by_edge):
        edge = edges.get(edge_id)
        if edge is None:
            invalid_edge_ids.append(edge_id)
            continue
        from_node = str(edge.get("from_node") or "")
        to_node = str(edge.get("to_node") or "")
        if not from_node or not to_node:
            invalid_edge_ids.append(edge_id)
            continue
        edge_endpoints[edge_id] = (from_node, to_node)
        union_find.union(from_node, to_node)

    component_edges: dict[str, list[str]] = defaultdict(list)
    component_nodes: dict[str, set[str]] = defaultdict(set)
    for edge_id, (from_node, to_node) in edge_endpoints.items():
        root = union_find.find(from_node)
        component_edges[root].append(edge_id)
        component_nodes[root].update([from_node, to_node])

    candidates: list[dict[str, Any]] = []
    for root in sorted(component_edges):
        candidates.append(component_candidate(
            candidate_index=len(candidates),
            area_id=area_id,
            component_nodes=component_nodes[root],
            component_bridge_edge_ids=component_edges[root],
            records_by_edge=records_by_edge,
            nodes=nodes,
            edges=edges,
            junction_area_by_node=junction_area_by_node,
            approaches=approaches,
        ))

    for edge_id in invalid_edge_ids:
        edge_records = records_by_edge.get(edge_id, [])
        candidates.append({
            "candidate_id": f"{area_id}_compound_merge_{len(candidates):03d}",
            "status": "blocked",
            "risk": "high",
            "issues": ["missing_bridge_edge"],
            "transaction_family": "compound_junction_merge（复合路口合并）",
            "member_junction_node_ids": sorted({str(record.get("junction_node_id") or "") for record in edge_records if record.get("junction_node_id")}),
            "bridge_edge_ids": [edge_id],
            "bridge_edges": [bridge_edge_record(edge_id=edge_id, records=edge_records, edge=None, nodes=nodes)],
            "external_approach_edge_ids": [],
            "affected_anchor_records": len(edge_records),
            "affected_corridor_ids": sorted({str(record.get("corridor_id") or "") for record in edge_records if record.get("corridor_id")}),
            "transaction_contract": "Blocked until missing bridge edge reference is resolved.",
        })

    candidates.sort(
        key=lambda item: (
            STATUS_ORDER.get(str(item.get("status") or ""), 99),
            RISK_ORDER.get(str(item.get("risk") or ""), 99),
            -int(item.get("affected_anchor_records") or 0),
            str(item.get("candidate_id") or ""),
        )
    )

    status_counts = Counter(str(candidate.get("status") or "unknown") for candidate in candidates)
    risk_counts = Counter(str(candidate.get("risk") or "unknown") for candidate in candidates)
    issue_counts = Counter(
        str(issue)
        for candidate in candidates
        for issue in candidate.get("issues", [])
    )
    affected_corridors = {
        str(corridor_id)
        for candidate in candidates
        for corridor_id in candidate.get("affected_corridor_ids", [])
        if corridor_id
    }
    candidate_doc = {
        "type": "compound_junction_merge_candidates",
        "metadata": {
            "area_id": area_id,
            "schema": "road_test_pipeline.compound_junction_merge_candidates.v1",
            "coord_domain": "local_xz_m",
            "planning_domain": "compound junction merge（复合路口合并）",
            "contract": (
                "Non-destructive planner（非破坏式规划器） for adjacent_junction_short_link（相邻路口短连接） "
                "records from movement_anchor_gap_audit（通行锚点缺口审计）. It groups short junction-to-junction "
                "bridge edges（桥接短边） into compound junction merge candidates（复合路口合并候选） and does not "
                "modify road_graph（道路图）, clean skeleton（干净道路骨架） or Houdini（胡迪尼） geometry."
            ),
        },
        "candidates": candidates,
    }
    report = {
        "area_id": area_id,
        "stage": "compound_junction_merge_planner_v1",
        "status": "warn" if candidates else "pass",
        "counts": {
            "remaining_anchor_records": len(movement_anchor_gap_audit.get("remaining_anchor_records", [])),
            "eligible_anchor_records": len(target_records),
            "eligible_bridge_edges": len(records_by_edge),
            "candidates": len(candidates),
            "transaction_candidates": status_counts.get("transaction_candidate", 0),
            "reference_errors": reference_errors,
            "status_counts": dict(sorted(status_counts.items())),
            "risk_counts": dict(sorted(risk_counts.items())),
            "issue_counts": dict(sorted(issue_counts.items())),
            "ignored_classification_counts": dict(sorted(ignored_classifications.items())),
            "affected_corridors": len(affected_corridors),
            "affected_anchor_records": sum(int(candidate.get("affected_anchor_records") or 0) for candidate in candidates),
            "max_member_junctions": max((len(candidate.get("member_junction_node_ids", [])) for candidate in candidates), default=0),
            "max_bridge_edges_per_candidate": max((len(candidate.get("bridge_edge_ids", [])) for candidate in candidates), default=0),
        },
        "thresholds": {
            "max_compound_bridge_length_m": MAX_COMPOUND_BRIDGE_LENGTH_M,
            "min_external_approaches": MIN_EXTERNAL_APPROACHES,
        },
        "top_candidates": candidates[:30],
        "next_action": (
            "Use transaction_candidate（事务候选） items to design a compound junction merge transaction（复合路口合并事务）. "
            "The transaction must trial-regenerate entry poses（入口姿态）, movement corridors（通行走廊） and QA reports（质检报告） "
            "before any clean skeleton（干净道路骨架） rewrite is accepted."
        ),
    }
    return candidate_doc, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan compound junction merge candidates from movement anchor gap audit.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--movement-anchor-gap-audit", default="")
    parser.add_argument("--junction-areas", default="")
    parser.add_argument("--road-graph", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    processed = root / "data" / "processed"
    reports = root / "reports"
    audit_path = (
        Path(args.movement_anchor_gap_audit)
        if args.movement_anchor_gap_audit
        else processed / f"{args.area_id}_movement_anchor_gap_audit.json"
    )
    junction_areas_path = Path(args.junction_areas) if args.junction_areas else processed / f"{args.area_id}_junction_areas.json"
    road_graph_path = Path(args.road_graph) if args.road_graph else processed / f"{args.area_id}_road_graph.json"
    output_path = Path(args.output) if args.output else processed / f"{args.area_id}_compound_junction_merge_candidates.json"
    report_path = Path(args.report) if args.report else reports / f"{args.area_id}_compound_junction_merge_report.json"

    candidate_doc, report = plan_compound_junction_merges(
        area_id=args.area_id,
        movement_anchor_gap_audit=read_json(audit_path),
        junction_areas=read_json(junction_areas_path),
        road_graph=read_json(road_graph_path),
    )
    candidate_doc["metadata"]["inputs"] = {
        "movement_anchor_gap_audit": str(audit_path),
        "junction_areas": str(junction_areas_path),
        "road_graph": str(road_graph_path),
    }
    report["inputs"] = candidate_doc["metadata"]["inputs"]
    report["outputs"] = {
        "compound_junction_merge_candidates": str(output_path),
        "report": str(report_path),
    }
    write_json(output_path, candidate_doc)
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
