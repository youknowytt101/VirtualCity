# 道路测试管线

这是 `ProjectManagement/RoadResearch` 下的独立道路研究管线。当前它已经收束为
LaneForge 道路自动升级系统的样本工程。

## 先读

下一个 AI 或开发者按这个顺序看：

```text
AI_START_HERE.md
NEXT_AI_HANDOFF_CURRENT.md
LANEFORGE_LANE_UPGRADE_SYSTEM.md
scripts/README.md
data/lane_upgrade_packages/pattaya_central_500m/latest.json
```

历史设计文档仍有参考价值，但如果与上面文件和最新 JSON 报告冲突，以当前入口文档和
JSON 报告为准。

## 当前心智模型

```text
地图原始数据输入
  -> LaneForge 道路自动升级系统
      -> 标准化 / 修复 / 车道升级 / 路口联动 / 转角优化 / 自动 QA / 版本发布
  -> 标准车道数据包
  -> Houdini 构建管线
```

Houdini 不负责修路，也不负责判断道路真值；Houdini 读取 LaneForge 发布的数据包。
网页/SVG viewer 是 QA 和操作入口，不是 source truth。

## 当前样本

```text
area_id: pattaya_central_500m
latest package: data/lane_upgrade_packages/pattaya_central_500m/lane_package_v0009/
pipeline_audit: pass
```

核心状态：

```text
lanes: 204
junctions: 49
lane_links: 308
continuity_links: 6
junction_envelope_surfaces: 49
active_lane_upgrades: 4
active_corner_optimizations: 3
corner_optimization_candidates: 20
```

## 主命令

重建并发布标准车道包：

```powershell
python scripts\rebuild_road_test.py --area-id pattaya_central_500m --skip-houdini
```

刷新 SVG QA view：

```powershell
python scripts\export_lane_graph_svg.py --area-id pattaya_central_500m
```

网页车道升级菜单对应的后端入口：

```powershell
python scripts\execute_lane_upgrade.py --area-id pattaya_central_500m --road-id e_0012 --canonical-road-id cr_0012 --target-lane-count 3 --reason "web menu lane upgrade"
```

## 重要目录

```text
data/processed/
  当前结构化中间产物：road graph、lane graph、overrides、corner candidates 等。

data/lane_upgrade_system/
  versioned transactions、propagation plans/applications、corner applications。

data/lane_upgrade_packages/<area_id>/lane_package_vXXXX/
  对外发布的标准车道数据包，Houdini 和下游系统优先读这里。

reports/
  stage reports、QA reports、pipeline audit、SVG report。

reports/visualizations/
  svg_live_viewer.html 和导出的 SVG QA view。
```

## 当前网页

```text
http://localhost:8765/svg_live_viewer.html
```

当前 viewer 支持：

- Raw / Repaired / Canonical / Corners 图层。
- 点击道路或车道生成 LaneForge 1/2/3/4 车道升级请求。
- 点击转角候选生成 LaneForge 转角优化请求。
- 固定屏幕尺寸的 marker / hit target，缩放时仍容易点击。
- 简化后的 inspector，技术详情默认折叠。

## 推荐下一步

下一步是新建受控的 `internal_centerline_bend` 平滑策略：

```text
low_risk_internal_centerline_bend_smoothing_v1
```

做法应该是：

```text
plan -> dry-run -> apply one explicit candidate -> rebuild -> audit -> publish -> SVG/browser review
```

不要一次性应用全部内部折角，也不要把结果写进浏览器或 Houdini。

## 验证

常用 focused tests：

```powershell
pytest D:\VirtualCity\tests\test_corner_optimization.py D:\VirtualCity\tests\test_lane_upgrade_system.py D:\VirtualCity\tests\test_lane_model_builder.py D:\VirtualCity\tests\test_lane_surface_v1.py D:\VirtualCity\tests\test_canonical_roads.py
```

当前最近一次已知结果：

```text
25 passed
```

文档变更至少检查：

```powershell
git diff --check
```
