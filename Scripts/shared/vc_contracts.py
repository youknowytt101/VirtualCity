"""Typed JSON contracts shared by pipeline status writers and readers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


BUILD_STATUSES = {"running", "completed", "failed"}
QA_STATUSES = {"pass", "warn", "fail", "error", "manual_review_required"}


def _require_text(value: str, field: str) -> str:
    text = str(value or "")
    if not text:
        raise ValueError(f"{field} is required")
    return text


@dataclass(frozen=True)
class BuildStatus:
    """Contract for Config/houdini_build_status.json."""

    area_id: str
    run_id: str
    status: str
    hip_path: str = ""
    message: str = ""
    timestamp: str = ""
    qa_status: str = ""
    qa_report: str = ""
    whitebox_path: str = ""

    def __post_init__(self) -> None:
        _require_text(self.area_id, "area_id")
        _require_text(self.run_id, "run_id")
        if self.status not in BUILD_STATUSES:
            raise ValueError(f"status must be one of {sorted(BUILD_STATUSES)}")
        if self.qa_status and self.qa_status not in QA_STATUSES:
            raise ValueError(f"qa_status must be one of {sorted(QA_STATUSES)}")

    def to_json_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "area_id": self.area_id,
            "run_id": self.run_id,
            "status": self.status,
            "hip_path": self.hip_path,
            "message": self.message,
            "timestamp": self.timestamp,
        }
        if self.qa_status:
            payload["qa_status"] = self.qa_status
        if self.qa_report:
            payload["qa_report"] = self.qa_report
        if self.whitebox_path:
            payload["whitebox_path"] = self.whitebox_path
        return payload

    @classmethod
    def from_json_dict(cls, payload: dict[str, Any]) -> "BuildStatus":
        return cls(
            area_id=str(payload.get("area_id") or ""),
            run_id=str(payload.get("run_id") or ""),
            status=str(payload.get("status") or ""),
            hip_path=str(payload.get("hip_path") or ""),
            message=str(payload.get("message") or ""),
            timestamp=str(payload.get("timestamp") or ""),
            qa_status=str(payload.get("qa_status") or ""),
            qa_report=str(payload.get("qa_report") or ""),
            whitebox_path=str(payload.get("whitebox_path") or ""),
        )


@dataclass(frozen=True)
class ModelQaReport:
    """Contract for the Model QA facts consumed by the run state."""

    area_id: str
    run_id: str
    status: str
    summary: dict[str, Any]

    def __post_init__(self) -> None:
        _require_text(self.area_id, "area_id")
        _require_text(self.run_id, "run_id")
        if self.status not in QA_STATUSES:
            raise ValueError(f"status must be one of {sorted(QA_STATUSES)}")

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def to_run_qa(self, report: str = "") -> dict[str, Any]:
        return {
            "status": self.status,
            "report": report,
            "passed": self.passed,
        }

    @classmethod
    def from_json_dict(cls, payload: dict[str, Any]) -> "ModelQaReport":
        summary = payload.get("summary")
        return cls(
            area_id=str(payload.get("area_id") or ""),
            run_id=str(payload.get("run_id") or ""),
            status=str(payload.get("status") or ""),
            summary=summary if isinstance(summary, dict) else {},
        )

