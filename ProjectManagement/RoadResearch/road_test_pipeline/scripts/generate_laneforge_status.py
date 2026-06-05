#!/usr/bin/env python3
"""Generate a current LaneForge status snapshot from the latest package.

This keeps volatile package/version/count/QA facts out of hand-written docs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from artifact_manifest import artifact_record, rel


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def resolve_latest_package(root: Path, area_id: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    latest_path = root / "data" / "lane_upgrade_packages" / area_id / "latest.json"
    latest = read_json(latest_path)
    package_dir = latest_path.parent / str(latest.get("latest_package_dir") or latest.get("latest_package_version") or "")
    manifest_path = package_dir / str(latest.get("manifest") or "manifest.json")
    manifest = read_json(manifest_path)
    return package_dir, latest, manifest


def optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return read_json(path)


def semantic_review_from_reports(root: Path, area_id: str) -> dict[str, Any]:
    reports = root / "reports"
    road_graph_report = optional_json(reports / f"{area_id}_road_graph_report.json")
    lane_attribute_report = optional_json(reports / f"{area_id}_lane_attribute_model_report.json")
    junction_semantics_report = optional_json(reports / f"{area_id}_junction_semantics_report.json")
    road_metrics = road_graph_report.get("metrics") or {}
    lane_metrics = lane_attribute_report.get("metrics") or {}
    junction_counts = junction_semantics_report.get("counts") or {}
    if not any([road_metrics, lane_metrics, junction_counts]):
        return {}
    return {
        "schema": "lane_upgrade_system.semantic_review_summary.v1.fallback_from_reports",
        "status": "manual_review_required",
        "active_lane_policy": str(lane_attribute_report.get("active_lane_policy") or ""),
        "width_fallback_ratio": road_metrics.get("width_fallback_ratio"),
        "lanes_fallback_ratio": road_metrics.get("lanes_fallback_ratio"),
        "missing_turn_lanes_ratio": lane_metrics.get("missing_turn_lanes_ratio"),
        "lane_count_policy_override_ratio": lane_metrics.get("lane_count_policy_override_ratio"),
        "direction_policy_override_ratio": lane_metrics.get("direction_policy_override_ratio"),
        "source_oneway_ignored_approaches": junction_counts.get("source_oneway_ignored_approaches"),
        "source_oneway_blocked_movements_if_trusted": junction_counts.get("source_oneway_blocked_movements_if_trusted"),
        "source": "current reports fallback; future packages embed semantic_review in manifest",
    }


def build_status(root: Path, area_id: str) -> dict[str, Any]:
    package_dir, latest, manifest = resolve_latest_package(root, area_id)
    metadata = manifest.get("metadata") or {}
    qa_gate = manifest.get("qa_gate") or {}
    semantic_review = manifest.get("semantic_review") or semantic_review_from_reports(root, area_id)
    contents = manifest.get("contents") or {}
    houdini_manifest = package_dir / str(contents.get("houdini_manifest") or "houdini_manifest.json")
    return {
        "type": "laneforge_current_status",
        "schema": "lane_upgrade_system.current_status.v1",
        "area_id": area_id,
        "latest_package_version": str(latest.get("latest_package_version") or metadata.get("package_version") or ""),
        "package_dir": rel(package_dir, root),
        "manifest": rel(package_dir / str(latest.get("manifest") or "manifest.json"), root),
        "houdini_manifest": rel(houdini_manifest, root),
        "path_policy": metadata.get("path_policy"),
        "qa_status": metadata.get("qa_status"),
        "qa_gate_status": metadata.get("qa_gate_status"),
        "qa_warning_summary": qa_gate.get("summary", latest.get("qa_warning_summary", {})),
        "counts": manifest.get("counts", {}),
        "semantic_review": semantic_review,
        "publish_decision": (qa_gate.get("publish_decision") or {}),
        "artifact_identity": {
            "latest": artifact_record(package_dir.parent / "latest.json", root=root),
            "manifest": artifact_record(package_dir / str(latest.get("manifest") or "manifest.json"), root=root),
            "houdini_manifest": artifact_record(houdini_manifest, root=root),
        },
        "handoff_rule": "Houdini and downstream systems consume the latest standard lane package, not data/processed internals.",
    }


def markdown_status(status: dict[str, Any]) -> str:
    counts = status.get("counts") or {}
    qa_summary = status.get("qa_warning_summary") or {}
    semantic = status.get("semantic_review") or {}
    lines = [
        "# LaneForge Current Status",
        "",
        "This file is generated from `data/lane_upgrade_packages/<area_id>/latest.json` and the package manifest.",
        "",
        f"- area_id: `{status.get('area_id')}`",
        f"- latest_package_version: `{status.get('latest_package_version')}`",
        f"- package_dir: `{status.get('package_dir')}`",
        f"- manifest: `{status.get('manifest')}`",
        f"- houdini_manifest: `{status.get('houdini_manifest')}`",
        f"- qa_status: `{status.get('qa_status')}`",
        f"- qa_gate_status: `{status.get('qa_gate_status')}`",
        f"- qa_warning_summary: `{json.dumps(qa_summary, ensure_ascii=False)}`",
        "",
        "## Counts",
        "",
    ]
    for key in sorted(counts):
        lines.append(f"- {key}: `{counts[key]}`")
    lines.extend([
        "",
        "## Semantic Review",
        "",
        f"- status: `{semantic.get('status')}`",
        f"- active_lane_policy: `{semantic.get('active_lane_policy')}`",
        f"- width_fallback_ratio: `{semantic.get('width_fallback_ratio')}`",
        f"- lanes_fallback_ratio: `{semantic.get('lanes_fallback_ratio')}`",
        f"- missing_turn_lanes_ratio: `{semantic.get('missing_turn_lanes_ratio')}`",
        f"- lane_count_policy_override_ratio: `{semantic.get('lane_count_policy_override_ratio')}`",
        f"- direction_policy_override_ratio: `{semantic.get('direction_policy_override_ratio')}`",
        f"- source_oneway_ignored_approaches: `{semantic.get('source_oneway_ignored_approaches')}`",
        "",
        "## Handoff Rule",
        "",
        status.get("handoff_rule", ""),
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the current LaneForge status snapshot.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--json-output", default="")
    parser.add_argument("--md-output", default="")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    status = build_status(root, args.area_id)
    json_output = Path(args.json_output) if args.json_output else root / "reports" / f"{args.area_id}_laneforge_current_status.json"
    md_output = Path(args.md_output) if args.md_output else root / "CURRENT_LANEFORGE_STATUS.md"
    write_json(json_output, status)
    md_output.write_text(markdown_status(status), encoding="utf-8")
    print(json.dumps({
        "status": "generated",
        "json_output": rel(json_output, root),
        "md_output": rel(md_output, root),
        "latest_package_version": status.get("latest_package_version"),
        "qa_gate_status": status.get("qa_gate_status"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
