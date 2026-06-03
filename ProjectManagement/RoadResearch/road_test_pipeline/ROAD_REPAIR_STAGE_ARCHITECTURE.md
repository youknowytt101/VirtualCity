# 道路修复阶段架构设计

## 上下文快照

当前工作边界：

```text
原始地图/API 数据
  -> 道路修复 / Houdini 前置工程处理
  -> 干净道路骨架
  -> Houdini 构建
```

Houdini 的职责是查看、调试和构建，不应该在里面发明或修复道路真值。
道路修复阶段必须把各种脏地图数据变成稳定、可审计、可复现的道路骨架。

当前 `pattaya_central_500m` 最新状态：

```text
topology repair QA: pass
repair casebook QA: pass
Houdini raw roads: 44 primitives / 303 points
repaired road graph input: 243 simple edges
Houdini clean skeleton: 413 primitives / 2182 points
internal dangling endpoints for review: 28
endpoint-to-edge review candidates: 0
high-confidence repair candidates: 0
possible unsplit crossings: 0
road graph QA warning: width_fallback_ratio = 1.0
junction semantics: blocked_movements = 0, source_oneway_blocked_movements_if_trusted = 142
junction area regularization warning: 28 entry_trim_capacity_limited, 26 short_edge_absorption_candidate
optimized centerlines: 149 regularized entry poses consumed, 50 bezier_tangent_fallback connectors
junction geometry audit warning: 78 radius_below_design_min
connector replacement transaction: 6 accepted replacements, no audit regression
connector solver v2 refresh: 85 solver cases, 85 unresolved solver cases, 0 replacement-ready candidates
junction-zone expansion planner: 26 short-edge flags, 19 transaction_ready, 46 affected unresolved connectors
lane attribute model: temporary_all_roads_bidirectional_two_lane_v1 active, source_oneway_overridden = 134, missing_turn_lanes_ratio = 1.0
lane graph topology: 486 directed lanes, 612 lane links, lane_link_reference_errors = 0, QA pass
movement corridor solver: 306 corridor cases, 918 candidate curves, reference_errors = 0, low_confidence_ratio = 1.0
```

旧的高置信候选 `1209258529:end -> 1210710015 segment 1` 已确认是误报。
该端点其实已经连接到 `27443575`；如果强行 snap 到 `1210710015`，会切穿第三条道路。
现在它被记录成 `forbid_snap_endpoint_to_edge` 手工 override。

## 设计目标

道路修复阶段不应该只是一个临时清理脚本，而应该像一个小型 HD Map 生产系统：

```text
数据接入 -> 标准化 -> 分类 -> 生成修复候选 -> 校验
  -> 事务式应用安全修复 -> 自我 QA -> 回滚或发布
  -> 生成人工审查 case -> 从 override / regression 中迭代学习
```

最重要的规则：

```text
任何几何编辑都必须可解释、可复现、可回滚。
```

## 核心原则

1. 原始数据不可变。
2. 每个派生产物都必须有 schema、stage 名称、source 路径和 metrics。
3. repair candidate 不是 repair；只有通过校验后才可以改变几何。
4. confidence 不等于安全。高置信候选仍然必须通过拓扑、几何、语义、工程 QA。
5. manual override 是一等数据，必须有 reason 和稳定 source reference。
6. 如果一次修复造成新的 QA 失败，必须回滚，并把它变成 review case。
7. Houdini 只导入已发布 artifact，不负责修路。

## 目标分层

```text
L0 source adapters
L1 canonical raw observations
L2 normalized road features
L3 conservative topology repair
L4 road graph and evidence graph
L5 junction semantics and movement graph
L6 engineering reference lines / clean skeleton
L7 road/lane model candidates
L8 QA, regression cases, manual overrides
L9 Houdini sync / visualization artifacts
```

当前管线已经有 L3-L6 的雏形。下一步应该把 L0-L8 显式化，变成契约清晰的阶段。

## 输入适配器

道路修复阶段未来会吃很多地图/API 数据，应该统一成 adapter 模式：

```text
OSM / Overpass
Overture Maps
商业道路 API
城市 GIS shapefile
已有 OpenDRIVE / Lanelet2 / GeoJSON
未来影像或点云推导出的道路候选
```

每个 adapter 输出不可变 observation：

