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
import copy
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
REVIEW_BRIDGE_GAP_M = 18.0
REVIEW_ENDPOINT_EDGE_GAP_M = 12.0
REVIEW_MIN_CONFIDENCE = 0.45
REVIEW_TOP_CANDIDATES = 40
HIGH_CONFIDENCE_PROMOTION_MIN = 0.75


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


def normalize(v: tuple[float, float]) -> tuple[float, float]:
    length = math.sqrt(v[0] * v[0] + v[1] * v[1])
    if length <= 1e-9:
        return 0.0, 0.0
    return v[0] / length, v[1] / length


def dot(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1]


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


def endpoint_direction(road: RoadFeature, point_index: int) -> tuple[float, float]:
    if len(road.local) < 2:
        return 0.0, 0.0
    if point_index == 0:
        return normalize((road.local[0][0] - road.local[1][0], road.local[0][1] - road.local[1][1]))
    return normalize((road.local[-1][0] - road.local[-2][0], road.local[-1][1] - road.local[-2][1]))


def road_class(road: RoadFeature) -> str:
    return str(road.props.get("road_class") or road.props.get("highway") or "unknown")


def road_name(road: RoadFeature) -> str:
    return str(road.props.get("name") or "").strip().lower()


def class_match_score(a: RoadFeature, b: RoadFeature) -> float:
    class_a = road_class(a)
    class_b = road_class(b)
    if class_a == class_b:
        return 1.0
    local_classes = {"residential", "service", "living_street", "unclassified"}
    if class_a in local_classes and class_b in local_classes:
        return 0.65
    return 0.35


def name_match_score(a: RoadFeature, b: RoadFeature) -> float:
    name_a = road_name(a)
    name_b = road_name(b)
    if name_a and name_b and name_a == name_b:
        return 1.0
    if not name_a and not name_b:
        return 0.5
    return 0.0


def dangling_endpoint_records(
    roads: list[RoadFeature],
    bbox: tuple[float, float, float, float] | None,
) -> list[dict[str, Any]]:
    degrees = segment_node_degrees(roads)
    endpoints: list[tuple[int, int, tuple[float, float]]] = []
    for road_index, road in enumerate(roads):
        if len(road.local) < 2:
            continue
        endpoints.append((road_index, 0, road.local[0]))
        endpoints.append((road_index, len(road.local) - 1, road.local[-1]))

    records = []
    for road_index, point_index, point in endpoints:
        if degrees.get(point_key(point), 0) != 1:
            continue
        road = roads[road_index]
        role = "start" if point_index == 0 else "end"
        records.append({
            "road_index": road_index,
            "source_feature_id": road.source_feature_id,
            "endpoint_role": role,
            "point_index": point_index,
            "point": point,
            "direction": endpoint_direction(road, point_index),
            "highway": str(road.props.get("highway") or ""),
            "road_class": road_class(road),
            "name": road_name(road),
            "near_bbox_edge": is_near_bbox_edge(point, bbox),
        })
    return records


def review_point(point: tuple[float, float]) -> dict[str, float]:
    return {"x": round(point[0], 3), "z": round(point[1], 3)}


def bridge_confidence(
    a_record: dict[str, Any],
    b_record: dict[str, Any],
    roads: list[RoadFeature],
) -> tuple[float, dict[str, float]]:
    a_point = a_record["point"]
    b_point = b_record["point"]
    gap_m = distance(a_point, b_point)
    if gap_m <= NODE_EPS_M or gap_m > REVIEW_BRIDGE_GAP_M:
        return 0.0, {}
    direction_ab = normalize((b_point[0] - a_point[0], b_point[1] - a_point[1]))
    direction_ba = (-direction_ab[0], -direction_ab[1])
    heading_a = max(0.0, dot(a_record["direction"], direction_ab))
    heading_b = max(0.0, dot(b_record["direction"], direction_ba))
    heading_score = (heading_a + heading_b) * 0.5
    if heading_score < 0.25:
        return 0.0, {}

    road_a = roads[int(a_record["road_index"])]
    road_b = roads[int(b_record["road_index"])]
    distance_score = max(0.0, 1.0 - gap_m / REVIEW_BRIDGE_GAP_M)
    class_score = class_match_score(road_a, road_b)
    name_score = name_match_score(road_a, road_b)
    confidence = 0.50 * heading_score + 0.25 * distance_score + 0.20 * class_score + 0.05 * name_score
    return confidence, {
        "gap_m": gap_m,
        "heading_score": heading_score,
        "distance_score": distance_score,
        "class_score": class_score,
        "name_score": name_score,
    }


def endpoint_bridge_candidates(
    records: list[dict[str, Any]],
    roads: list[RoadFeature],
) -> list[dict[str, Any]]:
    candidates = []
    internal = [record for record in records if not bool(record["near_bbox_edge"])]
    for i, a_record in enumerate(internal):
        for b_record in internal[i + 1 :]:
            if int(a_record["road_index"]) == int(b_record["road_index"]):
                continue
            road_a = roads[int(a_record["road_index"])]
            road_b = roads[int(b_record["road_index"])]
            if has_layer_separation(road_a.props) or has_layer_separation(road_b.props):
                continue
            confidence, metrics = bridge_confidence(a_record, b_record, roads)
            if confidence < REVIEW_MIN_CONFIDENCE:
                continue
            candidates.append({
                "kind": "endpoint_bridge",
                "confidence": round(confidence, 3),
                "from": {
                    "source_feature_id": a_record["source_feature_id"],
                    "endpoint_role": a_record["endpoint_role"],
                    **review_point(a_record["point"]),
                },
                "to": {
                    "source_feature_id": b_record["source_feature_id"],
                    "endpoint_role": b_record["endpoint_role"],
                    **review_point(b_record["point"]),
                },
                "gap_m": round(metrics["gap_m"], 3),
                "heading_score": round(metrics["heading_score"], 3),
                "class_score": round(metrics["class_score"], 3),
                "name_score": round(metrics["name_score"], 3),
                "suggested_action": "manual_review_or_high_confidence_bridge",
            })
    candidates.sort(key=lambda item: (-float(item["confidence"]), float(item["gap_m"])))
    return candidates


