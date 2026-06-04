# scripts 目录说明

## 当前主线入口

```text
repair_road_skeleton.py
```

它负责串起当前道路修复主线。除非明确开发某个阶段，否则优先从这个入口运行。

## 主线阶段脚本

```text
topology_repair.py
  L3 拓扑修复。生成 repaired roads、repair candidates、repair decisions、repair casebook。

run_repair_casebook.py
  L3 回归入口。重放已知误报和被拒绝的高置信候选。

run_auto_qa.py
  L3 / L4 / L7 / L8 通用 QA gate。
  当前支持 raw_roads、topology_repair、road_graph、lane_graph、movement_corridor、
  compound_junction_merge（复合路口合并）阶段。

build_road_graph.py
  L4 把 repaired roads 转成 node / edge road graph。

build_junction_semantics.py
  L5 识别 junction approaches、movements、through / turn 语义。

regularize_junction_areas.py
  L5.5 生成 junction conflict zone、entry poses、movement intents。

optimize_junction_centerlines.py
  L6 生成 clean engineering skeleton。当前已消费 regularized entry poses。

junction_geometry_audit.py
  L6 工程几何 QA。重点看 radius、trim spread、endpoint distance。

solve_junction_connectors.py
  L6.5 connector solver v2 候选入口。生成 current / circular / paramPoly3 Hermite / G1 proxy 候选并评分。
  只写 candidate/report，不直接替换 clean skeleton。

apply_connector_replacements.py
  L6.6 replacement transaction。只应用 replacement_ready_candidates，并用 junction_geometry_audit 做 trial QA。
  指标不回退才写回 optimized centerlines。

plan_short_edge_absorptions.py
  L6.9 junction-zone expansion planner。把 junction_areas.json 里的 short_edge_absorption_candidate
  细分成 transaction_ready / qa_candidate / blocked，输出候选和报告。
  这是非破坏阶段；short-edge absorption（短边吸收）只是 junction-zone expansion（路口影响区扩张）的子问题。

build_lane_attribute_model.py
  L7.0 lane attribute model。把 lanes / width / turn:lanes 标准化为 confidence-tagged lane attributes。
  当前启用 temporary_all_roads_bidirectional_two_lane_v1（临时全道路双向两车道策略）：
  所有道路边统一生成 2 条物理车道、双向通行；OSM oneway（OSM 单行）和原始 lanes / width
  只保留在 source_observation（源数据观察值）里，不能直接驱动后续车道拓扑。
  这是非破坏阶段，不生成 lane graph 或 lane geometry。

build_lane_graph.py
  L7.1 lane graph topology（车道拓扑图拓扑）v1。读取 road_graph、lane_attribute_model、junction_semantics，
  输出 lane_graph.json（车道拓扑图 JSON）和 lane_graph_report.json（车道拓扑图报告）。
  这是结构化 graph artifact（拓扑图产物），不是图片；centerline_xz 只是 approximate offset preview（近似偏移预览），
  不是 final lane geometry（最终车道几何）。
  traffic_direction_policy（交通方向策略）当前应全部为 temporary_bidirectional_two_lane_policy（临时双向两车道策略）；
  source_oneway（源数据单行）只作为 source_observation / issue（源数据观察值 / 问题标记）存在。

export_lane_graph_svg.py
  L7.2 lane graph SVG visualization（车道拓扑图 SVG 可视化）。
  默认输出 reports/visualizations/<area_id>_lane_graph_topology.svg。
  如果 movement_corridor_candidates.json（通行走廊候选 JSON）存在，会叠加 anchored movement corridors（锚点版通行走廊）。
  当前默认使用 review drawing（审图线稿）样式：3200px 宽画布、lane road casing（车道道路底线）、
  更小的 entry / exit anchors（入口 / 出口锚点）和 compound trial corridor（复合试运行走廊）高亮。
  这是 human QA view（人工质检视图），不是 source truth（源数据真值）。

solve_movement_corridors.py
  L8.0 movement corridor solver（通行走廊求解器）v1。
  读取 lane_graph.json（车道拓扑图 JSON）和 short_edge_absorption_candidates.json（短边吸收候选 JSON），
  输出 movement_corridor_candidates.json（通行走廊候选 JSON）。
  这是 non-destructive staging solver（非破坏式暂存求解器），不替换 clean skeleton（干净道路骨架）。
  当前 corridor endpoint（走廊端点）已优先来自 lane_entry_anchor / lane_exit_anchor（车道入口 / 出口锚点）。
  transaction_ready short-edge absorption（事务就绪短边吸收）候选会生成 planned virtual anchors（规划虚拟锚点），
  只用于预览 junction-zone expansion（路口影响区扩张）后的退让距离。
  best_candidate_family（最佳候选曲线族）仍只是 preview score（预览评分），不能作为发布选择。

score_movement_corridors.py
  L8.6 movement corridor scoring（通行走廊评分）v1。
  读取 lane_graph.json（车道拓扑图 JSON）、movement_corridor_candidates.json（通行走廊候选 JSON）
  和 compound_junction_merge_transactions.json（复合路口合并事务 JSON）。
  输出 movement_corridor_scoring.json（通行走廊评分 JSON）和 movement_corridor_scoring_report.json（评分报告）。
  当前评分包括 collision_score（碰撞评分）、swept_envelope_score（扫掠包络评分）和
  curvature_score（曲率评分）。这是 non-destructive QA scoring（非破坏式质检评分），不写回 clean skeleton（干净道路骨架）。

audit_movement_anchors.py
  L8.2 movement anchor gap audit（通行锚点缺口审计）v1。
  读取 movement_corridor_candidates.json、junction_areas.json、road_graph.json、short_edge_absorption_candidates.json。
  输出 movement_anchor_gap_audit.json（通行锚点缺口审计 JSON）和 movement_anchor_gap_audit_report.json（通行锚点缺口审计报告）。
  这是 non-destructive QA（非破坏式质检），用于把剩余偏近锚点分类成 compound_junction_merge（复合路口合并）、
  keep_qa（保留质检）或 defer（暂缓），不改 clean skeleton（干净道路骨架）。

plan_compound_junction_merges.py
  L8.3 compound junction merge planner（复合路口合并规划器）v1。
  读取 movement_anchor_gap_audit.json（通行锚点缺口审计 JSON）、junction_areas.json（路口区域 JSON）和 road_graph.json（道路图 JSON）。
  只消费 adjacent_junction_short_link（相邻路口短连接） + compound_junction_merge（复合路口合并）记录。
  输出 compound_junction_merge_candidates.json（复合路口合并候选 JSON）和 compound_junction_merge_report.json（复合路口合并报告）。
  当前 24 个偏近 anchor（锚点）被收敛为 3 个 low-risk transaction_candidate（低风险事务候选）。
  这是 non-destructive planner（非破坏式规划器），不改 road_graph（道路图）或 clean skeleton（干净道路骨架）。
```