```json
{
  "source_provider": "openstreetmap_overpass",
  "source_feature_id": "1209258529",
  "source_version": "...",
  "geometry": "...",
  "tags": {},
  "confidence": {
    "geometry": 0.75,
    "classification": 0.6,
    "lane_count": 0.4,
    "width": 0.2
  },
  "provenance": {
    "downloaded_at": "...",
    "query_or_api_call": "...",
    "license": "..."
  }
}
```

canonical raw 层不能静默 merge、snap 或 infer。所有推断都必须进入后续阶段。

## Evidence Graph

不要直接从 GeoJSON line 跳到最终 road graph。中间应该有 evidence graph：

```text
evidence_node
  source positions, endpoint roles, bbox relation, layer hints

evidence_edge
  source feature id, geometry, road class, name, lanes, width, oneway,
  bridge/tunnel/layer, source confidence

candidate_relation
  endpoint_endpoint_snap
  endpoint_to_edge_snap
  road_road_intersection
  duplicate_or_conflated_edge
  same_real_world_road
  forbidden_relation
```

这样道路修复阶段才有“记忆”：它能解释为什么某条连接存在，也能解释为什么某条连接被拒绝。

## 修复候选流程

候选生成可以宽，候选应用必须严。

候选来源：

```text
距离 + 朝向的 endpoint snap
endpoint-to-edge projection
line-line crossing
duplicate / near-parallel conflation
道路名、道路等级、oneway 一致性
HMM / map matching 风格的路线似然
junction context
source confidence / source priority
manual overrides
```

每个候选都应该有完整记录：

```json
{
  "candidate_id": "...",
  "action": "force_snap_endpoint_to_edge",
  "confidence": 0.82,
  "source_refs": [],
  "evidence": {},
  "validators": {},
  "status": "candidate | applied | rejected | blocked | manual_review",
  "reason": "..."
}
```

## 强制校验器

任何 candidate 改变几何前，至少需要通过：

```text
V1 引用的 source feature 存在
V2 bridge / tunnel / layer 分层不被破坏
V3 不产生 zero-length 或过短 edge
V4 不产生新的第三道路穿越
V5 不把端点从已有有效 node 拉走
V6 不违反 oneway / road class 语义
V7 graph 连通性变化可解释
V8 junction degree / type 变化可解释
V9 QA warning 不增加
V10 输出能从 source + config 完整复现
```

当前 `topology_repair.py` 已经补上了 endpoint-to-edge repair 的 V4/V5 核心保护。
当前 `optimize_junction_centerlines.py` 已经消费 `engineering_reference_lines.json` 的 regularized
entry poses；如果两端 entry pose 和切线不满足单圆弧条件，会输出 `bezier_tangent_fallback`，并继续
交给 `junction_geometry_audit.py` 暴露半径与 trim spread 问题。
当前 `solve_junction_connectors.py` 已经生成 connector solver v2 候选和评分，但不会直接替换
clean skeleton。替换必须进入下一轮 replacement transaction。
当前 `apply_connector_replacements.py` 已经把 replacement transaction 接入主线：只替换
`replacement_ready_candidates`，并在 trial audit 不回退时写回。剩余问题需要 short-edge absorption
和真实 clothoid / paramPoly3 fitting。
当前 `plan_short_edge_absorptions.py` 已经把 junction area 中的短边吸收标记转成非破坏式候选，
其中 `transaction_ready` 才允许进入下一步 destructive transaction（写入式事务）；该 planner 本身不改 road graph、
engineering reference 或 clean skeleton。
当前 `build_lane_attribute_model.py` 已经把 lanes / width / turn:lanes 标准化为
`confidence-tagged lane attributes（带置信度的车道属性）`，明确区分 source truth（源数据真值）、
inferred（推断）和 missing（缺失）。
当前 `build_lane_graph.py` 已经把 road_graph（道路拓扑图）、lane_attribute_model（车道属性模型）、
junction_semantics（路口语义）合成为 `lane_graph（车道拓扑图）` v1。它输出 structured graph data（结构化拓扑数据），
不是 image file（图片文件）；`centerline_xz` 只作为 approximate offset preview（近似偏移预览），
不代表 final lane geometry（最终车道几何）。
当前 `export_lane_graph_svg.py` 已经输出 lane graph SVG visualization（车道拓扑图 SVG 可视化），
默认路径是 `reports/visualizations/<area_id>_lane_graph_topology.svg`。该 SVG 只用于 human QA（人工质检）。
当前 `solve_movement_corridors.py` 已经从 lane_graph（车道拓扑图）生成 movement corridor candidates（通行走廊候选），
但因为 turn:lanes（分车道转向）缺失，所有候选仍保持低置信 QA candidate（需复核候选）。
当前 movement corridor solver v1（通行走廊求解器 v1）已经用 lane_entry_anchor /
lane_exit_anchor（车道入口 / 出口锚点）替代旧的 lane preview endpoint（车道预览端点），
并已消费 transaction_ready short-edge absorption（事务就绪短边吸收）候选生成 planned virtual anchors（规划虚拟锚点）。
如果仍看到偏近锚点，优先看 movement_anchor_gap_audit（通行锚点缺口审计）和
compound_junction_merge_candidates（复合路口合并候选），不要把 SVG（可缩放矢量图）当 source truth（源数据真值）。

