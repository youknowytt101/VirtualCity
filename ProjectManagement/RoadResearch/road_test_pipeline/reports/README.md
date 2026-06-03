# reports 目录说明

## 根目录报告

`reports/` 下是阶段运行报告和工程 audit。它们用于解释产物为什么变成当前状态。

重点文件：

```text
pattaya_central_500m_repair_report.json
pattaya_central_500m_road_graph_report.json
pattaya_central_500m_junction_semantics_report.json
pattaya_central_500m_junction_area_regularization_report.json
pattaya_central_500m_optimized_centerlines_report.json
pattaya_central_500m_junction_geometry_audit_report.json
pattaya_central_500m_junction_connector_solver_report.json
pattaya_central_500m_junction_connector_replacement_report.json
pattaya_central_500m_short_edge_absorption_report.json
pattaya_central_500m_lane_attribute_model_report.json
pattaya_central_500m_lane_graph_report.json
pattaya_central_500m_lane_graph_svg_report.json
pattaya_central_500m_movement_corridor_report.json
pattaya_central_500m_movement_anchor_gap_audit_report.json
pattaya_central_500m_compound_junction_merge_report.json
pattaya_central_500m_road_skeleton_repair_report.json
pattaya_central_500m_road_skeleton_repair_summary.json
pattaya_central_500m_road_skeleton_repair.log
```

## qa

`reports/qa/` 是自动 gate 和回归测试结果。

```text
pattaya_central_500m_raw_roads_qa_report.json
pattaya_central_500m_topology_repair_qa_report.json
pattaya_central_500m_repair_casebook_qa_report.json
pattaya_central_500m_road_graph_qa_report.json
pattaya_central_500m_lane_graph_qa_report.json
pattaya_central_500m_movement_corridor_qa_report.json
pattaya_central_500m_compound_junction_merge_qa_report.json
```

## 读报告顺序

如果某次改动导致输出异常，按这个顺序读：

```text
road_skeleton_repair.log
road_skeleton_repair_summary.json
qa/*_topology_repair_qa_report.json
qa/*_repair_casebook_qa_report.json
qa/*_road_graph_qa_report.json
junction_area_regularization_report.json
optimized_centerlines_report.json
junction_geometry_audit_report.json
junction_connector_solver_report.json
junction_connector_replacement_report.json
short_edge_absorption_report.json
lane_attribute_model_report.json
lane_graph_report.json
qa/*_lane_graph_qa_report.json
lane_graph_svg_report.json
movement_corridor_report.json
movement_anchor_gap_audit_report.json
compound_junction_merge_report.json
qa/*_movement_corridor_qa_report.json
```

## 当前 warning 含义

```text
width_fallback_ratio = 1.0
  OSM 样本几乎没有可靠 width tag，属于源数据覆盖问题。

entry_trim_capacity_limited
  路口附近 edge 太短，无法给足设计入口距离。

short_edge_absorption_candidate
  可能需要在 connector solver 或下一轮 topology repair 中吸收短边。

transaction_ready
  junction-zone expansion planner 认为可以进入破坏式事务试跑的候选；仍然必须 audit rollback。

lane_attribute_model
  带置信度的车道属性报告；用于暴露 lanes、width、turn:lanes 的来源、推断和缺失。

lane_graph_topology_v1
  lane graph（车道拓扑图）报告；验证 directed lanes（有方向车道）和 lane links（车道连接边）是否引用完整。
  它是 structured graph artifact（结构化拓扑产物），不是图片；后续 PNG/SVG 只应作为 visualization（可视化）。

lane_graph_svg_visualization
  lane graph SVG visualization（车道拓扑图 SVG 可视化）报告。默认 SVG 路径：
  reports/visualizations/<area_id>_lane_graph_topology.svg。这个 SVG 只用于 human QA（人工质检）。
  当前默认样式是 review_drawing（审图线稿）：3200px 宽画布、lane road casing（车道道路底线）、
  更小的 entry / exit anchors（入口 / 出口锚点）和 compound trial corridor（复合试运行走廊）高亮。

movement_corridor_solver_v1
  movement corridor（通行走廊）报告；从 laneLink（车道连接边）生成 corridor candidates（走廊候选）。
  当前是 non-destructive staging solver（非破坏式暂存求解器），不替换 clean skeleton（干净道路骨架）。
  如果 SVG 里 corridor endpoint（走廊端点）落到多车道整体中轴，这应作为 lane-level anchoring（车道级锚点）
  的下一步问题处理，不应解读为最终车道几何正确。

movement_anchor_gap_audit_v1
  通行锚点缺口审计报告；解释 planned virtual anchors（规划虚拟锚点）后仍偏近的锚点。
  当前 36 个 remaining_capacity_limited_anchors（剩余退让受限锚点）已分成：
  adjacent_junction_short_link（相邻路口短连接）、dead_end_stub_capacity_limited（死端短支路退让受限）、
  low_value_short_edge_absorption（低收益短边吸收）。
  其中 adjacent_junction_short_link 应进入 compound junction merge（复合路口合并）规划；
  dead-end stub 不应被硬延长。

compound_junction_merge_planner_v1
  复合路口合并规划报告；读取 movement_anchor_gap_audit（通行锚点缺口审计）后，
  只把 adjacent_junction_short_link（相邻路口短连接）归并成 compound junction merge candidates（复合路口合并候选）。
  当前样本是 24 个 eligible_anchor_records（合格锚点记录）、3 个 eligible_bridge_edges（合格桥接短边）、
  3 个 low-risk transaction_candidate（低风险事务候选）、0 个 reference_errors（引用错误）。
  这个报告不是写回证明；当前已经由 compound junction merge transaction（复合路口合并事务）生成
  24 条 staged compound movement corridor（暂存复合通行走廊）。

compound_junction_merge_transaction_v1
  复合路口合并事务报告；当前 3 个 transaction_candidate（事务候选）全部 accepted_for_staging（接受为暂存预览），
  compound_movement_corridor_cases（复合通行走廊案例）= 24。
  下一步是 movement corridor scoring（通行走廊评分），不是 clean skeleton writeback（干净道路骨架写回）。

compound_junction_merge QA
  复合路口合并质量门禁；当前 pass。关键检查：
  reference_errors（引用错误）= 0、blocked_candidates（阻断候选）= 0、
  affected_anchor_coverage_ratio（受影响锚点覆盖率）= 1.0、
  transaction_candidate_ratio（事务候选比例）= 1.0。

inferred_without_turn_lanes
  因为缺少 turn:lanes（分车道转向），lane_link（车道连接边）只能根据 road movement（道路通行动作）
  和 lane rank（车道顺序）推断，必须保持低置信度。

bezier_tangent_fallback
  正规化 entry pose 不满足单圆弧条件，当前用切线连续 Bezier 占位。

radius_below_design_min
  当前 connector 半径未达到设计阈值，是下一阶段 solver 的优先目标。

replacement_ready_candidates
  connector solver v2 认为可以进入替换事务的候选数量。不是自动发布数量。

accepted_replacements
  replacement transaction 已经通过 trial audit 并写回 optimized centerlines 的替换数量。

unresolved_solver_cases
  当前候选族仍无法安全解决的 connector，通常需要短边吸收、真实 clothoid/paramPoly3 或路口区域重构。
```