def endpoint_move_crossings(
    roads: list[RoadFeature],
    source_index: int,
    point_index: int,
    target_index: int,
    snap_point: tuple[float, float],
) -> list[dict[str, Any]]:
    road = roads[source_index]
    if len(road.local) < 2:
        return []
    neighbor = road.local[1] if point_index == 0 else road.local[-2]
    if distance(neighbor, snap_point) <= DEDUP_EPS_M:
        return []

    crossings = []
    for other_index, other in enumerate(roads):
        if other_index == source_index or len(other.local) < 2:
            continue
        if has_layer_separation(road.props) or has_layer_separation(other.props):
            continue
        for segment_index in range(len(other.local) - 1):
            a = other.local[segment_index]
            b = other.local[segment_index + 1]
            if other_index == target_index:
                proj, _t = closest_point_on_segment(snap_point, a, b)
                if distance(proj, snap_point) <= NODE_EPS_M:
                    continue
            crossing = segment_intersection(neighbor, snap_point, a, b)
            if crossing is None:
                continue
            crossings.append({
                "source_feature_id": other.source_feature_id,
                "segment_index": segment_index,
                **review_point(crossing),
            })
    return crossings


def endpoint_to_edge_review_candidates(
    records: list[dict[str, Any]],
    roads: list[RoadFeature],
) -> list[dict[str, Any]]:
    candidates = []
    for record in records:
        if bool(record["near_bbox_edge"]):
            continue
        road = roads[int(record["road_index"])]
        best: tuple[float, float, int, tuple[float, float], int, float] | None = None
        endpoint = record["point"]
        for target_index, target in enumerate(roads):
            if target_index == int(record["road_index"]) or len(target.local) < 2:
                continue
            if has_layer_separation(road.props) or has_layer_separation(target.props):
                continue
            for segment_index in range(len(target.local) - 1):
                proj, t = closest_point_on_segment(endpoint, target.local[segment_index], target.local[segment_index + 1])
                if t <= 0.02 or t >= 0.98:
                    continue
                gap_m = distance(endpoint, proj)
                if gap_m <= SNAP_EDGE_M or gap_m > REVIEW_ENDPOINT_EDGE_GAP_M:
                    continue
                toward_projection = normalize((proj[0] - endpoint[0], proj[1] - endpoint[1]))
                heading_score = max(0.0, dot(record["direction"], toward_projection))
                if heading_score < 0.25:
                    continue
                if best is None or gap_m < best[0]:
                    best = (gap_m, heading_score, target_index, proj, segment_index, t)
        if best is None:
            continue

        gap_m, heading_score, target_index, proj, segment_index, t = best
        crossings = endpoint_move_crossings(roads, int(record["road_index"]), int(record["point_index"]), target_index, proj)
        if crossings:
            continue

        target = roads[target_index]
        distance_score = max(0.0, 1.0 - gap_m / REVIEW_ENDPOINT_EDGE_GAP_M)
        class_score = class_match_score(road, target)
        name_score = name_match_score(road, target)
        confidence = 0.55 * heading_score + 0.25 * distance_score + 0.15 * class_score + 0.05 * name_score
        if confidence < REVIEW_MIN_CONFIDENCE:
            continue
        candidates.append({
            "kind": "endpoint_to_edge_review",
            "confidence": round(confidence, 3),
            "from": {
                "source_feature_id": record["source_feature_id"],
                "endpoint_role": record["endpoint_role"],
                **review_point(endpoint),
            },
            "to_edge": {
                "source_feature_id": target.source_feature_id,
                "segment_index": segment_index,
                "segment_t": round(t, 3),
                **review_point(proj),
            },
            "gap_m": round(gap_m, 3),
            "heading_score": round(heading_score, 3),
            "class_score": round(class_score, 3),
            "name_score": round(name_score, 3),
            "suggested_action": "manual_review_or_promote_snap_edge_threshold",
        })
    candidates.sort(key=lambda item: (-float(item["confidence"]), float(item["gap_m"])))
    return candidates


def build_repair_review(
    roads: list[RoadFeature],
    bbox: tuple[float, float, float, float] | None,
) -> dict[str, Any]:
    records = dangling_endpoint_records(roads, bbox)
    internal = [record for record in records if not bool(record["near_bbox_edge"])]
    boundary = [record for record in records if bool(record["near_bbox_edge"])]
    bridge_candidates = endpoint_bridge_candidates(records, roads)
    edge_candidates = endpoint_to_edge_review_candidates(records, roads)
    high_confidence = [
        candidate
        for candidate in bridge_candidates + edge_candidates
        if float(candidate["confidence"]) >= HIGH_CONFIDENCE_PROMOTION_MIN
    ]
    return {
        "dangling_endpoints": len(records),
        "internal_dangling_endpoints": len(internal),
        "bbox_boundary_dangling_endpoints": len(boundary),
        "endpoint_bridge_candidates": len(bridge_candidates),
        "endpoint_to_edge_review_candidates": len(edge_candidates),
        "high_confidence_candidates": len(high_confidence),
        "high_confidence_candidate_items": high_confidence[:REVIEW_TOP_CANDIDATES],
        "candidate_items": bridge_candidates + edge_candidates,
        "top_endpoint_bridge_candidates": bridge_candidates[:REVIEW_TOP_CANDIDATES],
        "top_endpoint_to_edge_candidates": edge_candidates[:REVIEW_TOP_CANDIDATES],
        "sample_internal_dangling_endpoints": [
            {
                "source_feature_id": record["source_feature_id"],
                "endpoint_role": record["endpoint_role"],
                "highway": record["highway"],
                "road_class": record["road_class"],
                **review_point(record["point"]),
            }
            for record in internal[:REVIEW_TOP_CANDIDATES]
        ],
        "note": "Review candidates are not applied automatically; promote only high-confidence cases after visual QA or manual overrides.",
    }


def default_manual_overrides_path(area_id: str) -> Path:
    return pipeline_root_from_script(Path(__file__)) / "config" / f"{area_id}.manual_overrides.json"


def default_repair_candidates_path(area_id: str) -> Path:
    return pipeline_root_from_script(Path(__file__)) / "data" / "processed" / f"{area_id}_repair_candidates.json"


