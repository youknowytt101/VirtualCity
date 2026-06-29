"""Houdini Python SOP: build capsule road surfaces from clean centerlines.

Input: clean road centerlines, preferably after road_profile_apply.
Output: capsule road surface quad strips split by a real center edge, with
round cap triangle fans.

This SOP is wired as the current main road surface output through
road_surface_color, while road_color keeps the fixed centerline chain available
as debug geometry.
"""

import math

import hou


node = hou.pwd()
geo = node.geometry()
geo.clear()

geo_in = node.inputs()[0].geometry() if node.inputs() else None

ENABLED = bool(int("__ENABLED__"))
DEFAULT_WIDTH = max(0.5, float("__DEFAULT_WIDTH__"))
USE_PROFILE_WIDTH = bool(int("__USE_PROFILE_WIDTH__"))
CAP_SEGMENTS = max(4, int("__CAP_SEGMENTS__"))
MIN_SEGMENT_LENGTH = max(0.05, float("__MIN_SEGMENT_LENGTH__"))
WIDTH_SCALE = max(0.01, float("__WIDTH_SCALE__"))
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


def v3(x, y, z):
    return hou.Vector3(float(x), float(y), float(z))


def length_xz(a, b):
    return math.hypot(float(b[0]) - float(a[0]), float(b[2]) - float(a[2]))


def vec_xz(a, b):
    return float(b[0]) - float(a[0]), float(b[2]) - float(a[2])


def normalize_xz(dx, dz):
    length = math.hypot(dx, dz)
    if length <= EPS:
        return None
    return dx / length, dz / length


def dot2(a, b):
    return a[0] * b[0] + a[1] * b[1]


def angle_of(direction):
    return math.atan2(direction[1], direction[0])


def append_unique(points, pos, eps=0.01):
    if points and length_xz(points[-1], pos) <= eps:
        return
    points.append(pos)


def clean_points(prim):
    out = []
    for vertex in prim.vertices():
        pos = vertex.point().position()
        if out and length_xz(out[-1], pos) <= MIN_SEGMENT_LENGTH:
            continue
        out.append(pos)
    return out


def copy_prim_attrs(src_prim, dst_prim, dst_attrs):
    for src_attr in geo_in.primAttribs():
        name = src_attr.name()
        if name not in dst_attrs:
            continue
        try:
            dst_prim.setAttribValue(dst_attrs[name], src_prim.attribValue(src_attr))
        except Exception:
            pass


def prim_float(prim, name, default=0.0):
    try:
        if prim.geometry().findPrimAttrib(name):
            return float(prim.attribValue(name))
    except Exception:
        pass
    return default


def prim_int(prim, name, default=0):
    try:
        if prim.geometry().findPrimAttrib(name):
            return int(prim.attribValue(name))
    except Exception:
        pass
    return default


def profile_width(prim):
    lane_num = max(0, prim_int(prim, "lane_num", 0))
    lane_width = max(0.0, prim_float(prim, "lane_width", 0.0))
    median_w = max(0.0, prim_float(prim, "median_w", 0.0))
    if lane_num > 0 and lane_width > 0.0:
        return lane_num * lane_width + median_w
    for attr_name in ("width", "osm_width", "road_width"):
        width = prim_float(prim, attr_name, 0.0)
        if width > 0.0:
            return width
    return DEFAULT_WIDTH


def capsule_width(prim):
    width = profile_width(prim) if USE_PROFILE_WIDTH else DEFAULT_WIDTH
    return max(0.5, width * WIDTH_SCALE)


def vertex_tangent(points, idx):
    if idx == 0:
        return normalize_xz(*vec_xz(points[0], points[1]))
    if idx == len(points) - 1:
        return normalize_xz(*vec_xz(points[-2], points[-1]))
    prev_dir = normalize_xz(*vec_xz(points[idx - 1], points[idx]))
    next_dir = normalize_xz(*vec_xz(points[idx], points[idx + 1]))
    if prev_dir is None:
        return next_dir
    if next_dir is None:
        return prev_dir
    mixed = normalize_xz(prev_dir[0] + next_dir[0], prev_dir[1] + next_dir[1])
    return mixed or next_dir


def normal_from_tangent(tangent):
    if tangent is None:
        return None
    return -tangent[1], tangent[0]


def offset_point(pos, normal, radius, side):
    return v3(
        float(pos[0]) + normal[0] * radius * side,
        float(pos[1]),
        float(pos[2]) + normal[1] * radius * side,
    )


def cap_points(center, radius, start_angle, end_angle, segments):
    out = []
    for step in range(segments + 1):
        t = float(step) / float(segments)
        angle = start_angle + (end_angle - start_angle) * t
        out.append(v3(
            float(center[0]) + math.cos(angle) * radius,
            float(center[1]),
            float(center[2]) + math.sin(angle) * radius,
        ))
    return out


