from __future__ import annotations

import json
import math
import os
from pathlib import Path
import sys

import hou


ROOT = Path(__file__).resolve().parent
SOURCE_HIP = ROOT / "RoadGenerator_with_tangent_circles.hip"
FALLBACK_HIP = ROOT / "RoadGenerator.hip"
OUTPUT_HIP = ROOT / "RoadGenerator_with_tangent_arcs.hip"
POINT_LOG = ROOT / "tangent_arc_point_log.json"
PREVIEW_PNG = ROOT / "tangent_arc_preview.png"


PYTHON_SOP_CODE = r'''
import json
import math

node = hou.pwd()
geo = node.geometry()
input_node = node.inputs()[0] if node.inputs() else None
if input_node is None:
    raise hou.NodeError("Connect this Python SOP to /obj/geo1/blast1.")

src_geo = input_node.geometry()
geo.clear()
geo.merge(src_geo)

ARC_SEGMENTS = 24
ARC_COLOR = (1.0, 0.82, 0.18)
TANGENT_COLOR_A = (0.1, 0.9, 1.0)
TANGENT_COLOR_B = (1.0, 0.25, 0.2)
MIN_TOUCH_DISTANCE = 1.2
MAX_TOUCH_FRACTION = 0.86
TOUCH_FRACTION = 0.72


def p2(point):
    pos = point.position()
    return (float(pos.x()), float(pos.z()))


def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def mul(a, s):
    return (a[0] * s, a[1] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def length(a):
    return math.sqrt(max(0.0, dot(a, a)))


def norm(a):
    l = length(a)
    return (a[0] / l, a[1] / l) if l > 1e-9 else (1.0, 0.0)


def perp_l(a):
    return (-a[1], a[0])


def perp_r(a):
    return (a[1], -a[0])


def angle(v):
    return math.atan2(v[1], v[0])


def same(a, b, tol=1e-2):
    return length(sub(a, b)) <= tol


def angle_diff(a, b):
    d = b - a
    while d <= 0.0:
        d += math.tau
    while d > math.tau:
        d -= math.tau
    return d


def line_intersection(p, n, q, m):
    den = cross(n, m)
    if abs(den) < 1e-7:
        return None
    pq = sub(q, p)
    t = cross(pq, m) / den
    u = cross(pq, n) / den
    return add(p, mul(n, t)), t, u


def sample_branch(branch, s):
    pts = branch["pts"]
    cum = branch["cum"]
    if s <= 0.0:
        return pts[0], norm(sub(pts[1], pts[0]))
    if s >= cum[-1]:
        return pts[-1], norm(sub(pts[-1], pts[-2]))
    for i in range(len(cum) - 1):
        if cum[i] <= s <= cum[i + 1]:
            span = cum[i + 1] - cum[i]
            t = (s - cum[i]) / span if span > 1e-9 else 0.0
            p = add(pts[i], mul(sub(pts[i + 1], pts[i]), t))
            return p, norm(sub(pts[i + 1], pts[i]))
    return pts[-1], norm(sub(pts[-1], pts[-2]))


def shortest_delta(a0, a1):
    d = a1 - a0
    while d <= -math.pi:
        d += math.tau
    while d > math.pi:
        d -= math.tau
    return d


endpoints = []
for prim in src_geo.prims():
    pts = prim.points()
    if len(pts) >= 2 and not prim.isClosed():
        endpoints.append(p2(pts[0]))
        endpoints.append(p2(pts[-1]))

if not endpoints:
    raise hou.NodeError("No open curve branch endpoints found.")

crossing = endpoints[0]
best_hits = 0
for candidate in endpoints:
    hits = sum(1 for other in endpoints if same(candidate, other))
    if hits > best_hits:
        crossing = candidate
        best_hits = hits

branches = []
for prim in src_geo.prims():
    pts = prim.points()
    if len(pts) < 2 or prim.isClosed():
        continue
    coords = [p2(p) for p in pts]
    if length(sub(coords[-1], crossing)) < length(sub(coords[0], crossing)):
        coords.reverse()
    if length(sub(coords[0], crossing)) > 1e-2:
        coords.insert(0, crossing)

    cum = [0.0]
    for a, b in zip(coords, coords[1:]):
        cum.append(cum[-1] + length(sub(b, a)))
    if cum[-1] <= 1e-5:
        continue

    direction = norm(sub(coords[1], coords[0]))
    branches.append(
        {
            "prim": prim.number(),
            "pts": coords,
            "cum": cum,
            "length": cum[-1],
            "dir": direction,
            "angle": angle(direction),
        }
    )

if len(branches) < 4:
    raise hou.NodeError("Expected four branches around the crossing, found %d." % len(branches))

branches.sort(key=lambda branch: branch["angle"])
branches = branches[:4]


def solve_pair(branch_a, branch_b):
    theta = angle_diff(branch_a["angle"], branch_b["angle"])
    mid_angle = branch_a["angle"] + theta * 0.5
    mid = (math.cos(mid_angle), math.sin(mid_angle))
    min_len = min(branch_a["length"], branch_b["length"])
    s = max(MIN_TOUCH_DISTANCE, min(min_len * TOUCH_FRACTION, min_len * MAX_TOUCH_FRACTION))
    p_a, _ = sample_branch(branch_a, s)
    p_b, _ = sample_branch(branch_b, s)

    # Place the circle center on the sector bisector and choose the point on that
    # ray that is equidistant from the two sampled branch points. This keeps the
    # arc visually in the desired lobe while the two endpoints stay on the input
    # curves at the same branch distance from the crossing.
    q = sub(p_b, p_a)
    denom = 2.0 * dot(mid, q)
    numerator = dot(p_b, p_b) - dot(p_a, p_a) - 2.0 * dot(crossing, q)
    if abs(denom) > 1e-7:
        t = numerator / denom
    else:
        t = -1.0

    if t > 0.0:
        circle_center = add(crossing, mul(mid, t))
        radius = length(sub(circle_center, p_a))
        rel = abs(length(sub(circle_center, p_a)) - length(sub(circle_center, p_b))) / max(radius, 1e-6)
        return (0.0, circle_center, radius, p_a, p_b, s, rel, branch_a["prim"], branch_b["prim"])

    # Straight-ray fallback for near-symmetric branch endpoints.
    half = max(0.18, theta * 0.5)
    radius = max(0.1, s * math.tan(half))
    center_distance = s / max(0.18, math.cos(half))
    circle_center = add(crossing, mul(mid, center_distance))
    return (0.0, circle_center, radius, p_a, p_b, s, 0.0, branch_a["prim"], branch_b["prim"])


if geo.findPointAttrib("Cd") is None:
    geo.addAttrib(hou.attribType.Point, "Cd", (1.0, 1.0, 1.0))
if geo.findPointAttrib("arc_id") is None:
    geo.addAttrib(hou.attribType.Point, "arc_id", -1)
if geo.findPointAttrib("arc_role") is None:
    geo.addAttrib(hou.attribType.Point, "arc_role", "")
if geo.findPrimAttrib("arc_id") is None:
    geo.addAttrib(hou.attribType.Prim, "arc_id", -1)
if geo.findPrimAttrib("circle_radius") is None:
    geo.addAttrib(hou.attribType.Prim, "circle_radius", 0.0)
if geo.findPrimAttrib("tangent_branch_pair") is None:
    geo.addAttrib(hou.attribType.Prim, "tangent_branch_pair", "")
if geo.findGlobalAttrib("mcp_tangent_arc_log") is None:
    geo.addAttrib(hou.attribType.Global, "mcp_tangent_arc_log", "")

arc_group = geo.findPrimGroup("mcp_tangent_arcs") or geo.createPrimGroup("mcp_tangent_arcs")
touch_group = geo.findPointGroup("mcp_tangent_points") or geo.createPointGroup("mcp_tangent_points")
center_y = src_geo.boundingBox().center().y()
arc_logs = []

for arc_id, branch_a in enumerate(branches):
    branch_b = branches[(arc_id + 1) % len(branches)]
    _, circle_center, radius, p_a, p_b, s, rel, prim_a, prim_b = solve_pair(branch_a, branch_b)

    a0 = math.atan2(p_a[1] - circle_center[1], p_a[0] - circle_center[0])
    a1 = math.atan2(p_b[1] - circle_center[1], p_b[0] - circle_center[0])
    delta = shortest_delta(a0, a1)

    poly = geo.createPolygon()
    poly.setIsClosed(False)
    for seg in range(ARC_SEGMENTS + 1):
        t = seg / float(ARC_SEGMENTS)
        a = a0 + delta * t
        x = circle_center[0] + math.cos(a) * radius
        z = circle_center[1] + math.sin(a) * radius
        if seg == 0:
            x, z = p_a
        elif seg == ARC_SEGMENTS:
            x, z = p_b
        pt = geo.createPoint()
        pt.setPosition(hou.Vector3(x, center_y, z))
        pt.setAttribValue("Cd", ARC_COLOR)
        pt.setAttribValue("arc_id", arc_id)
        pt.setAttribValue("arc_role", "arc")
        poly.addVertex(pt)
        if seg == 0 or seg == ARC_SEGMENTS:
            touch_group.add(pt)
            pt.setAttribValue("Cd", TANGENT_COLOR_A if seg == 0 else TANGENT_COLOR_B)
            pt.setAttribValue("arc_role", "tangent_a" if seg == 0 else "tangent_b")

    poly.setAttribValue("arc_id", arc_id)
    poly.setAttribValue("circle_radius", float(radius))
    poly.setAttribValue("tangent_branch_pair", "%d,%d" % (prim_a, prim_b))
    arc_group.add(poly)

    arc_logs.append(
        {
            "arc_id": arc_id,
            "branch_pair": [int(prim_a), int(prim_b)],
            "crossing_center_xz": [round(crossing[0], 6), round(crossing[1], 6)],
            "circle_center_xz": [round(circle_center[0], 6), round(circle_center[1], 6)],
            "circle_radius": round(radius, 6),
            "tangent_a_xz": [round(p_a[0], 6), round(p_a[1], 6)],
            "tangent_b_xz": [round(p_b[0], 6), round(p_b[1], 6)],
            "equal_branch_distance_from_crossing": round(s, 6),
            "euclidean_distance_a_from_crossing": round(length(sub(p_a, crossing)), 6),
            "euclidean_distance_b_from_crossing": round(length(sub(p_b, crossing)), 6),
            "radius_balance_error": round(rel, 6),
            "shortest_arc_angle_degrees": round(abs(delta) * 180.0 / math.pi, 6),
            "arc_point_count": ARC_SEGMENTS + 1,
        }
    )

geo.setGlobalAttribValue("mcp_tangent_arc_log", json.dumps(arc_logs, ensure_ascii=False, indent=2))
'''


