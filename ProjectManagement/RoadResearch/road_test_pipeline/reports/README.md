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
```

## 当前 warning 含义

```text
width_fallback_ratio = 1.0
  OSM 样本几乎没有可靠 width tag，属于源数据覆盖问题。

entry_trim_capacity_limited
  路口附近 edge 太短，无法给足设计入口距离。

short_edge_absorption_candidate
  可能需要在 connector solver 或下一轮 topology repair 中吸收短边。

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
