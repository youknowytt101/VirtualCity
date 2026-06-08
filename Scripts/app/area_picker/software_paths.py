"""Software path configuration helpers for the area picker."""
from __future__ import annotations

import json
import time
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[2]
ROOT = SCRIPTS.parent
SOFTWARE_PATHS_FILE = ROOT / "Config" / "software_paths.json"


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


def software_path_status() -> dict:
    data = read_software_paths()
    houdini_exe = str(data.get("houdini_exe") or "").strip()
    exists = bool(houdini_exe) and Path(houdini_exe).exists()
    return {
        "houdini_exe": houdini_exe,
        "houdini_exe_exists": exists,
        "config_path": str(SOFTWARE_PATHS_FILE),
    }
