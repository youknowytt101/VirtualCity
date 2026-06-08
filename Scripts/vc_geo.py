"""Compatibility alias for :mod:`shared.vc_geo`.

New code should import from ``shared.vc_geo``.
"""
from __future__ import annotations

import sys

from shared import vc_geo as _impl

sys.modules[__name__] = _impl
