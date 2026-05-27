"""
road_strips v3 — 全顶点路口识别 + 路段修剪 + 路口凸包填充
==========================================================
替换原 road_strips Python SOP。
输入 0: road_width_flat（resample + half_width attrib，Y=0）
输出:  路面 quad + 路口填充多边形，无 Z-fighting，无路口空洞。
"""
import hou, math

geo_in  = hou.pwd().inputs()[0].geometry()
geo     = hou.pwd().geometry()
geo.clear()
UP      = hou.Vector3(0, 1, 0)
ROUND   = 1.0   # 路口检测空间哈希精度 (m)
SEG_GRID = 25.0 # 未共享节点的视觉相交道路检测网格 (m)
MAX_INTERSECT_SEGMENTS = 12000
MAX_JUNCTION_RADIUS_FACTOR = 2.8
MAX_JUNCTION_RADIUS = 18.0
MAX_JUNCTION_AREA_FACTOR = 10.0
MAX_JUNCTION_AREA = 450.0

# ── attrib 定义 ──────────────────────────────────────────────────────────────
def _get_or_add(geo, atype, name, default):
    a = geo.findPrimAttrib(name) if atype == hou.attribType.Prim else None
    return a if a else geo.addAttrib(atype, name, default)
hw_attrib = _get_or_add(geo, hou.attribType.Prim, 'half_width', 0.0)
is_junc_a = _get_or_add(geo, hou.attribType.Prim, 'is_junction', 0)

# ── 辅助函数 ──────────────────────────────────────────────────────────────────
def norm_vec(v):
    l = v.length()
    return v / l if l > 1e-6 else hou.Vector3(1, 0, 0)

def make_perp(tang):
    perp = UP.cross(tang)
    l = perp.length()
    return perp / l if l > 1e-6 else hou.Vector3(1, 0, 0)

def jkey(pos):
    return (round(pos[0] / ROUND) * ROUND, round(pos[2] / ROUND) * ROUND)

def convex_hull_xz(points):
    """2D Convex hull in XZ plane (Jarvis march / gift wrap)."""
    pts = list({(round(p[0], 2), round(p[2], 2)): p for p in points}.values())
    if len(pts) < 3:
        return pts
    # Start from leftmost
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
            cross = ax * bz - az * bx
            if cross < 0:
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
    n = max(1, len(points))
    return hou.Vector3(
        sum(p[0] for p in points) / n,
        sum(p[1] for p in points) / n,
        sum(p[2] for p in points) / n,
    )

def cross2(ax, az, bx, bz):
    return ax * bz - az * bx

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
    # Avoid endpoint hits; shared/near endpoints are handled by jkey usage.
    if not (0.05 < t < 0.95 and 0.05 < u < 0.95):
        return None
    ay = a0[1] + (a1[1] - a0[1]) * t
    by = b0[1] + (b1[1] - b0[1]) * u
    return t, u, hou.Vector3(px + rx * t, (ay + by) * 0.5, pz + rz * t)

def append_unique_position(out, pos, eps=0.1):
    if out and (out[-1] - pos).length() < eps:
        return
    out.append(pos)

# ── 1. 读取所有道路 ─────────────────────────────────────────────────────────
road_data = []   # [{'hw': half_width, 'positions': [Vector3, ...]}]

for prim in geo_in.prims():
    try:    hw = prim.attribValue('half_width')
    except: hw = 2.0
    verts = list(prim.vertices())
    if len(verts) < 2:
        continue
    positions = []
    for v in verts:
        append_unique_position(positions, v.point().position(), eps=0.05)
    if len(positions) >= 2:
        road_data.append({'hw': hw, 'positions': positions})

# ── 1b. 未共享节点的视觉相交路口：插入交点，让后续全顶点路口识别能看见 ───────
segments = []
for ri, road in enumerate(road_data):
    ps = road['positions']
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
            ps = road['positions']
            rebuilt = []
            for si in range(len(ps) - 1):
                append_unique_position(rebuilt, ps[si], eps=0.05)
                added = sorted(insertions.get((ri, si), []), key=lambda x: x[0])
                for _t, ip in added:
                    append_unique_position(rebuilt, ip, eps=0.25)
            append_unique_position(rebuilt, ps[-1], eps=0.05)
            road['positions'] = rebuilt

# ── 1c. 统计所有道路顶点使用次数（端点 + 中间路口点）────────────────────────
pt_usage = {}
for road in road_data:
    for pos in road['positions']:
        k = jkey(pos)
        pt_usage[k] = pt_usage.get(k, 0) + 1

def is_junction(pos):
    return pt_usage.get(jkey(pos), 0) >= 2

# ── 2. 路段 quad 生成（路口处收短）+ 收集路口边缘点 ─────────────────────────
junction_pts = {}  # jkey -> list of (hou.Vector3, half_width)

