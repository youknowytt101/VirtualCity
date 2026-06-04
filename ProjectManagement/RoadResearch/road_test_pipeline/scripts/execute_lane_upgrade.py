#!/usr/bin/env python3
"""Execute a LaneForge lane-count upgrade through the audited pipeline.

This is the v1 backend entry for:

viewer road click -> choose 1/2/3/4 lanes -> transaction -> rebuild -> QA -> package -> SVG

The viewer remains an inspection surface. This command is the mutating boundary:
it creates the active transaction override, runs the structured rebuild, publishes
the next package version, and refreshes the SVG QA view.
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


EXECUTION_SCHEMA = "lane_upgrade_system.execution.v1"
PATH_POLICY = "pipeline_root_relative_paths_v1"


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


def resolve_artifact_path(value: str, root: Path) -> Path | None:
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


def portable_command(cmd: list[str], root: Path) -> list[str]:
    portable: list[str] = []
    for index, item in enumerate(cmd):
        text = str(item)
        path = Path(text)
        if index == 0 and path.name.lower() in {"python", "python.exe", "hython", "hython.exe"}:
            portable.append(path.stem.lower())
        elif path.is_absolute():
            portable.append(rel(path, root))
        else:
            portable.append(text)
    return portable


def python_cmd() -> str:
    return sys.executable


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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
    package_root = root / "data" / "lane_upgrade_packages" / area_id
    return next_versioned_name(package_root, prefix="lane_package_")


def next_execution_id(root: Path, area_id: str) -> tuple[str, Path]:
    execution_dir = root / "data" / "lane_upgrade_system" / "executions"
    version = next_versioned_name(execution_dir, prefix=f"{area_id}_lane_upgrade_execution_")
    execution_id = version.replace(f"{area_id}_", "")
    return execution_id, execution_dir / f"{version}.json"


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


def command_for_transaction(
    *,
    root: Path,
    area_id: str,
    road_id: str,
    canonical_road_id: str,
    target_lane_count: int | None,
    reason: str,
    reviewer: str,
    source: str,
    restore_default: bool = False,
) -> list[str]:
    cmd = [
        python_cmd(),
        str(root / "scripts" / "create_lane_upgrade_transaction.py"),
        "--area-id",
        area_id,
        "--reason",
        reason,
        "--reviewer",
        reviewer,
        "--source",
        source,
    ]
    if restore_default:
        cmd.append("--restore-default")
    else:
        if target_lane_count is None:
            raise ValueError("target_lane_count is required unless restore_default is true")
        cmd.extend(["--target-lane-count", str(target_lane_count)])
    if road_id:
        cmd.extend(["--road-id", road_id])
    if canonical_road_id:
        cmd.extend(["--canonical-road-id", canonical_road_id])
    return cmd


def execute_upgrade(
    *,
    root: Path,
    area_id: str,
    road_id: str,
    canonical_road_id: str,
    target_lane_count: int | None,
    reason: str,
    reviewer: str,
    source: str,
    with_houdini: bool,
    dry_run: bool,
    restore_default: bool = False,
) -> dict[str, Any]:
    execution_id, execution_path = next_execution_id(root, area_id)
    reports = root / "reports"
    log_path = reports / f"{area_id}_{execution_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(f"[LaneForge] execution started {time.strftime('%Y-%m-%d %H:%M:%S')}\n", encoding="utf-8")

    package_version = next_package_version(root, area_id)
    transaction_cmd = command_for_transaction(
        root=root,
        area_id=area_id,
        road_id=road_id,
        canonical_road_id=canonical_road_id,
        target_lane_count=target_lane_count,
        reason=reason,
        reviewer=reviewer,
        source=source,
        restore_default=restore_default,
    )
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
    propagation_cmd = [
        python_cmd(),
        str(root / "scripts" / "plan_lane_upgrade_propagation.py"),
        "--area-id",
        area_id,
    ]
    svg_cmd = [python_cmd(), str(root / "scripts" / "export_lane_graph_svg.py"), "--area-id", area_id]

    execution: dict[str, Any] = {
        "type": "lane_upgrade_execution",
        "metadata": {
            "area_id": area_id,
            "schema": EXECUTION_SCHEMA,
            "system": "LaneForge",
            "execution_id": execution_id,
            "path_policy": PATH_POLICY,
            "created_at_local": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
        "request": {
            "action": "restore_road_lane_count_default" if restore_default else "set_road_physical_lane_count",
            "road_id": road_id,
            "canonical_road_id": canonical_road_id,
            "target_physical_lane_count": target_lane_count,
            "reason": reason,
            "reviewer": reviewer,
            "source": source,
        },
        "planned_outputs": {
            "package_version": package_version,
            "package_manifest": rel(root / "data" / "lane_upgrade_packages" / area_id / package_version / "manifest.json", root),
            "propagation_report": rel(root / "reports" / f"{area_id}_lane_upgrade_propagation_report.json", root),
            "svg": rel(root / "reports" / "visualizations" / f"{area_id}_lane_graph_topology.svg", root),
            "execution_report": rel(execution_path, root),
            "log": rel(log_path, root),
        },
        "commands": {
            "create_transaction": portable_command(transaction_cmd, root),
            "rebuild": portable_command(rebuild_cmd, root),
            "plan_propagation": portable_command(propagation_cmd, root),
            "publish_package": portable_command(package_cmd, root),
            "export_svg": portable_command(svg_cmd, root),
        },
        "status": "dry_run" if dry_run else "running",
    }

    if dry_run:
        execution = portable_json_paths(execution, root=root)
        write_json(execution_path, execution)
        return execution

    transaction_stdout = run_command("Creating active lane upgrade transaction", transaction_cmd, root, log_path)
    transaction_summary = json.loads(transaction_stdout)
    run_command("Rebuilding audited road pipeline", rebuild_cmd, root, log_path)
    propagation_stdout = run_command("Planning LaneForge propagation candidates", propagation_cmd, root, log_path)
    package_stdout = run_command("Publishing next LaneForge package", package_cmd, root, log_path)
    run_command("Refreshing SVG QA view", svg_cmd, root, log_path)

    propagation_summary = json.loads(propagation_stdout)
    package_summary = json.loads(package_stdout)
    rebuild_report_path = reports / f"{area_id}_rebuild_report.json"
    svg_report_path = reports / f"{area_id}_lane_graph_svg_report.json"
    audit_report_path = reports / f"{area_id}_pipeline_audit_report.json"
    execution.update({
        "status": "completed",
        "transaction": transaction_summary,
        "rebuild_report": rel(rebuild_report_path, root),
        "pipeline_audit": read_json(audit_report_path) if audit_report_path.exists() else {},
        "propagation_report": propagation_summary,
        "published_package": package_summary,
        "svg_report": read_json(svg_report_path) if svg_report_path.exists() else {},
    })
    execution = portable_json_paths(execution, root=root)
    write_json(execution_path, execution)
    return execution


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute a LaneForge lane-count upgrade.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--road-id", default="", help="Road graph edge id, for example e_0012.")
    parser.add_argument("--canonical-road-id", default="", help="Canonical road id, for example cr_0012.")
    parser.add_argument("--target-lane-count", type=int, choices=[1, 2, 3, 4])
    parser.add_argument("--restore-default", action="store_true", help="Remove active override and return to source/default lane rules.")
    parser.add_argument("--reason", default="LaneForge execution request")
    parser.add_argument("--reviewer", default="codex")
    parser.add_argument("--source", default="web_lane_count_menu")
    parser.add_argument("--with-houdini", action="store_true", help="Run the Houdini cook during rebuild.")
    parser.add_argument("--dry-run", action="store_true", help="Write the execution plan without mutating pipeline data.")
    args = parser.parse_args()

    if not args.road_id and not args.canonical_road_id:
        raise SystemExit("--road-id or --canonical-road-id is required")
    if not args.restore_default and args.target_lane_count is None:
        raise SystemExit("--target-lane-count is required unless --restore-default is set")

    root = pipeline_root_from_script(Path(__file__))
    result = execute_upgrade(
        root=root,
        area_id=args.area_id,
        road_id=args.road_id,
        canonical_road_id=args.canonical_road_id,
        target_lane_count=args.target_lane_count,
        reason=args.reason,
        reviewer=args.reviewer,
        source=args.source,
        with_houdini=args.with_houdini,
        dry_run=args.dry_run,
        restore_default=args.restore_default,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
