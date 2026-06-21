"""Extract clean centre-line branch pairs around each road crossing.

Standalone Python SOP. Reads merged centre polylines from input 0, finds every
XZ-plane crossing between distinct primitives, clips each participating branch,
then emits only adjacent branch pairs as polylines through the crossing. For a
T-junction this yields three corner candidate lines, while a four-way crossing
yields four instead of diagonal all-pairs combinations.
"""

import bisect
import math
import os

import hou

EPS = 1.0e-9
CROSSING_MERGE_TOLERANCE = 1.0e-4
MIN_ARM_LENGTH = 1.0e-4
EXTRACTION_DISTANCE_SCALE = 4.0
_INTEGRATED_HELPERS = None


def _clamp(value, low, high):
    return max(low, min(high, value))


def _lerp_tuple(a, b, amount):
    if a is None or b is None:
        return a if amount < 0.5 else b
    return tuple(float(a[i]) * (1.0 - amount) + float(b[i]) * amount for i in range(len(a)))


def _point_record(point, pscale_attr, number_attr, normal_attr, rest_attr):
    pos = point.position()
    return {
        "pos": hou.Vector3(pos),
        "xz": (float(pos.x()), float(pos.z())),
        "pscale": float(point.attribValue(pscale_attr)) if pscale_attr is not None else 0.0,
        "number": int(point.attribValue(number_attr)) if number_attr is not None else point.number(),
        "N": tuple(point.attribValue(normal_attr)) if normal_attr is not None else None,
        "rest": tuple(point.attribValue(rest_attr)) if rest_attr is not None else None,
    }


def _polylines(geo):
    lines = []
    pscale_attr = geo.findPointAttrib("pscale")
    number_attr = geo.findPointAttrib("number")
    normal_attr = geo.findPointAttrib("N")
    rest_attr = geo.findPointAttrib("rest")
    for line_index, prim in enumerate(geo.prims()):
        verts = list(prim.vertices())
        if len(verts) < 2:
            continue
        pts = [
            _point_record(vertex.point(), pscale_attr, number_attr, normal_attr, rest_attr)
            for vertex in verts
        ]
        cum = [0.0]
        for index in range(1, len(pts)):
            cum.append(cum[-1] + pts[index]["pos"].distanceTo(pts[index - 1]["pos"]))
        lines.append({
            "index": line_index,
            "source_prim": prim.number(),
            "pts": pts,
            "cum": cum,
            "length": cum[-1],
        })
    return lines


def _seg_intersection_xz(a, b, c, d):
    """Return (point2d, t_on_ab, u_on_cd) including endpoint touches."""
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    denom = r[0] * s[1] - r[1] * s[0]
    if abs(denom) <= EPS:
        return None
    qp = (c[0] - a[0], c[1] - a[1])
    t = (qp[0] * s[1] - qp[1] * s[0]) / denom
    u = (qp[0] * r[1] - qp[1] * r[0]) / denom
    if t < -CROSSING_MERGE_TOLERANCE or t > 1.0 + CROSSING_MERGE_TOLERANCE:
        return None
    if u < -CROSSING_MERGE_TOLERANCE or u > 1.0 + CROSSING_MERGE_TOLERANCE:
        return None
    t = _clamp(t, 0.0, 1.0)
    u = _clamp(u, 0.0, 1.0)
    return (a[0] + r[0] * t, a[1] + r[1] * t), t, u


def _append_unique_length(lengths, value):
    if all(abs(value - existing) > CROSSING_MERGE_TOLERANCE for existing in lengths):
        lengths.append(value)


def _merge_crossing(crossings, candidate):
    for crossing in crossings:
        if crossing["point"].distanceTo(candidate["point"]) > CROSSING_MERGE_TOLERANCE:
            continue
        crossing["pscale"] = max(crossing["pscale"], candidate["pscale"])
        for line_index, lengths in candidate["line_lengths"].items():
            target = crossing["line_lengths"].setdefault(line_index, [])
            for length in lengths:
                _append_unique_length(target, length)
        return
    crossings.append(candidate)


