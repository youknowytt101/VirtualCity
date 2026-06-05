#!/usr/bin/env python3
"""Serve the LaneForge viewer and local mutation API.

The API keeps browser actions behind the LaneForge command boundary:
viewer click -> preview/apply request -> versioned transaction -> rebuild -> QA
-> package publish -> SVG refresh.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[0]
VISUALIZATIONS_DIR = ROOT / "reports" / "visualizations"
JOBS_DIR = ROOT / "reports" / "viewer_jobs"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import create_lane_upgrade_transaction  # noqa: E402

SYSTEM_NAME = "LaneForge"
JOB_SCHEMA = "lane_upgrade_system.viewer_job.v1"
API_SCHEMA = "lane_upgrade_system.viewer_api.v1"

jobs: dict[str, dict[str, Any]] = {}
jobs_lock = threading.Lock()
running_job_id: str | None = None


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def json_response(handler: SimpleHTTPRequestHandler, status: int, data: dict[str, Any]) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(payload)


def error_response(handler: SimpleHTTPRequestHandler, status: int, message: str, **extra: Any) -> None:
    json_response(handler, status, {"error": message, **extra})


def read_request_json(handler: SimpleHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def latest_package(area_id: str) -> dict[str, Any]:
    latest_path = ROOT / "data" / "lane_upgrade_packages" / area_id / "latest.json"
    latest = read_json(latest_path)
    return {
        "path": rel(latest_path),
        "data": latest,
    }


def active_lane_upgrade(area_id: str, road_id: str) -> dict[str, Any] | None:
    active_path = ROOT / "data" / "processed" / f"{area_id}_lane_upgrade_overrides.json"
    active = read_json(active_path)
    for item in active.get("active_upgrades", []):
        if str(item.get("road_id") or "") == road_id:
            return item
    return None


def road_chain_id_from_reason(reason: str) -> str:
    match = re.search(r"\brc_[A-Za-z0-9_-]+\b", reason or "")
    return match.group(0) if match else ""


def targets_for_road_chain(
    *,
    road_graph: dict[str, Any],
    edges: list[dict[str, Any]],
    road_chain_id: str,
    graph_path: Path,
) -> list[dict[str, Any]]:
    chain_edges = [
        edge for edge in edges
        if str(edge.get("road_chain_id") or "") == road_chain_id
    ]
    if not chain_edges:
        raise ValueError(f"road_chain_id {road_chain_id} was not found in {graph_path}")
    chain_edges.sort(key=lambda edge: (
        int(edge.get("road_chain_fragment_index") or 0),
        str(edge.get("edge_id") or ""),
    ))
    return [
        {
            "road_id": str(edge.get("edge_id") or ""),
            "canonical_road_id": str(edge.get("canonical_road_id") or ""),
            "road_chain_id": road_chain_id,
            "edge": edge,
            "road_graph": road_graph,
        }
        for edge in chain_edges
    ]


def resolve_lane_upgrade_targets(request: dict[str, Any]) -> list[dict[str, Any]]:
    area_id = request["area_id"]
    graph_path = ROOT / "data" / "processed" / f"{area_id}_road_graph.json"
    road_graph = read_json(graph_path)
    edges = list(road_graph.get("edges", []))
    targets: list[dict[str, Any]] = []

    road_chain_id = str(request.get("road_chain_id") or "") or road_chain_id_from_reason(str(request.get("reason") or ""))
    if road_chain_id:
        return targets_for_road_chain(
            road_graph=road_graph,
            edges=edges,
            road_chain_id=road_chain_id,
            graph_path=graph_path,
        )

    if str(request.get("selection_scope") or "") == "road_chain":
        resolved = create_lane_upgrade_transaction.resolve_road_reference(
            root=ROOT,
            area_id=area_id,
            road_id=request.get("road_id", ""),
            canonical_road_id=request.get("canonical_road_id", ""),
        )
        inferred_chain_id = str((resolved.get("edge") or {}).get("road_chain_id") or "")
        if inferred_chain_id:
            return targets_for_road_chain(
                road_graph=road_graph,
                edges=edges,
                road_chain_id=inferred_chain_id,
                graph_path=graph_path,
            )

    road_ids = list(request.get("road_ids") or [])
    canonical_ids = list(request.get("canonical_road_ids") or [])
    if road_ids or canonical_ids:
        count = max(len(road_ids), len(canonical_ids))
        for index in range(count):
            resolved = create_lane_upgrade_transaction.resolve_road_reference(
                root=ROOT,
                area_id=area_id,
                road_id=road_ids[index] if index < len(road_ids) else "",
                canonical_road_id=canonical_ids[index] if index < len(canonical_ids) else "",
            )
            targets.append({
                "road_id": resolved["road_id"],
                "canonical_road_id": resolved["canonical_road_id"],
                "road_chain_id": str((resolved.get("edge") or {}).get("road_chain_id") or ""),
                "edge": resolved["edge"],
                "road_graph": resolved["road_graph"],
            })
        return targets

    resolved = create_lane_upgrade_transaction.resolve_road_reference(
        root=ROOT,
        area_id=area_id,
        road_id=request["road_id"],
        canonical_road_id=request["canonical_road_id"],
    )
    return [{
        "road_id": resolved["road_id"],
        "canonical_road_id": resolved["canonical_road_id"],
        "road_chain_id": str((resolved.get("edge") or {}).get("road_chain_id") or ""),
        "edge": resolved["edge"],
        "road_graph": resolved["road_graph"],
    }]


def parse_lane_upgrade_request(body: dict[str, Any]) -> dict[str, Any]:
    area_id = str(body.get("area_id") or "pattaya_central_500m").strip()
    road_id = str(body.get("road_id") or "").strip()
    canonical_road_id = str(body.get("canonical_road_id") or "").strip()
    road_ids = string_list(body.get("road_ids"))
    canonical_road_ids = string_list(body.get("canonical_road_ids"))
    road_chain_id = str(body.get("road_chain_id") or "").strip()
    restore_default = bool(body.get("restore_default")) or str(body.get("action") or "") == "restore_road_lane_count_default"
    target = body.get("target_physical_lane_count", body.get("target_lane_count"))
    target_lane_count = 0 if restore_default else int(target or 0)
    if not area_id:
        raise ValueError("area_id is required")
    if not road_id and not canonical_road_id and not road_ids and not canonical_road_ids and not road_chain_id:
        raise ValueError("road_id, canonical_road_id or road_chain_id is required")
    if not restore_default and target_lane_count not in {1, 2, 3, 4}:
        raise ValueError("target_physical_lane_count must be one of 1, 2, 3 or 4")
    return {
        "area_id": area_id,
        "road_id": road_id,
        "canonical_road_id": canonical_road_id,
        "road_ids": road_ids,
        "canonical_road_ids": canonical_road_ids,
        "road_chain_id": road_chain_id,
        "selection_scope": str(body.get("selection_scope") or "").strip(),
        "restore_default": restore_default,
        "target_lane_count": target_lane_count,
        "reason": str(body.get("reason") or ("web restore default lane model" if restore_default else "web menu lane upgrade")),
    }


def preview_lane_upgrade(body: dict[str, Any]) -> dict[str, Any]:
    request = parse_lane_upgrade_request(body)
    targets = resolve_lane_upgrade_targets(request)
    primary = targets[0]
    road_id = primary["road_id"]
    canonical_road_id = primary["canonical_road_id"]
    road_ids = [target["road_id"] for target in targets]
    canonical_road_ids = [target["canonical_road_id"] for target in targets]
    affected_scopes = [
        create_lane_upgrade_transaction.affected_scope_for_edge(
            target["edge"],
            target["road_graph"],
            road_id=target["road_id"],
            canonical_road_id=target["canonical_road_id"],
        )
        for target in targets
    ]
    affected_scope = affected_scopes[0] if len(affected_scopes) == 1 else {
        "scope_policy": "road_chain_ordered_edges_v1",
        "road_chain_id": request["road_chain_id"] or primary.get("road_chain_id", ""),
        "target_count": len(targets),
        "targets": affected_scopes,
    }
    active = active_lane_upgrade(request["area_id"], road_id)
    operation = "--restore-default" if request["restore_default"] else f"--target-lane-count {request['target_lane_count']}"
    geometry_flag = " --apply-all-active-geometry"
    commands = [
        (
            f"python scripts\\execute_lane_upgrade.py --area-id {request['area_id']} "
            f"--road-id {target['road_id']} --canonical-road-id {target['canonical_road_id']} {operation}{geometry_flag} "
            f"--reason \"{request['reason']}\""
        )
        for target in targets
    ]
    return {
        "type": "lane_upgrade_preview",
        "metadata": {
            "schema": API_SCHEMA,
            "system": SYSTEM_NAME,
            "area_id": request["area_id"],
        },
        "request": {
            "action": "restore_road_lane_count_default" if request["restore_default"] else "set_road_physical_lane_count",
            "road_id": road_id,
            "canonical_road_id": canonical_road_id,
            "road_ids": road_ids,
            "canonical_road_ids": canonical_road_ids,
            "road_chain_id": request["road_chain_id"] or primary.get("road_chain_id", ""),
            "selection_scope": request.get("selection_scope", ""),
            "target_physical_lane_count": request["target_lane_count"],
            "apply_selected_geometry": False,
            "apply_all_active_geometry": True,
        },
        "current_active_override": active or {},
        "affected_scope": affected_scope,
        "geometry_application_policy": "apply_all_lane_upgrade_overrides_to_geometry_v1",
        "execution_cli_command": commands[0] if len(commands) == 1 else "\n".join(commands),
        "execution_cli_commands": commands,
        "latest_package": latest_package(request["area_id"]),
        "notes": [
            "All active LaneForge lane-count overrides are applied to geometry during the rebuild.",
            "The selected road's endpoint junction laneLinks and lane surfaces are regenerated before SVG refresh.",
            "Raw, repaired, canonical and road_graph truth layers are not edited.",
        ],
    }


def job_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def save_job(job: dict[str, Any]) -> None:
    with jobs_lock:
        jobs[job["job_id"]] = dict(job)
    write_json(job_path(job["job_id"]), job)


def run_lane_upgrade_job(job_id: str, commands: list[list[str]]) -> None:
    global running_job_id
    job = jobs[job_id]
    job.update({
        "status": "running",
        "started_at_local": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    save_job(job)
    exit_code = 0
    stdout_parts: list[str] = []
    for index, command in enumerate(commands):
        job.update({
            "current_step": index + 1,
            "total_steps": len(commands),
            "current_command": [str(item) for item in command],
        })
        save_job(job)
        proc = subprocess.run(
            command,
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        stdout_parts.append(f"\n[viewer step {index + 1}/{len(commands)}]\n" + (proc.stdout or ""))
        if proc.returncode != 0:
            exit_code = proc.returncode
            break
    stdout = "".join(stdout_parts)
    job.update({
        "exit_code": exit_code,
        "stdout_tail": stdout[-8000:],
        "completed_at_local": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    if exit_code == 0:
        area_id = str((job.get("request") or {}).get("area_id") or "pattaya_central_500m")
        job.update({
            "status": "completed",
            "latest_package": latest_package(area_id),
            "svg_report": read_json(ROOT / "reports" / f"{area_id}_lane_graph_svg_report.json"),
            "reload_url": f"svg_live_viewer.html?cache={int(time.time())}",
        })
    else:
        job["status"] = "failed"
    save_job(job)
    with jobs_lock:
        running_job_id = None


def start_lane_upgrade_job(body: dict[str, Any]) -> dict[str, Any]:
    global running_job_id
    preview = preview_lane_upgrade(body)
    request = preview["request"]
    with jobs_lock:
        if running_job_id:
            raise RuntimeError(f"LaneForge job already running: {running_job_id}")
        job_id = f"lane_upgrade_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        running_job_id = job_id
    area_id = str((preview["metadata"] or {}).get("area_id") or "pattaya_central_500m")
    road_ids = string_list(request.get("road_ids")) or [str(request["road_id"])]
    canonical_road_ids = string_list(request.get("canonical_road_ids")) or [str(request["canonical_road_id"])]
    commands: list[list[str]] = []
    for index, road_id in enumerate(road_ids):
        command = [
            sys.executable,
            str(ROOT / "scripts" / "execute_lane_upgrade.py"),
            "--area-id",
            area_id,
            "--road-id",
            road_id,
            "--reason",
            str(body.get("reason") or "web menu lane upgrade"),
            "--reviewer",
            "web_user",
            "--source",
            "web_lane_count_menu",
        ]
        canonical_road_id = canonical_road_ids[index] if index < len(canonical_road_ids) else ""
        if canonical_road_id:
            command.extend(["--canonical-road-id", canonical_road_id])
        if str(request["action"]) == "restore_road_lane_count_default":
            command.append("--restore-default")
        else:
            command.extend(["--target-lane-count", str(request["target_physical_lane_count"])])
        command.append("--apply-all-active-geometry")
        commands.append(command)
    job = {
        "type": "lane_upgrade_viewer_job",
        "schema": JOB_SCHEMA,
        "job_id": job_id,
        "status": "queued",
        "created_at_local": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "request": request,
        "preview": preview,
        "command": [[str(item) for item in command] for command in commands],
    }
    save_job(job)
    thread = threading.Thread(target=run_lane_upgrade_job, args=(job_id, commands), daemon=True)
    thread.start()
    return job


class LaneForgeViewerHandler(SimpleHTTPRequestHandler):
    server_version = "LaneForgeViewer/1.0"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(VISUALIZATIONS_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/status":
            area_id = "pattaya_central_500m"
            json_response(self, HTTPStatus.OK, {
                "status": "ok",
                "schema": API_SCHEMA,
                "system": SYSTEM_NAME,
                "root": rel(ROOT),
                "visualizations": rel(VISUALIZATIONS_DIR),
                "latest_package": latest_package(area_id),
                "running_job_id": running_job_id,
            })
            return
        if path.startswith("/api/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            job = jobs.get(job_id) or read_json(job_path(job_id))
            if not job:
                error_response(self, HTTPStatus.NOT_FOUND, f"Unknown job: {job_id}")
                return
            json_response(self, HTTPStatus.OK, job)
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            body = read_request_json(self)
            if path == "/api/lane-upgrades/preview":
                json_response(self, HTTPStatus.OK, preview_lane_upgrade(body))
                return
            if path == "/api/lane-upgrades/apply":
                try:
                    job = start_lane_upgrade_job(body)
                except RuntimeError as exc:
                    error_response(self, HTTPStatus.CONFLICT, str(exc))
                    return
                json_response(self, HTTPStatus.ACCEPTED, job)
                return
            error_response(self, HTTPStatus.NOT_FOUND, f"Unknown API endpoint: {path}")
        except Exception as exc:
            error_response(self, HTTPStatus.BAD_REQUEST, str(exc))


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve LaneForge viewer and local API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if not (VISUALIZATIONS_DIR / "svg_live_viewer.html").exists():
        raise SystemExit(f"Missing viewer HTML: {VISUALIZATIONS_DIR / 'svg_live_viewer.html'}")
    server = ThreadingHTTPServer((args.host, args.port), LaneForgeViewerHandler)
    print(json.dumps({
        "status": "serving",
        "url": f"http://{args.host}:{args.port}/svg_live_viewer.html",
        "api": f"http://{args.host}:{args.port}/api/status",
        "root": str(ROOT),
    }, ensure_ascii=False))
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
