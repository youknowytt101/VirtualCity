"""
road_strips v7 — quad strip + 圆角路口融合
===========================================
路口填充原理：
  - 以路口中心为圆心，radius = max(hw) 画圆
  - 每条路端向外延伸 hw 距离的矩形
  - unary_union(圆 + 各矩形) → 自然圆角路口多边形
  - 与路段 quad 的截止边完全吻合（共边，无缝无穿插）

只对 N >= 3 条路汇聚的真实路口做填充；2 路连接不截短也不填充。
"""
import hou, math
from shapely.geometry import Point, Polygon as SPolygon, MultiPolygon
from shapely.ops import unary_union

geo_in = hou.pwd().inputs()[0].geometry()
geo    = hou.pwd().geometry()
UP     = hou.Vector3(0, 1, 0)
RTOL   = 1.0   # 路口哈希精度 (m)
MIN_ROADS = 3  # 至少 3 条路才算路口

# ── 辅助 ─────────────────────────────────────────────────────────────────
def norm_v(v):
    l = v.length(); return v / l if l > 1e-6 else hou.Vector3(1, 0, 0)

def make_perp(t):
    p = UP.cross(t); l = p.length(); return p / l if l > 1e-6 else hou.Vector3(1, 0, 0)

def jkey(pos):
    return (round(pos[0] / RTOL) * RTOL, round(pos[2] / RTOL) * RTOL)

# ── 1. 读路，统计路口 ─────────────────────────────────────────────────────
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

def is_junc(pos): return pt_usage.get(jkey(pos), 0) >= MIN_ROADS

# junc_info[jkey] = {'center': (cx,cz), 'roads': [(tang_x,tang_z,hw), ...]}
junc_info = {}

# ── 2. 生成路段 quad strip + 收集路口数据 ─────────────────────────────────
for hw, positions in road_data:
    n = len(positions)
    if n < 2: continue

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

    # 收集路口信息
    for is_start, pos, tang in [(True, positions[0], tangs[0]),
                                (False, positions[-1], norm_v(positions[-1]-positions[-2]))]:
        if (is_start and st) or (not is_start and en):
            k = jkey(pos)
            if k not in junc_info:
                junc_info[k] = {'center': (pos[0], pos[2]), 'roads': []}
            junc_info[k]['roads'].append((tang[0], tang[2], hw))

    # 生成 quad strip（插入精确 gate 点，跳过路口区内点）
    lefts, rights = [], []

    if st:
        gate_pos = positions[0] + tangs[0] * hw
        perp = make_perp(tangs[0])
        lefts.append(hou.Vector3(gate_pos[0]+perp[0]*hw, 0, gate_pos[2]+perp[2]*hw))
        rights.append(hou.Vector3(gate_pos[0]-perp[0]*hw, 0, gate_pos[2]-perp[2]*hw))

    cumlen = 0.0
    for i, pos in enumerate(positions):
        if i > 0: cumlen += (positions[i]-positions[i-1]).length()
        if cumlen <= start_trim + 1e-4: continue
        if cumlen >= seg_len - end_trim - 1e-4: continue
        perp = make_perp(tangs[i])
        lefts.append(hou.Vector3(pos[0]+perp[0]*hw, 0, pos[2]+perp[2]*hw))
        rights.append(hou.Vector3(pos[0]-perp[0]*hw, 0, pos[2]-perp[2]*hw))

    if en:
        tang_away = norm_v(positions[-1]-positions[-2])
        gate_pos = positions[-1] + tang_away * hw
        perp = make_perp(tang_away)
        lefts.append(hou.Vector3(gate_pos[0]+perp[0]*hw, 0, gate_pos[2]+perp[2]*hw))
        rights.append(hou.Vector3(gate_pos[0]-perp[0]*hw, 0, gate_pos[2]-perp[2]*hw))

    if len(lefts) < 2: continue
    for i in range(len(lefts)-1):
        pts_pos = [lefts[i], lefts[i+1], rights[i+1], rights[i]]
        hpts = [geo.createPoint() for _ in pts_pos]
        for p, pp in zip(hpts, pts_pos): p.setPosition(pp)
        quad = geo.createPolygon()
        for p in hpts: quad.addVertex(p)

# ── 3. 路口圆角填充 ───────────────────────────────────────────────────────
def write_shapely_exterior(geo, sp):
    coords = list(sp.exterior.coords)
    if coords[0] == coords[-1]: coords = coords[:-1]
    if len(coords) < 3: return
    hpts = []
    for x, z in coords:
        p = geo.createPoint()
        p.setPosition(hou.Vector3(x, 0.0, z))
        hpts.append(p)
    poly = geo.createPolygon()
    for p in hpts: poly.addVertex(p)

junc_count = 0
for k, info in junc_info.items():
    roads = info['roads']
    if len(roads) < MIN_ROADS: continue

    cx, cz = info['center']
    # 圆的半径 = 所有汇入路中最大 hw（确保覆盖最宽的路）
    r = max(hw for _, _, hw in roads)

    parts = []
    # 圆心圆（生成圆角）
    parts.append(Point(cx, cz).buffer(r, resolution=16))

    # 每条路端延伸矩形（从路口中心到 gate 线）
    for tx, tz, hw in roads:
        px, pz = -tz, tx   # 2D 垂直向量（CCW 90°）
        # 矩形 4 角
        p1 = (cx - px*hw,      cz - pz*hw)       # 起点右侧
        p2 = (cx+tx*hw - px*hw, cz+tz*hw - pz*hw) # 终点右侧
        p3 = (cx+tx*hw + px*hw, cz+tz*hw + pz*hw) # 终点左侧
        p4 = (cx + px*hw,      cz + pz*hw)       # 起点左侧
        parts.append(SPolygon([p1, p2, p3, p4]))

    try:
        merged = unary_union(parts)
    except Exception:
        continue

    if isinstance(merged, SPolygon):
        write_shapely_exterior(geo, merged)
    elif isinstance(merged, MultiPolygon):
        for part in merged.geoms:
            write_shapely_exterior(geo, part)

    junc_count += 1

import sys
quads = sum(1 for p in geo.prims() if len(list(p.vertices())) == 4)
fills = sum(1 for p in geo.prims() if len(list(p.vertices())) > 4)
print('[road_strips_v7] roads=%d junctions=%d quads=%d fills=%d' % (
    len(road_data), junc_count, quads, fills), file=sys.stderr)
