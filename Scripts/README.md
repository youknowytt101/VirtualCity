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

也可以在项目根目录双击 `启动VirtualCity操作台.cmd`。它会检查 Houdini RPYC 端口并自动打开本地网页操作台。

当前完整流程：

```text
area_picker.py
    ↓
orchestration/run_pipeline.py（完整管线编排）
    ↓
acquisition/set_area.py --acquire-only
    ↓
orchestration/pipeline_state.py（生成 run_id，持续记录阶段状态）
    ↓
cleaning/refine_data.py
    ↓
houdini_build/recook_new_area.py
    ↓
houdini_model_qa.py --mode quick
    ↓
人工审核 Houdini OUT_city
    ↓
export_and_import.py（审核后）
```

注意：

- `area_picker.py` 是用户级入口。
- `orchestration/run_pipeline.py` 是完整构建的正式编排入口。
- `acquisition/set_area.py --acquire-only` 是数据获取 / 缓存入口；`acquisition/set_area.py --data-only` 只下载数据且不切换主线区域。
- `set_area.py` 是旧命令兼容 wrapper；不带参数模式仍保留旧完整流程兼容，但新自动化应优先调用 `orchestration/run_pipeline.py`。
- `houdini_build/recook_new_area.py` 是 Houdini 当前区域重构入口，只消费已发布的 `_houdini_ready`。
- `houdini_model_qa.py` 是 Houdini 输出后的自动模型审查工具。

当用户说“重新测试 / 从头测试 / 全流程测试”时，默认必须从 `area_picker.py` 开始，不能只运行 `houdini_build/recook_new_area.py`。

---

## 三大模块边界

当前主线按三大模块理解和验收：

| 模块 | 当前脚本 / 目录 | 交付物 | 说明 |
|---|---|---|---|
| 数据获取 / 下载 / 缓存 | `acquisition/set_area.py`, `area_picker.py`, `download_osm.py`, `download_dem.py`, `download_overture_buildings.py`, `_tile_cache.py` | `RawData/OSM/`, `RawData/DEM/`, `RawData/Overture/`, `RawData/_tiles/`, `RawData/_clip_cache/` | 缓存优先，缺失下载；`data-only` 只到这一层 |
| 数据清洗 / 语义 / QA | `cleaning/refine_data.py`, `clean_raw_data.py`, `data_cleaning_cache.py`, `shared/vc_geo.py`, `shared/vc_schema.py`, `shared/vc_buildings.py` | `RawData/_cleaned/{area_id}/`, `RawData/_houdini_ready/{area_id}/`, `Config/qa/*.json` | QA 通过后才发布 Houdini-ready；失败保留上一版 |
| Houdini 构建 / Model QA / 审核出口 | `houdini_build/recook_new_area.py`, `houdini_sops/`, `_osm_import_canonical.py`, `houdini_sops/road_capsule_surface_preview.py`, `houdini_model_qa.py`, `export_and_import.py` | `Houdini/Hip/*.hip`, `Reports/model_qa/*.json`, `Houdini/Export/*.fbx` | Houdini 只应消费 `_houdini_ready`；导出必须在人工审核后 |

重要判断：

- 业务流程已经是三大块。
- 核心执行入口已经物理分层：`acquisition/`、`cleaning/`、`houdini_build/`。
- Houdini 构建内部按资产域分层：`terrain` 是底座，`buildings` / `roads` 依赖地形，`nature` 当前为 no-op 占位，最后统一进入 `assembly` / `OUT_city`。
- 对外仍保持一个自动构建入口：`orchestration/run_pipeline.py` 调用 `houdini_build/recook_new_area.py`。不要把四个资产域拆成四个会分别写 `active_area` / status / hip 的独立命令。
- `Scripts/set_area.py`、`Scripts/refine_data.py`、`Scripts/_recook_new_area.py` 是兼容 wrapper，不是新实现位置。
- 坐标、路径、语义契约和纯建筑清洗已经迁入 `shared/`；根目录同名文件只作为兼容 wrapper。
- 共享辅助脚本和部分数据 / Houdini 工具仍保留在 `Scripts/` 根目录，后续可继续迁到对应模块。

详细口径见 `ProjectManagement/14_三大模块架构边界.md`。

---

## 关键脚本

