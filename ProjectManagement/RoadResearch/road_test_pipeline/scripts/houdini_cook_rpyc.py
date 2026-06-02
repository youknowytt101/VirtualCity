#!/usr/bin/env python3
"""Cook the isolated road test in the currently open Houdini session via RPYC.

This mirrors the main project's Houdini connection method: connect to the
existing Houdini RPYC service on localhost:18811, then execute this test
pipeline's own cook code inside that Houdini process.
"""

from __future__ import annotations

import argparse
import json
import socket
from pathlib import Path

import rpyc


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def build_remote_code(root: Path) -> str:
    cook_script = root / "scripts" / "houdini_cook_open_session.py"
    source = cook_script.read_text(encoding="utf-8")
    return (
        f"ROAD_TEST_ROOT = {json.dumps(str(root))}\n"
        f"__file__ = {json.dumps(str(cook_script))}\n"
        f"exec(compile({json.dumps(source)}, __file__, 'exec'))\n"
    )


def rpyc_port_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Cook road_test_pipeline in Houdini via RPYC.")
    parser.add_argument("--root", default="", help="road_test_pipeline root directory")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=18811)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    script_path = Path(__file__)
    root = Path(args.root).resolve() if args.root else pipeline_root_from_script(script_path)
    remote_code = build_remote_code(root)

    if not rpyc_port_reachable(args.host, args.port):
        print(f"[ERROR] Houdini RPYC is not reachable at {args.host}:{args.port}.")
        print("[ERROR] Enable the RPYC service in the open Houdini session, then run this again.")
        return 1

    try:
        conn = rpyc.classic.connect(args.host, args.port)
    except OSError as exc:
        print(f"[ERROR] Could not connect to Houdini RPYC at {args.host}:{args.port}: {exc}")
        print("[ERROR] Open Houdini with the RPYC service enabled on port 18811, then run this again.")
        return 1

    try:
        conn._config["sync_request_timeout"] = args.timeout
        conn.execute(remote_code)
    finally:
        conn.close()

    report_path = root / "reports" / "pattaya_central_500m_open_session_cook_report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        print("[RoadTest] RPYC cook complete")
        print(json.dumps({
            "area_id": report.get("area_id"),
            "obj_node": report.get("obj_node"),
            "display_node": report.get("display_node"),
            "centerline_prims": report.get("centerline_prims"),
            "preview_output_prims": report.get("preview_output_prims"),
            "preview_output_points": report.get("preview_output_points"),
            "lane_debug_node": report.get("lane_debug_node"),
            "lane_debug_prims": report.get("lane_debug_prims"),
            "lane_debug_points": report.get("lane_debug_points"),
            "lane_surface_node": report.get("lane_surface_node"),
            "lane_surface_prims": report.get("lane_surface_prims"),
            "lane_surface_points": report.get("lane_surface_points"),
        }, ensure_ascii=False, indent=2))
    else:
        print("[RoadTest] RPYC cook command finished, but no cook report was written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
