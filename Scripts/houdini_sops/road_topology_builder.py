# Houdini Python SOP — Road Topology Builder v3 (Milestone 2)
# Input: centerline polylines with per-primitive half-width attribute ("hw" or "road_hw" or fallback)
# Output: trimmed road strips (quads) and watertight junction fan polygons
#
# Algorithm:
#   1. Build adjacency graph from centerline endpoints (spatial hash, tolerance ~0.05m)
#   2. Detect adaptive junctions (degree >= 3) and classify into: Crossing, Junction, Freeway, or Roundabout
#   3. Calculate dynamic clipping margin Mi based on width, incident angles, and junction style
#   4. Trim each centerline from junction ends by Mi, emit corridor quads with shared boundary points
#   5. For each junction, gather the exact boundary points of the adjacent roads, sort radially, and emit watertight patch
#   6. Dead-ends (degree=1) get a rounded circular cap
#
# Attributes emitted:
#   road_face_area (prim)   — approximate face area in m²
#   road_segment_len (prim) — centerline segment length in m
#   is_junction (prim)      — 1 if this face is a junction fan, 0 otherwise
#

import math
import hou
from collections import defaultdict

node = hou.pwd()
geo_out = node.geometry()
geo_out.clear()

# ── helpers ──────────────────────────────────────────────────────────

def _v2(p):
    return (float(p[0]), float(p[2]))

def _vsub(a, b):
    return (a[0]-b[0], a[1]-b[1])

def _vlen(a):
    return math.hypot(a[0], a[1])

def _vnorm(a):
    l = _vlen(a)
    if l <= 1e-9:
        return (0.0, 0.0)
    return (a[0]/l, a[1]/l)

def _vperp(a):
    return (-a[1], a[0])

def _cross2(ax, az, bx, bz):
    return ax * bz - az * bx

def _poly_area_xz(pts):
    n = len(pts)
    if n < 3:
        return 0.0
    acc = 0.0
    for i in range(n):
        p0 = pts[i]
        p1 = pts[(i + 1) % n]
        acc += p0[0] * p1[1] - p1[0] * p0[1]
    return 0.5 * abs(acc)

def _segments_cross_xz(a0, a1, b0, b1):
    rx, rz = a1[0]-a0[0], a1[1]-a0[1]
    sx, sz = b1[0]-b0[0], b1[1]-b0[1]
    den = _cross2(rx, rz, sx, sz)
    if abs(den) < 1e-7:
        return False
    qpx, qpz = b0[0]-a0[0], b0[1]-a0[1]
    t = _cross2(qpx, qpz, sx, sz) / den
    u = _cross2(qpx, qpz, rx, rz) / den
    return 1e-4 < t < 0.9999 and 1e-4 < u < 0.9999

def _poly_self_intersects_xz(pts):
    n = len(pts)
    if n < 4:
        return False
    for i in range(n):
        a0, a1 = pts[i], pts[(i + 1) % n]
        for j in range(i + 2, n):
            if i == 0 and j == n-1:
                continue
            b0, b1 = pts[j], pts[(j + 1) % n]
            if _segments_cross_xz(a0, a1, b0, b1):
                return True
    return False

def _min_edge_len_xz(pts):
    if len(pts) < 2:
        return 0.0
    m = 1e9
    for i in range(len(pts)):
        p0 = pts[i]
        p1 = pts[(i + 1) % len(pts)]
        m = min(m, math.hypot(p1[0]-p0[0], p1[1]-p0[1]))
    return m if m < 1e9 else 0.0

def _min_angle_xz(pts):
    if len(pts) < 3:
        return None
    out = None
    for i, cur in enumerate(pts):
        prev = pts[(i - 1) % len(pts)]
        nxt = pts[(i + 1) % len(pts)]
        ax, az = prev[0] - cur[0], prev[1] - cur[1]
        bx, bz = nxt[0] - cur[0], nxt[1] - cur[1]
        al = _vlen((ax, az))
        bl = _vlen((bx, bz))
        if al <= 1e-9 or bl <= 1e-9:
            continue
        dot = max(-1.0, min(1.0, (ax * bx + az * bz) / (al * bl)))
        ang = math.degrees(math.acos(dot))
        out = ang if out is None else min(out, ang)
    return out

