# VirtualCity 工程根目录

> **Git 仓库**：`https://github.com/youknowytt101/VirtualCity.git`  
> 新机器首次使用：`git clone https://github.com/youknowytt101/VirtualCity.git`

> AI / 新成员接手项目时，先阅读根目录：`AI_HANDOFF.md`。  
> 然后阅读：`项目管理/00_AI接手指南.md`。  
> 当前状态和下一步见：`项目管理/02_当前状态与下一步.md`。

## 目录结构

```
VirtualCity/
├── README.md                  ← 本文件
├── AI_HANDOFF.md              ← AI / 人类接手第一入口
├── VirtualCity完整执行计划.md   ← 当前完整执行计划
├── 执行方案.md                  ← 早期可执行方案
│
├── 项目管理/                   ← AI 接手、状态、迭代日志、稳定流程
│   ├── 00_AI接手指南.md
│   ├── 01_资料地图.md
│   ├── 02_当前状态与下一步.md
│   ├── 03_迭代日志.md
│   ├── 04_稳定流程规范.md
│   ├── 05_自动迭代协议.md
│   ├── 06_任务记录模板.md
│   ├── 07_MVP_QA检查清单.md
│   ├── 08_任务看板.md
│   ├── 09_决策记录.md
│   ├── 10_AI启动自检清单.md
│   ├── 11_版本路线图.md
│   ├── project_manifest.json
│   ├── document_index.json
│   └── 区域记录/
│
├── Config/                       ← 机器可读配置模板
│   ├── area_config.template.json
│   ├── pipeline_config.template.json
│   └── qa_checklist.template.json
│
├── 调研文档/                   ← 行业调研文档
│   ├── README.md
│   └── 地图API-Houdini-UE流程/
│       ├── 01_地图数据获取与API对比.md
│       ├── 02_Houdini处理流程.md
│       ├── 03_UE5整合方案.md
│       ├── 04_完整流程速查表.md
│       ├── 05_虚拟城市主流技术方案.md
│       ├── 06_路线一详细拆解_Houdini+UE5城市管线.md
│       └── 07_补充优化建议_2026版.md
│
├── RawData/                   ← OSM / DEM / Overture 原始与缓存数据
│   ├── OSM/                   ← 区域道路与兜底建筑 .osm
│   ├── DEM/                   ← FABDEM / NASADEM CSV 与 GeoTIFF
│   ├── Overture/              ← Overture 建筑轮廓 GeoJSON
│   ├── _clip_cache/           ← 区域裁切缓存
│   └── _houdini_ready/        ← Houdini 输入中间结果（不提交）
│
├── Houdini/                   ← Houdini 工程、区域 hip、导出资产
│   ├── Hip/
│   ├── HDA/
│   └── Export/
│
├── Scripts/                 ← 数据获取、清洗、Houdini recook、QA 自动化
│   ├── 插件清单.md
│   ├── 工具开发规范.md
│   ├── 数据处理自动化/
│   ├── Houdini自动化/
│   └── UE5自动化/
│
└── UE5/                       ← Unreal Engine 5 工程
    └── （UE5 项目文件夹）
```

## 核心流程

```
area_picker.py (Leaflet 网页框选 / 用户级入口)
    ↓
set_area.py (区域状态 + 数据获取)
    ↓
refine_data.py (数据清洗 + 数据 QA)
    ↓
_recook_new_area.py (Houdini 自动构建)
    ↓
houdini_model_qa.py (模型 QA)
    ↓
人工审核 Houdini OUT_city
    ↓
export_and_import.py (审核后再进入 UE5)
```

## AI 快速入口

- AI 接手指南：`项目管理/00_AI接手指南.md`
- 当前状态与下一步：`项目管理/02_当前状态与下一步.md`
- 资料地图：`项目管理/01_资料地图.md`
- 迭代日志：`项目管理/03_迭代日志.md`
- 稳定流程规范：`项目管理/04_稳定流程规范.md`
- 自动迭代协议：`项目管理/05_自动迭代协议.md`
- 任务记录模板：`项目管理/06_任务记录模板.md`
- MVP QA 检查清单：`项目管理/07_MVP_QA检查清单.md`
- 任务看板：`项目管理/08_任务看板.md`
- 决策记录：`项目管理/09_决策记录.md`
- AI 启动自检清单：`项目管理/10_AI启动自检清单.md`
- 版本路线图：`项目管理/11_版本路线图.md`
- 机器可读项目清单：`项目管理/project_manifest.json`
- 机器可读文档索引：`项目管理/document_index.json`
- 配置模板目录：`Config/README.md`

## 计划与调研快速入口

- 完整执行计划：`VirtualCity完整执行计划.md`
- 早期可执行方案：`执行方案.md`
- 自动化预留规划：`Scripts/README.md`
- 自动化必要性判断：`Scripts/插件清单.md`
- 完整流程速查：`调研文档/地图API-Houdini-UE流程/04_完整流程速查表.md`
- 管线详细拆解：`调研文档/地图API-Houdini-UE流程/06_路线一详细拆解_Houdini+UE5城市管线.md`
- 2026 版补充优化：`调研文档/地图API-Houdini-UE流程/07_补充优化建议_2026版.md`

## 当前项目阶段

当前阶段：**Houdini 资产质量快速迭代**。

最终目标是俯视角虚拟城市构建。当前重点不是最终整合输出，而是稳定并优化：

```text
数据获取 → 数据清洗 → Houdini 自动构建 → Model QA → 人工视口审核
```

最新稳定主入口：

```bash
cd Scripts
uv run python area_picker.py
```

“重新测试 / 从头测试 / 全流程测试”必须从 `area_picker.py` 网页入口开始，并以 Houdini build status + Model QA 通过作为结束条件。当前 UE5 导出导入仍放在 Houdini 视口审核之后手动触发。
