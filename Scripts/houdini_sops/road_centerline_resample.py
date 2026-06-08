"""Houdini Python SOP: normalize road centerline point spacing.

Input: raw map/API road centerlines from road_api_raw_lines.
Output: road centerlines with a bounded, predictable point spacing.

This node keeps road_api_raw_lines as the untouched source of truth, then
standardizes the geometry consumed by downstream road processing. It is
conservative by design:
  * primitive attributes and primitive groups are copied through;
  * endpoints are kept exactly so road graph connectivity is stable;
  * shared input points from road_api_shared_topology stay shared;
  * sharp original bends are kept as anchors;
  * any processing error falls back to the original input geometry.
"""

import math

import hou


node = hou.pwd()
geo = node.geometry()
geo.clear()

geo_in = node.inputs()[0].geometry() if node.inputs() else None

ENABLED = bool(int("__ENABLED__"))
TARGET_SPACING = max(0.25, float("__TARGET_SPACING__"))
PRESERVE_BEND_DEG = max(1.0, min(179.0, float("__PRESERVE_BEND_DEG__")))
EPS = 1.0e-6
TOPOLOGY_REUSE_TOLERANCE = 0.01


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


def segment_len_xz_vec(vec):
    return math.hypot(float(vec[0]), float(vec[2]))


def lerp(a, b, t):
    return a + (b - a) * t


def append_unique(points, pos, eps=0.01):
    if points and length_xz(points[-1], pos) <= eps:
        return
    points.append(pos)


def append_point_ref(point_refs, point_number, pos, eps=0.01):
    if point_refs and length_xz(point_refs[-1][1], pos) <= eps:
        return
    point_refs.append((point_number, pos))


def clean_point_refs(prim):
    refs = []
    for vertex in prim.vertices():
        point = vertex.point()
        append_point_ref(refs, point.number(), point.position(), eps=EPS)
    return refs


def cumulative_lengths(points):
    distances = [0.0]
    total = 0.0
    max_seg = 0.0
    for idx in range(len(points) - 1):
        seg_len = length_xz(points[idx], points[idx + 1])
        total += seg_len
        max_seg = max(max_seg, seg_len)
        distances.append(total)
    return distances, total, max_seg


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


def bend_degrees(prev_pos, pos, next_pos):
    v0 = pos - prev_pos
    v1 = next_pos - pos
    l0 = segment_len_xz_vec(v0)
    l1 = segment_len_xz_vec(v1)
    if l0 <= EPS or l1 <= EPS:
        return 0.0
    dot = (float(v0[0]) * float(v1[0]) + float(v0[2]) * float(v1[2])) / (l0 * l1)
    dot = max(-1.0, min(1.0, dot))
    return math.degrees(math.acos(dot))


def append_distance(distances, value, input_point_number=None, eps=0.01):
    if distances and abs(distances[-1][0] - value) <= eps:
        if distances[-1][1] is None and input_point_number is not None:
            distances[-1] = (distances[-1][0], input_point_number)
        return
    distances.append((value, input_point_number))


def shared_input_point_numbers():
    if geo_in is None:
        return set()
    point_prim_counts = {}
    for prim in geo_in.prims():
        seen = set()
        for vertex in prim.vertices():
            try:
                seen.add(vertex.point().number())
            except Exception:
                pass
        for point_number in seen:
            point_prim_counts[point_number] = point_prim_counts.get(point_number, 0) + 1
    return {point_number for point_number, count in point_prim_counts.items() if count > 1}