def _poly_length(pts):
    L = 0.0
    for i in range(len(pts)-1):
        dx = pts[i+1][0] - pts[i][0]
        dz = pts[i+1][2] - pts[i][2]
        L += math.hypot(dx, dz)
    return L

def _advance_along(pts, dist):
    """Walk along polyline pts (list of hou.Vector3) by dist meters from start."""
    if not pts or dist <= 0:
        return pts[0] if pts else None
    d = 0.0
    for i in range(len(pts)-1):
        p, q = pts[i], pts[i+1]
        seg = (q[0]-p[0], q[2]-p[2])
        L = _vlen(seg)
        if L <= 1e-9:
            continue
        if d + L >= dist:
            t = (dist - d) / L
            return hou.Vector3(p[0] + seg[0]*t, p[1] + (q[1]-p[1])*t, p[2] + seg[1]*t)
        d += L
    return pts[-1]

def _prim_hw(prim):
    for name in ("hw", "road_hw", "half_width"):
        try:
            if prim.geometry().findPrimAttrib(name):
                v = float(prim.attribValue(name))
                if v > 0:
                    return max(0.5, v)
        except Exception:
            pass
    try:
        if prim.geometry().findPrimAttrib("osm_width"):
            return max(0.5, float(prim.attribValue("osm_width")) * 0.5)
    except Exception:
        pass
    return 3.0

def _key(p):
    TOL = 0.05
    return (round(p[0]/TOL), round(p[2]/TOL))

def _pt_key(pt):
    """Unique key for vertex dedup (1cm grid)."""
    return (round(pt[0]*100), round(pt[1]*100), round(pt[2]*100))

# ── read input ───────────────────────────────────────────────────────

geo_in = node.inputs()[0].geometry() if node.inputs() else None
if geo_in is None:
    raise hou.Error("road_topology_builder: no input centerlines")

prims = [pr for pr in geo_in.prims() if len(pr.vertices()) >= 2]
if not prims:
    raise hou.Error("road_topology_builder: no valid centerline primitives")

# ── build graph ──────────────────────────────────────────────────────

poly_pts = {}   # prim -> list of hou.Vector3
prim_hw = {}    # prim -> half_width
endpoints = {}  # spatial_key -> [(prim, is_start, hw)]

for pr in prims:
    pts = [v.point().position() for v in pr.vertices()]
    if len(pts) < 2:
        continue
    poly_pts[pr] = pts
    hw = _prim_hw(pr)
    prim_hw[pr] = hw
    k0 = _key(pts[0])
    k1 = _key(pts[-1])
    endpoints.setdefault(k0, []).append((pr, True, hw))
    endpoints.setdefault(k1, []).append((pr, False, hw))

# ── Adaptive Junction Classification & Dynamic Mi ────────────────────

junction_R = {}  # (node_key, prim) -> Mi
junction_types = {}  # node_key -> type_string

# Identify junctions (degree >= 3)
junction_keys = [k for k, items in endpoints.items() if len(items) >= 3]

