#!/usr/bin/env python3
"""Build the clean road skeleton stage before Houdini construction.

This runner intentionally stops before lane graph, lane surfaces and OpenDRIVE
export. Its contract is:

raw data -> road repair/pre-Houdini engineering -> clean skeleton GeoJSON

Houdini can then import only the clean skeleton as the starting viewport state.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def python_cmd() -> str:
    return sys.executable


def run_step(name: str, cmd: list[str], cwd: Path, log_path: Path) -> int:
    print(f"[RoadSkeleton] {name}...")
    with log_path.open("a", encoding="utf-8", newline="\n") as log:
        log.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] {name}\n")
        log.write(" ".join(cmd) + "\n")
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if proc.stdout:
            print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
            log.write(proc.stdout)
        log.write(f"[exit] {proc.returncode}\n")
    return proc.returncode


def rpyc_port_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def clean_skeleton_from_optimized(
    *,
    area_id: str,
    optimized_path: Path,
    output_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    optimized = read_json(optimized_path)
    features = optimized.get("features", [])
    part_counts: dict[str, int] = {}
    arc_counts: dict[str, int] = {}
    radius_violations = 0
    for feature in features:
        props = feature.get("properties") or {}
        part = str(props.get("vc_part") or "unknown")
        part_counts[part] = part_counts.get(part, 0) + 1
        arc = str(props.get("arc_geometry") or "")
        if arc:
            arc_counts[arc] = arc_counts.get(arc, 0) + 1
        if float(props.get("arc_radius_margin_m") or 0.0) < 0.0:
            radius_violations += 1

    metadata = dict(optimized.get("metadata") or {})
    metadata.update({
        "area_id": area_id,
        "schema": "road_test_pipeline.clean_road_skeleton.v1",
        "source": str(optimized_path),
        "stage": "road_repair_clean_skeleton",
        "display_contract": "Houdini imports this as the clean pre-construction road skeleton.",
    })
    clean = {
        "type": "FeatureCollection",
        "metadata": metadata,
        "features": features,
    }
    write_json(output_path, clean)

    report = {
        "area_id": area_id,
        "stage": "road_repair_clean_skeleton",
        "status": "warn" if radius_violations else "pass",
        "input": str(optimized_path),
        "output": str(output_path),
        "feature_count": len(features),
        "part_counts": dict(sorted(part_counts.items())),
        "arc_geometry_counts": dict(sorted(arc_counts.items())),
        "radius_violation_features": radius_violations,
        "note": "Radius violations stay visible as skeleton diagnostics; they are not fixed in Houdini.",
    }
    write_json(report_path, report)
    return report


def build_houdini_remote_code(
    root: Path,
    area_id: str,
    raw_roads_path: Path,
    repaired_roads_path: Path,
    clean_skeleton_path: Path,
) -> str:
    builder_path = root / "scripts" / "houdini_build_road_test.py"
    config_path = root / "config" / f"{area_id}.area.json"
    raw_report_path = root / "reports" / f"{area_id}_houdini_raw_road_preview_report.json"
    clean_report_path = root / "reports" / f"{area_id}_houdini_clean_skeleton_report.json"
    return f'''import importlib.util
import json
import time
from pathlib import Path
import hou

root = Path({json.dumps(str(root))})
builder_path = Path({json.dumps(str(builder_path))})
config_path = Path({json.dumps(str(config_path))})
raw_roads_path = Path({json.dumps(str(raw_roads_path))})
repaired_roads_path = Path({json.dumps(str(repaired_roads_path))})
clean_skeleton_path = Path({json.dumps(str(clean_skeleton_path))})
raw_report_path = Path({json.dumps(str(raw_report_path))})
clean_report_path = Path({json.dumps(str(clean_report_path))})
cfg = json.loads(config_path.read_text(encoding="utf-8"))
center = cfg["center"]
hip_path = root / "houdini" / f"{{cfg['area_id']}}_road_test.hip"

spec = importlib.util.spec_from_file_location("road_test_houdini_builder_clean_skeleton", str(builder_path))
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

obj = hou.node("/obj")
if obj is None:
    raise hou.NodeError("Missing /obj context")

geo_name = f"road_test_{{cfg['area_id']}}"
old_geo = obj.node(geo_name)
if old_geo is not None:
    old_geo.destroy()

geo = obj.createNode("geo", node_name=geo_name)
builder.clear_children(geo)

def filter_vc_part_code(allowed_parts):
    allowed_repr = repr(list(allowed_parts))
    return "import hou\\n\\n" + "\\n".join([
        "node = hou.pwd()",
        "geo = node.geometry()",
        "geo.clear()",
        "src = node.inputs()[0] if node.inputs() else None",
        "if src is None:",
        "    raise hou.NodeError('filter node requires an input')",
        "geo.merge(src.geometry())",
        "allowed = set(" + allowed_repr + ")",
        "attrib = geo.findPrimAttrib('vc_part')",
        "if attrib is None:",
        "    raise hou.NodeError('Missing vc_part primitive attribute')",
        "to_delete = [prim for prim in geo.prims() if str(prim.attribValue(attrib)) not in allowed]",
        "if to_delete:",
        "    geo.deletePrims(to_delete, keep_points=False)",
    ])

raw_import = geo.createNode("python", node_name="python_import_raw_roads")
raw_import.parm("python").set(builder.python_import_code(
    geojson_path=raw_roads_path,
    origin_lon=float(center["lon"]),
    origin_lat=float(center["lat"]),
))
raw_out = geo.createNode("null", node_name="OUT_raw_road_lines")
raw_out.setInput(0, raw_import)

repaired_import = geo.createNode("python", node_name="python_import_repaired_roads")
repaired_import.parm("python").set(builder.python_import_code(
    geojson_path=repaired_roads_path,
    origin_lon=float(center["lon"]),
    origin_lat=float(center["lat"]),
))
repaired_out = geo.createNode("null", node_name="OUT_repaired_road_lines")
repaired_out.setInput(0, repaired_import)

import_node = geo.createNode("python", node_name="python_import_clean_road_skeleton")
import_node.parm("python").set(builder.python_import_code(
    geojson_path=clean_skeleton_path,
    origin_lon=float(center["lon"]),
    origin_lat=float(center["lat"]),
))

out_node = geo.createNode("null", node_name="OUT_clean_road_skeleton")
out_node.setInput(0, import_node)
out_node.setDisplayFlag(True)
out_node.setRenderFlag(True)
out_node.setCurrent(True, clear_all_selected=True)

junction_arc_node = geo.createNode("python", node_name="python_filter_junction_connector_arcs")
junction_arc_node.setInput(0, import_node)
junction_arc_node.parm("python").set(filter_vc_part_code(["optimized_junction_connector"]))
junction_arc_out = geo.createNode("null", node_name="OUT_junction_connector_arcs")
junction_arc_out.setInput(0, junction_arc_node)

corner_arc_node = geo.createNode("python", node_name="python_filter_corner_fillet_arcs")
corner_arc_node.setInput(0, import_node)
corner_arc_node.parm("python").set(filter_vc_part_code(["optimized_corner_fillet"]))
corner_arc_out = geo.createNode("null", node_name="OUT_corner_fillet_arcs")
corner_arc_out.setInput(0, corner_arc_node)

note = geo.createStickyNote("ROAD_REPAIR_STAGE_NOTES")
note.setText(
    "Road repair stage output\\n"
    f"Area: {{cfg['area_id']}}\\n"
    "Left to right: raw source -> repaired topology -> clean single-line skeleton.\\n"
    "Junction connector arcs and corner fillet arcs are debug branches of the clean skeleton.\\n"
    "Next: start Houdini construction after this skeleton is accepted."
)
note.setPosition(hou.Vector2(-5.5, 1.8))

raw_import.setPosition(hou.Vector2(-6.0, 0.0))
raw_out.setPosition(hou.Vector2(-6.0, -1.0))
repaired_import.setPosition(hou.Vector2(-3.0, 0.0))
repaired_out.setPosition(hou.Vector2(-3.0, -1.0))
import_node.setPosition(hou.Vector2(0.0, 0.0))
out_node.setPosition(hou.Vector2(0.0, -1.0))
junction_arc_node.setPosition(hou.Vector2(3.0, 0.65))
junction_arc_out.setPosition(hou.Vector2(3.0, -0.35))
corner_arc_node.setPosition(hou.Vector2(3.0, -1.65))
corner_arc_out.setPosition(hou.Vector2(3.0, -2.65))
raw_import.cook(force=True)
raw_out.cook(force=True)
repaired_import.cook(force=True)
repaired_out.cook(force=True)
import_node.cook(force=True)
out_node.cook(force=True)
junction_arc_node.cook(force=True)
junction_arc_out.cook(force=True)
corner_arc_node.cook(force=True)
corner_arc_out.cook(force=True)

try:
    desktop = hou.ui.curDesktop()
    viewer = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewer is not None:
        viewer.setCurrentNode(out_node)
        viewer.curViewport().frameBoundingBox(out_node.geometry().boundingBox())
except Exception:
    pass

def geometry_stats(node):
    g = node.geometry()
    part_counts = {{}}
    if g.findPrimAttrib("vc_part") is not None:
        for prim in g.prims():
            part = prim.attribValue("vc_part")
            part_counts[part] = part_counts.get(part, 0) + 1
    return {{
        "primitives": len(g.prims()),
        "points": len(g.points()),
        "part_counts": part_counts,
    }}

raw_stats = geometry_stats(raw_out)
repaired_stats = geometry_stats(repaired_out)
clean_stats = geometry_stats(out_node)
junction_arc_stats = geometry_stats(junction_arc_out)
corner_arc_stats = geometry_stats(corner_arc_out)
raw_report = {{
    "area_id": cfg["area_id"],
    "stage": "houdini_raw_road_preview",
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    "hip_path": str(hip_path),
    "obj_node": geo.path(),
    "raw_node": raw_import.path(),
    "display_node": raw_out.path(),
    "raw_geojson_path": str(raw_roads_path),
    "primitives": raw_stats["primitives"],
    "points": raw_stats["points"],
    "part_counts": raw_stats["part_counts"],
    "compare_with": repaired_out.path(),
    "note": "Stage 1/3: raw source road lines.",
}}
clean_report = {{
    "area_id": cfg["area_id"],
    "stage": "houdini_clean_road_skeleton",
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    "hip_path": str(hip_path),
    "obj_node": geo.path(),
    "display_node": out_node.path(),
    "repaired_node": repaired_out.path(),
    "junction_arc_node": junction_arc_out.path(),
    "corner_arc_node": corner_arc_out.path(),
    "clean_skeleton_path": str(clean_skeleton_path),
    "repaired_roads_path": str(repaired_roads_path),
    "primitives": clean_stats["primitives"],
    "points": clean_stats["points"],
    "part_counts": clean_stats["part_counts"],
    "stage_stats": {{
        "raw": raw_stats,
        "repaired": repaired_stats,
        "clean_skeleton": clean_stats,
        "junction_connector_arcs": junction_arc_stats,
        "corner_fillet_arcs": corner_arc_stats,
    }},
    "compare_with": raw_out.path(),
    "note": "Stage layout: raw source -> repaired topology -> clean single-line skeleton, with junction/corner arc debug branches.",
}}
raw_report_path.parent.mkdir(parents=True, exist_ok=True)
raw_report_path.write_text(json.dumps(raw_report, ensure_ascii=False, indent=2), encoding="utf-8")
clean_report_path.write_text(json.dumps(clean_report, ensure_ascii=False, indent=2), encoding="utf-8")
hip_path.parent.mkdir(parents=True, exist_ok=True)
hou.hipFile.save(str(hip_path))
print("[RoadSkeleton] Houdini raw preview and clean skeleton synced")
print(json.dumps({{"raw": raw_report, "clean": clean_report}}, ensure_ascii=False, indent=2))
'''


def sync_houdini_clean_skeleton(
    root: Path,
    area_id: str,
    raw_roads_path: Path,
    repaired_roads_path: Path,
    clean_skeleton_path: Path,
    host: str,
    port: int,
) -> tuple[str, int]:
    if not rpyc_port_reachable(host, port):
        print(f"[WARN] Houdini RPYC is not reachable at {host}:{port}.")
        return "unavailable", 1
    try:
        import rpyc
    except Exception:
        print("[WARN] rpyc is not importable in this Python environment.")
        return "missing_rpyc", 1

    code = build_houdini_remote_code(root, area_id, raw_roads_path, repaired_roads_path, clean_skeleton_path)
    conn = rpyc.classic.connect(host, port)
    try:
        conn._config["sync_request_timeout"] = 600
        conn.execute(code)
    finally:
        conn.close()
    return "completed", 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the road repair clean skeleton stage.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--root", default="")
    parser.add_argument("--sync-houdini", action="store_true", help="Replace the Houdini road test object with clean skeleton view.")
    parser.add_argument("--require-houdini", action="store_true", help="Return non-zero if Houdini sync fails.")
    parser.add_argument("--apply-high-confidence", action="store_true", help="Promote high-confidence topology repair candidates before graph building.")
    parser.add_argument("--manual-overrides", default="", help="Manual topology overrides JSON. Defaults to config/<area_id>.manual_overrides.json.")
    parser.add_argument("--no-manual-overrides", action="store_true", help="Do not load manual topology overrides.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18811)
    args = parser.parse_args()

    script_path = Path(__file__).resolve()
    root = Path(args.root).resolve() if args.root else pipeline_root_from_script(script_path)
    reports = root / "reports"
    processed = root / "data" / "processed"
    reports.mkdir(parents=True, exist_ok=True)
    log_path = reports / f"{args.area_id}_road_skeleton_repair.log"
    log_path.write_text(f"[RoadSkeleton] started {time.strftime('%Y-%m-%d %H:%M:%S')}\n", encoding="utf-8")

    config = root / "config" / f"{args.area_id}.area.json"
    raw_geojson = processed / f"{args.area_id}_roads_raw.geojson"
    repaired_geojson = processed / f"{args.area_id}_roads_repaired.geojson"
    repair_candidates = processed / f"{args.area_id}_repair_candidates.json"
    repair_decisions = processed / f"{args.area_id}_repair_decisions.json"
    repair_casebook = processed / f"{args.area_id}_repair_casebook.json"
    road_graph = processed / f"{args.area_id}_road_graph.json"
    junction_semantics = processed / f"{args.area_id}_junction_semantics.json"
    junction_areas = processed / f"{args.area_id}_junction_areas.json"
    engineering_reference_lines = processed / f"{args.area_id}_engineering_reference_lines.json"
    optimized_centerlines = processed / f"{args.area_id}_roads_optimized_centerlines.geojson"
    clean_skeleton = processed / f"{args.area_id}_roads_clean_skeleton.geojson"
    clean_skeleton_report = reports / f"{args.area_id}_road_skeleton_repair_report.json"
    junction_geometry_audit = reports / f"{args.area_id}_junction_geometry_audit_report.json"
    junction_area_regularization = reports / f"{args.area_id}_junction_area_regularization_report.json"
    repair_casebook_qa = reports / "qa" / f"{args.area_id}_repair_casebook_qa_report.json"
    manual_overrides = Path(args.manual_overrides) if args.manual_overrides else root / "config" / f"{args.area_id}.manual_overrides.json"

    steps: list[tuple[str, list[str]]] = []
    if not raw_geojson.exists():
        steps.append(("Downloading sample data", [python_cmd(), str(root / "scripts" / "download_overpass.py"), "--config", str(config)]))
    topology_cmd = [python_cmd(), str(root / "scripts" / "topology_repair.py"), "--area-id", args.area_id]
    if args.apply_high_confidence:
        topology_cmd.append("--apply-high-confidence")
    if args.no_manual_overrides:
        topology_cmd.append("--no-manual-overrides")
    elif args.manual_overrides:
        topology_cmd.extend(["--manual-overrides", str(manual_overrides)])
    steps.extend([
        ("L3 topology repair", topology_cmd),
        (
            "L3 repaired-road analysis",
            [
                python_cmd(),
                str(root / "scripts" / "analyze_raw_roads.py"),
                "--area-id",
                args.area_id,
                "--input",
                str(repaired_geojson),
                "--output",
                str(reports / f"{args.area_id}_repaired_analysis.json"),
            ],
        ),
        ("L3 topology repair QA", [python_cmd(), str(root / "scripts" / "run_auto_qa.py"), "--stage", "topology_repair", "--area-id", args.area_id]),
        ("L3 repair casebook QA", [python_cmd(), str(root / "scripts" / "run_repair_casebook.py"), "--area-id", args.area_id]),
        ("L4 road graph", [python_cmd(), str(root / "scripts" / "build_road_graph.py"), "--area-id", args.area_id]),
        ("L4 road graph QA", [python_cmd(), str(root / "scripts" / "run_auto_qa.py"), "--stage", "road_graph", "--area-id", args.area_id]),
        ("L5 junction semantics", [python_cmd(), str(root / "scripts" / "build_junction_semantics.py"), "--area-id", args.area_id]),
        ("L5.5 junction area regularization", [python_cmd(), str(root / "scripts" / "regularize_junction_areas.py"), "--area-id", args.area_id]),
        ("L6 engineering centerline", [python_cmd(), str(root / "scripts" / "optimize_junction_centerlines.py"), "--area-id", args.area_id]),
        ("L6 junction geometry audit", [python_cmd(), str(root / "scripts" / "junction_geometry_audit.py"), "--area-id", args.area_id]),
    ])

    for name, cmd in steps:
        code = run_step(name, cmd, root, log_path)
        if code != 0:
            print(f"[ERROR] {name} failed. See {log_path}")
            return code

    clean_report = clean_skeleton_from_optimized(
        area_id=args.area_id,
        optimized_path=optimized_centerlines,
        output_path=clean_skeleton,
        report_path=clean_skeleton_report,
    )
    print("[RoadSkeleton] L6 clean skeleton artifact...")
    print(json.dumps({
        "output": str(clean_skeleton),
        "feature_count": clean_report["feature_count"],
        "part_counts": clean_report["part_counts"],
        "radius_violation_features": clean_report["radius_violation_features"],
    }, ensure_ascii=False, indent=2))

    houdini_status = "skipped"
    if args.sync_houdini:
        print("[RoadSkeleton] L9 Houdini raw preview + clean skeleton sync...")
        houdini_status, code = sync_houdini_clean_skeleton(
            root,
            args.area_id,
            raw_geojson,
            repaired_geojson,
            clean_skeleton,
            args.host,
            args.port,
        )
        if code != 0 and args.require_houdini:
            return code

    summary = {
        "area_id": args.area_id,
        "stage": "road_skeleton_repair",
        "status": "completed",
        "houdini_status": houdini_status,
        "outputs": {
            "raw_roads": str(raw_geojson),
            "repaired_roads": str(repaired_geojson),
            "repair_candidates": str(repair_candidates),
            "repair_decisions": str(repair_decisions),
            "repair_casebook": str(repair_casebook),
            "road_graph": str(road_graph),
            "junction_semantics": str(junction_semantics),
            "junction_areas": str(junction_areas),
            "engineering_reference_lines": str(engineering_reference_lines),
            "engineering_centerlines": str(optimized_centerlines),
            "clean_skeleton": str(clean_skeleton),
            "clean_skeleton_report": str(clean_skeleton_report),
            "junction_area_regularization": str(junction_area_regularization),
            "junction_geometry_audit": str(junction_geometry_audit),
            "repair_casebook_qa": str(repair_casebook_qa),
            "log": str(log_path),
            "manual_overrides": "" if args.no_manual_overrides else str(manual_overrides),
        },
        "options": {
            "apply_high_confidence": args.apply_high_confidence,
            "manual_overrides_enabled": not args.no_manual_overrides,
        },
        "next_stage": "Houdini construction can start only after the clean skeleton is accepted.",
    }
    summary_path = reports / f"{args.area_id}_road_skeleton_repair_summary.json"
    write_json(summary_path, summary)
    print("[RoadSkeleton] Road repair clean skeleton stage complete")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
