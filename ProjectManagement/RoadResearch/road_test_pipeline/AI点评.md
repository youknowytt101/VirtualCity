# LaneForge 优化计划

目标：把 LaneForge（道路/车道升级系统）从 research pipeline（研究型管线）升级成 production-grade road data pipeline（生产级道路数据管线）：可审查、可追溯、可回滚、可发布、可供 Houdini（程序化建模工具）稳定消费。

## 状态标记

- `[待做]`：尚未开始。
- `[部分具备]`：系统已有基础能力，但还需要补完整。
- `[已具备]`：当前系统已经支持，不需要重复建设。
- `[完成: 2026-06-05]` / `[完成: 2026-06-06]`：本轮已经完成或修正。

## 当前事实核对

截至 2026-06-06，本计划按以下事实重新核对：

1. latest package（最新数据包）是 `lane_package_v0166`。
2. QA gate（质量门禁）是 `manual_review_required`，有 6 个 manual review warning（人工复核警告），没有 blocker（阻断项）。
3. active lane upgrades（激活车道升级）是 50 条，且当前 lane graph（车道图）里全部应用到 geometry（几何）上。
4. active corner optimizations（激活转角优化）是 6 个。
5. propagation planning（传播规划）默认是 proposal-only（只提建议）；受控应用必须通过 apply script（应用脚本）逐条执行。
6. viewer（网页查看器）已经支持 restore default（恢复默认）、后台 apply job（应用任务）、job-level before/after package diff（任务级前后数据包差异）、QA warning inspector（质量警告检查面板）、Road-chain Review（道路链审查）只读面板、Junction Review（路口审查）只读面板、Package Lifecycle（数据包生命周期）治理面板、Propagation Review（传播审查）候选面板、review queue enqueue（审查队列入队）、semantic evidence inspector（语义证据检查面板）、before/after preview（前后预览）、laneLinks / surface diff preview（车道连接 / 车道面差异预览）和 detailed job timeline（详细任务时间线）。

## 核心原则

1. viewer（网页查看器）只做 inspection/action surface（检查与动作发起界面），不直接修改 geometry truth（几何真值）。
2. 所有 lane upgrade（车道升级）必须进入 transaction（事务记录）。
3. 每次 road/lane mutation（道路 / 车道变更）后必须 rebuild（重建）、QA（质量检查）、publish package（发布数据包）。
4. Houdini（程序化建模工具）只读取 standard lane package（标准车道数据包）。
5. automation（自动化）可以提出 proposal（建议），但不能绕过 QA gate（质量门禁）。
6. raw / repaired / canonical / road_graph（原始层 / 修复层 / 标准层 / 道路图）必须保持清晰边界。

## 阶段一：锁定 Baseline（基线）

以当前 `lane_package_v0126` 作为 baseline（优化基线）。

要做：

1. 固化当前 manifest（清单文件）、latest pointer（最新版本指针）、QA gate（质量门禁）、active upgrades（激活升级）。
2. 为每次优化生成 before/after diff（前后差异对比）。`[完成: 2026-06-05]`
3. 每个 viewer job（网页后台任务）输出 job summary（任务摘要）。`[完成: 2026-06-05]`
4. 每次 lane upgrade（车道升级）记录 reason（原因）、reviewer（复核人）、affected roads（影响道路）、affected junctions（影响路口）。

目标：任何一步都能回答“改了什么、为什么改、影响哪里、是否变好”。

## 阶段二：强化 Semantic Evidence（语义证据）

当前最大短板不是几何，而是 semantic truth（语义真值）。

重点处理：

1. width fallback ratio（宽度兜底比例）过高。
2. lanes fallback ratio（车道数兜底比例）仍需复核。
3. missing turn lanes ratio（缺失转向车道比例）过高。
4. dead-end ratio（断头路比例）和 dangling endpoint ratio（悬挂端点比例）需要分类。
5. oneway（单行属性）目前被 temporary bidirectional policy（临时双向策略）覆盖。

要做：

