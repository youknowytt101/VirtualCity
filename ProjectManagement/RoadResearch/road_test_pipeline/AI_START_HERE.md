# AI 先读我

这是 `road_test_pipeline` 的当前工程入口文档。下一个 AI 先读本文件，再读
`NEXT_AI_HANDOFF_CURRENT.md` 和 `LANEFORGE_LANE_UPGRADE_SYSTEM.md`。

## 当前主线

用户希望这个中间处理环节统一理解为一套可迭代的道路自动升级系统：

```text
地图原始数据输入
  -> LaneForge 道路自动升级系统
      -> 标准化 / 修复 / 车道升级 / 路口联动 / 转角优化 / 自动 QA / 版本发布
  -> 标准车道数据包
  -> Houdini 构建管线
```

关键边界：

- 浏览器/SVG 只是 QA 与操作入口，不是道路真值。
- Houdini 只消费 LaneForge 发布的数据包，不负责修路或判断拓扑。
- 原始地图数据不可变；所有升级、传播、转角优化都必须走 versioned transaction / application。
- 自动 QA 通过后才发布标准车道包。

## 当前状态

当前样本区域：

```text
area_id: pattaya_central_500m
```

最新标准包：

```text
data/lane_upgrade_packages/pattaya_central_500m/lane_package_v0009/
data/lane_upgrade_packages/pattaya_central_500m/latest.json
```

最新包状态：

```text
pipeline_audit: pass
lanes: 204
junctions: 49
lane_links: 308
continuity_links: 6
junction_envelope_surfaces: 49
active_lane_upgrades: 4
active_corner_optimizations: 3
corner_optimization_candidates: 20
corner_optimization_accepted_active: 3
lane_upgrade_propagation_candidates: 10
lane_upgrade_propagation_high_confidence: 3
```

当前 active lane upgrades：

```text
e_0005 / cr_0005 -> 3 physical lanes
e_0013 / cr_0013 -> 3 physical lanes
e_0014 / cr_0014 -> 3 physical lanes
e_0015 / cr_0015 -> 3 physical lanes
```

当前 active corner optimizations：

```text
corner_0000 -> accepted_active, degree2_connector_corner
corner_0001 -> accepted_active, degree2_connector_corner
corner_0002 -> accepted_active, degree2_connector_corner
```

剩余 17 个 `internal_centerline_bend` 仍是 review 候选，不要用现有
`degree2_connector_corner` 策略批量套用。

## 当前网页

用户当前打开：

```text
http://localhost:8765/svg_live_viewer.html
```

对应文件：

```text
reports/visualizations/svg_live_viewer.html
reports/visualizations/pattaya_central_500m_lane_graph_topology.svg
```

当前交互状态：

- Toolbar 有 `Auto`、`Raw`、`Repaired`、`Canonical`、`Corners`。
- 鼠标光标已经简化为小黑三角。
- 线路、点、转角候选的 hit target 已做固定屏幕尺寸，不随缩放变得不可点。
- Inspector 已简化：常用 LaneForge 动作优先，技术详情折叠。
- 截图参考：
  `reports/visualizations/laneforge_interaction_simplified_v0009.png`

## 主命令

从本目录运行：

```powershell
python scripts\rebuild_road_test.py --area-id pattaya_central_500m --skip-houdini
```

刷新 SVG：

```powershell
python scripts\export_lane_graph_svg.py --area-id pattaya_central_500m
```

发布当前 QA 通过的数据包：

```powershell
python scripts\build_lane_upgrade_package.py --area-id pattaya_central_500m
```

网页 1/2/3/4 车道菜单对应的后端执行入口：

```powershell
python scripts\execute_lane_upgrade.py --area-id pattaya_central_500m --road-id e_0012 --canonical-road-id cr_0012 --target-lane-count 3 --reason "web menu lane upgrade"
```

车道传播规划与受控应用：

```powershell
python scripts\plan_lane_upgrade_propagation.py --area-id pattaya_central_500m
python scripts\apply_lane_upgrade_propagation.py --area-id pattaya_central_500m --candidate-id prop_0000 --reason "accepted through-pair propagation"
python scripts\apply_lane_upgrade_propagation.py --area-id pattaya_central_500m --candidate-id prop_0000 --policy short_edge_absorption_only_v1 --reason "accepted controlled short-edge absorption"
```

转角候选规划与受控应用：

```powershell
python scripts\plan_corner_optimization.py --area-id pattaya_central_500m
python scripts\apply_corner_optimization.py --area-id pattaya_central_500m --candidate-id corner_0001 --reason "accepted low-risk degree2 connector corner"
```

## 推荐下一步

下一步最适合做：

```text
Controlled internal_centerline_bend smoothing policy v1
```

原因：

- 用户指出的道路转角问题已经进入 LaneForge 主流程。
- 3 个低风险 `degree2_connector_corner` 已经受控应用并通过 QA。
- 剩余问题主要是道路内部折角 / 局部折线平滑，属于另一类风险，必须单独建策略。

建议做法：

1. 先读取 `corner_optimization_candidates.json`，筛出低风险 `internal_centerline_bend`。
2. 新增独立 policy，例如 `low_risk_internal_centerline_bend_smoothing_v1`。
3. 先支持 dry-run 和单个 `--candidate-id`。
4. 只应用一个候选，重建、QA、刷新 SVG。
5. 在浏览器里对比该位置是否真的变顺，避免把真实道路形状抹平。

不要做：

- 不要一次性应用全部 internal bends。
- 不要把转角结果直接写进浏览器代码。
- 不要绕过 `rebuild_road_test.py`、`audit_road_pipeline.py` 和标准包发布。

## 必看文件

```text
NEXT_AI_HANDOFF_CURRENT.md
LANEFORGE_LANE_UPGRADE_SYSTEM.md
scripts/README.md
data/lane_upgrade_packages/pattaya_central_500m/latest.json
data/lane_upgrade_packages/pattaya_central_500m/lane_package_v0009/manifest.json
reports/pattaya_central_500m_pipeline_audit_report.json
reports/pattaya_central_500m_corner_optimization_report.json
reports/pattaya_central_500m_lane_upgrade_propagation_report.json
```
