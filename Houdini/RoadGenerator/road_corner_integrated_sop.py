"""Integrated road corner SOP.

Single Python SOP that reproduces the whole corner pipeline:

    null2 (centre curves)
      -> inline road_offset_stitch  -> 16 tagged polylines
                                       (corner_id 0-3, line_role offset/center)
      -> group by corner_id          -> per corner: 2 offset + 2 center
      -> tangent arc solver          -> modified / centerline / road_surface
      -> extract road_surface        -> clean closed face primitives
      -> merge every corner          -> node output

The two existing external scripts are reused UNMODIFIED. Their source is
exec-ed inside a sandbox whose ``hou.pwd()`` returns a stand-in node, so the
globals they read (node.inputGeometry / node.inputs / node.parent().node)
resolve to the geometry this coordinator feeds them.

Input 0 : null2 centre curves (point attribs number / pscale / N / rest / P).
"""

import sys
from pathlib import Path

import hou

SCRIPT_DIR = Path(__file__).resolve().parent
ROS_PATH = str(SCRIPT_DIR / "road_offset_stitch_sop.py")
ARC_PATH = str(SCRIPT_DIR / "houdini_tangent_arc_sop.py")


class _FakeInput:
    def __init__(self, geometry):
        self._geometry = geometry

    def geometry(self):
        return self._geometry


class _FakeNode:
    """Stand-in for the node that the embedded scripts expect via hou.pwd().

    Carries the input geometries it should expose and the output geometry the
    embedded script writes into, plus parameter passthrough to the real Python
    SOP. The parent passthrough is kept for legacy CTRL fallback.
    """

    def __init__(self, output_geo, inputs, real_node):
        self._geo = output_geo
        self._inputs = [_FakeInput(g) for g in inputs]
        self._real_node = real_node

    def geometry(self):
        return self._geo

    def inputGeometry(self, index):
        return self._inputs[index].geometry()

    def inputs(self):
        return list(self._inputs)

    def parm(self, name):
        return self._real_node.parm(name)

    def evalParm(self, name):
        return self._real_node.evalParm(name)

    def parent(self):
        return self._real_node.parent()

    def addWarning(self, message):
        pass


def _make_hou_proxy(fake_node):
    """Real hou module with pwd() overridden to return the stand-in node."""

    class _HouProxy:
        def pwd(self):
            return fake_node

        def __getattr__(self, name):
            return getattr(hou, name)

    return _HouProxy()


def _run_script(path, output_geo, inputs, real_node):
    """Exec an existing SOP script with a proxied hou.pwd().

    The embedded script's own module-level entry call (build()/main()) runs
    during exec, using the stand-in node so its geometry/inputs/ctrl globals
    resolve to what this coordinator supplies.
    """
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    proxy = _make_hou_proxy(_FakeNode(output_geo, inputs, real_node))
    namespace = {
        "hou": proxy,
        "__name__": "__embedded__",
    }
    saved = sys.modules.get("hou")
    sys.modules["hou"] = proxy
    try:
        exec(compile(source, path, "exec"), namespace)
    finally:
        if saved is not None:
            sys.modules["hou"] = saved
        else:
            sys.modules.pop("hou", None)
    return namespace


def _tag_corner(geo, corner_id):
    if geo.findPrimAttrib("corner_id") is None:
        geo.addAttrib(hou.attribType.Prim, "corner_id", -1)
    for prim in geo.prims():
        prim.setAttribValue("corner_id", int(corner_id))


def _surface_from_arc_output(arc_geo, corner_id):
    """Copy only the solver's closed road-surface faces into a clean geometry."""
    surface = hou.Geometry()
    corner_attrib = surface.addAttrib(hou.attribType.Prim, "corner_id", -1)
    source_attrib = surface.addAttrib(hou.attribType.Prim, "source_surface_prim", -1)

    road_group = arc_geo.findPrimGroup("arc_road_surface")
    if road_group is None:
        raise hou.NodeError(
            "Tangent arc stage did not create the arc_road_surface group."
        )

    point_map = {}

    def clone_point(source_point):
        point = point_map.get(source_point.number())
        if point is None:
            point = surface.createPoint()
            point.setPosition(source_point.position())
            point_map[source_point.number()] = point
        return point

    for source_prim in road_group.prims():
        vertices = list(source_prim.vertices())
        if len(vertices) < 3:
            continue
        poly = surface.createPolygon()
        poly.setIsClosed(True)
        for vertex in vertices:
            poly.addVertex(clone_point(vertex.point()))
        poly.setAttribValue(corner_attrib, int(corner_id))
        poly.setAttribValue(source_attrib, int(source_prim.number()))

    return surface


def build():
    node = hou.pwd()
    out_geo = node.geometry()
    source = node.inputGeometry(0)

    # Stage 1: road_offset_stitch -> 16 tagged polylines.
    stitched = hou.Geometry()
    _run_script(ROS_PATH, stitched, [source], node)

    corner_attrib = stitched.findPrimAttrib("corner_id")
    role_attrib = stitched.findPrimAttrib("line_role")
    if corner_attrib is None or role_attrib is None:
        raise hou.NodeError(
            "road_offset_stitch stage did not tag corner_id / line_role."
        )

    corner_ids = sorted({prim.attribValue(corner_attrib) for prim in stitched.prims()})

    out_geo.clear()

    for corner_id in corner_ids:
        corner_prims = [
            prim for prim in stitched.prims()
            if prim.attribValue(corner_attrib) == corner_id
        ]
        keep = {prim.number() for prim in corner_prims}

        # Bundle of all 4 lines for this corner (input 0 of the arc solver).
        bundle = hou.Geometry()
        bundle.merge(stitched)
        bundle.deletePrims(
            [prim for prim in bundle.prims() if prim.number() not in keep]
        )

        # Centre-only pair (input 1 of the arc solver).
        centre = hou.Geometry()
        centre.merge(stitched)
        centre_role = centre.findPrimAttrib("line_role")
        centre.deletePrims([
            prim for prim in centre.prims()
            if prim.number() not in keep
            or prim.attribValue(centre_role) != "center"
        ])

        # Stage 2: tangent arc for this corner.
        # The arc script reads node.geometry() as its input-0, then clears and
        # rewrites it, so seed the output geo with the 4-line bundle first.
        arc_out = hou.Geometry()
        arc_out.merge(bundle)
        _run_script(ARC_PATH, arc_out, [bundle, centre], node)

        surface = _surface_from_arc_output(arc_out, corner_id)
        out_geo.merge(surface)


build()
