# AI 先读我

## 当前目标

这里是独立的道路研究管线，目标是把各种地图 API / GIS 道路数据整理成可复现、可审计、可自我 QA 的 clean road skeleton。当前阶段不做最终 lane graph、OpenDRIVE 或完整车道面。

## 一条命令

从仓库根目录运行：

```powershell
python ProjectManagement/RoadResearch/road_test_pipeline/scripts/repair_road_skeleton.py --area-id pattaya_central_500m --sync-houdini
```

不需要 Houdini 时去掉 `--sync-houdini`。

## 主线阶段

```text
L0 raw source
L3 topology repair
L3 topology repair QA
L3 repair casebook QA
L4 road graph
L4 road graph QA
L5 junction semantics
L5.5 junction area regularization
L6 clean engineering skeleton
L6 junction geometry audit
L6.5 junction connector solver candidates
L9 optional Houdini sync
```

当前唯一主入口是 `scripts/repair_road_skeleton.py`。不要从旧 lane / preview 脚本启动当前阶段。

## 设计意图

```text
原始数据不可变。
候选修复不是正式修复。
任何几何修改必须可解释、可复现、可回滚。
高置信候选也必须走事务式 validator。
已知误报必须进入 casebook，成为回归测试。
Houdini 只导入 artifact，不负责修路。
```

## 当前已完成

```text
topology_repair.py
  保守拓扑修复，输出 candidates / decisions / casebook

run_repair_casebook.py
  自动重放已知坏 case，防止修复算法回退

regularize_junction_areas.py
  输出 junction_areas.json 和 engineering_reference_lines.json
  发布 entry poses、movement intents、short-edge absorption candidates

optimize_junction_centerlines.py
  已消费 regularized entry poses
  已把不满足单圆弧条件的 connector 标成 bezier_tangent_fallback

solve_junction_connectors.py
  connector solver v2 候选入口
  对每条 junction connector 生成 current / circular / paramPoly3 Hermite / G1 proxy 候选
  输出评分和是否可替换，不直接改 clean skeleton

repair_road_skeleton.py
  串起 L3-L6、QA、clean skeleton artifact 和可选 Houdini sync
```

## 当前样本状态

`pattaya_central_500m` 当前重点指标：

```text
topology repair QA: pass
repair casebook QA: pass
road graph QA: warn, width_fallback_ratio = 1.0
junction area regularization: warn, 34 entry_trim_capacity_limited, 22 short_edge_absorption_candidate
optimized centerlines: 149 regularized entry poses consumed
junction geometry audit: warn, radius_below_design_min = 90, junction_trim_spread_excess = 24
connector solver v2: warn, solver_cases = 103, unresolved_solver_cases = 102, replacement_ready_candidates = 1
```

`width_fallback_ratio` 是源数据缺少宽度；`radius_below_design_min` 和 `bezier_tangent_fallback` 是下一阶段 connector solver 的靶子，不应该在 Houdini 里硬改。

## 下一步

当前 connector solver v2 已经生成候选和评分。下一步是 replacement pass：

```text
输入:
  junction_connector_candidates.json
  junction_connector_solver_report.json

动作:
  只替换 replacement_ready_candidates
  替换后重跑 junction_geometry_audit.py
  如果半径/trim spread 变差，自动回滚
  剩余 unresolved case 进入 short-edge absorption 或真实 clothoid/paramPoly3 求解
```

不要直接把所有最高分候选写回 clean skeleton。候选必须先过 replacement transaction + QA。

## 必读顺序

```text
AI_START_HERE.md
README.md
NEXT_AI_HANDOFF.md
ROAD_REPAIR_STAGE_ARCHITECTURE.md
scripts/README.md
data/README.md
reports/README.md
```
