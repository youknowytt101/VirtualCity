"""
Road pipeline snippets for the Houdini recook script.

Keep this module pure-Python/string-only.  _recook_new_area.py owns the Houdini
connection and node graph; this module only centralizes road-specific code so
road iteration does not keep growing the main recook script.
"""
from __future__ import annotations

from pathlib import Path


ROAD_SNAP_VEX = """
// 点级别：按 XZ 垂直投射到地形，而不是用 3D 最近点。
// 山地/丘陵上 3D 最近点会吸到旁边低坡，导致道路埋入地形。
vector hitp;
vector uvw;
int hit_prim = intersect(1, set(@P.x, 10000.0, @P.z), set(0.0, -20000.0, 0.0), hitp, uvw);
if (hit_prim >= 0) {
    @P.y = hitp.y;
} else {
    int near_prim;
    vector near_uvw;
    xyzdist(1, set(@P.x, @P.y, @P.z), near_prim, near_uvw);
    vector terrain_pos = primuv(1, "P", near_prim, near_uvw);
    @P.y = terrain_pos.y;
}
"""


ROAD_WIDTH_VEX = """
// 道路宽度优先级：OSM 实测宽度 > lanes 推算 > 分类表 fallback。
// 最终再按 highway 类型做区域级 clamp，防止异常 width/lanes 标签放大成坏面片。
float osm_w = f@osm_width;
int   lanes = i@lanes;
string hw = s@highway;

if (osm_w > 0) {
    f@half_width = osm_w * 0.5;
} else if (lanes > 0) {
    f@half_width = lanes * 1.75;
} else {
    float hw_val;
    if      (hw == "motorway")                                    hw_val = 5.0;
    else if (hw == "motorway_link")                               hw_val = 3.5;
    else if (hw == "trunk")                                       hw_val = 4.5;
    else if (hw == "trunk_link")                                  hw_val = 3.0;
    else if (hw == "primary")                                     hw_val = 4.0;
    else if (hw == "primary_link")                                hw_val = 2.5;
    else if (hw == "secondary")                                   hw_val = 3.5;
    else if (hw == "secondary_link")                              hw_val = 2.0;
    else if (hw == "tertiary")                                    hw_val = 2.5;
    else if (hw == "tertiary_link")                               hw_val = 1.5;
    else if (hw == "residential" || hw == "living_street")        hw_val = 2.0;
    else if (hw == "unclassified")                                hw_val = 2.0;
    else if (hw == "service")                                     hw_val = 1.5;
    else if (hw == "track")                                       hw_val = 1.5;
    else if (hw == "pedestrian")                                  hw_val = 2.5;
    else if (hw == "footway" || hw == "path" || hw == "bridleway") hw_val = 0.75;
    else if (hw == "cycleway")                                    hw_val = 0.75;
    else if (hw == "steps")                                       hw_val = 0.6;
    else                                                          hw_val = 1.5;
    f@half_width = hw_val;
}

float min_hw = 0.75;
float max_hw = 5.0;
if (hw == "footway" || hw == "path" || hw == "bridleway" || hw == "cycleway") {
    min_hw = 0.5;
    max_hw = 1.5;
} else if (hw == "steps") {
    min_hw = 0.4;
    max_hw = 1.2;
} else if (hw == "service" || hw == "track") {
    min_hw = 1.0;
    max_hw = 3.0;
} else if (hw == "residential" || hw == "living_street" || hw == "unclassified") {
    min_hw = 1.2;
    max_hw = 3.5;
} else if (hw == "tertiary" || hw == "tertiary_link") {
    min_hw = 1.5;
    max_hw = 4.5;
} else if (hw == "secondary" || hw == "secondary_link" || hw == "primary" || hw == "primary_link") {
    min_hw = 2.0;
    max_hw = 7.5;
} else if (hw == "trunk" || hw == "trunk_link" || hw == "motorway" || hw == "motorway_link") {
    min_hw = 2.5;
    max_hw = 8.0;
} else if (hw == "pedestrian") {
    min_hw = 1.0;
    max_hw = 4.0;
}

f@half_width = clamp(f@half_width, min_hw, max_hw);
f@road_half_width = f@half_width;
"""


