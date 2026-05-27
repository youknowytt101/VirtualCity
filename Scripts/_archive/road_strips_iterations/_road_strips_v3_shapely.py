"""
road_strips v3 — Shapely buffer + unary_union
=============================================
对每条道路中心线做 Shapely LineString.buffer(half_width)，
再用 unary_union 自动合并所有重叠区域，彻底消除路口 Z-fighting 和悬空边缘。

输入 0: road_width_flat（resample + half_width attrib，Y=0）
输出:  统一路面多边形，无重叠，无路口空洞
"""
import hou
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import unary_union

geo_in = hou.pwd().inputs()[0].geometry()
geo    = hou.pwd().geometry()

# ── 1. 每条路 -> Shapely buffer polygon ────────────────────────────────────
road_polys = []
for prim in geo_in.prims():
    try:    hw = float(prim.attribValue('half_width'))
    except: hw = 2.0
    if hw < 0.1:
        continue
    verts = list(prim.vertices())
    if len(verts) < 2:
        continue
    coords = [(v.point().position()[0], v.point().position()[2]) for v in verts]
    line = LineString(coords)
    # cap_style=2 (flat), join_style=2 (mitre) 给路口最干净的直角
    buf = line.buffer(hw, cap_style=2, join_style=2, mitre_limit=4.0)
    if not buf.is_empty:
        road_polys.append(buf)

if not road_polys:
    import sys; print('road_strips v3: no road polygons generated', file=sys.stderr)

# ── 2. unary_union: 合并所有重叠区域 ───────────────────────────────────────
merged = unary_union(road_polys)

# ── 3. 将 Shapely polygon(s) 转为 Houdini geometry（Y=0）─────────────────
def add_shapely_poly(geo, shapely_poly):
    """将单个 Shapely Polygon（无孔）写入 Houdini geo。"""
    coords = list(shapely_poly.exterior.coords)
    if len(coords) < 3:
        return
    # 去掉首尾重复点
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

if isinstance(merged, Polygon):
    add_shapely_poly(geo, merged)
elif isinstance(merged, MultiPolygon):
    for part in merged.geoms:
        add_shapely_poly(geo, part)
else:
    # GeometryCollection fallback
    for geom in getattr(merged, 'geoms', []):
        if isinstance(geom, Polygon):
            add_shapely_poly(geo, geom)
