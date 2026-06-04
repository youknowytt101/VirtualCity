# LaneForge 车道升级系统

LaneForge 是 road_test_pipeline 中间处理环节的统一系统名。

人类心智模型：

```text
地图原始数据输入
  -> LaneForge 车道升级系统
      -> 标准化 / 修复 / 车道升级 / 路口升级 / 自动 QA / 版本发布
  -> 标准车道数据包
  -> Houdini 构建管线
```

Houdini 不负责修路，也不负责判断道路真值。Houdini 只消费 LaneForge 发布的标准车道数据包，并把这些数据构建成可见的真实车道、路口面和调试层。

## 第一版边界

当前第一版目标不是一次性解决所有转角，而是建立可迭代系统骨架：

- 原始地图数据保持不可变。
- 车道数、人为修正、AI 建议都进入 versioned transaction。
- transaction 只是一条升级请求，不直接成为 source truth。
- lane graph 重建时消费 active overrides。
- 相邻路口 laneLinks 和 surfaces 自动随 lane graph 重建。
- 自动 QA 通过后发布标准车道数据包。
- QA 失败时回滚或禁用 active override，再把失败事务留作 casebook。

## 标准车道数据包

默认发布目录：

```text
data/lane_upgrade_packages/<area_id>/lane_package_v0001/
```

核心文件：

```text
manifest.json
standard_lanes.json
standard_junctions.json
standard_lane_surfaces.geojson
standard_lane_surfaces.obj
lane_debug_geometry.geojson
qa_report.json
lane_graph_report.json
lane_surface_report.json
houdini_manifest.json
active_lane_upgrades.json
```

`manifest.json` 是外部系统入口。Houdini 构建管线优先读取 `houdini_manifest.json`，不要从内部临时报告里猜路径。

## 网页点击升级模型

未来网页点击某条道路时，菜单可以直接显示：

```text
1车道 / 2车道 / 3车道 / 4车道
```

点击后不直接改 GeoJSON 或 lane graph，而是生成：

```text
data/lane_upgrade_system/transactions/<area_id>_lane_upgrade_transaction_vXXXX.json
data/processed/<area_id>_lane_upgrade_overrides.json
```

然后重建：

```text
lane_upgrade_overrides.json
  -> lane_model_builder.py
  -> lane_graph.json
  -> lane surfaces / junction envelopes
  -> audit_road_pipeline.py
  -> build_lane_upgrade_package.py
```

第一版影响范围是这条 road edge 和它两端直接路口。短边、复合路口、连续相邻路口扩散，后续作为 LaneForge 规则升级。

## 车道数分配策略 v1

当前 `balanced_bidirectional_left_traffic_v1`：

```text
1 physical lane -> shared bidirectional lane representation
2 physical lanes -> 1 forward + 1 backward
3 physical lanes -> 2 forward + 1 backward
4 physical lanes -> 2 forward + 2 backward
```

这只是初版结构化策略，后续可以升级为：

- 根据 oneway 恢复真实方向。
- 根据 turn:lanes 恢复转向专用车道。
- 根据 road class 和路口类型自动调整 approaching lanes。
- 对复合路口做局部事务重建。

## AI 自动迭代规则

AI 可以提出规则，但不能直接发布为真值。

推荐闭环：

```text
AI proposes rule
  -> dry run transaction
  -> rebuild affected lane graph / junctions / surfaces
  -> automated QA
  -> report
  -> accept into rule set or keep as rejected case
```

规则也需要版本：

```text
lane_rule_set_v0001
lane_upgrade_transaction_v0001
lane_package_v0001
```

## 当前命令

创建一条车道升级事务：

```powershell
python scripts\create_lane_upgrade_transaction.py --area-id pattaya_central_500m --road-id e_0012 --canonical-road-id cr_0012 --target-lane-count 3 --reason "web menu test"
```

重建并发布标准车道包：

```powershell
python scripts\rebuild_road_test.py --area-id pattaya_central_500m --skip-houdini
```

只发布当前已通过 QA 的标准车道包：

```powershell
python scripts\build_lane_upgrade_package.py --area-id pattaya_central_500m
```

## Viewer transaction contract v1

The SVG viewer remains an inspection surface. It does not edit GeoJSON or
lane_graph truth directly.

Current click flow:

```text
canonical road click
  -> reads data-vc-road-graph-edge-id from the exported SVG
  -> shows 1 / 2 / 3 / 4 physical lane buttons
  -> emits a LaneForge transaction request JSON
  -> backend create_lane_upgrade_transaction.py validates road_id and canonical_road_id against road_graph.json
  -> transaction records the direct endpoint junction scope
  -> rebuild_road_test.py rebuilds lanes / laneLinks / surfaces and publishes only after QA passes
```

The direct endpoint junction scope is intentionally v1:

```text
affected road edge + its two endpoint nodes + endpoint nodes classified as junction
```

Compound junction expansion, nearby short-edge absorption, turn-lane semantics
and multi-road corridor effects should be added as versioned LaneForge rules
instead of hidden viewer behavior.

## Execution v1 command

Run the full audited upgrade loop:

