"""Houdini Python SOP: round all shared road junction centerlines.

Input: road centerlines from road_centerline_resample.
Output: centerlines with local junction spans rewritten as tangent arcs.

The algorithm is intentionally conservative:
  * shared points define candidate junctions;
  * every valid junction branch walks the same curve_distance from crossing;
  * T junctions keep the nearly straight through road untrimmed;
  * adjacent branch pairs get a tangent circular arc;
  * the original centerline spans near the crossing are trimmed away;
  * failures or unsupported dense inputs pass through unchanged.
"""

import math

import hou


node = hou.pwd()
geo = node.geometry()
geo.clear()

geo_in = node.inputs()[0].geometry() if node.inputs() else None

ENABLED = bool(int("__ENABLED__"))
CURVE_DISTANCE = max(0.25, float("__CURVE_DISTANCE__"))
MIN_BRANCH_DISTANCE = max(0.25, float("__MIN_BRANCH_DISTANCE__"))
MIN_ANGLE_DEG = max(1.0, float("__MIN_ANGLE_DEG__"))
MAX_ANGLE_DEG = min(179.0, max(MIN_ANGLE_DEG + 1.0, float("__MAX_ANGLE_DEG__")))
ARC_SPACING = max(0.25, float("__ARC_SPACING__"))
SMOOTH_ITERATIONS = max(0, int("__SMOOTH_ITERATIONS__"))
MAX_JUNCTIONS = max(50, int("__MAX_JUNCTIONS__"))
REUSE_TOLERANCE = max(0.001, float("__REUSE_TOLERANCE__"))
THROUGH_ANGLE_DEG = 150.0
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


def lerp(a, b, t):
    return a + (b - a) * t


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


def cross2(a, b):
    return a[0] * b[1] - a[1] * b[0]


def perp2(v):
    return -v[1], v[0]


def angle_of(v):
    return math.atan2(v[1], v[0])


def angle_delta_ccw(a0, a1):
    delta = (a1 - a0) % (math.tau)
    return delta


def unsigned_angle_deg(a, b):
    dot = max(-1.0, min(1.0, dot2(a, b)))
    return math.degrees(math.acos(dot))


def append_unique(points, pos, eps=0.01):
    if points and length_xz(points[-1], pos) <= eps:
        return
    points.append(pos)


def cumulative_lengths(points):
    out = [0.0]
    total = 0.0
    for idx in range(len(points) - 1):
        total += length_xz(points[idx], points[idx + 1])
        out.append(total)
    return out


def point_at_distance(points, distances, distance):
    if not points:
        return None
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


def extract_interval(points, distances, start, end):
    if end - start <= 0.05:
        return []
    out = []
    append_unique(out, point_at_distance(points, distances, start), eps=0.01)
    for idx, distance in enumerate(distances):
        if start + 0.01 < distance < end - 0.01:
            append_unique(out, points[idx], eps=0.01)
    append_unique(out, point_at_distance(points, distances, end), eps=0.01)
    return out if len(out) >= 2 else []


def clean_road_points(prim):
    points = []
    point_numbers = []
    for vertex in prim.vertices():
        point = vertex.point()
        pos = point.position()
        if points and length_xz(points[-1], pos) <= EPS:
            continue
        points.append(pos)
        point_numbers.append(point.number())
    return points, point_numbers


def branch_available(road, vertex_idx, direction, junction_numbers):
    points = road["points"]
    point_numbers = road["point_numbers"]
    total = 0.0
    idx = vertex_idx
    cur = points[idx]
    while 0 <= idx + direction < len(points):
        idx += direction
        nxt = points[idx]
        total += length_xz(cur, nxt)
        cur = nxt
        if point_numbers[idx] in junction_numbers:
            break
    return total


