"""Houdini Python SOP: create shared points for road centerline topology.

Input: road centerline primitives, ideally right after extract_roads.
Output: road centerlines with shared points at fused vertices and segment
intersections.

The node is intentionally conservative:
  * primitive attributes and road groups are copied through;
  * nearby endpoints/vertices reuse one Houdini point;
  * crossing line segments are split at the intersection and share that point;
  * unsupported dense inputs or runtime errors pass through unchanged.
"""

import math

import hou


node = hou.pwd()
geo = node.geometry()
geo.clear()

geo_in = node.inputs()[0].geometry() if node.inputs() else None

ENABLED = bool(int("__ENABLED__"))
FUSE_TOLERANCE = max(0.01, float("__FUSE_TOLERANCE__"))
INTERSECTION_TOLERANCE = max(0.005, float("__INTERSECTION_TOLERANCE__"))
MAX_SEGMENTS = max(100, int("__MAX_SEGMENTS__"))
EPS = 1.0e-8


def default_for_attrib(attrib):
    data_type = attrib.dataType()
    size = attrib.size()
    if data_type == hou.attribData.String:
        return "" if size <= 1 else tuple("" for _ in range(size))
    if data_type == hou.attribData.Int:
        return 0 if size <= 1 else tuple(0 for _ in range(size))
    return 0.0 if size <= 1 else tuple(0.0 for _ in range(size))


def ensure_global(name, default):
    attr = geo.findGlobalAttrib(name)
    return attr if attr else geo.addAttrib(hou.attribType.Global, name, default)


def set_global(name, value):
    default = 0.0 if isinstance(value, float) else 0
    if isinstance(value, str):
        default = ""
    ensure_global(name, default)
    geo.setGlobalAttribValue(name, value)


def length_xz(a, b):
    return math.hypot(float(b[0]) - float(a[0]), float(b[2]) - float(a[2]))


def lerp(a, b, t):
    return a + (b - a) * t


def append_unique(points, pos, eps=0.01):
    if points and length_xz(points[-1], pos) <= eps:
        return
    points.append(pos)


def clean_positions(prim):
    out = []
    for vertex in prim.vertices():
        append_unique(out, vertex.point().position(), eps=EPS)
    return out


def point_key(pos):
    return (
        round(float(pos[0]) / FUSE_TOLERANCE),
        round(float(pos[2]) / FUSE_TOLERANCE),
    )


def canonical_position(pos):
    return hou.Vector3(float(pos[0]), float(pos[1]), float(pos[2]))


def segment_intersection_xz(a0, a1, b0, b1):
    ax = float(a0[0])
    az = float(a0[2])
    bx = float(b0[0])
    bz = float(b0[2])
    rx = float(a1[0]) - ax
    rz = float(a1[2]) - az
    sx = float(b1[0]) - bx
    sz = float(b1[2]) - bz
    denom = rx * sz - rz * sx
    if abs(denom) <= EPS:
        return None
    qpx = bx - ax
    qpz = bz - az
    t = (qpx * sz - qpz * sx) / denom
    u = (qpx * rz - qpz * rx) / denom
    slack = 0.001
    if t < -slack or t > 1.0 + slack or u < -slack or u > 1.0 + slack:
        return None
    t = max(0.0, min(1.0, t))
    u = max(0.0, min(1.0, u))
    pos_a = lerp(a0, a1, t)
    pos_b = lerp(b0, b1, u)
    return t, u, hou.Vector3(
        (float(pos_a[0]) + float(pos_b[0])) * 0.5,
        (float(pos_a[1]) + float(pos_b[1])) * 0.5,
        (float(pos_a[2]) + float(pos_b[2])) * 0.5,
    )


def point_segment_projection_xz(pos, a, b):
    ax = float(a[0])
    az = float(a[2])
    bx = float(b[0])
    bz = float(b[2])
    px = float(pos[0])
    pz = float(pos[2])
    dx = bx - ax
    dz = bz - az
    denom = dx * dx + dz * dz
    if denom <= EPS:
        return None
    t = ((px - ax) * dx + (pz - az) * dz) / denom
    if t < -0.01 or t > 1.01:
        return None
    t = max(0.0, min(1.0, t))
    projected = lerp(a, b, t)
    if length_xz(pos, projected) > INTERSECTION_TOLERANCE:
        return None
    return t, projected


