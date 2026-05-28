import hou

MIN_DEPTH = 0.12
MAX_DEPTH = 25.0
TERRAIN_EPS = 0.03
SIDE_NORMAL_Y = 0.20
BOTTOM_Y_TOL = 0.01

# Input 0 must be the final building body, not an earlier footprint.
# The skirt top edge is copied from each actual wall bottom edge, so it cannot
# drift after fuse/divide/clip changes upstream.
body_geo = hou.pwd().inputs()[0].geometry()
terrain_geo = hou.pwd().inputs()[1].geometry()
geo = hou.pwd().geometry()
geo.clear()

is_foundation_a = geo.addAttrib(hou.attribType.Prim, "is_foundation", 0)

def terrain_y_at(x, z):
    pos = hou.Vector3()
    normal = hou.Vector3()
    uvw = hou.Vector3()
    hit = terrain_geo.intersect(
        hou.Vector3(x, 10000.0, z),
        hou.Vector3(0.0, -1.0, 0.0),
        pos,
        normal,
        uvw,
        min_hit=0.01,
        max_hit=20000.0,
        tolerance=0.01,
    )
    if hit >= 0:
        return pos.y()
    return None

def add_quad(a, b, c, d):
    pts = []
    for p in (a, b, c, d):
        pt = geo.createPoint()
        pt.setPosition(p)
        pts.append(pt)

    def make(order):
        prim = geo.createPolygon()
        for idx in order:
            prim.addVertex(pts[idx])
        prim.setAttribValue(is_foundation_a, 1)
        return prim

    prim = make([0, 1, 2, 3])
    return prim

def add_oriented_quad(top_a, top_b, bot_b, bot_a, ref_normal):
    prim = add_quad(top_a, top_b, bot_b, bot_a)
    if prim.normal().dot(ref_normal) >= 0:
        return prim
    pts = [v.point() for v in prim.vertices()]
    geo.deletePrims([prim], True)
    flipped = geo.createPolygon()
    for idx in (3, 2, 1, 0):
        flipped.addVertex(pts[idx])
    flipped.setAttribValue(is_foundation_a, 1)
    return flipped

def bottom_y_for(p):
    ty = terrain_y_at(p.x(), p.z())
    if ty is None:
        return p.y()
    bottom_y = min(ty + TERRAIN_EPS, p.y())
    if p.y() - bottom_y > MAX_DEPTH:
        bottom_y = p.y() - MAX_DEPTH
    return bottom_y

for prim in body_geo.prims():
    verts = list(prim.vertices())
    if len(verts) < 3:
        continue
    n = prim.normal()
    if abs(n.y()) > SIDE_NORMAL_Y:
        continue

    positions = [v.point().position() for v in verts]
    min_y = min(p.y() for p in positions)
    bottom_indices = [i for i, p in enumerate(positions) if abs(p.y() - min_y) <= BOTTOM_Y_TOL]
    if len(bottom_indices) < 2:
        continue

    bottom_positions = [positions[i] for i in bottom_indices]
    for i in range(len(bottom_positions) - 1):
        top_a = bottom_positions[i]
        top_b = bottom_positions[i + 1]
        bot_a = hou.Vector3(top_a.x(), bottom_y_for(top_a), top_a.z())
        bot_b = hou.Vector3(top_b.x(), bottom_y_for(top_b), top_b.z())
        if max(top_a.y() - bot_a.y(), top_b.y() - bot_b.y()) < MIN_DEPTH:
            continue
        add_oriented_quad(top_a, top_b, bot_b, bot_a, n)
