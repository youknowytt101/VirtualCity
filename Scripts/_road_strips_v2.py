"""
road_strips v2 — 路段修剪 + 路口凸包填充
==========================================
替换原 road_strips Python SOP。
输入 0: road_width_flat（resample + half_width attrib，Y=0）
输出:  路面 quad + 路口填充多边形，无 Z-fighting，无路口空洞。
"""
import hou, math

geo_in  = hou.pwd().inputs()[0].geometry()
geo     = hou.pwd().geometry()
UP      = hou.Vector3(0, 1, 0)
ROUND   = 1.0   # 路口检测空间哈希精度 (m)

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

# ── 1. 读取所有道路，统计端点使用次数 ────────────────────────────────────────
pt_usage  = {}   # jkey -> usage count
road_data = []   # [(hw, positions)]

for prim in geo_in.prims():
    try:    hw = prim.attribValue('half_width')
    except: hw = 2.0
    verts = list(prim.vertices())
    if len(verts) < 2:
        continue
    positions = [v.point().position() for v in verts]
    road_data.append((hw, positions))
    for pos in [positions[0], positions[-1]]:
        k = jkey(pos)
        pt_usage[k] = pt_usage.get(k, 0) + 1

def is_junction(pos):
    return pt_usage.get(jkey(pos), 0) >= 2

# ── 2. 路段 quad 生成（路口处收短）+ 收集路口边缘点 ─────────────────────────
junction_pts = {}  # jkey -> list of hou.Vector3

for hw, positions in road_data:
    n = len(positions)
    if n < 2:
        continue

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
        continue

    start_trim = hw if is_junction(positions[0])  else 0.0
    end_trim   = hw if is_junction(positions[-1]) else 0.0
    if start_trim + end_trim >= seg_len - 1e-4:
        continue  # 路段太短（两端都是路口），全部为路口填充区域

    # 收集路口边缘点（在收缩点处）
    if start_trim > 0:
        perp = make_perp(tangs[0])
        trim_pos = positions[0] + tangs[0] * start_trim
        lp = trim_pos + perp * hw
        rp = trim_pos - perp * hw
        jk = jkey(positions[0])
        junction_pts.setdefault(jk, []).extend([lp, rp])

    if end_trim > 0:
        perp = make_perp(tangs[-1])
        trim_pos = positions[-1] - tangs[-1] * end_trim
        lp = trim_pos + perp * hw
        rp = trim_pos - perp * hw
        jk = jkey(positions[-1])
        junction_pts.setdefault(jk, []).extend([lp, rp])

    # 构建 quad strip，路口端显式插入精确 trim 顶点（确保与凸包对齐，无缝隙）
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

# ── 3. 路口填充多边形（凸包）───────────────────────────────────────────────
for jk, edge_pts in junction_pts.items():
    if len(edge_pts) < 3:
        continue
    hull = convex_hull_xz(edge_pts)
    if len(hull) < 3:
        continue
    hpts = [geo.createPoint() for _ in hull]
    for p, pp in zip(hpts, hull):
        p.setPosition(pp)
    poly = geo.createPolygon()
    for p in hpts:
        poly.addVertex(p)
    avg_hw = sum(p[0] for p in edge_pts) / len(edge_pts)  # dummy, use max
    poly.setAttribValue(hw_attrib, 0.0)
    poly.setAttribValue(is_junc_a, 1)
