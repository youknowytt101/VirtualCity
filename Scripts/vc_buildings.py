"""Compatibility alias for :mod:`shared.vc_buildings`.

New code should import from ``shared.vc_buildings``. Kept as a root-level alias
because ``clean_raw_data.py`` (and legacy callers) import it as
``vc_buildings``. Aliased via ``sys.modules[__name__] = _impl``.

DO NOT DELETE without migrating those importers and re-verifying.
"""
from __future__ import annotations

import sys

from shared import vc_buildings as _impl

sys.modules[__name__] = _impl
