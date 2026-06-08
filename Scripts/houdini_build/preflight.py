"""Preflight checks for the Houdini build data contract."""
from __future__ import annotations

from pathlib import Path

import data_cleaning_cache as dcc
from shared import vc_paths


def houdini_ready_dir(area_id: str) -> Path:
    return vc_paths.HOUDINI_READY / area_id


def houdini_ready_failure_message(area_id: str) -> str:
    return (
        "Houdini-ready preflight failed: RawData/_houdini_ready/{area_id} "
        "is missing, incomplete, or does not match current run_id"
    ).format(area_id=area_id)


def check_houdini_ready(area_id: str, run_id: str) -> bool:
    """Return whether published Houdini-ready files match the active run."""
    return dcc.ready_outputs_exist(
        houdini_ready_dir(area_id),
        expected_area_id=area_id,
        expected_run_id=run_id or None,
    )
