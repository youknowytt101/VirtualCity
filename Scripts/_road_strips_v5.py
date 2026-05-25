"""
road_strips v5 — quad strips + 路口凸包填充（Y+0.01m 覆盖层）
==============================================================
输入 0: road_width_flat (resample + half_width, Y=0)
输出:
  - 完整路段 quad strips（不截短，v1 原始逻辑）
  - 路口凸包多边形（Y=+0.01m，精确贴合路面边缘，无曲线穿插）

凸包顶点 = 各汇入路在 hw 处的左/右 trim 点（精确坐标），
保证凸包边缘与路段 quad 边缘重合，消除 Z-fighting 同时不产生穿插线。
"""
import hou, math

geo_in = hou.pwd().inputs()[0].geometry()
geo    = hou.pwd().geometry()
UP     = hou.Vector3(0, 1, 0)
RTOL   = 1.0        # 路口检测哈希精度 (m)
JUNC_Y = 0.01       # 路口多边形高于路面的偏移 (m)
MIN_JUNC_ROADS = 2  # 至少几条路汇聚才生成路口填充

# ── 辅助函数 ────────────────────────────────────────────────────────────────
def norm_v(v):
    l = v.length(); return v / l if l > 1e-6 else hou.Vector3(1, 0, 0)

def make_perp(t):
    p = UP.cross(t); l = p.length(); return p / l if l > 1e-6 else hou.Vector3(1, 0, 0)

def jkey(pos):
    return (round(pos[0] / RTOL) * RTOL, round(pos[2] / RTOL) * RTOL)

def convex_hull_xz(pts_3d):
    """Gift-wrap convex hull in XZ plane，返回 hou.Vector3 列表（有序）。"""
    seen = {}
    for p in pts_3d:
        k = (round(p[0], 3), round(p[2], 3))
        seen[k] = p
    pts = list(seen.values())
    n = len(pts)
    if n < 3:
        return pts
    start = min(range(n), key=lambda i: (pts[i][0], pts[i][2]))
    hull = []
    cur = start
    while True:
        hull.append(pts[cur])
        nxt = (cur + 1) % n
        for i in range(n):
            ax = pts[nxt][0] - pts[cur][0]; az = pts[nxt][2] - pts[cur][2]
            bx = pts[i][0]  - pts[cur][0]; bz = pts[i][2]  - pts[cur][2]
            if ax * bz - az * bx < 0:
                nxt = i
        cur = nxt
        if cur == start or len(hull) > n + 2:
            break
    return hull

# ── 1. 读路数据，统计端点共享次数 ────────────────────────────────────────────
pt_usage  = {}
road_data = []

for prim in geo_in.prims():
    try:    hw = float(prim.attribValue('half_width'))
    except: hw = 2.0
    verts = list(prim.vertices())
    if len(verts) < 2: continue
    positions = [v.point().position() for v in verts]
    road_data.append((hw, positions))
    for pos in [positions[0], positions[-1]]:
        k = jkey(pos)
        pt_usage[k] = pt_usage.get(k, 0) + 1

def is_junc(pos): return pt_usage.get(jkey(pos), 0) >= MIN_JUNC_ROADS

# ── 2. 生成路段 quad strips（v1 原始逻辑，不截短）────────────────────────────
for hw, positions in road_data:
    n = len(positions)
    if n < 2: continue
    tangs = []
    for i in range(n):
        if i == 0:     t = norm_v(positions[1] - positions[0])
        elif i == n-1: t = norm_v(positions[-1] - positions[-2])
        else:          t = norm_v(positions[i+1] - positions[i-1])
        tangs.append(t)
    lefts, rights = [], []
    for i, pos in enumerate(positions):
        perp = make_perp(tangs[i])
        lefts.append(pos + perp * hw)
        rights.append(pos - perp * hw)
    for i in range(len(lefts) - 1):
        pts_pos = [lefts[i], lefts[i+1], rights[i+1], rights[i]]
        hpts = [geo.createPoint() for _ in pts_pos]
        for p, pp in zip(hpts, pts_pos): p.setPosition(pp)
        quad = geo.createPolygon()
        for p in hpts: quad.addVertex(p)

# ── 3. 收集各路口 trim 点 ────────────────────────────────────────────────────
junc_pts = {}   # jkey -> [hou.Vector3, ...]

for hw, positions in road_data:
    n = len(positions)
    if n < 2: continue
    tangs = []
    for i in range(n):
        if i == 0:     t = norm_v(positions[1] - positions[0])
        elif i == n-1: t = norm_v(positions[-1] - positions[-2])
        else:          t = norm_v(positions[i+1] - positions[i-1])
        tangs.append(t)

    for end, pos, tang_away in [
        ('start', positions[0],  tangs[0]),
        ('end',   positions[-1], -tangs[-1])
    ]:
        if not is_junc(pos): continue
        trim_pos = pos + tang_away * hw
        perp     = make_perp(tang_away)
        lp = hou.Vector3(trim_pos[0] + perp[0]*hw, 0, trim_pos[2] + perp[2]*hw)
        rp = hou.Vector3(trim_pos[0] - perp[0]*hw, 0, trim_pos[2] - perp[2]*hw)
        k  = jkey(pos)
        junc_pts.setdefault(k, []).extend([lp, rp])

# ── 4. 生成路口凸包多边形（Y = JUNC_Y，覆盖 quad 交叉边缘）────────────────────
junc_count = 0
for k, pts in junc_pts.items():
    hull = convex_hull_xz(pts)
    if len(hull) < 3: continue
    hpts = []
    for hp in hull:
        p = geo.createPoint()
        p.setPosition(hou.Vector3(hp[0], JUNC_Y, hp[2]))
        hpts.append(p)
    poly = geo.createPolygon()
    for p in hpts: poly.addVertex(p)
    junc_count += 1

import sys
print('[road_strips_v5] roads=%d junctions=%d total_prims=%d' % (
    len(road_data), junc_count, geo.primCount()), file=sys.stderr)
