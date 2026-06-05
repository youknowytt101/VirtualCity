# scripts 目录说明

这里的脚本分成三类：主重建入口、LaneForge 事务/规则入口、底层阶段脚本。

## 当前主入口

LaneForge 包发布主入口：

```powershell
python scripts\rebuild_road_test.py --area-id pattaya_central_500m --skip-houdini
```

它会串起：

```text
topology repair
canonical roads
road graph
junction semantics
optimized centerlines
corner optimization planning
lane graph
lane graph QA
preview/debug geometry
lane surface v1
pipeline audit
standard lane package publish
```

只刷新 SVG：

```powershell
python scripts\export_lane_graph_svg.py --area-id pattaya_central_500m
```

旧入口 `repair_road_skeleton.py` 仍保留给早期 structural/Houdini repair
路径。当前 LaneForge 标准包工作优先使用 `rebuild_road_test.py`。

## LaneForge 车道升级脚本

```text
create_lane_upgrade_transaction.py
  创建 versioned lane upgrade transaction，并更新 active lane overrides。

execute_lane_upgrade.py
  网页 1/2/3/4 车道菜单对应的完整执行入口：
  create transaction -> rebuild -> QA -> publish package -> refresh SVG。

plan_lane_upgrade_propagation.py
  proposal-only 传播规划，不修改 active overrides。

apply_lane_upgrade_propagation.py
  受控应用传播候选。当前支持 through_pair_only_v1 和
  short_edge_absorption_only_v1。

build_lane_upgrade_package.py
  发布 versioned standard lane package，供 Houdini 和下游系统读取。
```

## LaneForge 转角优化脚本

```text
plan_corner_optimization.py
  从 optimized centerlines 中生成转角候选。
  当前候选族：degree2_connector_corner、internal_centerline_bend。

apply_corner_optimization.py
  受控应用转角候选。
  当前已实现 policy：low_risk_degree2_connector_only_v1、
  low_risk_internal_centerline_bend_smoothing_v1。
  轻微视觉折线不应强行进入 corner optimization；当前派生
  lane centerline / lane surface 层已实现 derived_lane_centerline_smoothing_v1。
```

## 底层阶段脚本

```text
topology_repair.py
  生成 repaired roads、repair candidates、repair decisions、casebook。

build_canonical_roads.py
  repaired roads -> canonical roads。保留拓扑关键点，做保守几何整理。

build_road_graph.py
  canonical roads -> road graph。

build_junction_semantics.py
  生成 junction approaches、movements、through/turn 语义。

optimize_junction_centerlines.py
  生成 optimized centerlines，并消费 active corner overrides。

lane_model_builder.py
  生成 lane graph、laneLinks、continuity links。
  消费 active lane upgrades 和 optimized corner geometry。

generate_semantic_evidence_summary.py
  汇总每条 road edge 的 OSM lanes、oneway、width source、active lane
  upgrade、最终 geometry lane count 和 review flags。该文件是审查证据，
  不修改 raw / repaired / canonical / road_graph / lane_graph 真值。

generate_lane_geometry_debug.py
  生成 lane/debug curves 与 ribbons。存在 physical_lane_centerlines 时，
  debug 中心线跟随最终干净车道中心线契约。

generate_lane_surface_v1.py
  生成 lane surfaces、turn surfaces、continuity surfaces、junction envelopes。

audit_road_pipeline.py
  发布门禁审计。

run_auto_qa.py
  阶段 QA：topology_repair、road_graph、lane_graph 等。

export_lane_graph_svg.py
  生成 SVG QA view，叠加 movement corridors、compound corridors、
  raw/repaired/canonical roads、corner candidates。
```

## Houdini helper

```text
enable_rpyc_in_houdini.py
houdini_build_road_test.py
houdini_cook_rpyc.py
houdini_cook_open_session.py
```

Houdini 应读取 `lane_package_vXXXX/houdini_manifest.json`，不要从内部临时报告中猜路径。

## 修改后验证

代码变更的常用 focused tests：

```powershell
pytest E:\VirtualCity\tests\test_corner_optimization.py E:\VirtualCity\tests\test_lane_upgrade_system.py E:\VirtualCity\tests\test_lane_model_builder.py E:\VirtualCity\tests\test_lane_surface_v1.py E:\VirtualCity\tests\test_lane_geometry_debug.py E:\VirtualCity\tests\test_laneforge_houdini_contract.py E:\VirtualCity\tests\test_canonical_roads.py
```

改核心管线后重建：

```powershell
python scripts\rebuild_road_test.py --area-id pattaya_central_500m --skip-houdini
python scripts\export_lane_graph_svg.py --area-id pattaya_central_500m
```

改文档后至少运行：

```powershell
git diff --check
```
