# LaneForge 道路自动升级系统

LaneForge 是 `road_test_pipeline` 中间处理环节的系统名。

```text
地图原始数据输入
  -> LaneForge 道路自动升级系统
      -> 标准化 / 拓扑修复 / 车道升级 / 路口联动 / 转角优化 / 自动 QA / 版本发布
  -> 标准车道数据包
  -> Houdini 构建管线
```

Houdini 不修路、不判断道路真值，只读取 LaneForge 发布的数据包并构建可见车道、
路口面和调试层。

## 系统边界

- 原始地图数据不可变。
- 人工选择、AI 建议、网页点击、传播规则、转角优化都必须进入版本化记录。
- 浏览器只提交请求或复制命令，不直接改 GeoJSON、lane graph 或 package。
- 每次应用都必须重建、QA、发布新版本包。
- QA 失败时不发布，失败案例应该留作后续规则/casebook。

## 标准车道包

最新包指针：

```text
data/lane_upgrade_packages/<area_id>/latest.json
```

当前样本最新包：

```text
data/lane_upgrade_packages/pattaya_central_500m/lane_package_v0009/
```

核心文件：

```text
manifest.json
houdini_manifest.json
standard_lanes.json
standard_junctions.json
standard_lane_surfaces.geojson
standard_lane_surfaces.obj
lane_debug_geometry.geojson
qa_report.json
lane_graph_report.json
lane_surface_report.json
active_lane_upgrades.json
active_corner_optimizations.json
corner_optimization_candidates.json
corner_optimization_report.json
lane_upgrade_propagation_plan.json
lane_upgrade_propagation_report.json
```

`manifest.json` 是外部系统总入口；Houdini 优先读取 `houdini_manifest.json`。

## 车道升级

网页点击道路或车道后，用户看到：

```text
1车道 / 2车道 / 3车道 / 4车道
```

点击后应该生成 LaneForge 请求，而不是直接修改数据。后端入口：

```powershell
python scripts\execute_lane_upgrade.py --area-id pattaya_central_500m --road-id e_0012 --canonical-road-id cr_0012 --target-lane-count 3 --reason "web menu lane upgrade"
```

执行链路：

```text
execute_lane_upgrade.py
  -> create_lane_upgrade_transaction.py
  -> lane_upgrade_overrides.json
  -> rebuild_road_test.py
  -> lane_model_builder.py
  -> lane graph / junction laneLinks / lane surfaces
  -> audit_road_pipeline.py
  -> build_lane_upgrade_package.py
  -> export_lane_graph_svg.py
```

当前车道分配策略：

```text
balanced_bidirectional_left_traffic_v1

1 physical lane -> shared bidirectional representation
2 physical lanes -> 1 forward + 1 backward
3 physical lanes -> 2 forward + 1 backward
4 physical lanes -> 2 forward + 2 backward
```

当前 active upgrades：

```text
e_0005 / cr_0005 -> 3 lanes
e_0013 / cr_0013 -> 3 lanes
e_0014 / cr_0014 -> 3 lanes
e_0015 / cr_0015 -> 3 lanes
```

## 传播规则

传播规划是 proposal-only，默认不改 active overrides。

```powershell
python scripts\plan_lane_upgrade_propagation.py --area-id pattaya_central_500m
```

当前规则：

```text
through_pair_lane_count_continuity_v2
short_edge_absorption_lane_count_v2
same_class_adjacent_approach_review_v2
adjacent_junction_context_review_v2
```

受控应用策略：

```text
through_pair_only_v1
short_edge_absorption_only_v1
```

示例：

```powershell
python scripts\apply_lane_upgrade_propagation.py --area-id pattaya_central_500m --candidate-id prop_0000 --reason "accepted through-pair propagation"
python scripts\apply_lane_upgrade_propagation.py --area-id pattaya_central_500m --candidate-id prop_0000 --policy short_edge_absorption_only_v1 --reason "accepted controlled short-edge absorption"
```

规则：一次只应用一个 candidate，然后重建、QA、刷新 SVG。

## 转角优化

转角优化属于 LaneForge 主流程，不属于 Houdini，也不是浏览器真值。

位置：

```text
optimized centerlines
  -> corner optimization candidates
  -> active corner overrides
  -> lane graph continuity
  -> lane surfaces
  -> QA
  -> standard lane package
```

规划：

```powershell
python scripts\plan_corner_optimization.py --area-id pattaya_central_500m
```

当前候选：

```text
20 candidates
3 degree2_connector_corner
17 internal_centerline_bend
3 accepted_active
17 candidate_review
```

已完成的受控策略：

```text
low_risk_degree2_connector_only_v1
```

已应用：

```text
corner_0000
corner_0001
corner_0002
```

下一步要新建独立策略：

```text
low_risk_internal_centerline_bend_smoothing_v1
```

不要用 degree-2 connector 的 apply policy 批量处理 internal bends。

## Viewer 合约

`reports/visualizations/svg_live_viewer.html` 的职责：

- 加载 SVG。
- 提供 Raw / Repaired / Canonical / Corners QA 图层。
- 点击道路时显示 LaneForge 车道升级动作。
- 点击转角候选时显示 LaneForge 转角优化动作。
- 复制 JSON 或 CLI 命令。
- 展示技术详情。

它不应该：

- 直接写 active overrides。
- 直接改 GeoJSON。
- 直接改 lane graph。
- 直接发布 package。

## QA 合约

最小发布门禁：

```text
audit_road_pipeline.py status == pass
required outputs exist
lane link references valid
continuity link references valid
lane curves match trimmed lane endpoints
lane surface v1 matches lane graph
junction envelope surfaces have area
```

当前样本 `lane_package_v0009` 已通过这些门禁。

## 推荐下一步

从剩余 `internal_centerline_bend` 中挑一个低风险候选，建立新的
`low_risk_internal_centerline_bend_smoothing_v1` 受控策略：

```text
dry-run -> apply one candidate -> rebuild -> audit -> publish -> SVG/browser review
```

只有浏览器视觉检查和 pipeline audit 都稳定后，再考虑扩大策略范围。
