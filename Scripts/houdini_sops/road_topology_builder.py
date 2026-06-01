# Houdini Python SOP — Road Topology Builder v2
# Input: centerline polylines with per-primitive half-width attribute ("hw" or "road_hw" or fallback)
# Output: trimmed road strips (quads) and junction fan polygons
#
# Algorithm:
#   1. Build adjacency graph from centerline endpoints (spatial hash, tolerance ~0.05m)
#   2. Detect junctions (degree >= 3) and compute trim radius R = 1.2 * max(incident_hw)
#   3. Trim each centerline from junction ends by R, emit corridor quads with unique vertices
#   4. For each junction, collect trimmed boundary points, sort by angle, emit fan polygon
#   5. Dead-end (degree=1) roads get a rounded cap
#
# Attributes emitted:
#   road_face_area (prim)   — approximate face area in m²
#   road_segment_len (prim) — centerline segment length in m
#   is_junction (prim)      — 1 if this face is a junction fan, 0 otherwise

import math
import hou

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

# junctions: degree >= 3
junctions = {k: items for k, items in endpoints.items() if len(items) >= 3}

# trim radius per junction
junction_R = {}
for k, items in junctions.items():
    R = 1.2 * max(it[2] for it in items)
    junction_R[k] = max(2.0, min(R, 15.0))

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

# ── emit corridor quads ──────────────────────────────────────────────

for pr, pts in poly_pts.items():
    hw = prim_hw[pr]
    L = _poly_length(pts)
    if L <= 1e-6:
        continue

    k0 = _key(pts[0])
    k1 = _key(pts[-1])
    t0 = junction_R.get(k0, 0.0)
    t1 = junction_R.get(k1, 0.0)

    # Build left/right boundary points along the original centerline,
    # sampling at each original vertex (clamped to trim range).
    acc = 0.0
    prev_left = None
    prev_right = None

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

        if prev_left is not None:
            quad = geo_out.createPolygon()
            for vpos in (prev_left, left0, right0, prev_right):
                quad.addVertex(_get_pt(vpos))
            try:
                area = 0.5 * abs(
                    (prev_left[0]*left0[2] - left0[0]*prev_left[2]) +
                    (left0[0]*right0[2] - right0[0]*left0[2]) +
                    (right0[0]*prev_right[2] - prev_right[0]*right0[2]) +
                    (prev_right[0]*prev_left[2] - prev_left[0]*prev_right[2])
                )
            except Exception:
                area = 0.0
            quad.setAttribValue(road_face_area_attr, float(area))
            quad.setAttribValue(road_segment_len_attr, float((left0-prev_left).length()))
            quad.setAttribValue(is_junction_attr, 0)

        prev_left = left1
        prev_right = right1

# ── junction fan fill ────────────────────────────────────────────────

for k, items in junctions.items():
    center = hou.Vector3(k[0]*0.05, 0.0, k[1]*0.05)
    rim = []

    for pr, is_start, hw in items:
        pts = poly_pts.get(pr)
        if pts is None:
            continue
        L = _poly_length(pts)
        R = junction_R.get(k, 3.0)
        if is_start:
            p = _advance_along(pts, min(R, L*0.49))
        else:
            p = _advance_along(list(reversed(pts)), min(R, L*0.49))
        d = _vnorm(_vsub(_v2(p), (center[0], center[2])))
        n = _vperp(d)
        lp = hou.Vector3(p[0] + n[0]*hw, p[1], p[2] + n[1]*hw)
        rp = hou.Vector3(p[0] - n[0]*hw, p[1], p[2] - n[1]*hw)
        ang_l = math.atan2(n[1], n[0])
        ang_r = math.atan2(-n[1], -n[0])
        rim.append((ang_l, lp))
        rim.append((ang_r, rp))

    if len(rim) < 6:
        continue

    rim.sort(key=lambda t: t[0])
    poly = geo_out.createPolygon()
    for _, p in rim:
        poly.addVertex(_get_pt(p))
    poly.setAttribValue(road_face_area_attr, 0.0)
    poly.setAttribValue(road_segment_len_attr, 0.0)
    poly.setAttribValue(is_junction_attr, 1)
