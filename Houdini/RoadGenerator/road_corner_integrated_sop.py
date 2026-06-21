"""Integrated road corner SOP.

Single-file merge of road_corner_integrated_sop.py, road_offset_stitch_sop.py,
and houdini_tangent_arc_sop.py.
"""

import bisect
import math
import time

import hou

DEBUG_SINGLE_CORNER = None

# -- Arc constants --
EPS = 1.0e-9
TAU = math.pi * 2.0
SAMPLES = 900
INTERSECTION_COARSE_SAMPLES = 220
REFINE_SEGMENT_WINDOW = 56
ARC_INTERSECTION_TOLERANCE = 1.0e-5
SOURCE_POINT_LENGTH_TOLERANCE = 1.0e-6



# -- Arc module-level state (set per-call by _run_arc) --
_arc_node = None
_arc_geo = None
_arc_legacy_ctrl = None
_arc_centre_geo = None

def warn(message):
    if hasattr(_arc_node, "addWarning"):
        _arc_node.addWarning(message)


def control_parm(name):
    parm = _arc_node.parm(name) if hasattr(_arc_node, "parm") else None
    if parm is None and _arc_legacy_ctrl is not None:
        parm = _arc_legacy_ctrl.parm(name)
    return parm


def ctrl_value(name, default):
    parm = control_parm(name)
    return default if parm is None else parm.eval()


def clamp(value, low, high):
    return max(low, min(high, value))
def vec(value):
    return hou.Vector3(value)
def sample_curve(prim, sample_count):
    n = sample_count + 1
    inv_n = 1.0 / float(sample_count)
    params = [float(i) * inv_n for i in range(n)]
    points = [vec(prim.positionAt(u)) for u in params]
    cumulative = [0.0]
    for index in range(1, n):
        cumulative.append(cumulative[-1] + (points[index] - points[index - 1]).length())
    return {"prim": prim, "points": points, "u": params, "cum": cumulative, "length": cumulative[-1]}
def point_at_length(curve, distance):
    cum = curve["cum"]
    u_vals = curve["u"]
    curve_len = curve["length"]
    distance = clamp(distance, 0.0, curve_len)
    index = bisect.bisect_left(cum, distance)
    if index <= 0:
        u = u_vals[0]
    elif index >= len(cum):
        u = u_vals[-1]
    else:
        prev = cum[index - 1]
        seg_len = cum[index] - prev
        amount = 0.0 if seg_len <= EPS else (distance - prev) / seg_len
        u = u_vals[index - 1] + amount * (u_vals[index] - u_vals[index - 1])
    return vec(curve["prim"].positionAt(u)), u
def tangent_at_length(curve, distance):
    curve_len = curve["length"]
    step = max(curve_len * 1.0e-5, 1.0e-4)
    low = clamp(distance - step, 0.0, curve_len)
    high = clamp(distance + step, 0.0, curve_len)
    if abs(high - low) <= EPS:
        low = clamp(distance - step * 10.0, 0.0, curve_len)
        high = clamp(distance + step * 10.0, 0.0, curve_len)
    p0, _ = point_at_length(curve, low)
    p1, _ = point_at_length(curve, high)
    tangent = p1 - p0
    if tangent.length() <= EPS:
        raise hou.NodeError("Could not estimate curve tangent. Check the input curves.")
    return tangent.normalized()
def segment_index_at_length(curve, distance):
    cum = curve["cum"]
    index = bisect.bisect_right(cum, clamp(distance, 0.0, curve["length"])) - 1
    return max(0, min(index, len(cum) - 2))
def find_best_segment_pair(curve0, curve1, start0, end0, start1, end1):
    # Hot path for the intersection search. The maths is the exact scalar
    # expansion of closest_points_on_segments, but the active point windows are
    # pre-extracted as plain float triples so the inner loop never crosses the
    # hou.Vector3 binding layer. Only the surviving best candidate allocates a
    # Vector3.
    _eps = EPS
    best = None
    checks = 0
    pts0 = curve0["points"]
    pts1 = curve1["points"]
    cum0 = curve0["cum"]
    cum1 = curve1["cum"]
    start0 = max(0, start0)
    start1 = max(0, start1)
    end0 = min(end0, len(pts0) - 1)
    end1 = min(end1, len(pts1) - 1)
    if end0 <= start0 or end1 <= start1:
        return None, checks
    win0 = [(float(p[0]), float(p[1]), float(p[2])) for p in pts0[start0:end0 + 1]]
    win1 = [(float(p[0]), float(p[1]), float(p[2])) for p in pts1[start1:end1 + 1]]
    n1 = len(win1) - 1
    best_gap = None
    for i_off in range(end0 - start0):
        i = start0 + i_off
        ax, ay, az = win0[i_off]
        bx, by, bz = win0[i_off + 1]
        d1x = bx - ax
        d1y = by - ay
        d1z = bz - az
        a = d1x * d1x + d1y * d1y + d1z * d1z
        a_is_zero = a <= _eps
        seg0_len = cum0[i + 1] - cum0[i]
        for j_off in range(n1):
            checks += 1
            cx, cy, cz = win1[j_off]
            dx, dy, dz = win1[j_off + 1]
            d2x = dx - cx
            d2y = dy - cy
            d2z = dz - cz
            rx = ax - cx
            ry = ay - cy
            rz = az - cz
            e = d2x * d2x + d2y * d2y + d2z * d2z
            f = d2x * rx + d2y * ry + d2z * rz
            if a_is_zero and e <= _eps:
                s = 0.0
                t = 0.0
            elif a_is_zero:
                s = 0.0
                tv = f / e
                t = 0.0 if tv < 0.0 else (1.0 if tv > 1.0 else tv)
            else:
                cdot = d1x * rx + d1y * ry + d1z * rz
                if e <= _eps:
                    t = 0.0
                    sv = -cdot / a
                    s = 0.0 if sv < 0.0 else (1.0 if sv > 1.0 else sv)
                else:
                    b = d1x * d2x + d1y * d2y + d1z * d2z
                    denom = a * e - b * b
                    if abs(denom) > _eps:
                        sv = (b * f - cdot * e) / denom
                        s = 0.0 if sv < 0.0 else (1.0 if sv > 1.0 else sv)
                    else:
                        s = 0.0
                    tnom = b * s + f
                    if tnom < 0.0:
                        t = 0.0
                        sv = -cdot / a
                        s = 0.0 if sv < 0.0 else (1.0 if sv > 1.0 else sv)
                    elif tnom > e:
                        t = 1.0
                        sv = (b - cdot) / a
                        s = 0.0 if sv < 0.0 else (1.0 if sv > 1.0 else sv)
                    else:
                        t = tnom / e
            c0x = ax + d1x * s
            c0y = ay + d1y * s
            c0z = az + d1z * s
            c1x = cx + d2x * t
            c1y = cy + d2y * t
            c1z = cz + d2z * t
            gx = c0x - c1x
            gy = c0y - c1y
            gz = c0z - c1z
            gap = (gx * gx + gy * gy + gz * gz) ** 0.5
            if best_gap is None or gap < best_gap:
                best_gap = gap
                j = start1 + j_off
                seg1_len = cum1[j + 1] - cum1[j]
                best = {
                    "gap": gap,
                    "point": hou.Vector3(
                        (c0x + c1x) * 0.5, (c0y + c1y) * 0.5, (c0z + c1z) * 0.5
                    ),
                    "curve0_length": cum0[i] + seg0_len * s,
                    "curve1_length": cum1[j] + seg1_len * t,
                    "segment0": i,
                    "segment1": j,
                }
    return best, checks
def find_curve_intersection(curve0, curve1):
    coarse0 = sample_curve(curve0["prim"], INTERSECTION_COARSE_SAMPLES)
    coarse1 = sample_curve(curve1["prim"], INTERSECTION_COARSE_SAMPLES)
    coarse, coarse_checks = find_best_segment_pair(
        coarse0, coarse1, 0, len(coarse0["points"]) - 1, 0, len(coarse1["points"]) - 1
    )
    if coarse is None:
        raise hou.NodeError("Could not find an intersection between the two curves.")
    length0 = (
        0.0
        if coarse0["length"] <= EPS
        else clamp(coarse["curve0_length"] / coarse0["length"], 0.0, 1.0) * curve0["length"]
    )
    length1 = (
        0.0
        if coarse1["length"] <= EPS
        else clamp(coarse["curve1_length"] / coarse1["length"], 0.0, 1.0) * curve1["length"]
    )
    center0 = segment_index_at_length(curve0, length0)
    center1 = segment_index_at_length(curve1, length1)
    refine0_start = center0 - REFINE_SEGMENT_WINDOW
    refine0_end = center0 + REFINE_SEGMENT_WINDOW + 1
    refine1_start = center1 - REFINE_SEGMENT_WINDOW
    refine1_end = center1 + REFINE_SEGMENT_WINDOW + 1
    refined, refine_checks = find_best_segment_pair(
        curve0, curve1, refine0_start, refine0_end, refine1_start, refine1_end
    )
    if refined is None:
        refined = {
            "gap": coarse["gap"],
            "point": coarse["point"],
            "curve0_length": length0,
            "curve1_length": length1,
            "segment0": center0,
            "segment1": center1,
        }
    refined["candidate_checks"] = coarse_checks + refine_checks
    return refined
def intersect_normal_lines(p0, tangent0, p1, tangent1, plane_normal):
    normal0 = plane_normal.cross(tangent0)
    normal1 = plane_normal.cross(tangent1)
    if normal0.length() <= EPS or normal1.length() <= EPS:
        return None
    normal0 = normal0.normalized()
    normal1 = normal1.normalized()
    w0 = p0 - p1
    b = normal0.dot(normal1)
    d = normal0.dot(w0)
    e = normal1.dot(w0)
    denom = 1.0 - b * b
    if abs(denom) <= EPS:
        return None
    s = (b * e - d) / denom
    t = (e - b * d) / denom
    c0 = p0 + normal0 * s
    c1 = p1 + normal1 * t
    center = (c0 + c1) * 0.5
    r0 = (center - p0).length()
    r1 = (center - p1).length()
    return {
        "center": center,
        "normal0": normal0,
        "normal1": normal1,
        "radius0": r0,
        "radius1": r1,
        "radius": (r0 + r1) * 0.5,
        "radius_error": r0 - r1,
        "line_gap": (c0 - c1).length(),
    }
def project_center_to_equal_radii(center, p0, p1):
    chord = p1 - p0
    denom = chord.dot(chord)
    if denom <= EPS:
        raise hou.NodeError("The two tangent/interface points are too close together.")
    target = (p1.dot(p1) - p0.dot(p0)) * 0.5
    return center + chord * ((target - center.dot(chord)) / denom)
def point_line_distance(point, origin, direction):
    if direction.length() <= EPS:
        return 0.0
    return ((point - origin).cross(direction.normalized())).length()
def rotate_about_axis(vector, axis, angle):
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    return vector * cos_a + axis.cross(vector) * sin_a + axis * (axis.dot(vector) * (1.0 - cos_a))
def signed_angle(v0, v1, axis):
    a = v0.normalized()
    b = v1.normalized()
    dot_value = clamp(a.dot(b), -1.0, 1.0)
    angle = math.acos(dot_value)
    if axis.dot(a.cross(b)) < 0.0:
        angle = -angle
    return angle
def angular_distance(a, b):
    delta = (a - b + math.pi) % TAU - math.pi
    return abs(delta)
