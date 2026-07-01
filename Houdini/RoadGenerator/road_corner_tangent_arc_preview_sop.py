"""Preview an exact tangent circle for a road corner.

Input 0 is the current corner's two offset edge polylines.  The previous
version reused the legacy integrated arc stage, which selected source vertices
by distance and then projected its center to equal radii.  That preserved
neither the chosen input end points nor exact tangency.  This node solves the
preview arc directly:

1. Orient the two offset curves away from their shared corner.
2. Use the pscale distance to choose one real segment on each offset curve,
   then solve the segment-pair tangent circle directly.
3. Emit a circular arc whose first and last points are those input-curve
   tangent points.
"""

import bisect
import math

import hou


EPS = 1.0e-9
UP = hou.Vector3(0.0, 1.0, 0.0)
ARC_SEGMENTS_MIN = 16
ARC_SEGMENTS_MAX = 96
INPUT_POINT_SNAP_TOLERANCE = 1.0e-5


def _warn(node, message):
    if node is None:
        return
    if hasattr(node, "addWarning"):
        node.addWarning(message)
    else:
        print("Warning: {}".format(message))


def _arc_distance_from_pscale(geo):
    """Resolve the tangent search distance from the current input geometry."""
    checks = (
        (geo.findPrimAttrib("corner_pscale"), geo.prims()),
        (geo.findPointAttrib("pscale"), geo.points()),
        (geo.findPrimAttrib("corner_keep_distance"), geo.prims()),
    )
    for attrib, items in checks:
        if attrib is None:
            continue
        best = None
        for item in items:
            value = float(item.attribValue(attrib))
            if value > EPS and (best is None or value > best):
                best = value
        if best is not None:
            return best
    raise hou.NodeError("No positive pscale value found to drive the tangent arc distance.")


def _clamp(value, low, high):
    """将 value 限制在 [low, high] 范围内并返回。"""
    return max(low, min(high, value))


def _safe_normalized(vector):
    """返回向量的单位向量；长度低于 EPS 时返回 None 以避免零除。"""
    if vector.length() <= EPS:
        return None
    return vector.normalized()


def _prim_length(prim):
    """图元各顶点间的累计长度；用于剔除零长度的退化图元（重合点桩）。"""
    verts = list(prim.vertices())
    total = 0.0
    for index in range(1, len(verts)):
        total += (
            hou.Vector3(verts[index].point().position())
            - hou.Vector3(verts[index - 1].point().position())
        ).length()
    return total


def _offset_prims(geometry):
    """返回两条偏移臂图元（角的两条真实臂）。

    输入带 line_role 时只取 'offset'；否则取**最长的两条**折线。交汇点处常混入
    近乎退化的短桩（2 个几乎重合的点，长度 ~0.02），若被误当成臂，其搜索窗口会
    塌缩到 0 附近、把切点钉在角点上。真实臂总是远长于这些短桩，取两条最长即可稳妥剔除。
    """
    role_attrib = geometry.findPrimAttrib("line_role")
    prims = geometry.prims()
    if role_attrib is not None:
        prims = [prim for prim in prims if prim.attribValue(role_attrib) == "offset"]
    usable = [
        (prim, length)
        for prim, length in ((prim, _prim_length(prim)) for prim in prims)
        if length > EPS
    ]
    if role_attrib is not None:
        return [prim for prim, _length in usable[:2]]
    return [
        prim
        for prim, _length in sorted(usable, key=lambda item: item[1], reverse=True)[:2]
    ]


def _records_from_prim(prim):
    """将图元的每个顶点提取为含 position/number 的字典列表。"""
    geo = prim.geometry()
    number_attrib = geo.findPointAttrib("number")
    records = []
    for vertex in prim.vertices():
        point = vertex.point()
        position = hou.Vector3(point.position())
        records.append(
            {
                "position": position,
                "number": (
                    point.number()
                    if number_attrib is None
                    else int(point.attribValue(number_attrib))
                ),
            }
        )
    return records


def _cumulative_lengths(records):
    """计算记录列表的逐点累积弧长数组，首元素为 0.0。"""
    values = [0.0]
    for index in range(1, len(records)):
        values.append(
            values[-1]
            + records[index]["position"].distanceTo(records[index - 1]["position"])
        )
    return values


def _closest_endpoint_pair(records0, records1):
    """在两条曲线各自的两个端点间寻找距离最近的端点对，返回 (最近距离, 曲线0端点索引, 曲线1端点索引)。"""
    endpoints0 = (0, len(records0) - 1)
    endpoints1 = (0, len(records1) - 1)
    return min(
        (
            (records0[idx0]["position"].distanceTo(records1[idx1]["position"]), idx0, idx1)
            for idx0 in endpoints0
            for idx1 in endpoints1
        ),
        key=lambda item: item[0],
    )


