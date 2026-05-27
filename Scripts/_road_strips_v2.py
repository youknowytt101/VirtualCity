"""
road_strips v4 - full-vertex junction detection, segment trimming, junction fill,
and debug attributes.

Input 0: road_width_flat (resampled centerlines + half_width/highway attrs)
Output: road quads + bounded junction fill polygons.
"""
import hou
import math

geo_in = hou.pwd().inputs()[0].geometry()
geo = hou.pwd().geometry()
geo.clear()

UP = hou.Vector3(0, 1, 0)
ROUND = 1.0
SEG_GRID = 25.0
MAX_INTERSECT_SEGMENTS = 12000
MAX_JUNCTION_RADIUS_FACTOR = 2.8
MAX_JUNCTION_RADIUS = 18.0
MAX_JUNCTION_AREA_FACTOR = 10.0
MAX_JUNCTION_AREA = 450.0


# -- Attribute definitions ----------------------------------------------------
def prim_attrib(name, default):
    attrib = geo.findPrimAttrib(name)
    return attrib if attrib else geo.addAttrib(hou.attribType.Prim, name, default)


def global_attrib(name, default):
    attrib = geo.findGlobalAttrib(name)
    return attrib if attrib else geo.addAttrib(hou.attribType.Global, name, default)


hw_attrib = prim_attrib("half_width", 0.0)
is_junc_a = prim_attrib("is_junction", 0)
road_src_a = prim_attrib("road_src_id", -1)
road_highway_a = prim_attrib("road_highway", "")
road_hw_a = prim_attrib("road_half_width", 0.0)
seg_len_a = prim_attrib("road_segment_len", 0.0)
face_area_a = prim_attrib("road_face_area", 0.0)
reject_reason_a = prim_attrib("junction_rejected_reason", "")

global_attrib("junction_fill_count", 0)
global_attrib("junction_rejected_small_count", 0)
global_attrib("junction_rejected_radius_count", 0)
global_attrib("junction_rejected_area_count", 0)
global_attrib("junction_rejected_total_count", 0)


# -- Helpers ------------------------------------------------------------------
def norm_vec(v):
    length = v.length()
    return v / length if length > 1e-6 else hou.Vector3(1, 0, 0)


def make_perp(tang):
    perp = UP.cross(tang)
    length = perp.length()
    return perp / length if length > 1e-6 else hou.Vector3(1, 0, 0)


def jkey(pos):
    return (round(pos[0] / ROUND) * ROUND, round(pos[2] / ROUND) * ROUND)


def convex_hull_xz(points):
    pts = list({(round(p[0], 2), round(p[2], 2)): p for p in points}.values())
    if len(pts) < 3:
        return pts
    start = min(range(len(pts)), key=lambda i: pts[i][0])
    hull = []
    cur = start
    while True:
        hull.append(pts[cur])
        nxt = (cur + 1) % len(pts)
        for i in range(len(pts)):
            ax = pts[nxt][0] - pts[cur][0]
            az = pts[nxt][2] - pts[cur][2]
            bx = pts[i][0] - pts[cur][0]
            bz = pts[i][2] - pts[cur][2]
            if ax * bz - az * bx < 0:
                nxt = i
        cur = nxt
        if cur == start:
            break
        if len(hull) > len(pts) + 1:
            break
    return hull


def poly_area_xz(points):
    if len(points) < 3:
        return 0.0
    area = 0.0
    for i, p in enumerate(points):
        q = points[(i + 1) % len(points)]
        area += p[0] * q[2] - q[0] * p[2]
    return abs(area) * 0.5


def centroid_xz(points):
    count = max(1, len(points))
    return hou.Vector3(
        sum(p[0] for p in points) / count,
        sum(p[1] for p in points) / count,
        sum(p[2] for p in points) / count,
    )


def cross2(ax, az, bx, bz):
    return ax * bz - az * bx


def segments_intersect_xz_simple(a0, a1, b0, b1):
    rx, rz = a1[0] - a0[0], a1[2] - a0[2]
    sx, sz = b1[0] - b0[0], b1[2] - b0[2]
    den = cross2(rx, rz, sx, sz)
    if abs(den) < 1e-7:
        return False
    qpx, qpz = b0[0] - a0[0], b0[2] - a0[2]
    t = cross2(qpx, qpz, sx, sz) / den
    u = cross2(qpx, qpz, rx, rz) / den
    return 1e-4 < t < 0.9999 and 1e-4 < u < 0.9999


