#!/usr/bin/env python3
"""Build a LaneForge package from the current VirtualCity area roads.

This is the thin bridge between the main BBOX city pipeline and LaneForge.
It does not select an area, download OSM, or invent a second road source.
The only accepted road inputs are the current area's Houdini-ready outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from vc_paths import HOUDINI_READY, ROOT, SCRIPTS, load_active_area, project_relative, write_active_area


LANEFORGE_ROOT = ROOT / "ProjectManagement" / "RoadResearch" / "road_test_pipeline"
PROCESSED_DIR = LANEFORGE_ROOT / "data" / "processed"
REPORTS_DIR = LANEFORGE_ROOT / "reports"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def artifact(path: Path) -> dict[str, Any]:
    return {
        "path": project_relative(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "sha256": sha256_file(path) if path.exists() else "",
    }


def bbox_swen(cfg: dict[str, Any]) -> list[float]:
    west, south, east, north = [float(value) for value in cfg.get("bbox", [])]
    return [south, west, north, east]


def normalize_roads_for_laneforge(fc: dict[str, Any], cfg: dict[str, Any], source_path: Path) -> dict[str, Any]:
    area_id = str(cfg.get("area_id") or "")
    out = {
        "type": "FeatureCollection",
        "metadata": {
            "area_id": area_id,
            "schema": "road_test_pipeline.roads_raw.geojson",
            "coord_domain": "WGS84",
            "axes": "lon, lat",
            "bbox_swen": bbox_swen(cfg),
            "origin_lon": float(cfg.get("origin_lon")),
            "origin_lat": float(cfg.get("origin_lat")),
            "source_system": "VirtualCity",
            "source_stage": "refine_data.houdini_ready.roads_clean",
            "source_path": project_relative(source_path),
            "run_id": str(cfg.get("run_id") or ""),
            "handoff_rule": "LaneForge integration uses VirtualCity Houdini-ready roads as the only road source.",
        },
        "features": [],
    }

    for index, feature in enumerate(fc.get("features", [])):
        geom = feature.get("geometry") or {}
        if geom.get("type") != "LineString":
            continue
        coords = [
            [float(coord[0]), float(coord[1])]
            for coord in geom.get("coordinates", [])
            if isinstance(coord, list) and len(coord) >= 2
        ]
        if len(coords) < 2:
            continue

        props = dict(feature.get("properties") or {})
        base_source_id = str(props.get("source_feature_id") or feature.get("id") or props.get("seg_id") or index)
        seg_id = props.get("seg_id", "")
        source_id = f"{base_source_id}_seg_{seg_id}" if seg_id != "" and props.get("source_feature_id") is None else base_source_id
        lanes = props.get("lanes", "")
        width = props.get("width_m", props.get("width", ""))
        oneway = props.get("oneway", "")
        if isinstance(oneway, bool):
            oneway = "yes" if oneway else "no"

        props.update(
            {
                "source_provider": props.get("source_provider") or "VirtualCity.refine_data",
                "source_feature_id": source_id,
                "vc_source_feature_id": str(feature.get("id") or source_id),
                "vc_area_id": area_id,
                "vc_run_id": str(cfg.get("run_id") or ""),
                "highway": props.get("highway") or "unclassified",
                "road_class": props.get("road_class") or props.get("highway") or "unclassified",
                "lanes": "" if lanes is None else str(lanes),
                "lanes_forward": str(props.get("lanes_forward") or ""),
                "lanes_backward": str(props.get("lanes_backward") or ""),
                "turn_lanes": str(props.get("turn_lanes") or ""),
                "width_m": "" if width is None else str(width),
                "oneway": "" if oneway is None else str(oneway),
                "name": str(props.get("name") or ""),
                "bridge": str(props.get("bridge") or ""),
                "tunnel": str(props.get("tunnel") or ""),
                "layer": str(props.get("layer") or ""),
                "provider_tags": props.get("provider_tags") or {},
            }
        )
        out["features"].append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": props,
            }
        )
    return out


def run_step(name: str, cmd: list[str], log_path: Path) -> None:
    print(f"[LaneForgeBridge] {name}...")
    with log_path.open("a", encoding="utf-8", newline="\n") as log:
        log.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] {name}\n")
        log.write(" ".join(cmd) + "\n")
        proc = subprocess.run(
            cmd,
            cwd=str(LANEFORGE_ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if proc.stdout:
            print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
            log.write(proc.stdout)
        log.write(f"[exit] {proc.returncode}\n")
    if proc.returncode != 0:
        raise RuntimeError(f"{name} failed with exit code {proc.returncode}; see {log_path}")


def package_paths(area_id: str) -> tuple[Path, Path, Path]:
    latest_path = LANEFORGE_ROOT / "data" / "lane_upgrade_packages" / area_id / "latest.json"
    latest = read_json(latest_path)
    package_dir = latest_path.parent / str(latest.get("latest_package_dir") or latest.get("latest_package_version") or "")
    manifest = package_dir / str(latest.get("manifest") or "manifest.json")
    houdini_manifest = package_dir / "houdini_manifest.json"
    return package_dir, manifest, houdini_manifest


def inject_source_identity(path: Path, source_identity: dict[str, Any]) -> None:
    data = read_json(path)
    data.setdefault("metadata", {})["source_identity"] = source_identity
    data["source_identity"] = source_identity
    write_json(path, data)


def build_bridge_package(*, cfg: dict[str, Any], write_area: bool, fail_on_warn: bool) -> dict[str, Any]:
    area_id = str(cfg.get("area_id") or "")
    if not area_id:
        raise ValueError("active_area.json is missing area_id")

    ready_dir = HOUDINI_READY / area_id
    roads_clean = ready_dir / "roads_clean.geojson"
    road_graph = ready_dir / "road_graph.json"
    roads_osm = ready_dir / "roads.osm"
    missing = [path for path in [roads_clean, road_graph, roads_osm] if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing current Houdini-ready road inputs: " + ", ".join(str(path) for path in missing))

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = REPORTS_DIR / f"{area_id}_virtualcity_bridge.log"
    log_path.write_text(f"[LaneForgeBridge] started {time.strftime('%Y-%m-%d %H:%M:%S')}\n", encoding="utf-8")

    raw_out = PROCESSED_DIR / f"{area_id}_roads_raw.geojson"
    source_fc = read_json(roads_clean)
    normalized = normalize_roads_for_laneforge(source_fc, cfg, roads_clean)
    if not normalized["features"]:
        raise RuntimeError(f"No LineString roads found in {roads_clean}")
    write_json(raw_out, normalized)

    config_out = LANEFORGE_ROOT / "config" / f"{area_id}.area.json"
    write_json(
        config_out,
        {
            "area_id": area_id,
            "label": f"VirtualCity active area {area_id}",
            "center": {"lon": cfg.get("origin_lon"), "lat": cfg.get("origin_lat")},
            "bbox": cfg.get("bbox", []),
            "bbox_swen": bbox_swen(cfg),
            "origin_lon": cfg.get("origin_lon"),
            "origin_lat": cfg.get("origin_lat"),
            "run_id": cfg.get("run_id", ""),
            "data_source": {
                "provider": "VirtualCity.refine_data",
                "roads_clean": project_relative(roads_clean),
                "road_graph": project_relative(road_graph),
                "roads_osm": project_relative(roads_osm),
            },
            "output": {
                "raw_dir": "data/raw",
                "processed_dir": "data/processed",
                "reports_dir": "reports",
            },
        },
    )

    python = sys.executable
    run_step(
        "Rebuilding LaneForge package from VirtualCity roads",
        [python, str(LANEFORGE_ROOT / "scripts" / "rebuild_road_test.py"), "--area-id", area_id, "--skip-houdini"],
        log_path,
    )

    package_dir, manifest, houdini_manifest = package_paths(area_id)
    source_identity = {
        "schema": "virtualcity.laneforge.source_identity.v1",
        "source_system": "VirtualCity",
        "area_id": area_id,
        "run_id": str(cfg.get("run_id") or ""),
        "bbox": cfg.get("bbox", []),
        "bbox_swen": bbox_swen(cfg),
        "origin_lon": cfg.get("origin_lon"),
        "origin_lat": cfg.get("origin_lat"),
        "source_artifacts": {
            "active_area": artifact(ROOT / "Config" / "active_area.json"),
            "roads_clean": artifact(roads_clean),
            "road_graph": artifact(road_graph),
            "roads_osm": artifact(roads_osm),
            "laneforge_raw": artifact(raw_out),
        },
        "handoff_rule": "VirtualCity active area and Houdini-ready roads are the source of truth; LaneForge must not select or download a second road dataset in this integration mode.",
    }
    inject_source_identity(manifest, source_identity)
    inject_source_identity(houdini_manifest, source_identity)

    package_manifest = read_json(manifest)
    qa_gate_status = str((package_manifest.get("qa_gate") or {}).get("status") or package_manifest.get("metadata", {}).get("qa_gate_status") or "")
    if fail_on_warn and qa_gate_status and qa_gate_status != "pass":
        raise RuntimeError(f"LaneForge package built but qa_gate_status={qa_gate_status}")

    summary = {
        "status": "ok",
        "area_id": area_id,
        "run_id": cfg.get("run_id", ""),
        "package_dir": project_relative(package_dir),
        "manifest": project_relative(manifest),
        "houdini_manifest": project_relative(houdini_manifest),
        "qa_gate_status": qa_gate_status,
        "source_identity": source_identity,
        "log": project_relative(log_path),
    }
    summary_path = REPORTS_DIR / f"{area_id}_virtualcity_bridge_summary.json"
    write_json(summary_path, summary)
    summary["summary"] = project_relative(summary_path)

    if write_area:
        updated = dict(cfg)
        updated["road_source_mode"] = "laneforge_required" if updated.get("road_source_mode") == "laneforge_required" else "laneforge_auto"
        updated["lane_package_manifest"] = project_relative(houdini_manifest)
        updated["laneforge_bridge"] = {
            "status": "ok",
            "manifest": project_relative(manifest),
            "houdini_manifest": project_relative(houdini_manifest),
            "summary": project_relative(summary_path),
            "qa_gate_status": qa_gate_status,
            "source_run_id": cfg.get("run_id", ""),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        write_active_area(updated, relative=True)

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build LaneForge package from current VirtualCity Houdini-ready roads.")
    parser.add_argument("--no-write-active-area", action="store_true", help="Build package but do not update Config/active_area.json.")
    parser.add_argument("--fail-on-warn", action="store_true", help="Return non-zero if package QA gate is not pass.")
    parser.add_argument("--allow-failure", action="store_true", help="Write a warning summary and return success on bridge failure.")
    args = parser.parse_args()

    cfg = load_active_area(absolute=True)
    try:
        result = build_bridge_package(
            cfg=cfg,
            write_area=not args.no_write_active_area,
            fail_on_warn=args.fail_on_warn,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        area_id = str(cfg.get("area_id") or "unknown")
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        summary_path = REPORTS_DIR / f"{area_id}_virtualcity_bridge_summary.json"
        summary = {
            "status": "failed",
            "area_id": area_id,
            "run_id": cfg.get("run_id", ""),
            "error": str(exc),
            "fallback": "legacy road_strips remains available in VirtualCity recook",
        }
        write_json(summary_path, summary)
        if not args.no_write_active_area:
            updated = dict(cfg)
            updated.pop("lane_package_manifest", None)
            updated["road_source_mode"] = str(updated.get("roads_topology_preferred") or "strips")
            updated["laneforge_bridge"] = {
                "status": "failed",
                "summary": project_relative(summary_path),
                "error": str(exc),
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            write_active_area(updated, relative=True)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if args.allow_failure else 1


if __name__ == "__main__":
    raise SystemExit(main())