def _find_crossings(lines):
    crossings = []
    for first_index, first in enumerate(lines):
        for second_index in range(first_index + 1, len(lines)):
            second = lines[second_index]
            for first_segment in range(len(first["pts"]) - 1):
                a = first["pts"][first_segment]
                b = first["pts"][first_segment + 1]
                first_span = first["cum"][first_segment + 1] - first["cum"][first_segment]
                for second_segment in range(len(second["pts"]) - 1):
                    c = second["pts"][second_segment]
                    d = second["pts"][second_segment + 1]
                    hit = _seg_intersection_xz(a["xz"], b["xz"], c["xz"], d["xz"])
                    if hit is None:
                        continue
                    point_xz, amount_first, amount_second = hit
                    second_span = second["cum"][second_segment + 1] - second["cum"][second_segment]
                    first_length = first["cum"][first_segment] + first_span * amount_first
                    second_length = second["cum"][second_segment] + second_span * amount_second
                    first_pscale = a["pscale"] * (1.0 - amount_first) + b["pscale"] * amount_first
                    second_pscale = c["pscale"] * (1.0 - amount_second) + d["pscale"] * amount_second
                    _merge_crossing(crossings, {
                        "point": hou.Vector3(point_xz[0], 0.0, point_xz[1]),
                        "pscale": max(first_pscale, second_pscale),
                        "line_lengths": {
                            first["index"]: [first_length],
                            second["index"]: [second_length],
                        },
                    })
    crossings.sort(key=lambda item: (round(float(item["point"].x()), 4), round(float(item["point"].z()), 4)))
    return crossings


def _sample_line(line, length):
    pts = line["pts"]
    if not pts:
        return None
    if len(pts) == 1 or line["length"] <= EPS:
        return dict(pts[0])
    length = _clamp(length, 0.0, line["length"])
    index = bisect.bisect_left(line["cum"], length)
    if index <= 0:
        return dict(pts[0])
    if index >= len(pts):
        return dict(pts[-1])
    prev_length = line["cum"][index - 1]
    span = line["cum"][index] - prev_length
    amount = 0.0 if span <= EPS else (length - prev_length) / span
    a = pts[index - 1]
    b = pts[index]
    pos = a["pos"] + (b["pos"] - a["pos"]) * amount
    return {
        "pos": pos,
        "xz": (float(pos.x()), float(pos.z())),
        "pscale": a["pscale"] * (1.0 - amount) + b["pscale"] * amount,
        "number": a["number"] if amount < 0.5 else b["number"],
        "N": _lerp_tuple(a["N"], b["N"], amount),
        "rest": _lerp_tuple(a["rest"], b["rest"], amount),
    }


def _nearby_crossing_lengths(crossings, line_index):
    lengths = []
    for crossing in crossings:
        lengths.extend(crossing["line_lengths"].get(line_index, []))
    return sorted(lengths)


def _limited_bounds(line, line_index, center_length, radius, crossing_lengths):
    lower = max(0.0, center_length - radius)
    upper = min(line["length"], center_length + radius)
    for other in crossing_lengths:
        if abs(other - center_length) <= CROSSING_MERGE_TOLERANCE:
            continue
        midpoint = (other + center_length) * 0.5
        if other < center_length:
            lower = max(lower, midpoint)
        else:
            upper = min(upper, midpoint)
    return lower, upper


def _add_point(geo, sample, num_attr, ps_attr, normal_attr, rest_attr):
    point = geo.createPoint()
    point.setPosition(sample["pos"])
    if num_attr is not None:
        point.setAttribValue(num_attr, int(sample["number"]))
    if ps_attr is not None:
        point.setAttribValue(ps_attr, float(sample["pscale"]))
    if normal_attr is not None and sample["N"] is not None:
        point.setAttribValue(normal_attr, sample["N"])
    if rest_attr is not None and sample["rest"] is not None:
        point.setAttribValue(rest_attr, sample["rest"])
    return point


def _samples_between(line, start_length, end_length):
    low = min(start_length, end_length)
    high = max(start_length, end_length)
    interior = [
        (length, _sample_line(line, length))
        for length in line["cum"]
        if low + CROSSING_MERGE_TOLERANCE < length < high - CROSSING_MERGE_TOLERANCE
    ]
    if end_length < start_length:
        interior.reverse()
    samples = [_sample_line(line, start_length)] + [sample for _, sample in interior] + [_sample_line(line, end_length)]
    clean = []
    for sample in samples:
        if sample is None:
            continue
        if clean and sample["pos"].distanceTo(clean[-1]["pos"]) <= CROSSING_MERGE_TOLERANCE:
            continue
        clean.append(sample)
    return clean


def _branch_arm(line, start_length, end_length, side):
    if abs(end_length - start_length) <= MIN_ARM_LENGTH:
        return None
    samples = _samples_between(line, start_length, end_length)
    if len(samples) < 2:
        return None
    crossing_pos = samples[0]["pos"]
    end_pos = samples[-1]["pos"]
    return {
        "line": line,
        "side": int(side),
        "samples": samples,
        "angle": math.atan2(float(end_pos.z() - crossing_pos.z()), float(end_pos.x() - crossing_pos.x())),
    }


