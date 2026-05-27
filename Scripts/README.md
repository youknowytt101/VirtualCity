# Scripts

> 本目录是 VirtualCity 当前自动化管线的核心目录。
> 这里不存放官方插件本体，只存放项目脚本、Houdini Python SOP 源码、QA 工具和 UE5 辅助脚本。

---

## 当前主流程

用户级完整测试入口：

```bash
cd Scripts
uv run python area_picker.py
```

当前完整流程：

```text
area_picker.py
    ↓
set_area.py
    ↓
refine_data.py
    ↓
_recook_new_area.py
    ↓
houdini_model_qa.py --mode quick
    ↓
人工审核 Houdini OUT_city
    ↓
export_and_import.py（审核后）
```

注意：

- `area_picker.py` 是用户级入口。
- `set_area.py` 是底层 bbox 命令入口。
- `_recook_new_area.py` 是 Houdini 当前区域重构入口。
- `houdini_model_qa.py` 是 Houdini 输出后的自动模型审查工具。

当用户说“重新测试 / 从头测试 / 全流程测试”时，默认必须从 `area_picker.py` 开始，不能只运行 `_recook_new_area.py`。

---

## 关键脚本

| 脚本 | 职责 |
|---|---|
| `area_picker.py` | Leaflet 网页框选区域，触发完整管线，监控流程状态 |
| `set_area.py` | 更新 `active_area.json`，获取 / 恢复 OSM、DEM、Overture 数据 |
| `refine_data.py` | 执行数据清洗、raw snapshot、缓存、数据 QA |
| `clean_raw_data.py` | 建筑、道路、DEM 的清洗逻辑 |
| `data_cleaning_cache.py` | 数据清洗 cache fingerprint 与复用 |
| `_recook_new_area.py` | 通过 RPYC 驱动 Houdini SOP/VEX patch 与 recook |
| `_osm_import_canonical.py` | Houdini `osm_import` Python SOP 源码 |
| `_road_strips_v2.py` | Houdini `road_strips` Python SOP 源码 |
| `houdini_model_qa.py` | Houdini 模型 QA quick/full |
| `vc_paths.py` | 项目路径统一入口，禁止硬编码盘符 |
| `export_and_import.py` | Houdini 审核后导出并触发 UE5 导入 |

---

## 当前 Model QA

`houdini_model_qa.py --mode quick` 当前检查：

- required_nodes
- terrain_density
- building_color
- footprint_bevel
- building_normals
- foundation_tags
- foundation_normals
- foundation_alignment
- building_terrain_fit
- road_faces
- road_terrain_fit

几何统计必须在 Houdini 进程内部完成，再返回 JSON。不要通过 RPYC 在本地逐点/逐面读取大几何。

---

## 工作约束

- 自动化脚本禁止硬编码 `F:/VirtualCity`、`D:/VirtualCity`、`E:/VirtualCity` 等机器专属路径，统一使用 `vc_paths.py`。
- Windows 控制台关键状态优先使用 `[OK] / [WARN] / [FAIL]`，避免 emoji 导致 GBK 编码崩溃。
- Houdini RPYC 默认端口为 `18811`。
- 同一时间只运行一个完整管线，避免 `active_area.json` 和 Houdini status 被互相覆盖。
- UE5 导出导入不是当前默认测试终点，必须等 Houdini 视口审核通过后再运行。

---

## 目录说明

```text
Scripts/
├── README.md
├── area_picker.py
├── set_area.py
├── refine_data.py
├── _recook_new_area.py
├── houdini_model_qa.py
├── _osm_import_canonical.py
├── _road_strips_v2.py
├── vc_paths.py
├── 数据处理自动化/
├── Houdini自动化/
├── UE5自动化/
└── _archive/
```

`_archive/` 中保留历史 one-off 修复和道路生成实验脚本，仅供追溯，不作为当前主流程入口。
