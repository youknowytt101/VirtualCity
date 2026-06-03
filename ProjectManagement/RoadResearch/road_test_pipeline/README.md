# 道路测试管线

这个目录是 `ProjectManagement/RoadResearch` 下的独立道路研究管线。它不读写 VirtualCity
主管线的 `RawData/`、`Scripts/`、`Config/`、`Reports/`、`Houdini/` 目录。

## 先读

下一个 AI 或开发者优先按这个顺序看：

```text
AI_START_HERE.md
CURRENT_STAGE_SNAPSHOT.md
NEXT_AI_HANDOFF.md
LANE_LEVEL_JUNCTION_RECONSTRUCTION_PLAN.md
scripts/README.md
data/README.md
reports/README.md
ROAD_REPAIR_STAGE_ARCHITECTURE.md
```

## 当前目标

当前目标不是生成最终车道或 OpenDRIVE，而是先把地图 API 的脏道路数据修成稳定、可审计、
可迭代的道路骨架：

```text
原始地图数据
  -> 道路修复 / Houdini 前置工程处理
  -> road graph
  -> junction semantics
  -> junction area regularization
  -> clean single-line skeleton
  -> Houdini 只负责可视化和后续构建
```

Houdini 不负责修复道路拓扑，也不发明数据真值。

## 主入口

从仓库根目录运行：

```powershell
uv --cache-dir E:\VirtualCity\Scripts\.uv-cache run python ProjectManagement/RoadResearch/road_test_pipeline/scripts/repair_road_skeleton.py --area-id pattaya_central_500m --sync-houdini
```

如果不用 `uv`，当前环境也可以直接：

```powershell
python ProjectManagement/RoadResearch/road_test_pipeline/scripts/repair_road_skeleton.py --area-id pattaya_central_500m --sync-houdini
```

## 当前阶段顺序

```text
L3 topology repair
L3 topology repair QA
L3 repair casebook QA
L4 road graph
L4 road graph QA
L5 junction semantics
L5.5 junction area regularization
L6 engineering centerline, consumes regularized entry poses
L6 junction geometry audit
L6.5 junction connector solver candidates
L6.6 connector replacement transaction
L6.7 post-replacement junction geometry audit
L6.8 junction connector solver candidates refresh
L6.9 junction-zone expansion planner
L7.0 lane attribute model
L7.1 lane graph topology
L7.1 lane graph QA
L7.2 lane graph SVG visualization
L8.0 movement corridor candidates
L8.1 planned-anchor SVG visualization
L8.0 movement corridor QA
L8.2 movement anchor gap audit
L8.3 compound junction merge planner
L8.3 compound junction merge QA
L8.4 compound junction merge transaction
L8.4 compound junction merge transaction QA
L8.5 staged compound movement SVG visualization
L8.6 movement corridor scoring（通行走廊评分，下一步）
L6 clean skeleton artifact
L9 optional Houdini sync
```

## Houdini 节点视图

`--sync-houdini` 会重建 `/obj/road_test_<area_id>`。节点从左到右是阶段列：

```text
原始数据线
  python_import_raw_roads
  OUT_raw_road_lines

道路拓扑修复线
  python_import_repaired_roads
  OUT_repaired_road_lines

干净单线工程骨架
  python_import_clean_road_skeleton
  OUT_clean_road_skeleton

L6 debug 分支
  python_filter_junction_connector_arcs
  OUT_junction_connector_arcs
  python_filter_corner_fillet_arcs
  OUT_corner_fillet_arcs
```

主线是 `raw -> repaired topology -> clean single-line skeleton`。路口 connector arcs 和
corner fillets 是 clean skeleton 的 debug 分支，不是新的数据真值层。

## 核心产物

```text
data/processed/<area_id>_roads_raw.geojson
data/processed/<area_id>_roads_repaired.geojson
data/processed/<area_id>_repair_candidates.json
data/processed/<area_id>_repair_decisions.json
data/processed/<area_id>_repair_casebook.json
data/processed/<area_id>_road_graph.json
data/processed/<area_id>_junction_semantics.json
data/processed/<area_id>_junction_areas.json
data/processed/<area_id>_engineering_reference_lines.json
data/processed/<area_id>_roads_optimized_centerlines.geojson
data/processed/<area_id>_junction_connector_candidates.json
data/processed/<area_id>_short_edge_absorption_candidates.json
data/processed/<area_id>_lane_attribute_model.json
data/processed/<area_id>_lane_graph.json
data/processed/<area_id>_movement_corridor_candidates.json
data/processed/<area_id>_movement_anchor_gap_audit.json
data/processed/<area_id>_compound_junction_merge_candidates.json
data/processed/<area_id>_roads_clean_skeleton.geojson
```