def _clean_sample_sequence(samples):
    clean = []
    for sample in samples:
        if clean and sample["pos"].distanceTo(clean[-1]["pos"]) <= CROSSING_MERGE_TOLERANCE:
            continue
        clean.append(sample)
    return clean


def _sample_normal(sample):
    normal = sample.get("N")
    if normal is None:
        return None
    vector = hou.Vector3(float(normal[0]), 0.0, float(normal[2]))
    if vector.length() <= EPS:
        return None
    return vector.normalized()


def _normal_from_tangent(tangent, reference):
    tangent = hou.Vector3(float(tangent[0]), 0.0, float(tangent[2]))
    if tangent.length() <= EPS:
        return reference
    tangent = tangent.normalized()
    normal = hou.Vector3(-tangent.z(), 0.0, tangent.x())
    if reference is not None and normal.dot(reference) < 0.0:
        normal *= -1.0
    return normal.normalized()


def _rebuild_output_normals(samples):
    if not any(sample.get("N") is not None for sample in samples):
        return samples
    rebuilt = []
    previous_normal = None
    for index, sample in enumerate(samples):
        if len(samples) == 1:
            tangent = hou.Vector3(0.0, 0.0, 0.0)
        elif index == 0:
            tangent = samples[1]["pos"] - sample["pos"]
        elif index == len(samples) - 1:
            tangent = sample["pos"] - samples[index - 1]["pos"]
        else:
            tangent = samples[index + 1]["pos"] - samples[index - 1]["pos"]
        reference = previous_normal or _sample_normal(sample)
        normal = _normal_from_tangent(tangent, reference)
        if normal is not None:
            sample = dict(sample)
            sample["N"] = tuple(normal)
            previous_normal = normal
        rebuilt.append(sample)
    return rebuilt


def _sample_offset_xz(sample, sign):
    normal = _sample_normal(sample)
    if normal is None:
        return sample["xz"]
    offset = normal * float(sample.get("pscale", 0.0)) * sign
    pos = sample["pos"] + offset
    return float(pos.x()), float(pos.z())


def _is_endpoint_touch(t_on_output, u_on_input):
    endpoint_eps = 1.0e-5
    output_endpoint = t_on_output <= endpoint_eps or t_on_output >= 1.0 - endpoint_eps
    input_endpoint = u_on_input <= endpoint_eps or u_on_input >= 1.0 - endpoint_eps
    return output_endpoint and input_endpoint