def resample_positions(point_refs, shared_point_numbers):
    if len(point_refs) < 2:
        return [(pos, number if number in shared_point_numbers else None) for number, pos in point_refs], 0.0, 0.0, 0, 0

    point_numbers = [number for number, _pos in point_refs]
    points = [pos for _number, pos in point_refs]

    distances, total, max_before = cumulative_lengths(points)
    if total <= EPS:
        return [(pos, number if number in shared_point_numbers else None) for number, pos in point_refs], max_before, max_before, 0, 0

    endpoint_id = point_numbers[0] if point_numbers[0] in shared_point_numbers else None
    anchors = [(0.0, endpoint_id)]
    preserved_bends = 0
    preserved_shared = 1 if endpoint_id is not None else 0
    for idx in range(1, len(points) - 1):
        shared_id = point_numbers[idx] if point_numbers[idx] in shared_point_numbers else None
        is_shared = shared_id is not None
        is_bend = bend_degrees(points[idx - 1], points[idx], points[idx + 1]) >= PRESERVE_BEND_DEG
        if is_shared or is_bend:
            append_distance(anchors, distances[idx], shared_id)
        if is_bend:
            preserved_bends += 1
        if is_shared:
            preserved_shared += 1
    endpoint_id = point_numbers[-1] if point_numbers[-1] in shared_point_numbers else None
    append_distance(anchors, total, endpoint_id)
    if endpoint_id is not None:
        preserved_shared += 1

    sample_distances = []
    for idx in range(len(anchors) - 1):
        start, start_point_number = anchors[idx]
        end, _end_point_number = anchors[idx + 1]
        span = end - start
        if span <= EPS:
            continue
        pieces = max(1, int(math.ceil(span / TARGET_SPACING)))
        for step in range(pieces):
            input_point_number = start_point_number if step == 0 else None
            append_distance(sample_distances, start + span * (float(step) / float(pieces)), input_point_number)
    append_distance(sample_distances, total, anchors[-1][1])

    out = []
    for distance, input_point_number in sample_distances:
        pos = point_at_distance(points, distances, distance)
        if out and length_xz(out[-1][0], pos) <= 0.01:
            if out[-1][1] is None and input_point_number is not None:
                out[-1] = (out[-1][0], input_point_number)
            continue
        out.append((pos, input_point_number))

    out_positions = [pos for pos, _input_point_number in out]
    _, _, max_after = cumulative_lengths(out_positions) if len(out_positions) >= 2 else ([0.0], 0.0, 0.0)
    return out, max_before, max_after, preserved_bends, preserved_shared


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
    set_global("road_centerline_resample_status", status)
    set_global("road_centerline_resample_enabled", int(ENABLED))
    set_global("road_centerline_resample_target_spacing", float(TARGET_SPACING))
    set_global("road_centerline_resample_preserve_bend_deg", float(PRESERVE_BEND_DEG))
    set_global("road_centerline_resample_source_prims", int(geo_in.intrinsicValue("primitivecount")) if geo_in else 0)
    set_global("road_centerline_resample_output_prims", int(geo.intrinsicValue("primitivecount")))
    set_global("road_centerline_resample_inserted_points", 0)
    set_global("road_centerline_resample_removed_points", 0)
    set_global("road_centerline_resample_resampled_prims", 0)
    set_global("road_centerline_resample_preserved_bends", 0)
    set_global("road_centerline_resample_preserved_shared_points", 0)
    set_global("road_centerline_resample_reused_shared_points", 0)
    set_global("road_centerline_resample_max_segment_before", 0.0)
    set_global("road_centerline_resample_max_segment_after", 0.0)
    set_global("road_centerline_resample_fallbacks", int(fallbacks))
    if message:
        set_global("road_centerline_resample_message", str(message)[:240])


if geo_in is None:
    passthrough("missing_input", 1)
elif not ENABLED:
    passthrough("disabled", 0)