ROAD_DRAPE_VEX = """
// 对每个道路条带顶点按 XZ 垂直投射到地形，防止坡面道路侧边埋入地形。
vector hitp;
vector uvw;
int hit_prim = intersect(1, set(@P.x, 10000.0, @P.z), set(0.0, -20000.0, 0.0), hitp, uvw);
if (hit_prim >= 0) {
    @P.y = max(hitp.y, 0.0) + 0.15;  // 浮起 0.15m，且不低于海平面(Y=0)
} else {
    int near_prim;
    vector near_uvw;
    xyzdist(1, set(@P.x, @P.y, @P.z), near_prim, near_uvw);
    vector tp = primuv(1, "P", near_prim, near_uvw);
    @P.y = max(tp.y, 0.0) + 0.15;
}
"""


ROAD_BBOX_CLIP_TEMPLATE = r"""
import hou

XMIN = __XMIN__
XMAX = __XMAX__
ZMIN = __ZMIN__
ZMAX = __ZMAX__

geo_in = hou.pwd().inputs()[0].geometry()
geo = hou.pwd().geometry()
geo.clear()

prim_attribs = []
for attrib in geo_in.primAttribs():
    try:
        geo.addAttrib(hou.attribType.Prim, attrib.name(), attrib.defaultValue())
        prim_attribs.append(attrib.name())
    except Exception:
        pass

global_attribs = []
for attrib in geo_in.globalAttribs():
    try:
        geo.addAttrib(hou.attribType.Global, attrib.name(), attrib.defaultValue())
        geo.setGlobalAttribValue(attrib.name(), geo_in.attribValue(attrib.name()))
        global_attribs.append(attrib.name())
    except Exception:
        pass

def inside(p, axis, value, keep_greater):
    return p[axis] >= value if keep_greater else p[axis] <= value

def intersect(a, b, axis, value):
    denom = b[axis] - a[axis]
    if abs(denom) < 1e-8:
        return hou.Vector3(a)
    t = (value - a[axis]) / denom
    t = max(0.0, min(1.0, t))
    return hou.Vector3(
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    )

def clip_boundary(poly, axis, value, keep_greater):
    if not poly:
        return []
    out = []
    prev = poly[-1]
    prev_in = inside(prev, axis, value, keep_greater)
    for cur in poly:
        cur_in = inside(cur, axis, value, keep_greater)
        if cur_in:
            if not prev_in:
                out.append(intersect(prev, cur, axis, value))
            out.append(cur)
        elif prev_in:
            out.append(intersect(prev, cur, axis, value))
        prev, prev_in = cur, cur_in
    return out

def clip_poly(poly):
    poly = clip_boundary(poly, 0, XMIN, True)
    poly = clip_boundary(poly, 0, XMAX, False)
    poly = clip_boundary(poly, 2, ZMIN, True)
    poly = clip_boundary(poly, 2, ZMAX, False)
    return poly

for prim in geo_in.prims():
    try:
        if not prim.isClosed():
            continue
    except Exception:
        pass
    pts = [v.point().position() for v in prim.vertices()]
    if len(pts) < 3:
        continue
    clipped = clip_poly(pts)
    if len(clipped) < 3:
        continue
    hpts = []
    for pos in clipped:
        p = geo.createPoint()
        p.setPosition(pos)
        hpts.append(p)
    out_prim = geo.createPolygon()
    for p in hpts:
        out_prim.addVertex(p)
    for name in prim_attribs:
        try:
            out_prim.setAttribValue(name, prim.attribValue(name))
        except Exception:
            pass
"""


def load_road_strips_code(root: Path) -> str:
    return (root / "Scripts" / "_road_strips_v2.py").read_text(encoding="utf-8")


def road_bbox_clip_code(xmin: float, xmax: float, zmin: float, zmax: float) -> str:
    return (
        ROAD_BBOX_CLIP_TEMPLATE
        .replace("__XMIN__", str(xmin))
        .replace("__XMAX__", str(xmax))
        .replace("__ZMIN__", str(zmin))
        .replace("__ZMAX__", str(zmax))
    )