def _segment_context_at_distance(records, cumulative, distance):
    if len(records) < 2:
        raise hou.NodeError("Tangent arc input offset curve needs at least two points.")

    length = cumulative[-1]
    distance = _clamp(distance, 0.0, length)
    segment = bisect.bisect_right(cumulative, distance) - 1
    segment = max(0, min(segment, len(records) - 2))

    if cumulative[segment + 1] - cumulative[segment] <= EPS:
        for offset in range(1, len(records)):
            left = segment - offset
            right = segment + offset
            if left >= 0 and cumulative[left + 1] - cumulative[left] > EPS:
                segment = left
                break
            if right < len(records) - 1 and cumulative[right + 1] - cumulative[right] > EPS:
                segment = right
                break

    start = cumulative[segment]
    end = cumulative[segment + 1]
    if end - start <= EPS:
        raise hou.NodeError("Could not select a non-zero pscale segment.")

    a = records[segment]
    b = records[segment + 1]
    tangent = _safe_normalized(b["position"] - a["position"])
    if tangent is None:
        raise hou.NodeError("Could not estimate tangent from the pscale segment.")
    normal = _safe_normalized(UP.cross(tangent))
    if normal is None:
        raise hou.NodeError("Could not estimate normal from the pscale segment.")

    return {
        "segment": int(segment),
        "start": float(start),
        "end": float(end),
        "a": a,
        "b": b,
        "tangent": tangent,
        "normal": normal,
        "origin": a["position"] - tangent * start,
    }


def _sample_segment_at_distance(records, context, distance):
    start = context["start"]
    end = context["end"]
    amount = (distance - start) / (end - start)
    a = context["a"]
    b = context["b"]
    snap_tolerance = max((end - start) * 1.0e-7, INPUT_POINT_SNAP_TOLERANCE)

    if abs(distance - start) <= snap_tolerance:
        position = a["position"]
        number = int(a["number"])
        uses_input_point = True
        amount = 0.0
    elif abs(distance - end) <= snap_tolerance:
        position = b["position"]
        number = int(b["number"])
        uses_input_point = True
        amount = 1.0
    else:
        position = a["position"] + (b["position"] - a["position"]) * amount
        number = int(a["number"] if amount <= 0.5 else b["number"])
        uses_input_point = False

    return {
        "position": position,
        "number": number,
        "segment": int(context["segment"]),
        "segment_fraction": float(amount),
        "uses_input_point": uses_input_point,
    }


def _solve_underdetermined_2x3(cols, rhs, target):
    m00 = sum(col.x() * col.x() for col in cols)
    m01 = sum(col.x() * col.z() for col in cols)
    m11 = sum(col.z() * col.z() for col in cols)
    det = m00 * m11 - m01 * m01
    if abs(det) <= EPS:
        return None

    y0 = (rhs.x() * m11 - rhs.z() * m01) / det
    y1 = (rhs.z() * m00 - rhs.x() * m01) / det
    x0 = [col.x() * y0 + col.z() * y1 for col in cols]

    row_x = hou.Vector3(cols[0].x(), cols[1].x(), cols[2].x())
    row_z = hou.Vector3(cols[0].z(), cols[1].z(), cols[2].z())
    null = row_x.cross(row_z)
    null_len2 = null.dot(null)
    if null_len2 <= EPS:
        return x0

    denom = null.x() * null.x() + null.y() * null.y()
    if denom <= EPS:
        return x0
    k = -((x0[0] - target) * null.x() + (x0[1] - target) * null.y()) / denom
    return [
        x0[0] + null.x() * k,
        x0[1] + null.y() * k,
        x0[2] + null.z() * k,
    ]


