"""Compatibility alias for :mod:`shared.vc_paths`.

New code should import from ``shared.vc_paths``.  The module object is aliased
so legacy patches and attribute updates still target the real implementation.
"""
from __future__ import annotations

import sys

from shared import vc_paths as _impl

sys.modules[__name__] = _impl
