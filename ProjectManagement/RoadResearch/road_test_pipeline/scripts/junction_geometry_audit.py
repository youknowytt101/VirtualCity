#!/usr/bin/env python3
"""Audit junction connector geometry for engineering-model readiness.

This audit is intentionally stricter than the visual centerline preview. It
does not judge whether the lines look smooth; it flags junctions whose connector
arcs are not ready to become OpenDRIVE-style connecting roads.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


TRIM_SPREAD_WARN_M = 5.0
ENDPOINT_TOO_CLOSE_M = 2.0
ENDPOINT_TOO_FAR_M = 30.0
TURN_SWEEP_MIN_DEG = 25.0
TURN_SWEEP_MAX_DEG = 125.0


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def to_local(lon: float, lat: float, origin_lon: float, origin_lat: float) -> tuple[float, float]:
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(origin_lat))
    return (float(lon) - origin_lon) * m_per_deg_lon, (float(lat) - origin_lat) * m_per_deg_lat


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = a[0] - b[0]
    dz = a[1] - b[1]
    return math.sqrt(dx * dx + dz * dz)


def rounded(value: float) -> float:
    return round(float(value), 3)


def connector_record(
    feature: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    origin_lon: float,
    origin_lat: float,
) -> dict[str, Any] | None:
    props = feature.get("properties") or {}
    junction_id = str(props.get("junction_node_id") or "")
    node = nodes.get(junction_id)
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    if node is None or len(coords) < 2:
        return None

    center = (float(node["x"]), float(node["z"]))
    start = to_local(float(coords[0][0]), float(coords[0][1]), origin_lon, origin_lat)
    end = to_local(float(coords[-1][0]), float(coords[-1][1]), origin_lon, origin_lat)
    start_dist = distance(center, start)
    end_dist = distance(center, end)
    kind = str(props.get("connector_kind") or "unknown")
    radius = float(props.get("arc_radius_m") or 0.0)
    design_min = float(props.get("arc_design_min_radius_m") or 0.0)
    margin = float(props.get("arc_radius_margin_m") or (radius - design_min if design_min > 0 else 0.0))
    sweep = abs(float(props.get("arc_sweep_deg") or 0.0))
    is_turn = kind != "t_through" and kind != "through"

    issues: list[str] = []
    if is_turn and design_min > 0.0 and margin < 0.0:
        issues.append("radius_below_design_min")
    if is_turn and sweep > 0.0 and (sweep < TURN_SWEEP_MIN_DEG or sweep > TURN_SWEEP_MAX_DEG):
        issues.append("turn_sweep_abnormal")
    if min(start_dist, end_dist) < ENDPOINT_TOO_CLOSE_M:
        issues.append("endpoint_too_close_to_junction_center")
    if max(start_dist, end_dist) > ENDPOINT_TOO_FAR_M:
        issues.append("endpoint_too_far_from_junction_center")

    return {
        "connector_id": str(props.get("connector_id") or ""),
        "connector_kind": kind,
        "from_edge_id": str(props.get("from_edge_id") or ""),
        "to_edge_id": str(props.get("to_edge_id") or ""),
        "arc_geometry": str(props.get("arc_geometry") or ""),
        "arc_fit_status": str(props.get("arc_fit_status") or ""),
        "arc_radius_m": rounded(radius),
        "arc_design_min_radius_m": rounded(design_min),
        "arc_radius_margin_m": rounded(margin),
        "arc_sweep_deg_abs": rounded(sweep),
        "start_distance_to_center_m": rounded(start_dist),
        "end_distance_to_center_m": rounded(end_dist),
        "issues": issues,
    }


def audit(
    area_id: str,
    root: Path,
    output_path: Path,
    road_graph_path: Path | None = None,
    optimized_path: Path | None = None,
) -> dict[str, Any]:
    road_graph_path = road_graph_path or root / "data" / "processed" / f"{area_id}_road_graph.json"
    optimized_path = optimized_path or root / "data" / "processed" / f"{area_id}_roads_optimized_centerlines.geojson"
    graph = read_json(road_graph_path)
    optimized = read_json(optimized_path)
    meta = optimized.get("metadata") or graph.get("metadata") or {}
    origin_lon = float(meta["origin_lon"])
    origin_lat = float(meta["origin_lat"])
    nodes = {str(node["node_id"]): node for node in graph.get("nodes", [])}

    by_junction: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for feature in optimized.get("features", []):
        props = feature.get("properties") or {}
        if props.get("vc_part") != "optimized_junction_connector":
            continue
        record = connector_record(feature, nodes, origin_lon, origin_lat)
        if record is None:
            continue
        by_junction[str(props.get("junction_node_id") or "")].append(record)

    junction_reports: list[dict[str, Any]] = []
    issue_counts: Counter = Counter()
    connector_kind_counts: Counter = Counter()
    fit_status_counts: Counter = Counter()
    arc_geometry_counts: Counter = Counter()

    for junction_id, connectors in sorted(by_junction.items()):
        node = nodes[junction_id]
        endpoint_distances: list[float] = []
        turn_radii: list[float] = []
        turn_margins: list[float] = []
        local_issues: Counter = Counter()
        kinds: Counter = Counter()

        for connector in connectors:
            connector_kind_counts[connector["connector_kind"]] += 1
            fit_status_counts[connector["arc_fit_status"]] += 1
            arc_geometry_counts[connector["arc_geometry"]] += 1
            kinds[connector["connector_kind"]] += 1
            endpoint_distances.extend([
                float(connector["start_distance_to_center_m"]),
                float(connector["end_distance_to_center_m"]),
            ])
            if connector["connector_kind"] not in {"t_through", "through"} and connector["arc_radius_m"] > 0:
                turn_radii.append(float(connector["arc_radius_m"]))
                if connector["arc_design_min_radius_m"] > 0:
                    turn_margins.append(float(connector["arc_radius_margin_m"]))
            for issue in connector["issues"]:
                issue_counts[issue] += 1
                local_issues[issue] += 1

        endpoint_spread = max(endpoint_distances) - min(endpoint_distances) if endpoint_distances else 0.0
        if endpoint_spread > TRIM_SPREAD_WARN_M:
            local_issues["junction_trim_spread_excess"] += 1
            issue_counts["junction_trim_spread_excess"] += 1

        report = {
            "junction_id": junction_id,
            "degree": int(node.get("degree") or 0),
            "connector_count": len(connectors),
            "connector_kind_counts": dict(sorted(kinds.items())),
            "endpoint_distance_min_m": rounded(min(endpoint_distances)) if endpoint_distances else 0.0,
            "endpoint_distance_max_m": rounded(max(endpoint_distances)) if endpoint_distances else 0.0,
            "endpoint_distance_spread_m": rounded(endpoint_spread),
            "turn_radius_min_m": rounded(min(turn_radii)) if turn_radii else 0.0,
            "turn_radius_avg_m": rounded(sum(turn_radii) / len(turn_radii)) if turn_radii else 0.0,
            "turn_radius_margin_min_m": rounded(min(turn_margins)) if turn_margins else 0.0,
            "issue_counts": dict(sorted(local_issues.items())),
            "connectors_with_issues": [connector for connector in connectors if connector["issues"]],
        }
        if report["issue_counts"]:
            junction_reports.append(report)

    junction_reports.sort(
        key=lambda item: (
            -sum(int(v) for v in item["issue_counts"].values()),
            item["turn_radius_margin_min_m"],
            -item["endpoint_distance_spread_m"],
        )
    )

    report = {
        "area_id": area_id,
        "stage": "junction_geometry_audit_v1",
        "status": "warn" if issue_counts else "pass",
        "thresholds": {
            "trim_spread_warn_m": TRIM_SPREAD_WARN_M,
            "endpoint_too_close_m": ENDPOINT_TOO_CLOSE_M,
            "endpoint_too_far_m": ENDPOINT_TOO_FAR_M,
            "turn_sweep_min_deg": TURN_SWEEP_MIN_DEG,
            "turn_sweep_max_deg": TURN_SWEEP_MAX_DEG,
        },
        "metrics": {
            "junctions_with_connectors": len(by_junction),
            "junctions_with_issues": len(junction_reports),
            "connectors": sum(len(connectors) for connectors in by_junction.values()),
            "connector_kind_counts": dict(sorted(connector_kind_counts.items())),
            "arc_geometry_counts": dict(sorted(arc_geometry_counts.items())),
            "arc_fit_status_counts": dict(sorted(fit_status_counts.items())),
            "issue_counts": dict(sorted(issue_counts.items())),
        },
        "worst_junctions": junction_reports[:30],
        "inputs": {
            "road_graph": str(road_graph_path),
            "optimized_centerlines": str(optimized_path),
        },
        "next_action": (
            "Use this report to regularize T/cross junction geometry with a shared junction area "
            "and design-radius-driven connector solving."
        ),
    }
    write_json(output_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit optimized junction geometry for engineering readiness.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--root", default="")
    parser.add_argument("--road-graph", default="")
    parser.add_argument("--optimized-centerlines", default="")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    script_path = Path(__file__).resolve()
    root = Path(args.root).resolve() if args.root else pipeline_root_from_script(script_path)
    output_path = (
        Path(args.output).resolve()
        if args.output
        else root / "reports" / f"{args.area_id}_junction_geometry_audit_report.json"
    )
    road_graph_path = Path(args.road_graph).resolve() if args.road_graph else None
    optimized_path = Path(args.optimized_centerlines).resolve() if args.optimized_centerlines else None
    report = audit(args.area_id, root, output_path, road_graph_path, optimized_path)
    print(json.dumps({
        "area_id": report["area_id"],
        "status": report["status"],
        "output": str(output_path),
        "metrics": report["metrics"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
