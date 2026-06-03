#!/usr/bin/env python3
"""Transactionally apply publishable junction connector replacements."""

from __future__ import annotations

import argparse
import copy
import json
import tempfile
from pathlib import Path
from typing import Any

import junction_geometry_audit as jga
import optimize_junction_centerlines as oc


PROTECTED_ISSUES = {
    "radius_below_design_min",
    "junction_trim_spread_excess",
    "endpoint_too_close_to_junction_center",
    "endpoint_too_far_from_junction_center",
    "turn_sweep_abnormal",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def to_feature_coords(points_xz: list[list[float]], origin_lon: float, origin_lat: float) -> list[list[float]]:
    coords = []
    for point in points_xz:
        lon, lat = oc.to_lonlat(float(point[0]), float(point[1]), origin_lon, origin_lat)
        coords.append([round(lon, 8), round(lat, 8)])
    return coords


def candidate_by_id(case: dict[str, Any], candidate_id: str) -> dict[str, Any] | None:
    for candidate in case.get("candidates", []):
        if candidate.get("candidate_id") == candidate_id:
            return candidate
    return None


def candidate_arc_geometry(family: str) -> str:
    if family == "circular_arc_exact":
        return "circular_arc"
    if family == "param_poly3_hermite":
        return "param_poly3_hermite"
    if family == "biarc_g1_proxy":
        return "biarc_g1_proxy"
    return family or "solver_v2_replacement"


def update_connector_feature(
    feature: dict[str, Any],
    case: dict[str, Any],
    candidate: dict[str, Any],
    origin_lon: float,
    origin_lat: float,
) -> dict[str, Any]:
    updated = copy.deepcopy(feature)
    points_xz = candidate.get("points_xz") or []
    if len(points_xz) < 2:
        raise ValueError(f"Candidate {candidate.get('candidate_id')} has no retained replacement points.")

    metrics = candidate.get("metrics") or {}
    props = dict(updated.get("properties") or {})
    family = str(candidate.get("family") or "")
    updated["geometry"] = {
        "type": "LineString",
        "coordinates": to_feature_coords(points_xz, origin_lon, origin_lat),
    }
    props.update({
        "arc_geometry": candidate_arc_geometry(family),
        "arc_fit_status": "solver_v2_transaction_replacement",
        "arc_radius_m": float(metrics.get("min_radius_m") or 0.0),
        "arc_center_x": None,
        "arc_center_z": None,
        "arc_sweep_deg": float(props.get("arc_sweep_deg") or 0.0),
        "arc_sample_count": int(metrics.get("sample_count") or len(points_xz)),
        "arc_design_min_radius_m": float(metrics.get("design_min_radius_m") or 0.0),
        "arc_radius_margin_m": float(metrics.get("radius_margin_m") or 0.0),
        "connector_solver_v2_candidate_id": str(candidate.get("candidate_id") or ""),
        "connector_solver_v2_family": family,
        "connector_solver_v2_score": float(candidate.get("score") or 0.0),
        "connector_solver_v2_status": str(candidate.get("status") or ""),
        "connector_replacement_transaction": "accepted_trial",
    })
    updated["properties"] = props
    return updated


def issue_total(report: dict[str, Any]) -> int:
    return sum(int(value) for value in (report.get("metrics", {}).get("issue_counts") or {}).values())


def issue_count(report: dict[str, Any], issue: str) -> int:
    return int((report.get("metrics", {}).get("issue_counts") or {}).get(issue, 0))


def audit_checks(baseline: dict[str, Any], trial: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(check_id: str, passed: bool, before: Any, after: Any, message: str) -> None:
        checks.append({
            "check_id": check_id,
            "status": "pass" if passed else "fail",
            "before": before,
            "after": after,
            "message": message,
        })

    baseline_metrics = baseline.get("metrics", {})
    trial_metrics = trial.get("metrics", {})
    add(
        "connector_count_stable",
        int(trial_metrics.get("connectors") or 0) == int(baseline_metrics.get("connectors") or 0),
        int(baseline_metrics.get("connectors") or 0),
        int(trial_metrics.get("connectors") or 0),
        "Replacement must not add or remove connector primitives.",
    )
    add(
        "total_issue_count_no_regression",
        issue_total(trial) <= issue_total(baseline),
        issue_total(baseline),
        issue_total(trial),
        "Replacement must not increase total junction geometry audit issues.",
    )
    for issue in sorted(PROTECTED_ISSUES):
        add(
            f"{issue}_no_regression",
            issue_count(trial, issue) <= issue_count(baseline, issue),
            issue_count(baseline, issue),
            issue_count(trial, issue),
            f"Replacement must not increase {issue}.",
        )
    return checks


def apply_replacements(
    *,
    area_id: str,
    root: Path,
    optimized_path: Path,
    candidates_path: Path,
    output_path: Path,
    report_path: Path,
    audit_output_path: Path,
) -> dict[str, Any]:
    optimized = read_json(optimized_path)
    candidate_doc = read_json(candidates_path)
    meta = optimized.get("metadata") or {}
    origin_lon = float(meta["origin_lon"])
    origin_lat = float(meta["origin_lat"])

    ready_cases = [case for case in candidate_doc.get("cases", []) if bool(case.get("replacement_ready"))]
    replacements = {}
    rejected_candidates = []
    for case in ready_cases:
        candidate_id = str(case.get("best_replacement_candidate_id") or "")
        candidate = candidate_by_id(case, candidate_id)
        if candidate is None:
            rejected_candidates.append({
                "connector_id": case.get("connector_id", ""),
                "candidate_id": candidate_id,
                "reason": "missing_candidate",
            })
            continue
        if not candidate.get("points_retained") or len(candidate.get("points_xz") or []) < 2:
            rejected_candidates.append({
                "connector_id": case.get("connector_id", ""),
                "candidate_id": candidate_id,
                "reason": "candidate_points_not_retained",
            })
            continue
        replacements[str(case.get("connector_id") or "")] = (case, candidate)

    trial = copy.deepcopy(optimized)
    applied_trial_ids = []
    for feature_index, feature in enumerate(trial.get("features", [])):
        props = feature.get("properties") or {}
        connector_id = str(props.get("connector_id") or "")
        if connector_id not in replacements:
            continue
        case, candidate = replacements[connector_id]
        trial["features"][feature_index] = update_connector_feature(feature, case, candidate, origin_lon, origin_lat)
        applied_trial_ids.append(connector_id)

    trial.setdefault("metadata", {})
    trial["metadata"].update({
        "connector_replacement_transaction": "trial",
        "connector_replacement_source": str(candidates_path),
        "connector_replacement_trial_count": len(applied_trial_ids),
    })

    baseline_report_path = report_path.with_name(f"{area_id}_junction_connector_replacement_baseline_audit_report.json")
    baseline_audit = jga.audit(area_id, root, baseline_report_path, optimized_path=optimized_path)
    with tempfile.TemporaryDirectory(prefix="road_connector_replacement_") as tmp_dir:
        trial_path = Path(tmp_dir) / f"{area_id}_roads_optimized_centerlines_trial.geojson"
        write_json(trial_path, trial)
        trial_audit = jga.audit(area_id, root, audit_output_path, optimized_path=trial_path)
    trial_audit.setdefault("inputs", {})["optimized_centerlines"] = "temporary_connector_replacement_trial.geojson"
    trial_audit["inputs"]["optimized_centerlines_note"] = (
        "The trial GeoJSON is created in a temporary directory; the random local temp path is omitted for reproducible reports."
    )
    write_json(audit_output_path, trial_audit)

    checks = audit_checks(baseline_audit, trial_audit)
    accepted = bool(applied_trial_ids) and all(check["status"] == "pass" for check in checks)
    if accepted:
        trial["metadata"].update({
            "connector_replacement_transaction": "accepted",
            "connector_replacement_accepted_count": len(applied_trial_ids),
        })
        write_json(output_path, trial)

    report = {
        "area_id": area_id,
        "stage": "junction_connector_replacement_transaction_v1",
        "status": "accepted" if accepted else "no_op" if not applied_trial_ids else "rejected",
        "inputs": {
            "optimized_centerlines": str(optimized_path),
            "candidates": str(candidates_path),
        },
        "outputs": {
            "optimized_centerlines": str(output_path) if accepted else "",
            "report": str(report_path),
            "trial_audit": str(audit_output_path),
            "baseline_audit": str(baseline_report_path),
        },
        "counts": {
            "replacement_ready_cases": len(ready_cases),
            "trial_replacements": len(applied_trial_ids),
            "accepted_replacements": len(applied_trial_ids) if accepted else 0,
            "candidate_rejections": len(rejected_candidates),
        },
        "applied_trial_connector_ids": sorted(applied_trial_ids),
        "rejected_candidates": rejected_candidates,
        "audit_checks": checks,
        "baseline_metrics": baseline_audit.get("metrics", {}),
        "trial_metrics": trial_audit.get("metrics", {}),
        "note": (
            "Accepted replacements are written only when audit metrics do not regress. "
            "Rejected/no-op transactions leave optimized centerlines unchanged."
        ),
    }
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Transactionally apply safe connector solver replacements.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--optimized-centerlines", default="")
    parser.add_argument("--candidates", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--report", default="")
    parser.add_argument("--trial-audit-report", default="")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    processed = root / "data" / "processed"
    reports = root / "reports"
    optimized_path = Path(args.optimized_centerlines) if args.optimized_centerlines else processed / f"{args.area_id}_roads_optimized_centerlines.geojson"
    candidates_path = Path(args.candidates) if args.candidates else processed / f"{args.area_id}_junction_connector_candidates.json"
    output_path = Path(args.output) if args.output else optimized_path
    report_path = Path(args.report) if args.report else reports / f"{args.area_id}_junction_connector_replacement_report.json"
    audit_output_path = (
        Path(args.trial_audit_report)
        if args.trial_audit_report
        else reports / f"{args.area_id}_junction_connector_replacement_trial_audit_report.json"
    )
    report = apply_replacements(
        area_id=args.area_id,
        root=root,
        optimized_path=optimized_path,
        candidates_path=candidates_path,
        output_path=output_path,
        report_path=report_path,
        audit_output_path=audit_output_path,
    )
    print(json.dumps({
        "area_id": args.area_id,
        "status": report["status"],
        "counts": report["counts"],
        "audit_checks": report["audit_checks"],
        "outputs": report["outputs"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