`lane_graph.json（车道拓扑图 JSON）` 是 structured graph artifact（结构化拓扑产物），不是图片文件。
如果需要给人看，可以从它导出 PNG / SVG visualization（可视化），但图片不能作为 source truth（源数据真值）。
当前 `centerline_xz` 只是 approximate offset preview（近似偏移预览），不代表 final lane geometry（最终车道几何）。
当前 `traffic_direction_policy（交通方向策略）` 会明确区分：

```text
temporary_bidirectional_two_lane_policy（临时双向两车道策略）
```

当前启用 `temporary_all_roads_bidirectional_two_lane_v1（临时全道路双向两车道策略）`：
所有 road_graph edge（道路图边）统一展开为 2 条物理车道、双向通行；明确 `OSM oneway（OSM 单行）`
也只保留在 `source_observation（源数据观察值）` 和 issue（问题标记）里，不再阻断 L5/L7/L8 movement（通行动作）。
这个策略是临时稳定策略，不是 source truth（源数据真值）。

当前 SVG 可视化路径：

```text
reports/visualizations/<area_id>_lane_graph_topology.svg
```

`export_lane_graph_svg.py（SVG 导出器）` 默认会在相关 JSON 存在时自动叠加 movement corridors（通行走廊）和
compound trial corridors（复合试运行走廊）。当前主入口会分阶段显式控制：

```text
L8.1 planned-anchor SVG: 使用 --no-compound-transactions（禁用复合事务叠加），compound_corridors_rendered = 0
L8.5 staged compound SVG: 显式传入 compound_junction_merge_transactions.json，compound_corridors_rendered = 24
```

当前默认 SVG 是 `review_drawing（审图线稿）` 样式：

```text
svg_width_px = 3200
svg_height_px = 2740
lane road casing（车道道路底线）= enabled
anchor_marker_radius_px = 0.55
compound trial corridor（复合试运行走廊）= highlighted
```

`movement_corridor_candidates.json（通行走廊候选 JSON）` 是 structured candidate artifact（结构化候选产物），
用于 movement corridor solver（通行走廊求解器）和后续 collision（碰撞）/ swept envelope（扫掠包络）评分。
它同样不是 final lane geometry（最终车道几何）。

`movement_anchor_gap_audit.json（通行锚点缺口审计 JSON）` 解释 planned virtual anchors（规划虚拟锚点）
之后仍偏近的锚点。当前剩余 36 个偏近锚点已经分类为：

```text
24 adjacent_junction_short_link（相邻路口短连接） -> compound_junction_merge（复合路口合并）
8 dead_end_stub_capacity_limited（死端短支路退让受限） -> keep_qa（保留质检）
4 low_value_short_edge_absorption（低收益短边吸收） -> defer（暂缓）
```

`compound_junction_merge_candidates.json（复合路口合并候选 JSON）` 读取上述 audit（审计）结果，
只处理 `adjacent_junction_short_link（相邻路口短连接）`。当前 24 个相关锚点已经收敛为：

```text
3 transaction_candidate（事务候选）
3 low risk（低风险）
0 reference_errors（引用错误）
```

这是 non-destructive planner（非破坏式规划器）输出，不直接改 `road_graph（道路图）`、
`clean skeleton（干净道路骨架）` 或 Houdini（胡迪尼）几何。

## 当前 SVG 观察结论

如果在 `reports/visualizations/<area_id>_lane_graph_topology.svg` 里看到某些车道连接线的终点落在 3 车道或
4 车道整体中轴处，先确认 SVG report（SVG 报告）里的 `link_source`。当前 exporter（导出器）会在
`movement_corridor_candidates.json（通行走廊候选 JSON）` 存在时使用 `movement_corridor_anchors（通行走廊锚点）`。
如果 `link_source = lane_graph_endpoint_preview（车道拓扑端点预览）`，那张图不能判断真实汇入。

当前原因：

```text
lane_graph.centerline_xz
  是 approximate offset preview（近似偏移预览），不是 final lane geometry（最终车道几何）。

solve_movement_corridors.py
  已把 engineering_reference_lines.json 的 entry pose（入口姿态）和 lane lateral offset（车道横向偏移）
  合成为 lane_entry_anchor / lane_exit_anchor（车道入口 / 出口锚点）。
  已把 transaction_ready short-edge absorption candidates（事务就绪短边吸收候选）
  显示为 planned virtual anchors（规划虚拟锚点），用于复核短边路口退让距离。
  当前 best_candidate_family（最佳候选曲线族）仍是 preview score（预览评分），不是发布选择。

turn:lanes（分车道转向）
  当前源数据缺失率为 1.0，lane links（车道连接边）仍是低置信推断。
```