def capsule_rings(points, radius):
    if len(points) < 2 or radius <= EPS:
        return None

    left = []
    center = []
    right = []
    tangents = []
    for idx, pos in enumerate(points):
        tangent = vertex_tangent(points, idx)
        normal = normal_from_tangent(tangent)
        if tangent is None or normal is None:
            continue
        tangents.append(tangent)
        append_unique(center, pos, eps=0.01)
        append_unique(left, offset_point(pos, normal, radius, 1.0), eps=0.01)
        append_unique(right, offset_point(pos, normal, radius, -1.0), eps=0.01)

    if len(left) < 2 or len(center) < 2 or len(right) < 2:
        return None
    if len(left) != len(center) or len(left) != len(right) or len(left) != len(tangents):
        return None

    start_tangent = tangents[0]
    end_tangent = tangents[-1]
    start_angle = angle_of((-start_tangent[0], -start_tangent[1]))
    end_angle = angle_of(end_tangent)

    end_cap = cap_points(
        points[-1], radius, end_angle + math.pi * 0.5, end_angle - math.pi * 0.5, CAP_SEGMENTS
    )
    start_cap = cap_points(
        points[0], radius, start_angle + math.pi * 0.5, start_angle - math.pi * 0.5, CAP_SEGMENTS
    )
    end_cap[0] = left[-1]
    end_cap[-1] = right[-1]
    start_cap[0] = right[0]
    start_cap[-1] = left[0]
    return {
        "left": left,
        "center": center,
        "right": right,
        "start_cap": start_cap,
        "end_cap": end_cap,
    }


def set_surface_attrs(poly, src_prim, dst_attrs, preview_attr, role_attr, source_attr, width_attr, piece_attr, width, piece):
    copy_prim_attrs(src_prim, poly, dst_attrs)
    poly.setAttribValue(preview_attr, 1)
    poly.setAttribValue(role_attr, "surface")
    poly.setAttribValue(source_attr, int(src_prim.number()))
    poly.setAttribValue(width_attr, float(width))
    poly.setAttribValue(piece_attr, piece)


def orient2(a, b, c):
    return (
        (float(b[0]) - float(a[0])) * (float(c[2]) - float(a[2]))
        - (float(b[2]) - float(a[2])) * (float(c[0]) - float(a[0]))
    )


def polygon_area_xz(points):
    area = 0.0
    for idx, pos in enumerate(points):
        nxt = points[(idx + 1) % len(points)]
        area += float(pos[0]) * float(nxt[2]) - float(nxt[0]) * float(pos[2])
    return area * 0.5


def quad_is_valid(points):
    if len(points) != 4 or abs(polygon_area_xz(points)) <= 1.0e-6:
        return False
    signs = []
    for idx in range(4):
        cross = orient2(points[idx], points[(idx + 1) % 4], points[(idx + 2) % 4])
        if abs(cross) > 1.0e-6:
            signs.append(1 if cross > 0.0 else -1)
    if len(signs) < 3:
        return False
    return all(sign == signs[0] for sign in signs)


def passthrough(status, fallbacks=0, message=""):
    geo.clear()
    if geo_in is not None:
        geo.merge(geo_in)
    set_global("road_capsule_surface_preview_status", status)
    set_global("road_capsule_surface_preview_enabled", int(ENABLED))
    set_global("road_capsule_surface_preview_surface_prims", 0)
    set_global("road_capsule_surface_preview_centerline_guides", 0)
    set_global("road_capsule_surface_preview_fallbacks", int(fallbacks))
    if message:
        set_global("road_capsule_surface_preview_message", str(message)[:240])


if geo_in is None:
    passthrough("missing_input", 1)
elif not ENABLED:
    passthrough("disabled", 0)
