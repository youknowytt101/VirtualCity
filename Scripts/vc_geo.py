"""Compatibility alias for :mod:`shared.vc_geo`.

New code should import from ``shared.vc_geo``. This thin root-level module is
NOT dead code: it is the import entry point used by Houdini-injected SOP source.
``_osm_import_canonical.py`` (injected as the ``osm_import`` Python SOP) inserts
``Scripts/`` on ``sys.path`` and calls ``import vc_geo`` inside the Houdini
process; ``correct_dem_dtm.py`` and ``road_graph_builder.py`` do the same on the
local side. ``sys.modules[__name__] = _impl`` makes this name an alias of the
real module object (not a copy), so ``vc_geo is shared.vc_geo`` holds.

DO NOT DELETE without first rewriting those injected imports and re-verifying a
full Houdini recook — that path is invisible to pytest.
"""
from __future__ import annotations

import sys

from shared import vc_geo as _impl

sys.modules[__name__] = _impl