def fraction_for_point_on_arc(position, center, start_vec, plane_normal, arc_angle):
    if abs(arc_angle) <= EPS:
        return 0.0
    vector = position - center
    planar = vector - plane_normal * vector.dot(plane_normal)
    if planar.length() <= EPS:
        return 0.0
    theta = signed_angle(start_vec, planar, plane_normal)
    candidates = [theta - TAU, theta, theta + TAU]
    if arc_angle > 0.0:
        inside = [item for item in candidates if -EPS <= item <= arc_angle + EPS]
        if inside:
            selected = clamp(min(inside, key=lambda item: abs(item - theta)), 0.0, arc_angle)
        else:
            selected = 0.0 if angular_distance(theta, 0.0) <= angular_distance(theta, arc_angle) else arc_angle
    else:
        inside = [item for item in candidates if arc_angle - EPS <= item <= EPS]
        if inside:
            selected = clamp(min(inside, key=lambda item: abs(item - theta)), arc_angle, 0.0)
        else:
            selected = 0.0 if angular_distance(theta, 0.0) <= angular_distance(theta, arc_angle) else arc_angle
    return clamp(selected / arc_angle, 0.0, 1.0)
def fraction_for_point_inside_arc(position, center, start_vec, plane_normal, arc_angle, tolerance):
    if abs(arc_angle) <= EPS:
        return None
    vector = position - center
    planar = vector - plane_normal * vector.dot(plane_normal)
    if planar.length() <= EPS:
        return None
    theta = signed_angle(start_vec, planar, plane_normal)
    candidates = [theta - TAU, theta, theta + TAU]
    if arc_angle > 0.0:
        inside = [item for item in candidates if -tolerance <= item <= arc_angle + tolerance]
    else:
        inside = [item for item in candidates if arc_angle - tolerance <= item <= tolerance]
    if not inside:
        return None
    selected = min(inside, key=lambda item: abs(item - theta))
    return clamp(selected / arc_angle, 0.0, 1.0)
def arc_point_at_fraction(center, start_vec, plane_normal, arc_angle, fraction):
    fraction = clamp(fraction, 0.0, 1.0)
    return center + rotate_about_axis(start_vec, plane_normal, arc_angle * fraction)
def choose_arc_angle(center, start_vec, end_vec, plane_normal, near_point):
    minor = signed_angle(start_vec, end_vec, plane_normal)
    if abs(minor) <= EPS:
        raise hou.NodeError("The computed circular arc angle is too small.")
    other = minor - math.copysign(TAU, minor)
    choices = []
    for angle in (minor, other):
        fraction = fraction_for_point_on_arc(near_point, center, start_vec, plane_normal, angle)
        projected = arc_point_at_fraction(center, start_vec, plane_normal, angle, fraction)
        choices.append((projected.distanceTo(near_point), abs(angle), angle, fraction, projected))
    choices.sort(key=lambda item: (item[0], item[1]))
    return choices[0][2], choices[0][3], choices[0][4]
def source_segment_lengths(curve, start_length, end_length):
    low = min(start_length, end_length)
    high = max(start_length, end_length)
    tolerance = max(curve["length"] * 1.0e-7, 1.0e-6)
    values = [clamp(start_length, 0.0, curve["length"]), clamp(end_length, 0.0, curve["length"])]
    for length in curve["cum"]:
        if low + tolerance < length < high - tolerance:
            values.append(length)
    return unique_sorted([clamp(item, 0.0, curve["length"]) for item in values], tolerance)
def line_segment_circle_arc_intersections(pa, pb, la, lb, center, radius, start_vec, plane_normal, arc_angle, near_point):
    pa_planar = pa - center
    pa_planar = pa_planar - plane_normal * pa_planar.dot(plane_normal)
    pb_planar = pb - center
    pb_planar = pb_planar - plane_normal * pb_planar.dot(plane_normal)
    delta = pb_planar - pa_planar
    a = delta.dot(delta)
    if a <= EPS:
        return []
    b = 2.0 * pa_planar.dot(delta)
    c = pa_planar.dot(pa_planar) - radius * radius
    discriminant = b * b - 4.0 * a * c
    tolerance = max(radius * ARC_INTERSECTION_TOLERANCE, ARC_INTERSECTION_TOLERANCE)
    if discriminant < -tolerance:
        return []
    if abs(discriminant) <= tolerance:
        roots = [-b / (2.0 * a)]
    else:
        root = math.sqrt(max(discriminant, 0.0))
        roots = [(-b - root) / (2.0 * a), (-b + root) / (2.0 * a)]
    intersections = []
    for amount in roots:
        if amount < -ARC_INTERSECTION_TOLERANCE or amount > 1.0 + ARC_INTERSECTION_TOLERANCE:
            continue
        amount = clamp(amount, 0.0, 1.0)
        planar = pa_planar + delta * amount
        if planar.length() <= EPS:
            continue
        point = center + planar.normalized() * radius
        fraction = fraction_for_point_inside_arc(point, center, start_vec, plane_normal, arc_angle, ARC_INTERSECTION_TOLERANCE)
        if fraction is None:
            continue
        intersections.append({
            "point": point,
            "fraction": fraction,
            "curve_length": la + (lb - la) * amount,
            "near_distance": point.distanceTo(near_point),
        })
    return intersections
def dedupe_arc_intersections(items):
    result = []
    for item in sorted(items, key=lambda entry: (entry["fraction"], entry["curve_length"])):
        duplicate_index = None
        for index, existing in enumerate(result):
            if abs(item["fraction"] - existing["fraction"]) <= ARC_INTERSECTION_TOLERANCE:
                duplicate_index = index
                break
            if item["point"].distanceTo(existing["point"]) <= ARC_INTERSECTION_TOLERANCE:
                duplicate_index = index
                break
        if duplicate_index is None:
            result.append(item)
        elif item["near_distance"] < result[duplicate_index]["near_distance"]:
            result[duplicate_index] = item
    return result
def find_source_segment_arc_intersections(curve, intersection_length, tangent_length, center, radius, start_vec, plane_normal, arc_angle, near_point):
    lengths = source_segment_lengths(curve, intersection_length, tangent_length)
    hits = []
    for index in range(len(lengths) - 1):
        la = lengths[index]
        lb = lengths[index + 1]
        pa, _ = point_at_length(curve, la)
        pb, _ = point_at_length(curve, lb)
        hits += line_segment_circle_arc_intersections(
            pa, pb, la, lb, center, radius, start_vec, plane_normal, arc_angle, near_point
        )
    return dedupe_arc_intersections(hits)
def trim_intersection_to_nearest_curve_hit(curve0_hits, curve1_hits, current_fraction, current_point):
    candidates = []
    if len(curve0_hits) >= 2:
        best0 = min(curve0_hits, key=lambda item: item["near_distance"])
        best0["side"] = 0
        candidates.append(best0)
    if len(curve1_hits) >= 2:
        best1 = min(curve1_hits, key=lambda item: item["near_distance"])
        best1["side"] = 1
        candidates.append(best1)
    if not candidates:
        return {
            "trimmed": False,
            "fraction": current_fraction,
            "point": current_point,
            "side": -1,
        }
    selected = min(candidates, key=lambda item: item["near_distance"])
    return {
        "trimmed": True,
        "fraction": selected["fraction"],
        "point": selected["point"],
        "side": selected["side"],
    }
def unique_sorted(values, tolerance):
    result = []
    for value in sorted(values):
        if not result or abs(value - result[-1]) > tolerance:
            result.append(value)
    return result
def auto_direction(curve, intersection_length, requested_distance):
    backward = intersection_length
    forward = curve["length"] - intersection_length
    if forward >= requested_distance and backward < requested_distance:
        return 1.0
    if backward >= requested_distance and forward < requested_distance:
        return -1.0
    return 1.0 if forward >= backward else -1.0

def source_entries_for_curve(curve):
    entries = []
    prim_geo = curve["prim"].geometry()
    rest_attrib = prim_geo.findPointAttrib("rest")
    number_attrib = prim_geo.findPointAttrib("number")
    raw_points = [vec(vertex.point().position()) for vertex in curve["prim"].vertices()]
    raw_cumulative = [0.0]
    for index in range(1, len(raw_points)):
        raw_cumulative.append(raw_cumulative[-1] + raw_points[index].distanceTo(raw_points[index - 1]))
    raw_length = raw_cumulative[-1] if raw_cumulative else 0.0
    for vertex in curve["prim"].vertices():
        index = len(entries)
        point = vertex.point()
        position = raw_points[index]
        length = 0.0 if raw_length <= EPS else raw_cumulative[index] / raw_length * curve["length"]
        rest = vec(point.attribValue(rest_attrib)) if rest_attrib is not None else position
        number = int(point.attribValue(number_attrib)) if number_attrib is not None else point.number()
        entries.append({
            "length": clamp(length, 0.0, curve["length"]),
            "position": position,
            "rest": rest,
            "number": number,
        })
    if not entries:
        start_pos, _ = point_at_length(curve, 0.0)
        end_pos, _ = point_at_length(curve, curve["length"])
        entries = [
            {"length": 0.0, "position": start_pos, "rest": start_pos, "number": -1},
            {"length": curve["length"], "position": end_pos, "rest": end_pos, "number": -1},
        ]
    entries.sort(key=lambda item: item["length"])
    return entries
def polyline_from_prim(prim):
    points = []
    point_ids = []
    numbers = []
    number_attrib = prim.geometry().findPointAttrib("number")
    for vertex in prim.vertices():
        point = vertex.point()
        points.append(vec(point.position()))
        point_ids.append(point.number())
        numbers.append(int(point.attribValue(number_attrib)) if number_attrib is not None else point.number())
    cumulative = [0.0]
    for index in range(1, len(points)):
        cumulative.append(cumulative[-1] + points[index].distanceTo(points[index - 1]))
    return {
        "prim": prim,
        "points": points,
        "point_ids": point_ids,
        "numbers": numbers,
        "cum": cumulative,
        "length": cumulative[-1] if cumulative else 0.0,
    }
def closest_length_on_polyline(line, position):
    points = line["points"]
    if not points:
        return {"length": 0.0, "point": hou.Vector3(0.0, 0.0, 0.0), "distance": 0.0}
    if len(points) == 1:
        return {"length": 0.0, "point": points[0], "distance": points[0].distanceTo(position)}
    best = None
    for index in range(len(points) - 1):
        a = points[index]
        b = points[index + 1]
        delta = b - a
        denom = delta.dot(delta)
        amount = 0.0 if denom <= EPS else clamp((position - a).dot(delta) / denom, 0.0, 1.0)
        projected = a + delta * amount
        distance = projected.distanceTo(position)
        length = line["cum"][index] + (line["cum"][index + 1] - line["cum"][index]) * amount
        if best is None or distance < best["distance"]:
            best = {"length": length, "point": projected, "distance": distance, "segment": index}
    return best

def find_centerline_intersection(lines, fallback_position):
    occurrences = {}
    for line_index, line in enumerate(lines):
        for vertex_index, point_id in enumerate(line["point_ids"]):
            entry = occurrences.setdefault(point_id, {
                "lines": set(),
                "position": line["points"][vertex_index],
            })
            entry["lines"].add(line_index)
    candidates = [entry for entry in occurrences.values() if len(entry["lines"]) > 1]
    if candidates:
        selected = min(candidates, key=lambda item: item["position"].distanceTo(fallback_position))
        return {"point": selected["position"], "source": "shared_centerline_point"}
    if len(lines) >= 2:
        best, _ = find_best_segment_pair(lines[0], lines[1], 0, len(lines[0]["points"]) - 1, 0, len(lines[1]["points"]) - 1)
        if best is not None:
            return {"point": best["point"], "source": "closest_centerline_pair"}
    if lines:
        selected = min((closest_length_on_polyline(line, fallback_position) for line in lines), key=lambda item: item["distance"])
        return {"point": selected["point"], "source": "closest_centerline_point"}
    return {"point": fallback_position, "source": "fallback_input_rest"}
