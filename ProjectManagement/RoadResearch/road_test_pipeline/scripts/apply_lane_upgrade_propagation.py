#!/usr/bin/env python3
"""Apply selected LaneForge propagation candidates through QA.

Default policy is intentionally conservative:

- only candidate_high_confidence
- only through_pair_lane_count_continuity_v2
- min confidence 0.8

Short-edge absorption is available as a separate explicitly named policy. It
is not part of the default accept path.

The command creates transaction-scoped active overrides, rebuilds the pipeline,
plans the next propagation layer, publishes the next package and refreshes SVG.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


APPLICATION_SCHEMA = "lane_upgrade_system.propagation_application.v1"
PATH_POLICY = "pipeline_root_relative_paths_v1"
DEFAULT_RULES = ["through_pair_lane_count_continuity_v2"]
DEFAULT_STATUSES = ["candidate_high_confidence"]
DEFAULT_MIN_CONFIDENCE = 0.8
DEFAULT_POLICY = "through_pair_only_v1"
POLICY_CONFIGS: dict[str, dict[str, Any]] = {
    "through_pair_only_v1": {
        "rules": DEFAULT_RULES,
        "statuses": DEFAULT_STATUSES,
        "min_confidence": DEFAULT_MIN_CONFIDENCE,
        "max_candidate_length_m": None,
        "require_same_road_class": False,
    },
    "short_edge_absorption_only_v1": {
        "rules": ["short_edge_absorption_lane_count_v2"],
        "statuses": DEFAULT_STATUSES,
        "min_confidence": 0.74,
        "max_candidate_length_m": 12.0,
        "require_same_road_class": True,
    },
}


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


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
        return root.joinpath(*parts[index + 1 :])
    return None


def resolve_artifact_path(value: str, root: Path, *, base_dir: Path | None = None) -> Path:
    text = str(value or "").strip()
    if not text:
        raise ValueError("artifact path is empty")
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
    return candidates[-1]


def portable_path_string(value: str, root: Path) -> str:
    text = str(value)
    if not is_windows_absolute_path(text) and not Path(text).is_absolute():
        return text
    candidate = resolve_artifact_path(text, root)
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


def python_cmd() -> str:
    return sys.executable


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def import_script(root: Path, name: str):
    path = root / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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


def latest_plan_path(root: Path, area_id: str) -> Path:
    latest = root / "data" / "lane_upgrade_system" / "propagation" / f"{area_id}_latest.json"
    if not latest.exists():
        raise FileNotFoundError(f"Missing latest propagation pointer: {latest}")
    data = read_json(latest)
    path = resolve_artifact_path(str(data.get("latest_plan") or ""), root, base_dir=latest.parent)
    if not path.exists():
        raise FileNotFoundError(f"Missing latest propagation plan: {path}")
    return path


def selected_candidates(
    plan: dict[str, Any],
    *,
    candidate_ids: set[str],
    allowed_rules: set[str],
    allowed_statuses: set[str],
    min_confidence: float,
    max_candidate_length_m: float | None = None,
    require_same_road_class: bool = False,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for candidate in plan.get("candidates", []):
        candidate_id = str(candidate.get("candidate_id") or "")
        if candidate_ids and candidate_id not in candidate_ids:
            continue
        if str(candidate.get("rule_id") or "") not in allowed_rules:
            continue
        if str(candidate.get("status") or "") not in allowed_statuses:
            continue
        if float(candidate.get("confidence") or 0.0) < min_confidence:
            continue
        if max_candidate_length_m is not None:
            length_m = float(candidate.get("candidate_length_m") or 0.0)
            if length_m <= 0.0 or length_m > max_candidate_length_m:
                continue
        if require_same_road_class:
            candidate_class = str(candidate.get("candidate_road_class") or "")
            source_class = str(candidate.get("source_road_class") or "")
            if not candidate_class or not source_class or candidate_class != source_class:
                continue
        selected.append(candidate)
    return selected


def active_road_ids(active_overrides_path: Path) -> set[str]:
    if not active_overrides_path.exists():
        return set()
    data = read_json(active_overrides_path)
    return {
        str(item.get("road_id") or "")
        for item in data.get("active_upgrades", [])
        if bool(item.get("enabled", True)) and str(item.get("road_id") or "")
    }


def road_lane_snapshot(lane_graph_path: Path, road_ids: list[str]) -> dict[str, Any]:
    if not lane_graph_path.exists():
        return {}
    lane_graph = read_json(lane_graph_path)
    snapshot: dict[str, Any] = {}
    for road_id in road_ids:
        lanes = [lane for lane in lane_graph.get("lanes", []) if str(lane.get("road_id") or "") == road_id]
        snapshot[road_id] = {
            "lane_count": len(lanes),
            "lane_ids": [str(lane.get("lane_id") or "") for lane in lanes],
            "directions": [str(lane.get("direction") or "") for lane in lanes],
            "upgrade_targets": [int(lane.get("lane_upgrade_target_physical_lane_count") or 0) for lane in lanes],
        }
    return snapshot


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


def apply_propagation(
    *,
    root: Path,
    area_id: str,
    plan_path: Path,
    candidate_ids: set[str],
    allowed_rules: set[str],
    allowed_statuses: set[str],
    min_confidence: float,
    reviewer: str,
    reason: str,
    dry_run: bool,
    no_rebuild: bool,
    with_houdini: bool,
    policy_name: str = DEFAULT_POLICY,
    max_candidate_length_m: float | None = None,
    require_same_road_class: bool = False,
) -> dict[str, Any]:
    plan = read_json(plan_path)
    processed = root / "data" / "processed"
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    active_overrides_path = processed / f"{area_id}_lane_upgrade_overrides.json"
    lane_graph_path = processed / f"{area_id}_lane_graph.json"
    existing_active = active_road_ids(active_overrides_path)
    selected = [
        candidate
        for candidate in selected_candidates(
            plan,
            candidate_ids=candidate_ids,
            allowed_rules=allowed_rules,
            allowed_statuses=allowed_statuses,
            min_confidence=min_confidence,
            max_candidate_length_m=max_candidate_length_m,
            require_same_road_class=require_same_road_class,
        )
        if str(candidate.get("candidate_road_id") or "") not in existing_active
    ]
    selected_road_ids = [str(candidate.get("candidate_road_id") or "") for candidate in selected]

    version, application_path = next_versioned_path(
        root / "data" / "lane_upgrade_system" / "propagation_applications",
        f"{area_id}_lane_upgrade_propagation_application_",
    )
    log_path = reports / f"{area_id}_lane_upgrade_propagation_application_{version}.log"
    log_path.write_text(f"[LaneForge] propagation application started {time.strftime('%Y-%m-%d %H:%M:%S')}\n", encoding="utf-8")
    before_snapshot = road_lane_snapshot(lane_graph_path, selected_road_ids)
    package_version = next_package_version(root, area_id)

    application: dict[str, Any] = {
        "type": "lane_upgrade_propagation_application",
        "metadata": {
            "area_id": area_id,
            "schema": APPLICATION_SCHEMA,
            "system": "LaneForge",
            "version": version,
            "path_policy": PATH_POLICY,
            "policy": policy_name,
        },
        "source_plan": rel(plan_path, root),
        "selection_policy": {
            "candidate_ids": sorted(candidate_ids),
            "allowed_rules": sorted(allowed_rules),
            "allowed_statuses": sorted(allowed_statuses),
            "min_confidence": min_confidence,
            "max_candidate_length_m": max_candidate_length_m,
            "require_same_road_class": require_same_road_class,
        },
        "status": "dry_run" if dry_run else "running",
        "selected_candidates": selected,
        "skipped_existing_active_road_ids": sorted(existing_active),
        "before_lane_snapshot": before_snapshot,
        "planned_package_version": package_version,
        "log": rel(log_path, root),
    }

    if dry_run or not selected:
        application["status"] = "dry_run" if dry_run else "no_candidates"
        application = portable_json_paths(application, root=root)
        write_json(application_path, application)
        return application

    create_transaction = import_script(root, "create_lane_upgrade_transaction")
    transactions: list[dict[str, Any]] = []
    for candidate in selected:
        target = int(candidate.get("proposed_target_physical_lane_count") or 0)
        transaction = create_transaction.create_transaction(
            area_id=area_id,
            road_id=str(candidate.get("candidate_road_id") or ""),
            canonical_road_id=str(candidate.get("candidate_canonical_road_id") or ""),
            target_physical_lane_count=target,
            reason=f"{reason}: {candidate.get('candidate_id')} {candidate.get('rule_id')}",
            reviewer=reviewer,
            source="lane_upgrade_propagation_v2",
            root=root,
            activate=True,
        )
        transactions.append({
            "candidate_id": candidate.get("candidate_id"),
            "transaction_id": transaction["transaction"]["transaction_id"],
            "road_id": transaction["transaction"]["request"]["road_id"],
            "canonical_road_id": transaction["transaction"]["request"]["canonical_road_id"],
            "target_physical_lane_count": transaction["transaction"]["request"]["target_physical_lane_count"],
            "transaction_path": transaction["transaction_path"],
        })

    if no_rebuild:
        application.update({
            "status": "applied_without_rebuild",
            "transactions": transactions,
        })
        application = portable_json_paths(application, root=root)
        write_json(application_path, application)
        return application

    rebuild_cmd = [python_cmd(), str(root / "scripts" / "rebuild_road_test.py"), "--area-id", area_id]
    if not with_houdini:
        rebuild_cmd.append("--skip-houdini")
    propagation_cmd = [python_cmd(), str(root / "scripts" / "plan_lane_upgrade_propagation.py"), "--area-id", area_id]
    package_cmd = [
        python_cmd(),
        str(root / "scripts" / "build_lane_upgrade_package.py"),
        "--area-id",
        area_id,
        "--version",
        package_version,
    ]
    svg_cmd = [python_cmd(), str(root / "scripts" / "export_lane_graph_svg.py"), "--area-id", area_id]

    run_command("Rebuilding after accepted propagation candidates", rebuild_cmd, root, log_path)
    propagation_stdout = run_command("Planning next propagation layer", propagation_cmd, root, log_path)
    package_stdout = run_command("Publishing package with accepted propagation", package_cmd, root, log_path)
    run_command("Refreshing SVG QA view", svg_cmd, root, log_path)

    after_snapshot = road_lane_snapshot(lane_graph_path, selected_road_ids)
    audit_path = reports / f"{area_id}_pipeline_audit_report.json"
    application.update({
        "status": "completed",
        "transactions": transactions,
        "after_lane_snapshot": after_snapshot,
        "pipeline_audit": read_json(audit_path) if audit_path.exists() else {},
        "next_propagation_report": json.loads(propagation_stdout),
        "published_package": json.loads(package_stdout),
    })
    application = portable_json_paths(application, root=root)
    write_json(application_path, application)
    return application


def parse_csv(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def policy_config(policy_name: str) -> dict[str, Any]:
    if policy_name not in POLICY_CONFIGS:
        raise ValueError(f"Unknown propagation application policy: {policy_name}")
    return POLICY_CONFIGS[policy_name]


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply selected LaneForge propagation candidates.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--plan", default="")
    parser.add_argument("--candidate-id", action="append", default=[])
    parser.add_argument("--policy", choices=sorted(POLICY_CONFIGS), default=DEFAULT_POLICY)
    parser.add_argument("--rules", default="")
    parser.add_argument("--statuses", default="")
    parser.add_argument("--min-confidence", type=float, default=None)
    parser.add_argument("--reviewer", default="codex")
    parser.add_argument("--reason", default="accepted high-confidence propagation candidate")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-rebuild", action="store_true")
    parser.add_argument("--with-houdini", action="store_true")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    plan_path = Path(args.plan) if args.plan else latest_plan_path(root, args.area_id)
    config = policy_config(args.policy)
    allowed_rules = parse_csv(args.rules) if args.rules else set(config["rules"])
    allowed_statuses = parse_csv(args.statuses) if args.statuses else set(config["statuses"])
    min_confidence = float(args.min_confidence) if args.min_confidence is not None else float(config["min_confidence"])
    result = apply_propagation(
        root=root,
        area_id=args.area_id,
        plan_path=plan_path,
        candidate_ids=set(args.candidate_id),
        allowed_rules=allowed_rules,
        allowed_statuses=allowed_statuses,
        min_confidence=min_confidence,
        policy_name=args.policy,
        max_candidate_length_m=config["max_candidate_length_m"],
        require_same_road_class=bool(config["require_same_road_class"]),
        reviewer=args.reviewer,
        reason=args.reason,
        dry_run=args.dry_run,
        no_rebuild=args.no_rebuild,
        with_houdini=args.with_houdini,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
