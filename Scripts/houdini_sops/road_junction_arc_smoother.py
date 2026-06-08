"""Houdini Python SOP: add tangent-arc samples near road junctions.

Input: centerline primitives after road_graph_filter.
Output: centerline primitives with the same topology and key attributes, but
with extra points near degree>=3 junction endpoints so downstream road surface
builders get smoother approach tangents.

The solver is intentionally conservative:
  * shared junction endpoints are preserved exactly;
  * only the first/last segment near a junction is resampled;
  * roads shorter than the requested arc length are clamped;
  * primitive attributes used by road builders are copied through.
"""
import math

import hou

node = hou.pwd()
geo = node.geometry()
geo.clear()

geo_in = node.inputs()[0].geometry() if node.inputs() else None
if geo_in is None:
    raise hou.NodeError("road_junction_arc_smoother: no input centerlines")

ENABLED = bool(int("__ENABLED__"))
ARC_DISTANCE = max(0.25, float("__ARC_DISTANCE__"))
ARC_SEGMENTS = max(2, int("__ARC_SEGMENTS__"))
JUNCTION_GRID = max(0.05, float("__JUNCTION_GRID__"))
MIN_DEGREE = max(3, int("__MIN_DEGREE__"))
MAX_BEND = max(0.0, min(0.65, float("__MAX_BEND__")))
MAX_APPROACH_FRACTION = max(0.05, min(0.45, float("__MAX_APPROACH_FRACTION__")))

KNOWN_PRIM_ATTRS = (
    ("half_width", 0.0),
    ("road_hw", 0.0),
    ("hw", 0.0),
    ("osm_width", 0.0),
    ("highway", ""),
    ("seg_id", -1),
    ("from_node", ""),
    ("to_node", ""),
)


def ensure_global(name, default):
    attr = geo.findGlobalAttrib(name)
    return attr if attr else geo.addAttrib(hou.attribType.Global, name, default)


def set_global(name, value):
    default = 0.0 if isinstance(value, float) else 0
    if isinstance(value, str):
        default = ""
    ensure_global(name, default)
    geo.setGlobalAttribValue(name, value)


def key_pos(pos):
    return (round(float(pos[0]) / JUNCTION_GRID), round(float(pos[2]) / JUNCTION_GRID))


def v_xz(pos):
    return hou.Vector3(float(pos[0]), 0.0, float(pos[2]))


def length_xz(a, b):
    return (v_xz(a) - v_xz(b)).length()


def norm_xz(vec, fallback=None):
    out = hou.Vector3(float(vec[0]), 0.0, float(vec[2]))
    if out.length() <= 1.0e-7:
        return fallback if fallback is not None else hou.Vector3(1.0, 0.0, 0.0)
    return out.normalized()


def lerp(a, b, t):
    return a + (b - a) * t


def cubic_bezier(p0, c0, c1, p1, t):
    a = lerp(p0, c0, t)
    b = lerp(c0, c1, t)
    c = lerp(c1, p1, t)
    d = lerp(a, b, t)
    e = lerp(b, c, t)
    return lerp(d, e, t)


def poly_length(points):
    total = 0.0
    for idx in range(len(points) - 1):
        total += length_xz(points[idx], points[idx + 1])
    return total


def point_at_distance(points, distance):
    if distance <= 0.0:
        return points[0]
    walked = 0.0
    for idx in range(len(points) - 1):
        p0 = points[idx]
        p1 = points[idx + 1]
        seg_len = length_xz(p0, p1)
        if seg_len <= 1.0e-7:
            continue
        if walked + seg_len >= distance:
            return lerp(p0, p1, (distance - walked) / seg_len)
        walked += seg_len
    return points[-1]


def default_for_attrib(attrib):
    data_type = attrib.dataType()
    size = attrib.size()
    if data_type == hou.attribData.String:
        return ""
    if data_type == hou.attribData.Int:
        return tuple(0 for _ in range(size)) if size > 1 else 0
    return tuple(0.0 for _ in range(size)) if size > 1 else 0.0


def copy_prim_attrs(src_prim, dst_prim, dst_attrs):
    for src_attr in geo_in.primAttribs():
        name = src_attr.name()
        if name not in dst_attrs:
            continue
        try:
            dst_prim.setAttribValue(dst_attrs[name], src_prim.attribValue(src_attr))
        except Exception:
            pass


def append_unique(points, pos, eps=0.03):
    if points and length_xz(points[-1], pos) <= eps:
        return
    points.append(pos)


