# AI 先读我

## 当前目标

这里是独立的道路研究管线，目标是把各种地图 API / GIS 道路数据整理成可复现、可审计、可自我 QA 的 clean road skeleton，并建立 lane graph topology（车道拓扑图拓扑）作为后续车道级路口重建的输入契约。当前阶段不做最终 lane surface（车道路面）、OpenDRIVE（开放道路描述格式）或完整车道面。

## 2026-06-04 交接快照

当前已经形成非破坏式闭环：

```text
road skeleton repair（道路骨架修复）
  -> lane attribute model（车道属性模型）
  -> lane graph topology（车道拓扑图拓扑）
  -> movement corridor candidates（通行走廊候选）
  -> compound junction merge candidates（复合路口合并候选）
```

`L8.1 lane-level movement anchoring（车道级通行锚点）` v1 已完成，并已补上
`planned virtual anchors（规划虚拟锚点）`：

```text
movement corridor solver（通行走廊求解器）已读取 L5.5 entry pose（入口姿态）
并结合 lane lateral offset（车道横向偏移）
生成 lane_entry_anchor / lane_exit_anchor（车道入口 / 出口锚点）。
同时读取 L6.9 short-edge absorption candidates（短边吸收候选），
只对 transaction_ready（事务就绪）候选使用 planned_entry_pose（规划入口姿态）
生成非破坏式 junction-zone expansion planned anchor（路口影响区扩张规划锚点）。
```

`L8.3 compound junction merge planner（复合路口合并规划器）` v1 已完成：

```text
planner（规划器）读取 movement_anchor_gap_audit（通行锚点缺口审计），
只消费 adjacent_junction_short_link（相邻路口短连接） + compound_junction_merge（复合路口合并）记录，
把 24 个 remaining close anchors（剩余偏近锚点）归并成 3 个 low-risk transaction_candidate（低风险事务候选）。
dead_end_stub_capacity_limited（死端短支路退让受限）和
low_value_short_edge_absorption（低收益短边吸收）不会被误合并。
```

`L8.4 compound junction merge transaction（复合路口合并事务）` v1 已完成：

```text
apply_compound_junction_merges.py（复合路口合并事务脚本）不会写回 clean skeleton（干净道路骨架）。
它把 external lane -> bridge lane（外部车道 -> 桥接车道）和
bridge lane -> external lane（桥接车道 -> 外部车道）组合成
external lane -> external lane（外部车道 -> 外部车道）的 staged compound movement corridor（暂存复合通行走廊）。
当前 3 个 transaction_candidate（事务候选）全部 accepted_for_staging（接受为暂存预览），
生成 24 个 compound movement corridor cases（复合通行走廊案例）。
exposed_bridge_edge_cases（暴露桥接短边案例）= 0，
capacity_limited_anchor_cases（退让受限锚点案例）= 0。
```

`L8.5 staged compound movement SVG visualization（暂存复合通行走廊 SVG 可视化）` 已接入：

```text
export_lane_graph_svg.py（车道拓扑图 SVG 导出器）现在会叠加 compound_junction_merge_transactions（复合路口合并事务）。
虚线 corridor（走廊）表示 trial-only compound movement（仅试运行复合通行），不是 final lane geometry（最终车道几何）。
当前默认输出 review_drawing（审图线稿）样式：
  3200px 宽画布
  lane road casing（车道道路底线）
  更小的 entry / exit anchors（入口 / 出口锚点）
  compound trial corridor（复合试运行走廊）高亮
```

当前 SVG 可视化需要看 `movement_corridor_candidates.json（通行走廊候选 JSON）` 和
`compound_junction_merge_transactions.json（复合路口合并事务 JSON）` 叠加后的审图版输出。
旧 lane graph endpoint preview（车道拓扑端点预览）不能用来判断最终路口汇入。

当前还启用了 `temporary_all_roads_bidirectional_two_lane_v1（临时全道路双向两车道策略）`：

```text
所有 road_graph edge（道路图边）统一输出 2 条物理车道。
明确 OSM oneway（OSM 单行）也被覆盖成 bidirectional（双向）。
原始 lanes / width / oneway 只保留为 source_observation（源数据观察值）和 issue（问题标记）。
不要让 source_oneway（源数据单行）在 L5/L7/L8 重新阻断 movement（通行动作）。
```

## 一条命令

从仓库根目录运行：

```powershell
python ProjectManagement/RoadResearch/road_test_pipeline/scripts/repair_road_skeleton.py --area-id pattaya_central_500m --sync-houdini
```