## 事务式自我修复闭环

推荐运行方式：

```text
1. 加载 normalized roads
2. 计算 baseline QA
3. 生成 repair candidates
4. 按 confidence 和 risk 排序
5. 在临时 graph 上应用一个 candidate
6. 运行 local validators
7. 运行 affected-area QA
8. 全部通过才 accept
9. 把 applied / rejected 写进 report
10. 每个被拒绝的高置信候选都生成 regression case
```

这比一次性批量应用所有高置信候选安全得多。一个错误 snap 很容易在当前阶段看起来没问题，
但在 road graph、junction、lane model 阶段放大成严重问题。

## QA 分类

QA 需要按语义拆开，而不是一个总分：

```text
geometry QA
  empty geometry, duplicate points, short segments, self-intersection,
  segment angle spikes, coordinate precision, invalid projection

topology QA
  dangling endpoint classes, unsplit crossings, orphan edges,
  graph contradiction, layer crossing, dead-end ratio

semantic QA
  road class, oneway, lane count, width, speed, access, service/private,
  bridge/tunnel/layer, turn restrictions

junction QA
  junction type, approach count, movement count, blocked movements,
  connector feasibility, conflict-zone size, short-edge compression

engineering QA
  min radius, curvature continuity, swept envelope, laneLink consistency,
  OpenDRIVE exportability

provenance QA
  source coverage, fallback ratios, override counts, confidence distribution
```

修复阶段应该同时输出机器可读 QA 和 Houdini 可视化 debug layer。

## Manual Overrides

manual overrides 建议固定在：

```text
config/<area_id>.manual_overrides.json
```

拓扑类 override 类型：

```text
force_connect
force_snap_endpoint_to_edge
forbid_connect
forbid_snap_endpoint_to_edge
ignore_dangling_endpoint
force_road_class
force_lane_count
force_width
force_junction_type
force_turn_restriction
```

规则：

```text
enabled 必须显式
reason 必须填写
source reference 必须用稳定 id，不能用易变数组索引
override 结果必须进入 report
override 可以阻止自动 high-confidence promotion
```

## 数据归类

修复前要先分类问题，不要把所有 dangling endpoint 都当成 snap 问题：

```text
真实 dead end
bbox 边界截断
内部 dangling endpoint
service driveway / private access
parking aisle
roundabout / mini roundabout
T / cross / Y / offset / compound junction
short-edge compression
dual carriageway split
bridge/tunnel/layer separation
可能缺失道路
可能重复道路
可能是地图编辑 artifact
```

分类清楚以后，自动修复才不会乱接。

## 当前路口圆弧算法复盘

当前 `optimize_junction_centerlines.py` 的策略：

```text
先把 approach 从 graph node 回退 trim
对 junction 周围 trim 做 equalize
推断 through / turn movement pair
对 connector 和 corner fillet 拟合严格 tangent circular arc
记录 radius / design-min diagnostics
违反半径要求时保留诊断，不在 Houdini 里假修
```

优点：

```text
确定性强
实现简单
能保证 circular arc 真圆
诊断 metadata 清晰
适合作为 Houdini clean skeleton 预览层
```

问题：

```text
圆弧是 constant curvature，接直线时会有曲率跳变
短边压缩会把半径挤到不可能的小值
所有 turn movement 都是局部求解，没有 junction conflict-zone 模型
没有 design vehicle swept-path check
还没有 lane-level entry / exit anchor
还没有 OpenDRIVE connecting-road / laneLink 对象模型
```

## 更先进的路口几何方向

