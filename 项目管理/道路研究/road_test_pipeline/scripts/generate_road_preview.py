#!/usr/bin/env python3
"""Generate standalone road preview geometry without Houdini.

Outputs:
- preview GeoJSON road polygons
- simple OBJ mesh
- SVG top-down preview

V1 goal: visualize road continuity and junction coverage for the selected
500m road test area.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


WIDTH_DEFAULTS = {
    "motorway": 28.0,
    "trunk": 22.0,
    "primary": 16.0,
    "secondary": 12.0,
    "tertiary": 9.0,
    "residential": 6.0,
    "unclassified": 6.0,
    "service": 4.0,
    "living_street": 4.0,
}

LANE_DEFAULTS = {
    "motorway": 4,
    "trunk": 3,
    "primary": 2,
    "secondary": 2,
    "tertiary": 2,
    "residential": 2,
    "unclassified": 2,
    "service": 1,
    "living_street": 1,
}

NODE_EPS_M = 0.35
JUNCTION_MIN_DEGREE = 3
JUNCTION_CLUSTER_M = 10.0


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


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = a[0] - b[0]
    dz = a[1] - b[1]
    return math.sqrt(dx * dx + dz * dz)


def normalize(v: tuple[float, float]) -> tuple[float, float]:
    l = math.sqrt(v[0] * v[0] + v[1] * v[1])
    if l <= 1e-9:
        return 0.0, 0.0
    return v[0] / l, v[1] / l


def parse_lanes(value: Any, highway: str) -> int:
    try:
        text = str(value or "").split(";")[0].split("|")[0].strip()
        if text:
            lanes = int(float(text))
            if lanes > 0:
                return lanes
    except Exception:
        pass
    return LANE_DEFAULTS.get(highway, 1)


def parse_width(value: Any, highway: str, lanes: int) -> float:
    try:
        text = str(value or "").lower().replace("meters", "").replace("meter", "").replace("m", "").strip()
        if text:
            width = float(text)
            if width > 0:
                return width
    except Exception:
        pass
    return WIDTH_DEFAULTS.get(highway, max(4.0, lanes * 3.2))


def node_key(p: tuple[float, float], eps: float = NODE_EPS_M) -> tuple[int, int]:
    return round(p[0] / eps), round(p[1] / eps)


def road_quad(a: tuple[float, float], b: tuple[float, float], half_width: float) -> list[tuple[float, float]]:
    d = normalize((b[0] - a[0], b[1] - a[1]))
    n = (-d[1], d[0])
    return [
        (a[0] + n[0] * half_width, a[1] + n[1] * half_width),
        (b[0] + n[0] * half_width, b[1] + n[1] * half_width),
        (b[0] - n[0] * half_width, b[1] - n[1] * half_width),
        (a[0] - n[0] * half_width, a[1] - n[1] * half_width),
    ]


def load_edges(path: Path) -> tuple[list[dict[str, Any]], float, float, dict[str, Any]]:
    fc = read_json(path)
    origin_lon, origin_lat = local_projector_from_metadata(fc)
    edges = []
    for index, feat in enumerate(fc.get("features", [])):
        geom = feat.get("geometry") or {}
        props = feat.get("properties") or {}
        if geom.get("type") != "LineString":
            continue
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        a = to_local(float(coords[0][0]), float(coords[0][1]), origin_lon, origin_lat)
        b = to_local(float(coords[-1][0]), float(coords[-1][1]), origin_lon, origin_lat)
        if distance(a, b) < 0.05:
            continue
        highway = str(props.get("highway") or "unclassified")
        lanes = parse_lanes(props.get("lanes"), highway)
        width = parse_width(props.get("width_m"), highway, lanes)
        edges.append({
            "edge_id": len(edges),
            "source_feature_id": str(props.get("source_feature_id") or index),
            "highway": highway,
            "lanes": lanes,
            "width_m": width,
            "half_width": width * 0.5,
            "a": a,
            "b": b,
            "props": props,
        })
    return edges, origin_lon, origin_lat, fc.get("metadata") or {}


def build_nodes(edges: list[dict[str, Any]]) -> dict[tuple[int, int], dict[str, Any]]:
    nodes: dict[tuple[int, int], dict[str, Any]] = {}
    for edge in edges:
        for role in ("a", "b"):
            p = edge[role]
            key = node_key(p)
            item = nodes.setdefault(key, {"points": [], "edges": []})
            item["points"].append(p)
            item["edges"].append(edge)
    for item in nodes.values():
        pts = item["points"]
        item["pos"] = (
            sum(p[0] for p in pts) / len(pts),
            sum(p[1] for p in pts) / len(pts),
        )
        item["degree"] = len(item["edges"])
    return nodes


def junction_radius(node: dict[str, Any]) -> float:
    return max(edge["half_width"] for edge in node["edges"]) + 2.0


def circle_points(pos: tuple[float, float], radius: float, segments: int) -> list[tuple[float, float]]:
    return [
        (
            pos[0] + math.cos(i / segments * math.tau) * radius,
            pos[1] + math.sin(i / segments * math.tau) * radius,
        )
        for i in range(segments)
    ]


def convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def build_junction_polygon(node: dict[str, Any]) -> list[tuple[float, float]]:
    pos = node["pos"]
    radius = junction_radius(node)
    degree = node["degree"]
    segments = max(12, min(28, degree * 6))
    return circle_points(pos, radius, segments)


def build_junction_clusters(nodes: dict[tuple[int, int], dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [node for node in nodes.values() if node["degree"] >= JUNCTION_MIN_DEGREE]
    used: set[int] = set()
    clusters: list[dict[str, Any]] = []

    for start_index, start in enumerate(candidates):
        if start_index in used:
            continue
        queue = [start_index]
        used.add(start_index)
        members: list[dict[str, Any]] = []

        while queue:
            current_index = queue.pop()
            current = candidates[current_index]
            members.append(current)
            for other_index, other in enumerate(candidates):
                if other_index in used:
                    continue
                if distance(current["pos"], other["pos"]) <= JUNCTION_CLUSTER_M:
                    used.add(other_index)
                    queue.append(other_index)

        degree = sum(int(node["degree"]) for node in members)
        pos = (
            sum(node["pos"][0] * node["degree"] for node in members) / max(1, degree),
            sum(node["pos"][1] * node["degree"] for node in members) / max(1, degree),
        )
        clusters.append({
            "cluster_id": len(clusters),
            "nodes": members,
            "degree": degree,
            "pos": pos,
        })
    return clusters


def build_junction_cluster_polygon(cluster: dict[str, Any]) -> list[tuple[float, float]]:
    nodes = cluster["nodes"]
    if len(nodes) == 1:
        return build_junction_polygon(nodes[0])

    samples: list[tuple[float, float]] = []
    for node in nodes:
        radius = junction_radius(node)
        segments = max(12, min(24, int(node["degree"]) * 5))
        samples.extend(circle_points(node["pos"], radius, segments))

    hull = convex_hull(samples)
    if len(hull) >= 3:
        return hull
    return circle_points(cluster["pos"], max(junction_radius(node) for node in nodes), 16)


def trimmed_road_surface_points(
    edge: dict[str, Any],
    nodes: dict[tuple[int, int], dict[str, Any]],
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    a = edge["a"]
    b = edge["b"]
    length = distance(a, b)
    if length <= 0.05:
        return None

    start_node = nodes.get(node_key(a))
    end_node = nodes.get(node_key(b))
    trim_start = junction_radius(start_node) * 0.85 if start_node and start_node["degree"] >= JUNCTION_MIN_DEGREE else 0.0
    trim_end = junction_radius(end_node) * 0.85 if end_node and end_node["degree"] >= JUNCTION_MIN_DEGREE else 0.0

    trim_total = trim_start + trim_end
    max_trim_total = max(0.0, length - 0.5)
    if trim_total > max_trim_total:
        if max_trim_total <= 0.0:
            return None
        scale = max_trim_total / trim_total
        trim_start *= scale
        trim_end *= scale

    direction = normalize((b[0] - a[0], b[1] - a[1]))
    trimmed_a = (a[0] + direction[0] * trim_start, a[1] + direction[1] * trim_start)
    trimmed_b = (b[0] - direction[0] * trim_end, b[1] - direction[1] * trim_end)
    if distance(trimmed_a, trimmed_b) <= 0.05:
        return None
    return trimmed_a, trimmed_b


def polygon_to_lonlat(poly: list[tuple[float, float]], origin_lon: float, origin_lat: float) -> list[list[float]]:
    coords = []
    for x, z in poly:
        lon, lat = to_lonlat(x, z, origin_lon, origin_lat)
        coords.append([round(lon, 8), round(lat, 8)])
    if coords and coords[0] != coords[-1]:
        coords.append(coords[0])
    return coords


def polygon_area(poly: list[tuple[float, float]]) -> float:
    if len(poly) < 3:
        return 0.0
    twice_area = 0.0
    for i, p in enumerate(poly):
        q = poly[(i + 1) % len(poly)]
        twice_area += p[0] * q[1] - q[0] * p[1]
    return abs(twice_area) * 0.5


def patch_area_stats(junction_clusters: list[dict[str, Any]]) -> dict[str, Any]:
    areas = [polygon_area(build_junction_cluster_polygon(cluster)) for cluster in junction_clusters]
    if not areas:
        return {
            "min_m2": 0.0,
            "median_m2": 0.0,
            "max_m2": 0.0,
            "outliers_gt_4x_median": 0,
        }
    ordered = sorted(areas)
    median = ordered[len(ordered) // 2]
    outlier_threshold = median * 4.0 if median > 0 else float("inf")
    return {
        "min_m2": round(ordered[0], 3),
        "median_m2": round(median, 3),
        "max_m2": round(ordered[-1], 3),
        "outliers_gt_4x_median": sum(1 for area in areas if area > outlier_threshold),
    }


def road_surface_extrusion_stats(
    edges: list[dict[str, Any]],
    nodes: dict[tuple[int, int], dict[str, Any]],
) -> dict[str, Any]:
    generated = 0
    trimmed_count = 0
    absorbed_count = 0
    max_width_error = 0.0
    max_centering_error = 0.0

    for edge in edges:
        trimmed = trimmed_road_surface_points(edge, nodes)
        if trimmed is None:
            absorbed_count += 1
            continue
        if distance(trimmed[0], edge["a"]) > 0.001 or distance(trimmed[1], edge["b"]) > 0.001:
            trimmed_count += 1
        poly = road_quad(trimmed[0], trimmed[1], edge["half_width"])
        width_a = distance(poly[0], poly[3])
        width_b = distance(poly[1], poly[2])
        expected_width = edge["width_m"]
        max_width_error = max(max_width_error, abs(width_a - expected_width), abs(width_b - expected_width))

        center_a = ((poly[0][0] + poly[3][0]) * 0.5, (poly[0][1] + poly[3][1]) * 0.5)
        center_b = ((poly[1][0] + poly[2][0]) * 0.5, (poly[1][1] + poly[2][1]) * 0.5)
        max_centering_error = max(
            max_centering_error,
            distance(center_a, trimmed[0]),
            distance(center_b, trimmed[1]),
        )
        generated += 1

    return {
        "rule": "road surface is offset from retained centerline by width_m / 2 on both sides",
        "generated_surfaces": generated,
        "trimmed_at_junction": trimmed_count,
        "absorbed_by_junction": absorbed_count,
        "max_width_error_m": round(max_width_error, 6),
        "max_centering_error_m": round(max_centering_error, 6),
    }


def write_surface_geojson(
    path: Path,
    area_id: str,
    edges: list[dict[str, Any]],
    nodes: dict[tuple[int, int], dict[str, Any]],
    junction_clusters: list[dict[str, Any]],
    origin_lon: float,
    origin_lat: float,
) -> dict[str, int]:
    features = []
    road_surface_count = 0
    road_surface_trimmed_count = 0
    for edge in edges:
        trimmed = trimmed_road_surface_points(edge, nodes)
        if trimmed is None:
            continue
        if distance(trimmed[0], edge["a"]) > 0.001 or distance(trimmed[1], edge["b"]) > 0.001:
            road_surface_trimmed_count += 1
        poly = road_quad(trimmed[0], trimmed[1], edge["half_width"])
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [polygon_to_lonlat(poly, origin_lon, origin_lat)],
            },
            "properties": {
                "vc_part": "road_surface_preview",
                "edge_id": edge["edge_id"],
                "source_feature_id": edge["source_feature_id"],
                "highway": edge["highway"],
                "lanes": edge["lanes"],
                "width_m": edge["width_m"],
            },
        })
        road_surface_count += 1

    for edge in edges:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    list(to_lonlat(edge["a"][0], edge["a"][1], origin_lon, origin_lat)),
                    list(to_lonlat(edge["b"][0], edge["b"][1], origin_lon, origin_lat)),
                ],
            },
            "properties": {
                "vc_part": "road_centerline",
                "edge_id": edge["edge_id"],
                "source_feature_id": edge["source_feature_id"],
                "highway": edge["highway"],
                "lanes": edge["lanes"],
                "width_m": edge["width_m"],
            },
        })

    for junction_count, cluster in enumerate(junction_clusters):
        poly = build_junction_cluster_polygon(cluster)
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [polygon_to_lonlat(poly, origin_lon, origin_lat)],
            },
            "properties": {
                "vc_part": "junction_patch_preview",
                "junction_id": f"j_{junction_count:03d}",
                "degree": cluster["degree"],
                "cluster_node_count": len(cluster["nodes"]),
            },
        })

    write_json(path, {
        "type": "FeatureCollection",
        "metadata": {
            "area_id": area_id,
            "schema": "road_test_pipeline.roads_preview_surfaces.geojson",
            "coord_domain": "WGS84",
            "origin_lon": origin_lon,
            "origin_lat": origin_lat,
        },
            "features": features,
        })
    return {
        "road_surface_polygons": road_surface_count,
        "road_surface_trimmed_polygons": road_surface_trimmed_count,
        "road_surface_absorbed_by_junction": len(edges) - road_surface_count,
        "road_centerline_features": len(edges),
        "junction_patch_polygons": len(junction_clusters),
        "junction_clustered_nodes": sum(len(cluster["nodes"]) for cluster in junction_clusters),
    }


def write_obj(
    path: Path,
    edges: list[dict[str, Any]],
    nodes: dict[tuple[int, int], dict[str, Any]],
    junction_clusters: list[dict[str, Any]],
) -> dict[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    vertices: list[tuple[float, float, float]] = []
    faces: list[list[int]] = []
    groups: list[str] = []

    def add_poly(poly: list[tuple[float, float]], group: str) -> None:
        start = len(vertices) + 1
        for x, z in poly:
            vertices.append((x, 0.0, -z))
        faces.append(list(range(start, start + len(poly))))
        groups.append(group)

    for edge in edges:
        trimmed = trimmed_road_surface_points(edge, nodes)
        if trimmed is None:
            continue
        add_poly(road_quad(trimmed[0], trimmed[1], edge["half_width"]), "road_surface")

    for cluster in junction_clusters:
        add_poly(build_junction_cluster_polygon(cluster), "junction_patch")

    line_groups: list[str] = []
    lines_out: list[list[int]] = []
    for edge in edges:
        start = len(vertices) + 1
        for x, z in (edge["a"], edge["b"]):
            vertices.append((x, 0.06, -z))
        lines_out.append([start, start + 1])
        line_groups.append("road_centerline")

    with path.open("w", encoding="utf-8") as f:
        f.write("# road_test_pipeline standalone preview OBJ\n")
        for x, y, z in vertices:
            f.write(f"v {x:.4f} {y:.4f} {z:.4f}\n")
        last_group = None
        for group, face in zip(groups, faces):
            if group != last_group:
                f.write(f"g {group}\n")
                last_group = group
            f.write("f " + " ".join(str(i) for i in face) + "\n")
        for group, line in zip(line_groups, lines_out):
            if group != last_group:
                f.write(f"g {group}\n")
                last_group = group
            f.write("l " + " ".join(str(i) for i in line) + "\n")

    return {
        "obj_vertices": len(vertices),
        "obj_faces": len(faces),
        "obj_centerlines": len(lines_out),
        "obj_junction_patches": len(junction_clusters),
    }


def bounds_for(edges: list[dict[str, Any]], nodes: dict[tuple[int, int], dict[str, Any]]) -> tuple[float, float, float, float]:
    pts = []
    for edge in edges:
        pts.extend([edge["a"], edge["b"]])
    for node in nodes.values():
        pts.append(node["pos"])
    min_x = min(p[0] for p in pts)
    max_x = max(p[0] for p in pts)
    min_z = min(p[1] for p in pts)
    max_z = max(p[1] for p in pts)
    pad = 25.0
    return min_x - pad, min_z - pad, max_x + pad, max_z + pad


def svg_point(p: tuple[float, float], bounds: tuple[float, float, float, float], scale: float, margin: float) -> tuple[float, float]:
    min_x, min_z, _max_x, max_z = bounds
    x = margin + (p[0] - min_x) * scale
    y = margin + (max_z - p[1]) * scale
    return x, y


def write_svg(
    path: Path,
    edges: list[dict[str, Any]],
    nodes: dict[tuple[int, int], dict[str, Any]],
    junction_clusters: list[dict[str, Any]],
    area_id: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    b = bounds_for(edges, nodes)
    width_m = b[2] - b[0]
    height_m = b[3] - b[1]
    margin = 50
    canvas_w = 1200
    canvas_h = max(800, int(canvas_w * height_m / max(width_m, 1.0)))
    scale = min((canvas_w - margin * 2) / width_m, (canvas_h - margin * 2) / height_m)

    road_color = "#C7CCD2"
    centerline_color = "#8F969E"

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w}" height="{canvas_h}" viewBox="0 0 {canvas_w} {canvas_h}">',
        '<rect width="100%" height="100%" fill="#f7f9fc"/>',
        f'<text x="40" y="34" font-family="Arial, Microsoft YaHei" font-size="22" font-weight="700" fill="#172033">{area_id} road preview</text>',
        '<text x="40" y="58" font-family="Arial, Microsoft YaHei" font-size="13" fill="#5b6878">Standalone generation: repaired edges + simple road surfaces + junction patches</text>',
    ]

    for cluster in junction_clusters:
        poly = build_junction_cluster_polygon(cluster)
        svg_poly = [svg_point(p, b, scale, margin) for p in poly]
        points = " ".join(f"{x:.2f},{y:.2f}" for x, y in svg_poly)
        lines.append(f'<polygon points="{points}" fill="#D3D7DC" opacity="0.72" stroke="#9AA1A9" stroke-width="1"/>')

    for edge in edges:
        trimmed = trimmed_road_surface_points(edge, nodes)
        if trimmed is None:
            continue
        a = svg_point(trimmed[0], b, scale, margin)
        c = svg_point(trimmed[1], b, scale, margin)
        sw = max(1.5, edge["width_m"] * scale)
        lines.append(
            f'<line x1="{a[0]:.2f}" y1="{a[1]:.2f}" x2="{c[0]:.2f}" y2="{c[1]:.2f}" '
            f'stroke="{road_color}" stroke-width="{sw:.2f}" stroke-linecap="round" opacity="0.92"/>'
        )

    for edge in edges:
        a = svg_point(edge["a"], b, scale, margin)
        c = svg_point(edge["b"], b, scale, margin)
        lines.append(
            f'<line x1="{a[0]:.2f}" y1="{a[1]:.2f}" x2="{c[0]:.2f}" y2="{c[1]:.2f}" '
            f'stroke="{centerline_color}" stroke-width="0.7" stroke-linecap="round" opacity="0.55"/>'
        )

    counts = Counter(edge["highway"] for edge in edges)
    legend_y = canvas_h - 90
    lines.append(f'<text x="40" y="{legend_y}" font-family="Arial, Microsoft YaHei" font-size="13" fill="#334155">edges: {len(edges)} | junction patches: {len(junction_clusters)} | classes: {dict(counts)}</text>')
    lines.append("</svg>")
    path.write_text("\n".join(lines), encoding="utf-8")


def generate(area_id: str, root: Path) -> dict[str, Any]:
    processed = root / "data" / "processed"
    preview = root / "data" / "preview"
    reports = root / "reports"
    repaired = processed / f"{area_id}_roads_repaired.geojson"
    raw = processed / f"{area_id}_roads_raw.geojson"
    input_path = repaired if repaired.exists() else raw
    edges, origin_lon, origin_lat, _meta = load_edges(input_path)
    nodes = build_nodes(edges)
    junction_clusters = build_junction_clusters(nodes)

    surface_geojson = preview / f"{area_id}_roads_preview_surfaces.geojson"
    obj_path = preview / f"{area_id}_roads_preview.obj"
    svg_path = preview / f"{area_id}_roads_preview.svg"
    report_path = reports / f"{area_id}_road_preview_report.json"

    geojson_stats = write_surface_geojson(surface_geojson, area_id, edges, nodes, junction_clusters, origin_lon, origin_lat)
    obj_stats = write_obj(obj_path, edges, nodes, junction_clusters)
    write_svg(svg_path, edges, nodes, junction_clusters, area_id)

    junction_nodes = [node for node in nodes.values() if node["degree"] >= JUNCTION_MIN_DEGREE]
    report = {
        "area_id": area_id,
        "input": str(input_path),
        "input_mode": "repaired" if input_path == repaired else "raw",
        "outputs": {
            "surface_geojson": str(surface_geojson),
            "obj": str(obj_path),
            "svg": str(svg_path),
        },
        "counts": {
            "edges": len(edges),
            "endpoint_clusters": len(nodes),
            "junction_nodes_degree_ge_3": len(junction_nodes),
            "junction_clusters": len(junction_clusters),
            **geojson_stats,
            **obj_stats,
        },
        "junction_patch_area_m2": patch_area_stats(junction_clusters),
        "road_surface_extrusion": road_surface_extrusion_stats(edges, nodes),
        "highway_class_counts": dict(Counter(edge["highway"] for edge in edges).most_common()),
        "notes": [
            "V2 standalone preview uses road segment quads, retained road centerlines and clustered junction patches.",
            "This is for continuity and junction visual testing only, not final lane-level geometry.",
        ],
    }
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate standalone road preview geometry.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    args = parser.parse_args()
    root = pipeline_root_from_script(Path(__file__))
    report = generate(args.area_id, root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
