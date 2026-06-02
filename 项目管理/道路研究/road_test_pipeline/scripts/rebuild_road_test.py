#!/usr/bin/env python3
"""Rebuild the isolated road test pipeline from the command line.

This replaces the old double-click batch entry. It keeps the test pipeline
independent while giving Codex a single command to run after edits.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def run_step(name: str, cmd: list[str], cwd: Path, log_path: Path) -> int:
    print(f"[RoadTest] {name}...")
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


def python_cmd() -> str:
    return sys.executable


def rpyc_cook_cmd(root: Path, area_id: str) -> list[str] | None:
    script = root / "scripts" / "houdini_cook_rpyc.py"
    if importlib.util.find_spec("rpyc") is not None:
        return [python_cmd(), str(script), "--root", str(root), "--port", "18811"]
    uv = shutil.which("uv")
    if uv:
        return [uv, "run", "--with", "rpyc==4.1.0", "python", str(script), "--root", str(root), "--port", "18811"]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild the isolated road test pipeline.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--skip-houdini", action="store_true", help="Do not attempt RPYC Houdini cook.")
    parser.add_argument("--require-houdini", action="store_true", help="Return non-zero if RPYC cook fails.")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    log_path = reports / "last_rebuild.log"
    log_path.write_text(f"[RoadTest] rebuild started {time.strftime('%Y-%m-%d %H:%M:%S')}\n", encoding="utf-8")

    raw_geojson = root / "data" / "processed" / f"{args.area_id}_roads_raw.geojson"
    repaired_geojson = root / "data" / "processed" / f"{args.area_id}_roads_repaired.geojson"
    config = root / "config" / f"{args.area_id}.area.json"

    steps: list[tuple[str, list[str]]] = []
    if not raw_geojson.exists():
        steps.append(("Downloading sample data", [python_cmd(), str(root / "scripts" / "download_overpass.py"), "--config", str(config)]))
    steps.extend([
        ("Running topology repair", [python_cmd(), str(root / "scripts" / "topology_repair.py"), "--area-id", args.area_id]),
        (
            "Analyzing repaired roads",
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
        ("Running topology repair QA", [python_cmd(), str(root / "scripts" / "run_auto_qa.py"), "--stage", "topology_repair", "--area-id", args.area_id]),
        ("Generating standalone preview", [python_cmd(), str(root / "scripts" / "generate_road_preview.py"), "--area-id", args.area_id]),
    ])

    for name, cmd in steps:
        code = run_step(name, cmd, root, log_path)
        if code != 0:
            print(f"[ERROR] {name} failed. See {log_path}")
            return code

    houdini_status = "skipped"
    if not args.skip_houdini:
        cmd = rpyc_cook_cmd(root, args.area_id)
        if cmd is None:
            houdini_status = "missing_rpyc"
            print("[WARN] Houdini RPYC cook skipped: rpyc is not installed and uv was not found.")
        else:
            code = run_step("Cooking Houdini via RPYC", cmd, root, log_path)
            houdini_status = "completed" if code == 0 else "unavailable"
            if code != 0 and args.require_houdini:
                print(f"[ERROR] Houdini RPYC cook failed. See {log_path}")
                return code

    summary = {
        "area_id": args.area_id,
        "status": "completed",
        "houdini_status": houdini_status,
        "outputs": {
            "repaired_geojson": str(repaired_geojson),
            "preview_report": str(reports / f"{args.area_id}_road_preview_report.json"),
            "qa_report": str(reports / "qa" / f"{args.area_id}_topology_repair_qa_report.json"),
            "log": str(log_path),
        },
    }
    summary_path = reports / f"{args.area_id}_rebuild_report.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[RoadTest] Rebuild complete")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
