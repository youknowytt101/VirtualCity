# VirtualCity AI / Human Handoff

> Start here when taking over this project. This file is intentionally short,
> current-state focused, and should be updated after major iteration rounds.

Last updated: 2026-06-09

## 0. 当前活跃交接入口

当前工作已回到 VirtualCity 主线自动化流程，不再使用独立车道研究管线。

主入口：

```text
Scripts/area_picker.py  (compat entrypoint)
Scripts/app/area_picker/server.py
Scripts/set_area.py
Scripts/refine_data.py
Scripts/_recook_new_area.py
Scripts/houdini_model_qa.py
```

下一位 AI 如果继续自动化或道路生成工作，先读：

```text
Scripts/README.md
ProjectManagement/04_稳定流程规范.md
ProjectManagement/12_已知坑点与解决方案.md
```

## 1. Current Goal

Final goal: build a top-down virtual city generation pipeline.

Current phase: Houdini asset-quality rapid iteration.

This is not the final UE5 integration/output phase yet. The active work is:

```text
data acquisition
    -> data cleaning / cache / data QA
    -> Houdini automated build
    -> Model QA
    -> human review of OUT_city in Houdini
```

UE5 export/import remains manual and should happen only after Houdini visual output is approved.

## 2. Required Reading Order

1. `AI_HANDOFF.md`
2. `ProjectManagement/00_AI接手指南.md`
3. `ProjectManagement/02_当前状态与下一步.md`
4. `ProjectManagement/03_迭代日志.md`
5. `ProjectManagement/08_任务看板.md`
6. `ProjectManagement/12_已知坑点与解决方案.md`

For implementation work, also inspect the relevant code before changing it.

## 3. Current Git Baseline

Latest pushed architecture baseline:

```text
58b6480d refactor: split area picker and shared modules
```

Current workspace note:

```text
The architecture split is committed and pushed to origin/main. The remaining
known local changes at handoff time are machine/runtime state:
Config/software_paths.json and Houdini/Hip/VC_master_citygen_v001.hip.
Do not mix those into architecture/documentation commits without explicit intent.
```

Key commits in the recent hardening rounds:

```text
58b6480d refactor: split area picker and shared modules
c5472866 Lock raw road output and update control room UI
4c6e7de7 Improve VirtualCity launcher and lane preview startup
75d334a1 Integrate LaneForge preview bridge into BBOX flow
93a359b chore: sync handoff and experimental area snapshot
f3a5ce9 docs: architecture panorama SVG
ce89a53 feat(semantics): semantic contract vc_schema + height provenance + QA
7634bf6 docs: log vc_geo/houdini_sops/vc_buildings hardening
70e50e0 refactor(cleaning): extract pure vc_buildings
af3c57a refactor(coords): route Houdini osm_import through vc_geo
a7a1129 refactor(houdini): externalize inline SOP code into houdini_sops
de8f11e refactor(coords): centralize WGS84/local/Houdini conversions in vc_geo
```

This handoff update closes the physical-layer split round:

- Shared authority modules moved to `Scripts/shared/` with root-level
  compatibility aliases.
- Pipeline run state moved to `Scripts/orchestration/pipeline_state.py`.
- Area picker implementation moved to `Scripts/app/area_picker/server.py`,
  with `template.py` and `software_paths.py` split out.
- `Scripts/area_picker.py` remains the user-facing command entrypoint.
- A regression in `shared/vc_paths.py` root detection was fixed and covered by
  `tests/test_vc_paths.py`; offline tests are now 111 passing.

If pushing to GitHub fails with TLS handshake errors, check Git proxy settings. On this machine, pushing succeeded by bypassing Git proxy:

```powershell
git -c http.proxy= -c https.proxy= push origin main
```

## 4. Current Tested Area

Latest full-pipeline attempt (from `area_picker.py`):

```text
z47n_e702000_n1428000_w1000_h1000_s1000
run_id: 20260609_003032_z47n_e702000_n1428000_w1000_h1000_s1000_e7a33766
OBJ path: /obj/pattaya_osm
latest area HIP: Houdini/Hip/VC_z47n_e702000_n1428000_w1000_h1000_s1000_citygen_v001.hip
master HIP: Houdini/Hip/VC_master_citygen_v001.hip
```

Latest Houdini build status:

```text
Config/houdini_build_status.json
status: failed
qa_status: fail
```

Latest Model QA:

```text
Reports/model_qa/latest.json
summary: 11 pass / 0 warn / 1 fail
fail: building_terrain_fit
details: bld_with_foundation has 1 sampled point below terrain threshold
min_delta: -0.0668m, threshold: -0.05m
```

The latest run confirms the refactored entrypoints and path helpers reach the
Houdini / Model QA stage, but it is not a passing baseline. Next work should
inspect the `building_terrain_fit` failure before promoting this area.

Most recent clean successful reference before this failure:

```text
z47n_e704000_n1431000_w1000_h1000_s1000
Model QA quick: 12 pass / 0 warn / 0 fail
report timestamp: 2026-06-09 00:02:00
```

## 5. Full Pipeline Definition

When the user says "重新测试", "从头测试", "全流程测试", or "测试自动化管线", run the true full pipeline:

```powershell
cd Scripts
uv run python area_picker.py
```

