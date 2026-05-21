---
description: AI 接手 VirtualCity 项目并继续迭代
---

# AI 接手 VirtualCity 工作流

当用户要求“继续”“接着做”“查看项目状态”“自动迭代”时，按以下步骤执行。

## 1. 先读项目入口

读取以下文件：

1. `项目管理/00_AI接手指南.md`
2. `项目管理/02_当前状态与下一步.md`
3. `项目管理/01_资料地图.md`
4. `项目管理/project_manifest.json`

## 2. 判断当前阶段

根据 `02_当前状态与下一步.md` 和 `project_manifest.json` 判断当前阶段：

- `mvp_preparation`：准备数据和环境。
- `mvp_houdini`：正在搭建 Houdini MVP 网络。
- `mvp_ue5`：正在导入 UE5 和 Bake。
- `pipeline_standardization`：正在固化流程和自动化。

## 3. 只做当前阶段必要工作

MVP 前不要主动推进以下内容：

- 完整 City Sample 复刻。
- 大型自研插件。
- Mass AI。
- 复杂交通系统。
- 全国或整城级数据。

## 4. 每次完成后更新状态

阶段性任务完成后，更新：

- `项目管理/02_当前状态与下一步.md`
- `项目管理/03_迭代日志.md`
- 必要时更新 `项目管理/project_manifest.json`

## 5. 新区域必须建记录

如果用户选择了新测试区域，在 `项目管理/区域记录/` 下创建 `{area_id}.md`，并记录：

- bbox。
- 数据来源。
- 坐标系。
- OSM / DEM 路径。
- Houdini 参数。
- UE5 输出。
- QA 结果。

## 6. 优先建议下一步

如果用户只说“继续”，且没有更具体要求，优先检查：

1. 是否已有 MVP bbox。
2. 是否已有 OSM 文件。
3. 是否已有 Houdini `.hip`。
4. 是否已有 UE5 `.uproject`。

根据缺失项推进下一步。