1. 新增 `semantic_evidence_summary.json`（语义证据汇总文件）。`[完成: 2026-06-05]`
2. 每条 road edge（道路边）记录 OSM lanes（原始车道数）、OSM oneway（原始单行信息）、highway class（道路等级）、width source（宽度来源）、lane count source（车道数来源）、confidence（置信度）。
3. viewer（网页查看器）点击道路时显示“为什么这条路是这个车道数”。`[完成: 2026-06-05]`

目标：让每条路的车道决策可解释、可审查。

## 阶段三：升级 Viewer UX（网页交互体验）

viewer（网页查看器）要从“能点”升级为 professional review workstation（专业审查工作台）。

建议增加：

1. Road Inspector（道路检查面板）：显示 road id（道路编号）、road-chain id（道路链编号）、当前 lane count（车道数）、active transaction（激活事务）、QA warnings（质量警告）。`[完成: 2026-06-05]`
2. Before / After Preview（前后预览）：点 1/2/3/4 车道后，先显示影响范围，再确认应用；同时显示 laneLinks / surface diff（车道连接 / 车道面差异）的只读估算。`[完成: 2026-06-05]`
3. Rollback（回滚）：不删除旧 transaction（事务记录），而是生成 restore transaction（恢复事务）。`[已具备]`
4. Job Timeline（任务时间线）：显示 submit request（提交请求）、create transaction（创建事务）、rebuild lane graph（重建车道图）、run QA gate（运行质量门禁）、plan propagation（规划传播）、publish package（发布数据包）、export SVG QA view（导出 SVG 审查图）、refresh viewer SVG（刷新网页 SVG）。`[完成: 2026-06-05]`

目标：每次点击都是一次可审计的专业操作，而不是盲改。

## 阶段四：强化 Road-chain Upgrade（道路链升级）

road-chain（道路链 / 连续路段）是系统里非常关键的概念。真实道路升级不能只看单条 edge（边），应该看 corridor（道路走廊）。

建议规则：

1. arterial_chain_lane_consistency（主干路车道一致性）。`[完成: 2026-06-06]` 已在 `/api/road-chain/lookup`（道路链查询接口）和 Road-chain Review（道路链审查）面板中实现；规则名保留为 arterial（主干路），但实际按 corridor（道路走廊）审查 residential / service（居住 / 服务道路）等非主干链的一致性。
2. short_edge_absorption（短边吸收相邻主路语义）。`[完成: 2026-06-06]` 已识别 15m 以下 short edge（短边），并判断是否已经吸收到相邻 corridor lane semantics（走廊车道语义）。
3. junction_approach_continuity（路口入口连续性）。`[完成: 2026-06-06]` 已对接 lane_graph（车道图）的 approach_lanes（入口车道）和 semantic_through_pairs（语义直行对），只读复核入口 / 出口车道连续性。
4. lane_count_transition_review（车道数变化复核）。`[完成: 2026-06-06]` 已检查同一 road-chain（道路链）内部连续 edge（边）的 physical lane count（物理车道数）变化。
5. Road-chain Review（道路链审查）保持 review_only_no_geometry_mutation（只审查不修改几何），不会直接写 transaction（事务）或改 package（数据包）。`[完成: 2026-06-06]`

目标：从 single road upgrade（单路段升级）升级为 corridor-level upgrade（道路走廊级升级）。

## 阶段五：推进 Propagation（传播规则）

当前 propagation planning（传播规划）保持 proposal-only（只提建议）是正确的；propagation application（传播应用）必须通过受控脚本逐条执行，继续保持可审计。

下一步做半自动：