当前圆弧 solver 可以继续作为预览和诊断层，但不应该成为最终工程道路模型。

更好的目标：

```text
junction conflict zone
  -> 每个 approach / lane 的 entry / exit pose
  -> 每个 movement 的 connecting road
  -> laneLink graph
  -> line / arc / clothoid / paramPoly3 几何候选
  -> swept-path + collision + curvature QA
```

OpenDRIVE 的模型也指向这个方向：junction 用 connecting roads 和 lane links 表达，
reference line 几何可以由 line、arc、spiral/clothoid、paramPoly3 组合。

推荐 connector 层级：

```text
through movement
  line 或 line-spiral-line

普通低速转弯
  line-spiral-arc-spiral-line

不规则或空间受限转弯
  G2 continuous clothoid spline 或 parametric cubic curve

roundabout-like movement
  circular arc / arc spline 可以接受

不可行 movement
  blocked movement 或 manual review，不能塞一个假小半径
```

优化目标：

```text
最小化与 source centerline 的偏离
最大化 radius margin
保持 entry / exit tangent
优先 G2 curvature continuity
避免 connector self-intersection
避免 connector-connector / connector-road collision
尊重 road class、lane count、width、design vehicle、turn restriction
尽量少改上游 repaired topology
```

因此，圆弧应该只是 candidate 之一。它需要和 clothoid、paramPoly3 一起竞争；
如果半径、碰撞、曲率连续性不满足，就应该失败并进入诊断，而不是输出假工程几何。

最新 HD Map 研究也在朝 learned topology 和多源地图构建发展。这些方法适合用来生成候选和置信度，
但不应该绕过确定性校验。在本管线里，ML 或外部 map-prior 模型只能提供 evidence；
最终发布的几何仍然必须通过 topology、semantic、engineering QA。

## 近期实现计划

Phase 1：显式化 repair contracts。

```text
schemas/
  road_observations.schema.json
  normalized_roads.schema.json
  repair_candidates.schema.json
  repair_decisions.schema.json
  road_graph.schema.json
  junction_semantics.schema.json

scripts/
  generate_repair_candidates.py
  validate_repair_candidate.py
  apply_repair_decisions.py
  build_repair_casebook.py
```

当前已落地的第一步：

```text
data/processed/<area_id>_repair_candidates.json
  记录 topology repair 候选、置信度、风险、生成时通过的 validator。

data/processed/<area_id>_repair_decisions.json
  记录基础修复摘要、manual override 处理结果、high-confidence promotion 决策。

data/processed/<area_id>_repair_casebook.json
  记录 manual forbid、被事务校验拒绝的高置信候选，以及后续回归测试需要固定的 case。
```

Phase 2：把一次性 repair 改成 transaction loop。

```text
topology_repair.py 保留保守基础修复
新的 candidate runner 一次尝试一个候选
每个 accepted / rejected candidate 都写 report
high-confidence promotion 默认关闭，除非全部 validator 通过
```

当前 `--apply-high-confidence` 已进入初版事务式路径：

```text
candidate -> operation -> deepcopy roads -> trial apply
  -> no_new_short_or_zero_edge
  -> no_new_third_road_crossing
  -> dangling_endpoint_ratio_no_regression
  -> operation_result_acceptable
  -> accepted commit / rejected casebook
```

当前 `run_repair_casebook.py` 已作为自动回归入口接入一键 runner：

```text
topology_repair.py
  -> repair_candidates / repair_decisions / repair_casebook
  -> run_auto_qa.py --stage topology_repair
  -> run_repair_casebook.py
```

Houdini 视图采用从左到右的阶段列，而不是假装在 Houdini 内修路：

```text
raw source lines
  -> repaired topology lines
  -> clean single-line skeleton
       -> junction connector arc debug branch
       -> corner fillet arc debug branch
```

Phase 3：junction area regularization。

```text
识别 compound / offset junction
把过短边吸收到 conflict-zone boundary
从稳定 approach 计算 entry / exit pose
发布 engineering_reference_lines.json
```

当前已落地初版：

```text
scripts/regularize_junction_areas.py

data/processed/<area_id>_junction_areas.json
  junction conflict zone 估计、approach entry pose、short-edge absorption candidate。

data/processed/<area_id>_engineering_reference_lines.json
  approach_entry_poses + connecting_road_intents，供后续 connector solver 使用。

reports/<area_id>_junction_area_regularization_report.json
  记录 capacity-limited entry pose、short-edge absorption candidate 等问题。
```

