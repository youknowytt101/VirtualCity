"""Software path configuration helpers for the area picker."""
from __future__ import annotations

import json
import time
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[2]
ROOT = SCRIPTS.parent
SOFTWARE_PATHS_FILE = ROOT / "Config" / "software_paths.json"
SOFTWARE_IDS = ("houdini", "blender", "unity", "unreal", "godot")


def software_path_key(software_id: str) -> str:
    software_id = str(software_id or "").strip().lower()
    if software_id not in SOFTWARE_IDS:
        return ""
    return f"{software_id}_exe"


def read_software_paths() -> dict:
    try:
        if SOFTWARE_PATHS_FILE.exists():
            data = json.loads(SOFTWARE_PATHS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def write_software_paths(data: dict) -> None:
    SOFTWARE_PATHS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SOFTWARE_PATHS_FILE.with_name(f".{SOFTWARE_PATHS_FILE.name}.{time.time_ns()}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(SOFTWARE_PATHS_FILE)


def asset_dir_status() -> dict:
    value = str(read_software_paths().get("asset_dir") or "").strip()
    return {"asset_dir": value, "asset_dir_exists": bool(value) and Path(value).is_dir()}


def write_asset_dir(value: str) -> dict:
    data = read_software_paths()
    data["asset_dir"] = str(value or "").strip().strip('"')
    write_software_paths(data)
    return asset_dir_status()


def scene_root_status() -> dict:
    value = str(read_software_paths().get("scene_root") or "").strip()
    return {"scene_root": value, "scene_root_exists": bool(value) and Path(value).is_dir()}


def write_scene_root(value: str) -> dict:
    data = read_software_paths()
    scene_root = str(value or "").strip().strip('"')
    if scene_root:
        Path(scene_root).mkdir(parents=True, exist_ok=True)
    data["scene_root"] = scene_root
    write_software_paths(data)
    return scene_root_status()


def software_path_status() -> dict:
    data = read_software_paths()
    status = {"config_path": str(SOFTWARE_PATHS_FILE)}
    for software_id in SOFTWARE_IDS:
        key = software_path_key(software_id)
        value = str(data.get(key) or "").strip()
        status[key] = value
        status[f"{key}_exists"] = bool(value) and Path(value).exists()
    return status