```powershell
python scripts\execute_lane_upgrade.py --area-id pattaya_central_500m --road-id e_0012 --canonical-road-id cr_0012 --target-lane-count 3 --reason "web menu lane upgrade"
```

This command creates the active transaction, rebuilds the structured road/lane
pipeline, runs the automated QA gate, publishes the next `lane_package_vXXXX`,
and refreshes the SVG QA view.

## Execution v1 smoke test

Completed one real end-to-end upgrade:

```text
road_id: e_0015
canonical_road_id: cr_0015
target_physical_lane_count: 3
transaction: lane_upgrade_transaction_v0001
package: lane_package_v0002
pipeline_audit: pass
```

The upgraded road now publishes:

```text
e_0015_f_1
e_0015_f_2
e_0015_b_1
```

This proves v1 can rebuild the affected road, direct endpoint junction
laneLinks, lane surfaces and junction envelopes, then publish a standard lane
package after QA passes.

## Junction propagation rules v2

Propagation v2 is proposal-only. It reads active upgrades and proposes nearby
roads that may need the same lane-count target, but it does not edit active
overrides directly.

Run:

```powershell
python scripts\plan_lane_upgrade_propagation.py --area-id pattaya_central_500m
```

Current v2 rules:

```text
through_pair_lane_count_continuity_v2
short_edge_absorption_lane_count_v2
same_role_same_class_junction_balance_v2
same_class_adjacent_approach_review_v2
adjacent_junction_context_review_v2
```

For the `e_0015 -> 3 lanes` smoke test, v2 produced:

```text
prop_0000: e_0014 / cr_0014, high confidence, through continuation
prop_0001: e_0019 / cr_0019, review, same-class adjacent approach
prop_0002: e_0020 / cr_0020, review, same-class adjacent approach
```

The latest package that includes this propagation plan is:

```text
lane_package_v0003
```

## Propagation application v1

Propagation application v1 is the controlled accept path for proposal-only
candidates.

Default accept policy:

```text
status == candidate_high_confidence
rule_id == through_pair_lane_count_continuity_v2
confidence >= 0.8
```

Run:

```powershell
python scripts\apply_lane_upgrade_propagation.py --area-id pattaya_central_500m --candidate-id prop_0000 --reason "accepted high-confidence through-pair propagation"
```

Current accepted propagation:

```text
candidate: prop_0000
road_id: e_0014
canonical_road_id: cr_0014
transaction: lane_upgrade_transaction_v0002
target_physical_lane_count: 3
pipeline_audit: pass
package: lane_package_v0004
```

The paired upgraded roads now publish:

```text
e_0014_f_1, e_0014_f_2, e_0014_b_1
e_0015_f_1, e_0015_f_2, e_0015_b_1
```

## Short-edge absorption application v1

Short-edge absorption is intentionally not part of the default propagation
application policy. It has a separate accept policy:

```text
policy == short_edge_absorption_only_v1
status == candidate_high_confidence
rule_id == short_edge_absorption_lane_count_v2
confidence >= 0.74
candidate_length_m <= 12.0
candidate_road_class == source_road_class
```

Run:

```powershell
python scripts\apply_lane_upgrade_propagation.py --area-id pattaya_central_500m --candidate-id prop_0000 --policy short_edge_absorption_only_v1 --reason "accepted controlled short-edge absorption"
```

This keeps short connector absorption reviewable and auditable before it
becomes an active lane upgrade.

## Corner optimization candidates v1

Road corner optimization belongs inside the LaneForge / road upgrade system,
between optimized centerlines and lane graph construction:

```text
optimized centerlines
  -> corner optimization candidates
  -> lane graph
  -> lane surfaces
  -> QA
  -> standard lane package
```

The first version is proposal-only. It does not mutate road geometry.

Run:

```powershell
python scripts\plan_corner_optimization.py --area-id pattaya_central_500m
```

Outputs:

```text
data/processed/<area_id>_corner_optimization_candidates.json
reports/<area_id>_corner_optimization_report.json
```

Candidate families:

```text
degree2_connector_corner
internal_centerline_bend
```

The SVG viewer has a `Corners` overlay. Clicking a candidate shows its source
edge, candidate type, risk level, turn angle, suggested cut distance and
suggested radius. Accepted candidates should later become versioned geometry
transactions, then rebuild and pass QA before publishing.

## Corner optimization application v1

Corner optimization now has a controlled apply path. The default accept policy
is intentionally narrow:

```text
policy == low_risk_degree2_connector_only_v1
candidate_type == degree2_connector_corner
risk_level == low
candidate id is explicit
```

Command:

```powershell
python scripts\apply_corner_optimization.py --area-id pattaya_central_500m --candidate-id corner_0001 --reason "accepted low-risk corner"
```

This writes:

```text
data/processed/<area_id>_corner_optimization_overrides.json
data/lane_upgrade_system/corner_applications/<area_id>_corner_optimization_application_vXXXX.json
```

Then it rebuilds, audits, publishes the next LaneForge package and refreshes
the SVG. `optimize_junction_centerlines.py` consumes active corner overrides
and annotates matching `optimized_corner_fillet` features with transaction
metadata, so the accepted turn can be traced from candidate -> centerline ->
lane graph continuity -> package.