正确下一步是在 `scripts/solve_movement_corridors.py` 和 staged compound corridor（暂存复合走廊）候选曲线上增加
collision_score（碰撞评分）/ swept_envelope_score（扫掠包络评分）/ curvature_score（曲率评分），
不是手工编辑 SVG 或 Houdini（胡迪尼）节点。

## 核心报告

```text
reports/<area_id>_repair_report.json
reports/qa/<area_id>_topology_repair_qa_report.json
reports/qa/<area_id>_repair_casebook_qa_report.json
reports/<area_id>_road_graph_report.json
reports/qa/<area_id>_road_graph_qa_report.json
reports/<area_id>_junction_semantics_report.json
reports/<area_id>_junction_area_regularization_report.json
reports/<area_id>_optimized_centerlines_report.json
reports/<area_id>_junction_geometry_audit_report.json
reports/<area_id>_junction_connector_solver_report.json
reports/<area_id>_junction_connector_replacement_report.json
reports/<area_id>_short_edge_absorption_report.json
reports/<area_id>_lane_attribute_model_report.json
reports/<area_id>_lane_graph_report.json
reports/qa/<area_id>_lane_graph_qa_report.json
reports/<area_id>_lane_graph_svg_report.json
reports/<area_id>_movement_corridor_report.json
reports/<area_id>_movement_anchor_gap_audit_report.json
reports/<area_id>_compound_junction_merge_report.json
reports/qa/<area_id>_compound_junction_merge_qa_report.json
reports/qa/<area_id>_movement_corridor_qa_report.json
reports/<area_id>_road_skeleton_repair_report.json
reports/<area_id>_road_skeleton_repair_summary.json
reports/<area_id>_houdini_raw_road_preview_report.json
reports/<area_id>_houdini_clean_skeleton_report.json
```

## 当前主线脚本

```text
scripts/repair_road_skeleton.py          # 当前唯一主入口
scripts/topology_repair.py               # 保守拓扑修复 + candidates/decisions/casebook
scripts/run_repair_casebook.py           # 已知误报/拒绝案例回归测试
scripts/build_road_graph.py
scripts/build_junction_semantics.py
scripts/regularize_junction_areas.py     # 路口区域正规化，输出 entry poses / movement intents
scripts/optimize_junction_centerlines.py # 当前 clean skeleton 生成器，消费 regularized entry poses
scripts/junction_geometry_audit.py
scripts/solve_junction_connectors.py     # connector solver v2 候选生成 + 评分，不直接替换几何
scripts/apply_connector_replacements.py  # replacement transaction，trial audit 通过才写回
scripts/plan_short_edge_absorptions.py   # junction-zone expansion 候选规划，不直接改图
scripts/build_lane_attribute_model.py    # 带置信度的车道属性标准化，不生成车道几何
scripts/build_lane_graph.py              # 车道拓扑图 v1，生成 directed lanes / lane links，不生成最终路面
scripts/export_lane_graph_svg.py         # 车道拓扑图 SVG 可视化，只给人看
scripts/solve_movement_corridors.py      # 通行走廊候选 v1，不做破坏式替换
scripts/audit_movement_anchors.py        # 通行锚点缺口审计，分类剩余偏近锚点
scripts/plan_compound_junction_merges.py # 复合路口合并规划器，只输出事务候选
scripts/run_auto_qa.py
```

Houdini 相关 helper：

```text
scripts/enable_rpyc_in_houdini.py
scripts/houdini_build_road_test.py
scripts/houdini_cook_rpyc.py
```

旧 lane / preview / rebuild 脚本暂时保留给未来 lane/OpenDRIVE 阶段，但不是当前入口：

```text
scripts/rebuild_road_test.py
scripts/lane_model_builder.py
scripts/generate_lane_geometry_debug.py
scripts/generate_lane_surface_v1.py
scripts/generate_road_preview.py
scripts/audit_road_pipeline.py
```

## 设计文档

优先阅读：

```text
NEXT_AI_HANDOFF.md
ROAD_REPAIR_STAGE_ARCHITECTURE.md
LAYERED_PIPELINE_INITIAL_PLAN.md
```

`HANDOFF_DESIGN.md` 是较早的交接设计，仍可参考，但当前进度以本 README 和
`NEXT_AI_HANDOFF.md` 为准。

## 当前已知状态

`pattaya_central_500m` 当前样本：

