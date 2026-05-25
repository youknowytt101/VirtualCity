"""
road_strips v3c — Shapely union + Delaunay triangulation（正确保留城市街区空洞）
===============================================================================
输入 0: road_width_flat (resample + half_width, Y=0)
输出:  三角网格化路面，路口自动合并，城市街区空洞完整保留，Y=0
"""
import hou
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import unary_union, triangulate
from shapely import prepare

geo_in = hou.pwd().inputs()[0].geometry()
geo    = hou.pwd().geometry()

# ── 1. buffer all roads ───────────────────────────────────────────────────
road_polys = []
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
            road_polys.append(buf)
    except Exception:
        pass

# ── 2. unary_union ────────────────────────────────────────────────────────
merged = unary_union(road_polys)

# ── 3. 简化顶点（0.5m 精度），大幅降低三角化成本 ──────────────────────────
merged = merged.simplify(0.5, preserve_topology=True)

# ── 4. Delaunay triangulate + containment filter ─────────────────────────
prepare(merged)   # 加速后续 contains 查询
tris = triangulate(merged)

# ── 4. 输出仅在 merged 内部的三角形（排除城市街区空洞内的三角形）────────
added = 0
for tri in tris:
    if not merged.contains(tri.centroid):
        continue
    coords = list(tri.exterior.coords)[:-1]
    if len(coords) < 3:
        continue
    hpts = []
    for x, z in coords:
        p = geo.createPoint()
        p.setPosition(hou.Vector3(x, 0.0, z))
        hpts.append(p)
    poly = geo.createPolygon()
    for p in hpts:
        poly.addVertex(p)
    added += 1

import sys
print('[road_strips_v3c] triangles=%d' % added, file=sys.stderr)
