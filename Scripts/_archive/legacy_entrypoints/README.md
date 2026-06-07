# Legacy Entry Points

This folder keeps old or one-off scripts that are not part of the current
VirtualCity main pipeline.

Archived on 2026-06-08 during the Scripts physical layering cleanup.

Current main entry points live in:

- `Scripts/orchestration/run_pipeline.py`
- `Scripts/acquisition/set_area.py`
- `Scripts/cleaning/refine_data.py`
- `Scripts/houdini_build/recook_new_area.py`

Do not call files in this folder from new automation unless they are first
reviewed, moved back into the appropriate module, and covered by tests.
