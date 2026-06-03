# 车道级路口重建计划

## 一句话结论

后续目标不是把 `arc（圆弧）` 调得更像圆弧，而是重建接近真实世界的
`lane-level junction（车道级路口）`。`arc（圆弧）`、`clothoid（缓和曲线 / 回旋线）`、
`paramPoly3（参数三次曲线）`、`spline（样条曲线）` 都只是
`geometry candidate family（几何候选曲线族）`。

## 第一性原理

真实路口首先是一个交通与空间问题，不是一个单纯曲线拟合问题。

```text
incoming lane（进入车道）
  -> allowed movement（允许通行动作）
  -> drivable corridor（可行驶通道）
  -> outgoing lane（驶出车道）
```

所以算法顺序应该是：

```text
source map data（原始地图数据）
  -> road graph（道路拓扑图）
  -> confidence-tagged lane attributes（带置信度的车道属性）
  -> lane graph（车道拓扑图）
  -> junction zone model（路口影响区模型）
  -> movement corridor solver（通行走廊求解器）
  -> multi-curve fitting（多曲线拟合）
  -> audit / rollback（审计 / 回滚）
```

当前的 `junction connector arc（路口连接圆弧）` 应继续保留，但它的定位是
`diagnostic baseline（诊断基线）`。它负责暴露 `radius_below_design_min（半径低于设计最小值）`、
`single_arc_incompatible（单圆弧不兼容）`、`junction_trim_spread_excess（路口裁剪距离差异过大）`
等问题，而不是作为最终真实路口的唯一表达。

## 对现有工作的重新定性

当前 `road skeleton pipeline（道路骨架管线）` 不需要推翻。它是后续车道级重建的稳定底座：

```text
topology_repair（拓扑修复）
  清理地图 API（地图接口）脏数据，保证后续 graph（拓扑图）可用。

run_repair_casebook（修复案例回归）
  保护已知坏 case（案例），防止自动修复回退。

road_graph（道路拓扑图）
  提供 edge / node（边 / 节点）结构，是 lane graph（车道拓扑图）的上游。

junction_area_regularization（路口区域正规化）
  应升级理解为 junction zone model（路口影响区模型）的早期版本。

solve_junction_connectors（路口连接线求解器）
  应升级成 movement corridor solver（通行走廊求解器）的候选生成层。

short-edge absorption（短边吸收）
  应重新理解为 junction-zone expansion（路口影响区扩张）的一个子问题。
```

## 地图 API 车道数据缺失策略

地图 API（地图接口）可能缺少或污染这些字段：

```text
lanes（车道数）
lanes:forward / lanes:backward（正向 / 反向车道数）
turn:lanes（分车道转向）
width / width:lanes（道路宽度 / 分车道宽度）
oneway（单行）
turn restrictions（转向限制）
```

解决原则：任何推断值都不能伪装成真值。每个字段必须带：

```text
value（值）
source（来源）
confidence（置信度）
issues（问题标记）
```

推荐来源等级：

```text
source_tag（源标签）
  地图 API 原始字段明确给出，置信度最高。

source_tag_normalized（源标签标准化）
  原始字段存在但格式不标准，经过 parser（解析器）清洗。

inferred_topology（拓扑推断）
  根据 oneway（单行）、degree（节点度数）、turn movement（转向动作）推断。

inferred_road_class（道路等级推断）
  根据 highway / road_class（道路等级）给默认车道数和宽度。

assumed_default（默认假设）
  没有更好证据时使用，必须低置信度并进入 QA（质量门禁）。

manual_override（人工修正）
  人工覆写，必须有 reason（原因）和 reviewer（审查者）。
```

当前实现补充：

```text
temporary_all_roads_bidirectional_two_lane_v1（临时全道路双向两车道策略）
  当前阶段为了抵消 OSM lanes / turn:lanes / oneway（车道数 / 分车道转向 / 单行）缺失或污染，
  先把所有道路边统一展开为 bidirectional two-lane（双向两车道）。
  明确 oneway（单行）也只保留为 source_observation（源数据观察值），不直接阻断 movement（通行动作）。
  这是临时稳定策略；未来恢复真实车道时必须重新引入可审计的 direction / lane-count recovery（方向 / 车道数恢复）。
```

## 车道级路口重建目标

下一阶段不要直接生成最终路面，而是先生成这些中间层：

