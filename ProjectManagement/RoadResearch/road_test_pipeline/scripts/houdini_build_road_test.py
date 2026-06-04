#!/usr/bin/env hython
"""Build and cook the isolated Houdini road test scene.

This script writes only inside road_test_pipeline. It intentionally avoids
VirtualCity's main Scripts, RawData, Config and Houdini pipeline.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

import hou


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def clear_children(node: hou.Node) -> None:
    for child in node.children():
        child.destroy()


def remove_test_materials() -> None:
    material = hou.node("/mat/road_test_centerline_dark")
    if material is not None:
        material.destroy()


def load_geojson_stats(path: Path) -> dict[str, Any]:
    fc = read_json(path)
    features = fc.get("features", [])
    highway_counts: dict[str, int] = {}
    lanes_count = 0
    oneway_count = 0
    for feat in features:
        props = feat.get("properties") or {}
        highway = str(props.get("highway") or "unknown")
        highway_counts[highway] = highway_counts.get(highway, 0) + 1
        if props.get("lanes") or props.get("lanes_forward") or props.get("lanes_backward"):
            lanes_count += 1
        if props.get("oneway"):
            oneway_count += 1
    return {
        "feature_count": len(features),
        "highway_counts": highway_counts,
        "features_with_lanes": lanes_count,
        "features_with_oneway": oneway_count,
    }


def resolve_package_path(value: str, package_dir: Path) -> Path:
    path = Path(str(value or ""))
    if not path.is_absolute():
        path = package_dir / path
    resolved = path.resolve()
    package_root = package_dir.resolve()
    try:
        resolved.relative_to(package_root)
    except ValueError as exc:
        raise ValueError(f"Houdini package input escapes package dir: {resolved}") from exc
    return resolved


def resolve_latest_houdini_package(root: Path, area_id: str) -> dict[str, Any]:
    latest_path = root / "data" / "lane_upgrade_packages" / area_id / "latest.json"
    if not latest_path.exists():
        raise FileNotFoundError(f"Missing LaneForge latest package pointer: {latest_path}")
    latest = read_json(latest_path)
    package_dir = Path(str(latest.get("latest_package_dir") or ""))
    if not package_dir.is_absolute():
        package_dir = latest_path.parent / package_dir
    package_dir = package_dir.resolve()

    package_manifest_path = Path(str(latest.get("manifest") or ""))
    if not package_manifest_path.is_absolute():
        package_manifest_path = package_dir / (str(latest.get("manifest") or "manifest.json"))
    package_manifest_path = package_manifest_path.resolve()
    try:
        package_manifest_path.relative_to(package_dir)
    except ValueError as exc:
        raise ValueError(f"LaneForge latest manifest escapes package dir: {package_manifest_path}") from exc
    package_manifest = read_json(package_manifest_path)
    contents = package_manifest.get("contents") or {}

    houdini_manifest_path = resolve_package_path(str(contents.get("houdini_manifest") or "houdini_manifest.json"), package_dir)
    houdini_manifest = read_json(houdini_manifest_path)
    inputs = houdini_manifest.get("inputs") or {}
    required_inputs = {
        "standard_lanes": "standard_lanes_path",
        "standard_junctions": "standard_junctions_path",
        "standard_lane_surfaces": "standard_lane_surfaces_path",
        "standard_lane_surfaces_obj": "standard_lane_surfaces_obj_path",
    }
    resolved_inputs: dict[str, Path] = {}
    missing_keys = [key for key in required_inputs if not inputs.get(key)]
    if missing_keys:
        raise KeyError(f"Houdini manifest missing required inputs: {missing_keys}")
    for input_key, result_key in required_inputs.items():
        input_path = resolve_package_path(str(inputs.get(input_key)), package_dir)
        if not input_path.exists():
            raise FileNotFoundError(f"Missing Houdini package input {input_key}: {input_path}")
        resolved_inputs[result_key] = input_path

    return {
        "mode": "lane_upgrade_package_houdini_manifest",
        "area_id": area_id,
        "package_version": str((houdini_manifest.get("metadata") or package_manifest.get("metadata") or {}).get("package_version") or ""),
        "latest_path": latest_path,
        "package_dir": package_dir,
        "package_manifest_path": package_manifest_path,
        "houdini_manifest_path": houdini_manifest_path,
        "package_manifest": package_manifest,
        "houdini_manifest": houdini_manifest,
        **resolved_inputs,
    }


def load_standard_lane_package_stats(standard_lanes_path: Path, standard_junctions_path: Path, standard_surface_path: Path) -> dict[str, Any]:
    standard_lanes = read_json(standard_lanes_path)
    standard_junctions = read_json(standard_junctions_path)
    standard_surfaces = read_json(standard_surface_path)
    lanes = standard_lanes.get("lanes", [])
    physical_lane_centerlines = standard_lanes.get("physical_lane_centerlines") or []
    centerline_records = physical_lane_centerlines or lanes
    road_ids = {
        str(road_id)
        for record in centerline_records
        for road_id in (record.get("road_ids") or [record.get("road_id", "")])
        if str(road_id)
    }
    directions: dict[str, int] = {}
    for record in centerline_records:
        direction = str(record.get("direction") or "unknown")
        directions[direction] = directions.get(direction, 0) + 1
    return {
        "feature_count": len(centerline_records),
        "highway_counts": {"standard_lane": len(centerline_records)},
        "features_with_lanes": len(centerline_records),
        "features_with_oneway": 0,
        "standard_lane_count": len(centerline_records),
        "standard_lane_segment_count": len(lanes),
        "physical_lane_centerline_count": len(physical_lane_centerlines),
        "standard_road_count": len(road_ids),
        "standard_junction_count": len(standard_junctions.get("junctions", [])),
        "standard_surface_count": len(standard_surfaces.get("features", [])),
        "lane_direction_counts": dict(sorted(directions.items())),
    }


def python_import_code(geojson_path: Path, origin_lon: float, origin_lat: float) -> str:
    return f'''import json
import math
import hou

GEOJSON_PATH = r"{geojson_path}"
ORIGIN_LON = {origin_lon:.12f}
ORIGIN_LAT = {origin_lat:.12f}
M_PER_DEG_LAT = 111320.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(ORIGIN_LAT))

WIDTH_DEFAULTS = {{
    "motorway": 28.0,
    "trunk": 22.0,
    "primary": 16.0,
    "secondary": 12.0,
    "tertiary": 9.0,
    "residential": 6.0,
    "unclassified": 6.0,
    "service": 4.0,
    "living_street": 4.0,
}}

LANE_DEFAULTS = {{
    "motorway": 4,
    "trunk": 3,
    "primary": 2,
    "secondary": 2,
    "tertiary": 2,
    "residential": 2,
    "unclassified": 2,
    "service": 1,
    "living_street": 1,
}}


def to_local(lon, lat):
    x = (float(lon) - ORIGIN_LON) * M_PER_DEG_LON
    z = (float(lat) - ORIGIN_LAT) * M_PER_DEG_LAT
    return x, z


def parse_lanes(value, highway):
    try:
        text = str(value or "").split(";")[0].split("|")[0].strip()
        if text:
            lanes = int(float(text))
            if lanes > 0:
                return lanes
    except Exception:
        pass
    return LANE_DEFAULTS.get(highway, 1)


def parse_width(value, highway, lanes):
    try:
        text = str(value or "").lower().replace("meters", "").replace("meter", "").replace("m", "").strip()
        if text:
            width = float(text)
            if width > 0:
                return width
    except Exception:
        pass
    return WIDTH_DEFAULTS.get(highway, max(4.0, lanes * 3.2))


node = hou.pwd()
geo = node.geometry()
geo.clear()

geo.addAttrib(hou.attribType.Prim, "source_provider", "")
geo.addAttrib(hou.attribType.Prim, "source_feature_id", "")
geo.addAttrib(hou.attribType.Prim, "highway", "")
geo.addAttrib(hou.attribType.Prim, "name", "")
geo.addAttrib(hou.attribType.Prim, "lanes", 0)
geo.addAttrib(hou.attribType.Prim, "osm_width", 0.0)
geo.addAttrib(hou.attribType.Prim, "half_width", 0.0)
geo.addAttrib(hou.attribType.Prim, "oneway", 0)
geo.addAttrib(hou.attribType.Prim, "seg_id", -1)
geo.addAttrib(hou.attribType.Prim, "vc_part", "")
geo.addAttrib(hou.attribType.Prim, "connector_id", "")
geo.addAttrib(hou.attribType.Prim, "connector_kind", "")
geo.addAttrib(hou.attribType.Prim, "corner_id", "")
geo.addAttrib(hou.attribType.Prim, "from_edge_id", "")
geo.addAttrib(hou.attribType.Prim, "to_edge_id", "")
geo.addAttrib(hou.attribType.Prim, "arc_geometry", "")
geo.addAttrib(hou.attribType.Prim, "arc_fit_status", "")
geo.addAttrib(hou.attribType.Prim, "arc_radius_m", 0.0)
geo.addAttrib(hou.attribType.Prim, "arc_center_x", 0.0)
geo.addAttrib(hou.attribType.Prim, "arc_center_z", 0.0)
geo.addAttrib(hou.attribType.Prim, "arc_sweep_deg", 0.0)
geo.addAttrib(hou.attribType.Prim, "arc_sample_count", 0)
geo.addAttrib(hou.attribType.Prim, "arc_design_min_radius_m", 0.0)
geo.addAttrib(hou.attribType.Prim, "arc_radius_margin_m", 0.0)

road_group = geo.createPrimGroup("roads_centerline")

with open(GEOJSON_PATH, encoding="utf-8") as f:
    fc = json.load(f)

for i, feat in enumerate(fc.get("features", [])):
    geom = feat.get("geometry") or {{}}
    props = feat.get("properties") or {{}}
    if geom.get("type") != "LineString":
        continue
    coords = geom.get("coordinates") or []
    if len(coords) < 2:
        continue

    highway = str(props.get("highway") or "unclassified")
    lanes = parse_lanes(props.get("lanes"), highway)
    width = parse_width(props.get("width_m"), highway, lanes)

    poly = geo.createPolygon(is_closed=False)
    for lon, lat in coords:
        x, z = to_local(lon, lat)
        pt = geo.createPoint()
        pt.setPosition(hou.Vector3(x, 0.0, -z))
        poly.addVertex(pt)

    poly.setAttribValue("source_provider", str(props.get("source_provider") or "openstreetmap_overpass"))
    poly.setAttribValue("source_feature_id", str(props.get("source_feature_id") or ""))
    poly.setAttribValue("highway", highway)
    poly.setAttribValue("name", str(props.get("name") or ""))
    poly.setAttribValue("lanes", int(lanes))
    poly.setAttribValue("osm_width", float(width))
    poly.setAttribValue("half_width", float(width) * 0.5)
    poly.setAttribValue("oneway", 1 if str(props.get("oneway") or "").lower() in ("1", "true", "yes") else 0)
    poly.setAttribValue("seg_id", int(props.get("seg_id") or i))
    poly.setAttribValue("vc_part", str(props.get("vc_part") or "road_centerline"))
    poly.setAttribValue("connector_id", str(props.get("connector_id") or ""))
    poly.setAttribValue("connector_kind", str(props.get("connector_kind") or ""))
    poly.setAttribValue("corner_id", str(props.get("corner_id") or ""))
    poly.setAttribValue("from_edge_id", str(props.get("from_edge_id") or ""))
    poly.setAttribValue("to_edge_id", str(props.get("to_edge_id") or ""))
    poly.setAttribValue("arc_geometry", str(props.get("arc_geometry") or ""))
    poly.setAttribValue("arc_fit_status", str(props.get("arc_fit_status") or ""))
    poly.setAttribValue("arc_radius_m", float(props.get("arc_radius_m") or 0.0))
    poly.setAttribValue("arc_center_x", float(props.get("arc_center_x") or 0.0))
    poly.setAttribValue("arc_center_z", float(props.get("arc_center_z") or 0.0))
    poly.setAttribValue("arc_sweep_deg", float(props.get("arc_sweep_deg") or 0.0))
    poly.setAttribValue("arc_sample_count", int(props.get("arc_sample_count") or 0))
    poly.setAttribValue("arc_design_min_radius_m", float(props.get("arc_design_min_radius_m") or 0.0))
    poly.setAttribValue("arc_radius_margin_m", float(props.get("arc_radius_margin_m") or 0.0))
    road_group.add(poly)
'''


def python_import_standard_lanes_code(standard_lanes_path: Path) -> str:
    template = r'''import json
import hou

STANDARD_LANES_PATH = __STANDARD_LANES_PATH__

node = hou.pwd()
geo = node.geometry()
geo.clear()

geo.addAttrib(hou.attribType.Prim, "source_provider", "")
geo.addAttrib(hou.attribType.Prim, "source_feature_id", "")
geo.addAttrib(hou.attribType.Prim, "highway", "")
geo.addAttrib(hou.attribType.Prim, "name", "")
geo.addAttrib(hou.attribType.Prim, "lanes", 0)
geo.addAttrib(hou.attribType.Prim, "osm_width", 0.0)
geo.addAttrib(hou.attribType.Prim, "half_width", 0.0)
geo.addAttrib(hou.attribType.Prim, "oneway", 0)
geo.addAttrib(hou.attribType.Prim, "seg_id", -1)
geo.addAttrib(hou.attribType.Prim, "vc_part", "")
geo.addAttrib(hou.attribType.Prim, "lane_id", "")
geo.addAttrib(hou.attribType.Prim, "road_id", "")
geo.addAttrib(hou.attribType.Prim, "direction", "")
geo.addAttrib(hou.attribType.Prim, "lane_width_m", 0.0)
geo.addAttrib(hou.attribType.Prim, "road_width_m", 0.0)

road_group = geo.createPrimGroup("roads_centerline")
lane_group = geo.createPrimGroup("standard_lane_centerline")

with open(STANDARD_LANES_PATH, encoding="utf-8") as f:
    standard_lanes = json.load(f)

centerline_records = standard_lanes.get("physical_lane_centerlines") or standard_lanes.get("lanes", [])

for index, lane in enumerate(centerline_records):
    coords = lane.get("centerline_xz") or []
    if len(coords) < 2:
        continue
    lane_id = str(lane.get("centerline_id") or lane.get("lane_id") or "")
    road_ids = lane.get("road_ids") or [lane.get("road_id", "")]
    road_id = ",".join(str(value) for value in road_ids if str(value))
    width = float(lane.get("width_m") or 3.2)

    poly = geo.createPolygon(is_closed=False)
    for x, z in coords:
        pt = geo.createPoint()
        pt.setPosition(hou.Vector3(float(x), 0.0, -float(z)))
        poly.addVertex(pt)

    poly.setAttribValue("source_provider", "LaneForge")
    poly.setAttribValue("source_feature_id", lane_id)
    poly.setAttribValue("highway", "standard_lane")
    poly.setAttribValue("name", lane_id)
    poly.setAttribValue("lanes", 1)
    poly.setAttribValue("osm_width", width)
    poly.setAttribValue("half_width", width * 0.5)
    poly.setAttribValue("oneway", 1)
    poly.setAttribValue("seg_id", index)
    poly.setAttribValue("vc_part", "standard_lane_centerline")
    poly.setAttribValue("lane_id", lane_id)
    poly.setAttribValue("road_id", road_id)
    poly.setAttribValue("direction", str(lane.get("direction") or ""))
    poly.setAttribValue("lane_width_m", width)
    poly.setAttribValue("road_width_m", float(lane.get("road_width_m") or width))
    road_group.add(poly)
    lane_group.add(poly)
'''
    return template.replace("__STANDARD_LANES_PATH__", json.dumps(str(standard_lanes_path).replace("\\", "/")))


def python_surface_code() -> str:
    return r'''import hou
import math
from collections import defaultdict

node = hou.pwd()
geo = node.geometry()
geo.clear()

src_node = node.inputs()[0] if node.inputs() else None
if src_node is None:
    raise hou.NodeError("road_preview_surface requires centerline input")
src = src_node.geometry()

geo.addAttrib(hou.attribType.Prim, "source_feature_id", "")
geo.addAttrib(hou.attribType.Prim, "highway", "")
geo.addAttrib(hou.attribType.Prim, "lanes", 0)
geo.addAttrib(hou.attribType.Prim, "osm_width", 0.0)
geo.addAttrib(hou.attribType.Prim, "half_width", 0.0)
geo.addAttrib(hou.attribType.Prim, "seg_id", -1)
geo.addAttrib(hou.attribType.Prim, "is_junction", 0)
geo.addAttrib(hou.attribType.Prim, "vc_part", "")

surface_group = geo.createPrimGroup("roads_preview_surface")
junction_group = geo.createPrimGroup("junction_patch")
NODE_EPS_M = 0.35
JUNCTION_MIN_DEGREE = 3
JUNCTION_CLUSTER_M = 10.0
JUNCTION_RADIUS_M = 2.0
MIN_JUNCTION_ANGLE_DEG = 25.0
MAX_CLIP_MARGIN_M = 14.0


def prim_attr(prim, name, default):
    try:
        value = prim.attribValue(name)
    except Exception:
        return default
    return value if value not in (None, "") else default


def pos_key(pos, eps=NODE_EPS_M):
    return (round(pos.x() / eps), round(pos.z() / eps))


def pos_distance(a, b):
    dx = a.x() - b.x()
    dz = a.z() - b.z()
    return math.sqrt(dx * dx + dz * dz)


def normalize2(dx, dz):
    length = math.sqrt(dx * dx + dz * dz)
    if length <= 1e-9:
        return (0.0, 0.0)
    return (dx / length, dz / length)


def rotate90(direction):
    return (-direction[1], direction[0])


def angle_of(direction):
    return math.atan2(direction[1], direction[0])


def angle_between(a, b):
    dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1]))
    return math.acos(dot)


def edge_direction_out(edge_end):
    edge = edge_end["edge"]
    if edge_end["role"] == "a":
        return normalize2(edge["b"].x() - edge["a"].x(), edge["b"].z() - edge["a"].z())
    return normalize2(edge["a"].x() - edge["b"].x(), edge["a"].z() - edge["b"].z())


def circle_points(pos, radius, segments):
    return [
        (
            pos.x() + math.cos(i / float(segments) * math.tau) * radius,
            pos.z() + math.sin(i / float(segments) * math.tau) * radius,
        )
        for i in range(segments)
    ]


def convex_hull(points):
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def compute_node_clip_margins(item):
    item["clip_by_edge"] = {}
    if item["degree"] < JUNCTION_MIN_DEGREE:
        return

    ends = []
    for edge_end in item["edge_ends"]:
        direction = edge_direction_out(edge_end)
        ends.append({
            "edge": edge_end["edge"],
            "direction": direction,
            "angle": angle_of(direction),
            "half_width": edge_end["edge"]["half_width"],
        })
    ends.sort(key=lambda end: end["angle"])

    min_angle_floor = math.radians(MIN_JUNCTION_ANGLE_DEG)
    for index, edge_end in enumerate(ends):
        prev_end = ends[index - 1]
        next_end = ends[(index + 1) % len(ends)]
        a0 = angle_between(edge_end["direction"], prev_end["direction"])
        a1 = angle_between(edge_end["direction"], next_end["direction"])
        min_angle = max(min_angle_floor, min(a0, a1))
        neighbor_hw = max(edge_end["half_width"], prev_end["half_width"], next_end["half_width"])
        clip = neighbor_hw / max(0.25, 2.0 * math.sin(min_angle)) + JUNCTION_RADIUS_M
        clip = min(clip, edge_end["edge"]["length"] * 0.45, MAX_CLIP_MARGIN_M)
        item["clip_by_edge"][edge_end["edge"]["edge_id"]] = max(0.0, clip)


def build_junction_polygon(item):
    pos = item["pos"]
    boundary_points = []
    for edge_end in sorted(item["edge_ends"], key=lambda end: angle_of(edge_direction_out(end))):
        edge = edge_end["edge"]
        direction = edge_direction_out(edge_end)
        normal = rotate90(direction)
        clip = item.get("clip_by_edge", {}).get(edge["edge_id"], edge["half_width"] + JUNCTION_RADIUS_M)
        cx = pos.x() + direction[0] * clip
        cz = pos.z() + direction[1] * clip
        boundary_points.append((cx - normal[0] * edge["half_width"], cz - normal[1] * edge["half_width"]))
        boundary_points.append((cx + normal[0] * edge["half_width"], cz + normal[1] * edge["half_width"]))

    if len(boundary_points) < 3:
        return []
    return sorted(boundary_points, key=lambda p: math.atan2(p[1] - pos.z(), p[0] - pos.x()))


def build_junction_clusters(items):
    candidates = [item for item in items if item["degree"] >= JUNCTION_MIN_DEGREE]
    used = set()
    clusters = []

    for start_index, start in enumerate(candidates):
        if start_index in used:
            continue
        queue = [start_index]
        used.add(start_index)
        members = []

        while queue:
            current_index = queue.pop()
            current = candidates[current_index]
            members.append(current)
            for other_index, other in enumerate(candidates):
                if other_index in used:
                    continue
                if pos_distance(current["pos"], other["pos"]) <= JUNCTION_CLUSTER_M:
                    used.add(other_index)
                    queue.append(other_index)

        degree = sum(int(item["degree"]) for item in members)
        x = sum(item["pos"].x() * item["degree"] for item in members) / float(max(1, degree))
        y = sum(item["pos"].y() * item["degree"] for item in members) / float(max(1, degree))
        z = sum(item["pos"].z() * item["degree"] for item in members) / float(max(1, degree))
        clusters.append({"nodes": members, "degree": degree, "pos": hou.Vector3(x, y, z)})
    return clusters


def build_junction_cluster_polygon(cluster):
    nodes = cluster["nodes"]
    if len(nodes) == 1:
        return build_junction_polygon(nodes[0])

    samples = []
    for item in nodes:
        samples.extend(build_junction_polygon(item))
    hull = convex_hull(samples)
    if len(hull) >= 3:
        return hull
    return []


junction_nodes = defaultdict(lambda: {"pos": None, "count": 0, "degree": 0, "edge_ends": []})
edge_records = []
for prim in src.prims():
    points = [v.point().position() for v in prim.vertices()]
    if len(points) < 2:
        continue
    half_width = float(prim_attr(prim, "half_width", 3.0))
    edge_record = {
        "edge_id": len(edge_records),
        "a": points[0],
        "b": points[-1],
        "half_width": half_width,
        "length": pos_distance(points[0], points[-1]),
    }
    edge_records.append(edge_record)
    for role, pos in (("a", points[0]), ("b", points[-1])):
        item = junction_nodes[pos_key(pos)]
        if item["pos"] is None:
            item["pos"] = hou.Vector3(pos)
        else:
            n = item["count"]
            item["pos"] = (item["pos"] * n + pos) / float(n + 1)
        item["count"] += 1
        item["degree"] += 1
        item["edge_ends"].append({"edge": edge_record, "role": role})

for item in junction_nodes.values():
    compute_node_clip_margins(item)


def trim_for_junctions(p0, p1):
    dx = p1.x() - p0.x()
    dz = p1.z() - p0.z()
    length = math.sqrt(dx * dx + dz * dz)
    if length < 0.05:
        return None

    start_node = junction_nodes.get(pos_key(p0))
    end_node = junction_nodes.get(pos_key(p1))
    edge_id = None
    for record in edge_records:
        if pos_distance(record["a"], p0) <= NODE_EPS_M and pos_distance(record["b"], p1) <= NODE_EPS_M:
            edge_id = record["edge_id"]
            break
    trim_start = start_node.get("clip_by_edge", {}).get(edge_id, 0.0) if start_node else 0.0
    trim_end = end_node.get("clip_by_edge", {}).get(edge_id, 0.0) if end_node else 0.0

    trim_total = trim_start + trim_end
    max_trim_total = max(0.0, length - 0.5)
    if trim_total > max_trim_total:
        if max_trim_total <= 0.0:
            return None
        scale = max_trim_total / trim_total
        trim_start *= scale
        trim_end *= scale

    ux = dx / length
    uz = dz / length
    a = hou.Vector3(p0.x() + ux * trim_start, p0.y(), p0.z() + uz * trim_start)
    b = hou.Vector3(p1.x() - ux * trim_end, p1.y(), p1.z() - uz * trim_end)
    if pos_distance(a, b) <= 0.05:
        return None
    return a, b


for prim in src.prims():
    points = [v.point().position() for v in prim.vertices()]
    if len(points) < 2:
        continue

    half_width = float(prim_attr(prim, "half_width", 3.0))
    highway = str(prim_attr(prim, "highway", "unclassified"))
    source_feature_id = str(prim_attr(prim, "source_feature_id", ""))
    seg_id = int(prim_attr(prim, "seg_id", prim.number()))
    lanes = int(prim_attr(prim, "lanes", 0))
    width = float(prim_attr(prim, "osm_width", half_width * 2.0))

    for index in range(len(points) - 1):
        p0 = points[index]
        p1 = points[index + 1]
        trimmed = trim_for_junctions(p0, p1)
        if trimmed is None:
            continue
        p0, p1 = trimmed
        dx = p1.x() - p0.x()
        dz = p1.z() - p0.z()
        length = math.sqrt(dx * dx + dz * dz)
        if length < 0.05:
            continue

        sx = -dz / length
        sz = dx / length
        corners = [
            hou.Vector3(p0.x() + sx * half_width, p0.y(), p0.z() + sz * half_width),
            hou.Vector3(p1.x() + sx * half_width, p1.y(), p1.z() + sz * half_width),
            hou.Vector3(p1.x() - sx * half_width, p1.y(), p1.z() - sz * half_width),
            hou.Vector3(p0.x() - sx * half_width, p0.y(), p0.z() - sz * half_width),
        ]

        poly = geo.createPolygon(is_closed=True)
        for pos in corners:
            pt = geo.createPoint()
            pt.setPosition(pos)
            poly.addVertex(pt)

        poly.setAttribValue("source_feature_id", source_feature_id)
        poly.setAttribValue("highway", highway)
        poly.setAttribValue("lanes", lanes)
        poly.setAttribValue("osm_width", width)
        poly.setAttribValue("half_width", half_width)
        poly.setAttribValue("seg_id", seg_id)
        poly.setAttribValue("is_junction", 0)
        poly.setAttribValue("vc_part", "road_surface_preview")
        surface_group.add(poly)

for cluster_index, cluster in enumerate(build_junction_clusters(list(junction_nodes.values()))):
    poly_points = build_junction_cluster_polygon(cluster)
    if len(poly_points) < 3:
        continue
    poly = geo.createPolygon(is_closed=True)
    for x, z in poly_points:
        pt = geo.createPoint()
        pt.setPosition(hou.Vector3(x, 0.03, z))
        poly.addVertex(pt)
    poly.setAttribValue("source_feature_id", "junction_%03d" % cluster_index)
    poly.setAttribValue("highway", "junction")
    poly.setAttribValue("lanes", 0)
    poly.setAttribValue("osm_width", 0.0)
    poly.setAttribValue("half_width", 0.0)
    poly.setAttribValue("seg_id", cluster_index)
    poly.setAttribValue("is_junction", 1)
    poly.setAttribValue("vc_part", "junction_patch_preview")
    surface_group.add(poly)
    junction_group.add(poly)
'''


def python_centerline_code() -> str:
    return r'''import hou

node = hou.pwd()
geo = node.geometry()
geo.clear()

src_node = node.inputs()[0] if node.inputs() else None
if src_node is None:
    raise hou.NodeError("road_centerline requires centerline input")
src = src_node.geometry()

geo.addAttrib(hou.attribType.Prim, "source_feature_id", "")
geo.addAttrib(hou.attribType.Prim, "highway", "")
geo.addAttrib(hou.attribType.Prim, "lanes", 0)
geo.addAttrib(hou.attribType.Prim, "osm_width", 0.0)
geo.addAttrib(hou.attribType.Prim, "half_width", 0.0)
geo.addAttrib(hou.attribType.Prim, "seg_id", -1)
geo.addAttrib(hou.attribType.Prim, "is_junction", 0)
geo.addAttrib(hou.attribType.Prim, "vc_part", "")
geo.addAttrib(hou.attribType.Prim, "width", 0.35)
geo.addAttrib(hou.attribType.Prim, "lane_id", "")
geo.addAttrib(hou.attribType.Prim, "road_id", "")
geo.addAttrib(hou.attribType.Prim, "direction", "")

centerline_group = geo.createPrimGroup("road_centerline")
CENTERLINE_Y = 0.12


def prim_attr(prim, name, default):
    try:
        value = prim.attribValue(name)
    except Exception:
        return default
    return value if value not in (None, "") else default


for prim in src.prims():
    highway = str(prim_attr(prim, "highway", "unclassified"))
    source_feature_id = str(prim_attr(prim, "source_feature_id", ""))
    seg_id = int(prim_attr(prim, "seg_id", prim.number()))
    lanes = int(prim_attr(prim, "lanes", 0))
    width = float(prim_attr(prim, "osm_width", 0.0))
    half_width = float(prim_attr(prim, "half_width", 0.0))

    points = [v.point().position() for v in prim.vertices()]
    if len(points) < 2:
        continue

    line = geo.createPolygon(is_closed=False)
    for pos in points:
        pt = geo.createPoint()
        pt.setPosition(hou.Vector3(pos.x(), CENTERLINE_Y, pos.z()))
        line.addVertex(pt)

    line.setAttribValue("source_feature_id", source_feature_id)
    line.setAttribValue("highway", highway)
    line.setAttribValue("lanes", lanes)
    line.setAttribValue("osm_width", width)
    line.setAttribValue("half_width", half_width)
    line.setAttribValue("seg_id", seg_id)
    line.setAttribValue("is_junction", 0)
    line.setAttribValue("vc_part", "road_centerline")
    line.setAttribValue("width", 0.35)
    line.setAttribValue("lane_id", str(prim_attr(prim, "lane_id", "")))
    line.setAttribValue("road_id", str(prim_attr(prim, "road_id", "")))
    line.setAttribValue("direction", str(prim_attr(prim, "direction", "")))
    centerline_group.add(line)
'''


def python_lane_debug_code(
    lane_graph_path: Path | None = None,
    *,
    standard_lanes_path: Path | None = None,
    standard_junctions_path: Path | None = None,
) -> str:
    template = r'''import hou
import json
import math

LANE_GRAPH_PATH = __LANE_GRAPH_PATH__
STANDARD_LANES_PATH = __STANDARD_LANES_PATH__
STANDARD_JUNCTIONS_PATH = __STANDARD_JUNCTIONS_PATH__
LANE_RIBBON_WIDTH_M = 0.7
LANE_LINK_RIBBON_WIDTH_M = 1.0
LANE_LINE_Y = 0.18
LANE_LINK_LINE_Y = 0.26
RIBBON_Y = 0.03

node = hou.pwd()
geo = node.geometry()
geo.clear()

geo.addAttrib(hou.attribType.Prim, "vc_part", "")
geo.addAttrib(hou.attribType.Prim, "debug_id", "")
geo.addAttrib(hou.attribType.Prim, "from_lane", "")
geo.addAttrib(hou.attribType.Prim, "to_lane", "")
geo.addAttrib(hou.attribType.Prim, "turn", "")
geo.addAttrib(hou.attribType.Prim, "confidence", 0.0)
geo.addAttrib(hou.attribType.Prim, "debug_width_m", 0.0)
geo.addAttrib(hou.attribType.Prim, "width", 0.35)

lane_line_group = geo.createPrimGroup("lane_debug_centerline")
lane_ribbon_group = geo.createPrimGroup("lane_debug_ribbon")
link_line_group = geo.createPrimGroup("lane_link_debug_curve")
link_ribbon_group = geo.createPrimGroup("lane_link_debug_ribbon")
continuity_line_group = geo.createPrimGroup("lane_continuity_debug_curve")
continuity_ribbon_group = geo.createPrimGroup("lane_continuity_debug_ribbon")


def normalize(v):
    length = math.sqrt(v[0] * v[0] + v[1] * v[1])
    if length <= 1e-9:
        return (0.0, 0.0)
    return (v[0] / length, v[1] / length)


def rotate90(v):
    return (-v[1], v[0])


def as_points(coords):
    return [(float(point[0]), float(point[1])) for point in coords]


def distance(a, b):
    dx = a[0] - b[0]
    dz = a[1] - b[1]
    return math.sqrt(dx * dx + dz * dz)


def polyline_length(points):
    return sum(distance(points[i], points[i + 1]) for i in range(len(points) - 1))


def resolve_trim_distances(length, trim_start_m, trim_end_m, locked_start_m=0.0, locked_end_m=0.0):
    trim_start_m = max(0.0, trim_start_m)
    trim_end_m = max(0.0, trim_end_m)
    locked_start_m = min(max(0.0, locked_start_m), trim_start_m)
    locked_end_m = min(max(0.0, locked_end_m), trim_end_m)
    trim_total = trim_start_m + trim_end_m
    max_trim_total = max(0.0, length - 0.5)
    if trim_total > max_trim_total and trim_total > 0.0:
        locked_total = locked_start_m + locked_end_m
        if locked_total >= max_trim_total and locked_total > 0.0:
            scale = max_trim_total / locked_total
            return locked_start_m * scale, locked_end_m * scale
        remaining = max_trim_total - locked_total
        start_extra = trim_start_m - locked_start_m
        end_extra = trim_end_m - locked_end_m
        extra_total = start_extra + end_extra
        if extra_total <= 0.0:
            return locked_start_m, locked_end_m
        scale = remaining / extra_total
        return locked_start_m + start_extra * scale, locked_end_m + end_extra * scale
    return trim_start_m, trim_end_m


def trim_polyline(points, trim_start_m, trim_end_m, locked_start_m=0.0, locked_end_m=0.0):
    if len(points) < 2:
        return []
    length = polyline_length(points)
    if length <= 0.05:
        return []
    trim_start_m, trim_end_m = resolve_trim_distances(length, trim_start_m, trim_end_m, locked_start_m, locked_end_m)

    def point_at(distance_m):
        if distance_m <= 0.0:
            return points[0]
        remaining = distance_m
        for i in range(len(points) - 1):
            seg_len = distance(points[i], points[i + 1])
            if seg_len <= 1e-9:
                continue
            if remaining <= seg_len:
                t = remaining / seg_len
                return (
                    points[i][0] + (points[i + 1][0] - points[i][0]) * t,
                    points[i][1] + (points[i + 1][1] - points[i][1]) * t,
                )
            remaining -= seg_len
        return points[-1]

    start_distance = trim_start_m
    end_distance = max(start_distance + 0.05, length - trim_end_m)
    trimmed = [point_at(start_distance)]
    cursor = 0.0
    for i in range(len(points) - 1):
        seg_len = distance(points[i], points[i + 1])
        next_cursor = cursor + seg_len
        if start_distance < next_cursor and cursor < end_distance:
            if start_distance < next_cursor and points[i] != trimmed[-1] and cursor >= start_distance:
                trimmed.append(points[i])
            if next_cursor <= end_distance:
                trimmed.append(points[i + 1])
        cursor = next_cursor
    end_point = point_at(end_distance)
    if not trimmed or distance(trimmed[-1], end_point) > 0.01:
        trimmed.append(end_point)
    return trimmed if polyline_length(trimmed) > 0.05 else []


def lane_link_records(lane_graph):
    records = []
    for junction in lane_graph.get("junctions", []):
        for connection in junction.get("connections", []):
            for link in connection.get("lane_links", []):
                records.append(dict(link))
    return records


def lane_trim_distances(lane_graph, lane_links, continuity_links):
    trim_m = float(lane_graph.get("metadata", {}).get("junction_trim_m") or 8.0)
    lanes_by_id = {str(lane.get("lane_id") or ""): lane for lane in lane_graph.get("lanes", [])}
    trim_by_lane = {}

    def update(lane_id, side, value):
        if not lane_id or value <= 0.0:
            return
        item = trim_by_lane.setdefault(lane_id, {"start": 0.0, "end": 0.0, "locked_start": 0.0, "locked_end": 0.0})
        item[side] = max(item[side], value)

    def lock(lane_id, side, value):
        if not lane_id or value <= 0.0:
            return
        item = trim_by_lane.setdefault(lane_id, {"start": 0.0, "end": 0.0, "locked_start": 0.0, "locked_end": 0.0})
        item[side] = max(item[side], value)
        item["locked_" + side] = max(item["locked_" + side], value)

    def default_lane_link_trim(lane_id):
        lane = lanes_by_id.get(lane_id)
        if lane is not None and bool(lane.get("approach_centerline_trimmed")):
            return 0.0
        return trim_m

    def link_trim_value(link, key, default):
        if key not in link or link.get(key) is None:
            return default
        return max(0.0, float(link.get(key) or 0.0))

    for link in lane_links:
        from_lane = str(link.get("from_lane") or "")
        to_lane = str(link.get("to_lane") or "")
        update(from_lane, "end", link_trim_value(link, "from_lane_trim_end_m", default_lane_link_trim(from_lane)))
        update(to_lane, "start", link_trim_value(link, "to_lane_trim_start_m", default_lane_link_trim(to_lane)))

    for link in continuity_links:
        lock(str(link.get("from_lane") or ""), "end", float(link.get("from_lane_trim_end_m") or 0.0))
        lock(str(link.get("to_lane") or ""), "start", float(link.get("to_lane_trim_start_m") or 0.0))

    return trim_by_lane


def centerline_source_lane_ids(record):
    source_lane_ids = [
        str(lane_id)
        for lane_id in (record.get("source_lane_ids") or [])
        if str(lane_id)
    ]
    if source_lane_ids:
        return source_lane_ids
    lane_id = str(record.get("lane_id") or "")
    return [lane_id] if lane_id else []


def centerline_trim(record, trim_by_lane):
    source_lane_ids = centerline_source_lane_ids(record)
    if not source_lane_ids:
        return {}
    start_trim = trim_by_lane.get(source_lane_ids[0], {})
    end_trim = trim_by_lane.get(source_lane_ids[-1], {})
    return {
        "start": float(start_trim.get("start") or 0.0),
        "end": float(end_trim.get("end") or 0.0),
        "locked_start": float(start_trim.get("locked_start") or 0.0),
        "locked_end": float(end_trim.get("locked_end") or 0.0),
    }


def trimmed_centerline_points(record, trim_by_lane):
    points = as_points(record.get("centerline_xz") or [])
    trim = centerline_trim(record, trim_by_lane)
    return trim_polyline(
        points,
        float(trim.get("start") or 0.0),
        float(trim.get("end") or 0.0),
        float(trim.get("locked_start") or 0.0),
        float(trim.get("locked_end") or 0.0),
    )


def ribbon_polygon(points, width_m):
    if len(points) < 2:
        return []
    half = width_m * 0.5
    left = []
    right = []
    for i, point in enumerate(points):
        if i == 0:
            tangent = normalize((points[1][0] - point[0], points[1][1] - point[1]))
        elif i == len(points) - 1:
            tangent = normalize((point[0] - points[i - 1][0], point[1] - points[i - 1][1]))
        else:
            prev_tangent = normalize((point[0] - points[i - 1][0], point[1] - points[i - 1][1]))
            next_tangent = normalize((points[i + 1][0] - point[0], points[i + 1][1] - point[1]))
            tangent = normalize((prev_tangent[0] + next_tangent[0], prev_tangent[1] + next_tangent[1]))
            if tangent == (0.0, 0.0):
                tangent = next_tangent
        normal = rotate90(tangent)
        left.append((point[0] + normal[0] * half, point[1] + normal[1] * half))
        right.append((point[0] - normal[0] * half, point[1] - normal[1] * half))
    return left + list(reversed(right))


def add_line(points, part, debug_id, y, width, group, turn="", from_lane="", to_lane="", confidence=0.0):
    if len(points) < 2:
        return None
    prim = geo.createPolygon(is_closed=False)
    for x, z in points:
        point = geo.createPoint()
        point.setPosition(hou.Vector3(x, y, -z))
        prim.addVertex(point)
    prim.setAttribValue("vc_part", part)
    prim.setAttribValue("debug_id", debug_id)
    prim.setAttribValue("from_lane", from_lane)
    prim.setAttribValue("to_lane", to_lane)
    prim.setAttribValue("turn", turn)
    prim.setAttribValue("confidence", float(confidence))
    prim.setAttribValue("debug_width_m", float(width))
    prim.setAttribValue("width", 0.35 if part == "lane_debug_centerline" else 0.65)
    group.add(prim)
    return prim


def add_ribbon(points, width, part, debug_id, y, group, turn="", from_lane="", to_lane="", confidence=0.0):
    polygon = ribbon_polygon(points, width)
    if len(polygon) < 3:
        return None
    prim = geo.createPolygon(is_closed=True)
    for x, z in polygon:
        point = geo.createPoint()
        point.setPosition(hou.Vector3(x, y, -z))
        prim.addVertex(point)
    prim.setAttribValue("vc_part", part)
    prim.setAttribValue("debug_id", debug_id)
    prim.setAttribValue("from_lane", from_lane)
    prim.setAttribValue("to_lane", to_lane)
    prim.setAttribValue("turn", turn)
    prim.setAttribValue("confidence", float(confidence))
    prim.setAttribValue("debug_width_m", float(width))
    group.add(prim)
    return prim


if LANE_GRAPH_PATH:
    with open(LANE_GRAPH_PATH, encoding="utf-8") as f:
        lane_graph = json.load(f)
else:
    with open(STANDARD_LANES_PATH, encoding="utf-8") as f:
        standard_lanes = json.load(f)
    with open(STANDARD_JUNCTIONS_PATH, encoding="utf-8") as f:
        standard_junctions = json.load(f)
    lane_graph = {
        "metadata": standard_lanes.get("metadata") or {},
        "lanes": standard_lanes.get("lanes", []),
        "physical_lane_centerlines": standard_lanes.get("physical_lane_centerlines", []),
        "continuity_links": standard_lanes.get("continuity_links", []),
        "junctions": standard_junctions.get("junctions", []),
    }

lane_links = lane_link_records(lane_graph)
continuity_links = [dict(link) for link in lane_graph.get("continuity_links", [])]
trim_by_lane = lane_trim_distances(lane_graph, lane_links, continuity_links)

centerline_records = lane_graph.get("physical_lane_centerlines") or lane_graph.get("lanes", [])
for record in centerline_records:
    points = trimmed_centerline_points(record, trim_by_lane)
    debug_id = str(record.get("centerline_id") or record.get("lane_id") or "")
    add_line(points, "lane_debug_centerline", debug_id, LANE_LINE_Y, LANE_RIBBON_WIDTH_M, lane_line_group)
    add_ribbon(points, LANE_RIBBON_WIDTH_M, "lane_debug_ribbon", debug_id, RIBBON_Y, lane_ribbon_group)

for junction in lane_graph.get("junctions", []):
    for connection in junction.get("connections", []):
        turn = str(connection.get("turn") or "")
        for link in connection.get("lane_links", []):
            points = as_points(link.get("connecting_curve_xz") or [])
            lane_link_id = str(link.get("lane_link_id") or "")
            from_lane = str(link.get("from_lane") or "")
            to_lane = str(link.get("to_lane") or "")
            confidence = float(link.get("confidence") or 0.0)
            add_line(points, "lane_link_debug_curve", lane_link_id, LANE_LINK_LINE_Y, LANE_LINK_RIBBON_WIDTH_M, link_line_group, turn, from_lane, to_lane, confidence)
            add_ribbon(points, LANE_LINK_RIBBON_WIDTH_M, "lane_link_debug_ribbon", lane_link_id, RIBBON_Y + 0.02, link_ribbon_group, turn, from_lane, to_lane, confidence)

for link in lane_graph.get("continuity_links", []):
    if link.get("micro_seam_absorbed"):
        continue
    points = as_points(link.get("connecting_curve_xz") or [])
    continuity_link_id = str(link.get("continuity_link_id") or "")
    from_lane = str(link.get("from_lane") or "")
    to_lane = str(link.get("to_lane") or "")
    confidence = float(link.get("width_confidence") or 0.0)
    turn = str(link.get("turn") or "corner")
    add_line(points, "lane_continuity_debug_curve", continuity_link_id, LANE_LINK_LINE_Y, LANE_LINK_RIBBON_WIDTH_M, continuity_line_group, turn, from_lane, to_lane, confidence)
    add_ribbon(points, LANE_LINK_RIBBON_WIDTH_M, "lane_continuity_debug_ribbon", continuity_link_id, RIBBON_Y + 0.02, continuity_ribbon_group, turn, from_lane, to_lane, confidence)
'''
    if lane_graph_path is None and (standard_lanes_path is None or standard_junctions_path is None):
        raise ValueError("python_lane_debug_code requires lane_graph_path or standard package lane/junction paths")
    replacements = {
        "__LANE_GRAPH_PATH__": json.dumps(str(lane_graph_path).replace("\\", "/")) if lane_graph_path is not None else "None",
        "__STANDARD_LANES_PATH__": json.dumps(str(standard_lanes_path).replace("\\", "/")) if standard_lanes_path is not None else "None",
        "__STANDARD_JUNCTIONS_PATH__": json.dumps(str(standard_junctions_path).replace("\\", "/")) if standard_junctions_path is not None else "None",
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    return template


def python_lane_surface_import_code(surface_geojson_path: Path) -> str:
    template = r'''import hou
import json

SURFACE_GEOJSON_PATH = __SURFACE_GEOJSON_PATH__

node = hou.pwd()
geo = node.geometry()
geo.clear()

geo.addAttrib(hou.attribType.Prim, "vc_part", "")
geo.addAttrib(hou.attribType.Prim, "lane_id", "")
geo.addAttrib(hou.attribType.Prim, "lane_link_id", "")
geo.addAttrib(hou.attribType.Prim, "continuity_link_id", "")
geo.addAttrib(hou.attribType.Prim, "junction_id", "")
geo.addAttrib(hou.attribType.Prim, "node_id", "")
geo.addAttrib(hou.attribType.Prim, "junction_type", "")
geo.addAttrib(hou.attribType.Prim, "from_lane", "")
geo.addAttrib(hou.attribType.Prim, "to_lane", "")
geo.addAttrib(hou.attribType.Prim, "turn", "")
geo.addAttrib(hou.attribType.Prim, "confidence", 0.0)
geo.addAttrib(hou.attribType.Prim, "width_m", 0.0)
geo.addAttrib(hou.attribType.Prim, "area_m2", 0.0)

lane_surface_group = geo.createPrimGroup("lane_surface_v1")
turn_surface_group = geo.createPrimGroup("lane_turn_surface_v1")
continuity_surface_group = geo.createPrimGroup("lane_continuity_surface_v1")
junction_envelope_group = geo.createPrimGroup("junction_envelope_surface_v1")

with open(SURFACE_GEOJSON_PATH, encoding="utf-8") as f:
    fc = json.load(f)

for feature in fc.get("features", []):
    geom = feature.get("geometry") or {}
    props = feature.get("properties") or {}
    if geom.get("type") != "Polygon":
        continue
    rings = geom.get("coordinates") or []
    if not rings or len(rings[0]) < 4:
        continue
    ring = rings[0]
    if ring[0] == ring[-1]:
        ring = ring[:-1]
    part = str(props.get("vc_part") or "")
    y = 0.01 if part == "junction_envelope_surface_v1" else 0.02 if part == "lane_surface_v1" else 0.05
    prim = geo.createPolygon(is_closed=True)
    for x, z in ring:
        point = geo.createPoint()
        point.setPosition(hou.Vector3(float(x), y, -float(z)))
        prim.addVertex(point)
    prim.setAttribValue("vc_part", part)
    prim.setAttribValue("lane_id", str(props.get("lane_id") or ""))
    prim.setAttribValue("lane_link_id", str(props.get("lane_link_id") or ""))
    prim.setAttribValue("continuity_link_id", str(props.get("continuity_link_id") or ""))
    prim.setAttribValue("junction_id", str(props.get("junction_id") or ""))
    prim.setAttribValue("node_id", str(props.get("node_id") or ""))
    prim.setAttribValue("junction_type", str(props.get("junction_type") or ""))
    prim.setAttribValue("from_lane", str(props.get("from_lane") or ""))
    prim.setAttribValue("to_lane", str(props.get("to_lane") or ""))
    prim.setAttribValue("turn", str(props.get("turn") or ""))
    prim.setAttribValue("confidence", float(props.get("confidence") or 0.0))
    prim.setAttribValue("width_m", float(props.get("width_m") or 0.0))
    prim.setAttribValue("area_m2", float(props.get("area_m2") or 0.0))
    if part == "lane_turn_surface_v1":
        turn_surface_group.add(prim)
    elif part == "lane_continuity_surface_v1":
        continuity_surface_group.add(prim)
    elif part == "junction_envelope_surface_v1":
        junction_envelope_group.add(prim)
    else:
        lane_surface_group.add(prim)
'''
    return template.replace("__SURFACE_GEOJSON_PATH__", json.dumps(str(surface_geojson_path).replace("\\", "/")))


def python_junction_debug_code() -> str:
    return r'''import hou
import math
from collections import defaultdict

node = hou.pwd()
geo = node.geometry()
geo.clear()

src_node = node.inputs()[0] if node.inputs() else None
if src_node is None:
    raise hou.NodeError("junction_debug_points requires centerline input")
src = src_node.geometry()

geo.addAttrib(hou.attribType.Point, "degree", 0)
geo.addAttrib(hou.attribType.Point, "vc_part", "")

clusters = defaultdict(lambda: {"pos": None, "count": 0})
eps = 6.0

for prim in src.prims():
    pts = [v.point().position() for v in prim.vertices()]
    if len(pts) < 2:
        continue
    for pos in (pts[0], pts[-1]):
        key = (round(pos.x() / eps), round(pos.z() / eps))
        item = clusters[key]
        if item["pos"] is None:
            item["pos"] = hou.Vector3(pos)
        else:
            n = item["count"]
            item["pos"] = (item["pos"] * n + pos) / float(n + 1)
        item["count"] += 1

for item in clusters.values():
    if item["count"] < 3:
        continue
    pt = geo.createPoint()
    pt.setPosition(item["pos"] + hou.Vector3(0, 0.15, 0))
    pt.setAttribValue("degree", int(item["count"]))
    pt.setAttribValue("vc_part", "junction_candidate")
'''


def create_or_get(parent: hou.Node, node_type: str, name: str) -> hou.Node:
    existing = parent.node(name)
    if existing is not None:
        existing.destroy()
    return parent.createNode(node_type, node_name=name)


def build_scene(root: Path, config_path: Path) -> dict[str, Any]:
    cfg = read_json(config_path)
    area_id = cfg["area_id"]
    package_inputs = resolve_latest_houdini_package(root, area_id)
    standard_lanes_path = package_inputs["standard_lanes_path"]
    standard_junctions_path = package_inputs["standard_junctions_path"]
    lane_surface_geojson_path = package_inputs["standard_lane_surfaces_path"]

    hip_dir = ensure_dir(root / "houdini")
    report_dir = ensure_dir(root / "reports")
    hip_path = hip_dir / f"{area_id}_road_test.hip"
    report_path = report_dir / f"{area_id}_houdini_cook_report.json"

    hou.hipFile.clear(suppress_save_prompt=True)
    obj = hou.node("/obj")
    clear_children(obj)
    remove_test_materials()

    geo = obj.createNode("geo", node_name=f"road_test_{area_id}")
    clear_children(geo)

    import_node = create_or_get(geo, "python", "python_import_standard_lanes")
    import_node.parm("python").set(python_import_standard_lanes_code(standard_lanes_path))
    import_node.setDisplayFlag(False)

    center_null = create_or_get(geo, "null", "OUT_centerlines")
    center_null.setInput(0, import_node)
    center_null.setDisplayFlag(False)
    center_null.setRenderFlag(False)

    centerline_node = create_or_get(geo, "python", "python_centerlines_retained")
    centerline_node.setInput(0, import_node)
    centerline_node.parm("python").set(python_centerline_code())

    out_node = create_or_get(geo, "null", "OUT_roads_centerlines")
    out_node.setInput(0, centerline_node)
    out_node.setDisplayFlag(True)
    out_node.setRenderFlag(True)

    lane_debug_node = None
    lane_debug_out = None
    lane_debug_node = create_or_get(geo, "python", "python_lane_geometry_debug")
    lane_debug_node.parm("python").set(
        python_lane_debug_code(
            standard_lanes_path=standard_lanes_path,
            standard_junctions_path=standard_junctions_path,
        )
    )
    lane_debug_node.setDisplayFlag(False)
    lane_debug_node.setRenderFlag(False)

    lane_debug_out = create_or_get(geo, "null", "OUT_lane_connections_debug")
    lane_debug_out.setInput(0, lane_debug_node)
    lane_debug_out.setDisplayFlag(False)
    lane_debug_out.setRenderFlag(False)

    lane_surface_node = None
    lane_surface_out = None
    if lane_surface_geojson_path.exists():
        lane_surface_node = create_or_get(geo, "python", "python_lane_surfaces_v1")
        lane_surface_node.parm("python").set(python_lane_surface_import_code(lane_surface_geojson_path))
        lane_surface_node.setDisplayFlag(False)
        lane_surface_node.setRenderFlag(False)

        lane_surface_out = create_or_get(geo, "null", "OUT_lane_surfaces_v1")
        lane_surface_out.setInput(0, lane_surface_node)
        lane_surface_out.setDisplayFlag(False)
        lane_surface_out.setRenderFlag(False)

    note = geo.createStickyNote("ROAD_TEST_NOTES")
    note.setText(
        "Isolated road_test_pipeline cook\\n"
        f"Area: {area_id}\\n"
        f"Package: {package_inputs['package_version']}\\n"
        "Input: lane_upgrade_packages/latest -> houdini_manifest.json\\n"
        "Output: OUT_roads_centerlines\\n"
        "Debug: OUT_lane_connections_debug\\n"
        "Surface: OUT_lane_surfaces_v1\\n"
        "Mode: centerlines only\\n"
        "This HIP does not touch the main VirtualCity pipeline."
    )
    note.setPosition(hou.Vector2(-3.5, 2.0))

    geo.layoutChildren()
    cook_nodes = [import_node, center_null, centerline_node, out_node]
    if lane_debug_node is not None and lane_debug_out is not None:
        cook_nodes.extend([lane_debug_node, lane_debug_out])
    if lane_surface_node is not None and lane_surface_out is not None:
        cook_nodes.extend([lane_surface_node, lane_surface_out])
    for node in cook_nodes:
        node.cook(force=True)

    stats = load_standard_lane_package_stats(standard_lanes_path, standard_junctions_path, lane_surface_geojson_path)
    center_geo = center_null.geometry()
    out_geo = out_node.geometry()
    lane_debug_geo = lane_debug_out.geometry() if lane_debug_out is not None else None
    lane_surface_geo = lane_surface_out.geometry() if lane_surface_out is not None else None
    report = {
        "area_id": area_id,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "hip_path": str(hip_path),
        "input_mode": package_inputs["mode"],
        "package_version": package_inputs["package_version"],
        "package_dir": str(package_inputs["package_dir"]),
        "package_manifest": str(package_inputs["package_manifest_path"]),
        "houdini_manifest": str(package_inputs["houdini_manifest_path"]),
        "standard_lanes": str(standard_lanes_path),
        "standard_junctions": str(standard_junctions_path),
        "standard_lane_surfaces": str(lane_surface_geojson_path),
        "input_features": stats["feature_count"],
        "input_highway_counts": stats["highway_counts"],
        "input_features_with_lanes": stats["features_with_lanes"],
        "input_features_with_oneway": stats["features_with_oneway"],
        "package_counts": {
            "standard_lanes": stats["standard_lane_count"],
            "standard_roads": stats["standard_road_count"],
            "standard_junctions": stats["standard_junction_count"],
            "standard_surface_features": stats["standard_surface_count"],
            "lane_direction_counts": stats["lane_direction_counts"],
        },
        "houdini": {
            "centerline_prims": len(center_geo.prims()),
            "preview_output_prims": len(out_geo.prims()),
            "preview_output_points": len(out_geo.points()),
            "lane_debug_prims": len(lane_debug_geo.prims()) if lane_debug_geo is not None else 0,
            "lane_debug_points": len(lane_debug_geo.points()) if lane_debug_geo is not None else 0,
            "lane_surface_prims": len(lane_surface_geo.prims()) if lane_surface_geo is not None else 0,
            "lane_surface_points": len(lane_surface_geo.points()) if lane_surface_geo is not None else 0,
            "obj_node": geo.path(),
            "display_node": out_node.path(),
            "lane_debug_node": lane_debug_out.path() if lane_debug_out is not None else "",
            "lane_surface_node": lane_surface_out.path() if lane_surface_out is not None else "",
        },
        "notes": [
            "Houdini cook is manifest-driven and reads only the latest LaneForge package outputs.",
            "The displayed output contains standard lane centerlines from standard_lanes.json.",
            "Lane-level debug geometry is available on OUT_lane_connections_debug but is not the display node.",
            "Lane surface geometry is imported from standard_lane_surfaces.geojson and is available on OUT_lane_surfaces_v1.",
        ],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    hou.hipFile.save(str(hip_path))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build isolated Houdini road test HIP.")
    parser.add_argument("--root", required=True, help="road_test_pipeline root directory")
    parser.add_argument("--config", required=True, help="area config path")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    config_path = Path(args.config).resolve()
    report = build_scene(root=root, config_path=config_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