def default_repair_decisions_path(area_id: str) -> Path:
    return pipeline_root_from_script(Path(__file__)) / "data" / "processed" / f"{area_id}_repair_decisions.json"


def default_repair_casebook_path(area_id: str) -> Path:
    return pipeline_root_from_script(Path(__file__)) / "data" / "processed" / f"{area_id}_repair_casebook.json"


def safe_id_part(value: Any) -> str:
    text = str(value or "").strip().lower()
    out = []
    for ch in text:
        out.append(ch if ch.isalnum() else "_")
    return "_".join(part for part in "".join(out).split("_") if part)


def candidate_id(candidate: dict[str, Any], index: int) -> str:
    kind = str(candidate.get("kind") or "candidate")
    if kind == "endpoint_bridge":
        from_ref = dict(candidate.get("from") or {})
        to_ref = dict(candidate.get("to") or {})
        return "_".join([
            "cand",
            safe_id_part(kind),
            safe_id_part(from_ref.get("source_feature_id")),
            safe_id_part(from_ref.get("endpoint_role")),
            safe_id_part(to_ref.get("source_feature_id")),
            safe_id_part(to_ref.get("endpoint_role")),
        ])
    if kind == "endpoint_to_edge_review":
        from_ref = dict(candidate.get("from") or {})
        to_edge = dict(candidate.get("to_edge") or {})
        return "_".join([
            "cand",
            "endpoint_to_edge",
            safe_id_part(from_ref.get("source_feature_id")),
            safe_id_part(from_ref.get("endpoint_role")),
            safe_id_part(to_edge.get("source_feature_id")),
            safe_id_part(to_edge.get("segment_index")),
        ])
    return f"cand_{safe_id_part(kind)}_{index:04d}"


def candidate_risk(candidate: dict[str, Any]) -> str:
    gap = float(candidate.get("gap_m") or 0.0)
    confidence = float(candidate.get("confidence") or 0.0)
    if gap <= SNAP_ENDPOINT_M and confidence >= HIGH_CONFIDENCE_PROMOTION_MIN:
        return "low"
    if gap <= REVIEW_ENDPOINT_EDGE_GAP_M and confidence >= REVIEW_MIN_CONFIDENCE:
        return "medium"
    return "high"


def candidate_validators(candidate: dict[str, Any]) -> dict[str, str]:
    kind = str(candidate.get("kind") or "")
    validators = {
        "source_refs_exist": "pass_at_generation",
        "layer_separation": "pass_at_generation",
        "confidence_threshold": "pass_at_generation",
        "manual_visual_qa": "required_before_apply",
    }
    if kind == "endpoint_to_edge_review":
        validators.update({
            "projection_inside_target_segment": "pass_at_generation",
            "no_new_third_road_crossing": "pass_at_generation",
            "do_not_move_valid_existing_node": "pass_at_generation",
        })
    if kind == "endpoint_bridge":
        validators.update({
            "no_new_third_road_crossing": "not_run",
            "bridge_geometry_validation": "required_before_apply",
        })
    return validators


def build_repair_candidate_document(
    *,
    area_id: str,
    input_path: Path,
    repair_review: dict[str, Any],
    apply_high_confidence: bool,
) -> dict[str, Any]:
    candidates = []
    for index, candidate in enumerate(repair_review.get("candidate_items", [])):
        item = dict(candidate)
        cid = candidate_id(item, index)
        item.update({
            "candidate_id": cid,
            "status": "candidate",
            "risk": candidate_risk(item),
            "auto_promotable": bool(float(item.get("confidence") or 0.0) >= HIGH_CONFIDENCE_PROMOTION_MIN),
            "auto_promotion_enabled": apply_high_confidence,
            "validators": candidate_validators(item),
        })
        candidates.append(item)

    return {
        "area_id": area_id,
        "stage": "topology_repair_candidates_v1",
        "schema": "road_test_pipeline.repair_candidates.v1",
        "source": str(input_path),
        "candidate_count": len(candidates),
        "counts": {
            "endpoint_bridge": sum(1 for item in candidates if item.get("kind") == "endpoint_bridge"),
            "endpoint_to_edge": sum(1 for item in candidates if item.get("kind") == "endpoint_to_edge_review"),
            "auto_promotable": sum(1 for item in candidates if item.get("auto_promotable")),
        },
        "candidates": candidates,
        "note": "Candidates are evidence, not repairs. A candidate can change geometry only after validator and QA gates pass.",
    }


def operation_decision_id(result: dict[str, Any], index: int) -> str:
    source = safe_id_part(result.get("source"))
    action = safe_id_part(result.get("action"))
    op_id = safe_id_part(result.get("id"))
    if op_id:
        return f"decision_{source}_{action}_{op_id}"
    return f"decision_{source}_{action}_{index:04d}"


def build_repair_decision_document(
    *,
    area_id: str,
    input_path: Path,
    output_path: Path,
    candidate_doc: dict[str, Any],
    base_counts: dict[str, Any],
    manual_results: list[dict[str, Any]],
    high_confidence_results: list[dict[str, Any]],
    apply_high_confidence: bool,
) -> dict[str, Any]:
    decisions = []
    for index, candidate in enumerate(candidate_doc.get("candidates", [])):
        status = "queued_for_manual_review"
        reason = "Automatic promotion is disabled; candidate remains available for visual QA or manual override."
        if apply_high_confidence and candidate.get("auto_promotable"):
            status = "queued_for_transactional_apply"
            reason = "Candidate is auto-promotable and will be attempted only through validator-gated repair operations."
        decisions.append({
            "decision_id": f"decision_candidate_{candidate['candidate_id']}",
            "candidate_id": candidate["candidate_id"],
            "source": "repair_candidate_generator",
            "action": candidate.get("suggested_action", candidate.get("kind", "")),
            "status": status,
            "reason": reason,
        })

    operation_results = manual_results + high_confidence_results
    for index, result in enumerate(operation_results):
        decisions.append({
            "decision_id": operation_decision_id(result, index),
            "source": result.get("source", ""),
            "action": result.get("action", ""),
            "status": result.get("status", ""),
            "reason": result.get("reason") or result.get("message") or "",
            "result": result,
        })

    return {
        "area_id": area_id,
        "stage": "topology_repair_decisions_v1",
        "schema": "road_test_pipeline.repair_decisions.v1",
        "source": str(input_path),
        "output": str(output_path),
        "base_repair_summary": {
            "duplicate_points_removed": base_counts.get("duplicate_points_removed", 0),
            "endpoint_snaps": base_counts.get("endpoint_snaps", 0),
            "endpoint_to_edge_snaps": base_counts.get("endpoint_to_edge_snaps", 0),
            "intersection_split_insertions": base_counts.get("intersection_split_insertions", 0),
            "short_edge_points_removed": base_counts.get("short_edge_points_removed", 0),
        },
        "decision_count": len(decisions),
        "decision_status_counts": {
            status: sum(1 for item in decisions if item.get("status") == status)
            for status in sorted({str(item.get("status") or "") for item in decisions})
        },
        "decisions": decisions,
        "note": "Decisions are the audit trail for candidate handling, manual overrides and high-confidence promotion attempts.",
    }