The full pipeline starts from the Leaflet web area picker and ends only after:

1. the web area selection flow starts;
2. OSM / FABDEM / Overture data is acquired or restored;
3. `refine_data.py` finishes data cleaning and data QA;
4. Houdini recook finishes through RPYC;
5. `houdini_model_qa.py` finishes;
6. `Config/houdini_build_status.json` says `completed`;
7. `Reports/model_qa/latest.json` is written and has no `fail` checks. `warn` means the pipeline completed but needs human review before promotion to a baseline.

Do not call `_recook_new_area.py` or `set_area.py` a full test unless the user explicitly asks to skip the web UI or rebuild the current area only.

## 6. Recently Completed Work

Architecture / semantics hardening (this round, behavior-preserving):

- `Scripts/shared/vc_geo.py` is the single coordinate authority (WGS84 / local (x,z) / Houdini). z-flip happens only in `local_to_houdini` / `local_xz_to_houdini_xz`. Root `Scripts/vc_geo.py` remains a compatibility alias.
- `Scripts/houdini_sops/` holds the externalized SOP Python/VEX text (previously inline in `_recook_new_area.py`).
- `Scripts/shared/vc_buildings.py` is the pure building-cleaning function (filter / height-fix, geometry passthrough).
- `Scripts/shared/vc_schema.py` is the semantic contract (single authority): per-layer attribute specs + `check_buildings` / `check_roads` (attribute completeness, height provenance, road connectivity). `refine_data` OutputQA runs these; `meta.json` records `schema_version`.
- `Scripts/app/area_picker/` now owns the area picker web implementation:
  `server.py`, `template.py`, `software_paths.py`. `Scripts/area_picker.py`
  stays as the stable user entrypoint.
- `Scripts/orchestration/pipeline_state.py` now owns durable run state.
- `tests/test_vc_paths.py` locks project-root discovery after the package move.
- Building `height_source` provenance is stamped end-to-end: `overture` / `osm` (L3 enrich) / `estimated_pending` (Houdini procedural).
- `ProjectManagement/VirtualCity_架构全景图.svg` is a full-pipeline architecture panorama.
- `tests/` now has 111 offline tests passing after the physical split.

Building / terrain:

- Building snap uses vertical terrain sampling and max footprint height to avoid burying buildings in slopes.
- Building foundation/skirt is generated from final building bottom edges.
- Foundation color matches building body color.
- Foundation normals, tags, and alignment are covered by QA.
- Footprint bevel exists and targets exterior corners with the current `<=100°` rule and tolerance.
- Terrain snap target uses `dem_subdivide` with denser sampling.

Roads:

- Road centerlines and strips are vertically draped to terrain.
- `road_width_flat` input is forcibly repaired to the terrain-snapped road centerline.
- Road width now uses `OSM width > lanes > highway fallback`, then highway-based clamp.
- Road SOP code was thin-split into `Scripts/houdini_road_pipeline.py`.
- `Scripts/_road_strips_v2.py` is now road_strips v5:
  - debug attributes for source/highway/width/segment/face area;
  - self-intersection and tiny-angle protection;
  - bounded convex junction fill;
  - complex-junction downgrade instead of unsafe overfill.
- `road_bbox_clip` now cleans clipped polygons, triangulates clipped n-gons safely, and skips bad tiny slivers.
- Model QA now checks both source road faces and clipped road faces.

## 7. High-Value Next Steps

1. Investigate latest Model QA failure: `building_terrain_fit` on
   `z47n_e702000_n1428000_w1000_h1000_s1000` (1 sampled point below threshold).
2. Human-review `OUT_city` in Houdini after the failure is understood.
3. Inspect road visuals and raw line output after the latest control-room changes.
4. If roads look stable, start visual road layering:
   `road_surface / sidewalk_strip / curb_edge`.
5. Keep UE5 export/import outside the default test loop until Houdini output is visually approved.
6. Continue updating this file and `ProjectManagement/02_当前状态与下一步.md` after each major iteration.

## 8. Key Files

Pipeline:

- `Scripts/area_picker.py`
- `Scripts/app/area_picker/server.py`
- `Scripts/app/area_picker/template.py`
- `Scripts/set_area.py`
- `Scripts/refine_data.py`
- `Scripts/_recook_new_area.py`
- `Scripts/houdini_model_qa.py`

Roads:

- `Scripts/houdini_road_pipeline.py`
- `Scripts/_road_strips_v2.py`

Core authority modules:

- `Scripts/shared/vc_geo.py` (coordinates)
- `Scripts/shared/vc_buildings.py` (building cleaning)
- `Scripts/shared/vc_schema.py` (semantic contract)
- `Scripts/orchestration/pipeline_state.py` (run state)
- `Scripts/houdini_sops/` (externalized SOP code)
- `tests/` (offline unit tests)

State / reports:

- `Config/active_area.json`
- `Config/houdini_build_status.json`
- `Reports/model_qa/latest.json`

Project docs:

- `ProjectManagement/00_AI接手指南.md`
- `ProjectManagement/02_当前状态与下一步.md`
- `ProjectManagement/03_迭代日志.md`
- `ProjectManagement/08_任务看板.md`
- `ProjectManagement/12_已知坑点与解决方案.md`
