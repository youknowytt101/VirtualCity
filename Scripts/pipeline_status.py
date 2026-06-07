"""Current-run status aggregation for the VirtualCity pipeline.

This module is intentionally read-only.  It gives UI and export scripts one
place to answer: "does this artifact belong to the active area/run?"
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import manual_review
import vc_paths


MANUAL_REVIEW_QA = {"warn", "manual_review_required"}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _resolve(root: Path, value: str | Path | None) -> Path:
    if not value:
        return root
    raw = str(value).replace("\\", "/")
    path = Path(raw)
    if path.is_absolute():
        return path
    lowered = raw.lower()
    marker = "/virtualcity/"
    idx = lowered.find(marker)
    if idx >= 0:
        return root / raw[idx + len(marker):]
    return root / raw


def _project_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _same_identity(payload: dict[str, Any], area_id: str, run_id: str) -> bool:
    if not payload:
        return False
    if payload.get("area_id") != area_id:
        return False
    payload_run = str(payload.get("run_id") or "")
    return not run_id or payload_run == run_id


def load_active(root: Path | None = None) -> dict[str, Any]:
    base = root or vc_paths.ROOT
    return _read_json(base / "Config" / "active_area.json")


def load_run(root: Path, run_id: str) -> dict[str, Any]:
    if not run_id:
        return {}
    return _read_json(root / "Reports" / "pipeline_runs" / f"{run_id}.json")


def load_houdini_status(root: Path, area_id: str, run_id: str) -> dict[str, Any]:
    path = root / "Config" / "houdini_build_status.json"
    payload = _read_json(path)
    if not payload:
        return {"available": False, "path": _project_path(root, path), "message": "status file missing"}
    same = _same_identity(payload, area_id, run_id)
    out = dict(payload)
    out.update({
        "available": same,
        "same_identity": same,
        "path": _project_path(root, path),
    })
    if not same:
        out["message"] = (
            f"stale houdini status: {payload.get('area_id', '')}/{payload.get('run_id', '')} "
            f"!= {area_id}/{run_id}"
        )
    return out


def load_model_qa(root: Path, area_id: str, run_id: str,
                  houdini_status: dict[str, Any] | None = None) -> dict[str, Any]:
    candidates: list[Path] = []
    report_value = (houdini_status or {}).get("qa_report")
    if report_value:
        candidates.append(_resolve(root, report_value))
    candidates.extend([
        root / "Reports" / "model_qa" / f"{area_id}_latest.json",
        root / "Reports" / "model_qa" / "latest.json",
    ])
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        payload = _read_json(path)
        if not payload:
            continue
        if _same_identity(payload, area_id, run_id):
            out = dict(payload)
            out.update({
                "available": True,
                "same_identity": True,
                "path": _project_path(root, path),
            })
            return out
    return {"available": False, "same_identity": False, "message": "current model QA report missing"}


def current_status(root: Path | None = None,
                   active_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    base = root or vc_paths.ROOT
    active = active_cfg or load_active(base)
    area_id = str(active.get("area_id") or "")
    run_id = str(active.get("run_id") or "")
    run = load_run(base, run_id)
    houdini = load_houdini_status(base, area_id, run_id)
    model_qa = load_model_qa(base, area_id, run_id, houdini)
    review = manual_review.load_review(area_id, run_id, root=base)
    return {
        "area_id": area_id,
        "run_id": run_id,
        "active_area": active,
        "run": run,
        "houdini": houdini,
        "model_qa": model_qa,
        "manual_review": review,
    }


def export_gate(root: Path | None = None,
                active_cfg: dict[str, Any] | None = None,
                live_model_ready: bool | None = None) -> dict[str, Any]:
    base = root or vc_paths.ROOT
    status = current_status(base, active_cfg)
    area_id = status["area_id"]
    run_id = status["run_id"]
    reasons: list[str] = []
    warnings: list[str] = []
    requires_review = False

    if not area_id or not run_id:
        reasons.append("active area/run_id is missing")

    houdini = status["houdini"]
    if not houdini.get("available"):
        reasons.append(str(houdini.get("message") or "current Houdini build status is missing"))
    elif str(houdini.get("status") or "").lower() != "completed":
        reasons.append(f"Houdini status is {houdini.get('status') or 'unknown'}")

    qa = status["model_qa"]
    qa_status = str(qa.get("status") or houdini.get("qa_status") or "").lower()
    if not qa.get("available"):
        reasons.append(str(qa.get("message") or "current Model QA report is missing"))
    elif qa_status == "fail":
        reasons.append("Model QA status is fail")
    elif qa_status in MANUAL_REVIEW_QA:
        requires_review = True
        warnings.append(f"Model QA status is {qa_status}")

    if live_model_ready is False:
        reasons.append("Houdini OUT_city is not live/exportable")

    review_ok = manual_review.review_approves_export(area_id, run_id, root=base)
    if requires_review and not review_ok:
        reasons.append("manual review approval is required for this area/run")

    return {
        "allowed": not reasons,
        "requires_manual_review": requires_review,
        "manual_review_approved": review_ok,
        "reasons": reasons,
        "warnings": warnings,
        "primary_reason": reasons[0] if reasons else "",
        "status": status,
    }