for k in junction_keys:
    items = endpoints[k]
    center_pos = hou.Vector3(k[0]*0.05, 0.0, k[1]*0.05)
    
    # 1. Classify Junction Type (Freeway / Junction / Crossing / Roundabout)
    is_freeway = False
    is_roundabout = False
    
    max_hw = 0.0
    sec_hw = 0.0
    
    for pr, is_start, hw in items:
        max_hw = max(max_hw, hw)
        hw_class = pr.attribValue("highway") if pr.geometry().findPrimAttrib("highway") else "residential"
        if hw_class in ("motorway", "trunk", "motorway_link", "trunk_link"):
            is_freeway = True
        if hw_class == "roundabout":
            is_roundabout = True

    # Find the second-widest road
    hw_vals = sorted([it[2] for it in items], reverse=True)
    if len(hw_vals) >= 2:
        sec_hw = hw_vals[1]

    # Decide type
    if is_roundabout:
        j_type = "Roundabout"
    elif is_freeway:
        j_type = "Freeway"
    elif sec_hw > 0 and (max_hw / sec_hw) >= 1.5:
        j_type = "Junction"  # Main-branch style
    else:
        j_type = "Crossing"  # Standard style

    junction_types[k] = j_type

    # 2. Sort incident roads radially to compute mutual angles
    radial_items = []
    for pr, is_start, hw in items:
        pts = poly_pts[pr]
        L = _poly_length(pts)
        p = _advance_along(pts, min(3.0, L*0.49)) if is_start else _advance_along(list(reversed(pts)), min(3.0, L*0.49))
        d = _vnorm(_vsub(_v2(p), (center_pos[0], center_pos[2])))
        angle = math.atan2(d[1], d[0])
        radial_items.append((angle, pr, is_start, hw, d))

    radial_items.sort(key=lambda x: x[0])
    n_inc = len(radial_items)

    # 3. Calculate dynamic clipping margin Mi for each incident edge
    # Corner radius styles
    r_corner = 6.0
    if j_type == "Freeway":
        r_corner = 20.0
    elif j_type == "Junction":
        r_corner = 5.0
    elif j_type == "Roundabout":
        r_corner = 4.0

    for i in range(n_inc):
        curr_ang, pr, is_start, hw, d = radial_items[i]
        
        # Calculate angle with left and right neighbors
        prev_ang, _, _, _, _ = radial_items[(i - 1) % n_inc]
        next_ang, _, _, _, _ = radial_items[(i + 1) % n_inc]
        
        diff_prev = abs(curr_ang - prev_ang)
        if diff_prev > math.pi:
            diff_prev = 2 * math.pi - diff_prev
            
        diff_next = abs(next_ang - curr_ang)
        if diff_next > math.pi:
            diff_next = 2 * math.pi - diff_next
            
        theta = min(diff_prev, diff_next)
        sin_theta = max(0.25, math.sin(theta))  # clamp to protect narrow angles

        # Find max width among neighbors
        w_max = max(hw, radial_items[(i - 1) % n_inc][3], radial_items[(i + 1) % n_inc][3])

        # Dynamic clip formula
        m_i = (w_max / (2.0 * sin_theta)) + r_corner

        # Principle Street exception: if Junction style, do not over-clip the main road
        if j_type == "Junction" and hw >= max_hw:
            # Main road gets very tight clipping
            m_i = (sec_hw / (2.0 * sin_theta)) + 0.5

        # Safety clamp: never trim more than 45% of total road length to prevent collapse
        L = _poly_length(poly_pts[pr])
        m_i = max(hw * 1.5, min(m_i, L * 0.45))

        junction_R[(k, pr)] = m_i

# ── vertex cache for dedup ───────────────────────────────────────────

_vert_cache = {}  # _pt_key -> hou.Point

def _get_pt(pos):
    """Return existing or new point at pos, deduplicating by 1cm grid."""
    k = _pt_key(pos)
    if k in _vert_cache:
        return _vert_cache[k]
    pt = geo_out.createPoint()
    pt.setPosition(pos)
    _vert_cache[k] = pt
    return pt

# ── attributes ───────────────────────────────────────────────────────

road_face_area_attr = geo_out.addAttrib(hou.attribType.Prim, 'road_face_area', 0.0)
road_segment_len_attr = geo_out.addAttrib(hou.attribType.Prim, 'road_segment_len', 0.0)
is_junction_attr = geo_out.addAttrib(hou.attribType.Prim, 'is_junction', 0)
half_width_attr = geo_out.addAttrib(hou.attribType.Prim, 'half_width', 0.0)
highway_attr = geo_out.addAttrib(hou.attribType.Prim, 'highway', '')
seg_id_attr = geo_out.addAttrib(hou.attribType.Prim, 'seg_id', -1)
from_node_attr = geo_out.addAttrib(hou.attribType.Prim, 'from_node', '')
to_node_attr = geo_out.addAttrib(hou.attribType.Prim, 'to_node', '')
skipped_corridor_attr = geo_out.addAttrib(hou.attribType.Global, 'rtb_skipped_degenerate_corridors', 0)
skipped_junction_attr = geo_out.addAttrib(hou.attribType.Global, 'rtb_skipped_degenerate_junction_tris', 0)

skipped_degenerate_corridors = 0
skipped_degenerate_junction_tris = 0

def _prim_val_str(pr, name, default=''):
    try:
        if pr.geometry().findPrimAttrib(name):
            v = pr.attribValue(name)
            return str(v) if v is not None else default
    except Exception:
        pass
    return default

