# Road Test Pipeline Layered Plan

Date: 2026-06-03
Area: `pattaya_central_500m`
Status: initial layered plan

## 目标

本计划用于把当前道路测试管线从“中心线可视化修复”推进到 OpenDRIVE 风格的车道级道路生成。

核心目标不是一次性把所有地图错误自动修好，而是建立一条可以持续迭代的分层管线：

- 原始数据不被破坏。
- 每一次修复都可追踪。
- 高置信问题可以自动处理。
- 中低置信问题进入可视化审计和人工 override。
- 每一种未知异常都沉淀成 case，再变成规则、测试或 override。

## 总体原则

1. 原始数据层只读，不直接修改。
2. 修复、推断、几何拟合和车道生成必须分层。
3. 每层都输出稳定 artifact 和 report。
4. 每层都要有自动 QA gate。
5. 每层失败时要能回流到上一层，而不是在下游临时补洞。
6. Houdini 是可视化和验收环境，不是唯一的数据真相来源。
7. OpenDRIVE 导出必须来自结构化道路模型，而不是直接从 Houdini 视觉线条反推。

## 分层框架

### L0 Raw Data Layer

职责：

- 保存原始地图道路数据。
- 保留 source id、tags、geometry 和 metadata。
- 不做破坏性修改。

主要输入：

- Overpass / OSM-like road data
- 后续可能加入其他地图源

主要输出：

- `data/processed/<area_id>_roads_raw.geojson`
- `reports/<area_id>_raw_analysis.json`
- `reports/qa/<area_id>_raw_roads_qa_report.json`

自动迭代：

- 检查空 geometry。
- 检查重复点。
- 检查过短 feature。
- 统计 `lanes`、`width`、`oneway`、`turn:lanes` 覆盖率。
- 统计 dangling endpoint ratio。
- 统计 possible unsplit crossings。
- 只报告问题，不修复。

QA gate：

- raw feature 数量足够。
- empty geometry 为 0。
- duplicate point feature 为 0。
- too-short feature 不超过阈值。

### L1 Normalization Layer

职责：

- 把不同来源、不同 tag 风格的数据标准化成统一 schema。
- 做轻量、无语义风险的几何清洗。

主要输入：

- L0 raw roads

主要输出：

- `data/processed/<area_id>_roads_normalized.geojson`
- `reports/<area_id>_normalization_report.json`

自动迭代：

- 坐标轴和投影 metadata 统一。
- 道路等级字段归一化。
- `lanes`、`width_m`、`oneway` 基础解析。
- 去除相邻重复点。
- 删除或标记无法使用的空/短几何。
- 对异常 tag 进入 warning list。

QA gate：

- 输出 feature 不少于 raw 的有效 feature。
- 坐标和 metadata 完整。
- 基础 tag fallback 可解释。

当前状态：

- 该层还没有完全独立出来。
- 当前部分逻辑分散在 raw analysis、topology repair 和 road graph builder 中。

### L2 Repair Audit Layer

职责：

- 发现原始/标准化道路的拓扑问题。
- 生成候选修复，但不直接应用激进修复。
- 给每个候选打置信度。

主要输入：

- L1 normalized roads 或当前 L0 raw roads

主要输出：

- `reports/<area_id>_repair_report.json`
- report 内的 `repair_review`
- 后续可拆为 `data/processed/<area_id>_repair_candidates.json`

自动迭代：

- 找 dangling endpoints。
- 区分 bbox 边界 dangling 和内部 dangling。
- 找 endpoint-to-endpoint gap。
- 找 endpoint-to-edge gap。
- 找疑似未搭上的 T junction。
- 找未 split 的道路交叉。
- 按距离、方向、道路等级、道路名称打分。
- 分为 high / medium / low confidence。

QA gate：

- 所有候选必须可追踪到 source feature。
- 每个候选必须有 confidence。
- low confidence 不允许自动应用。

当前状态：

- `scripts/topology_repair.py` 已加入初版 `repair_review`。
- 当前样本输出：
  - internal dangling endpoints: `72`
  - endpoint bridge candidates: `0`
  - endpoint-to-edge review candidates: `1`
  - high-confidence candidates: `1`

