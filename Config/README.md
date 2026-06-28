# 配置

> 本目录存放 WorldBuilder 后续自动化和持续迭代所需的机器可读配置。  
> Markdown 文档负责解释流程，JSON 配置负责让 AI / 脚本读取和执行。

---

## 目录内容

```text
Config/
├── README.md
├── area_config.template.json       ← 区域配置模板
├── pipeline_config.template.json   ← 管线配置模板
├── qa_checklist.template.json      ← QA 检查清单模板
├── active_area.json                ← 当前 Houdini 主线区域状态
├── houdini_build_status.json       ← 当前 Houdini 构建状态（运行时输出）
├── road_profiles.json              ← 道路截面参数
├── road_curb_variation.json        ← 路缘细节参数
└── qa/                             ← 区域 QA 快照
```

---

## 使用原则

- 新增区域时，复制 `area_config.template.json` 为 `{area_id}.area.json`。
- 调整管线参数时，复制 `pipeline_config.template.json` 为 `{pipeline_name}.pipeline.json`。
- 每轮生成后，可基于 `qa_checklist.template.json` 记录检查结果。
- 配置文件只保存可复用参数和小型状态快照，不保存大型数据或二进制资产。
- `active_area.json` 是主线构建的当前区域，`houdini_build_status.json` 是最近一次 Houdini 构建状态；二者必须用 `area_id` / `run_id` 交叉确认后再作为“当前完成状态”。

---

## 与文档的关系

| 文档 | 配置 |
|---|---|
| `ProjectManagement/区域记录/{area_id}.md` | `{area_id}.area.json` |
| `ProjectManagement/04_稳定流程规范.md` | `pipeline_config.template.json` |
| `ProjectManagement/05_自动迭代协议.md` | `qa_checklist.template.json` |

---

## 当前状态

当前目录已经包含主线自动化所需的运行状态和小型 QA 快照。大型原始数据、Houdini ready 数据、模型 QA 报告和导出资产仍应放在 `RawData/`、`Reports/`、`Houdini/Export/` 等专用目录，并按 `.gitignore` 管理。
