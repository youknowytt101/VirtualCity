"""Run Model QA against an existing Houdini connection."""
from __future__ import annotations

import time
from typing import Any

import houdini_model_qa as model_qa


def run_model_qa(conn: Any, hou: Any, obj_path: str, mode: str, area_cfg: dict[str, Any]) -> dict[str, Any]:
    """Execute Model QA without opening a second RPYC connection."""
    conn.execute("import hou")
    conn.execute(model_qa.REMOTE_HELPERS)

    if hou.node(obj_path) is None and obj_path == "/obj/city_gen" and hou.node("/obj/pattaya_osm") is not None:
        obj_path = "/obj/pattaya_osm"

    qa = model_qa.QA(conn, hou, obj_path, mode)
    qa.run()
    status = model_qa.overall_status(qa.checks)
    report = {
        "tool": "houdini_model_qa",
        "mode": mode,
        "status": status,
        "area_id": area_cfg.get("area_id", ""),
        "run_id": area_cfg.get("run_id", ""),
        "obj_path": obj_path,
        "hip_path": hou.hipFile.path(),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "timestamp_compact": model_qa.now_stamp(),
        "summary": {
            "pass": sum(1 for c in qa.checks if c["status"] == model_qa.PASS),
            "warn": sum(1 for c in qa.checks if c["status"] == model_qa.WARN),
            "fail": sum(1 for c in qa.checks if c["status"] == model_qa.FAIL),
        },
        "checks": qa.checks,
        "metrics": qa.metrics,
    }
    report_path = model_qa.write_report(report)
    model_qa.print_summary(report, report_path)
    return {
        "status": status,
        "report_path": report.get("report_path", str(report_path)),
        "returncode": 1 if status == model_qa.FAIL else 0,
    }