def poly_self_intersections_xz(points):
    count = len(points)
    if count < 4:
        return 0
    hits = 0
    for i in range(count):
        a0, a1 = points[i], points[(i + 1) % count]
        for j in range(i + 1, count):
            if j == (i + 1) % count or i == (j + 1) % count:
                continue
            if i == 0 and j == count - 1:
                continue
            b0, b1 = points[j], points[(j + 1) % count]
            if segments_intersect_xz_simple(a0, a1, b0, b1):
                hits += 1
    return hits


def poly_min_angle_xz(points):
    if len(points) < 3:
        return None
    angles = []
    for i, cur in enumerate(points):
        prev = points[(i - 1) % len(points)]
        nxt = points[(i + 1) % len(points)]
        ax, az = prev[0] - cur[0], prev[2] - cur[2]
        bx, bz = nxt[0] - cur[0], nxt[2] - cur[2]
        al = math.sqrt(ax * ax + az * az)
        bl = math.sqrt(bx * bx + bz * bz)
        if al <= 0.05 or bl <= 0.05:
            continue
        dot = max(-1.0, min(1.0, (ax * bx + az * bz) / (al * bl)))
        angles.append(math.degrees(math.acos(dot)))
    return min(angles) if angles else None


def segment_intersection_xz(a0, a1, b0, b1):
    """Return (t, u, pos) for strict XZ intersection, or None."""
    px, pz = a0[0], a0[2]
    rx, rz = a1[0] - a0[0], a1[2] - a0[2]
    qx, qz = b0[0], b0[2]
    sx, sz = b1[0] - b0[0], b1[2] - b0[2]
    den = cross2(rx, rz, sx, sz)
    if abs(den) < 1e-6:
        return None
    qpx, qpz = qx - px, qz - pz
    t = cross2(qpx, qpz, sx, sz) / den
    u = cross2(qpx, qpz, rx, rz) / den
    if not (0.05 < t < 0.95 and 0.05 < u < 0.95):
        return None
    ay = a0[1] + (a1[1] - a0[1]) * t
    by = b0[1] + (b1[1] - b0[1]) * u
    return t, u, hou.Vector3(px + rx * t, (ay + by) * 0.5, pz + rz * t)


def append_unique_position(out, pos, eps=0.1):
    if out and (out[-1] - pos).length() < eps:
        return
    out.append(pos)


def prim_value(prim, name, default):
    try:
        return prim.attribValue(name)
    except Exception:
        return default


def prim_highway(prim):
    value = prim_value(prim, "highway", "")
    if value is None:
        return ""
    return str(value)


def set_road_attrs(poly, road, is_junction, segment_len, face_area, reason=""):
    hw = float(road.get("hw", 0.0))
    poly.setAttribValue(hw_attrib, hw)
    poly.setAttribValue(is_junc_a, int(is_junction))
    poly.setAttribValue(road_src_a, int(road.get("src_id", -1)))
    poly.setAttribValue(road_highway_a, str(road.get("highway", "")))
    poly.setAttribValue(road_hw_a, hw)
    poly.setAttribValue(seg_len_a, float(segment_len))
    poly.setAttribValue(face_area_a, float(face_area))
    poly.setAttribValue(reject_reason_a, str(reason))


# -- 1. Read roads ------------------------------------------------------------
road_data = []

for prim in geo_in.prims():
    hw = float(prim_value(prim, "half_width", 2.0) or 2.0)
    verts = list(prim.vertices())
    if len(verts) < 2:
        continue
    positions = []
    for v in verts:
        append_unique_position(positions, v.point().position(), eps=0.05)
    if len(positions) >= 2:
        road_data.append({
            "src_id": int(prim.number()),
            "highway": prim_highway(prim),
            "hw": hw,
            "positions": positions,
        })


# -- 1b. Insert visual intersections for roads that do not share vertices -----
segments = []
for ri, road in enumerate(road_data):
    ps = road["positions"]
    for si in range(len(ps) - 1):
        p0, p1 = ps[si], ps[si + 1]
        if (p1 - p0).length() < 0.25:
            continue
        mnx, mxx = min(p0[0], p1[0]), max(p0[0], p1[0])
        mnz, mxz = min(p0[2], p1[2]), max(p0[2], p1[2])
        segments.append((ri, si, p0, p1, mnx, mxx, mnz, mxz))

