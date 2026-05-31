"""Durable run state for the VirtualCity automation pipeline."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import vc_paths


RUN_SCHEMA_VERSION = 1
RUNS_DIR = vc_paths.ROOT / "Reports" / "pipeline_runs"
LATEST_RUN = RUNS_DIR / "latest.json"
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_run_id(area_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", area_id).strip("_.-") or "area"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{slug}_{uuid.uuid4().hex[:8]}"


def run_path(run_id: str) -> Path:
    if not run_id or not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError(f"invalid run_id: {run_id!r}")
    return RUNS_DIR / f"{run_id}.json"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(path)


def _write_run(payload: dict[str, Any]) -> None:
    _write_json_atomic(run_path(payload["run_id"]), payload)
    _write_json_atomic(LATEST_RUN, payload)


def load_run(run_id: str) -> dict[str, Any]:
    with open(run_path(run_id), encoding="utf-8") as f:
        return json.load(f)


def create_run(area_cfg: dict[str, Any], *, source: str,
               run_id: str | None = None) -> dict[str, Any]:
    run_id = run_id or area_cfg.get("run_id") or new_run_id(area_cfg.get("area_id", "area"))
    created = now()
    payload = {
        "schema": RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "area_id": area_cfg.get("area_id", ""),
        "bbox": area_cfg.get("bbox"),
        "source": source,
        "status": "running",
        "phase": "created",
        "created": created,
        "updated": created,
        "events": [
            {"time": created, "status": "running", "phase": "created", "message": "pipeline run created"}
        ],
    }
    _write_run(payload)
    return payload


def update_run(run_id: str, *, status: str | None = None,
               phase: str | None = None, message: str = "",
               fields: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = load_run(run_id)
    timestamp = now()
    if status:
        payload["status"] = status
    if phase:
        payload["phase"] = phase
    if fields:
        payload.update(fields)
    payload["updated"] = timestamp
    if status or phase or message:
        payload.setdefault("events", []).append({
            "time": timestamp,
            "status": payload.get("status", ""),
            "phase": payload.get("phase", ""),
            "message": message,
        })
    _write_run(payload)
    return payload


def fail_run(run_id: str, *, phase: str, message: str) -> dict[str, Any]:
    return update_run(run_id, status="failed", phase=phase, message=message)


def complete_run(run_id: str, *, phase: str = "completed",
                 message: str = "pipeline completed") -> dict[str, Any]:
    return update_run(run_id, status="completed", phase=phase, message=message)

