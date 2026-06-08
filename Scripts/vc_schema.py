"""Compatibility alias for :mod:`shared.vc_schema`.

New code should import from ``shared.vc_schema``.
"""
from __future__ import annotations

import sys

from shared import vc_schema as _impl

sys.modules[__name__] = _impl