def add_split(split_map, road_idx, seg_idx, t_value, pos):
    key = (road_idx, seg_idx)
    split_map.setdefault(key, []).append((max(0.0, min(1.0, t_value)), canonical_position(pos)))


def copy_global_attrs():
    if geo_in is None:
        return
    for src_attr in geo_in.globalAttribs():
        name = src_attr.name()
        if name == "P":
            continue
        try:
            dst_attr = geo.findGlobalAttrib(name) or geo.addAttrib(
                hou.attribType.Global, name, default_for_attrib(src_attr)
            )
            geo.setGlobalAttribValue(dst_attr, geo_in.attribValue(name))
        except Exception:
            pass


def copy_prim_attrs(src_prim, dst_prim, dst_attrs):
    for src_attr in geo_in.primAttribs():
        name = src_attr.name()
        if name not in dst_attrs:
            continue
        try:
            dst_prim.setAttribValue(dst_attrs[name], src_prim.attribValue(src_attr))
        except Exception:
            pass


def passthrough(status, fallbacks=0, message=""):
    geo.clear()
    if geo_in is not None:
        geo.merge(geo_in)
    set_global("road_shared_topology_status", status)
    set_global("road_shared_topology_enabled", int(ENABLED))
    set_global("road_shared_topology_source_prims", int(geo_in.intrinsicValue("primitivecount")) if geo_in else 0)
    set_global("road_shared_topology_output_prims", int(geo.intrinsicValue("primitivecount")))
    set_global("road_shared_topology_source_points", int(geo_in.intrinsicValue("pointcount")) if geo_in else 0)
    set_global("road_shared_topology_output_points", int(geo.intrinsicValue("pointcount")))
    set_global("road_shared_topology_intersections", 0)
    set_global("road_shared_topology_endpoint_splits", 0)
    set_global("road_shared_topology_split_segments", 0)
    set_global("road_shared_topology_fused_points", 0)
    set_global("road_shared_topology_fallbacks", int(fallbacks))
    if message:
        set_global("road_shared_topology_message", str(message)[:240])


if geo_in is None:
    passthrough("missing_input", 1)
elif not ENABLED:
    passthrough("disabled", 0)