def _draw_preview(log_data: list[dict], source_node: hou.Node) -> None:
    from PIL import Image, ImageDraw

    src_geo = source_node.geometry()
    polylines: list[list[tuple[float, float]]] = []
    all_points: list[tuple[float, float]] = []
    for prim in src_geo.prims():
        pts = [(float(p.position().x()), float(p.position().z())) for p in prim.points()]
        if pts:
            polylines.append(pts)
            all_points.extend(pts)

    arc_lines: list[list[tuple[float, float]]] = []
    arc_node = hou.node("/obj/geo1/find_4_tangent_circles_py")
    arc_geo = arc_node.geometry()
    arc_group = arc_geo.findPrimGroup("mcp_tangent_arcs")
    if arc_group:
        for prim in arc_group.prims():
            pts = [(float(p.position().x()), float(p.position().z())) for p in prim.points()]
            arc_lines.append(pts)
            all_points.extend(pts)

    for item in log_data:
        all_points.append(tuple(item["tangent_a_xz"]))
        all_points.append(tuple(item["tangent_b_xz"]))
        all_points.append(tuple(item["circle_center_xz"]))

    min_x = min(p[0] for p in all_points)
    max_x = max(p[0] for p in all_points)
    min_z = min(p[1] for p in all_points)
    max_z = max(p[1] for p in all_points)
    pad = 4.0
    min_x -= pad
    max_x += pad
    min_z -= pad
    max_z += pad

    width, height = 1400, 950
    scale = min(width / max(max_x - min_x, 1e-6), height / max(max_z - min_z, 1e-6))
    ox = (width - (max_x - min_x) * scale) * 0.5
    oy = (height - (max_z - min_z) * scale) * 0.5

    def tx(p: tuple[float, float]) -> tuple[int, int]:
        x = ox + (p[0] - min_x) * scale
        y = height - (oy + (p[1] - min_z) * scale)
        return int(round(x)), int(round(y))

    img = Image.new("RGB", (width, height), (219, 230, 232))
    draw = ImageDraw.Draw(img)

    # Grid.
    grid_step = 5.0
    gx = math.floor(min_x / grid_step) * grid_step
    while gx <= max_x:
        x0, _ = tx((gx, min_z))
        draw.line([(x0, 0), (x0, height)], fill=(196, 208, 211), width=1)
        gx += grid_step
    gz = math.floor(min_z / grid_step) * grid_step
    while gz <= max_z:
        _, y0 = tx((min_x, gz))
        draw.line([(0, y0), (width, y0)], fill=(196, 208, 211), width=1)
        gz += grid_step

    for pts in polylines:
        if len(pts) > 1:
            draw.line([tx(p) for p in pts], fill=(35, 56, 162), width=3)
            for p in pts:
                x, y = tx(p)
                draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(20, 30, 160))

    colors = [(245, 180, 20), (230, 95, 35), (70, 170, 75), (125, 80, 220)]
    for idx, pts in enumerate(arc_lines):
        if len(pts) > 1:
            draw.line([tx(p) for p in pts], fill=colors[idx % len(colors)], width=6)

    for item in log_data:
        c = tuple(item["circle_center_xz"])
        a = tuple(item["tangent_a_xz"])
        b = tuple(item["tangent_b_xz"])
        cx, cy = tx(c)
        draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(60, 60, 60))
        for p, fill in [(a, (0, 210, 255)), (b, (255, 55, 55))]:
            x, y = tx(p)
            draw.ellipse([x - 7, y - 7, x + 7, y + 7], fill=fill, outline=(30, 30, 30), width=1)
        label_pos = tx(c)
        draw.text((label_pos[0] + 8, label_pos[1] - 16), f"arc {item['arc_id']}", fill=(20, 20, 20))

    img.save(PREVIEW_PNG)


