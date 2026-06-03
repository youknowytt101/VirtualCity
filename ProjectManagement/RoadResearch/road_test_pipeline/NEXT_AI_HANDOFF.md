# 下一个 AI 接手指南

## 一句话目标

这个目录正在把“地图 API 道路数据”变成一个可复现、可审计、可自我 QA 的道路修复管线。
当前目标是稳定 road skeleton，并建立 topology-only lane graph（仅拓扑车道图）作为后续车道级路口重建的输入契约；不是最终 lane surface（车道路面）、OpenDRIVE（开放道路描述格式）或完整车道面。

## 当前接手判断

`L8.1 lane-level movement anchoring（车道级通行锚点）`、`L8.3 compound junction merge planner（复合路口合并规划器）`、
`L8.4 compound junction merge transaction（复合路口合并事务）` 和
`L8.5 staged compound movement SVG visualization（暂存复合通行走廊 SVG 可视化）` 已经完成。
当前最自然的下一步是 `L8.6 movement corridor scoring（通行走廊评分）`：
给普通 movement corridor（通行走廊）和 24 条 compound trial corridor（复合试运行走廊）补
`collision_score（碰撞评分） / swept_envelope_score（扫掠包络评分） / curvature_score（曲率评分）`，
不是继续在 Houdini（胡迪尼）里调节点，也不是直接写回 clean skeleton（干净道路骨架）。

补充：`L8.2 movement anchor gap audit（通行锚点缺口审计）` 已经完成。剩余 36 个偏近锚点已分类：

```text
24 adjacent_junction_short_link（相邻路口短连接） -> compound_junction_merge（复合路口合并）
8 dead_end_stub_capacity_limited（死端短支路退让受限） -> keep_qa（保留质检）
4 low_value_short_edge_absorption（低收益短边吸收） -> defer（暂缓）
```

当前临时方向/车道策略是 `temporary_all_roads_bidirectional_two_lane_v1（临时全道路双向两车道策略）`：

```text
所有道路边统一展开为双向 2 车道。
明确 OSM oneway（OSM 单行）也只保留为 source_observation（源数据观察值），不再阻断 movement（通行动作）。
lane_graph_report 中 source_oneway_lane_ratio = 0.0，temporary_bidirectional_two_lane_policy_lane_ratio = 1.0。
```

补充：`L8.3 compound junction merge planner（复合路口合并规划器）` 已完成。它把 24 个
`adjacent_junction_short_link（相邻路口短连接）` 锚点归并为 3 个 low-risk
`transaction_candidate（事务候选）`：

```text
compound junction merge planner: warn
eligible_anchor_records = 24
eligible_bridge_edges = 3
candidates = 3
transaction_candidates = 3
reference_errors = 0
compound_junction_merge QA = pass
ignored dead_end_stub_capacity_limited = 8
ignored low_value_short_edge_absorption = 4
```

用户已经在 SVG 里看到车道连接终点落到 3/4 车道整体中轴附近。这个现象应明确记录为 `preview limitation（预览限制）`：

```text
lane_graph.centerline_xz
  只是 approximate offset preview（近似偏移预览）

movement_corridor_solver_v1
  已用 engineering entry pose（工程入口姿态） + lane lateral offset（车道横向偏移）
  生成 lane_entry_anchor / lane_exit_anchor（车道入口 / 出口锚点）
  已用 short_edge_absorption_candidates.json（短边吸收候选 JSON）里的 transaction_ready（事务就绪）候选
  生成 junction-zone expansion planned virtual anchors（路口影响区扩张规划虚拟锚点）

正确修复点
  scripts/solve_movement_corridors.py
  engineering_reference_lines.json
  junction_areas.json
  lane_graph.json
```

所以旧 SVG 里的中轴汇入不是最终道路效果正确与否的结论。现在必须看审图版 SVG 或
movement_corridor_candidates.json（通行走廊候选 JSON）和
compound_junction_merge_transactions.json（复合路口合并事务 JSON）。

