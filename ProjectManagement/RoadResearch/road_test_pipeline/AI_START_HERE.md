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
data/lane_upgrade_packages/pattaya_central_500m/lane_package_v0026/
data/lane_upgrade_packages/pattaya_central_500m/latest.json
```

最新包状态：

```text
pipeline_audit: pass
qa_gate_status: manual_review_required
qa_warning_summary: publishable_warn=0, manual_review_required=3, blocker=0
path_policy: portable_lane_package_paths_v1
lanes: 200
junctions: 49
lane_links: 306
continuity_links: 20
micro_seam_continuity_links: 12
surface_continuity_links: 8
direct_connector_continuity_links: 14
junction_envelope_surfaces: 49
active_lane_upgrades: 4
active_lane_upgrades_applied: 0
active_lane_upgrades_deferred: 4
active_corner_optimizations: 4
corner_optimization_candidates: 19
corner_optimization_accepted_active: 4
corner_optimization_accepted_active_candidates: 3
corner_optimization_accepted_active_overrides: 4
lane_upgrade_propagation_candidates: 10
lane_upgrade_propagation_high_confidence: 3
```

当前 active lane upgrades（事务记录仍保留，但几何输出暂时全部 defer）：

```text
e_0005 / cr_0005 -> 3 physical lanes
e_0013 / cr_0013 -> 3 physical lanes
e_0014 / cr_0014 -> 3 physical lanes
e_0015 / cr_0015 -> 3 physical lanes
```

当前 lane graph 几何输出遵守临时策略：

```text
defer_lane_upgrade_overrides_keep_all_roads_bidirectional_two_lane_v1
100 roads -> 200 lanes
```

当前 active corner optimizations：

```text
corner_0000 -> accepted_active, degree2_connector_corner
corner_0001 -> accepted_active, degree2_connector_corner
corner_0002 -> accepted_active, degree2_connector_corner
corner_0003 -> accepted_for_geometry_apply, internal_centerline_bend, e_0017 / cr_0017 point_index=1
```

`corner_0003` 已通过独立的
`low_risk_internal_centerline_bend_smoothing_v1` 策略应用。当前候选列表
不再复用 `corner_0003` 这个已占用事务 ID；新的 `e_0017` 后续待审折弯从
`corner_0004` 开始。

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
- 左上角品牌为 `LaneForge（道路升级系统）`，关键英文 UI 后面已加中文注释。
- 鼠标光标已经简化为小黑三角。
- 线路、点、转角候选的 hit target 已做固定屏幕尺寸，不随缩放变得不可点。
- Inspector 已改成页面右侧长条状面板；常用 LaneForge 动作优先，技术详情折叠。

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
road_semantics_rule_inputs_v1
```

原因：

- `derived_lane_centerline_smoothing_v1` 已完成，派生车道中心线平滑不改
  `raw` / `repaired` / `canonical` / `road_graph` 真值。
- Houdini cook 已改为 manifest-driven，只读最新 LaneForge package。
- `lane_package_v0026` 已采用 `portable_lane_package_paths_v1`，package JSON
  和 latest pointer 不再写入盘符绝对路径。
- `degree2_connector_through_continuity_v1` 已补上近直线 degree-2 connector
  的显式车道连续关系，例如 `e_0082_f_1 -> e_0078_f_1`。
- `derived_lane_centerline_smoothing_v1` 已覆盖短连接段硬折角，例如
  `e_0079_f_1 / e_0079_b_1`，不改 truth layers。
- `degree2_connector_micro_seam_endpoint_snap_v1` 已吸收 degree-2 through
  connector 的厘米级微缝，例如 `n_0069_through_cl_01_00`，保留拓扑连续
  link，但不再生成可见小桥 surface/SVG。
- `qa_warning_severity_tiers_v1` 已完成，当前 package 标记
  `manual_review_required`，原因是 dangling endpoint、dead end 和 width fallback。
- 下一阶段要把 `oneway`、`width`、`lanes`、`turn:lanes` 从观察值/临时策略
  提升为可审计的规则输入。

建议做法：

1. 保持当前临时双向双车道输出，不直接重新启用 active lane upgrade 几何。
2. 建立 road semantics rule input 层，显式记录 `oneway`、`width`、`lanes`、
   `turn:lanes` 的来源、置信度和 fallback 原因。
3. 先让规则进入报告/manifest，不急着改变 lane count 或交通组织几何。
4. 把 `width_fallback_ratio=1.0` 这类 manual review 项指向可改进的规则输入。
5. 保持 Houdini 只读 package manifest，不让语义推断绕过标准包边界。

不要做：

- 不要把所有轻微折线都塞进 `corner_optimization`。
- 不要直接修改 `raw` / `repaired` / `canonical` / `road_graph` 真值。
- 不要把转角结果直接写进浏览器代码。
- 不要绕过 `rebuild_road_test.py`、`audit_road_pipeline.py` 和标准包发布。
- 不要在 package/latest JSON 里重新写入 `E:\` / `D:\` 这类盘符路径。

## 必看文件

```text
NEXT_AI_HANDOFF_CURRENT.md
LANEFORGE_LANE_UPGRADE_SYSTEM.md
scripts/README.md
data/lane_upgrade_packages/pattaya_central_500m/latest.json
data/lane_upgrade_packages/pattaya_central_500m/lane_package_v0026/manifest.json
reports/pattaya_central_500m_pipeline_audit_report.json
reports/pattaya_central_500m_corner_optimization_report.json
reports/pattaya_central_500m_lane_upgrade_propagation_report.json
```

可选复盘：

```text
AI点评.md
```

`AI点评.md` 是工程状态评审和风险评分，不是 source truth；真实状态仍以最新 JSON 报告和 package manifest 为准。
