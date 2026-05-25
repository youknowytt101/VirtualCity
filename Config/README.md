# 配置

> 本目录存放 VirtualCity 后续自动化和持续迭代所需的机器可读配置。  
> Markdown 文档负责解释流程，JSON 配置负责让 AI / 脚本读取和执行。

---

## 目录内容

```text
Config/
├── README.md
├── area_config.template.json       ← 区域配置模板
├── pipeline_config.template.json   ← 管线配置模板
└── qa_checklist.template.json      ← QA 检查清单模板
```

---

## 使用原则

- 新增区域时，复制 `area_config.template.json` 为 `{area_id}.area.json`。
- 调整管线参数时，复制 `pipeline_config.template.json` 为 `{pipeline_name}.pipeline.json`。
- 每轮生成后，可基于 `qa_checklist.template.json` 记录检查结果。
- 配置文件只保存可复用参数，不保存大型数据或二进制资产。

---

## 与文档的关系

| 文档 | 配置 |
|---|---|
| `项目管理/区域记录/{area_id}.md` | `{area_id}.area.json` |
| `项目管理/04_稳定流程规范.md` | `pipeline_config.template.json` |
| `项目管理/05_自动迭代协议.md` | `qa_checklist.template.json` |

---

## 当前状态

当前目录只提供模板。等第一个 MVP 区域确定后，再创建真实区域配置。
