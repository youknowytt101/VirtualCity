# VirtualCity AI / Human Handoff

> Start here when taking over this project. This file is intentionally short,
> current-state focused, and should be updated after major iteration rounds.

Last updated: 2026-06-04

## 0. 当前活跃交接入口

当前最新工作集中在独立道路研究管线：

```text
ProjectManagement/RoadResearch/road_test_pipeline/
```

下一位 AI 如果是继续“道路修复 / 车道级路口 / lane graph（车道拓扑图） / movement corridor（通行走廊）”工作，先读：

```text
ProjectManagement/RoadResearch/road_test_pipeline/AI_START_HERE.md
ProjectManagement/RoadResearch/road_test_pipeline/CURRENT_STAGE_SNAPSHOT.md
ProjectManagement/RoadResearch/road_test_pipeline/NEXT_AI_HANDOFF.md
```

当前道路管线已经完成 `road skeleton repair（道路骨架修复） -> lane attribute model（车道属性模型） -> lane graph topology（车道拓扑图拓扑） -> movement corridor candidates（通行走廊候选） -> compound junction merge transaction（复合路口合并事务） -> staged compound movement SVG visualization（暂存复合通行走廊 SVG 可视化）` 的非破坏式闭环。

`L8.5 staged compound movement SVG visualization（暂存复合通行走廊 SVG 可视化）` 已升级为 `review_drawing（审图线稿）`：默认 3200px 宽画布、`lane road casing（车道道路底线）`、更小的 `entry / exit anchors（入口 / 出口锚点）`，并高亮 24 条 `compound trial corridor（复合试运行走廊）`。当前 SVG 路径：

```text
ProjectManagement/RoadResearch/road_test_pipeline/reports/visualizations/pattaya_central_500m_lane_graph_topology.svg
```

当前道路研究管线临时启用 `temporary_all_roads_bidirectional_two_lane_v1（临时全道路双向两车道策略）`：所有 road edge（道路边）统一展开为双向 2 车道，明确 `OSM oneway（OSM 单行）` 也只作为 `source_observation（源数据观察值）` 保留，不再阻断 L5/L7/L8 的 movement（通行动作）。

`L8.3 compound junction merge planner（复合路口合并规划器）` 和 `L8.4 compound junction merge transaction（复合路口合并事务）` 已闭环：24 个 `adjacent_junction_short_link（相邻路口短连接）` 锚点已归并成 3 个 low-risk `transaction_candidate（低风险事务候选）`，并生成 24 条 staged compound movement corridor（暂存复合通行走廊）。下一步是 `L8.6 movement corridor scoring（通行走廊评分）`：补 `collision_score（碰撞评分） / swept_envelope_score（扫掠包络评分） / curvature_score（曲率评分）`，不是写回 clean skeleton（干净道路骨架）。

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
93a359b chore: sync handoff and experimental area snapshot
```

Key commits in the latest hardening rounds (newest first):

```text
93a359b chore: sync handoff and experimental area snapshot
f3a5ce9 docs: architecture panorama SVG
ce89a53 feat(semantics): semantic contract vc_schema + height provenance + QA
7634bf6 docs: log vc_geo/houdini_sops/vc_buildings hardening
70e50e0 refactor(cleaning): extract pure vc_buildings
af3c57a refactor(coords): route Houdini osm_import through vc_geo
a7a1129 refactor(houdini): externalize inline SOP code into houdini_sops
de8f11e refactor(coords): centralize WGS84/local/Houdini conversions in vc_geo
```

This handoff update closes the next small round: `download_dem.py` and
`clean_raw_data.py` were migrated off direct `_utm_lite` use onto
`vc_geo.LocalProjector`; offline tests now cover that coordinate-authority
closeout.

This round also treats the latest Git-visible test outputs (OSM / DEM /
Overture / HIP / Config QA JSON / clip cache) as an experimental snapshot on
`main`, so a new machine can resume without rebuilding all inputs. If visual
review rejects it, revert or clean this snapshot as one follow-up.

If pushing to GitHub fails with TLS handshake errors, check Git proxy settings. On this machine, pushing succeeded by bypassing Git proxy:

```powershell
git -c http.proxy= -c https.proxy= push origin main
```

## 4. Current Tested Area

Latest full-pipeline area (from `area_picker.py`):

```text
area_12.946_100.892
OBJ path: /obj/pattaya_osm
latest area HIP: Houdini/Hip/VC_area_12.946_100.892_citygen_v001.hip
master HIP: Houdini/Hip/VC_master_citygen_v001.hip
```

Latest Houdini build status:

```text
Config/houdini_build_status.json
status: completed
qa_status: warn
```

Latest Model QA:

```text
Reports/model_qa/latest.json
summary: 11 pass / 1 warn / 0 fail
warn: road_faces (single long-thin road_strips sliver near bbox edge; BENIGN)
```

The `road_faces` warn is benign: it is one intermediate-geometry sliver
(`max_aspect_ratio` just over the 150 warn threshold) on a larger/denser area.
The final `road_clipped` output passes (`road_clipped_faces: pass`,
`road_terrain_fit: pass`), so downstream geometry is clean. Stable clean-pass
areas from the previous round remain useful as visual baselines.

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

- `Scripts/vc_geo.py` is the single coordinate authority (WGS84 / local (x,z) / Houdini). z-flip happens only in `local_to_houdini` / `local_xz_to_houdini_xz`. `download_dem.py` and `clean_raw_data.py` are now migrated onto it (no more direct `_utm_lite` use in business scripts).
- `Scripts/houdini_sops/` holds the externalized SOP Python/VEX text (previously inline in `_recook_new_area.py`).
- `Scripts/vc_buildings.py` is the pure building-cleaning function (filter / height-fix, geometry passthrough).
- `Scripts/vc_schema.py` is the semantic contract (single authority): per-layer attribute specs + `check_buildings` / `check_roads` (attribute completeness, height provenance, road connectivity). `refine_data` OutputQA runs these; `meta.json` records `schema_version`.
- Building `height_source` provenance is stamped end-to-end: `overture` / `osm` (L3 enrich) / `estimated_pending` (Houdini procedural).
- `项目管理/VirtualCity_架构全景图.svg` is a full-pipeline architecture panorama.
- `tests/` now has 35 offline unit tests (`vc_geo`, `houdini_sops`, `vc_buildings`, `vc_schema`).

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

Core authority modules:

- `Scripts/vc_geo.py` (coordinates)
- `Scripts/vc_buildings.py` (building cleaning)
- `Scripts/vc_schema.py` (semantic contract)
- `Scripts/houdini_sops/` (externalized SOP code)
- `tests/` (offline unit tests)

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
