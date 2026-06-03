#!/usr/bin/env python3
"""Build road-level junction semantics from road_graph.json.

This is the second layer of the road research stack: it classifies each
junction, names approach roles, finds through-road pairs and exports ordered
road-level movements. It does not generate geometry; later lane and surface
builders should consume this model.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


ROAD_CLASS_RANK = {
    "motorway": 7,
    "trunk": 6,
    "primary": 5,
    "secondary": 4,
    "tertiary": 3,
    "residential": 2,
    "unclassified": 2,
    "service": 1,
    "living_street": 1,
}

T_THROUGH_MIN_ANGLE_DEG = 120.0
CROSS_THROUGH_MIN_ANGLE_DEG = 140.0
COMPLEX_THROUGH_MIN_ANGLE_DEG = 135.0
T_ADAPTIVE_THRESHOLDS_DEG = [120.0, 115.0, 110.0, 105.0]
CROSS_ADAPTIVE_THRESHOLDS_DEG = [140.0, 135.0, 130.0, 125.0, 120.0]
COMPLEX_ADAPTIVE_THRESHOLDS_DEG = [135.0, 130.0, 125.0]
JUNCTION_TYPES = ["T", "cross", "Y", "offset", "complex"]
TEMPORARY_DIRECTION_POLICY_ID = "temporary_all_roads_bidirectional_two_lane_v1"
TEMPORARY_LANE_COUNT = 2
TEMPORARY_LANE_WIDTH_M = 3.2
TEMPORARY_TOTAL_WIDTH_M = TEMPORARY_LANE_COUNT * TEMPORARY_LANE_WIDTH_M


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def normalize(v: tuple[float, float]) -> tuple[float, float]:
    length = math.sqrt(v[0] * v[0] + v[1] * v[1])
    if length <= 1e-9:
        return 0.0, 0.0
    return v[0] / length, v[1] / length


def dot(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1]


def cross(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[1] - a[1] * b[0]


def angle_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.acos(max(-1.0, min(1.0, dot(a, b))))


def edge_points(edge: dict[str, Any]) -> list[tuple[float, float]]:
    return [(float(p[0]), float(p[1])) for p in edge["geometry_xz"]]


def direction_out(edge: dict[str, Any], node_id: str) -> tuple[float, float]:
    pts = edge_points(edge)
    if node_id == edge["from_node"]:
        return normalize((pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]))
    return normalize((pts[-2][0] - pts[-1][0], pts[-2][1] - pts[-1][1]))


def edge_priority(edge: dict[str, Any]) -> float:
    road_class = str(edge.get("road_class") or edge.get("highway") or "unclassified")
    rank = ROAD_CLASS_RANK.get(road_class, ROAD_CLASS_RANK.get(str(edge.get("highway") or ""), 1))
    return rank * 10.0 + float(edge.get("width_m") or 0.0)


def pair_key(edge_a: str, edge_b: str) -> tuple[str, str]:
    return tuple(sorted((edge_a, edge_b)))


def source_allows_incoming(edge: dict[str, Any], node_id: str) -> bool:
    if not edge.get("oneway"):
        return True
    direction = str(edge.get("oneway_direction") or "forward")
    if direction == "reverse":
        return node_id == edge["from_node"]
    return node_id == edge["to_node"]


def source_allows_outgoing(edge: dict[str, Any], node_id: str) -> bool:
    if not edge.get("oneway"):
        return True
    direction = str(edge.get("oneway_direction") or "forward")
    if direction == "reverse":
        return node_id == edge["to_node"]
    return node_id == edge["from_node"]


def allows_incoming(_edge: dict[str, Any], _node_id: str) -> bool:
    return True


def allows_outgoing(_edge: dict[str, Any], _node_id: str) -> bool:
    return True


def build_approaches(node: dict[str, Any], edges: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    approaches = []
    for edge_id in node["incident_edges"]:
        edge = edges[edge_id]
        direction = direction_out(edge, node["node_id"])
        source_can_enter = source_allows_incoming(edge, node["node_id"])
        source_can_exit = source_allows_outgoing(edge, node["node_id"])
        source_oneway = bool(edge.get("oneway"))
        policy_issues = []
        if source_oneway:
            policy_issues.append("source_oneway_ignored_by_temporary_bidirectional_two_lane_policy")
        approaches.append({
            "approach_id": f"{node['node_id']}_{edge_id}",
            "edge_id": edge_id,
            "direction_out_xz": [round(direction[0], 6), round(direction[1], 6)],
            "angle_deg": round(math.degrees(math.atan2(direction[1], direction[0])), 3),
            "road_class": edge.get("road_class", edge.get("highway", "unclassified")),
            "highway": edge.get("highway", "unclassified"),
            "lanes": TEMPORARY_LANE_COUNT,
            "width_m": TEMPORARY_TOTAL_WIDTH_M,
            "source_lanes": int(edge.get("lanes") or 1),
            "source_width_m": float(edge.get("width_m") or 0.0),
            "priority": round(edge_priority(edge), 3),
            "oneway": False,
            "oneway_direction": "bidirectional",
            "source_oneway": source_oneway,
            "source_oneway_direction": edge.get("oneway_direction", "unknown"),
            "can_enter_junction": allows_incoming(edge, node["node_id"]),
            "can_exit_junction": allows_outgoing(edge, node["node_id"]),
            "source_can_enter_junction": source_can_enter,
            "source_can_exit_junction": source_can_exit,
            "traffic_direction_policy": TEMPORARY_DIRECTION_POLICY_ID,
            "policy_issues": policy_issues,
            "role": "approach",
        })
    approaches.sort(key=lambda item: item["angle_deg"])
    return approaches


def select_through_pairs(
    approaches: list[dict[str, Any]],
    min_angle: float | None = None,
) -> set[tuple[str, str]]:
    degree = len(approaches)
    if min_angle is None:
        if degree == 3:
            min_angle = T_THROUGH_MIN_ANGLE_DEG
        elif degree == 4:
            min_angle = CROSS_THROUGH_MIN_ANGLE_DEG
        else:
            min_angle = COMPLEX_THROUGH_MIN_ANGLE_DEG

    candidates = []
    for i, a in enumerate(approaches):
        for b in approaches[i + 1 :]:
            da = tuple(a["direction_out_xz"])
            db = tuple(b["direction_out_xz"])
            angle = math.degrees(angle_between(da, db))
            if angle < min_angle:
                continue
            opposite_score = 1.0 - abs(180.0 - angle) / 180.0
            priority_score = (float(a["priority"]) + float(b["priority"])) * 0.01
            candidates.append((opposite_score + priority_score, angle, a, b))
    candidates.sort(key=lambda item: item[0], reverse=True)

    through: set[tuple[str, str]] = set()
    used_edges: set[str] = set()
    max_pairs = max(1, degree // 2)
    for _score, _angle, a, b in candidates:
        if a["edge_id"] in used_edges or b["edge_id"] in used_edges:
            continue
        through.add(pair_key(a["edge_id"], b["edge_id"]))
        used_edges.update((a["edge_id"], b["edge_id"]))
        if len(through) >= max_pairs:
            break
    return through


def classify_from_pairs(approaches: list[dict[str, Any]], through_pairs: set[tuple[str, str]]) -> str:
    degree = len(approaches)
    if degree == 3:
        return "T" if through_pairs else "Y"
    if degree == 4:
        if len(through_pairs) >= 2:
            return "cross"
        if len(through_pairs) == 1:
            return "offset"
        return "complex"
    return "complex"


def adaptive_classify_junction(
    approaches: list[dict[str, Any]],
) -> tuple[str, set[tuple[str, str]], list[dict[str, Any]]]:
    degree = len(approaches)
    if degree == 3:
        thresholds = T_ADAPTIVE_THRESHOLDS_DEG
    elif degree == 4:
        thresholds = CROSS_ADAPTIVE_THRESHOLDS_DEG
    else:
        thresholds = COMPLEX_ADAPTIVE_THRESHOLDS_DEG

    iteration_history = []
    best_type = "complex" if degree != 3 else "Y"
    best_pairs: set[tuple[str, str]] = set()

    for iteration, threshold in enumerate(thresholds):
        pairs = select_through_pairs(approaches, threshold)
        candidate_type = classify_from_pairs(approaches, pairs)
        iteration_history.append({
            "iteration": iteration,
            "through_angle_threshold_deg": threshold,
            "candidate_type": candidate_type,
            "through_pair_count": len(pairs),
        })

        best_type = candidate_type
        best_pairs = pairs

        if degree == 3 and candidate_type in {"T", "Y"}:
            if candidate_type == "T" or iteration == len(thresholds) - 1:
                break
        elif degree == 4 and candidate_type in {"cross", "offset"}:
            break
        elif degree > 4:
            # Complex junctions still keep through candidates for role hints, but
            # their public class remains one of the five requested categories.
            best_type = "complex"
            best_pairs = pairs
            if pairs or iteration == len(thresholds) - 1:
                break

    if best_type not in {"T", "cross", "Y", "offset", "complex"}:
        best_type = "complex"
    return best_type, best_pairs, iteration_history


def assign_roles(approaches: list[dict[str, Any]], through_pairs: set[tuple[str, str]], junction_type: str) -> None:
    pair_strength: dict[tuple[str, str], float] = {}
    by_edge = {approach["edge_id"]: approach for approach in approaches}
    for key in through_pairs:
        a, b = key
        pair_strength[key] = float(by_edge[a]["priority"]) + float(by_edge[b]["priority"])

    major_pair = (
        max(sorted(pair_strength), key=lambda key: (pair_strength[key], key))
        if pair_strength
        else None
    )
    for approach in approaches:
        approach["role"] = "approach"

    if junction_type == "T" and major_pair:
        for approach in approaches:
            approach["role"] = "major_through" if approach["edge_id"] in major_pair else "minor_branch"
        return

    if junction_type in {"cross", "offset"}:
        for key in through_pairs:
            role = "major_through" if key == major_pair else "minor_through"
            for edge_id in key:
                by_edge[edge_id]["role"] = role
        return

    for key in through_pairs:
        for edge_id in key:
            by_edge[edge_id]["role"] = "through_candidate"


def classify_movement(
    from_approach: dict[str, Any],
    to_approach: dict[str, Any],
    through_pairs: set[tuple[str, str]],
) -> str:
    key = pair_key(from_approach["edge_id"], to_approach["edge_id"])
    if key in through_pairs:
        return "through"
    incoming = (-float(from_approach["direction_out_xz"][0]), -float(from_approach["direction_out_xz"][1]))
    outgoing = (float(to_approach["direction_out_xz"][0]), float(to_approach["direction_out_xz"][1]))
    turn_cross = cross(incoming, outgoing)
    if abs(turn_cross) < 0.08:
        return "through_candidate"
    return "left" if turn_cross > 0 else "right"


def build_movements(
    node: dict[str, Any],
    approaches: list[dict[str, Any]],
    through_pairs: set[tuple[str, str]],
    junction_type: str,
) -> list[dict[str, Any]]:
    movements = []
    for from_approach in approaches:
        for to_approach in approaches:
            if from_approach["edge_id"] == to_approach["edge_id"]:
                continue
            allowed = bool(from_approach["can_enter_junction"] and to_approach["can_exit_junction"])
            source_allowed = bool(from_approach["source_can_enter_junction"] and to_approach["source_can_exit_junction"])
            movement_kind = classify_movement(from_approach, to_approach, through_pairs)
            movements.append({
                "movement_id": f"{node['node_id']}_m_{len(movements):03d}",
                "from_edge": from_approach["edge_id"],
                "to_edge": to_approach["edge_id"],
                "kind": movement_kind,
                "allowed": allowed,
                "source_direction_allowed": source_allowed,
                "traffic_direction_policy": TEMPORARY_DIRECTION_POLICY_ID,
                "confidence": 0.82 if junction_type in {"T", "cross"} else 0.62 if junction_type == "offset" else 0.55,
                "source": "geometry_inferred_from_osm_plus_temporary_bidirectional_two_lane_policy",
                "notes": (
                    ["source_oneway_ignored_by_temporary_bidirectional_two_lane_policy"]
                    if allowed and not source_allowed
                    else [] if allowed else ["blocked_by_direction_policy"]
                ),
            })
    return movements


def build_semantics(input_path: Path, output_path: Path, report_path: Path, area_id: str) -> dict[str, Any]:
    graph = read_json(input_path)
    edges = {edge["edge_id"]: edge for edge in graph["edges"]}
    semantic_junctions = []

    for node in graph["nodes"]:
        if node.get("kind") != "junction":
            continue
        approaches = build_approaches(node, edges)
        junction_type, through_pairs, iteration_history = adaptive_classify_junction(approaches)
        assign_roles(approaches, through_pairs, junction_type)
        movements = build_movements(node, approaches, through_pairs, junction_type)

        semantic_junctions.append({
            "junction_id": f"j_{len(semantic_junctions):03d}",
            "node_id": node["node_id"],
            "type": junction_type,
            "center_xz": [float(node["x"]), float(node["z"])],
            "degree": int(node["degree"]),
            "classification_iterations": iteration_history,
            "approaches": approaches,
            "through_pairs": [
                {
                    "edge_a": key[0],
                    "edge_b": key[1],
                }
                for key in sorted(through_pairs)
            ],
            "movements": movements,
        })

    raw_junction_type_counts = Counter(junction["type"] for junction in semantic_junctions)
    junction_type_counts = {kind: raw_junction_type_counts.get(kind, 0) for kind in JUNCTION_TYPES}
    classification_iteration_counts = Counter(
        str(junction["classification_iterations"][-1]["iteration"] if junction["classification_iterations"] else 0)
        for junction in semantic_junctions
    )
    approach_role_counts = Counter(
        approach["role"]
        for junction in semantic_junctions
        for approach in junction["approaches"]
    )
    movement_kind_counts = Counter(
        movement["kind"]
        for junction in semantic_junctions
        for movement in junction["movements"]
        if movement["allowed"]
    )
    blocked_movements = sum(
        1
        for junction in semantic_junctions
        for movement in junction["movements"]
        if not movement["allowed"]
    )
    source_oneway_ignored_approaches = sum(
        1
        for junction in semantic_junctions
        for approach in junction["approaches"]
        if "source_oneway_ignored_by_temporary_bidirectional_two_lane_policy" in approach.get("policy_issues", [])
    )
    source_oneway_blocked_movements_if_trusted = sum(
        1
        for junction in semantic_junctions
        for movement in junction["movements"]
        if movement["allowed"] and not movement.get("source_direction_allowed", True)
    )

    output = {
        "type": "junction_semantics",
        "metadata": {
            "area_id": area_id,
            "schema": "road_test_pipeline.junction_semantics.v1",
            "coord_domain": "local_xz_m",
            "source": str(input_path),
            "active_direction_policy": TEMPORARY_DIRECTION_POLICY_ID,
            "design_note": "Road-level semantic model for later laneLink and junction surface generation.",
        },
        "junctions": semantic_junctions,
    }
    write_json(output_path, output)

    report = {
        "area_id": area_id,
        "stage": "junction_semantics_v1",
        "input": str(input_path),
        "output": str(output_path),
        "counts": {
            "junctions": len(semantic_junctions),
            "approaches": sum(len(junction["approaches"]) for junction in semantic_junctions),
            "through_pairs": sum(len(junction["through_pairs"]) for junction in semantic_junctions),
            "movements": sum(len(junction["movements"]) for junction in semantic_junctions),
            "blocked_movements": blocked_movements,
            "source_oneway_ignored_approaches": source_oneway_ignored_approaches,
            "source_oneway_blocked_movements_if_trusted": source_oneway_blocked_movements_if_trusted,
        },
        "junction_type_counts": junction_type_counts,
        "classification_iteration_counts": dict(sorted(classification_iteration_counts.items())),
        "approach_role_counts": dict(sorted(approach_role_counts.items())),
        "allowed_movement_kind_counts": dict(sorted(movement_kind_counts.items())),
        "notes": [
            "This model classifies road-level junctions and movement intent; it does not generate geometry.",
            "Public junction classes are restricted to T, cross, Y, offset and complex.",
            "Adaptive classification iteratively relaxes through-pair angle thresholds for low-quality OSM geometry.",
            "Movement permissions currently use temporary_all_roads_bidirectional_two_lane_v1（临时全道路双向两车道策略）; OSM oneway（OSM 单行） is retained as source observation（源数据观察值） only.",
            "T and cross junctions are high-confidence; Y, offset and complex junctions remain lower-confidence inference.",
        ],
    }
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build road-level junction semantic model.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--input", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    input_path = Path(args.input) if args.input else root / "data" / "processed" / f"{args.area_id}_road_graph.json"
    output_path = Path(args.output) if args.output else root / "data" / "processed" / f"{args.area_id}_junction_semantics.json"
    report_path = Path(args.report) if args.report else root / "reports" / f"{args.area_id}_junction_semantics_report.json"

    report = build_semantics(input_path, output_path, report_path, args.area_id)
    print(json.dumps({
        "area_id": args.area_id,
        "output": str(output_path),
        "report": str(report_path),
        "counts": report["counts"],
        "junction_type_counts": report["junction_type_counts"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