当前审图版 SVG 路径和关键样式：

```text
reports/visualizations/pattaya_central_500m_lane_graph_topology.svg
reports/pattaya_central_500m_lane_graph_svg_report.json
visual_mode = review_drawing（审图线稿）
svg_width_px = 3200
svg_height_px = 2740
anchor_marker_radius_px = 0.55
compound_corridors_rendered = 24
```

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

plan_short_edge_absorptions.py
  junction-zone expansion planner
  treats short-edge absorption as junction-zone expansion candidate planning
  writes short_edge_absorption_candidates.json and short_edge_absorption_report.json
  does not mutate road graph or clean skeleton

build_lane_attribute_model.py
  confidence-tagged lane attribute model
  writes lane_attribute_model.json and lane_attribute_model_report.json
  applies temporary_all_roads_bidirectional_two_lane_v1（临时全道路双向两车道策略）
  exposes missing width / turn:lanes and overridden source lanes / oneway before lane graph work

build_lane_graph.py
  topology-only lane graph（仅拓扑车道图）v1
  writes lane_graph.json and lane_graph_report.json
  creates directed lanes（有方向车道） and lane links（车道连接边） with confidence（置信度） and issues（问题标记）
  lane_graph（车道拓扑图） is structured graph data（结构化拓扑数据）, not an image file（图片文件）

export_lane_graph_svg.py
  lane graph SVG visualization（车道拓扑图 SVG 可视化）
  writes reports/visualizations/<area_id>_lane_graph_topology.svg
  if movement_corridor_candidates.json exists, renders anchored movement corridors（锚点版通行走廊）
  if compound_junction_merge_transactions.json exists, renders compound trial corridors（复合试运行走廊）
  current default style is review_drawing（审图线稿） with 3200px canvas width, lane road casing（车道道路底线）,
  smaller entry / exit anchors（入口 / 出口锚点） and highlighted compound corridors（复合走廊高亮）
  image is human QA（人工质检） only, not source truth（源数据真值）

solve_movement_corridors.py
  movement corridor solver（通行走廊求解器）v1
  writes movement_corridor_candidates.json and movement_corridor_report.json
  non-destructive staging solver（非破坏式暂存求解器）, no clean skeleton replacement
  endpoints now come from lane_entry_anchor / lane_exit_anchor（车道入口 / 出口锚点） when entry poses are available
  transaction_ready short-edge absorption（事务就绪短边吸收）候选会被显示为 planned virtual anchors（规划虚拟锚点）
  best_candidate_family（最佳候选曲线族） is preview-only（仅预览）, not publishable selection（可发布选择）

audit_movement_anchors.py
  movement anchor gap audit（通行锚点缺口审计）v1
  explains remaining capacity-limited anchors（剩余退让受限锚点）
  writes movement_anchor_gap_audit.json and movement_anchor_gap_audit_report.json
  classifies remaining close anchors into compound junction merge（复合路口合并）, keep_qa（保留质检）, or defer（暂缓）