1. high confidence candidates（高置信候选）可批量入队 review queue（审查队列），但执行时仍逐条确认和记录 transaction（事务记录）。`[完成: 2026-06-05]` viewer（网页查看器）已支持 dry-run preview（试运行预览）和 enqueue（入队）；入队只记录 review intent（复核意图），不会应用 geometry（几何）。
2. medium confidence candidates（中置信候选）在 viewer（网页查看器）中高亮等待人工确认。`[完成: 2026-06-05]`
3. low confidence candidates（低置信候选）只记录，不自动推荐。`[完成: 2026-06-05]`
4. 每个 candidate（候选项）必须说明 source（来源）、target（目标）、reason（原因）、risk（风险）。`[完成: 2026-06-05]`
5. 新增 Propagation Review（传播审查）只读面板：按 selected road / road-chain（选中道路 / 道路链）过滤 candidate（候选项），显示 global status（全局状态）、rule counts（规则计数）、confidence tier（置信层级）和 risk policy（风险策略）。`[完成: 2026-06-05]`
6. 新增 propagation_review_queue（传播审查队列）数据模型和 `/api/propagation/review-queue/enqueue`（传播审查队列入队接口）；queue item（队列项）记录 plan version（计划版本）、candidate id（候选编号）、target road（目标道路）和 manual review contract（人工复核契约）。`[完成: 2026-06-05]`

目标：让系统帮你加速，但不越权。

## 阶段六：优化 Junction Semantics（路口语义）

lane upgrade（车道升级）真正难点在 junction（路口）。

建议新增 QA checks（质量检查项）：

1. junction_lane_count_balance_check（路口车道数平衡检查）。`[完成: 2026-06-06]` 已在 `/api/junction/lookup`（路口查询接口）和 Junction Review（路口审查）面板中实现，检查 approach_lanes（入口车道）的 incoming / outgoing（入口 / 出口）平衡。
2. approach_exit_lane_compatibility_check（入口 / 出口车道兼容检查）。`[完成: 2026-06-06]` 已按 movement（通行关系）检查 from approach（来源入口）到 to exit（目标出口）的 laneLinks（车道连接）容量兼容。
3. turn_curve_radius_review（转弯半径复核）。`[完成: 2026-06-06]` 已基于 laneLink connecting_curve_xz（车道连接曲线坐标）估算 min radius（最小半径），低于阈值时进入 manual_review_required（需要人工复核）。
4. lane_link_conflict_check（车道连接冲突检查）。`[完成: 2026-06-06]` 已检查 duplicate lane_link_id（重复车道连接编号）和 ambiguous / duplicate lane targets（重复或过多目标）。
5. orphan_lane_link_check（孤立车道连接检查）。`[完成: 2026-06-06]` 已检查 laneLinks（车道连接）是否引用 lane_graph（车道图）中存在的 from_lane / to_lane（来源 / 目标车道）。
6. Junction Review（路口审查）保持 review_only_no_geometry_mutation（只审查不修改几何）；当前 `rc_27443571`（道路链）验证结果为 7 个 junction（路口）、42 条 laneLinks（车道连接），4 项通过，turn_curve_radius_review（转弯半径复核）需要人工复核。`[完成: 2026-06-06]`

目标：不仅 road segment（路段）像真实道路，junction（路口）也要可驾驶、可解释。

## 阶段七：治理 Package Lifecycle（数据包生命周期）

现在已经到 `lane_package_v0166`，说明迭代很快，需要版本治理。

要做：