def _offset_centerline_hit_count(samples, source_lines, sign):
    if not any(sample.get("N") is not None for sample in samples):
        return 0
    offset_points = [_sample_offset_xz(sample, sign) for sample in samples]
    hits = 0
    for start, end in zip(offset_points[:-1], offset_points[1:]):
        if (end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2 <= EPS:
            continue
        for line in source_lines:
            pts = line["pts"]
            for first, second in zip(pts[:-1], pts[1:]):
                hit = _seg_intersection_xz(start, end, first["xz"], second["xz"])
                if hit is None:
                    continue
                _, t_on_output, u_on_input = hit
                if _is_endpoint_touch(t_on_output, u_on_input):
                    continue
                hits += 1
                if hits > 8:
                    return hits
    return hits


def _flip_sample_normals(samples):
    flipped = []
    for sample in samples:
        normal = sample.get("N")
        if normal is None:
            flipped.append(sample)
            continue
        sample = dict(sample)
        sample["N"] = tuple(-float(component) for component in normal)
        flipped.append(sample)
    return flipped


def _copy_candidate_point_attrs(geo):
    return {
        "number": geo.addAttrib(hou.attribType.Point, "number", -1),
        "pscale": geo.addAttrib(hou.attribType.Point, "pscale", 0.0),
        "N": geo.addAttrib(hou.attribType.Point, "N", (0.0, 0.0, 0.0)),
        "rest": geo.addAttrib(hou.attribType.Point, "rest", (0.0, 0.0, 0.0)),
    }


def _copy_candidate_prim_attrs(geo):
    return {
        "corner_id": geo.addAttrib(hou.attribType.Prim, "corner_id", -1),
        "crossing_id": geo.addAttrib(hou.attribType.Prim, "crossing_id", -1),
        "source_prim": geo.addAttrib(hou.attribType.Prim, "source_prim", -1),
        "source_line": geo.addAttrib(hou.attribType.Prim, "source_line", -1),
        "corner_side": geo.addAttrib(hou.attribType.Prim, "corner_side", 0),
        "source_prim0": geo.addAttrib(hou.attribType.Prim, "source_prim0", -1),
        "source_prim1": geo.addAttrib(hou.attribType.Prim, "source_prim1", -1),
        "source_line0": geo.addAttrib(hou.attribType.Prim, "source_line0", -1),
        "source_line1": geo.addAttrib(hou.attribType.Prim, "source_line1", -1),
        "corner_side0": geo.addAttrib(hou.attribType.Prim, "corner_side0", 0),
        "corner_side1": geo.addAttrib(hou.attribType.Prim, "corner_side1", 0),
        "branch_angle0": geo.addAttrib(hou.attribType.Prim, "branch_angle0", 0.0),
        "branch_angle1": geo.addAttrib(hou.attribType.Prim, "branch_angle1", 0.0),
        "corner_position": geo.addAttrib(hou.attribType.Prim, "corner_position", (0.0, 0.0, 0.0)),
        "corner_pscale": geo.addAttrib(hou.attribType.Prim, "corner_pscale", 0.0),
        "corner_keep_distance": geo.addAttrib(hou.attribType.Prim, "corner_keep_distance", 0.0),
    }


def _candidate_geometry(samples, first_arm, second_arm, crossing, crossing_id, corner_id, keep_distance):
    geometry = hou.Geometry()
    point_attrs = _copy_candidate_point_attrs(geometry)
    prim_attrs = _copy_candidate_prim_attrs(geometry)
    poly = geometry.createPolygon()
    poly.setIsClosed(False)
    for sample in samples:
        point = geometry.createPoint()
        point.setPosition(sample["pos"])
        point.setAttribValue(point_attrs["number"], int(sample.get("number", -1)))
        point.setAttribValue(point_attrs["pscale"], float(sample.get("pscale", 0.0)))
        point.setAttribValue(point_attrs["N"], sample.get("N") or (0.0, 0.0, 0.0))
        point.setAttribValue(point_attrs["rest"], sample.get("rest") or tuple(sample["pos"]))
        poly.addVertex(point)

    poly.setAttribValue(prim_attrs["corner_id"], int(corner_id))
    poly.setAttribValue(prim_attrs["crossing_id"], int(crossing_id))
    poly.setAttribValue(prim_attrs["source_prim"], int(first_arm["line"]["source_prim"]))
    poly.setAttribValue(prim_attrs["source_line"], int(first_arm["line"]["index"]))
    poly.setAttribValue(prim_attrs["corner_side"], 0)
    poly.setAttribValue(prim_attrs["source_prim0"], int(first_arm["line"]["source_prim"]))
    poly.setAttribValue(prim_attrs["source_prim1"], int(second_arm["line"]["source_prim"]))
    poly.setAttribValue(prim_attrs["source_line0"], int(first_arm["line"]["index"]))
    poly.setAttribValue(prim_attrs["source_line1"], int(second_arm["line"]["index"]))
    poly.setAttribValue(prim_attrs["corner_side0"], int(first_arm["side"]))
    poly.setAttribValue(prim_attrs["corner_side1"], int(second_arm["side"]))
    poly.setAttribValue(prim_attrs["branch_angle0"], float(first_arm["angle"]))
    poly.setAttribValue(prim_attrs["branch_angle1"], float(second_arm["angle"]))
    poly.setAttribValue(prim_attrs["corner_position"], tuple(crossing["point"]))
    poly.setAttribValue(prim_attrs["corner_pscale"], float(crossing["pscale"]))
    poly.setAttribValue(prim_attrs["corner_keep_distance"], float(keep_distance))
    return geometry


def _load_integrated_helpers():
    global _INTEGRATED_HELPERS
    if _INTEGRATED_HELPERS is not None:
        return _INTEGRATED_HELPERS
    script_path = os.path.join(os.path.dirname(hou.hipFile.path()), "road_corner_integrated_sop.py")
    namespace = {
        "ROAD_CORNER_INTEGRATED_AUTOBUILD": False,
        "__file__": script_path,
    }
    with open(script_path, "r", encoding="utf-8") as handle:
        exec(compile(handle.read(), script_path, "exec"), namespace)
    _INTEGRATED_HELPERS = namespace
    return namespace


def _polyline_source_hit_count(points_xz, source_lines):
    hits = 0
    for start, end in zip(points_xz[:-1], points_xz[1:]):
        if (end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2 <= EPS:
            continue
        for line in source_lines:
            pts = line["pts"]
            for first, second in zip(pts[:-1], pts[1:]):
                hit = _seg_intersection_xz(start, end, first["xz"], second["xz"])
                if hit is None:
                    continue
                _, t_on_output, u_on_input = hit
                if _is_endpoint_touch(t_on_output, u_on_input):
                    continue
                hits += 1
                if hits > 8:
                    return hits
    return hits


def _stitched_offset_source_hit_count(stitched, source_lines):
    role_attr = stitched.findPrimAttrib("line_role")
    hits = 0
    for prim in stitched.prims():
        if role_attr is not None and prim.attribValue(role_attr) != "offset":
            continue
        points_xz = [
            (float(vertex.point().position().x()), float(vertex.point().position().z()))
            for vertex in prim.vertices()
        ]
        hits += _polyline_source_hit_count(points_xz, source_lines)
        if hits > 8:
            return hits
    return hits


def _candidate_stitch_is_valid(samples, first_arm, second_arm, crossing, crossing_id, corner_id, keep_distance, source_lines):
    try:
        helpers = _load_integrated_helpers()
        candidate = _candidate_geometry(
            samples,
            first_arm,
            second_arm,
            crossing,
            crossing_id,
            corner_id,
            keep_distance,
        )
        stitched = helpers["_run_stitch"](candidate)
    except Exception:
        return True
    return _stitched_offset_source_hit_count(stitched, source_lines) == 0


def _validate_output_normal_side(samples, source_lines):
    current_hits = _offset_centerline_hit_count(samples, source_lines, 1.0)
    if current_hits == 0:
        return samples
    flipped_hits = _offset_centerline_hit_count(samples, source_lines, -1.0)
    if flipped_hits == 0:
        return _flip_sample_normals(samples)
    return samples


def _emit_corner_pair(geo, first_arm, second_arm, crossing, crossing_id, corner_id, keep_distance, source_lines, attrs):
    # Arms are stored crossing -> branch end. Reverse the first so each output
    # primitive runs branch end -> crossing -> branch end.
    samples = _clean_sample_sequence(
        list(reversed(first_arm["samples"])) + second_arm["samples"][1:]
    )
    if len(samples) < 2:
        return None
    samples = _rebuild_output_normals(samples)
    samples = _validate_output_normal_side(samples, source_lines)
    if not _candidate_stitch_is_valid(
        samples,
        first_arm,
        second_arm,
        crossing,
        crossing_id,
        corner_id,
        keep_distance,
        source_lines,
    ):
        return None
    poly = geo.createPolygon()
    poly.setIsClosed(False)
    for sample in samples:
        poly.addVertex(_add_point(
            geo,
            sample,
            attrs["number"],
            attrs["pscale"],
            attrs["N"],
            attrs["rest"],
        ))
    poly.setAttribValue(attrs["corner_id"], int(corner_id))
    poly.setAttribValue(attrs["crossing_id"], int(crossing_id))
    poly.setAttribValue(attrs["source_prim"], int(first_arm["line"]["source_prim"]))
    poly.setAttribValue(attrs["source_line"], int(first_arm["line"]["index"]))
    poly.setAttribValue(attrs["corner_side"], 0)
    poly.setAttribValue(attrs["source_prim0"], int(first_arm["line"]["source_prim"]))
    poly.setAttribValue(attrs["source_prim1"], int(second_arm["line"]["source_prim"]))
    poly.setAttribValue(attrs["source_line0"], int(first_arm["line"]["index"]))
    poly.setAttribValue(attrs["source_line1"], int(second_arm["line"]["index"]))
    poly.setAttribValue(attrs["corner_side0"], int(first_arm["side"]))
    poly.setAttribValue(attrs["corner_side1"], int(second_arm["side"]))
    poly.setAttribValue(attrs["branch_angle0"], float(first_arm["angle"]))
    poly.setAttribValue(attrs["branch_angle1"], float(second_arm["angle"]))
    poly.setAttribValue(attrs["corner_position"], tuple(crossing["point"]))
    poly.setAttribValue(attrs["corner_pscale"], float(crossing["pscale"]))
    poly.setAttribValue(attrs["corner_keep_distance"], float(keep_distance))
    return poly


def _output_attrs(src, geo):
    attrs = {
        "number": geo.addAttrib(hou.attribType.Point, "number", -1)
        if src.findPointAttrib("number") is not None else None,
        "pscale": geo.addAttrib(hou.attribType.Point, "pscale", 0.0)
        if src.findPointAttrib("pscale") is not None else None,
        "N": geo.addAttrib(hou.attribType.Point, "N", (0.0, 0.0, 0.0))
        if src.findPointAttrib("N") is not None else None,
        "rest": geo.addAttrib(hou.attribType.Point, "rest", (0.0, 0.0, 0.0))
        if src.findPointAttrib("rest") is not None else None,
        "corner_id": geo.addAttrib(hou.attribType.Prim, "corner_id", -1),
        "crossing_id": geo.addAttrib(hou.attribType.Prim, "crossing_id", -1),
        "source_prim": geo.addAttrib(hou.attribType.Prim, "source_prim", -1),
        "source_line": geo.addAttrib(hou.attribType.Prim, "source_line", -1),
        "corner_side": geo.addAttrib(hou.attribType.Prim, "corner_side", 0),
        "source_prim0": geo.addAttrib(hou.attribType.Prim, "source_prim0", -1),
        "source_prim1": geo.addAttrib(hou.attribType.Prim, "source_prim1", -1),
        "source_line0": geo.addAttrib(hou.attribType.Prim, "source_line0", -1),
        "source_line1": geo.addAttrib(hou.attribType.Prim, "source_line1", -1),
        "corner_side0": geo.addAttrib(hou.attribType.Prim, "corner_side0", 0),
        "corner_side1": geo.addAttrib(hou.attribType.Prim, "corner_side1", 0),
        "branch_angle0": geo.addAttrib(hou.attribType.Prim, "branch_angle0", 0.0),
        "branch_angle1": geo.addAttrib(hou.attribType.Prim, "branch_angle1", 0.0),
        "corner_position": geo.addAttrib(hou.attribType.Prim, "corner_position", (0.0, 0.0, 0.0)),
        "corner_pscale": geo.addAttrib(hou.attribType.Prim, "corner_pscale", 0.0),
        "corner_keep_distance": geo.addAttrib(hou.attribType.Prim, "corner_keep_distance", 0.0),
    }
    return attrs


def build():
    node = hou.pwd()
    geo = node.geometry()
    src = node.inputGeometry(0)

    lines = _polylines(src)
    geo.clear()
    attrs = _output_attrs(src, geo)
    if len(lines) < 2:
        node.addWarning("road_corner_extract needs at least two centre-line primitives.")
        return

    crossings = _find_crossings(lines)
    if not crossings:
        node.addWarning("road_corner_extract found no centre-line crossings.")
        return

    lines_by_index = {line["index"]: line for line in lines}
    crossing_lengths_by_line = {
        line["index"]: _nearby_crossing_lengths(crossings, line["index"])
        for line in lines
    }
    emitted = 0
    next_corner_id = 0
    for crossing_id, crossing in enumerate(crossings):
        radius = crossing["pscale"] * EXTRACTION_DISTANCE_SCALE
        if radius <= MIN_ARM_LENGTH:
            continue
        arms = []
        for line_index, lengths in sorted(crossing["line_lengths"].items()):
            line = lines_by_index.get(line_index)
            if line is None:
                continue
            for center_length in sorted(lengths):
                lower, upper = _limited_bounds(
                    line,
                    line_index,
                    center_length,
                    radius,
                    crossing_lengths_by_line.get(line_index, []),
                )
                if center_length - lower > MIN_ARM_LENGTH:
                    arm = _branch_arm(line, center_length, lower, -1)
                    if arm is not None:
                        arms.append(arm)
                if upper - center_length > MIN_ARM_LENGTH:
                    arm = _branch_arm(line, center_length, upper, 1)
                    if arm is not None:
                        arms.append(arm)
        arms.sort(key=lambda arm: arm["angle"])
        adjacent_pairs = []
        if len(arms) == 2:
            adjacent_pairs.append((arms[0], arms[1]))
        elif len(arms) > 2:
            adjacent_pairs.extend(
                (arms[index], arms[(index + 1) % len(arms)])
                for index in range(len(arms))
            )
        for first_arm, second_arm in adjacent_pairs:
            if _emit_corner_pair(geo, first_arm, second_arm, crossing, crossing_id, next_corner_id, radius, lines, attrs):
                emitted += 1
                next_corner_id += 1
    if emitted == 0:
        node.addWarning("road_corner_extract found crossings, but no extraction arm exceeded the minimum length.")


build()