plan_compound_junction_merges.py
  compound junction merge planner（复合路口合并规划器）v1
  reads movement_anchor_gap_audit.json（通行锚点缺口审计 JSON）, junction_areas.json（路口区域 JSON） and road_graph.json（道路图 JSON）
  writes compound_junction_merge_candidates.json（复合路口合并候选 JSON） and compound_junction_merge_report.json（复合路口合并报告）
  current output: 3 low-risk transaction_candidate（低风险事务候选）, no graph or skeleton mutation（无图或骨架写回）

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
junction semantics: blocked_movements = 0; source_oneway_blocked_movements_if_trusted = 142
junction area regularization: warn because 28 entry trims are capacity-limited and 26 short edges are absorption candidates
optimized centerlines: 149 regularized entry poses consumed, 129 exact, 20 scaled for edge length
junction geometry audit: warn because radius_below_design_min = 78
connector replacement: accepted 6 replacements without audit regression
connector solver v2 refresh: warn because solver_cases = 85, unresolved_solver_cases = 85, replacement_ready_candidates = 0
junction-zone expansion planner: warn because 26 short-edge flags were planned; 19 are transaction_ready and touch 46 unresolved connectors
lane attribute model: warn because all 243 edges are temporarily forced to bidirectional two-lane; source_oneway_overridden = 134; missing_turn_lanes_ratio = 1.0
lane graph topology: warn because missing_turn_lanes_lane_ratio = 1.0, but lane_link_reference_errors = 0; lanes = 486; lane_links = 612
lane graph QA: pass
lane graph SVG: reports/visualizations/pattaya_central_500m_lane_graph_topology.svg, review_drawing = 3200 x 2740
movement corridor solver: warn because all 306 corridor cases are low-confidence QA candidates; fully_anchored_case_ratio = 1.0, anchor_fallback_ratio = 0.0, planned_virtual_anchors = 76, planned_virtual_anchor_cases = 72
movement anchor gap audit: warn because 36 capacity-limited anchors remain; 24 are adjacent_junction_short_link, 8 are dead_end_stub_capacity_limited, 4 are low_value_short_edge_absorption
compound junction merge planner: warn because 3 low-risk transaction candidates are planned from 24 adjacent short-link anchors; 0 reference errors
compound junction merge QA: pass because reference_errors = 0, blocked_candidates = 0, affected_anchor_coverage_ratio = 1.0
compound junction merge transaction: warn because transactions = 3, accepted_for_staging = 3, compound_movement_corridor_cases = 24
compound junction merge transaction QA: pass because exposed_bridge_edge_cases = 0, capacity_limited_anchor_cases = 0, affected_corridor_replacement_ratio = 1.0
lane graph SVG compound overlay: pass because compound_corridors_rendered = 24, compound_anchor_markers_rendered = 48
movement corridor QA: warn because low_confidence_ratio = 1.0 and ready_ratio = 0.0
```

`radius_below_design_min` 现在已经不是 Houdini 布局问题，也不是 entry pose 未接入问题。
当前根因集中在两类：短边/路口空间不足，以及单圆弧无法同时满足两端 entry pose 和切线。
这些 case 已通过 `bezier_tangent_fallback`、`radius_below_design_min`、`junction_trim_spread_excess`
暴露给下一轮 solver。
更高层目标已经调整为 lane-level junction reconstruction（车道级路口重建）；arc（圆弧）只是候选曲线族。

## 下一步建议

优先做：

```text
remaining connector resolution:
  use movement_corridor_candidates.json as lane-level movement contract
  use lane_graph.json as topology contract
  keep lane_attribute_model.json as confidence contract
  use compound_junction_merge_transactions.json（复合路口合并事务 JSON） as staged compound corridor contract
  review review_drawing SVG（审图线稿 SVG） before trusting visual junction merge
  keep dead-end stubs as QA unless a better source proves the road continues
  add collision_score（碰撞评分） / swept_envelope_score（扫掠包络评分） / curvature_score（曲率评分） before trusting best_candidate_family
  use short_edge_absorption_candidates.json transaction_ready cases as junction-zone expansion candidates
  build destructive junction-zone expansion transaction（写入式路口影响区扩张事务） with audit rollback（审计回滚）
  add real clothoid / paramPoly3 fitting instead of Hermite proxy
  add collision / swept-envelope scoring
```

然后再做：

```text
circular arc candidate
clothoid candidate
paramPoly3 candidate
radius/collision/curvature scoring
junction-zone expansion transaction
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
CURRENT_STAGE_SNAPSHOT.md
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
scripts/build_lane_attribute_model.py
LANE_LEVEL_JUNCTION_RECONSTRUCTION_PLAN.md
```
