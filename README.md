# VirtualCity

VirtualCity is a local pipeline for building a top-down virtual city from real
map data. The current product surface is the local area picker / control room,
but the core project is the reproducible asset pipeline:

```text
area picker -> data acquisition/cache -> data cleaning/QA -> Houdini build -> Model QA -> human review -> UE5 export
```

## Current Truth

Last updated: 2026-06-24

- Current phase: Houdini asset-quality iteration.
- Current active area: `z47n_e702000_n1428000_w1000_h1000_s1000`.
- Latest Houdini build: completed.
- Latest Model QA: failed, `11 pass / 0 warn / 2 fail`.
- Failing checks: `building_terrain_fit`, `road_terrain_fit`.
- UE5 export/import is still an audited exit, not the default pipeline end.

Do not treat the current browser UI, orbit preview, or old demo output as the
design target. The design target is a stable, repeatable city-generation
pipeline with clear QA gates.

## Read First

Use these documents as the active source of truth:

| Need | File |
|---|---|
| Current handoff | `AI_HANDOFF.md` |
| AI/new-member startup | `ProjectManagement/00_AI接手指南.md` |
| Document map | `ProjectManagement/01_资料地图.md` |
| Current status | `ProjectManagement/02_当前状态与下一步.md` |
| Task board | `ProjectManagement/08_任务看板.md` |
| Stable workflow | `ProjectManagement/04_稳定流程规范.md` |
| Architecture boundary | `ProjectManagement/14_三大模块架构边界.md` |
| Known Houdini pitfalls | `ProjectManagement/12_已知坑点与解决方案.md` |

Older plans and research are retained for traceability, but they are not the
current operating instructions unless one of the files above points to them.

## Main Command

Start the user-facing control room:

```powershell
cd Scripts
uv run python area_picker.py
```

When someone says "重新测试", "从头测试", "全流程测试", or "测试自动化管线",
the test must start from `Scripts/area_picker.py` and must end with both:

- `Config/houdini_build_status.json` for the same `area_id` / `run_id`
- `Reports/model_qa/latest.json` for the same `area_id` / `run_id`

`qa_status=fail` means the pipeline ran, but the output is not promotable.

## Architecture

The active architecture is three modules:

```text
数据获取 / 下载 / 缓存
    -> 数据清洗 / 语义 / QA
    -> Houdini 构建 / Model QA / 审核出口
```

Primary implementation boundaries:

| Module | Main files | Outputs |
|---|---|---|
| Acquisition | `Scripts/acquisition/`, `Scripts/app/area_picker/` | `RawData/OSM/`, `RawData/DEM/`, `RawData/Overture/`, `RawData/_tiles/`, `RawData/_clip_cache/` |
| Cleaning | `Scripts/cleaning/`, `Scripts/shared/`, `Scripts/data_cleaning_cache.py` | `RawData/_cleaned/`, `RawData/_houdini_ready/`, `Config/qa/` |
| Houdini build | `Scripts/houdini_build/`, `Scripts/houdini_sops/`, `Scripts/houdini_model_qa.py` | `Houdini/Hip/`, `Reports/model_qa/`, `Houdini/Export/` |

Compatibility wrappers remain in `Scripts/` root. New work should use the
physical module locations above.

## Repository Map

```text
Config/              machine-readable area, pipeline, QA, and runtime status
RawData/             source data, cache, cleaned data, Houdini-ready data
Scripts/             acquisition, cleaning, Houdini build, QA, UE5 helpers
Houdini/             master/area HIP files, HDA placeholder, exports
UE5/                 Unreal project and launch helper
ProjectManagement/   active handoff docs, board, decisions, logs, research index
Reports/             pipeline run reports, Model QA, build history
调研文档/             research archive, not day-to-day operating state
```

## What Not To Prioritize Now

- Full City Sample recreation.
- Mass AI / complex traffic.
- Whole-city or nationwide datasets.
- New plugin framework.
- UE5 polish before Houdini output passes QA and human review.