def main() -> None:
    source = SOURCE_HIP if SOURCE_HIP.exists() else FALLBACK_HIP
    hou.hipFile.load(str(source).replace("\\", "/"), suppress_save_prompt=True)

    parent = hou.node("/obj/geo1")
    source_node = hou.node("/obj/geo1/blast1")
    if parent is None or source_node is None:
        raise RuntimeError("Missing /obj/geo1 or /obj/geo1/blast1.")

    node = hou.node("/obj/geo1/find_4_tangent_circles_py")
    if node is None:
        node = parent.createNode("python", "find_4_tangent_circles_py")
    node.setInput(0, source_node, 0)
    parm = node.parm("python") or node.parm("code")
    if parm is None:
        raise RuntimeError("Python SOP code parameter not found.")
    parm.set(PYTHON_SOP_CODE)
    node.setDisplayFlag(True)
    node.setRenderFlag(True)
    node.moveToGoodPosition()
    node.cook(force=True)

    out_geo = node.geometry()
    arc_group = out_geo.findPrimGroup("mcp_tangent_arcs")
    touch_group = out_geo.findPointGroup("mcp_tangent_points")
    log_text = out_geo.attribValue("mcp_tangent_arc_log")
    log_data = json.loads(log_text)

    POINT_LOG.write_text(json.dumps(log_data, ensure_ascii=False, indent=2), encoding="utf-8")
    _draw_preview(log_data, source_node)
    hou.hipFile.save(str(OUTPUT_HIP).replace("\\", "/"))

    print("source", source)
    print("saved", OUTPUT_HIP)
    print("point_log", POINT_LOG)
    print("preview_png", PREVIEW_PNG)
    print("arc_prims", len(arc_group.prims()) if arc_group else 0)
    print("tangent_points", len(touch_group.points()) if touch_group else 0)
    for item in log_data:
        print(
            "arc",
            item["arc_id"],
            "pair",
            item["branch_pair"],
            "radius",
            item["circle_radius"],
            "equal_distance",
            item["equal_branch_distance_from_crossing"],
            "tangent_a",
            item["tangent_a_xz"],
            "tangent_b",
            item["tangent_b_xz"],
        )


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
