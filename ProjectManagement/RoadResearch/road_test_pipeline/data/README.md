# data 目录说明

## raw

`raw/` 保存原始下载或 API 返回数据。原则上只追加，不手工修。

当前样本：

```text
raw/pattaya_central_500m_roads.osm
raw/pattaya_central_500m.overpassql
```

## processed

`processed/` 保存每个阶段的机器可读 artifact。它们可以由脚本重建，不要把它们当手工编辑源。

当前主线产物：

```text
pattaya_central_500m_roads_raw.geojson
pattaya_central_500m_roads_repaired.geojson
pattaya_central_500m_repair_candidates.json
pattaya_central_500m_repair_decisions.json
pattaya_central_500m_repair_casebook.json
pattaya_central_500m_road_graph.json
pattaya_central_500m_junction_semantics.json
pattaya_central_500m_junction_areas.json
pattaya_central_500m_engineering_reference_lines.json
pattaya_central_500m_roads_optimized_centerlines.geojson
pattaya_central_500m_junction_connector_candidates.json
pattaya_central_500m_roads_clean_skeleton.geojson
pattaya_central_500m_junction_movements_debug.geojson
```

## 数据边界

```text
roads_raw.geojson
  canonical raw road lines, 不承载拓扑修复结果。

roads_repaired.geojson
  L3 之后的保守拓扑修复结果。

junction_areas.json / engineering_reference_lines.json
  L5.5 产物，是 L6 connector solver 的输入。

roads_optimized_centerlines.geojson
  L6 工程中心线，包含 approach、junction connector、corner fillet。

junction_connector_candidates.json
  L6.5 connector solver v2 候选集。用于 replacement transaction，不是发布几何。

roads_clean_skeleton.geojson
  Houdini 默认导入的 clean skeleton artifact。
```
