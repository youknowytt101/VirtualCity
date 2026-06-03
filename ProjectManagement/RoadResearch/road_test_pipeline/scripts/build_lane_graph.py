#!/usr/bin/env python3
"""Build topology-only lane_graph.json from road graph, lane attributes and junction semantics.

The lane graph is a structured graph artifact, not an image. It creates
directed lane records and candidate lane links with provenance and confidence,
but it does not publish final lane surfaces or final junction geometry.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_CONFIDENCE = 0.35
TURN_INFERENCE_CONFIDENCE_CAP = 0.42
SHARED_LANE_CONFIDENCE_CAP = 0.45
OFFSET_PREVIEW_CONFIDENCE_CAP = 0.62
DIRECTION_POLICY_CONFIDENCE = {
    "source_oneway": 0.9,
    "source_bidirectional": 0.86,
    "known_oneway_corridor": 0.82,
    "temporary_bidirectional_two_lane_policy": 0.56,
    "inferred_bidirectional_prior": 0.58,
    "ambiguous_direction": 0.35,
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


def normalize(v: tuple[float, float]) -> tuple[float, float]:
    length = math.sqrt(v[0] * v[0] + v[1] * v[1])
    if length <= 1e-9:
        return 0.0, 0.0
    return v[0] / length, v[1] / length


def left_normal(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    direction = normalize((b[0] - a[0], b[1] - a[1]))
    return -direction[1], direction[0]


def offset_polyline(points: list[tuple[float, float]], offset_m: float) -> list[list[float]]:
    """Return a lightweight offset preview; this is not final lane geometry."""
    if not points:
        return []
    if len(points) == 1 or abs(offset_m) <= 1e-9:
        return [[rounded(x), rounded(z)] for x, z in points]

    segment_normals = [left_normal(points[i], points[i + 1]) for i in range(len(points) - 1)]
    output: list[list[float]] = []
    for index, point in enumerate(points):
        if index == 0:
            normal = segment_normals[0]
        elif index == len(points) - 1:
            normal = segment_normals[-1]
        else:
            prev_n = segment_normals[index - 1]
            next_n = segment_normals[index]
            normal = normalize((prev_n[0] + next_n[0], prev_n[1] + next_n[1]))
            if normal == (0.0, 0.0):
                normal = next_n
        output.append([
            rounded(point[0] + normal[0] * offset_m),
            rounded(point[1] + normal[1] * offset_m),
        ])
    return output


def edge_points(edge: dict[str, Any], direction: str) -> list[tuple[float, float]]:
    points = [(float(p[0]), float(p[1])) for p in edge.get("geometry_xz", [])]
    if direction == "backward":
        return list(reversed(points))
    return points


def lane_attribute_index(model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("edge_id") or ""): item
        for item in model.get("edge_lane_attributes", [])
    }


def fallback_lane_attribute(edge: dict[str, Any]) -> dict[str, Any]:
    lanes = max(1, int(edge.get("lanes") or 1))
    width_m = max(0.0, float(edge.get("width_m") or lanes * 3.2))
    return {
        "edge_id": str(edge.get("edge_id") or ""),
        "source_feature_id": str(edge.get("source_feature_id") or ""),
        "road_class": str(edge.get("road_class") or edge.get("highway") or "unknown"),
        "highway": str(edge.get("highway") or "unknown"),
        "length_m": rounded(float(edge.get("length_m") or 0.0)),
        "lane_count": {
            "value": lanes,
            "source": str(edge.get("lanes_source") or "missing"),
            "confidence": DEFAULT_CONFIDENCE,
            "issues": ["lane_attribute_missing_from_model"],
        },
        "width": {
            "value": rounded(width_m),
            "source": str(edge.get("width_source") or "missing"),
            "confidence": DEFAULT_CONFIDENCE,
            "issues": ["lane_attribute_missing_from_model"],
        },
        "per_lane_width_m": rounded(width_m / max(1, lanes)),
        "oneway": {
            "value": {
                "oneway": bool(edge.get("oneway")),
                "direction": str(edge.get("oneway_direction") or "unknown"),
            },
            "source": "missing",
            "confidence": DEFAULT_CONFIDENCE,
            "issues": ["lane_attribute_missing_from_model"],
        },
        "turn_lanes": {
            "source": "missing",
            "confidence": 0.0,
            "general": [],
            "forward": [],
            "backward": [],
            "issues": ["missing_turn_lanes"],
        },
        "overall_confidence": DEFAULT_CONFIDENCE,
        "issues": ["lane_attribute_missing_from_model", "missing_turn_lanes"],
    }


def as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def as_int(value: Any, default: int) -> int:
    try:
        parsed = int(float(value))
        return parsed if parsed > 0 else default
    except Exception:
        return default


def one_way_info(edge: dict[str, Any], attr: dict[str, Any]) -> tuple[bool, str]:
    value = (attr.get("oneway") or {}).get("value") or {}
    if isinstance(value, dict):
        oneway = bool(value.get("oneway", edge.get("oneway")))
        direction = str(value.get("direction") or edge.get("oneway_direction") or "unknown")
        return oneway, direction
    return bool(edge.get("oneway")), str(edge.get("oneway_direction") or "unknown")


def traffic_direction_policy(edge: dict[str, Any], attr: dict[str, Any]) -> dict[str, Any]:
    """Classify traffic direction without pretending inferred defaults are source truth."""
    oneway, oneway_direction = one_way_info(edge, attr)
    source = str((attr.get("oneway") or {}).get("source") or "missing")
    direction = "backward" if oneway_direction == "reverse" else "forward"

    if source == "stage_policy_override":
        return {
            "policy": "temporary_bidirectional_two_lane_policy",
            "source": source,
            "directions": ["forward", "backward"],
            "confidence": DIRECTION_POLICY_CONFIDENCE["temporary_bidirectional_two_lane_policy"],
            "issues": ["direction_forced_bidirectional_two_lane_policy"],
            "rationale": "Current stage policy（当前阶段策略） forces every road to bidirectional two-lane fallback（双向两车道兜底）.",
        }

    if oneway:
        policy = "source_oneway" if source == "source_tag" else "known_oneway_corridor"
        return {
            "policy": policy,
            "source": source,
            "directions": [direction],
            "confidence": DIRECTION_POLICY_CONFIDENCE[policy],
            "issues": [] if source == "source_tag" else ["oneway_inferred_without_source_tag"],
            "rationale": "oneway（单行） is explicit in source tags." if source == "source_tag" else "oneway（单行） inferred by policy context.",
        }

    if source == "source_tag":
        return {
            "policy": "source_bidirectional",
            "source": source,
            "directions": ["forward", "backward"],
            "confidence": DIRECTION_POLICY_CONFIDENCE["source_bidirectional"],
            "issues": [],
            "rationale": "source tag explicitly allows bidirectional（双向） travel.",
        }

    if oneway_direction in {"unknown", "bidirectional", ""}:
        return {
            "policy": "inferred_bidirectional_prior",
            "source": source,
            "directions": ["forward", "backward"],
            "confidence": DIRECTION_POLICY_CONFIDENCE["inferred_bidirectional_prior"],
            "issues": ["direction_inferred_bidirectional_prior"],
            "rationale": "oneway（单行） is missing/unknown; Pattaya local-road prior prefers bidirectional fallback（双向兜底）.",
        }

    return {
        "policy": "ambiguous_direction",
        "source": source,
        "directions": ["forward", "backward"],
        "confidence": DIRECTION_POLICY_CONFIDENCE["ambiguous_direction"],
        "issues": ["ambiguous_direction_policy"],
        "rationale": "traffic direction（交通方向） is ambiguous; keep bidirectional fallback at low confidence.",
    }


def direction_counts(total_lanes: int, direction_policy: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    issues: list[str] = []
    directions = [str(direction) for direction in direction_policy.get("directions") or ["forward", "backward"]]
    policy_name = str(direction_policy.get("policy") or "ambiguous_direction")
    issues.extend(str(issue) for issue in direction_policy.get("issues") or [])

    if len(directions) == 1:
        return [{"direction": directions[0], "count": total_lanes, "shared_physical_lane": False, "mode": policy_name}], issues

    if total_lanes == 1:
        issues.append("bidirectional_shared_physical_lane")
        return [
            {"direction": "forward", "count": 1, "shared_physical_lane": True, "mode": "bidirectional_shared"},
            {"direction": "backward", "count": 1, "shared_physical_lane": True, "mode": "bidirectional_shared"},
        ], issues

    forward_count = (total_lanes + 1) // 2
    backward_count = total_lanes // 2
    if total_lanes % 2 == 1:
        issues.append("ambiguous_bidirectional_odd_lane_split")
    return [
        {"direction": "forward", "count": forward_count, "shared_physical_lane": False, "mode": "bidirectional_split"},
        {"direction": "backward", "count": backward_count, "shared_physical_lane": False, "mode": "bidirectional_split"},
    ], issues


def offsets_for_plan(
    *,
    mode: str,
    count: int,
    lane_width_m: float,
    traffic_side: str,
    shared_physical_lane: bool,
) -> list[float]:
    if shared_physical_lane:
        return [0.0]
    if mode == "oneway":
        if count == 1:
            return [0.0]
        return [((count - 1) * 0.5 - index) * lane_width_m for index in range(count)]
    sign = 1.0 if traffic_side == "left" else -1.0
    return [sign * (index + 0.5) * lane_width_m for index in range(count)]


def turn_options_for_lane(
    *,
    attr: dict[str, Any],
    direction: str,
    lane_index: int,
    is_oneway: bool,
) -> tuple[list[str], str, list[str]]:
    turn = attr.get("turn_lanes") or {}
    directional = turn.get(direction) or []
    source = str(turn.get("source") or "missing")
    issues: list[str] = []

    if directional:
        if lane_index < len(directional):
            return [str(item) for item in directional[lane_index]], source, issues
        issues.append(f"turn_lanes_{direction}_count_mismatch")
        return ["unknown"], source, issues

    general = turn.get("general") or []
    if general and is_oneway:
        if lane_index < len(general):
            return [str(item) for item in general[lane_index]], source, issues
        issues.append("turn_lanes_count_mismatch")
        return ["unknown"], source, issues

    if general and not is_oneway:
        issues.append("ambiguous_bidirectional_general_turn_lanes")
    issues.append("missing_turn_lanes")
    return ["unknown"], "missing", issues


def lane_confidence(attr: dict[str, Any], lane_issues: list[str], shared_physical_lane: bool) -> float:
    confidence = as_float(attr.get("overall_confidence"), DEFAULT_CONFIDENCE)
    if "missing_turn_lanes" in lane_issues:
        confidence = min(confidence, TURN_INFERENCE_CONFIDENCE_CAP)
    if shared_physical_lane:
        confidence = min(confidence, SHARED_LANE_CONFIDENCE_CAP)
    confidence = min(confidence, OFFSET_PREVIEW_CONFIDENCE_CAP)
    return rounded(confidence)


def build_lanes_for_edge(
    *,
    edge: dict[str, Any],
    attr: dict[str, Any],
    traffic_side: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    edge_id = str(edge.get("edge_id") or "")
    total_lanes = as_int((attr.get("lane_count") or {}).get("value"), as_int(edge.get("lanes"), 1))
    total_width_m = as_float((attr.get("width") or {}).get("value"), as_float(edge.get("width_m"), total_lanes * 3.2))
    lane_width_m = max(1.0, total_width_m / max(1, total_lanes))
    oneway, oneway_direction = one_way_info(edge, attr)
    direction_policy = traffic_direction_policy(edge, attr)
    plans, split_issues = direction_counts(total_lanes, direction_policy)
    lanes: list[dict[str, Any]] = []
    edge_issues = sorted(set((attr.get("issues") or []) + split_issues))

    for plan in plans:
        direction = str(plan["direction"])
        direction_count = int(plan["count"])
        offsets = offsets_for_plan(
            mode=str(plan["mode"]),
            count=direction_count,
            lane_width_m=lane_width_m,
            traffic_side=traffic_side,
            shared_physical_lane=bool(plan["shared_physical_lane"]),
        )
        points = edge_points(edge, direction)
        travel_from_node = str(edge.get("from_node") if direction == "forward" else edge.get("to_node"))
        travel_to_node = str(edge.get("to_node") if direction == "forward" else edge.get("from_node"))

        for lane_index, offset_m in enumerate(offsets):
            turn_options, turn_source, turn_issues = turn_options_for_lane(
                attr=attr,
                direction=direction,
                lane_index=lane_index,
                is_oneway=oneway,
            )
            lane_issues = sorted(set(edge_issues + turn_issues + ["offset_centerline_preview_only"]))
            lane_id = f"ln_{edge_id}_{'f' if direction == 'forward' else 'b'}_{lane_index:02d}"
            lanes.append({
                "lane_id": lane_id,
                "edge_id": edge_id,
                "source_feature_id": str(edge.get("source_feature_id") or attr.get("source_feature_id") or ""),
                "direction": direction,
                "travel_from_node": travel_from_node,
                "travel_to_node": travel_to_node,
                "road_class": str(edge.get("road_class") or attr.get("road_class") or "unknown"),
                "highway": str(edge.get("highway") or attr.get("highway") or "unknown"),
                "physical_lane_count_on_edge": total_lanes,
                "directed_lane_count_for_direction": direction_count,
                "lane_index_in_direction": lane_index,
                "lane_order": "left_to_right_in_travel_direction",
                "traffic_side_assumption": traffic_side,
                "traffic_direction_policy": str(direction_policy["policy"]),
                "traffic_direction_confidence": rounded(float(direction_policy["confidence"])),
                "traffic_direction_rationale": str(direction_policy["rationale"]),
                "shared_physical_lane": bool(plan["shared_physical_lane"]),
                "width_m": rounded(lane_width_m),
                "lateral_offset_m": rounded(offset_m),
                "centerline_xz": offset_polyline(points, offset_m),
                "centerline_quality": "approximate_offset_preview_not_final_geometry",
                "turn_options": turn_options,
                "sources": {
                    "lane_count": str((attr.get("lane_count") or {}).get("source") or "missing"),
                    "width": str((attr.get("width") or {}).get("source") or "missing"),
                    "oneway": str((attr.get("oneway") or {}).get("source") or "missing"),
                    "traffic_direction": str(direction_policy["source"]),
                    "turn_lanes": turn_source,
                },
                "attribute_confidence": rounded(as_float(attr.get("overall_confidence"), DEFAULT_CONFIDENCE)),
                "overall_confidence": lane_confidence(attr, lane_issues, bool(plan["shared_physical_lane"])),
                "issues": lane_issues,
            })

    group = {
        "edge_id": edge_id,
        "source_feature_id": str(edge.get("source_feature_id") or attr.get("source_feature_id") or ""),
        "physical_lane_count": total_lanes,
        "directed_lane_count": len(lanes),
        "width_m": rounded(total_width_m),
        "lane_width_m": rounded(lane_width_m),
        "oneway": oneway,
        "oneway_direction": oneway_direction,
        "traffic_direction_policy": str(direction_policy["policy"]),
        "traffic_direction_confidence": rounded(float(direction_policy["confidence"])),
        "traffic_direction_rationale": str(direction_policy["rationale"]),
        "direction_groups": [
            {
                "direction": str(plan["direction"]),
                "count": int(plan["count"]),
                "shared_physical_lane": bool(plan["shared_physical_lane"]),
                "mode": str(plan["mode"]),
            }
            for plan in plans
        ],
        "lane_ids": [lane["lane_id"] for lane in lanes],
        "sources": {
            "lane_count": str((attr.get("lane_count") or {}).get("source") or "missing"),
            "width": str((attr.get("width") or {}).get("source") or "missing"),
            "oneway": str((attr.get("oneway") or {}).get("source") or "missing"),
            "traffic_direction": str(direction_policy["source"]),
            "turn_lanes": str((attr.get("turn_lanes") or {}).get("source") or "missing"),
        },
        "issues": edge_issues,
    }
    return lanes, group, edge_issues


def sorted_lanes_left_to_right(lanes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(lanes, key=lambda lane: (-float(lane.get("lateral_offset_m") or 0.0), str(lane.get("lane_id") or "")))


def turn_matches(options: list[str], movement_kind: str) -> bool:
    normalized = {str(item).strip().lower() for item in options}
    if not normalized or normalized == {"unknown"}:
        return False
    if movement_kind == "through_candidate":
        movement_kind = "through"
    aliases = {
        "through": {"through", "straight"},
        "left": {"left", "slight_left", "sharp_left"},
        "right": {"right", "slight_right", "sharp_right"},
    }
    allowed = aliases.get(movement_kind, {movement_kind})
    return bool(normalized & allowed)


def select_incoming_lanes(
    incoming: list[dict[str, Any]],
    movement_kind: str,
) -> tuple[list[dict[str, Any]], str, list[str]]:
    ordered = sorted_lanes_left_to_right(incoming)
    tagged = [lane for lane in ordered if turn_matches(lane.get("turn_options") or [], movement_kind)]
    if tagged:
        return tagged, "source_turn_lanes", []

    issues = ["inferred_without_turn_lanes"]
    if movement_kind == "left":
        return ordered[:1], "inferred_lane_rank", issues
    if movement_kind == "right":
        return ordered[-1:], "inferred_lane_rank", issues
    return ordered, "inferred_lane_rank", issues


def match_lanes_by_rank(
    from_lanes: list[dict[str, Any]],
    to_lanes: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    ordered_from = sorted_lanes_left_to_right(from_lanes)
    ordered_to = sorted_lanes_left_to_right(to_lanes)
    if not ordered_from or not ordered_to:
        return []

    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for index, from_lane in enumerate(ordered_from):
        if len(ordered_from) == 1:
            target_index = min(len(ordered_to) - 1, len(ordered_to) // 2)
        else:
            target_index = round(index * (len(ordered_to) - 1) / (len(ordered_from) - 1))
        pairs.append((from_lane, ordered_to[target_index]))
    return pairs


def lane_link_confidence(
    from_lane: dict[str, Any],
    to_lane: dict[str, Any],
    movement_confidence: float,
    issues: list[str],
) -> float:
    confidence = min(
        as_float(from_lane.get("overall_confidence"), DEFAULT_CONFIDENCE),
        as_float(to_lane.get("overall_confidence"), DEFAULT_CONFIDENCE),
        movement_confidence,
    )
    if "inferred_without_turn_lanes" in issues:
        confidence = min(confidence, TURN_INFERENCE_CONFIDENCE_CAP)
    return rounded(confidence)


def endpoint_lane_indexes(lanes: list[dict[str, Any]]) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], dict[tuple[str, str], list[dict[str, Any]]]]:
    entering: dict[tuple[str, str], list[dict[str, Any]]] = {}
    exiting: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for lane in lanes:
        edge_id = str(lane["edge_id"])
        entering.setdefault((edge_id, str(lane["travel_to_node"])), []).append(lane)
        exiting.setdefault((edge_id, str(lane["travel_from_node"])), []).append(lane)
    return entering, exiting


def build_lane_graph(
    *,
    area_id: str,
    road_graph: dict[str, Any],
    lane_attribute_model: dict[str, Any],
    junction_semantics: dict[str, Any],
    traffic_side: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    attrs = lane_attribute_index(lane_attribute_model)
    lanes: list[dict[str, Any]] = []
    edge_lane_groups: list[dict[str, Any]] = []
    edge_issue_counts: Counter[str] = Counter()

    for edge in road_graph.get("edges", []):
        edge_id = str(edge.get("edge_id") or "")
        edge_lanes, group, group_issues = build_lanes_for_edge(
            edge=edge,
            attr=attrs.get(edge_id) or fallback_lane_attribute(edge),
            traffic_side=traffic_side,
        )
        lanes.extend(edge_lanes)
        edge_lane_groups.append(group)
        edge_issue_counts.update(group_issues)

    entering, exiting = endpoint_lane_indexes(lanes)
    lane_links: list[dict[str, Any]] = []
    junctions: list[dict[str, Any]] = []
    connection_issue_counts: Counter[str] = Counter()

    def add_lane_link(
        *,
        from_lane: dict[str, Any],
        to_lane: dict[str, Any],
        node_id: str,
        link_kind: str,
        movement_kind: str,
        source: str,
        movement_id: str = "",
        junction_id: str = "",
        connection_id: str = "",
        movement_confidence: float = 0.5,
        issues: list[str] | None = None,
    ) -> dict[str, Any]:
        link_issues = sorted(set(issues or []))
        confidence = lane_link_confidence(from_lane, to_lane, movement_confidence, link_issues)
        link = {
            "lane_link_id": f"ll_{len(lane_links):05d}",
            "from_lane_id": str(from_lane["lane_id"]),
            "to_lane_id": str(to_lane["lane_id"]),
            "node_id": node_id,
            "junction_id": junction_id,
            "connection_id": connection_id,
            "semantic_movement_id": movement_id,
            "link_kind": link_kind,
            "movement_kind": movement_kind,
            "source": source,
            "status": "candidate",
            "confidence": confidence,
            "issues": link_issues,
        }
        lane_links.append(link)
        connection_issue_counts.update(link_issues)
        return link

    for junction in junction_semantics.get("junctions", []):
        junction_id = str(junction.get("junction_id") or "")
        node_id = str(junction.get("node_id") or "")
        connections: list[dict[str, Any]] = []
        for movement in junction.get("movements", []):
            if not movement.get("allowed"):
                continue
            from_edge = str(movement.get("from_edge") or "")
            to_edge = str(movement.get("to_edge") or "")
            incoming = entering.get((from_edge, node_id), [])
            outgoing = exiting.get((to_edge, node_id), [])
            movement_kind = str(movement.get("kind") or "unknown")
            movement_issues: list[str] = []
            if not incoming:
                movement_issues.append("missing_incoming_lanes_for_movement")
            if not outgoing:
                movement_issues.append("missing_outgoing_lanes_for_movement")
            if movement_issues:
                connection_issue_counts.update(movement_issues)
                continue

            selected_incoming, selection_source, selection_issues = select_incoming_lanes(incoming, movement_kind)
            pairs = match_lanes_by_rank(selected_incoming, outgoing)
            if not pairs:
                connection_issue_counts.update(["no_lane_pairs_for_movement"])
                continue

            connection_id = f"{junction_id}_conn_{len(connections):03d}"
            link_ids: list[str] = []
            for from_lane, to_lane in pairs:
                issues = list(selection_issues)
                if from_lane.get("sources", {}).get("turn_lanes") == "missing":
                    issues.append("inferred_without_turn_lanes")
                if as_float(from_lane.get("overall_confidence"), DEFAULT_CONFIDENCE) < 0.5:
                    issues.append("low_confidence_from_lane")
                if as_float(to_lane.get("overall_confidence"), DEFAULT_CONFIDENCE) < 0.5:
                    issues.append("low_confidence_to_lane")
                link = add_lane_link(
                    from_lane=from_lane,
                    to_lane=to_lane,
                    node_id=node_id,
                    junction_id=junction_id,
                    connection_id=connection_id,
                    movement_id=str(movement.get("movement_id") or ""),
                    link_kind="junction_movement",
                    movement_kind=movement_kind,
                    source=f"{selection_source}_plus_road_movement",
                    movement_confidence=as_float(movement.get("confidence"), 0.5),
                    issues=issues,
                )
                link_ids.append(str(link["lane_link_id"]))

            connections.append({
                "connection_id": connection_id,
                "semantic_movement_id": str(movement.get("movement_id") or ""),
                "from_edge": from_edge,
                "to_edge": to_edge,
                "turn": movement_kind,
                "source": "junction_semantics_plus_lane_attribute_model",
                "confidence": rounded(as_float(movement.get("confidence"), 0.5)),
                "lane_link_ids": link_ids,
                "issues": sorted(set(selection_issues)),
            })

        junctions.append({
            "junction_id": junction_id,
            "node_id": node_id,
            "type": str(junction.get("type") or "unknown"),
            "degree": int(junction.get("degree") or 0),
            "connections": connections,
        })

    graph_nodes = {str(node.get("node_id") or ""): node for node in road_graph.get("nodes", [])}
    for node_id, node in graph_nodes.items():
        if str(node.get("kind") or "") != "connector":
            continue
        incident_edges = [str(edge_id) for edge_id in node.get("incident_edges", [])]
        if len(incident_edges) != 2:
            continue
        for from_edge in incident_edges:
            for to_edge in incident_edges:
                if from_edge == to_edge:
                    continue
                incoming = entering.get((from_edge, node_id), [])
                outgoing = exiting.get((to_edge, node_id), [])
                for from_lane, to_lane in match_lanes_by_rank(incoming, outgoing):
                    add_lane_link(
                        from_lane=from_lane,
                        to_lane=to_lane,
                        node_id=node_id,
                        link_kind="connector_continuity",
                        movement_kind="through",
                        source="connector_node_rank_match",
                        movement_confidence=0.58,
                        issues=["connector_continuity_inferred"],
                    )

    lane_ids = {str(lane["lane_id"]) for lane in lanes}
    reference_errors = sum(
        1
        for link in lane_links
        if str(link["from_lane_id"]) not in lane_ids or str(link["to_lane_id"]) not in lane_ids
    )
    all_lane_issues = Counter(issue for lane in lanes for issue in lane.get("issues", []))
    all_link_issues = Counter(issue for link in lane_links for issue in link.get("issues", []))
    lane_direction_counts = Counter(str(lane.get("direction") or "unknown") for lane in lanes)
    lane_source_counts = Counter(str(lane.get("sources", {}).get("lane_count") or "missing") for lane in lanes)
    width_source_counts = Counter(str(lane.get("sources", {}).get("width") or "missing") for lane in lanes)
    turn_source_counts = Counter(str(lane.get("sources", {}).get("turn_lanes") or "missing") for lane in lanes)
    traffic_direction_policy_counts = Counter(str(lane.get("traffic_direction_policy") or "unknown") for lane in lanes)
    lane_link_source_counts = Counter(str(link.get("source") or "unknown") for link in lane_links)
    lane_link_kind_counts = Counter(str(link.get("link_kind") or "unknown") for link in lane_links)
    turn_counts = Counter(
        str(connection.get("turn") or "unknown")
        for junction in junctions
        for connection in junction.get("connections", [])
    )
    lane_confidences = [as_float(lane.get("overall_confidence"), 0.0) for lane in lanes]
    link_confidences = [as_float(link.get("confidence"), 0.0) for link in lane_links]
    junction_link_count = sum(1 for link in lane_links if link.get("link_kind") == "junction_movement")
    connection_count = sum(len(junction.get("connections", [])) for junction in junctions)
    issue_counts = edge_issue_counts + all_lane_issues + all_link_issues + connection_issue_counts

    graph = {
        "type": "lane_graph",
        "metadata": {
            "area_id": area_id,
            "schema": "road_test_pipeline.lane_graph.topology.v1",
            "coord_domain": "local_xz_m",
            "traffic_side_assumption": traffic_side,
            "source_road_graph": str((road_graph.get("metadata") or {}).get("source") or "road_graph"),
            "source_lane_attribute_model_schema": str((lane_attribute_model.get("metadata") or {}).get("schema") or ""),
            "source_junction_semantics_schema": str((junction_semantics.get("metadata") or {}).get("schema") or ""),
            "artifact_contract": (
                "lane_graph（车道拓扑图） is structured graph data. PNG/SVG/image exports are "
                "visualization（可视化） only and must not be treated as source truth（源数据真值）."
            ),
            "geometry_contract": (
                "centerline_xz is an approximate offset preview（近似偏移预览） for QA. "
                "Final lane geometry（最终车道几何） belongs to movement corridor and surface stages."
            ),
        },
        "edge_lane_groups": edge_lane_groups,
        "lanes": lanes,
        "junctions": junctions,
        "lane_links": lane_links,
    }

    report = {
        "area_id": area_id,
        "stage": "lane_graph_topology_v1",
        "status": "warn" if issue_counts else "pass",
        "counts": {
            "edges": len(edge_lane_groups),
            "lanes": len(lanes),
            "junctions": len(junctions),
            "connections": connection_count,
            "lane_links": len(lane_links),
            "junction_lane_links": junction_link_count,
            "connector_continuity_links": len(lane_links) - junction_link_count,
            "issue_counts": dict(sorted(issue_counts.items())),
        },
        "lane_direction_counts": dict(sorted(lane_direction_counts.items())),
        "lane_source_counts": dict(sorted(lane_source_counts.items())),
        "width_source_counts": dict(sorted(width_source_counts.items())),
        "turn_lanes_source_counts": dict(sorted(turn_source_counts.items())),
        "traffic_direction_policy_counts": dict(sorted(traffic_direction_policy_counts.items())),
        "turn_counts": dict(sorted(turn_counts.items())),
        "connection_source_counts": {
            "junction_semantics_plus_lane_attribute_model": connection_count,
        },
        "lane_link_source_counts": dict(sorted(lane_link_source_counts.items())),
        "lane_link_kind_counts": dict(sorted(lane_link_kind_counts.items())),
        "fallback_counts": {
            "offset_centerline_preview": len(lanes),
            "shared_bidirectional_physical_lane": all_lane_issues.get("bidirectional_shared_physical_lane", 0),
            "inferred_without_turn_lanes": all_link_issues.get("inferred_without_turn_lanes", 0),
        },
        "metrics": {
            "avg_lane_confidence": rounded(sum(lane_confidences) / max(1, len(lane_confidences))),
            "min_lane_confidence": rounded(min(lane_confidences)) if lane_confidences else 0.0,
            "avg_lane_link_confidence": rounded(sum(link_confidences) / max(1, len(link_confidences))),
            "min_lane_link_confidence": rounded(min(link_confidences)) if link_confidences else 0.0,
            "lane_link_reference_errors": reference_errors,
            "blocked_lane_links": 0,
            "empty_connection_curves": 0,
            "fan_fallback_ratio": 0.0,
            "avg_lane_links_per_junction": rounded(junction_link_count / max(1, len(junctions))),
            "inferred_turn_link_ratio": rounded(all_link_issues.get("inferred_without_turn_lanes", 0) / max(1, len(lane_links))),
            "missing_turn_lanes_lane_ratio": rounded(all_lane_issues.get("missing_turn_lanes", 0) / max(1, len(lanes))),
            "inferred_bidirectional_prior_lane_ratio": rounded(traffic_direction_policy_counts.get("inferred_bidirectional_prior", 0) / max(1, len(lanes))),
            "source_oneway_lane_ratio": rounded(traffic_direction_policy_counts.get("source_oneway", 0) / max(1, len(lanes))),
            "temporary_bidirectional_two_lane_policy_lane_ratio": rounded(traffic_direction_policy_counts.get("temporary_bidirectional_two_lane_policy", 0) / max(1, len(lanes))),
        },
        "next_action": (
            "Use lane_graph（车道拓扑图） as the topology contract（拓扑契约） for movement "
            "corridor solver（通行走廊求解器）. Do not treat offset centerlines as final lane geometry（最终车道几何）."
        ),
    }
    return graph, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build topology-only lane_graph.json.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--road-graph", default="")
    parser.add_argument("--lane-attribute-model", default="")
    parser.add_argument("--junction-semantics", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--report", default="")
    parser.add_argument("--traffic-side", choices=["left", "right"], default="left")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    processed = root / "data" / "processed"
    reports = root / "reports"
    road_graph_path = Path(args.road_graph) if args.road_graph else processed / f"{args.area_id}_road_graph.json"
    lane_attribute_path = Path(args.lane_attribute_model) if args.lane_attribute_model else processed / f"{args.area_id}_lane_attribute_model.json"
    junction_semantics_path = Path(args.junction_semantics) if args.junction_semantics else processed / f"{args.area_id}_junction_semantics.json"
    output_path = Path(args.output) if args.output else processed / f"{args.area_id}_lane_graph.json"
    report_path = Path(args.report) if args.report else reports / f"{args.area_id}_lane_graph_report.json"

    graph, report = build_lane_graph(
        area_id=args.area_id,
        road_graph=read_json(road_graph_path),
        lane_attribute_model=read_json(lane_attribute_path),
        junction_semantics=read_json(junction_semantics_path),
        traffic_side=args.traffic_side,
    )
    graph["metadata"]["inputs"] = {
        "road_graph": str(road_graph_path),
        "lane_attribute_model": str(lane_attribute_path),
        "junction_semantics": str(junction_semantics_path),
    }
    graph["metadata"]["source_road_graph"] = str(road_graph_path)
    report["inputs"] = graph["metadata"]["inputs"]
    report["outputs"] = {"lane_graph": str(output_path), "report": str(report_path)}
    write_json(output_path, graph)
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