### L3 Topology Repair Application Layer

职责：

- 只应用保守或高置信修复。
- 输出稳定的 repaired road centerline。

主要输入：

- L1 normalized roads
- L2 repair candidates
- L12 manual overrides

主要输出：

- `data/processed/<area_id>_roads_repaired.geojson`
- `reports/<area_id>_repair_report.json`
- `reports/qa/<area_id>_topology_repair_qa_report.json`

自动迭代：

- endpoint snapping。
- endpoint-to-edge snapping。
- planar intersection splitting。
- same-road small gap bridge。
- short edge cleanup。
- 每轮修复后重新计算 dangling / crossing / short edge。
- 如果修复导致指标变差，回滚该操作或降低规则置信度。
- 迭代直到指标收敛或只剩 review candidates。

QA gate：

- output edge 数量足够。
- empty geometry 为 0。
- duplicate points 为 0。
- too-short edge 不超过阈值。
- dangling endpoint ratio 低于阈值。
- possible unsplit crossings 为 0。

当前状态：

- 已有 `topology_repair_v2`。
- 已支持 endpoint snap、endpoint-to-edge snap、intersection split、short edge cleanup。
- 还需要把 L2 high-confidence candidate promotion 做成可控开关。

### L4 Road Graph Layer

职责：

- 把 repaired centerlines 转成稳定道路图。
- 形成 node / edge contract。

主要输入：

- L3 repaired roads

主要输出：

- `data/processed/<area_id>_road_graph.json`
- `reports/<area_id>_road_graph_report.json`
- `reports/qa/<area_id>_road_graph_qa_report.json`

自动迭代：

- 构建 graph nodes 和 edges。
- 计算 node degree。
- 分类 boundary dead end、internal dead end、junction、connector。
- 检查 orphan edges。
- 检查 zero-length edges。
- 回传异常节点给 L2/L3。

QA gate：

- nodes / edges 非空。
- orphan edge 为 0。
- zero-length edge 为 0。
- internal dead-end ratio 低于阈值或进入 review。

当前状态：

- `scripts/build_road_graph.py` 已存在。
- road graph QA 当前允许 fixed-width fallback warning。

### L5 Junction Semantics Layer

职责：

- 判断路口类型和道路级 movement。
- 保持语义和几何分离。

主要输入：

- L4 road graph

主要输出：

- `data/processed/<area_id>_junction_semantics.json`
- `reports/<area_id>_junction_semantics_report.json`

自动迭代：

- 分类 T / cross / Y / fork / merge / roundabout / complex。
- 推断 allowed movements。
- 推断 blocked movements。
- 应用 one-way 约束。
- 检查 movement 是否引用有效 road edge。
- 不确定路口进入 visual review。

QA gate：

- 每个 allowed movement 后续必须生成 connection。
- blocked movement 不允许生成 laneLink。
- unsupported junction type 必须显式标记。

当前状态：

- 已有 junction semantics builder。
- 当前样本主要是 T junction 和少量 cross junction。

### L6 Engineering Reference Line Layer

职责：

- 把道路中心线从 polyline 草稿升级成工程几何。
- 为 OpenDRIVE reference line 做准备。

主要输入：

- L4 road graph
- L5 junction semantics

主要输出：

- `data/processed/<area_id>_roads_optimized_centerlines.geojson`
- 后续目标：`data/processed/<area_id>_engineering_reference_lines.json`
- `reports/<area_id>_optimized_centerlines_report.json`

自动迭代：

- 拟合 `line`。
- 拟合严格 `circular_arc`。
- 后续加入 `spiral / clothoid`。
- 记录 radius、center、sweep、sample count、fit status。
- 检查切线连续。
- 检查转弯半径是否满足设计最小值。
- 如果半径不足，尝试增加 trim 或降低 speed/design class。
- 如果空间不足，标记 `constrained_junction`。

QA gate：

- circular arc 采样点必须落在声明圆上。
- connector endpoint 必须贴合 approach endpoint。
- corner fillet 与 junction connector 必须分开。
- optimized connector 不得污染 lane semantic layer。

