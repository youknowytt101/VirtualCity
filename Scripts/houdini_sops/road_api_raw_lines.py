"""Houdini Python SOP: copy raw map API road lines from osm_import.

Input: combined osm_import geometry containing building polygons and road lines.
Output: only road primitives, selected by the `roads` group or `highway` attr.

This SOP intentionally does not resample, simplify, graph-filter, smooth, or
surface roads. It preserves the API way geometry after Houdini coordinate
conversion.
"""

import hou

node = hou.pwd()
geo = node.geometry()
geo.clear()

geo_in = node.inputs()[0].geometry() if node.inputs() else None


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


if geo_in is None:
    set_global("road_api_raw_status", "missing_input")
    set_global("road_api_raw_copied_prims", 0)
    set_global("road_api_raw_copied_points", 0)
else:
    geo.merge(geo_in)

    roads_group = geo.findPrimGroup("roads")
    highway_attr = geo.findPrimAttrib("highway")
    keep_numbers = set()

    if roads_group is not None:
        keep_numbers.update(prim.number() for prim in roads_group.prims())

    if highway_attr is not None:
        for prim in geo.prims():
            try:
                if str(prim.attribValue(highway_attr) or "").strip():
                    keep_numbers.add(prim.number())
            except Exception:
                pass

    doomed = [prim for prim in geo.prims() if prim.number() not in keep_numbers]
    if doomed:
        geo.deletePrims(doomed, True)

    set_global("road_api_raw_status", "copied")
    set_global("road_api_raw_copied_prims", int(len(geo.prims())))
    set_global("road_api_raw_copied_points", int(len(geo.points())))