```text
lane_attribute_model.json（车道属性模型）
  每条 road edge（道路边）的车道数、宽度、转向标签、来源、置信度和问题标记。

lane_graph.json（车道拓扑图）
  每条 lane（车道）的方向、宽度、中心线、可进入/驶出关系。
  这是 structured graph data（结构化拓扑数据），不是 image file（图片文件）。
  当前 v1 的 centerline_xz 是 approximate offset preview（近似偏移预览），用于 QA（质量检查）和连接关系调试，
  不是 final lane geometry（最终车道几何）。

junction_zone_expansion_candidates.json（路口影响区扩张候选）
  哪些 short edge（短边）应该纳入路口影响区。

movement_corridor_candidates.json（通行走廊候选）
  每个 lane movement（车道通行动作）的可行驶通道候选。
  当前 v1 已由 solve_movement_corridors.py 输出，包含 topology_straight_baseline（拓扑直线基线）、
  bezier_g1_preview（G1 连续贝塞尔预览）、param_poly3_hermite_proxy（参数三次曲线 Hermite 代理）。
  这些仍是 candidate preview（候选预览），不是 final lane geometry（最终车道几何）。
```

## 当前预览限制

当前 SVG（可缩放矢量图）里看到的“车道连接终点落到多车道整体中轴”不是最终设计目标。

它来自当前 v1 契约的两个临时简化：

```text
lane_graph.centerline_xz（车道拓扑图中心线）
  是 approximate offset preview（近似偏移预览），用于 QA（质量检查）和连接关系调试。

movement_corridor_solver_v1（通行走廊求解器 v1）
  用 lane preview endpoint（车道预览端点）构建 corridor（走廊）。
  v1 已生成 lane_entry_anchor / lane_exit_anchor（车道入口 / 出口锚点），后续仍需 collision（碰撞）和 swept envelope（扫掠包络）评分。
```

下一步必须把 `engineering_reference_lines.json` 中的 `entry pose（入口姿态）` 扩展为车道级锚点：

```text
road-level entry pose（道路级入口姿态）
  + lane lateral offset（车道横向偏移）
  + traffic_side（通行侧，当前 Pattaya 为 left 左侧通行）
  -> lane_entry_anchor（车道入口锚点）
  -> lane_exit_anchor（车道出口锚点）
```

只有这样，通行走廊的起终点才会落在真实目标车道上，而不是多车道道路的整体中轴或临时预览点上。

## 几何候选策略

对每个 movement corridor（通行走廊），候选曲线应并行生成：

```text
current_geometry（当前几何）
  保留现状作为 baseline（基线）。

circular_arc（圆弧）
  适合简单、半径稳定的低复杂路口。

biarc（双圆弧）
  适合单圆弧无法同时满足两端切线的情况。

clothoid（缓和曲线 / 回旋线）
  更接近真实道路的曲率渐变。

paramPoly3（参数三次曲线）
  适合 OpenDRIVE（开放道路描述格式）连接道路表达。

spline（样条曲线）
  可作为复杂路口候选，但必须受 curvature（曲率）和 collision（碰撞）约束。
```

评分不应只看曲线是否漂亮，而要看：

```text
lane connectivity（车道连通性）
endpoint continuity（端点连续）
tangent continuity（切线连续）
curvature continuity（曲率连续）
turn radius（转弯半径）
swept envelope（扫掠包络）
collision（碰撞）
source confidence（源数据置信度）
OpenDRIVE exportability（OpenDRIVE 可导出性）
```

## 下一个最小闭环

最小可实施顺序：

```text
1. build_lane_attribute_model.py
   生成 confidence-tagged lane attributes（带置信度的车道属性）。

2. junction-zone expansion planner（路口影响区扩张规划器）
   把现有 short-edge absorption planner（短边吸收规划器）重新包装成路口影响区扩张候选。

3. lane graph v1（车道拓扑图 v1）
   已落地为 build_lane_graph.py。只做 topology（拓扑）和 confidence（置信度），不生成最终路面。

4. movement corridor solver v1（通行走廊求解器 v1）
   已落地为 solve_movement_corridors.py。每个 lane movement（车道通行动作）生成多曲线候选。
   当前已接入 lane-level entry/exit anchors（车道级入口/出口锚点），仍需 collision（碰撞）和 swept envelope（扫掠包络）评分。

5. compound junction merge planner（复合路口合并规划器）
   已落地为 plan_compound_junction_merges.py。它读取 movement_anchor_gap_audit（通行锚点缺口审计），
   把 adjacent_junction_short_link（相邻路口短连接）归并成 compound junction merge candidates（复合路口合并候选）。
   当前样本输出 3 个 low-risk transaction_candidate（低风险事务候选），尚未写回 clean skeleton（干净道路骨架）。

6. transaction + audit rollback（事务 + 审计回滚）
   只有 QA（质量门禁）不回退的候选才允许写回。
```

## 明确禁止

```text
不要为了消除 radius warning（半径警告）硬调小圆弧。
不要把 inferred（推断）车道数据当 source truth（源数据真值）。
不要在 Houdini（胡迪尼）里修复道路真值。
不要直接批量写回最高分曲线候选。
不要把 lane surface（车道路面）提前当作当前目标。
```
