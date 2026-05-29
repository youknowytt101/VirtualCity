"""Cache and fingerprint helpers for the VirtualCity data cleaning pipeline.

The goal is to keep acquisition, clipping, cleaning, and Houdini-ready export
separable.  A paid/high-precision data source should only need a new adapter;
the cleaning cache remains keyed by bbox, input file hashes, and recipe params.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import vc_paths


CACHE_SCHEMA_VERSION = 1
CLIP_CACHE_DIR = vc_paths.DATA_ROOT / "_clip_cache"
CLEAN_CACHE_INDEX = vc_paths.DATA_ROOT / "_clean_cache_index.json"

OUTPUT_NAMES = {
    "buildings": "buildings.geojson",
    "roads": "roads.osm",
    "dem": "dem.csv",
}

SOURCE_CONFIG_KEYS = {
    "buildings": "buildings_file",
    "roads": "osm_file",
    "dem": "dem_csv",
}

CLEAN_RECIPE_VERSION = {
    # buildings: +height_source provenance (语义契约 vc_schema) → 2026_05_29
    "buildings": "buildings_l1_l3_v2026_05_29",
    "roads": "roads_l1_l2_v2026_05_28",
    "dem": "dem_l1_l2_v2026_05_28",
}


def utc_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def stable_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest_obj(data: Any, length: int | None = None) -> str:
    digest = hashlib.sha256(stable_json(data).encode("utf-8")).hexdigest()
    return digest[:length] if length else digest


def normalize_bbox(bbox: list[float] | tuple[float, ...] | None) -> list[float] | None:
    if not bbox:
        return None
    return [round(float(v), 7) for v in bbox]


def normalize_source_signature(source_signature: dict[str, Any] | None) -> dict[str, Any]:
    return source_signature or {"profile": "default_v1"}


def bbox_cache_key(bbox: list[float] | tuple[float, ...] | None,
                   source_signature: dict[str, Any] | None = None) -> str | None:
    norm = normalize_bbox(bbox)
    if not norm:
        return None
    return "bbox_" + digest_obj({
        "bbox": norm,
        "source_signature": normalize_source_signature(source_signature),
    }, 16)


def file_fingerprint(path: str | Path) -> dict[str, Any]:
    p = vc_paths.resolve_project_path(path)
    info: dict[str, Any] = {
        "path": vc_paths.project_relative(p),
        "exists": p.exists(),
    }
    if not p.exists():
        return info

    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)

    stat = p.stat()
    info.update({
        "size": stat.st_size,
        "sha256": h.hexdigest(),
    })
    return info


def outputs_exist(base_dir: str | Path, *, min_bytes: int = 128) -> bool:
    base = Path(base_dir)
    return all((base / name).exists() and (base / name).stat().st_size > min_bytes
               for name in OUTPUT_NAMES.values())


def _clean_params() -> dict[str, Any]:
    params: dict[str, Any] = {
        "schema": CACHE_SCHEMA_VERSION,
        "road_merge_tolerance_m": 1.0,
    }
    try:
        import clean_raw_data as cr
        params.update({
            "building_min_ring_points": cr.MIN_RING_POINTS,
            "building_min_area_m2": cr.MIN_AREA_M2,
            "building_max_height_m": cr.MAX_HEIGHT_M,
            "building_floor_height_m": cr.FLOOR_HEIGHT_M,
            "building_dedup_dist_m": cr.DEDUP_DIST_M,
            "road_highway_whitelist": sorted(cr.HIGHWAY_WHITELIST),
        })
    except Exception as exc:
        params["clean_raw_data_import_error"] = str(exc)
    return params


def source_snapshot(area_cfg: dict[str, Any],
                    source_paths: dict[str, str | Path]) -> dict[str, Any]:
    bbox = normalize_bbox(area_cfg.get("bbox"))
    origin = {
        "lon": round(float(area_cfg["origin_lon"]), 7) if area_cfg.get("origin_lon") is not None else None,
        "lat": round(float(area_cfg["origin_lat"]), 7) if area_cfg.get("origin_lat") is not None else None,
    }
    return {
        "area_id": area_cfg.get("area_id"),
        "bbox": bbox,
        "origin": origin,
        "dem_source": area_cfg.get("dem_source", "unknown"),
        "providers": area_cfg.get("sources", {}),
        "files": {
            group: file_fingerprint(path)
            for group, path in sorted(source_paths.items())
        },
    }


def recipe_snapshot() -> dict[str, Any]:
    return {
        "schema": CACHE_SCHEMA_VERSION,
        "versions": CLEAN_RECIPE_VERSION,
        "params": _clean_params(),
    }


def refine_cache_state(area_cfg: dict[str, Any],
                       source_paths: dict[str, str | Path]) -> dict[str, Any]:
    sources = source_snapshot(area_cfg, source_paths)
    recipe = recipe_snapshot()
    portable_sources = json.loads(stable_json(sources))
    portable_sources.pop("area_id", None)
    for file_info in portable_sources.get("files", {}).values():
        file_info.pop("path", None)

    key_payload = {
        "schema": CACHE_SCHEMA_VERSION,
        "stage": "refine",
        "sources": portable_sources,
        "recipe": recipe,
    }
    fingerprint = digest_obj(key_payload)
    payload = {
        "schema": CACHE_SCHEMA_VERSION,
        "stage": "refine",
        "sources": sources,
        "recipe": recipe,
    }
    payload["fingerprint"] = fingerprint
    payload["key"] = "refine_" + fingerprint[:16]
    payload["created"] = utc_now()
    return payload


def cache_match(manifest: dict[str, Any], state: dict[str, Any]) -> tuple[bool, str]:
    cache = manifest.get("cache", {})
    if not cache:
        return False, "manifest has no cache fingerprint"
    if cache.get("schema") != CACHE_SCHEMA_VERSION:
        return False, "cache schema changed"
    if cache.get("fingerprint") != state.get("fingerprint"):
        return False, "source files or cleaning recipe changed"
    return True, "cache fingerprint matches"


def reset_levels(manifest: dict[str, Any]) -> None:
    manifest["levels"] = {
        "buildings": {"current": 0},
        "roads": {"current": 0},
        "dem": {"current": 0},
    }


def mark_refine_cache(manifest: dict[str, Any],
                      state: dict[str, Any],
                      cleaned_dir: Path,
                      ready_dir: Path) -> None:
    cache = dict(state)
    cache["schema"] = CACHE_SCHEMA_VERSION
    cache["cleaned_outputs"] = {
        group: file_fingerprint(cleaned_dir / name)
        for group, name in OUTPUT_NAMES.items()
    }
    cache["ready_outputs"] = {
        group: file_fingerprint(ready_dir / name)
        for group, name in OUTPUT_NAMES.items()
    }
    cache["last_validated"] = utc_now()
    manifest["cache"] = cache


def update_clean_cache_index(area_id: str, state: dict[str, Any], manifest_path: Path) -> None:
    CLEAN_CACHE_INDEX.parent.mkdir(parents=True, exist_ok=True)
    if CLEAN_CACHE_INDEX.exists():
        with open(CLEAN_CACHE_INDEX, encoding="utf-8") as f:
            index = json.load(f)
    else:
        index = {"schema": CACHE_SCHEMA_VERSION, "refine": {}}

    index["schema"] = CACHE_SCHEMA_VERSION
    index.setdefault("refine", {})[state["key"]] = {
        "area_id": area_id,
        "bbox": state.get("sources", {}).get("bbox"),
        "fingerprint": state["fingerprint"],
        "manifest": vc_paths.project_relative(manifest_path),
        "updated": utc_now(),
    }

    tmp = CLEAN_CACHE_INDEX.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(CLEAN_CACHE_INDEX)


def restore_refine_cache(state: dict[str, Any], cleaned_dir: str | Path) -> dict[str, Any] | None:
    if not CLEAN_CACHE_INDEX.exists():
        return None
    with open(CLEAN_CACHE_INDEX, encoding="utf-8") as f:
        index = json.load(f)

    record = index.get("refine", {}).get(state["key"])
    if not record:
        return None

    manifest_path = vc_paths.resolve_project_path(record.get("manifest", ""))
    if not manifest_path.exists():
        return None

    source_dir = manifest_path.parent
    if not outputs_exist(source_dir):
        return None

    target_dir = Path(cleaned_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in OUTPUT_NAMES.values():
        shutil.copy2(source_dir / name, target_dir / name)

    with open(manifest_path, encoding="utf-8") as f:
        cached_manifest = json.load(f)

    return {
        "record": record,
        "manifest": cached_manifest,
        "source_dir": vc_paths.project_relative(source_dir),
    }


def clip_cache_paths(key: str) -> dict[str, Path]:
    base = CLIP_CACHE_DIR / key
    return {
        "base": base,
        "manifest": base / "_manifest.json",
        "buildings": base / OUTPUT_NAMES["buildings"],
        "roads": base / OUTPUT_NAMES["roads"],
        "dem": base / OUTPUT_NAMES["dem"],
    }


def restore_clip_cache(bbox: list[float] | tuple[float, ...] | None,
                       outputs: dict[str, str | Path],
                       *,
                       source_signature: dict[str, Any] | None = None) -> dict[str, Any] | None:
    signature = normalize_source_signature(source_signature)
    key = bbox_cache_key(bbox, signature)
    if not key:
        return None

    paths = clip_cache_paths(key)
    if not paths["manifest"].exists():
        return None
    if not all(paths[group].exists() for group in OUTPUT_NAMES):
        return None

    with open(paths["manifest"], encoding="utf-8") as f:
        manifest = json.load(f)
    if manifest.get("bbox") != normalize_bbox(bbox):
        return None
    if manifest.get("source_signature", {"profile": "default_v1"}) != signature:
        return None

    for group, src in ((g, paths[g]) for g in OUTPUT_NAMES):
        dst = vc_paths.resolve_project_path(outputs[group])
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    manifest["restored_at"] = utc_now()
    return manifest


def write_clip_cache(bbox: list[float] | tuple[float, ...] | None,
                     area_cfg: dict[str, Any],
                     outputs: dict[str, str | Path],
                     *,
                     source_signature: dict[str, Any] | None = None,
                     source_note: str = "set_area") -> dict[str, Any] | None:
    signature = normalize_source_signature(source_signature)
    key = bbox_cache_key(bbox, signature)
    if not key:
        return None

    paths = clip_cache_paths(key)
    paths["base"].mkdir(parents=True, exist_ok=True)

    copied: dict[str, Any] = {}
    for group in OUTPUT_NAMES:
        src = vc_paths.resolve_project_path(outputs[group])
        if not src.exists():
            return None
        shutil.copy2(src, paths[group])
        copied[group] = file_fingerprint(paths[group])

    manifest = {
        "schema": CACHE_SCHEMA_VERSION,
        "key": key,
        "bbox": normalize_bbox(bbox),
        "area_id": area_cfg.get("area_id"),
        "origin_lon": area_cfg.get("origin_lon"),
        "origin_lat": area_cfg.get("origin_lat"),
        "dem_source": area_cfg.get("dem_source", "unknown"),
        "source_signature": signature,
        "source_note": source_note,
        "files": copied,
        "created": utc_now(),
    }

    with open(paths["manifest"], "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return manifest
