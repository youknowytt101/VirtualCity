# VirtualCity AI / Human Handoff

Last updated: 2026-06-24

This is the first file to read when taking over the project.

## Current Goal

Build a reproducible top-down virtual city generation pipeline:

```text
real map data -> cleaned semantic data -> Houdini city asset -> QA -> human review -> UE5 export
```

Current phase: Houdini asset-quality iteration.

## Current Status

Active area:

```text
area_id: z47n_e702000_n1428000_w1000_h1000_s1000
run_id: 20260621_134716_z47n_e702000_n1428000_w1000_h1000_s1000_3e5b0106
HIP: Houdini/Hip/VC_z47n_e702000_n1428000_w1000_h1000_s1000_citygen_v001.hip
OBJ path: /obj/pattaya_osm
```

Latest status:

```text
Config/houdini_build_status.json: status=completed, qa_status=fail
Reports/model_qa/latest.json: 11 pass / 0 warn / 2 fail
fail: building_terrain_fit, road_terrain_fit
```

Meaning: Houdini automation ran to completion, but the generated asset is not a
promotable baseline. Fix the terrain-fit failures or manually inspect before any
export decision.

## Read Order

Read only these first:

1. `AI_HANDOFF.md`
2. `ProjectManagement/00_AI接手指南.md`
3. `ProjectManagement/02_当前状态与下一步.md`
4. `ProjectManagement/08_任务看板.md`
5. `ProjectManagement/12_已知坑点与解决方案.md`
6. `Scripts/README.md`
7. `Houdini/README.md`

Open older plans only when one of the files above points there.

## Current Pipeline

User-facing full run:

```powershell
cd Scripts
uv run python area_picker.py
```

Execution path:

```text
Scripts/area_picker.py
-> Scripts/app/area_picker/server.py
-> Scripts/orchestration/run_pipeline.py
-> Scripts/acquisition/set_area.py --acquire-only
-> Scripts/cleaning/refine_data.py
-> Scripts/houdini_build/recook_new_area.py
-> Scripts/houdini_model_qa.py --mode quick
-> human review of OUT_city
-> Scripts/export_and_import.py only after review
```

Do not call `set_area.py`, `refine_data.py`, or `recook_new_area.py` alone a
full-pipeline test.

## Architecture Rules

- `Scripts/shared/vc_geo.py` is the coordinate authority.
- `Scripts/shared/vc_schema.py` is the semantic contract authority.
- `RawData/_houdini_ready/{area_id}/ready_manifest.json` is the Houdini input contract.
- `area_id` and `run_id` must match across `active_area`, build status, pipeline run, and Model QA.
- UE5 export is outside the default test loop.

## Next Best Work

1. Diagnose `road_terrain_fit` and `building_terrain_fit` on the active area.
2. Confirm whether failures are true geometry defects or terrain boundary/ray coverage artifacts.
3. Keep the browser control room focused on area selection, pipeline state, and export gating.
4. Update `ProjectManagement/02_当前状态与下一步.md` and `ProjectManagement/08_任务看板.md` after the next meaningful run.

## Do Not Chase

- Full City Sample.
- New plugin framework.
- Mass AI / complex traffic.
- UE5 visual polish before Houdini QA and human review.
