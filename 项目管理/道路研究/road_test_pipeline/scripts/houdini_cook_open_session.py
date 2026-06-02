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
    center = cfg["center"]

    repaired_geojson_path = root / "data" / "processed" / f"{area_id}_roads_repaired.geojson"
    raw_geojson_path = root / "data" / "processed" / f"{area_id}_roads_raw.geojson"
    geojson_path = repaired_geojson_path if repaired_geojson_path.exists() else raw_geojson_path
    if not geojson_path.exists():
        raise hou.NodeError(f"Missing road sample GeoJSON: {geojson_path}")

    builder = load_builder_module(this_file)
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

    import_node = create_or_get(geo, "python", "python_import_roads_raw")
    import_node.parm("python").set(
        builder.python_import_code(
            geojson_path=geojson_path,
            origin_lon=float(center["lon"]),
            origin_lat=float(center["lat"]),
        )
    )

    center_null = create_or_get(geo, "null", "OUT_centerlines")
    center_null.setInput(0, import_node)

    surface_node = create_or_get(geo, "python", "python_build_preview_surfaces")
    surface_node.setInput(0, import_node)
    surface_node.parm("python").set(builder.python_surface_code())

    centerline_node = create_or_get(geo, "python", "python_centerlines_retained")
    centerline_node.setInput(0, import_node)
    centerline_node.parm("python").set(builder.python_centerline_code())

    junction_node = create_or_get(geo, "python", "python_debug_junction_candidates")
    junction_node.setInput(0, import_node)
    junction_node.parm("python").set(builder.python_junction_debug_code())

    merge_node = create_or_get(geo, "merge", "merge_preview_surface_and_junction_debug")
    merge_node.setInput(0, surface_node)
    merge_node.setInput(1, centerline_node)
    merge_node.setInput(2, junction_node)

    normal_node = create_or_get(geo, "normal", "normal_preview")
    normal_node.setInput(0, merge_node)

    out_node = create_or_get(geo, "null", "OUT_roads_preview")
    out_node.setInput(0, normal_node)
    out_node.setDisplayFlag(True)
    out_node.setRenderFlag(True)

    note = geo.createStickyNote("ROAD_TEST_NOTES")
    note.setText(
        "Open-session road test cook\\n"
        f"Area: {area_id}\\n"
        "Entry: RUN_HOUDINI_ROAD_TEST.bat\\n"
        "This updates only this road_test object."
    )
    note.setPosition(hou.Vector2(-3.5, 2.0))

    geo.layoutChildren()
    for n in (import_node, center_null, surface_node, centerline_node, junction_node, merge_node, normal_node, out_node):
        n.cook(force=True)

    out_node.setCurrent(True, clear_all_selected=True)
    frame_scene_viewer(out_node)

    report_dir = root / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{area_id}_open_session_cook_report.json"
    preview_report_path = report_dir / f"{area_id}_road_preview_report.json"
    qa_report_path = report_dir / "qa" / f"{area_id}_topology_repair_qa_report.json"
    stats = builder.load_geojson_stats(geojson_path)
    report = {
        "area_id": area_id,
        "mode": "open_houdini_session",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "refresh_behavior": "replace_existing_road_test_object",
        "obj_node": geo.path(),
        "display_node": out_node.path(),
        "geojson_path": str(geojson_path),
        "geojson_mode": "repaired" if geojson_path == repaired_geojson_path else "raw",
        "preview_report": str(preview_report_path) if preview_report_path.exists() else "",
        "qa_report": str(qa_report_path) if qa_report_path.exists() else "",
        "input_features": stats["feature_count"],
        "centerline_prims": len(center_null.geometry().prims()),
        "preview_output_prims": len(out_node.geometry().prims()),
        "preview_output_points": len(out_node.geometry().points()),
        "note": "This cook did not clear or save the current HIP scene.",
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[RoadTest] Open-session cook complete")
    print(json.dumps(report, ensure_ascii=False, indent=2))


main()
