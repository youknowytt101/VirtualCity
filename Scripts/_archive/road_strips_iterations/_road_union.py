"""
road_union — 局部连通分量 2D union
====================================
替换 road_strips Python SOP。

算法:
  1. 每条道路中心线 → Shapely buffer(half_width) → 独立多边形
  2. STRtree 找实际重叠的路段对（buffer 有面积交叠）
  3. Union-Find 将重叠路段归入同一 component
  4. 每个 component: unary_union → 小局部合并多边形（无大面积洞）
  5. 孤立路段直接输出（无需合并）

结果: 路口自动合并（无 Z-fighting），城市街区保持空白，Y=0
"""
import hou
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import unary_union
from shapely import STRtree

geo_in = hou.pwd().inputs()[0].geometry()
geo    = hou.pwd().geometry()

# ── 1. buffer all roads ───────────────────────────────────────────────────
road_polys = []  # [(hw, Shapely Polygon)]
for prim in geo_in.prims():
    try:    hw = float(prim.attribValue('half_width'))
    except: hw = 2.0
    if hw < 0.1: continue
    verts = list(prim.vertices())
    if len(verts) < 2: continue
    coords = [(v.point().position()[0], v.point().position()[2]) for v in verts]
    try:
        buf = LineString(coords).buffer(hw, cap_style=2, join_style=2, mitre_limit=3.0)
        if not buf.is_empty:
            road_polys.append((hw, buf))
    except Exception:
        pass

n = len(road_polys)
polys = [p for _, p in road_polys]

# ── 2. STRtree 找重叠对 ───────────────────────────────────────────────────
tree = STRtree(polys)
# 对每个 polygon，查找与它 bbox 相交的候选
adjacency = [set() for _ in range(n)]

for i, poly in enumerate(polys):
    candidates = tree.query(poly)
    for j in candidates:
        if j <= i:
            continue
        # 真实面积交叠检查（非仅 bbox）
        try:
            inter = poly.intersection(polys[j])
            if inter.area > 0.01:   # 0.01 m² 以上才算真正重叠
                adjacency[i].add(j)
                adjacency[j].add(i)
        except Exception:
            pass

# ── 3. Union-Find ─────────────────────────────────────────────────────────
parent = list(range(n))

def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x

def union(a, b):
    a, b = find(a), find(b)
    if a != b:
        parent[b] = a

for i in range(n):
    for j in adjacency[i]:
        union(i, j)

# 按 root 分组
components = {}
for i in range(n):
    root = find(i)
    components.setdefault(root, []).append(i)

# ── 4. 逐 component 合并并写入 Houdini ────────────────────────────────────
def write_shapely_poly(geo, shapely_poly):
    """只写 exterior ring（小 component 基本无洞）"""
    coords = list(shapely_poly.exterior.coords)
    if coords[0] == coords[-1]:
        coords = coords[:-1]
    if len(coords) < 3:
        return
    hpts = []
    for x, z in coords:
        p = geo.createPoint()
        p.setPosition(hou.Vector3(x, 0.0, z))
        hpts.append(p)
    poly = geo.createPolygon()
    for p in hpts:
        poly.addVertex(p)
    # 处理 interior rings（局部 component 偶有小洞时也写出）
    for interior in shapely_poly.interiors:
        ic = list(interior.coords)
        if ic[0] == ic[-1]:
            ic = ic[:-1]
        if len(ic) < 3:
            continue
        ihpts = []
        for x, z in ic:
            p = geo.createPoint()
            p.setPosition(hou.Vector3(x, 0.0, z))
            ihpts.append(p)
        # 内环用反转顶点顺序写，后续若需 Boolean 可用 is_hole attrib 区分
        ipoly = geo.createPolygon()
        for p in reversed(ihpts):
            ipoly.addVertex(p)

merged_count = 0
solo_count   = 0

for root, indices in components.items():
    if len(indices) == 1:
        # 孤立路段
        write_shapely_poly(geo, polys[indices[0]])
        solo_count += 1
    else:
        # 局部合并
        group_polys = [polys[i] for i in indices]
        try:
            merged = unary_union(group_polys)
        except Exception:
            for p in group_polys:
                write_shapely_poly(geo, p)
            continue
        if isinstance(merged, Polygon):
            write_shapely_poly(geo, merged)
        elif isinstance(merged, MultiPolygon):
            for part in merged.geoms:
                write_shapely_poly(geo, part)
        merged_count += 1

import sys
print('[road_union] components=%d merged=%d solo=%d prims_out=%d' % (
    len(components), merged_count, solo_count, geo.primCount()), file=sys.stderr)
