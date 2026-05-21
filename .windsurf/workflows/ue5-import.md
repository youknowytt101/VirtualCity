---
description: 指导和检查 VirtualCity 的 UE5 导入、Bake 和基础展示流程
---

# UE5 Import 工作流

当用户要求“导入 UE5”“检查 Houdini Engine”“Bake 资产”“创建展示关卡”“检查 UE5 导入结果”时，使用本工作流。

## 1. 必读文件

执行前读取：

1. `项目管理/project_manifest.json`
2. `项目管理/04_稳定流程规范.md`
3. `项目管理/07_MVP_QA检查清单.md`
4. `配置/pipeline_config.template.json`
5. 对应的 `项目管理/区域记录/{area_id}.md`，如果已存在
6. `UE5/README.md`
7. `Houdini/Export/README.md`

## 2. 适用阶段

优先适用于：

- `mvp_ue5`
- `pipeline_standardization`

如果当前仍是 `mvp_preparation` 或 `mvp_houdini`，先确认是否已满足 Gate 2：Houdini 可生成。

## 3. 输入条件

进入 UE5 阶段前应具备：

- Houdini 中道路和建筑体量可见。
- HDA、HDALC 或静态导出文件存在。
- 输出比例规则明确。
- Houdini 到 UE 的缩放规则明确。

默认单位策略参考：

- Houdini：`1 unit = 1 meter`
- UE：`1 Unreal unit = 1 centimeter`
- Houdini 到 UE 缩放：`100.0`

## 4. UE5 MVP 目标

第一轮 MVP 只追求导入、Bake 和可展示：

- UE5 项目存在。
- Houdini Engine for Unreal 可用，或静态资产可导入。
- 生成结果比例合理。
- Bake 后可脱离 Houdini 查看。
- Play 模式无严重报错。
- 至少能形成基础展示视角。

## 5. 推荐内容结构

参考 `pipeline_config.template.json`：

- UE5 项目：`UE5/VirtualCityUE/VirtualCityUE.uproject`
- 内容根目录：`Content/VirtualCity/`
- 关卡命名：`LV_{area_id}_MVP`
- Data Layer：
  - `DL_Terrain`
  - `DL_Roads`
  - `DL_Buildings`
  - `DL_Foliage`
  - `DL_Props`
  - `DL_Debug`

## 6. 执行步骤

1. 确认 area_id 和 Houdini 输出状态。
2. 判断是否满足 Gate 2。
3. 检查 UE5 项目路径。
4. 检查 Houdini Engine 或静态导入方式。
5. 检查比例和坐标是否合理。
6. 检查 Bake 是否成功。
7. 检查 Play 模式是否有严重报错。
8. 检查基础展示截图或展示视角是否具备。
9. 判断是否满足 Gate 3：UE5 可 Bake。
10. 必要时建议更新区域记录、当前状态和迭代日志。

## 7. Gate 3 判定

进入展示或复用阶段前必须满足：

- HDA 可导入 UE5，或静态资产可稳定导入。
- 生成结果比例正确。
- Bake 后可脱离 Houdini 查看。
- Play 模式无严重报错。

## 8. 禁止事项

- 不得覆盖 `.uproject` 文件。
- 不得删除 UE5 Content 下已有资产，除非用户明确确认。
- 不得在 MVP 阶段主动启用复杂 Mass AI 或完整交通系统。
- 不得把未验证的 Bake 状态写成成功。
- 不得伪造性能结果或截图结果。

## 9. 输出格式

最终输出：

# UE5 导入检查结论

## 是否满足 Gate 3

## UE5 项目状态

## 导入方式

## 比例和坐标状态

## Bake 状态

## Play / 展示状态

## 阻塞项

## 下一步建议

## 10. 执行后复盘

任务结束后检查：

1. UE5 目录规范是否需要更新。
2. Bake 流程是否需要固化。
3. 是否有重复操作可未来自动化。
4. 是否需要更新本 workflow。

如需修改本 workflow，先提出建议，等待用户确认。