def sample_branch(road, vertex_idx, direction, distance):
    points = road["points"]
    remaining = distance
    idx = vertex_idx
    cur = points[idx]
    while 0 <= idx + direction < len(points):
        nxt = points[idx + direction]
        seg_len = length_xz(cur, nxt)
        if seg_len <= EPS:
            idx += direction
            cur = nxt
            continue
        if remaining <= seg_len + EPS:
            t = max(0.0, min(1.0, remaining / seg_len))
            pos = lerp(cur, nxt, t)
            tangent = normalize_xz(*vec_xz(cur, nxt))
            return pos, tangent
        remaining -= seg_len
        idx += direction
        cur = nxt
    tangent = normalize_xz(*vec_xz(points[vertex_idx], cur))
    return cur, tangent


def line_intersection_2d(p, r, q, s):
    denom = cross2(r, s)
    if abs(denom) <= EPS:
        return None
    qp = (float(q[0]) - float(p[0]), float(q[2]) - float(p[2]))
    t = cross2(qp, s) / denom
    return v3(float(p[0]) + r[0] * t, (float(p[1]) + float(q[1])) * 0.5, float(p[2]) + r[1] * t)


def project_center_to_equal_radii(center, p0, p1):
    vx = float(p1[0]) - float(p0[0])
    vz = float(p1[2]) - float(p0[2])
    d2 = vx * vx + vz * vz
    if d2 <= EPS:
        return center
    mx = (float(p0[0]) + float(p1[0])) * 0.5
    mz = (float(p0[2]) + float(p1[2])) * 0.5
    offset = ((float(center[0]) - mx) * vx + (float(center[2]) - mz) * vz) / d2
    return v3(float(center[0]) - offset * vx, float(center[1]), float(center[2]) - offset * vz)


def arc_points_for(center, p0, p1, ccw, segments):
    radius = length_xz(center, p0)
    if radius <= EPS:
        return []
    a0 = math.atan2(float(p0[2]) - float(center[2]), float(p0[0]) - float(center[0]))
    a1 = math.atan2(float(p1[2]) - float(center[2]), float(p1[0]) - float(center[0]))
    if ccw:
        delta = angle_delta_ccw(a0, a1)
    else:
        delta = -angle_delta_ccw(a1, a0)
    if abs(delta) <= EPS:
        return []
    out = []
    for idx in range(segments + 1):
        t = float(idx) / float(segments)
        angle = a0 + delta * t
        y = float(p0[1]) + (float(p1[1]) - float(p0[1])) * t
        out.append(v3(
            float(center[0]) + math.cos(angle) * radius,
            y,
            float(center[2]) + math.sin(angle) * radius,
        ))
    out[0] = p0
    out[-1] = p1
    return out


def smooth_points(points, iterations):
    if iterations <= 0 or len(points) <= 3:
        return points
    out = list(points)
    for _ in range(iterations):
        nxt = [out[0]]
        for idx in range(1, len(out) - 1):
            prev_pos = out[idx - 1]
            cur_pos = out[idx]
            next_pos = out[idx + 1]
            nxt.append(v3(
                float(cur_pos[0]) * 0.70 + (float(prev_pos[0]) + float(next_pos[0])) * 0.15,
                float(cur_pos[1]) * 0.70 + (float(prev_pos[1]) + float(next_pos[1])) * 0.15,
                float(cur_pos[2]) * 0.70 + (float(prev_pos[2]) + float(next_pos[2])) * 0.15,
            ))
        nxt.append(out[-1])
        out = nxt
    return out


