# VirtualCity AI / Human Handoff

> Start here when taking over this project. This file is intentionally short,
> current-state focused, and should be updated after major iteration rounds.

Last updated: 2026-05-28

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
2. `项目管理/00_AI接手指南.md`
3. `项目管理/02_当前状态与下一步.md`
4. `项目管理/03_迭代日志.md`
5. `项目管理/08_任务看板.md`
6. `项目管理/12_已知坑点与解决方案.md`

For implementation work, also inspect the relevant code before changing it.

## 3. Current Git Baseline

GitHub `main` and local `main` were confirmed identical at:

```text
f7b217b feat: stabilize road junction clipping
```

Previous key road commit:

```text
670769a feat: harden Houdini road QA pipeline
```

If pushing to GitHub fails with TLS handshake errors, check Git proxy settings. On this machine, pushing succeeded by bypassing Git proxy:

```powershell
git -c http.proxy= -c https.proxy= push origin main
```

## 4. Current Tested Area

Current active/tested area:

```text
area_12.918_100.865
bbox: [100.859385, 12.912967, 100.870199, 12.92334]
OBJ path: /obj/pattaya_osm
latest area HIP: Houdini/Hip/VC_area_12.918_100.865_citygen_v001.hip
master HIP: Houdini/Hip/VC_master_citygen_v001.hip
```

Latest Houdini build status:

```text
Config/houdini_build_status.json
status: completed
qa_status: pass
```

Latest Model QA:

```text
Reports/model_qa/latest.json
status: pass
summary: 12 pass / 0 warn / 0 fail
```

Important road QA results from the latest pass:

```text
road_faces: pass
road_clipped_faces: pass
road_terrain_fit: pass
road_clipped max_vertices: 4
road_clipped ngon_count: 0
road_clipped self_intersection_count: 0
road_clipped small_angle_warn_count: 0
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
7. `Reports/model_qa/latest.json` says `pass`.

Do not call `_recook_new_area.py` or `set_area.py` a full test unless the user explicitly asks to skip the web UI or rebuild the current area only.

## 6. Recently Completed Work

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

1. Human-review `OUT_city` in Houdini.
2. Inspect road junction visuals after the v5 downgrade strategy.
3. If roads look stable, start visual road layering:
   `road_surface / sidewalk_strip / curb_edge`.
4. Keep UE5 export/import outside the default test loop until Houdini output is visually approved.
5. Continue updating this file and `项目管理/02_当前状态与下一步.md` after each major iteration.

## 8. Key Files

Pipeline:

- `Scripts/area_picker.py`
- `Scripts/set_area.py`
- `Scripts/refine_data.py`
- `Scripts/_recook_new_area.py`
- `Scripts/houdini_model_qa.py`

Roads:

- `Scripts/houdini_road_pipeline.py`
- `Scripts/_road_strips_v2.py`

State / reports:

- `Config/active_area.json`
- `Config/houdini_build_status.json`
- `Reports/model_qa/latest.json`

Project docs:

- `项目管理/00_AI接手指南.md`
- `项目管理/02_当前状态与下一步.md`
- `项目管理/03_迭代日志.md`
- `项目管理/08_任务看板.md`
- `项目管理/12_已知坑点与解决方案.md`
