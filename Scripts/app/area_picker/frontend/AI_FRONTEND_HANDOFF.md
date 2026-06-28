# AI Frontend Handoff

Use `AI_FRONTEND_HANDOFF.md` first when a user reports a frontend problem. It maps user-facing symptoms to the smallest useful code surface, backend route, and test. Keep this file aligned with `API_CONTRACT.md` when adding or moving frontend behavior.

## Fast Symptom Map

| User description | Feature domain | Start with | Key symbols | Backend route | Guard test |
|---|---|---|---|---|---|
| 白盒预览不显示, 白盒预览不刷新, 预览加载失败 | Houdini preview | `houdini_preview.js` | `VC_HOUDINI_PREVIEW.update`, `loadWhitebox`, `computeTerrainPreviewPivot` | `/whitebox.glb`, `/health`, `/status`, `/events` | `test_houdini_panel_preview_uses_explicit_whitebox_contract` |
| Houdini 按钮不可用, Houdini 已连接但导出不可用, 状态行不对 | Pipeline/status + DCC bridge | `pipeline_status.js`, `dcc_bridge.js` | `applySharedStatus`, `setHoudiniBadge`, `updateHoudiniStatusPanel` | `/health`, `/status`, `/software-paths`, `/open-houdini` | `test_houdini_status_updates_use_shared_frontend_projection` |
| 地图框选异常, 选区恢复失败, 网格按钮没反应 | Map selection | `selection_search.js`, then `app.js` | `setSelection`, `loadGrid`, `restoreRememberedSelection`, `selectionPayloadFromSelection` | `/tiles`, `/selection`, `/selection/clear` | `test_picker_uses_draw_rectangle_for_fixed_grid_blocks` |
| DCC 路径保存失败, DCCbridge 开关异常, 软件启动/关闭失败 | DCC bridge | `dcc_bridge.js` | `saveSoftwarePath`, `updateDccSoftwarePaths`, `openDccSoftware`, `closeDccSoftware` | `/software-paths`, `/open-software`, `/close-software` | `test_dccbridge_controls_are_clickable` |
| 运行监控日志不更新, 进度卡住, 失败摘要不显示 | Pipeline/status | `pipeline_status.js`, then `server.py` | `startStatusStream`, `pollStatus`, `applyStatus`, `setFailureSummary` | `/events`, `/status`, `/health` | `test_frontend_consumption_loses_no_line_across_rollover` |
| 数据源列表不对, 下载地图数据按钮异常 | Pipeline/data sources | `pipeline_status.js` | `refreshDataSources`, `renderDataSources`, `downloadData` | `/data-sources`, `/jobs` | `test_picker_exposes_current_data_sources` |
| 工作区切换错位, 右栏无法收起, 刷新后 workspace 丢失 | Workspace shell | `workspace.js` | `setWorkspace`, `syncActionPanelContent`, `bindWorkspaceSwitching` | `/restart` | `test_workspace_switcher_has_mode_hooks` |
| 游戏编辑器同步白盒失败, 资产拖拽异常 | Game workbench | `game_workbench.js`, then `vc_glb.js` | `importHoudiniWhitebox`, `VC_GAME_WORKBENCH`, `VC_GLB.load` | `/whitebox.glb` through preview contract | `test_game_workspace_mounts_three_scene` |
| 本地资产目录保存失败, 资产树不显示 | Asset library | `asset_dir.js`, then `game_workbench.js` | `applyStatus`, `renderTree`, `asset-dir-form` submit handler | `/asset-dir` | `test_game_workspace_has_asset_dir_controls` |
| 地点搜索异常, 搜索结果不飞到地图 | Location search | `selection_search.js`, then `app.js` | `bindLocationSearch`, `focusSearchResult`, `flyToBbox` | `/geocode` | `test_picker_uses_draw_rectangle_for_fixed_grid_blocks` |
| 区域导航不显示, 城市按钮不工作 | Region navigation | `app.js` | `loadRegionNav`, `renderCountries`, `renderCities`, `loadBoundary` | `/area-picker/regions.json`, `/boundary` | `test_workspace_menu_order_and_default_page` |
| 底图或世界轮廓不显示, 世界地图空白 | Basemap/world layers | `app.js` | `VECTOR_STYLE_URL`, `WORLD_GEOJSON_URL`, `loadWorldGeojson`, `setBasemapStyle` | `/area-picker/basemap-style.json`, `/area-picker/world_countries.json` | `test_picker_uses_local_web_assets_and_online_basemap` |

## Runtime Chain Shortcuts

- **Submit generation:** `index.html` button -> `runPipeline()` -> `submitSelectedArea('generate')` -> `POST /jobs` -> `server.py do_POST` -> `orchestration/run_pipeline.py`.
- **Submit data download:** `downloadData()` -> `submitSelectedArea('download')` -> `POST /jobs` with `body.mode = download`.
- **Status refresh:** `refreshServiceState()` reads `/health`; live runs use `startStatusStream()` on `/events` with `/status` as polling fallback.
- **Shared status projection:** frontend status rendering must pass through `applySharedStatus(d)`; backend `/health`, `/status`, and `/events` must share `_attach_service_status_fields()`.
- **Whitebox preview:** backend reports `houdini_asset.whitebox`; frontend only loads when `asset.preview_ready` and `whitebox.available` are both true.

## Search Tips

- Start with this command for route-level questions: `rg -n "fetch\('/|new EventSource\('/|navigator\.sendBeacon\('/" Scripts/app/area_picker/frontend`.
- Start with this command for backend handlers: `rg -n "if parsed\.path|def _post_|def _serve_whitebox|def _sse_events" Scripts/app/area_picker/server.py`.
- For symbol impact, use CodeGraph first when `.codegraph/codegraph.db` exists: `python C:\Users\yintong\.codex\skills\codegraph\scripts\query_codegraph.py --repo E:\VirtualCity neighbors applySharedStatus`.