def _segment_tangent_candidate(records0, ctx0, records1, ctx1, target, side_sign):
    cols = [
        ctx0["tangent"] * -1.0,
        ctx1["tangent"],
        ctx1["normal"] * side_sign - ctx0["normal"],
    ]
    rhs = ctx0["origin"] - ctx1["origin"]
    solved = _solve_underdetermined_2x3(cols, rhs, target)
    if solved is None:
        return None

    distance0, distance1, signed_radius = solved
    tolerance = max(INPUT_POINT_SNAP_TOLERANCE, target * 1.0e-4)
    if distance0 < ctx0["start"] - tolerance or distance0 > ctx0["end"] + tolerance:
        return None
    if distance1 < ctx1["start"] - tolerance or distance1 > ctx1["end"] + tolerance:
        return None

    sample0 = _sample_segment_at_distance(records0, ctx0, distance0)
    sample1 = _sample_segment_at_distance(records1, ctx1, distance1)
    center0 = sample0["position"] + ctx0["normal"] * signed_radius
    center1 = sample1["position"] + ctx1["normal"] * (side_sign * signed_radius)
    center = (center0 + center1) * 0.5
    radius0 = center.distanceTo(sample0["position"])
    radius1 = center.distanceTo(sample1["position"])
    radius = (radius0 + radius1) * 0.5
    if radius <= EPS:
        return None

    score = (
        abs(distance0 - target) + abs(distance1 - target),
        radius,
    )
    return score, {
        "center": center,
        "radius": float(radius),
        "sample0": sample0,
        "sample1": sample1,
        "exact": True,
    }


def _solve_pscale_segment_tangent(records0, records1, requested_distance):
    cum0 = _cumulative_lengths(records0)
    cum1 = _cumulative_lengths(records1)
    target = max(requested_distance, 1.0e-4)

    base0 = _segment_context_at_distance(records0, cum0, target)
    base1 = _segment_context_at_distance(records1, cum1, target)

    contexts0 = []
    contexts1 = []
    for contexts, records, cumulative, base in (
        (contexts0, records0, cum0, base0),
        (contexts1, records1, cum1, base1),
    ):
        seen = set()
        first = max(0, base["segment"] - 1)
        last = min(len(records) - 2, base["segment"] + 1)
        for segment in range(first, last + 1):
            midpoint = (cumulative[segment] + cumulative[segment + 1]) * 0.5
            context = _segment_context_at_distance(records, cumulative, midpoint)
            if context["segment"] not in seen:
                seen.add(context["segment"])
                contexts.append(context)

    candidates = []
    for ctx0 in contexts0:
        for ctx1 in contexts1:
            for side_sign in (1.0, -1.0):
                candidate = _segment_tangent_candidate(
                    records0, ctx0, records1, ctx1, target, side_sign
                )
                if candidate is not None:
                    candidates.append(candidate)

    if not candidates:
        raise hou.NodeError("Could not solve a direct pscale-segment tangent circle.")

    return min(candidates, key=lambda item: item[0])[1]


def _signed_angle(v0, v1, axis):
    """计算从 v0 到 v1 关于给定轴的有向夹角（弧度）；顺时针方向为负。"""
    a = v0.normalized()
    b = v1.normalized()
    dot_value = _clamp(a.dot(b), -1.0, 1.0)
    angle = math.acos(dot_value)
    if axis.dot(a.cross(b)) < 0.0:
        angle = -angle
    return angle


def _rotate_about_axis(vector, axis, angle):
    """按罗德里格斯公式将向量绕指定轴旋转 angle 弧度后返回。"""
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    return (
        vector * cos_a
        + axis.cross(vector) * sin_a
        + axis * (axis.dot(vector) * (1.0 - cos_a))
    )


def _reflect_center_if_inverted(center, p0, p1, corner):
    """Reflect the circle center across the chord p0-p1 if it is INVERTED.

    A tangent circle is inverted when its center lies on the SAME side of the
    chord as the corner. Reflecting it keeps the same radius and makes the
    signed minor arc round the corner on the intended side.
    """
    center = hou.Vector3(center)
    p0 = hou.Vector3(p0)
    chord = hou.Vector3(p1) - p0
    normal = hou.Vector3(-chord.z(), 0.0, chord.x())
    if normal.length() <= EPS:
        return center
    normal = normal.normalized()
    center_side = (center - p0).dot(normal)
    corner_side = (hou.Vector3(corner) - p0).dot(normal)
    if center_side * corner_side <= 0.0:
        return center
    return center - normal * (2.0 * center_side)


