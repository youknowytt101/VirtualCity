# 旧阶段交接参考：转角连续性与路口语义分层

日期：2026-06-03
区域：`pattaya_central_500m`

## 当前定位

这份文档是早期 lane / surface 阶段的设计参考，不是当前道路修复主入口。当前主线以
`AI_START_HERE.md`、`README.md`、`NEXT_AI_HANDOFF.md` 为准。

本文件仍然保留一个重要原则：

```text
几何连续性和路口通行语义必须分层。
```

普通道路转角可以通过 `optimized_corner_fillet` 维持视觉和工程连续性；真实 T、Y、fork、
merge、split、cross 路口必须由 junction semantics / movement graph 决定，不能直接把道路骨架层的
`optimized_junction_connector` 当成 laneLink 真值。

## 分层契约

```text
拓扑修复层
  修 raw OSM-like centerline，输出 repaired road centerlines。

道路图层
  构建 node / edge graph，保留 road class、lane count、width、oneway 等基础属性。

路口语义层
  识别真实图路口，生成 approaches、movements、allowed / blocked movement。

道路骨架几何层
  输出 optimized_approach_centerline、optimized_junction_connector、optimized_corner_fillet。
  这些是道路 skeleton，不是 laneLink 语义真值。

车道模型层
  未来从结构化 road graph / junction semantics / connector solver 生成 lane graph。

Houdini 层
  只导入 artifact 进行查看、验收和后续构建，不发明道路真值。
```

## 普通转角

普通道路转角通常是 degree 2 connector：

```text
Topology: degree 2
Semantics: 不是 merge / split / fork / cross
Geometry source: optimized_corner_fillet
Future lane output: continuity_links
Future surface output: lane_continuity_surface_v1
```

这类转角可以作为连续性几何向下游传递。

## 真实路口

真实路口通常是 degree >= 3：

```text
Topology: degree >= 3
Semantics: T / Y / cross / fork / merge / split
Road skeleton geometry: optimized_junction_connector
Future laneLink source: junction semantics + connector solver
```

`optimized_junction_connector` 只能作为道路骨架层可视化和工程参考，不能直接成为 laneLink 曲线。

## 早期回归原因

早期问题不是 `optimized_corner_fillet` 本身，而是把道路骨架层的 `optimized_junction_connector`
也推到了 laneLink 生成里。这样会让真实 T / cross / fork 的车道通行关系被道路视觉连接线污染。

因此后续开发必须保持两条线：

```text
road skeleton connector
  解决道路中心线连续、Houdini 查看、后续工程参考。

lane movement connector
  解决车道级 from-lane / to-lane 语义、turn restriction、OpenDRIVE laneLink。
```

## 当前对后续的约束

```text
不要用 optimized_junction_connector 直接替代 laneLink。
不要把 degree 2 corner fillet 误判成真实 junction movement。
不要在 Houdini 里手工修复路口语义。
未来 lane graph 应从 junction_semantics、junction_areas、engineering_reference_lines 和 connector solver 读取结构化输入。
```

## 和当前主线的关系

当前道路修复主线已经把路口处理推进到：

```text
junction_semantics.json
junction_areas.json
engineering_reference_lines.json
roads_optimized_centerlines.geojson
roads_clean_skeleton.geojson
```

下一阶段应该做 connector solver v2，再进入 lane graph / OpenDRIVE。不要跳回旧 lane surface 脚本作为主入口。