```text
topology repair QA: pass
repair casebook QA: pass
road graph QA: warn, width_fallback_ratio = 1.0
junction semantics: blocked_movements = 0, source_oneway_blocked_movements_if_trusted = 142
junction area regularization: warn, entry_trim_capacity_limited = 28, short_edge_absorption_candidate = 26
optimized centerlines: 149 regularized entry poses consumed, 50 bezier_tangent_fallback connectors
junction geometry audit: warn, radius_below_design_min = 78
connector replacement: accepted_replacements = 6
connector solver v2 refresh: warn, solver_cases = 85, unresolved_solver_cases = 85, replacement_ready_candidates = 0
junction-zone expansion planner: warn, 26 short-edge flags, 19 transaction_ready, affected_unresolved_connectors = 46
lane attribute model: warn, active_lane_policy = temporary_all_roads_bidirectional_two_lane_v1, source_oneway_overridden = 134, missing_turn_lanes_ratio = 1.0
lane graph topology: warn, lanes = 486, lane_links = 612, lane_link_reference_errors = 0
traffic direction policy: source_oneway_lane_ratio = 0.0, temporary_bidirectional_two_lane_policy_lane_ratio = 1.0
lane graph QA: pass
lane graph SVG: reports/visualizations/pattaya_central_500m_lane_graph_topology.svg, review_drawing = 3200 x 2740
L8.1 anchor-only SVG: pass, compound_corridors_rendered = 0
movement corridor solver: warn, corridor_cases = 306, candidate_curves = 918, reference_errors = 0, planned_virtual_anchors = 76, planned_virtual_anchor_cases = 72
movement anchor gap audit: warn, remaining_capacity_limited_anchors = 36, adjacent_junction_short_link = 24, dead_end_stub_capacity_limited = 8, low_value_short_edge_absorption = 4
compound junction merge planner: warn, eligible_anchor_records = 24, eligible_bridge_edges = 3, candidates = 3, transaction_candidates = 3, risk_counts.low = 3
compound junction merge QA: pass, reference_errors = 0, blocked_candidates = 0, affected_anchor_coverage_ratio = 1.0, transaction_candidate_ratio = 1.0
compound junction merge transaction: warn, transactions = 3, accepted_for_staging = 3, compound_movement_corridor_cases = 24
compound junction merge transaction QA: pass, exposed_bridge_edge_cases = 0, capacity_limited_anchor_cases = 0, affected_corridor_replacement_ratio = 1.0
lane graph SVG compound overlay: pass, compound_corridors_rendered = 24, compound_anchor_markers_rendered = 48
movement corridor QA: warn, low_confidence_ratio = 1.0, ready_ratio = 0.0
```

这些 warning 不是 Houdini 布局问题。`width_fallback_ratio` 说明 OSM 宽度缺失；`radius_below_design_min`
和 `bezier_tangent_fallback` 说明当前 connector solver 还停留在圆弧 + 切线 Bezier 占位阶段。
当前 replacement transaction 已经能安全替换可发布候选；short-edge absorption planner 已经把
`26` 个短边候选缩小成 `19` 个 transaction_ready 候选，并且 L8 已把这些候选预览成
planned virtual anchors（规划虚拟锚点）。这一步不改 clean skeleton（干净道路骨架）。
L8.2 又把剩余 36 个偏近锚点拆成了复合路口、死端短支路和低收益短边三类。
L8.3 已把 `adjacent_junction_short_link（相邻路口短连接）` 收敛为 3 个
compound junction merge transaction_candidate（复合路口合并事务候选）。
L8.4 已完成 compound junction merge transaction（复合路口合并事务）的 trial staging（试运行暂存），
并生成 24 条 staged compound movement corridor（暂存复合通行走廊）。
L8.5 已把这些走廊叠加到 review_drawing SVG（审图线稿 SVG）。
下一步应先做 L8.6 movement corridor scoring（通行走廊评分），再推进真实
clothoid（缓和曲线） / paramPoly3（三次参数多项式）拟合和 destructive writeback（写入式回写）。
不要把 dead-end stub（死端短支路）强行延长。

新的上层目标是 lane-level junction reconstruction（车道级路口重建）。`arc（圆弧）` 不再是目标，
只是 `geometry candidate family（几何候选曲线族）` 之一。当前 lane graph（车道拓扑图）v1 和
movement corridor solver（通行走廊求解器）v1 已经落地，并已生成 lane_entry_anchor /
lane_exit_anchor（车道入口 / 出口锚点）。compound junction merge planner（复合路口合并规划器）v1
和 compound junction merge transaction（复合路口合并事务）v1 也已经落地。
下一步应该加入 collision_score（碰撞评分）、swept_envelope_score（扫掠包络评分）
和 curvature_score（曲率评分）；
缺失 `turn:lanes（分车道转向）`、`width（宽度）` 的推断继续保持低置信度。
