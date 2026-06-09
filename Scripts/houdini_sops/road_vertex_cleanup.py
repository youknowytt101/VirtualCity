"""Houdini Python SOP: clean and even out road centerline vertices.

Input: road centerlines after road_turn_curve_smooth.
Output: centerlines with more uniform vertex spacing and reused shared points.

This node is deliberately geometric housekeeping only. It does not create new
turn or junction arcs; it resamples spans between protected anchors and reuses
nearby output points so junction/shared locations do not accumulate duplicates.
"""

import math

import hou


node = hou.pwd()
geo = node.geometry()
geo.clear()

geo_in = node.inputs()[0].geometry() if node.inputs() else None

ENABLED = bool(int("__ENABLED__"))
TARGET_SPACING = max(0.25, float("__TARGET_SPACING__"))
MIN_SPACING = max(0.01, min(TARGET_SPACING, float("__MIN_SPACING__")))
ANCHOR_ANGLE_DEG = max(1.0, min(179.0, float("__ANCHOR_ANGLE_DEG__")))
REUSE_TOLERANCE = max(0.001, float("__REUSE_TOLERANCE__"))
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


def vec_xz(a, b):
    return float(b[0]) - float(a[0]), float(b[2]) - float(a[2])


def normalize_xz(dx, dz):
    length = math.hypot(dx, dz)
    if length <= EPS:
        return None
    return dx / length, dz / length


def dot2(a, b):
    return a[0] * b[0] + a[1] * b[1]


def lerp(a, b, t):
    return a + (b - a) * t


def turn_angle_deg(prev_pos, pos, next_pos):
    tangent_in = normalize_xz(*vec_xz(prev_pos, pos))
    tangent_out = normalize_xz(*vec_xz(pos, next_pos))
    if tangent_in is None or tangent_out is None:
        return 0.0
    dot = max(-1.0, min(1.0, dot2(tangent_in, tangent_out)))
    return math.degrees(math.acos(dot))


def append_unique(items, item, eps=0.01):
    if items and length_xz(items[-1][0], item[0]) <= eps:
        if items[-1][1] is None and item[1] is not None:
            items[-1] = item
        return
    items.append(item)


def clean_refs(prim):
    refs = []
    for vertex in prim.vertices():
        point = vertex.point()
        pos = point.position()
        if refs and length_xz(refs[-1][1], pos) <= EPS:
            continue
        refs.append((point.number(), pos))
    return refs


def cumulative_lengths(points):
    distances = [0.0]
    total = 0.0
    max_seg = 0.0
    min_seg = None
    close_segments = 0
    for idx in range(len(points) - 1):
        seg_len = length_xz(points[idx], points[idx + 1])
        total += seg_len
        max_seg = max(max_seg, seg_len)
        if seg_len > EPS:
            min_seg = seg_len if min_seg is None else min(min_seg, seg_len)
            if seg_len < MIN_SPACING:
                close_segments += 1
        distances.append(total)
    return distances, total, max_seg, (min_seg or 0.0), close_segments


def point_at_distance(points, distances, distance):
    if distance <= 0.0:
        return points[0]
    total = distances[-1]
    if distance >= total:
        return points[-1]
    for idx in range(len(points) - 1):
        d0 = distances[idx]
        d1 = distances[idx + 1]
        if d1 <= d0 + EPS:
            continue
        if distance <= d1 + EPS:
            return lerp(points[idx], points[idx + 1], (distance - d0) / (d1 - d0))
    return points[-1]


def append_distance(distances, value, point_number=None, eps=0.01):
    if distances and abs(distances[-1][0] - value) <= eps:
        if distances[-1][1] is None and point_number is not None:
            distances[-1] = (distances[-1][0], point_number)
        return
    distances.append((value, point_number))


def shared_point_numbers():
    counts = {}
    for prim in geo_in.prims():
        seen = set()
        for vertex in prim.vertices():
            try:
                seen.add(vertex.point().number())
            except Exception:
                pass
        for point_number in seen:
            counts[point_number] = counts.get(point_number, 0) + 1
    return {point_number for point_number, count in counts.items() if count > 1}


