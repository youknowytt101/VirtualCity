# 当前阶段快照

更新时间：2026-06-04

## 一句话

当前管线已经完成 `road skeleton repair（道路骨架修复） -> lane attribute model（车道属性模型） -> lane graph topology（车道拓扑图拓扑） -> movement corridor candidates（通行走廊候选）` 的非破坏式闭环。

后续目标不是继续把 `arc（圆弧）` 调漂亮，而是还原真实世界的 `lane-level junction（车道级路口）`。`arc（圆弧）` 只是候选曲线族之一。

最新补充：`compound junction merge planner（复合路口合并规划器）` v1 和
`compound junction merge transaction（复合路口合并事务）` v1 已落地。
当前把 `adjacent_junction_short_link（相邻路口短连接）` 先归并为事务候选，再生成
`staged compound movement corridors（暂存复合通行走廊）`；仍不改 `clean skeleton（干净道路骨架）`。

## 当前主入口

从仓库根目录运行：

```powershell
python ProjectManagement/RoadResearch/road_test_pipeline/scripts/repair_road_skeleton.py --area-id pattaya_central_500m
```

需要同步 Houdini（胡迪尼）时加：

```powershell
--sync-houdini
```

最近一次 summary（摘要）显示：

```text
stage: road_skeleton_repair
status: completed
houdini_status: skipped
traffic_side: left
next_stage: use movement_anchor_gap_audit（通行锚点缺口审计） to design compound junction merge（复合路口合并） cases, then add collision（碰撞） / swept-envelope（扫掠包络） scoring
```

最新 next_stage（下一阶段）应理解为：

```text
L8.5 review_drawing SVG（审图线稿 SVG）已完成。
下一步是 L8.6 movement corridor scoring（通行走廊评分）：
对 staged compound movement corridors（暂存复合通行走廊）计算
collision（碰撞） / swept-envelope（扫掠包络） / curvature（曲率）评分，
再考虑 destructive writeback（写入式回写）。
```

## 已完成到哪里

```text
L3 topology repair（拓扑修复）: pass
L3 repair casebook QA（修复案例回归质量门禁）: pass
L4 road graph（道路拓扑图）: warn，原因是 width_fallback_ratio = 1.0
L5 junction semantics（路口语义）: 已启用 temporary_all_roads_bidirectional_two_lane_v1（临时全道路双向两车道策略），blocked_movements = 0；如果信任源单行会阻断 142 个 movement
L5.5 junction area regularization（路口区域正规化）: warn，28 个 entry_trim_capacity_limited，26 个 short_edge_absorption_candidate
L6 clean engineering skeleton（干净工程骨架）: 已生成，149 个 regularized entry poses 已消费
L6 connector replacement transaction（连接线替换事务）: 已安全接受 6 个替换
L6.9 junction-zone expansion planner（路口影响区扩张规划器）: 26 个短边候选，19 个 transaction_ready
L7.0 lane attribute model（车道属性模型）: warn，243 条边全部强制为双向 2 车道；134 条源单行被策略覆盖；turn:lanes 全缺失
L7.1 lane graph topology（车道拓扑图拓扑）: warn，486 条 directed lanes，612 条 lane links，reference error = 0，QA pass；temporary_bidirectional_two_lane_policy_lane_ratio = 1.0
L7.2 lane graph SVG visualization（车道拓扑图 SVG 可视化）: 已输出，当前默认 review_drawing（审图线稿）样式
L8.0 movement corridor solver（通行走廊求解器）: warn，306 个 corridor cases，918 条 candidate curves，fully_anchored_case_ratio = 1.0，anchor_fallback_ratio = 0.0，planned_virtual_anchors = 76，planned_virtual_anchor_cases = 72，ready_ratio = 0.0；不再有 pose_cannot_enter / pose_cannot_exit 残留
L8.1 anchored SVG visualization（锚点版 SVG 可视化）: 已接入 movement corridor anchors（通行走廊锚点）和 planned virtual anchors（规划虚拟锚点）
L8.2 movement anchor gap audit（通行锚点缺口审计）: warn，remaining_capacity_limited_anchors = 36，unique_remaining_approaches = 9；24 个 adjacent_junction_short_link（相邻路口短连接），8 个 dead_end_stub_capacity_limited（死端短支路退让受限），4 个 low_value_short_edge_absorption（低收益短边吸收）
L8.3 compound junction merge planner（复合路口合并规划器）: warn，eligible_anchor_records = 24，eligible_bridge_edges = 3，candidates = 3，transaction_candidates = 3，risk_counts.low = 3；8 个 dead_end_stub_capacity_limited（死端短支路退让受限）和 4 个 low_value_short_edge_absorption（低收益短边吸收）被正确忽略
L8.3 compound junction merge QA（复合路口合并质量门禁）: pass，reference_errors = 0，blocked_candidates = 0，affected_anchor_coverage_ratio = 1.0，transaction_candidate_ratio = 1.0
L8.4 compound junction merge transaction（复合路口合并事务）: warn，transactions = 3，accepted_for_staging = 3，compound_movement_corridor_cases = 24，affected_corridor_replacement_ratio = 1.0，exposed_bridge_edge_cases = 0，capacity_limited_anchor_cases = 0
L8.4 compound junction merge transaction QA（复合路口合并事务质量门禁）: pass，reference_errors = 0，exposed_bridge_edge_cases = 0，capacity_limited_anchor_cases = 0，accepted_transaction_ratio = 1.0，affected_corridor_replacement_ratio = 1.0
L8.5 staged compound movement SVG visualization（暂存复合通行走廊 SVG 可视化）: pass，review_drawing = 3200 x 2740，compound_corridors_rendered = 24，compound_anchor_markers_rendered = 48
```