else:
    try:
        dst_attrs = {}
        for src_attr in geo_in.primAttribs():
            dst_attrs[src_attr.name()] = geo.findPrimAttrib(src_attr.name()) or geo.addAttrib(
                hou.attribType.Prim, src_attr.name(), default_for_attrib(src_attr)
            )

        preview_attr = geo.findPrimAttrib("road_capsule_preview") or geo.addAttrib(
            hou.attribType.Prim, "road_capsule_preview", 0
        )
        role_attr = geo.findPrimAttrib("road_capsule_role") or geo.addAttrib(
            hou.attribType.Prim, "road_capsule_role", ""
        )
        source_attr = geo.findPrimAttrib("road_capsule_source_prim") or geo.addAttrib(
            hou.attribType.Prim, "road_capsule_source_prim", -1
        )
        width_attr = geo.findPrimAttrib("road_capsule_width") or geo.addAttrib(
            hou.attribType.Prim, "road_capsule_width", 0.0
        )
        piece_attr = geo.findPrimAttrib("road_capsule_piece") or geo.addAttrib(
            hou.attribType.Prim, "road_capsule_piece", ""
        )

        surface_group = geo.createPrimGroup("road_capsule_surface_preview")
        surface_prims = 0
        skipped_prims = 0
        body_quads = 0
        center_split_quads = 0
        cap_triangles = 0
        skipped_self_intersecting_quads = 0
        output_point_by_key = {}

        def point_key(pos):
            return (
                round(float(pos[0]) / 0.001),
                round(float(pos[1]) / 0.001),
                round(float(pos[2]) / 0.001),
            )

        def shared_point(pos):
            key = point_key(pos)
            point = output_point_by_key.get(key)
            if point is not None and length_xz(point.position(), pos) <= 0.001:
                return point
            point = geo.createPoint()
            point.setPosition(pos)
            output_point_by_key[key] = point
            return point

        for src_prim in geo_in.prims():
            points = clean_points(src_prim)
            if len(points) < 2:
                skipped_prims += 1
                continue
            width = capsule_width(src_prim)
            radius = width * 0.5
            rings = capsule_rings(points, radius)
            if rings:
                left = rings["left"]
                center = rings["center"]
                right = rings["right"]
                for idx in range(len(left) - 1):
                    if (
                        length_xz(left[idx], left[idx + 1]) <= EPS
                        or length_xz(center[idx], center[idx + 1]) <= EPS
                        or length_xz(right[idx], right[idx + 1]) <= EPS
                    ):
                        continue
                    for piece, quad_points in (
                        ("left_quad", (left[idx], left[idx + 1], center[idx + 1], center[idx])),
                        ("right_quad", (center[idx], center[idx + 1], right[idx + 1], right[idx])),
                    ):
                        if not quad_is_valid(quad_points):
                            skipped_self_intersecting_quads += 1
                            continue
                        poly = geo.createPolygon()
                        poly.setIsClosed(True)
                        # H-002: 在已 z 翻转的 Houdini 帧 (x,0,-z) 里按此顺序造面法线朝下，
                        # 反绕使法线朝上，与地形/建筑一致（见 vc_geo.needs_winding_flip）。
                        for pos in reversed(quad_points):
                            poly.addVertex(shared_point(pos))
                        set_surface_attrs(
                            poly, src_prim, dst_attrs, preview_attr, role_attr, source_attr,
                            width_attr, piece_attr, width, piece
                        )
                        surface_group.add(poly)
                        surface_prims += 1
                        body_quads += 1
                        center_split_quads += 1

                for cap_name, cap_center in (("start_cap", points[0]), ("end_cap", points[-1])):
                    cap = rings[cap_name]
                    for idx in range(len(cap) - 1):
                        if length_xz(cap[idx], cap[idx + 1]) <= EPS:
                            continue
                        poly = geo.createPolygon()
                        poly.setIsClosed(True)
                        # H-002: 同上，反绕端盖三角使法线朝上。
                        for pos in (cap[idx + 1], cap[idx], cap_center):
                            poly.addVertex(shared_point(pos))
                        set_surface_attrs(
                            poly, src_prim, dst_attrs, preview_attr, role_attr, source_attr,
                            width_attr, piece_attr, width, cap_name
                        )
                        surface_group.add(poly)
                        surface_prims += 1
                        cap_triangles += 1
            else:
                skipped_prims += 1

        set_global("road_capsule_surface_preview_status", "preview")
        set_global("road_capsule_surface_preview_enabled", int(ENABLED))
        set_global("road_capsule_surface_preview_surface_prims", int(surface_prims))
        set_global("road_capsule_surface_preview_body_quads", int(body_quads))
        set_global("road_capsule_surface_preview_center_split_quads", int(center_split_quads))
        set_global("road_capsule_surface_preview_cap_triangles", int(cap_triangles))
        set_global("road_capsule_surface_preview_skipped_self_intersecting_quads", int(skipped_self_intersecting_quads))
        set_global("road_capsule_surface_preview_centerline_guides", 0)
        set_global("road_capsule_surface_preview_skipped_prims", int(skipped_prims))
        set_global("road_capsule_surface_preview_default_width", float(DEFAULT_WIDTH))
        set_global("road_capsule_surface_preview_use_profile_width", int(USE_PROFILE_WIDTH))
        set_global("road_capsule_surface_preview_cap_segments", int(CAP_SEGMENTS))
        set_global("road_capsule_surface_preview_fallbacks", 0)
    except Exception as exc:
        passthrough("fallback", 1, "{}: {}".format(type(exc).__name__, exc))
