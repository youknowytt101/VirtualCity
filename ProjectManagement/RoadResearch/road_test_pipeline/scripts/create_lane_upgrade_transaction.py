#!/usr/bin/env python3
"""Create a LaneForge lane-count upgrade transaction.

This is the backend-facing command that a future web click menu can call:

road click -> choose 1/2/3/4 lanes -> transaction JSON -> active overrides

The transaction does not edit raw map data. The next lane graph rebuild consumes
the active override file and publishes a new audited lane package.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LANE_UPGRADE_SYSTEM_NAME = "LaneForge"
TRANSACTION_SCHEMA = "lane_upgrade_system.transaction.v1"
ACTIVE_OVERRIDE_SCHEMA = "lane_upgrade_system.active_overrides.v1"
DEFAULT_DISTRIBUTION_POLICY = "balanced_bidirectional_left_traffic_v1"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def road_graph_path(root: Path, area_id: str) -> Path:
    return root / "data" / "processed" / f"{area_id}_road_graph.json"


def road_graph_indexes(road_graph: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    edges_by_id: dict[str, dict[str, Any]] = {}
    edges_by_canonical: dict[str, dict[str, Any]] = {}
    for edge in road_graph.get("edges", []):
        edge_id = str(edge.get("edge_id") or "")
        canonical_road_id = str(edge.get("canonical_road_id") or edge.get("source_feature_id") or "")
        if edge_id:
            edges_by_id[edge_id] = edge
        if canonical_road_id:
            edges_by_canonical[canonical_road_id] = edge
    return edges_by_id, edges_by_canonical


def resolve_road_reference(
    *,
    root: Path,
    area_id: str,
    road_id: str,
    canonical_road_id: str,
) -> dict[str, Any]:
    road_id = str(road_id or "").strip()
    canonical_road_id = str(canonical_road_id or "").strip()
    graph_path = road_graph_path(root, area_id)
    if not graph_path.exists():
        if not road_id:
            raise ValueError("road_id is required when road_graph.json is unavailable")
        return {
            "road_id": road_id,
            "canonical_road_id": canonical_road_id,
            "road_graph_path": "",
            "road_graph": None,
            "edge": None,
            "resolution_policy": "unvalidated_no_road_graph",
        }

    road_graph = read_json(graph_path)
    edges_by_id, edges_by_canonical = road_graph_indexes(road_graph)
    if canonical_road_id:
        mapped_edge = edges_by_canonical.get(canonical_road_id)
        if not mapped_edge:
            raise ValueError(f"canonical_road_id {canonical_road_id} was not found in {graph_path}")
        mapped_road_id = str(mapped_edge.get("edge_id") or "")
        if road_id and road_id != mapped_road_id:
            raise ValueError(
                f"road_id {road_id} does not match canonical_road_id {canonical_road_id}; expected {mapped_road_id}"
            )
        road_id = mapped_road_id

    if not road_id:
        raise ValueError("road_id or canonical_road_id is required")

    edge = edges_by_id.get(road_id)
    if not edge:
        raise ValueError(f"road_id {road_id} was not found in {graph_path}")
    if not canonical_road_id:
        canonical_road_id = str(edge.get("canonical_road_id") or "")

    return {
        "road_id": road_id,
        "canonical_road_id": canonical_road_id,
        "road_graph_path": str(graph_path),
        "road_graph": road_graph,
        "edge": edge,
        "resolution_policy": "road_graph_edge_lookup_v1",
    }


def affected_scope_for_edge(
    edge: dict[str, Any] | None,
    road_graph: dict[str, Any] | None,
    *,
    road_id: str = "",
    canonical_road_id: str = "",
) -> dict[str, Any]:
    if not edge:
        return {
            "scope_policy": "direct_edge_endpoints_v1",
            "road_id": road_id,
            "canonical_road_id": canonical_road_id,
            "endpoint_node_ids": [],
            "adjacent_junction_node_ids": [],
            "notes": ["road graph was unavailable; affected junction scope could not be resolved"],
        }

    node_by_id = {
        str(node.get("node_id") or ""): node
        for node in (road_graph or {}).get("nodes", [])
        if str(node.get("node_id") or "")
    }
    endpoint_node_ids = [
        node_id
        for node_id in [str(edge.get("from_node") or ""), str(edge.get("to_node") or "")]
        if node_id
    ]
    adjacent_junction_node_ids = [
        node_id
        for node_id in endpoint_node_ids
        if str((node_by_id.get(node_id) or {}).get("kind") or "") == "junction"
    ]
    return {
        "scope_policy": "direct_edge_endpoints_v1",
        "road_id": str(edge.get("edge_id") or ""),
        "canonical_road_id": str(edge.get("canonical_road_id") or ""),
        "endpoint_node_ids": endpoint_node_ids,
        "adjacent_junction_node_ids": adjacent_junction_node_ids,
        "rebuild_contract": "lane graph and direct endpoint junction laneLinks are regenerated before package publish",
    }


def next_transaction_version(transactions_dir: Path, area_id: str) -> str:
    prefix = f"{area_id}_lane_upgrade_transaction_v"
    highest = 0
    if transactions_dir.exists():
        for path in transactions_dir.glob(f"{prefix}*.json"):
            text = path.stem.replace(prefix, "")
            try:
                highest = max(highest, int(text))
            except ValueError:
                continue
    return f"v{highest + 1:04d}"


def active_override_record(transaction: dict[str, Any]) -> dict[str, Any]:
    request = transaction["request"]
    return {
        "enabled": True,
        "upgrade_id": transaction["transaction_id"],
        "transaction_id": transaction["transaction_id"],
        "version": transaction["version"],
        "road_id": request["road_id"],
        "canonical_road_id": request.get("canonical_road_id", ""),
        "target_physical_lane_count": request["target_physical_lane_count"],
        "distribution_policy": request["distribution_policy"],
        "source": request["source"],
        "reason": request["reason"],
        "reviewer": request["reviewer"],
        "affected_scope": transaction.get("affected_scope", {}),
    }


def update_active_overrides(active_path: Path, transaction: dict[str, Any], area_id: str) -> dict[str, Any]:
    active = read_json(active_path)
    request = transaction["request"]
    road_id = str(request["road_id"])
    existing = [
        item
        for item in active.get("active_upgrades", [])
        if str(item.get("road_id") or "") != road_id
    ]
    if request["action"] != "restore_road_lane_count_default":
        existing.append(active_override_record(transaction))
    output = {
        "type": "lane_upgrade_overrides",
        "metadata": {
            "area_id": area_id,
            "schema": ACTIVE_OVERRIDE_SCHEMA,
            "system": LANE_UPGRADE_SYSTEM_NAME,
            "updated_by_transaction": transaction["transaction_id"],
            "updated_at_utc": transaction["created_at_utc"],
            "note": "Active LaneForge lane-count overrides consumed by lane_model_builder.py.",
        },
        "active_upgrades": sorted(existing, key=lambda item: str(item.get("road_id") or "")),
    }
    write_json(active_path, output)
    return output


def create_transaction(
    *,
    area_id: str,
    road_id: str,
    canonical_road_id: str,
    target_physical_lane_count: int,
    reason: str,
    reviewer: str,
    source: str,
    root: Path,
    activate: bool,
) -> dict[str, Any]:
    target_physical_lane_count = int(target_physical_lane_count)
    if target_physical_lane_count < 1 or target_physical_lane_count > 4:
        raise ValueError("target physical lane count must be one of 1, 2, 3 or 4")
    resolved = resolve_road_reference(
        root=root,
        area_id=area_id,
        road_id=road_id,
        canonical_road_id=canonical_road_id,
    )
    road_id = resolved["road_id"]
    canonical_road_id = resolved["canonical_road_id"]
    affected_scope = affected_scope_for_edge(
        resolved["edge"],
        resolved["road_graph"],
        road_id=road_id,
        canonical_road_id=canonical_road_id,
    )

    transactions_dir = root / "data" / "lane_upgrade_system" / "transactions"
    version = next_transaction_version(transactions_dir, area_id)
    transaction_id = f"lane_upgrade_transaction_{version}"
    created_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    transaction = {
        "type": "lane_upgrade_transaction",
        "metadata": {
            "area_id": area_id,
            "schema": TRANSACTION_SCHEMA,
            "system": LANE_UPGRADE_SYSTEM_NAME,
        },
        "transaction_id": transaction_id,
        "version": version,
        "created_at_utc": created_at_utc,
        "status": "active" if activate else "candidate",
        "request": {
            "action": "set_road_physical_lane_count",
            "road_id": road_id,
            "canonical_road_id": canonical_road_id,
            "target_physical_lane_count": target_physical_lane_count,
            "distribution_policy": DEFAULT_DISTRIBUTION_POLICY,
            "source": source,
            "reason": reason,
            "reviewer": reviewer,
        },
        "resolution": {
            "policy": resolved["resolution_policy"],
            "road_graph": resolved["road_graph_path"],
        },
        "affected_scope": affected_scope,
        "qa_policy": {
            "rebuild_required": True,
            "publish_only_if_pipeline_audit_passes": True,
            "rollback_behavior": "remove_or_disable_active_override_then_rebuild",
        },
        "notes": [
            "This transaction is an upgrade request, not source map truth.",
            "Adjacent junction laneLinks are rebuilt from lane_graph semantics during the next pipeline run.",
        ],
    }
    transaction_path = transactions_dir / f"{area_id}_{transaction_id}.json"
    write_json(transaction_path, transaction)

    active_path = root / "data" / "processed" / f"{area_id}_lane_upgrade_overrides.json"
    active = None
    if activate:
        active = update_active_overrides(active_path, transaction, area_id)

    return {
        "transaction": transaction,
        "transaction_path": str(transaction_path),
        "active_overrides_path": str(active_path) if activate else "",
        "active_overrides": active,
    }


def create_restore_transaction(
    *,
    area_id: str,
    road_id: str,
    canonical_road_id: str,
    reason: str,
    reviewer: str,
    source: str,
    root: Path,
    activate: bool,
) -> dict[str, Any]:
    resolved = resolve_road_reference(
        root=root,
        area_id=area_id,
        road_id=road_id,
        canonical_road_id=canonical_road_id,
    )
    road_id = resolved["road_id"]
    canonical_road_id = resolved["canonical_road_id"]
    affected_scope = affected_scope_for_edge(
        resolved["edge"],
        resolved["road_graph"],
        road_id=road_id,
        canonical_road_id=canonical_road_id,
    )

    transactions_dir = root / "data" / "lane_upgrade_system" / "transactions"
    version = next_transaction_version(transactions_dir, area_id)
    transaction_id = f"lane_upgrade_transaction_{version}"
    created_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    transaction = {
        "type": "lane_upgrade_transaction",
        "metadata": {
            "area_id": area_id,
            "schema": TRANSACTION_SCHEMA,
            "system": LANE_UPGRADE_SYSTEM_NAME,
        },
        "transaction_id": transaction_id,
        "version": version,
        "created_at_utc": created_at_utc,
        "status": "active" if activate else "candidate",
        "request": {
            "action": "restore_road_lane_count_default",
            "road_id": road_id,
            "canonical_road_id": canonical_road_id,
            "target_physical_lane_count": 0,
            "distribution_policy": "source_or_default_lane_model_v1",
            "source": source,
            "reason": reason,
            "reviewer": reviewer,
        },
        "resolution": {
            "policy": resolved["resolution_policy"],
            "road_graph": resolved["road_graph_path"],
        },
        "affected_scope": affected_scope,
        "qa_policy": {
            "rebuild_required": True,
            "publish_only_if_pipeline_audit_passes": True,
            "rollback_behavior": "re-activate a prior lane-count transaction then rebuild",
        },
        "notes": [
            "This transaction restores the road to the pipeline's source/default lane model.",
            "Adjacent junction laneLinks are rebuilt from lane_graph semantics during the next pipeline run.",
        ],
    }
    transaction_path = transactions_dir / f"{area_id}_{transaction_id}.json"
    write_json(transaction_path, transaction)

    active_path = root / "data" / "processed" / f"{area_id}_lane_upgrade_overrides.json"
    active = None
    if activate:
        active = update_active_overrides(active_path, transaction, area_id)

    return {
        "transaction": transaction,
        "transaction_path": str(transaction_path),
        "active_overrides_path": str(active_path) if activate else "",
        "active_overrides": active,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a LaneForge lane-count upgrade transaction.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--road-id", default="", help="Road graph edge id, for example e_0012.")
    parser.add_argument("--canonical-road-id", default="", help="Canonical road id, for example cr_0012.")
    parser.add_argument("--target-lane-count", type=int, choices=[1, 2, 3, 4])
    parser.add_argument("--restore-default", action="store_true", help="Remove the active override and return this road to source/default lane rules.")
    parser.add_argument("--reason", default="manual lane count upgrade request")
    parser.add_argument("--reviewer", default="codex")
    parser.add_argument("--source", default="web_lane_count_menu")
    parser.add_argument("--no-activate", action="store_true", help="Create the transaction but do not update active overrides.")
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    if args.restore_default:
        result = create_restore_transaction(
            area_id=args.area_id,
            road_id=args.road_id,
            canonical_road_id=args.canonical_road_id,
            reason=args.reason,
            reviewer=args.reviewer,
            source=args.source,
            root=root,
            activate=not args.no_activate,
        )
    else:
        if args.target_lane_count is None:
            raise SystemExit("--target-lane-count is required unless --restore-default is set")
        result = create_transaction(
            area_id=args.area_id,
            road_id=args.road_id,
            canonical_road_id=args.canonical_road_id,
            target_physical_lane_count=args.target_lane_count,
            reason=args.reason,
            reviewer=args.reviewer,
            source=args.source,
            root=root,
            activate=not args.no_activate,
        )
    print(json.dumps({
        "area_id": args.area_id,
        "transaction_id": result["transaction"]["transaction_id"],
        "status": result["transaction"]["status"],
        "action": result["transaction"]["request"]["action"],
        "road_id": result["transaction"]["request"]["road_id"],
        "canonical_road_id": result["transaction"]["request"]["canonical_road_id"],
        "target_physical_lane_count": result["transaction"]["request"]["target_physical_lane_count"],
        "affected_scope": result["transaction"]["affected_scope"],
        "transaction_path": result["transaction_path"],
        "active_overrides_path": result["active_overrides_path"],
        "next_step": "Run rebuild_road_test.py --skip-houdini, then publish a lane package if audit passes.",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
