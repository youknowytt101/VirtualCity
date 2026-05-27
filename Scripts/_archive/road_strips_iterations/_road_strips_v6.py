"""
road_strips v6 — 路段 quad strip + 路口中心点扇形三角填充
============================================================
完全匹配用户 3.fbx 的拓扑结构：
  - 路段 quad strip：端头精确截止在路口边缘（distance = hw）
  - 路口填充：以路口中心点为顶点的三角扇（fan triangulation）

输入 0: road_width_flat (resample + half_width, Y=0)
"""
import hou, math

geo_in = hou.pwd().inputs()[0].geometry()
geo    = hou.pwd().geometry()
UP     = hou.Vector3(0, 1, 0)
RTOL   = 1.0   # 路口哈希精度 (m)

# ── 辅助 ─────────────────────────────────────────────────────────────────
def norm_v(v):
    l = v.length(); return v / l if l > 1e-6 else hou.Vector3(1, 0, 0)

def make_perp(t):
    p = UP.cross(t); l = p.length(); return p / l if l > 1e-6 else hou.Vector3(1, 0, 0)

def jkey(pos):
    return (round(pos[0] / RTOL) * RTOL, round(pos[2] / RTOL) * RTOL)

def v3(x, y, z): return hou.Vector3(x, y, z)

# ── 1. 读路数据，统计路口（共享端点）────────────────────────────────────────
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

def is_junc(pos): return pt_usage.get(jkey(pos), 0) >= 2

# ── 2. 生成路段 quad strip（路口端精确截短 + 插入 gate 顶点）─────────────────
# junc_gates[jkey] = [(angle, gate_L, gate_R), ...]
# junc_center[jkey] = hou.Vector3 (路口中心坐标)
junc_gates  = {}
junc_center = {}

for hw, positions in road_data:
    n = len(positions)
    if n < 2: continue

    # 切线
    tangs = []
    for i in range(n):
        if i == 0:     t = norm_v(positions[1] - positions[0])
        elif i == n-1: t = norm_v(positions[-1] - positions[-2])
        else:          t = norm_v(positions[i+1] - positions[i-1])
        tangs.append(t)

    seg_len = sum((positions[i+1]-positions[i]).length() for i in range(n-1))
    if seg_len < 1e-6: continue

    st = is_junc(positions[0])
    en = is_junc(positions[-1])
    start_trim = hw if st else 0.0
    end_trim   = hw if en else 0.0

    # ── 收集 gate 点（路口端精确位置）────────────────────────────────────
    if st:
        tang_away = tangs[0]
        gate_pos  = positions[0] + tang_away * hw
        perp      = make_perp(tang_away)
        gL = v3(gate_pos[0]+perp[0]*hw, 0, gate_pos[2]+perp[2]*hw)
        gR = v3(gate_pos[0]-perp[0]*hw, 0, gate_pos[2]-perp[2]*hw)
        angle = math.atan2(tang_away[2], tang_away[0])
        k = jkey(positions[0])
        junc_gates.setdefault(k, []).append((angle, gL, gR))
        if k not in junc_center:
            junc_center[k] = v3(positions[0][0], 0, positions[0][2])

    if en:
        tang_away = norm_v(positions[-1] - positions[-2])  # outward from junction
        gate_pos  = positions[-1] + tang_away * hw
        perp      = make_perp(tang_away)
        gL = v3(gate_pos[0]+perp[0]*hw, 0, gate_pos[2]+perp[2]*hw)
        gR = v3(gate_pos[0]-perp[0]*hw, 0, gate_pos[2]-perp[2]*hw)
        angle = math.atan2(tang_away[2], tang_away[0])
        k = jkey(positions[-1])
        junc_gates.setdefault(k, []).append((angle, gL, gR))
        if k not in junc_center:
            junc_center[k] = v3(positions[-1][0], 0, positions[-1][2])

    # ── 生成 quad strip（插入 gate 顶点，跳过路口区内的 resample 点）────────
    lefts  = []
    rights = []

    # 起始 gate（如果是路口）
    if st:
        tang_away = tangs[0]
        gate_pos  = positions[0] + tang_away * hw
        perp      = make_perp(tang_away)
        lefts.append(v3(gate_pos[0]+perp[0]*hw, 0, gate_pos[2]+perp[2]*hw))
        rights.append(v3(gate_pos[0]-perp[0]*hw, 0, gate_pos[2]-perp[2]*hw))

    # 路段中间顶点（跳过路口区）
    cumlen = 0.0
    for i, pos in enumerate(positions):
        if i > 0: cumlen += (positions[i]-positions[i-1]).length()
        if cumlen <= start_trim + 1e-4: continue
        if cumlen >= seg_len - end_trim - 1e-4: continue
        perp = make_perp(tangs[i])
        lefts.append(v3(pos[0]+perp[0]*hw, 0, pos[2]+perp[2]*hw))
        rights.append(v3(pos[0]-perp[0]*hw, 0, pos[2]-perp[2]*hw))

    # 末端 gate（如果是路口）
    if en:
        tang_away = norm_v(positions[-1] - positions[-2])
        gate_pos  = positions[-1] + tang_away * hw
        perp      = make_perp(tang_away)
        lefts.append(v3(gate_pos[0]+perp[0]*hw, 0, gate_pos[2]+perp[2]*hw))
        rights.append(v3(gate_pos[0]-perp[0]*hw, 0, gate_pos[2]-perp[2]*hw))

    if len(lefts) < 2: continue

    for i in range(len(lefts)-1):
        pts_pos = [lefts[i], lefts[i+1], rights[i+1], rights[i]]
        hpts = [geo.createPoint() for _ in pts_pos]
        for p, pp in zip(hpts, pts_pos): p.setPosition(pp)
        quad = geo.createPolygon()
        for p in hpts: quad.addVertex(p)