def select_centerline_for_curve(lines, tangent_rest, intersection_position):
    best = None
    for line_index, line in enumerate(lines):
        tangent = closest_length_on_polyline(line, tangent_rest)
        intersection = closest_length_on_polyline(line, intersection_position)
        score = tangent["distance"] + intersection["distance"]
        if best is None or score < best["score"]:
            best = {
                "line_index": line_index,
                "line": line,
                "tangent": tangent,
                "intersection": intersection,
                "score": score,
            }
    return best
def directed_index_range(start_index, end_index):
    step = 1 if end_index >= start_index else -1
    return list(range(start_index, end_index + step, step))
def build_centerline_curve(entries, intersection_index, tangent_index, line_info, centerline_intersection):
    positions = []
    weights = []
    if line_info is None:
        for entry in entries:
            positions.append(entry.get("rest", entry["position"]))
            weights.append(0.0)
        return positions, weights, {"projected_count": 0, "line_index": -1}
    line = line_info["line"]
    tangent_length = line_info["tangent"]["length"]
    intersection_length = line_info["intersection"]["length"]
    path_indices = directed_index_range(tangent_index, intersection_index)
    rank_by_index = {index: rank for rank, index in enumerate(path_indices)}
    rank_max = max(len(path_indices) - 1, 1)
    for index, entry in enumerate(entries):
        if index in rank_by_index:
            amount = float(rank_by_index[index]) / float(rank_max)
            length = tangent_length + (intersection_length - tangent_length) * amount
            # Snap the rung's centerline landing to the nearest real centerline
            # vertex (by arc length) instead of an interpolated position, so the
            # road surface connects to actual centerline points. Endpoints stay
            # pinned to the geometric anchors below.
            cum = line["cum"]
            vidx = bisect.bisect_left(cum, length)
            if vidx <= 0:
                vidx = 0
            elif vidx >= len(cum):
                vidx = len(cum) - 1
            elif (length - cum[vidx - 1]) <= (cum[vidx] - length):
                vidx = vidx - 1
            position = line["points"][vidx]
            if index == tangent_index:
                position = line_info["tangent"]["point"]
            if index == intersection_index:
                position = centerline_intersection
            positions.append(position)
            weights.append(1.0)
        else:
            positions.append(entry.get("rest", entry["position"]))
            weights.append(0.0)
    return positions, weights, {
        "projected_count": len(path_indices),
        "line_index": int(line_info["line_index"]),
        "tangent_length": float(tangent_length),
        "intersection_length": float(intersection_length),
        "tangent_distance": float(line_info["tangent"]["distance"]),
        "intersection_distance": float(line_info["intersection"]["distance"]),
    }
def ordered_indices_to_intersection(positions, intersection_index):
    from_start = list(range(0, intersection_index + 1))
    from_end = list(range(len(positions) - 1, intersection_index - 1, -1))
    return from_start if len(from_start) >= len(from_end) else from_end
def ordered_indices_from_intersection(positions, intersection_index):
    to_end = list(range(intersection_index, len(positions)))
    to_start = list(range(intersection_index, -1, -1))
    return to_end if len(to_end) >= len(to_start) else to_start
def stitch_quads_aligned(edge_points, centerline_points):
    """Zip two index-aligned, equal-length rows into pure quads.
    edge_points[k] and centerline_points[k] are the same source vertex pushed
    apart laterally, so every step is a clean same-source quad. No triangles,
    no nearest-vertex search.
    """
    count = min(len(edge_points), len(centerline_points))
    for k in range(count - 1):
        yield [
            edge_points[k],
            edge_points[k + 1],
            centerline_points[k + 1],
            centerline_points[k],
        ]
def signed_area_xz(points):
    if len(points) < 3:
        return 0.0
    area = 0.0
    for index, point in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        pos = point.position()
        nxt_pos = nxt.position()
        area += float(pos.x()) * float(nxt_pos.z()) - float(nxt_pos.x()) * float(pos.z())
    return area * 0.5
def polygon_span_ok(points):
    unique_positions = []
    for point in points:
        pos = point.position()
        if all(pos.distanceTo(existing) > 1.0e-6 for existing in unique_positions):
            unique_positions.append(pos)
    return len(unique_positions) >= 3 and abs(signed_area_xz(points)) > 1.0e-8
def choose_far_source_index_on_segment(entries, target_length, direction):
    if len(entries) <= 1:
        return 0
    tolerance = max(entries[-1]["length"] * SOURCE_POINT_LENGTH_TOLERANCE, SOURCE_POINT_LENGTH_TOLERANCE)
    if direction >= 0.0:
        for index, entry in enumerate(entries):
            if entry["length"] >= target_length - tolerance:
                return index
        return len(entries) - 1
    for index in range(len(entries) - 1, -1, -1):
        if entries[index]["length"] <= target_length + tolerance:
            return index
    return 0
def source_index_range(a, b):
    low = min(a, b)
    high = max(a, b)
    return list(range(low, high + 1))
def ensure_distinct_source_indices(entries, start_index, end_index, direction, label):
    if start_index != end_index:
        return end_index
    step = 1 if direction >= 0.0 else -1
    candidate = end_index + step
    if 0 <= candidate < len(entries):
        return candidate
    raise hou.NodeError(
        "%s needs at least two original source points on the selected side. Increase the distance or add source points."
        % label
    )
def effective_tangent_after_trim(entries, inter_idx, tan_idx, default_fraction, arc_hits, intersection_arc_fraction):
    # The tangent circle is built so its theoretical contact point sits at the
    # interface (default_fraction). When the source curve bends back into the
    # circle, the arc crosses the curve again *before* reaching that interface,
    # i.e. an extra contact nearer the crossing. That extra contact is what the
    # user wants to keep as the real tangent point; the arc is shortened to it
    # and everything past it falls back to the untouched source curve.
    #
    # The theoretical interface contact lands on the segment boundary and is not
    # reported in arc_hits, so a single reported hit already means "two contacts
    # on this curve". Trigger on any in-range hit, then keep the one closest to
    # the crossing (smallest near_distance to the projected intersection).
    if not arc_hits:
        return tan_idx, default_fraction, False, None
    tolerance = max(abs(intersection_arc_fraction) * 1.0e-4, 1.0e-6)
    fraction_low = min(default_fraction, intersection_arc_fraction)
    fraction_high = max(default_fraction, intersection_arc_fraction)
    candidates = []
    for hit in arc_hits:
        frac = hit["fraction"]
        if frac < fraction_low - tolerance or frac > fraction_high + tolerance:
            continue
        if abs(frac - default_fraction) <= tolerance:
            continue
        candidates.append(hit)
    if not candidates:
        return tan_idx, default_fraction, False, None
    nearest = min(candidates, key=lambda hit: hit["near_distance"])
    new_fraction = nearest["fraction"]
    new_length = nearest["curve_length"]
    direction = 1.0 if tan_idx >= inter_idx else -1.0
    new_tan_idx = choose_far_source_index_on_segment(entries, new_length, direction)
    if tan_idx >= inter_idx:
        new_tan_idx = max(inter_idx + 1, min(new_tan_idx, tan_idx))
    else:
        new_tan_idx = min(inter_idx - 1, max(new_tan_idx, tan_idx))
    if new_tan_idx == inter_idx or new_tan_idx == tan_idx:
        return tan_idx, default_fraction, False, None
    info = {
        "raw_tan_idx": int(tan_idx),
        "new_tan_idx": int(new_tan_idx),
        "new_fraction": float(new_fraction),
        "new_length": float(new_length),
        "near_distance": float(nearest["near_distance"]),
        "hit_count": int(len(arc_hits)),
    }
    return new_tan_idx, new_fraction, True, info
def build_modified_curve(entries, intersection_index, tangent_index, tangent_fraction, center, start_vec, plane_normal, arc_angle, intersection_arc_fraction):
    if intersection_index == tangent_index:
        raise hou.NodeError("The snapped intersection and interface point resolved to the same original point.")
    lengths = [entry["length"] for entry in entries]
    cut_indices = source_index_range(intersection_index, tangent_index)
    cut_index_set = set(cut_indices)
    positions = []
    weights = []
    fraction_low = min(intersection_arc_fraction, tangent_fraction)
    fraction_high = max(intersection_arc_fraction, tangent_fraction)
    length_low = lengths[intersection_index]
    length_high = lengths[tangent_index]
    length_span = length_high - length_low
    for index, entry in enumerate(entries):
        if index in cut_index_set:
            weights.append(1.0)
            amount = clamp((entry["length"] - length_low) / length_span, 0.0, 1.0)
            fraction = intersection_arc_fraction + (tangent_fraction - intersection_arc_fraction) * amount
            positions.append(arc_point_at_fraction(center, start_vec, plane_normal, arc_angle, clamp(fraction, fraction_low, fraction_high)))
        else:
            weights.append(0.0)
            positions.append(entry["position"])
    positions[intersection_index] = arc_point_at_fraction(center, start_vec, plane_normal, arc_angle, intersection_arc_fraction)
    positions[tangent_index] = arc_point_at_fraction(center, start_vec, plane_normal, arc_angle, tangent_fraction)
    return positions, weights, intersection_index, tangent_index
def _orient_arm(line, crossing, end_at_crossing):
    """Order a centre-line polyline's vertex indices relative to the crossing.
    end_at_crossing=True  -> the returned order runs far-endpoint .. crossing
    end_at_crossing=False -> the returned order runs crossing .. far-endpoint
    Keeps every real vertex of the polyline; only the direction may flip.
    """
    pts = line["points"]
    if not pts:
        return []
    order = list(range(len(pts)))
    end_is_nearer = pts[-1].distanceTo(crossing) <= pts[0].distanceTo(crossing)
    if end_at_crossing and not end_is_nearer:
        order.reverse()
    if (not end_at_crossing) and end_is_nearer:
        order.reverse()
    return order
def build_real_centerline_sequence(line0, line1, crossing):
    """Concatenate the two corner centre-line arms into one ordered vertex run.
    Walks arm0 from its far endpoint into the crossing, then arm1 from the
    crossing out to its far endpoint, dropping arm1's duplicate crossing vertex.
    Every real centre-line vertex is preserved (no resampling / snapping).
    Returns a list of (position, number) tuples.
    """
    order0 = _orient_arm(line0, crossing, True)
    order1 = _orient_arm(line1, crossing, False)
    seq = [(line0["points"][i], line0["numbers"][i]) for i in order0]
    tail = [(line1["points"][i], line1["numbers"][i]) for i in order1]
    if seq:
        seq[-1] = (crossing, seq[-1][1])
    if seq and tail and tail[0][0].distanceTo(seq[-1][0]) < 0.5:
        tail = tail[1:]
    return seq + tail

def select_arc_curve_prims(geometry):
    """Pick the two offset boundary polylines the tangent arc is fitted between.
    The input is a per-corner bundle of polylines tagged with a string prim
    attribute ``line_role`` ("offset" boundary vs "center" line). The arc is
    fitted between the two ``offset`` polylines.
    """
    role_attrib = geometry.findPrimAttrib("line_role")
    if role_attrib is None:
        raise hou.NodeError(
            "Input geometry is missing the 'line_role' primitive attribute. "
            "Connect the offset/center polylines from road_offset_stitch."
        )
    return [
        prim for prim in geometry.prims()
        if prim.attribValue(role_attrib) == "offset"
    ]

