# Houdini 输出说明

这个目录只属于 `road_test_pipeline`，不属于 VirtualCity 主管线的 Houdini 工程。

当前 HIP：

```text
pattaya_central_500m_road_test.hip
```

## 当前节点顺序

运行主入口并带上 `--sync-houdini` 后，会重建 `/obj/road_test_<area_id>`。节点应从左到右排列：

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

`OUT_clean_road_skeleton` 是默认显示节点。connector arcs 和 corner fillets 是 clean skeleton 的调试分支，不是新的数据真值层。

## 重要边界

```text
Houdini 只负责导入、查看、验收和后续构建。
道路拓扑修复不在 Houdini 内完成。
不要在 HIP 里手工改线来掩盖 QA warning。
```