Phase 4：connector solver。

```text
生成 circular、clothoid、paramPoly3 candidates
按 curvature、radius、collision、source fit、OpenDRIVE exportability 打分
输出带 laneLink 意图的 connecting road candidates
短边吸收必须先作为 transaction candidate（事务候选）进入 trial（试运行），再由 audit rollback（审计回滚）决定是否写回
```

Phase 4.5：lane-level junction reconstruction（车道级路口重建）。

```text
arc（圆弧）不是目标，只是 geometry candidate family（几何候选曲线族）之一
先建立 confidence-tagged lane attributes（带置信度的车道属性）
再建立 lane graph（车道拓扑图）：当前 v1 已输出 structured graph data（结构化拓扑数据），不是 image（图片）
再生成 lane-level entry/exit anchors（车道级入口/出口锚点）：当前 v1 已完成
再用 movement_anchor_gap_audit（通行锚点缺口审计）生成 compound junction merge candidates（复合路口合并候选）：当前 v1 已完成
最后做 compound junction merge transaction（复合路口合并事务）和 collision（碰撞）/ swept envelope（扫掠包络）评分
```

Phase 5：regression 和人工审查。

```text
所有被拒绝的高置信候选都进入 casebook
渲染 before / after 可视化 QA layer
每次代码修改都跑 casebook
```

## 关键参考

- ASAM OpenDRIVE 1.9.0，geometry elements：line、spiral/clothoid、arc、parametric cubic curve。
  OpenDRIVE 明确支持用 spiral 避免 line 与 arc 之间的曲率跳变。
  https://publications.pages.asam.net/standards/ASAM_OpenDRIVE/ASAM_OpenDRIVE_Specification/latest/specification/09_geometries/09_01_introduction.html
- ASAM OpenDRIVE 1.9.0，spiral/clothoid geometry：curvature 沿弧长线性变化。
  https://publications.pages.asam.net/standards/ASAM_OpenDRIVE/ASAM_OpenDRIVE_Specification/latest/specification/09_geometries/09_04_spiral.html
- ASAM OpenDRIVE 1.9.0，arc geometry：arc 是 constant curvature。
  https://publications.pages.asam.net/standards/ASAM_OpenDRIVE/ASAM_OpenDRIVE_Specification/latest/specification/09_geometries/09_05_arc.html
- ASAM OpenDRIVE 1.9.0，junction connecting roads 和 lane links。
  https://publications.pages.asam.net/standards/ASAM_OpenDRIVE/ASAM_OpenDRIVE_Specification/latest/specification/12_junctions/12_04_connecting_roads.html
- Lanelet2 paper：自动驾驶 HD Map 需要 lane-level 和 semantic structure，不能只依赖粗 centerline。
  https://www.mrt.kit.edu/z/publ/download/2018/Poggenhans2018Lanelet2.pdf
- Lane-level road network generation survey：arc curve 简单，适合 roundabout-like intersection；
  不规则 intersection 需要更自适应的曲线。
  https://www.mdpi.com/2071-1050/11/16/4511
- CMU Robotics Institute composite clothoid path generation：clothoid 能提供连续 position、tangent direction、curvature。
  https://publications.ri.cmu.edu/path-generation-for-robot-vehicles-using-composite-clothoid-segments
- Queensland Road Planning and Design Manual，clothoid spiral：curvature 沿 spiral length 均匀变化。
  https://www.tmr.qld.gov.au/-/media/busind/techstdpubs/Road-planning-and-design/Road-planning-and-design-manual/Current-document/RPDM_Chapter11.pdf
- Newson and Krumm，Hidden Markov map matching：用概率方式处理噪声和 road network layout，
  可作为多源道路证据评分的参考。
  https://www.microsoft.com/en-us/research/wp-content/uploads/2016/12/map-matching-ACM-GIS-camera-ready.pdf
- SIO-Mapper 2025：结合 satellite imagery 和 OSM，用深度 encoder + cluster/graph lane integration
  构建城市级 HD Map，可作为未来 repair evidence 来源。
  https://huggingface.co/papers/2504.09882
- TLSD 2025：结合几何 lane segment 预测、graph knowledge 和 topology post-processing
  来增强 HD Map connectivity。
  https://proceedings.mlr.press/v304/trong26a.html
