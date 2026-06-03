# scripts 目录说明

## 当前主线入口

```text
repair_road_skeleton.py
```

它负责串起当前道路修复主线。除非明确开发某个阶段，否则优先从这个入口运行。

## 主线阶段脚本

```text
topology_repair.py
  L3 拓扑修复。生成 repaired roads、repair candidates、repair decisions、repair casebook。

run_repair_casebook.py
  L3 回归入口。重放已知误报和被拒绝的高置信候选。

run_auto_qa.py
  L3 / L4 通用 QA gate。

build_road_graph.py
  L4 把 repaired roads 转成 node / edge road graph。

build_junction_semantics.py
  L5 识别 junction approaches、movements、through / turn 语义。

regularize_junction_areas.py
  L5.5 生成 junction conflict zone、entry poses、movement intents。

optimize_junction_centerlines.py
  L6 生成 clean engineering skeleton。当前已消费 regularized entry poses。

junction_geometry_audit.py
  L6 工程几何 QA。重点看 radius、trim spread、endpoint distance。

solve_junction_connectors.py
  L6.5 connector solver v2 候选入口。生成 current / circular / paramPoly3 Hermite / G1 proxy 候选并评分。
  只写 candidate/report，不直接替换 clean skeleton。

apply_connector_replacements.py
  L6.6 replacement transaction。只应用 replacement_ready_candidates，并用 junction_geometry_audit 做 trial QA。
  指标不回退才写回 optimized centerlines。
```

## Houdini helper

```text
enable_rpyc_in_houdini.py
houdini_build_road_test.py
houdini_cook_rpyc.py
houdini_cook_open_session.py
```

当前 `--sync-houdini` 走 `repair_road_skeleton.py` 内的远程同步代码，负责创建三阶段节点列。

## 暂存的下游研究脚本

```text
rebuild_road_test.py
lane_model_builder.py
generate_lane_geometry_debug.py
generate_lane_surface_v1.py
generate_road_preview.py
audit_road_pipeline.py
```

这些脚本保留给未来 lane graph、lane surface、OpenDRIVE 阶段。它们不是当前 clean skeleton 阶段的入口。

## 修改规则

```text
修 topology_repair.py 后必须跑 run_repair_casebook.py。
修 regularize_junction_areas.py 后必须重跑 optimize_junction_centerlines.py 和 junction_geometry_audit.py。
修 optimize_junction_centerlines.py 后必须看 optimized_centerlines_report 和 junction_geometry_audit_report。
修 solve_junction_connectors.py 后必须看 junction_connector_solver_report，确认 replacement_ready 与 unresolved case。
修 apply_connector_replacements.py 后必须看 junction_connector_replacement_report 和替换后的 junction_geometry_audit_report。
修 Houdini 同步后必须确认 OUT_raw_road_lines、OUT_repaired_road_lines、OUT_clean_road_skeleton 的列顺序。
```
