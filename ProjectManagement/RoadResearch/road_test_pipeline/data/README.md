# data 目录说明

## raw

`raw/` 保存原始下载或 API 返回数据。原则上只追加，不手工修。

当前样本：

```text
raw/pattaya_central_500m_roads.osm
raw/pattaya_central_500m.overpassql
```

## processed

`processed/` 保存每个阶段的机器可读 artifact。它们可以由脚本重建，不要把它们当手工编辑源。

当前主线产物：

```text
pattaya_central_500m_roads_raw.geojson
pattaya_central_500m_roads_repaired.geojson
pattaya_central_500m_repair_candidates.json
pattaya_central_500m_repair_decisions.json
pattaya_central_500m_repair_casebook.json
pattaya_central_500m_road_graph.json
pattaya_central_500m_junction_semantics.json
pattaya_central_500m_junction_areas.json
pattaya_central_500m_engineering_reference_lines.json
pattaya_central_500m_roads_optimized_centerlines.geojson
pattaya_central_500m_junction_connector_candidates.json
pattaya_central_500m_short_edge_absorption_candidates.json
pattaya_central_500m_lane_attribute_model.json
pattaya_central_500m_lane_graph.json
pattaya_central_500m_movement_corridor_candidates.json
pattaya_central_500m_movement_anchor_gap_audit.json
pattaya_central_500m_compound_junction_merge_candidates.json
pattaya_central_500m_roads_clean_skeleton.geojson
pattaya_central_500m_junction_movements_debug.geojson
```

## 数据边界

```text
roads_raw.geojson
  canonical raw road lines, 不承载拓扑修复结果。

roads_repaired.geojson
  L3 之后的保守拓扑修复结果。

junction_areas.json / engineering_reference_lines.json
  L5.5 产物，是 L6 connector solver 的输入。

roads_optimized_centerlines.geojson
  L6 工程中心线，包含 approach、junction connector、corner fillet。

junction_connector_candidates.json
  L6.5 connector solver v2 候选集。用于 replacement transaction，不是发布几何。

short_edge_absorption_candidates.json
  L6.9 junction-zone expansion（路口影响区扩张）候选集。用于下一步 destructive transaction（写入式事务），不直接改 graph 或 clean skeleton。

lane_attribute_model.json
  L7.0 confidence-tagged lane attributes（带置信度的车道属性）。用于 lane graph，不是车道几何。

lane_graph.json
  L7.1 lane graph topology（车道拓扑图拓扑）。这是 structured graph data（结构化拓扑数据），
  包含 directed lanes（有方向车道）、lane links（车道连接边）、confidence（置信度）和 issues（问题标记）。
  它不是图片文件；PNG / SVG 只能作为 visualization（可视化）导出。
  其中 centerline_xz 是 approximate offset preview（近似偏移预览），不是 final lane geometry（最终车道几何）。

movement_corridor_candidates.json
  L8.0 movement corridor candidates（通行走廊候选）。从 lane_graph（车道拓扑图）生成 lane-level
  movement corridor（车道级通行走廊）候选，包含 topology_straight_baseline（拓扑直线基线）、
  bezier_g1_preview（G1 连续贝塞尔预览）、param_poly3_hermite_proxy（参数三次曲线 Hermite 代理）。
  这是候选数据，不直接改 clean skeleton（干净道路骨架）。
  当前 v1 的 start/end 来自 lane_entry_anchor / lane_exit_anchor（车道入口 / 出口锚点）。
  transaction_ready short-edge absorption（事务就绪短边吸收）候选会以 planned virtual anchors（规划虚拟锚点）预览。

movement_anchor_gap_audit.json
  L8.2 movement anchor gap audit（通行锚点缺口审计）。解释 planned virtual anchors（规划虚拟锚点）之后仍偏近的锚点。
  当前分类包括 adjacent_junction_short_link（相邻路口短连接）、dead_end_stub_capacity_limited（死端短支路退让受限）、
  low_value_short_edge_absorption（低收益短边吸收）。这是 QA artifact（质检产物），不直接改 clean skeleton（干净道路骨架）。

compound_junction_merge_candidates.json
  L8.3 compound junction merge planner（复合路口合并规划器）输出。
  只消费 movement_anchor_gap_audit（通行锚点缺口审计）里的 adjacent_junction_short_link（相邻路口短连接）。
  当前把 24 个偏近 anchor（锚点）归并成 3 个 transaction_candidate（事务候选）。
  这是 transaction planning artifact（事务规划产物），不是已写回的 road graph（道路图）或 clean skeleton（干净道路骨架）。

roads_clean_skeleton.geojson
  Houdini 默认导入的 clean skeleton artifact。
```
