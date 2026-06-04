"""Cook the road test directly inside the currently open Houdini session.

This file is executed inside Houdini by scripts/houdini_cook_rpyc.py.
It updates only /obj/road_test_<area_id> and does not clear or save the user's scene.
"""

from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

import hou


def load_builder_module(script_path: Path):
    module_path = script_path.with_name("houdini_build_road_test.py")
    spec = importlib.util.spec_from_file_location("road_test_houdini_builder", str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load builder module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_or_get(parent: hou.Node, node_type: str, name: str) -> hou.Node:
    existing = parent.node(name)
    if existing is not None:
        existing.destroy()
    return parent.createNode(node_type, node_name=name)


def frame_scene_viewer(node: hou.Node) -> None:
    try:
        desktop = hou.ui.curDesktop()
        viewer = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
        if viewer is None:
            return
        viewer.setCurrentNode(node)
        viewport = viewer.curViewport()
        viewport.frameBoundingBox(node.geometry().boundingBox())
    except Exception:
        pass


def main() -> None:
    root_override = globals().get("ROAD_TEST_ROOT")
    if root_override:
        root = Path(str(root_override)).resolve()
        this_file = root / "scripts" / "houdini_cook_open_session.py"
    else:
        this_file = Path(__file__).resolve()
        root = this_file.parents[1]
    config_path = root / "config" / "pattaya_central_500m.area.json"
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    area_id = cfg["area_id"]
    builder = load_builder_module(this_file)
    package_inputs = builder.resolve_latest_houdini_package(root, area_id)
    standard_lanes_path = package_inputs["standard_lanes_path"]
    standard_junctions_path = package_inputs["standard_junctions_path"]
    lane_surface_geojson_path = package_inputs["standard_lane_surfaces_path"]
    builder.remove_test_materials()

    obj = hou.node("/obj")
    if obj is None:
        raise hou.NodeError("Missing /obj context")

    geo_name = f"road_test_{area_id}"
    old_geo = obj.node(geo_name)
    if old_geo is not None:
        old_geo.destroy()

    geo = obj.createNode("geo", node_name=geo_name)
    builder.clear_children(geo)

    import_node = create_or_get(geo, "python", "python_import_standard_lanes")
    import_node.parm("python").set(builder.python_import_standard_lanes_code(standard_lanes_path))

    center_null = create_or_get(geo, "null", "OUT_centerlines")
    center_null.setInput(0, import_node)

    centerline_node = create_or_get(geo, "python", "python_centerlines_retained")
    centerline_node.setInput(0, import_node)
    centerline_node.parm("python").set(builder.python_centerline_code())

    out_node = create_or_get(geo, "null", "OUT_roads_centerlines")
    out_node.setInput(0, centerline_node)
    out_node.setDisplayFlag(True)
    out_node.setRenderFlag(True)

    lane_debug_node = None
    lane_debug_out = None
    lane_debug_node = create_or_get(geo, "python", "python_lane_geometry_debug")
    lane_debug_node.parm("python").set(
        builder.python_lane_debug_code(
            standard_lanes_path=standard_lanes_path,
            standard_junctions_path=standard_junctions_path,
        )
    )
    lane_debug_node.setDisplayFlag(False)
    lane_debug_node.setRenderFlag(False)

    lane_debug_out = create_or_get(geo, "null", "OUT_lane_connections_debug")
    lane_debug_out.setInput(0, lane_debug_node)
    lane_debug_out.setDisplayFlag(False)
    lane_debug_out.setRenderFlag(False)

    lane_surface_node = None
    lane_surface_out = None
    if lane_surface_geojson_path.exists():
        lane_surface_node = create_or_get(geo, "python", "python_lane_surfaces_v1")
        lane_surface_node.parm("python").set(builder.python_lane_surface_import_code(lane_surface_geojson_path))
        lane_surface_node.setDisplayFlag(False)
        lane_surface_node.setRenderFlag(False)

        lane_surface_out = create_or_get(geo, "null", "OUT_lane_surfaces_v1")
        lane_surface_out.setInput(0, lane_surface_node)
        lane_surface_out.setDisplayFlag(False)
        lane_surface_out.setRenderFlag(False)

    note = geo.createStickyNote("ROAD_TEST_NOTES")
    note.setText(
        "Open-session road test cook\\n"
        f"Area: {area_id}\\n"
        f"Package: {package_inputs['package_version']}\\n"
        "Mode: centerlines only\\n"
        "Debug: OUT_lane_connections_debug\\n"
        "Surface: OUT_lane_surfaces_v1\\n"
        "Entry: RUN_HOUDINI_ROAD_TEST.bat\\n"
        "This updates only this road_test object."
    )
    note.setPosition(hou.Vector2(-3.5, 2.0))

    geo.layoutChildren()
    cook_nodes = [import_node, center_null, centerline_node, out_node]
    if lane_debug_node is not None and lane_debug_out is not None:
        cook_nodes.extend([lane_debug_node, lane_debug_out])
    if lane_surface_node is not None and lane_surface_out is not None:
        cook_nodes.extend([lane_surface_node, lane_surface_out])
    for n in cook_nodes:
        n.cook(force=True)

    out_node.setCurrent(True, clear_all_selected=True)
    frame_scene_viewer(out_node)

    report_dir = root / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{area_id}_open_session_cook_report.json"
    preview_report_path = report_dir / f"{area_id}_road_preview_report.json"
    qa_report_path = report_dir / "qa" / f"{area_id}_topology_repair_qa_report.json"
    stats = builder.load_standard_lane_package_stats(standard_lanes_path, standard_junctions_path, lane_surface_geojson_path)
    lane_debug_geo = lane_debug_out.geometry() if lane_debug_out is not None else None
    lane_surface_geo = lane_surface_out.geometry() if lane_surface_out is not None else None
    report = {
        "area_id": area_id,
        "mode": "open_houdini_session",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "refresh_behavior": "replace_existing_road_test_object",
        "obj_node": geo.path(),
        "display_node": out_node.path(),
        "input_mode": package_inputs["mode"],
        "package_version": package_inputs["package_version"],
        "package_dir": str(package_inputs["package_dir"]),
        "package_manifest": str(package_inputs["package_manifest_path"]),
        "houdini_manifest": str(package_inputs["houdini_manifest_path"]),
        "standard_lanes": str(standard_lanes_path),
        "standard_junctions": str(standard_junctions_path),
        "standard_lane_surfaces": str(lane_surface_geojson_path),
        "preview_report": str(preview_report_path) if preview_report_path.exists() else "",
        "qa_report": str(qa_report_path) if qa_report_path.exists() else "",
        "input_features": stats["feature_count"],
        "package_counts": {
            "standard_lanes": stats["standard_lane_count"],
            "standard_roads": stats["standard_road_count"],
            "standard_junctions": stats["standard_junction_count"],
            "standard_surface_features": stats["standard_surface_count"],
            "lane_direction_counts": stats["lane_direction_counts"],
        },
        "centerline_prims": len(center_null.geometry().prims()),
        "preview_output_prims": len(out_node.geometry().prims()),
        "preview_output_points": len(out_node.geometry().points()),
        "lane_debug_node": lane_debug_out.path() if lane_debug_out is not None else "",
        "lane_debug_prims": len(lane_debug_geo.prims()) if lane_debug_geo is not None else 0,
        "lane_debug_points": len(lane_debug_geo.points()) if lane_debug_geo is not None else 0,
        "lane_surface_node": lane_surface_out.path() if lane_surface_out is not None else "",
        "lane_surface_prims": len(lane_surface_geo.prims()) if lane_surface_geo is not None else 0,
        "lane_surface_points": len(lane_surface_geo.points()) if lane_surface_geo is not None else 0,
        "note": "This cook did not clear or save the current HIP scene.",
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[RoadTest] Open-session cook complete")
    print(json.dumps(report, ensure_ascii=False, indent=2))


main()