else:
    try:
        roads = []
        for prim in geo_in.prims():
            pts = clean_positions(prim)
            if len(pts) >= 2:
                roads.append((prim, pts))

        segments = []
        for road_idx, (_prim, pts) in enumerate(roads):
            for seg_idx in range(len(pts) - 1):
                p0 = pts[seg_idx]
                p1 = pts[seg_idx + 1]
                if length_xz(p0, p1) <= EPS:
                    continue
                segments.append((
                    road_idx,
                    seg_idx,
                    p0,
                    p1,
                    min(float(p0[0]), float(p1[0])) - INTERSECTION_TOLERANCE,
                    max(float(p0[0]), float(p1[0])) + INTERSECTION_TOLERANCE,
                    min(float(p0[2]), float(p1[2])) - INTERSECTION_TOLERANCE,
                    max(float(p0[2]), float(p1[2])) + INTERSECTION_TOLERANCE,
                ))

        if len(segments) > MAX_SEGMENTS:
            passthrough("too_many_segments", 1, "segments={} > max={}".format(len(segments), MAX_SEGMENTS))
        else:
            split_map = {}
            intersections = 0
            endpoint_splits = 0

            for road_idx, (_prim, pts) in enumerate(roads):
                for seg_idx in range(len(pts) - 1):
                    add_split(split_map, road_idx, seg_idx, 0.0, pts[seg_idx])
                    add_split(split_map, road_idx, seg_idx, 1.0, pts[seg_idx + 1])

            for i in range(len(segments)):
                ai, asi, a0, a1, aminx, amaxx, aminz, amaxz = segments[i]
                for j in range(i + 1, len(segments)):
                    bi, bsi, b0, b1, bminx, bmaxx, bminz, bmaxz = segments[j]
                    if ai == bi and abs(asi - bsi) <= 1:
                        continue
                    if amaxx < bminx or bmaxx < aminx or amaxz < bminz or bmaxz < aminz:
                        continue
                    hit = segment_intersection_xz(a0, a1, b0, b1)
                    if hit is None:
                        continue
                    ta, tb, pos = hit
                    # Existing shared endpoints are already handled by point reuse.
                    if (ta <= 0.001 or ta >= 0.999) and (tb <= 0.001 or tb >= 0.999):
                        continue
                    add_split(split_map, ai, asi, ta, pos)
                    add_split(split_map, bi, bsi, tb, pos)
                    intersections += 1

            # Also split a segment when another road vertex lands on it.
            for road_idx, (_prim, pts) in enumerate(roads):
                for pos in pts:
                    for si, ssi, s0, s1, smnx, smxx, smnz, smxz in segments:
                        if si == road_idx:
                            continue
                        if float(pos[0]) < smnx or float(pos[0]) > smxx or float(pos[2]) < smnz or float(pos[2]) > smxz:
                            continue
                        projected = point_segment_projection_xz(pos, s0, s1)
                        if projected is None:
                            continue
                        t, projected_pos = projected
                        if t <= 0.001 or t >= 0.999:
                            continue
                        add_split(split_map, si, ssi, t, projected_pos)
                        endpoint_splits += 1

            copy_global_attrs()
            dst_attrs = {}
            for src_attr in geo_in.primAttribs():
                dst_attrs[src_attr.name()] = geo.findPrimAttrib(src_attr.name()) or geo.addAttrib(
                    hou.attribType.Prim, src_attr.name(), default_for_attrib(src_attr)
                )

            group_members = {}
            dst_groups = {}
            for group in geo_in.primGroups():
                try:
                    group_members[group.name()] = set(prim.number() for prim in group.prims())
                    dst_groups[group.name()] = geo.createPrimGroup(group.name())
                except Exception:
                    pass

            point_by_key = {}
            split_segments = 0

            def shared_point(pos):
                key = point_key(pos)
                point = point_by_key.get(key)
                if point is not None:
                    return point
                point = geo.createPoint()
                point.setPosition(canonical_position(pos))
                point_by_key[key] = point
                return point

            for road_idx, (src_prim, pts) in enumerate(roads):
                rebuilt = []
                for seg_idx in range(len(pts) - 1):
                    items = split_map.get((road_idx, seg_idx), [(0.0, pts[seg_idx]), (1.0, pts[seg_idx + 1])])
                    dedup = []
                    for t_value, pos in sorted(items, key=lambda item: item[0]):
                        if dedup and abs(dedup[-1][0] - t_value) <= 0.001:
                            continue
                        dedup.append((t_value, pos))
                    if len(dedup) > 2:
                        split_segments += 1
                    for _t, pos in dedup:
                        append_unique(rebuilt, pos, eps=FUSE_TOLERANCE * 0.5)

                if len(rebuilt) < 2:
                    continue
                poly = geo.createPolygon()
                poly.setIsClosed(False)
                for pos in rebuilt:
                    poly.addVertex(shared_point(pos))
                copy_prim_attrs(src_prim, poly, dst_attrs)
                for name, members in group_members.items():
                    if src_prim.number() in members and name in dst_groups:
                        try:
                            dst_groups[name].add(poly)
                        except Exception:
                            pass

            set_global("road_shared_topology_status", "shared")
            set_global("road_shared_topology_enabled", int(ENABLED))
            set_global("road_shared_topology_source_prims", int(len(roads)))
            set_global("road_shared_topology_output_prims", int(geo.intrinsicValue("primitivecount")))
            set_global("road_shared_topology_source_points", int(geo_in.intrinsicValue("pointcount")))
            set_global("road_shared_topology_output_points", int(geo.intrinsicValue("pointcount")))
            set_global("road_shared_topology_intersections", int(intersections))
            set_global("road_shared_topology_endpoint_splits", int(endpoint_splits))
            set_global("road_shared_topology_split_segments", int(split_segments))
            set_global("road_shared_topology_fused_points", int(max(0, geo_in.intrinsicValue("pointcount") - geo.intrinsicValue("pointcount"))))
            set_global("road_shared_topology_fallbacks", 0)
    except Exception as exc:
        passthrough("fallback", 1, "{}: {}".format(type(exc).__name__, exc))