当前状态：

- `scripts/optimize_junction_centerlines.py` 已开始输出圆弧 metadata。
- 当前样本：
  - corner circular arcs: `21`
  - junction circular arcs: `107`
  - near-straight infinite radius connectors: `42`
  - 有部分 junction connector 半径低于设计最小半径，需要下一轮处理。

### L7 Lane Model Layer

职责：

- 从 road reference line 推导 lane sections。
- 生成 lane-level contract。

主要输入：

- L4 road graph
- L6 engineering reference lines

主要输出：

- `data/processed/<area_id>_lane_graph.json`
- `reports/<area_id>_lane_graph_report.json`
- `reports/qa/<area_id>_lane_graph_qa_report.json`

自动迭代：

- 推断 lane count。
- 推断 lane width。
- 生成 lane centerline / boundary。
- 判断 lane direction。
- 处理 one-way / two-way。
- 检查 lane 是否连续。
- 检查 width 是否异常。
- 记录 width source 和 confidence。

QA gate：

- lane 数量合理。
- lane width 在可接受范围。
- lane centerline 不为空。
- lane references 全部有效。

当前状态：

- 当前阶段采用固定 `3.2m` lane width baseline。
- 后续需要升级为 OpenDRIVE laneSection 模型。

### L8 Lane-Level Junction Layer

职责：

- 生成车道级路口连接。
- 最终接近 OpenDRIVE `junction / connection / laneLink`。

主要输入：

- L5 junction semantics
- L7 lane model
- L6 engineering geometry

主要输出：

- lane-level junction model
- 后续目标：`data/processed/<area_id>_lane_junctions.json`

自动迭代：

- 每个 movement 生成 connecting road。
- connecting road 也拥有 reference line。
- 生成 lane-to-lane mapping。
- 生成 laneLink。
- 检查 laneLink 起终点 gap。
- 检查转弯半径。
- 检查 forbidden movement。
- 失败时回退到保守连接或进入 review。

QA gate：

- every allowed movement has connection。
- every laneLink references valid lanes。
- no blocked movement laneLink。
- laneLink curves nonempty。
- laneLink endpoint gap 低于阈值。

当前状态：

- 当前 laneLink 仍主要使用 semantic endpoint Bezier。
- 下一阶段应升级为 engineering connector road。

### L9 Visualization And Geometry QA Layer

职责：

- 生成 Houdini 和 standalone 可视化。
- 把每层输出可视化为可审查 geometry。

主要输入：

- L3 repaired roads
- L6 engineering reference lines
- L7 lane model
- L8 lane junctions

主要输出：

- Houdini Python nodes
- debug GeoJSON / OBJ / SVG
- viewport screenshots
- `reports/qa/*`

自动迭代：

- 自动生成 centerline debug。
- 自动生成 repair candidate debug。
- 自动生成 lane boundary debug。
- 自动生成 junction connector debug。
- 高亮 low-confidence 修复。
- 高亮 radius violation。
- 高亮 dangling / crossing / overlap。
- 每轮输出截图和统计。

QA gate：

- Houdini cook 无 error。
- primitive / point counts 与报告一致。
- debug geometry 不为空。
- visual layers 不混淆数据职责。

当前状态：

- 当前 Houdini 已回到中心线导入为主。
- 后续应新增 repair review debug node，再重建 lane debug node。

### L10 OpenDRIVE Export Layer

职责：

- 从结构化道路模型导出 `.xodr`。

主要输入：

- L6 engineering reference lines
- L7 lane model
- L8 lane-level junctions

主要输出：

- `data/export/<area_id>.xodr`
- `reports/<area_id>_xodr_export_report.json`

自动迭代：

- reference line 转 OpenDRIVE `geometry`。
- lane section 转 OpenDRIVE `laneSection`。
- connecting road 转 OpenDRIVE junction connection。
- laneLink 转 OpenDRIVE laneLink。
- 导出后用 parser/viewer 回读。
- 回读失败定位到对应 layer。

QA gate：

- XML schema valid。
- road id / junction id / lane id 引用完整。
- geometry length 与采样长度误差低于阈值。
- viewer 可打开。