不需要 Houdini 时去掉 `--sync-houdini`。

## 主线阶段

```text
L0 raw source
L3 topology repair
L3 topology repair QA
L3 repair casebook QA
L4 road graph
L4 road graph QA
L5 junction semantics
L5.5 junction area regularization
L6 clean engineering skeleton
L6 junction geometry audit
L6.5 junction connector solver candidates
L6.6 connector replacement transaction
L6.7 post-replacement junction geometry audit
L6.8 connector solver candidates refresh
L6.9 junction-zone expansion planner
L7.0 lane attribute model
L7.1 lane graph topology
L7.1 lane graph QA
L7.2 lane graph SVG visualization
L8.0 movement corridor candidates
L8.0 movement corridor QA
L8.2 movement anchor gap audit
L8.3 compound junction merge planner
L8.3 compound junction merge QA
L8.4 compound junction merge transaction
L8.4 compound junction merge transaction QA
L8.5 staged compound movement SVG visualization
L8.6 movement corridor scoring（通行走廊评分，下一步）
L9 optional Houdini sync
```

当前唯一主入口是 `scripts/repair_road_skeleton.py`。不要从旧 lane / preview 脚本启动当前阶段。

## 设计意图

```text
原始数据不可变。
候选修复不是正式修复。
任何几何修改必须可解释、可复现、可回滚。
高置信候选也必须走事务式 validator。
已知误报必须进入 casebook，成为回归测试。
Houdini 只导入 artifact，不负责修路。
```

## 当前已完成

```text
topology_repair.py
  保守拓扑修复，输出 candidates / decisions / casebook

run_repair_casebook.py
  自动重放已知坏 case，防止修复算法回退

regularize_junction_areas.py
  输出 junction_areas.json 和 engineering_reference_lines.json
  发布 entry poses、movement intents、short-edge absorption candidates

optimize_junction_centerlines.py
  已消费 regularized entry poses
  已把不满足单圆弧条件的 connector 标成 bezier_tangent_fallback

solve_junction_connectors.py
  connector solver v2 候选入口
  对每条 junction connector 生成 current / circular / paramPoly3 Hermite / G1 proxy 候选
  输出评分和是否可替换，不直接改 clean skeleton

apply_connector_replacements.py
  replacement transaction
  只替换 replacement_ready_candidates
  trial audit 不回退才写回 optimized centerlines

plan_short_edge_absorptions.py
  junction-zone expansion planner
  读取 junction_areas.json 里的 short_edge_absorption_candidate
  把 short-edge absorption（短边吸收）视为 junction-zone expansion（路口影响区扩张）候选
  输出可事务化候选，不直接改 graph / clean skeleton

build_lane_attribute_model.py
  lane attribute model
  从 road_graph.json 生成 confidence-tagged lane attributes（带置信度的车道属性）
  当前强制应用 temporary_all_roads_bidirectional_two_lane_v1（临时全道路双向两车道策略）
  专门处理 lanes / width / turn:lanes / oneway 缺失或不规范，不生成 lane geometry

build_lane_graph.py
  lane graph topology（车道拓扑图拓扑）v1
  输出 lane_graph.json（车道拓扑图 JSON）和 lane_graph_report.json（车道拓扑图报告）
  生成 directed lanes（有方向车道）和 lane links（车道连接边）
  这是 structured graph data（结构化拓扑数据），不是图片；图片只能作为 visualization（可视化）
  当前 traffic_direction_policy（交通方向策略）应全部为:
    temporary_bidirectional_two_lane_policy（临时双向两车道策略）
  source_oneway（源数据单行）只允许作为源观察/问题标记出现

export_lane_graph_svg.py
  lane graph SVG visualization（车道拓扑图 SVG 可视化）
  默认输出 reports/visualizations/<area_id>_lane_graph_topology.svg
  如果 movement_corridor_candidates.json 已存在，会优先叠加 lane_entry_anchor / lane_exit_anchor（车道入口 / 出口锚点）
  如果 compound_junction_merge_transactions.json 已存在，会叠加 compound trial corridor（复合试运行走廊）
  当前默认是 review_drawing（审图线稿）模式：3200px 宽画布、lane road casing（车道道路底线）、小锚点和复合走廊高亮
  只给人看图，不是 source truth（源数据真值）

solve_movement_corridors.py
  movement corridor solver（通行走廊求解器）v1
  从 lane_graph（车道拓扑图）生成 movement corridor candidates（通行走廊候选）
  这是 non-destructive staging solver（非破坏式暂存求解器），不改 clean skeleton（干净道路骨架）
  已接入 lane-level entry/exit anchors（车道级入口/出口锚点）
  已消费 transaction_ready short-edge absorption candidates（事务就绪短边吸收候选）生成 planned virtual anchors（规划虚拟锚点）
  当前仍需要 collision（碰撞）和 swept envelope（扫掠包络）评分

audit_movement_anchors.py
  movement anchor gap audit（通行锚点缺口审计）v1
  解释 planned virtual anchors（规划虚拟锚点）之后仍偏近的 anchor（锚点）
  输出 movement_anchor_gap_audit.json（通行锚点缺口审计 JSON）和 movement_anchor_gap_audit_report.json（通行锚点缺口审计报告）
  这是 non-destructive QA（非破坏式质检），不改 clean skeleton（干净道路骨架）

plan_compound_junction_merges.py
  compound junction merge planner（复合路口合并规划器）v1
  读取 movement_anchor_gap_audit.json（通行锚点缺口审计 JSON）、junction_areas.json（路口区域 JSON）和 road_graph.json（道路图 JSON）
  只处理 adjacent_junction_short_link（相邻路口短连接）记录
  输出 compound_junction_merge_candidates.json（复合路口合并候选 JSON）和 compound_junction_merge_report.json（复合路口合并报告）
  当前是 non-destructive planner（非破坏式规划器），不改 road_graph（道路图）或 clean skeleton（干净道路骨架）

apply_compound_junction_merges.py
  compound junction merge transaction（复合路口合并事务）v1
  读取 compound_junction_merge_candidates.json（复合路口合并候选 JSON）、lane_graph.json（车道拓扑图 JSON）、
  engineering_reference_lines.json（工程参考线 JSON）和 short_edge_absorption_candidates.json（短边吸收候选 JSON）
  输出 compound_junction_merge_transactions.json（复合路口合并事务 JSON）和 compound_junction_merge_transaction_report.json（复合路口合并事务报告）
  当前只做 staged preview（暂存预览），不改 clean skeleton（干净道路骨架）

repair_road_skeleton.py
  串起 L3-L8.5、QA、clean skeleton artifact 和可选 Houdini sync
```

