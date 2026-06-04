#!/usr/bin/env python3
"""Publish a versioned LaneForge standard lane data package.

The package is the handoff between the lane upgrade system and the downstream
Houdini construction pipeline. It copies normalized lane data into one stable
directory with a manifest, instead of asking Houdini to discover pipeline
internals.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


SYSTEM_NAME = "LaneForge"
PACKAGE_SCHEMA = "lane_upgrade_system.standard_lane_package.v1"
DEFAULT_PACKAGE_VERSION = "lane_package_v0001"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def copy_json(src: Path, dst: Path) -> dict[str, Any]:
    data = read_json(src)
    write_json(dst, data)
    return data


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)


def build_package(
    *,
    area_id: str,
    root: Path,
    package_version: str,
    allow_warn: bool = True,
) -> dict[str, Any]:
    processed = root / "data" / "processed"
    preview = root / "data" / "preview"
    reports = root / "reports"
    package_dir = root / "data" / "lane_upgrade_packages" / area_id / package_version
    package_dir.mkdir(parents=True, exist_ok=True)

    lane_graph_path = processed / f"{area_id}_lane_graph.json"
    lane_surface_path = preview / f"{area_id}_lane_surfaces_v1.geojson"
    lane_surface_obj_path = preview / f"{area_id}_lane_surfaces_v1.obj"
    lane_debug_path = preview / f"{area_id}_lane_geometry_debug.geojson"
    audit_path = reports / f"{area_id}_pipeline_audit_report.json"
    lane_report_path = reports / f"{area_id}_lane_graph_report.json"
    surface_report_path = reports / f"{area_id}_lane_surface_v1_report.json"
    active_overrides_path = processed / f"{area_id}_lane_upgrade_overrides.json"
    active_corner_overrides_path = processed / f"{area_id}_corner_optimization_overrides.json"
    corner_candidates_path = processed / f"{area_id}_corner_optimization_candidates.json"
    corner_report_path = reports / f"{area_id}_corner_optimization_report.json"
    propagation_latest_path = root / "data" / "lane_upgrade_system" / "propagation" / f"{area_id}_latest.json"

    required = [
        lane_graph_path,
        lane_surface_path,
        lane_surface_obj_path,
        lane_debug_path,
        audit_path,
        lane_report_path,
        surface_report_path,
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing package inputs: " + ", ".join(str(path) for path in missing))

    audit = read_json(audit_path)
    if audit.get("status") == "fail" or (audit.get("status") == "warn" and not allow_warn):
        raise RuntimeError(f"Pipeline audit status is {audit.get('status')}; refusing to publish package.")

    lane_graph = read_json(lane_graph_path)
    lanes = lane_graph.get("lanes", [])
    junctions = lane_graph.get("junctions", [])
    continuity_links = lane_graph.get("continuity_links", [])
    lane_links = [
        link
        for junction in junctions
        for connection in junction.get("connections", [])
        for link in connection.get("lane_links", [])
    ]

    standard_lanes = {
        "type": "standard_lanes",
        "metadata": {
            "area_id": area_id,
            "schema": "lane_upgrade_system.standard_lanes.v1",
            "system": SYSTEM_NAME,
            "package_version": package_version,
            "source": rel(lane_graph_path, root),
        },
        "lanes": lanes,
        "continuity_links": continuity_links,
    }
    standard_junctions = {
        "type": "standard_junctions",
        "metadata": {
            "area_id": area_id,
            "schema": "lane_upgrade_system.standard_junctions.v1",
            "system": SYSTEM_NAME,
            "package_version": package_version,
            "source": rel(lane_graph_path, root),
        },
        "junctions": junctions,
    }
    write_json(package_dir / "standard_lanes.json", standard_lanes)
    write_json(package_dir / "standard_junctions.json", standard_junctions)
    copy_json(lane_surface_path, package_dir / "standard_lane_surfaces.geojson")
    copy_json(lane_debug_path, package_dir / "lane_debug_geometry.geojson")
    copy_json(audit_path, package_dir / "qa_report.json")
    copy_json(lane_report_path, package_dir / "lane_graph_report.json")
    copy_json(surface_report_path, package_dir / "lane_surface_report.json")
    shutil.copyfile(lane_surface_obj_path, package_dir / "standard_lane_surfaces.obj")
    active_overrides = copy_json(active_overrides_path, package_dir / "active_lane_upgrades.json") if active_overrides_path.exists() else None
    active_corner_overrides = copy_json(active_corner_overrides_path, package_dir / "active_corner_optimizations.json") if active_corner_overrides_path.exists() else None
    corner_candidates = copy_json(corner_candidates_path, package_dir / "corner_optimization_candidates.json") if corner_candidates_path.exists() else None
    corner_report = copy_json(corner_report_path, package_dir / "corner_optimization_report.json") if corner_report_path.exists() else None
    propagation_plan = None
    propagation_report = None
    if propagation_latest_path.exists():
        propagation_latest = read_json(propagation_latest_path)
        propagation_plan_path = Path(str(propagation_latest.get("latest_plan") or ""))
        propagation_report_path = Path(str(propagation_latest.get("latest_report") or ""))
        if propagation_plan_path.exists():
            propagation_plan = copy_json(propagation_plan_path, package_dir / "lane_upgrade_propagation_plan.json")
        if propagation_report_path.exists():
            propagation_report = copy_json(propagation_report_path, package_dir / "lane_upgrade_propagation_report.json")

    surface_report = read_json(surface_report_path)
    lane_report = read_json(lane_report_path)
    manifest = {
        "type": "standard_lane_package_manifest",
        "metadata": {
            "area_id": area_id,
            "schema": PACKAGE_SCHEMA,
            "system": SYSTEM_NAME,
            "package_version": package_version,
            "source_pipeline_root": str(root),
            "qa_status": audit.get("status"),
        },
        "human_model": "raw map data -> LaneForge lane upgrade system -> standard lane package -> Houdini construction pipeline",
        "contents": {
            "standard_lanes": "standard_lanes.json",
            "standard_junctions": "standard_junctions.json",
            "standard_lane_surfaces": "standard_lane_surfaces.geojson",
            "standard_lane_surfaces_obj": "standard_lane_surfaces.obj",
            "lane_debug_geometry": "lane_debug_geometry.geojson",
            "qa_report": "qa_report.json",
            "lane_graph_report": "lane_graph_report.json",
            "lane_surface_report": "lane_surface_report.json",
            "active_lane_upgrades": "active_lane_upgrades.json" if active_overrides is not None else "",
            "active_corner_optimizations": "active_corner_optimizations.json" if active_corner_overrides is not None else "",
            "corner_optimization_candidates": "corner_optimization_candidates.json" if corner_candidates is not None else "",
            "corner_optimization_report": "corner_optimization_report.json" if corner_report is not None else "",
            "lane_upgrade_propagation_plan": "lane_upgrade_propagation_plan.json" if propagation_plan is not None else "",
            "lane_upgrade_propagation_report": "lane_upgrade_propagation_report.json" if propagation_report is not None else "",
            "houdini_manifest": "houdini_manifest.json",
        },
        "counts": {
            "lanes": len(lanes),
            "junctions": len(junctions),
            "lane_links": len(lane_links),
            "continuity_links": len(continuity_links),
            "junction_envelope_surfaces": surface_report.get("counts", {}).get("junction_envelope_surfaces", 0),
            "active_lane_upgrades": len((active_overrides or {}).get("active_upgrades", [])),
            "active_corner_optimizations": len((active_corner_overrides or {}).get("active_corner_optimizations", [])),
            "corner_optimization_candidates": len((corner_candidates or {}).get("candidates", [])),
            "corner_optimization_accepted_active": (corner_report or {}).get("counts", {}).get("accepted_active", 0),
            "lane_upgrade_propagation_candidates": len((propagation_plan or {}).get("candidates", [])),
            "lane_upgrade_propagation_high_confidence": (propagation_report or {}).get("counts", {}).get("high_confidence_candidates", 0),
        },
        "metrics": {
            "lane_graph": lane_report.get("metrics", {}),
            "lane_surface": surface_report.get("metrics", {}),
            "pipeline_audit": audit.get("metrics", {}),
        },
        "publish_policy": {
            "source_map_data_immutable": True,
            "manual_lane_upgrades_are_transactions": True,
            "houdini_consumes_package_outputs_only": True,
        },
    }
    houdini_manifest = {
        "type": "houdini_lane_package_manifest",
        "metadata": {
            "area_id": area_id,
            "schema": "lane_upgrade_system.houdini_manifest.v1",
            "system": SYSTEM_NAME,
            "package_version": package_version,
        },
        "inputs": {
            "standard_lanes": str(package_dir / "standard_lanes.json"),
            "standard_junctions": str(package_dir / "standard_junctions.json"),
            "standard_lane_surfaces": str(package_dir / "standard_lane_surfaces.geojson"),
            "standard_lane_surfaces_obj": str(package_dir / "standard_lane_surfaces.obj"),
        },
        "expected_houdini_outputs": [
            "OUT_roads_centerlines",
            "OUT_lane_connections_debug",
            "OUT_lane_surfaces_v1",
        ],
        "primitive_groups": [
            "lane_surface_v1",
            "lane_turn_surface_v1",
            "lane_continuity_surface_v1",
            "junction_envelope_surface_v1",
        ],
    }
    write_json(package_dir / "manifest.json", manifest)
    write_json(package_dir / "houdini_manifest.json", houdini_manifest)
    latest = {
        "area_id": area_id,
        "system": SYSTEM_NAME,
        "latest_package_version": package_version,
        "latest_package_dir": str(package_dir),
        "manifest": str(package_dir / "manifest.json"),
    }
    write_json(package_dir.parent / "latest.json", latest)
    return {
        "area_id": area_id,
        "package_version": package_version,
        "package_dir": str(package_dir),
        "manifest": str(package_dir / "manifest.json"),
        "counts": manifest["counts"],
        "qa_status": audit.get("status"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a LaneForge standard lane package.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--version", default=DEFAULT_PACKAGE_VERSION)
    parser.add_argument("--fail-on-warn", action="store_true")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    result = build_package(
        area_id=args.area_id,
        root=root,
        package_version=args.version,
        allow_warn=not args.fail_on_warn,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