def build_repair_casebook_document(
    *,
    area_id: str,
    input_path: Path,
    manual_override_ops: list[dict[str, Any]],
    manual_results: list[dict[str, Any]],
    high_confidence_results: list[dict[str, Any]],
) -> dict[str, Any]:
    cases = []
    manual_result_by_id = {str(result.get("id") or ""): result for result in manual_results}
    for op in manual_override_ops:
        if op.get("enabled") is False:
            continue
        action = str(op.get("action") or op.get("kind") or "").strip().lower()
        if action not in {"forbid_connect", "forbid_snap_endpoint_to_edge", "ignore_dangling_endpoint"}:
            continue
        op_id = str(op.get("id") or operation_signature(op))
        cases.append({
            "case_id": f"case_manual_{safe_id_part(op_id)}",
            "case_type": "manual_override_regression",
            "source": "manual_override",
            "action": action,
            "status": "active",
            "expected_result": "must_remain_blocked_or_recorded",
            "reason": str(op.get("reason") or ""),
            "operation": op,
            "latest_result": manual_result_by_id.get(op_id, {}),
        })

    for result in high_confidence_results:
        if result.get("status") not in {"rejected", "failed"}:
            continue
        result_id = str(result.get("id") or operation_decision_id(result, len(cases)))
        cases.append({
            "case_id": f"case_rejected_{safe_id_part(result_id)}",
            "case_type": "rejected_high_confidence_regression",
            "source": result.get("source", "high_confidence_promotion"),
            "action": result.get("action", ""),
            "status": "active",
            "expected_result": "must_fail_until_validator_or_source_data_changes",
            "reason": result.get("message") or result.get("reason") or "Rejected by transaction validators.",
            "operation_result": result,
        })

    return {
        "area_id": area_id,
        "stage": "topology_repair_casebook_v1",
        "schema": "road_test_pipeline.repair_casebook.v1",
        "source": str(input_path),
        "case_count": len(cases),
        "case_type_counts": {
            case_type: sum(1 for item in cases if item.get("case_type") == case_type)
            for case_type in sorted({str(item.get("case_type") or "") for item in cases})
        },
        "cases": cases,
        "note": "Casebook entries are regression fixtures for known false positives, rejected high-confidence repairs and manual review decisions.",
    }


