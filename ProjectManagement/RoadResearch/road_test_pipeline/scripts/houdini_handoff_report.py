#!/usr/bin/env python3
"""Build a read-only Houdini handoff QA report for a LaneForge package."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

SYSTEM_NAME = "LaneForge"
REPORT_SCHEMA = "lane_upgrade_system.houdini_handoff_report.v1"
IMPORT_QA_SCHEMA = "lane_upgrade_system.houdini_import_qa_report.v1"
PACKAGE_SCHEMA = "lane_upgrade_system.standard_lane_package.v1"
HOUDINI_MANIFEST_SCHEMA = "lane_upgrade_system.houdini_manifest.v1"
HOUDINI_HANDOFF_COMPATIBILITY_VERSION = "laneforge_houdini_handoff.v1"
PATH_POLICY = "portable_lane_package_paths_v1"

REQUIRED_HOUDINI_INPUTS = {
    "standard_lanes": "standard_lanes.json",
    "standard_junctions": "standard_junctions.json",
    "standard_lane_surfaces": "standard_lane_surfaces.geojson",
    "standard_lane_surfaces_obj": "standard_lane_surfaces.obj",
}

REQUIRED_HOUDINI_OUTPUTS = [
    "OUT_roads_centerlines",
    "OUT_lane_connections_debug",
    "OUT_lane_surfaces_v1",
]

REQUIRED_PRIMITIVE_GROUPS = [
    "lane_surface_v1",
    "lane_turn_surface_v1",
    "lane_continuity_surface_v1",
    "junction_envelope_surface_v1",
]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def artifact_identity(path: Path, *, root: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": rel(path, root),
        "exists": path.exists(),
    }
    if not path.exists():
        return record
    stat = path.stat()
    record.update({
        "size_bytes": stat.st_size,
        "mtime_utc": stat.st_mtime,
        "sha256": sha256_file(path),
    })
    return record


def sorted_count_dict(mapping: dict[str, int]) -> dict[str, int]:
    return dict(sorted(mapping.items(), key=lambda item: (-item[1], item[0])))


def is_warning_tier(tier: str) -> bool:
    return str(tier or "") not in {"", "info", "pass"}


def handoff_entry(
    *,
    check_id: str,
    tier: str,
    message: str,
    recommendation: str = "",
    value: Any = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "stage": "houdini_handoff",
        "check_id": check_id,
        "tier": tier,
        "scope": "latest_lane_package",
        "message": message,
        "recommendation": recommendation,
        "value": value,
        "evidence": evidence or {},
    }


def package_root_dir(root: Path, area_id: str) -> Path:
    return root / "data" / "lane_upgrade_packages" / area_id


def latest_manifest_path(root: Path, area_id: str, package_version: str = "") -> tuple[Path, dict[str, Any], str]:
    latest_path = package_root_dir(root, area_id) / "latest.json"
    latest = read_json(latest_path)
    version = package_version or str(latest.get("latest_package_version") or latest.get("latest_package_dir") or "")
    manifest_name = str(latest.get("manifest") or "manifest.json")
    return package_root_dir(root, area_id) / version / manifest_name, latest, version


def resolve_package_path(root: Path, package_dir: Path, value: str) -> Path:
    text = str(value or "").strip()
    if not text:
        return package_dir
    path = Path(text)
    if path.is_absolute():
        return path
    if len(path.parts) > 1 and path.parts[0] == "data":
        return root / path
    return package_dir / path


def registry_entries_for_version(root: Path, area_id: str, package_version: str) -> list[dict[str, Any]]:
    registry = read_json(package_root_dir(root, area_id) / "package_milestones.json")
    entries = registry.get("entries") if isinstance(registry, dict) else []
    if not isinstance(entries, list):
        return []
    return [
        entry for entry in entries
        if isinstance(entry, dict) and str(entry.get("package_version") or "") == package_version
    ]


def stable_milestone_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stable_statuses = {
        "stable_handoff",
        "stable_handoff_approved",
        "approved_for_houdini_handoff",
        "published_stable",
    }
    return [
        entry for entry in entries
        if str(entry.get("status") or "") in stable_statuses
        or str(entry.get("handoff_status") or "") in stable_statuses
    ]


def build_input_assets(
    *,
    root: Path,
    package_dir: Path,
    manifest: dict[str, Any],
    houdini_manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    inputs = houdini_manifest.get("inputs") or {}
    package_artifacts = manifest.get("package_artifacts") or {}
    embedded_hashes = houdini_manifest.get("input_asset_hashes") or {}
    names = sorted(set(REQUIRED_HOUDINI_INPUTS) | set(inputs))
    assets: list[dict[str, Any]] = []
    for name in names:
        input_path = str(inputs.get(name) or REQUIRED_HOUDINI_INPUTS.get(name) or "")
        actual_path = resolve_package_path(root, package_dir, input_path)
        actual = artifact_identity(actual_path, root=root)
        package_record = package_artifacts.get(name) or {}
        embedded_record = embedded_hashes.get(name) or {}
        declared_sha = str(package_record.get("sha256") or "")
        embedded_sha = str(embedded_record.get("sha256") or "")
        actual_sha = str(actual.get("sha256") or "")
        assets.append({
            "name": name,
            "input_path": input_path,
            "exists": bool(actual.get("exists")),
            "declared_path": str(package_record.get("path") or ""),
            "declared_sha256": declared_sha,
            "embedded_houdini_sha256": embedded_sha,
            "actual_sha256": actual_sha,
            "package_artifact_hash_matches": bool(declared_sha and actual_sha and declared_sha == actual_sha),
            "embedded_houdini_hash_matches": (not embedded_sha) or bool(actual_sha and embedded_sha == actual_sha),
            "size_bytes": actual.get("size_bytes", 0),
        })
    return assets


def build_houdini_import_qa_report(
    *,
    root: Path,
    area_id: str,
    package_version: str,
    input_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    rebuild_report = read_json(root / "reports" / f"{area_id}_rebuild_report.json")
    houdini_status = str(rebuild_report.get("houdini_status") or "unknown")
    missing_inputs = [asset for asset in input_assets if not asset.get("exists")]
    hash_mismatches = [
        asset for asset in input_assets
        if not asset.get("package_artifact_hash_matches") or not asset.get("embedded_houdini_hash_matches")
    ]
    if missing_inputs or hash_mismatches:
        status = "input_contract_failed"
    elif houdini_status == "completed":
        status = "houdini_import_smoke_pass"
    elif houdini_status == "skipped":
        status = "houdini_import_not_run"
    else:
        status = "houdini_import_manual_review_required"
    return {
        "type": "houdini_import_qa_report",
        "schema": IMPORT_QA_SCHEMA,
        "area_id": area_id,
        "package_version": package_version,
        "status": status,
        "houdini_status": houdini_status,
        "read_only": True,
        "source_report": rel(root / "reports" / f"{area_id}_rebuild_report.json", root),
        "input_count": len(input_assets),
        "missing_input_count": len(missing_inputs),
        "hash_mismatch_count": len(hash_mismatches),
    }


def build_houdini_handoff_report(root: Path, area_id: str, package_version: str = "") -> dict[str, Any]:
    manifest_path, latest, resolved_version = latest_manifest_path(root, area_id, package_version)
    package_dir = manifest_path.parent
    manifest = read_json(manifest_path)
    metadata = manifest.get("metadata") or {}
    contents = manifest.get("contents") or {}
    houdini_manifest_path = resolve_package_path(root, package_dir, str(contents.get("houdini_manifest") or "houdini_manifest.json"))
    houdini_manifest = read_json(houdini_manifest_path)
    houdini_meta = houdini_manifest.get("metadata") or {}
    input_assets = build_input_assets(
        root=root,
        package_dir=package_dir,
        manifest=manifest,
        houdini_manifest=houdini_manifest,
    )
    missing_inputs = [asset for asset in input_assets if not asset.get("exists")]
    missing_hashes = [asset for asset in input_assets if not asset.get("declared_sha256")]
    hash_mismatches = [
        asset for asset in input_assets
        if not asset.get("package_artifact_hash_matches") or not asset.get("embedded_houdini_hash_matches")
    ]
    expected_outputs = [str(item) for item in houdini_manifest.get("expected_houdini_outputs") or []]
    primitive_groups = [str(item) for item in houdini_manifest.get("primitive_groups") or []]
    missing_outputs = [item for item in REQUIRED_HOUDINI_OUTPUTS if item not in expected_outputs]
    missing_groups = [item for item in REQUIRED_PRIMITIVE_GROUPS if item not in primitive_groups]
    milestone_entries = registry_entries_for_version(root, area_id, resolved_version)
    stable_entries = stable_milestone_entries(milestone_entries)
    qa_gate_status = str(metadata.get("qa_gate_status") or (manifest.get("qa_gate") or {}).get("status") or latest.get("qa_gate_status") or "")
    semantic_status = str((manifest.get("semantic_review") or {}).get("status") or "")
    compatibility_version = str(houdini_meta.get("compatibility_version") or "")
    import_qa = build_houdini_import_qa_report(
        root=root,
        area_id=area_id,
        package_version=resolved_version,
        input_assets=input_assets,
    )

    checks = [
        handoff_entry(
            check_id="manifest_schema_compatibility",
            tier=(
                "pass"
                if metadata.get("schema") == PACKAGE_SCHEMA
                and houdini_meta.get("schema") == HOUDINI_MANIFEST_SCHEMA
                and metadata.get("path_policy") == PATH_POLICY
                and houdini_meta.get("path_policy") == PATH_POLICY
                and str(metadata.get("package_version") or "") == str(houdini_meta.get("package_version") or "")
                else "manual_review_required"
            ),
            message="Package and Houdini manifest schemas are compatible（数据包与 Houdini 清单架构兼容）.",
            recommendation="Keep Houdini reading the package manifest, not pipeline internals（保持 Houdini 读取数据包清单，不读取管线内部文件）.",
            value={
                "package_schema": metadata.get("schema", ""),
                "houdini_schema": houdini_meta.get("schema", ""),
                "path_policy": metadata.get("path_policy", ""),
                "houdini_path_policy": houdini_meta.get("path_policy", ""),
                "package_version": metadata.get("package_version", ""),
                "houdini_package_version": houdini_meta.get("package_version", ""),
            },
        ),
        handoff_entry(
            check_id="compatibility_version_declared",
            tier="pass" if compatibility_version == HOUDINI_HANDOFF_COMPATIBILITY_VERSION else "manual_review_required",
            message=(
                "Houdini compatibility version is declared（Houdini 兼容版本已声明）."
                if compatibility_version
                else "Houdini compatibility version is missing（Houdini 兼容版本缺失）."
            ),
            recommendation="Rebuild the next package with Stage 8 compatibility metadata（下一次发布数据包时写入阶段八兼容元数据）.",
            value={
                "required_compatibility_version": HOUDINI_HANDOFF_COMPATIBILITY_VERSION,
                "actual_compatibility_version": compatibility_version,
            },
        ),
        handoff_entry(
            check_id="houdini_input_missing_file_check",
            tier="pass" if not missing_inputs else "blocker",
            message=(
                "All Houdini input files exist（Houdini 输入文件全部存在）."
                if not missing_inputs
                else "Some Houdini input files are missing（部分 Houdini 输入文件缺失）."
            ),
            recommendation="Do not cook Houdini until all package inputs exist（输入文件完整前不要执行 Houdini 构建）.",
            value={"missing_input_count": len(missing_inputs), "input_count": len(input_assets)},
            evidence={"missing_inputs": missing_inputs},
        ),
        handoff_entry(
            check_id="input_asset_hash_validation",
            tier="pass" if not missing_hashes and not hash_mismatches else "manual_review_required",
            message=(
                "Houdini input asset hashes match package artifacts（Houdini 输入资产哈希与数据包资产记录一致）."
                if not missing_hashes and not hash_mismatches
                else "Houdini input asset hashes need review（Houdini 输入资产哈希需要复核）."
            ),
            recommendation="Treat package_artifacts sha256 as the source of asset identity（以 package_artifacts 的 sha256 作为资产身份真值）.",
            value={
                "input_count": len(input_assets),
                "missing_hash_count": len(missing_hashes),
                "hash_mismatch_count": len(hash_mismatches),
            },
            evidence={"hash_mismatches": hash_mismatches, "missing_hashes": missing_hashes},
        ),
        handoff_entry(
            check_id="houdini_outputs_contract",
            tier="pass" if not missing_outputs and not missing_groups else "manual_review_required",
            message=(
                "Expected Houdini outputs and primitive groups are declared（预期 Houdini 输出与图元组已声明）."
                if not missing_outputs and not missing_groups
                else "Houdini output contract needs review（Houdini 输出合同需要复核）."
            ),
            recommendation="Keep output node and primitive group names stable for downstream tools（保持输出节点与图元组命名稳定）.",
            value={
                "missing_output_count": len(missing_outputs),
                "missing_primitive_group_count": len(missing_groups),
            },
            evidence={"missing_outputs": missing_outputs, "missing_primitive_groups": missing_groups},
        ),
        handoff_entry(
            check_id="package_boundary_contract",
            tier="pass" if (manifest.get("publish_policy") or {}).get("houdini_consumes_package_outputs_only") else "manual_review_required",
            message="Houdini consumes package outputs only（Houdini 只消费数据包输出）.",
            recommendation="Never let Houdini discover data/processed internals directly（不要让 Houdini 直接发现 data/processed 内部文件）.",
            value={
                "houdini_consumes_package_outputs_only": bool((manifest.get("publish_policy") or {}).get("houdini_consumes_package_outputs_only")),
            },
        ),
        handoff_entry(
            check_id="houdini_import_qa_report",
            tier="pass" if import_qa.get("status") == "houdini_import_smoke_pass" else "manual_review_required",
            message=(
                "Houdini import smoke report is passing（Houdini 导入冒烟报告通过）."
                if import_qa.get("status") == "houdini_import_smoke_pass"
                else "Houdini import smoke report is not passing yet（Houdini 导入冒烟报告尚未通过）."
            ),
            recommendation="Run a Houdini smoke import before stable handoff（稳定交付前运行 Houdini 冒烟导入）.",
            value=import_qa,
        ),
        handoff_entry(
            check_id="stable_handoff_readiness",
            tier=(
                "pass"
                if stable_entries
                and qa_gate_status in {"pass", "publishable"}
                and semantic_status in {"pass", "publishable", "reviewed"}
                and import_qa.get("status") == "houdini_import_smoke_pass"
                else "manual_review_required"
            ),
            message=(
                "Package is ready for stable Houdini handoff（数据包可稳定交付 Houdini）."
                if stable_entries
                and qa_gate_status in {"pass", "publishable"}
                and semantic_status in {"pass", "publishable", "reviewed"}
                and import_qa.get("status") == "houdini_import_smoke_pass"
                else "Package is not stable Houdini handoff yet（数据包尚未达到 Houdini 稳定交付）."
            ),
            recommendation="Promote only after QA, semantic review and Houdini smoke import all pass（质量、语义和 Houdini 冒烟导入全部通过后再提升）.",
            value={
                "qa_gate_status": qa_gate_status,
                "semantic_review_status": semantic_status,
                "stable_milestone_count": len(stable_entries),
                "import_qa_status": import_qa.get("status", ""),
            },
        ),
    ]

    tier_counts: dict[str, int] = {}
    for check in checks:
        tier = str(check.get("tier") or "unknown")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    warning_count = sum(1 for check in checks if is_warning_tier(str(check.get("tier") or "")))
    return {
        "type": "houdini_handoff_report",
        "schema": REPORT_SCHEMA,
        "area_id": area_id,
        "system": SYSTEM_NAME,
        "read_only": True,
        "mutation_policy": "review_only_no_houdini_or_package_mutation（只审查不修改 Houdini 或数据包）",
        "status": "manual_review_required" if warning_count else "houdini_handoff_pass",
        "scoped_warning_count": warning_count,
        "check_count": len(checks),
        "tier_counts": sorted_count_dict(tier_counts),
        "package": {
            "version": resolved_version,
            "manifest": rel(manifest_path, root),
            "package_dir": rel(package_dir, root),
            "qa_gate_status": qa_gate_status,
            "semantic_review_status": semantic_status,
        },
        "compatibility": {
            "required_compatibility_version": HOUDINI_HANDOFF_COMPATIBILITY_VERSION,
            "actual_compatibility_version": compatibility_version,
            "package_schema": metadata.get("schema", ""),
            "houdini_schema": houdini_meta.get("schema", ""),
            "path_policy": metadata.get("path_policy", ""),
        },
        "houdini_manifest": {
            "path": rel(houdini_manifest_path, root),
            "schema": houdini_meta.get("schema", ""),
            "expected_outputs": expected_outputs,
            "primitive_groups": primitive_groups,
        },
        "input_assets": input_assets,
        "missing_files": missing_inputs,
        "import_qa_report": import_qa,
        "checks": checks,
        "reports": {
            "handoff_report": f"reports/{area_id}_houdini_handoff_report.json",
            "rebuild_report": rel(root / "reports" / f"{area_id}_rebuild_report.json", root),
        },
    }


def write_houdini_handoff_report(root: Path, area_id: str, package_version: str = "") -> dict[str, Any]:
    report = build_houdini_handoff_report(root, area_id, package_version)
    write_json(root / "reports" / f"{area_id}_houdini_handoff_report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--package-version", default="")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    report = write_houdini_handoff_report(args.root, args.area_id, args.package_version)
    print(
        f"[HoudiniHandoff] {report['package']['version']} "
        f"{report['status']} ({report['scoped_warning_count']} warnings)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