| 脚本 | 职责 |
|---|---|
| `area_picker.py` | 用户级兼容入口，转发到 `app/area_picker/server.py` |
| `app/area_picker/server.py` | Leaflet 网页框选固定 1km UTM 网格块，触发完整管线，监控流程状态 |
| `app/area_picker/template.py` | area picker 的 HTML / CSS / JS 模板 |
| `app/area_picker/software_paths.py` | Houdini / UE 等本机软件路径配置读写 |
| `orchestration/run_pipeline.py` | 显式编排数据获取、数据清洗、Houdini 构建三大模块 |
| `acquisition/set_area.py` | 更新 `active_area.json`，获取 / 恢复 OSM、DEM、Overture 数据；旧完整流程兼容入口由根目录 `set_area.py` 转发 |
| `orchestration/pipeline_state.py` | 为每次完整构建生成 `run_id`，写入 `Reports/pipeline_runs/` 运行清单 |
| `cleaning/refine_data.py` | 执行数据清洗、raw snapshot、缓存、数据 QA |
| `clean_raw_data.py` | 建筑、道路、DEM 的清洗逻辑 |
| `data_cleaning_cache.py` | 数据清洗 cache fingerprint 与复用 |
| `houdini_build/recook_new_area.py` | 通过 RPYC 驱动 Houdini SOP/VEX patch 与 recook；根目录 `_recook_new_area.py` 仅兼容旧命令 |
| `houdini_build/context.py` | Houdini 构建上下文：active area、run_id、颜色、刷新链和输出路径 |
| `houdini_build/preflight.py` | Houdini-ready 数据契约校验，确保只消费当前 area/run |
| `houdini_build/status.py` | 写入 `Config/houdini_build_status.json`，供 UI / export gate 读取 |
| `houdini_build/domains/` | 资产域注册表：地形、建筑、道路、自然占位、总装 |
| `_osm_import_canonical.py` | Houdini `osm_import` Python SOP 源码 |
| `houdini_sops/road_capsule_surface_preview.py` | 当前主道路面 SOP：从干净中线生成胶囊车道面，并通过 `road_surface_color` 进入 `OUT_city` |
| `_road_strips_v2.py` | 旧道路条带实验 SOP，保留供追溯，不再由当前主构建链创建 |
| `houdini_model_qa.py` | Houdini 模型 QA quick/full |
| `shared/vc_paths.py` | 项目路径统一入口，禁止硬编码盘符；根目录 `vc_paths.py` 仅兼容旧导入 |
| `export_and_import.py` | Houdini 审核后导出并触发 UE5 导入 |

---

## 当前 Houdini 道路链

道路中线和道路面分开维护：

```text
road_api_raw_lines
    -> road_api_shared_topology
    -> road_centerline_resample
    -> road_turn_curve_smooth
    -> road_vertex_cleanup
    -> road_junction_curve_smooth
    -> snap_road_strips / road_bbox_clip / snap_road_clipped
    -> road_clipped
    -> road_profile_apply
```

`road_color` 只给上面的干净中线写颜色，保留为调试输出；最终 `OUT_city` 的道路输入来自：

```text
road_profile_apply
    -> road_capsule_surface_preview
    -> road_surface_color
    -> merge_all
```

`road_surface_union_preview` 和 `road_surface_quad_preview` 已退出主流程，只保留在 legacy cleanup 名单中，避免 Houdini 自动构建后遗留旧节点。

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
- road_faces（检查 `road_surface_color` 胶囊道路面）
- road_clipped_lines（检查裁剪后的干净道路中线）
- road_profile_attrs
- road_terrain_fit

几何统计必须在 Houdini 进程内部完成，再返回 JSON。不要通过 RPYC 在本地逐点/逐面读取大几何。

---

## 工作约束

