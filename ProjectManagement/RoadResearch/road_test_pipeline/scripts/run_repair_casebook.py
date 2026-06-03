#!/usr/bin/env python3
"""Replay topology repair regression cases.

The casebook protects known false positives and rejected high-confidence
repairs. It runs after the conservative base repair state is reconstructed from
raw roads, then replays each case against the transactional repair validator.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

import topology_repair as tr


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def build_base_repaired_roads(input_path: Path) -> tuple[list[tr.RoadFeature], dict[str, Any]]:
    fc, roads, _origin_lon, _origin_lat = tr.load_roads(input_path)
    local_bbox = tr.local_bbox_from_metadata(fc, _origin_lon, _origin_lat)
    duplicate_points_removed = 0
    for road in roads:
        road.local, removed = tr.remove_adjacent_duplicates(road.local)
        duplicate_points_removed += removed

    endpoint_snaps = tr.apply_endpoint_snaps(roads)
    endpoint_to_edge_snaps = tr.apply_endpoint_to_edge_snaps(roads)
    intersection_splits = tr.apply_intersection_splits(roads)
    short_edges_before = tr.count_short_segments(roads, tr.SHORT_EDGE_M)
    short_edge_cleanup = tr.apply_short_edge_cleanup(roads, local_bbox)
    return roads, {
        "duplicate_points_removed": duplicate_points_removed,
        "endpoint_snaps": endpoint_snaps,
        "endpoint_to_edge_snaps": endpoint_to_edge_snaps,
        "intersection_split_insertions": intersection_splits,
        "short_edges_before_cleanup": short_edges_before,
        **short_edge_cleanup,
    }


def force_operation_from_forbid(operation: dict[str, Any]) -> dict[str, Any] | None:
    action = str(operation.get("action") or "").strip().lower()
    force = dict(operation)
    force["id"] = f"replay_{operation.get('id') or action}"
    if action == "forbid_snap_endpoint_to_edge":
        force["action"] = "force_snap_endpoint_to_edge"
        return force
    if action == "forbid_connect":
        force["action"] = "force_connect"
        return force
    return None


def case_check(case_id: str, check_id: str, passed: bool, message: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    result = {
        "case_id": case_id,
        "check_id": check_id,
        "status": "pass" if passed else "fail",
        "message": message,
    }
    if extra:
        result.update(extra)
    return result


def replay_manual_override_case(
    case: dict[str, Any],
    base_roads: list[tr.RoadFeature],
    manual_override_ops: list[dict[str, Any]],
) -> dict[str, Any]:
    case_id = str(case.get("case_id") or "")
    operation = dict(case.get("operation") or {})
    force_op = force_operation_from_forbid(operation)
    checks = []

    if force_op is None:
        checks.append(case_check(case_id, "supported_manual_override_replay", False, "Unsupported manual override action for replay."))
        return {"case_id": case_id, "status": "fail", "checks": checks}

    blocked = tr.operation_signature(force_op) in tr.forbidden_signatures(manual_override_ops)
    checks.append(case_check(
        case_id,
        "manual_override_blocks_candidate",
        blocked,
        "Manual override must still block the corresponding force operation.",
    ))

    trial_roads = copy.deepcopy(base_roads)
    trial_result = tr.transactional_apply_operation(trial_roads, force_op, "casebook_replay")
    accepted = trial_result.get("transaction_status") == "accepted"
    checks.append(case_check(
        case_id,
        "transaction_does_not_accept",
        not accepted,
        "Known false-positive force operation must not be accepted by transactional validation.",
        {"transaction_status": trial_result.get("transaction_status"), "operation_status": trial_result.get("status")},
    ))

    status = "pass" if all(check["status"] == "pass" for check in checks) else "fail"
    return {
        "case_id": case_id,
        "case_type": case.get("case_type", ""),
        "status": status,
        "checks": checks,
        "trial_result": trial_result,
    }


def replay_rejected_high_confidence_case(case: dict[str, Any], base_roads: list[tr.RoadFeature]) -> dict[str, Any]:
    case_id = str(case.get("case_id") or "")
    operation = dict(case.get("operation_result") or {})
    if not operation:
        check = case_check(case_id, "has_operation_result", False, "Rejected high-confidence case has no operation_result.")
        return {"case_id": case_id, "status": "fail", "checks": [check]}

    trial_roads = copy.deepcopy(base_roads)
    trial_result = tr.transactional_apply_operation(trial_roads, operation, "casebook_replay")
    accepted = trial_result.get("transaction_status") == "accepted"
    check = case_check(
        case_id,
        "transaction_does_not_accept",
        not accepted,
        "Rejected high-confidence operation must remain rejected until source data or validators change.",
        {"transaction_status": trial_result.get("transaction_status"), "operation_status": trial_result.get("status")},
    )
    return {
        "case_id": case_id,
        "case_type": case.get("case_type", ""),
        "status": check["status"],
        "checks": [check],
        "trial_result": trial_result,
    }


def run_casebook(
    *,
    area_id: str,
    input_path: Path,
    casebook_path: Path,
    manual_overrides_path: Path | None,
    report_path: Path,
) -> dict[str, Any]:
    casebook = tr.read_json(casebook_path)
    manual_override_ops, manual_override_info = tr.load_manual_override_ops(manual_overrides_path)
    base_roads, base_repair_counts = build_base_repaired_roads(input_path)
    cases = casebook.get("cases") or []

    results = []
    for case in cases:
        case_type = str(case.get("case_type") or "")
        if case_type == "manual_override_regression":
            results.append(replay_manual_override_case(case, base_roads, manual_override_ops))
        elif case_type == "rejected_high_confidence_regression":
            results.append(replay_rejected_high_confidence_case(case, base_roads))
        else:
            results.append({
                "case_id": str(case.get("case_id") or ""),
                "case_type": case_type,
                "status": "fail",
                "checks": [case_check(str(case.get("case_id") or ""), "supported_case_type", False, f"Unsupported case_type {case_type!r}.")],
            })

    status = "pass" if all(result.get("status") == "pass" for result in results) else "fail"
    report = {
        "area_id": area_id,
        "stage": "repair_casebook_qa",
        "status": status,
        "input": str(input_path),
        "casebook": str(casebook_path),
        "manual_overrides": manual_override_info,
        "base_repair_counts": base_repair_counts,
        "case_count": len(results),
        "pass_count": sum(1 for result in results if result.get("status") == "pass"),
        "fail_count": sum(1 for result in results if result.get("status") == "fail"),
        "results": results,
    }
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay road repair regression casebook.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--input", default="")
    parser.add_argument("--casebook", default="")
    parser.add_argument("--manual-overrides", default="")
    parser.add_argument("--no-manual-overrides", action="store_true")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    input_path = Path(args.input) if args.input else root / "data" / "processed" / f"{args.area_id}_roads_raw.geojson"
    casebook_path = Path(args.casebook) if args.casebook else root / "data" / "processed" / f"{args.area_id}_repair_casebook.json"
    if args.no_manual_overrides:
        manual_overrides_path = None
    elif args.manual_overrides:
        manual_overrides_path = Path(args.manual_overrides)
    else:
        manual_overrides_path = tr.default_manual_overrides_path(args.area_id)
    report_path = Path(args.report) if args.report else root / "reports" / "qa" / f"{args.area_id}_repair_casebook_qa_report.json"

    report = run_casebook(
        area_id=args.area_id,
        input_path=input_path,
        casebook_path=casebook_path,
        manual_overrides_path=manual_overrides_path,
        report_path=report_path,
    )
    print(json.dumps({
        "area_id": args.area_id,
        "status": report["status"],
        "case_count": report["case_count"],
        "pass_count": report["pass_count"],
        "fail_count": report["fail_count"],
        "report": str(report_path),
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
