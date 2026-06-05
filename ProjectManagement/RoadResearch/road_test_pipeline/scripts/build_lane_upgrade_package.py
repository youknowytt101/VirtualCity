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
import re
import shutil
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from artifact_manifest import artifact_records


SYSTEM_NAME = "LaneForge"
PACKAGE_SCHEMA = "lane_upgrade_system.standard_lane_package.v1"
DEFAULT_PACKAGE_VERSION = "auto"
PATH_POLICY = "portable_lane_package_paths_v1"
QA_WARNING_SEVERITY_POLICY_ID = "qa_warning_severity_tiers_v1"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def copy_json(src: Path, dst: Path, *, root: Path | None = None) -> dict[str, Any]:
    data = read_json(src)
    if root is not None:
        data = portable_json_paths(data, root=root)
    write_json(dst, data)
    return data


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)


def is_windows_absolute_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value)) or value.startswith("\\\\")


def rebase_legacy_root_path(path: Path, root: Path) -> Path | None:
    raw_parts = re.split(r"[\\/]+", str(path))
    parts = [part for part in raw_parts if part and not re.match(r"^[A-Za-z]:$", part)]
    root_name = root.name.lower()
    for index, part in enumerate(parts):
        if str(part).lower() != root_name:
            continue
        tail = parts[index + 1 :]
        return root.joinpath(*tail)
    return None


def resolve_artifact_path(value: str, root: Path, *, base_dir: Path | None = None) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    candidates: list[Path] = []
    if path.is_absolute() or is_windows_absolute_path(text):
        candidates.append(path)
        rebased = rebase_legacy_root_path(path, root)
        if rebased is not None:
            candidates.append(rebased)
    else:
        if base_dir is not None:
            candidates.append(base_dir / path)
        candidates.append(root / path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1] if candidates else None