- 自动化脚本禁止硬编码 `F:/VirtualCity`、`D:/VirtualCity`、`E:/VirtualCity` 等机器专属路径，统一使用 `vc_paths.py`。
- Windows 控制台关键状态优先使用 `[OK] / [WARN] / [FAIL]`，避免 emoji 导致 GBK 编码崩溃。
- Houdini RPYC 默认端口为 `18811`。
- 同一时间只运行一个完整管线，避免 `active_area.json` 和 Houdini status 被互相覆盖。
- `active_area.json`、Houdini build status、数据 QA 和 Model QA 使用同一个 `run_id`。排查问题时优先查看 `Reports/pipeline_runs/latest.json`。
- `Reports/pipeline_runs/latest.json` 表示最近一次管线动作，可能是 `data-only` 下载；不要把它直接等同于最近一次 Houdini 成功构建。判断 Houdini 可导出状态时必须同时检查 `Config/active_area.json`、`Config/houdini_build_status.json` 和 Model QA 报告的 `area_id` / `run_id`。
- `cleaning/refine_data.py` 只在 QA 通过后发布 `_houdini_ready/{area_id}`；失败时保留上一版可用数据。
- `_houdini_ready/{area_id}/ready_manifest.json` 是 Houdini 构建层的硬契约，必须匹配当前 `area_id` / `run_id` 和关键输出文件指纹。
- `houdini_build/recook_new_area.py` 不再兜底运行 `cleaning/refine_data.py`；preflight 未通过时直接失败，完整流程应从 `orchestration/run_pipeline.py` 启动。
- `area_picker.py` 在 `http://localhost:8765/health` 暴露服务版本。重复启动会复用同版本服务，检测到旧版服务则拒绝继续，避免误跑旧代码。
- `area_picker.py` 默认用矩形工具框选固定 1km x 1km UTM 基础格；框选结果会吸附并补齐成连续矩形网格块，`/run` 接受 `tile_ids` 后由服务端重新计算 bbox。
- `area_picker.py` 使用 OpenStreetMap 在线底图；数据获取仍然缓存优先，缺失时联网下载。
- 网页支持三个主要动作：`Houdini 生成` 跑完整管线，`导出 FBX` 只导出已通过 Model QA 的当前区域，`下载数据` 只准备 OSM / DEM / 建筑原始数据并写入缓存。
- 网页 Leaflet / Leaflet.draw 资源已本地化到 `Scripts/web_assets/`，避免依赖 CDN。
- Houdini Model QA 通过，并且当前 Houdini 会话中视口显示节点 `OUT_city` 仍存在且几何非空时，网页才会启用“导出 FBX”按钮；该按钮只导出 `Houdini/Export/*.fbx`，不会触发 UE5 导入。
- 网页缓存状态只保留两类：未缓存网格无填充，三类原始数据可本地恢复的网格显示半透明蓝色；“只显示已有缓存”复选框用于筛选。
- Houdini 边界处理只做完整资产过滤：建筑/地基按连通块保留，道路按完整面片保留，禁止把边界过渡区资产切成半截。
- 完成后区域选择器默认保留页面和 `/status` 状态接口；手动按 `Ctrl+C` 退出。仅在设置 `VC_AREA_PICKER_AUTO_SHUTDOWN=1` 时恢复自动关闭。
- UE5 导出导入不是当前默认测试终点，必须等 Houdini 视口审核通过后再运行。

---

## 目录说明

```text
Scripts/
├── README.md
├── area_picker.py            # compatibility entrypoint
├── app/
│   └── area_picker/
│       ├── server.py
│       ├── template.py
│       └── software_paths.py
├── orchestration/
│   ├── run_pipeline.py
│   └── pipeline_state.py
├── acquisition/
│   └── set_area.py
├── cleaning/
│   └── refine_data.py
├── houdini_build/
│   ├── recook_new_area.py
│   ├── context.py
│   ├── preflight.py
│   ├── status.py
│   └── domains/
├── set_area.py              # compatibility wrapper
├── pipeline_state.py        # compatibility alias
├── refine_data.py           # compatibility wrapper
├── _recook_new_area.py      # compatibility wrapper
├── houdini_model_qa.py
├── _osm_import_canonical.py
├── _road_strips_v2.py
├── vc_paths.py              # compatibility wrapper
├── vc_geo.py                # compatibility wrapper
├── vc_schema.py             # compatibility wrapper
├── vc_buildings.py          # compatibility wrapper
├── shared/
│   ├── vc_paths.py
│   ├── vc_geo.py
│   ├── vc_schema.py
│   └── vc_buildings.py
├── ue5/
├── houdini_sops/
└── _archive/
```

`_archive/` 中保留历史 one-off 修复、道路生成实验脚本和 legacy 入口，仅供追溯，不作为当前主流程入口。
