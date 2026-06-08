"""Compatibility alias for :mod:`shared.vc_buildings`.

New code should import from ``shared.vc_buildings``.
"""
from __future__ import annotations

import sys

from shared import vc_buildings as _impl

sys.modules[__name__] = _impl