def portable_path_string(value: str, root: Path) -> str:
    text = str(value)
    if not is_windows_absolute_path(text) and not Path(text).is_absolute():
        return text
    candidate = resolve_artifact_path(text, root)
    if candidate is None:
        return text
    try:
        return str(candidate.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return text


def portable_json_paths(value: Any, *, root: Path) -> Any:
    if isinstance(value, dict):
        return {key: portable_json_paths(item, root=root) for key, item in value.items()}
    if isinstance(value, list):
        return [portable_json_paths(item, root=root) for item in value]
    if isinstance(value, str):
        return portable_path_string(value, root)
    return value


def next_versioned_name(directory: Path, *, prefix: str, width: int = 4) -> str:
    highest = 0
    if directory.exists():
        for path in directory.iterdir():
            match = re.match(rf"^{re.escape(prefix)}v(\d+)(?:\..*)?$", path.name)
            if not match:
                continue
            highest = max(highest, int(match.group(1)))
    return f"{prefix}v{highest + 1:0{width}d}"


def next_package_version(root: Path, area_id: str) -> str:
    return next_versioned_name(root / "data" / "lane_upgrade_packages" / area_id, prefix="lane_package_")


def qa_gate_from_audit(audit: dict[str, Any]) -> dict[str, Any]:
    gate = audit.get("qa_gate")
    if isinstance(gate, dict) and gate.get("status"):
        return gate

    audit_status = str(audit.get("status") or "pass")
    gate_status = "pass"
    if audit_status == "fail":
        gate_status = "blocker"
    elif audit_status == "warn":
        gate_status = "publishable_warn"
    return {
        "policy_id": f"{QA_WARNING_SEVERITY_POLICY_ID}.legacy_audit_status_fallback",
        "status": gate_status,
        "summary": {
            "publishable_warn": 1 if gate_status == "publishable_warn" else 0,
            "manual_review_required": 0,
            "blocker": 1 if gate_status == "blocker" else 0,
        },
        "entries": [],
        "publish_decision": {
            "research_publish_allowed": gate_status != "blocker",
            "autonomous_production_allowed": gate_status in {"pass", "publishable_warn"},
            "manual_review_required": gate_status == "manual_review_required",
            "blocker": gate_status == "blocker",
        },
    }


def optional_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return read_json(path)


def build_semantic_review_summary(
    *,
    road_graph_report: dict[str, Any],
    lane_attribute_report: dict[str, Any],
    junction_semantics_report: dict[str, Any],
    qa_gate: dict[str, Any],
) -> dict[str, Any]:
    road_metrics = road_graph_report.get("metrics") or {}
    lane_metrics = lane_attribute_report.get("metrics") or {}
    lane_counts = lane_attribute_report.get("counts") or {}
    junction_counts = junction_semantics_report.get("counts") or {}
    qa_entries = [
        entry
        for entry in qa_gate.get("entries", [])
        if str(entry.get("stage") or "") in {"road_graph", "junction_semantics", "lane_attribute_model"}
    ]
    return {
        "schema": "lane_upgrade_system.semantic_review_summary.v1",
        "status": "manual_review_required" if qa_entries else "pass",
        "active_lane_policy": str(lane_attribute_report.get("active_lane_policy") or ""),
        "width_fallback_ratio": road_metrics.get("width_fallback_ratio"),
        "lanes_fallback_ratio": road_metrics.get("lanes_fallback_ratio"),
        "missing_turn_lanes_ratio": lane_metrics.get("missing_turn_lanes_ratio"),
        "lane_count_policy_override_ratio": lane_metrics.get("lane_count_policy_override_ratio"),
        "direction_policy_override_ratio": lane_metrics.get("direction_policy_override_ratio"),
        "source_oneway_ignored_approaches": junction_counts.get("source_oneway_ignored_approaches"),
        "source_oneway_blocked_movements_if_trusted": junction_counts.get("source_oneway_blocked_movements_if_trusted"),
        "turn_lanes_source_counts": lane_counts.get("turn_lanes_source_counts", {}),
        "qa_review_entries": qa_entries,
        "production_note": (
            "Lane geometry is publishable for research when qa_gate allows it, but traffic semantics remain review-gated "
            "until width, lanes, oneway and turn-lanes sources are promoted from temporary policy/fallback inputs."
        ),
    }


def build_package(
    *,
    area_id: str,
    root: Path,
    package_version: str,
    allow_warn: bool = True,
    allow_manual_review: bool = True,
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
    road_graph_report_path = reports / f"{area_id}_road_graph_report.json"
    lane_attribute_report_path = reports / f"{area_id}_lane_attribute_model_report.json"
    junction_semantics_report_path = reports / f"{area_id}_junction_semantics_report.json"
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
    qa_gate = qa_gate_from_audit(audit)
    qa_gate_status = str(qa_gate.get("status") or "pass")
    if audit.get("status") == "fail":
        raise RuntimeError(f"Pipeline audit status is {audit.get('status')}; refusing to publish package.")
    if qa_gate_status == "blocker":
        raise RuntimeError("Pipeline QA gate status is blocker; refusing to publish package.")
    if (audit.get("status") == "warn" or qa_gate_status != "pass") and not allow_warn:
        raise RuntimeError(f"Pipeline QA gate status is {qa_gate_status}; refusing to publish package.")
    if qa_gate_status == "manual_review_required" and not allow_manual_review:
        raise RuntimeError("Pipeline QA gate requires manual review; refusing to publish package.")

    source_artifacts = artifact_records(
        {
            "lane_graph": lane_graph_path,
            "standard_lane_surfaces_source": lane_surface_path,
            "standard_lane_surfaces_obj_source": lane_surface_obj_path,
            "lane_debug_geometry_source": lane_debug_path,
            "pipeline_audit_report": audit_path,
            "lane_graph_report": lane_report_path,
            "lane_surface_report": surface_report_path,
            "road_graph_report": road_graph_report_path,
            "lane_attribute_model_report": lane_attribute_report_path,
            "junction_semantics_report": junction_semantics_report_path,
        },
        root=root,
    )
    lane_graph = read_json(lane_graph_path)
    lanes = lane_graph.get("lanes", [])
    physical_lane_centerlines = lane_graph.get("physical_lane_centerlines", [])
    junctions = lane_graph.get("junctions", [])
    continuity_links = lane_graph.get("continuity_links", [])
    lane_graph_metadata = lane_graph.get("metadata") or {}
    derived_smoothing = lane_graph_metadata.get("derived_lane_centerline_smoothing") or {}
    rounding_style = lane_graph_metadata.get("lane_geometry_rounding_style") or derived_smoothing.get("rounding_style") or {}
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
            "lane_geometry_rounding_style": rounding_style,
            "derived_lane_centerline_smoothing": derived_smoothing,
            "physical_lane_centerlines": lane_graph_metadata.get("physical_lane_centerlines") or {},
        },
        "lanes": lanes,
        "physical_lane_centerlines": physical_lane_centerlines,
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
    copy_json(lane_surface_path, package_dir / "standard_lane_surfaces.geojson", root=root)
    copy_json(lane_debug_path, package_dir / "lane_debug_geometry.geojson", root=root)
    copy_json(audit_path, package_dir / "qa_report.json", root=root)
    copy_json(lane_report_path, package_dir / "lane_graph_report.json", root=root)
    copy_json(surface_report_path, package_dir / "lane_surface_report.json", root=root)
    shutil.copyfile(lane_surface_obj_path, package_dir / "standard_lane_surfaces.obj")
    active_overrides = copy_json(active_overrides_path, package_dir / "active_lane_upgrades.json", root=root) if active_overrides_path.exists() else None
    active_corner_overrides = copy_json(active_corner_overrides_path, package_dir / "active_corner_optimizations.json", root=root) if active_corner_overrides_path.exists() else None
    corner_candidates = copy_json(corner_candidates_path, package_dir / "corner_optimization_candidates.json", root=root) if corner_candidates_path.exists() else None
    corner_report = copy_json(corner_report_path, package_dir / "corner_optimization_report.json", root=root) if corner_report_path.exists() else None
    propagation_plan = None
    propagation_report = None
    if propagation_latest_path.exists():
        propagation_latest = read_json(propagation_latest_path)
        propagation_plan_path = resolve_artifact_path(
            str(propagation_latest.get("latest_plan") or ""),
            root,
            base_dir=propagation_latest_path.parent,
        )
        propagation_report_path = resolve_artifact_path(
            str(propagation_latest.get("latest_report") or ""),
            root,
            base_dir=propagation_latest_path.parent,
        )
        if propagation_plan_path is not None and propagation_plan_path.exists():
            propagation_plan = copy_json(propagation_plan_path, package_dir / "lane_upgrade_propagation_plan.json", root=root)
        if propagation_report_path is not None and propagation_report_path.exists():
            propagation_report = copy_json(propagation_report_path, package_dir / "lane_upgrade_propagation_report.json", root=root)

    surface_report = read_json(surface_report_path)
    lane_report = read_json(lane_report_path)
    semantic_review = build_semantic_review_summary(
        road_graph_report=optional_report(road_graph_report_path),
        lane_attribute_report=optional_report(lane_attribute_report_path),
        junction_semantics_report=optional_report(junction_semantics_report_path),
        qa_gate=qa_gate,
    )
    corner_report_counts = (corner_report or {}).get("counts", {})
    manifest = {
        "type": "standard_lane_package_manifest",
        "metadata": {
            "area_id": area_id,
            "schema": PACKAGE_SCHEMA,
            "system": SYSTEM_NAME,
            "package_version": package_version,
            "path_policy": PATH_POLICY,
            "source_pipeline_root": "",
            "source_pipeline_root_policy": "not_embedded_for_portable_package",
            "qa_status": audit.get("status"),
            "qa_gate_status": qa_gate_status,
            "qa_warning_severity_policy_id": qa_gate.get("policy_id", QA_WARNING_SEVERITY_POLICY_ID),
            "lane_geometry_rounding_style_id": str(rounding_style.get("style_id") or derived_smoothing.get("rounding_style_id") or ""),
            "lane_geometry_rounding_style": rounding_style,
        },
        "human_model": "raw map data -> LaneForge lane upgrade system -> standard lane package -> Houdini construction pipeline",
        "source_artifacts": source_artifacts,
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
            "physical_lane_centerlines": len(physical_lane_centerlines),
            "physical_lane_group_centerlines": sum(
                1 for centerline in physical_lane_centerlines if int(centerline.get("member_count") or 0) > 1
            ),
            "junctions": len(junctions),
            "lane_links": len(lane_links),
            "continuity_links": len(continuity_links),
            "junction_envelope_surfaces": surface_report.get("counts", {}).get("junction_envelope_surfaces", 0),
            "active_lane_upgrades": len((active_overrides or {}).get("active_upgrades", [])),
            "active_corner_optimizations": len((active_corner_overrides or {}).get("active_corner_optimizations", [])),
            "corner_optimization_candidates": len((corner_candidates or {}).get("candidates", [])),
            "corner_optimization_accepted_active": corner_report_counts.get("accepted_active", 0),
            "corner_optimization_accepted_active_candidates": corner_report_counts.get("accepted_active_candidates", 0),
            "corner_optimization_accepted_active_overrides": corner_report_counts.get("accepted_active_overrides", 0),
            "lane_upgrade_propagation_candidates": len((propagation_plan or {}).get("candidates", [])),
            "lane_upgrade_propagation_high_confidence": (propagation_report or {}).get("counts", {}).get("high_confidence_candidates", 0),
        },
        "semantic_review": semantic_review,
        "metrics": {
            "lane_graph": lane_report.get("metrics", {}),
            "lane_surface": surface_report.get("metrics", {}),
            "pipeline_audit": audit.get("metrics", {}),
        },
        "qa_gate": qa_gate,
        "publish_policy": {
            "source_map_data_immutable": True,
            "manual_lane_upgrades_are_transactions": True,
            "derived_lane_centerline_smoothing_is_downstream_geometry": True,
            "unified_lane_geometry_rounding_style_is_downstream_geometry": True,
            "houdini_consumes_package_outputs_only": True,
            "qa_warning_severity_tiers": True,
            "blocker_warnings_refuse_package_publish": True,
            "manual_review_required_warnings_are_marked": True,
        },
    }
    houdini_manifest = {
        "type": "houdini_lane_package_manifest",
        "metadata": {
            "area_id": area_id,
            "schema": "lane_upgrade_system.houdini_manifest.v1",
            "system": SYSTEM_NAME,
            "package_version": package_version,
            "path_policy": PATH_POLICY,
            "qa_gate_status": qa_gate_status,
            "lane_geometry_rounding_style_id": str(rounding_style.get("style_id") or derived_smoothing.get("rounding_style_id") or ""),
        },
        "inputs": {
            "standard_lanes": "standard_lanes.json",
            "standard_junctions": "standard_junctions.json",
            "standard_lane_surfaces": "standard_lane_surfaces.geojson",
            "standard_lane_surfaces_obj": "standard_lane_surfaces.obj",
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
    write_json(package_dir / "houdini_manifest.json", houdini_manifest)
    package_artifacts = artifact_records(
        {
            "standard_lanes": package_dir / "standard_lanes.json",
            "standard_junctions": package_dir / "standard_junctions.json",
            "standard_lane_surfaces": package_dir / "standard_lane_surfaces.geojson",
            "standard_lane_surfaces_obj": package_dir / "standard_lane_surfaces.obj",
            "lane_debug_geometry": package_dir / "lane_debug_geometry.geojson",
            "qa_report": package_dir / "qa_report.json",
            "lane_graph_report": package_dir / "lane_graph_report.json",
            "lane_surface_report": package_dir / "lane_surface_report.json",
            "houdini_manifest": package_dir / "houdini_manifest.json",
        },
        root=root,
    )
    manifest["package_artifacts"] = package_artifacts
    write_json(package_dir / "manifest.json", manifest)
    latest = {
        "area_id": area_id,
        "system": SYSTEM_NAME,
        "latest_package_version": package_version,
        "path_policy": PATH_POLICY,
        "latest_package_dir": package_version,
        "manifest": "manifest.json",
        "qa_gate_status": qa_gate_status,
        "qa_warning_summary": qa_gate.get("summary", {}),
        "source_artifacts": {
            "lane_graph": source_artifacts["lane_graph"],
            "pipeline_audit_report": source_artifacts["pipeline_audit_report"],
        },
    }
    write_json(package_dir.parent / "latest.json", latest)
    return {
        "area_id": area_id,
        "package_version": package_version,
        "package_dir": rel(package_dir, root),
        "manifest": rel(package_dir / "manifest.json", root),
        "path_policy": PATH_POLICY,
        "counts": manifest["counts"],
        "qa_status": audit.get("status"),
        "qa_gate_status": qa_gate_status,
        "qa_warning_summary": qa_gate.get("summary", {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a LaneForge standard lane package.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--version", default=DEFAULT_PACKAGE_VERSION, help="Package version, or 'auto' for the next lane_package_vXXXX.")
    parser.add_argument("--fail-on-warn", action="store_true")
    parser.add_argument("--fail-on-manual-review", action="store_true")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    package_version = next_package_version(root, args.area_id) if args.version == "auto" else args.version
    result = build_package(
        area_id=args.area_id,
        root=root,
        package_version=package_version,
        allow_warn=not args.fail_on_warn,
        allow_manual_review=not args.fail_on_manual_review,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
