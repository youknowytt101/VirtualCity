"""Houdini Python SOP: round hard bends inside individual road centerlines.

Input: road centerlines from road_centerline_resample.
Output: centerlines whose non-junction hard turns are replaced by tangent arcs.

This node deliberately skips shared junction points. Road intersections remain
owned by road_junction_curve_smooth; this node only rewrites ordinary bends
inside one road primitive.
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
MAX_BENDS = max(50, int("__MAX_BENDS__"))
REUSE_TOLERANCE = max(0.001, float("__REUSE_TOLERANCE__"))
TURN_DETECT_TOLERANCE = max(0.15, min(0.75, CURVE_DISTANCE * 0.08))
CHAIN_ENDPOINT_TOLERANCE = max(REUSE_TOLERANCE * 2.0, min(0.25, CURVE_DISTANCE * 0.04))
DIRECTION_MERGE_COS = math.cos(math.radians(12.0))
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


def angle_delta_ccw(a0, a1):
    return (a1 - a0) % math.tau


def unsigned_angle_deg(a, b):
    dot = max(-1.0, min(1.0, dot2(a, b)))
    return math.degrees(math.acos(dot))


def append_unique(points, pos, eps=0.01):
    if points and length_xz(points[-1], pos) <= eps:
        return
    points.append(pos)


def point_line_distance_xz(pos, a, b):
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
        return math.hypot(px - ax, pz - az)
    t = ((px - ax) * dx + (pz - az) * dz) / denom
    t = max(0.0, min(1.0, t))
    qx = ax + dx * t
    qz = az + dz * t
    return math.hypot(px - qx, pz - qz)


def rdp_indices(points, start, end, tolerance):
    if end - start <= 1:
        return [start, end] if end > start else [start]
    best_idx = None
    best_dist = 0.0
    for idx in range(start + 1, end):
        dist = point_line_distance_xz(points[idx], points[start], points[end])
        if dist > best_dist:
            best_dist = dist
            best_idx = idx
    if best_idx is not None and best_dist > tolerance:
        left = rdp_indices(points, start, best_idx, tolerance)
        right = rdp_indices(points, best_idx, end, tolerance)
        return left[:-1] + right
    return [start, end]


def local_turn_angle_deg(points, idx):
    prev_idx = idx - 1
    while prev_idx >= 0 and length_xz(points[prev_idx], points[idx]) <= EPS:
        prev_idx -= 1
    next_idx = idx + 1
    while next_idx < len(points) and length_xz(points[idx], points[next_idx]) <= EPS:
        next_idx += 1
    if prev_idx < 0 or next_idx >= len(points):
        return None
    tangent_in = normalize_xz(*vec_xz(points[prev_idx], points[idx]))
    tangent_out = normalize_xz(*vec_xz(points[idx], points[next_idx]))
    if tangent_in is None or tangent_out is None:
        return None
    return unsigned_angle_deg(tangent_in, tangent_out)


def ring_turn_angle_deg(points, idx):
    if len(points) < 3:
        return None
    prev_pos = points[(idx - 1) % len(points)]
    cur_pos = points[idx]
    next_pos = points[(idx + 1) % len(points)]
    tangent_in = normalize_xz(*vec_xz(prev_pos, cur_pos))
    tangent_out = normalize_xz(*vec_xz(cur_pos, next_pos))
    if tangent_in is None or tangent_out is None:
        return None
    return unsigned_angle_deg(tangent_in, tangent_out)


def ring_distance_markers(points):
    markers = [0.0]
    total = 0.0
    for idx in range(1, len(points)):
        total += length_xz(points[idx - 1], points[idx])
        markers.append(total)
    if len(points) > 1:
        total += length_xz(points[-1], points[0])
    return markers, total


def cyclic_marker_distance(markers, total, idx_a, idx_b):
    if total <= EPS:
        return 0.0
    delta = abs(markers[idx_a] - markers[idx_b])
    return min(delta, total - delta)


def rotate_closed_chain(points, point_numbers):
    if len(points) < 4:
        return points, point_numbers
    if point_numbers[0] != point_numbers[-1] and length_xz(points[0], points[-1]) > CHAIN_ENDPOINT_TOLERANCE:
        return points, point_numbers

    ring_points = list(points[:-1])
    ring_numbers = list(point_numbers[:-1])
    if len(ring_points) < 3:
        return points, point_numbers

    angles = []
    hard_indices = []
    for idx in range(len(ring_points)):
        angle = ring_turn_angle_deg(ring_points, idx)
        if angle is None:
            continue
        angles.append((idx, angle))
        if angle >= MIN_ANGLE_DEG:
            hard_indices.append(idx)

    if not angles:
        return ring_points + [ring_points[0]], ring_numbers + [ring_numbers[0]]

    best_idx = 0
    if hard_indices:
        markers, total = ring_distance_markers(ring_points)
        best_score = None
        for idx, angle in angles:
            nearest_hard = min(cyclic_marker_distance(markers, total, idx, hard_idx) for hard_idx in hard_indices)
            score = (nearest_hard, -angle)
            if best_score is None or score > best_score:
                best_idx = idx
                best_score = score
    else:
        best_angle = None
        for idx, angle in angles:
            if best_angle is None or angle < best_angle:
                best_idx = idx
                best_angle = angle

    if best_idx == 0:
        return ring_points + [ring_points[0]], ring_numbers + [ring_numbers[0]]
    return (
        ring_points[best_idx:] + ring_points[:best_idx + 1],
        ring_numbers[best_idx:] + ring_numbers[:best_idx + 1],
    )


def add_unique_direction(directions, direction):
    if direction is None:
        return
    for existing in directions:
        if dot2(existing, direction) >= DIRECTION_MERGE_COS:
            return
    directions.append(direction)


def turn_candidate_indices(points, point_numbers, shared_point_numbers):
    boundaries = [0]
    for idx in range(1, len(points) - 1):
        if point_numbers[idx] in shared_point_numbers:
            boundaries.append(idx)
    boundaries.append(len(points) - 1)

    candidates = set()
    for bidx in range(len(boundaries) - 1):
        start = boundaries[bidx]
        end = boundaries[bidx + 1]
        if end - start < 2:
            continue
        anchors = rdp_indices(points, start, end, TURN_DETECT_TOLERANCE)
        for anchor_idx in anchors[1:-1]:
            if point_numbers[anchor_idx] not in shared_point_numbers:
                candidates.add(anchor_idx)
        for idx in range(start + 1, end):
            if point_numbers[idx] in shared_point_numbers:
                continue
            angle = local_turn_angle_deg(points, idx)
            if angle is not None and MIN_ANGLE_DEG <= angle <= MAX_ANGLE_DEG:
                candidates.add(idx)
    return sorted(candidates)


def cumulative_lengths(points):
    out = [0.0]
    total = 0.0
    for idx in range(len(points) - 1):
        total += length_xz(points[idx], points[idx + 1])
        out.append(total)
    return out


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


def nearest_boundary_indices(idx, point_numbers, shared_point_numbers):
    prev_idx = 0
    next_idx = len(point_numbers) - 1
    for scan in range(idx - 1, -1, -1):
        if point_numbers[scan] in shared_point_numbers:
            prev_idx = scan
            break
    for scan in range(idx + 1, len(point_numbers)):
        if point_numbers[scan] in shared_point_numbers:
            next_idx = scan
            break
    return prev_idx, next_idx


def incident_degree(points, vertex_idx):
    degree = 0
    if vertex_idx > 0 and length_xz(points[vertex_idx - 1], points[vertex_idx]) > EPS:
        degree += 1
    if vertex_idx + 1 < len(points) and length_xz(points[vertex_idx], points[vertex_idx + 1]) > EPS:
        degree += 1
    return degree


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
    delta = angle_delta_ccw(a0, a1) if ccw else -angle_delta_ccw(a1, a0)
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


def build_tangent_arc(turn):
    p0 = turn["cut_start"]
    p1 = turn["cut_end"]
    t0 = turn["tangent_in"]
    t1 = turn["tangent_out"]
    bend_pos = turn["bend_pos"]
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
                score = length_xz(midpoint, bend_pos) + tangent_error * 5.0 + max(0.0, delta - math.pi) * radius
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
    set_global("road_turn_curve_smooth_status", status)
    set_global("road_turn_curve_smooth_enabled", int(ENABLED))
    set_global("road_turn_curve_smooth_curve_distance", float(CURVE_DISTANCE))
    set_global("road_turn_curve_smooth_candidate_bends", 0)
    set_global("road_turn_curve_smooth_processed_bends", 0)
    set_global("road_turn_curve_smooth_skipped_bends", 0)
    set_global("road_turn_curve_smooth_fallbacks", int(fallbacks))
    if message:
        set_global("road_turn_curve_smooth_message", str(message)[:240])


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
        arc_attr = geo.findPrimAttrib("road_turn_curve_smooth_arc") or geo.addAttrib(
            hou.attribType.Prim, "road_turn_curve_smooth_arc", 0
        )

        group_members = {}
        dst_groups = {}
        for group in geo_in.primGroups():
            try:
                group_members[group.name()] = set(prim.number() for prim in group.prims())
                dst_groups[group.name()] = geo.createPrimGroup(group.name())
            except Exception:
                pass

        point_usage = {}
        point_incident_directions = {}
        for prim in geo_in.prims():
            seen = set()
            vertices = list(prim.vertices())
            for vertex_idx, vertex in enumerate(vertices):
                try:
                    point_number = vertex.point().number()
                    pos = vertex.point().position()
                    seen.add(point_number)
                    if vertex_idx > 0:
                        prev_pos = vertices[vertex_idx - 1].point().position()
                        direction = normalize_xz(*vec_xz(pos, prev_pos))
                        add_unique_direction(point_incident_directions.setdefault(point_number, []), direction)
                    if vertex_idx + 1 < len(vertices):
                        next_pos = vertices[vertex_idx + 1].point().position()
                        direction = normalize_xz(*vec_xz(pos, next_pos))
                        add_unique_direction(point_incident_directions.setdefault(point_number, []), direction)
                except Exception:
                    pass
            for point_number in seen:
                point_usage[point_number] = point_usage.get(point_number, 0) + 1
        shared_point_numbers = {
            point_number
            for point_number, count in point_usage.items()
            if count > 1 and len(point_incident_directions.get(point_number, ())) >= 3
        }

        candidate_bends = 0
        processed_bends = 0
        skipped_bends = 0
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

        def build_chains():
            roads = []
            for prim in geo_in.prims():
                pts, nums = clean_road_points(prim)
                if len(pts) >= 2:
                    roads.append({"src_prim": prim, "points": pts, "point_numbers": nums})

            endpoint_map = {}

            def endpoint_grid_key(pos):
                return (
                    round(float(pos[0]) / CHAIN_ENDPOINT_TOLERANCE),
                    round(float(pos[2]) / CHAIN_ENDPOINT_TOLERANCE),
                )

            def neighbor_endpoint_keys(key):
                for dx in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        yield key[0] + dx, key[1] + dz

            def endpoint_cluster_key(pos):
                grid_key = endpoint_grid_key(pos)
                for near_key in neighbor_endpoint_keys(grid_key):
                    refs = endpoint_map.get(near_key)
                    if refs and length_xz(refs[0][2], pos) <= CHAIN_ENDPOINT_TOLERANCE:
                        return near_key
                return grid_key

            for road_idx, road in enumerate(roads):
                pts = road["points"]
                for endpoint_idx in (0, len(pts) - 1):
                    key = endpoint_cluster_key(pts[endpoint_idx])
                    endpoint_map.setdefault(key, []).append(
                        (road_idx, endpoint_idx, pts[endpoint_idx], road["point_numbers"][endpoint_idx])
                    )

            used = set()
            chains = []

            def chain_endpoint_key(pos):
                grid_key = endpoint_grid_key(pos)
                best = None
                best_dist = CHAIN_ENDPOINT_TOLERANCE
                for near_key in neighbor_endpoint_keys(grid_key):
                    for _road_idx, _endpoint_idx, endpoint_pos, _point_number in endpoint_map.get(near_key, ()):
                        dist = length_xz(endpoint_pos, pos)
                        if dist <= best_dist:
                            best = near_key
                            best_dist = dist
                return best

            def endpoint_out_direction(road_idx, endpoint_idx):
                road = roads[road_idx]
                points = road["points"]
                if endpoint_idx == 0 and len(points) >= 2:
                    return normalize_xz(*vec_xz(points[0], points[1]))
                if endpoint_idx == len(points) - 1 and len(points) >= 2:
                    return normalize_xz(*vec_xz(points[-1], points[-2]))
                return None

            def endpoint_direction_groups(refs):
                groups = []
                for road_idx, endpoint_idx, _pos, _point_number in refs:
                    direction = endpoint_out_direction(road_idx, endpoint_idx)
                    if direction is None:
                        continue
                    matched = False
                    for group in groups:
                        if dot2(group["direction"], direction) >= DIRECTION_MERGE_COS:
                            group["refs"].append((road_idx, endpoint_idx))
                            matched = True
                            break
                    if not matched:
                        groups.append({"direction": direction, "refs": [(road_idx, endpoint_idx)]})
                return groups

            def mergeable_endpoint(key):
                refs = endpoint_map.get(key, ()) if key is not None else ()
                groups = endpoint_direction_groups(refs)
                if len(groups) != 2:
                    return False
                for _road_idx, _endpoint_idx, _pos, point_number in refs:
                    if point_number in shared_point_numbers:
                        return False
                return True

            def other_endpoint_road(key, current_direction):
                refs = endpoint_map.get(key, ())
                for group in endpoint_direction_groups(refs):
                    if current_direction is not None and dot2(group["direction"], current_direction) >= DIRECTION_MERGE_COS:
                        continue
                    for road_idx, endpoint_idx in group["refs"]:
                        if road_idx not in used:
                            return road_idx, endpoint_idx
                return None

            for seed_idx, seed in enumerate(roads):
                if seed_idx in used:
                    continue
                used.add(seed_idx)
                src_prim = seed["src_prim"]
                points = list(seed["points"])
                point_numbers = list(seed["point_numbers"])

                changed = True
                while changed:
                    changed = False
                    front_key = chain_endpoint_key(points[0])
                    if mergeable_endpoint(front_key):
                        current_direction = normalize_xz(*vec_xz(points[0], points[1])) if len(points) >= 2 else None
                        match = other_endpoint_road(front_key, current_direction)
                        if match is not None:
                            other_idx, endpoint_idx = match
                            other = roads[other_idx]
                            used.add(other_idx)
                            if endpoint_idx == 0:
                                add_points = list(reversed(other["points"]))[:-1]
                                add_numbers = list(reversed(other["point_numbers"]))[:-1]
                            else:
                                add_points = other["points"][:-1]
                                add_numbers = other["point_numbers"][:-1]
                            points = add_points + points
                            point_numbers = add_numbers + point_numbers
                            changed = True
                            continue

                    back_key = chain_endpoint_key(points[-1])
                    if mergeable_endpoint(back_key):
                        current_direction = normalize_xz(*vec_xz(points[-1], points[-2])) if len(points) >= 2 else None
                        match = other_endpoint_road(back_key, current_direction)
                        if match is not None:
                            other_idx, endpoint_idx = match
                            other = roads[other_idx]
                            used.add(other_idx)
                            if endpoint_idx == 0:
                                add_points = other["points"][1:]
                                add_numbers = other["point_numbers"][1:]
                            else:
                                add_points = list(reversed(other["points"]))[1:]
                                add_numbers = list(reversed(other["point_numbers"]))[1:]
                            points = points + add_points
                            point_numbers = point_numbers + add_numbers
                            changed = True

                points, point_numbers = rotate_closed_chain(points, point_numbers)
                chains.append({
                    "src_prim": src_prim,
                    "points": points,
                    "point_numbers": point_numbers,
                })
            return chains

        for chain in build_chains():
            prim = chain["src_prim"]
            points = chain["points"]
            point_numbers = chain["point_numbers"]
            if len(points) < 3:
                add_polyline(points, prim, False)
                continue
            distances = cumulative_lengths(points)
            total = distances[-1]
            turns = []
            last_end = -1.0
            for idx in turn_candidate_indices(points, point_numbers, shared_point_numbers):
                prev_boundary_idx, next_boundary_idx = nearest_boundary_indices(
                    idx, point_numbers, shared_point_numbers
                )
                prev_pos = point_at_distance(points, distances, max(distances[prev_boundary_idx], distances[idx] - CURVE_DISTANCE))
                bend_pos = points[idx]
                next_pos = point_at_distance(points, distances, min(distances[next_boundary_idx], distances[idx] + CURVE_DISTANCE))
                tangent_in = normalize_xz(*vec_xz(prev_pos, bend_pos))
                tangent_out = normalize_xz(*vec_xz(bend_pos, next_pos))
                if tangent_in is None or tangent_out is None:
                    continue
                bend_angle = unsigned_angle_deg(tangent_in, tangent_out)
                if bend_angle < MIN_ANGLE_DEG or bend_angle > MAX_ANGLE_DEG:
                    continue
                candidate_bends += 1
                if processed_bends >= MAX_BENDS:
                    skipped_bends += 1
                    continue
                before_len = distances[idx] - distances[prev_boundary_idx]
                after_len = distances[next_boundary_idx] - distances[idx]
                walk_distance = min(CURVE_DISTANCE, before_len * 0.45, after_len * 0.45)
                if walk_distance < MIN_BRANCH_DISTANCE:
                    skipped_bends += 1
                    continue
                start_s = distances[idx] - walk_distance
                end_s = distances[idx] + walk_distance
                if start_s <= last_end + 0.05:
                    skipped_bends += 1
                    continue
                turn = {
                    "cut_start": point_at_distance(points, distances, start_s),
                    "cut_end": point_at_distance(points, distances, end_s),
                    "tangent_in": tangent_in,
                    "tangent_out": tangent_out,
                    "bend_pos": bend_pos,
                    "start_s": start_s,
                    "end_s": end_s,
                }
                arc_points = build_tangent_arc(turn)
                if not arc_points:
                    skipped_bends += 1
                    continue
                turn["arc_points"] = arc_points
                turns.append(turn)
                last_end = end_s
                processed_bends += 1

            if not turns:
                add_polyline(points, prim, False)
                continue
            cursor = 0.0
            for turn in turns:
                add_polyline(extract_interval(points, distances, cursor, turn["start_s"]), prim, False)
                add_polyline(turn["arc_points"], prim, True)
                cursor = turn["end_s"]
            add_polyline(extract_interval(points, distances, cursor, total), prim, False)

            set_global("road_turn_curve_smooth_status", "smoothed")
            set_global("road_turn_curve_smooth_enabled", int(ENABLED))
            set_global("road_turn_curve_smooth_curve_distance", float(CURVE_DISTANCE))
            set_global("road_turn_curve_smooth_candidate_bends", int(candidate_bends))
            set_global("road_turn_curve_smooth_processed_bends", int(processed_bends))
            set_global("road_turn_curve_smooth_skipped_bends", int(skipped_bends))
            set_global("road_turn_curve_smooth_output_prims", int(geo.intrinsicValue("primitivecount")))
            set_global("road_turn_curve_smooth_fallbacks", 0)
    except Exception as exc:
        passthrough("fallback", 1, "{}: {}".format(type(exc).__name__, exc))
