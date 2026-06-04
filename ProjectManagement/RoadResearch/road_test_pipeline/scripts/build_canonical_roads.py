#!/usr/bin/env python3
"""Build canonical road chains from repaired topology edges.

This stage converts the many two-point repaired edges into longer, traceable
road chains. It only merges through degree-2 connector nodes and keeps
junctions, dead ends, bbox exits, and attribute changes as chain boundaries.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


NODE_EPS_M = 0.35
BBOX_EDGE_MARGIN_M = 5.0
DEDUP_EPS_M = 0.05


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def local_projector_from_metadata(fc: dict[str, Any]) -> tuple[float, float]:
    meta = fc.get("metadata") or {}
    origin_lon = meta.get("origin_lon")
    origin_lat = meta.get("origin_lat")
    if origin_lon is not None and origin_lat is not None:
        return float(origin_lon), float(origin_lat)

    bbox = meta.get("bbox_swen")
    if bbox and len(bbox) == 4:
        south, west, north, east = [float(value) for value in bbox]
        return (west + east) * 0.5, (south + north) * 0.5

    coords: list[list[float]] = []
    for feature in fc.get("features", []):
        geom = feature.get("geometry") or {}
        if geom.get("type") == "LineString":
            coords.extend(geom.get("coordinates") or [])
    valid = [coord for coord in coords if len(coord) >= 2]
    if not valid:
        return 0.0, 0.0
    return (
        sum(float(coord[0]) for coord in valid) / len(valid),
        sum(float(coord[1]) for coord in valid) / len(valid),
    )


def to_local(lon: float, lat: float, origin_lon: float, origin_lat: float) -> tuple[float, float]:
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(origin_lat))
    return (lon - origin_lon) * m_per_deg_lon, (lat - origin_lat) * m_per_deg_lat


def to_lonlat(x: float, z: float, origin_lon: float, origin_lat: float) -> tuple[float, float]:
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(origin_lat))
    return origin_lon + x / m_per_deg_lon, origin_lat + z / m_per_deg_lat


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = a[0] - b[0]
    dz = a[1] - b[1]
    return math.sqrt(dx * dx + dz * dz)


def polyline_length(points: list[tuple[float, float]]) -> float:
    return sum(distance(points[index], points[index + 1]) for index in range(len(points) - 1))


def node_key(point: tuple[float, float], eps: float = NODE_EPS_M) -> tuple[int, int]:
    return round(point[0] / eps), round(point[1] / eps)


def local_bbox_from_metadata(
    fc: dict[str, Any],
    origin_lon: float,
    origin_lat: float,
) -> tuple[float, float, float, float] | None:
    bbox = (fc.get("metadata") or {}).get("bbox_swen")
    if not bbox or len(bbox) != 4:
        return None
    south, west, north, east = [float(value) for value in bbox]
    west_x, south_z = to_local(west, south, origin_lon, origin_lat)
    east_x, north_z = to_local(east, north, origin_lon, origin_lat)
    return (
        min(west_x, east_x),
        min(south_z, north_z),
        max(west_x, east_x),
        max(south_z, north_z),
    )


def is_near_bbox_edge(
    point: tuple[float, float],
    bbox: tuple[float, float, float, float] | None,
    margin_m: float = BBOX_EDGE_MARGIN_M,
) -> bool:
    if bbox is None:
        return False
    min_x, min_z, max_x, max_z = bbox
    x, z = point
    if x < min_x - margin_m or x > max_x + margin_m or z < min_z - margin_m or z > max_z + margin_m:
        return False
    return (
        abs(x - min_x) <= margin_m
        or abs(x - max_x) <= margin_m
        or abs(z - min_z) <= margin_m
        or abs(z - max_z) <= margin_m
    )


def normalize_attr(value: Any) -> str:
    return str(value or "").strip().lower()


def edge_signature(props: dict[str, Any]) -> tuple[str, ...]:
    highway = normalize_attr(props.get("highway") or "unknown")
    road_class = normalize_attr(props.get("road_class") or highway)
    return (
        highway,
        road_class,
        normalize_attr(props.get("name")),
        normalize_attr(props.get("oneway")),
        normalize_attr(props.get("lanes")),
        normalize_attr(props.get("width_m")),
        normalize_attr(props.get("bridge")),
        normalize_attr(props.get("tunnel")),
        normalize_attr(props.get("layer")),
    )


def feature_points(feature: dict[str, Any], origin_lon: float, origin_lat: float) -> list[tuple[float, float]]:
    geom = feature.get("geometry") or {}
    if geom.get("type") != "LineString":
        return []
    points: list[tuple[float, float]] = []
    for coord in geom.get("coordinates") or []:
        if len(coord) < 2:
            continue
        points.append(to_local(float(coord[0]), float(coord[1]), origin_lon, origin_lat))
    return points


def compact_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not points:
        return []
    output = [points[0]]
    for point in points[1:]:
        if distance(output[-1], point) <= DEDUP_EPS_M:
            continue
        output.append(point)
    return output


def source_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if value is None or value == "":
        return []
    return [str(value)]


def edge_records(fc: dict[str, Any], origin_lon: float, origin_lat: float) -> tuple[list[dict[str, Any]], dict[tuple[int, int], list[int]], int]:
    records: list[dict[str, Any]] = []
    incident: dict[tuple[int, int], list[int]] = defaultdict(list)
    skipped = 0
    for index, feature in enumerate(fc.get("features", [])):
        points = compact_points(feature_points(feature, origin_lon, origin_lat))
        if len(points) < 2:
            skipped += 1
            continue
        props = dict(feature.get("properties") or {})
        edge_id = len(records)
        start_key = node_key(points[0])
        end_key = node_key(points[-1])
        record = {
            "edge_id": edge_id,
            "points": points,
            "start_key": start_key,
            "end_key": end_key,
            "props": props,
            "signature": edge_signature(props),
            "length_m": polyline_length(points),
        }
        records.append(record)
        incident[start_key].append(edge_id)
        incident[end_key].append(edge_id)
    return records, incident, skipped


def other_node(edge: dict[str, Any], key: tuple[int, int]) -> tuple[int, int]:
    if edge["start_key"] == key:
        return edge["end_key"]
    return edge["start_key"]


def oriented_points(edge: dict[str, Any], from_key: tuple[int, int]) -> list[tuple[float, float]]:
    points = list(edge["points"])
    if edge["start_key"] == from_key:
        return points
    return list(reversed(points))


def merge_allowed_node(
    key: tuple[int, int],
    node_points: dict[tuple[int, int], tuple[float, float]],
    incident: dict[tuple[int, int], list[int]],
    bbox: tuple[float, float, float, float] | None,
) -> bool:
    if len(incident.get(key, [])) != 2:
        return False
    return not is_near_bbox_edge(node_points[key], bbox)


def collect_chain(
    start_edge_id: int,
    edges: list[dict[str, Any]],
    incident: dict[tuple[int, int], list[int]],
    node_points: dict[tuple[int, int], tuple[float, float]],
    bbox: tuple[float, float, float, float] | None,
    assigned: set[int],
) -> tuple[list[int], list[tuple[int, int]]] | None:
    signature = edges[start_edge_id]["signature"]

    def extend(edge_id: int, through_key: tuple[int, int], chain_set: set[int]) -> list[int]:
        ordered: list[int] = []
        current_edge_id = edge_id
        current_key = through_key
        while merge_allowed_node(current_key, node_points, incident, bbox):
            candidates = [
                candidate
                for candidate in incident[current_key]
                if candidate != current_edge_id
                and candidate not in assigned
                and candidate not in chain_set
                and edges[candidate]["signature"] == signature
            ]
            if len(candidates) != 1:
                break
            next_edge_id = candidates[0]
            ordered.append(next_edge_id)
            chain_set.add(next_edge_id)
            current_key = other_node(edges[next_edge_id], current_key)
            current_edge_id = next_edge_id
        return ordered

    chain_set = {start_edge_id}
    left = extend(start_edge_id, edges[start_edge_id]["start_key"], chain_set)
    right = extend(start_edge_id, edges[start_edge_id]["end_key"], chain_set)
    chain_ids = list(reversed(left)) + [start_edge_id] + right
    if len(chain_ids) != len(set(chain_ids)):
        return None

    keys: list[tuple[int, int]] = []
    first = edges[chain_ids[0]]
    if len(chain_ids) == 1:
        keys = [first["start_key"], first["end_key"]]
    else:
        second = edges[chain_ids[1]]
        shared = first["start_key"] if first["start_key"] in {second["start_key"], second["end_key"]} else first["end_key"]
        keys.append(other_node(first, shared))
        keys.append(shared)
        for chain_edge_id in chain_ids[1:]:
            keys.append(other_node(edges[chain_edge_id], keys[-1]))
    return chain_ids, keys


def unique_sorted(values: list[str]) -> list[str]:
    return sorted({value for value in values if value})


def merged_props(
    canonical_id: str,
    chain_ids: list[int],
    edges: list[dict[str, Any]],
    length_m: float,
) -> dict[str, Any]:
    props_list = [edges[edge_id]["props"] for edge_id in chain_ids]
    base = dict(props_list[0])

    repaired_source_ids: list[str] = []
    repair_parent_ids: list[str] = []
    raw_source_ids: list[str] = []
    repair_edge_ids: list[str] = []
    repair_ops: list[str] = []
    provider_keys: set[str] = set()
    conflicts: dict[str, list[str]] = {}
    tracked_fields = ["highway", "road_class", "name", "lanes", "width_m", "oneway", "bridge", "tunnel", "layer"]

    for props in props_list:
        repaired_source_ids.extend(source_list(props.get("source_feature_id")))
        repair_parent_ids.extend(source_list(props.get("repair_parent_id")))
        repair_edge_ids.extend(source_list(props.get("repair_edge_id")))
        repair_ops.extend(source_list(props.get("repair_ops")))
        provider_tags = props.get("provider_tags") or {}
        if isinstance(provider_tags, dict):
            provider_keys.update(str(key) for key in provider_tags.keys())
        raw_source_ids.extend(source_list(props.get("source_feature_ids")))

    if not raw_source_ids:
        raw_source_ids = repair_parent_ids or repaired_source_ids

    for field in tracked_fields:
        values = unique_sorted([str(props.get(field) or "") for props in props_list])
        if len(values) > 1:
            conflicts[field] = values

    base["source_feature_id"] = canonical_id
    base["canonical_road_id"] = canonical_id
    base["canonical_schema"] = "road_test_pipeline.roads_canonical.v1"
    base["canonical_edge_count"] = len(chain_ids)
    base["canonical_length_m"] = round(length_m, 3)
    base["source_feature_ids"] = unique_sorted(raw_source_ids)
    base["repaired_source_feature_ids"] = unique_sorted(repaired_source_ids)
    base["repair_parent_ids"] = unique_sorted(repair_parent_ids)
    base["repair_edge_ids"] = unique_sorted(repair_edge_ids)
    base["provider_tag_keys"] = sorted(provider_keys)
    base["repair_ops"] = sorted(set(repair_ops))
    base["canonical_ops"] = ["degree2_chain_merge"] if len(chain_ids) > 1 else ["single_repaired_edge_passthrough"]
    base["attribute_conflicts"] = conflicts
    return base


def build_canonical_roads(
    input_path: Path,
    output_path: Path,
    report_path: Path,
    area_id: str,
) -> dict[str, Any]:
    fc = read_json(input_path)
    origin_lon, origin_lat = local_projector_from_metadata(fc)
    bbox = local_bbox_from_metadata(fc, origin_lon, origin_lat)
    edges, incident, skipped_empty_geometry = edge_records(fc, origin_lon, origin_lat)

    node_points: dict[tuple[int, int], tuple[float, float]] = {}
    node_point_samples: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
    for edge in edges:
        node_point_samples[edge["start_key"]].append(edge["points"][0])
        node_point_samples[edge["end_key"]].append(edge["points"][-1])
    for key, samples in node_point_samples.items():
        node_points[key] = (
            sum(point[0] for point in samples) / len(samples),
            sum(point[1] for point in samples) / len(samples),
        )

    assigned: set[int] = set()
    features: list[dict[str, Any]] = []
    chain_edge_counts: Counter[int] = Counter()
    merge_stop_counts: Counter[str] = Counter()

    for edge in edges:
        edge_id = int(edge["edge_id"])
        if edge_id in assigned:
            continue
        chain = collect_chain(edge_id, edges, incident, node_points, bbox, assigned)
        if chain is None:
            chain_ids = [edge_id]
            chain_keys = [edge["start_key"], edge["end_key"]]
            merge_stop_counts["cycle_or_ambiguous_chain"] += 1
        else:
            chain_ids, chain_keys = chain
        assigned.update(chain_ids)

        points: list[tuple[float, float]] = []
        for index, chain_edge_id in enumerate(chain_ids):
            edge_points = oriented_points(edges[chain_edge_id], chain_keys[index])
            if points:
                points.extend(edge_points[1:])
            else:
                points.extend(edge_points)
        points = compact_points(points)
        if len(points) < 2:
            continue
        canonical_id = f"cr_{len(features):04d}"
        length_m = polyline_length(points)
        props = merged_props(canonical_id, chain_ids, edges, length_m)
        coords = [
            [round(lon, 8), round(lat, 8)]
            for lon, lat in (to_lonlat(point[0], point[1], origin_lon, origin_lat) for point in points)
        ]
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": coords,
            },
            "properties": props,
        })
        chain_edge_counts[len(chain_ids)] += 1

    connector_nodes = sum(1 for key, ids in incident.items() if len(ids) == 2 and not is_near_bbox_edge(node_points[key], bbox))
    boundary_nodes = sum(1 for key in incident if is_near_bbox_edge(node_points[key], bbox))
    junction_or_terminal_nodes = sum(1 for ids in incident.values() if len(ids) != 2)

    output = {
        "type": "FeatureCollection",
        "metadata": {
            "area_id": area_id,
            "schema": "road_test_pipeline.roads_canonical.geojson",
            "coord_domain": "WGS84",
            "axes": "lon, lat",
            "source": str(input_path),
            "origin_lon": origin_lon,
            "origin_lat": origin_lat,
            "bbox_swen": (fc.get("metadata") or {}).get("bbox_swen"),
            "node_eps_m": NODE_EPS_M,
            "contract": "canonical road chains for road graph and lane upgrade input",
        },
        "features": features,
    }
    write_json(output_path, output)

    input_count = len(edges)
    output_count = len(features)
    merged_input_edges = sum(max(0, count - 1) * chain_count for count, chain_count in chain_edge_counts.items())
    report = {
        "area_id": area_id,
        "stage": "canonical_roads_v1",
        "status": "pass",
        "input": str(input_path),
        "output": str(output_path),
        "parameters": {
            "node_eps_m": NODE_EPS_M,
            "bbox_edge_margin_m": BBOX_EDGE_MARGIN_M,
            "merge_policy": "degree2_nodes_only_with_matching_attribute_signature",
        },
        "counts": {
            "input_edges": input_count,
            "output_canonical_roads": output_count,
            "skipped_empty_geometry": skipped_empty_geometry,
            "merged_input_edges": merged_input_edges,
            "connector_nodes_available_for_merge": connector_nodes,
            "boundary_nodes_protected": boundary_nodes,
            "junction_or_terminal_nodes_protected": junction_or_terminal_nodes,
        },
        "chain_edge_count_histogram": {str(key): value for key, value in sorted(chain_edge_counts.items())},
        "merge_stop_counts": dict(sorted(merge_stop_counts.items())),
        "metrics": {
            "edge_reduction_ratio": round((input_count - output_count) / max(1, input_count), 3),
            "avg_input_edges_per_canonical_road": round(input_count / max(1, output_count), 3),
            "total_length_m": round(sum(polyline_length(compact_points(feature_points(feature, origin_lon, origin_lat))) for feature in features), 3),
        },
        "notes": [
            "Canonical roads are machine-readable GeoJSON, not SVG visualization.",
            "Each canonical road keeps source_feature_ids, repaired_source_feature_ids, and repair_parent_ids for traceability.",
            "The stage does not cross true junctions or attribute conflicts; it only removes unstable degree-2 fragmentation from downstream graph construction.",
        ],
    }
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build canonical road chains from repaired roads.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--input", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    input_path = Path(args.input) if args.input else root / "data" / "processed" / f"{args.area_id}_roads_repaired.geojson"
    output_path = Path(args.output) if args.output else root / "data" / "processed" / f"{args.area_id}_roads_canonical.geojson"
    report_path = Path(args.report) if args.report else root / "reports" / f"{args.area_id}_canonical_roads_report.json"

    report = build_canonical_roads(input_path, output_path, report_path, args.area_id)
    print(json.dumps({
        "area_id": args.area_id,
        "output": str(output_path),
        "report": str(report_path),
        "counts": report["counts"],
        "metrics": report["metrics"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
