"""Durable run state for the WorldBuilder automation pipeline."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from shared.vc_contracts import ModelQaReport
from shared import vc_paths


RUN_SCHEMA_VERSION = 2
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
        "progress": {"step": 0, "total": 0, "label": ""},
        "qa": {},
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


def update_progress(run_id: str, *, step: int, total: int,
                    label: str = "", phase: str | None = None) -> dict[str, Any]:
    """Record structured build progress in the single source of truth.

    Progress lives in the run file as data, not as a log line for an upstream
    reader to parse. Callers pass explicit step/total/label instead of relying
    on the wording of a print statement.
    """
    payload = load_run(run_id)
    payload["progress"] = {"step": int(step), "total": int(total), "label": label}
    if phase:
        payload["phase"] = phase
    payload["updated"] = now()
    _write_run(payload)
    return payload


def set_qa(run_id: str, *, status: str, report: str = "",
           passed: bool | None = None) -> dict[str, Any]:
    """Fold the Model QA outcome into the run as raw facts.

    Only the raw QA result is stored here. Derived judgements such as
    requires_review or failed-check extraction are left to the read layer
    (pipeline_status), keeping this source of truth free of policy.
    """
    payload = load_run(run_id)
    qa = ModelQaReport(
        area_id=str(payload.get("area_id") or ""),
        run_id=str(payload.get("run_id") or ""),
        status=str(status or ""),
        summary={},
    ).to_run_qa(report=report)
    if passed is not None:
        qa["passed"] = bool(passed)
    payload["qa"] = qa
    payload["updated"] = now()
    _write_run(payload)
    return payload


def fail_run(run_id: str, *, phase: str, message: str) -> dict[str, Any]:
    payload = update_run(run_id, status="failed", phase=phase, message=message)
    _archive_history(run_id)
    return payload


def complete_run(run_id: str, *, phase: str = "completed",
                 message: str = "pipeline completed") -> dict[str, Any]:
    payload = update_run(run_id, status="completed", phase=phase, message=message)
    _archive_history(run_id)
    return payload


def _archive_history(run_id: str) -> None:
    """Derive the human-readable build history archive for a finished run.

    Observability only: never let an archiving error break the pipeline's
    terminal bookkeeping.
    """
    try:
        from orchestration import build_history
    except ImportError:
        try:
            import build_history  # type: ignore
        except ImportError:
            return
    try:
        build_history.write_history_for_run(run_id)
    except Exception:
        pass
