# 下一个 AI 接手指南

## 一句话目标

这个目录正在把“地图 API 道路数据”变成一个可复现、可审计、可自我 QA 的道路修复管线。
当前目标是稳定 road skeleton，不是最终 lane graph、OpenDRIVE 或完整车道面。

## 当前主入口

```powershell
python ProjectManagement/RoadResearch/road_test_pipeline/scripts/repair_road_skeleton.py --area-id pattaya_central_500m --sync-houdini
```

这个入口会跑：

```text
topology repair
topology repair QA
repair casebook QA
road graph
road graph QA
junction semantics
junction area regularization
engineering centerline / clean skeleton
junction geometry audit
optional Houdini sync
```

## 设计原则

```text
Raw data immutable.
Houdini only visualizes/imports artifacts.
Repair candidates are not repairs.
High confidence must still pass validators.
Manual overrides are data and must stay reproducible.
Known false positives go into casebook.
```

## 当前已落地

```text
topology_repair.py
  conservative repair
  repair_candidates.json
  repair_decisions.json
  repair_casebook.json
  transactional high-confidence apply path

run_repair_casebook.py
  replays known false positives / rejected cases
  currently protects 1209258529:end -> 1210710015 segment 1

regularize_junction_areas.py
  creates junction_areas.json
  creates engineering_reference_lines.json
  marks short-edge absorption candidates
  publishes approach entry poses and movement intents

optimize_junction_centerlines.py
  consumes junction_areas.json / engineering_reference_lines.json
  uses regularized entry poses instead of hard graph-node trim where available
  marks incompatible single-arc connectors as bezier_tangent_fallback
  leaves radius and fallback issues visible to junction_geometry_audit.py

solve_junction_connectors.py
  connector solver v2 candidate generator
  scores current / circular / paramPoly3 Hermite / G1 proxy candidates
  writes junction_connector_candidates.json and junction_connector_solver_report.json
  does not replace clean skeleton geometry yet

apply_connector_replacements.py
  transactional replacement pass
  applies only replacement_ready_candidates
  accepts only if trial audit does not regress
  writes junction_connector_replacement_report.json

repair_road_skeleton.py
  main runner
  Houdini layout is raw -> repaired -> clean skeleton, with arc debug branches
```

## Houdini 节点意图

```text
OUT_raw_road_lines
  原始 API 数据线

OUT_repaired_road_lines
  拓扑修复后的 simple edges

OUT_clean_road_skeleton
  L6 clean single-line skeleton

OUT_junction_connector_arcs
OUT_corner_fillet_arcs
  clean skeleton 的 debug 分支，不是独立数据真值
```

## 当前关键 QA 状态

```text
topology repair QA: pass
repair casebook QA: pass
possible_unsplit_crossings: 0
road graph QA: warn because width_fallback_ratio = 1.0
junction area regularization: warn because 34 entry trims are capacity-limited and 22 short edges are absorption candidates
optimized centerlines: 149 regularized entry poses consumed, 120 exact, 29 scaled for edge length
junction geometry audit: warn because radius_below_design_min = 90 and junction_trim_spread_excess = 24
connector replacement: accepted 1 replacement without audit regression
connector solver v2 refresh: warn because solver_cases = 102, unresolved_solver_cases = 102, replacement_ready_candidates = 0
```

`radius_below_design_min` 现在已经不是 Houdini 布局问题，也不是 entry pose 未接入问题。
当前根因集中在两类：短边/路口空间不足，以及单圆弧无法同时满足两端 entry pose 和切线。
这些 case 已通过 `bezier_tangent_fallback`、`radius_below_design_min`、`junction_trim_spread_excess`
暴露给下一轮 solver。

## 下一步建议

优先做：

```text
remaining connector resolution:
  use junction_areas.json short_edge_absorption_candidate cases
  build short-edge absorption transaction
  add real clothoid / paramPoly3 fitting instead of Hermite proxy
  add collision / swept-envelope scoring
```

然后再做：

```text
circular arc candidate
clothoid candidate
paramPoly3 candidate
radius/collision/curvature scoring
short-edge absorption transaction
  OpenDRIVE connecting road + laneLink intent
```

## 不要优先做

```text
不要把修复逻辑移到 Houdini。
不要恢复旧 lane_graph / lane_surface 作为当前主线。
不要为了消除 radius warning 在 Houdini 几何里硬调小圆弧。
不要批量自动应用 repair candidates，必须走 transaction + QA。
```

## 必读文件

```text
README.md
AI_START_HERE.md
ROAD_REPAIR_STAGE_ARCHITECTURE.md
LAYERED_PIPELINE_INITIAL_PLAN.md
scripts/README.md
data/README.md
reports/README.md
scripts/repair_road_skeleton.py
scripts/topology_repair.py
scripts/regularize_junction_areas.py
scripts/optimize_junction_centerlines.py
```