## 当前样本状态

`pattaya_central_500m` 当前重点指标：

```text
topology repair QA: pass
repair casebook QA: pass
road graph QA: warn, width_fallback_ratio = 1.0
junction semantics: blocked_movements = 0, source_oneway_blocked_movements_if_trusted = 142
junction area regularization: warn, 28 entry_trim_capacity_limited, 26 short_edge_absorption_candidate
optimized centerlines: 149 regularized entry poses consumed
junction geometry audit: warn, radius_below_design_min = 78
connector replacement: accepted_replacements = 6
connector solver v2 refresh: warn, solver_cases = 85, unresolved_solver_cases = 85, replacement_ready_candidates = 0
junction-zone expansion planner: warn, 26 short-edge flags, 19 transaction_ready, 46 affected unresolved connectors
lane attribute model: warn, active_lane_policy = temporary_all_roads_bidirectional_two_lane_v1, source_oneway_overridden = 134
lane graph topology: warn, lanes = 486, lane_links = 612, lane_link_reference_errors = 0
traffic direction policy: source_oneway_lane_ratio = 0.0, temporary_bidirectional_two_lane_policy_lane_ratio = 1.0
lane graph QA: pass
lane graph SVG: reports/visualizations/pattaya_central_500m_lane_graph_topology.svg, review_drawing, 3200 x 2740
movement corridor solver: warn, corridor_cases = 306, candidate_curves = 918, reference_errors = 0, fully_anchored_case_ratio = 1.0, anchor_fallback_ratio = 0.0, planned_virtual_anchors = 76, planned_virtual_anchor_cases = 72
movement anchor gap audit: warn, remaining_capacity_limited_anchors = 36, unique_remaining_approaches = 9, adjacent_junction_short_link = 24, dead_end_stub_capacity_limited = 8, low_value_short_edge_absorption = 4
compound junction merge planner: warn, eligible_anchor_records = 24, candidates = 3, transaction_candidates = 3, risk_counts.low = 3, ignored dead_end_stub_capacity_limited = 8, ignored low_value_short_edge_absorption = 4
compound junction merge QA: pass, reference_errors = 0, blocked_candidates = 0, affected_anchor_coverage_ratio = 1.0, transaction_candidate_ratio = 1.0
compound junction merge transaction: warn, transactions = 3, accepted_for_staging = 3, compound_movement_corridor_cases = 24, affected_corridor_replacement_ratio = 1.0, exposed_bridge_edge_cases = 0, capacity_limited_anchor_cases = 0
compound junction merge transaction QA: pass, reference_errors = 0, exposed_bridge_edge_cases = 0, capacity_limited_anchor_cases = 0, accepted_transaction_ratio = 1.0, affected_corridor_replacement_ratio = 1.0
lane graph SVG compound overlay: pass, compound_corridors_rendered = 24, compound_anchor_markers_rendered = 48, visual_mode = review_drawing（审图线稿）
movement corridor QA: warn, low_confidence_ratio = 1.0, ready_ratio = 0.0
```