if len(segments) <= MAX_INTERSECT_SEGMENTS:
    insertions = {}
    grid = {}
    seen_pairs = set()
    for idx, seg in enumerate(segments):
        ri, si, p0, p1, mnx, mxx, mnz, mxz = seg
        gx0, gx1 = int(math.floor(mnx / SEG_GRID)), int(math.floor(mxx / SEG_GRID))
        gz0, gz1 = int(math.floor(mnz / SEG_GRID)), int(math.floor(mxz / SEG_GRID))
        nearby = set()
        for gx in range(gx0, gx1 + 1):
            for gz in range(gz0, gz1 + 1):
                nearby.update(grid.get((gx, gz), []))
        for j in nearby:
            pair = (j, idx) if j < idx else (idx, j)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            rj, sj, q0, q1, qmnx, qmxx, qmnz, qmxz = segments[j]
            if ri == rj:
                continue
            if mxx < qmnx or qmxx < mnx or mxz < qmnz or qmxz < mnz:
                continue
            hit = segment_intersection_xz(p0, p1, q0, q1)
            if not hit:
                continue
            t, u, ip = hit
            insertions.setdefault((ri, si), []).append((t, ip))
            insertions.setdefault((rj, sj), []).append((u, ip))
        for gx in range(gx0, gx1 + 1):
            for gz in range(gz0, gz1 + 1):
                grid.setdefault((gx, gz), []).append(idx)

    if insertions:
        for ri, road in enumerate(road_data):
            ps = road["positions"]
            rebuilt = []
            for si in range(len(ps) - 1):
                append_unique_position(rebuilt, ps[si], eps=0.05)
                added = sorted(insertions.get((ri, si), []), key=lambda x: x[0])
                for _t, ip in added:
                    append_unique_position(rebuilt, ip, eps=0.25)
            append_unique_position(rebuilt, ps[-1], eps=0.05)
            road["positions"] = rebuilt


# -- 1c. Count shared/inserted vertices ---------------------------------------
pt_usage = {}
for road in road_data:
    for pos in road["positions"]:
        key = jkey(pos)
        pt_usage[key] = pt_usage.get(key, 0) + 1


def is_junction(pos):
    return pt_usage.get(jkey(pos), 0) >= 2


# -- 2. Road quads + junction edge samples ------------------------------------
junction_pts = {}


def add_junction_edge(key, pos, hw, road):
    junction_pts.setdefault(key, []).append({
        "pos": pos,
        "hw": hw,
        "src_id": road.get("src_id", -1),
        "highway": road.get("highway", ""),
    })


def emit_chunk(road, positions):
    hw = float(road["hw"])
    count = len(positions)
    if count < 2:
        return

    tangs = []
    for i in range(count):
        if i == 0:
            tang = norm_vec(positions[1] - positions[0])
        elif i == count - 1:
            tang = norm_vec(positions[-1] - positions[-2])
        else:
            tang = norm_vec(positions[i + 1] - positions[i - 1])
        tangs.append(tang)

    seg_len = sum((positions[j + 1] - positions[j]).length() for j in range(count - 1))
    if seg_len < 1e-6:
        return

    start_trim = min(hw, seg_len * 0.45) if is_junction(positions[0]) else 0.0
    end_trim = min(hw, seg_len * 0.45) if is_junction(positions[-1]) else 0.0
    if start_trim + end_trim >= seg_len - 1e-4:
        return

    if start_trim > 0:
        perp = make_perp(tangs[0])
        trim_pos = positions[0] + tangs[0] * start_trim
        add_junction_edge(jkey(positions[0]), trim_pos + perp * hw, hw, road)
        add_junction_edge(jkey(positions[0]), trim_pos - perp * hw, hw, road)

    if end_trim > 0:
        perp = make_perp(tangs[-1])
        trim_pos = positions[-1] - tangs[-1] * end_trim
        add_junction_edge(jkey(positions[-1]), trim_pos + perp * hw, hw, road)
        add_junction_edge(jkey(positions[-1]), trim_pos - perp * hw, hw, road)

    lefts, rights = [], []
    if start_trim > 0:
        tp = positions[0] + tangs[0] * start_trim
        perp = make_perp(tangs[0])
        lefts.append(tp + perp * hw)
        rights.append(tp - perp * hw)

    cumlen = 0.0
    for i, pos in enumerate(positions):
        if i > 0:
            cumlen += (positions[i] - positions[i - 1]).length()
        if cumlen <= start_trim + 1e-4:
            continue
        if cumlen >= seg_len - end_trim - 1e-4:
            continue
        perp = make_perp(tangs[i])
        lefts.append(pos + perp * hw)
        rights.append(pos - perp * hw)

    if end_trim > 0:
        tp = positions[-1] - tangs[-1] * end_trim
        perp = make_perp(tangs[-1])
        lefts.append(tp + perp * hw)
        rights.append(tp - perp * hw)

    for i in range(len(lefts) - 1):
        pts_pos = [lefts[i], lefts[i + 1], rights[i + 1], rights[i]]
        min_angle = poly_min_angle_xz(pts_pos)
        needs_rect_fallback = (
            poly_self_intersections_xz(pts_pos)
            or (min_angle is not None and min_angle < 5.0)
        )
        if needs_rect_fallback:
            center0 = (lefts[i] + rights[i]) * 0.5
            center1 = (lefts[i + 1] + rights[i + 1]) * 0.5
            tang = norm_vec(center1 - center0)
            perp = make_perp(tang)
            pts_pos = [
                center0 + perp * hw,
                center1 + perp * hw,
                center1 - perp * hw,
                center0 - perp * hw,
            ]
            fallback_angle = poly_min_angle_xz(pts_pos)
            if (
                poly_self_intersections_xz(pts_pos)
                or poly_area_xz(pts_pos) < 1e-5
                or (fallback_angle is not None and fallback_angle < 2.0)
            ):
                continue
        hpts = [geo.createPoint() for _ in pts_pos]
        for point, pos in zip(hpts, pts_pos):
            point.setPosition(pos)
        quad = geo.createPolygon()
        for point in hpts:
            quad.addVertex(point)
        face_len = 0.5 * ((lefts[i + 1] - lefts[i]).length() + (rights[i + 1] - rights[i]).length())
        set_road_attrs(quad, road, 0, face_len, poly_area_xz(pts_pos))


