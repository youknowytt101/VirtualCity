"""Houdini Python SOP: keep complete assets whose bounds touch the build area.

This is deliberately not a geometric clipper.  It removes whole primitives or
whole connected components so edge buildings/roads do not become half-assets.
"""
import hou

XMIN = __XMIN__
XMAX = __XMAX__
ZMIN = __ZMIN__
ZMAX = __ZMAX__
MODE = "__MODE__"  # "component" for buildings/foundations, "primitive" for roads.

geo_in = hou.pwd().inputs()[0].geometry()
geo = hou.pwd().geometry()
geo.clear()
geo.merge(geo_in)


def ensure_global(name, default):
    try:
        if geo.findGlobalAttrib(name) is None:
            geo.addAttrib(hou.attribType.Global, name, default)
    except Exception:
        pass


def set_global(name, value):
    try:
        ensure_global(name, value)
        geo.setGlobalAttribValue(name, value)
    except Exception:
        pass


def prim_bounds(prim):
    pts = [v.point().position() for v in prim.vertices()]
    if not pts:
        return None
    xs = [p[0] for p in pts]
    zs = [p[2] for p in pts]
    return min(xs), max(xs), min(zs), max(zs)


def bounds_touch_area(bounds):
    if bounds is None:
        return False
    min_x, max_x, min_z, max_z = bounds
    return not (max_x < XMIN or min_x > XMAX or max_z < ZMIN or min_z > ZMAX)


def merged_bounds(prims):
    out = None
    for prim in prims:
        b = prim_bounds(prim)
        if b is None:
            continue
        if out is None:
            out = list(b)
        else:
            out[0] = min(out[0], b[0])
            out[1] = max(out[1], b[1])
            out[2] = min(out[2], b[2])
            out[3] = max(out[3], b[3])
    return out


prims = list(geo.prims())
drop = set()
kept_units = 0
removed_units = 0

if MODE == "primitive":
    for prim in prims:
        if bounds_touch_area(prim_bounds(prim)):
            kept_units += 1
        else:
            drop.add(prim.number())
            removed_units += 1
else:
    point_to_prims = {}
    for prim in prims:
        for point in prim.points():
            point_to_prims.setdefault(point.number(), []).append(prim.number())

    prim_by_number = {prim.number(): prim for prim in prims}
    pending = set(prim_by_number)
    while pending:
        seed = pending.pop()
        stack = [seed]
        component_numbers = [seed]
        while stack:
            current = stack.pop()
            prim = prim_by_number[current]
            for point in prim.points():
                for neighbor in point_to_prims.get(point.number(), ()):
                    if neighbor in pending:
                        pending.remove(neighbor)
                        stack.append(neighbor)
                        component_numbers.append(neighbor)

        component_prims = [prim_by_number[num] for num in component_numbers]
        if bounds_touch_area(merged_bounds(component_prims)):
            kept_units += 1
        else:
            removed_units += 1
            drop.update(component_numbers)

if drop:
    doomed = [prim for prim in geo.prims() if prim.number() in drop]
    geo.deletePrims(doomed, True)

set_global("asset_bounds_filter_mode", MODE)
set_global("asset_bounds_kept_units", int(kept_units))
set_global("asset_bounds_removed_units", int(removed_units))
set_global("asset_bounds_removed_prims", int(len(drop)))

# Preserve the road QA counters without claiming that geometric bbox clipping happened.
if MODE == "primitive":
    set_global("road_bbox_triangulated_count", 0)
    set_global("road_bbox_clipped_ngon_count", 0)
    set_global("road_bbox_preserved_ngon_count", int(kept_units))
