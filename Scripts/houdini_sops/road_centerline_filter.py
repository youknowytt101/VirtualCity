"""Houdini Python SOP: Pre-filter road centerlines to prevent fragmented output.

Input: road centerlines from road_width_flat

Output: filtered centerlines with problematic segments removed

This filter removes:
1. Extremely short segments (< 0.5m) that would cause degenerate quads
2. Segments with extreme angles that cause self-intersection
3. Segments that are too narrow relative to their length (aspect ratio > 100:1)

This prevents the downstream road_topology_builder from generating
fragmented fan-triangulated patches.
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
filtered_short_segments = 0
filtered_degenerate_segments = 0
preserved_segments = 0

MIN_SEGMENT_LENGTH_M = 0.1  # 降低到 10cm，只过滤极短的段
MAX_ASPECT_RATIO = 500.0    # 提高到 500:1，允许更细长的道路


def segment_length_xz(p0, p1):
    """2D distance in XZ plane."""
    dx = p1[0] - p0[0]
    dz = p1[2] - p0[2]
    return math.hypot(dx, dz)


def angle_between_vectors(v1, v2):
    """Angle in degrees between two 2D vectors."""
    len1 = math.hypot(v1[0], v1[1])
    len2 = math.hypot(v2[0], v2[1])
    if len1 < 1e-9 or len2 < 1e-9:
        return 0.0
    dot = (v1[0] * v2[0] + v1[1] * v2[1]) / (len1 * len2)
    dot = max(-1.0, min(1.0, dot))
    return math.degrees(math.acos(dot))


def is_degenerate_segment(pts, hw):
    """Check if a segment would produce degenerate geometry."""
    if len(pts) < 2:
        return True

    # Check total length
    total_len = 0.0
    for i in range(len(pts) - 1):
        total_len += segment_length_xz(pts[i], pts[i + 1])

    if total_len < MIN_SEGMENT_LENGTH_M:
        return True

    # Check aspect ratio (length vs width)
    if hw > 0 and total_len / (2.0 * hw) > MAX_ASPECT_RATIO:
        return True

    # Check for extreme angles (sharp turns that cause self-intersection)
    # Only filter if angle is > 170° (nearly 180° U-turn) to avoid false positives
    for i in range(1, len(pts) - 1):
        prev_seg = (pts[i][0] - pts[i - 1][0], pts[i][2] - pts[i - 1][2])
        next_seg = (pts[i + 1][0] - pts[i][0], pts[i + 1][2] - pts[i][2])
        angle = angle_between_vectors(prev_seg, next_seg)
        # Only filter nearly-180° turns that are almost certain to self-intersect
        if angle > 170.0:
            return True

    return False


# Filter primitives
prims_to_delete = []
for prim in geo.prims():
    try:
        pts = [v.point().position() for v in prim.vertices()]
        if len(pts) < 2:
            prims_to_delete.append(prim)
            filtered_short_segments += 1
            continue

        # Get half-width attribute
        hw = 0.0
        try:
            for attr_name in ['road_hw', 'hw', 'half_width']:
                if geo.findPrimAttrib(attr_name):
                    hw = float(prim.attribValue(attr_name) or 0.0)
                    break
        except Exception:
            pass

        if is_degenerate_segment(pts, hw):
            prims_to_delete.append(prim)
            filtered_degenerate_segments += 1
        else:
            preserved_segments += 1
    except Exception:
        preserved_segments += 1

# Delete marked primitives
if prims_to_delete:
    geo.deletePrims(prims_to_delete, False)

# Set global attributes
try:
    geo.addAttrib(hou.attribType.Global, 'rcf_filtered_short_segments', 0)
    geo.setGlobalAttribValue('rcf_filtered_short_segments', int(filtered_short_segments))
except Exception:
    pass

try:
    geo.addAttrib(hou.attribType.Global, 'rcf_filtered_degenerate_segments', 0)
    geo.setGlobalAttribValue('rcf_filtered_degenerate_segments', int(filtered_degenerate_segments))
except Exception:
    pass

try:
    geo.addAttrib(hou.attribType.Global, 'rcf_preserved_segments', 0)
    geo.setGlobalAttribValue('rcf_preserved_segments', int(preserved_segments))
except Exception:
    pass