# ── 3. 路口扇形三角填充（所有角点 → 中心点）──────────────────────────────
# junc_gates[k] = [(angle, gL, gR), ...]
# 正确做法：将 TL 和 TR 分别按角度插入，排序后做全扇形三角剖分
import math as _math

junc_count = 0
tri_count  = 0

for k, gates in junc_gates.items():
    if len(gates) < 2: continue
    center_pos = junc_center[k]

    # 把每条路的 TL 和 TR 分别加入角度列表
    all_pts = []   # [(angle_from_center, hou.Vector3), ...]
    for _, gL, gR in gates:
        cx, cz = center_pos[0], center_pos[2]
        aL = _math.atan2(gL[2]-cz, gL[0]-cx)
        aR = _math.atan2(gR[2]-cz, gR[0]-cx)
        all_pts.append((aL, gL))
        all_pts.append((aR, gR))

    # 按角度排序
    all_pts.sort(key=lambda x: x[0])

    # 去除角度/位置重复点（容差 0.05m）
    unique = []
    for ang, pt in all_pts:
        if unique and (pt - unique[-1][1]).length() < 0.05:
            continue
        unique.append((ang, pt))
    # 检查首尾
    if len(unique) > 1 and (unique[0][1] - unique[-1][1]).length() < 0.05:
        unique = unique[:-1]

    if len(unique) < 3: continue

    # 路口中心点
    cp = geo.createPoint()
    cp.setPosition(center_pos)

    # 扇形三角：相邻角点两两与中心点成三角形
    N = len(unique)
    for i in range(N):
        p1 = unique[i][1]
        p2 = unique[(i+1) % N][1]
        dist = (p1 - p2).length()
        if dist < 0.05: continue  # 退化

        pt1 = geo.createPoint(); pt1.setPosition(v3(p1[0], 0, p1[2]))
        pt2 = geo.createPoint(); pt2.setPosition(v3(p2[0], 0, p2[2]))
        tri = geo.createPolygon()
        tri.addVertex(pt1)
        tri.addVertex(cp)
        tri.addVertex(pt2)
        tri_count += 1

    junc_count += 1

import sys
roads = len(road_data)
quads = sum(1 for p in geo.prims() if len(list(p.vertices())) == 4)
tris  = sum(1 for p in geo.prims() if len(list(p.vertices())) == 3)
print('[road_strips_v6] roads=%d junctions=%d quads=%d tris=%d' % (roads, junc_count, quads, tris), file=sys.stderr)