def load_manual_override_ops(path: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if path is None:
        return [], {"enabled": False, "path": ""}
    info: dict[str, Any] = {"enabled": True, "path": str(path), "exists": path.exists()}
    if not path.exists():
        return [], info

    data = read_json(path)
    raw_ops: Any = data.get("topology_repair", data.get("overrides", []))
    if isinstance(raw_ops, dict):
        raw_ops = raw_ops.get("overrides", [])
    if not isinstance(raw_ops, list):
        info["load_error"] = "Expected topology_repair or overrides to be a list."
        return [], info

    ops = [dict(item) for item in raw_ops if isinstance(item, dict)]
    info["loaded"] = len(ops)
    return ops, info


def road_index_by_source_id(roads: list[RoadFeature]) -> dict[str, int]:
    return {road.source_feature_id: index for index, road in enumerate(roads)}


def endpoint_index_for_role(road: RoadFeature, endpoint_role: str) -> int | None:
    role = str(endpoint_role or "").strip().lower()
    if role == "start":
        return 0
    if role == "end":
        return len(road.local) - 1
    return None


def endpoint_ref(ref: dict[str, Any]) -> tuple[str, str]:
    return str(ref.get("source_feature_id") or ""), str(ref.get("endpoint_role") or "").strip().lower()


def operation_signature(op: dict[str, Any]) -> tuple[Any, ...]:
    action = str(op.get("action") or op.get("kind") or "").strip().lower()
    if action in {"force_snap_endpoint_to_edge", "snap_endpoint_to_edge", "endpoint_to_edge_review"}:
        to_edge = dict(op.get("to_edge") or {})
        return (
            "snap_endpoint_to_edge",
            endpoint_ref(dict(op.get("from") or {})),
            str(to_edge.get("source_feature_id") or ""),
            int(to_edge.get("segment_index") or 0),
        )
    if action in {"force_connect", "endpoint_bridge", "endpoint_bridge_review"}:
        ends = sorted([endpoint_ref(dict(op.get("from") or {})), endpoint_ref(dict(op.get("to") or {}))])
        return ("endpoint_bridge", tuple(ends))
    if action in {"forbid_connect", "forbid_snap_endpoint_to_edge", "ignore_dangling_endpoint"}:
        return (action, endpoint_ref(dict(op.get("from") or {})), endpoint_ref(dict(op.get("to") or {})))
    return (action, str(op.get("id") or ""))


def candidate_to_operation(candidate: dict[str, Any]) -> dict[str, Any] | None:
    kind = str(candidate.get("kind") or "")
    if kind == "endpoint_to_edge_review":
        return {
            "id": "high_confidence_snap_endpoint_to_edge",
            "action": "force_snap_endpoint_to_edge",
            "reason": "Promoted from high-confidence endpoint-to-edge repair candidate.",
            "from": dict(candidate.get("from") or {}),
            "to_edge": dict(candidate.get("to_edge") or {}),
            "candidate": candidate,
        }
    if kind == "endpoint_bridge":
        return {
            "id": "high_confidence_endpoint_bridge",
            "action": "force_connect",
            "reason": "Promoted from high-confidence endpoint bridge repair candidate.",
            "from": dict(candidate.get("from") or {}),
            "to": dict(candidate.get("to") or {}),
            "candidate": candidate,
        }
    return None


def forbidden_signatures(ops: list[dict[str, Any]]) -> set[tuple[Any, ...]]:
    signatures: set[tuple[Any, ...]] = set()
    for op in ops:
        if op.get("enabled") is False:
            continue
        action = str(op.get("action") or op.get("kind") or "").strip().lower()
        if action == "forbid_snap_endpoint_to_edge":
            block = dict(op)
            block["action"] = "force_snap_endpoint_to_edge"
            signatures.add(operation_signature(block))
        elif action == "forbid_connect":
            block = dict(op)
            block["action"] = "force_connect"
            signatures.add(operation_signature(block))
    return signatures


def operation_failed(op: dict[str, Any], source: str, message: str) -> dict[str, Any]:
    return {
        "source": source,
        "id": str(op.get("id") or ""),
        "action": str(op.get("action") or op.get("kind") or ""),
        "status": "failed",
        "message": message,
    }


def operation_skipped(op: dict[str, Any], source: str, message: str) -> dict[str, Any]:
    return {
        "source": source,
        "id": str(op.get("id") or ""),
        "action": str(op.get("action") or op.get("kind") or ""),
        "status": "skipped",
        "message": message,
    }


def apply_endpoint_to_edge_operation(
    roads: list[RoadFeature],
    op: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    road_by_id = road_index_by_source_id(roads)
    from_ref = dict(op.get("from") or {})
    to_edge = dict(op.get("to_edge") or {})
    source_id, endpoint_role = endpoint_ref(from_ref)
    target_id = str(to_edge.get("source_feature_id") or "")
    if source_id not in road_by_id:
        return operation_failed(op, source, f"Unknown source feature {source_id!r}.")
    if target_id not in road_by_id:
        return operation_failed(op, source, f"Unknown target edge feature {target_id!r}.")

    road = roads[road_by_id[source_id]]
    target = roads[road_by_id[target_id]]
    endpoint_index = endpoint_index_for_role(road, endpoint_role)
    if endpoint_index is None:
        return operation_failed(op, source, "Endpoint role must be 'start' or 'end'.")
    if has_layer_separation(road.props) or has_layer_separation(target.props):
        return operation_failed(op, source, "Layer-separated roads are not eligible for planar endpoint-to-edge repair.")

    try:
        segment_index = int(to_edge.get("segment_index"))
    except Exception:
        segment_index = -1
    if segment_index < 0 or segment_index >= len(target.local) - 1:
        return operation_failed(op, source, f"Invalid target segment_index {to_edge.get('segment_index')!r}.")

    endpoint = road.local[endpoint_index]
    snap_point, t = closest_point_on_segment(endpoint, target.local[segment_index], target.local[segment_index + 1])
    if t <= 1e-6 or t >= 1.0 - 1e-6:
        return operation_failed(op, source, "Projection lands on target segment endpoint; use endpoint snapping or force_connect instead.")

    gap_m = distance(endpoint, snap_point)
    crossings = endpoint_move_crossings(roads, road_by_id[source_id], endpoint_index, road_by_id[target_id], snap_point)
    if crossings:
        result = operation_failed(op, source, "Endpoint move would cross another planar road segment.")
        result["blocking_crossings"] = crossings[:5]
        return result

    if gap_m <= NODE_EPS_M:
        inserted = insert_point_on_road(target, snap_point)
        return {
            "source": source,
            "id": str(op.get("id") or ""),
            "action": "force_snap_endpoint_to_edge",
            "status": "noop",
            "from": from_ref,
            "to_edge": to_edge,
            "gap_m": round(gap_m, 3),
            "inserted_split_point": inserted,
            "message": "Endpoint is already at the target edge.",
        }

    road.local[endpoint_index] = snap_point
    road.repair_ops.add(f"{source}_endpoint_to_edge_snap")
    target.repair_ops.add(f"{source}_edge_split_for_endpoint")
    inserted = insert_point_on_road(target, snap_point)
    return {
        "source": source,
        "id": str(op.get("id") or ""),
        "action": "force_snap_endpoint_to_edge",
        "status": "applied",
        "from": from_ref,
        "to_edge": to_edge,
        "gap_m": round(gap_m, 3),
        "segment_t": round(t, 4),
        "inserted_split_point": inserted,
        "reason": str(op.get("reason") or ""),
    }


def apply_endpoint_bridge_operation(
    roads: list[RoadFeature],
    op: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    road_by_id = road_index_by_source_id(roads)
    from_ref = dict(op.get("from") or {})
    to_ref = dict(op.get("to") or {})
    from_id, from_role = endpoint_ref(from_ref)
    to_id, to_role = endpoint_ref(to_ref)
    if from_id not in road_by_id:
        return operation_failed(op, source, f"Unknown from feature {from_id!r}.")
    if to_id not in road_by_id:
        return operation_failed(op, source, f"Unknown to feature {to_id!r}.")
    if from_id == to_id:
        return operation_failed(op, source, "Endpoint bridge cannot connect a road to itself.")

    road_a = roads[road_by_id[from_id]]
    road_b = roads[road_by_id[to_id]]
    index_a = endpoint_index_for_role(road_a, from_role)
    index_b = endpoint_index_for_role(road_b, to_role)
    if index_a is None or index_b is None:
        return operation_failed(op, source, "Endpoint roles must be 'start' or 'end'.")
    if has_layer_separation(road_a.props) or has_layer_separation(road_b.props):
        return operation_failed(op, source, "Layer-separated roads are not eligible for planar endpoint bridge repair.")

    point_a = road_a.local[index_a]
    point_b = road_b.local[index_b]
    gap_m = distance(point_a, point_b)
    if gap_m <= NODE_EPS_M:
        return operation_skipped(op, source, "Endpoints are already coincident.")

    bridge_id = f"repair_bridge_{from_id}_{from_role}_{to_id}_{to_role}"
    props = dict(road_a.props)
    props.update({
        "source_provider": "road_test_pipeline",
        "source_feature_id": bridge_id,
        "repair_bridge": 1,
        "repair_bridge_from": f"{from_id}:{from_role}",
        "repair_bridge_to": f"{to_id}:{to_role}",
        "repair_override_reason": str(op.get("reason") or ""),
    })
    bridge = RoadFeature(
        source_feature_id=bridge_id,
        props=props,
        lonlat=[],
        local=[point_a, point_b],
        repair_ops={f"{source}_endpoint_bridge"},
    )
    roads.append(bridge)
    return {
        "source": source,
        "id": str(op.get("id") or ""),
        "action": "force_connect",
        "status": "applied",
        "from": from_ref,
        "to": to_ref,
        "bridge_feature_id": bridge_id,
        "gap_m": round(gap_m, 3),
        "reason": str(op.get("reason") or ""),
    }


def apply_repair_operations(
    roads: list[RoadFeature],
    ops: list[dict[str, Any]],
    source: str,
    *,
    require_reason: bool,
) -> list[dict[str, Any]]:
    results = []
    for op in ops:
        if op.get("enabled") is False:
            results.append(operation_skipped(op, source, "Override is disabled."))
            continue

        action = str(op.get("action") or op.get("kind") or "").strip().lower()
        if require_reason and not str(op.get("reason") or "").strip():
            results.append(operation_failed(op, source, "Manual topology overrides must include a reason."))
            continue

        if action in {"force_snap_endpoint_to_edge", "snap_endpoint_to_edge", "endpoint_to_edge_review"}:
            results.append(apply_endpoint_to_edge_operation(roads, op, source))
        elif action in {"force_connect", "endpoint_bridge", "endpoint_bridge_review"}:
            results.append(apply_endpoint_bridge_operation(roads, op, source))
        elif action in {"forbid_connect", "forbid_snap_endpoint_to_edge", "ignore_dangling_endpoint"}:
            results.append({
                "source": source,
                "id": str(op.get("id") or ""),
                "action": action,
                "status": "recorded",
                "reason": str(op.get("reason") or ""),
            })
        else:
            results.append(operation_failed(op, source, f"Unsupported topology override action {action!r}."))
    return results


def summarize_operation_results(results: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {
        "applied": 0,
        "failed": 0,
        "rejected": 0,
        "skipped": 0,
        "noop": 0,
        "recorded": 0,
    }
    for result in results:
        status = str(result.get("status") or "unknown")
        summary[status] = summary.get(status, 0) + 1
    return summary


def possible_unsplit_crossing_samples(
    roads: list[RoadFeature],
    *,
    sample_limit: int = 10,
) -> tuple[int, list[dict[str, Any]]]:
    segments: list[tuple[int, int, tuple[float, float], tuple[float, float]]] = []
    for road_index, road in enumerate(roads):
        if len(road.local) < 2 or has_layer_separation(road.props):
            continue
        for segment_index in range(len(road.local) - 1):
            a = road.local[segment_index]
            b = road.local[segment_index + 1]
            if distance(a, b) < DEDUP_EPS_M:
                continue
            segments.append((road_index, segment_index, a, b))

    count = 0
    samples: list[dict[str, Any]] = []
    for i, (road_a_index, seg_a, a0, a1) in enumerate(segments):
        road_a = roads[road_a_index]
        for road_b_index, seg_b, b0, b1 in segments[i + 1 :]:
            if road_a_index == road_b_index:
                continue
            road_b = roads[road_b_index]
            if has_layer_separation(road_b.props):
                continue
            pt = segment_intersection(a0, a1, b0, b1)
            if pt is None:
                continue
            count += 1
            if len(samples) < sample_limit:
                samples.append({
                    "a": {
                        "source_feature_id": road_a.source_feature_id,
                        "segment_index": seg_a,
                    },
                    "b": {
                        "source_feature_id": road_b.source_feature_id,
                        "segment_index": seg_b,
                    },
                    **review_point(pt),
                })
    return count, samples


def repair_validation_metrics(roads: list[RoadFeature]) -> dict[str, Any]:
    crossings, samples = possible_unsplit_crossing_samples(roads)
    endpoint = endpoint_stats(roads)
    return {
        "short_segments_under_threshold": count_short_segments(roads, SHORT_EDGE_M),
        "possible_unsplit_crossings": crossings,
        "possible_unsplit_crossing_samples": samples,
        "endpoint_clusters": endpoint["endpoint_clusters"],
        "dangling_endpoint_clusters": endpoint["dangling_endpoint_clusters"],
        "dangling_endpoint_ratio": endpoint["dangling_endpoint_ratio"],
    }


def validator_result(name: str, passed: bool, before: Any, after: Any, message: str) -> dict[str, Any]:
    return {
        "id": name,
        "status": "pass" if passed else "fail",
        "before": before,
        "after": after,
        "message": message,
    }


def validate_trial_metrics(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        validator_result(
            "no_new_short_or_zero_edge",
            int(after["short_segments_under_threshold"]) <= int(before["short_segments_under_threshold"]),
            before["short_segments_under_threshold"],
            after["short_segments_under_threshold"],
            "Trial repair must not increase short segments under the repair threshold.",
        ),
        validator_result(
            "no_new_third_road_crossing",
            int(after["possible_unsplit_crossings"]) <= int(before["possible_unsplit_crossings"]),
            before["possible_unsplit_crossings"],
            after["possible_unsplit_crossings"],
            "Trial repair must not introduce new planar road-road crossings.",
        ),
        validator_result(
            "dangling_endpoint_ratio_no_regression",
            float(after["dangling_endpoint_ratio"]) <= float(before["dangling_endpoint_ratio"]) + 1e-9,
            before["dangling_endpoint_ratio"],
            after["dangling_endpoint_ratio"],
            "Trial repair must not increase the dangling endpoint ratio.",
        ),
    ]


def validators_pass(validators: list[dict[str, Any]]) -> bool:
    return all(str(item.get("status")) == "pass" for item in validators)


def transactional_apply_operation(
    roads: list[RoadFeature],
    op: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    before_metrics = repair_validation_metrics(roads)
    trial_roads = copy.deepcopy(roads)
    result = apply_repair_operations(
        trial_roads,
        [op],
        source,
        require_reason=False,
    )[0]
    after_metrics = repair_validation_metrics(trial_roads)
    validators = validate_trial_metrics(before_metrics, after_metrics)
    operation_ok = result.get("status") in {"applied", "noop"}
    validators.append(validator_result(
        "operation_result_acceptable",
        operation_ok,
        "pending",
        result.get("status"),
        "The operation must apply cleanly or be a deterministic no-op.",
    ))

    transaction = {
        **result,
        "transactional": True,
        "validators": validators,
        "before_metrics": before_metrics,
        "after_metrics": after_metrics,
    }
    if validators_pass(validators):
        roads[:] = trial_roads
        transaction["transaction_status"] = "accepted"
        return transaction

    transaction["status"] = "rejected"
    transaction["transaction_status"] = "rejected"
    transaction["message"] = "Rejected by transactional repair validators."
    return transaction


def apply_repair_operations_transactionally(
    roads: list[RoadFeature],
    ops: list[dict[str, Any]],
    source: str,
) -> list[dict[str, Any]]:
    return [transactional_apply_operation(roads, op, source) for op in ops]


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


def repair(
    input_path: Path,
    output_path: Path,
    report_path: Path,
    area_id: str,
    *,
    candidates_path: Path | None = None,
    decisions_path: Path | None = None,
    casebook_path: Path | None = None,
    manual_overrides_path: Path | None = None,
    apply_high_confidence: bool = False,
) -> dict[str, Any]:
    fc, roads, origin_lon, origin_lat = load_roads(input_path)
    input_road_count = len(roads)
    local_bbox = local_bbox_from_metadata(fc, origin_lon, origin_lat)
    before = endpoint_stats(roads)
    manual_override_ops, manual_override_info = load_manual_override_ops(manual_overrides_path)

    duplicate_points_removed = 0
    for road in roads:
        road.local, removed = remove_adjacent_duplicates(road.local)
        duplicate_points_removed += removed

    endpoint_snaps = apply_endpoint_snaps(roads)
    endpoint_to_edge_snaps = apply_endpoint_to_edge_snaps(roads)
    intersection_splits = apply_intersection_splits(roads)
    short_edges_before = count_short_segments(roads, SHORT_EDGE_M)
    short_edge_cleanup = apply_short_edge_cleanup(roads, local_bbox)
    repair_review_before_promotions = build_repair_review(roads, local_bbox)

    manual_results = apply_repair_operations(
        roads,
        manual_override_ops,
        "manual_override",
        require_reason=True,
    )
    blocked = forbidden_signatures(manual_override_ops)
    manual_force_signatures = {
        operation_signature(op)
        for op in manual_override_ops
        if op.get("enabled") is not False
        and str(op.get("action") or op.get("kind") or "").strip().lower()
        in {"force_snap_endpoint_to_edge", "snap_endpoint_to_edge", "force_connect", "endpoint_bridge"}
    }
    high_confidence_ops: list[dict[str, Any]] = []
    skipped_high_confidence_ops: list[dict[str, Any]] = []
    if apply_high_confidence:
        for candidate in repair_review_before_promotions.get("high_confidence_candidate_items", []):
            op = candidate_to_operation(candidate)
            if op is None:
                continue
            signature = operation_signature(op)
            if signature in blocked:
                skipped_high_confidence_ops.append(operation_skipped(op, "high_confidence_promotion", "Blocked by manual forbid override."))
                continue
            if signature in manual_force_signatures:
                skipped_high_confidence_ops.append(operation_skipped(op, "high_confidence_promotion", "Already covered by a manual override."))
                continue
            high_confidence_ops.append(op)

    high_confidence_results = apply_repair_operations_transactionally(
        roads,
        high_confidence_ops,
        "high_confidence_promotion",
    )
    high_confidence_results.extend(skipped_high_confidence_ops)

    post_promotion_short_edge_cleanup = {
        "short_edge_collapse_passes": 0,
        "short_edge_points_removed": 0,
        "short_edges_remaining_under_threshold_pre_output": count_short_segments(roads, SHORT_EDGE_M),
    }
    if any(result.get("status") == "applied" for result in manual_results + high_confidence_results):
        post_promotion_short_edge_cleanup = apply_short_edge_cleanup(roads, local_bbox)

    after = endpoint_stats(roads)
    repair_review = build_repair_review(roads, local_bbox)

    features = build_output_features(roads, origin_lon, origin_lat)
    output_edge_stats = endpoint_stats_from_output_features(features, origin_lon, origin_lat)
    short_edges_remaining_output = count_short_output_features(features, origin_lon, origin_lat, SHORT_EDGE_M)
    base_counts = {
        "input_features": input_road_count,
        "output_edges": len(features),
        "duplicate_points_removed": duplicate_points_removed,
        "endpoint_snaps": endpoint_snaps,
        "endpoint_to_edge_snaps": endpoint_to_edge_snaps,
        "intersection_split_insertions": intersection_splits,
        "short_edges_before_cleanup": short_edges_before,
        **short_edge_cleanup,
        "post_promotion_short_edge_points_removed": post_promotion_short_edge_cleanup["short_edge_points_removed"],
        "post_promotion_short_edges_remaining_under_threshold_pre_output": post_promotion_short_edge_cleanup["short_edges_remaining_under_threshold_pre_output"],
        "short_edges_remaining_under_threshold": short_edges_remaining_output,
        "internal_dangling_endpoints_for_review": repair_review["internal_dangling_endpoints"],
        "endpoint_bridge_candidates_for_review": repair_review["endpoint_bridge_candidates"],
        "endpoint_to_edge_candidates_for_review": repair_review["endpoint_to_edge_review_candidates"],
        "high_confidence_repair_candidates": repair_review["high_confidence_candidates"],
        "manual_override_ops_loaded": int(manual_override_info.get("loaded") or 0),
        "manual_override_ops_applied": summarize_operation_results(manual_results)["applied"],
        "manual_override_ops_failed": summarize_operation_results(manual_results)["failed"],
        "high_confidence_promotions_applied": summarize_operation_results(high_confidence_results)["applied"],
        "high_confidence_promotions_rejected": summarize_operation_results(high_confidence_results)["rejected"],
        "high_confidence_promotions_failed": summarize_operation_results(high_confidence_results)["failed"],
        "high_confidence_promotions_skipped": summarize_operation_results(high_confidence_results)["skipped"],
    }
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

    candidate_doc = build_repair_candidate_document(
        area_id=area_id,
        input_path=input_path,
        repair_review=repair_review_before_promotions,
        apply_high_confidence=apply_high_confidence,
    )
    decision_doc = build_repair_decision_document(
        area_id=area_id,
        input_path=input_path,
        output_path=output_path,
        candidate_doc=candidate_doc,
        base_counts=base_counts,
        manual_results=manual_results,
        high_confidence_results=high_confidence_results,
        apply_high_confidence=apply_high_confidence,
    )
    casebook_doc = build_repair_casebook_document(
        area_id=area_id,
        input_path=input_path,
        manual_override_ops=manual_override_ops,
        manual_results=manual_results,
        high_confidence_results=high_confidence_results,
    )
    if candidates_path is not None:
        write_json(candidates_path, candidate_doc)
    if decisions_path is not None:
        write_json(decisions_path, decision_doc)
    if casebook_path is not None:
        write_json(casebook_path, casebook_doc)

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
            "review_bridge_gap_m": REVIEW_BRIDGE_GAP_M,
            "review_endpoint_edge_gap_m": REVIEW_ENDPOINT_EDGE_GAP_M,
            "review_min_confidence": REVIEW_MIN_CONFIDENCE,
            "high_confidence_promotion_min": HIGH_CONFIDENCE_PROMOTION_MIN,
            "apply_high_confidence": apply_high_confidence,
            "manual_overrides_path": str(manual_overrides_path) if manual_overrides_path else "",
            "repair_candidates_path": str(candidates_path) if candidates_path else "",
            "repair_decisions_path": str(decisions_path) if decisions_path else "",
            "repair_casebook_path": str(casebook_path) if casebook_path else "",
        },
        "counts": base_counts,
        "repair_candidate_artifact": {
            "path": str(candidates_path) if candidates_path else "",
            "candidate_count": candidate_doc["candidate_count"],
            "counts": candidate_doc["counts"],
        },
        "repair_decision_artifact": {
            "path": str(decisions_path) if decisions_path else "",
            "decision_count": decision_doc["decision_count"],
            "decision_status_counts": decision_doc["decision_status_counts"],
        },
        "repair_casebook_artifact": {
            "path": str(casebook_path) if casebook_path else "",
            "case_count": casebook_doc["case_count"],
            "case_type_counts": casebook_doc["case_type_counts"],
        },
        "endpoint_stats_before": before,
        "endpoint_stats_after_parent_roads": after,
        "endpoint_stats_after_output_edges": output_edge_stats,
        "repair_review_before_promotions": repair_review_before_promotions,
        "repair_review": repair_review,
        "manual_overrides": {
            **manual_override_info,
            "result_counts": summarize_operation_results(manual_results),
            "results": manual_results,
        },
        "high_confidence_promotion": {
            "enabled": apply_high_confidence,
            "candidate_count_before": repair_review_before_promotions["high_confidence_candidates"],
            "result_counts": summarize_operation_results(high_confidence_results),
            "results": high_confidence_results,
        },
        "notes": [
            "V2 solves road continuity, planar junction insertion and conservative short-edge cleanup.",
            "Bridge, tunnel and layer-separated crossings are not planarized.",
            "Short-edge cleanup preserves road endpoints, junction anchors and bbox boundary points.",
            "Output is split into simple two-point edges for later road_graph building.",
            "Dangling endpoints and longer gap candidates are reported before promotion; manual overrides are reproducible in config.",
            "High-confidence repair candidates are attempted transactionally only when --apply-high-confidence is passed.",
            "Candidate and decision ledgers are written for transactional repair and regression-case workflows.",
            "Casebook entries preserve known false positives and rejected high-confidence repairs as regression fixtures.",
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
    parser.add_argument("--candidates-output", default="", help="Repair candidate ledger JSON.")
    parser.add_argument("--decisions-output", default="", help="Repair decision ledger JSON.")
    parser.add_argument("--casebook-output", default="", help="Repair regression casebook JSON.")
    parser.add_argument("--manual-overrides", default="", help="Manual topology overrides JSON. Defaults to config/<area_id>.manual_overrides.json when present.")
    parser.add_argument("--no-manual-overrides", action="store_true", help="Do not load config/<area_id>.manual_overrides.json.")
    parser.add_argument("--apply-high-confidence", action="store_true", help="Promote high-confidence review candidates into geometry repairs.")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    input_path = Path(args.input) if args.input else root / "data" / "processed" / f"{args.area_id}_roads_raw.geojson"
    output_path = Path(args.output) if args.output else root / "data" / "processed" / f"{args.area_id}_roads_repaired.geojson"
    report_path = Path(args.report) if args.report else root / "reports" / f"{args.area_id}_repair_report.json"
    candidates_path = Path(args.candidates_output) if args.candidates_output else default_repair_candidates_path(args.area_id)
    decisions_path = Path(args.decisions_output) if args.decisions_output else default_repair_decisions_path(args.area_id)
    casebook_path = Path(args.casebook_output) if args.casebook_output else default_repair_casebook_path(args.area_id)
    if args.no_manual_overrides:
        manual_overrides_path = None
    elif args.manual_overrides:
        manual_overrides_path = Path(args.manual_overrides)
    else:
        manual_overrides_path = default_manual_overrides_path(args.area_id)

    report = repair(
        input_path,
        output_path,
        report_path,
        args.area_id,
        candidates_path=candidates_path,
        decisions_path=decisions_path,
        casebook_path=casebook_path,
        manual_overrides_path=manual_overrides_path,
        apply_high_confidence=args.apply_high_confidence,
    )
    print(json.dumps({
        "area_id": args.area_id,
        "output": str(output_path),
        "report": str(report_path),
        "repair_candidates": str(candidates_path),
        "repair_decisions": str(decisions_path),
        "repair_casebook": str(casebook_path),
        "counts": report["counts"],
        "endpoint_stats_after_output_edges": report["endpoint_stats_after_output_edges"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