def resample_refs(refs, shared_numbers):
    if len(refs) < 2:
        return [(pos, number if number in shared_numbers else None) for number, pos in refs], 0, 0

    point_numbers = [number for number, _pos in refs]
    points = [pos for _number, pos in refs]
    distances, total, _max_before, _min_before, _close_before = cumulative_lengths(points)
    if total <= EPS:
        return [(points[0], point_numbers[0] if point_numbers[0] in shared_numbers else None)], 0, 0

    anchors = []
    preserved_shared = 0
    preserved_angles = 0
    for idx, point_number in enumerate(point_numbers):
        keep_point_number = point_number if point_number in shared_numbers else None
        is_endpoint = idx == 0 or idx == len(point_numbers) - 1
        is_shared = keep_point_number is not None
        is_angle = (
            not is_endpoint
            and turn_angle_deg(points[idx - 1], points[idx], points[idx + 1]) >= ANCHOR_ANGLE_DEG
        )
        if is_endpoint or is_shared or is_angle:
            append_distance(anchors, distances[idx], keep_point_number)
        if is_shared:
            preserved_shared += 1
        if is_angle:
            preserved_angles += 1

    if not anchors:
        append_distance(anchors, 0.0, None)
        append_distance(anchors, total, None)

    sample_distances = []
    for idx in range(len(anchors) - 1):
        start, start_point_number = anchors[idx]
        end, _end_point_number = anchors[idx + 1]
        span = end - start
        if span <= EPS:
            continue
        pieces = max(1, int(math.ceil(span / TARGET_SPACING)))
        for step in range(pieces):
            point_number = start_point_number if step == 0 else None
            append_distance(sample_distances, start + span * (float(step) / float(pieces)), point_number)
    append_distance(sample_distances, anchors[-1][0], anchors[-1][1])

    out = []
    for distance, point_number in sample_distances:
        append_unique(out, (point_at_distance(points, distances, distance), point_number), eps=MIN_SPACING * 0.5)
    return out, preserved_shared, preserved_angles


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


def point_key(pos):
    return (
        round(float(pos[0]) / REUSE_TOLERANCE),
        round(float(pos[2]) / REUSE_TOLERANCE),
    )


def neighbor_keys(key):
    for dx in (-1, 0, 1):
        for dz in (-1, 0, 1):
            yield key[0] + dx, key[1] + dz


def passthrough(status, fallbacks=0, message=""):
    geo.clear()
    if geo_in is not None:
        geo.merge(geo_in)
    set_global("road_vertex_cleanup_status", status)
    set_global("road_vertex_cleanup_enabled", int(ENABLED))
    set_global("road_vertex_cleanup_target_spacing", float(TARGET_SPACING))
    set_global("road_vertex_cleanup_min_spacing", float(MIN_SPACING))
    set_global("road_vertex_cleanup_input_points", int(geo_in.intrinsicValue("pointcount")) if geo_in else 0)
    set_global("road_vertex_cleanup_output_points", int(geo.intrinsicValue("pointcount")))
    set_global("road_vertex_cleanup_removed_points", 0)
    set_global("road_vertex_cleanup_close_segments_before", 0)
    set_global("road_vertex_cleanup_close_segments_after", 0)
    set_global("road_vertex_cleanup_fallbacks", int(fallbacks))
    if message:
        set_global("road_vertex_cleanup_message", str(message)[:240])


if geo_in is None:
    passthrough("missing_input", 1)
elif not ENABLED:
    passthrough("disabled", 0)
