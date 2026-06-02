#!/usr/bin/env python3
"""Initial topology repair for the isolated road test pipeline.

V1 scope:
- remove adjacent duplicate points
- snap nearby road endpoints together
- snap endpoints to nearby road edges and insert a split point
- insert proper planar road-road intersection points
- output simple segment edges with coincident endpoints

This is intentionally conservative and ignores bridge/tunnel/layer crossings.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SNAP_ENDPOINT_M = 4.0
SNAP_EDGE_M = 5.0
DEDUP_EPS_M = 0.05
NODE_EPS_M = 0.25
SHORT_EDGE_M = 3.0
BBOX_EDGE_MARGIN_M = 5.0


@dataclass
class RoadFeature:
    source_feature_id: str
    props: dict[str, Any]
    lonlat: list[tuple[float, float]]
    local: list[tuple[float, float]]
    repair_ops: set[str] = field(default_factory=set)


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


def to_lonlat(x: float, z: float, origin_lon: float, origin_lat: float) -> tuple[float, float]:
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(origin_lat))
    return origin_lon + x / m_per_deg_lon, origin_lat + z / m_per_deg_lat


def local_bbox_from_metadata(
    fc: dict[str, Any],
    origin_lon: float,
    origin_lat: float,
) -> tuple[float, float, float, float] | None:
    bbox = (fc.get("metadata") or {}).get("bbox_swen")
    if not bbox or len(bbox) != 4:
        return None
    south, west, north, east = [float(v) for v in bbox]
    west_south = to_local(west, south, origin_lon, origin_lat)
    east_north = to_local(east, north, origin_lon, origin_lat)
    return (
        min(west_south[0], east_north[0]),
        min(west_south[1], east_north[1]),
        max(west_south[0], east_north[0]),
        max(west_south[1], east_north[1]),
    )


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = a[0] - b[0]
    dz = a[1] - b[1]
    return math.sqrt(dx * dx + dz * dz)


def point_key(p: tuple[float, float], eps: float = NODE_EPS_M) -> tuple[int, int]:
    return round(p[0] / eps), round(p[1] / eps)


def is_near_bbox_edge(
    p: tuple[float, float],
    bbox: tuple[float, float, float, float] | None,
    margin_m: float = BBOX_EDGE_MARGIN_M,
) -> bool:
    if bbox is None:
        return False
    min_x, min_z, max_x, max_z = bbox
    x, z = p
    if x < min_x - margin_m or x > max_x + margin_m or z < min_z - margin_m or z > max_z + margin_m:
        return False
    return (
        abs(x - min_x) <= margin_m
        or abs(x - max_x) <= margin_m
        or abs(z - min_z) <= margin_m
        or abs(z - max_z) <= margin_m
    )


def remove_adjacent_duplicates(points: list[tuple[float, float]], eps: float = DEDUP_EPS_M) -> tuple[list[tuple[float, float]], int]:
    if not points:
        return [], 0
    out = [points[0]]
    removed = 0
    for p in points[1:]:
        if distance(out[-1], p) <= eps:
            removed += 1
            continue
        out.append(p)
    return out, removed


def interpolate_lonlat(
    p: tuple[float, float],
    origin_lon: float,
    origin_lat: float,
) -> tuple[float, float]:
    lon, lat = to_lonlat(p[0], p[1], origin_lon, origin_lat)
    return round(lon, 8), round(lat, 8)


def cluster_endpoints(roads: list[RoadFeature], snap_m: float) -> list[list[tuple[int, int]]]:
    endpoints: list[tuple[int, int, tuple[float, float]]] = []
    for road_index, road in enumerate(roads):
        if len(road.local) < 2:
            continue
        endpoints.append((road_index, 0, road.local[0]))
        endpoints.append((road_index, len(road.local) - 1, road.local[-1]))

    used = [False] * len(endpoints)
    clusters: list[list[tuple[int, int]]] = []
    for i, (_ri, _pi, p) in enumerate(endpoints):
        if used[i]:
            continue
        cluster = [i]
        used[i] = True
        changed = True
        while changed:
            changed = False
            for j, (_rj, _pj, q) in enumerate(endpoints):
                if used[j]:
                    continue
                if any(distance(q, endpoints[k][2]) <= snap_m for k in cluster):
                    cluster.append(j)
                    used[j] = True
                    changed = True
        if len(cluster) > 1:
            clusters.append([(endpoints[k][0], endpoints[k][1]) for k in cluster])
    return clusters


def apply_endpoint_snaps(roads: list[RoadFeature]) -> int:
    clusters = cluster_endpoints(roads, SNAP_ENDPOINT_M)
    count = 0
    for cluster in clusters:
        pts = [roads[ri].local[pi] for ri, pi in cluster]
        centroid = (
            sum(p[0] for p in pts) / len(pts),
            sum(p[1] for p in pts) / len(pts),
        )
        for road_index, point_index in cluster:
            road = roads[road_index]
            if distance(road.local[point_index], centroid) > NODE_EPS_M:
                road.local[point_index] = centroid
                road.repair_ops.add("endpoint_snap")
                count += 1
    return count


def closest_point_on_segment(
    p: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> tuple[tuple[float, float], float]:
    ax, az = a
    bx, bz = b
    px, pz = p
    dx = bx - ax
    dz = bz - az
    denom = dx * dx + dz * dz
    if denom <= 1e-9:
        return a, 0.0
    t = ((px - ax) * dx + (pz - az) * dz) / denom
    t = max(0.0, min(1.0, t))
    return (ax + dx * t, az + dz * t), t


def has_layer_separation(props: dict[str, Any]) -> bool:
    return any(str(props.get(k) or "").strip() for k in ("bridge", "tunnel", "layer"))


def insert_point_on_road(road: RoadFeature, point: tuple[float, float], eps: float = NODE_EPS_M) -> bool:
    if any(distance(point, p) <= eps for p in road.local):
        return False

    best_index = None
    best_t = 0.0
    best_d = float("inf")
    for i in range(len(road.local) - 1):
        proj, t = closest_point_on_segment(point, road.local[i], road.local[i + 1])
        d = distance(point, proj)
        if d < best_d:
            best_d = d
            best_index = i
            best_t = t

    if best_index is None:
        return False
    if best_t <= 1e-6 or best_t >= 1.0 - 1e-6:
        return False
    road.local.insert(best_index + 1, point)
    return True


def apply_endpoint_to_edge_snaps(roads: list[RoadFeature]) -> int:
    snaps = 0
    for road_index, road in enumerate(roads):
        if len(road.local) < 2:
            continue
        for endpoint_index in (0, len(road.local) - 1):
            endpoint = road.local[endpoint_index]
            best = None
            for target_index, target in enumerate(roads):
                if target_index == road_index or len(target.local) < 2:
                    continue
                if has_layer_separation(road.props) or has_layer_separation(target.props):
                    continue
                for seg_index in range(len(target.local) - 1):
                    proj, t = closest_point_on_segment(endpoint, target.local[seg_index], target.local[seg_index + 1])
                    if t <= 0.02 or t >= 0.98:
                        continue
                    d = distance(endpoint, proj)
                    if d <= SNAP_EDGE_M and (best is None or d < best[0]):
                        best = (d, target_index, proj)
            if best is None:
                continue
            _d, target_index, snap_point = best
            if distance(endpoint, snap_point) <= NODE_EPS_M:
                continue
            road.local[endpoint_index] = snap_point
            road.repair_ops.add("endpoint_to_edge_snap")
            roads[target_index].repair_ops.add("edge_split_for_endpoint")
            insert_point_on_road(roads[target_index], snap_point)
            snaps += 1
    return snaps


def orient(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def bbox_overlap(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], d: tuple[float, float]) -> bool:
    return (
        max(min(a[0], b[0]), min(c[0], d[0])) <= min(max(a[0], b[0]), max(c[0], d[0]))
        and max(min(a[1], b[1]), min(c[1], d[1])) <= min(max(a[1], b[1]), max(c[1], d[1]))
    )


def shares_endpoint(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], d: tuple[float, float]) -> bool:
    return any(distance(p, q) <= NODE_EPS_M for p in (a, b) for q in (c, d))


def segment_intersection(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> tuple[float, float] | None:
    if shares_endpoint(a, b, c, d):
        return None
    if not bbox_overlap(a, b, c, d):
        return None
    o1 = orient(a, b, c)
    o2 = orient(a, b, d)
    o3 = orient(c, d, a)
    o4 = orient(c, d, b)
    if not ((o1 * o2 < 0) and (o3 * o4 < 0)):
        return None

    x1, y1 = a
    x2, y2 = b
    x3, y3 = c
    x4, y4 = d
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-9:
        return None
    px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / denom
    py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / denom
    return px, py


def apply_intersection_splits(roads: list[RoadFeature]) -> int:
    intersections: list[tuple[int, int, tuple[float, float]]] = []
    for i, a_road in enumerate(roads):
        if has_layer_separation(a_road.props):
            continue
        for j in range(i + 1, len(roads)):
            b_road = roads[j]
            if has_layer_separation(b_road.props):
                continue
            for ai in range(len(a_road.local) - 1):
                a0, a1 = a_road.local[ai], a_road.local[ai + 1]
                for bi in range(len(b_road.local) - 1):
                    b0, b1 = b_road.local[bi], b_road.local[bi + 1]
                    pt = segment_intersection(a0, a1, b0, b1)
                    if pt is None:
                        continue
                    intersections.append((i, j, pt))

    inserted = 0
    for i, j, pt in intersections:
        if insert_point_on_road(roads[i], pt):
            roads[i].repair_ops.add("intersection_split")
            inserted += 1
        if insert_point_on_road(roads[j], pt):
            roads[j].repair_ops.add("intersection_split")
            inserted += 1
    return inserted


def segment_node_degrees(roads: list[RoadFeature]) -> dict[tuple[int, int], int]:
    degrees: dict[tuple[int, int], int] = defaultdict(int)
    for road in roads:
        for i in range(len(road.local) - 1):
            a = road.local[i]
            b = road.local[i + 1]
            if distance(a, b) < DEDUP_EPS_M:
                continue
            degrees[point_key(a)] += 1
            degrees[point_key(b)] += 1
    return degrees


def count_short_segments(roads: list[RoadFeature], threshold_m: float) -> int:
    count = 0
    for road in roads:
        for i in range(len(road.local) - 1):
            if distance(road.local[i], road.local[i + 1]) < threshold_m:
                count += 1
    return count


def can_remove_short_edge_point(
    road: RoadFeature,
    point_index: int,
    degrees: dict[tuple[int, int], int],
    bbox: tuple[float, float, float, float] | None,
) -> bool:
    if point_index <= 0 or point_index >= len(road.local) - 1:
        return False
    point = road.local[point_index]
    if is_near_bbox_edge(point, bbox):
        return False
    return degrees.get(point_key(point), 0) == 2


def apply_short_edge_cleanup(
    roads: list[RoadFeature],
    bbox: tuple[float, float, float, float] | None,
    threshold_m: float = SHORT_EDGE_M,
) -> dict[str, int]:
    removed_points = 0
    passes = 0

    while True:
        degrees = segment_node_degrees(roads)
        removed_this_pass = 0

        for road in roads:
            i = 0
            while i < len(road.local) - 1:
                seg_len = distance(road.local[i], road.local[i + 1])
                if seg_len >= threshold_m:
                    i += 1
                    continue

                remove_index = None
                if can_remove_short_edge_point(road, i + 1, degrees, bbox):
                    remove_index = i + 1
                elif can_remove_short_edge_point(road, i, degrees, bbox):
                    remove_index = i

                if remove_index is None:
                    i += 1
                    continue

                del road.local[remove_index]
                road.repair_ops.add("short_edge_collapse")
                removed_points += 1
                removed_this_pass += 1
                i = max(0, remove_index - 1)

        if removed_this_pass == 0:
            break
        passes += 1

    return {
        "short_edge_threshold_m": int(threshold_m) if threshold_m.is_integer() else threshold_m,
        "short_edge_collapse_passes": passes,
        "short_edge_points_removed": removed_points,
        "short_edges_remaining_under_threshold_pre_output": count_short_segments(roads, threshold_m),
    }


def endpoint_stats(roads: list[RoadFeature]) -> dict[str, Any]:
    clusters: dict[tuple[int, int], int] = defaultdict(int)
    for road in roads:
        if len(road.local) < 2:
            continue
        clusters[point_key(road.local[0])] += 1
        clusters[point_key(road.local[-1])] += 1
    dangling = sum(1 for v in clusters.values() if v == 1)
    return {
        "endpoint_clusters": len(clusters),
        "dangling_endpoint_clusters": dangling,
        "dangling_endpoint_ratio": round(dangling / max(1, len(clusters)), 3),
    }


def endpoint_stats_from_output_features(
    features: list[dict[str, Any]],
    origin_lon: float,
    origin_lat: float,
) -> dict[str, Any]:
    clusters: dict[tuple[int, int], int] = defaultdict(int)
    for feat in features:
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        a = to_local(float(coords[0][0]), float(coords[0][1]), origin_lon, origin_lat)
        b = to_local(float(coords[-1][0]), float(coords[-1][1]), origin_lon, origin_lat)
        clusters[point_key(a)] += 1
        clusters[point_key(b)] += 1
    dangling = sum(1 for v in clusters.values() if v == 1)
    return {
        "endpoint_clusters": len(clusters),
        "dangling_endpoint_clusters": dangling,
        "dangling_endpoint_ratio": round(dangling / max(1, len(clusters)), 3),
    }


def count_short_output_features(
    features: list[dict[str, Any]],
    origin_lon: float,
    origin_lat: float,
    threshold_m: float,
) -> int:
    count = 0
    for feat in features:
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        a = to_local(float(coords[0][0]), float(coords[0][1]), origin_lon, origin_lat)
        b = to_local(float(coords[-1][0]), float(coords[-1][1]), origin_lon, origin_lat)
        if distance(a, b) < threshold_m:
            count += 1
    return count


def load_roads(path: Path) -> tuple[dict[str, Any], list[RoadFeature], float, float]:
    fc = read_json(path)
    origin_lon, origin_lat = local_projector_from_metadata(fc)
    roads: list[RoadFeature] = []

    for index, feat in enumerate(fc.get("features", [])):
        geom = feat.get("geometry") or {}
        props = dict(feat.get("properties") or {})
        if geom.get("type") != "LineString":
            continue
        lonlat = [(float(c[0]), float(c[1])) for c in geom.get("coordinates") or [] if len(c) >= 2]
        local = [to_local(lon, lat, origin_lon, origin_lat) for lon, lat in lonlat]
        local, _removed = remove_adjacent_duplicates(local)
        if len(local) < 2:
            continue
        source_id = str(props.get("source_feature_id") or index)
        roads.append(RoadFeature(source_id, props, lonlat, local))
    return fc, roads, origin_lon, origin_lat


def build_output_features(roads: list[RoadFeature], origin_lon: float, origin_lat: float) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    edge_id = 0
    for road in roads:
        for i in range(len(road.local) - 1):
            a = road.local[i]
            b = road.local[i + 1]
            if distance(a, b) < DEDUP_EPS_M:
                continue
            props = dict(road.props)
            props["repair_parent_id"] = road.source_feature_id
            props["repair_edge_id"] = edge_id
            props["repair_segment_index"] = i
            props["repair_ops"] = sorted(road.repair_ops)
            props["source_feature_id"] = f"{road.source_feature_id}_seg_{i}"
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        list(interpolate_lonlat(a, origin_lon, origin_lat)),
                        list(interpolate_lonlat(b, origin_lon, origin_lat)),
                    ],
                },
                "properties": props,
            })
            edge_id += 1
    return features


def repair(input_path: Path, output_path: Path, report_path: Path, area_id: str) -> dict[str, Any]:
    fc, roads, origin_lon, origin_lat = load_roads(input_path)
    local_bbox = local_bbox_from_metadata(fc, origin_lon, origin_lat)
    before = endpoint_stats(roads)

    duplicate_points_removed = 0
    for road in roads:
        road.local, removed = remove_adjacent_duplicates(road.local)
        duplicate_points_removed += removed

    endpoint_snaps = apply_endpoint_snaps(roads)
    endpoint_to_edge_snaps = apply_endpoint_to_edge_snaps(roads)
    intersection_splits = apply_intersection_splits(roads)
    short_edges_before = count_short_segments(roads, SHORT_EDGE_M)
    short_edge_cleanup = apply_short_edge_cleanup(roads, local_bbox)
    after = endpoint_stats(roads)

    features = build_output_features(roads, origin_lon, origin_lat)
    output_edge_stats = endpoint_stats_from_output_features(features, origin_lon, origin_lat)
    short_edges_remaining_output = count_short_output_features(features, origin_lon, origin_lat, SHORT_EDGE_M)
    out_fc = {
        "type": "FeatureCollection",
        "metadata": {
            "area_id": area_id,
            "schema": "road_test_pipeline.roads_repaired.geojson",
            "coord_domain": "WGS84",
            "axes": "lon, lat",
            "source": str(input_path),
            "origin_lon": origin_lon,
            "origin_lat": origin_lat,
            "bbox_swen": (fc.get("metadata") or {}).get("bbox_swen"),
        },
        "features": features,
    }
    write_json(output_path, out_fc)

    report = {
        "area_id": area_id,
        "stage": "topology_repair_v2",
        "input": str(input_path),
        "output": str(output_path),
        "parameters": {
            "snap_endpoint_m": SNAP_ENDPOINT_M,
            "snap_edge_m": SNAP_EDGE_M,
            "node_eps_m": NODE_EPS_M,
            "short_edge_m": SHORT_EDGE_M,
            "bbox_edge_margin_m": BBOX_EDGE_MARGIN_M,
        },
        "counts": {
            "input_features": len(roads),
            "output_edges": len(features),
            "duplicate_points_removed": duplicate_points_removed,
            "endpoint_snaps": endpoint_snaps,
            "endpoint_to_edge_snaps": endpoint_to_edge_snaps,
            "intersection_split_insertions": intersection_splits,
            "short_edges_before_cleanup": short_edges_before,
            **short_edge_cleanup,
            "short_edges_remaining_under_threshold": short_edges_remaining_output,
        },
        "endpoint_stats_before": before,
        "endpoint_stats_after_parent_roads": after,
        "endpoint_stats_after_output_edges": output_edge_stats,
        "notes": [
            "V2 solves road continuity, planar junction insertion and conservative short-edge cleanup.",
            "Bridge, tunnel and layer-separated crossings are not planarized.",
            "Short-edge cleanup preserves road endpoints, junction anchors and bbox boundary points.",
            "Output is split into simple two-point edges for later road_graph building.",
        ],
    }
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Initial road topology repair.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--input", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    input_path = Path(args.input) if args.input else root / "data" / "processed" / f"{args.area_id}_roads_raw.geojson"
    output_path = Path(args.output) if args.output else root / "data" / "processed" / f"{args.area_id}_roads_repaired.geojson"
    report_path = Path(args.report) if args.report else root / "reports" / f"{args.area_id}_repair_report.json"

    report = repair(input_path, output_path, report_path, args.area_id)
    print(json.dumps({
        "area_id": args.area_id,
        "output": str(output_path),
        "report": str(report_path),
        "counts": report["counts"],
        "endpoint_stats_after_output_edges": report["endpoint_stats_after_output_edges"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