else:
    try:
        copy_global_attrs()

        dst_attrs = {}
        for src_attr in geo_in.primAttribs():
            name = src_attr.name()
            dst_attrs[name] = geo.findPrimAttrib(name) or geo.addAttrib(
                hou.attribType.Prim, name, default_for_attrib(src_attr)
            )

        group_members = {}
        dst_groups = {}
        for group in geo_in.primGroups():
            try:
                group_members[group.name()] = set(prim.number() for prim in group.prims())
                dst_groups[group.name()] = geo.createPrimGroup(group.name())
            except Exception:
                pass

        source_prims = 0
        output_prims = 0
        inserted_points = 0
        removed_points = 0
        resampled_prims = 0
        preserved_bends = 0
        preserved_shared_points = 0
        reused_shared_points = 0
        max_before_all = 0.0
        max_after_all = 0.0
        shared_point_numbers = shared_input_point_numbers()
        output_point_by_input_number = {}
        output_point_by_position = {}

        def position_key(pos):
            return (
                round(float(pos[0]) / TOPOLOGY_REUSE_TOLERANCE),
                round(float(pos[2]) / TOPOLOGY_REUSE_TOLERANCE),
            )

        def shared_point(pos, input_point_number=None):
            global reused_shared_points
            if input_point_number is not None:
                point = output_point_by_input_number.get(input_point_number)
                if point is not None:
                    reused_shared_points += 1
                    return point
                point = geo.createPoint()
                point.setPosition(pos)
                output_point_by_input_number[input_point_number] = point
                output_point_by_position[position_key(pos)] = point
                return point

            key = position_key(pos)
            point = output_point_by_position.get(key)
            if point is not None and length_xz(point.position(), pos) <= TOPOLOGY_REUSE_TOLERANCE:
                reused_shared_points += 1
                return point
            point = geo.createPoint()
            point.setPosition(pos)
            output_point_by_position[key] = point
            return point

        for prim in geo_in.prims():
            source_prims += 1
            point_refs = clean_point_refs(prim)
            if len(point_refs) < 2:
                continue

            resampled, max_before, max_after, bends, shared = resample_positions(point_refs, shared_point_numbers)
            max_before_all = max(max_before_all, max_before)
            max_after_all = max(max_after_all, max_after)
            preserved_bends += bends
            preserved_shared_points += shared
            inserted_points += max(0, len(resampled) - len(point_refs))
            removed_points += max(0, len(point_refs) - len(resampled))
            if len(resampled) != len(point_refs) or max_before > TARGET_SPACING + 0.01:
                resampled_prims += 1

            poly = geo.createPolygon()
            try:
                poly.setIsClosed(bool(prim.isClosed()))
            except Exception:
                poly.setIsClosed(False)
            for pos, input_point_number in resampled:
                poly.addVertex(shared_point(pos, input_point_number))
            copy_prim_attrs(prim, poly, dst_attrs)
            for name, members in group_members.items():
                if prim.number() in members and name in dst_groups:
                    try:
                        dst_groups[name].add(poly)
                    except Exception:
                        pass
            output_prims += 1

        set_global("road_centerline_resample_status", "resampled")
        set_global("road_centerline_resample_enabled", int(ENABLED))
        set_global("road_centerline_resample_target_spacing", float(TARGET_SPACING))
        set_global("road_centerline_resample_preserve_bend_deg", float(PRESERVE_BEND_DEG))
        set_global("road_centerline_resample_source_prims", int(source_prims))
        set_global("road_centerline_resample_output_prims", int(output_prims))
        set_global("road_centerline_resample_inserted_points", int(inserted_points))
        set_global("road_centerline_resample_removed_points", int(removed_points))
        set_global("road_centerline_resample_resampled_prims", int(resampled_prims))
        set_global("road_centerline_resample_preserved_bends", int(preserved_bends))
        set_global("road_centerline_resample_preserved_shared_points", int(preserved_shared_points))
        set_global("road_centerline_resample_reused_shared_points", int(reused_shared_points))
        set_global("road_centerline_resample_max_segment_before", float(max_before_all))
        set_global("road_centerline_resample_max_segment_after", float(max_after_all))
        set_global("road_centerline_resample_fallbacks", 0)
    except Exception as exc:
        passthrough("fallback", 1, "{}: {}".format(type(exc).__name__, exc))
