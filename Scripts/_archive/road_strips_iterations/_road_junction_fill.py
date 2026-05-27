"""
road_junction_fill — 路口局部 Shapely union 填充
=================================================
输入 0: road_width_flat (resample + half_width attrib, Y=0)
输出:  仅路口填充多边形（Y=+0.05m，压住 road_strips 路口处的穿插边缘）

算法:
  1. 统计每个端点被几条路共享（路口检测）
  2. 对每个路口节点，取各汇入路的端部短段（2×hw 长度）做 buffer
  3. unary_union 仅这 2-4 个局部 buffer → 干净的路口多边形
  4. 转换为 Houdini polygon，Y=0.05m（比 road_strips 高，消除 Z-fighting）
"""
import hou, math
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import unary_union

geo_in = hou.pwd().inputs()[0].geometry()
geo    = hou.pwd().geometry()

JUNC_DETECT_TOL = 1.0   # 路口检测空间哈希精度 (m)
JUNC_Y_OFFSET   = 0.05  # 高于 road_strips 的偏移量 (m)
LOCAL_SEG_MULT  = 2.0   # 取路口端部多少倍 hw 长度作为局部 buffer 范围

# ── 1. 读取道路数据，统计端点使用次数 ────────────────────────────────────────
def jkey(pos, tol=JUNC_DETECT_TOL):
    return (round(pos[0] / tol) * tol, round(pos[2] / tol) * tol)

pt_usage   = {}   # jkey -> count
road_data  = []   # [(hw, positions_list)]

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

# ── 2. 对每个路口节点收集汇入路的端部 buffer ─────────────────────────────────
# junction_local_buffers: jkey -> [Shapely Polygon, ...]
junction_buffers = {}

for hw, positions in road_data:
    n = len(positions)
    if n < 2: continue

    seg_len = sum((positions[i+1]-positions[i]).length() for i in range(n-1))
    local_len = max(hw * LOCAL_SEG_MULT, 0.5)   # 最少 0.5m

    for end in ['start', 'end']:
        if end == 'start':
            pos = positions[0]
        else:
            pos = positions[-1]

        k = jkey(pos)
        if pt_usage.get(k, 0) < 2:
            continue   # 不是路口，跳过

        # 截取端部折线片段（累积距离 <= local_len）
        if end == 'start':
            seg_pts = [positions[0]]
            cum = 0.0
            for i in range(n-1):
                d = (positions[i+1]-positions[i]).length()
                cum += d
                seg_pts.append(positions[i+1])
                if cum >= local_len:
                    break
        else:
            seg_pts = [positions[-1]]
            cum = 0.0
            for i in range(n-1, 0, -1):
                d = (positions[i]-positions[i-1]).length()
                cum += d
                seg_pts.append(positions[i-1])
                if cum >= local_len:
                    break
            seg_pts.reverse()

        if len(seg_pts) < 2:
            seg_pts = [positions[0], positions[1]] if end == 'start' else [positions[-2], positions[-1]]

        coords = [(p[0], p[2]) for p in seg_pts]
        try:
            line = LineString(coords)
            buf  = line.buffer(hw, cap_style=2, join_style=2, mitre_limit=3.0)
            if not buf.is_empty:
                junction_buffers.setdefault(k, []).append(buf)
        except Exception:
            pass

# ── 3. 对每个路口做局部 unary_union，输出填充多边形 ───────────────────────────
def write_shapely_poly(geo, shapely_poly, y_offset):
    coords = list(shapely_poly.exterior.coords)
    if coords[0] == coords[-1]:
        coords = coords[:-1]
    if len(coords) < 3:
        return
    hpts = []
    for x, z in coords:
        p = geo.createPoint()
        p.setPosition(hou.Vector3(x, y_offset, z))
        hpts.append(p)
    poly = geo.createPolygon()
    for p in hpts:
        poly.addVertex(p)

filled = 0
for k, bufs in junction_buffers.items():
    if len(bufs) < 2:
        continue   # 只有 1 条路的端点，不需要填充
    try:
        merged = unary_union(bufs)
    except Exception:
        continue

    if isinstance(merged, Polygon):
        write_shapely_poly(geo, merged, JUNC_Y_OFFSET)
        filled += 1
    elif isinstance(merged, MultiPolygon):
        for part in merged.geoms:
            write_shapely_poly(geo, part, JUNC_Y_OFFSET)
        filled += 1

import sys
print('[road_junction_fill] junctions=%d  fill_prims=%d' % (filled, geo.primCount()), file=sys.stderr)
