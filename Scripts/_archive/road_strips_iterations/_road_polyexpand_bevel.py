"""
road_polyexpand_bevel — PolyExpand2D 风格道路扩展
=================================================
输入 0: OSM road centerlines，primitive attrib: half_width

算法：
  - 每条中心线单独扩展成封闭道路面
  - 端点 End Style = Butt
  - 内部折线点 Join Style = Bevel，带 Miter Limit
  - 输出为道路 polygon，不做路口 union
"""
import hou, math

geo_in = hou.pwd().inputs()[0].geometry()
geo    = hou.pwd().geometry()

MITER_LIMIT = 2.0
EPS = 1e-6

# ── 2D helpers: Houdini XZ plane ──────────────────────────────────────────
def p2(v):
    return (float(v[0]), float(v[2]))

def add(a, b): return (a[0]+b[0], a[1]+b[1])
def sub(a, b): return (a[0]-b[0], a[1]-b[1])
def mul(a, s): return (a[0]*s, a[1]*s)
def dot(a, b): return a[0]*b[0] + a[1]*b[1]
def cross(a, b): return a[0]*b[1] - a[1]*b[0]
def length(a): return math.sqrt(a[0]*a[0] + a[1]*a[1])

def norm(a):
    l = length(a)
    if l < EPS: return (1.0, 0.0)
    return (a[0]/l, a[1]/l)

def left_perp(d):
    return (-d[1], d[0])

def line_intersection(p, r, q, s):
    den = cross(r, s)
    if abs(den) < EPS:
        return None
    t = cross(sub(q, p), s) / den
    return add(p, mul(r, t))

def signed_area(poly):
    a = 0.0
    n = len(poly)
    for i in range(n):
        x1, z1 = poly[i]
        x2, z2 = poly[(i+1) % n]
        a += x1*z2 - x2*z1
    return a * 0.5

def append_join(out_pts, center, d_prev, d_next, side, hw):
    # side: +1 left, -1 right
    n_prev = mul(left_perp(d_prev), side)
    n_next = mul(left_perp(d_next), side)

    p1 = add(center, mul(n_prev, hw))
    p2 = add(center, mul(n_next, hw))
    inter = line_intersection(p1, d_prev, p2, d_next)

    if inter is not None and length(sub(inter, center)) <= MITER_LIMIT * hw:
        out_pts.append(inter)
    else:
        out_pts.append(p1)
        if length(sub(p2, p1)) > 0.01:
            out_pts.append(p2)

# ── main ──────────────────────────────────────────────────────────────────
created = 0
skipped = 0

for prim in geo_in.prims():
    try:
        hw = float(prim.attribValue('half_width'))
    except Exception:
        hw = 2.0
    if hw < 0.05:
        skipped += 1
        continue

    verts = list(prim.vertices())
    pts = [p2(v.point().position()) for v in verts]

    # remove consecutive duplicate points
    clean = []
    for pt in pts:
        if not clean or length(sub(pt, clean[-1])) > 0.01:
            clean.append(pt)
    pts = clean
    n = len(pts)
    if n < 2:
        skipped += 1
        continue

    dirs = []
    valid = True
    for i in range(n-1):
        d = norm(sub(pts[i+1], pts[i]))
        if length(sub(pts[i+1], pts[i])) < 0.01:
            valid = False
            break
        dirs.append(d)
    if not valid:
        skipped += 1
        continue

    left = []
    right = []

    # Butt start
    n0 = left_perp(dirs[0])
    left.append(add(pts[0], mul(n0, hw)))
    right.append(add(pts[0], mul(n0, -hw)))

    # Internal bevel/miter joins
    for i in range(1, n-1):
        d_prev = dirs[i-1]
        d_next = dirs[i]
        center = pts[i]
        append_join(left,  center, d_prev, d_next, +1, hw)
        append_join(right, center, d_prev, d_next, -1, hw)

    # Butt end
    n1 = left_perp(dirs[-1])
    left.append(add(pts[-1], mul(n1, hw)))
    right.append(add(pts[-1], mul(n1, -hw)))

    poly_pts = left + list(reversed(right))

    # basic cleanup / reject degenerate polygons
    if len(poly_pts) < 3 or abs(signed_area(poly_pts)) < 0.01:
        skipped += 1
        continue

    # keep consistent winding
    if signed_area(poly_pts) < 0:
        poly_pts.reverse()

    hpts = []
    for x, z in poly_pts:
        p = geo.createPoint()
        p.setPosition(hou.Vector3(x, 0.0, z))
        hpts.append(p)

    poly = geo.createPolygon()
    for p in hpts:
        poly.addVertex(p)
    created += 1

import sys
print('[road_polyexpand_bevel] roads=%d created=%d skipped=%d prims=%d' % (
    len(list(geo_in.prims())), created, skipped, geo.primCount()), file=sys.stderr)
