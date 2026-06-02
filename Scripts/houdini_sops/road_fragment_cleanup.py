"""Houdini Python SOP: Remove fragmented road triangles from fan-triangulation.

Input: road geometry from road_strips or road_topology_builder

Output: same geometry with small degenerate triangles removed

This filter removes:
1. Triangles with area < 0.1 m² (obviously degenerate)
2. Triangles with any edge < 0.05m (microscopic slivers)
3. Triangles with min angle < 5° (extremely sharp)

These are typically artifacts from fan-triangulation of self-intersecting quads
or invalid junction patches, not real road geometry.
"""

import math
import hou

node = hou.pwd()
geo_in = node.inputs()[0].geometry() if node.inputs() else None
geo = node.geometry()

if geo_in:
    geo.clear()
    geo.merge(geo_in)

# Preserve all attributes
prim_attribs = []
for attrib in geo.primAttribs():
    try:
        if geo.findPrimAttrib(attrib.name()) is None:
            geo.addAttrib(hou.attribType.Prim, attrib.name(), attrib.defaultValue())
        prim_attribs.append(attrib.name())
    except Exception:
        pass

# Global counters
removed_tiny_triangles = 0
removed_sliver_triangles = 0
removed_sharp_triangles = 0
preserved_prims = 0

MIN_TRIANGLE_AREA_M2 = 0.1
MIN_EDGE_LENGTH_M = 0.05
MIN_ANGLE_DEG = 5.0


def poly_area_xz(pts):
    """Calculate 2D polygon area in XZ plane."""
    if len(pts) < 3:
        return 0.0
    area = 0.0
    for i in range(len(pts)):
        p0 = pts[i]
        p1 = pts[(i + 1) % len(pts)]
        area += p0[0] * p1[1] - p1[0] * p0[1]
    return abs(area) * 0.5


def min_edge_length_xz(pts):
    """Find minimum edge length in 2D XZ plane."""
    if len(pts) < 2:
        return 0.0
    min_len = 1e9
    for i in range(len(pts)):
        p0 = pts[i]
        p1 = pts[(i + 1) % len(pts)]
        dx = p1[0] - p0[0]
        dz = p1[1] - p0[1]
        length = math.hypot(dx, dz)
        min_len = min(min_len, length)
    return min_len if min_len < 1e9 else 0.0


def min_angle_xz(pts):
    """Find minimum interior angle in 2D XZ polygon."""
    if len(pts) < 3:
        return None
    min_angle = None
    for i in range(len(pts)):
        prev = pts[(i - 1) % len(pts)]
        cur = pts[i]
        nxt = pts[(i + 1) % len(pts)]

        v1 = (prev[0] - cur[0], prev[1] - cur[1])
        v2 = (nxt[0] - cur[0], nxt[1] - cur[1])

        len1 = math.hypot(v1[0], v1[1])
        len2 = math.hypot(v2[0], v2[1])

        if len1 < 1e-9 or len2 < 1e-9:
            continue

        dot = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (len1 * len2)))
        angle = math.degrees(math.acos(dot))

        if min_angle is None:
            min_angle = angle
        else:
            min_angle = min(min_angle, angle)

    return min_angle


# Filter primitives
prims_to_delete = []
for prim in geo.prims():
    try:
        # Only check triangles (3 vertices)
        if len(prim.vertices()) != 3:
            preserved_prims += 1
            continue

        pts_3d = [v.point().position() for v in prim.vertices()]
        pts_2d = [(p[0], p[2]) for p in pts_3d]  # XZ plane

        # Check area
        area = poly_area_xz(pts_2d)
        if area < MIN_TRIANGLE_AREA_M2:
            prims_to_delete.append(prim)
            removed_tiny_triangles += 1
            continue

        # Check minimum edge length
        min_edge = min_edge_length_xz(pts_2d)
        if min_edge < MIN_EDGE_LENGTH_M:
            prims_to_delete.append(prim)
            removed_sliver_triangles += 1
            continue

        # Check minimum angle
        min_angle = min_angle_xz(pts_2d)
        if min_angle is not None and min_angle < MIN_ANGLE_DEG:
            prims_to_delete.append(prim)
            removed_sharp_triangles += 1
            continue

        preserved_prims += 1
    except Exception:
        preserved_prims += 1

# Delete marked primitives
if prims_to_delete:
    geo.deletePrims(prims_to_delete, False)

# Set global attributes
try:
    geo.addAttrib(hou.attribType.Global, 'rfc_removed_tiny_triangles', 0)
    geo.setGlobalAttribValue('rfc_removed_tiny_triangles', int(removed_tiny_triangles))
except Exception:
    pass

try:
    geo.addAttrib(hou.attribType.Global, 'rfc_removed_sliver_triangles', 0)
    geo.setGlobalAttribValue('rfc_removed_sliver_triangles', int(removed_sliver_triangles))
except Exception:
    pass

try:
    geo.addAttrib(hou.attribType.Global, 'rfc_removed_sharp_triangles', 0)
    geo.setGlobalAttribValue('rfc_removed_sharp_triangles', int(removed_sharp_triangles))
except Exception:
    pass

try:
    geo.addAttrib(hou.attribType.Global, 'rfc_preserved_prims', 0)
    geo.setGlobalAttribValue('rfc_preserved_prims', int(preserved_prims))
except Exception:
    pass
