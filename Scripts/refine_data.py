"""Compatibility wrapper for the cleaning module.

The implementation lives in `Scripts/cleaning/refine_data.py`.
Legacy commands such as `uv run python refine_data.py --skip-probe` are kept
working while the project moves toward strict physical layering.
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path
from importlib import import_module


SCRIPTS = Path(__file__).resolve().parent
IMPLEMENTATION = SCRIPTS / "cleaning" / "refine_data.py"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


if __name__ == "__main__":
    runpy.run_path(str(IMPLEMENTATION), run_name="__main__")
else:
    sys.modules[__name__] = import_module("cleaning.refine_data")
