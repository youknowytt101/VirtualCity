import hou, math

BEVEL_DIST = 0.60
MAX_ANGLE_DEG = 100.0
ANGLE_EPS_DEG = 2.0
MAX_EDGE_FRACTION = 0.25
MIN_CUT = 0.08
MIN_EDGE_LEN = 0.35

src_geo = hou.pwd().inputs()[0].geometry()
geo = hou.pwd().geometry()
geo.clear()

prim_attribs = []
for attrib in src_geo.primAttribs():
    if attrib.name() == "P":
        continue
    try:
        new_attrib = geo.addAttrib(hou.attribType.Prim, attrib.name(), attrib.defaultValue())
        prim_attribs.append((attrib, new_attrib))
    except Exception:
        pass

bevel_a = geo.addAttrib(hou.attribType.Prim, "footprint_bevel_count", 0)

def v2(p):
    return (float(p.x()), float(p.z()))

def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])

def add(a, b):
    return (a[0] + b[0], a[1] + b[1])

def mul(a, s):
    return (a[0] * s, a[1] * s)

def length(a):
    return math.sqrt(a[0] * a[0] + a[1] * a[1])

def norm(a):
    l = length(a)
    if l <= 1e-9:
        return (0.0, 0.0)
    return (a[0] / l, a[1] / l)

def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]

def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]

def signed_area(points):
    acc = 0.0
    n = len(points)
    for i, p in enumerate(points):
        q = points[(i + 1) % n]
        acc += p[0] * q[1] - q[0] * p[1]
    return acc * 0.5

def angle_deg(prev_p, curr_p, next_p):
    a = norm(sub(prev_p, curr_p))
    b = norm(sub(next_p, curr_p))
    d = max(-1.0, min(1.0, dot(a, b)))
    return math.degrees(math.acos(d))

def make_point(xz, y):
    pt = geo.createPoint()
    pt.setPosition(hou.Vector3(xz[0], y, xz[1]))
    return pt

for prim in src_geo.prims():
    try:
        if not prim.isClosed():
            continue
    except Exception:
        pass

    verts = list(prim.vertices())
    if len(verts) < 3:
        continue

    src_positions = [v.point().position() for v in verts]
    points = [v2(p) for p in src_positions]
    base_y = sum(p.y() for p in src_positions) / len(src_positions)
    area = signed_area(points)
    if abs(area) <= 1e-6:
        continue
    orient = 1.0 if area > 0.0 else -1.0

    new_points = []
    bevel_count = 0
    n = len(points)
    for i, curr in enumerate(points):
        prev_p = points[(i - 1) % n]
        next_p = points[(i + 1) % n]
        prev_edge = sub(curr, prev_p)
        next_edge = sub(next_p, curr)
        prev_len = length(prev_edge)
        next_len = length(next_edge)
        turn = cross(prev_edge, next_edge)
        convex = turn * orient > 1e-8
        ang = angle_deg(prev_p, curr, next_p)

        can_bevel = (
            convex
            and ang <= MAX_ANGLE_DEG + ANGLE_EPS_DEG
            and prev_len >= MIN_EDGE_LEN
            and next_len >= MIN_EDGE_LEN
        )

        if not can_bevel:
            new_points.append(curr)
            continue

        cut = min(
            BEVEL_DIST,
            prev_len * MAX_EDGE_FRACTION,
            next_len * MAX_EDGE_FRACTION,
        )
        if cut < MIN_CUT:
            new_points.append(curr)
            continue

        into_prev = norm(sub(prev_p, curr))
        into_next = norm(sub(next_p, curr))
        new_points.append(add(curr, mul(into_prev, cut)))
        new_points.append(add(curr, mul(into_next, cut)))
        bevel_count += 1

    if len(new_points) < 3:
        continue

    new_prim = geo.createPolygon()
    for p in new_points:
        new_prim.addVertex(make_point(p, base_y))
    for src_attr, dst_attr in prim_attribs:
        try:
            new_prim.setAttribValue(dst_attr, prim.attribValue(src_attr))
        except Exception:
            pass
    new_prim.setAttribValue(bevel_a, bevel_count)