else:
    try:
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

        shared_numbers = shared_point_numbers()
        output_point_by_number = {}
        output_points_by_key = {}
        reuse_stats = {"shared": 0, "spatial": 0}

        def shared_point(pos, source_point_number=None):
            if source_point_number is not None:
                existing = output_point_by_number.get(source_point_number)
                if existing is not None:
                    reuse_stats["shared"] += 1
                    return existing
            key = point_key(pos)
            for near_key in neighbor_keys(key):
                for existing in output_points_by_key.get(near_key, ()):
                    if length_xz(existing.position(), pos) <= REUSE_TOLERANCE:
                        if source_point_number is not None:
                            output_point_by_number[source_point_number] = existing
                        reuse_stats["spatial"] += 1
                        return existing
            point = geo.createPoint()
            point.setPosition(pos)
            output_points_by_key.setdefault(key, []).append(point)
            if source_point_number is not None:
                output_point_by_number[source_point_number] = point
            return point

        input_points = int(geo_in.intrinsicValue("pointcount"))
        input_prims = int(geo_in.intrinsicValue("primitivecount"))
        close_before_total = 0
        close_after_total = 0
        max_before = 0.0
        max_after = 0.0
        min_before = 0.0
        min_after = 0.0
        preserved_shared_total = 0
        preserved_angles_total = 0

        for src_prim in geo_in.prims():
            refs = clean_refs(src_prim)
            if len(refs) < 2:
                continue
            points_before = [pos for _number, pos in refs]
            _dist_before, _total_before, prim_max_before, prim_min_before, close_before = cumulative_lengths(points_before)
            resampled, preserved_shared, preserved_angles = resample_refs(refs, shared_numbers)
            points_after = [pos for pos, _point_number in resampled]
            _dist_after, _total_after, prim_max_after, prim_min_after, close_after = cumulative_lengths(points_after)
            max_before = max(max_before, prim_max_before)
            max_after = max(max_after, prim_max_after)
            if prim_min_before > EPS:
                min_before = prim_min_before if min_before <= EPS else min(min_before, prim_min_before)
            if prim_min_after > EPS:
                min_after = prim_min_after if min_after <= EPS else min(min_after, prim_min_after)
            close_before_total += close_before
            close_after_total += close_after
            preserved_shared_total += preserved_shared
            preserved_angles_total += preserved_angles

            if len(resampled) < 2:
                continue
            poly = geo.createPolygon()
            poly.setIsClosed(False)
            for pos, point_number in resampled:
                poly.addVertex(shared_point(pos, point_number))
            copy_prim_attrs(src_prim, poly, dst_attrs)
            for name, members in group_members.items():
                if src_prim.number() in members and name in dst_groups:
                    try:
                        dst_groups[name].add(poly)
                    except Exception:
                        pass

        output_points = int(geo.intrinsicValue("pointcount"))
        set_global("road_vertex_cleanup_status", "cleaned")
        set_global("road_vertex_cleanup_enabled", int(ENABLED))
        set_global("road_vertex_cleanup_target_spacing", float(TARGET_SPACING))
        set_global("road_vertex_cleanup_min_spacing", float(MIN_SPACING))
        set_global("road_vertex_cleanup_anchor_angle_deg", float(ANCHOR_ANGLE_DEG))
        set_global("road_vertex_cleanup_input_points", int(input_points))
        set_global("road_vertex_cleanup_input_prims", int(input_prims))
        set_global("road_vertex_cleanup_output_points", int(output_points))
        set_global("road_vertex_cleanup_output_prims", int(geo.intrinsicValue("primitivecount")))
        set_global("road_vertex_cleanup_removed_points", int(max(0, input_points - output_points)))
        set_global("road_vertex_cleanup_close_segments_before", int(close_before_total))
        set_global("road_vertex_cleanup_close_segments_after", int(close_after_total))
        set_global("road_vertex_cleanup_max_segment_before", float(max_before))
        set_global("road_vertex_cleanup_max_segment_after", float(max_after))
        set_global("road_vertex_cleanup_min_segment_before", float(min_before))
        set_global("road_vertex_cleanup_min_segment_after", float(min_after))
        set_global("road_vertex_cleanup_preserved_shared_points", int(preserved_shared_total))
        set_global("road_vertex_cleanup_preserved_angle_points", int(preserved_angles_total))
        set_global("road_vertex_cleanup_reused_shared_points", int(reuse_stats["shared"]))
        set_global("road_vertex_cleanup_reused_spatial_points", int(reuse_stats["spatial"]))
        set_global("road_vertex_cleanup_fallbacks", 0)
    except Exception as exc:
        passthrough("fallback", 1, "{}: {}".format(type(exc).__name__, exc))
