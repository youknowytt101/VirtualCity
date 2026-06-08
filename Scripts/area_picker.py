"""Compatibility entrypoint for the interactive area picker.

The implementation lives in ``app.area_picker.server``.  Keeping this module
preserves the existing command:

    uv run python area_picker.py
"""
from __future__ import annotations

import sys

from app.area_picker import server as _server

if __name__ == "__main__":
    raise SystemExit(_server.main())

sys.modules[__name__] = _server
