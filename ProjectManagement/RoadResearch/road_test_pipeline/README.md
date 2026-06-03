# 道路测试管线

这个目录是 `ProjectManagement/RoadResearch` 下的独立道路研究管线。它不读写 VirtualCity
主管线的 `RawData/`、`Scripts/`、`Config/`、`Reports/`、`Houdini/` 目录。

## 先读

下一个 AI 或开发者优先按这个顺序看：

```text
AI_START_HERE.md
NEXT_AI_HANDOFF.md
scripts/README.md
data/README.md
reports/README.md
ROAD_REPAIR_STAGE_ARCHITECTURE.md
```

## 当前目标

当前目标不是生成最终车道或 OpenDRIVE，而是先把地图 API 的脏道路数据修成稳定、可审计、
可迭代的道路骨架：

```text
原始地图数据
  -> 道路修复 / Houdini 前置工程处理
  -> road graph
  -> junction semantics
  -> junction area regularization
  -> clean single-line skeleton
  -> Houdini 只负责可视化和后续构建
```

Houdini 不负责修复道路拓扑，也不发明数据真值。

## 主入口

从仓库根目录运行：

```powershell
uv --cache-dir E:\VirtualCity\Scripts\.uv-cache run python ProjectManagement/RoadResearch/road_test_pipeline/scripts/repair_road_skeleton.py --area-id pattaya_central_500m --sync-houdini
```

如果不用 `uv`，当前环境也可以直接：

```powershell
python ProjectManagement/RoadResearch/road_test_pipeline/scripts/repair_road_skeleton.py --area-id pattaya_central_500m --sync-houdini
```

## 当前阶段顺序

```text
L3 topology repair
L3 topology repair QA
L3 repair casebook QA
L4 road graph
L4 road graph QA
L5 junction semantics
L5.5 junction area regularization
L6 engineering centerline, consumes regularized entry poses
L6 junction geometry audit
L6 clean skeleton artifact
L9 optional Houdini sync
```

## Houdini 节点视图

`--sync-houdini` 会重建 `/obj/road_test_<area_id>`。节点从左到右是阶段列：

```text
原始数据线
  python_import_raw_roads
  OUT_raw_road_lines

道路拓扑修复线
  python_import_repaired_roads
  OUT_repaired_road_lines

干净单线工程骨架
  python_import_clean_road_skeleton
  OUT_clean_road_skeleton

L6 debug 分支
  python_filter_junction_connector_arcs
  OUT_junction_connector_arcs
  python_filter_corner_fillet_arcs
  OUT_corner_fillet_arcs
```

主线是 `raw -> repaired topology -> clean single-line skeleton`。路口 connector arcs 和
corner fillets 是 clean skeleton 的 debug 分支，不是新的数据真值层。

## 核心产物

```text
data/processed/<area_id>_roads_raw.geojson
data/processed/<area_id>_roads_repaired.geojson
data/processed/<area_id>_repair_candidates.json
data/processed/<area_id>_repair_decisions.json
data/processed/<area_id>_repair_casebook.json
data/processed/<area_id>_road_graph.json
data/processed/<area_id>_junction_semantics.json
data/processed/<area_id>_junction_areas.json
data/processed/<area_id>_engineering_reference_lines.json
data/processed/<area_id>_roads_optimized_centerlines.geojson
data/processed/<area_id>_roads_clean_skeleton.geojson
```

## 核心报告

```text
reports/<area_id>_repair_report.json
reports/qa/<area_id>_topology_repair_qa_report.json
reports/qa/<area_id>_repair_casebook_qa_report.json
reports/<area_id>_road_graph_report.json
reports/qa/<area_id>_road_graph_qa_report.json
reports/<area_id>_junction_semantics_report.json
reports/<area_id>_junction_area_regularization_report.json
reports/<area_id>_optimized_centerlines_report.json
reports/<area_id>_junction_geometry_audit_report.json
reports/<area_id>_road_skeleton_repair_report.json
reports/<area_id>_road_skeleton_repair_summary.json
reports/<area_id>_houdini_raw_road_preview_report.json
reports/<area_id>_houdini_clean_skeleton_report.json
```

## 当前主线脚本

```text
scripts/repair_road_skeleton.py          # 当前唯一主入口
scripts/topology_repair.py               # 保守拓扑修复 + candidates/decisions/casebook
scripts/run_repair_casebook.py           # 已知误报/拒绝案例回归测试
scripts/build_road_graph.py
scripts/build_junction_semantics.py
scripts/regularize_junction_areas.py     # 路口区域正规化，输出 entry poses / movement intents
scripts/optimize_junction_centerlines.py # 当前 clean skeleton 生成器，消费 regularized entry poses
scripts/junction_geometry_audit.py
scripts/run_auto_qa.py
```

Houdini 相关 helper：

```text
scripts/enable_rpyc_in_houdini.py
scripts/houdini_build_road_test.py
scripts/houdini_cook_rpyc.py
```

旧 lane / preview / rebuild 脚本暂时保留给未来 lane/OpenDRIVE 阶段，但不是当前入口：

```text
scripts/rebuild_road_test.py
scripts/lane_model_builder.py
scripts/generate_lane_geometry_debug.py
scripts/generate_lane_surface_v1.py
scripts/generate_road_preview.py
scripts/audit_road_pipeline.py
```

## 设计文档

优先阅读：

```text
NEXT_AI_HANDOFF.md
ROAD_REPAIR_STAGE_ARCHITECTURE.md
LAYERED_PIPELINE_INITIAL_PLAN.md
```

`HANDOFF_DESIGN.md` 是较早的交接设计，仍可参考，但当前进度以本 README 和
`NEXT_AI_HANDOFF.md` 为准。

## 当前已知状态

`pattaya_central_500m` 当前样本：

```text
topology repair QA: pass
repair casebook QA: pass
road graph QA: warn, width_fallback_ratio = 1.0
junction area regularization: warn, entry_trim_capacity_limited = 34, short_edge_absorption_candidate = 22
optimized centerlines: 149 regularized entry poses consumed, 91 bezier_tangent_fallback connectors
junction geometry audit: warn, radius_below_design_min = 90, junction_trim_spread_excess = 24
```

这些 warning 不是 Houdini 布局问题。`width_fallback_ratio` 说明 OSM 宽度缺失；`radius_below_design_min`
和 `bezier_tangent_fallback` 说明当前 connector solver 还停留在圆弧 + 切线 Bezier 占位阶段。
下一步应该做 circular / clothoid / paramPoly3 候选求解和评分。
