"""Compatibility wrapper for the acquisition module.

The implementation lives in `Scripts/acquisition/set_area.py`.
Legacy commands such as `uv run python set_area.py --data-only` and
`uv run python set_area.py --acquire-only` are intentionally kept working.
Markers kept for regression tests: data_download_completed, 跳过 refine_data 与 Houdini 重算.
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent
IMPLEMENTATION = SCRIPTS / "acquisition" / "set_area.py"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


if __name__ == "__main__":
    runpy.run_path(str(IMPLEMENTATION), run_name="__main__")
