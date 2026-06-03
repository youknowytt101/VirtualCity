#!/usr/bin/env python3
"""Audit the road_test_pipeline contracts across data, semantics and preview.

This is a lightweight regression gate for the research pipeline. It checks the
contracts that matter while the default output remains centerline-only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


JUNCTION_TYPES = {"T", "cross", "Y", "offset", "complex"}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def make_check(check_id: str, ok: bool, message: str, value: Any = None, warn: bool = False) -> dict[str, Any]:
    status = "pass" if ok else "warn" if warn else "fail"
    return {
        "id": check_id,
        "status": status,
        "value": value,
        "message": message,
    }


def worst_status(checks: list[dict[str, Any]]) -> str:
    order = {"pass": 0, "warn": 1, "fail": 2}
    status = "pass"
    for check in checks:
        if order[check["status"]] > order[status]:
            status = check["status"]
    return status


def geometry_type_counts(fc: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for feature in fc.get("features", []):
        geom_type = str((feature.get("geometry") or {}).get("type") or "missing")
        counts[geom_type] = counts.get(geom_type, 0) + 1
    return counts


def line_coordinate_count(fc: dict[str, Any]) -> int:
    total = 0
    for feature in fc.get("features", []):
        geom = feature.get("geometry") or {}
        if geom.get("type") == "LineString":
            total += len(geom.get("coordinates") or [])
    return total


def as_points(points: list[Any]) -> list[tuple[float, float]]:
    return [(float(point[0]), float(point[1])) for point in points]


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = a[0] - b[0]
    dz = a[1] - b[1]
    return (dx * dx + dz * dz) ** 0.5


def polyline_length(points: list[tuple[float, float]]) -> float:
    return sum(distance(points[i], points[i + 1]) for i in range(len(points) - 1))


def resolve_trim_distances(
    length: float,
    trim_start_m: float,
    trim_end_m: float,
    locked_start_m: float = 0.0,
    locked_end_m: float = 0.0,
) -> tuple[float, float]:
    trim_start_m = max(0.0, trim_start_m)
    trim_end_m = max(0.0, trim_end_m)
    locked_start_m = min(max(0.0, locked_start_m), trim_start_m)
    locked_end_m = min(max(0.0, locked_end_m), trim_end_m)
    trim_total = trim_start_m + trim_end_m
    max_trim_total = max(0.0, length - 0.5)
    if trim_total > max_trim_total and trim_total > 0.0:
        locked_total = locked_start_m + locked_end_m
        if locked_total >= max_trim_total and locked_total > 0.0:
            scale = max_trim_total / locked_total
            return locked_start_m * scale, locked_end_m * scale
        remaining = max_trim_total - locked_total
        start_extra = trim_start_m - locked_start_m
        end_extra = trim_end_m - locked_end_m
        extra_total = start_extra + end_extra
        if extra_total <= 0.0:
            return locked_start_m, locked_end_m
        scale = remaining / extra_total
        return locked_start_m + start_extra * scale, locked_end_m + end_extra * scale
    return trim_start_m, trim_end_m


def point_at_distance(points: list[tuple[float, float]], distance_m: float) -> tuple[float, float]:
    if distance_m <= 0.0:
        return points[0]
    remaining = distance_m
    for i in range(len(points) - 1):
        seg_len = distance(points[i], points[i + 1])
        if seg_len <= 1e-9:
            continue
        if remaining <= seg_len:
            t = remaining / seg_len
            return (
                points[i][0] + (points[i + 1][0] - points[i][0]) * t,
                points[i][1] + (points[i + 1][1] - points[i][1]) * t,
            )
        remaining -= seg_len
    return points[-1]


def trimmed_endpoint(
    lane: dict[str, Any],
    side: str,
    trim: dict[str, float],
) -> tuple[float, float] | None:
    points = as_points(lane.get("centerline_xz") or [])
    if len(points) < 2:
        return None
    length = polyline_length(points)
    trim_start_m, trim_end_m = resolve_trim_distances(
        length,
        float(trim.get("start") or 0.0),
        float(trim.get("end") or 0.0),
        float(trim.get("locked_start") or 0.0),
        float(trim.get("locked_end") or 0.0),
    )
    station = trim_start_m if side == "start" else max(0.0, length - trim_end_m)
    return point_at_distance(points, station)


def lane_trim_distances(
    lane_graph: dict[str, Any],
    lane_links: list[dict[str, Any]],
    continuity_links: list[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    trim_m = float(lane_graph.get("metadata", {}).get("junction_trim_m") or 8.0)
    lanes_by_id = {str(lane.get("lane_id") or ""): lane for lane in lane_graph.get("lanes", [])}
    trim_by_lane: dict[str, dict[str, float]] = {}

    def update(lane_id: str, side: str, value: float) -> None:
        if not lane_id or value <= 0.0:
            return
        item = trim_by_lane.setdefault(lane_id, {"start": 0.0, "end": 0.0, "locked_start": 0.0, "locked_end": 0.0})
        item[side] = max(item[side], value)

    def lock(lane_id: str, side: str, value: float) -> None:
        if not lane_id or value <= 0.0:
            return
        item = trim_by_lane.setdefault(lane_id, {"start": 0.0, "end": 0.0, "locked_start": 0.0, "locked_end": 0.0})
        item[side] = max(item[side], value)
        item[f"locked_{side}"] = max(item[f"locked_{side}"], value)

    def default_lane_link_trim(lane_id: str) -> float:
        lane = lanes_by_id.get(lane_id)
        if lane is not None and bool(lane.get("approach_centerline_trimmed")):
            return 0.0
        return trim_m

    def link_trim_value(link: dict[str, Any], key: str, default: float) -> float:
        if key not in link or link.get(key) is None:
            return default
        return max(0.0, float(link.get(key) or 0.0))

    for link in lane_links:
        from_lane = str(link.get("from_lane") or "")
        to_lane = str(link.get("to_lane") or "")
        update(from_lane, "end", link_trim_value(link, "from_lane_trim_end_m", default_lane_link_trim(from_lane)))
        update(to_lane, "start", link_trim_value(link, "to_lane_trim_start_m", default_lane_link_trim(to_lane)))

    for link in continuity_links:
        lock(str(link.get("from_lane") or ""), "end", float(link.get("from_lane_trim_end_m") or 0.0))
        lock(str(link.get("to_lane") or ""), "start", float(link.get("to_lane_trim_start_m") or 0.0))

    return trim_by_lane


def lane_curve_gap_metrics(
    lane_graph: dict[str, Any],
    lane_links: list[dict[str, Any]],
    continuity_links: list[dict[str, Any]],
) -> dict[str, Any]:
    lanes_by_id = {str(lane.get("lane_id") or ""): lane for lane in lane_graph.get("lanes", [])}
    trim_by_lane = lane_trim_distances(lane_graph, lane_links, continuity_links)
    max_lane_link_start_gap = 0.0
    max_lane_link_end_gap = 0.0
    max_continuity_start_gap = 0.0
    max_continuity_end_gap = 0.0

    for link in lane_links:
        curve = as_points(link.get("connecting_curve_xz") or [])
        from_lane = lanes_by_id.get(str(link.get("from_lane") or ""))
        to_lane = lanes_by_id.get(str(link.get("to_lane") or ""))
        if len(curve) < 2 or from_lane is None or to_lane is None:
            continue
        from_endpoint = trimmed_endpoint(from_lane, "end", trim_by_lane.get(str(link.get("from_lane") or ""), {}))
        to_endpoint = trimmed_endpoint(to_lane, "start", trim_by_lane.get(str(link.get("to_lane") or ""), {}))
        if from_endpoint is not None:
            max_lane_link_start_gap = max(max_lane_link_start_gap, distance(from_endpoint, curve[0]))
        if to_endpoint is not None:
            max_lane_link_end_gap = max(max_lane_link_end_gap, distance(to_endpoint, curve[-1]))

    for link in continuity_links:
        curve = as_points(link.get("connecting_curve_xz") or [])
        from_lane = lanes_by_id.get(str(link.get("from_lane") or ""))
        to_lane = lanes_by_id.get(str(link.get("to_lane") or ""))
        if len(curve) < 2 or from_lane is None or to_lane is None:
            continue
        from_endpoint = trimmed_endpoint(from_lane, "end", trim_by_lane.get(str(link.get("from_lane") or ""), {}))
        to_endpoint = trimmed_endpoint(to_lane, "start", trim_by_lane.get(str(link.get("to_lane") or ""), {}))
        if from_endpoint is not None:
            max_continuity_start_gap = max(max_continuity_start_gap, distance(from_endpoint, curve[0]))
        if to_endpoint is not None:
            max_continuity_end_gap = max(max_continuity_end_gap, distance(to_endpoint, curve[-1]))

    return {
        "max_lane_link_start_gap_m": round(max_lane_link_start_gap, 6),
        "max_lane_link_end_gap_m": round(max_lane_link_end_gap, 6),
        "max_continuity_start_gap_m": round(max_continuity_start_gap, 6),
        "max_continuity_end_gap_m": round(max_continuity_end_gap, 6),
    }


def audit(root: Path, area_id: str, output_path: Path) -> dict[str, Any]:
    processed = root / "data" / "processed"
    preview_dir = root / "data" / "preview"
    reports = root / "reports"
    qa_reports = reports / "qa"

    paths = {
        "raw_roads": processed / f"{area_id}_roads_raw.geojson",
        "repaired_roads": processed / f"{area_id}_roads_repaired.geojson",
        "road_graph": processed / f"{area_id}_road_graph.json",
        "junction_semantics": processed / f"{area_id}_junction_semantics.json",
        "optimized_centerlines": processed / f"{area_id}_roads_optimized_centerlines.geojson",
        "lane_graph": processed / f"{area_id}_lane_graph.json",
        "preview_geojson": preview_dir / f"{area_id}_roads_preview_surfaces.geojson",
        "preview_obj": preview_dir / f"{area_id}_roads_preview.obj",
        "preview_svg": preview_dir / f"{area_id}_roads_preview.svg",
        "lane_geometry_debug_geojson": preview_dir / f"{area_id}_lane_geometry_debug.geojson",
        "lane_geometry_debug_obj": preview_dir / f"{area_id}_lane_geometry_debug.obj",
        "lane_geometry_debug_svg": preview_dir / f"{area_id}_lane_geometry_debug.svg",
        "lane_geometry_debug_report": reports / f"{area_id}_lane_geometry_debug_report.json",
        "lane_surface_v1_geojson": preview_dir / f"{area_id}_lane_surfaces_v1.geojson",
        "lane_surface_v1_obj": preview_dir / f"{area_id}_lane_surfaces_v1.obj",
        "lane_surface_v1_svg": preview_dir / f"{area_id}_lane_surfaces_v1.svg",
        "lane_surface_v1_report": reports / f"{area_id}_lane_surface_v1_report.json",
        "topology_qa": qa_reports / f"{area_id}_topology_repair_qa_report.json",
        "road_graph_qa": qa_reports / f"{area_id}_road_graph_qa_report.json",
        "lane_graph_qa": qa_reports / f"{area_id}_lane_graph_qa_report.json",
    }

    checks: list[dict[str, Any]] = []
    missing = [name for name, path in paths.items() if not path.exists()]
    checks.append(make_check(
        "required_outputs_exist",
        not missing,
        "All required stage outputs should exist for reproducible review.",
        missing,
    ))
    if missing:
        report = {"area_id": area_id, "stage": "pipeline_audit", "status": "fail", "checks": checks}
        write_json(output_path, report)
        return report

    road_graph = read_json(paths["road_graph"])
    semantics = read_json(paths["junction_semantics"])
    optimized = read_json(paths["optimized_centerlines"])
    lane_graph = read_json(paths["lane_graph"])
    preview = read_json(paths["preview_geojson"])
    lane_debug_report = read_json(paths["lane_geometry_debug_report"])
    lane_surface_report = read_json(paths["lane_surface_v1_report"])
    topology_qa = read_json(paths["topology_qa"])
    road_graph_qa = read_json(paths["road_graph_qa"])
    lane_graph_qa = read_json(paths["lane_graph_qa"])

    road_counts = {
        "nodes": len(road_graph.get("nodes", [])),
        "edges": len(road_graph.get("edges", [])),
    }
    checks.append(make_check(
        "road_graph_nonempty",
        road_counts["nodes"] > 0 and road_counts["edges"] > 0,
        "Road graph should expose non-empty nodes and edges.",
        road_counts,
    ))

    semantic_types = {junction.get("type") for junction in semantics.get("junctions", [])}
    checks.append(make_check(
        "junction_type_contract",
        semantic_types.issubset(JUNCTION_TYPES),
        "Junction semantics must stay within T/cross/Y/offset/complex.",
        sorted(semantic_types),
    ))

    allowed = {
        movement["movement_id"]
        for junction in semantics.get("junctions", [])
        for movement in junction.get("movements", [])
        if movement.get("allowed")
    }
    blocked = {
        movement["movement_id"]
        for junction in semantics.get("junctions", [])
        for movement in junction.get("movements", [])
        if not movement.get("allowed")
    }
    connection_ids = {
        connection["semantic_movement_id"]
        for junction in lane_graph.get("junctions", [])
        for connection in junction.get("connections", [])
    }
    checks.append(make_check(
        "allowed_movements_have_connections",
        allowed == connection_ids,
        "Every allowed semantic movement should become exactly one lane-level connection.",
        {
            "allowed": len(allowed),
            "connections": len(connection_ids),
            "missing": sorted(allowed - connection_ids)[:20],
            "extra": sorted(connection_ids - allowed)[:20],
        },
    ))
    checks.append(make_check(
        "blocked_movements_have_no_connections",
        not (blocked & connection_ids),
        "Blocked or one-way-disallowed movements must not create lane connections.",
        sorted(blocked & connection_ids)[:20],
    ))

    lane_ids = {lane["lane_id"] for lane in lane_graph.get("lanes", [])}
    lane_links = [
        link
        for junction in lane_graph.get("junctions", [])
        for connection in junction.get("connections", [])
        for link in connection.get("lane_links", [])
    ]
    continuity_links = list(lane_graph.get("continuity_links", []))
    bad_refs = [
        link.get("lane_link_id", "")
        for link in lane_links
        if link.get("from_lane") not in lane_ids or link.get("to_lane") not in lane_ids
    ]
    bad_continuity_refs = [
        link.get("continuity_link_id", "")
        for link in continuity_links
        if link.get("from_lane") not in lane_ids or link.get("to_lane") not in lane_ids
    ]
    empty_curves = [
        link.get("lane_link_id", "")
        for link in lane_links
        if not link.get("connecting_curve_xz")
    ]
    empty_continuity_curves = [
        link.get("continuity_link_id", "")
        for link in continuity_links
        if not link.get("connecting_curve_xz")
    ]
    checks.append(make_check(
        "lane_link_references_valid",
        not bad_refs,
        "Every laneLink should reference existing from/to lanes.",
        bad_refs[:20],
    ))
    checks.append(make_check(
        "lane_link_curves_nonempty",
        not empty_curves,
        "Every laneLink should carry a connector curve.",
        empty_curves[:20],
    ))
    checks.append(make_check(
        "continuity_link_references_valid",
        not bad_continuity_refs,
        "Every corner continuity link should reference existing from/to lanes.",
        bad_continuity_refs[:20],
    ))
    checks.append(make_check(
        "continuity_link_curves_nonempty",
        not empty_continuity_curves,
        "Every corner continuity link should carry an optimized fillet curve.",
        empty_continuity_curves[:20],
    ))
    gap_metrics = lane_curve_gap_metrics(lane_graph, lane_links, continuity_links)
    max_curve_trim_gap = max(float(value) for value in gap_metrics.values())
    checks.append(make_check(
        "lane_curves_match_trimmed_lane_endpoints",
        max_curve_trim_gap <= 0.01,
        "LaneLink and corner continuity curves should start/end at the same trimmed lane endpoints used by lane surfaces.",
        gap_metrics,
    ))

    fan_fallback_junctions = [
        junction["junction_id"]
        for junction in lane_graph.get("junctions", [])
        if junction.get("envelope_strategy") == "junction_fan_envelope"
    ]
    checks.append(make_check(
        "no_fan_fallback_in_layer3",
        not fan_fallback_junctions,
        "Layer 3 should remain semantic/lane-level and not rely on junction fan fallback.",
        fan_fallback_junctions[:20],
    ))

    optimized_types = geometry_type_counts(optimized)
    preview_types = geometry_type_counts(preview)
    optimized_coord_count = line_coordinate_count(optimized)
    preview_coord_count = line_coordinate_count(preview)
    optimized_corner_fillet_count = sum(
        1
        for feature in optimized.get("features", [])
        if (feature.get("properties") or {}).get("vc_part") == "optimized_corner_fillet"
    )
    optimized_junction_connector_count = sum(
        1
        for feature in optimized.get("features", [])
        if (feature.get("properties") or {}).get("vc_part") == "optimized_junction_connector"
    )
    lane_link_curve_source_counts: dict[str, int] = {}
    for link in lane_links:
        source = str(link.get("curve_source") or "unknown")
        lane_link_curve_source_counts[source] = lane_link_curve_source_counts.get(source, 0) + 1
    checks.append(make_check(
        "optimized_centerlines_are_lines",
        set(optimized_types) == {"LineString"},
        "Optimized centerline output should contain only LineString features.",
        optimized_types,
    ))
    checks.append(make_check(
        "preview_preserves_centerline_samples",
        optimized_coord_count == preview_coord_count,
        "Standalone preview should preserve all optimized centerline sample points.",
        {
            "optimized_points": optimized_coord_count,
            "preview_points": preview_coord_count,
        },
    ))
    checks.append(make_check(
        "preview_has_no_polygons",
        set(preview_types) == {"LineString"},
        "Preview GeoJSON should be centerline-only while surfaces are deferred.",
        preview_types,
    ))
    checks.append(make_check(
        "optimized_corner_fillets_have_lane_continuity",
        optimized_corner_fillet_count == 0 or len(continuity_links) > 0,
        "Lane graph should preserve road-level rounded corner fillets as continuity links.",
        {
            "optimized_corner_fillets": optimized_corner_fillet_count,
            "continuity_links": len(continuity_links),
        },
    ))
    checks.append(make_check(
        "junction_lane_links_are_semantic_not_optimized_connectors",
        lane_link_curve_source_counts.get("optimized_junction_connector", 0) == 0
        and lane_link_curve_source_counts.get("optimized_approach_endpoint_bezier", 0) == 0,
        "T/cross/Y/merge junction laneLinks should stay on the semantic lane movement branch; optimized road connectors are reserved for the centerline skeleton.",
        {
            "optimized_junction_connectors": optimized_junction_connector_count,
            "lane_link_curve_source_counts": lane_link_curve_source_counts,
        },
    ))

    obj_lines = paths["preview_obj"].read_text(encoding="utf-8").splitlines()
    obj_vertex_count = sum(1 for line in obj_lines if line.startswith("v "))
    obj_face_count = sum(1 for line in obj_lines if line.startswith("f "))
    obj_line_count = sum(1 for line in obj_lines if line.startswith("l "))
    checks.append(make_check(
        "preview_obj_centerline_only",
        obj_face_count == 0 and obj_line_count == len(preview.get("features", [])),
        "Preview OBJ should contain line elements only, with no faces.",
        {
            "vertices": obj_vertex_count,
            "line_elements": obj_line_count,
            "faces": obj_face_count,
        },
    ))

    lane_debug_counts = lane_debug_report.get("counts", {})
    checks.append(make_check(
        "lane_debug_geometry_matches_lane_graph",
        lane_debug_counts.get("lanes") == len(lane_graph.get("lanes", []))
        and lane_debug_counts.get("lane_links") == len(lane_links)
        and lane_debug_counts.get("lane_link_curves") == len(lane_links)
        and lane_debug_counts.get("lane_link_ribbons") == len(lane_links)
        and lane_debug_counts.get("continuity_links", 0) == len(continuity_links)
        and lane_debug_counts.get("lane_continuity_curves", 0) == len(continuity_links)
        and lane_debug_counts.get("lane_continuity_ribbons", 0) == len(continuity_links),
        "Lane debug geometry should expose every lane, every laneLink and every corner continuity curve/ribbon.",
        {
            "debug_counts": lane_debug_counts,
            "lane_graph_lanes": len(lane_graph.get("lanes", [])),
            "lane_graph_lane_links": len(lane_links),
            "lane_graph_continuity_links": len(continuity_links),
        },
    ))
    lane_debug_metrics = lane_debug_report.get("metrics", {})
    checks.append(make_check(
        "lane_debug_curves_nonempty",
        int(lane_debug_metrics.get("empty_lane_link_curves", 0)) == 0
        and int(lane_debug_metrics.get("empty_continuity_curves", 0)) == 0,
        "Lane debug geometry should not contain empty laneLink or continuity curves.",
        {
            "empty_lane_link_curves": lane_debug_metrics.get("empty_lane_link_curves", 0),
            "empty_continuity_curves": lane_debug_metrics.get("empty_continuity_curves", 0),
        },
    ))
    lane_debug_obj_lines = paths["lane_geometry_debug_obj"].read_text(encoding="utf-8").splitlines()
    lane_debug_obj_stats = {
        "vertices": sum(1 for line in lane_debug_obj_lines if line.startswith("v ")),
        "line_elements": sum(1 for line in lane_debug_obj_lines if line.startswith("l ")),
        "faces": sum(1 for line in lane_debug_obj_lines if line.startswith("f ")),
    }
    checks.append(make_check(
        "lane_debug_obj_has_lines_and_faces",
        lane_debug_obj_stats["line_elements"] > 0 and lane_debug_obj_stats["faces"] > 0,
        "Lane debug OBJ should contain both centerline curves and narrow debug ribbon faces.",
        lane_debug_obj_stats,
    ))

    lane_surface_counts = lane_surface_report.get("counts", {})
    checks.append(make_check(
        "lane_surface_v1_matches_lane_graph",
        lane_surface_counts.get("lane_surfaces") == len(lane_graph.get("lanes", []))
        and lane_surface_counts.get("lane_turn_surfaces") == len(lane_links)
        and lane_surface_counts.get("lane_continuity_surfaces", 0) == len(continuity_links),
        "Lane surface v1 should generate one approach surface per lane, one turn surface per laneLink and one continuity surface per rounded corner link.",
        {
            "surface_counts": lane_surface_counts,
            "lane_graph_lanes": len(lane_graph.get("lanes", [])),
            "lane_graph_lane_links": len(lane_links),
            "lane_graph_continuity_links": len(continuity_links),
        },
    ))
    lane_surface_obj_lines = paths["lane_surface_v1_obj"].read_text(encoding="utf-8").splitlines()
    lane_surface_obj_stats = {
        "vertices": sum(1 for line in lane_surface_obj_lines if line.startswith("v ")),
        "faces": sum(1 for line in lane_surface_obj_lines if line.startswith("f ")),
    }
    checks.append(make_check(
        "lane_surface_v1_obj_has_faces",
        lane_surface_obj_stats["faces"] == lane_surface_counts.get("obj_faces", 0)
        and lane_surface_obj_stats["faces"] > 0,
        "Lane surface v1 OBJ should contain surface faces.",
        lane_surface_obj_stats,
    ))

    houdini_build = (root / "scripts" / "houdini_build_road_test.py").read_text(encoding="utf-8")
    houdini_open = (root / "scripts" / "houdini_cook_open_session.py").read_text(encoding="utf-8")
    houdini_contract_ok = all(
        token in script
        for script in (houdini_build, houdini_open)
        for token in (
            "python_import_roads_geojson",
            "OUT_roads_centerlines",
            "OUT_lane_connections_debug",
            "OUT_lane_surfaces_v1",
            "out_node.setInput(0, centerline_node)",
            "out_node.setDisplayFlag(True)",
        )
    )
    checks.append(make_check(
        "houdini_default_output_centerline_only",
        houdini_contract_ok,
        "Houdini default output should import GeoJSON and display OUT_roads_centerlines from the retained centerline node.",
        houdini_contract_ok,
    ))

    qa_statuses = {
        "topology_repair": topology_qa.get("status"),
        "road_graph": road_graph_qa.get("status"),
        "lane_graph": lane_graph_qa.get("status"),
    }
    checks.append(make_check(
        "qa_reports_have_no_failures",
        all(status != "fail" for status in qa_statuses.values()),
        "Stage QA reports should have no failures; warnings are kept for data-quality issues.",
        qa_statuses,
        warn=True,
    ))

    metrics = {
        "road_graph": road_counts,
        "junctions": len(semantics.get("junctions", [])),
        "allowed_movements": len(allowed),
        "blocked_movements": len(blocked),
        "lanes": len(lane_graph.get("lanes", [])),
        "lane_connections": len(connection_ids),
        "lane_links": len(lane_links),
        "continuity_links": len(continuity_links),
        "lane_curve_gap_metrics": gap_metrics,
        "lane_link_curve_source_counts": lane_link_curve_source_counts,
        "optimized_features": len(optimized.get("features", [])),
        "optimized_corner_fillets": optimized_corner_fillet_count,
        "optimized_junction_connectors": optimized_junction_connector_count,
        "optimized_points": optimized_coord_count,
        "preview_points": preview_coord_count,
        "preview_obj_vertices": obj_vertex_count,
        "lane_debug_obj_vertices": lane_debug_obj_stats["vertices"],
        "lane_debug_obj_faces": lane_debug_obj_stats["faces"],
        "lane_surface_v1_obj_vertices": lane_surface_obj_stats["vertices"],
        "lane_surface_v1_obj_faces": lane_surface_obj_stats["faces"],
        "qa_statuses": qa_statuses,
    }
    report = {
        "area_id": area_id,
        "stage": "pipeline_audit",
        "status": worst_status(checks),
        "checks": checks,
        "metrics": metrics,
        "inputs": {name: str(path) for name, path in paths.items()},
        "next_action": "Use this audit as the automated gate before adding lane ribbons and junction surface geometry.",
    }
    write_json(output_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit road_test_pipeline stage contracts.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    output_path = Path(args.output) if args.output else root / "reports" / f"{args.area_id}_pipeline_audit_report.json"
    report = audit(root, args.area_id, output_path)
    print(json.dumps({
        "area_id": args.area_id,
        "status": report["status"],
        "output": str(output_path),
        "metrics": report.get("metrics", {}),
        "failed_or_warn_checks": [
            check
            for check in report["checks"]
            if check["status"] != "pass"
        ],
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] != "fail" else 2


if __name__ == "__main__":
    raise SystemExit(main())