def _emit_arc(target_geo, solution, corner_id, number_attrib):
    """Emit the preview arc points and boundary segments."""
    sample0 = solution["sample0"]
    sample1 = solution["sample1"]
    endpoint0 = solution["endpoint0"]
    endpoint1 = solution["endpoint1"]
    corner_point = (solution["corner0"] + solution["corner1"]) * 0.5
    center = _reflect_center_if_inverted(
        solution["center"], sample0["position"], sample1["position"], corner_point
    )
    start_vec = sample0["position"] - center
    end_vec = sample1["position"] - center
    arc_angle = _signed_angle(start_vec, end_vec, UP)
    if abs(arc_angle) <= EPS:
        raise hou.NodeError("The computed tangent arc angle is too small.")

    arc_length = abs(solution["radius"] * arc_angle)
    segment_count = max(
        ARC_SEGMENTS_MIN,
        min(ARC_SEGMENTS_MAX, int(math.ceil(arc_length / 0.25))),
    )
    point_count = max(segment_count + 1, 2)
    point_specs = []
    for index in range(point_count):
        fraction = float(index) / float(point_count - 1)
        position = center + _rotate_about_axis(start_vec, UP, arc_angle * fraction)
        number = sample0["number"] if fraction < 0.5 else sample1["number"]
        if index == 0:
            position = endpoint0["position"]
            number = endpoint0["number"]
        elif index == point_count - 1:
            position = endpoint1["position"]
            number = endpoint1["number"]
        point_specs.append((position, int(number)))

    if (
        len(point_specs) >= 2
        and point_specs[0][1] > point_specs[-1][1]
    ):
        point_specs.reverse()

    points = []
    for position, number in point_specs:
        point = target_geo.createPoint()
        point.setPosition(position)
        point.setAttribValue(number_attrib, number)
        points.append(point)

    boundary_group = target_geo.findPrimGroup("arc_boundary_edge")
    if boundary_group is None:
        boundary_group = target_geo.createPrimGroup("arc_boundary_edge")
    corner_attrib = target_geo.findPrimAttrib("corner_id")
    if corner_attrib is None:
        corner_attrib = target_geo.addAttrib(
            hou.attribType.Prim, "corner_id", -1, create_local_variable=False
        )

    emitted = 0
    for index in range(len(points) - 1):
        poly = target_geo.createPolygon()
        poly.setIsClosed(False)
        poly.addVertex(points[index])
        poly.addVertex(points[index + 1])
        poly.setAttribValue(corner_attrib, int(corner_id))
        boundary_group.add(poly)
        emitted += 1

    return emitted


def _next_endpoint_record(records, sample):
    """Return the next source record after a tangent sample on an oriented arm."""
    if not records:
        return sample

    segment = int(sample.get("segment", 0))
    fraction = float(sample.get("segment_fraction", 0.0))
    segment = max(0, min(segment, len(records) - 1))

    if bool(sample.get("uses_input_point", False)):
        index = segment + 1 if fraction >= 0.5 else segment
        index = max(0, min(index, len(records) - 1))
        return records[index]

    base = records[segment]
    base_number = int(base.get("number", -1))
    fallback = records[min(segment + 1, len(records) - 1)]
    for index in range(segment + 1, len(records)):
        record = records[index]
        if hou.Vector3(record["position"]).distanceTo(base["position"]) <= EPS:
            continue
        if int(record.get("number", -1)) == base_number and index < len(records) - 1:
            continue
        return record
    return fallback


def _solve_corner(bundle_geo, _centre_geo, requested_distance):
    """Solve one exact tangent arc from the two offset arms."""
    offsets = _offset_prims(bundle_geo)
    if len(offsets) < 2:
        raise hou.NodeError("Expected two offset curves for tangent arc preview.")

    records0 = _records_from_prim(offsets[0])
    records1 = _records_from_prim(offsets[1])
    if len(records0) < 2 or len(records1) < 2:
        raise hou.NodeError("Each offset curve needs at least two points.")

    _, endpoint0, endpoint1 = _closest_endpoint_pair(records0, records1)
    arm0 = list(records0) if endpoint0 == 0 else list(reversed(records0))
    arm1 = list(records1) if endpoint1 == 0 else list(reversed(records1))

    solution = _solve_pscale_segment_tangent(arm0, arm1, requested_distance)
    solution["endpoint0"] = _next_endpoint_record(arm0, solution["sample0"])
    solution["endpoint1"] = _next_endpoint_record(arm1, solution["sample1"])
    solution["corner0"] = arm0[0]["position"]
    solution["corner1"] = arm1[0]["position"]
    return solution


def build():
    """Build one tangent arc from the current two-offset input geometry."""
    node = hou.pwd()
    out_geo = node.geometry()
    source = node.inputGeometry(0)

    out_geo.clear()
    number_attrib = out_geo.addAttrib(
        hou.attribType.Point, "number", -1, create_local_variable=False
    )

    emitted = 0
    try:
        requested_distance = _arc_distance_from_pscale(source)
        solution = _solve_corner(source, None, requested_distance)
        emitted = _emit_arc(out_geo, solution, 0, number_attrib)
    except Exception as exc:
        _warn(
            node,
            "tangent arc preview skipped current corner: {}".format(exc),
        )

    if emitted == 0:
        _warn(node, "tangent arc preview found no usable exact tangent arc.")


if globals().get("ROAD_CORNER_TANGENT_ARC_PREVIEW_AUTOBUILD", True):
    build()
