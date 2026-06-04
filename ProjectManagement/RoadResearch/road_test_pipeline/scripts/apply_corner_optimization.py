#!/usr/bin/env python3
"""Apply selected LaneForge corner optimization candidates through QA.

This is the controlled accept path for road-corner geometry. It starts with the
lowest-risk family only:

- degree2_connector_corner
- low risk
- accepted by explicit candidate id, or by an explicit all-matching flag

The command writes active corner overrides, rebuilds the structured pipeline,
publishes the next package and refreshes the SVG QA view.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


APPLICATION_SCHEMA = "lane_upgrade_system.corner_optimization_application.v1"
OVERRIDE_SCHEMA = "lane_upgrade_system.corner_optimization_overrides.v1"
DEFAULT_POLICY = "low_risk_degree2_connector_only_v1"
INTERNAL_BEND_POLICY = "low_risk_internal_centerline_bend_smoothing_v1"
POLICY_CONFIGS: dict[str, dict[str, Any]] = {
    DEFAULT_POLICY: {
        "candidate_types": {"degree2_connector_corner"},
        "risk_levels": {"low"},
        "allowed_actions": {"candidate_for_auto_fillet_after_review", "active_geometry_transaction"},
        "min_turn_angle_deg": 18.0,
        "max_nearest_junction_distance_m": None,
    },
    INTERNAL_BEND_POLICY: {
        "candidate_types": {"internal_centerline_bend"},
        "risk_levels": {"low"},
        "allowed_actions": {"candidate_for_smoothing_after_review", "active_geometry_transaction"},
        "min_turn_angle_deg": 28.0,
        "max_nearest_junction_distance_m": None,
    },
}


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def python_cmd() -> str:
    return sys.executable


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def next_versioned_path(directory: Path, prefix: str) -> tuple[str, Path]:
    highest = 0
    if directory.exists():
        for path in directory.glob(f"{prefix}v*.json"):
            match = re.match(rf"^{re.escape(prefix)}v(\d+)$", path.stem)
            if match:
                highest = max(highest, int(match.group(1)))
    version = f"v{highest + 1:04d}"
    return version, directory / f"{prefix}{version}.json"


def next_versioned_name(directory: Path, *, prefix: str, width: int = 4) -> str:
    highest = 0
    if directory.exists():
        for path in directory.iterdir():
            match = re.match(rf"^{re.escape(prefix)}v(\d+)(?:\..*)?$", path.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return f"{prefix}v{highest + 1:0{width}d}"


def next_package_version(root: Path, area_id: str) -> str:
    return next_versioned_name(root / "data" / "lane_upgrade_packages" / area_id, prefix="lane_package_")


def policy_config(policy_name: str) -> dict[str, Any]:
    if policy_name not in POLICY_CONFIGS:
        raise ValueError(f"Unknown corner optimization policy: {policy_name}")
    return POLICY_CONFIGS[policy_name]


def degree2_candidate_key(candidate: dict[str, Any]) -> tuple[str, tuple[str, str]]:
    node_id = str(candidate.get("node_id") or "")
    edge_ids = [str(candidate.get("from_edge_id") or ""), str(candidate.get("to_edge_id") or "")]
    a, b = sorted(edge_ids)
    return node_id, (a, b)


def degree2_active_override_key(item: dict[str, Any]) -> tuple[str, tuple[str, str]]:
    node_id = str(item.get("node_id") or "")
    edge_ids = [str(item.get("from_edge_id") or ""), str(item.get("to_edge_id") or "")]
    a, b = sorted(edge_ids)
    return node_id, (a, b)


def internal_bend_candidate_key(candidate: dict[str, Any]) -> tuple[str, int]:
    source_edge_id = str(candidate.get("source_edge_id") or "")
    try:
        point_index = int(candidate.get("point_index"))
    except (TypeError, ValueError):
        point_index = -1
    return source_edge_id, point_index


def internal_bend_active_override_key(item: dict[str, Any]) -> tuple[str, int]:
    source_edge_id = str(item.get("source_edge_id") or "")
    try:
        point_index = int(item.get("point_index"))
    except (TypeError, ValueError):
        point_index = -1
    return source_edge_id, point_index


def candidate_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    candidate_type = str(candidate.get("candidate_type") or "")
    if candidate_type == "internal_centerline_bend":
        source_edge_id, point_index = internal_bend_candidate_key(candidate)
        return candidate_type, source_edge_id, point_index
    node_id, edge_pair = degree2_candidate_key(candidate)
    return candidate_type or "degree2_connector_corner", node_id, edge_pair[0], edge_pair[1]


def active_override_key(item: dict[str, Any]) -> tuple[Any, ...]:
    candidate_type = str(item.get("candidate_type") or "")
    if candidate_type == "internal_centerline_bend":
        source_edge_id, point_index = internal_bend_active_override_key(item)
        return candidate_type, source_edge_id, point_index
    node_id, edge_pair = degree2_active_override_key(item)
    return candidate_type or "degree2_connector_corner", node_id, edge_pair[0], edge_pair[1]


def candidate_has_required_geometry(candidate: dict[str, Any]) -> bool:
    candidate_type = str(candidate.get("candidate_type") or "")
    if candidate_type == "internal_centerline_bend":
        source_edge_id, point_index = internal_bend_candidate_key(candidate)
        context = candidate.get("context_polyline_xz") or []
        return bool(source_edge_id and point_index >= 1 and len(context) >= 3)
    node_id, edge_pair = degree2_candidate_key(candidate)
    return bool(node_id and all(edge_pair))


def candidate_matches_policy(candidate: dict[str, Any], config: dict[str, Any]) -> bool:
    if str(candidate.get("candidate_type") or "") not in config["candidate_types"]:
        return False
    if str(candidate.get("risk_level") or "") not in config["risk_levels"]:
        return False
    if str(candidate.get("recommended_action") or "") not in config["allowed_actions"]:
        return False
    if float(candidate.get("turn_angle_deg") or 0.0) < float(config["min_turn_angle_deg"]):
        return False
    max_junction_distance = config.get("max_nearest_junction_distance_m")
    if max_junction_distance is not None:
        if float(candidate.get("nearest_junction_distance_m") or 0.0) > float(max_junction_distance):
            return False
    return candidate_has_required_geometry(candidate)


def selected_candidates(
    candidate_doc: dict[str, Any],
    *,
    candidate_ids: set[str],
    config: dict[str, Any],
    all_matching_policy: bool,
) -> list[dict[str, Any]]:
    if not candidate_ids and not all_matching_policy:
        raise ValueError("--candidate-id is required unless --all-matching-policy is explicitly set")
    selected: list[dict[str, Any]] = []
    for candidate in candidate_doc.get("candidates", []):
        candidate_id = str(candidate.get("candidate_id") or "")
        if candidate_ids and candidate_id not in candidate_ids:
            continue
        if not candidate_matches_policy(candidate, config):
            continue
        selected.append(candidate)
    return selected


def read_active_overrides(path: Path, area_id: str) -> dict[str, Any]:
    if path.exists():
        return read_json(path)
    return {
        "type": "corner_optimization_overrides",
        "metadata": {
            "area_id": area_id,
            "schema": OVERRIDE_SCHEMA,
            "system": "LaneForge",
        },
        "active_corner_optimizations": [],
    }


def upsert_active_overrides(
    *,
    path: Path,
    area_id: str,
    selected: list[dict[str, Any]],
    application_id: str,
    policy_name: str,
    reason: str,
    reviewer: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    data = read_active_overrides(path, area_id)
    active = [
        item
        for item in data.get("active_corner_optimizations", [])
        if bool(item.get("enabled", True))
    ]
    active_keys = {active_override_key(item) for item in active}
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for index, candidate in enumerate(selected):
        candidate_type = str(candidate.get("candidate_type") or "")
        key = candidate_key(candidate)
        if key in active_keys:
            skipped.append({
                "candidate_id": candidate.get("candidate_id"),
                "node_id": candidate.get("node_id", ""),
                "source_edge_id": candidate.get("source_edge_id", ""),
                "point_index": candidate.get("point_index", ""),
                "reason": "corner_already_active",
            })
            continue
        common = {
            "enabled": True,
            "corner_optimization_id": f"{application_id}_corner_{index:04d}",
            "application_id": application_id,
            "candidate_id": str(candidate.get("candidate_id") or ""),
            "candidate_type": candidate_type,
            "suggested_cut_m": float(candidate.get("suggested_cut_m") or 0.0),
            "suggested_radius_m": float(candidate.get("suggested_radius_m") or 0.0),
            "turn_angle_deg": float(candidate.get("turn_angle_deg") or 0.0),
            "policy": policy_name,
            "reason": reason,
            "reviewer": reviewer,
            "status": "accepted_for_geometry_apply",
            "created_at_local": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        if candidate_type == "internal_centerline_bend":
            item = {
                **common,
                "source_edge_id": str(candidate.get("source_edge_id") or ""),
                "canonical_road_id": str(candidate.get("canonical_road_id") or ""),
                "point_index": int(candidate.get("point_index") or 0),
                "center_xz": candidate.get("center_xz") or [],
                "context_polyline_xz": candidate.get("context_polyline_xz") or [],
                "target_geometry": "optimized_internal_centerline_bend_smoothing",
            }
        else:
            item = {
                **common,
                "node_id": str(candidate.get("node_id") or ""),
                "from_edge_id": str(candidate.get("from_edge_id") or ""),
                "to_edge_id": str(candidate.get("to_edge_id") or ""),
                "from_canonical_road_id": str(candidate.get("from_canonical_road_id") or ""),
                "to_canonical_road_id": str(candidate.get("to_canonical_road_id") or ""),
                "target_geometry": "optimized_corner_fillet",
            }
        data.setdefault("active_corner_optimizations", []).append(item)
        active_keys.add(key)
        created.append(item)
    data["metadata"] = {
        **dict(data.get("metadata") or {}),
        "area_id": area_id,
        "schema": OVERRIDE_SCHEMA,
        "system": "LaneForge",
        "updated_at_local": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    write_json(path, data)
    return data, created, skipped


def run_command(name: str, cmd: list[str], cwd: Path, log_path: Path) -> str:
    print(f"[LaneForge] {name}...")
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
    if proc.returncode != 0:
        raise RuntimeError(f"{name} failed with exit code {proc.returncode}; see {log_path}")
    return proc.stdout or ""


def corner_geometry_snapshot(path: Path, selected: list[dict[str, Any]]) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = read_json(path)
    node_ids = {str(candidate.get("node_id") or "") for candidate in selected if str(candidate.get("node_id") or "")}
    edge_ids = {
        str(candidate.get("source_edge_id") or "")
        for candidate in selected
        if str(candidate.get("candidate_type") or "") == "internal_centerline_bend"
        and str(candidate.get("source_edge_id") or "")
    }
    matches: list[dict[str, Any]] = []
    approach_matches: list[dict[str, Any]] = []
    for feature in data.get("features", []):
        props = feature.get("properties") or {}
        part = str(props.get("vc_part") or "")
        if part == "optimized_corner_fillet":
            if node_ids and str(props.get("corner_node_id") or "") not in node_ids:
                continue
            matches.append({
                "corner_node_id": props.get("corner_node_id"),
                "corner_id": props.get("corner_id"),
                "from_edge_id": props.get("from_edge_id"),
                "to_edge_id": props.get("to_edge_id"),
                "cut_m": props.get("cut_m"),
                "arc_radius_m": props.get("arc_radius_m"),
                "corner_optimization_source": props.get("corner_optimization_source"),
                "corner_optimization_candidate_id": props.get("corner_optimization_candidate_id"),
            })
        elif part == "optimized_approach_centerline":
            source_edge_id = str(props.get("source_edge_id") or "")
            if source_edge_id not in edge_ids:
                continue
            coords = (feature.get("geometry") or {}).get("coordinates") or []
            approach_matches.append({
                "source_edge_id": source_edge_id,
                "coordinate_count": len(coords),
                "internal_bend_smoothing_count": props.get("internal_bend_smoothing_count", 0),
                "internal_bend_smoothing_candidate_ids": props.get("internal_bend_smoothing_candidate_ids", ""),
            })
    return {
        "corner_fillets": len(matches),
        "matched_corner_fillets": matches,
        "internal_bend_approaches": len(approach_matches),
        "matched_internal_bend_approaches": approach_matches,
    }


def apply_corner_optimizations(
    *,
    root: Path,
    area_id: str,
    candidates_path: Path,
    candidate_ids: set[str],
    policy_name: str,
    reason: str,
    reviewer: str,
    dry_run: bool,
    no_rebuild: bool,
    with_houdini: bool,
    all_matching_policy: bool,
) -> dict[str, Any]:
    config = policy_config(policy_name)
    candidate_doc = read_json(candidates_path)
    selected = selected_candidates(
        candidate_doc,
        candidate_ids=candidate_ids,
        config=config,
        all_matching_policy=all_matching_policy,
    )
    version, application_path = next_versioned_path(
        root / "data" / "lane_upgrade_system" / "corner_applications",
        f"{area_id}_corner_optimization_application_",
    )
    application_id = f"corner_optimization_application_{version}"
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    log_path = reports / f"{area_id}_corner_optimization_application_{version}.log"
    log_path.write_text(f"[LaneForge] corner optimization application started {time.strftime('%Y-%m-%d %H:%M:%S')}\n", encoding="utf-8")
    processed = root / "data" / "processed"
    active_overrides_path = processed / f"{area_id}_corner_optimization_overrides.json"
    optimized_centerlines_path = processed / f"{area_id}_roads_optimized_centerlines.geojson"
    package_version = next_package_version(root, area_id)
    before_snapshot = corner_geometry_snapshot(optimized_centerlines_path, selected)

    application: dict[str, Any] = {
        "type": "corner_optimization_application",
        "metadata": {
            "area_id": area_id,
            "schema": APPLICATION_SCHEMA,
            "system": "LaneForge",
            "version": version,
            "application_id": application_id,
            "policy": policy_name,
        },
        "source_candidates": str(candidates_path),
        "selection_policy": {
            "candidate_ids": sorted(candidate_ids),
            "all_matching_policy": all_matching_policy,
            "policy": policy_name,
        },
        "status": "dry_run" if dry_run else "running",
        "selected_candidates": selected,
        "before_corner_snapshot": before_snapshot,
        "planned_package_version": package_version,
        "log": str(log_path),
    }

    if dry_run or not selected:
        application["status"] = "dry_run" if dry_run else "no_candidates"
        write_json(application_path, application)
        return application

    _active_doc, created_overrides, skipped_existing = upsert_active_overrides(
        path=active_overrides_path,
        area_id=area_id,
        selected=selected,
        application_id=application_id,
        policy_name=policy_name,
        reason=reason,
        reviewer=reviewer,
    )
    application["created_overrides"] = created_overrides
    application["skipped_existing"] = skipped_existing
    application["active_overrides_path"] = str(active_overrides_path)

    if not created_overrides:
        application["status"] = "no_new_overrides"
        write_json(application_path, application)
        return application

    if no_rebuild:
        application["status"] = "applied_without_rebuild"
        write_json(application_path, application)
        return application

    rebuild_cmd = [python_cmd(), str(root / "scripts" / "rebuild_road_test.py"), "--area-id", area_id]
    if not with_houdini:
        rebuild_cmd.append("--skip-houdini")
    package_cmd = [
        python_cmd(),
        str(root / "scripts" / "build_lane_upgrade_package.py"),
        "--area-id",
        area_id,
        "--version",
        package_version,
    ]
    svg_cmd = [python_cmd(), str(root / "scripts" / "export_lane_graph_svg.py"), "--area-id", area_id]

    run_command("Rebuilding after accepted corner optimization", rebuild_cmd, root, log_path)
    package_stdout = run_command("Publishing package with accepted corner optimization", package_cmd, root, log_path)
    run_command("Refreshing SVG QA view", svg_cmd, root, log_path)

    audit_path = reports / f"{area_id}_pipeline_audit_report.json"
    corner_report_path = reports / f"{area_id}_corner_optimization_report.json"
    svg_report_path = reports / f"{area_id}_lane_graph_svg_report.json"
    application.update({
        "status": "completed",
        "after_corner_snapshot": corner_geometry_snapshot(optimized_centerlines_path, selected),
        "pipeline_audit": read_json(audit_path) if audit_path.exists() else {},
        "corner_optimization_report": read_json(corner_report_path) if corner_report_path.exists() else {},
        "published_package": json.loads(package_stdout),
        "svg_report": read_json(svg_report_path) if svg_report_path.exists() else {},
    })
    write_json(application_path, application)
    return application


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply selected LaneForge corner optimization candidates.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--candidates", default="")
    parser.add_argument("--candidate-id", action="append", default=[])
    parser.add_argument("--policy", choices=sorted(POLICY_CONFIGS), default=DEFAULT_POLICY)
    parser.add_argument("--reason", default="accepted low-risk corner optimization candidate")
    parser.add_argument("--reviewer", default="codex")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-rebuild", action="store_true")
    parser.add_argument("--with-houdini", action="store_true")
    parser.add_argument("--all-matching-policy", action="store_true")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    processed = root / "data" / "processed"
    candidates_path = Path(args.candidates) if args.candidates else processed / f"{args.area_id}_corner_optimization_candidates.json"
    result = apply_corner_optimizations(
        root=root,
        area_id=args.area_id,
        candidates_path=candidates_path,
        candidate_ids={str(item) for item in args.candidate_id if str(item)},
        policy_name=args.policy,
        reason=args.reason,
        reviewer=args.reviewer,
        dry_run=args.dry_run,
        no_rebuild=args.no_rebuild,
        with_houdini=args.with_houdini,
        all_matching_policy=args.all_matching_policy,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
