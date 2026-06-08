import bisect
import math
import time

cook_start = time.perf_counter()
node = hou.pwd()
geo = node.geometry()
ctrl = node.parent().node("CTRL")

EPS = 1.0e-9
TAU = math.pi * 2.0
SAMPLES = 900
INTERSECTION_COARSE_SAMPLES = 220
REFINE_SEGMENT_WINDOW = 56
ORIGINAL_CURVE_POINTS = 128
CUT_SEGMENT_POINTS = 32
FRACTION_SMOOTH_PASSES = 4
ARC_INTERSECTION_TOLERANCE = 1.0e-5


def warn(message):
    if hasattr(node, "addWarning"):
        node.addWarning(message)


def ctrl_value(name, default):
    parm = ctrl.parm(name) if ctrl is not None else None
    return default if parm is None else parm.eval()


def clamp(value, low, high):
    return max(low, min(high, value))


def vec(value):
    return hou.Vector3(value)


def sample_curve(prim, sample_count):
    points = []
    params = []
    for index in range(sample_count + 1):
        u = float(index) / float(sample_count)
        params.append(u)
        points.append(vec(prim.positionAt(u)))
    cumulative = [0.0]
    for index in range(1, len(points)):
        cumulative.append(cumulative[-1] + (points[index] - points[index - 1]).length())
    return {"prim": prim, "points": points, "u": params, "cum": cumulative, "length": cumulative[-1]}


def point_at_length(curve, distance):
    cumulative = curve["cum"]
    distance = clamp(distance, 0.0, curve["length"])
    index = bisect.bisect_left(cumulative, distance)
    if index <= 0:
        u = curve["u"][0]
    elif index >= len(cumulative):
        u = curve["u"][-1]
    else:
        previous_len = cumulative[index - 1]
        segment_len = cumulative[index] - previous_len
        amount = 0.0 if segment_len <= EPS else (distance - previous_len) / segment_len
        u = curve["u"][index - 1] + amount * (curve["u"][index] - curve["u"][index - 1])
    return vec(curve["prim"].positionAt(u)), u


def tangent_at_length(curve, distance):
    step = max(curve["length"] * 1.0e-5, 1.0e-4)
    low = clamp(distance - step, 0.0, curve["length"])
    high = clamp(distance + step, 0.0, curve["length"])
    if abs(high - low) <= EPS:
        low = clamp(distance - step * 10.0, 0.0, curve["length"])
        high = clamp(distance + step * 10.0, 0.0, curve["length"])
    p0, _ = point_at_length(curve, low)
    p1, _ = point_at_length(curve, high)
    tangent = p1 - p0
    if tangent.length() <= EPS:
        raise hou.NodeError("Could not estimate curve tangent. Check the input curves.")
    return tangent.normalized()


def closest_points_on_segments(p1, q1, p2, q2):
    d1 = q1 - p1
    d2 = q2 - p2
    r = p1 - p2
    a = d1.dot(d1)
    e = d2.dot(d2)
    f = d2.dot(r)
    if a <= EPS and e <= EPS:
        s = 0.0
        t = 0.0
    elif a <= EPS:
        s = 0.0
        t = clamp(f / e, 0.0, 1.0)
    else:
        c = d1.dot(r)
        if e <= EPS:
            t = 0.0
            s = clamp(-c / a, 0.0, 1.0)
        else:
            b = d1.dot(d2)
            denom = a * e - b * b
            s = clamp((b * f - c * e) / denom, 0.0, 1.0) if abs(denom) > EPS else 0.0
            tnom = b * s + f
            if tnom < 0.0:
                t = 0.0
                s = clamp(-c / a, 0.0, 1.0)
            elif tnom > e:
                t = 1.0
                s = clamp((b - c) / a, 0.0, 1.0)
            else:
                t = tnom / e
    c1 = p1 + d1 * s
    c2 = p2 + d2 * t
    return c1, c2, s, t, (c1 - c2).length()


def segment_index_at_length(curve, distance):
    cumulative = curve["cum"]
    index = bisect.bisect_right(cumulative, clamp(distance, 0.0, curve["length"])) - 1
    return max(0, min(index, len(cumulative) - 2))


