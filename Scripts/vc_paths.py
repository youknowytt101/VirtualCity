"""
VirtualCity path helpers.

All automation scripts should derive paths from this file instead of hard-coding a drive letter.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "Scripts"
CONFIG = ROOT / "Config"
DATA_ROOT = ROOT / "RawData"
HOUDINI = ROOT / "Houdini"
HIP = HOUDINI / "Hip" / "VC_pattaya_quality_test_citygen_v001.hip"
EXPORT = HOUDINI / "Export"
UE5_PROJECT = ROOT / "UE5" / "VirtualCityUE" / "VirtualCityUE.uproject"
ACTIVE_AREA = CONFIG / "active_area.json"
CFG_PATH = ACTIVE_AREA  # backward-compat alias
TRIGGER = ROOT / ".ue5_trigger"

_PATH_KEYS = {"osm_file", "buildings_file", "dem_csv", "dem_tif", "output", "output_tif", "output_csv"}


def posix(path: str | Path) -> str:
    return Path(path).as_posix()


def resolve_project_path(value: str | Path) -> Path:
    raw = str(value).replace("\\", "/")
    lowered = raw.lower()
    marker = "/virtualcity/"
    idx = lowered.find(marker)
    if idx >= 0:
        return ROOT / raw[idx + len(marker):]
    if lowered.endswith("/virtualcity"):
        return ROOT
    p = Path(raw)
    if p.is_absolute():
        return p
    return ROOT / p


def project_relative(path: str | Path) -> str:
    p = resolve_project_path(path)
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def normalize_config_paths(cfg: dict[str, Any], *, absolute: bool = True) -> dict[str, Any]:
    out = dict(cfg)
    for key in _PATH_KEYS:
        if key in out and out[key]:
            resolved = resolve_project_path(out[key])
            out[key] = resolved.as_posix() if absolute else project_relative(resolved)
    return out


def load_active_area(*, absolute: bool = True) -> dict[str, Any]:
    with open(ACTIVE_AREA, encoding="utf-8") as f:
        cfg = json.load(f)
    return normalize_config_paths(cfg, absolute=absolute)


def write_active_area(cfg: dict[str, Any], *, relative: bool = True) -> None:
    ACTIVE_AREA.parent.mkdir(parents=True, exist_ok=True)
    out = normalize_config_paths(cfg, absolute=not relative)
    with open(ACTIVE_AREA, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")
