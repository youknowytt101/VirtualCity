"""Compatibility wrapper for the Houdini build module.

The implementation lives in `Scripts/houdini_build/recook_new_area.py`.
Legacy commands such as `uv run python _recook_new_area.py` are kept working.
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent
IMPLEMENTATION = SCRIPTS / "houdini_build" / "recook_new_area.py"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


if __name__ == "__main__":
    runpy.run_path(str(IMPLEMENTATION), run_name="__main__")
