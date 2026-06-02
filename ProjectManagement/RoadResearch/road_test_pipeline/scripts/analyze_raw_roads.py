#!/usr/bin/env python3
"""Analyze raw road GeoJSON quality for the isolated road test pipeline."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def local_projector_from_metadata(fc: dict[str, Any]) -> tuple[float, float]:
    meta = fc.get("metadata") or {}
    bbox = meta.get("bbox_swen")
    if bbox and len(bbox) == 4:
        south, west, north, east = [float(v) for v in bbox]
        return (west + east) * 0.5, (south + north) * 0.5

    coords = []
    for feat in fc.get("features", []):
        geom = feat.get("geometry") or {}
        if geom.get("type") == "LineString":
            coords.extend(geom.get("coordinates") or [])
    if not coords:
        return 0.0, 0.0
    lon = sum(float(c[0]) for c in coords) / len(coords)
    lat = sum(float(c[1]) for c in coords) / len(coords)
    return lon, lat


def to_local(lon: float, lat: float, origin_lon: float, origin_lat: float) -> tuple[float, float]:
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(origin_lat))
    return (lon - origin_lon) * m_per_deg_lon, (lat - origin_lat) * m_per_deg_lat


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = a[0] - b[0]
    dz = a[1] - b[1]
    return math.sqrt(dx * dx + dz * dz)


def polyline_length(points: list[tuple[float, float]]) -> float:
    return sum(distance(points[i], points[i + 1]) for i in range(len(points) - 1))


def has_duplicate_adjacent(points: list[tuple[float, float]], eps: float = 0.05) -> bool:
    return any(distance(points[i], points[i + 1]) <= eps for i in range(len(points) - 1))


def endpoint_key(p: tuple[float, float], cell_m: float) -> tuple[int, int]:
    return round(p[0] / cell_m), round(p[1] / cell_m)


def orient(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def bbox_overlap(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], d: tuple[float, float]) -> bool:
    return (
        max(min(a[0], b[0]), min(c[0], d[0])) <= min(max(a[0], b[0]), max(c[0], d[0]))
        and max(min(a[1], b[1]), min(c[1], d[1])) <= min(max(a[1], b[1]), max(c[1], d[1]))
    )


def shares_endpoint(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], d: tuple[float, float], eps: float = 0.25) -> bool:
    return any(distance(p, q) <= eps for p in (a, b) for q in (c, d))


def proper_intersection(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], d: tuple[float, float]) -> bool:
    if shares_endpoint(a, b, c, d):
        return False
    if not bbox_overlap(a, b, c, d):
        return False
    o1 = orient(a, b, c)
    o2 = orient(a, b, d)
    o3 = orient(c, d, a)
    o4 = orient(c, d, b)
    return (o1 * o2 < 0) and (o3 * o4 < 0)


def feature_points(feat: dict[str, Any], origin_lon: float, origin_lat: float) -> list[tuple[float, float]]:
    geom = feat.get("geometry") or {}
    if geom.get("type") != "LineString":
        return []
    pts = []
    for coord in geom.get("coordinates") or []:
        if len(coord) < 2:
            continue
        pts.append(to_local(float(coord[0]), float(coord[1]), origin_lon, origin_lat))
    return pts


def has_any(props: dict[str, Any], keys: list[str]) -> bool:
    return any(str(props.get(key) or "").strip() for key in keys)


def analyze(geojson_path: Path, area_id: str) -> dict[str, Any]:
    fc = read_json(geojson_path)
    origin_lon, origin_lat = local_projector_from_metadata(fc)
    features = fc.get("features", [])

    class_counts: Counter[str] = Counter()
    empty_geometry = 0
    duplicate_point_features = 0
    too_short_features = 0
    total_length_m = 0.0
    lengths: list[float] = []
    endpoint_clusters: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    segments: list[tuple[str, int, tuple[float, float], tuple[float, float], dict[str, Any]]] = []

    tags = {
        "lanes": 0,
        "turn_lanes": 0,
        "width": 0,
        "oneway": 0,
        "maxspeed": 0,
        "bridge_tunnel_layer": 0,
    }

    for index, feat in enumerate(features):
        props = feat.get("properties") or {}
        highway = str(props.get("highway") or "unknown")
        class_counts[highway] += 1

        pts = feature_points(feat, origin_lon, origin_lat)
        if len(pts) < 2:
            empty_geometry += 1
            continue

        if has_duplicate_adjacent(pts):
            duplicate_point_features += 1

        length_m = polyline_length(pts)
        lengths.append(length_m)
        total_length_m += length_m
        if length_m < 2.0:
            too_short_features += 1

        if has_any(props, ["lanes", "lanes_forward", "lanes_backward"]):
            tags["lanes"] += 1
        if has_any(props, ["turn_lanes", "turn_lanes_forward", "turn_lanes_backward"]):
            tags["turn_lanes"] += 1
        if has_any(props, ["width_m"]):
            tags["width"] += 1
        if has_any(props, ["oneway"]):
            tags["oneway"] += 1
        if has_any(props, ["maxspeed"]):
            tags["maxspeed"] += 1
        if has_any(props, ["bridge", "tunnel", "layer"]):
            tags["bridge_tunnel_layer"] += 1

        source_id = str(props.get("source_feature_id") or index)
        for endpoint_role, p in (("start", pts[0]), ("end", pts[-1])):
            endpoint_clusters[endpoint_key(p, 3.0)].append({
                "feature_index": index,
                "source_feature_id": source_id,
                "role": endpoint_role,
                "highway": highway,
            })

        for seg_index in range(len(pts) - 1):
            if distance(pts[seg_index], pts[seg_index + 1]) < 0.05:
                continue
            segments.append((source_id, seg_index, pts[seg_index], pts[seg_index + 1], props))

    possible_unsplit_crossings = []
    for i in range(len(segments)):
        src_a, seg_a, a0, a1, props_a = segments[i]
        for j in range(i + 1, len(segments)):
            src_b, seg_b, b0, b1, props_b = segments[j]
            if src_a == src_b:
                continue
            if has_any(props_a, ["bridge", "tunnel", "layer"]) or has_any(props_b, ["bridge", "tunnel", "layer"]):
                continue
            if proper_intersection(a0, a1, b0, b1):
                possible_unsplit_crossings.append({
                    "a": {"source_feature_id": src_a, "segment": seg_a},
                    "b": {"source_feature_id": src_b, "segment": seg_b},
                })

    endpoint_cluster_sizes = Counter(len(v) for v in endpoint_clusters.values())
    dangling_clusters = [items for items in endpoint_clusters.values() if len(items) == 1]
    low_confidence_endpoint_clusters = [
        items for items in endpoint_clusters.values()
        if len(items) == 2 and items[0]["highway"] != items[1]["highway"]
    ]

    feature_count = len(features)
    pct = lambda n: round((n / feature_count * 100.0), 3) if feature_count else 0.0

    return {
        "area_id": area_id,
        "input": str(geojson_path),
        "origin": {"lon": origin_lon, "lat": origin_lat},
        "feature_count": feature_count,
        "geometry": {
            "empty_geometry": empty_geometry,
            "duplicate_point_features": duplicate_point_features,
            "too_short_features": too_short_features,
            "total_length_m": round(total_length_m, 3),
            "min_length_m": round(min(lengths), 3) if lengths else 0.0,
            "max_length_m": round(max(lengths), 3) if lengths else 0.0,
        },
        "tags": {
            "lanes_count": tags["lanes"],
            "lanes_coverage_pct": pct(tags["lanes"]),
            "turn_lanes_count": tags["turn_lanes"],
            "turn_lanes_coverage_pct": pct(tags["turn_lanes"]),
            "width_count": tags["width"],
            "width_coverage_pct": pct(tags["width"]),
            "oneway_count": tags["oneway"],
            "oneway_coverage_pct": pct(tags["oneway"]),
            "maxspeed_count": tags["maxspeed"],
            "maxspeed_coverage_pct": pct(tags["maxspeed"]),
            "bridge_tunnel_layer_count": tags["bridge_tunnel_layer"],
        },
        "topology": {
            "endpoint_clusters": len(endpoint_clusters),
            "endpoint_cluster_size_distribution": dict(sorted(endpoint_cluster_sizes.items())),
            "dangling_endpoint_clusters": len(dangling_clusters),
            "dangling_endpoint_ratio": round(len(dangling_clusters) / max(1, len(endpoint_clusters)), 3),
            "low_confidence_endpoint_clusters": len(low_confidence_endpoint_clusters),
            "possible_unsplit_crossings": len(possible_unsplit_crossings),
            "possible_unsplit_crossing_samples": possible_unsplit_crossings[:20],
        },
        "highway_class_counts": dict(class_counts.most_common()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze raw road GeoJSON quality.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--input", default="")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    input_path = Path(args.input) if args.input else root / "data" / "processed" / f"{args.area_id}_roads_raw.geojson"
    output_path = Path(args.output) if args.output else root / "reports" / f"{args.area_id}_raw_analysis.json"

    result = analyze(input_path, args.area_id)
    write_json(output_path, result)
    print(json.dumps({
        "area_id": args.area_id,
        "input": str(input_path),
        "output": str(output_path),
        "feature_count": result["feature_count"],
        "possible_unsplit_crossings": result["topology"]["possible_unsplit_crossings"],
        "dangling_endpoint_clusters": result["topology"]["dangling_endpoint_clusters"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