def find_best_segment_pair(curve0, curve1, start0, end0, start1, end1):
    best = None
    checks = 0
    end0 = min(end0, len(curve0["points"]) - 1)
    end1 = min(end1, len(curve1["points"]) - 1)
    for i in range(max(0, start0), end0):
        p0 = curve0["points"][i]
        p1 = curve0["points"][i + 1]
        seg0_len = curve0["cum"][i + 1] - curve0["cum"][i]
        for j in range(max(0, start1), end1):
            checks += 1
            c0, c1, s, t, gap = closest_points_on_segments(p0, p1, curve1["points"][j], curve1["points"][j + 1])
            if best is None or gap < best["gap"]:
                seg1_len = curve1["cum"][j + 1] - curve1["cum"][j]
                best = {
                    "gap": gap,
                    "point": (c0 + c1) * 0.5,
                    "curve0_length": curve0["cum"][i] + seg0_len * s,
                    "curve1_length": curve1["cum"][j] + seg1_len * t,
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
    a = normal0.dot(normal0)
    b = normal0.dot(normal1)
    c = normal1.dot(normal1)
    d = normal0.dot(w0)
    e = normal1.dot(w0)
    denom = a * c - b * b
    if abs(denom) <= EPS:
        return None
    s = (b * e - c * d) / denom
    t = (a * e - b * d) / denom
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


def smooth_fraction_list(values, fixed_indices):
    if len(values) <= 2:
        return values
    result = list(values)
    for _ in range(FRACTION_SMOOTH_PASSES):
        previous = list(result)
        for index in range(1, len(result) - 1):
            if index in fixed_indices:
                continue
            result[index] = previous[index - 1] * 0.25 + previous[index] * 0.5 + previous[index + 1] * 0.25
        first = result[0]
        last = result[-1]
        if last >= first:
            for index in range(1, len(result) - 1):
                result[index] = clamp(result[index], min(result[index - 1], last), max(result[index - 1], last))
        else:
            for index in range(1, len(result) - 1):
                result[index] = clamp(result[index], min(last, result[index - 1]), max(last, result[index - 1]))
    return result


def clamp_fraction_to_span(value, a, b):
    return clamp(value, min(a, b), max(a, b))


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
    if geo.findGlobalAttrib(name) is None:
        geo.addAttrib(hou.attribType.Global, name, default)
    geo.setGlobalAttribValue(name, stored)


def source_entries_for_curve(curve):
    entries = []
    raw_points = [vec(vertex.point().position()) for vertex in curve["prim"].vertices()]
    raw_cumulative = [0.0]
    for index in range(1, len(raw_points)):
        raw_cumulative.append(raw_cumulative[-1] + raw_points[index].distanceTo(raw_points[index - 1]))
    raw_length = raw_cumulative[-1] if raw_cumulative else 0.0
    for vertex in curve["prim"].vertices():
        index = len(entries)
        position = raw_points[index]
        length = 0.0 if raw_length <= EPS else raw_cumulative[index] / raw_length * curve["length"]
        entries.append({
            "length": clamp(length, 0.0, curve["length"]),
            "position": position,
            "interface": False,
            "inserted": False,
        })
    if not entries:
        start_pos, _ = point_at_length(curve, 0.0)
        end_pos, _ = point_at_length(curve, curve["length"])
        entries = [
            {"length": 0.0, "position": start_pos, "interface": False, "inserted": False},
            {"length": curve["length"], "position": end_pos, "interface": False, "inserted": False},
        ]
    entries.sort(key=lambda item: item["length"])
    return entries


def mark_or_insert_interface_entry(curve, entries, tangent_length, tangent_position):
    tolerance = max(curve["length"] * 1.0e-5, 1.0e-4)
    best_index = min(range(len(entries)), key=lambda idx: entries[idx]["position"].distanceTo(tangent_position))
    if entries[best_index]["position"].distanceTo(tangent_position) <= tolerance:
        entries[best_index]["position"] = tangent_position
        entries[best_index]["length"] = tangent_length
        entries[best_index]["interface"] = True
        entries.sort(key=lambda item: item["length"])
        return entries.index(next(item for item in entries if item["interface"])), 0

    entries.append({
        "length": tangent_length,
        "position": tangent_position,
        "interface": True,
        "inserted": True,
    })
    entries.sort(key=lambda item: item["length"])
    for index, item in enumerate(entries):
        if item["interface"]:
            return index, 1
    return len(entries) - 1, 1


def build_modified_curve(curve, intersection_length, direction, distance, tangent_fraction, center, start_vec, plane_normal, arc_angle, intersection_arc_fraction, projected_intersection):
    tangent_length = intersection_length + direction * distance
    cut_low = min(intersection_length, tangent_length)
    cut_high = max(intersection_length, tangent_length)
    tolerance = max(curve["length"] * 1.0e-7, 1.0e-6)
    entries = source_entries_for_curve(curve)
    tangent_index, interface_points_added = mark_or_insert_interface_entry(curve, entries, tangent_length, arc_point_at_fraction(center, start_vec, plane_normal, arc_angle, tangent_fraction))
    lengths = [entry["length"] for entry in entries]

    positions = []
    weights = []
    cut_indices = []
    raw_fractions = []
    fraction_low = min(intersection_arc_fraction, tangent_fraction)
    fraction_high = max(intersection_arc_fraction, tangent_fraction)
    for entry in entries:
        length = entry["length"]
        original_pos = entry["position"]
        if cut_low - tolerance <= length <= cut_high + tolerance:
            positions.append(original_pos)
            weights.append(1.0)
            cut_indices.append(len(positions) - 1)
            fraction = fraction_for_point_on_arc(original_pos, center, start_vec, plane_normal, arc_angle)
            raw_fractions.append(clamp(fraction, fraction_low, fraction_high))
        else:
            positions.append(original_pos)
            weights.append(0.0)

    intersection_index = min(range(len(lengths)), key=lambda idx: abs(lengths[idx] - intersection_length))
    fraction_by_index = dict(zip(cut_indices, raw_fractions))
    fraction_by_index[intersection_index] = intersection_arc_fraction
    fraction_by_index[tangent_index] = tangent_fraction
    if intersection_index not in cut_indices:
        cut_indices.append(intersection_index)
    if tangent_index not in cut_indices:
        cut_indices.append(tangent_index)

    ordered_cut_indices = [idx for idx in sorted(cut_indices, key=lambda idx: lengths[idx]) if idx in fraction_by_index]
    ordered_fractions = [fraction_by_index[idx] for idx in ordered_cut_indices]
    fixed_local_indices = set()
    for local_index, point_index in enumerate(ordered_cut_indices):
        if point_index == intersection_index or point_index == tangent_index:
            fixed_local_indices.add(local_index)
    ordered_fractions = smooth_fraction_list(ordered_fractions, fixed_local_indices)

    for local_index, point_index in enumerate(ordered_cut_indices):
        fraction = clamp_fraction_to_span(ordered_fractions[local_index], intersection_arc_fraction, tangent_fraction)
        positions[point_index] = arc_point_at_fraction(center, start_vec, plane_normal, arc_angle, fraction)
    positions[intersection_index] = projected_intersection
    positions[tangent_index] = arc_point_at_fraction(center, start_vec, plane_normal, arc_angle, tangent_fraction)
    return positions, weights, intersection_index, tangent_index, interface_points_added


def main():
    if ctrl is None:
        raise hou.NodeError("Missing /obj/geo1/CTRL controller node.")

    requested_distance = float(ctrl_value("curve_distance", 5.0))
    curve_prims = [prim for prim in geo.prims() if "curve" in prim.type().name().lower()]
    if len(curve_prims) < 2:
        raise hou.NodeError("Expected at least two curve primitives in the input geometry.")
    if len(curve_prims) > 2:
        warn("More than two curves found. Using primitive 0 and primitive 1.")

    curve0_full = sample_curve(curve_prims[0], SAMPLES)
    curve1_full = sample_curve(curve_prims[1], SAMPLES)
    intersection = find_curve_intersection(curve0_full, curve1_full)
    intersection_length0 = clamp(intersection["curve0_length"], 0.0, curve0_full["length"])
    intersection_length1 = clamp(intersection["curve1_length"], 0.0, curve1_full["length"])
    intersection_point = intersection["point"]

    direction0 = auto_direction(curve0_full, intersection_length0, requested_distance)
    direction1 = auto_direction(curve1_full, intersection_length1, requested_distance)
    max_distance0 = curve0_full["length"] - intersection_length0 if direction0 > 0.0 else intersection_length0
    max_distance1 = curve1_full["length"] - intersection_length1 if direction1 > 0.0 else intersection_length1
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
    p0, u0 = point_at_length(curve0_full, length0)
    p1, u1 = point_at_length(curve1_full, length1)
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
    trim_info = trim_intersection_to_nearest_curve_hit(
        curve0_arc_hits, curve1_arc_hits, intersection_arc_fraction, projected_intersection
    )
    if trim_info["trimmed"]:
        intersection_arc_fraction = trim_info["fraction"]
        projected_intersection = trim_info["point"]

    curve0_positions, curve0_weights, curve0_inter_idx, curve0_tan_idx, curve0_inserted = build_modified_curve(
        curve0_full, intersection_length0, direction0, distance, 0.0, center, start_vec, plane_normal, arc_angle, intersection_arc_fraction, projected_intersection
    )
    curve1_positions, curve1_weights, curve1_inter_idx, curve1_tan_idx, curve1_inserted = build_modified_curve(
        curve1_full, intersection_length1, direction1, distance, 1.0, center, start_vec, plane_normal, arc_angle, intersection_arc_fraction, projected_intersection
    )
    interface_points_added = int(curve0_inserted + curve1_inserted)

    geo.clear()
    role_attrib = geo.addAttrib(hou.attribType.Point, "arc_role", "")
    side_attrib = geo.addAttrib(hou.attribType.Point, "arc_side", -1)
    weight_attrib = geo.addAttrib(hou.attribType.Point, "arc_project_weight", 0.0)
    interface_group = geo.createPointGroup("arc_interface_points")
    intersection_group = geo.createPointGroup("arc_intersection_point")
    projected_group = geo.createPointGroup("arc_projected_segment_points")
    original_group = geo.createPrimGroup("modified_original_curves")

    def create_point(position, role, side, weight):
        point = geo.createPoint()
        point.setPosition(position)
        point.setAttribValue(role_attrib, role)
        point.setAttribValue(side_attrib, int(side))
        point.setAttribValue(weight_attrib, float(weight))
        return point

    intersection_pt = create_point(projected_intersection, "projected_intersection", -1, 1.0)
    intersection_group.add(intersection_pt)
    interface0_pt = create_point(p0, "interface", 0, 1.0)
    interface1_pt = create_point(p1, "interface", 1, 1.0)
    interface_group.add(interface0_pt)
    interface_group.add(interface1_pt)

    def add_modified_curve(positions, weights, inter_idx, tan_idx, side, interface_pt):
        poly = geo.createPolygon()
        poly.setIsClosed(False)
        for index, position in enumerate(positions):
            if index == inter_idx:
                point = intersection_pt
            elif index == tan_idx:
                point = interface_pt
            else:
                role = "projected_original_curve" if weights[index] > 0.0 else "source_original_curve"
                point = create_point(position, role, side, weights[index])
                if weights[index] > 0.0:
                    projected_group.add(point)
            poly.addVertex(point)
        original_group.add(poly)

    add_modified_curve(curve0_positions, curve0_weights, curve0_inter_idx, curve0_tan_idx, 0, interface0_pt)
    add_modified_curve(curve1_positions, curve1_weights, curve1_inter_idx, curve1_tan_idx, 1, interface1_pt)

    set_global("arc_center", center)
    set_global("arc_radius", float(radius))
    set_global("arc_intersection", intersection_point)
    set_global("arc_projected_intersection", projected_intersection)
    set_global("arc_projected_intersection_fraction", float(intersection_arc_fraction))
    set_global("arc_curve0_arc_intersections", int(len(curve0_arc_hits)))
    set_global("arc_curve1_arc_intersections", int(len(curve1_arc_hits)))
    set_global("arc_trimmed_to_curve_intersection", int(trim_info["trimmed"]))
    set_global("arc_trim_selected_side", int(trim_info["side"]))
    set_global("arc_trim_selected_fraction", float(intersection_arc_fraction))
    set_global("arc_projection_arc0_fraction_min", float(min(intersection_arc_fraction, 0.0)))
    set_global("arc_projection_arc0_fraction_max", float(max(intersection_arc_fraction, 0.0)))
    set_global("arc_projection_arc1_fraction_min", float(min(intersection_arc_fraction, 1.0)))
    set_global("arc_projection_arc1_fraction_max", float(max(intersection_arc_fraction, 1.0)))
    set_global("arc_projection_trim_mode", "nearest_curve_arc_intersection_when_multiple")
    set_global("arc_tangent0", p0)
    set_global("arc_tangent1", p1)
    set_global("arc_equal_distance", float(distance))
    set_global("arc_requested_distance", float(requested_distance))
    set_global("arc_max_distance", float(max_distance))
    set_global("arc_distance_was_clamped", int(distance_was_clamped))
    set_global("arc_solve_mode", "distance_only")
    set_global("arc_output_mode", "modify_original_curves")
    set_global("arc_projection_direction", "original_segment_to_arc")
    set_global("arc_projection_weight_mode", "closest_point_to_arc_smoothed")
    set_global("arc_projection_method", "closest_point_on_circular_arc")
    set_global("arc_projection_smooth_passes", int(FRACTION_SMOOTH_PASSES))
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
    set_global("arc_interface_points_created", 2)
    set_global("arc_interface_points_inserted", int(interface_points_added))
    set_global("arc_output_point_policy", "original_points_plus_interface_points")
    set_global("arc_projected_segments_created", 0)
    set_global("arc_modified_original_curves", 2)
    set_global("arc_intersection_candidate_checks", int(intersection.get("candidate_checks", 0)))
    set_global("arc_cook_ms", float((time.perf_counter() - cook_start) * 1000.0))


main()
