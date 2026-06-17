"""Extract the near-intersection segments from the input centre lines.

Standalone Python SOP. Reads the merged centre polylines (input 0), finds where
they cross in the XZ plane, and outputs only the stretch of each line that lies
within a pscale-scaled arc-length window around each crossing -- i.e. the pieces
that actually need corner / arc processing downstream.
"""

import hou

EPS = 1.0e-9


def _polylines(geo):
    lines = []
    pscale_attr = geo.findPointAttrib("pscale")
    number_attr = geo.findPointAttrib("number")
    for prim in geo.prims():
        verts = list(prim.vertices())
        if len(verts) < 2:
            continue
        pts = []
        for vtx in verts:
            p = vtx.point()
            pos = p.position()
            pts.append({
                "pos": pos,
                "xz": (pos[0], pos[2]),
                "pscale": float(p.attribValue(pscale_attr)) if pscale_attr else 0.0,
                "number": int(p.attribValue(number_attr)) if number_attr else p.number(),
                "point": p,
            })
        cum = [0.0]
        for i in range(1, len(pts)):
            cum.append(cum[-1] + (pts[i]["pos"] - pts[i - 1]["pos"]).length())
        lines.append({"pts": pts, "cum": cum, "length": cum[-1]})
    return lines
def _orient(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _seg_cross(p1, p2, p3, p4):
    d1 = _orient(p3, p4, p1)
    d2 = _orient(p3, p4, p2)
    d3 = _orient(p1, p2, p3)
    d4 = _orient(p1, p2, p4)
    s1 = (d1 > EPS and d2 < -EPS) or (d1 < -EPS and d2 > EPS)
    s2 = (d3 > EPS and d4 < -EPS) or (d3 < -EPS and d4 > EPS)
    return s1 and s2


def _seg_intersection_xz(a, b, c, d):
    """Return (point2d, t_on_ab, u_on_cd) for the crossing of ab and cd, or None."""
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    denom = r[0] * s[1] - r[1] * s[0]
    if abs(denom) <= EPS:
        return None
    qp = (c[0] - a[0], c[1] - a[1])
    t = (qp[0] * s[1] - qp[1] * s[0]) / denom
    u = (qp[0] * r[1] - qp[1] * r[0]) / denom
    pt = (a[0] + r[0] * t, a[1] + r[1] * t)
    return pt, t, u


def _find_crossings(line0, line1):
    """Every XZ crossing between the two polylines.

    Each crossing is a dict {"point": Vector3 (y=0), "pscale": max pscale of the
    two lines at the crossing}. The max pscale drives the extraction radius.
    """
    pts0 = line0["pts"]
    pts1 = line1["pts"]
    crossings = []
    for i in range(len(pts0) - 1):
        a, b = pts0[i]["xz"], pts0[i + 1]["xz"]
        for j in range(len(pts1) - 1):
            c, d = pts1[j]["xz"], pts1[j + 1]["xz"]
            if not _seg_cross(a, b, c, d):
                continue
            hit = _seg_intersection_xz(a, b, c, d)
            if hit is None:
                continue
            pt, t, u = hit
            ps0 = pts0[i]["pscale"] * (1.0 - t) + pts0[i + 1]["pscale"] * t
            ps1 = pts1[j]["pscale"] * (1.0 - u) + pts1[j + 1]["pscale"] * u
            crossings.append({
                "point": hou.Vector3(pt[0], 0.0, pt[1]),
                "pscale": max(ps0, ps1),
            })
    return crossings
def _select_indices(line, crossings, multiplier):
    """Pick vertices that fall inside their nearest crossing's radius.

    Each vertex is assigned to the closest crossing (so when two crossings are
    near each other the midpoint between them splits ownership). The radius for
    that crossing is its max pscale * multiplier, so wider roads keep a longer
    stretch and a vertex never reaches past the halfway point to a neighbour.
    """
    pts = line["pts"]
    keep = set()
    for idx, src in enumerate(pts):
        pos = src["pos"]
        nearest = None
        best = None
        for cx in crossings:
            dist = (pos - cx["point"]).length()
            if best is None or dist < best:
                best = dist
                nearest = cx
        if nearest is not None and best <= nearest["pscale"] * multiplier:
            keep.add(idx)
    return keep


def _contiguous_runs(indices, count):
    """Split a set of vertex indices into maximal contiguous runs."""
    runs = []
    run = []
    for i in range(count):
        if i in indices:
            run.append(i)
        elif run:
            runs.append(run)
            run = []
    if run:
        runs.append(run)
    return runs


def _emit_run(geo, line, run, num_attr, ps_attr, n_attr, rest_attr):
    """Build one polyline from a contiguous run of line vertices."""
    if len(run) < 2:
        return None
    pts = line["pts"]
    poly = geo.createPolygon()
    poly.setIsClosed(False)
    for i in run:
        src = pts[i]
        p = geo.createPoint()
        p.setPosition(src["pos"])
        if num_attr:
            p.setAttribValue(num_attr, src["number"])
        if ps_attr:
            p.setAttribValue(ps_attr, src["pscale"])
        if n_attr:
            p.setAttribValue(n_attr, tuple(src["point"].attribValue("N")))
        if rest_attr:
            p.setAttribValue(rest_attr, tuple(src["point"].attribValue("rest")))
        poly.addVertex(p)
    return poly


def _downstream_multiplier(node):
    """Read pscale_distance_multiplier from the downstream integrated node.

    Falls back to this node's own window_multiplier, then 5.0.
    """
    for out in node.outputs():
        parm = out.parm("pscale_distance_multiplier")
        if parm is not None:
            return parm.eval()
    own = node.parm("window_multiplier")
    return own.eval() if own else 5.0


def build():
    node = hou.pwd()
    geo = node.geometry()
    src = node.inputGeometry(0)

    multiplier = _downstream_multiplier(node)

    lines = _polylines(src)
    geo.clear()
    if len(lines) < 2:
        return

    has_num = src.findPointAttrib("number") is not None
    has_ps = src.findPointAttrib("pscale") is not None
    has_n = src.findPointAttrib("N") is not None
    has_rest = src.findPointAttrib("rest") is not None
    num_attr = geo.addAttrib(hou.attribType.Point, "number", -1) if has_num else None
    ps_attr = geo.addAttrib(hou.attribType.Point, "pscale", 0.0) if has_ps else None
    n_attr = geo.addAttrib(hou.attribType.Point, "N", (0.0, 0.0, 0.0)) if has_n else None
    rest_attr = geo.addAttrib(hou.attribType.Point, "rest", (0.0, 0.0, 0.0)) if has_rest else None

    crossings = _find_crossings(lines[0], lines[1])
    if not crossings:
        return

    for line in lines:
        keep = _select_indices(line, crossings, multiplier)
        for run in _contiguous_runs(keep, len(line["pts"])):
            _emit_run(geo, line, run, num_attr, ps_attr, n_attr, rest_attr)


build()