def set_global(name, value):
    if isinstance(value, hou.Vector3):
        default = (0.0, 0.0, 0.0)
        stored = tuple(value)
    elif isinstance(value, bool):
        default = 0
        stored = int(value)
    elif isinstance(value, int):
        default = 0
        stored = value
    elif isinstance(value, float):
        default = 0.0
        stored = value
    else:
        default = ""
        stored = str(value)
    if _arc_geo.findGlobalAttrib(name) is None:
        _arc_geo.addAttrib(hou.attribType.Global, name, default)
    _arc_geo.setGlobalAttribValue(name, stored)

def centerline_polylines_from_input():
    lines = []
    for prim in _arc_centre_geo.prims():
        if len(prim.vertices()) >= 2:
            lines.append(polyline_from_prim(prim))
    return lines


def _corner_position_from_geo(geo):
    if geo is None:
        return None
    corner_attr = geo.findPrimAttrib("corner_position")
    if corner_attr is None:
        return None
    prims = list(geo.prims())
    if not prims:
        return None
    return hou.Vector3(prims[0].attribValue(corner_attr))


def _positive_prim_values(geo, name):
    if geo is None:
        return []
    attrib = geo.findPrimAttrib(name)
    if attrib is None:
        return []
    return [
        float(prim.attribValue(attrib))
        for prim in geo.prims()
        if float(prim.attribValue(attrib)) > EPS
    ]


def _positive_point_values(geo, name):
    if geo is None:
        return []
    attrib = geo.findPointAttrib(name)
    if attrib is None:
        return []
    return [
        float(point.attribValue(attrib))
        for point in geo.points()
        if float(point.attribValue(attrib)) > EPS
    ]


def _arc_distance_from_pscale(*geometries):
    checks = (
        ("prim", "corner_pscale"),
        ("point", "pscale"),
        ("prim", "corner_keep_distance"),
    )
    for kind, name in checks:
        values = []
        for geo in geometries:
            if kind == "prim":
                values.extend(_positive_prim_values(geo, name))
            else:
                values.extend(_positive_point_values(geo, name))
        if values:
            return max(values), name
    raise hou.NodeError("No positive pscale value found to drive the tangent arc distance.")