1. 标记 milestone package（里程碑数据包）。`[完成: 2026-06-06]` 已新增 Package Lifecycle（数据包生命周期）只读面板和 milestone_candidate（里程碑候选）输出；当前 `lane_package_v0166` 是 review_candidate_manual_review_required（需要人工复核的里程碑候选），不是 stable handoff milestone（稳定交付里程碑）。
2. 维护 package changelog（数据包变更日志）。`[完成: 2026-06-06]` 已新增 `package_changelog.json`（数据包变更日志注册文件），并登记 `lane_package_v0166` 相对 `lane_package_v0165` 的 source artifact hash diff（源资产哈希差异）。
3. 每个 package（数据包）记录与上一版的 diff summary（差异摘要）。`[完成: 2026-06-06]` 已在 `/api/package-lifecycle/lookup`（数据包生命周期查询接口）中返回 latest vs previous（最新 vs 上一版）的 count diff（计数差异）、source artifact hash diff（源资产哈希差异）和 latest changelog coverage（最新变更日志覆盖）。
4. 旧 experimental package（实验包）归档。`[完成: 2026-06-06]` 已新增 archive_review（归档复核）输出；当前 165 个 package（数据包）中，按 keep latest 12（保留最近 12 个）策略有 153 个 archive candidate（归档候选），但不会自动删除。
5. latest pointer（最新版本指针）只指向当前推荐版本。`[完成: 2026-06-06]` 已新增 latest_pointer_consistency（最新指针一致性）检查；当前 latest pointer（最新指针）正确指向最高版本 `lane_package_v0166`。
6. Package Lifecycle（数据包生命周期）保持 review_only_no_package_mutation（只审查不修改数据包）；当前已补齐 changelog registry（变更日志注册）和 milestone registry（里程碑注册），但 stable handoff（稳定交付）仍需等 QA / semantic review / Houdini import checks（质量 / 语义 / Houdini 导入检查）通过后再提升。`[完成: 2026-06-06]`
7. 新增 package registry coverage checks（数据包注册覆盖率检查）：`package_changelog_latest_coverage`（最新数据包变更日志覆盖）、`milestone_candidate_registry`（里程碑候选注册）、`stable_handoff_milestone_readiness`（稳定交付里程碑就绪度）。`[完成: 2026-06-06]`

目标：让版本增长不变成维护负担。

## 阶段八：稳定 Houdini Handoff（Houdini 交付）

Houdini（程序化建模工具）继续只读 package manifest（数据包清单）和 houdini_manifest（Houdini 清单）。

要做：

1. 增加 compatibility version（兼容版本）。`[完成: 2026-06-06]` 已在后续 package builder（数据包构建器）中为新发布包写入 `laneforge_houdini_handoff.v1`（LaneForge Houdini 交付兼容版本）；当前 `lane_package_v0166` 是旧包，只读门禁会提示 compatibility version missing（兼容版本缺失），不会回写已发布数据包。
2. 增加 asset hash（资产哈希）。`[完成: 2026-06-06]` 已新增 Houdini Handoff Gate（Houdini 交付门禁）校验 `package_artifacts`（数据包资产记录）的 sha256（哈希）与实际输入文件一致；后续新包会把 input_asset_hashes（输入资产哈希）写进 `houdini_manifest.json`（Houdini 清单）。
3. 增加 missing file check（缺失文件检查）。`[完成: 2026-06-06]` 已检查 `standard_lanes.json`、`standard_junctions.json`、`standard_lane_surfaces.geojson`、`standard_lane_surfaces.obj` 四个 Houdini input（Houdini 输入）是否存在。
4. 增加 Houdini import QA report（Houdini 导入质量报告）。`[完成: 2026-06-06]` 已新增 `reports/pattaya_central_500m_houdini_handoff_report.json`（Houdini 交付报告）和 `/api/houdini-handoff/lookup`（Houdini 交付查询接口）；当前 import QA（导入质量）是 `houdini_import_not_run`，因为最近 rebuild（重建）是 `--skip-houdini`（跳过 Houdini）。
5. 新增 viewer（网页查看器）Houdini Handoff（Houdini 交付）只读面板。`[完成: 2026-06-06]` 面板显示 package（数据包）、compatibility（兼容）、input hashes（输入哈希）、import QA（导入质量）和 stable handoff readiness（稳定交付就绪度）。

目标：LaneForge（道路升级系统）发布什么，Houdini（程序化建模工具）就稳定构建什么。

## 近期执行顺序

1. 先用 viewer（网页查看器）人工审主干 road-chain（道路链）。
2. 每次只应用一个 road（道路）或一个 road-chain（道路链）。
3. 应用后检查 QA gate（质量门禁）、lane graph（车道图）、junction laneLinks（路口车道连接）。
4. 把重复的人为判断沉淀成 propagation rule（传播规则）。
5. 继续扩展 before/after preview（前后预览），加入更细的 laneLinks / surface diff（车道连接 / 车道面差异）。`[完成: 2026-06-05]` rollback UI（回滚界面）已具备基础入口。
6. 最后完善 semantic evidence（语义证据）和 package lifecycle（数据包生命周期）。