for road in road_data:
    positions = road["positions"]
    if len(positions) < 2:
        continue
    start = 0
    for i in range(1, len(positions)):
        if is_junction(positions[i]) and i - start >= 1:
            emit_chunk(road, positions[start:i + 1])
            start = i
    if start < len(positions) - 1:
        emit_chunk(road, positions[start:])


# -- 3. Junction fill polygons -------------------------------------------------
junction_fill_count = 0
junction_rejected_small_count = 0
junction_rejected_radius_count = 0
junction_rejected_area_count = 0

for _jk, edge_data in junction_pts.items():
    if len(edge_data) < 3:
        junction_rejected_small_count += 1
        continue

    edge_pts = [item["pos"] for item in edge_data]
    hws = [max(0.1, float(item["hw"])) for item in edge_data]
    max_hw = max(hws)
    ctr = centroid_xz(edge_pts)
    max_radius = max(max_hw * MAX_JUNCTION_RADIUS_FACTOR, 3.0)
    max_radius = min(max_radius, MAX_JUNCTION_RADIUS)
    if max((p - ctr).length() for p in edge_pts) > max_radius:
        junction_rejected_radius_count += 1
        continue

    hull = convex_hull_xz(edge_pts)
    if len(hull) < 3:
        junction_rejected_small_count += 1
        continue
    if poly_self_intersections_xz(hull):
        junction_rejected_small_count += 1
        continue

    hull_area = poly_area_xz(hull)
    max_area = min(MAX_JUNCTION_AREA, max_hw * max_hw * MAX_JUNCTION_AREA_FACTOR)
    if hull_area > max_area:
        junction_rejected_area_count += 1
        continue

    hpts = [geo.createPoint() for _ in hull]
    for point, pos in zip(hpts, hull):
        point.setPosition(pos)
    poly = geo.createPolygon()
    for point in hpts:
        poly.addVertex(point)

    source_ids = [int(item.get("src_id", -1)) for item in edge_data]
    road = {
        "src_id": min(source_ids) if source_ids else -1,
        "highway": "junction",
        "hw": max_hw,
    }
    set_road_attrs(poly, road, 1, 0.0, hull_area)
    junction_fill_count += 1

geo.setGlobalAttribValue("junction_fill_count", int(junction_fill_count))
geo.setGlobalAttribValue("junction_rejected_small_count", int(junction_rejected_small_count))
geo.setGlobalAttribValue("junction_rejected_radius_count", int(junction_rejected_radius_count))
geo.setGlobalAttribValue("junction_rejected_area_count", int(junction_rejected_area_count))
geo.setGlobalAttribValue(
    "junction_rejected_total_count",
    int(junction_rejected_small_count + junction_rejected_radius_count + junction_rejected_area_count),
)
