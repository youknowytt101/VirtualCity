"""Compatibility alias for :mod:`orchestration.pipeline_state`.

The module object is replaced so tests or legacy callers that patch attributes
such as ``RUNS_DIR`` patch the real implementation module.
"""
from __future__ import annotations

import sys

from orchestration import pipeline_state as _impl

sys.modules[__name__] = _impl
