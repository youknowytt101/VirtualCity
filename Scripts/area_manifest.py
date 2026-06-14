"""Authoritative records of areas the user has actually downloaded.

This is deliberately separate from ``RawData/_tiles/_index.json`` (the macro
precache of raw inputs). The precache answers "can I restore raw data for this
bbox"; this manifest answers "what did a download action actually produce".
Conflating the two is what made the quick-jump tile_count drift (a coarse bbox
reverse-calc dropped boundary tiles, e.g. 121 -> 100). A download writes the
real tile_ids/tile_count here once, so readers never have to reverse-calc.

Record shape (RawData/_areas/{area_id}.json):
{
  "area_id": "...",
  "label": "...",
  "tile_count": 121,
  "tile_ids": ["z47n_e...", ...],
  "bbox": [west, south, east, north],
  "updated": "ISO8601"
}
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from vc_paths import DATA_ROOT

AREAS_DIR = DATA_ROOT / "_areas"
_SAFE_AREA_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def areas_dir(root: Path | None = None) -> Path:
    return (root / "RawData" / "_areas") if root is not None else AREAS_DIR


def manifest_path(area_id: str, *, root: Path | None = None) -> Path:
    if not area_id or not _SAFE_AREA_ID.fullmatch(area_id):
        raise ValueError(f"invalid area_id: {area_id!r}")
    return areas_dir(root) / f"{area_id}.json"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(path)


def write(area_id: str, *, tile_ids: list[str], bbox: list[float],
          label: str = "", root: Path | None = None) -> dict[str, Any]:
    """Record what a download produced as raw facts, no reverse-calc."""
    ids = [str(t).strip() for t in (tile_ids or []) if str(t).strip()]
    payload = {
        "area_id": area_id,
        "label": label,
        "tile_count": len(ids),
        "tile_ids": ids,
        "bbox": [float(v) for v in bbox] if bbox else [],
        "updated": _now(),
    }
    _write_json_atomic(manifest_path(area_id, root=root), payload)
    return payload


def load(area_id: str, *, root: Path | None = None) -> dict[str, Any] | None:
    path = manifest_path(area_id, root=root)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_all(root: Path | None = None) -> dict[str, dict[str, Any]]:
    directory = areas_dir(root)
    if not directory.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for entry in sorted(directory.glob("*.json")):
        try:
            with open(entry, encoding="utf-8") as f:
                record = json.load(f)
        except Exception:
            continue
        area_id = str(record.get("area_id") or entry.stem)
        out[area_id] = record
    return out