def _prim_val_int(pr, name, default=-1):
    try:
        if pr.geometry().findPrimAttrib(name):
            v = pr.attribValue(name)
            return int(v)
    except Exception:
        pass
    return default

# ── emit corridor quads ──────────────────────────────────────────────

junction_boundary_points = defaultdict(list)  # node_key -> list of (x, y, z) actual boundary points

for pr, pts in poly_pts.items():
    hw = prim_hw[pr]
    L = _poly_length(pts)
    if L <= 1e-6:
        continue

    k0 = _key(pts[0])
    k1 = _key(pts[-1])
    t0 = junction_R.get((k0, pr), 0.0)
    t1 = junction_R.get((k1, pr), 0.0)

    # Build left/right boundary points along the original centerline,
    # sampling at each original vertex (clamped to trim range).
    acc = 0.0

    for i in range(len(pts)-1):
        p, q = pts[i], pts[i+1]
        seg = (q[0]-p[0], q[2]-p[2])
        seg_len = _vlen(seg)
        if seg_len <= 1e-9:
            continue

        t_dir = _vnorm(seg)
        n_dir = _vperp(t_dir)

        span_start = acc
        span_end = acc + seg_len
        acc = span_end

        trim_start_dist = t0
        trim_end_dist = L - t1 if t1 > 0 else L

        if span_end <= trim_start_dist or span_start >= trim_end_dist:
            continue

        local_start = max(span_start, trim_start_dist) - span_start
        local_end = min(span_end, trim_end_dist) - span_start

        p0 = hou.Vector3(
            p[0] + t_dir[0]*local_start,
            p[1] + (q[1]-p[1])*local_start/seg_len if seg_len>0 else p[1],
            p[2] + t_dir[1]*local_start)
        p1 = hou.Vector3(
            p[0] + t_dir[0]*local_end,
            p[1] + (q[1]-p[1])*local_end/seg_len if seg_len>0 else p[1],
            p[2] + t_dir[1]*local_end)

        left0 = hou.Vector3(p0[0] + n_dir[0]*hw, p0[1], p0[2] + n_dir[1]*hw)
        right0 = hou.Vector3(p0[0] - n_dir[0]*hw, p0[1], p0[2] - n_dir[1]*hw)
        left1 = hou.Vector3(p1[0] + n_dir[0]*hw, p1[1], p1[2] + n_dir[1]*hw)
        right1 = hou.Vector3(p1[0] - n_dir[0]*hw, p1[1], p1[2] - n_dir[1]*hw)

        # Collect final actual boundary points for Watertight Junction Fill
        if t0 > 0 and math.isclose(local_start, trim_start_dist - span_start, abs_tol=1e-3):
            junction_boundary_points[k0].append(left0)
            junction_boundary_points[k0].append(right0)
        if t1 > 0 and math.isclose(local_end, trim_end_dist - span_start, abs_tol=1e-3):
            junction_boundary_points[k1].append(left1)
            junction_boundary_points[k1].append(right1)

        # Degenerate guard: microscopic trim spans are safer to skip than to
        # triangulate into needle faces. Only real self-intersections attempt a
        # center fan fallback.
        quad2d = [ (left0[0], left0[2]), (left1[0], left1[2]), (right1[0], right1[2]), (right0[0], right0[2]) ]
        q_area = _poly_area_xz(quad2d)
        q_min_edge = _min_edge_len_xz(quad2d)
        if q_area < 0.05 or q_min_edge < 0.05:
            skipped_degenerate_corridors += 1
            continue
        if _poly_self_intersects_xz(quad2d):
            c = hou.Vector3(
                (left0[0]+left1[0]+right1[0]+right0[0])/4.0,
                (left0[1]+left1[1]+right1[1]+right0[1])/4.0,
                (left0[2]+left1[2]+right1[2]+right0[2])/4.0)
            tris = [ (left0, left1, c), (left1, right1, c), (right1, right0, c), (right0, left0, c) ]
            for a,b,cpos in tris:
                tri2d = [ (a[0],a[2]), (b[0],b[2]), (cpos[0],cpos[2]) ]
                t_area = _poly_area_xz(tri2d)
                if t_area < 0.05 or _min_edge_len_xz(tri2d) < 0.05:
                    skipped_degenerate_corridors += 1
                    continue
                tri = geo_out.createPolygon()
                for vpos in (a,b,cpos):
                    tri.addVertex(_get_pt(vpos))
                tri.setAttribValue(road_face_area_attr, float(t_area))
                tri.setAttribValue(road_segment_len_attr, 0.0)
                tri.setAttribValue(is_junction_attr, 0)
                tri.setAttribValue(half_width_attr, float(hw))
                tri.setAttribValue(highway_attr, _prim_val_str(pr, 'highway', ''))
                tri.setAttribValue(seg_id_attr, _prim_val_int(pr, 'seg_id', -1))
                tri.setAttribValue(from_node_attr, _prim_val_str(pr, 'from_node', ''))
                tri.setAttribValue(to_node_attr, _prim_val_str(pr, 'to_node', ''))
        else:
            quad = geo_out.createPolygon()
            for vpos in (left0, left1, right1, right0):
                quad.addVertex(_get_pt(vpos))
            quad.setAttribValue(road_face_area_attr, float(q_area))
            quad.setAttribValue(road_segment_len_attr, float(math.hypot(left1[0]-left0[0], left1[2]-left0[2])))
            quad.setAttribValue(is_junction_attr, 0)
            quad.setAttribValue(half_width_attr, float(hw))
            quad.setAttribValue(highway_attr, _prim_val_str(pr, 'highway', ''))
            quad.setAttribValue(seg_id_attr, _prim_val_int(pr, 'seg_id', -1))
            quad.setAttribValue(from_node_attr, _prim_val_str(pr, 'from_node', ''))
            quad.setAttribValue(to_node_attr, _prim_val_str(pr, 'to_node', ''))

    # ── Dead-end (degree=1) Rounded Circular Cap ─────────────────────
    if t0 == 0 and len(endpoints[k0]) == 1:
        # Emit a semi-circular cap at start point k0
        p = pts[0]
        seg = (pts[1][0]-pts[0][0], pts[1][2]-pts[0][2])
        t_dir = _vnorm(seg)
        n_dir = _vperp(t_dir)
        # Semi-circular segments
        cap_pts = []
        for d_ang in range(0, 181, 30):
            rad = math.radians(d_ang)
            # rotate n_dir around Y
            rx = n_dir[0] * math.cos(rad) - t_dir[0] * math.sin(rad)
            rz = n_dir[1] * math.cos(rad) - t_dir[1] * math.sin(rad)
            cap_pt = hou.Vector3(p[0] + rx * hw, p[1], p[2] + rz * hw)
            cap_pts.append(cap_pt)
        # emit cap polygon
        poly = geo_out.createPolygon()
        for cpos in reversed(cap_pts):
            poly.addVertex(_get_pt(cpos))
        poly.setAttribValue(road_face_area_attr, float(math.pi * hw * hw * 0.5))
        poly.setAttribValue(road_segment_len_attr, 0.0)
        poly.setAttribValue(is_junction_attr, 0)
        poly.setAttribValue(half_width_attr, float(hw))
        poly.setAttribValue(highway_attr, _prim_val_str(pr, 'highway', ''))
        poly.setAttribValue(seg_id_attr, _prim_val_int(pr, 'seg_id', -1))
        poly.setAttribValue(from_node_attr, _prim_val_str(pr, 'from_node', ''))
        poly.setAttribValue(to_node_attr, _prim_val_str(pr, 'to_node', ''))

    if t1 == 0 and len(endpoints[k1]) == 1:
        # Emit a semi-circular cap at end point k1
        p = pts[-1]
        seg = (pts[-1][0]-pts[-2][0], pts[-1][2]-pts[-2][2])
        t_dir = _vnorm(seg)
        n_dir = _vperp(t_dir)
        cap_pts = []
        for d_ang in range(0, 181, 30):
            rad = math.radians(d_ang)
            rx = n_dir[0] * math.cos(rad) + t_dir[0] * math.sin(rad)
            rz = n_dir[1] * math.cos(rad) + t_dir[1] * math.sin(rad)
            cap_pt = hou.Vector3(p[0] + rx * hw, p[1], p[2] + rz * hw)
            cap_pts.append(cap_pt)
        poly = geo_out.createPolygon()
        for cpos in cap_pts:
            poly.addVertex(_get_pt(cpos))
        poly.setAttribValue(road_face_area_attr, float(math.pi * hw * hw * 0.5))
        poly.setAttribValue(road_segment_len_attr, 0.0)
        poly.setAttribValue(is_junction_attr, 0)
        poly.setAttribValue(half_width_attr, float(hw))
        poly.setAttribValue(highway_attr, _prim_val_str(pr, 'highway', ''))
        poly.setAttribValue(seg_id_attr, _prim_val_int(pr, 'seg_id', -1))
        poly.setAttribValue(from_node_attr, _prim_val_str(pr, 'from_node', ''))
        poly.setAttribValue(to_node_attr, _prim_val_str(pr, 'to_node', ''))

