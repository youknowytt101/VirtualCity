# Area Picker Frontend API Contract

This contract records the frontend routes that are part of the Area Picker runtime surface. Update it whenever a route is added, renamed, removed, or changes required fields.

## GET /health

- Used by: `pipeline_status.js -> refreshServiceState()`.
- Backend: `server.py -> _service_payload()` and `_attach_service_status_fields()`.
- Required fields: `running`, `export_running`, `houdini_available`, `houdini_asset`, `software_paths`, `export_available`, `selection`, `downloaded_areas`, `failure_summary`, `last_run`.
- Notes: this is the first refresh path after page load and after failed job submissions.

## GET /status

- Used by: `pipeline_status.js -> pollStatus()` as the polling fallback for live runs.
- Backend: `server.py -> _build_status_payload()`.
- Required fields: all `/health` shared fields plus `done`, `ok`, `returncode`, `operation`, `run_id`, `step`, `total_steps`, `step_label`, `phase`, `phase_label`, `pct`, `log_lines`, `log_offset`, `export_log_lines`, `export_log_offset`.
- Notes: top-level `done` and `ok` only describe the active run; historical completion is exposed through `last_run`.

## GET /events

- Used by: `pipeline_status.js -> startStatusStream()`.
- Backend: `server.py -> _sse_events()`.
- Required fields: same payload shape as `/status`.
- Notes: the client falls back to `/status` polling if `EventSource` is unavailable or errors.

## POST /jobs

- Used by: `pipeline_status.js -> submitSelectedArea()`.
- Backend: `server.py -> do_POST` job branch.
- Request body: `tile_ids: string[]`, `mode: "generate" | "download"`.
- Response fields: `ok`, `message`.
- Notes: legacy `/run` and `/download-data` routes remain compatibility entries, but the frontend should use `/jobs`.

## GET /whitebox.glb

- Used by: `houdini_preview.js -> VC_HOUDINI_PREVIEW.update()` through `asset.whitebox.url`, and by `game_workbench.js` when importing the latest whitebox.
- Backend: `server.py -> _serve_whitebox_glb()`.
- Related status fields: `houdini_asset.preview_ready`, `houdini_asset.whitebox.available`, `houdini_asset.whitebox.url`, `houdini_asset.whitebox.cache_key`, `houdini_asset.whitebox.run_id`, `houdini_asset.whitebox.path`, `houdini_asset.whitebox.message`.
- Notes: frontend must not probe Houdini directly for preview readiness.

## GET /data-sources

- Used by: `pipeline_status.js -> refreshDataSources()`.
- Backend: `server.py -> _data_sources_status()`.
- Required fields: `available`, `message`, `items`.
- Notes: data source cards render from this response after `/health` refreshes.

## GET /tiles

- Used by: `selection_search.js -> loadGrid()`.
- Backend: `server.py -> do_GET` `/tiles` branch.
- Query: `west`, `south`, `east`, `north`, `z`.
- Required fields: `tiles`, `truncated`, optional `message`.

## GET /selection and POST /selection

- Used by: `selection_search.js -> restoreRememberedSelection()`, `persistSelection()`.
- Backend: `server.py -> _remembered_selection_status()`, `_post_selection()`.
- Request body for POST: `tile_ids: string[]`.
- Required fields: `ok`, `selection`.

## POST /selection/clear

- Used by: `selection_search.js -> clearPersistedSelection()`.
- Backend: `server.py -> do_POST` `/selection/clear` branch.
- Response fields: `ok`.

## GET /geocode

- Used by: `selection_search.js -> bindLocationSearch()`.
- Backend: `server.py -> do_GET` `/geocode` branch.
- Query: `q`.
- Required fields: `ok`, `results`, optional `message`.

## GET /boundary

- Used by: `app.js -> loadBoundary()`.
- Backend: `server.py -> _fetch_boundary()`.
- Query: `osm_type`, `osm_id`.
- Required fields: `ok`, `message`, `geojson`.

## GET /area-picker/regions.json

- Used by: `app.js -> loadRegionNav()`.
- Backend: `server.py -> _frontend_static()` through the `/area-picker/` static branch.
- Required shape: top-level region JSON consumed by `renderCountries()` and `renderCities()`.
- Notes: this is versioned with `window.VC_CONFIG.version` to keep frontend cache invalidation aligned with script changes.

## GET /area-picker/basemap-style.json

- Used by: `app.js -> VECTOR_STYLE_URL` for the MapLibre vector basemap style.
- Backend: `server.py -> _frontend_static()` through the `/area-picker/` static branch.
- Required shape: MapLibre style JSON.

## GET /area-picker/world_countries.json

- Used by: `app.js -> WORLD_GEOJSON_URL` and `loadWorldGeojson()`.
- Backend: `server.py -> _frontend_static()` through the `/area-picker/` static branch.
- Required shape: GeoJSON feature collection for world base layers.

## GET /static/*

- Used by: `index.html` for MapLibre, Deck.gl, Three.js, and by `vc_glb.js` for `GLTFLoader.js`.
- Backend: `server.py -> _static()` through the `/static/` static branch.
- Notes: static vendor assets live under `Scripts/web_assets`.

## GET and POST /software-paths

- Used by: `dcc_bridge.js -> saveSoftwarePath()`, `saveDccSoftwarePath()`.
- Backend: `server.py -> _software_path_status()`, `_post_software_paths()`.
- Request fields: `houdini_exe`, `blender_exe`, `unity_exe`, `unreal_exe`, `godot_exe` as needed.
- Required response fields: `ok`, `message`, `software_paths`.

## POST /open-houdini

- Used by: `dcc_bridge.js -> openOrProbeHoudini()`.
- Backend: `server.py -> _post_open_houdini()`.
- Request fields: `houdini_exe`.
- Required response fields: `ok`, `message`, `software_paths`.

## POST /open-software and POST /close-software

- Used by: `dcc_bridge.js -> openDccSoftware()`, `closeDccSoftware()`.
- Backend: `server.py -> _post_open_software()`, `_post_close_software()`.
- Request fields: `software_id`, optional path field for the software.
- Required response fields: `ok`, `message`, `software_paths`.

## GET and POST /asset-dir

- Used by: `asset_dir.js`.
- Backend: `server.py -> _asset_dir_status()`, `_post_asset_dir()`.
- Request fields: `path`.
- Required response fields: `ok`, `message`, `asset_dir`.

## POST /export

- Used by: `pipeline_status.js -> exportFbx()`.
- Backend: `server.py -> _post_export()`.
- Response fields: `ok`, `message`.
- Notes: export progress is reported through `/status` and `/events` export log fields.

## POST /session and POST /session/closed

- Used by: `app.js -> touchPageSession()`, `notifyPageClosed()`.
- Backend: `server.py -> do_POST` session branches.
- Response fields: `ok`.
- Notes: only active when `window.VC_CONFIG.shutdownWithPage` is true.

## POST /restart

- Used by: `workspace.js -> bindFrontendRefresh()`.
- Backend: `server.py -> do_POST` `/restart` branch.
- Response fields: `ok`, `message`.