## 当前临时车道策略

```text
temporary_all_roads_bidirectional_two_lane_v1（临时全道路双向两车道策略）
  所有 road_graph edge（道路图边）统一生成 2 条物理车道
  每条边都允许 forward / backward（正向 / 反向）通行
  明确 OSM oneway（OSM 单行）也被覆盖，不再阻断路口 movement（通行动作）
  原始 lanes / width / oneway 仍保留在 source_observation（源数据观察值）和 issue（问题标记）中
```

这个策略是为了在 OSM 车道/转向/方向数据严重缺失时先得到稳定、对称、可 QA 的 lane graph（车道拓扑图）。
后续升级真实车道时，必须从 source_observation（源数据观察值）、现场规则和更高质量地图源重新恢复方向与车道数。

## 当前最容易误判的点

`reports/visualizations/pattaya_central_500m_lane_graph_topology.svg` 只是 `human QA visualization（人工质检可视化）`，不是 `source truth（源数据真值）`，也不是最终车道几何。当前 exporter（导出器）会在 `movement_corridor_candidates.json（通行走廊候选 JSON）` 存在时叠加锚点版 corridor preview（通行走廊预览），在 `compound_junction_merge_transactions.json（复合路口合并事务 JSON）` 存在时叠加 compound trial corridor（复合试运行走廊）。

当前 SVG 已经升级为 `review_drawing（审图线稿）`：

```text
svg_width_px = 3200
svg_height_px = 2740
lane_casing = enabled（车道道路底线已启用）
anchor_marker_radius_px = 0.55
compound_corridors_rendered = 24
```

如果在 SVG 里看到车道级连接的终点落在 3 车道或 4 车道整体中轴附近，这不是最终正确状态，而是当前 L7/L8 预览阶段的临时状态。原因是：

```text
lane_graph.centerline_xz
  只是 approximate offset preview（近似偏移预览）

solve_movement_corridors.py
  已把 L5.5 的 entry pose（入口姿态）提升成 lane-level entry/exit anchor（车道级入口/出口锚点）
  已在 junction boundary（路口边界）上按 lane lateral offset（车道横向偏移）重算锚点
  已读取 L6.9 transaction_ready short-edge absorption candidates（事务就绪短边吸收候选）
  并把 planned_entry_pose（规划入口姿态）作为非破坏式 planned virtual anchor（规划虚拟锚点）显示
  尚未做 collision（碰撞）/ swept envelope（扫掠包络）评分

turn:lanes（分车道转向）
  当前源数据缺失率为 1.0
  lane links 只能通过 lane rank（车道顺序）和 road movement（道路通行动作）低置信推断
```

所以不要手工调整 SVG，也不要把这些预览终点当成真实路口设计。当前如果仍看到少量起点/终点偏近，优先检查对应 anchor（锚点）的 `source`：
`junction_zone_expansion_planned_pose_lateral_offset（路口影响区扩张规划姿态横向偏移）` 已经是短边规划预览；
仍为 `engineering_entry_pose_lateral_offset（工程入口姿态横向偏移）` 且带 `entry_trim_capacity_limited（入口退让距离受限）`
的 case 现在已经由 `movement_anchor_gap_audit.json（通行锚点缺口审计 JSON）` 分类。
其中大头不是短边吸收问题，而是相邻路口短连接，需要 compound junction merge（复合路口合并）策略。
之后再进入 collision（碰撞）/ swept envelope（扫掠包络）评分。

## 下一步第一优先级

先做 `L8.6 movement corridor scoring（通行走廊评分）`，并把
`compound_junction_merge_transactions（复合路口合并事务）` 作为重点输入：

