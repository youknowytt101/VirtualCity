"""Common helpers for the isolated road test QA pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


STATUS_ORDER = {
    "pass": 0,
    "warn": 1,
    "fail": 2,
}


@dataclass
class Check:
    id: str
    status: str
    value: Any
    threshold: Any
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "value": self.value,
            "threshold": self.threshold,
            "message": self.message,
        }


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def worst_status(checks: list[Check]) -> str:
    status = "pass"
    for check in checks:
        if STATUS_ORDER[check.status] > STATUS_ORDER[status]:
            status = check.status
    return status


def check_min(check_id: str, value: float, threshold: float, message: str) -> Check:
    status = "pass" if value >= threshold else "fail"
    return Check(check_id, status, value, threshold, message)


def check_max(check_id: str, value: float, threshold: float, message: str, warn: bool = False) -> Check:
    if value <= threshold:
        status = "pass"
    else:
        status = "warn" if warn else "fail"
    return Check(check_id, status, value, threshold, message)


def check_warn_below(check_id: str, value: float, threshold: float, message: str) -> Check:
    status = "pass" if value >= threshold else "warn"
    return Check(check_id, status, round(value, 3), threshold, message)


def check_warn_above(check_id: str, value: float, threshold: float, message: str) -> Check:
    status = "pass" if value <= threshold else "warn"
    return Check(check_id, status, round(value, 3), threshold, message)


def qa_report(
    *,
    area_id: str,
    stage: str,
    checks: list[Check],
    metrics: dict[str, Any],
    inputs: dict[str, str],
    next_action: str,
) -> dict[str, Any]:
    return {
        "area_id": area_id,
        "stage": stage,
        "status": worst_status(checks),
        "checks": [check.to_dict() for check in checks],
        "metrics": metrics,
        "inputs": inputs,
        "next_action": next_action,
    }
