---
description: 指导和检查 VirtualCity 的 Houdini MVP 城市生成流程
---

# Houdini MVP 工作流

当用户要求“搭建 Houdini MVP”“检查 Houdini 生成”“生成道路建筑”“导出 HDA 或静态资产”时，使用本工作流。

## 1. 必读文件

执行前读取：

1. `项目管理/project_manifest.json`
2. `项目管理/04_稳定流程规范.md`
3. `项目管理/07_MVP_QA检查清单.md`
4. `配置/pipeline_config.template.json`
5. 对应的 `项目管理/区域记录/{area_id}.md`，如果已存在
6. `Houdini/README.md`
7. `Houdini/Hip/README.md`
8. `Houdini/HDA/README.md`
9. `Houdini/Export/README.md`

## 2. 适用阶段

优先适用于：

- `mvp_houdini`
- `pipeline_standardization`

如果当前仍是 `mvp_preparation`，先确认是否已满足 Gate 1：数据可复现。

## 3. 输入条件

进入 Houdini 阶段前应具备：

- bbox 已记录。
- OSM 文件已保存。
- 数据来源已记录。
- 坐标系已确认或标记为待确认。
- DEM 使用状态明确。

## 4. Houdini MVP 目标

第一轮 MVP 只追求白盒城市区块可生成：

- OSM 道路能导入并生成基础路面。
- 建筑轮廓能拉伸成体量。
- 地形可使用平面或 DEM，高级地形细节可后置。
- 输出节点命名清晰。
- 可导出 HDA、HDALC 或静态资产。

## 5. 推荐输出节点

根据 `pipeline_config.template.json`，优先保持以下输出：

- `OUT_buildings`
- `OUT_roads`
- `OUT_landscape`
- `OUT_points`
- `OUT_debug`

## 6. 推荐关键参数

至少记录：

- `building_height_multiplier`
- `default_floor_height`
- `default_levels_min`
- `default_levels_max`
- `road_width_multiplier`
- `terrain_resolution`
- `preview_lod`
- `random_seed`

## 7. 执行步骤

1. 确认 area_id 和输入数据状态。
2. 判断是否满足 Gate 1。
3. 检查或规划 Houdini `.hip` 文件路径。
4. 检查 OSM 导入方式。
5. 检查道路、建筑、地形的基础生成结果。
6. 检查输出节点命名。
7. 检查是否可以保存 HDA 或导出静态资产。
8. 记录关键参数到区域记录。
9. 判断是否满足 Gate 2：Houdini 可生成。
10. 必要时建议更新当前状态和迭代日志。

## 8. Gate 2 判定

进入 UE5 阶段前必须满足：

- 道路、建筑体量可见。
- 道路和建筑没有明显错位。
- 关键参数可调。
- HDA 或静态导出文件存在。

## 9. 禁止事项

- 不得覆盖已有 `.hip`、`.hda`、`.hdalc` 文件，除非用户明确确认。
- 不得删除 Houdini 输出目录下已有资产。
- 不得在 MVP 阶段主动扩展复杂 City Sample 级系统。
- 不得在没有数据依据时伪造建筑高度、道路宽度或坐标转换结果。
- 不得优先开发大型自研 Houdini 工具。

## 10. 输出格式

最终输出：

# Houdini MVP 检查结论

## 是否满足 Gate 2

## 输入数据状态

## 节点网络状态

## 输出节点状态

## HDA / 静态导出状态

## 关键参数记录

## 阻塞项

## 下一步建议

## 11. 执行后复盘

任务结束后检查：

1. Houdini 参数是否需要固化进模板。
2. 输出节点是否需要调整命名规范。
3. 是否存在重复操作，未来可进入自动化。
4. 是否需要更新本 workflow。

如需修改本 workflow，先提出建议，等待用户确认。
