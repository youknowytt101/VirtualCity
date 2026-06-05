#!/usr/bin/env python3
"""Serve the LaneForge viewer and local mutation API.

The API keeps browser actions behind the LaneForge command boundary:
viewer click -> preview/apply request -> versioned transaction -> rebuild -> QA
-> package publish -> SVG refresh.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[0]
VISUALIZATIONS_DIR = ROOT / "reports" / "visualizations"
JOBS_DIR = ROOT / "reports" / "viewer_jobs"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import create_lane_upgrade_transaction  # noqa: E402
import houdini_handoff_report  # noqa: E402

SYSTEM_NAME = "LaneForge"
JOB_SCHEMA = "lane_upgrade_system.viewer_job.v1"
API_SCHEMA = "lane_upgrade_system.viewer_api.v1"
SHORT_EDGE_ABSORPTION_THRESHOLD_M = 15.0
ARTERIAL_HIGHWAY_CLASSES = {"motorway", "trunk", "primary", "secondary", "tertiary"}
TURN_CURVE_RADIUS_WARN_M = 4.5
THROUGH_CURVE_RADIUS_WARN_M = 3.0

LANE_UPGRADE_TIMELINE_STEPS: list[dict[str, str]] = [
    {
        "id": "submit_request",
        "label": "submit request（提交请求）",
        "description": "viewer validates the selected road scope and queues a background job",
    },
    {
        "id": "create_transaction",
        "label": "create transaction（创建事务）",
        "description": "write an auditable lane upgrade transaction or restore transaction",
    },
    {
        "id": "rebuild_lane_graph",
        "label": "rebuild lane graph（重建车道图）",
        "description": "rebuild lane centerlines, laneLinks and junction surfaces",
    },
    {
        "id": "run_qa_gate",
        "label": "run QA gate（运行质量门禁）",
        "description": "evaluate QA reports and package gate status from rebuilt artifacts",
    },
    {
        "id": "plan_propagation",
        "label": "plan propagation（规划传播）",
        "description": "refresh proposal-only lane upgrade propagation candidates",
    },
    {
        "id": "publish_package",
        "label": "publish package（发布数据包）",
        "description": "publish the next standard LaneForge package and update latest pointer",
    },
    {
        "id": "export_svg",
        "label": "export SVG QA view（导出 SVG 审查图）",
        "description": "regenerate the SVG review drawing consumed by the live viewer",
    },
]

LANE_UPGRADE_STAGE_PATTERNS: list[tuple[str, str]] = [
    ("Creating active lane upgrade transaction", "create_transaction"),
    ("Rebuilding audited road pipeline", "rebuild_lane_graph"),
    ("Planning LaneForge propagation candidates", "plan_propagation"),
    ("Publishing next LaneForge package", "publish_package"),
    ("Refreshing SVG QA view", "export_svg"),
]

LANE_UPGRADE_TIMELINE_ORDER = [step["id"] for step in LANE_UPGRADE_TIMELINE_STEPS]

jobs: dict[str, dict[str, Any]] = {}
jobs_lock = threading.Lock()
running_job_id: str | None = None


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def json_response(handler: SimpleHTTPRequestHandler, status: int, data: dict[str, Any]) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(payload)


def error_response(handler: SimpleHTTPRequestHandler, status: int, message: str, **extra: Any) -> None:
    json_response(handler, status, {"error": message, **extra})


def read_request_json(handler: SimpleHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def latest_package(area_id: str) -> dict[str, Any]:
    latest_path = ROOT / "data" / "lane_upgrade_packages" / area_id / "latest.json"
    latest = read_json(latest_path)
    return {
        "path": rel(latest_path),
        "data": latest,
    }


def semantic_evidence(area_id: str) -> dict[str, Any]:
    evidence_path = ROOT / "data" / "processed" / f"{area_id}_semantic_evidence_summary.json"
    if not evidence_path.exists():
        evidence_path = ROOT / "reports" / f"{area_id}_semantic_evidence_summary.json"
    return {
        "path": rel(evidence_path),
        "data": read_json(evidence_path),
    }


def semantic_evidence_records(area_id: str, *, road_id: str = "", canonical_road_id: str = "", road_chain_id: str = "") -> dict[str, Any]:
    evidence = semantic_evidence(area_id)
    records = []
    for record in (evidence.get("data") or {}).get("edges", []) or []:
        if road_id and str(record.get("road_id") or "") != road_id:
            continue
        if canonical_road_id and str(record.get("canonical_road_id") or "") != canonical_road_id:
            continue
        if road_chain_id and str(record.get("road_chain_id") or "") != road_chain_id:
            continue
        records.append(record)
    return {
        "type": "semantic_evidence_lookup",
        "schema": "lane_upgrade_system.semantic_evidence_lookup.v1",
        "area_id": area_id,
        "source": evidence["path"],
        "filters": {
            "road_id": road_id,
            "canonical_road_id": canonical_road_id,
            "road_chain_id": road_chain_id,
        },
        "count": len(records),
        "records": records,
    }


def road_graph(area_id: str) -> dict[str, Any]:
    return read_json(ROOT / "data" / "processed" / f"{area_id}_road_graph.json")


def pipeline_audit(area_id: str) -> dict[str, Any]:
    return read_json(ROOT / "reports" / f"{area_id}_pipeline_audit_report.json")


def road_graph_qa(area_id: str) -> dict[str, Any]:
    return read_json(ROOT / "reports" / "qa" / f"{area_id}_road_graph_qa_report.json")


def qa_lookup_edges(
    area_id: str,
    *,
    road_id: str = "",
    canonical_road_id: str = "",
    road_chain_id: str = "",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    graph = road_graph(area_id)
    edges = list(graph.get("edges", []) or [])
    road_ids = set(string_list(road_id))
    canonical_ids = set(string_list(canonical_road_id))
    if road_chain_id:
        selected = [
            edge for edge in edges
            if str(edge.get("road_chain_id") or "") == road_chain_id
        ]
    elif road_ids:
        selected = [
            edge for edge in edges
            if str(edge.get("edge_id") or "") in road_ids
        ]
    elif canonical_ids:
        selected = [
            edge for edge in edges
            if str(edge.get("canonical_road_id") or edge.get("source_feature_id") or "") in canonical_ids
        ]
    else:
        selected = []
    selected.sort(key=lambda edge: (
        str(edge.get("road_chain_id") or ""),
        int(edge.get("road_chain_fragment_index") or 0),
        str(edge.get("edge_id") or ""),
    ))
    return graph, selected


def qa_entry(
    *,
    stage: str,
    check_id: str,
    tier: str,
    scope: str,
    message: str,
    reason: str = "",
    value: Any = None,
    threshold: Any = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "check_id": check_id,
        "tier": tier,
        "scope": scope,
        "message": message,
        "reason": reason,
        "value": value,
        "threshold": threshold,
        "evidence": evidence or {},
    }


def qa_gate_entry_by_check(area_id: str) -> dict[str, dict[str, Any]]:
    entries = (pipeline_audit(area_id).get("qa_gate") or {}).get("entries") or []
    return {
        str(entry.get("check_id") or ""): entry
        for entry in entries
        if str(entry.get("check_id") or "")
    }


def matching_fragmentation_sample(
    area_id: str,
    *,
    selected_road_ids: set[str],
    selected_road_chain_ids: set[str],
) -> dict[str, Any]:
    entry = qa_gate_entry_by_check(area_id).get("road_identity_fragmentation_tracked") or {}
    value = entry.get("value") or {}
    for sample in value.get("samples", []) or []:
        sample_chain = str(sample.get("road_identity_key") or "")
        sample_edges = {str(edge_id) for edge_id in sample.get("edge_ids", []) or [] if str(edge_id)}
        if sample_chain in selected_road_chain_ids or bool(sample_edges & selected_road_ids):
            return sample
    return {}


def selected_node_summary(graph: dict[str, Any], selected_edges: list[dict[str, Any]]) -> dict[str, Any]:
    node_by_id = {
        str(node.get("node_id") or ""): node
        for node in graph.get("nodes", []) or []
        if str(node.get("node_id") or "")
    }
    endpoint_ids: list[str] = []
    for edge in selected_edges:
        for key in ("from_node", "to_node"):
            node_id = str(edge.get(key) or "")
            if node_id and node_id not in endpoint_ids:
                endpoint_ids.append(node_id)
    by_kind: dict[str, list[str]] = {}
    for node_id in endpoint_ids:
        kind = str((node_by_id.get(node_id) or {}).get("kind") or "unknown")
        by_kind.setdefault(kind, []).append(node_id)
    return {
        "endpoint_node_ids": endpoint_ids,
        "endpoint_node_kind_counts": {key: len(value) for key, value in sorted(by_kind.items())},
        "dead_end_node_ids": by_kind.get("dead_end", []),
        "boundary_node_ids": by_kind.get("boundary", []),
        "junction_node_ids": by_kind.get("junction", []),
    }


def semantic_flag_summary(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        for flag in (record.get("review") or {}).get("flags", []) or []:
            key = str(flag or "").strip()
            if key:
                counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def qa_tier_for_semantic_flag(flag: str) -> str:
    if flag in {
        "active_lane_upgrade_transaction",
        "lane_count_set_by_lane_upgrade_transaction",
    }:
        return "info"
    return "manual_review_required"


def is_warning_tier(tier: str) -> bool:
    return str(tier or "") not in {"", "info", "pass"}


def qa_warning_lookup(
    area_id: str,
    *,
    road_id: str = "",
    canonical_road_id: str = "",
    road_chain_id: str = "",
) -> dict[str, Any]:
    graph, selected_edges = qa_lookup_edges(
        area_id,
        road_id=road_id,
        canonical_road_id=canonical_road_id,
        road_chain_id=road_chain_id,
    )
    selected_road_ids = {str(edge.get("edge_id") or "") for edge in selected_edges if str(edge.get("edge_id") or "")}
    selected_canonical_ids = {
        str(edge.get("canonical_road_id") or "")
        for edge in selected_edges
        if str(edge.get("canonical_road_id") or "")
    }
    selected_chain_ids = {
        str(edge.get("road_chain_id") or "")
        for edge in selected_edges
        if str(edge.get("road_chain_id") or "")
    }
    requested_chain = str(road_chain_id or "").strip()
    if requested_chain:
        selected_chain_ids.add(requested_chain)

    qa_gate = pipeline_audit(area_id).get("qa_gate") or {}
    qa_by_check = qa_gate_entry_by_check(area_id)
    node_summary = selected_node_summary(graph, selected_edges)
    evidence_records = semantic_evidence_records(
        area_id,
        road_chain_id=requested_chain,
        road_id="" if requested_chain else ",".join(sorted(selected_road_ids)),
        canonical_road_id="" if requested_chain or selected_road_ids else ",".join(sorted(selected_canonical_ids)),
    ).get("records", []) or []
    if not evidence_records and selected_road_ids:
        all_semantic = semantic_evidence(area_id).get("data", {}).get("edges", []) or []
        evidence_records = [
            record for record in all_semantic
            if str(record.get("road_id") or "") in selected_road_ids
        ]

    entries: list[dict[str, Any]] = []
    width_default_roads = [
        str(edge.get("edge_id") or "")
        for edge in selected_edges
        if str(edge.get("width_source") or "") == "default"
    ]
    lanes_default_roads = [
        str(edge.get("edge_id") or "")
        for edge in selected_edges
        if str(edge.get("lanes_source") or "") == "default"
    ]
    if width_default_roads:
        gate = qa_by_check.get("width_fallback_ratio") or {}
        entries.append(qa_entry(
            stage="road_graph",
            check_id="width_fallback_ratio",
            tier=str(gate.get("tier") or "manual_review_required"),
            scope="selected_roads",
            message="Selected road edges use width fallback（选中道路使用宽度兜底）.",
            reason=str(gate.get("reason") or gate.get("message") or ""),
            value=len(width_default_roads),
            threshold=gate.get("threshold"),
            evidence={"road_ids": width_default_roads},
        ))
    if lanes_default_roads:
        entries.append(qa_entry(
            stage="road_graph",
            check_id="lanes_fallback_selected",
            tier="manual_review_required",
            scope="selected_roads",
            message="Selected road edges use lane-count defaults（选中道路使用车道数默认值）.",
            reason="Lane count is inferred locally; review before unattended propagation.",
            value=len(lanes_default_roads),
            evidence={"road_ids": lanes_default_roads},
        ))
    if node_summary["dead_end_node_ids"]:
        gate = qa_by_check.get("dead_end_ratio") or {}
        entries.append(qa_entry(
            stage="road_graph",
            check_id="selected_dead_end_nodes",
            tier=str(gate.get("tier") or "manual_review_required"),
            scope="selected_endpoints",
            message="Selected scope touches dead-end nodes（选中范围触及断头节点）.",
            reason=str(gate.get("reason") or gate.get("message") or ""),
            value=len(node_summary["dead_end_node_ids"]),
            threshold=gate.get("threshold"),
            evidence={"node_ids": node_summary["dead_end_node_ids"]},
        ))
    if node_summary["dead_end_node_ids"] or node_summary["boundary_node_ids"]:
        gate = qa_by_check.get("dangling_endpoint_ratio") or {}
        entries.append(qa_entry(
            stage="topology_repair",
            check_id="selected_endpoint_review",
            tier=str(gate.get("tier") or "manual_review_required"),
            scope="selected_endpoints",
            message="Selected endpoints need boundary/dead-end review（选中端点需要边界 / 断头复核）.",
            reason=str(gate.get("reason") or gate.get("message") or ""),
            value={
                "dead_end_nodes": len(node_summary["dead_end_node_ids"]),
                "boundary_nodes": len(node_summary["boundary_node_ids"]),
            },
            threshold=gate.get("threshold"),
            evidence={
                "dead_end_node_ids": node_summary["dead_end_node_ids"],
                "boundary_node_ids": node_summary["boundary_node_ids"],
            },
        ))

    fragmentation = matching_fragmentation_sample(
        area_id,
        selected_road_ids=selected_road_ids,
        selected_road_chain_ids=selected_chain_ids,
    )
    if fragmentation:
        gate = qa_by_check.get("road_identity_fragmentation_tracked") or {}
        entries.append(qa_entry(
            stage="pipeline_audit",
            check_id="road_identity_fragmentation_tracked",
            tier=str(gate.get("tier") or "manual_review_required"),
            scope="selected_road_chain",
            message="Selected road-chain is fragmented（选中道路链存在碎片化）.",
            reason=str(gate.get("reason") or gate.get("message") or ""),
            value=int(fragmentation.get("fragment_count") or 0),
            evidence=fragmentation,
        ))

    flag_counts = semantic_flag_summary(evidence_records)
    for flag, count in flag_counts.items():
        tier = qa_tier_for_semantic_flag(flag)
        entries.append(qa_entry(
            stage="semantic_evidence",
            check_id=f"semantic_flag:{flag}",
            tier=tier,
            scope="selected_roads",
            message=(
                f"{flag} recorded for audit（语义标记作为审计信息）."
                if tier == "info"
                else f"{flag} requires review（语义标记需要复核）."
            ),
            value=count,
            evidence={"flag": flag, "count": count},
        ))

    global_entries = [
        qa_entry(
            stage=str(entry.get("stage") or ""),
            check_id=str(entry.get("check_id") or ""),
            tier=str(entry.get("tier") or "manual_review_required"),
            scope="global_qa_gate",
            message=str(entry.get("message") or ""),
            reason=str(entry.get("reason") or ""),
            value=entry.get("value"),
            threshold=entry.get("threshold"),
        )
        for entry in qa_gate.get("entries", []) or []
    ]

    tier_counts: dict[str, int] = {}
    for entry in entries:
        tier = str(entry.get("tier") or "unknown")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    warning_count = sum(1 for entry in entries if is_warning_tier(str(entry.get("tier") or "")))
    return {
        "type": "qa_warning_lookup",
        "schema": "lane_upgrade_system.qa_warning_lookup.v1",
        "area_id": area_id,
        "filters": {
            "road_id": road_id,
            "canonical_road_id": canonical_road_id,
            "road_chain_id": road_chain_id,
        },
        "selection": {
            "road_ids": sorted(selected_road_ids),
            "canonical_road_ids": sorted(selected_canonical_ids),
            "road_chain_ids": sorted(selected_chain_ids),
            **node_summary,
        },
        "qa_gate": {
            "status": str(qa_gate.get("status") or ""),
            "summary": qa_gate.get("summary") or {},
            "policy_id": str(qa_gate.get("policy_id") or ""),
        },
        "scoped_warning_count": warning_count,
        "scoped_entry_count": len(entries),
        "tier_counts": dict(sorted(tier_counts.items())),
        "entries": entries,
        "global_entries": global_entries,
        "reports": {
            "pipeline_audit": rel(ROOT / "reports" / f"{area_id}_pipeline_audit_report.json"),
            "road_graph_qa": rel(ROOT / "reports" / "qa" / f"{area_id}_road_graph_qa_report.json"),
            "road_graph": rel(ROOT / "data" / "processed" / f"{area_id}_road_graph.json"),
            "semantic_evidence": semantic_evidence(area_id).get("path", ""),
        },
    }


def propagation_latest_pointer(area_id: str) -> dict[str, Any]:
    pointer_path = ROOT / "data" / "lane_upgrade_system" / "propagation" / f"{area_id}_latest.json"
    pointer = read_json(pointer_path)
    return {
        "path": rel(pointer_path),
        "data": pointer,
    }


def propagation_artifacts(area_id: str) -> dict[str, Any]:
    pointer = propagation_latest_pointer(area_id)
    pointer_data = pointer.get("data") or {}
    plan_path = ROOT / str(pointer_data.get("latest_plan") or "")
    report_path = ROOT / str(pointer_data.get("latest_report") or "")
    return {
        "pointer": pointer,
        "plan_path": plan_path,
        "report_path": report_path,
        "plan": read_json(plan_path),
        "report": read_json(report_path),
    }


def propagation_confidence_tier(candidate: dict[str, Any]) -> str:
    status = str(candidate.get("status") or "").strip()
    if status == "already_satisfies_target":
        return "already_satisfies_target"
    if status == "candidate_high_confidence":
        return "high_confidence"
    if status in {"candidate_review", "context_review"}:
        return "medium_confidence"
    confidence = float(candidate.get("confidence") or 0.0)
    if confidence >= 0.75:
        return "high_confidence"
    if confidence >= 0.45:
        return "medium_confidence"
    return "low_confidence"


def propagation_risk_policy(candidate: dict[str, Any], tier: str) -> str:
    if tier == "high_confidence":
        return "review_queue_eligible（可进入审查队列）"
    if tier == "medium_confidence":
        return "manual_confirmation_required（需要人工确认）"
    if tier == "low_confidence":
        return "record_only（只记录不推荐）"
    if tier == "already_satisfies_target":
        return "no_action_already_satisfied（已满足无需动作）"
    return "manual_review_required（需要人工复核）"


def propagation_review_queue_path(area_id: str) -> Path:
    return ROOT / "data" / "lane_upgrade_system" / "propagation_review_queue" / f"{area_id}_review_queue.json"


def empty_propagation_review_queue(area_id: str) -> dict[str, Any]:
    return {
        "type": "lane_upgrade_propagation_review_queue",
        "schema": "lane_upgrade_system.propagation_review_queue.v1",
        "area_id": area_id,
        "system": SYSTEM_NAME,
        "path_policy": "pipeline_root_relative_paths_v1",
        "updated_at_local": "",
        "entries": [],
    }


def propagation_review_queue(area_id: str) -> dict[str, Any]:
    queue_path = propagation_review_queue_path(area_id)
    queue = read_json(queue_path)
    if not queue:
        queue = empty_propagation_review_queue(area_id)
    queue.setdefault("entries", [])
    return queue


def propagation_review_queue_key(*, plan_version: str, candidate_id: str) -> str:
    return f"{plan_version}:{candidate_id}"


def queued_candidate_index(queue: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for entry in queue.get("entries", []) or []:
        if str(entry.get("status") or "") not in {"queued_for_review", "reviewing"}:
            continue
        key = propagation_review_queue_key(
            plan_version=str(entry.get("plan_version") or ""),
            candidate_id=str(entry.get("candidate_id") or ""),
        )
        if key.strip(":"):
            index[key] = entry
    return index


def propagation_review_queue_summary(
    queue: dict[str, Any],
    *,
    plan_version: str = "",
    candidate_ids: set[str] | None = None,
) -> dict[str, Any]:
    entries = list(queue.get("entries", []) or [])
    active_entries = [
        entry for entry in entries
        if str(entry.get("status") or "") in {"queued_for_review", "reviewing"}
    ]
    matched_entries = active_entries
    if plan_version:
        matched_entries = [
            entry for entry in matched_entries
            if str(entry.get("plan_version") or "") == plan_version
        ]
    if candidate_ids is not None:
        matched_entries = [
            entry for entry in matched_entries
            if str(entry.get("candidate_id") or "") in candidate_ids
        ]
    status_counts: dict[str, int] = {}
    for entry in entries:
        increment_count(status_counts, str(entry.get("status") or "unknown"))
    return {
        "source": rel(propagation_review_queue_path(str(queue.get("area_id") or ""))),
        "total_entry_count": len(entries),
        "total_active_count": len(active_entries),
        "matched_queued_count": len(matched_entries),
        "status_counts": sorted_count_dict(status_counts),
    }


def propagation_relation(
    candidate: dict[str, Any],
    *,
    selected_road_ids: set[str],
    selected_canonical_ids: set[str],
    selected_node_ids: set[str],
) -> str:
    candidate_road = str(candidate.get("candidate_road_id") or "")
    source_road = str(candidate.get("source_road_id") or "")
    candidate_canonical = str(candidate.get("candidate_canonical_road_id") or "")
    source_canonical = str(candidate.get("source_canonical_road_id") or "")
    junction_node = str(candidate.get("junction_node_id") or "")
    if candidate_road in selected_road_ids or candidate_canonical in selected_canonical_ids:
        return "target_candidate"
    if source_road in selected_road_ids or source_canonical in selected_canonical_ids:
        return "source_upgrade"
    if junction_node and junction_node in selected_node_ids:
        return "junction_context"
    return ""


def propagation_review_candidate(candidate: dict[str, Any], relation: str) -> dict[str, Any]:
    tier = propagation_confidence_tier(candidate)
    return {
        "candidate_id": str(candidate.get("candidate_id") or ""),
        "relation": relation,
        "confidence_tier": tier,
        "status": str(candidate.get("status") or ""),
        "rule_id": str(candidate.get("rule_id") or ""),
        "confidence": round(float(candidate.get("confidence") or 0.0), 3),
        "source": {
            "road_id": str(candidate.get("source_road_id") or ""),
            "canonical_road_id": str(candidate.get("source_canonical_road_id") or ""),
            "upgrade_id": str(candidate.get("source_upgrade_id") or ""),
            "road_class": str(candidate.get("source_road_class") or ""),
            "approach_role": str(candidate.get("source_approach_role") or ""),
        },
        "target": {
            "road_id": str(candidate.get("candidate_road_id") or ""),
            "canonical_road_id": str(candidate.get("candidate_canonical_road_id") or ""),
            "current_physical_lane_count": candidate.get("current_physical_lane_count"),
            "proposed_target_physical_lane_count": candidate.get("proposed_target_physical_lane_count"),
            "length_m": candidate.get("candidate_length_m"),
            "road_class": str(candidate.get("candidate_road_class") or ""),
            "approach_role": str(candidate.get("candidate_approach_role") or ""),
        },
        "junction": {
            "junction_id": str(candidate.get("junction_id") or ""),
            "junction_node_id": str(candidate.get("junction_node_id") or ""),
            "junction_type": str(candidate.get("junction_type") or ""),
            "through_partner_of_source": str(candidate.get("through_partner_of_source") or ""),
        },
        "recommended_action": str(candidate.get("recommended_action") or ""),
        "risk_policy": propagation_risk_policy(candidate, tier),
        "rationale": str(candidate.get("rationale") or ""),
    }


def increment_count(mapping: dict[str, int], key: str) -> None:
    if key:
        mapping[key] = mapping.get(key, 0) + 1


def sorted_count_dict(mapping: dict[str, int]) -> dict[str, int]:
    return dict(sorted(mapping.items(), key=lambda item: (-item[1], item[0])))


def apply_policy_hint_for_candidate(candidate: dict[str, Any]) -> str:
    rule_id = str(candidate.get("rule_id") or "")
    if rule_id == "through_pair_lane_count_continuity_v2":
        return "through_pair_only_v1"
    if rule_id == "short_edge_absorption_lane_count_v2":
        return "short_edge_absorption_only_v1（短边吸收显式应用策略）"
    return "manual_policy_selection_required（需要人工选择策略）"


def propagation_review_queue_entry(
    *,
    area_id: str,
    plan: dict[str, Any],
    selection: dict[str, Any],
    candidate: dict[str, Any],
    queued_by: str,
    source_surface: str,
) -> dict[str, Any]:
    plan_version = str(plan.get("version") or "")
    candidate_id = str(candidate.get("candidate_id") or "")
    queue_item_id = f"rq_{plan_version}_{candidate_id}".replace(":", "_")
    target = candidate.get("target") or {}
    return {
        "queue_item_id": queue_item_id,
        "status": "queued_for_review",
        "queued_at_local": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "queued_by": queued_by,
        "source_surface": source_surface,
        "area_id": area_id,
        "plan_version": plan_version,
        "plan_source": str(plan.get("source") or ""),
        "candidate_id": candidate_id,
        "candidate_status": str(candidate.get("status") or ""),
        "confidence_tier": str(candidate.get("confidence_tier") or ""),
        "rule_id": str(candidate.get("rule_id") or ""),
        "target_road_id": str(target.get("road_id") or ""),
        "target_canonical_road_id": str(target.get("canonical_road_id") or ""),
        "proposed_target_physical_lane_count": target.get("proposed_target_physical_lane_count"),
        "selection": selection,
        "candidate": candidate,
        "manual_review_contract": {
            "geometry_mutation": False,
            "requires_manual_confirmation_before_apply": True,
            "apply_boundary": "apply_lane_upgrade_propagation.py（受控传播应用脚本）",
            "policy_hint": apply_policy_hint_for_candidate(candidate),
            "note": (
                "Queue entry only records review intent（队列项只记录复核意图）; "
                "accepted candidates must still be applied one by one through a transaction（接受后仍需逐条事务应用）."
            ),
        },
    }


def propagation_review_lookup(
    area_id: str,
    *,
    road_id: str = "",
    canonical_road_id: str = "",
    road_chain_id: str = "",
) -> dict[str, Any]:
    graph, selected_edges = qa_lookup_edges(
        area_id,
        road_id=road_id,
        canonical_road_id=canonical_road_id,
        road_chain_id=road_chain_id,
    )
    selected_road_ids = {str(edge.get("edge_id") or "") for edge in selected_edges if str(edge.get("edge_id") or "")}
    selected_canonical_ids = {
        str(edge.get("canonical_road_id") or "")
        for edge in selected_edges
        if str(edge.get("canonical_road_id") or "")
    }
    selected_chain_ids = {
        str(edge.get("road_chain_id") or "")
        for edge in selected_edges
        if str(edge.get("road_chain_id") or "")
    }
    requested_chain = str(road_chain_id or "").strip()
    if requested_chain:
        selected_chain_ids.add(requested_chain)
    node_summary = selected_node_summary(graph, selected_edges)
    selected_node_ids = set(node_summary["endpoint_node_ids"])

    artifacts = propagation_artifacts(area_id)
    plan = artifacts["plan"] or {}
    report = artifacts["report"] or {}
    plan_version = str((plan.get("metadata") or {}).get("version") or "")
    queue = propagation_review_queue(area_id)
    active_queue_index = queued_candidate_index(queue)
    candidates = list(plan.get("candidates", []) or [])
    matched: list[dict[str, Any]] = []
    tier_counts: dict[str, int] = {}
    relation_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    global_tier_counts: dict[str, int] = {}

    for candidate in candidates:
        tier = propagation_confidence_tier(candidate)
        increment_count(global_tier_counts, tier)
        relation = propagation_relation(
            candidate,
            selected_road_ids=selected_road_ids,
            selected_canonical_ids=selected_canonical_ids,
            selected_node_ids=selected_node_ids,
        )
        if not relation:
            continue
        increment_count(tier_counts, tier)
        increment_count(relation_counts, relation)
        increment_count(status_counts, str(candidate.get("status") or ""))
        review_candidate = propagation_review_candidate(candidate, relation)
        queue_key = propagation_review_queue_key(
            plan_version=plan_version,
            candidate_id=str(review_candidate.get("candidate_id") or ""),
        )
        queued_entry = active_queue_index.get(queue_key) or {}
        review_candidate["review_queue"] = {
            "queued": bool(queued_entry),
            "queue_item_id": str(queued_entry.get("queue_item_id") or ""),
            "status": str(queued_entry.get("status") or ""),
        }
        matched.append(review_candidate)

    matched.sort(key=lambda item: (
        {
            "high_confidence": 0,
            "medium_confidence": 1,
            "low_confidence": 2,
            "already_satisfies_target": 3,
        }.get(str(item.get("confidence_tier") or ""), 9),
        {
            "target_candidate": 0,
            "source_upgrade": 1,
            "junction_context": 2,
        }.get(str(item.get("relation") or ""), 9),
        str(item.get("candidate_id") or ""),
    ))
    return {
        "type": "propagation_review_lookup",
        "schema": "lane_upgrade_system.propagation_review_lookup.v1",
        "area_id": area_id,
        "filters": {
            "road_id": road_id,
            "canonical_road_id": canonical_road_id,
            "road_chain_id": road_chain_id,
        },
        "selection": {
            "road_ids": sorted(selected_road_ids),
            "canonical_road_ids": sorted(selected_canonical_ids),
            "road_chain_ids": sorted(selected_chain_ids),
            **node_summary,
        },
        "plan": {
            "version": plan_version,
            "policy": str((plan.get("metadata") or {}).get("policy") or ""),
            "schema": str((plan.get("metadata") or {}).get("schema") or ""),
            "source": rel(artifacts["plan_path"]),
            "pointer": artifacts["pointer"]["path"],
        },
        "report": {
            "source": rel(artifacts["report_path"]),
            "counts": report.get("counts") or {},
            "status_counts": report.get("status_counts") or {},
            "rule_counts": report.get("rule_counts") or {},
            "note": str(report.get("note") or ""),
        },
        "matched_candidate_count": len(matched),
        "total_candidate_count": len(candidates),
        "matched_tier_counts": sorted_count_dict(tier_counts),
        "matched_relation_counts": sorted_count_dict(relation_counts),
        "matched_status_counts": sorted_count_dict(status_counts),
        "global_tier_counts": sorted_count_dict(global_tier_counts),
        "review_queue": propagation_review_queue_summary(
            queue,
            plan_version=plan_version,
            candidate_ids={str(candidate.get("candidate_id") or "") for candidate in matched},
        ),
        "candidates": matched,
    }


def enqueue_propagation_review_candidates(body: dict[str, Any]) -> dict[str, Any]:
    area_id = str(body.get("area_id") or "pattaya_central_500m").strip()
    dry_run = bool(body.get("dry_run"))
    candidate_ids = set(string_list(body.get("candidate_ids") or body.get("candidate_id")))
    lookup = propagation_review_lookup(
        area_id,
        road_id=str(body.get("road_id") or ""),
        canonical_road_id=str(body.get("canonical_road_id") or ""),
        road_chain_id=str(body.get("road_chain_id") or ""),
    )
    plan = lookup.get("plan") or {}
    selection = lookup.get("selection") or {}
    queue = propagation_review_queue(area_id)
    active_queue_index = queued_candidate_index(queue)
    requested_candidates = [
        candidate
        for candidate in lookup.get("candidates", []) or []
        if not candidate_ids or str(candidate.get("candidate_id") or "") in candidate_ids
    ]
    proposed_entries: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for candidate in requested_candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        tier = str(candidate.get("confidence_tier") or "")
        status = str(candidate.get("status") or "")
        if tier != "high_confidence" or status != "candidate_high_confidence":
            skipped.append({
                "candidate_id": candidate_id,
                "reason": "not_high_confidence_candidate（不是高置信可入队候选）",
            })
            continue
        queue_key = propagation_review_queue_key(
            plan_version=str(plan.get("version") or ""),
            candidate_id=candidate_id,
        )
        if queue_key in active_queue_index:
            skipped.append({
                "candidate_id": candidate_id,
                "reason": "already_queued（已在审查队列）",
            })
            continue
        proposed_entries.append(propagation_review_queue_entry(
            area_id=area_id,
            plan=plan,
            selection=selection,
            candidate=candidate,
            queued_by=str(body.get("queued_by") or "web_user"),
            source_surface=str(body.get("source_surface") or "svg_live_viewer"),
        ))

    if not dry_run and proposed_entries:
        queue_entries = list(queue.get("entries", []) or [])
        queue_entries.extend(proposed_entries)
        queue["entries"] = queue_entries
        queue["updated_at_local"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        write_json(propagation_review_queue_path(area_id), queue)
        queue = propagation_review_queue(area_id)

    return {
        "type": "propagation_review_queue_enqueue",
        "schema": "lane_upgrade_system.propagation_review_queue_enqueue.v1",
        "area_id": area_id,
        "dry_run": dry_run,
        "filters": {
            "road_id": str(body.get("road_id") or ""),
            "canonical_road_id": str(body.get("canonical_road_id") or ""),
            "road_chain_id": str(body.get("road_chain_id") or ""),
            "candidate_ids": sorted(candidate_ids),
        },
        "plan": plan,
        "selection": selection,
        "requested_candidate_count": len(requested_candidates),
        "enqueued_count": 0 if dry_run else len(proposed_entries),
        "proposed_enqueue_count": len(proposed_entries),
        "skipped_count": len(skipped),
        "entries": proposed_entries,
        "skipped": skipped,
        "review_queue": propagation_review_queue_summary(
            queue,
            plan_version=str(plan.get("version") or ""),
            candidate_ids={str(entry.get("candidate_id") or "") for entry in proposed_entries},
        ),
    }


def active_lane_upgrade(area_id: str, road_id: str) -> dict[str, Any] | None:
    active_path = ROOT / "data" / "processed" / f"{area_id}_lane_upgrade_overrides.json"
    active = read_json(active_path)
    for item in active.get("active_upgrades", []):
        if str(item.get("road_id") or "") == road_id:
            return item
    return None


def road_chain_id_from_reason(reason: str) -> str:
    match = re.search(r"\brc_[A-Za-z0-9_-]+\b", reason or "")
    return match.group(0) if match else ""


def targets_for_road_chain(
    *,
    road_graph: dict[str, Any],
    edges: list[dict[str, Any]],
    road_chain_id: str,
    graph_path: Path,
) -> list[dict[str, Any]]:
    chain_edges = [
        edge for edge in edges
        if str(edge.get("road_chain_id") or "") == road_chain_id
    ]
    if not chain_edges:
        raise ValueError(f"road_chain_id {road_chain_id} was not found in {graph_path}")
    chain_edges.sort(key=lambda edge: (
        int(edge.get("road_chain_fragment_index") or 0),
        str(edge.get("edge_id") or ""),
    ))
    return [
        {
            "road_id": str(edge.get("edge_id") or ""),
            "canonical_road_id": str(edge.get("canonical_road_id") or ""),
            "road_chain_id": road_chain_id,
            "edge": edge,
            "road_graph": road_graph,
        }
        for edge in chain_edges
    ]


def resolve_lane_upgrade_targets(request: dict[str, Any]) -> list[dict[str, Any]]:
    area_id = request["area_id"]
    graph_path = ROOT / "data" / "processed" / f"{area_id}_road_graph.json"
    road_graph = read_json(graph_path)
    edges = list(road_graph.get("edges", []))
    targets: list[dict[str, Any]] = []

    road_chain_id = str(request.get("road_chain_id") or "") or road_chain_id_from_reason(str(request.get("reason") or ""))
    if road_chain_id:
        return targets_for_road_chain(
            road_graph=road_graph,
            edges=edges,
            road_chain_id=road_chain_id,
            graph_path=graph_path,
        )

    if str(request.get("selection_scope") or "") == "road_chain":
        resolved = create_lane_upgrade_transaction.resolve_road_reference(
            root=ROOT,
            area_id=area_id,
            road_id=request.get("road_id", ""),
            canonical_road_id=request.get("canonical_road_id", ""),
        )
        inferred_chain_id = str((resolved.get("edge") or {}).get("road_chain_id") or "")
        if inferred_chain_id:
            return targets_for_road_chain(
                road_graph=road_graph,
                edges=edges,
                road_chain_id=inferred_chain_id,
                graph_path=graph_path,
            )

    road_ids = list(request.get("road_ids") or [])
    canonical_ids = list(request.get("canonical_road_ids") or [])
    if road_ids or canonical_ids:
        count = max(len(road_ids), len(canonical_ids))
        for index in range(count):
            resolved = create_lane_upgrade_transaction.resolve_road_reference(
                root=ROOT,
                area_id=area_id,
                road_id=road_ids[index] if index < len(road_ids) else "",
                canonical_road_id=canonical_ids[index] if index < len(canonical_ids) else "",
            )
            targets.append({
                "road_id": resolved["road_id"],
                "canonical_road_id": resolved["canonical_road_id"],
                "road_chain_id": str((resolved.get("edge") or {}).get("road_chain_id") or ""),
                "edge": resolved["edge"],
                "road_graph": resolved["road_graph"],
            })
        return targets

    resolved = create_lane_upgrade_transaction.resolve_road_reference(
        root=ROOT,
        area_id=area_id,
        road_id=request["road_id"],
        canonical_road_id=request["canonical_road_id"],
    )
    return [{
        "road_id": resolved["road_id"],
        "canonical_road_id": resolved["canonical_road_id"],
        "road_chain_id": str((resolved.get("edge") or {}).get("road_chain_id") or ""),
        "edge": resolved["edge"],
        "road_graph": resolved["road_graph"],
    }]


def parse_lane_upgrade_request(body: dict[str, Any]) -> dict[str, Any]:
    area_id = str(body.get("area_id") or "pattaya_central_500m").strip()
    road_id = str(body.get("road_id") or "").strip()
    canonical_road_id = str(body.get("canonical_road_id") or "").strip()
    road_ids = string_list(body.get("road_ids"))
    canonical_road_ids = string_list(body.get("canonical_road_ids"))
    road_chain_id = str(body.get("road_chain_id") or "").strip()
    restore_default = bool(body.get("restore_default")) or str(body.get("action") or "") == "restore_road_lane_count_default"
    target = body.get("target_physical_lane_count", body.get("target_lane_count"))
    target_lane_count = 0 if restore_default else int(target or 0)
    if not area_id:
        raise ValueError("area_id is required")
    if not road_id and not canonical_road_id and not road_ids and not canonical_road_ids and not road_chain_id:
        raise ValueError("road_id, canonical_road_id or road_chain_id is required")
    if not restore_default and target_lane_count not in {1, 2, 3, 4}:
        raise ValueError("target_physical_lane_count must be one of 1, 2, 3 or 4")
    return {
        "area_id": area_id,
        "road_id": road_id,
        "canonical_road_id": canonical_road_id,
        "road_ids": road_ids,
        "canonical_road_ids": canonical_road_ids,
        "road_chain_id": road_chain_id,
        "selection_scope": str(body.get("selection_scope") or "").strip(),
        "restore_default": restore_default,
        "target_lane_count": target_lane_count,
        "reason": str(body.get("reason") or ("web restore default lane model" if restore_default else "web menu lane upgrade")),
    }


def semantic_evidence_by_road(area_id: str) -> dict[str, dict[str, Any]]:
    data = semantic_evidence(area_id).get("data") or {}
    return {
        str(record.get("road_id") or ""): record
        for record in data.get("edges", []) or []
        if str(record.get("road_id") or "")
    }


def unique_text(values: list[Any]) -> list[str]:
    output: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in output:
            output.append(text)
    return output


def semantic_flag_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        for flag in (record.get("review") or {}).get("flags", []) or []:
            text = str(flag or "").strip()
            if text:
                counts[text] = counts.get(text, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def physical_lane_count_for_preview_item(item: dict[str, Any], request: dict[str, Any]) -> int:
    if request.get("restore_default"):
        # Current default lane model is the temporary bidirectional two-lane policy.
        return 2
    return max(1, int(item.get("target_physical_lane_count") or request.get("target_lane_count") or 0))


def generated_direction_counts_for_physical_lanes(physical_lane_count: int) -> tuple[int, int]:
    target = max(0, int(physical_lane_count or 0))
    if target <= 0:
        return 1, 1
    if target == 1:
        return 1, 1
    forward = (target + 1) // 2
    backward = target - forward
    return max(1, forward), max(1, backward)


def estimated_physical_lane_surfaces_for_count(physical_lane_count: int) -> int:
    target = max(0, int(physical_lane_count or 0))
    if target <= 0:
        return 2
    return max(1, target)


def road_ids_from_surface_value(value: Any) -> set[str]:
    if isinstance(value, list):
        values = value
    else:
        values = str(value or "").replace(";", ",").split(",")
    return {str(item).strip() for item in values if str(item).strip()}


def lane_road_id(lane_id: Any) -> str:
    match = re.match(r"^(e_\d+)_", str(lane_id or ""))
    return match.group(1) if match else ""


def lane_graph_path(area_id: str) -> Path:
    return ROOT / "data" / "processed" / f"{area_id}_lane_graph.json"


def lane_surface_geojson_path(area_id: str) -> Path:
    return ROOT / "data" / "preview" / f"{area_id}_lane_surfaces_v1.geojson"


def junction_lane_link_records(junction: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for connection in junction.get("connections", []) or []:
        for link in connection.get("lane_links", []) or []:
            item = dict(link)
            from_lane = str(link.get("from_lane") or link.get("from_lane_id") or "")
            to_lane = str(link.get("to_lane") or link.get("to_lane_id") or "")
            item.update({
                "junction_id": str(junction.get("junction_id") or ""),
                "node_id": str(junction.get("node_id") or ""),
                "connection_id": str(connection.get("connection_id") or ""),
                "from_lane": from_lane,
                "to_lane": to_lane,
                "from_road": str(connection.get("from_road") or connection.get("from_edge") or lane_road_id(from_lane)),
                "to_road": str(connection.get("to_road") or connection.get("to_edge") or lane_road_id(to_lane)),
                "turn": str(connection.get("turn") or link.get("turn") or ""),
            })
            records.append(item)
    return records


def lane_link_candidate_count(lane_count: int, turn: str) -> int:
    count = max(0, int(lane_count or 0))
    if count <= 0:
        return 0
    normalized = str(turn or "").strip().lower()
    if normalized == "through":
        return count
    return 1


def current_approach_count(
    junction: dict[str, Any],
    road_id: str,
    direction: str,
) -> int:
    for approach in junction.get("approach_lanes", []) or []:
        if str(approach.get("edge_id") or "") != road_id:
            continue
        return int(approach.get(f"{direction}_lane_count") or 0)
    return 0


def estimated_approach_counts_at_junction(
    *,
    edge: dict[str, Any],
    node_id: str,
    physical_lane_count: int,
) -> dict[str, int]:
    forward_count, backward_count = generated_direction_counts_for_physical_lanes(physical_lane_count)
    if node_id == str(edge.get("to_node") or ""):
        return {"incoming": forward_count, "outgoing": backward_count}
    if node_id == str(edge.get("from_node") or ""):
        return {"incoming": backward_count, "outgoing": forward_count}
    return {"incoming": forward_count, "outgoing": backward_count}


def road_chain_review_entry(
    *,
    check_id: str,
    tier: str,
    message: str,
    recommendation: str = "",
    value: Any = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "stage": "road_chain_upgrade",
        "check_id": check_id,
        "tier": tier,
        "scope": "selected_road_chain",
        "message": message,
        "recommendation": recommendation,
        "value": value,
        "evidence": evidence or {},
    }


def int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def road_chain_groups(edges: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        chain_id = str(edge.get("road_chain_id") or "")
        groups.setdefault(chain_id, []).append(edge)
    output: list[list[dict[str, Any]]] = []
    for chain_id in sorted(groups):
        group = groups[chain_id]
        group.sort(key=lambda item: (
            int(item.get("road_chain_fragment_index") or 0),
            str(item.get("edge_id") or ""),
        ))
        output.append(group)
    return output


def expanded_road_chain_selection(
    area_id: str,
    *,
    road_id: str = "",
    canonical_road_id: str = "",
    road_chain_id: str = "",
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    graph, selected_edges = qa_lookup_edges(
        area_id,
        road_id=road_id,
        canonical_road_id=canonical_road_id,
        road_chain_id=road_chain_id,
    )
    requested_chain_id = str(road_chain_id or "").strip()
    selected_chain_ids = {
        str(edge.get("road_chain_id") or "")
        for edge in selected_edges
        if str(edge.get("road_chain_id") or "")
    }
    if requested_chain_id:
        selected_chain_ids = {requested_chain_id}

    all_edges = list(graph.get("edges", []) or [])
    if selected_chain_ids:
        chain_edges = [
            edge for edge in all_edges
            if str(edge.get("road_chain_id") or "") in selected_chain_ids
        ]
    else:
        chain_edges = selected_edges

    chain_edges.sort(key=lambda edge: (
        str(edge.get("road_chain_id") or ""),
        int(edge.get("road_chain_fragment_index") or 0),
        str(edge.get("edge_id") or ""),
    ))
    return graph, chain_edges, sorted(selected_chain_ids)


def semantic_records_for_road_ids(area_id: str, road_ids: set[str]) -> list[dict[str, Any]]:
    data = semantic_evidence(area_id).get("data") or {}
    records = [
        record for record in data.get("edges", []) or []
        if str(record.get("road_id") or "") in road_ids
    ]
    records.sort(key=lambda record: str(record.get("road_id") or ""))
    return records


def road_chain_review_lane_count(edge: dict[str, Any], semantic_by_road: dict[str, dict[str, Any]]) -> int | None:
    road_id = str(edge.get("edge_id") or "")
    semantic = semantic_by_road.get(road_id) or {}
    active = semantic.get("active_lane_upgrade") or {}
    for value in (
        (semantic.get("geometry") or {}).get("physical_lane_count"),
        active.get("target_physical_lane_count") if isinstance(active, dict) else None,
        edge.get("lanes"),
    ):
        lane_count = int_or_none(value)
        if lane_count is not None and lane_count > 0:
            return lane_count
    return None


def road_chain_source_lane_count(edge: dict[str, Any], semantic_by_road: dict[str, dict[str, Any]]) -> int | None:
    road_id = str(edge.get("edge_id") or "")
    semantic = semantic_by_road.get(road_id) or {}
    for value in (
        (semantic.get("source") or {}).get("lanes"),
        edge.get("lanes"),
    ):
        lane_count = int_or_none(value)
        if lane_count is not None and lane_count > 0:
            return lane_count
    return None


def dominant_int(values: list[int | None]) -> int | None:
    counts: dict[str, int] = {}
    for value in values:
        if value is None:
            continue
        increment_count(counts, str(value))
    if not counts:
        return None
    return int(next(iter(sorted_count_dict(counts).keys())))


def road_chain_selection_summary(
    graph: dict[str, Any],
    chain_edges: list[dict[str, Any]],
    semantic_records: list[dict[str, Any]],
) -> dict[str, Any]:
    semantic_by_road = {
        str(record.get("road_id") or ""): record
        for record in semantic_records
        if str(record.get("road_id") or "")
    }
    lane_count_by_road: dict[str, int] = {}
    source_lane_count_by_road: dict[str, int] = {}
    highway_counts: dict[str, int] = {}
    lane_count_counts: dict[str, int] = {}
    source_lane_count_counts: dict[str, int] = {}
    width_source_counts: dict[str, int] = {}
    short_edge_ids: list[str] = []
    total_length_m = 0.0
    active_override_count = 0
    for edge in chain_edges:
        road_id = str(edge.get("edge_id") or "")
        highway = str(edge.get("highway") or "unknown")
        increment_count(highway_counts, highway)
        length_m = float(edge.get("length_m") or 0.0)
        total_length_m += length_m
        if length_m <= SHORT_EDGE_ABSORPTION_THRESHOLD_M:
            short_edge_ids.append(road_id)
        lane_count = road_chain_review_lane_count(edge, semantic_by_road)
        if lane_count is not None:
            lane_count_by_road[road_id] = lane_count
            increment_count(lane_count_counts, str(lane_count))
        source_lane_count = road_chain_source_lane_count(edge, semantic_by_road)
        if source_lane_count is not None:
            source_lane_count_by_road[road_id] = source_lane_count
            increment_count(source_lane_count_counts, str(source_lane_count))
        width_source = str(
            ((semantic_by_road.get(road_id) or {}).get("source") or {}).get("width_source")
            or edge.get("width_source")
            or "unknown"
        )
        increment_count(width_source_counts, width_source)
        if (semantic_by_road.get(road_id) or {}).get("active_lane_upgrade"):
            active_override_count += 1

    node_summary = selected_node_summary(graph, chain_edges)
    return {
        "road_ids": [str(edge.get("edge_id") or "") for edge in chain_edges if str(edge.get("edge_id") or "")],
        "canonical_road_ids": [str(edge.get("canonical_road_id") or "") for edge in chain_edges if str(edge.get("canonical_road_id") or "")],
        "road_chain_ids": unique_text([edge.get("road_chain_id") for edge in chain_edges]),
        "edge_count": len(chain_edges),
        "total_length_m": round(total_length_m, 3),
        "highway_counts": sorted_count_dict(highway_counts),
        "lane_count_counts": sorted_count_dict(lane_count_counts),
        "source_lane_count_counts": sorted_count_dict(source_lane_count_counts),
        "width_source_counts": sorted_count_dict(width_source_counts),
        "lane_count_by_road": lane_count_by_road,
        "source_lane_count_by_road": source_lane_count_by_road,
        "active_override_count": active_override_count,
        "short_edge_ids": short_edge_ids,
        "short_edge_count": len(short_edge_ids),
        **node_summary,
    }


def arterial_chain_lane_consistency_check(summary: dict[str, Any], chain_edges: list[dict[str, Any]]) -> dict[str, Any]:
    lane_count_counts = summary.get("lane_count_counts") or {}
    highway_counts = summary.get("highway_counts") or {}
    is_arterial = any(highway in ARTERIAL_HIGHWAY_CLASSES for highway in highway_counts)
    inconsistent = len(lane_count_counts) > 1
    tier = "manual_review_required" if inconsistent else "pass"
    message = (
        "Road-chain lane count changes inside the same corridor（同一道路走廊内车道数不一致）."
        if inconsistent
        else "Road-chain lane count is consistent under current geometry（当前几何下道路链车道数一致）."
    )
    if not is_arterial and not inconsistent:
        message = "Non-arterial road-chain is still corridor-consistent（非主干道路链当前也保持走廊一致）."
    return road_chain_review_entry(
        check_id="arterial_chain_lane_consistency",
        tier=tier,
        message=message,
        recommendation=(
            "Review as one corridor before applying more single-edge upgrades（继续单边升级前按整条走廊复核）."
            if inconsistent
            else "Keep using road-chain scoped upgrades for this corridor（继续使用道路链范围升级）."
        ),
        value={
            "is_arterial": is_arterial,
            "lane_count_counts": lane_count_counts,
        },
        evidence={
            "road_ids": summary.get("road_ids") or [],
            "lane_count_by_road": summary.get("lane_count_by_road") or {},
            "highway_counts": highway_counts,
            "edge_count": len(chain_edges),
        },
    )


def short_edge_absorption_check(summary: dict[str, Any], groups: list[list[dict[str, Any]]]) -> dict[str, Any]:
    lane_count_by_road = summary.get("lane_count_by_road") or {}
    items: list[dict[str, Any]] = []
    needs_review = False
    for group in groups:
        group_lane_counts = [lane_count_by_road.get(str(edge.get("edge_id") or "")) for edge in group]
        group_target = dominant_int(group_lane_counts)
        for index, edge in enumerate(group):
            road_id = str(edge.get("edge_id") or "")
            length_m = float(edge.get("length_m") or 0.0)
            if length_m > SHORT_EDGE_ABSORPTION_THRESHOLD_M:
                continue
            neighbor_edges = [
                group[pos] for pos in (index - 1, index + 1)
                if 0 <= pos < len(group)
            ]
            neighbor_lane_counts = unique_text([
                lane_count_by_road.get(str(neighbor.get("edge_id") or ""))
                for neighbor in neighbor_edges
            ])
            recommended = int(neighbor_lane_counts[0]) if len(neighbor_lane_counts) == 1 else group_target
            current = lane_count_by_road.get(road_id)
            status = "already_absorbed" if recommended is not None and current == recommended else "needs_review"
            if status == "needs_review":
                needs_review = True
            items.append({
                "road_id": road_id,
                "road_chain_id": str(edge.get("road_chain_id") or ""),
                "length_m": round(length_m, 3),
                "current_physical_lane_count": current,
                "recommended_physical_lane_count": recommended,
                "neighbor_road_ids": [str(neighbor.get("edge_id") or "") for neighbor in neighbor_edges],
                "neighbor_lane_counts": neighbor_lane_counts,
                "status": status,
            })
    if not items:
        return road_chain_review_entry(
            check_id="short_edge_absorption",
            tier="info",
            message="No short edge inside selected road-chain（选中道路链内没有短边）.",
            recommendation="No short-edge absorption action needed（无需短边吸收动作）.",
            value={"threshold_m": SHORT_EDGE_ABSORPTION_THRESHOLD_M, "short_edge_count": 0},
            evidence={"short_edges": []},
        )
    return road_chain_review_entry(
        check_id="short_edge_absorption",
        tier="manual_review_required" if needs_review else "pass",
        message=(
            "Short edges need lane semantic absorption review（短边需要车道语义吸收复核）."
            if needs_review
            else "Short edges already match adjacent corridor lane semantics（短边已匹配相邻走廊车道语义）."
        ),
        recommendation=(
            "Apply only after confirming the adjacent corridor target（确认相邻走廊目标后再应用）."
            if needs_review
            else "Keep short edges tied to neighboring corridor semantics（保持短边跟随相邻走廊语义）."
        ),
        value={"threshold_m": SHORT_EDGE_ABSORPTION_THRESHOLD_M, "short_edge_count": len(items)},
        evidence={"short_edges": items},
    )


def lane_count_transition_review_check(summary: dict[str, Any], groups: list[list[dict[str, Any]]]) -> dict[str, Any]:
    lane_count_by_road = summary.get("lane_count_by_road") or {}
    transitions: list[dict[str, Any]] = []
    for group in groups:
        for before, after in zip(group, group[1:]):
            before_id = str(before.get("edge_id") or "")
            after_id = str(after.get("edge_id") or "")
            before_count = lane_count_by_road.get(before_id)
            after_count = lane_count_by_road.get(after_id)
            if before_count is None or after_count is None or before_count == after_count:
                continue
            transitions.append({
                "from_road_id": before_id,
                "to_road_id": after_id,
                "from_physical_lane_count": before_count,
                "to_physical_lane_count": after_count,
                "delta": after_count - before_count,
                "status": "transition_requires_review",
            })
    return road_chain_review_entry(
        check_id="lane_count_transition_review",
        tier="manual_review_required" if transitions else "pass",
        message=(
            "Lane-count transitions exist inside the selected road-chain（选中道路链内部存在车道数变化）."
            if transitions
            else "No lane-count transition inside selected road-chain（选中道路链内部没有车道数变化）."
        ),
        recommendation=(
            "Confirm taper, merge or junction intent before applying geometry（应用几何前确认渐变、并线或路口意图）."
            if transitions
            else "No transition-specific action needed before the next review stage（进入下一复核阶段前无需车道变化专项动作）."
        ),
        value={"transition_count": len(transitions)},
        evidence={"transitions": transitions},
    )


def junction_approach_continuity_check(
    *,
    area_id: str,
    graph: dict[str, Any],
    chain_edges: list[dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, Any]:
    lane_count_by_road = summary.get("lane_count_by_road") or {}
    node_by_id = {
        str(node.get("node_id") or ""): node
        for node in graph.get("nodes", []) or []
        if str(node.get("node_id") or "")
    }
    lane_graph = read_json(lane_graph_path(area_id))
    junction_by_node = {
        str(junction.get("node_id") or ""): junction
        for junction in lane_graph.get("junctions", []) or []
        if str(junction.get("node_id") or "")
    }
    chain_road_ids = set(summary.get("road_ids") or [])
    approach_items: list[dict[str, Any]] = []
    through_pair_items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    for edge in chain_edges:
        road_id = str(edge.get("edge_id") or "")
        lane_count = lane_count_by_road.get(road_id)
        if lane_count is None:
            continue
        for node_key in ("from_node", "to_node"):
            node_id = str(edge.get(node_key) or "")
            node = node_by_id.get(node_id) or {}
            if str(node.get("kind") or "") != "junction":
                continue
            junction = junction_by_node.get(node_id)
            if not junction:
                issue = {
                    "road_id": road_id,
                    "node_id": node_id,
                    "reason": "missing_lane_graph_junction（车道图缺少路口对象）",
                }
                issues.append(issue)
                approach_items.append(issue)
                continue
            approach = next(
                (
                    item for item in junction.get("approach_lanes", []) or []
                    if str(item.get("edge_id") or "") == road_id
                ),
                {},
            )
            semantic_approach = next(
                (
                    item for item in junction.get("semantic_approaches", []) or []
                    if str(item.get("edge_id") or "") == road_id
                ),
                {},
            )
            if not approach:
                issue = {
                    "road_id": road_id,
                    "node_id": node_id,
                    "junction_id": str(junction.get("junction_id") or ""),
                    "reason": "missing_approach_lane_record（缺少入口车道记录）",
                }
                issues.append(issue)
                approach_items.append(issue)
                continue
            expected = estimated_approach_counts_at_junction(
                edge=edge,
                node_id=node_id,
                physical_lane_count=lane_count,
            )
            incoming = int(approach.get("incoming_lane_count") or 0)
            outgoing = int(approach.get("outgoing_lane_count") or 0)
            status = "continuous"
            if incoming != expected["incoming"] or outgoing != expected["outgoing"]:
                status = "count_mismatch"
                issues.append({
                    "road_id": road_id,
                    "node_id": node_id,
                    "junction_id": str(junction.get("junction_id") or ""),
                    "actual": {"incoming": incoming, "outgoing": outgoing},
                    "expected": expected,
                    "reason": "approach_lane_count_mismatch（入口车道数不匹配）",
                })
            approach_items.append({
                "road_id": road_id,
                "node_id": node_id,
                "junction_id": str(junction.get("junction_id") or ""),
                "junction_type": str(junction.get("type") or ""),
                "role": str(semantic_approach.get("role") or approach.get("role") or ""),
                "incoming_lane_count": incoming,
                "outgoing_lane_count": outgoing,
                "expected_incoming_lane_count": expected["incoming"],
                "expected_outgoing_lane_count": expected["outgoing"],
                "policy_issues": semantic_approach.get("policy_issues") or [],
                "status": status,
            })

    for junction in junction_by_node.values():
        node_id = str(junction.get("node_id") or "")
        for pair in junction.get("semantic_through_pairs", []) or []:
            edge_a = str(pair.get("edge_a") or "")
            edge_b = str(pair.get("edge_b") or "")
            if edge_a not in chain_road_ids or edge_b not in chain_road_ids:
                continue
            count_a = lane_count_by_road.get(edge_a)
            count_b = lane_count_by_road.get(edge_b)
            status = "continuous" if count_a == count_b else "through_pair_count_mismatch"
            item = {
                "node_id": node_id,
                "junction_id": str(junction.get("junction_id") or ""),
                "edge_a": edge_a,
                "edge_b": edge_b,
                "edge_a_physical_lane_count": count_a,
                "edge_b_physical_lane_count": count_b,
                "status": status,
            }
            through_pair_items.append(item)
            if status != "continuous":
                issues.append({
                    **item,
                    "reason": "through_pair_lane_count_mismatch（直行对车道数不匹配）",
                })

    if not approach_items:
        return road_chain_review_entry(
            check_id="junction_approach_continuity",
            tier="info",
            message="Selected road-chain has no junction approach in current scope（选中道路链当前范围没有路口入口）.",
            recommendation="Continue with corridor review; no junction approach check was triggered（继续走廊审查；未触发路口入口检查）.",
            value={"approach_count": 0, "issue_count": 0},
            evidence={"approaches": [], "through_pairs": []},
        )
    return road_chain_review_entry(
        check_id="junction_approach_continuity",
        tier="manual_review_required" if issues else "pass",
        message=(
            "Junction approaches need continuity review（路口入口连续性需要复核）."
            if issues
            else "Junction approaches are continuous with current lane geometry（路口入口与当前车道几何连续）."
        ),
        recommendation=(
            "Review laneLinks at affected junctions before publishing more upgrades（继续发布升级前复核受影响路口 laneLinks）."
            if issues
            else "Use the junction stage for movement-level checks next（下一步进入路口 movement 级检查）."
        ),
        value={"approach_count": len(approach_items), "issue_count": len(issues)},
        evidence={
            "approaches": approach_items,
            "through_pairs": through_pair_items,
            "issues": issues,
        },
    )


def road_chain_review_lookup(
    area_id: str,
    *,
    road_id: str = "",
    canonical_road_id: str = "",
    road_chain_id: str = "",
) -> dict[str, Any]:
    graph, chain_edges, selected_chain_ids = expanded_road_chain_selection(
        area_id,
        road_id=road_id,
        canonical_road_id=canonical_road_id,
        road_chain_id=road_chain_id,
    )
    road_ids = {str(edge.get("edge_id") or "") for edge in chain_edges if str(edge.get("edge_id") or "")}
    semantic_records = semantic_records_for_road_ids(area_id, road_ids)
    summary = road_chain_selection_summary(graph, chain_edges, semantic_records)
    groups = road_chain_groups(chain_edges)
    checks = [
        arterial_chain_lane_consistency_check(summary, chain_edges),
        short_edge_absorption_check(summary, groups),
        junction_approach_continuity_check(
            area_id=area_id,
            graph=graph,
            chain_edges=chain_edges,
            summary=summary,
        ),
        lane_count_transition_review_check(summary, groups),
    ]
    tier_counts: dict[str, int] = {}
    for check in checks:
        increment_count(tier_counts, str(check.get("tier") or "unknown"))
    warning_count = sum(1 for check in checks if is_warning_tier(str(check.get("tier") or "")))
    return {
        "type": "road_chain_review_lookup",
        "schema": "lane_upgrade_system.road_chain_review_lookup.v1",
        "area_id": area_id,
        "read_only": True,
        "mutation_policy": "review_only_no_geometry_mutation（只审查不修改几何）",
        "filters": {
            "road_id": road_id,
            "canonical_road_id": canonical_road_id,
            "road_chain_id": road_chain_id,
        },
        "selection": {
            "requested_road_chain_ids": selected_chain_ids,
            **summary,
        },
        "status": "manual_review_required" if warning_count else "corridor_review_pass",
        "scoped_warning_count": warning_count,
        "check_count": len(checks),
        "tier_counts": sorted_count_dict(tier_counts),
        "checks": checks,
        "semantic_records": semantic_records,
        "reports": {
            "road_graph": rel(ROOT / "data" / "processed" / f"{area_id}_road_graph.json"),
            "lane_graph": rel(lane_graph_path(area_id)),
            "semantic_evidence": semantic_evidence(area_id).get("path", ""),
        },
    }


def point_distance(a: Any, b: Any) -> float:
    if not isinstance(a, list) or not isinstance(b, list) or len(a) < 2 or len(b) < 2:
        return 0.0
    try:
        return ((float(a[0]) - float(b[0])) ** 2 + (float(a[1]) - float(b[1])) ** 2) ** 0.5
    except (TypeError, ValueError):
        return 0.0


def triangle_area(a: Any, b: Any, c: Any) -> float:
    if not all(isinstance(point, list) and len(point) >= 2 for point in (a, b, c)):
        return 0.0
    try:
        ax, ay = float(a[0]), float(a[1])
        bx, by = float(b[0]), float(b[1])
        cx, cy = float(c[0]), float(c[1])
    except (TypeError, ValueError):
        return 0.0
    return abs((ax * (by - cy) + bx * (cy - ay) + cx * (ay - by)) / 2.0)


def curve_min_radius(points: Any) -> float | None:
    if not isinstance(points, list) or len(points) < 3:
        return None
    min_radius: float | None = None
    for first, middle, last in zip(points, points[1:], points[2:]):
        side_a = point_distance(first, middle)
        side_b = point_distance(middle, last)
        side_c = point_distance(first, last)
        area = triangle_area(first, middle, last)
        if area <= 0.001 or side_a <= 0 or side_b <= 0 or side_c <= 0:
            continue
        radius = (side_a * side_b * side_c) / (4.0 * area)
        if min_radius is None or radius < min_radius:
            min_radius = radius
    return round(min_radius, 3) if min_radius is not None else None


def junction_review_entry(
    *,
    check_id: str,
    tier: str,
    message: str,
    recommendation: str = "",
    value: Any = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "stage": "junction_semantics",
        "check_id": check_id,
        "tier": tier,
        "scope": "selected_junctions",
        "message": message,
        "recommendation": recommendation,
        "value": value,
        "evidence": evidence or {},
    }


def lane_graph_junction_indexes(area_id: str) -> dict[str, Any]:
    lane_graph = read_json(lane_graph_path(area_id))
    junctions = list(lane_graph.get("junctions", []) or [])
    by_junction_id = {
        str(junction.get("junction_id") or ""): junction
        for junction in junctions
        if str(junction.get("junction_id") or "")
    }
    by_node_id = {
        str(junction.get("node_id") or ""): junction
        for junction in junctions
        if str(junction.get("node_id") or "")
    }
    return {
        "lane_graph": lane_graph,
        "junctions": junctions,
        "by_junction_id": by_junction_id,
        "by_node_id": by_node_id,
    }


def junctions_for_selection(
    area_id: str,
    *,
    road_id: str = "",
    canonical_road_id: str = "",
    road_chain_id: str = "",
    node_id: str = "",
    junction_id: str = "",
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    graph = road_graph(area_id)
    indexes = lane_graph_junction_indexes(area_id)
    selected: list[dict[str, Any]] = []
    selected_node_ids: set[str] = set(string_list(node_id))
    selected_junction_ids: set[str] = set(string_list(junction_id))
    selection_edges: list[dict[str, Any]] = []

    for item in selected_junction_ids:
        junction = indexes["by_junction_id"].get(item)
        if junction:
            selected.append(junction)
            selected_node_ids.add(str(junction.get("node_id") or ""))

    for item in selected_node_ids:
        junction = indexes["by_node_id"].get(item)
        if junction and str(junction.get("junction_id") or "") not in {
            str(existing.get("junction_id") or "") for existing in selected
        }:
            selected.append(junction)
            selected_junction_ids.add(str(junction.get("junction_id") or ""))

    if not selected:
        graph_for_edges, selected_edges = expanded_road_chain_selection(
            area_id,
            road_id=road_id,
            canonical_road_id=canonical_road_id,
            road_chain_id=road_chain_id,
        )[:2]
        graph = graph_for_edges
        selection_edges = selected_edges
        node_summary = selected_node_summary(graph, selection_edges)
        for item in node_summary.get("junction_node_ids", []) or []:
            junction = indexes["by_node_id"].get(str(item))
            if junction:
                selected.append(junction)
                selected_node_ids.add(str(item))
                selected_junction_ids.add(str(junction.get("junction_id") or ""))

    selected.sort(key=lambda junction: str(junction.get("junction_id") or ""))
    selection = {
        "road_ids": [
            str(edge.get("edge_id") or "")
            for edge in selection_edges
            if str(edge.get("edge_id") or "")
        ],
        "road_chain_ids": unique_text([edge.get("road_chain_id") for edge in selection_edges]),
        "node_ids": sorted(selected_node_ids),
        "junction_ids": sorted({
            str(junction.get("junction_id") or "")
            for junction in selected
            if str(junction.get("junction_id") or "")
        }),
    }
    return graph, selected, selection


def junction_lane_link_summary(junctions: list[dict[str, Any]]) -> dict[str, Any]:
    turn_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    lane_link_count = 0
    connection_count = 0
    for junction in junctions:
        connection_count += len(junction.get("connections", []) or [])
        for approach in junction.get("approach_lanes", []) or []:
            increment_count(role_counts, str(approach.get("role") or "unknown"))
        for connection in junction.get("connections", []) or []:
            turn = str(connection.get("turn_normalized") or connection.get("turn") or "unknown")
            increment_count(turn_counts, turn)
            lane_links = connection.get("lane_links", []) or []
            lane_link_count += len(lane_links)
            for link in lane_links:
                increment_count(source_counts, str(link.get("source") or connection.get("source") or "unknown"))
    return {
        "junction_count": len(junctions),
        "connection_count": connection_count,
        "lane_link_count": lane_link_count,
        "turn_counts": sorted_count_dict(turn_counts),
        "approach_role_counts": sorted_count_dict(role_counts),
        "lane_link_source_counts": sorted_count_dict(source_counts),
    }


def junction_lane_count_balance_check(junctions: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    approach_count = 0
    for junction in junctions:
        for approach in junction.get("approach_lanes", []) or []:
            approach_count += 1
            incoming = int(approach.get("incoming_lane_count") or 0)
            outgoing = int(approach.get("outgoing_lane_count") or 0)
            if incoming <= 0 or outgoing <= 0:
                issues.append({
                    "junction_id": str(junction.get("junction_id") or ""),
                    "node_id": str(junction.get("node_id") or ""),
                    "edge_id": str(approach.get("edge_id") or ""),
                    "incoming_lane_count": incoming,
                    "outgoing_lane_count": outgoing,
                    "reason": "missing_enter_or_exit_lane（缺少入口或出口车道）",
                })
            elif abs(incoming - outgoing) > 1:
                issues.append({
                    "junction_id": str(junction.get("junction_id") or ""),
                    "node_id": str(junction.get("node_id") or ""),
                    "edge_id": str(approach.get("edge_id") or ""),
                    "incoming_lane_count": incoming,
                    "outgoing_lane_count": outgoing,
                    "reason": "approach_lane_count_imbalance（入口出口车道数不平衡）",
                })
    return junction_review_entry(
        check_id="junction_lane_count_balance_check",
        tier="manual_review_required" if issues else "pass",
        message=(
            "Some junction approaches have lane-count imbalance（部分路口入口车道数不平衡）."
            if issues
            else "Junction approach lane counts are balanced（路口入口车道数平衡）."
        ),
        recommendation=(
            "Review approach generation and lane-count overrides before publishing（发布前复核入口生成和车道覆盖）."
            if issues
            else "Use movement-level laneLink checks next（下一步看 movement 级 laneLink 检查）."
        ),
        value={"approach_count": approach_count, "issue_count": len(issues)},
        evidence={"issues": issues[:24]},
    )


def approach_exit_lane_compatibility_check(junctions: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    connection_count = 0
    for junction in junctions:
        approaches = {
            str(approach.get("edge_id") or ""): approach
            for approach in junction.get("approach_lanes", []) or []
        }
        for connection in junction.get("connections", []) or []:
            connection_count += 1
            from_road = str(connection.get("from_road") or connection.get("from_edge") or "")
            to_road = str(connection.get("to_road") or connection.get("to_edge") or "")
            turn = str(connection.get("turn_normalized") or connection.get("turn") or "unknown")
            from_approach = approaches.get(from_road) or {}
            to_approach = approaches.get(to_road) or {}
            incoming = int(from_approach.get("incoming_lane_count") or 0)
            outgoing = int(to_approach.get("outgoing_lane_count") or 0)
            expected = min(lane_link_candidate_count(incoming, turn), lane_link_candidate_count(outgoing, turn))
            actual = len(connection.get("lane_links", []) or [])
            if incoming <= 0 or outgoing <= 0 or actual <= 0:
                issues.append({
                    "junction_id": str(junction.get("junction_id") or ""),
                    "node_id": str(junction.get("node_id") or ""),
                    "connection_id": str(connection.get("connection_id") or ""),
                    "from_road": from_road,
                    "to_road": to_road,
                    "turn": turn,
                    "incoming_lane_count": incoming,
                    "outgoing_lane_count": outgoing,
                    "actual_lane_links": actual,
                    "expected_lane_links": expected,
                    "reason": "missing_compatible_lane_link（缺少兼容车道连接）",
                })
            elif actual > expected and expected > 0:
                issues.append({
                    "junction_id": str(junction.get("junction_id") or ""),
                    "node_id": str(junction.get("node_id") or ""),
                    "connection_id": str(connection.get("connection_id") or ""),
                    "from_road": from_road,
                    "to_road": to_road,
                    "turn": turn,
                    "actual_lane_links": actual,
                    "expected_lane_links": expected,
                    "reason": "lane_link_count_exceeds_compatible_capacity（车道连接数超过兼容容量）",
                })
    return junction_review_entry(
        check_id="approach_exit_lane_compatibility_check",
        tier="manual_review_required" if issues else "pass",
        message=(
            "Some movements lack compatible approach/exit laneLinks（部分 movement 缺少兼容入口 / 出口车道连接）."
            if issues
            else "Approach and exit laneLinks are compatible（入口 / 出口车道连接兼容）."
        ),
        recommendation=(
            "Review movement lane pairing before accepting the junction（接受路口前复核 movement 车道配对）."
            if issues
            else "Proceed to curve and conflict review（继续转弯曲线和冲突复核）."
        ),
        value={"connection_count": connection_count, "issue_count": len(issues)},
        evidence={"issues": issues[:24]},
    )


def turn_curve_radius_review(junctions: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    curve_count = 0
    min_radius_seen: float | None = None
    for junction in junctions:
        for connection in junction.get("connections", []) or []:
            turn = str(connection.get("turn_normalized") or connection.get("turn") or "unknown")
            threshold = THROUGH_CURVE_RADIUS_WARN_M if turn == "through" else TURN_CURVE_RADIUS_WARN_M
            for link in connection.get("lane_links", []) or []:
                curve_count += 1
                points = link.get("connecting_curve_xz") or connection.get("connecting_curve_xz") or []
                radius = curve_min_radius(points)
                if radius is None:
                    continue
                if min_radius_seen is None or radius < min_radius_seen:
                    min_radius_seen = radius
                if radius < threshold:
                    issues.append({
                        "junction_id": str(junction.get("junction_id") or ""),
                        "node_id": str(junction.get("node_id") or ""),
                        "connection_id": str(connection.get("connection_id") or ""),
                        "lane_link_id": str(link.get("lane_link_id") or ""),
                        "turn": turn,
                        "min_radius_m": radius,
                        "threshold_m": threshold,
                        "curve_length_m": link.get("curve_length_m") or connection.get("curve_length_m"),
                        "reason": "turn_curve_radius_below_threshold（转弯半径低于阈值）",
                    })
    return junction_review_entry(
        check_id="turn_curve_radius_review",
        tier="manual_review_required" if issues else "pass",
        message=(
            "Some laneLink curves are too tight（部分车道连接曲线过急）."
            if issues
            else "LaneLink curve radii are within current review thresholds（车道连接曲线半径满足当前审查阈值）."
        ),
        recommendation=(
            "Review affected connector curves before surface generation（生成路口面前复核受影响连接曲线）."
            if issues
            else "Keep current connector curve policy for these junctions（当前路口可保持连接曲线策略）."
        ),
        value={
            "curve_count": curve_count,
            "issue_count": len(issues),
            "min_radius_m": min_radius_seen,
            "turn_threshold_m": TURN_CURVE_RADIUS_WARN_M,
            "through_threshold_m": THROUGH_CURVE_RADIUS_WARN_M,
        },
        evidence={"issues": issues[:24]},
    )


def lane_link_conflict_check(junctions: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    lane_link_count = 0
    for junction in junctions:
        from_lane_targets: dict[str, list[dict[str, Any]]] = {}
        lane_link_ids: set[str] = set()
        for connection in junction.get("connections", []) or []:
            for link in connection.get("lane_links", []) or []:
                lane_link_count += 1
                link_id = str(link.get("lane_link_id") or "")
                if link_id:
                    if link_id in lane_link_ids:
                        issues.append({
                            "junction_id": str(junction.get("junction_id") or ""),
                            "node_id": str(junction.get("node_id") or ""),
                            "lane_link_id": link_id,
                            "reason": "duplicate_lane_link_id（重复车道连接编号）",
                        })
                    lane_link_ids.add(link_id)
                from_lane = str(link.get("from_lane") or link.get("from_lane_id") or "")
                to_lane = str(link.get("to_lane") or link.get("to_lane_id") or "")
                turn = str(link.get("turn_normalized") or link.get("turn") or connection.get("turn_normalized") or connection.get("turn") or "")
                if from_lane:
                    from_lane_targets.setdefault(from_lane, []).append({
                        "to_lane": to_lane,
                        "turn": turn,
                        "connection_id": str(connection.get("connection_id") or ""),
                        "lane_link_id": link_id,
                    })
        for from_lane, targets in from_lane_targets.items():
            unique_targets = {f"{item['to_lane']}:{item['turn']}" for item in targets}
            if len(targets) > 3 or len(unique_targets) != len(targets):
                issues.append({
                    "junction_id": str(junction.get("junction_id") or ""),
                    "node_id": str(junction.get("node_id") or ""),
                    "from_lane": from_lane,
                    "target_count": len(targets),
                    "unique_target_count": len(unique_targets),
                    "targets": targets[:8],
                    "reason": "ambiguous_or_duplicate_lane_link_targets（车道连接目标重复或过多）",
                })
    return junction_review_entry(
        check_id="lane_link_conflict_check",
        tier="manual_review_required" if issues else "pass",
        message=(
            "Potential laneLink conflicts were found（发现潜在车道连接冲突）."
            if issues
            else "No laneLink id or target conflict found（未发现车道连接编号或目标冲突）."
        ),
        recommendation=(
            "Review conflicted laneLink fan-out before using this junction for driving（用于驾驶前复核冲突车道连接分叉）."
            if issues
            else "LaneLink conflict risk is low for this selection（当前选择车道连接冲突风险低）."
        ),
        value={"lane_link_count": lane_link_count, "issue_count": len(issues)},
        evidence={"issues": issues[:24]},
    )


def orphan_lane_link_check(area_id: str, junctions: list[dict[str, Any]]) -> dict[str, Any]:
    lane_graph = read_json(lane_graph_path(area_id))
    lane_ids = {str(lane.get("lane_id") or "") for lane in lane_graph.get("lanes", []) or [] if str(lane.get("lane_id") or "")}
    issues: list[dict[str, Any]] = []
    lane_link_count = 0
    for junction in junctions:
        for connection in junction.get("connections", []) or []:
            for link in connection.get("lane_links", []) or []:
                lane_link_count += 1
                from_lane = str(link.get("from_lane") or link.get("from_lane_id") or "")
                to_lane = str(link.get("to_lane") or link.get("to_lane_id") or "")
                missing = []
                if from_lane and from_lane not in lane_ids:
                    missing.append("from_lane")
                if to_lane and to_lane not in lane_ids:
                    missing.append("to_lane")
                if not from_lane or not to_lane:
                    missing.append("empty_lane_ref")
                if missing:
                    issues.append({
                        "junction_id": str(junction.get("junction_id") or ""),
                        "node_id": str(junction.get("node_id") or ""),
                        "connection_id": str(connection.get("connection_id") or ""),
                        "lane_link_id": str(link.get("lane_link_id") or ""),
                        "from_lane": from_lane,
                        "to_lane": to_lane,
                        "missing": missing,
                        "reason": "orphan_lane_link_reference（孤立车道连接引用）",
                    })
    return junction_review_entry(
        check_id="orphan_lane_link_check",
        tier="manual_review_required" if issues else "pass",
        message=(
            "Some laneLinks reference missing lanes（部分车道连接引用缺失车道）."
            if issues
            else "All scoped laneLinks reference existing lanes（当前范围车道连接均引用有效车道）."
        ),
        recommendation=(
            "Rebuild lane graph or repair laneLink references before publishing（发布前重建车道图或修复车道连接引用）."
            if issues
            else "Reference integrity is ready for downstream junction surface review（引用完整性可进入下游路口面复核）."
        ),
        value={"lane_link_count": lane_link_count, "issue_count": len(issues)},
        evidence={"issues": issues[:24]},
    )


def junction_review_lookup(
    area_id: str,
    *,
    road_id: str = "",
    canonical_road_id: str = "",
    road_chain_id: str = "",
    node_id: str = "",
    junction_id: str = "",
) -> dict[str, Any]:
    graph, junctions, selection = junctions_for_selection(
        area_id,
        road_id=road_id,
        canonical_road_id=canonical_road_id,
        road_chain_id=road_chain_id,
        node_id=node_id,
        junction_id=junction_id,
    )
    summary = junction_lane_link_summary(junctions)
    checks = [
        junction_lane_count_balance_check(junctions),
        approach_exit_lane_compatibility_check(junctions),
        turn_curve_radius_review(junctions),
        lane_link_conflict_check(junctions),
        orphan_lane_link_check(area_id, junctions),
    ]
    tier_counts: dict[str, int] = {}
    for check in checks:
        increment_count(tier_counts, str(check.get("tier") or "unknown"))
    warning_count = sum(1 for check in checks if is_warning_tier(str(check.get("tier") or "")))
    return {
        "type": "junction_review_lookup",
        "schema": "lane_upgrade_system.junction_review_lookup.v1",
        "area_id": area_id,
        "read_only": True,
        "mutation_policy": "review_only_no_geometry_mutation（只审查不修改几何）",
        "filters": {
            "road_id": road_id,
            "canonical_road_id": canonical_road_id,
            "road_chain_id": road_chain_id,
            "node_id": node_id,
            "junction_id": junction_id,
        },
        "selection": {
            **selection,
            **summary,
        },
        "status": "manual_review_required" if warning_count else "junction_review_pass",
        "scoped_warning_count": warning_count,
        "check_count": len(checks),
        "tier_counts": sorted_count_dict(tier_counts),
        "checks": checks,
        "reports": {
            "road_graph": rel(ROOT / "data" / "processed" / f"{area_id}_road_graph.json"),
            "lane_graph": rel(lane_graph_path(area_id)),
            "lane_graph_qa": rel(ROOT / "reports" / "qa" / f"{area_id}_lane_graph_qa_report.json"),
        },
        "source_summary": {
            "road_graph_node_count": len(graph.get("nodes", []) or []),
        },
    }


def estimated_connection_lane_link_count(
    *,
    junction: dict[str, Any],
    connection: dict[str, Any],
    target_counts_by_road: dict[str, int],
    target_edges_by_road: dict[str, dict[str, Any]],
) -> int:
    node_id = str(junction.get("node_id") or "")
    from_road = str(connection.get("from_road") or "")
    to_road = str(connection.get("to_road") or "")
    turn = str(connection.get("turn_normalized") or connection.get("turn") or "")

    if from_road in target_counts_by_road and from_road in target_edges_by_road:
        from_count = estimated_approach_counts_at_junction(
            edge=target_edges_by_road[from_road],
            node_id=node_id,
            physical_lane_count=target_counts_by_road[from_road],
        )["incoming"]
    else:
        from_count = current_approach_count(junction, from_road, "incoming")

    if to_road in target_counts_by_road and to_road in target_edges_by_road:
        to_count = estimated_approach_counts_at_junction(
            edge=target_edges_by_road[to_road],
            node_id=node_id,
            physical_lane_count=target_counts_by_road[to_road],
        )["outgoing"]
    else:
        to_count = current_approach_count(junction, to_road, "outgoing")

    return min(lane_link_candidate_count(from_count, turn), lane_link_candidate_count(to_count, turn))


def surface_diff_values(current: int | float, after: int | float) -> dict[str, Any]:
    return {
        "current": current,
        "estimated_after": after,
        "delta": round(float(after) - float(current), 3),
    }


def topology_surface_preview(
    *,
    request: dict[str, Any],
    items: list[dict[str, Any]],
    affected_scope: dict[str, Any],
    targets: list[dict[str, Any]],
) -> dict[str, Any]:
    area_id = str(request.get("area_id") or "pattaya_central_500m")
    selected_road_ids = {str(item.get("road_id") or "") for item in items if str(item.get("road_id") or "")}
    scope_index = affected_scope_index(affected_scope)
    affected_junction_node_ids = set(scope_index["adjacent_junction_node_ids"])
    lane_graph = read_json(lane_graph_path(area_id))
    surface_geojson = read_json(lane_surface_geojson_path(area_id))

    target_counts_by_road = {
        str(item.get("road_id") or ""): physical_lane_count_for_preview_item(item, request)
        for item in items
        if str(item.get("road_id") or "")
    }
    target_edges_by_road = {
        str(target.get("road_id") or ""): target.get("edge") or {}
        for target in targets
        if str(target.get("road_id") or "")
    }

    affected_junctions = [
        junction
        for junction in lane_graph.get("junctions", []) or []
        if str(junction.get("node_id") or "") in affected_junction_node_ids
    ]
    affected_junction_ids = {str(junction.get("junction_id") or "") for junction in affected_junctions}

    current_junction_lane_links = 0
    current_selected_road_lane_links = 0
    current_lane_link_ids: set[str] = set()
    estimated_after_junction_lane_links = 0
    estimated_after_selected_road_lane_links = 0
    junction_details: list[dict[str, Any]] = []
    for junction in affected_junctions:
        junction_current_links = junction_lane_link_records(junction)
        current_junction_lane_links += len(junction_current_links)
        selected_current = [
            link
            for link in junction_current_links
            if str(link.get("from_road") or "") in selected_road_ids
            or str(link.get("to_road") or "") in selected_road_ids
        ]
        current_selected_road_lane_links += len(selected_current)
        current_lane_link_ids.update(str(link.get("lane_link_id") or "") for link in junction_current_links if str(link.get("lane_link_id") or ""))

        junction_estimated = 0
        junction_estimated_selected = 0
        for connection in junction.get("connections", []) or []:
            estimate = estimated_connection_lane_link_count(
                junction=junction,
                connection=connection,
                target_counts_by_road=target_counts_by_road,
                target_edges_by_road=target_edges_by_road,
            )
            junction_estimated += estimate
            if str(connection.get("from_road") or "") in selected_road_ids or str(connection.get("to_road") or "") in selected_road_ids:
                junction_estimated_selected += estimate
        estimated_after_junction_lane_links += junction_estimated
        estimated_after_selected_road_lane_links += junction_estimated_selected
        junction_details.append({
            "junction_id": str(junction.get("junction_id") or ""),
            "node_id": str(junction.get("node_id") or ""),
            "junction_type": str(junction.get("type") or ""),
            "current_lane_links": len(junction_current_links),
            "estimated_after_lane_links": junction_estimated,
            "current_selected_road_lane_links": len(selected_current),
            "estimated_after_selected_road_lane_links": junction_estimated_selected,
        })

    current_lane_surfaces = 0
    current_continuity_surfaces = 0
    current_turn_surfaces = 0
    current_envelope_surfaces = 0
    current_surface_area_m2 = 0.0
    for feature in surface_geojson.get("features", []) or []:
        props = feature.get("properties") or {}
        part = str(props.get("vc_part") or "")
        include = False
        if part == "lane_surface_v1":
            include = bool(road_ids_from_surface_value(props.get("road_id")) & selected_road_ids)
            if include:
                current_lane_surfaces += 1
        elif part == "lane_turn_surface_v1":
            include = str(props.get("lane_link_id") or "") in current_lane_link_ids
            if include:
                current_turn_surfaces += 1
        elif part == "lane_continuity_surface_v1":
            include = (
                str(props.get("from_road") or "") in selected_road_ids
                or str(props.get("to_road") or "") in selected_road_ids
            )
            if include:
                current_continuity_surfaces += 1
        elif part == "junction_envelope_surface_v1":
            include = (
                str(props.get("node_id") or "") in affected_junction_node_ids
                or str(props.get("junction_id") or "") in affected_junction_ids
            )
            if include:
                current_envelope_surfaces += 1
        if include:
            current_surface_area_m2 += float(props.get("area_m2") or 0.0)

    estimated_after_lane_surfaces = sum(
        estimated_physical_lane_surfaces_for_count(count)
        for count in target_counts_by_road.values()
    )
    estimated_after_turn_surfaces = estimated_after_junction_lane_links
    estimated_after_envelope_surfaces = sum(1 for detail in junction_details if int(detail["estimated_after_lane_links"]) > 0)

    current_total_surfaces = (
        current_lane_surfaces
        + current_turn_surfaces
        + current_continuity_surfaces
        + current_envelope_surfaces
    )
    estimated_after_total_surfaces = (
        estimated_after_lane_surfaces
        + estimated_after_turn_surfaces
        + current_continuity_surfaces
        + estimated_after_envelope_surfaces
    )

    return {
        "type": "lane_upgrade_topology_surface_preview",
        "schema": "lane_upgrade_system.topology_surface_preview.v1",
        "estimate_only": True,
        "estimate_policy": "current_artifact_scope_plus_lane_count_rebuild_estimate_v1",
        "selected_road_ids": sorted(selected_road_ids),
        "affected_junction_node_ids": sorted(affected_junction_node_ids),
        "affected_junction_ids": sorted(affected_junction_ids),
        "target_physical_lane_counts_by_road": target_counts_by_road,
        "lane_links": {
            "junction_scope": surface_diff_values(current_junction_lane_links, estimated_after_junction_lane_links),
            "selected_road_scope": surface_diff_values(current_selected_road_lane_links, estimated_after_selected_road_lane_links),
        },
        "surfaces": {
            "selected_lane_surfaces": surface_diff_values(current_lane_surfaces, estimated_after_lane_surfaces),
            "turn_surfaces": surface_diff_values(current_turn_surfaces, estimated_after_turn_surfaces),
            "continuity_surfaces": surface_diff_values(current_continuity_surfaces, current_continuity_surfaces),
            "junction_envelope_surfaces": surface_diff_values(current_envelope_surfaces, estimated_after_envelope_surfaces),
            "total_touched_surfaces": surface_diff_values(current_total_surfaces, estimated_after_total_surfaces),
            "current_touched_area_m2": round(current_surface_area_m2, 3),
        },
        "junction_details": junction_details,
        "notes": [
            "This is a non-mutating estimate derived from current lane_graph and lane_surface artifacts.",
            "Actual lane surface counts may be lower after degree-2 physical lane grouping during rebuild.",
            "QA gate remains authoritative after the real transaction -> rebuild -> package publish flow.",
        ],
    }


def lane_upgrade_preview_items(
    *,
    request: dict[str, Any],
    targets: list[dict[str, Any]],
    affected_scopes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    semantic_by_road = semantic_evidence_by_road(request["area_id"])
    items: list[dict[str, Any]] = []
    for index, target in enumerate(targets):
        road_id = target["road_id"]
        semantic_record = semantic_by_road.get(road_id) or {}
        active = active_lane_upgrade(request["area_id"], road_id)
        geometry = semantic_record.get("geometry") or {}
        source = semantic_record.get("source") or {}
        review = semantic_record.get("review") or {}
        current_count = int(geometry.get("physical_lane_count") or 0)
        source_count = source.get("lanes")
        if request["restore_default"]:
            target_count: int | None = None
            after_label = "default/source rules（默认 / 源规则）"
        else:
            target_count = int(request["target_lane_count"])
            after_label = f"{target_count} physical lanes（{target_count} 物理车道）"
        items.append({
            "road_id": road_id,
            "canonical_road_id": target["canonical_road_id"],
            "road_chain_id": target.get("road_chain_id", ""),
            "current_physical_lane_count": current_count,
            "source_lanes": source_count,
            "source_lanes_raw": source.get("lanes_raw", ""),
            "target_physical_lane_count": target_count,
            "after_label": after_label,
            "current_lane_count_source": geometry.get("lane_count_source", ""),
            "confidence_tier": review.get("confidence_tier", ""),
            "review_flags": review.get("flags", []) or [],
            "active_lane_upgrade": active or {},
            "affected_scope": affected_scopes[index] if index < len(affected_scopes) else {},
        })
    return items


def lane_upgrade_preview_summary(
    *,
    request: dict[str, Any],
    items: list[dict[str, Any]],
    affected_scope: dict[str, Any],
    latest: dict[str, Any],
) -> dict[str, Any]:
    scope_index = affected_scope_index(affected_scope)
    package = package_summary_from_latest(latest)
    semantic_records = [
        {
            "review": {"flags": item.get("review_flags", [])},
        }
        for item in items
    ]
    active_count = sum(1 for item in items if item.get("active_lane_upgrade"))
    action = "restore_road_lane_count_default" if request["restore_default"] else "set_road_physical_lane_count"
    target_label = "default/source rules（默认 / 源规则）" if request["restore_default"] else f"{request['target_lane_count']} physical lanes（{request['target_lane_count']} 物理车道）"
    return {
        "type": "lane_upgrade_preview_summary",
        "schema": "lane_upgrade_system.preview_summary.v1",
        "action": action,
        "target_label": target_label,
        "target_physical_lane_count": None if request["restore_default"] else request["target_lane_count"],
        "affected_road_count": len(items),
        "affected_junction_count": len(scope_index["adjacent_junction_node_ids"]),
        "affected_junction_node_ids": scope_index["adjacent_junction_node_ids"],
        "active_override_count_before": active_count,
        "current_lane_counts": unique_text([item.get("current_physical_lane_count") for item in items]),
        "source_lane_counts": unique_text([item.get("source_lanes") for item in items]),
        "road_ids": [item["road_id"] for item in items],
        "canonical_road_ids": [item["canonical_road_id"] for item in items],
        "road_chain_ids": unique_text([item.get("road_chain_id") for item in items]),
        "semantic_review_flag_counts": semantic_flag_counts(semantic_records),
        "package_before": package.get("version", ""),
        "qa_gate_status_before": package.get("qa_gate_status", ""),
        "qa_warning_summary_before": package.get("qa_warning_summary") or {},
        "execution_effect": "transaction -> rebuild -> QA -> publish package -> refresh SVG",
    }


def preview_lane_upgrade(body: dict[str, Any]) -> dict[str, Any]:
    request = parse_lane_upgrade_request(body)
    targets = resolve_lane_upgrade_targets(request)
    primary = targets[0]
    road_id = primary["road_id"]
    canonical_road_id = primary["canonical_road_id"]
    road_ids = [target["road_id"] for target in targets]
    canonical_road_ids = [target["canonical_road_id"] for target in targets]
    affected_scopes = [
        create_lane_upgrade_transaction.affected_scope_for_edge(
            target["edge"],
            target["road_graph"],
            road_id=target["road_id"],
            canonical_road_id=target["canonical_road_id"],
        )
        for target in targets
    ]
    affected_scope = affected_scopes[0] if len(affected_scopes) == 1 else {
        "scope_policy": "road_chain_ordered_edges_v1",
        "road_chain_id": request["road_chain_id"] or primary.get("road_chain_id", ""),
        "target_count": len(targets),
        "targets": affected_scopes,
    }
    latest = latest_package(request["area_id"])
    preview_items = lane_upgrade_preview_items(
        request=request,
        targets=targets,
        affected_scopes=affected_scopes,
    )
    preview_summary = lane_upgrade_preview_summary(
        request=request,
        items=preview_items,
        affected_scope=affected_scope,
        latest=latest,
    )
    topology_preview = topology_surface_preview(
        request=request,
        items=preview_items,
        affected_scope=affected_scope,
        targets=targets,
    )
    preview_summary["topology_surface_preview"] = topology_preview
    active = active_lane_upgrade(request["area_id"], road_id)
    operation = "--restore-default" if request["restore_default"] else f"--target-lane-count {request['target_lane_count']}"
    geometry_flag = " --apply-all-active-geometry"
    commands = [
        (
            f"python scripts\\execute_lane_upgrade.py --area-id {request['area_id']} "
            f"--road-id {target['road_id']} --canonical-road-id {target['canonical_road_id']} {operation}{geometry_flag} "
            f"--reason \"{request['reason']}\""
        )
        for target in targets
    ]
    return {
        "type": "lane_upgrade_preview",
        "metadata": {
            "schema": API_SCHEMA,
            "system": SYSTEM_NAME,
            "area_id": request["area_id"],
        },
        "request": {
            "action": "restore_road_lane_count_default" if request["restore_default"] else "set_road_physical_lane_count",
            "road_id": road_id,
            "canonical_road_id": canonical_road_id,
            "road_ids": road_ids,
            "canonical_road_ids": canonical_road_ids,
            "road_chain_id": request["road_chain_id"] or primary.get("road_chain_id", ""),
            "selection_scope": request.get("selection_scope", ""),
            "target_physical_lane_count": request["target_lane_count"],
            "apply_selected_geometry": False,
            "apply_all_active_geometry": True,
        },
        "current_active_override": active or {},
        "affected_scope": affected_scope,
        "preview_summary": preview_summary,
        "preview_items": preview_items,
        "topology_surface_preview": topology_preview,
        "geometry_application_policy": "apply_all_lane_upgrade_overrides_to_geometry_v1",
        "execution_cli_command": commands[0] if len(commands) == 1 else "\n".join(commands),
        "execution_cli_commands": commands,
        "latest_package": latest,
        "notes": [
            "All active LaneForge lane-count overrides are applied to geometry during the rebuild.",
            "The selected road's endpoint junction laneLinks and lane surfaces are regenerated before SVG refresh.",
            "Raw, repaired, canonical and road_graph truth layers are not edited.",
        ],
    }


def affected_scope_index(scope: dict[str, Any]) -> dict[str, list[str]]:
    road_ids: list[str] = []
    canonical_road_ids: list[str] = []
    junction_node_ids: list[str] = []

    def append_unique(items: list[str], value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in items:
            items.append(text)

    def visit(item: Any) -> None:
        if not isinstance(item, dict):
            return
        append_unique(road_ids, item.get("road_id"))
        append_unique(canonical_road_ids, item.get("canonical_road_id"))
        for node_id in item.get("adjacent_junction_node_ids", []) or []:
            append_unique(junction_node_ids, node_id)
        for target in item.get("targets", []) or []:
            visit(target)

    visit(scope)
    return {
        "road_ids": road_ids,
        "canonical_road_ids": canonical_road_ids,
        "adjacent_junction_node_ids": junction_node_ids,
    }


def request_string_list(request: dict[str, Any], key: str, fallback_key: str) -> list[str]:
    values = string_list(request.get(key))
    if values:
        return values
    fallback = str(request.get(fallback_key) or "").strip()
    return [fallback] if fallback else []


def package_manifest_path_from_latest(latest_entry: dict[str, Any]) -> Path | None:
    data = (latest_entry.get("data") or latest_entry) if isinstance(latest_entry, dict) else {}
    area_id = str(data.get("area_id") or "").strip()
    package_dir = str(data.get("latest_package_dir") or data.get("latest_package_version") or "").strip()
    manifest_name = str(data.get("manifest") or "manifest.json").strip()
    if not area_id or not package_dir:
        return None
    manifest_path = Path(manifest_name)
    if manifest_path.is_absolute():
        return manifest_path
    if len(manifest_path.parts) > 1 and manifest_path.parts[0] == "data":
        return ROOT / manifest_path
    return ROOT / "data" / "lane_upgrade_packages" / area_id / package_dir / manifest_path


def package_summary_from_latest(latest_entry: dict[str, Any] | None) -> dict[str, Any]:
    latest_entry = latest_entry or {}
    data = latest_entry.get("data") or {}
    manifest_path = package_manifest_path_from_latest(latest_entry)
    manifest = read_json(manifest_path) if manifest_path and manifest_path.exists() else {}
    metadata = manifest.get("metadata") or {}
    qa_gate = manifest.get("qa_gate") or {}
    return {
        "latest_pointer": str(latest_entry.get("path") or ""),
        "version": str(
            data.get("latest_package_version")
            or data.get("latest_package_dir")
            or metadata.get("package_version")
            or ""
        ),
        "manifest": rel(manifest_path) if manifest_path else "",
        "qa_status": str(metadata.get("qa_status") or ""),
        "qa_gate_status": str(metadata.get("qa_gate_status") or data.get("qa_gate_status") or qa_gate.get("status") or ""),
        "qa_warning_summary": data.get("qa_warning_summary") or qa_gate.get("summary") or {},
        "counts": manifest.get("counts") or {},
    }


def diff_values(before: Any, after: Any) -> dict[str, Any]:
    if isinstance(before, bool) or isinstance(after, bool):
        return {"before": before, "after": after}
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        return {
            "before": before,
            "after": after,
            "delta": round(float(after) - float(before), 6),
        }
    return {"before": before, "after": after}


def package_count_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_counts = before.get("counts") or {}
    after_counts = after.get("counts") or {}
    changed: dict[str, Any] = {}
    for key in sorted(set(before_counts) | set(after_counts)):
        before_value = before_counts.get(key)
        after_value = after_counts.get(key)
        if before_value != after_value:
            changed[key] = diff_values(before_value, after_value)
    return changed


def package_diff_summary(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "lane_upgrade_package_diff_summary",
        "schema": "lane_upgrade_system.package_diff_summary.v1",
        "package_before": before.get("version", ""),
        "package_after": after.get("version", ""),
        "package_version_changed": before.get("version", "") != after.get("version", ""),
        "qa_gate_status_before": before.get("qa_gate_status", ""),
        "qa_gate_status_after": after.get("qa_gate_status", ""),
        "qa_gate_status_changed": before.get("qa_gate_status", "") != after.get("qa_gate_status", ""),
        "qa_warning_summary_before": before.get("qa_warning_summary") or {},
        "qa_warning_summary_after": after.get("qa_warning_summary") or {},
        "count_changes": package_count_diff(before, after),
    }


def package_root_dir(area_id: str) -> Path:
    return ROOT / "data" / "lane_upgrade_packages" / area_id


def package_version_number(version: str) -> int:
    match = re.search(r"v(\d+)$", str(version or ""))
    return int(match.group(1)) if match else -1


def package_summary_from_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    metadata = manifest.get("metadata") or {}
    qa_gate = manifest.get("qa_gate") or {}
    package_dir = manifest_path.parent
    return {
        "version": str(metadata.get("package_version") or package_dir.name),
        "version_number": package_version_number(str(metadata.get("package_version") or package_dir.name)),
        "package_dir": package_dir.name,
        "manifest": rel(manifest_path),
        "manifest_exists": manifest_path.exists(),
        "mtime_local": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(manifest_path.stat().st_mtime)) if manifest_path.exists() else "",
        "qa_status": str(metadata.get("qa_status") or ""),
        "qa_gate_status": str(metadata.get("qa_gate_status") or qa_gate.get("status") or ""),
        "qa_warning_summary": qa_gate.get("summary") or manifest.get("semantic_review", {}).get("qa_warning_summary") or {},
        "counts": manifest.get("counts") or {},
        "semantic_review_status": str((manifest.get("semantic_review") or {}).get("status") or ""),
        "source_artifacts": manifest.get("source_artifacts") or {},
        "contents": manifest.get("contents") or {},
    }


def available_package_summaries(area_id: str) -> list[dict[str, Any]]:
    base = package_root_dir(area_id)
    summaries: list[dict[str, Any]] = []
    if not base.exists():
        return summaries
    for item in base.iterdir():
        if not item.is_dir() or not re.match(r"^lane_package_v\d+$", item.name):
            continue
        manifest_path = item / "manifest.json"
        if manifest_path.exists():
            summaries.append(package_summary_from_manifest(manifest_path))
        else:
            summaries.append({
                "version": item.name,
                "version_number": package_version_number(item.name),
                "package_dir": item.name,
                "manifest": rel(manifest_path),
                "manifest_exists": False,
                "mtime_local": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(item.stat().st_mtime)),
                "qa_gate_status": "missing_manifest",
                "qa_warning_summary": {},
                "counts": {},
            })
    summaries.sort(key=lambda item: int(item.get("version_number") or -1), reverse=True)
    return summaries


def package_summary_for_version(area_id: str, version: str) -> dict[str, Any]:
    manifest_path = package_root_dir(area_id) / version / "manifest.json"
    return package_summary_from_manifest(manifest_path) if manifest_path.exists() else {}


def package_source_artifact_changes(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_artifacts = before.get("source_artifacts") or {}
    after_artifacts = after.get("source_artifacts") or {}
    changes: dict[str, Any] = {}
    for key in sorted(set(before_artifacts) | set(after_artifacts)):
        before_item = before_artifacts.get(key) or {}
        after_item = after_artifacts.get(key) or {}
        before_hash = str(before_item.get("sha256") or "")
        after_hash = str(after_item.get("sha256") or "")
        if before_hash != after_hash:
            changes[key] = {
                "before_sha256": before_hash,
                "after_sha256": after_hash,
                "before_path": str(before_item.get("path") or ""),
                "after_path": str(after_item.get("path") or ""),
            }
    return changes


def package_lifecycle_entry(
    *,
    check_id: str,
    tier: str,
    message: str,
    recommendation: str = "",
    value: Any = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "stage": "package_lifecycle",
        "check_id": check_id,
        "tier": tier,
        "scope": "area_package_registry",
        "message": message,
        "recommendation": recommendation,
        "value": value,
        "evidence": evidence or {},
    }


def package_lifecycle_registry(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "exists": path.exists(),
        "path": rel(path),
        "read_error": "",
        "data": {},
        "entries": [],
    }
    if not path.exists():
        return result
    try:
        data = read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        result["read_error"] = str(exc)
        return result
    entries = data.get("entries") if isinstance(data, dict) else []
    result["data"] = data
    result["entries"] = [entry for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else []
    return result


def package_lifecycle_registry_entries_for_version(registry: dict[str, Any], version: str) -> list[dict[str, Any]]:
    return [
        entry for entry in registry.get("entries", []) or []
        if str(entry.get("package_version") or "") == version
    ]


def stable_handoff_milestone_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def package_lifecycle_lookup(area_id: str, *, keep_latest_count: int = 12) -> dict[str, Any]:
    latest = latest_package(area_id)
    latest_data = latest.get("data") or {}
    packages = available_package_summaries(area_id)
    latest_version = str(latest_data.get("latest_package_version") or latest_data.get("latest_package_dir") or "")
    latest_summary = package_summary_for_version(area_id, latest_version) if latest_version else {}
    highest = packages[0] if packages else {}
    previous = next(
        (
            package for package in packages
            if int(package.get("version_number") or -1) < int(latest_summary.get("version_number") or -1)
        ),
        {},
    )
    diff = package_diff_summary(previous, latest_summary) if previous and latest_summary else {}
    source_changes = package_source_artifact_changes(previous, latest_summary) if previous and latest_summary else {}

    changelog_items: list[dict[str, Any]] = []
    if diff:
        for key, value in (diff.get("count_changes") or {}).items():
            changelog_items.append({
                "kind": "count_change",
                "field": key,
                "change": value,
            })
        if diff.get("qa_gate_status_changed"):
            changelog_items.append({
                "kind": "qa_gate_status_change",
                "change": {
                    "before": diff.get("qa_gate_status_before"),
                    "after": diff.get("qa_gate_status_after"),
                },
            })
    for key, value in source_changes.items():
        changelog_items.append({
            "kind": "source_artifact_change",
            "field": key,
            "change": value,
        })

    archive_candidates = packages[keep_latest_count:] if len(packages) > keep_latest_count else []
    missing_manifest_packages = [
        package for package in packages
        if not package.get("manifest_exists")
    ]
    qa_gate_status = str(latest_summary.get("qa_gate_status") or latest_data.get("qa_gate_status") or "")
    latest_is_highest = bool(highest) and str(highest.get("version") or "") == latest_version
    pointer_manifest_matches = bool(latest_summary) and str(latest_summary.get("version") or "") == latest_version
    changelog_file = package_root_dir(area_id) / "package_changelog.json"
    milestone_file = package_root_dir(area_id) / "package_milestones.json"
    changelog_registry = package_lifecycle_registry(changelog_file)
    milestone_registry = package_lifecycle_registry(milestone_file)
    latest_changelog_entries = package_lifecycle_registry_entries_for_version(changelog_registry, latest_version)
    latest_milestone_entries = package_lifecycle_registry_entries_for_version(milestone_registry, latest_version)
    stable_latest_milestones = stable_handoff_milestone_entries(latest_milestone_entries)
    changelog_registry_ok = bool(changelog_registry.get("exists")) and not changelog_registry.get("read_error")
    milestone_registry_ok = bool(milestone_registry.get("exists")) and not milestone_registry.get("read_error")

    milestone_status = "candidate_requires_review"
    if qa_gate_status in {"pass", "publishable"}:
        milestone_status = "candidate_publishable"
    elif qa_gate_status == "manual_review_required":
        milestone_status = "candidate_manual_review_required"
    elif not qa_gate_status:
        milestone_status = "candidate_unknown_qa"

    checks = [
        package_lifecycle_entry(
            check_id="latest_pointer_consistency",
            tier="pass" if latest_is_highest and pointer_manifest_matches else "manual_review_required",
            message=(
                "Latest pointer matches the highest available package（最新指针匹配最高版本数据包）."
                if latest_is_highest and pointer_manifest_matches
                else "Latest pointer needs review（最新指针需要复核）."
            ),
            recommendation=(
                "Keep latest pointer on this package（保持当前最新指针）."
                if latest_is_highest and pointer_manifest_matches
                else "Review latest.json before downstream handoff（下游交付前复核 latest.json）."
            ),
            value={
                "latest_pointer_version": latest_version,
                "highest_package_version": str(highest.get("version") or ""),
                "pointer_manifest_matches": pointer_manifest_matches,
            },
            evidence={"latest_pointer": latest.get("path", ""), "latest_manifest": latest_summary.get("manifest", "")},
        ),
        package_lifecycle_entry(
            check_id="package_changelog_presence",
            tier="pass" if changelog_registry_ok else "manual_review_required",
            message=(
                "Package changelog registry exists（数据包变更日志已存在）."
                if changelog_registry_ok
                else "Package changelog registry cannot be read（数据包变更日志注册文件无法读取）."
                if changelog_registry.get("exists")
                else "Package changelog registry is missing（数据包变更日志注册文件缺失）."
            ),
            recommendation=(
                "Keep changelog registry append-only（保持变更日志注册表只追加）."
                if changelog_registry_ok
                else "Create package_changelog.json from the generated changelog draft（用生成的变更日志草案建立 package_changelog.json）."
            ),
            value={
                "exists": changelog_registry.get("exists"),
                "path": changelog_registry.get("path"),
                "entry_count": len(changelog_registry.get("entries", []) or []),
                "latest_entry_count": len(latest_changelog_entries),
                "read_error": changelog_registry.get("read_error", ""),
            },
            evidence={
                "draft_item_count": len(changelog_items),
                "draft_items": changelog_items[:16],
                "latest_entries": latest_changelog_entries[:4],
            },
        ),
        package_lifecycle_entry(
            check_id="package_changelog_latest_coverage",
            tier="pass" if latest_changelog_entries else "manual_review_required",
            message=(
                "Latest package has a registered changelog entry（最新数据包已有正式变更日志条目）."
                if latest_changelog_entries
                else "Latest package has no registered changelog entry（最新数据包还没有正式变更日志条目）."
            ),
            recommendation=(
                "Use this entry as the minimum package diff record（把该条目作为最小数据包差异记录）."
                if latest_changelog_entries
                else "Register the latest package diff before archive or handoff review（归档或交付复核前登记最新数据包差异）."
            ),
            value={
                "package_version": latest_version,
                "latest_entry_count": len(latest_changelog_entries),
                "draft_item_count": len(changelog_items),
            },
            evidence={"latest_entries": latest_changelog_entries[:4], "draft_items": changelog_items[:16]},
        ),
        package_lifecycle_entry(
            check_id="milestone_registry_presence",
            tier="pass" if milestone_registry_ok else "manual_review_required",
            message=(
                "Package milestone registry exists（数据包里程碑注册文件已存在）."
                if milestone_registry_ok
                else "Package milestone registry cannot be read（数据包里程碑注册文件无法读取）."
                if milestone_registry.get("exists")
                else "Package milestone registry is missing（数据包里程碑注册文件缺失）."
            ),
            recommendation=(
                "Keep candidate milestones separate from stable handoff milestones（保持候选里程碑与稳定交付里程碑分离）."
                if milestone_registry_ok
                else "Create package_milestones.json before marking stable handoff packages（标记稳定交付包前建立 package_milestones.json）."
            ),
            value={
                "exists": milestone_registry.get("exists"),
                "path": milestone_registry.get("path"),
                "entry_count": len(milestone_registry.get("entries", []) or []),
                "latest_entry_count": len(latest_milestone_entries),
                "read_error": milestone_registry.get("read_error", ""),
            },
            evidence={
                "latest_milestone_candidate": latest_version,
                "milestone_status": milestone_status,
                "latest_entries": latest_milestone_entries[:4],
            },
        ),
        package_lifecycle_entry(
            check_id="milestone_candidate_registry",
            tier="pass" if latest_milestone_entries else "manual_review_required",
            message=(
                "Latest package is registered as a milestone candidate（最新数据包已登记为里程碑候选）."
                if latest_milestone_entries
                else "Latest package is not registered as a milestone candidate（最新数据包还没有登记为里程碑候选）."
            ),
            recommendation=(
                "Keep this package in review-candidate state until QA and handoff checks close（质量和交付检查完成前保持复核候选状态）."
                if latest_milestone_entries
                else "Register review candidates separately from stable handoff milestones（把复核候选与稳定交付里程碑分开登记）."
            ),
            value={
                "package_version": latest_version,
                "latest_entry_count": len(latest_milestone_entries),
                "registered_statuses": [str(entry.get("status") or "") for entry in latest_milestone_entries],
            },
            evidence={"latest_entries": latest_milestone_entries[:4]},
        ),
        package_lifecycle_entry(
            check_id="stable_handoff_milestone_readiness",
            tier="pass" if stable_latest_milestones and qa_gate_status in {"pass", "publishable"} else "manual_review_required",
            message=(
                "Latest package is approved as a stable handoff milestone（最新数据包已批准为稳定交付里程碑）."
                if stable_latest_milestones and qa_gate_status in {"pass", "publishable"}
                else "Latest package is review candidate only, not stable handoff（最新数据包只是复核候选，不是稳定交付里程碑）."
            ),
            recommendation="Promote to stable handoff only after QA and semantic review pass（质量与语义复核通过后再提升为稳定交付）.",
            value={
                "package_version": latest_version,
                "qa_gate_status": qa_gate_status,
                "stable_milestone_count": len(stable_latest_milestones),
                "candidate_milestone_count": len(latest_milestone_entries),
            },
            evidence={"stable_milestones": stable_latest_milestones[:4], "candidate_milestones": latest_milestone_entries[:4]},
        ),
        package_lifecycle_entry(
            check_id="package_diff_summary_available",
            tier="pass" if diff else "manual_review_required",
            message=(
                "Previous-package diff summary is available（上一版差异摘要可用）."
                if diff
                else "Previous-package diff summary is unavailable（上一版差异摘要不可用）."
            ),
            recommendation="Use the diff summary as the minimum changelog entry（用差异摘要作为最小变更日志条目）.",
            value={
                "previous_package": previous.get("version", ""),
                "latest_package": latest_version,
                "count_change_count": len((diff.get("count_changes") or {}) if diff else {}),
                "source_artifact_change_count": len(source_changes),
            },
            evidence={"diff": diff, "source_artifact_changes": source_changes},
        ),
        package_lifecycle_entry(
            check_id="experimental_package_archive_review",
            tier="manual_review_required" if archive_candidates else "pass",
            message=(
                "Older experimental packages should be reviewed for archive（旧实验数据包需要归档复核）."
                if archive_candidates
                else "No package exceeds the current keep-latest policy（当前没有超过保留策略的数据包）."
            ),
            recommendation=(
                "Archive only after explicit human approval; this check is read-only（只在人工明确批准后归档；本检查只读）."
                if archive_candidates
                else "Keep current package set（保留当前数据包集合）."
            ),
            value={
                "keep_latest_count": keep_latest_count,
                "package_count": len(packages),
                "archive_candidate_count": len(archive_candidates),
            },
            evidence={
                "archive_candidates": [
                    {
                        "version": package.get("version"),
                        "qa_gate_status": package.get("qa_gate_status"),
                        "mtime_local": package.get("mtime_local"),
                    }
                    for package in archive_candidates[:24]
                ],
            },
        ),
    ]
    if missing_manifest_packages:
        checks.append(package_lifecycle_entry(
            check_id="package_manifest_presence",
            tier="manual_review_required",
            message="Some package directories are missing manifest.json（部分数据包目录缺少清单）.",
            recommendation="Repair or archive package directories without manifest.json（修复或归档缺清单的数据包目录）.",
            value={"missing_manifest_count": len(missing_manifest_packages)},
            evidence={"packages": missing_manifest_packages[:24]},
        ))

    tier_counts: dict[str, int] = {}
    for check in checks:
        increment_count(tier_counts, str(check.get("tier") or "unknown"))
    warning_count = sum(1 for check in checks if is_warning_tier(str(check.get("tier") or "")))
    return {
        "type": "package_lifecycle_lookup",
        "schema": "lane_upgrade_system.package_lifecycle_lookup.v1",
        "area_id": area_id,
        "read_only": True,
        "mutation_policy": "review_only_no_package_mutation（只审查不修改数据包）",
        "status": "manual_review_required" if warning_count else "package_lifecycle_pass",
        "scoped_warning_count": warning_count,
        "check_count": len(checks),
        "tier_counts": sorted_count_dict(tier_counts),
        "latest": latest_summary,
        "previous": previous,
        "highest": highest,
        "package_count": len(packages),
        "recent_packages": packages[:min(keep_latest_count, len(packages))],
        "diff": diff,
        "changelog_draft": {
            "schema": "lane_upgrade_system.package_changelog_entry.v1",
            "package_version": latest_version,
            "previous_package_version": previous.get("version", ""),
            "qa_gate_status": qa_gate_status,
            "items": changelog_items,
        },
        "changelog_registry": {
            "exists": changelog_registry.get("exists"),
            "path": changelog_registry.get("path"),
            "entry_count": len(changelog_registry.get("entries", []) or []),
            "latest_entry_count": len(latest_changelog_entries),
            "latest_entries": latest_changelog_entries[:4],
            "read_error": changelog_registry.get("read_error", ""),
        },
        "milestone_candidate": {
            "package_version": latest_version,
            "status": milestone_status,
            "qa_gate_status": qa_gate_status,
            "blockers": (latest_data.get("qa_warning_summary") or latest_summary.get("qa_warning_summary") or {}).get("blocker", 0),
            "requires_manual_review": qa_gate_status == "manual_review_required",
            "recommended_label": f"{area_id}_{latest_version}_review_candidate",
        },
        "milestone_registry": {
            "exists": milestone_registry.get("exists"),
            "path": milestone_registry.get("path"),
            "entry_count": len(milestone_registry.get("entries", []) or []),
            "latest_entry_count": len(latest_milestone_entries),
            "latest_entries": latest_milestone_entries[:4],
            "stable_latest_count": len(stable_latest_milestones),
            "read_error": milestone_registry.get("read_error", ""),
        },
        "stable_handoff": {
            "status": (
                "stable_handoff_ready"
                if stable_latest_milestones and qa_gate_status in {"pass", "publishable"}
                else "review_candidate_only"
            ),
            "stable_milestone_count": len(stable_latest_milestones),
            "candidate_milestone_count": len(latest_milestone_entries),
            "qa_gate_status": qa_gate_status,
        },
        "archive_review": {
            "keep_latest_count": keep_latest_count,
            "archive_candidate_count": len(archive_candidates),
            "archive_candidates": [
                {
                    "version": package.get("version"),
                    "qa_gate_status": package.get("qa_gate_status"),
                    "mtime_local": package.get("mtime_local"),
                }
                for package in archive_candidates[:24]
            ],
        },
        "checks": checks,
        "reports": {
            "latest_pointer": latest.get("path", ""),
            "changelog_registry": rel(changelog_file),
            "milestone_registry": rel(milestone_file),
        },
    }


def lane_upgrade_stage_from_output(line: str) -> str:
    for pattern, stage_id in LANE_UPGRADE_STAGE_PATTERNS:
        if pattern in line:
            return stage_id
    return ""


def timeline_status_for_step(
    *,
    job_status: str,
    step_id: str,
    active_index: int,
) -> str:
    step_index = LANE_UPGRADE_TIMELINE_ORDER.index(step_id)
    if step_id == "submit_request":
        return "completed"
    if job_status == "queued":
        return "pending"
    if job_status == "completed":
        return "completed"
    if job_status == "failed":
        if step_index < active_index:
            return "completed"
        if step_index == active_index:
            return "failed"
        return "pending"
    if step_index < active_index:
        return "completed"
    if step_index == active_index:
        return "running"
    return "pending"


def timeline_detail_for_step(step_id: str, job: dict[str, Any], summary: dict[str, Any]) -> str:
    if step_id == "submit_request":
        return str(job.get("job_id") or "")
    if step_id == "create_transaction":
        return (
            f"{summary.get('affected_road_count', 0)} road edge（道路边） / "
            f"{summary.get('affected_junction_count', 0)} junction（路口）"
        )
    if step_id == "rebuild_lane_graph":
        return str(summary.get("geometry_application_policy") or "apply active lane upgrades to geometry")
    if step_id == "run_qa_gate":
        qa_gate = summary.get("qa_gate_status_after") or "pending"
        blockers = (summary.get("qa_warning_summary_after") or {}).get("blocker")
        if blockers is None:
            return f"QA gate（质量门禁） {qa_gate}"
        return f"QA gate（质量门禁） {qa_gate} / blocker（阻断项） {blockers}"
    if step_id == "plan_propagation":
        return "proposal-only propagation plan（只生成传播建议）"
    if step_id == "publish_package":
        before = summary.get("package_before") or "pending"
        after = summary.get("package_after") or "pending"
        return f"{before} -> {after}"
    if step_id == "export_svg":
        return str(job.get("reload_url") or "refresh QA drawing for viewer（刷新网页审查图）")
    return ""


def build_lane_upgrade_timeline(job: dict[str, Any], summary: dict[str, Any]) -> list[dict[str, Any]]:
    job_status = str(job.get("status") or "queued")
    active_stage = str(job.get("current_pipeline_stage") or "")
    if not active_stage and job_status == "running":
        active_stage = "create_transaction"
    active_index = (
        LANE_UPGRADE_TIMELINE_ORDER.index(active_stage)
        if active_stage in LANE_UPGRADE_TIMELINE_ORDER
        else 1
    )
    timeline: list[dict[str, Any]] = []
    current_step = int(job.get("current_step") or 0)
    total_steps = int(job.get("total_steps") or len(job.get("command") or []) or 0)
    for step in LANE_UPGRADE_TIMELINE_STEPS:
        step_id = step["id"]
        status = timeline_status_for_step(
            job_status=job_status,
            step_id=step_id,
            active_index=active_index,
        )
        item = {
            **step,
            "status": status,
            "detail": timeline_detail_for_step(step_id, job, summary),
        }
        if current_step and total_steps:
            item["batch_progress"] = {
                "current": current_step,
                "total": total_steps,
                "label": f"road batch（道路批次） {current_step}/{total_steps}",
            }
        timeline.append(item)
    return timeline


def timeline_progress_percent(timeline: list[dict[str, Any]]) -> int:
    if not timeline:
        return 0
    score = 0.0
    for step in timeline:
        status = step.get("status")
        if status == "completed":
            score += 1.0
        elif status == "running":
            score += 0.45
        elif status == "failed":
            score += 0.2
    return int(round((score / len(timeline)) * 100))


def build_lane_upgrade_job_summary(
    job: dict[str, Any],
    *,
    latest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = job.get("request") or {}
    preview = job.get("preview") or {}
    scope_index = affected_scope_index(preview.get("affected_scope") or {})
    road_ids = request_string_list(request, "road_ids", "road_id") or scope_index["road_ids"]
    canonical_road_ids = (
        request_string_list(request, "canonical_road_ids", "canonical_road_id")
        or scope_index["canonical_road_ids"]
    )
    commands = job.get("command") or []
    before_latest = preview.get("latest_package") or {}
    after_latest = latest or job.get("latest_package") or before_latest
    before_package = package_summary_from_latest(before_latest)
    after_package = package_summary_from_latest(after_latest)
    summary = {
        "type": "lane_upgrade_viewer_job_summary",
        "schema": "lane_upgrade_system.viewer_job_summary.v1",
        "job_id": str(job.get("job_id") or ""),
        "status": str(job.get("status") or ""),
        "action": str(request.get("action") or ""),
        "target_physical_lane_count": int(request.get("target_physical_lane_count") or 0),
        "road_ids": road_ids,
        "canonical_road_ids": canonical_road_ids,
        "road_chain_id": str(request.get("road_chain_id") or ""),
        "selection_scope": str(request.get("selection_scope") or ""),
        "affected_road_count": len(road_ids),
        "affected_junction_count": len(scope_index["adjacent_junction_node_ids"]),
        "affected_junction_node_ids": scope_index["adjacent_junction_node_ids"],
        "geometry_application_policy": str(preview.get("geometry_application_policy") or ""),
        "package_before": str(before_package.get("version") or ""),
        "package_after": str(after_package.get("version") or ""),
        "qa_gate_status_after": str(after_package.get("qa_gate_status") or ""),
        "qa_warning_summary_after": after_package.get("qa_warning_summary") or {},
        "package_before_summary": before_package,
        "package_after_summary": after_package,
        "package_diff": package_diff_summary(before_package, after_package),
        "current_step": int(job.get("current_step") or 0),
        "total_steps": int(job.get("total_steps") or len(commands) or 0),
        "command_count": len(commands),
        "exit_code": job.get("exit_code"),
        "created_at_local": str(job.get("created_at_local") or ""),
        "started_at_local": str(job.get("started_at_local") or ""),
        "completed_at_local": str(job.get("completed_at_local") or ""),
        "reload_url": str(job.get("reload_url") or ""),
    }
    timeline = build_lane_upgrade_timeline(job, summary)
    current_step = next((step for step in timeline if step.get("status") in {"running", "failed"}), {})
    summary.update({
        "current_pipeline_stage": str(job.get("current_pipeline_stage") or ""),
        "current_timeline_step": current_step,
        "timeline": timeline,
        "progress_percent": timeline_progress_percent(timeline),
    })
    return summary


def job_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def save_job(job: dict[str, Any]) -> None:
    with jobs_lock:
        jobs[job["job_id"]] = dict(job)
    write_json(job_path(job["job_id"]), job)


def run_lane_upgrade_job(job_id: str, commands: list[list[str]]) -> None:
    global running_job_id
    job = jobs[job_id]
    job.update({
        "status": "running",
        "started_at_local": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    job["job_summary"] = build_lane_upgrade_job_summary(job)
    save_job(job)
    exit_code = 0
    stdout_parts: list[str] = []
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    for index, command in enumerate(commands):
        job.update({
            "current_step": index + 1,
            "total_steps": len(commands),
            "current_command": [str(item) for item in command],
            "current_pipeline_stage": "create_transaction",
        })
        job["job_summary"] = build_lane_upgrade_job_summary(job)
        save_job(job)
        step_output: list[str] = [f"\n[viewer step {index + 1}/{len(commands)}]\n"]
        proc = subprocess.Popen(
            command,
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        if proc.stdout is not None:
            for line in proc.stdout:
                step_output.append(line)
                next_stage = lane_upgrade_stage_from_output(line)
                if next_stage and next_stage != job.get("current_pipeline_stage"):
                    job.update({
                        "current_pipeline_stage": next_stage,
                        "stdout_tail": ("".join(stdout_parts + step_output))[-8000:],
                    })
                    job["job_summary"] = build_lane_upgrade_job_summary(job)
                    save_job(job)
        proc.wait()
        stdout_parts.append("".join(step_output))
        if proc.returncode != 0:
            exit_code = proc.returncode
            break
        job.update({
            "completed_command_count": index + 1,
            "stdout_tail": ("".join(stdout_parts))[-8000:],
        })
        job["job_summary"] = build_lane_upgrade_job_summary(job)
        save_job(job)
    stdout = "".join(stdout_parts)
    job.update({
        "exit_code": exit_code,
        "stdout_tail": stdout[-8000:],
        "completed_at_local": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    area_id = str((job.get("request") or {}).get("area_id") or "pattaya_central_500m")
    latest = latest_package(area_id)
    if exit_code == 0:
        job.update({
            "status": "completed",
            "latest_package": latest,
            "svg_report": read_json(ROOT / "reports" / f"{area_id}_lane_graph_svg_report.json"),
            "reload_url": f"svg_live_viewer.html?cache={int(time.time())}",
        })
    else:
        job.update({
            "status": "failed",
            "latest_package": latest,
        })
    job["job_summary"] = build_lane_upgrade_job_summary(job, latest=latest)
    save_job(job)
    with jobs_lock:
        running_job_id = None


def start_lane_upgrade_job(body: dict[str, Any]) -> dict[str, Any]:
    global running_job_id
    preview = preview_lane_upgrade(body)
    request = preview["request"]
    with jobs_lock:
        if running_job_id:
            raise RuntimeError(f"LaneForge job already running: {running_job_id}")
        job_id = f"lane_upgrade_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        running_job_id = job_id
    area_id = str((preview["metadata"] or {}).get("area_id") or "pattaya_central_500m")
    road_ids = string_list(request.get("road_ids")) or [str(request["road_id"])]
    canonical_road_ids = string_list(request.get("canonical_road_ids")) or [str(request["canonical_road_id"])]
    commands: list[list[str]] = []
    for index, road_id in enumerate(road_ids):
        command = [
            sys.executable,
            str(ROOT / "scripts" / "execute_lane_upgrade.py"),
            "--area-id",
            area_id,
            "--road-id",
            road_id,
            "--reason",
            str(body.get("reason") or "web menu lane upgrade"),
            "--reviewer",
            "web_user",
            "--source",
            "web_lane_count_menu",
        ]
        canonical_road_id = canonical_road_ids[index] if index < len(canonical_road_ids) else ""
        if canonical_road_id:
            command.extend(["--canonical-road-id", canonical_road_id])
        if str(request["action"]) == "restore_road_lane_count_default":
            command.append("--restore-default")
        else:
            command.extend(["--target-lane-count", str(request["target_physical_lane_count"])])
        command.append("--apply-all-active-geometry")
        commands.append(command)
    job = {
        "type": "lane_upgrade_viewer_job",
        "schema": JOB_SCHEMA,
        "job_id": job_id,
        "status": "queued",
        "created_at_local": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "request": request,
        "preview": preview,
        "command": [[str(item) for item in command] for command in commands],
    }
    job["job_summary"] = build_lane_upgrade_job_summary(job)
    save_job(job)
    thread = threading.Thread(target=run_lane_upgrade_job, args=(job_id, commands), daemon=True)
    thread.start()
    return job


class LaneForgeViewerHandler(SimpleHTTPRequestHandler):
    server_version = "LaneForgeViewer/1.0"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(VISUALIZATIONS_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        if path == "/api/status":
            area_id = "pattaya_central_500m"
            json_response(self, HTTPStatus.OK, {
                "status": "ok",
                "schema": API_SCHEMA,
                "system": SYSTEM_NAME,
                "root": rel(ROOT),
                "visualizations": rel(VISUALIZATIONS_DIR),
                "latest_package": latest_package(area_id),
                "running_job_id": running_job_id,
            })
            return
        if path == "/api/semantic-evidence":
            area_id = str(query.get("area_id", ["pattaya_central_500m"])[0] or "pattaya_central_500m")
            json_response(self, HTTPStatus.OK, semantic_evidence(area_id))
            return
        if path == "/api/semantic-evidence/lookup":
            area_id = str(query.get("area_id", ["pattaya_central_500m"])[0] or "pattaya_central_500m")
            json_response(self, HTTPStatus.OK, semantic_evidence_records(
                area_id,
                road_id=str(query.get("road_id", [""])[0] or ""),
                canonical_road_id=str(query.get("canonical_road_id", [""])[0] or ""),
                road_chain_id=str(query.get("road_chain_id", [""])[0] or ""),
            ))
            return
        if path == "/api/qa-warnings/lookup":
            area_id = str(query.get("area_id", ["pattaya_central_500m"])[0] or "pattaya_central_500m")
            json_response(self, HTTPStatus.OK, qa_warning_lookup(
                area_id,
                road_id=str(query.get("road_id", [""])[0] or ""),
                canonical_road_id=str(query.get("canonical_road_id", [""])[0] or ""),
                road_chain_id=str(query.get("road_chain_id", [""])[0] or ""),
            ))
            return
        if path == "/api/road-chain/lookup":
            area_id = str(query.get("area_id", ["pattaya_central_500m"])[0] or "pattaya_central_500m")
            json_response(self, HTTPStatus.OK, road_chain_review_lookup(
                area_id,
                road_id=str(query.get("road_id", [""])[0] or ""),
                canonical_road_id=str(query.get("canonical_road_id", [""])[0] or ""),
                road_chain_id=str(query.get("road_chain_id", [""])[0] or ""),
            ))
            return
        if path == "/api/junction/lookup":
            area_id = str(query.get("area_id", ["pattaya_central_500m"])[0] or "pattaya_central_500m")
            json_response(self, HTTPStatus.OK, junction_review_lookup(
                area_id,
                road_id=str(query.get("road_id", [""])[0] or ""),
                canonical_road_id=str(query.get("canonical_road_id", [""])[0] or ""),
                road_chain_id=str(query.get("road_chain_id", [""])[0] or ""),
                node_id=str(query.get("node_id", [""])[0] or ""),
                junction_id=str(query.get("junction_id", [""])[0] or ""),
            ))
            return
        if path == "/api/package-lifecycle/lookup":
            area_id = str(query.get("area_id", ["pattaya_central_500m"])[0] or "pattaya_central_500m")
            keep_latest_count = int(query.get("keep_latest_count", ["12"])[0] or "12")
            json_response(self, HTTPStatus.OK, package_lifecycle_lookup(
                area_id,
                keep_latest_count=max(1, keep_latest_count),
            ))
            return
        if path == "/api/houdini-handoff/lookup":
            area_id = str(query.get("area_id", ["pattaya_central_500m"])[0] or "pattaya_central_500m")
            package_version = str(query.get("package_version", [""])[0] or "")
            json_response(self, HTTPStatus.OK, houdini_handoff_report.build_houdini_handoff_report(
                ROOT,
                area_id,
                package_version,
            ))
            return
        if path == "/api/propagation/lookup":
            area_id = str(query.get("area_id", ["pattaya_central_500m"])[0] or "pattaya_central_500m")
            json_response(self, HTTPStatus.OK, propagation_review_lookup(
                area_id,
                road_id=str(query.get("road_id", [""])[0] or ""),
                canonical_road_id=str(query.get("canonical_road_id", [""])[0] or ""),
                road_chain_id=str(query.get("road_chain_id", [""])[0] or ""),
            ))
            return
        if path.startswith("/api/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            job = jobs.get(job_id) or read_json(job_path(job_id))
            if not job:
                error_response(self, HTTPStatus.NOT_FOUND, f"Unknown job: {job_id}")
                return
            json_response(self, HTTPStatus.OK, job)
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            body = read_request_json(self)
            if path == "/api/lane-upgrades/preview":
                json_response(self, HTTPStatus.OK, preview_lane_upgrade(body))
                return
            if path == "/api/lane-upgrades/apply":
                try:
                    job = start_lane_upgrade_job(body)
                except RuntimeError as exc:
                    error_response(self, HTTPStatus.CONFLICT, str(exc))
                    return
                json_response(self, HTTPStatus.ACCEPTED, job)
                return
            if path == "/api/propagation/review-queue/enqueue":
                json_response(self, HTTPStatus.OK, enqueue_propagation_review_candidates(body))
                return
            error_response(self, HTTPStatus.NOT_FOUND, f"Unknown API endpoint: {path}")
        except Exception as exc:
            error_response(self, HTTPStatus.BAD_REQUEST, str(exc))


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve LaneForge viewer and local API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if not (VISUALIZATIONS_DIR / "svg_live_viewer.html").exists():
        raise SystemExit(f"Missing viewer HTML: {VISUALIZATIONS_DIR / 'svg_live_viewer.html'}")
    server = ThreadingHTTPServer((args.host, args.port), LaneForgeViewerHandler)
    print(json.dumps({
        "status": "serving",
        "url": f"http://{args.host}:{args.port}/svg_live_viewer.html",
        "api": f"http://{args.host}:{args.port}/api/status",
        "root": str(ROOT),
    }, ensure_ascii=False))
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
