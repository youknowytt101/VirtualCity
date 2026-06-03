#!/usr/bin/env python3
"""Build confidence-tagged lane attributes from road_graph.json.

This is a non-destructive normalization layer. It does not build lane geometry;
it records what lane-related facts came from source tags, what was inferred,
and what should remain visible to QA before lane-level junction reconstruction.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


SOURCE_CONFIDENCE = {
    "source_tag": 0.9,
    "source_tag_normalized": 0.78,
    "stage_policy_override": 0.56,
    "inferred_topology": 0.62,
    "inferred_road_class": 0.45,
    "assumed_default": 0.35,
    "missing": 0.0,
}

TEMPORARY_LANE_POLICY_ID = "temporary_all_roads_bidirectional_two_lane_v1"
TEMPORARY_LANE_COUNT = 2
TEMPORARY_LANE_WIDTH_M = 3.2
TEMPORARY_TOTAL_WIDTH_M = TEMPORARY_LANE_COUNT * TEMPORARY_LANE_WIDTH_M
LANE_WIDTH_MIN_M = 2.6
LANE_WIDTH_MAX_M = 4.5


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def rounded(value: float) -> float:
    return round(float(value), 3)


def source_from_graph_source(source: str) -> str:
    if source == "tag":
        return "source_tag"
    if source == "default":
        return "inferred_road_class"
    if source:
        return "source_tag_normalized"
    return "missing"


def field_record(value: Any, source: str, issues: list[str] | None = None) -> dict[str, Any]:
    return {
        "value": value,
        "source": source,
        "confidence": SOURCE_CONFIDENCE.get(source, 0.2),
        "issues": issues or [],
    }


def split_turn_lanes(value: Any) -> list[list[str]]:
    text = str(value or "").strip()
    if not text:
        return []
    lanes: list[list[str]] = []
    for lane_text in text.split("|"):
        options = [item.strip() for item in lane_text.split(";") if item.strip()]
        lanes.append(options or ["unknown"])
    return lanes


def turn_lanes_record(edge: dict[str, Any], lanes: int) -> dict[str, Any]:
    tags = edge.get("provider_tags") or {}
    general = split_turn_lanes(tags.get("turn:lanes"))
    forward = split_turn_lanes(tags.get("turn:lanes:forward"))
    backward = split_turn_lanes(tags.get("turn:lanes:backward"))
    issues: list[str] = []

    if general or forward or backward:
        source = "source_tag"
        if edge.get("oneway") and general and len(general) != lanes:
            issues.append("turn_lanes_count_mismatch")
        if forward and len(forward) > lanes:
            issues.append("turn_lanes_forward_exceeds_lanes")
        if backward and len(backward) > lanes:
            issues.append("turn_lanes_backward_exceeds_lanes")
    else:
        source = "missing"
        issues.append("missing_turn_lanes")

    return {
        "source": source,
        "confidence": SOURCE_CONFIDENCE[source],
        "general": general,
        "forward": forward,
        "backward": backward,
        "issues": issues,
    }


def source_oneway_record(edge: dict[str, Any]) -> dict[str, Any]:
    tags = edge.get("provider_tags") or {}
    if "oneway" in tags:
        source = "source_tag"
    elif edge.get("oneway_direction") == "unknown":
        source = "assumed_default"
    else:
        source = "inferred_topology"
    return field_record(
        {
            "oneway": bool(edge.get("oneway")),
            "direction": str(edge.get("oneway_direction") or "unknown"),
        },
        source,
    )


def policy_oneway_record(edge: dict[str, Any]) -> dict[str, Any]:
    source_record = source_oneway_record(edge)
    issues = ["direction_forced_bidirectional_two_lane_policy"]
    if bool((source_record.get("value") or {}).get("oneway")):
        issues.append("source_oneway_overridden_by_bidirectional_two_lane_policy")
    return field_record(
        {
            "oneway": False,
            "direction": "bidirectional",
        },
        "stage_policy_override",
        sorted(set(issues)),
    )


def lane_attribute_for_edge(edge: dict[str, Any]) -> dict[str, Any]:
    source_lanes = max(1, int(edge.get("lanes") or 1))
    source_width_m = max(0.0, float(edge.get("width_m") or 0.0))
    lanes = TEMPORARY_LANE_COUNT
    width_m = TEMPORARY_TOTAL_WIDTH_M
    per_lane_width = width_m / lanes if lanes else 0.0
    source_lane_source = source_from_graph_source(str(edge.get("lanes_source") or ""))
    source_width_source = source_from_graph_source(str(edge.get("width_source") or ""))
    lane_source = "stage_policy_override"
    width_source = "stage_policy_override"
    issues: list[str] = [
        "direction_forced_bidirectional_two_lane_policy",
        "lane_count_forced_bidirectional_two_lane_policy",
        "lanes_inferred",
        "width_forced_bidirectional_two_lane_policy",
        "width_inferred",
    ]

    if source_lanes != lanes or source_lane_source == "source_tag":
        issues.append("source_lane_count_overridden_by_bidirectional_two_lane_policy")
    if abs(source_width_m - width_m) > 0.01 or source_width_source == "source_tag":
        issues.append("source_width_overridden_by_bidirectional_two_lane_policy")
    if per_lane_width < LANE_WIDTH_MIN_M:
        issues.append("lane_width_too_narrow")
    if per_lane_width > LANE_WIDTH_MAX_M:
        issues.append("lane_width_too_wide")

    turn_record = turn_lanes_record(edge, lanes)
    issues.extend(turn_record["issues"])
    lane_count_record = field_record(lanes, lane_source)
    width_record = field_record(rounded(width_m), width_source)
    source_oneway = source_oneway_record(edge)
    oneway = policy_oneway_record(edge)
    issues.extend(oneway["issues"])
    confidence = min(
        float(lane_count_record["confidence"]),
        float(width_record["confidence"]),
        float(oneway["confidence"]),
        0.55 if turn_record["source"] == "missing" else float(turn_record["confidence"]),
    )

    return {
        "edge_id": str(edge.get("edge_id") or ""),
        "source_feature_id": str(edge.get("source_feature_id") or ""),
        "road_class": str(edge.get("road_class") or edge.get("highway") or "unknown"),
        "highway": str(edge.get("highway") or "unknown"),
        "length_m": rounded(float(edge.get("length_m") or 0.0)),
        "lane_count": lane_count_record,
        "width": width_record,
        "per_lane_width_m": rounded(per_lane_width),
        "oneway": oneway,
        "turn_lanes": turn_record,
        "active_policy": {
            "policy_id": TEMPORARY_LANE_POLICY_ID,
            "description": "Temporary conservative lane model（临时保守车道模型）: every road edge becomes one bidirectional road with two physical lanes.",
            "physical_lane_count": lanes,
            "traffic_direction": "bidirectional",
            "per_lane_width_m": TEMPORARY_LANE_WIDTH_M,
        },
        "source_observation": {
            "lane_count": source_lanes,
            "lane_count_source": source_lane_source,
            "width_m": rounded(source_width_m),
            "width_source": source_width_source,
            "oneway": source_oneway,
        },
        "provider_tags_present": sorted((edge.get("provider_tags") or {}).keys()),
        "overall_confidence": rounded(confidence),
        "issues": sorted(set(issues)),
        "note": "Lane attributes only; lane geometry and lane links are generated by later lane-level stages.",
    }


def build_lane_attribute_model(
    *,
    area_id: str,
    road_graph: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    edges = road_graph.get("edges", [])
    attributes = [lane_attribute_for_edge(edge) for edge in edges]
    issue_counts: Counter[str] = Counter()
    lane_source_counts: Counter[str] = Counter()
    width_source_counts: Counter[str] = Counter()
    turn_source_counts: Counter[str] = Counter()
    confidence_values: list[float] = []

    for item in attributes:
        issue_counts.update(item["issues"])
        lane_source_counts[str(item["lane_count"]["source"])] += 1
        width_source_counts[str(item["width"]["source"])] += 1
        turn_source_counts[str(item["turn_lanes"]["source"])] += 1
        confidence_values.append(float(item["overall_confidence"]))

    model = {
        "type": "lane_attribute_model",
        "metadata": {
            "area_id": area_id,
            "schema": "road_test_pipeline.lane_attribute_model.v1",
            "source": "road_graph",
            "active_lane_policy": TEMPORARY_LANE_POLICY_ID,
            "note": (
                "Confidence-tagged lane attributes for lane-level junction reconstruction; "
                "this artifact does not contain lane geometry."
            ),
        },
        "source_levels": {
            "source_tag": "地图 API 原始字段明确给出。",
            "source_tag_normalized": "地图 API 字段存在但经过标准化。",
            "stage_policy_override": "当前阶段策略覆盖；保留源数据观察值，但后续生成暂时使用策略值。",
            "inferred_topology": "根据拓扑或方向推断。",
            "inferred_road_class": "根据 road_class / highway 道路等级推断。",
            "assumed_default": "没有更好证据时的默认假设。",
            "missing": "缺失，必须进入后续推断或人工复核。",
        },
        "edge_lane_attributes": attributes,
    }
    report = {
        "area_id": area_id,
        "stage": "lane_attribute_model_v1",
        "active_lane_policy": TEMPORARY_LANE_POLICY_ID,
        "status": "warn" if issue_counts else "pass",
        "counts": {
            "edges": len(attributes),
            "lane_source_counts": dict(sorted(lane_source_counts.items())),
            "width_source_counts": dict(sorted(width_source_counts.items())),
            "turn_lanes_source_counts": dict(sorted(turn_source_counts.items())),
            "issue_counts": dict(sorted(issue_counts.items())),
        },
        "metrics": {
            "avg_overall_confidence": rounded(sum(confidence_values) / max(1, len(confidence_values))),
            "min_overall_confidence": rounded(min(confidence_values)) if confidence_values else 0.0,
            "lanes_inferred_ratio": rounded(issue_counts.get("lanes_inferred", 0) / max(1, len(attributes))),
            "width_inferred_ratio": rounded(issue_counts.get("width_inferred", 0) / max(1, len(attributes))),
            "missing_turn_lanes_ratio": rounded(issue_counts.get("missing_turn_lanes", 0) / max(1, len(attributes))),
            "lane_count_policy_override_ratio": rounded(issue_counts.get("lane_count_forced_bidirectional_two_lane_policy", 0) / max(1, len(attributes))),
            "direction_policy_override_ratio": rounded(issue_counts.get("direction_forced_bidirectional_two_lane_policy", 0) / max(1, len(attributes))),
        },
        "next_action": (
            "Use this model as the input contract for lane_graph and lane-level junction reconstruction. "
            "Do not treat inferred/default lane attributes as source truth."
        ),
    }
    return model, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build confidence-tagged lane attributes from road_graph.json.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--road-graph", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    processed = root / "data" / "processed"
    reports = root / "reports"
    road_graph_path = Path(args.road_graph) if args.road_graph else processed / f"{args.area_id}_road_graph.json"
    output_path = Path(args.output) if args.output else processed / f"{args.area_id}_lane_attribute_model.json"
    report_path = Path(args.report) if args.report else reports / f"{args.area_id}_lane_attribute_model_report.json"

    model, report = build_lane_attribute_model(area_id=args.area_id, road_graph=read_json(road_graph_path))
    model["metadata"]["source_road_graph"] = str(road_graph_path)
    report["inputs"] = {"road_graph": str(road_graph_path)}
    report["outputs"] = {"lane_attribute_model": str(output_path), "report": str(report_path)}
    write_json(output_path, model)
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
