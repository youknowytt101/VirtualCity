"""Road corner extrapolation SOP.

This node exposes the offset/intersection-stitch stage that used to be hidden
inside road_corner_integrated. Keeping it upstream makes bad extrapolated
center/edge curves visible before the tangent-arc surface stage runs.
"""

import os

import hou


def _load_integrated_helpers():
    script_path = os.path.join(
        os.path.dirname(hou.hipFile.path()),
        "road_corner_integrated_sop.py",
    )
    namespace = {
        "ROAD_CORNER_INTEGRATED_AUTOBUILD": False,
        "__file__": script_path,
    }
    with open(script_path, "r", encoding="utf-8") as handle:
        exec(compile(handle.read(), script_path, "exec"), namespace)
    return namespace


def _set_detail_string(geo, name, value):
    attrib = geo.findGlobalAttrib(name)
    if attrib is None:
        attrib = geo.addAttrib(hou.attribType.Global, name, "")
    geo.setGlobalAttribValue(attrib, value)


def build():
    node = hou.pwd()
    out_geo = node.geometry()
    source = node.inputGeometry(0)
    helpers = _load_integrated_helpers()

    out_geo.clear()

    direct_surface = helpers["_direct_extrapolated_surface"](source)
    if direct_surface is not None:
        out_geo.merge(direct_surface)
        _set_detail_string(out_geo, "road_corner_extrapolate_mode", "surface")
        return

    stitched = helpers["_run_stitch"](source)
    out_geo.merge(stitched)
    _set_detail_string(out_geo, "road_corner_extrapolate_mode", "stitched")


build()
