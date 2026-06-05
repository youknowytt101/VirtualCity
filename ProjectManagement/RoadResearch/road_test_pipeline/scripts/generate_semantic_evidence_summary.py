#!/usr/bin/env python3
"""Generate per-road semantic evidence for LaneForge review.

This report is a review aid, not a truth mutation stage. It gathers the current
road graph observations, active lane transactions, and lane graph outputs so the
viewer can explain why a road currently has its lane geometry.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SCHEMA = "lane_upgrade_system.semantic_evidence_summary.v1"
POLICY_ID = "semantic_evidence_review_aid_v1"
TEMPORARY_LANE_POLICY = "temporary_all_roads_bidirectional_two_lane_v1"


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)


def parse_int(value: Any) -> int | None:
    if value in {"", None}:
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def active_upgrades_by_road(active: dict[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for item in active.get("active_upgrades", []) or []:
        if not bool(item.get("enabled", True)):
            continue
        road_id = str(item.get("road_id") or "").strip()
        if road_id:
            output[road_id] = item
    return output


def lanes_by_road(lane_graph: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for lane in lane_graph.get("lanes", []) or []:
        road_id = str(lane.get("road_id") or "").strip()
        if road_id:
            output[road_id].append(lane)
    return dict(output)


def geometry_physical_lane_count(lanes: list[dict[str, Any]]) -> int:
    if not lanes:
        return 0
    if any(bool(lane.get("physical_lane_shared")) for lane in lanes):
        return 1
    return len(lanes)


def first_nonempty(items: list[dict[str, Any]], key: str, default: Any = "") -> Any:
    for item in items:
        value = item.get(key)
        if value not in {"", None}:
            return value
    return default


def source_tag(edge: dict[str, Any], key: str) -> str:
    tags = edge.get("provider_tags") or {}
    value = tags.get(key, edge.get(key, ""))
    return str(value or "")


def lane_count_evidence(
    *,
    edge: dict[str, Any],
    lanes: list[dict[str, Any]],
    active_upgrade: dict[str, Any] | None,
) -> dict[str, Any]:
    source_lanes = parse_int(edge.get("lanes"))
    geometry_lane_count = geometry_physical_lane_count(lanes)
    if active_upgrade:
        source = "lane_upgrade_transaction"
        confidence_tier = "manual_reviewed_override"
        target = parse_int(active_upgrade.get("target_physical_lane_count")) or geometry_lane_count
    else:
        source = "temporary_bidirectional_policy"
        confidence_tier = "temporary_policy_review_required"
        target = geometry_lane_count
    return {
        "source_lanes": source_lanes,
        "source_lanes_raw": source_tag(edge, "lanes"),
        "source_lanes_source": str(edge.get("lanes_source") or ""),
        "geometry_physical_lane_count": target,
        "geometry_lane_records": len(lanes),
        "geometry_lane_count_source": source,
        "confidence_tier": confidence_tier,
    }


def review_flags(
    *,
    edge: dict[str, Any],
    lanes: list[dict[str, Any]],
    active_upgrade: dict[str, Any] | None,
    lane_count: dict[str, Any],
) -> list[str]:
    flags: list[str] = []
    width_source = str(edge.get("width_source") or "")
    if width_source in {"", "default"}:
        flags.append("width_fallback")
    if not source_tag(edge, "turn_lanes") and not source_tag(edge, "turn_lanes:forward") and not source_tag(edge, "turn_lanes:backward"):
        flags.append("missing_turn_lanes")
    if bool(edge.get("oneway")):
        flags.append("source_oneway_overridden_by_temporary_bidirectional_policy")
    source_lanes = lane_count.get("source_lanes")
    geometry_lanes = lane_count.get("geometry_physical_lane_count")
    if source_lanes and geometry_lanes and int(source_lanes) != int(geometry_lanes):
        flags.append("source_lane_count_differs_from_geometry")
    if active_upgrade:
        flags.append("active_lane_upgrade_transaction")
    if int(edge.get("road_chain_fragment_count") or 0) > 1:
        flags.append("road_chain_fragment")
    if any("lane_count_set_by_lane_upgrade_transaction" in (lane.get("policy_issues") or []) for lane in lanes):
        flags.append("lane_count_set_by_lane_upgrade_transaction")
    return flags


def build_edge_record(
    *,
    edge: dict[str, Any],
    lanes: list[dict[str, Any]],
    active_upgrade: dict[str, Any] | None,
) -> dict[str, Any]:
    lane_count = lane_count_evidence(edge=edge, lanes=lanes, active_upgrade=active_upgrade)
    return {
        "road_id": str(edge.get("edge_id") or ""),
        "canonical_road_id": str(edge.get("canonical_road_id") or edge.get("source_feature_id") or ""),
        "road_chain_id": str(edge.get("road_chain_id") or ""),
        "road_chain_fragment_index": edge.get("road_chain_fragment_index"),
        "road_chain_fragment_count": edge.get("road_chain_fragment_count"),
        "name": str(edge.get("name") or ""),
        "highway": str(edge.get("highway") or edge.get("road_class") or ""),
        "length_m": edge.get("length_m"),
        "source": {
            "provider": str(edge.get("source_provider") or ""),
            "source_feature_ids": edge.get("source_feature_ids") or [],
            "provider_tags": edge.get("provider_tags") or {},
            "oneway": bool(edge.get("oneway")),
            "oneway_raw": source_tag(edge, "oneway"),
            "oneway_direction": str(edge.get("oneway_direction") or ""),
            "lanes": lane_count["source_lanes"],
            "lanes_raw": lane_count["source_lanes_raw"],
            "lanes_source": lane_count["source_lanes_source"],
            "turn_lanes": source_tag(edge, "turn_lanes"),
            "turn_lanes_forward": source_tag(edge, "turn_lanes:forward") or source_tag(edge, "turn_lanes_forward"),
            "turn_lanes_backward": source_tag(edge, "turn_lanes:backward") or source_tag(edge, "turn_lanes_backward"),
            "width_m": edge.get("width_m"),
            "width_source": str(edge.get("width_source") or ""),
        },
        "geometry": {
            "physical_lane_count": lane_count["geometry_physical_lane_count"],
            "lane_records": lane_count["geometry_lane_records"],
            "lane_count_source": lane_count["geometry_lane_count_source"],
            "lane_sources": sorted({str(lane.get("source") or "") for lane in lanes if str(lane.get("source") or "")}),
            "width_m": first_nonempty(lanes, "width_m", 0),
            "width_source": first_nonempty(lanes, "width_source", ""),
            "width_confidence": first_nonempty(lanes, "width_confidence", 0),
            "traffic_policy": first_nonempty(lanes, "traffic_policy", TEMPORARY_LANE_POLICY),
            "traffic_side_assumption": first_nonempty(lanes, "traffic_side_assumption", ""),
        },
        "active_lane_upgrade": active_upgrade or {},
        "review": {
            "confidence_tier": lane_count["confidence_tier"],
            "flags": review_flags(edge=edge, lanes=lanes, active_upgrade=active_upgrade, lane_count=lane_count),
        },
    }


def build_summary(root: Path, area_id: str) -> dict[str, Any]:
    processed = root / "data" / "processed"
    road_graph_path = processed / f"{area_id}_road_graph.json"
    lane_graph_path = processed / f"{area_id}_lane_graph.json"
    active_path = processed / f"{area_id}_lane_upgrade_overrides.json"
    road_graph = read_json(road_graph_path)
    lane_graph = read_json(lane_graph_path)
    active = read_json(active_path)
    active_by_road = active_upgrades_by_road(active)
    lane_index = lanes_by_road(lane_graph)

    records = [
        build_edge_record(
            edge=edge,
            lanes=lane_index.get(str(edge.get("edge_id") or ""), []),
            active_upgrade=active_by_road.get(str(edge.get("edge_id") or "")),
        )
        for edge in road_graph.get("edges", []) or []
    ]

    flag_counts = Counter(flag for record in records for flag in record["review"]["flags"])
    confidence_counts = Counter(record["review"]["confidence_tier"] for record in records)
    highway_counts = Counter(record["highway"] for record in records)
    return {
        "type": "semantic_evidence_summary",
        "metadata": {
            "area_id": area_id,
            "schema": SCHEMA,
            "system": "LaneForge",
            "policy_id": POLICY_ID,
            "source_road_graph": rel(road_graph_path, root),
            "source_lane_graph": rel(lane_graph_path, root),
            "source_active_lane_upgrades": rel(active_path, root),
            "note": "Review aid only; this file does not mutate raw, repaired, canonical, road_graph, lane_graph, or package truth.",
        },
        "counts": {
            "road_edges": len(records),
            "active_lane_upgrade_edges": sum(1 for record in records if record["active_lane_upgrade"]),
            "source_oneway_edges": sum(1 for record in records if record["source"]["oneway"]),
            "source_lanes_tag_edges": sum(1 for record in records if record["source"]["lanes_source"] == "tag"),
            "width_fallback_edges": flag_counts.get("width_fallback", 0),
            "missing_turn_lanes_edges": flag_counts.get("missing_turn_lanes", 0),
            "source_lane_count_differs_from_geometry_edges": flag_counts.get("source_lane_count_differs_from_geometry", 0),
        },
        "confidence_tier_counts": dict(sorted(confidence_counts.items())),
        "review_flag_counts": dict(sorted(flag_counts.items())),
        "highway_counts": dict(sorted(highway_counts.items())),
        "edges": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate LaneForge semantic evidence summary.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--output", default="", help="Optional output path. Defaults to reports/<area>_semantic_evidence_summary.json.")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    summary = build_summary(root, args.area_id)
    report_path = Path(args.output) if args.output else root / "reports" / f"{args.area_id}_semantic_evidence_summary.json"
    processed_path = root / "data" / "processed" / f"{args.area_id}_semantic_evidence_summary.json"
    write_json(report_path, summary)
    if processed_path.resolve() != report_path.resolve():
        write_json(processed_path, summary)
    print(json.dumps({
        "area_id": args.area_id,
        "status": "completed",
        "schema": SCHEMA,
        "report": rel(report_path, root),
        "processed": rel(processed_path, root),
        "counts": summary["counts"],
        "review_flag_counts": summary["review_flag_counts"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