def emit_chunk(hw, positions):
    n = len(positions)
    if n < 2:
        return

    # 计算各点切线
    tangs = []
    for i in range(n):
        if i == 0:      t = norm_vec(positions[1] - positions[0])
        elif i == n-1:  t = norm_vec(positions[-1] - positions[-2])
        else:           t = norm_vec(positions[i+1] - positions[i-1])
        tangs.append(t)

    # 路段总长
    seg_len = sum((positions[j+1] - positions[j]).length() for j in range(n-1))
    if seg_len < 1e-6:
        return

    start_trim = min(hw, seg_len * 0.45) if is_junction(positions[0])  else 0.0
    end_trim   = min(hw, seg_len * 0.45) if is_junction(positions[-1]) else 0.0
    if start_trim + end_trim >= seg_len - 1e-4:
        return  # 路段太短（两端都是路口），全部为路口填充区域

    # 收集路口边缘点（在收缩点处）
    if start_trim > 0:
        perp = make_perp(tangs[0])
        trim_pos = positions[0] + tangs[0] * start_trim
        lp = trim_pos + perp * hw
        rp = trim_pos - perp * hw
        jk = jkey(positions[0])
        junction_pts.setdefault(jk, []).extend([(lp, hw), (rp, hw)])

    if end_trim > 0:
        perp = make_perp(tangs[-1])
        trim_pos = positions[-1] - tangs[-1] * end_trim
        lp = trim_pos + perp * hw
        rp = trim_pos - perp * hw
        jk = jkey(positions[-1])
        junction_pts.setdefault(jk, []).extend([(lp, hw), (rp, hw)])

    # 构建 quad strip，路口端显式插入精确 trim 顶点（确保与凸包对齐）
    lefts, rights = [], []

    # ── 起点精确 trim 顶点
    if start_trim > 0:
        tp   = positions[0] + tangs[0] * start_trim
        perp = make_perp(tangs[0])
        lefts.append(tp + perp * hw)
        rights.append(tp - perp * hw)

    cumlen = 0.0
    for i, pos in enumerate(positions):
        if i > 0:
            cumlen += (positions[i] - positions[i-1]).length()

        # 跳过精确 trim 区域内的原始顶点（已由精确点替代）
        if cumlen <= start_trim + 1e-4:
            continue
        if cumlen >= seg_len - end_trim - 1e-4:
            continue

        perp = make_perp(tangs[i])
        lefts.append(pos + perp * hw)
        rights.append(pos - perp * hw)

    # ── 终点精确 trim 顶点
    if end_trim > 0:
        tp   = positions[-1] - tangs[-1] * end_trim
        perp = make_perp(tangs[-1])
        lefts.append(tp + perp * hw)
        rights.append(tp - perp * hw)

    for i in range(len(lefts) - 1):
        pts_pos = [lefts[i], lefts[i+1], rights[i+1], rights[i]]
        hpts = [geo.createPoint() for _ in pts_pos]
        for p, pp in zip(hpts, pts_pos):
            p.setPosition(pp)
        quad = geo.createPolygon()
        for p in hpts:
            quad.addVertex(p)
        quad.setAttribValue(hw_attrib, float(hw))
        quad.setAttribValue(is_junc_a, 0)

for road in road_data:
    hw = road['hw']
    positions = road['positions']
    if len(positions) < 2:
        continue

    # 用内部路口点切分 polyline，避免一条长 way 穿过多个路口却只在两端收短。
    start = 0
    for i in range(1, len(positions)):
        if is_junction(positions[i]) and i - start >= 1:
            emit_chunk(hw, positions[start:i+1])
            start = i
    if start < len(positions) - 1:
        emit_chunk(hw, positions[start:])

# ── 3. 路口填充多边形（凸包）───────────────────────────────────────────────
for jk, edge_data in junction_pts.items():
    if len(edge_data) < 3:
        continue
    edge_pts = [item[0] for item in edge_data]
    hws = [max(0.1, float(item[1])) for item in edge_data]
    max_hw = max(hws)
    ctr = centroid_xz(edge_pts)
    max_radius = max(max_hw * MAX_JUNCTION_RADIUS_FACTOR, 3.0)
    max_radius = min(max_radius, MAX_JUNCTION_RADIUS)
    # A bad jkey/intersection cluster can collect unrelated roads and create a
    # giant convex hull. Reject those fills; road segment quads still remain.
    if max((p - ctr).length() for p in edge_pts) > max_radius:
        continue
    hull = convex_hull_xz(edge_pts)
    if len(hull) < 3:
        continue
    hull_area = poly_area_xz(hull)
    max_area = min(MAX_JUNCTION_AREA, max_hw * max_hw * MAX_JUNCTION_AREA_FACTOR)
    if hull_area > max_area:
        continue
    hpts = [geo.createPoint() for _ in hull]
    for p, pp in zip(hpts, hull):
        p.setPosition(pp)
    poly = geo.createPolygon()
    for p in hpts:
        poly.addVertex(p)
    poly.setAttribValue(hw_attrib, float(max_hw))
    poly.setAttribValue(is_junc_a, 1)