```text
输入:
  data/processed/pattaya_central_500m_compound_junction_merge_transactions.json
  reports/pattaya_central_500m_compound_junction_merge_transaction_report.json
  reports/qa/pattaya_central_500m_compound_junction_merge_transaction_qa_report.json
  reports/visualizations/pattaya_central_500m_lane_graph_topology.svg
  data/processed/pattaya_central_500m_compound_junction_merge_candidates.json
  reports/pattaya_central_500m_compound_junction_merge_report.json
  data/processed/pattaya_central_500m_movement_anchor_gap_audit.json
  data/processed/pattaya_central_500m_junction_areas.json
  data/processed/pattaya_central_500m_road_graph.json
  data/processed/pattaya_central_500m_movement_corridor_candidates.json

目标:
  先看 L8.5 SVG 里的 dashed compound trial corridor（虚线复合试运行走廊）
  对 24 个 staged compound movement corridor（暂存复合通行走廊）计算 collision_score（碰撞评分）、
  swept_envelope_score（扫掠包络评分）和 curvature_score（曲率评分）
  只有评分稳定后，才考虑 destructive writeback（写入式回写）
  不碰 dead_end_stub_capacity_limited（死端短支路退让受限）
  不把 low_value_short_edge_absorption（低收益短边吸收）强行升级成 transaction_ready（事务就绪）
```

## 下一步第二优先级

做 `collision / swept-envelope scoring（碰撞 / 扫掠包络评分）`：

```text
输入:
  data/processed/pattaya_central_500m_lane_graph.json
  data/processed/pattaya_central_500m_engineering_reference_lines.json
  data/processed/pattaya_central_500m_junction_areas.json
  data/processed/pattaya_central_500m_movement_corridor_candidates.json
  reports/visualizations/pattaya_central_500m_lane_graph_topology.svg

目标:
  检查 corridor candidate（通行走廊候选）是否侵占非目标车道
  检查 swept envelope（扫掠包络）是否与道路/路口冲突
  检查 curvature / radius（曲率 / 半径）是否可发布
  把 best_candidate_family（最佳候选曲线族）从 preview score（预览评分）升级成可审计评分
```

建议最小实现：

```text
1. 保留当前 lane_entry_anchor / lane_exit_anchor（车道入口 / 出口锚点）作为端点契约。
2. 对每条 candidate curve（候选曲线）构建 lane-width buffer（车道宽度缓冲）或 swept envelope（扫掠包络）。
3. 与非目标 lane centerline / road edge 做冲突检测。
4. 把 collision_score（碰撞评分）、swept_envelope_score（扫掠包络评分）、curvature_score（曲率评分）写回 candidates。
5. 只有这些评分存在后，best_candidate_family（最佳候选曲线族）才允许变成发布候选。
```

## 下一步第三优先级

做 `junction-zone expansion transaction（路口影响区扩张事务）`：

```text
只消费 short_edge_absorption_candidates.json 里的 transaction_ready（事务就绪）候选。
先做 trial apply（试运行应用）。
重建 engineering_reference_lines（工程参考线）和 optimized_centerlines（工程中心线）。
重跑 connector solver（连接线求解器）、replacement transaction（替换事务）和 junction_geometry_audit（路口几何审计）。
保护指标回退就 rollback（回滚）。
```

只有 scoring（评分）稳定后，再进入 `destructive junction-zone expansion transaction（写入式路口影响区扩张事务）`。

## 后续事务规则

只对 `short_edge_absorption_candidates.json` 里的 `transaction_ready` 候选做写入式事务：

```text
transaction_ready: 19
affected_unresolved_connectors: 46
```

事务必须：

```text
trial apply（试运行应用）
regenerate engineering_reference_lines（重建工程参考线）
regenerate optimized_centerlines（重建工程中心线）
rerun connector solver（重跑路口连接求解器）
rerun replacement transaction（重跑替换事务）
rerun junction_geometry_audit（重跑路口几何审计）
rollback on protected regression（保护指标回退则回滚）
```

## 不要做

```text
不要在 Houdini（胡迪尼）里修路。
不要把 SVG visualization（SVG 可视化）当 source truth（源数据真值）。
不要把 temporary_bidirectional_two_lane_policy（临时双向两车道策略）当成真实道路方向。
不要重新让 OSM oneway（OSM 单行）直接阻断 L5/L7/L8，除非先引入可审计的方向恢复策略。
不要因为 OSM 缺 turn:lanes（分车道转向）就发布高置信 lane links。
不要批量写回最高分 corridor candidate（通行走廊候选）。
不要为了消除 radius warning（半径警告）硬塞小圆弧。
```

## 必读顺序

```text
AI_START_HERE.md
CURRENT_STAGE_SNAPSHOT.md
NEXT_AI_HANDOFF.md
README.md
LANE_LEVEL_JUNCTION_RECONSTRUCTION_PLAN.md
ROAD_REPAIR_STAGE_ARCHITECTURE.md
scripts/README.md
data/README.md
reports/README.md
```
