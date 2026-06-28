"""Status file writer for the Houdini build layer."""
from __future__ import annotations

import json
import time
from pathlib import Path

from shared.vc_paths import ROOT, project_relative


def _project_relative(path: str | Path) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT.resolve()).as_posix()
    except Exception:
        return project_relative(path)


def write_build_status(area_id: str, status: str, hip_path: str | Path | None = None,
                       message: str = "", qa_status: str = "",
                       qa_report: str = "", run_id: str = "",
                       whitebox_path: str | Path | None = None) -> None:
    """Write the current Houdini build status used by UI/export gates."""
    status_file = ROOT / "Config" / "houdini_build_status.json"
    payload = {
        "area_id": area_id,
        "run_id": run_id,
        "status": status,
        "hip_path": _project_relative(hip_path) if hip_path else "",
        "message": message,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if qa_status:
        payload["qa_status"] = qa_status
    if qa_report:
        payload["qa_report"] = qa_report
    if whitebox_path:
        payload["whitebox_path"] = _project_relative(whitebox_path)
    status_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = status_file.with_name(".{}.{}.tmp".format(status_file.name, time.time_ns()))
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(status_file)