def build_tangent_arc(branch_a, branch_b, junction_pos):
    p0 = branch_a["cut_pos"]
    p1 = branch_b["cut_pos"]
    t0 = branch_a["tangent"]
    t1 = branch_b["tangent"]
    if t0 is None or t1 is None:
        return None

    normals0 = [perp2(t0), (-perp2(t0)[0], -perp2(t0)[1])]
    normals1 = [perp2(t1), (-perp2(t1)[0], -perp2(t1)[1])]
    best = None
    for n0 in normals0:
        for n1 in normals1:
            center = line_intersection_2d(p0, n0, p1, n1)
            if center is None:
                continue
            center = project_center_to_equal_radii(center, p0, p1)
            radius = (length_xz(center, p0) + length_xz(center, p1)) * 0.5
            if radius < 0.25 or radius > max(25.0, CURVE_DISTANCE * 12.0):
                continue
            chord = length_xz(p0, p1)
            if chord <= EPS:
                continue
            for ccw in (True, False):
                a0 = math.atan2(float(p0[2]) - float(center[2]), float(p0[0]) - float(center[0]))
                a1 = math.atan2(float(p1[2]) - float(center[2]), float(p1[0]) - float(center[0]))
                delta = angle_delta_ccw(a0, a1) if ccw else angle_delta_ccw(a1, a0)
                if delta <= EPS:
                    continue
                arc_len = radius * delta
                segments = max(4, min(32, int(math.ceil(arc_len / ARC_SPACING))))
                points = smooth_points(arc_points_for(center, p0, p1, ccw, segments), SMOOTH_ITERATIONS)
                if len(points) < 2:
                    continue
                midpoint = points[len(points) // 2]
                tangent_error = abs(dot2(normalize_xz(*vec_xz(center, p0)) or (1.0, 0.0), t0))
                tangent_error += abs(dot2(normalize_xz(*vec_xz(center, p1)) or (1.0, 0.0), t1))
                score = length_xz(midpoint, junction_pos) + tangent_error * 5.0 + max(0.0, delta - math.pi) * radius
                if best is None or score < best[0]:
                    best = (score, points)
    return best[1] if best else None


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
    set_global("road_junction_curve_smooth_status", status)
    set_global("road_junction_curve_smooth_enabled", int(ENABLED))
    set_global("road_junction_curve_smooth_curve_distance", float(CURVE_DISTANCE))
    set_global("road_junction_curve_smooth_candidate_junctions", 0)
    set_global("road_junction_curve_smooth_processed_junctions", 0)
    set_global("road_junction_curve_smooth_arc_prims", 0)
    set_global("road_junction_curve_smooth_trimmed_prims", 0)
    set_global("road_junction_curve_smooth_skipped_junctions", 0)
    set_global("road_junction_curve_smooth_t_junctions", 0)
    set_global("road_junction_curve_smooth_fallbacks", int(fallbacks))
    if message:
        set_global("road_junction_curve_smooth_message", str(message)[:240])


if geo_in is None:
    passthrough("missing_input", 1)
elif not ENABLED:
    passthrough("disabled", 0)
else:
    try:
        roads = []
        point_usage = {}
        for src_prim in geo_in.prims():
            points, point_numbers = clean_road_points(src_prim)
            if len(points) < 2:
                continue
            road = {
                "src_prim": src_prim,
                "points": points,
                "point_numbers": point_numbers,
                "distances": cumulative_lengths(points),
            }
            road_idx = len(roads)
            roads.append(road)
            for vertex_idx, point_number in enumerate(point_numbers):
                point_usage.setdefault(point_number, []).append((road_idx, vertex_idx))

        junction_numbers = {point_number for point_number, refs in point_usage.items() if len(refs) > 1}
        if len(junction_numbers) > MAX_JUNCTIONS:
            passthrough("too_many_junctions", 1, "junctions={} max={}".format(len(junction_numbers), MAX_JUNCTIONS))
        else:
            copy_global_attrs()
            dst_attrs = {}
            for src_attr in geo_in.primAttribs():
                dst_attrs[src_attr.name()] = geo.findPrimAttrib(src_attr.name()) or geo.addAttrib(
                    hou.attribType.Prim, src_attr.name(), default_for_attrib(src_attr)
                )
            arc_attr = geo.findPrimAttrib("road_junction_curve_smooth_arc") or geo.addAttrib(
                hou.attribType.Prim, "road_junction_curve_smooth_arc", 0
            )

            group_members = {}
            dst_groups = {}
            for group in geo_in.primGroups():
                try:
                    group_members[group.name()] = set(prim.number() for prim in group.prims())
                    dst_groups[group.name()] = geo.createPrimGroup(group.name())
                except Exception:
                    pass

            trim_windows = {}
            arc_records = []
            processed_junctions = 0
            skipped_junctions = 0
            t_junctions = 0

            for point_number in junction_numbers:
                refs = point_usage.get(point_number, [])
                raw_branches = []
                junction_pos = None
                for road_idx, vertex_idx in refs:
                    road = roads[road_idx]
                    junction_pos = road["points"][vertex_idx]
                    for direction in (-1, 1):
                        if not (0 <= vertex_idx + direction < len(road["points"])):
                            continue
                        available = branch_available(road, vertex_idx, direction, junction_numbers)
                        if available >= MIN_BRANCH_DISTANCE:
                            raw_branches.append({
                                "road_idx": road_idx,
                                "vertex_idx": vertex_idx,
                                "direction": direction,
                                "available": available,
                            })

                if junction_pos is None or len(raw_branches) < 3:
                    skipped_junctions += 1
                    continue

                shortest = min(branch["available"] for branch in raw_branches)
                walk_distance = min(CURVE_DISTANCE, shortest * 0.45 if shortest < CURVE_DISTANCE * 2.2 else CURVE_DISTANCE)
                if walk_distance < MIN_BRANCH_DISTANCE:
                    skipped_junctions += 1
                    continue

                branches = []
                for branch in raw_branches:
                    road = roads[branch["road_idx"]]
                    cut_pos, tangent = sample_branch(road, branch["vertex_idx"], branch["direction"], walk_distance)
                    if tangent is None:
                        continue
                    branch = dict(branch)
                    branch["cut_pos"] = cut_pos
                    branch["tangent"] = tangent
                    branch["angle"] = angle_of(tangent)
                    branch["walk_distance"] = walk_distance
                    branch["junction_pos"] = junction_pos
                    branches.append(branch)

                if len(branches) < 3:
                    skipped_junctions += 1
                    continue

                branches.sort(key=lambda item: item["angle"])
                through_keys = set()
                if len(branches) == 3:
                    best_pair = None
                    for ai in range(len(branches)):
                        for bi in range(ai + 1, len(branches)):
                            angle = unsigned_angle_deg(branches[ai]["tangent"], branches[bi]["tangent"])
                            score = abs(180.0 - angle)
                            if best_pair is None or score < best_pair[0]:
                                best_pair = (score, angle, ai, bi)
                    if best_pair and best_pair[1] >= THROUGH_ANGLE_DEG:
                        t_junctions += 1
                        for idx in (best_pair[2], best_pair[3]):
                            branch = branches[idx]
                            through_keys.add((branch["road_idx"], branch["vertex_idx"], branch["direction"]))

                branch_arc_count = {}
                local_arcs = []
                for idx, branch_a in enumerate(branches):
                    branch_b = branches[(idx + 1) % len(branches)]
                    key_a = (branch_a["road_idx"], branch_a["vertex_idx"], branch_a["direction"])
                    key_b = (branch_b["road_idx"], branch_b["vertex_idx"], branch_b["direction"])
                    # Do not bridge across the straight-through pair in T junctions.
                    if key_a in through_keys and key_b in through_keys:
                        continue
                    gap = angle_delta_ccw(branch_a["angle"], branch_b["angle"])
                    gap_deg = math.degrees(gap)
                    if gap_deg < MIN_ANGLE_DEG or gap_deg > MAX_ANGLE_DEG:
                        continue
                    arc_points = build_tangent_arc(branch_a, branch_b, junction_pos)
                    if not arc_points:
                        continue
                    local_arcs.append((arc_points, branch_a, branch_b))
                    branch_arc_count[key_a] = branch_arc_count.get(key_a, 0) + 1
                    branch_arc_count[key_b] = branch_arc_count.get(key_b, 0) + 1

                if not local_arcs:
                    skipped_junctions += 1
                    continue

                processed_junctions += 1
                arc_records.extend(local_arcs)
                for branch in branches:
                    key = (branch["road_idx"], branch["vertex_idx"], branch["direction"])
                    if key in through_keys:
                        continue
                    if key not in branch_arc_count:
                        continue
                    road = roads[branch["road_idx"]]
                    junction_s = road["distances"][branch["vertex_idx"]]
                    cut_s = junction_s + branch["direction"] * branch["walk_distance"]
                    start = min(junction_s, cut_s)
                    end = max(junction_s, cut_s)
                    trim_windows.setdefault(branch["road_idx"], []).append((start, end))

            output_point_by_key = {}

            def point_key(pos):
                return (
                    round(float(pos[0]) / REUSE_TOLERANCE),
                    round(float(pos[2]) / REUSE_TOLERANCE),
                )

            def shared_point(pos):
                key = point_key(pos)
                point = output_point_by_key.get(key)
                if point is not None and length_xz(point.position(), pos) <= REUSE_TOLERANCE:
                    return point
                point = geo.createPoint()
                point.setPosition(pos)
                output_point_by_key[key] = point
                return point

            def add_polyline(points, src_prim, is_arc):
                if len(points) < 2:
                    return None
                poly = geo.createPolygon()
                poly.setIsClosed(False)
                for pos in points:
                    poly.addVertex(shared_point(pos))
                copy_prim_attrs(src_prim, poly, dst_attrs)
                try:
                    poly.setAttribValue(arc_attr, 1 if is_arc else 0)
                except Exception:
                    pass
                for name, members in group_members.items():
                    if src_prim.number() in members and name in dst_groups:
                        try:
                            dst_groups[name].add(poly)
                        except Exception:
                            pass
                return poly

            trimmed_prims = 0
            for road_idx, road in enumerate(roads):
                src_prim = road["src_prim"]
                distances = road["distances"]
                total = distances[-1]
                windows = sorted(trim_windows.get(road_idx, []))
                if not windows:
                    add_polyline(road["points"], src_prim, False)
                    continue
                merged = []
                for start, end in windows:
                    start = max(0.0, min(total, start))
                    end = max(0.0, min(total, end))
                    if end - start <= 0.01:
                        continue
                    if merged and start <= merged[-1][1] + 0.01:
                        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
                    else:
                        merged.append((start, end))
                cursor = 0.0
                emitted = 0
                for start, end in merged:
                    interval = extract_interval(road["points"], distances, cursor, start)
                    if add_polyline(interval, src_prim, False):
                        emitted += 1
                    cursor = max(cursor, end)
                interval = extract_interval(road["points"], distances, cursor, total)
                if add_polyline(interval, src_prim, False):
                    emitted += 1
                if emitted:
                    trimmed_prims += 1

            arc_prims = 0
            for arc_points, branch_a, _branch_b in arc_records:
                src_prim = roads[branch_a["road_idx"]]["src_prim"]
                if add_polyline(arc_points, src_prim, True):
                    arc_prims += 1

            set_global("road_junction_curve_smooth_status", "smoothed")
            set_global("road_junction_curve_smooth_enabled", int(ENABLED))
            set_global("road_junction_curve_smooth_curve_distance", float(CURVE_DISTANCE))
            set_global("road_junction_curve_smooth_candidate_junctions", int(len(junction_numbers)))
            set_global("road_junction_curve_smooth_processed_junctions", int(processed_junctions))
            set_global("road_junction_curve_smooth_arc_prims", int(arc_prims))
            set_global("road_junction_curve_smooth_trimmed_prims", int(trimmed_prims))
            set_global("road_junction_curve_smooth_skipped_junctions", int(skipped_junctions))
            set_global("road_junction_curve_smooth_t_junctions", int(t_junctions))
            set_global("road_junction_curve_smooth_output_prims", int(geo.intrinsicValue("primitivecount")))
            set_global("road_junction_curve_smooth_fallbacks", 0)
    except Exception as exc:
        passthrough("fallback", 1, "{}: {}".format(type(exc).__name__, exc))
