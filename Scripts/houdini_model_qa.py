"""
Houdini model QA for VirtualCity.

This script inspects the cooked Houdini SOP graph through RPYC and writes a
structured report under Reports/model_qa.  The default quick mode is intended
to run after every recook; full mode scans larger point sets for pre-commit or
manual review.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import rpyc

from vc_paths import ROOT, load_active_area, project_relative


REPORT_DIR = ROOT / "Reports" / "model_qa"
PASS = "pass"
WARN = "warn"
FAIL = "fail"
INFO = "info"

REMOTE_HELPERS = r'''
import hou, json, math

def _vc_model_qa_percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    idx = int(round((len(values) - 1) * q))
    idx = max(0, min(idx, len(values) - 1))
    return values[idx]

def _vc_model_qa_limited(items, max_items):
    if max_items is None or len(items) <= max_items:
        return items
    step = max(1, int(math.ceil(float(len(items)) / float(max_items))))
    return items[::step]

def _vc_model_qa_terrain_delta(node_path, terrain_path, max_points, threshold):
    node = hou.node(node_path)
    terrain = hou.node(terrain_path)
    if node is None or terrain is None:
        return json.dumps({"missing": True, "node": node_path, "terrain": terrain_path})
    geo = node.geometry()
    terrain_geo = terrain.geometry()
    pts = _vc_model_qa_limited(list(geo.points()), max_points)
    deltas = []
    misses = 0
    for point in pts:
        p = point.position()
        hit_pos = hou.Vector3()
        hit_normal = hou.Vector3()
        hit_uvw = hou.Vector3()
        hit = terrain_geo.intersect(
            hou.Vector3(p.x(), 10000.0, p.z()),
            hou.Vector3(0.0, -1.0, 0.0),
            hit_pos,
            hit_normal,
            hit_uvw,
            min_hit=0.01,
            max_hit=20000.0,
            tolerance=0.01,
        )
        if hit >= 0:
            deltas.append(float(p.y()) - float(hit_pos.y()))
        else:
            misses += 1
    result = {
        "missing": False,
        "node": node_path,
        "terrain": terrain_path,
        "sampled_points": len(pts),
        "misses": misses,
        "min_delta": min(deltas) if deltas else None,
        "p05_delta": _vc_model_qa_percentile(deltas, 0.05),
        "p50_delta": _vc_model_qa_percentile(deltas, 0.50),
        "p95_delta": _vc_model_qa_percentile(deltas, 0.95),
        "below_threshold": sum(1 for d in deltas if d < threshold),
        "threshold": threshold,
    }
    return json.dumps(result)

def _vc_model_qa_road_faces(node_path):
    node = hou.node(node_path)
    if node is None:
        return json.dumps({"missing": True, "node": node_path})
    geo = node.geometry()

    def area_xz(prim):
        verts = prim.vertices()
        if len(verts) < 3:
            return 0.0
        acc = 0.0
        pts = [v.point().position() for v in verts]
        for i, p in enumerate(pts):
            q = pts[(i + 1) % len(pts)]
            acc += p.x() * q.z() - q.x() * p.z()
        return abs(acc) * 0.5

    open_prims = 0
    max_vertices = 0
    max_area = 0.0
    area_warn = 750.0
    area_fail = 5000.0
    large_warn = 0
    large_fail = 0
    too_many_vertices = 0
    for prim in geo.prims():
        verts = len(prim.vertices())
        max_vertices = max(max_vertices, verts)
        try:
            if not prim.isClosed():
                open_prims += 1
        except Exception:
            pass
        area = area_xz(prim)
        max_area = max(max_area, area)
        if area > area_warn:
            large_warn += 1
        if area > area_fail:
            large_fail += 1
        if verts > 64:
            too_many_vertices += 1
    return json.dumps({
        "missing": False,
        "prims": int(geo.intrinsicValue("primitivecount")),
        "open_prims": open_prims,
        "max_vertices": max_vertices,
        "max_area_xz": max_area,
        "area_warn_threshold": area_warn,
        "area_fail_threshold": area_fail,
        "large_area_warn_count": large_warn,
        "large_area_fail_count": large_fail,
        "too_many_vertices_count": too_many_vertices,
    })

def _vc_model_qa_building_bundle(obj_path):
    def node(name):
        return hou.node(obj_path.rstrip("/") + "/" + name)

    def vec_len(v):
        return math.sqrt(sum(x * x for x in v))

    def vec_norm(v):
        l = vec_len(v)
        if l <= 1e-9:
            return (0.0, 0.0, 0.0)
        return (v[0] / l, v[1] / l, v[2] / l)

    def vec_dot(a, b):
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

    def pos3(p):
        return (float(p.x()), float(p.y()), float(p.z()))

    def xz_dist(a, b):
        return math.hypot(a[0] - b[0], a[2] - b[2])

    def grid_key(p, cell):
        return (int(math.floor(p[0] / cell)), int(math.floor(p[2] / cell)))

    def build_xz_grid(items, cell):
        grid = {}
        for item in items:
            p = item[0]
            key = grid_key(p, cell)
            grid.setdefault(key, []).append(item)
        return grid

    def iter_xz_grid(grid, p, cell, radius):
        cx, cz = grid_key(p, cell)
        for dz in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                for item in grid.get((cx + dx, cz + dz), ()):
                    yield item

    def prim_normal(prim):
        n = prim.normal()
        return (float(n.x()), float(n.y()), float(n.z()))

    def prim_center(prim):
        pts = [v.point().position() for v in prim.vertices()]
        if not pts:
            return (0.0, 0.0, 0.0)
        return (
            sum(p.x() for p in pts) / len(pts),
            sum(p.y() for p in pts) / len(pts),
            sum(p.z() for p in pts) / len(pts),
        )

    def percentile(values, q):
        if not values:
            return None
        values = sorted(values)
        idx = int(round((len(values) - 1) * q))
        idx = max(0, min(idx, len(values) - 1))
        return values[idx]

    def unique_cd(name):
        n = node(name)
        if n is None:
            return []
        geo = n.geometry()
        if not geo.findPointAttrib("Cd"):
            return []
        vals = []
        seen = set()
        for point in geo.points():
            cd = tuple(round(float(x), 4) for x in point.attribValue("Cd"))
            if cd not in seen:
                vals.append(cd)
                seen.add(cd)
            if len(vals) >= 8:
                break
        return vals

    def avg_stored_normal(prim, geo):
        if geo.findVertexAttrib("N"):
            vals = []
            for vert in prim.vertices():
                try:
                    vals.append(tuple(float(x) for x in vert.attribValue("N")))
                except Exception:
                    pass
            if vals:
                return vec_norm(tuple(sum(v[i] for v in vals) / len(vals) for i in range(3)))
        if geo.findPointAttrib("N"):
            vals = []
            for point in prim.points():
                try:
                    vals.append(tuple(float(x) for x in point.attribValue("N")))
                except Exception:
                    pass
            if vals:
                return vec_norm(tuple(sum(v[i] for v in vals) / len(vals) for i in range(3)))
        if geo.findPrimAttrib("N"):
            try:
                return vec_norm(tuple(float(x) for x in prim.attribValue("N")))
            except Exception:
                return None
        return None

    result = {"missing_nodes": []}

    # Colors
    result["building_colors"] = {
        "bld_color": unique_cd("bld_color"),
        "bld_foundation_color": unique_cd("bld_foundation_color"),
        "bld_with_foundation": unique_cd("bld_with_foundation"),
    }

    # Footprint bevel
    bevel_node = node("bld_footprint_bevel")
    if bevel_node is None:
        result["missing_nodes"].append("bld_footprint_bevel")
        result["footprint_bevel"] = {"missing": True}
    else:
        geo = bevel_node.geometry()
        bevel_attr = geo.findPrimAttrib("footprint_bevel_count")
        total = 0
        buildings = 0
        short_edges = 0
        min_edge = None
        short_threshold = 0.08
        if bevel_attr is not None:
            for prim in geo.prims():
                count = int(prim.attribValue(bevel_attr))
                total += count
                if count > 0:
                    buildings += 1
                pts = [pos3(v.point().position()) for v in prim.vertices()]
                if len(pts) < 2:
                    continue
                for i, p in enumerate(pts):
                    q = pts[(i + 1) % len(pts)]
                    edge_len = xz_dist(p, q)
                    min_edge = edge_len if min_edge is None else min(min_edge, edge_len)
                    if edge_len < short_threshold:
                        short_edges += 1
        result["footprint_bevel"] = {
            "missing": False,
            "has_attr": bevel_attr is not None,
            "prims": int(geo.intrinsicValue("primitivecount")),
            "points": int(geo.intrinsicValue("pointcount")),
            "beveled_buildings": buildings,
            "total_beveled_corners": total,
            "min_edge": min_edge,
            "short_edges": short_edges,
            "short_threshold": short_threshold,
        }

    final_node = node("bld_with_foundation")
    body_node = node("bld_color")
    foundation_node = node("bld_foundation_color")
    if final_node is None:
        result["missing_nodes"].append("bld_with_foundation")
        return json.dumps(result)
    final_geo = final_node.geometry()
    body_geo = body_node.geometry() if body_node else None
    foundation_geo = foundation_node.geometry() if foundation_node else None

    # Normals
    has_n = bool(final_geo.findVertexAttrib("N") or final_geo.findPointAttrib("N") or final_geo.findPrimAttrib("N"))
    missing = zero = mismatch = degenerate = 0
    up = side = down = 0
    if has_n:
        for prim in final_geo.prims():
            face_n = prim_normal(prim)
            if vec_len(face_n) < 0.5:
                degenerate += 1
            elif face_n[1] > 0.65:
                up += 1
            elif face_n[1] < -0.65:
                down += 1
            else:
                side += 1
            stored = avg_stored_normal(prim, final_geo)
            if stored is None:
                missing += 1
            elif vec_len(stored) < 0.1:
                zero += 1
            elif vec_dot(vec_norm(face_n), stored) < 0.8:
                mismatch += 1
    result["building_normals"] = {
        "has_n": has_n,
        "prims": int(final_geo.intrinsicValue("primitivecount")),
        "up": up,
        "side": side,
        "down": down,
        "degenerate": degenerate,
        "storedN_missing": missing,
        "storedN_zero": zero,
        "storedN_mismatch": mismatch,
    }

    # Foundation tags, normals, and top-edge alignment.
    tag_attr = final_geo.findPrimAttrib("is_foundation")
    vals = [prim.attribValue(tag_attr) for prim in final_geo.prims()] if tag_attr else []
    body_count = int(body_geo.intrinsicValue("primitivecount")) if body_geo else 0
    foundation_count = int(foundation_geo.intrinsicValue("primitivecount")) if foundation_geo else 0
    result["foundation_tags"] = {
        "has_attr": tag_attr is not None,
        "body_expected": body_count,
        "foundation_expected": foundation_count,
        "tag_0": sum(1 for v in vals if v == 0),
        "tag_1": sum(1 for v in vals if v == 1),
        "other": sum(1 for v in vals if v not in (0, 1)),
    }

    body_sides = []
    foundation_sides = []
    body_bottom = []
    foundation_top = []
    if tag_attr is not None:
        for prim in final_geo.prims():
            face_n = prim_normal(prim)
            if abs(face_n[1]) >= 0.2:
                continue
            points = [pos3(v.point().position()) for v in prim.vertices()]
            is_foundation = prim.attribValue(tag_attr) == 1
            row = (prim_center(prim), face_n)
            if is_foundation:
                foundation_sides.append(row)
                max_y = max(p[1] for p in points)
                foundation_top.extend(p for p in points if abs(p[1] - max_y) <= 0.01)
            else:
                body_sides.append(row)
                min_y = min(p[1] for p in points)
                body_bottom.extend(p for p in points if abs(p[1] - min_y) <= 0.01)

    no_near = normal_mismatch = aligned = 0
    worst_dot = 1.0
    match_radius = 0.35
    body_side_grid = build_xz_grid(body_sides, match_radius) if body_sides else {}
    for f_center, f_normal in foundation_sides:
        candidates = []
        for b_center, b_normal in iter_xz_grid(body_side_grid, f_center, match_radius, 1):
            if xz_dist(f_center, b_center) <= match_radius:
                candidates.append(vec_dot(f_normal, b_normal))
        if not candidates:
            no_near += 1
            continue
        best = max(candidates)
        worst_dot = min(worst_dot, best)
        if best > 0.8:
            aligned += 1
        else:
            normal_mismatch += 1
    result["foundation_normals"] = {
        "body_side_count": len(body_sides),
        "foundation_side_count": len(foundation_sides),
        "aligned": aligned,
        "mismatch": normal_mismatch,
        "no_near_match": no_near,
        "worst_best_dot": worst_dot,
        "match_radius_m": match_radius,
    }

    distances = []
    align_search_radius = 0.05
    body_bottom_grid = build_xz_grid([(p,) for p in body_bottom], align_search_radius) if body_bottom else {}
    for p in foundation_top:
        if body_bottom_grid:
            candidates = [item[0] for item in iter_xz_grid(body_bottom_grid, p, align_search_radius, 1)]
            if not candidates:
                candidates = [item[0] for item in iter_xz_grid(body_bottom_grid, p, align_search_radius, 2)]
            if candidates:
                distances.append(min(xz_dist(p, q) for q in candidates))
    distances.sort()
    align_threshold = 0.005
    result["foundation_alignment"] = {
        "foundation_top_points": len(foundation_top),
        "body_bottom_points": len(body_bottom),
        "max_distance": max(distances) if distances else None,
        "p95_distance": percentile(distances, 0.95),
        "over_threshold": sum(1 for d in distances if d > align_threshold),
        "threshold_m": align_threshold,
    }

    return json.dumps(result)
'''


def now_stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def vec_len(v: tuple[float, float, float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def vec_norm(v: tuple[float, float, float]) -> tuple[float, float, float]:
    length = vec_len(v)
    if length <= 1e-9:
        return (0.0, 0.0, 0.0)
    return (v[0] / length, v[1] / length, v[2] / length)


def vec_dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def xz_dist(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.hypot(a[0] - b[0], a[2] - b[2])


def pos3(p: Any) -> tuple[float, float, float]:
    return (float(p[0]), float(p[1]), float(p[2]))


def prim_center(prim: Any) -> tuple[float, float, float]:
    pts = [v.point().position() for v in prim.vertices()]
    if not pts:
        return (0.0, 0.0, 0.0)
    return (
        sum(p.x() for p in pts) / len(pts),
        sum(p.y() for p in pts) / len(pts),
        sum(p.z() for p in pts) / len(pts),
    )


def prim_normal(prim: Any) -> tuple[float, float, float]:
    n = prim.normal()
    return (float(n.x()), float(n.y()), float(n.z()))


def polygon_area_xz(prim: Any) -> float:
    pts = [v.point().position() for v in prim.vertices()]
    if len(pts) < 3:
        return 0.0
    acc = 0.0
    for i, p in enumerate(pts):
        q = pts[(i + 1) % len(pts)]
        acc += p.x() * q.z() - q.x() * p.z()
    return abs(acc) * 0.5


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    data = sorted(values)
    idx = int(round((len(data) - 1) * q))
    return data[max(0, min(idx, len(data) - 1))]


def limited(items: list[Any], max_items: int | None) -> list[Any]:
    if max_items is None or len(items) <= max_items:
        return items
    step = max(1, math.ceil(len(items) / max_items))
    return items[::step]


def avg_stored_normal(prim: Any, geo: Any) -> tuple[float, float, float] | None:
    if geo.findVertexAttrib("N"):
        vals = []
        for vert in prim.vertices():
            try:
                vals.append(tuple(float(x) for x in vert.attribValue("N")))
            except Exception:
                pass
        if vals:
            return vec_norm(tuple(sum(v[i] for v in vals) / len(vals) for i in range(3)))
    if geo.findPointAttrib("N"):
        vals = []
        for point in prim.points():
            try:
                vals.append(tuple(float(x) for x in point.attribValue("N")))
            except Exception:
                pass
        if vals:
            return vec_norm(tuple(sum(v[i] for v in vals) / len(vals) for i in range(3)))
    if geo.findPrimAttrib("N"):
        try:
            return vec_norm(tuple(float(x) for x in prim.attribValue("N")))
        except Exception:
            return None
    return None


class QA:
    def __init__(self, conn: Any, hou: Any, obj_path: str, mode: str):
        self.conn = conn
        self.hou = hou
        self.obj_path = obj_path.rstrip("/")
        self.mode = mode
        self.max_points = None if mode == "full" else 3000
        self.checks: list[dict[str, Any]] = []
        self.metrics: dict[str, Any] = {}

    def add(self, name: str, status: str, message: str, **details: Any) -> None:
        self.checks.append(
            {
                "name": name,
                "status": status,
                "message": message,
                "details": details,
            }
        )

    def node(self, name: str) -> Any:
        return self.hou.node(f"{self.obj_path}/{name}")

    def geo(self, name: str) -> Any | None:
        node = self.node(name)
        if node is None:
            return None
        return node.geometry()

    def terrain_y_at(self, terrain_geo: Any, x: float, z: float) -> float | None:
        pos = self.hou.Vector3()
        normal = self.hou.Vector3()
        uvw = self.hou.Vector3()
        hit = terrain_geo.intersect(
            self.hou.Vector3(x, 10000.0, z),
            self.hou.Vector3(0.0, -1.0, 0.0),
            pos,
            normal,
            uvw,
            min_hit=0.01,
            max_hit=20000.0,
            tolerance=0.01,
        )
        if hit >= 0:
            return float(pos.y())
        return None

    def check_required_nodes(self) -> None:
        required = [
            "dem_subdivide",
            "bld_footprint_bevel",
            "bld_with_foundation",
            "road_strips",
            "road_clipped",
            "road_extrude",
            "merge_all",
            "OUT_city",
        ]
        counts = {}
        for name in required:
            node = self.node(name)
            if node is None:
                self.add("node_exists", FAIL, f"{name} is missing", node=name)
                counts[name] = None
                continue
            geo = node.geometry()
            pts = int(geo.intrinsicValue("pointcount"))
            prims = int(geo.intrinsicValue("primitivecount"))
            counts[name] = {"points": pts, "prims": prims}
            if pts <= 0 or prims <= 0:
                self.add("node_nonempty", FAIL, f"{name} has empty geometry", node=name, points=pts, prims=prims)
        self.metrics["node_counts"] = counts
        if not any(c["status"] == FAIL and c["name"] in {"node_exists", "node_nonempty"} for c in self.checks):
            self.add("required_nodes", PASS, "required SOP nodes exist and are non-empty")

    def unique_cd(self, name: str) -> list[tuple[float, float, float]]:
        geo = self.geo(name)
        if geo is None or not geo.findPointAttrib("Cd"):
            return []
        vals: list[tuple[float, float, float]] = []
        seen = set()
        for point in geo.points():
            cd = tuple(round(float(x), 4) for x in point.attribValue("Cd"))
            if cd not in seen:
                vals.append(cd)
                seen.add(cd)
            if len(vals) >= 8:
                break
        return vals

    def check_building_color(self) -> None:
        body_cd = self.unique_cd("bld_color")
        foundation_cd = self.unique_cd("bld_foundation_color")
        final_cd = self.unique_cd("bld_with_foundation")
        self.metrics["building_colors"] = {
            "bld_color": body_cd,
            "bld_foundation_color": foundation_cd,
            "bld_with_foundation": final_cd,
        }
        if not body_cd:
            self.add("building_color", FAIL, "bld_color has no Cd attribute")
            return
        if not foundation_cd:
            self.add("foundation_color", WARN, "bld_foundation_color is missing or has no Cd")
            return
        if body_cd != foundation_cd:
            self.add("foundation_color_match", FAIL, "foundation Cd differs from building Cd", body_cd=body_cd, foundation_cd=foundation_cd)
        elif final_cd and final_cd != body_cd:
            self.add("building_final_color", FAIL, "final building Cd differs from source building Cd", body_cd=body_cd, final_cd=final_cd)
        else:
            self.add("building_color", PASS, "building body and foundation colors match", cd=body_cd)

    def check_building_normals(self) -> None:
        geo = self.geo("bld_with_foundation")
        if geo is None:
            self.add("building_normals", FAIL, "bld_with_foundation is missing")
            return
        has_n = bool(geo.findVertexAttrib("N") or geo.findPointAttrib("N") or geo.findPrimAttrib("N"))
        if not has_n:
            self.add("building_normals", FAIL, "bld_with_foundation has no N attribute")
            return

        missing = zero = mismatch = degenerate = 0
        up = side = down = 0
        for prim in geo.prims():
            face_n = prim_normal(prim)
            if vec_len(face_n) < 0.5:
                degenerate += 1
            elif face_n[1] > 0.65:
                up += 1
            elif face_n[1] < -0.65:
                down += 1
            else:
                side += 1

            stored = avg_stored_normal(prim, geo)
            if stored is None:
                missing += 1
            elif vec_len(stored) < 0.1:
                zero += 1
            elif vec_dot(vec_norm(face_n), stored) < 0.8:
                mismatch += 1

        detail = {
            "prims": int(geo.intrinsicValue("primitivecount")),
            "up": up,
            "side": side,
            "down": down,
            "degenerate": degenerate,
            "storedN_missing": missing,
            "storedN_zero": zero,
            "storedN_mismatch": mismatch,
        }
        self.metrics["building_normals"] = detail
        if missing or zero or mismatch or degenerate:
            self.add("building_normals", FAIL, "building final normals are invalid", **detail)
        else:
            self.add("building_normals", PASS, "building final normals are valid", **detail)

    def check_footprint_bevel(self) -> None:
        geo = self.geo("bld_footprint_bevel")
        if geo is None:
            self.add("footprint_bevel", FAIL, "bld_footprint_bevel is missing")
            return
        bevel_attr = geo.findPrimAttrib("footprint_bevel_count")
        if bevel_attr is None:
            self.add("footprint_bevel", FAIL, "bld_footprint_bevel lacks footprint_bevel_count")
            return

        total_beveled_corners = 0
        beveled_buildings = 0
        short_edges = 0
        min_edge = None
        short_threshold = 0.08
        for prim in geo.prims():
            count = int(prim.attribValue(bevel_attr))
            total_beveled_corners += count
            if count > 0:
                beveled_buildings += 1
            pts = [pos3(v.point().position()) for v in prim.vertices()]
            if len(pts) < 2:
                continue
            for i, p in enumerate(pts):
                q = pts[(i + 1) % len(pts)]
                edge_len = xz_dist(p, q)
                min_edge = edge_len if min_edge is None else min(min_edge, edge_len)
                if edge_len < short_threshold:
                    short_edges += 1

        detail = {
            "prims": int(geo.intrinsicValue("primitivecount")),
            "points": int(geo.intrinsicValue("pointcount")),
            "beveled_buildings": beveled_buildings,
            "total_beveled_corners": total_beveled_corners,
            "min_edge": min_edge,
            "short_edges": short_edges,
            "short_threshold": short_threshold,
        }
        self.metrics["footprint_bevel"] = detail
        if short_edges:
            self.add("footprint_bevel", FAIL, "footprint bevel produced too-short edges", **detail)
        elif total_beveled_corners <= 0:
            self.add("footprint_bevel", WARN, "no eligible footprint corners were beveled", **detail)
        else:
            self.add("footprint_bevel", PASS, "eligible footprint corners were beveled", **detail)

    def check_foundation_tags_and_normals(self) -> None:
        final_geo = self.geo("bld_with_foundation")
        body_geo = self.geo("bld_color")
        foundation_geo = self.geo("bld_foundation_color")
        if final_geo is None or body_geo is None or foundation_geo is None:
            self.add("foundation_integrity", WARN, "foundation nodes are incomplete")
            return
        if not final_geo.findPrimAttrib("is_foundation"):
            self.add("foundation_tags", FAIL, "final building geometry lacks is_foundation")
            return

        vals = [prim.attribValue("is_foundation") for prim in final_geo.prims()]
        body_count = int(body_geo.intrinsicValue("primitivecount"))
        foundation_count = int(foundation_geo.intrinsicValue("primitivecount"))
        tag_counts = {
            "body_expected": body_count,
            "foundation_expected": foundation_count,
            "tag_0": sum(1 for v in vals if v == 0),
            "tag_1": sum(1 for v in vals if v == 1),
            "other": sum(1 for v in vals if v not in (0, 1)),
        }
        self.metrics["foundation_tags"] = tag_counts
        if tag_counts["tag_0"] != body_count or tag_counts["tag_1"] != foundation_count or tag_counts["other"]:
            self.add("foundation_tags", FAIL, "is_foundation tag counts do not match merged geometry", **tag_counts)
        else:
            self.add("foundation_tags", PASS, "is_foundation tags match body/foundation counts", **tag_counts)

        body_sides = []
        foundation_sides = []
        for prim in final_geo.prims():
            face_n = prim_normal(prim)
            if abs(face_n[1]) >= 0.2:
                continue
            row = (prim, prim_center(prim), face_n)
            if prim.attribValue("is_foundation") == 1:
                foundation_sides.append(row)
            else:
                body_sides.append(row)

        no_near = mismatch = aligned = 0
        worst_dot = 1.0
        match_radius = 0.35
        for _, f_center, f_normal in foundation_sides:
            candidates = [
                vec_dot(f_normal, b_normal)
                for _, b_center, b_normal in body_sides
                if xz_dist(f_center, b_center) <= match_radius
            ]
            if not candidates:
                no_near += 1
                continue
            best = max(candidates)
            worst_dot = min(worst_dot, best)
            if best > 0.8:
                aligned += 1
            else:
                mismatch += 1

        detail = {
            "body_side_count": len(body_sides),
            "foundation_side_count": len(foundation_sides),
            "aligned": aligned,
            "mismatch": mismatch,
            "no_near_match": no_near,
            "worst_best_dot": worst_dot,
            "match_radius_m": match_radius,
        }
        self.metrics["foundation_vs_body_normals"] = detail
        if mismatch:
            self.add("foundation_normals", FAIL, "foundation side normals disagree with nearby building sides", **detail)
        elif no_near:
            self.add("foundation_normals", WARN, "some foundation sides have no nearby building side match", **detail)
        else:
            self.add("foundation_normals", PASS, "foundation side normals align with building sides", **detail)

        body_bottom = []
        foundation_top = []
        for prim in final_geo.prims():
            face_n = prim_normal(prim)
            if abs(face_n[1]) >= 0.2:
                continue
            points = [pos3(v.point().position()) for v in prim.vertices()]
            if prim.attribValue("is_foundation") == 1:
                max_y = max(p[1] for p in points)
                foundation_top.extend(p for p in points if abs(p[1] - max_y) <= 0.01)
            else:
                min_y = min(p[1] for p in points)
                body_bottom.extend(p for p in points if abs(p[1] - min_y) <= 0.01)

        distances = []
        for p in foundation_top:
            if body_bottom:
                distances.append(min(xz_dist(p, q) for q in body_bottom))
        distances.sort()
        align_threshold = 0.005
        align_detail = {
            "foundation_top_points": len(foundation_top),
            "body_bottom_points": len(body_bottom),
            "max_distance": max(distances) if distances else None,
            "p95_distance": percentile(distances, 0.95),
            "over_threshold": sum(1 for d in distances if d > align_threshold),
            "threshold_m": align_threshold,
        }
        self.metrics["foundation_alignment"] = align_detail
        if not foundation_top:
            self.add("foundation_alignment", WARN, "no foundation top points found", **align_detail)
        elif align_detail["over_threshold"]:
            self.add("foundation_alignment", FAIL, "foundation top edge is offset from building bottom edge", **align_detail)
        else:
            self.add("foundation_alignment", PASS, "foundation top edge matches building bottom edge", **align_detail)

    def check_building_bundle(self) -> None:
        bundle = json.loads(self.conn.eval("_vc_model_qa_building_bundle({})".format(json.dumps(self.obj_path))))

        colors = bundle.get("building_colors", {})
        self.metrics["building_colors"] = colors
        body_cd = colors.get("bld_color", [])
        foundation_cd = colors.get("bld_foundation_color", [])
        final_cd = colors.get("bld_with_foundation", [])
        if not body_cd:
            self.add("building_color", FAIL, "bld_color has no Cd attribute")
        elif not foundation_cd:
            self.add("foundation_color", WARN, "bld_foundation_color is missing or has no Cd")
        elif body_cd != foundation_cd:
            self.add("foundation_color_match", FAIL, "foundation Cd differs from building Cd", body_cd=body_cd, foundation_cd=foundation_cd)
        elif final_cd and final_cd != body_cd:
            self.add("building_final_color", FAIL, "final building Cd differs from source building Cd", body_cd=body_cd, final_cd=final_cd)
        else:
            self.add("building_color", PASS, "building body and foundation colors match", cd=body_cd)

        bevel = bundle.get("footprint_bevel", {"missing": True})
        self.metrics["footprint_bevel"] = bevel
        if bevel.get("missing"):
            self.add("footprint_bevel", FAIL, "bld_footprint_bevel is missing", **bevel)
        elif not bevel.get("has_attr"):
            self.add("footprint_bevel", FAIL, "bld_footprint_bevel lacks footprint_bevel_count", **bevel)
        elif bevel.get("short_edges", 0):
            self.add("footprint_bevel", FAIL, "footprint bevel produced too-short edges", **bevel)
        elif bevel.get("total_beveled_corners", 0) <= 0:
            self.add("footprint_bevel", WARN, "no eligible footprint corners were beveled", **bevel)
        else:
            self.add("footprint_bevel", PASS, "eligible footprint corners were beveled", **bevel)

        normals = bundle.get("building_normals", {})
        self.metrics["building_normals"] = normals
        if not normals.get("has_n"):
            self.add("building_normals", FAIL, "bld_with_foundation has no N attribute", **normals)
        elif any(normals.get(k, 0) for k in ("storedN_missing", "storedN_zero", "storedN_mismatch", "degenerate")):
            self.add("building_normals", FAIL, "building final normals are invalid", **normals)
        else:
            self.add("building_normals", PASS, "building final normals are valid", **normals)

        tags = bundle.get("foundation_tags", {})
        self.metrics["foundation_tags"] = tags
        if not tags.get("has_attr"):
            self.add("foundation_tags", FAIL, "final building geometry lacks is_foundation", **tags)
        elif tags.get("tag_0") != tags.get("body_expected") or tags.get("tag_1") != tags.get("foundation_expected") or tags.get("other"):
            self.add("foundation_tags", FAIL, "is_foundation tag counts do not match merged geometry", **tags)
        else:
            self.add("foundation_tags", PASS, "is_foundation tags match body/foundation counts", **tags)

        fnormals = bundle.get("foundation_normals", {})
        self.metrics["foundation_vs_body_normals"] = fnormals
        if fnormals.get("mismatch", 0):
            self.add("foundation_normals", FAIL, "foundation side normals disagree with nearby building sides", **fnormals)
        elif fnormals.get("no_near_match", 0):
            self.add("foundation_normals", WARN, "some foundation sides have no nearby building side match", **fnormals)
        else:
            self.add("foundation_normals", PASS, "foundation side normals align with building sides", **fnormals)

        align = bundle.get("foundation_alignment", {})
        self.metrics["foundation_alignment"] = align
        if not align.get("foundation_top_points"):
            self.add("foundation_alignment", WARN, "no foundation top points found", **align)
        elif align.get("over_threshold", 0):
            self.add("foundation_alignment", FAIL, "foundation top edge is offset from building bottom edge", **align)
        else:
            self.add("foundation_alignment", PASS, "foundation top edge matches building bottom edge", **align)

    def terrain_delta_stats(
        self,
        node_name: str,
        terrain_name: str,
        label: str,
        threshold: float,
        miss_warn_ratio: float = 0.10,
    ) -> None:
        node_path = f"{self.obj_path}/{node_name}"
        terrain_path = f"{self.obj_path}/{terrain_name}"
        expr = "_vc_model_qa_terrain_delta({}, {}, {}, {})".format(
            json.dumps(node_path),
            json.dumps(terrain_path),
            "None" if self.max_points is None else int(self.max_points),
            repr(float(threshold)),
        )
        stats = json.loads(self.conn.eval(expr))
        if stats.get("missing"):
            self.add(label, WARN, f"{node_name} or {terrain_name} missing")
            return
        self.metrics[label] = stats
        if stats["below_threshold"]:
            self.add(label, FAIL, f"{node_name} has points below terrain threshold", **stats)
        elif stats["misses"] and stats["misses"] > stats["sampled_points"] * miss_warn_ratio:
            self.add(label, WARN, f"{node_name} has many terrain ray misses", **stats)
        else:
            self.add(label, PASS, f"{node_name} terrain placement is within threshold", **stats)

    def check_road_faces(self) -> None:
        node_path = f"{self.obj_path}/road_strips"
        detail = json.loads(self.conn.eval("_vc_model_qa_road_faces({})".format(json.dumps(node_path))))
        if detail.get("missing"):
            self.add("road_faces", FAIL, "road_strips is missing")
            return
        self.metrics["road_faces"] = detail
        if detail["open_prims"] or detail["large_area_fail_count"] or detail["too_many_vertices_count"]:
            self.add("road_faces", FAIL, "road strip geometry has invalid faces", **detail)
        elif detail["large_area_warn_count"]:
            self.add("road_faces", WARN, "road strip geometry has unusually large faces", **detail)
        else:
            self.add("road_faces", PASS, "road strip faces look bounded", **detail)

    def check_terrain_density(self) -> None:
        dem = self.geo("dem_terrain")
        subdiv = self.geo("dem_subdivide")
        if dem is None or subdiv is None:
            self.add("terrain_density", WARN, "terrain nodes are missing")
            return
        dem_pts = int(dem.intrinsicValue("pointcount"))
        subdiv_pts = int(subdiv.intrinsicValue("pointcount"))
        detail = {
            "dem_terrain_points": dem_pts,
            "dem_subdivide_points": subdiv_pts,
            "ratio": (subdiv_pts / dem_pts) if dem_pts else None,
        }
        self.metrics["terrain_density"] = detail
        if subdiv_pts <= dem_pts:
            self.add("terrain_density", WARN, "terrain snap target is not denser than raw DEM", **detail)
        else:
            self.add("terrain_density", PASS, "terrain snap target is subdivided", **detail)

    def run(self) -> None:
        self.check_required_nodes()
        self.check_terrain_density()
        self.check_building_bundle()
        self.terrain_delta_stats("bld_with_foundation", "dem_subdivide", "building_terrain_fit", -0.05)
        self.check_road_faces()
        self.terrain_delta_stats("road_clipped", "dem_subdivide", "road_terrain_fit", -0.05, miss_warn_ratio=0.35)


def overall_status(checks: list[dict[str, Any]]) -> str:
    if any(c["status"] == FAIL for c in checks):
        return FAIL
    if any(c["status"] == WARN for c in checks):
        return WARN
    return PASS


def write_report(report: dict[str, Any]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    area_id = report.get("area_id", "unknown")
    path = REPORT_DIR / f"{area_id}_{report['timestamp_compact']}_{report['mode']}.json"
    latest = REPORT_DIR / "latest.json"
    for out in (path, latest):
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
            f.write("\n")
    return path


def print_summary(report: dict[str, Any], report_path: Path) -> None:
    status = report["status"].upper()
    summary = report["summary"]
    print(f"[ModelQA] status={status} mode={report['mode']} checks={summary}")
    for check in report["checks"]:
        tag = "[OK]" if check["status"] == PASS else "[WARN]" if check["status"] == WARN else "[FAIL]" if check["status"] == FAIL else "[INFO]"
        print(f"  {tag} {check['name']}: {check['message']}")
    print(f"  report: {project_relative(report_path)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["quick", "full"], default="quick")
    parser.add_argument("--obj-path", default=None, help="Override Houdini object network path")
    parser.add_argument("--json", action="store_true", help="Print the full JSON report")
    parser.add_argument("--fail-on-warn", action="store_true")
    args = parser.parse_args()

    cfg = load_active_area(absolute=False)
    obj_path = args.obj_path or f"/obj/{cfg.get('obj_network', 'city_gen')}"
    conn = rpyc.classic.connect("localhost", 18811)
    try:
        conn._config["sync_request_timeout"] = 600
        conn.execute("import hou")
        conn.execute(REMOTE_HELPERS)
        hou = conn.modules.hou
        if hou.node(obj_path) is None and obj_path == "/obj/city_gen" and hou.node("/obj/pattaya_osm") is not None:
            obj_path = "/obj/pattaya_osm"
        qa = QA(conn, hou, obj_path, args.mode)
        qa.run()
        status = overall_status(qa.checks)
        compact = now_stamp()
        report = {
            "tool": "houdini_model_qa",
            "mode": args.mode,
            "status": status,
            "area_id": cfg.get("area_id", ""),
            "obj_path": obj_path,
            "hip_path": hou.hipFile.path(),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp_compact": compact,
            "summary": {
                "pass": sum(1 for c in qa.checks if c["status"] == PASS),
                "warn": sum(1 for c in qa.checks if c["status"] == WARN),
                "fail": sum(1 for c in qa.checks if c["status"] == FAIL),
            },
            "checks": qa.checks,
            "metrics": qa.metrics,
        }
        report_path = write_report(report)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print_summary(report, report_path)
        if status == FAIL or (args.fail_on_warn and status == WARN):
            return 1
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