class Road:
    def __init__(self, prim, points):
        self.prim = prim
        self.points = points
        self.length = poly_length(points)
        self.start_key = key_pos(points[0])
        self.end_key = key_pos(points[-1])

    def endpoint_direction(self, is_start):
        if is_start:
            return norm_xz(self.points[1] - self.points[0])
        return norm_xz(self.points[-2] - self.points[-1])


roads = []
for prim in geo_in.prims():
    vertices = list(prim.vertices())
    if len(vertices) < 2:
        continue
    pts = []
    for vertex in vertices:
        append_unique(pts, vertex.point().position())
    if len(pts) >= 2:
        roads.append(Road(prim, pts))

endpoints = {}
for idx, road in enumerate(roads):
    endpoints.setdefault(road.start_key, []).append((idx, True))
    endpoints.setdefault(road.end_key, []).append((idx, False))

junctions = {key: items for key, items in endpoints.items() if len(items) >= MIN_DEGREE}


def smoothed_endpoint_points(road, is_start, items):
    source_points = road.points if is_start else list(reversed(road.points))
    if road.length <= 0.5 or len(items) < MIN_DEGREE:
        return source_points

    base_dir = road.endpoint_direction(is_start)
    incident_dirs = []
    for other_idx, other_is_start in items:
        other = roads[other_idx]
        incident_dirs.append(other.endpoint_direction(other_is_start))

    left = hou.Vector3(0.0, 0.0, 0.0)
    right = hou.Vector3(0.0, 0.0, 0.0)
    base_angle = math.atan2(base_dir[2], base_dir[0])
    best_left = None
    best_right = None
    for direction in incident_dirs:
        if direction.length() <= 1.0e-7:
            continue
        angle = math.atan2(direction[2], direction[0])
        delta = (angle - base_angle + math.pi) % (math.pi * 2.0) - math.pi
        if delta > 1.0e-5 and (best_left is None or delta < best_left[0]):
            best_left = (delta, direction)
        elif delta < -1.0e-5 and (best_right is None or abs(delta) < best_right[0]):
            best_right = (abs(delta), direction)
    if best_left is not None:
        left = best_left[1]
    if best_right is not None:
        right = best_right[1]

    neighbor_blend = left + right
    if neighbor_blend.length() <= 1.0e-7:
        junction_tangent = base_dir
    else:
        junction_tangent = norm_xz(base_dir * (1.0 - MAX_BEND) + neighbor_blend.normalized() * MAX_BEND, base_dir)

    distance = min(ARC_DISTANCE, road.length * MAX_APPROACH_FRACTION)
    if distance <= 0.25:
        return source_points

    p0 = source_points[0]
    p1 = point_at_distance(source_points, distance)
    handle = distance * 0.38
    c0 = p0 + junction_tangent * handle
    c1 = p1 - base_dir * handle

    rebuilt = [p0]
    for seg in range(1, ARC_SEGMENTS + 1):
        append_unique(rebuilt, cubic_bezier(p0, c0, c1, p1, float(seg) / float(ARC_SEGMENTS)))
    for pos in source_points[1:]:
        if length_xz(pos, p1) > 0.08:
            append_unique(rebuilt, pos)
    return rebuilt


dst_attrs = {}
for src_attr in geo_in.primAttribs():
    dst_attrs[src_attr.name()] = geo.addAttrib(hou.attribType.Prim, src_attr.name(), default_for_attrib(src_attr))

smoothed_roads = 0
inserted_points = 0

for road in roads:
    pts = list(road.points)
    if ENABLED:
        if road.start_key in junctions:
            old_count = len(pts)
            pts = smoothed_endpoint_points(road, True, junctions[road.start_key])
            inserted_points += max(0, len(pts) - old_count)
        if road.end_key in junctions:
            old_count = len(pts)
            reversed_smoothed = smoothed_endpoint_points(
                Road(road.prim, pts), False, junctions[road.end_key]
            )
            pts = list(reversed(reversed_smoothed))
            inserted_points += max(0, len(pts) - old_count)
        if len(pts) != len(road.points):
            smoothed_roads += 1

    poly = geo.createPolygon()
    poly.setIsClosed(False)
    for pos in pts:
        point = geo.createPoint()
        point.setPosition(pos)
        poly.addVertex(point)
    copy_prim_attrs(road.prim, poly, dst_attrs)

set_global("road_junction_arc_smoothing_enabled", int(ENABLED))
set_global("road_junction_arc_junction_count", int(len(junctions)))
set_global("road_junction_arc_smoothed_roads", int(smoothed_roads))
set_global("road_junction_arc_inserted_points", int(inserted_points))
set_global("road_junction_arc_distance", float(ARC_DISTANCE))
set_global("road_junction_arc_segments", int(ARC_SEGMENTS))