def _run_arc(arc_out, bundle_geo, centre_geo, real_node, source_geo=None):
    global _arc_node, _arc_geo, _arc_legacy_ctrl, _arc_centre_geo
    _arc_node = real_node
    _arc_geo = arc_out
    _arc_legacy_ctrl = real_node.parent().node("CTRL")
    _arc_centre_geo = centre_geo

    geo = arc_out
    cook_start = time.perf_counter()
    requested_distance, requested_distance_source = _arc_distance_from_pscale(
        centre_geo, bundle_geo, source_geo
    )
    curve_prims = select_arc_curve_prims(geo)
    if len(curve_prims) < 2:
        raise hou.NodeError("Expected at least two curve primitives in the input geometry.")
    if len(curve_prims) > 2:
        warn("More than two curves found. Using primitive 0 and primitive 1.")
    curve0_full = sample_curve(curve_prims[0], SAMPLES)
    curve1_full = sample_curve(curve_prims[1], SAMPLES)
    c0_len = curve0_full["length"]
    c1_len = curve1_full["length"]
    intersection = find_curve_intersection(curve0_full, curve1_full)
    intersection_length0 = clamp(intersection["curve0_length"], 0.0, c0_len)
    intersection_length1 = clamp(intersection["curve1_length"], 0.0, c1_len)
    intersection_point = intersection["point"]
    direction0 = auto_direction(curve0_full, intersection_length0, requested_distance)
    direction1 = auto_direction(curve1_full, intersection_length1, requested_distance)
    max_distance0 = c0_len - intersection_length0 if direction0 > 0.0 else intersection_length0
    max_distance1 = c1_len - intersection_length1 if direction1 > 0.0 else intersection_length1
    max_distance = min(max_distance0, max_distance1)
    if max_distance <= EPS:
        raise hou.NodeError("The selected curve side has no length after the intersection.")
    distance_was_clamped = False
    if requested_distance <= 0.0:
        requested_distance = max_distance * 0.25
        distance_was_clamped = True
        warn("Distance was <= 0, so a quarter of the available curve length was used.")
    if requested_distance >= max_distance:
        distance_was_clamped = True
        warn("Distance was clamped to the available selected curve side length.")
    distance = clamp(requested_distance, max_distance * 1.0e-5, max_distance * 0.999)
    length0 = intersection_length0 + direction0 * distance
    length1 = intersection_length1 + direction1 * distance
    curve0_entries = source_entries_for_curve(curve0_full)
    curve1_entries = source_entries_for_curve(curve1_full)
    curve0_inter_idx = choose_far_source_index_on_segment(curve0_entries, intersection_length0, direction0)
    curve1_inter_idx = choose_far_source_index_on_segment(curve1_entries, intersection_length1, direction1)
    curve0_tan_idx = choose_far_source_index_on_segment(curve0_entries, length0, direction0)
    curve1_tan_idx = choose_far_source_index_on_segment(curve1_entries, length1, direction1)
    curve0_tan_idx = ensure_distinct_source_indices(curve0_entries, curve0_inter_idx, curve0_tan_idx, direction0, "Curve 0")
    curve1_tan_idx = ensure_distinct_source_indices(curve1_entries, curve1_inter_idx, curve1_tan_idx, direction1, "Curve 1")
    cd0_inter = curve0_entries[curve0_inter_idx]
    cd1_inter = curve1_entries[curve1_inter_idx]
    cd0_tan = curve0_entries[curve0_tan_idx]
    cd1_tan = curve1_entries[curve1_tan_idx]
    intersection_length0 = cd0_inter["length"]
    intersection_length1 = cd1_inter["length"]
    length0 = cd0_tan["length"]
    length1 = cd1_tan["length"]
    snapped_distance0 = abs(length0 - intersection_length0)
    snapped_distance1 = abs(length1 - intersection_length1)
    intersection_point = (cd0_inter["position"] + cd1_inter["position"]) * 0.5
    p0 = cd0_tan["position"]
    p1 = cd1_tan["position"]
    u0 = 0.0 if c0_len <= EPS else clamp(length0 / c0_len, 0.0, 1.0)
    u1 = 0.0 if c1_len <= EPS else clamp(length1 / c1_len, 0.0, 1.0)
    tangent0 = tangent_at_length(curve0_full, length0)
    tangent1 = tangent_at_length(curve1_full, length1)
    base_tangent0 = tangent_at_length(curve0_full, intersection_length0)
    base_tangent1 = tangent_at_length(curve1_full, intersection_length1)
    plane_normal = base_tangent0.cross(base_tangent1)
    plane_normal = hou.Vector3(0.0, 1.0, 0.0) if plane_normal.length() <= EPS else plane_normal.normalized()
    normal_result = intersect_normal_lines(p0, tangent0, p1, tangent1, plane_normal)
    if normal_result is None:
        raise hou.NodeError("Could not build the projection guide from the two tangent normals.")
    raw_center = normal_result["center"]
    raw_radius_error = normal_result["radius_error"]
    raw_radius0 = normal_result["radius0"]
    raw_radius1 = normal_result["radius1"]
    center = project_center_to_equal_radii(raw_center, p0, p1)
    radius0 = (center - p0).length()
    radius1 = (center - p1).length()
    radius = (radius0 + radius1) * 0.5
    if radius <= EPS:
        raise hou.NodeError("The computed projection guide radius is too small.")
    center_offset0 = point_line_distance(center, p0, normal_result["normal0"])
    center_offset1 = point_line_distance(center, p1, normal_result["normal1"])
    tangent_dot0 = abs((center - p0).normalized().dot(tangent0))
    tangent_dot1 = abs((center - p1).normalized().dot(tangent1))
    exact_tangent = (
        center_offset0 <= max(1.0e-5, radius * 1.0e-5)
        and center_offset1 <= max(1.0e-5, radius * 1.0e-5)
        and tangent_dot0 <= 1.0e-4
        and tangent_dot1 <= 1.0e-4
    )
    if not exact_tangent:
        warn("Distance pins the two interface points. This distance is not an exact two-tangent circle for the current curves; see arc_tangent_dot0/1.")
    start_vec = p0 - center
    end_vec = p1 - center
    arc_angle, intersection_arc_fraction, projected_intersection = choose_arc_angle(
        center, start_vec, end_vec, plane_normal, intersection_point
    )
    curve0_arc_hits = find_source_segment_arc_intersections(
        curve0_full, intersection_length0, length0, center, radius, start_vec, plane_normal, arc_angle, intersection_point
    )
    curve1_arc_hits = find_source_segment_arc_intersections(
        curve1_full, intersection_length1, length1, center, radius, start_vec, plane_normal, arc_angle, intersection_point
    )
    curve_arc_trim_candidate = trim_intersection_to_nearest_curve_hit(
        curve0_arc_hits, curve1_arc_hits, intersection_arc_fraction, projected_intersection
    )
    curve0_tan_fraction = 0.0
    curve1_tan_fraction = 1.0
    curve0_tan_idx, curve0_tan_fraction, curve0_trimmed, curve0_trim_info = effective_tangent_after_trim(
        curve0_entries, curve0_inter_idx, curve0_tan_idx, curve0_tan_fraction, curve0_arc_hits, intersection_arc_fraction
    )
    curve1_tan_idx, curve1_tan_fraction, curve1_trimmed, curve1_trim_info = effective_tangent_after_trim(
        curve1_entries, curve1_inter_idx, curve1_tan_idx, curve1_tan_fraction, curve1_arc_hits, intersection_arc_fraction
    )
    if curve0_trimmed:
        cd0_tan = curve0_entries[curve0_tan_idx]
        p0 = cd0_tan["position"]
        length0 = cd0_tan["length"]
        snapped_distance0 = abs(length0 - intersection_length0)
    if curve1_trimmed:
        cd1_tan = curve1_entries[curve1_tan_idx]
        p1 = cd1_tan["position"]
        length1 = cd1_tan["length"]
        snapped_distance1 = abs(length1 - intersection_length1)
    trim_info = {
        "trimmed": bool(curve0_trimmed or curve1_trimmed),
        "fraction": intersection_arc_fraction,
        "point": projected_intersection,
        "side": 0 if curve0_trimmed else (1 if curve1_trimmed else -1),
    }
    curve0_positions, curve0_weights, curve0_inter_idx, curve0_tan_idx = build_modified_curve(
        curve0_entries, curve0_inter_idx, curve0_tan_idx, curve0_tan_fraction, center, start_vec, plane_normal, arc_angle, intersection_arc_fraction
    )
    curve1_positions, curve1_weights, curve1_inter_idx, curve1_tan_idx = build_modified_curve(
        curve1_entries, curve1_inter_idx, curve1_tan_idx, curve1_tan_fraction, center, start_vec, plane_normal, arc_angle, intersection_arc_fraction
    )
    centerline_lines = centerline_polylines_from_input()
    forced_centerline_intersection = (
        _corner_position_from_geo(_arc_centre_geo)
        or _corner_position_from_geo(source_geo)
    )
    if forced_centerline_intersection is not None:
        centerline_intersection_info = {
            "point": forced_centerline_intersection,
            "source": "corner_position",
        }
    else:
        centerline_intersection_info = find_centerline_intersection(centerline_lines, intersection_point)
    centerline_intersection = centerline_intersection_info["point"]
    curve0_centerline_info = select_centerline_for_curve(centerline_lines, cd0_tan["rest"], centerline_intersection)
    curve1_centerline_info = select_centerline_for_curve(centerline_lines, cd1_tan["rest"], centerline_intersection)
    curve0_centerline_positions, curve0_centerline_weights, curve0_centerline_stats = build_centerline_curve(
        curve0_entries, curve0_inter_idx, curve0_tan_idx, curve0_centerline_info, centerline_intersection
    )
    curve1_centerline_positions, curve1_centerline_weights, curve1_centerline_stats = build_centerline_curve(
        curve1_entries, curve1_inter_idx, curve1_tan_idx, curve1_centerline_info, centerline_intersection
    )
    centerline_indices0 = ordered_indices_to_intersection(curve0_centerline_positions, curve0_inter_idx)
    centerline_indices1 = ordered_indices_from_intersection(curve1_centerline_positions, curve1_inter_idx)
    geo.clear()
    role_attrib = geo.addAttrib(hou.attribType.Point, "arc_role", "")
    side_attrib = geo.addAttrib(hou.attribType.Point, "arc_side", -1)
    weight_attrib = geo.addAttrib(hou.attribType.Point, "arc_project_weight", 0.0)
    rest_attrib = geo.addAttrib(hou.attribType.Point, "rest", (0.0, 0.0, 0.0))
    centerline_weight_attrib = geo.addAttrib(hou.attribType.Point, "arc_centerline_project_weight", 0.0)
    number_attrib = geo.addAttrib(hou.attribType.Point, "number", -1)
    is_arc_attrib = geo.addAttrib(hou.attribType.Point, "is_arc", 0)
    interface_group = geo.createPointGroup("arc_interface_points")
    intersection_group = geo.createPointGroup("arc_intersection_point")
    projected_group = geo.createPointGroup("arc_projected_segment_points")
    centerline_point_group = geo.createPointGroup("arc_centerline_points")
    original_group = geo.createPrimGroup("modified_original_curves")
    centerline_group = geo.createPrimGroup("arc_centerline_curve")
    road_surface_group = geo.createPrimGroup("arc_road_surface")
    def create_point(position, role, side, weight, rest=None, centerline_weight=0.0, number=-1):
        point = geo.createPoint()
        point.setPosition(position)
        point.setAttribValue(role_attrib, role)
        point.setAttribValue(side_attrib, int(side))
        point.setAttribValue(weight_attrib, float(weight))
        point.setAttribValue(rest_attrib, tuple(rest if rest is not None else position))
        point.setAttribValue(centerline_weight_attrib, float(centerline_weight))
        point.setAttribValue(number_attrib, int(number))
        return point
    def add_modified_curve(entries, positions, weights, inter_idx, tan_idx, side):
        poly = geo.createPolygon()
        poly.setIsClosed(False)
        points = []
        for index, position in enumerate(positions):
            rest = entries[index].get("rest", entries[index]["position"])
            number = entries[index].get("number", -1)
            if index == inter_idx:
                point = create_point(position, "projected_intersection", side, 1.0, rest, 0.0, number)
                intersection_group.add(point)
            elif index == tan_idx:
                point = create_point(position, "interface", side, 1.0, rest, 0.0, number)
                interface_group.add(point)
            else:
                role = "projected_original_curve" if weights[index] > 0.0 else "source_original_curve"
                point = create_point(position, role, side, weights[index], rest, 0.0, number)
                if weights[index] > 0.0:
                    projected_group.add(point)
            poly.addVertex(point)
            points.append(point)
        original_group.add(poly)
        return poly, points
    def add_centerline_curve():
        poly = geo.createPolygon()
        poly.setIsClosed(False)
        points = []
        for index in centerline_indices0:
            rest = curve0_entries[index].get("rest", curve0_entries[index]["position"])
            number = curve0_entries[index].get("number", -1)
            role = "centerline_projected" if curve0_centerline_weights[index] > 0.0 else "centerline_rest"
            if index == curve0_inter_idx:
                role = "centerline_intersection"
            elif index == curve0_tan_idx:
                role = "centerline_interface"
            point = create_point(
                curve0_centerline_positions[index],
                role,
                2,
                curve0_weights[index],
                rest,
                curve0_centerline_weights[index],
                number,
            )
            centerline_point_group.add(point)
            poly.addVertex(point)
            points.append(point)
        for index in centerline_indices1:
            if index == curve1_inter_idx:
                continue
            rest = curve1_entries[index].get("rest", curve1_entries[index]["position"])
            number = curve1_entries[index].get("number", -1)
            role = "centerline_projected" if curve1_centerline_weights[index] > 0.0 else "centerline_rest"
            if index == curve1_tan_idx:
                role = "centerline_interface"
            point = create_point(
                curve1_centerline_positions[index],
                role,
                2,
                curve1_weights[index],
                rest,
                curve1_centerline_weights[index],
                number,
            )
            centerline_point_group.add(point)
            poly.addVertex(point)
            points.append(point)
        centerline_group.add(poly)
        return poly, points
    _, curve0_points = add_modified_curve(curve0_entries, curve0_positions, curve0_weights, curve0_inter_idx, curve0_tan_idx, 0)
    _, curve1_points = add_modified_curve(curve1_entries, curve1_positions, curve1_weights, curve1_inter_idx, curve1_tan_idx, 1)
    _, centerline_points = add_centerline_curve()
    # --- Road surface: every real centerline vertex preserved, projected to the arc edge. ---
    # Map displayed arc-edge positions back to real centerline vertices. Source
    # numbers are mirrored on extract V curves, so use each offset point's rest
    # position as the disambiguating key instead of treating number as unique.
    arc_edge_records = []
    for i, pt in enumerate(curve0_points):
        num = int(curve0_entries[i].get("number", -1))
        arc_edge_records.append({
            "number": num,
            "rest": hou.Vector3(curve0_entries[i].get("rest", pt.position())),
            "position": pt.position(),
            "weight": curve0_weights[i],
        })
    for i, pt in enumerate(curve1_points):
        num = int(curve1_entries[i].get("number", -1))
        arc_edge_records.append({
            "number": num,
            "rest": hou.Vector3(curve1_entries[i].get("rest", pt.position())),
            "position": pt.position(),
            "weight": curve1_weights[i],
        })
    if len(centerline_lines) >= 2:
        real_center_seq = build_real_centerline_sequence(
            centerline_lines[0], centerline_lines[1], centerline_intersection
        )
    elif centerline_lines:
        line = centerline_lines[0]
        real_center_seq = list(zip(line["points"], line["numbers"]))
    else:
        real_center_seq = []
    def project_edge_to_arc(pos):
        frac = fraction_for_point_on_arc(pos, center, start_vec, plane_normal, arc_angle)
        return arc_point_at_fraction(center, start_vec, plane_normal, arc_angle, frac), frac
    def matching_arc_edge_record(position, number):
        if not arc_edge_records:
            return None
        same_number = [
            record for record in arc_edge_records
            if int(record["number"]) == int(number)
        ]
        candidates = same_number or arc_edge_records
        best = min(
            candidates,
            key=lambda record: record["rest"].distanceTo(position),
        )
        tolerance = 0.25 if same_number else 1.0
        if best["rest"].distanceTo(position) > tolerance:
            return None
        return best
    # Edge row per centerline vertex. Straight runs reuse the parallel arc-edge
    # vertex (same source number). Each rounded run (vertices the offset edge had
    # trimmed away) is filled by an arc-length parameterised sweep between its two
    # flanking straight anchors, so the rounded edge points stay monotonic and
    # evenly spread on the arc instead of fanning out and overlapping.
    seq_positions = [position for position, _ in real_center_seq]
    edge_records = [
        matching_arc_edge_record(position, number)
        for position, number in real_center_seq
    ]
    edge_positions = [
        record["position"] if record is not None else None
        for record in edge_records
    ]
    arc_edge_indices = {
        i for i, record in enumerate(edge_records)
        if record is None or record["weight"] > 0.0
    }
    n_seq = len(real_center_seq)
    k = 0
    while k < n_seq:
        if edge_positions[k] is not None:
            k += 1
            continue
        start = k
        while k < n_seq and edge_positions[k] is None:
            k += 1
        end = k - 1
        left = start - 1 if start >= 1 else None
        right = end + 1 if end + 1 < n_seq else None
        if left is None or right is None:
            for i in range(start, end + 1):
                edge_positions[i], _ = project_edge_to_arc(seq_positions[i])
            continue
        _, frac_left = project_edge_to_arc(edge_positions[left])
        _, frac_right = project_edge_to_arc(edge_positions[right])
        span_idx = list(range(left, right + 1))
        cum = [0.0]
        for j in range(1, len(span_idx)):
            cum.append(
                cum[-1] + seq_positions[span_idx[j]].distanceTo(seq_positions[span_idx[j - 1]])
            )
        total = cum[-1] if cum[-1] > EPS else 1.0
        for rank, i in enumerate(span_idx):
            if i < start or i > end:
                continue
            amount = cum[rank] / total
            frac = frac_left + (frac_right - frac_left) * amount
            edge_positions[i] = arc_point_at_fraction(
                center, start_vec, plane_normal, arc_angle, frac
            )
    # Even-distribution pass for is_arc edge points. The marked points form one
    # contiguous run whose two ends are the tangent interface points. Spread the
    # whole run's arc fractions uniformly by angle so the degenerate spans that
    # bunched up at a single spot get pulled out into an even fan on the circle.
    marked_arc_idx = [
        i for i in range(n_seq)
        if i in arc_edge_indices
    ]
    if len(marked_arc_idx) >= 2:
        frac_start = project_edge_to_arc(edge_positions[marked_arc_idx[0]])[1]
        frac_end = project_edge_to_arc(edge_positions[marked_arc_idx[-1]])[1]
        last_rank = len(marked_arc_idx) - 1
        for rank, i in enumerate(marked_arc_idx):
            frac = frac_start + (frac_end - frac_start) * (float(rank) / last_rank)
            edge_positions[i] = arc_point_at_fraction(
                center, start_vec, plane_normal, arc_angle, frac
            )
    centerline_points = []
    edge_points = []
    for idx, (position, number) in enumerate(real_center_seq):
        center_pt = create_point(position, "centerline_real", 2, 1.0, None, 0.0, int(number))
        centerline_point_group.add(center_pt)
        centerline_points.append(center_pt)
        edge_pt = create_point(
            edge_positions[idx], "road_surface_edge", 2, 0.0, None, 0.0, int(number)
        )
        on_arc = idx in arc_edge_indices
        edge_pt.setAttribValue(is_arc_attrib, 1 if on_arc else 0)
        edge_points.append(edge_pt)
    road_surface_count = 0
    road_surface_tris = 0
    road_surface_quads = 0
    for face_points in stitch_quads_aligned(edge_points, centerline_points):
        if not polygon_span_ok(face_points):
            continue
        poly = geo.createPolygon()
        poly.setIsClosed(True)
        for point in face_points:
            poly.addVertex(point)
        road_surface_group.add(poly)
        road_surface_count += 1
        if len(face_points) == 3:
            road_surface_tris += 1
        else:
            road_surface_quads += 1
    set_global("arc_center", center)
    set_global("arc_radius", float(radius))
    set_global("arc_intersection", intersection_point)
    set_global("arc_projected_intersection", projected_intersection)
    set_global("arc_projected_intersection_fraction", float(intersection_arc_fraction))
    set_global("arc_curve0_arc_intersections", int(len(curve0_arc_hits)))
    set_global("arc_curve1_arc_intersections", int(len(curve1_arc_hits)))
    set_global("arc_trimmed_to_curve_intersection", int(trim_info["trimmed"]))
    set_global("arc_curve0_trimmed", int(curve0_trimmed))
    set_global("arc_curve1_trimmed", int(curve1_trimmed))
    set_global("arc_trim_selected_side", int(trim_info["side"]))
    set_global("arc_curve_arc_trim_candidate", int(curve_arc_trim_candidate["trimmed"]))
    set_global("arc_curve_arc_trim_candidate_side", int(curve_arc_trim_candidate["side"]))
    set_global("arc_trim_selected_fraction", float(intersection_arc_fraction))
    set_global("arc_projection_arc0_fraction_min", float(min(intersection_arc_fraction, 0.0)))
    set_global("arc_projection_arc0_fraction_max", float(max(intersection_arc_fraction, 0.0)))
    set_global("arc_projection_arc1_fraction_min", float(min(intersection_arc_fraction, 1.0)))
    set_global("arc_projection_arc1_fraction_max", float(max(intersection_arc_fraction, 1.0)))
    set_global("arc_projection_trim_mode", "disabled_original_points_only")
    set_global("arc_tangent0", p0)
    set_global("arc_tangent1", p1)
    set_global("arc_equal_distance", float(distance))
    set_global("arc_requested_distance", float(requested_distance))
    set_global("arc_requested_distance_source", requested_distance_source)
    set_global("arc_max_distance", float(max_distance))
    set_global("arc_snapped_distance0", float(snapped_distance0))
    set_global("arc_snapped_distance1", float(snapped_distance1))
    set_global("arc_distance_was_clamped", int(distance_was_clamped))
    set_global("arc_solve_mode", "distance_only")
    set_global("arc_output_mode", "modify_original_curves_with_centerline_and_road_surface")
    set_global("arc_projection_direction", "original_segment_to_arc")
    set_global("arc_projection_weight_mode", "source_index_range_linear")
    set_global("arc_projection_method", "original_points_only_no_insert")
    set_global("arc_projection_smooth_passes", 0)
    set_global("arc_radius_error", float(radius0 - radius1))
    set_global("arc_raw_radius_error", float(raw_radius_error))
    set_global("arc_raw_radius0", float(raw_radius0))
    set_global("arc_raw_radius1", float(raw_radius1))
    set_global("arc_normal_line_gap", float(normal_result["line_gap"]))
    set_global("arc_center_normal_offset0", float(center_offset0))
    set_global("arc_center_normal_offset1", float(center_offset1))
    set_global("arc_tangent_dot0", float(tangent_dot0))
    set_global("arc_tangent_dot1", float(tangent_dot1))
    set_global("arc_exact_tangent", int(exact_tangent))
    set_global("arc_angle_radians", float(arc_angle))
    set_global("arc_curve0_u", float(u0))
    set_global("arc_curve1_u", float(u1))
    set_global("arc_curve0_direction", int(direction0))
    set_global("arc_curve1_direction", int(direction1))
    set_global("arc_curve0_intersection_index", int(curve0_inter_idx))
    set_global("arc_curve1_intersection_index", int(curve1_inter_idx))
    set_global("arc_curve0_interface_index", int(curve0_tan_idx))
    set_global("arc_curve1_interface_index", int(curve1_tan_idx))
    set_global("arc_interface_points_created", 0)
    set_global("arc_interface_points_inserted", 0)
    set_global("arc_output_point_policy", "original_points_plus_centerline")
    set_global("arc_projected_segments_created", 1)
    set_global("arc_modified_original_curves", 2)
    set_global("arc_centerline_input_prims", int(len(centerline_lines)))
    set_global("arc_centerline_output_prims", 1)
    set_global("arc_centerline_output_points", int(len(centerline_points)))
    set_global("arc_centerline_intersection", centerline_intersection)
    set_global("arc_centerline_intersection_source", centerline_intersection_info["source"])
    set_global("arc_centerline_curve0_projected_points", int(curve0_centerline_stats["projected_count"]))
    set_global("arc_centerline_curve1_projected_points", int(curve1_centerline_stats["projected_count"]))
    set_global("arc_centerline_curve0_line_index", int(curve0_centerline_stats["line_index"]))
    set_global("arc_centerline_curve1_line_index", int(curve1_centerline_stats["line_index"]))
    set_global("arc_centerline_curve0_tangent_distance", float(curve0_centerline_stats.get("tangent_distance", 0.0)))
    set_global("arc_centerline_curve1_tangent_distance", float(curve1_centerline_stats.get("tangent_distance", 0.0)))
    set_global("arc_road_surface_prims", int(road_surface_count))
    set_global("arc_road_surface_boundary_points", int(len(edge_points)))
    set_global("arc_road_surface_mode", "quads_real_centerline_projected_to_arc")
    set_global("arc_intersection_candidate_checks", int(intersection.get("candidate_checks", 0)))
    set_global("arc_cook_ms", float((time.perf_counter() - cook_start) * 1000.0))