## Houdini helper

```text
enable_rpyc_in_houdini.py
houdini_build_road_test.py
houdini_cook_rpyc.py
houdini_cook_open_session.py
```

当前 `--sync-houdini` 走 `repair_road_skeleton.py` 内的远程同步代码，负责创建三阶段节点列。

## 暂存的下游研究脚本

```text
rebuild_road_test.py
lane_model_builder.py
generate_lane_geometry_debug.py
generate_lane_surface_v1.py
generate_road_preview.py
audit_road_pipeline.py
```

这些脚本保留给未来 lane surface、OpenDRIVE 阶段或旧版对照。它们不是当前 clean skeleton / lane graph topology 阶段的入口。

## 修改规则

```text
修 topology_repair.py 后必须跑 run_repair_casebook.py。
修 regularize_junction_areas.py 后必须重跑 optimize_junction_centerlines.py 和 junction_geometry_audit.py。
修 optimize_junction_centerlines.py 后必须看 optimized_centerlines_report 和 junction_geometry_audit_report。
修 solve_junction_connectors.py 后必须看 junction_connector_solver_report，确认 replacement_ready 与 unresolved case。
修 apply_connector_replacements.py 后必须看 junction_connector_replacement_report 和替换后的 junction_geometry_audit_report。
修 plan_short_edge_absorptions.py 后必须看 short_edge_absorption_report，确认 transaction_ready 数量和 affected_unresolved_connectors。
修 build_lane_attribute_model.py 后必须看 lane_attribute_model_report，确认 inferred ratio 和 missing turn lanes。
修 build_lane_graph.py 后必须跑 run_auto_qa.py --stage lane_graph，并看 lane_graph_report，确认 lane_link reference error 为 0。
修 export_lane_graph_svg.py 后必须确认 reports/visualizations/<area_id>_lane_graph_topology.svg 存在，并看 report 里的 link_source 是否为 movement_corridor_anchors（通行走廊锚点）。
修 solve_movement_corridors.py 后必须跑 run_auto_qa.py --stage movement_corridor，并看 movement_corridor_report。
如果改的是 short-edge planned anchor（短边规划锚点），还必须看 planned_virtual_anchors（规划虚拟锚点数量）、
planned_virtual_anchor_cases（规划虚拟锚点案例数）和剩余 entry_trim_capacity_limited（入口退让距离受限）数量。
如果改的是 lane-level anchoring（车道级锚点），还必须人工看锚点版 SVG：junction_movement（路口通行动作）的端点不应继续吸到多车道整体中轴。
修 audit_movement_anchors.py 后必须看 movement_anchor_gap_audit_report，确认 adjacent_junction_short_link（相邻路口短连接）、
dead_end_stub_capacity_limited（死端短支路退让受限）和 low_value_short_edge_absorption（低收益短边吸收）分类数量。
修 plan_compound_junction_merges.py 后必须看 compound_junction_merge_report，确认 eligible_anchor_records（合格锚点记录）、
transaction_candidates（事务候选）、risk_counts（风险计数）和 ignored_classification_counts（忽略分类计数）。
修 Houdini 同步后必须确认 OUT_raw_road_lines、OUT_repaired_road_lines、OUT_clean_road_skeleton 的列顺序。
```
