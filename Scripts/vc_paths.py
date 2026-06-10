"""Compatibility alias for :mod:`shared.vc_paths`.

New code should import from ``shared.vc_paths``. This root-level module is NOT
dead code: ``data_cleaning_cache``, ``_tile_cache``, ``correct_dem_dtm``,
``road_graph_builder``, ``download_dem`` and other active scripts import it as
``vc_paths`` / ``from vc_paths import ...``. The module object is aliased via
``sys.modules[__name__] = _impl`` so legacy patches and attribute updates
(e.g. tests patching ``RUNS_DIR``) still target the real implementation.

DO NOT DELETE without migrating all those importers and re-verifying.
"""
from __future__ import annotations

import sys

from shared import vc_paths as _impl

sys.modules[__name__] = _impl
