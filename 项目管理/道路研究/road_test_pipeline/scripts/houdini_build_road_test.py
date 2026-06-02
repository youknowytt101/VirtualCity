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
    poly.setAttribValue("vc_part", "road_centerline")
    road_group.add(poly)
'''


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


def junction_radius(item):
    return max(edge["half_width"] for edge in item["edges"]) + 2.0


def build_junction_polygon(item):
    degree = int(item["degree"])
    segments = max(12, min(28, degree * 6))
    return circle_points(item["pos"], junction_radius(item), segments)


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
        segments = max(12, min(24, int(item["degree"]) * 5))
        samples.extend(circle_points(item["pos"], junction_radius(item), segments))
    hull = convex_hull(samples)
    if len(hull) >= 3:
        return hull
    radius = max(junction_radius(item) for item in nodes)
    return circle_points(cluster["pos"], radius, 16)


junction_nodes = defaultdict(lambda: {"pos": None, "count": 0, "degree": 0, "edges": []})
for prim in src.prims():
    points = [v.point().position() for v in prim.vertices()]
    if len(points) < 2:
        continue
    half_width = float(prim_attr(prim, "half_width", 3.0))
    for pos in (points[0], points[-1]):
        item = junction_nodes[pos_key(pos)]
        if item["pos"] is None:
            item["pos"] = hou.Vector3(pos)
        else:
            n = item["count"]
            item["pos"] = (item["pos"] * n + pos) / float(n + 1)
        item["count"] += 1
        item["degree"] += 1
        item["edges"].append({"half_width": half_width})


def trim_for_junctions(p0, p1):
    dx = p1.x() - p0.x()
    dz = p1.z() - p0.z()
    length = math.sqrt(dx * dx + dz * dz)
    if length < 0.05:
        return None

    start_node = junction_nodes.get(pos_key(p0))
    end_node = junction_nodes.get(pos_key(p1))
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
    centerline_group.add(line)
'''


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
    center = cfg["center"]

    repaired_geojson_path = root / "data" / "processed" / f"{area_id}_roads_repaired.geojson"
    raw_geojson_path = root / "data" / "processed" / f"{area_id}_roads_raw.geojson"
    geojson_path = repaired_geojson_path if repaired_geojson_path.exists() else raw_geojson_path
    if not geojson_path.exists():
        raise FileNotFoundError(f"Missing road sample GeoJSON: {geojson_path}")

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

    import_node = create_or_get(geo, "python", "python_import_roads_raw")
    import_node.parm("python").set(
        python_import_code(
            geojson_path=geojson_path,
            origin_lon=float(center["lon"]),
            origin_lat=float(center["lat"]),
        )
    )
    import_node.setDisplayFlag(False)

    center_null = create_or_get(geo, "null", "OUT_centerlines")
    center_null.setInput(0, import_node)
    center_null.setDisplayFlag(False)
    center_null.setRenderFlag(False)

    surface_node = create_or_get(geo, "python", "python_build_preview_surfaces")
    surface_node.setInput(0, import_node)
    surface_node.parm("python").set(python_surface_code())

    centerline_node = create_or_get(geo, "python", "python_centerlines_retained")
    centerline_node.setInput(0, import_node)
    centerline_node.parm("python").set(python_centerline_code())

    junction_node = create_or_get(geo, "python", "python_debug_junction_candidates")
    junction_node.setInput(0, import_node)
    junction_node.parm("python").set(python_junction_debug_code())

    merge_node = create_or_get(geo, "merge", "merge_preview_surface_and_junction_debug")
    merge_node.setInput(0, surface_node)
    merge_node.setInput(1, centerline_node)
    merge_node.setInput(2, junction_node)

    normal_node = create_or_get(geo, "normal", "normal_preview")
    normal_node.setInput(0, merge_node)

    out_node = create_or_get(geo, "null", "OUT_roads_preview")
    out_node.setInput(0, normal_node)
    out_node.setDisplayFlag(True)
    out_node.setRenderFlag(True)

    note = geo.createStickyNote("ROAD_TEST_NOTES")
    note.setText(
        "Isolated road_test_pipeline cook\\n"
        f"Area: {area_id}\\n"
        "Input: data/processed/*_roads_raw.geojson\\n"
        "Output: OUT_roads_preview\\n"
        "This HIP does not touch the main VirtualCity pipeline."
    )
    note.setPosition(hou.Vector2(-3.5, 2.0))

    geo.layoutChildren()
    for node in (import_node, center_null, surface_node, centerline_node, junction_node, merge_node, normal_node, out_node):
        node.cook(force=True)

    stats = load_geojson_stats(geojson_path)
    center_geo = center_null.geometry()
    out_geo = out_node.geometry()
    report = {
        "area_id": area_id,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "hip_path": str(hip_path),
        "geojson_path": str(geojson_path),
        "geojson_mode": "repaired" if geojson_path == repaired_geojson_path else "raw",
        "input_features": stats["feature_count"],
        "input_highway_counts": stats["highway_counts"],
        "input_features_with_lanes": stats["features_with_lanes"],
        "input_features_with_oneway": stats["features_with_oneway"],
        "houdini": {
            "centerline_prims": len(center_geo.prims()),
            "preview_output_prims": len(out_geo.prims()),
            "preview_output_points": len(out_geo.points()),
            "obj_node": geo.path(),
            "display_node": out_node.path(),
        },
        "notes": [
            "Preview surfaces include road segment quads, clustered junction patches and retained road centerline primitives.",
            "python_debug_junction_candidates marks endpoint clusters with degree >= 3 for visual review.",
            "Next research step: add topology_repair and road_graph builder inside road_test_pipeline.",
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