# ── Watertight Junction Patch Generation ─────────────────────────────

for k in junction_keys:
    center = hou.Vector3(k[0]*0.05, 0.0, k[1]*0.05)
    rim = junction_boundary_points.get(k, [])

    if len(rim) < 3:
        continue

    # De-duplicate boundary points that snapped together (within 1cm)
    unique_rim = []
    seen = set()
    for p in rim:
        pt_k = _pt_key(p)
        if pt_k not in seen:
            seen.add(pt_k)
            unique_rim.append(p)

    if len(unique_rim) < 3:
        continue

    # Sort boundary points radially around the junction center to form watertight loop
    sorted_rim = []
    for p in unique_rim:
        d = _vnorm(_vsub(_v2(p), (center[0], center[2])))
        ang = math.atan2(d[1], d[0])
        sorted_rim.append((ang, p))

    sorted_rim.sort(key=lambda t: t[0])

    # Emit watertight patch if valid; otherwise fan-triangulate
    poly_pts_2d = [_v2(p) for _, p in sorted_rim]
    rim_min_angle = _min_angle_xz(poly_pts_2d)
    full_valid = (
        (not _poly_self_intersects_xz(poly_pts_2d))
        and (_poly_area_xz(poly_pts_2d) > 1e-5)
        and (_min_edge_len_xz(poly_pts_2d) >= 0.05)
        and (rim_min_angle is None or rim_min_angle >= 2.0)
        and (len(sorted_rim) <= 8)
    )
    if full_valid:
        poly = geo_out.createPolygon()
        for _, p in sorted_rim:
            poly.addVertex(_get_pt(p))
        area = _poly_area_xz(poly_pts_2d)
        poly.setAttribValue(road_face_area_attr, float(area))
        poly.setAttribValue(road_segment_len_attr, 0.0)
        poly.setAttribValue(is_junction_attr, 1)
        poly.setAttribValue(half_width_attr, 0.0)
        poly.setAttribValue(highway_attr, 'junction')
    else:
        center_pt = _get_pt(center)
        m = len(sorted_rim)
        for i in range(m):
            p0 = sorted_rim[i][1]
            p1 = sorted_rim[(i+1)%m][1]
            tri2d = [ (center[0],center[2]), (p0[0],p0[2]), (p1[0],p1[2]) ]
            t_area = _poly_area_xz(tri2d)
            t_angle = _min_angle_xz(tri2d)
            if t_area < 0.05 or _min_edge_len_xz(tri2d) < 0.05 or (t_angle is not None and t_angle < 2.0):
                skipped_degenerate_junction_tris += 1
                continue
            tri = geo_out.createPolygon()
            tri.addVertex(center_pt)
            tri.addVertex(_get_pt(p0))
            tri.addVertex(_get_pt(p1))
            tri.setAttribValue(road_face_area_attr, float(t_area))
            tri.setAttribValue(road_segment_len_attr, 0.0)
            tri.setAttribValue(is_junction_attr, 1)
            tri.setAttribValue(half_width_attr, 0.0)
            tri.setAttribValue(highway_attr, 'junction')

geo_out.setGlobalAttribValue('rtb_skipped_degenerate_corridors', int(skipped_degenerate_corridors))
geo_out.setGlobalAttribValue('rtb_skipped_degenerate_junction_tris', int(skipped_degenerate_junction_tris))