### L11 Pipeline Audit And Regression Layer

职责：

- 跨层检查整个 pipeline。
- 支撑后续大量道路 case 的自动回归。

主要输入：

- 所有 layer reports
- 所有 stage outputs

主要输出：

- `reports/<area_id>_pipeline_audit_report.json`
- case library
- regression summary

自动迭代：

- 每层 QA gate 汇总。
- 对比关键指标趋势。
- 识别新增异常。
- 把未知情况写入 case library。
- 把已解决 case 加入 regression suite。

QA gate：

- required outputs exist。
- failed checks 为 0。
- warn checks 可解释。
- 新规则不得破坏旧 case。

当前状态：

- `scripts/audit_road_pipeline.py` 已存在。
- 需要加入 repair candidate、arc radius violation、OpenDRIVE export 检查。

### L12 Manual Override Layer

职责：

- 处理自动系统无法可靠判断的歧义。
- 保证人工决策可复现。

主要输入：

- visual QA
- human review
- failing cases

主要输出：

- `config/<area_id>.manual_overrides.json`

自动迭代：

- 每次 pipeline 自动读取 override。
- override 必须带 reason。
- override 必须绑定 source feature/node/edge。
- 如果后续规则能自动解决，override 可降级为 regression case。

支持的 override 类型：

- force connect
- forbid connect
- force snap endpoint to edge
- force junction type
- force lane count
- force lane width
- force turn restriction
- force radius
- ignore dangling endpoint

QA gate：

- override 引用对象必须存在。
- override 不得造成 graph contradiction。
- override 数量和原因进入报告。

## 自动迭代总循环

推荐每个 area 的自动流程如下：

```text
L0 raw ingest
  -> L1 normalize
  -> L2 repair audit
  -> L3 repair apply
  -> L4 road graph
  -> L5 junction semantics
  -> L6 engineering reference lines
  -> L7 lane model
  -> L8 lane-level junctions
  -> L9 visualization QA
  -> L10 OpenDRIVE export
  -> L11 pipeline audit
```

如果任意层失败：

```text
fail
  -> classify failure
  -> write case
  -> try safe auto-fix
  -> rerun affected downstream layers
  -> if still fail, create manual override candidate
```

## 近期落地顺序

### Phase 1: 拓扑修复可审计化

- 完善 L2 repair candidates。
- 输出 Houdini repair review debug。
- 支持 manual override skeleton。
- high-confidence candidate 可选自动应用。

### Phase 2: 工程中心线稳定化

- 普通转角全部使用严格 circular arc。
- 路口 connector 使用 circular arc 或 straight infinite radius。
- 把 radius violation 加入 audit。
- 空间不足的路口显式标记 constrained。

### Phase 3: OpenDRIVE-style lane model

- 引入 road reference line + laneSection。
- lane centerline 改为从 reference line 派生。
- 固定宽度 baseline 保留为 fallback。

### Phase 4: Lane-level junction connecting roads

- 每个 movement 生成 connecting road。
- laneLink 从 connecting road 派生。
- 不再用 road skeleton connector 代替 laneLink 语义。

### Phase 5: XODR export and viewer validation

- 输出最小可打开 `.xodr`。
- 回读验证 road/lane/junction/laneLink。
- 建立多区域 regression suite。

## 当前重点风险

1. 原始地图存在断点和未搭接路口。
2. 自动吸附阈值过大时可能误连平行道路或辅路。
3. 路口 connector 虽已是圆弧，但部分半径低于设计最小半径。
4. 当前 lane graph 仍是固定宽度 baseline，还不是完整 OpenDRIVE laneSection。
5. Houdini 视觉层需要重新按新分层搭建，避免把调试图层误当数据源。

## 最小成功标准

对每个测试区域，至少需要做到：

- raw QA 可解释。
- repaired topology QA pass。
- road graph QA 无 fail。
- engineering centerline audit pass。
- lane graph QA pass。
- Houdini debug cook pass。
- 所有 low-confidence repair candidates 都可视化。
- 所有 manual overrides 可复现。
- 最终 OpenDRIVE viewer 可打开并能显示 lane-level junctions。
