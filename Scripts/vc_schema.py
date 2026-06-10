"""Compatibility alias for :mod:`shared.vc_schema`.

New code should import from ``shared.vc_schema``. Kept as a root-level alias for
legacy callers that import it as ``vc_schema``. Aliased via
``sys.modules[__name__] = _impl`` so it is the same object as the shared module.

DO NOT DELETE without migrating those importers and re-verifying.
"""
from __future__ import annotations

import sys

from shared import vc_schema as _impl

sys.modules[__name__] = _impl
