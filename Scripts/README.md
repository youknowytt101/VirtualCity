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
pipeline_state.py（生成 run_id，持续记录阶段状态）
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
| `area_picker.py` | Leaflet 网页框选固定 1km UTM 网格块，触发完整管线，监控流程状态 |
| `set_area.py` | 更新 `active_area.json`，获取 / 恢复 OSM、DEM、Overture 数据 |
| `pipeline_state.py` | 为每次完整构建生成 `run_id`，写入 `Reports/pipeline_runs/` 运行清单 |
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
- `active_area.json`、Houdini build status、数据 QA 和 Model QA 使用同一个 `run_id`。排查问题时优先查看 `Reports/pipeline_runs/latest.json`。
- `refine_data.py` 只在 QA 通过后发布 `_houdini_ready/{area_id}`；失败时保留上一版可用数据。
- `area_picker.py` 在 `http://localhost:8765/health` 暴露服务版本。重复启动会复用同版本服务，检测到旧版服务则拒绝继续，避免误跑旧代码。
- `area_picker.py` 默认用矩形工具框选固定 1km x 1km UTM 基础格；框选结果会吸附并补齐成连续矩形网格块，`/run` 接受 `tile_ids` 后由服务端重新计算 bbox。
- 网页缓存状态只保留两类：未缓存网格无填充，三类原始数据可本地恢复的网格显示半透明蓝色；“只显示已有缓存”复选框用于筛选。
- Houdini 边界处理只做完整资产过滤：建筑/地基按连通块保留，道路按完整面片保留，禁止把边界过渡区资产切成半截。
- 完成后区域选择器默认保留页面和 `/status` 状态接口；手动按 `Ctrl+C` 退出。仅在设置 `VC_AREA_PICKER_AUTO_SHUTDOWN=1` 时恢复自动关闭。
- UE5 导出导入不是当前默认测试终点，必须等 Houdini 视口审核通过后再运行。

---

## 目录说明

```text
Scripts/
├── README.md
├── area_picker.py
├── set_area.py
├── pipeline_state.py
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