# -- Stitch helpers --
def _offset_copy(source, sign):
    """Push every point along N by sign*pscale (attribwrangle1 / attribwrangle2)."""
    geo = hou.Geometry()
    geo.merge(source)
    for point in geo.points():
        position = point.position()
        normal = hou.Vector3(point.attribValue("N"))
        pscale = point.attribValue("pscale")
        point.setPosition(position + normal * (pscale * sign))
    return geo

def _flatten_y(geo):
    """attribwrangle5: collapse onto the ground plane (P.y = 0)."""
    for point in geo.points():
        position = point.position()
        point.setPosition((position[0], 0.0, position[2]))

def _centre_segments_xz(geo):
    """Original curve edges projected to the XZ plane."""
    segments = []
    for prim in geo.prims():
        points = prim.points()
        for index in range(len(points) - 1):
            a = points[index].position()
            b = points[index + 1].position()
            segments.append(((a[0], a[2]), (b[0], b[2])))
    return segments

def _orient(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

def _segments_cross(p1, p2, p3, p4):
    d1 = _orient(p3, p4, p1)
    d2 = _orient(p3, p4, p2)
    d3 = _orient(p1, p2, p3)
    d4 = _orient(p1, p2, p4)
    straddles_first = (d1 > EPS and d2 < -EPS) or (d1 < -EPS and d2 > EPS)
    straddles_second = (d3 > EPS and d4 < -EPS) or (d3 < -EPS and d4 > EPS)
    return straddles_first and straddles_second

def _prim_crosses_curve(prim, centre_segments):
    points = prim.points()
    for index in range(len(points) - 1):
        a = points[index].position()
        b = points[index + 1].position()
        edge_a = (a[0], a[2])
        edge_b = (b[0], b[2])
        for c1, c2 in centre_segments:
            if _segments_cross(edge_a, edge_b, c1, c2):
                return True
    return False
# --------------------------------------------------------------------------- #
# centre-line stitch + corner pairing helpers
# --------------------------------------------------------------------------- #

def _dist2d(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _source_projection_info(source, position):
    pscale_attr = source.findPointAttrib("pscale")
    px = float(position[0])
    pz = float(position[2])
    best = None
    for prim in source.prims():
        points = prim.points()
        for index in range(1, len(points)):
            a_pos = points[index - 1].position()
            b_pos = points[index].position()
            ax, az = float(a_pos[0]), float(a_pos[2])
            bx, bz = float(b_pos[0]), float(b_pos[2])
            vx, vz = bx - ax, bz - az
            segment_len2 = vx * vx + vz * vz
            if segment_len2 <= EPS:
                continue
            amount = clamp(((px - ax) * vx + (pz - az) * vz) / segment_len2, 0.0, 1.0)
            qx = ax + vx * amount
            qz = az + vz * amount
            dx = px - qx
            dz = pz - qz
            distance = (dx * dx + dz * dz) ** 0.5
            if pscale_attr is not None:
                ps0 = float(points[index - 1].attribValue(pscale_attr))
                ps1 = float(points[index].attribValue(pscale_attr))
                pscale = ps0 * (1.0 - amount) + ps1 * amount
            else:
                pscale = 0.0
            side = vx * dz - vz * dx
            info = {
                "distance": distance,
                "pscale": pscale,
                "side": side,
            }
            if best is None or distance < best["distance"]:
                best = info
    return best


def _offset_distance_stats(prim, source):
    ratios = []
    signs = []
    for point in prim.points():
        info = _source_projection_info(source, point.position())
        if info is None or info["pscale"] <= EPS:
            continue
        ratios.append(info["distance"] / info["pscale"])
        if info["side"] > 1.0e-6:
            signs.append(1)
        elif info["side"] < -1.0e-6:
            signs.append(-1)
    if not ratios:
        return None
    sign_counts = {sign: signs.count(sign) for sign in (-1, 1)}
    side_consistency = 1.0
    dominant_side = 0
    if signs:
        dominant_side = max(sign_counts, key=sign_counts.get)
        side_consistency = float(sign_counts[dominant_side]) / float(len(signs))
    start, end = _prim_ends_xz(prim)
    return {
        "min_ratio": min(ratios),
        "max_ratio": max(ratios),
        "avg_ratio": sum(ratios) / float(len(ratios)),
        "side_consistency": side_consistency,
        "dominant_side": dominant_side,
        "closed": _dist2d(start, end) <= 1.0e-5,
    }


def _valid_offset_prim(prim, source, centre_segments):
    if _prim_crosses_curve(prim, centre_segments):
        return False
    stats = _offset_distance_stats(prim, source)
    if stats is None:
        return True
    if stats["closed"]:
        return False
    if stats["side_consistency"] < 0.8:
        return False
    if stats["min_ratio"] < 0.45 or stats["max_ratio"] > 1.55:
        return False
    return 0.75 <= stats["avg_ratio"] <= 1.25


def _point_record(point):
    geo = point.geometry()
    number_attr = geo.findPointAttrib("number")
    rest_attr = geo.findPointAttrib("rest")
    position = hou.Vector3(point.position())
    return {
        "position": position,
        "number": int(point.attribValue(number_attr)) if number_attr is not None else point.number(),
        "rest": hou.Vector3(point.attribValue(rest_attr)) if rest_attr is not None else position,
    }


def _prim_records(prim):
    return [_point_record(vertex.point()) for vertex in prim.vertices()]


def _record_distance(a, b):
    return a["position"].distanceTo(b["position"])


def _chain_record_fragments(fragments, tolerance=0.25):
    remaining = [list(fragment) for fragment in fragments if len(fragment) >= 2]
    if not remaining:
        return []
    chain = max(remaining, key=len)
    remaining.remove(chain)
    while remaining:
        best = None
        for fragment in remaining:
            tests = (
                (_record_distance(chain[-1], fragment[0]), "append", False, fragment),
                (_record_distance(chain[-1], fragment[-1]), "append", True, fragment),
                (_record_distance(chain[0], fragment[-1]), "prepend", False, fragment),
                (_record_distance(chain[0], fragment[0]), "prepend", True, fragment),
            )
            candidate = min(tests, key=lambda item: item[0])
            if best is None or candidate[0] < best[0]:
                best = candidate
        if best is None or best[0] > tolerance:
            break
        _, mode, reverse_fragment, fragment = best
        ordered = list(reversed(fragment)) if reverse_fragment else list(fragment)
        if mode == "append":
            chain.extend(ordered[1:])
        else:
            chain = ordered[:-1] + chain
        remaining.remove(fragment)
    return chain


def _create_record_polyline(geo, records, role, corner_id):
    if len(records) < 2:
        return None
    number_attr = geo.findPointAttrib("number")
    if number_attr is None:
        number_attr = geo.addAttrib(hou.attribType.Point, "number", -1)
    rest_attr = geo.findPointAttrib("rest")
    if rest_attr is None:
        rest_attr = geo.addAttrib(hou.attribType.Point, "rest", (0.0, 0.0, 0.0))
    poly = geo.createPolygon()
    poly.setIsClosed(False)
    for record in records:
        point = geo.createPoint()
        point.setPosition(record["position"])
        point.setAttribValue(number_attr, int(record["number"]))
        point.setAttribValue(rest_attr, tuple(record["rest"]))
        poly.addVertex(point)
    poly.setAttribValue("line_role", role)
    poly.setAttribValue("corner_id", int(corner_id))
    return poly


def _source_corner_id(source):
    corner_attr = source.findPrimAttrib("corner_id")
    prims = list(source.prims())
    if corner_attr is not None and prims:
        return int(prims[0].attribValue(corner_attr))
    return 0


def _extract_corner_info(source):
    prims = list(source.prims())
    if not prims:
        return None
    prim = prims[0]
    required = ("branch_angle0", "branch_angle1", "corner_position")
    attrs = {name: source.findPrimAttrib(name) for name in required}
    if any(attrib is None for attrib in attrs.values()):
        return None
    angle0 = float(prim.attribValue(attrs["branch_angle0"]))
    angle1 = float(prim.attribValue(attrs["branch_angle1"]))
    delta = (angle1 - angle0) % TAU
    return {
        "angle0": angle0,
        "angle1": angle1,
        "delta": delta,
        "corner_position": hou.Vector3(prim.attribValue(attrs["corner_position"])),
    }


def _offset_intersection_count(source, verbs):
    outer = _offset_copy(source, 1.0)
    inner = _offset_copy(source, -1.0)
    merged = hou.Geometry()
    verbs["merge"].execute(merged, [outer, inner])
    _flatten_y(merged)
    analysis_verb = verbs["intersectionanalysis"]
    analysis_verb.setParms(
        {
            "useinputnumattrib": 1,
            "useprimnumattrib": 1,
            "useprimuvwattrib": 1,
            "useptnumattrib": 1,
        }
    )
    analysis = hou.Geometry()
    analysis_verb.execute(analysis, [merged])
    return len(analysis.points()) + len(analysis.prims())


def _angle_in_ccw_sector(angle, start, delta):
    rel = (angle - start) % TAU
    return rel <= delta + 1.0e-5


def _sector_score_for_prim(prim, corner_info):
    if corner_info is None:
        return 0.0
    return _sector_score_for_positions(
        [point.position() for point in prim.points()],
        corner_info,
    )


def _sector_score_for_positions(positions, corner_info):
    if corner_info is None or not positions:
        return 0.0
    corner = corner_info["corner_position"]
    start = corner_info["angle0"]
    delta = corner_info["delta"]
    inside = 0
    for position in positions:
        angle = math.atan2(
            float(position.z() - corner.z()),
            float(position.x() - corner.x()),
        )
        if _angle_in_ccw_sector(angle, start, delta):
            inside += 1
    return float(inside) / float(len(positions))


def _sector_score_for_records(records, corner_info):
    return _sector_score_for_positions(
        [record["position"] for record in records],
        corner_info,
    )


def _source_branch_lookup(source, corner_position):
    number_attr = source.findPointAttrib("number")
    points = list(source.points())
    if not points:
        return {}, [], 0
    corner_index = min(
        range(len(points)),
        key=lambda index: points[index].position().distanceTo(corner_position),
    )
    by_number = {}
    source_records = []
    for index, point in enumerate(points):
        if index < corner_index:
            branch = 0
        elif index > corner_index:
            branch = 1
        else:
            branch = -1
        number = int(point.attribValue(number_attr)) if number_attr is not None else point.number()
        by_number.setdefault(number, branch)
        source_records.append({"position": point.position(), "branch": branch})

    source_segments = []
    for index in range(1, len(points)):
        if index <= corner_index:
            branch = 0
        elif index - 1 >= corner_index:
            branch = 1
        else:
            branch = -1
        source_segments.append({
            "a": points[index - 1].position(),
            "b": points[index].position(),
            "branch": branch,
        })
    return by_number, source_segments, corner_index


def _record_branch(record, by_number, source_segments):
    if not source_segments:
        branch = by_number.get(int(record["number"]))
        return branch if branch in (0, 1) else -1

    position = record["position"]
    px = float(position[0])
    pz = float(position[2])
    best = None
    for segment in source_segments:
        a = segment["a"]
        b = segment["b"]
        ax, az = float(a[0]), float(a[2])
        bx, bz = float(b[0]), float(b[2])
        vx, vz = bx - ax, bz - az
        length2 = vx * vx + vz * vz
        if length2 <= EPS:
            continue
        amount = clamp(((px - ax) * vx + (pz - az) * vz) / length2, 0.0, 1.0)
        qx = ax + vx * amount
        qz = az + vz * amount
        distance = ((px - qx) ** 2 + (pz - qz) ** 2) ** 0.5
        if best is None or distance < best[0]:
            best = (distance, segment["branch"])
    if best is None:
        return -1
    return best[1] if best[1] in (0, 1) else -1


def _split_sector_offset_records(records, source, corner_info):
    if len(records) < 3 or corner_info is None:
        return None
    by_number, source_records, _ = _source_branch_lookup(
        source, corner_info["corner_position"]
    )
    labels = [_record_branch(record, by_number, source_records) for record in records]
    transitions = [
        index for index in range(len(labels) - 1)
        if labels[index] in (0, 1)
        and labels[index + 1] in (0, 1)
        and labels[index] != labels[index + 1]
    ]
    if not transitions:
        return None
    split_index = max(
        transitions,
        key=lambda index: _record_distance(records[index], records[index + 1]),
    )
    left = list(records[: split_index + 1])
    right = list(records[split_index + 1 :])
    if not left or not right:
        return None
    left_label = next((label for label in labels[: split_index + 1] if label in (0, 1)), -1)
    right_label = next((label for label in labels[split_index + 1 :] if label in (0, 1)), -1)
    corner_pos = (left[-1]["position"] + right[0]["position"]) * 0.5
    corner_record = {
        "position": corner_pos,
        "number": -1,
        "rest": corner_pos,
    }
    if left_label == 0 and right_label == 1:
        return left + [corner_record], [corner_record] + right
    if left_label == 1 and right_label == 0:
        return list(reversed(right)) + [corner_record], [corner_record] + list(reversed(left))
    return None


def _surface_from_center_edge_records(center_records, edge_records, corner_id):
    count = min(len(center_records), len(edge_records))
    if count < 2:
        return None

    surface = hou.Geometry()
    corner_attrib = surface.addAttrib(hou.attribType.Prim, "corner_id", -1)
    source_attrib = surface.addAttrib(hou.attribType.Prim, "source_surface_prim", -1)
    is_arc_attrib = surface.addAttrib(hou.attribType.Point, "is_arc", 0)

    center_points = []
    edge_points = []
    for index in range(count):
        center_point = surface.createPoint()
        center_point.setPosition(center_records[index]["position"])
        center_point.setAttribValue(is_arc_attrib, 0)
        center_points.append(center_point)

        edge_point = surface.createPoint()
        edge_point.setPosition(edge_records[index]["position"])
        edge_point.setAttribValue(is_arc_attrib, 0)
        edge_points.append(edge_point)

    surface_count = 0
    for index in range(count - 1):
        face_points = [
            edge_points[index],
            edge_points[index + 1],
            center_points[index + 1],
            center_points[index],
        ]
        if not polygon_span_ok(face_points):
            continue
        poly = surface.createPolygon()
        poly.setIsClosed(True)
        for point in face_points:
            poly.addVertex(point)
        poly.setAttribValue(corner_attrib, int(corner_id))
        poly.setAttribValue(source_attrib, int(index))
        surface_count += 1

    if surface_count == 0:
        return None
    return surface


def _direct_extrapolated_surface(source):
    if source.findPrimAttrib("corner_position") is None or len(source.prims()) != 1:
        return None
    corner_info = _extract_corner_info(source)
    if corner_info is None or corner_info["delta"] <= math.pi:
        return None

    verbs = hou.sopNodeTypeCategory().nodeVerbs()
    if _offset_intersection_count(source, verbs) > 0:
        return None

    candidates = []
    for sign in (1.0, -1.0):
        edge_geo = _offset_copy(source, sign)
        _flatten_y(edge_geo)
        prims = list(edge_geo.prims())
        if not prims:
            continue
        records = _prim_records(prims[0])
        if len(records) < 2:
            continue
        length = sum(
            _record_distance(records[index - 1], records[index])
            for index in range(1, len(records))
        )
        candidates.append((
            _sector_score_for_records(records, corner_info),
            length,
            records,
        ))

    if not candidates:
        return None
    score, _, edge_records = max(candidates, key=lambda item: (item[0], item[1]))
    if score <= 0.5:
        return None

    return _surface_from_center_edge_records(
        _prim_records(source.prims()[0]),
        edge_records,
        _source_corner_id(source),
    )


def _run_extract_pair_stitch(source, verbs):
    if source.findPrimAttrib("corner_position") is None or len(source.prims()) != 1:
        return None

    corner_info = _extract_corner_info(source)
    centre_segments = _centre_segments_xz(source)
    outer = _offset_copy(source, 1.0)
    inner = _offset_copy(source, -1.0)
    merged = hou.Geometry()
    verbs["merge"].execute(merged, [outer, inner])
    _flatten_y(merged)
    analysis_verb = verbs["intersectionanalysis"]
    analysis_verb.setParms(
        {
            "useinputnumattrib": 1,
            "useprimnumattrib": 1,
            "useprimuvwattrib": 1,
            "useptnumattrib": 1,
        }
    )
    analysis = hou.Geometry()
    analysis_verb.execute(analysis, [merged])
    stitched = hou.Geometry()
    verbs["intersectionstitch"].execute(stitched, [merged, None, analysis])

    by_side = {-1: [], 1: []}
    for prim in stitched.prims():
        if not _valid_offset_prim(prim, source, centre_segments):
            continue
        stats = _offset_distance_stats(prim, source)
        if stats is None or stats["dominant_side"] == 0:
            continue
        by_side[stats["dominant_side"]].append(_prim_records(prim))

    if corner_info is not None and corner_info["delta"] <= math.pi:
        scored = []
        for fragments in by_side.values():
            records = _chain_record_fragments(fragments)
            if len(records) < 3:
                continue
            length = sum(
                _record_distance(records[index - 1], records[index])
                for index in range(1, len(records))
            )
            scored.append((
                _sector_score_for_records(records, corner_info),
                length,
                records,
            ))
        scored = [item for item in scored if item[0] > 0.5]
        if scored:
            _, _, selected = max(scored, key=lambda item: (item[0], item[1]))
            split_records = _split_sector_offset_records(
                selected,
                source,
                corner_info,
            )
            if split_records is not None:
                out = hou.Geometry()
                _ensure_role_attribs(out)
                corner_id = _source_corner_id(source)
                for records in split_records:
                    _create_record_polyline(out, records, "offset", corner_id)
                _create_record_polyline(
                    out, _prim_records(source.prims()[0]), "center", corner_id
                )
                return out

    if not by_side[-1] or not by_side[1]:
        return None

    out = hou.Geometry()
    _ensure_role_attribs(out)
    corner_id = _source_corner_id(source)
    for side in (-1, 1):
        records = _chain_record_fragments(by_side[side])
        _create_record_polyline(out, records, "offset", corner_id)
    _create_record_polyline(out, _prim_records(source.prims()[0]), "center", corner_id)
    return out


def _prim_ends_xz(prim):
    points = prim.points()
    a = points[0].position()
    b = points[-1].position()
    return (a[0], a[2]), (b[0], b[2])

def _stitch_centre_halves(source, verbs):
    """Flatten the centre curves and stitch them at their real crossing.
    Returns the stitched geometry (one polyline per arm, each running from the
    crossing out to an original endpoint) which is the ground-truth centre pair
    source seen in Target.bgeo.sc.
    """
    flat = hou.Geometry()
    flat.merge(source)
    _flatten_y(flat)
    analysis_verb = verbs["intersectionanalysis"]
    analysis_verb.setParms(
        {
            "useinputnumattrib": 1,
            "useprimnumattrib": 1,
            "useprimuvwattrib": 1,
            "useptnumattrib": 1,
        }
    )
    analysis = hou.Geometry()
    analysis_verb.execute(analysis, [flat])
    stitched = hou.Geometry()
    verbs["intersectionstitch"].execute(stitched, [flat, None, analysis])
    return stitched

def _centre_far_points(centre_geo):
    """For each centre half, the endpoint that is NOT the shared crossing."""
    endpoints = []
    for prim in centre_geo.prims():
        a, b = _prim_ends_xz(prim)
        endpoints.append((prim.number(), a, b))
    all_pts = []
    for _, a, b in endpoints:
        all_pts.extend((a, b))
    crossing = all_pts[0]
    best = 0
    for cand in all_pts:
        count = sum(1 for q in all_pts if _dist2d(cand, q) < 0.5)
        if count > best:
            best = count
            crossing = cand
    far = {}
    for num, a, b in endpoints:
        far[num] = b if _dist2d(a, crossing) < 0.5 else a
    return far, crossing

def _assign_corners(offset_geo, centre_far):
    """Group offset prims into corners and find each corner's centre pair.
    Returns:
        offset_corner_id : {offset_prim_number -> corner_id}
        corner_centres   : {corner_id -> [centre_half_number, ...]}
    """
    far_by_prim = {}
    cross_by_prim = {}
    for prim in offset_geo.prims():
        a, b = _prim_ends_xz(prim)
        best = None
        for cnum, cfar in centre_far.items():
            for end, is_a in ((a, True), (b, False)):
                d = _dist2d(end, cfar)
                if best is None or d < best[0]:
                    best = (d, cnum, is_a)
        _, cnum, end_is_a = best
        far_by_prim[prim.number()] = cnum
        cross_by_prim[prim.number()] = b if end_is_a else a
    clusters = []  # [rep_cross_point, [prim_numbers]]
    for prim in offset_geo.prims():
        cp = cross_by_prim[prim.number()]
        for cluster in clusters:
            if _dist2d(cluster[0], cp) < 1.0:
                cluster[1].append(prim.number())
                break
        else:
            clusters.append([cp, [prim.number()]])
    clusters.sort(key=lambda c: (round(c[0][0], 2), round(c[0][1], 2)))
    offset_corner_id = {}
    corner_centres = {}
    for corner_id, (_, prim_numbers) in enumerate(clusters):
        for pnum in prim_numbers:
            offset_corner_id[pnum] = corner_id
        corner_centres[corner_id] = sorted(
            {far_by_prim[pnum] for pnum in prim_numbers}
        )
    return offset_corner_id, corner_centres

def _ensure_role_attribs(geo):
    if geo.findPrimAttrib("line_role") is None:
        geo.addAttrib(hou.attribType.Prim, "line_role", "")
    if geo.findPrimAttrib("corner_id") is None:
        geo.addAttrib(hou.attribType.Prim, "corner_id", -1)


def _run_stitch(source):
    verbs = hou.sopNodeTypeCategory().nodeVerbs()
    extract_stitched = _run_extract_pair_stitch(source, verbs)
    if extract_stitched is not None:
        return extract_stitched

    centre_segments = _centre_segments_xz(source)
    outer = _offset_copy(source, 1.0)
    inner = _offset_copy(source, -1.0)
    merged = hou.Geometry()
    verbs["merge"].execute(merged, [outer, inner])
    _flatten_y(merged)
    analysis_verb = verbs["intersectionanalysis"]
    analysis_verb.setParms(
        {
            "useinputnumattrib": 1,
            "useprimnumattrib": 1,
            "useprimuvwattrib": 1,
            "useptnumattrib": 1,
        }
    )
    analysis = hou.Geometry()
    analysis_verb.execute(analysis, [merged])
    stitched = hou.Geometry()
    verbs["intersectionstitch"].execute(stitched, [merged, None, analysis])
    doomed = [
        prim for prim in stitched.prims()
        if not _valid_offset_prim(prim, source, centre_segments)
    ]
    if doomed:
        stitched.deletePrims(doomed)
    centre_halves = _stitch_centre_halves(source, verbs)
    centre_far, _ = _centre_far_points(centre_halves)
    offset_corner_id, corner_centres = _assign_corners(stitched, centre_far)
    _ensure_role_attribs(stitched)
    for prim in stitched.prims():
        prim.setAttribValue("line_role", "offset")
        prim.setAttribValue("corner_id", int(offset_corner_id.get(prim.number(), -1)))
    out = hou.Geometry()
    out.merge(stitched)
    for corner_id, centre_nums in corner_centres.items():
        corner_geo = hou.Geometry()
        corner_geo.merge(centre_halves)
        keep = set(centre_nums)
        corner_geo.deletePrims(
            [prim for prim in corner_geo.prims() if prim.number() not in keep]
        )
        _ensure_role_attribs(corner_geo)
        for prim in corner_geo.prims():
            prim.setAttribValue("line_role", "center")
            prim.setAttribValue("corner_id", int(corner_id))
        out.merge(corner_geo)
    return out


# -- Coordinator helpers --
def _polygon_normal_y(vertices):
    positions = [vertex.point().position() for vertex in vertices]
    return sum(
        (positions[index][2] - positions[(index + 1) % len(positions)][2])
        * (positions[index][0] + positions[(index + 1) % len(positions)][0])
        for index in range(len(positions))
    )


def _upward_vertices(vertices):
    return vertices if _polygon_normal_y(vertices) <= 0.0 else list(reversed(vertices))


def _dedupe_ordered_vertices(vertices, tolerance=1.0e-6):
    clean = []
    for vertex in vertices:
        position = vertex.point().position()
        if clean and position.distanceTo(clean[-1].point().position()) <= tolerance:
            continue
        clean.append(vertex)
    if len(clean) > 2:
        first = clean[0].point().position()
        last = clean[-1].point().position()
        if first.distanceTo(last) <= tolerance:
            clean.pop()
    return clean


def _surface_from_arc_output(arc_geo, corner_id):
    """Copy only the solver's closed road-surface faces into a clean geometry."""
    surface = hou.Geometry()
    corner_attrib = surface.addAttrib(hou.attribType.Prim, "corner_id", -1)
    source_attrib = surface.addAttrib(hou.attribType.Prim, "source_surface_prim", -1)
    is_arc_attrib = surface.addAttrib(hou.attribType.Point, "is_arc", 0)

    road_group = arc_geo.findPrimGroup("arc_road_surface")
    if road_group is None:
        raise hou.NodeError(
            "Tangent arc stage did not create the arc_road_surface group."
        )

    src_is_arc_attrib = arc_geo.findPointAttrib("is_arc")
    point_map = {}

    def clone_point(source_point):
        point = point_map.get(source_point.number())
        if point is None:
            point = surface.createPoint()
            point.setPosition(source_point.position())
            arc_value = (
                int(source_point.attribValue(src_is_arc_attrib))
                if src_is_arc_attrib is not None
                else 0
            )
            point.setAttribValue(is_arc_attrib, arc_value)
            point_map[source_point.number()] = point
        return point

    for source_prim in road_group.prims():
        vertices = _dedupe_ordered_vertices(_upward_vertices(list(source_prim.vertices())))
        if len(vertices) < 3:
            continue
        poly = surface.createPolygon()
        poly.setIsClosed(True)
        for vertex in vertices:
            poly.addVertex(clone_point(vertex.point()))
        poly.setAttribValue(corner_attrib, int(corner_id))
        poly.setAttribValue(source_attrib, int(source_prim.number()))

    return surface


def _corner_sets(stitched):
    corner_attrib = stitched.findPrimAttrib("corner_id")
    role_attrib = stitched.findPrimAttrib("line_role")
    if corner_attrib is None or role_attrib is None:
        raise hou.NodeError(
            "road_offset_stitch stage did not tag corner_id / line_role."
        )

    all_by_corner = {}
    centers_by_corner = {}
    for prim in stitched.prims():
        corner_id = prim.attribValue(corner_attrib)
        prim_number = prim.number()
        all_by_corner.setdefault(corner_id, set()).add(prim_number)
        if prim.attribValue(role_attrib) == "center":
            centers_by_corner.setdefault(corner_id, set()).add(prim_number)

    corner_ids = sorted(all_by_corner)
    if DEBUG_SINGLE_CORNER is not None:
        corner_ids = [c for c in corner_ids if c == DEBUG_SINGLE_CORNER][:1]

    return [
        (corner_id, all_by_corner[corner_id], centers_by_corner.get(corner_id, set()))
        for corner_id in corner_ids
    ]


def _copy_prims(source, keep):
    geo = hou.Geometry()
    geo.merge(source)
    geo.deletePrims([prim for prim in geo.prims() if prim.number() not in keep])
    return geo


def _is_extrapolated_stitch_input(source):
    role_attrib = source.findPrimAttrib("line_role")
    corner_attrib = source.findPrimAttrib("corner_id")
    if role_attrib is None or corner_attrib is None:
        return False
    roles = {prim.attribValue(role_attrib) for prim in source.prims()}
    return "offset" in roles and "center" in roles


def _is_final_surface_input(source):
    if source.findPrimAttrib("line_role") is not None:
        return False
    return (
        source.findPrimAttrib("source_surface_prim") is not None
        and source.findPrimAttrib("corner_id") is not None
        and source.findPointAttrib("is_arc") is not None
    )


def _input_geometry_or_none(node, index):
    inputs = node.inputs()
    if index >= len(inputs) or inputs[index] is None:
        return None
    return node.inputGeometry(index)


# -- Coordinator entry --
def build():
    node = hou.pwd()
    out_geo = node.geometry()
    source = node.inputGeometry(0)
    raw_source = _input_geometry_or_none(node, 1) or source

    if _is_final_surface_input(source):
        out_geo.clear()
        out_geo.merge(source)
        return

    if _is_extrapolated_stitch_input(source):
        stitched = hou.Geometry()
        stitched.merge(source)
    else:
        direct_surface = _direct_extrapolated_surface(source)
        if direct_surface is not None:
            out_geo.clear()
            out_geo.merge(direct_surface)
            return

        stitched = _run_stitch(source)

    out_geo.clear()

    for corner_id, keep, center_keep in _corner_sets(stitched):
        bundle = _copy_prims(stitched, keep)
        # A tangent arc needs two offset boundary polylines to round between.
        # Road stubs / dead-ends produce a corner with a single offset edge;
        # skip those instead of letting _run_arc abort the whole cook.
        role_attrib = bundle.findPrimAttrib("line_role")
        offset_count = sum(
            1 for prim in bundle.prims()
            if role_attrib is not None and prim.attribValue(role_attrib) == "offset"
        )
        if offset_count < 2:
            continue
        centre = _copy_prims(stitched, center_keep)

        arc_out = hou.Geometry()
        arc_out.merge(bundle)
        _run_arc(arc_out, bundle, centre, node, raw_source)

        out_geo.merge(_surface_from_arc_output(arc_out, corner_id))

if globals().get("ROAD_CORNER_INTEGRATED_AUTOBUILD", True):
    build()
