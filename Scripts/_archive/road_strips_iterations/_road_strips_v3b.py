"""
road_strips v3b — Shapely union + exterior/interior ring 分离
=============================================================
输入 0: road_width_flat (resample + half_width attrib, Y=0)
输出:
  - ring_type=0: exterior ring polygon（外边界，路面区域）
  - ring_type=1: interior ring polygon（内环 = 城市街区，用于后续 Boolean 减法）
后续需用 Boolean SOP: exterior_group - interior_group = 正确路面（有洞）
"""
import hou
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import unary_union

geo_in = hou.pwd().inputs()[0].geometry()
geo    = hou.pwd().geometry()

ring_type_a = geo.addAttrib(hou.attribType.Prim, 'ring_type', 0)

# ── 1. buffer all roads ────────────────────────────────────────────────────
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

# ── 3. exterior + interior rings → Houdini polygons ─────────────────────
def write_ring(geo, ring_coords, y, ring_type_a, rt):
    coords = list(ring_coords)
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    if len(coords) < 3:
        return
    hpts = []
    for x, z in coords:
        p = geo.createPoint()
        p.setPosition(hou.Vector3(x, y, z))
        hpts.append(p)
    poly = geo.createPolygon()
    for p in hpts:
        poly.addVertex(p)
    poly.setAttribValue(ring_type_a, rt)

def process_poly(geo, shapely_poly, ring_type_a):
    # exterior ring: ring_type=0
    write_ring(geo, shapely_poly.exterior.coords, 0.0, ring_type_a, 0)
    # interior rings: ring_type=1 (city blocks = holes)
    for interior in shapely_poly.interiors:
        write_ring(geo, interior.coords, 0.0, ring_type_a, 1)

if isinstance(merged, Polygon):
    process_poly(geo, merged, ring_type_a)
elif isinstance(merged, MultiPolygon):
    for part in merged.geoms:
        process_poly(geo, part, ring_type_a)
else:
    for geom in getattr(merged, 'geoms', []):
        if isinstance(geom, Polygon):
            process_poly(geo, geom, ring_type_a)

import sys
ext_count = sum(1 for p in geo.prims() if p.attribValue('ring_type') == 0)
int_count = sum(1 for p in geo.prims() if p.attribValue('ring_type') == 1)
print('[road_strips_v3b] exterior=%d interior=%d' % (ext_count, int_count), file=sys.stderr)