`width_fallback_ratio` 是源数据缺少宽度；`radius_below_design_min` 和 `bezier_tangent_fallback` 是下一阶段 connector solver 的靶子，不应该在 Houdini 里硬改。
后续目标是 lane-level junction reconstruction（车道级路口重建）；arc（圆弧）只是候选曲线族之一。

## 下一步

当前 replacement transaction（替换事务）、lane-level movement anchoring（车道级通行锚点）v1、
movement anchor gap audit（通行锚点缺口审计）v1、compound junction merge planner（复合路口合并规划器）v1
和 compound junction merge transaction（复合路口合并事务）v1 已经闭环。
锚点版 SVG 已经会把 19 个 transaction_ready short-edge absorption（事务就绪短边吸收）候选显示成
planned virtual anchors（规划虚拟锚点）。
剩余 36 个偏近锚点已经归类：24 个是 adjacent_junction_short_link（相邻路口短连接），
8 个是 dead_end_stub_capacity_limited（死端短支路退让受限），4 个是 low_value_short_edge_absorption（低收益短边吸收）。
其中 24 个 adjacent_junction_short_link（相邻路口短连接）已经被 L8.3 收敛为 3 个
low-risk transaction_candidate（低风险事务候选），并由 L8.4 生成 24 个 staged compound movement corridor
（暂存复合通行走廊）。
下一步不要先硬调圆弧，也不要写回 clean skeleton（干净道路骨架）。
直接进入 `L8.6 movement corridor scoring（通行走廊评分）`：基于 L8.5 审图版 SVG 复核暂存复合走廊，
然后实现 collision（碰撞）/ swept envelope（扫掠包络）/ curvature（曲率）评分：

```text
输入:
  junction_connector_candidates.json
  junction_connector_solver_report.json
  junction_connector_replacement_report.json
  short_edge_absorption_candidates.json
  short_edge_absorption_report.json
  lane_attribute_model.json
  lane_attribute_model_report.json
  lane_graph.json
  movement_corridor_candidates.json
  movement_corridor_report.json
  movement_anchor_gap_audit.json
  movement_anchor_gap_audit_report.json
  compound_junction_merge_candidates.json
  compound_junction_merge_report.json
  reports/qa/pattaya_central_500m_compound_junction_merge_qa_report.json
  compound_junction_merge_transactions.json
  compound_junction_merge_transaction_report.json
  reports/qa/pattaya_central_500m_compound_junction_merge_transaction_qa_report.json

动作:
  先消费 movement corridor candidates（通行走廊候选）和 confidence-tagged lane attributes（带置信度的车道属性）
  用 compound_junction_merge_transactions（复合路口合并事务）里的 staged compound movement corridors（暂存复合通行走廊）做碰撞/扫掠评分
  继续降低 corridor_too_short（走廊过短）和 radius_proxy_below_lane_min（半径代理低于车道最小值）
  不要把 best_candidate_family（最佳候选曲线族）当发布选择；当前只是 preview score（预览评分）
  保留 traffic_direction_policy（交通方向策略），不要把 temporary_bidirectional_two_lane_policy（临时双向两车道策略）误当 source truth（源数据真值）
  只挑 transaction_ready 的 junction-zone expansion candidates
  做 destructive transaction（写入式事务） + audit rollback（审计回滚）
  clothoid / true paramPoly3 fitting
  collision / swept-envelope scoring
  replacement transaction（替换事务） + audit rollback（审计回滚）
```

不要直接把所有最高分候选写回 clean skeleton。任何替换仍然必须过 transaction + QA。

## 必读顺序

```text
AI_START_HERE.md
CURRENT_STAGE_SNAPSHOT.md
README.md
NEXT_AI_HANDOFF.md
ROAD_REPAIR_STAGE_ARCHITECTURE.md
LANE_LEVEL_JUNCTION_RECONSTRUCTION_PLAN.md
scripts/README.md
data/README.md
reports/README.md
```
