"""Offline tests for area_picker state and progress helpers."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))

import area_picker
import houdini_build.status as houdini_status_writer
import manual_review
import pipeline_status

FRONTEND_ROOT = Path(area_picker.FRONTEND_ROOT)
_PICKER_INDEX_HTML = area_picker._HTML
_PICKER_STYLES = (FRONTEND_ROOT / "styles.css").read_text(encoding="utf-8")
_PICKER_SCRIPT_NAMES = (
    "vc_glb.js",
    "game_workbench.js",
    "houdini_preview.js",
    "asset_dir.js",
    "workspace.js",
    "selection_search.js",
    "pipeline_status.js",
    "dcc_bridge.js",
    "app.js",
)
_PICKER_APP_JS = "\n".join(
    (FRONTEND_ROOT / name).read_text(encoding="utf-8")
    for name in _PICKER_SCRIPT_NAMES
)
_PICKER_FRONTEND = "\n".join([_PICKER_INDEX_HTML, _PICKER_STYLES, _PICKER_APP_JS])


class TestProgressView(unittest.TestCase):
    """进度来自真相源投影，不再解析 stdout 日志。"""

    def test_houdini_stage_maps_into_high_band(self):
        run = {"phase": "houdini_recook", "status": "running",
               "progress": {"step": 4, "total": 7, "label": "[Houdini 4/7] 全链路验证"}}
        pv = pipeline_status.progress_view(run)
        self.assertGreater(pv["pct"], 85)
        self.assertLessEqual(pv["pct"], 99)
        self.assertEqual(pv["label"], "[Houdini 4/7] 全链路验证")

    def test_completed_run_reaches_full(self):
        run = {"phase": "pipeline_completed", "status": "completed",
               "progress": {"step": 7, "total": 7, "label": "done"}}
        self.assertEqual(pipeline_status.progress_view(run)["pct"], 100)

    def test_acquire_phase_uses_anchor_and_label(self):
        run = {"phase": "acquire_dem", "status": "running", "progress": {}}
        pv = pipeline_status.progress_view(run)
        self.assertEqual(pv["pct"], 38)
        self.assertEqual(pv["label"], "获取地形数据")


class TestRollingLogOffset(unittest.TestCase):
    """日志窗口滚动后，全局序号必须单调增长，前端据此消费不丢行。"""

    def _isolated_state(self):
        previous = dict(area_picker._state)
        with area_picker._state_lock:
            area_picker._reset_log("log_lines", "log_offset")
        return previous

    def test_offset_tracks_dropped_lines(self):
        previous = self._isolated_state()
        try:
            total = area_picker._MAX_LOG_LINES + 25
            with area_picker._state_lock:
                for i in range(total):
                    area_picker._append_log("log_lines", "log_offset", f"line-{i}")
            self.assertEqual(len(area_picker._state["log_lines"]), area_picker._MAX_LOG_LINES)
            self.assertEqual(area_picker._state["log_offset"], 25)
            self.assertEqual(area_picker._state["log_lines"][0], "line-25")
        finally:
            with area_picker._state_lock:
                area_picker._state.update(previous)

    def test_frontend_consumption_loses_no_line_across_rollover(self):
        previous = self._isolated_state()
        try:
            total = area_picker._MAX_LOG_LINES + 40
            consumed = []
            next_seq = 0
            with area_picker._state_lock:
                for i in range(total):
                    area_picker._append_log("log_lines", "log_offset", f"line-{i}")
                    base = area_picker._state["log_offset"]
                    window = list(area_picker._state["log_lines"])
                    global_end = base + len(window)
                    if global_end > next_seq:
                        start = max(next_seq, base) - base
                        consumed.extend(window[start:])
                        next_seq = global_end
            self.assertEqual(consumed, [f"line-{i}" for i in range(total)])
        finally:
            with area_picker._state_lock:
                area_picker._state.update(previous)


class TestPickerHtml(unittest.TestCase):
    def test_picker_frontend_is_split_into_static_assets(self):
        self.assertTrue((FRONTEND_ROOT / "index.html").exists())
        self.assertTrue((FRONTEND_ROOT / "styles.css").exists())
        self.assertTrue((FRONTEND_ROOT / "app.js").exists())
        for name in _PICKER_SCRIPT_NAMES:
            self.assertTrue((FRONTEND_ROOT / name).exists())
            self.assertIn(f"/area-picker/{name}?v=__VERSION__", _PICKER_INDEX_HTML)
        self.assertIn('/area-picker/styles.css?v=__VERSION__', _PICKER_INDEX_HTML)
        self.assertIn("window.VC_CONFIG", _PICKER_INDEX_HTML)
        self.assertNotIn("<style>", _PICKER_INDEX_HTML)
        self.assertIn("def _frontend_static", Path(area_picker.__file__).read_text(encoding="utf-8"))

    def test_houdini_status_updates_use_shared_frontend_projection(self):
        self.assertIn("function applySharedStatus(d)", _PICKER_FRONTEND)
        self.assertGreaterEqual(_PICKER_FRONTEND.count("applySharedStatus(d);"), 2)

    def test_houdini_preview_honors_preview_ready_gate(self):
        self.assertIn("var previewReady = !!asset.preview_ready;", _PICKER_FRONTEND)
        self.assertIn("if (!previewReady || !whitebox.available)", _PICKER_FRONTEND)

    def test_houdini_preview_uses_terrain_mesh_for_preview_pivot(self):
        preview_js = (FRONTEND_ROOT / "houdini_preview.js").read_text(encoding="utf-8")
        self.assertIn("function findLayerObject(root, layerKey)", preview_js)
        self.assertIn("function computeTerrainPreviewPivot(model)", preview_js)
        self.assertIn("var terrainObject = findLayerObject(model, 'terrain');", preview_js)
        self.assertIn("var buildingsObject = findLayerObject(model, 'buildings');", preview_js)
        self.assertIn("var roadsObject = findLayerObject(model, 'roads');", preview_js)
        self.assertIn("var frameObject = buildingsObject || roadsObject || terrainObject || model;", preview_js)
        self.assertIn("model.position.set(-pivot.center.x, -pivot.center.y, -pivot.groundZ);", preview_js)
        self.assertNotIn("model.position.sub(center);", preview_js)

    def test_houdini_preview_uses_editor_default_lighting_profile(self):
        preview_js = (FRONTEND_ROOT / "houdini_preview.js").read_text(encoding="utf-8")
        self.assertIn("renderer.shadowMap.enabled = true;", preview_js)
        self.assertIn("renderer.shadowMap.type = THREE.BasicShadowMap;", preview_js)
        self.assertIn("renderer.outputColorSpace = THREE.SRGBColorSpace;", preview_js)
        self.assertIn("renderer.toneMapping = THREE.ACESFilmicToneMapping;", preview_js)
        self.assertIn("renderer.toneMappingExposure = 1.0;", preview_js)
        self.assertIn("new THREE.HemisphereLight(0xffffff, 0x8a9bb0, 0.9)", preview_js)
        self.assertIn("var sun = new THREE.DirectionalLight(0xffffff, 2.0);", preview_js)
        self.assertIn("sun.position.set(8, 14, 10);", preview_js)
        self.assertIn("sun.castShadow = true;", preview_js)
        self.assertIn("sun.shadow.mapSize.set(4096, 4096);", preview_js)
        self.assertIn("sun.shadow.camera.far = 400;", preview_js)
        self.assertIn("sun.shadow.camera.left = -60;", preview_js)
        self.assertIn("sun.shadow.bias = -0.00015;", preview_js)
        self.assertIn("sun.shadow.normalBias = 0.03;", preview_js)
        self.assertIn("scene.add(sun, sun.target);", preview_js)

        self.assertNotIn("AmbientLight", preview_js)

    def test_houdini_preview_replaces_imported_materials_with_lit_whitebox_material(self):
        preview_js = (FRONTEND_ROOT / "houdini_preview.js").read_text(encoding="utf-8")
        self.assertIn("function applyPreviewWhiteboxMaterial(object)", preview_js)
        self.assertIn("new THREE.MeshStandardMaterial({", preview_js)
        self.assertIn("color: previewWhiteboxColor(object)", preview_js)
        self.assertIn("disposeMaterial(object.material);", preview_js)
        self.assertIn("object.material = applyPreviewWhiteboxMaterial(object);", preview_js)

    def test_houdini_preview_uses_editor_ground_grid_and_camera_orbit(self):
        preview_js = (FRONTEND_ROOT / "houdini_preview.js").read_text(encoding="utf-8")
        self.assertIn("function createPreviewGround()", preview_js)
        self.assertIn("new THREE.ShadowMaterial({", preview_js)
        self.assertIn("new THREE.GridHelper(80, 80, 0x7f8790, 0xc4c9cf)", preview_js)
        self.assertIn("grid.rotation.x = Math.PI / 2;", preview_js)
        self.assertIn("function updatePreviewCameraOrbit()", preview_js)
        self.assertIn("previewYaw += model ? 0.005 : 0.02;", preview_js)
        self.assertIn("camera.position.set(", preview_js)
        self.assertNotIn("turntable.rotation.z", preview_js)

    def test_houdini_preview_keeps_terrain_roads_and_buildings_visible_with_layered_shadows(self):
        preview_js = (FRONTEND_ROOT / "houdini_preview.js").read_text(encoding="utf-8")
        self.assertIn("function isTerrainObject(object)", preview_js)
        self.assertIn("function isRoadObject(object)", preview_js)
        self.assertIn("var castsShadow = !isTerrainObject(object) && !isRoadObject(object);", preview_js)
        self.assertIn("object.castShadow = castsShadow;", preview_js)
        self.assertIn("object.receiveShadow = true;", preview_js)
        self.assertNotIn("object.visible = false", preview_js)

    def test_status_payloads_share_common_service_projection(self):
        source = Path(area_picker.__file__).read_text(encoding="utf-8")
        self.assertIn("def _attach_service_status_fields", source)
        self.assertGreaterEqual(source.count("_attach_service_status_fields("), 3)

    def test_picker_uses_draw_rectangle_for_fixed_grid_blocks(self):
        self.assertIn("固定网格框选器", _PICKER_FRONTEND)
        self.assertIn("new maplibregl.Map(", _PICKER_FRONTEND)
        self.assertIn("selectTilesByBounds", _PICKER_FRONTEND)
        self.assertIn("function tileDisplayBbox(tile)", _PICKER_FRONTEND)
        self.assertIn("function assignDisplayGridBounds(tiles)", _PICKER_FRONTEND)
        self.assertIn("tile.display_bbox =", _PICKER_FRONTEND)
        self.assertIn("bboxIntersects(bounds, tileDisplayBbox(tile))", _PICKER_FRONTEND)
        self.assertIn("id: 'grid-fill',", _PICKER_FRONTEND)
        self.assertIn("id: 'grid-line',", _PICKER_FRONTEND)
        self.assertIn("map.addSource('grid'", _PICKER_FRONTEND)
        self.assertIn("tile_ids", _PICKER_FRONTEND)
        self.assertIn("downloadData", _PICKER_FRONTEND)
        self.assertIn('id="selection-tools"', _PICKER_FRONTEND)
        self.assertIn("map-tool-control", _PICKER_FRONTEND)
        self.assertIn("activateRectangleTool", _PICKER_FRONTEND)
        self.assertIn("selectTileByLatLng", _PICKER_FRONTEND)
        self.assertIn("clearSelectionFromMapTool", _PICKER_FRONTEND)
        self.assertIn("bindSelectionTools", _PICKER_FRONTEND)
        self.assertIn("function setGridVisible(visible)", _PICKER_FRONTEND)
        self.assertIn("function toggleGridVisible()", _PICKER_FRONTEND)
        self.assertNotIn("leaflet.draw", _PICKER_FRONTEND)
        self.assertNotIn("L.Control.Draw", _PICKER_FRONTEND)
        self.assertNotIn("L.rectangle(", _PICKER_FRONTEND)
        self.assertNotIn("leaflet-draw-edit-remove", _PICKER_FRONTEND)
        self.assertNotIn(".leaflet-control-zoom", _PICKER_FRONTEND)
        self.assertNotIn('id="clear-btn"', _PICKER_FRONTEND)
        self.assertNotIn('id="legend"', _PICKER_FRONTEND)
        self.assertNotIn("未缓存：整体压暗", _PICKER_FRONTEND)
        self.assertNotIn("swatch-dim", _PICKER_FRONTEND)
        self.assertNotIn("cached-only", _PICKER_FRONTEND)
        self.assertNotIn("只显示已有缓存", _PICKER_FRONTEND)

    def test_houdini_action_panel_toggle_lives_in_top_toolbar(self):
        toolbar_start = _PICKER_INDEX_HTML.index('<div id="toolbar">')
        workspace_start = _PICKER_INDEX_HTML.index('<main id="workspace"')
        toolbar_html = _PICKER_INDEX_HTML[toolbar_start:workspace_start]
        action_panel_start = _PICKER_INDEX_HTML.index('<aside id="action-panel"')
        action_panel_html = _PICKER_INDEX_HTML[action_panel_start:]

        self.assertIn('class="toolbar-cluster"', toolbar_html)
        self.assertIn('id="action-panel-toggle"', toolbar_html)
        self.assertNotIn('id="action-panel-toggle"', action_panel_html)
        self.assertIn('data-action-panel-collapsed="false"', _PICKER_FRONTEND)
        self.assertIn('#workspace[data-action-panel-collapsed="true"]', _PICKER_STYLES)
        self.assertIn('function setActionPanelCollapsed(collapsed)', _PICKER_APP_JS)
        self.assertIn('function bindActionPanelToggle()', _PICKER_APP_JS)

    def test_picker_version_uses_public_date_semver_format(self):
        self.assertRegex(area_picker.APP_VERSION, r"^\d{2}-\d{2}-\d{2}_v\d+\.\d+$")

    def test_version_text_and_test_buttons_are_split(self):
        self.assertIn('id="app-version-label" class="version-text">__APP_VERSION__</span>', _PICKER_INDEX_HTML)
        self.assertIn('id="backend-restart-button"', _PICKER_INDEX_HTML)
        self.assertIn('id="frontend-refresh-button"', _PICKER_INDEX_HTML)
        self.assertIn('class="test-chip"', _PICKER_INDEX_HTML)
        self.assertIn('aria-label="测试期间重启后端服务"', _PICKER_INDEX_HTML)
        self.assertIn('aria-label="测试期间刷新前端资源"', _PICKER_INDEX_HTML)
        self.assertNotIn('id="frontend-refresh-button" class="version-chip"', _PICKER_INDEX_HTML)
        self.assertIn("frontendRefreshWorkspaceKey = 'vc.areaPicker.refreshWorkspace.v1'", _PICKER_APP_JS)
        self.assertIn("function bindFrontendRefresh()", _PICKER_APP_JS)
        self.assertIn("var restartButton = document.getElementById('backend-restart-button');", _PICKER_APP_JS)
        self.assertIn("var refreshButton = document.getElementById('frontend-refresh-button');", _PICKER_APP_JS)
        self.assertIn("function rememberWorkspace()", _PICKER_APP_JS)
        self.assertIn("clearDccPathCache();", _PICKER_APP_JS)
        self.assertIn("fetch('/restart'", _PICKER_APP_JS)
        self.assertIn("reloadWithCacheBust();", _PICKER_APP_JS)
        self.assertIn("url.searchParams.set('refresh', String(Date.now()))", _PICKER_APP_JS)
        self.assertIn("window.location.replace(url.toString())", _PICKER_APP_JS)
        self.assertTrue(hasattr(area_picker, "_schedule_desktop_restart"))
        server_source = Path(area_picker.__file__).read_text(encoding="utf-8")
        self.assertIn("parsed.path == '/restart'", server_source)
        self.assertIn("VC_AREA_PICKER_FORCE_RESTART", server_source)
        self.assertIn("def _clear_dcc_path_cache", server_source)
        self.assertIn("function initialWorkspaceId()", _PICKER_APP_JS)
        self.assertIn("bindFrontendRefresh();", _PICKER_APP_JS)
        self.assertIn("setWorkspace(initialWorkspaceId());", _PICKER_APP_JS)

    def test_picker_uses_local_web_assets_and_online_basemap(self):
        self.assertIn('/static/maplibre/maplibre-gl.css', _PICKER_FRONTEND)
        self.assertIn('/static/maplibre/maplibre-gl.js', _PICKER_FRONTEND)
        self.assertIn('/static/deckgl/deck.gl.min.js', _PICKER_FRONTEND)
        self.assertNotIn('/static/leaflet/leaflet.js', _PICKER_FRONTEND)
        self.assertNotIn('/static/leaflet-draw/leaflet.draw.js', _PICKER_FRONTEND)
        self.assertNotIn('unpkg.com/leaflet', _PICKER_FRONTEND)
        self.assertNotIn('cdnjs.cloudflare.com/ajax/libs/leaflet.draw', _PICKER_FRONTEND)
        self.assertIn('tile.openstreetmap.org', _PICKER_FRONTEND)
        self.assertIn('/area-picker/basemap-style.json', _PICKER_FRONTEND)
        self.assertNotIn('run-mode', _PICKER_FRONTEND)
        self.assertNotIn('local-basemap-enabled', _PICKER_FRONTEND)
        self.assertNotIn('loadLocalBasemap', _PICKER_FRONTEND)
        self.assertIn('type="button" class="badge badge-warn" onclick="openOrProbeHoudini()"', _PICKER_FRONTEND)
        self.assertIn('function openOrProbeHoudini()', _PICKER_FRONTEND)
        self.assertNotIn('setInterval(refreshServiceState', _PICKER_FRONTEND)
        self.assertIn("new EventSource('/events')", _PICKER_FRONTEND)
        self.assertIn('function startStatusStream()', _PICKER_FRONTEND)
        self.assertIn('var shutdownWithPage = window.VC_CONFIG.shutdownWithPage;', _PICKER_FRONTEND)
        self.assertIn("navigator.sendBeacon('/session/closed'", _PICKER_FRONTEND)
        self.assertIn("fetch('/session'", _PICKER_FRONTEND)
        self.assertTrue(hasattr(area_picker, "_schedule_page_close_shutdown"))
        self.assertIn('exportFbx', _PICKER_FRONTEND)
        self.assertIn('id="download-btn" disabled onclick="downloadData()"', _PICKER_FRONTEND)
        self.assertIn('class="source-action-btn"', _PICKER_FRONTEND)
        self.assertIn("submitSelectedArea('download'", _PICKER_FRONTEND)
        self.assertIn("id: 'grid-fill',", _PICKER_FRONTEND)
        self.assertIn("id: 'grid-line',", _PICKER_FRONTEND)
        self.assertNotIn("invert(1)", _PICKER_FRONTEND)
        self.assertNotIn("visualRoad", _PICKER_FRONTEND)
        self.assertNotIn("/visual-roads", _PICKER_FRONTEND)

    def test_lane_preview_button_is_not_exposed(self):
        removed_endpoint = "lane" + "-upgrade"
        self.assertNotIn(removed_endpoint, _PICKER_FRONTEND)
        self.assertNotIn("updateLaneUpgradeButton", _PICKER_FRONTEND)
        self.assertNotIn("handleLaneUpgrade", _PICKER_FRONTEND)

    def test_selection_survives_page_reload(self):
        self.assertIn("selectionStorageKey = 'vc.areaPicker.selection.v1'", _PICKER_FRONTEND)
        self.assertIn("function selectionPayloadFromSelection", _PICKER_FRONTEND)
        self.assertIn("function persistSelection()", _PICKER_FRONTEND)
        self.assertIn("function restoreSelectionFromPayload", _PICKER_FRONTEND)
        self.assertIn("function restoreRememberedSelection", _PICKER_FRONTEND)
        self.assertIn("function restorePendingSelection", _PICKER_FRONTEND)
        self.assertIn("fetch('/selection'", _PICKER_FRONTEND)
        self.assertIn("fetch('/selection/clear'", _PICKER_FRONTEND)
        self.assertIn("restoreRememberedSelection();", _PICKER_FRONTEND)
        self.assertIn("persistSelection();", _PICKER_FRONTEND)
        self.assertIn("syncDrawnSelectionLayer();", _PICKER_FRONTEND)
        self.assertIn("setRunStatus('warn', '待命', 0, '已选择区域，等待执行');", _PICKER_FRONTEND)
        self.assertIn("已恢复上次框选", _PICKER_FRONTEND)

    def test_viewport_data_summary_is_not_exposed(self):
        self.assertNotIn("视口数据", _PICKER_FRONTEND)
        self.assertNotIn("完整数据区域", _PICKER_FRONTEND)
        self.assertNotIn('id="grid-status"', _PICKER_FRONTEND)
        self.assertNotIn('id="downloaded-area-count"', _PICKER_FRONTEND)
        self.assertNotIn('id="selection-bbox"', _PICKER_FRONTEND)
        self.assertNotIn("function updateDownloadedAreaCount", _PICKER_FRONTEND)
        self.assertNotIn("data-overview", _PICKER_FRONTEND)
        self.assertNotIn("metric-grid", _PICKER_FRONTEND)
        self.assertNotIn("已下载区域数量", _PICKER_FRONTEND)
        self.assertNotIn("网格数量", _PICKER_FRONTEND)
        self.assertNotIn("区域尺寸", _PICKER_FRONTEND)
        self.assertNotIn("缓存覆盖", _PICKER_FRONTEND)
        self.assertNotIn("网格矩阵", _PICKER_FRONTEND)
        self.assertNotIn('id="selection-count"', _PICKER_FRONTEND)
        self.assertNotIn('id="selection-size"', _PICKER_FRONTEND)
        self.assertNotIn('id="selection-cache"', _PICKER_FRONTEND)
        self.assertNotIn('id="selection-matrix"', _PICKER_FRONTEND)

    def test_picker_exposes_current_data_sources(self):
        self.assertIn('id="source-list"', _PICKER_FRONTEND)
        self.assertIn("function refreshDataSources()", _PICKER_FRONTEND)
        self.assertIn("fetch('/data-sources'", _PICKER_FRONTEND)
        self.assertIn("选取区域预先下载地图数据加快Houdini自动管线构建速度", _PICKER_FRONTEND)
        self.assertNotIn("读取当前区域数据源...", _PICKER_FRONTEND)
        self.assertNotIn("当前区域数据源", _PICKER_FRONTEND)
        self.assertIn("数据源：OpenStreetMap", _PICKER_FRONTEND)
        self.assertIn("数据源：Overture Maps + Google Open Buildings", _PICKER_FRONTEND)
        self.assertIn("策略：本地缓存优先", _PICKER_FRONTEND)
        self.assertIn("item.strategy_label", _PICKER_FRONTEND)
        self.assertNotIn("source-state", _PICKER_FRONTEND)
        self.assertNotIn("已就绪", _PICKER_FRONTEND)

    def test_action_panel_groups_workflow_modules(self):
        self.assertIn('id="action-panel"', _PICKER_FRONTEND)
        self.assertIn("待命/运行监控", _PICKER_FRONTEND)
        self.assertIn("数据源", _PICKER_FRONTEND)
        self.assertIn("预览", _PICKER_FRONTEND)
        self.assertIn("构建", _PICKER_FRONTEND)
        self.assertIn("运行监控", _PICKER_FRONTEND)
        self.assertIn("建筑", _PICKER_FRONTEND)
        self.assertIn("地形", _PICKER_FRONTEND)
        self.assertIn("自然", _PICKER_FRONTEND)
        self.assertIn("道路", _PICKER_FRONTEND)
        self.assertIn("自然数据处理入口待接入", _PICKER_FRONTEND)
        self.assertIn("道路数据处理入口待接入", _PICKER_FRONTEND)
        self.assertNotIn("植被数据清洗入口待接入", _PICKER_FRONTEND)
        self.assertNotIn("车道数据处理入口待接入", _PICKER_FRONTEND)
        self.assertIn("placeholder-btn", _PICKER_FRONTEND)
        self.assertIn('id="run-status-panel"', _PICKER_FRONTEND)
        self.assertIn('id="run-status-bar"', _PICKER_FRONTEND)
        self.assertIn("function updateRunStatusFromHealth", _PICKER_FRONTEND)
        self.assertIn('id="failure-summary"', _PICKER_FRONTEND)
        self.assertIn("function setFailureSummary", _PICKER_FRONTEND)
        self.assertIn("function logFailureSummary", _PICKER_FRONTEND)
        self.assertIn("上次失败", _PICKER_FRONTEND)
        self.assertNotIn("打开输出", _PICKER_FRONTEND)

    def test_workspace_uses_gapless_three_column_layout(self):
        self.assertIn('grid-template-areas: "controls map actions";', _PICKER_FRONTEND)
        self.assertIn("gap: 0;", _PICKER_FRONTEND)
        self.assertIn("grid-area: controls;", _PICKER_FRONTEND)
        self.assertIn("grid-area: map;", _PICKER_FRONTEND)
        self.assertIn("grid-area: actions;", _PICKER_FRONTEND)
        self.assertIn("border-radius: 0;", _PICKER_FRONTEND)
        self.assertNotIn("left: 18px;", _PICKER_FRONTEND)
        self.assertNotIn("right: 18px;", _PICKER_FRONTEND)
        self.assertNotIn("top: 18px;", _PICKER_FRONTEND)
        self.assertNotIn("max-height: calc(100% - 36px);", _PICKER_FRONTEND)

    def test_workspace_switcher_has_mode_hooks(self):
        self.assertIn('data-workspace-target="city-preview"', _PICKER_FRONTEND)
        self.assertIn('data-workspace-target="news"', _PICKER_FRONTEND)
        self.assertNotIn('data-workspace-target="neighborhood"', _PICKER_FRONTEND)
        self.assertIn('data-workspace-target="game"', _PICKER_FRONTEND)
        self.assertIn('data-workspace-target="houdini"', _PICKER_FRONTEND)
        self.assertIn('id="game-workbench"', _PICKER_FRONTEND)
        self.assertIn('data-workspace-kind', _PICKER_FRONTEND)
        self.assertIn('#workspace[data-workspace-kind="earth"] #map-shell', _PICKER_FRONTEND)
        self.assertIn('grid-column: 2 / 3;', _PICKER_FRONTEND)
        self.assertIn('#action-panel[hidden]', _PICKER_FRONTEND)
        self.assertIn('var WORKSPACE_KINDS = {', _PICKER_FRONTEND)
        self.assertIn('function setWorkspace(id)', _PICKER_FRONTEND)
        self.assertIn('function bindWorkspaceSwitching()', _PICKER_FRONTEND)
        self.assertIn("map.resize();", _PICKER_FRONTEND)

    def test_workspace_action_panel_has_tabbed_panels_for_unimplemented_modules(self):
        self.assertIn('data-action-panel-content="houdini"', _PICKER_INDEX_HTML)
        for workspace in ("news", "city-preview", "neighborhood", "game"):
            self.assertIn(f'data-action-panel-content="{workspace}"', _PICKER_INDEX_HTML)
        self.assertIn(".action-tabs", _PICKER_STYLES)
        self.assertIn("function syncActionPanelContent(workspaceId)", _PICKER_APP_JS)
        self.assertIn("querySelectorAll('[data-action-panel-content]')", _PICKER_APP_JS)

    def test_city_workspace_defaults_to_singapore_central_3d_preview(self):
        self.assertIn("function showDefaultCityPreview()", _PICKER_APP_JS)
        self.assertIn("findRegionById(regionData, 'sg')", _PICKER_APP_JS)
        self.assertIn("findRegionById(country.cities || [], 'central')", _PICKER_APP_JS)
        self.assertIn("loadBoundary(city.osmId);", _PICKER_APP_JS)
        self.assertIn("var lastCityView = null;", _PICKER_APP_JS)
        self.assertIn("lastCityView = { bbox: city.bbox, maxZoom: 12 };", _PICKER_APP_JS)
        self.assertIn("flyToBbox(lastCityView.bbox, lastCityView.maxZoom);", _PICKER_APP_JS)
        self.assertIn("function syncHoudiniCameraToCity()", _PICKER_APP_JS)
        self.assertIn("if (city && city.bbox) view = { bbox: city.bbox, maxZoom: 12 };", _PICKER_APP_JS)
        self.assertIn("flyToBbox(view.bbox, view.maxZoom);", _PICKER_APP_JS)
        self.assertIn("flyTo3DCity(target[0], target[1], city.landmark_zoom || 15);", _PICKER_APP_JS)
        self.assertIn("syncHoudiniCameraToCity();", _PICKER_APP_JS)
        self.assertIn("if (nextWorkspace === 'city-preview') showDefaultCityPreview();", _PICKER_APP_JS)
        self.assertIn("else if (cityPreviewActive && nextWorkspace !== 'city-preview' && nextWorkspace !== 'houdini' && showsMap) {", _PICKER_APP_JS)
        self.assertIn("cityPreviewActive = false;", _PICKER_APP_JS)
        self.assertIn("if (activeWorkspaceId === 'city-preview') showDefaultCityPreview();", _PICKER_APP_JS)
        self.assertIn("else if (activeWorkspaceId === 'houdini') syncHoudiniCameraToCity();", _PICKER_APP_JS)

    def test_eol_workspace_defaults_to_global_overview(self):
        self.assertIn("function flyToWorld()", _PICKER_APP_JS)
        self.assertIn("center: [window.VC_CONFIG.lon, 20]", _PICKER_APP_JS)
        self.assertIn("zoom: 2.5", _PICKER_APP_JS)
        self.assertIn("pitch: 0", _PICKER_APP_JS)
        self.assertIn("flyToWorld: flyToWorld", _PICKER_APP_JS)
        self.assertIn("function showGlobalOverview()", _PICKER_APP_JS)
        self.assertIn("cameraController.flyToWorld();", _PICKER_APP_JS)
        self.assertIn("if (nextWorkspace === 'news') showGlobalOverview();", _PICKER_APP_JS)

    def test_game_action_panel_overlays_without_resizing_viewport(self):
        self.assertIn('#workspace[data-workspace-kind="game"] {', _PICKER_STYLES)
        self.assertIn("grid-template-columns: 300px minmax(0, 1fr) 0;", _PICKER_STYLES)
        self.assertIn('#workspace[data-workspace-kind="game"] #action-panel:not([hidden])', _PICKER_STYLES)
        self.assertIn("grid-area: auto;", _PICKER_STYLES)
        self.assertIn("position: absolute;", _PICKER_STYLES)
        self.assertIn("min-width: 326px;", _PICKER_STYLES)
        self.assertIn("max-width: 326px;", _PICKER_STYLES)

    def test_account_footer_uses_codex_style_menu(self):
        self.assertIn('<details class="account-menu">', _PICKER_INDEX_HTML)
        self.assertIn('class="account-trigger"', _PICKER_INDEX_HTML)
        self.assertIn('class="account-popover"', _PICKER_INDEX_HTML)
        self.assertIn('role="menu"', _PICKER_INDEX_HTML)
        self.assertIn('<span class="account-name">Settings</span>', _PICKER_INDEX_HTML)
        self.assertIn('<span class="account-plan">Account</span>', _PICKER_INDEX_HTML)
        self.assertIn("border-top: 1px solid var(--line);", _PICKER_STYLES)
        self.assertIn(".account-menu[open] .account-popover", _PICKER_STYLES)
        self.assertNotIn(".account-menu:hover .account-popover", _PICKER_STYLES)
        self.assertIn("function bindAccountMenu()", _PICKER_APP_JS)
        self.assertIn("if (!menu.contains(event.target)) menu.open = false;", _PICKER_APP_JS)
        self.assertNotIn("account-card", _PICKER_FRONTEND)

    def test_game_workspace_mounts_three_scene(self):
        game_js_path = FRONTEND_ROOT / "game_workbench.js"
        self.assertTrue(game_js_path.exists())
        game_js = game_js_path.read_text(encoding="utf-8")
        self.assertIn('/static/three/three.min.js', _PICKER_INDEX_HTML)
        self.assertIn('/area-picker/game_workbench.js?v=__VERSION__', _PICKER_INDEX_HTML)
        self.assertIn('id="game-scene-host"', _PICKER_INDEX_HTML)
        self.assertIn('game-asset-button', _PICKER_INDEX_HTML)
        self.assertIn('data-game-asset="character"', _PICKER_INDEX_HTML)
        self.assertIn('id="game-run-button"', _PICKER_INDEX_HTML)
        self.assertIn('initGameWorkbench', game_js)
        self.assertIn('createToonGrayMaterial', game_js)
        self.assertIn('createPlayModeController', game_js)
        self.assertIn('placeCharacterAt', game_js)
        self.assertIn('handleGameShortcut', game_js)
        self.assertIn('window.VC_GAME_WORKBENCH', game_js)
        self.assertIn('window.VC_GAME_WORKBENCH.init()', _PICKER_APP_JS)
        self.assertIn('window.VC_GAME_WORKBENCH.setActive(', _PICKER_APP_JS)

    def test_game_play_mode_hides_editor_overlays_and_start_ui(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        enter_start = game_js.index("function enter(character)")
        enter_end = game_js.index("function exit()", enter_start)
        enter_body = game_js[enter_start:enter_end]

        self.assertNotIn("BoxHelper", game_js)
        self.assertIn("function syncSelectionHighlight()", game_js)
        self.assertIn("syncEditOverlays();", game_js)
        self.assertNotIn("requestPointerLock();", enter_body)
        self.assertIn("#game-workbench.is-playing .game-toolbar", _PICKER_STYLES)
        self.assertIn("#game-workbench.is-playing .game-status", _PICKER_STYLES)

    def test_game_workbench_static_version_changes_with_script(self):
        game_js_path = FRONTEND_ROOT / "game_workbench.js"
        stat = game_js_path.stat()
        fingerprint = f"{int(stat.st_mtime)}-{stat.st_size}"
        self.assertIn(fingerprint, area_picker._frontend_asset_version())

    def test_houdini_panel_preview_uses_explicit_whitebox_contract(self):
        preview_js = (FRONTEND_ROOT / "houdini_preview.js").read_text(encoding="utf-8")
        pipeline_js = (FRONTEND_ROOT / "pipeline_status.js").read_text(encoding="utf-8")

        self.assertIn("function frameRadius(", preview_js)
        self.assertIn("asset.whitebox", preview_js)
        self.assertIn("whitebox.url", preview_js)
        self.assertIn("window.VC_HOUDINI_PREVIEW.update(d);", pipeline_js)
        self.assertNotIn("model_ready && !d.running", preview_js)

    def test_game_character_uses_stylized_readable_avatar(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        self.assertIn('createCharacterMaterial', game_js)
        self.assertIn("name: 'player-visor'", game_js)
        self.assertIn("name: 'player-backpack'", game_js)
        self.assertIn("name: 'player-left-arm'", game_js)
        self.assertIn("name: 'player-right-arm'", game_js)
        self.assertIn("name: 'player-left-leg'", game_js)
        self.assertIn("name: 'player-right-leg'", game_js)
        self.assertIn('character.userData.motionParts', game_js)
        self.assertIn('updateCharacterMotion(player, moveDirection, deltaTime)', game_js)
        self.assertIn('resetCharacterMotion(player)', game_js)

    def test_game_workspace_has_composition_viewport_controls(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        self.assertIn('id="game-speed-control"', _PICKER_INDEX_HTML)
        self.assertIn('id="game-speed-input"', _PICKER_INDEX_HTML)
        self.assertIn('class="game-tool-button game-asset-button"', _PICKER_INDEX_HTML)
        self.assertIn('class="game-tool-button game-run-button"', _PICKER_INDEX_HTML)
        self.assertIn('id="game-run-label"', _PICKER_INDEX_HTML)
        self.assertIn('.game-toolbar-shell', _PICKER_STYLES)
        self.assertIn('.game-speed-control', _PICKER_STYLES)
        self.assertIn('.game-run-label', _PICKER_STYLES)
        self.assertIn('-webkit-appearance: none;', _PICKER_STYLES)
        self.assertIn('appearance: textfield;', _PICKER_STYLES)
        self.assertIn('handleAltViewportDrag', game_js)
        self.assertIn('setMoveSpeed', game_js)
        self.assertIn('runLabel.textContent', game_js)
        self.assertNotIn('runButton.textContent', game_js)
        self.assertIn('event.altKey', game_js)
        self.assertIn("beginViewportDrag('orbit'", game_js)
        self.assertIn("beginViewportDrag('track'", game_js)
        self.assertIn("beginViewportDrag('dolly'", game_js)

    def test_game_transform_controls_have_explicit_modes(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        self.assertIn('data-transform-mode="translate"', _PICKER_INDEX_HTML)
        self.assertIn('data-transform-mode="rotate"', _PICKER_INDEX_HTML)
        self.assertIn('data-transform-mode="scale"', _PICKER_INDEX_HTML)
        self.assertIn("function setTransformMode(mode)", game_js)
        self.assertIn("transformControls.setMode(transformMode);", game_js)
        self.assertIn("transformControls.setSize(1);", game_js)
        self.assertIn("function bindTransformModeButtons()", game_js)

    def test_game_transform_controls_own_pointer_interaction(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        controls_start = game_js.index("function createGameCameraController()")
        down_start = game_js.index("function handlePointerDown(event)", controls_start)
        down_end = game_js.index("function handlePointerMove(event)", down_start)
        down_body = game_js[down_start:down_end]

        self.assertIn("function isTransformControlActive()", game_js)
        self.assertIn("transformControls.dragging || transformControls.axis", game_js)
        self.assertIn("if (isTransformControlActive()) return true;", down_body)
        self.assertLess(
            down_body.index("if (isTransformControlActive()) return true;"),
            down_body.index("pickCharacter(event);"),
        )

    def test_game_middle_mouse_tracks_viewport_without_alt(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        controls_start = game_js.index("function createGameCameraController()")
        down_start = game_js.index("function handlePointerDown(event)", controls_start)
        down_end = game_js.index("function handlePointerMove(event)", down_start)
        down_body = game_js[down_start:down_end]

        self.assertIn("if (event.button === 1) {", down_body)
        self.assertIn("beginViewportDrag('track', event, getViewportPivot(event));", down_body)

    def test_game_right_mouse_wheel_adjusts_flight_speed(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        wheel_start = game_js.index("sceneHost.addEventListener('wheel'")
        wheel_end = game_js.index("}, { passive: false });", wheel_start)
        wheel_body = game_js[wheel_start:wheel_end]

        self.assertIn("function adjustMoveSpeed(event)", game_js)
        self.assertIn("return setMoveSpeed(moveSpeed + (event.deltaY < 0 ? 1 : -1));", game_js)
        self.assertIn("if (cameraControls.isLooking()) {", wheel_body)
        self.assertIn("cameraControls.adjustMoveSpeed(event);", wheel_body)
        self.assertLess(
            wheel_body.index("cameraControls.adjustMoveSpeed(event);"),
            wheel_body.index("cameraControls.zoomView(event);"),
        )

    def test_game_editor_shortcuts_match_unreal_viewport(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        self.assertIn("setTransformMode('translate');", game_js)
        self.assertIn("setTransformMode('rotate');", game_js)
        self.assertIn("setTransformMode('scale');", game_js)
        self.assertNotIn("code === 'keyr' || code === 'space'", game_js)
        self.assertIn("code === 'space'", game_js)
        self.assertIn("state.distance - dy * state.distance * 0.01", game_js)

    def test_game_renderer_matches_composition_lighting_baseline(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        self.assertIn('THREE.ColorManagement.legacyMode = false;', game_js)
        self.assertIn('renderer.shadowMap.type = THREE.BasicShadowMap;', game_js)
        self.assertIn('opacity: 0.4', game_js)
        self.assertIn('sun.shadow.mapSize.set(4096, 4096);', game_js)
        self.assertIn('sun.shadow.normalBias = 0.03;', game_js)

    def test_game_workspace_uses_transform_controls(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        self.assertIn('type="importmap"', _PICKER_INDEX_HTML)
        self.assertIn('/static/three/three.module.js', _PICKER_INDEX_HTML)
        self.assertIn('/static/three/TransformControls.js', game_js)
        self.assertIn('transformControls.attach(selectedCharacter)', game_js)
        self.assertIn('transformControls.addEventListener("dragging-changed"', game_js)

    def test_game_viewport_orbits_selected_character_first(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        pivot_body = game_js[
            game_js.index("function getViewportPivot(event)"):
            game_js.index("function beginViewportDrag")
        ]
        self.assertLess(
            pivot_body.index("if (selectedCharacter)"),
            pivot_body.index("screenToGround(event.clientX, event.clientY)")
        )
        self.assertIn("camera.position.clone().addScaledVector(forward, 10)", pivot_body)

    def test_map_controls_are_repositioned(self):
        self.assertIn('#map #selection-tools {', _PICKER_FRONTEND)
        self.assertIn('#map #basemap-control {', _PICKER_FRONTEND)
        self.assertIn('right: 14px;', _PICKER_FRONTEND)
        self.assertIn('top: 14px;', _PICKER_FRONTEND)

    def test_grid_tools_are_houdini_only(self):
        self.assertIn('#workspace:not([data-workspace-kind="houdini"]) #selection-tools', _PICKER_FRONTEND)
        self.assertIn("if (activeWorkspaceId !== 'houdini') return;", _PICKER_APP_JS)
        self.assertIn('setGridVisible(true);', _PICKER_APP_JS)
        self.assertIn('setGridVisible(false);', _PICKER_APP_JS)
        self.assertIn('setPointSelectActive(false);', _PICKER_APP_JS)

    def test_workspace_menu_order_and_default_page(self):
        menu_labels = [
            'data-workspace-target="news" aria-pressed="true" title="切换到 EOL">EOL',
            'data-workspace-target="city-preview" aria-pressed="false" title="切换到城市">城市',
            'data-workspace-target="game" aria-pressed="false" title="切换到编辑器">编辑器',
            'data-workspace-target="houdini" aria-pressed="false" title="切换到 Houdini 工作台">Houdini',
            "DCCbridge",
        ]
        positions = [_PICKER_INDEX_HTML.index(label) for label in menu_labels]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('id="workspace" data-workspace-kind="earth" data-action-panel-collapsed="false"', _PICKER_INDEX_HTML)
        self.assertIn('data-workspace-target="news" aria-pressed="true"', _PICKER_INDEX_HTML)
        self.assertIn('id="action-panel" aria-label="执行操作面板"', _PICKER_INDEX_HTML)
        self.assertNotIn('id="action-panel" aria-label="执行操作面板" hidden', _PICKER_INDEX_HTML)
        self.assertIn('var activeWorkspaceId = \'news\';', _PICKER_APP_JS)
        self.assertIn('var actionPanelCollapsed = false;', _PICKER_APP_JS)

    def test_dccbridge_controls_are_clickable(self):
        self.assertIn('class="dcc-toggle" aria-pressed="false" aria-label="打开 Houdini"', _PICKER_INDEX_HTML)
        self.assertIn('class="dcc-install-btn" aria-pressed="false">安装</button>', _PICKER_INDEX_HTML)
        self.assertNotIn('class="dcc-install-btn" disabled', _PICKER_INDEX_HTML)
        self.assertIn("function bindDccBridgeControls", _PICKER_APP_JS)
        self.assertIn("install.textContent = installed ? '已安装' : '安装';", _PICKER_APP_JS)
        self.assertIn(".dcc-bridge-panel.flat-item:hover", _PICKER_FRONTEND)
        self.assertIn(".dcc-bridge-summary.active", _PICKER_FRONTEND)
        self.assertIn("updateWorkspaceButtons('');", _PICKER_APP_JS)
        self.assertIn("summary.classList.add('active');", _PICKER_APP_JS)
        self.assertIn("bridge.open && !bridge.contains(event.target)", _PICKER_APP_JS)
        self.assertIn("min-width: 36px;", _PICKER_FRONTEND)
        self.assertIn(".dcc-option-row.is-enabled .dcc-name", _PICKER_FRONTEND)
        self.assertIn("function openDccSoftware", _PICKER_APP_JS)
        self.assertIn("fetch('/open-software'", _PICKER_APP_JS)
        self.assertIn("function closeDccSoftware", _PICKER_APP_JS)
        self.assertIn("fetch('/close-software'", _PICKER_APP_JS)
        self.assertIn("if (toggle.classList.contains('is-on')) closeDccSoftware(row, toggle);", _PICKER_APP_JS)
        self.assertIn("function setDccSoftwareSwitch", _PICKER_APP_JS)
        self.assertIn("if (available) setDccSoftwareSwitch('houdini', true);", _PICKER_APP_JS)
        self.assertIn("setDccSoftwareSwitch(softwareId, ok);", _PICKER_APP_JS)
        self.assertIn("function saveDccSoftwarePath", _PICKER_APP_JS)
        self.assertIn("function updateDccSoftwarePaths", _PICKER_APP_JS)
        for label in ("Houdini", "Blender", "Unity", "Unreal", "Godot"):
            self.assertIn(label, _PICKER_INDEX_HTML)
        for removed in ("3ds Max", "Maya", "Cocos", "ZBrush"):
            self.assertNotIn(removed, _PICKER_INDEX_HTML)
        self.assertIn('data-dcc-id="houdini"', _PICKER_INDEX_HTML)
        self.assertIn('class="dcc-path-btn" aria-expanded="false" title="设置 Houdini 本地路径"', _PICKER_INDEX_HTML)
        self.assertIn('class="dcc-path-icon"', _PICKER_INDEX_HTML)
        self.assertIn('/area-picker/icons/lucide-folder.svg', _PICKER_STYLES)
        self.assertIn('/area-picker/icons/bootstrap-folder-fill.svg', _PICKER_STYLES)
        self.assertIn("clip-path: inset(0 100% 0 0);", _PICKER_STYLES)
        self.assertIn(".dcc-option-row.has-path .dcc-path-icon::after", _PICKER_STYLES)
        self.assertTrue((FRONTEND_ROOT / "icons" / "lucide-folder.svg").exists())
        self.assertTrue((FRONTEND_ROOT / "icons" / "bootstrap-folder-fill.svg").exists())
        self.assertTrue((FRONTEND_ROOT / "icons" / "LUCIDE_LICENSE.txt").exists())
        self.assertTrue((FRONTEND_ROOT / "icons" / "BOOTSTRAP_ICONS_LICENSE.txt").exists())
        self.assertIn('class="dcc-path-input" type="text"', _PICKER_INDEX_HTML)
        self.assertIn("dccPathCachePrefix = 'virtualcity.dcc.path.'", _PICKER_APP_JS)
        self.assertIn("function dccPathStorageKey", _PICKER_APP_JS)
        self.assertIn("function clearDccPathCache", _PICKER_APP_JS)
        self.assertIn("localStorage.setItem(dccPathStorageKey(row), value);", _PICKER_APP_JS)
        self.assertIn("localStorage.removeItem(key);", _PICKER_APP_JS)
        self.assertIn("paths[key] || getCachedDccPath(row)", _PICKER_APP_JS)
        self.assertIn("function saveAndCloseDccPathEditor", _PICKER_APP_JS)
        self.assertIn("event.key !== 'Enter'", _PICKER_APP_JS)
        self.assertIn("document.addEventListener('pointerdown'", _PICKER_APP_JS)
        self.assertIn("row.classList.toggle('has-path', !!value);", _PICKER_APP_JS)
        self.assertIn("panel.addEventListener('input'", _PICKER_APP_JS)
        self.assertIn("row.classList.toggle('has-path', !!input.value.trim());", _PICKER_APP_JS)
        self.assertIn("if (d.ok) row.classList.toggle('has-path', !!input.value.trim());", _PICKER_APP_JS)
        server_source = Path(area_picker.__file__).read_text(encoding="utf-8")
        self.assertIn("def _post_open_software", server_source)
        self.assertIn("parsed.path == '/open-software'", server_source)
        self.assertIn("def _post_close_software", server_source)
        self.assertIn("parsed.path == '/close-software'", server_source)

    def test_dccbridge_software_directory_resolves_to_exe(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blender = root / "blender.exe"
            blender.write_text("", encoding="utf-8")
            self.assertEqual(area_picker._resolve_software_launch_path("blender", str(root)), blender)

    def test_dccbridge_close_software_uses_process_name(self):
        fake_run = SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch.object(area_picker.os, "name", "nt"), \
                patch.object(area_picker, "_software_path_status", return_value={"blender_exe": "C:/missing/blender.exe"}), \
                patch.object(area_picker.subprocess, "run", return_value=fake_run) as run:
            payload = area_picker._close_software_from_config("blender")
        self.assertTrue(payload["ok"])
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[:3], ["powershell", "-NoProfile", "-Command"])
        self.assertIn("Get-Process -Name 'blender'", cmd[3])

    def test_restart_clears_dcc_path_cache(self):
        data = {
            "houdini_exe": "C:/Houdini/houdini.exe",
            "blender_exe": "C:/Blender/blender.exe",
            "unity_exe": "C:/Unity/Unity.exe",
            "unreal_exe": "C:/Unreal/UnrealEditor.exe",
            "godot_exe": "C:/Godot/Godot.exe",
            "unrelated": "keep",
        }
        with patch.object(area_picker, "_read_software_paths", return_value=dict(data)), \
                patch.object(area_picker, "_write_software_paths") as write_paths:
            area_picker._clear_dcc_path_cache()
        write_paths.assert_called_once_with({"unrelated": "keep"})

    def test_houdini_status_lives_in_action_panel(self):
        self.assertIn('id="houdini-badge"', _PICKER_FRONTEND)
        self.assertIn('id="houdini-connection-value"', _PICKER_FRONTEND)
        self.assertIn('id="houdini-asset-value"', _PICKER_FRONTEND)
        self.assertIn('id="houdini-export-value"', _PICKER_FRONTEND)
        self.assertIn("function updateHoudiniStatusPanel", _PICKER_FRONTEND)


class TestDataSourcesStatus(unittest.TestCase):
    def test_downloaded_area_status_counts_complete_directory_areas(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "RawData"
            (raw / "_downloads" / "area_snapshot").mkdir(parents=True)
            (raw / "_downloads" / "area_snapshot" / "roads.osm").write_text("<osm/>", encoding="utf-8")
            (raw / "_downloads" / "area_snapshot" / "buildings.geojson").write_text("{}", encoding="utf-8")
            (raw / "_downloads" / "area_snapshot" / "dem.csv").write_text("x,y,z\n", encoding="utf-8")
            (raw / "_downloads" / "area_incomplete").mkdir()
            (raw / "_downloads" / "area_incomplete" / "roads.osm").write_text("<osm/>", encoding="utf-8")

            (raw / "OSM").mkdir()
            (raw / "Overture").mkdir()
            (raw / "DEM").mkdir()
            (raw / "OSM" / "area_raw_osm_v001.osm").write_text("<osm/>", encoding="utf-8")
            (raw / "Overture" / "area_raw_buildings_overture_v001.geojson").write_text("{}", encoding="utf-8")
            (raw / "DEM" / "area_raw_dem_v001.csv").write_text("x,y,z\n", encoding="utf-8")
            (raw / "OSM" / "area_snapshot_osm_v001.osm").write_text("<osm/>", encoding="utf-8")
            (raw / "Overture" / "area_snapshot_buildings_overture_v001.geojson").write_text("{}", encoding="utf-8")
            (raw / "DEM" / "area_snapshot_dem_v001.csv").write_text("x,y,z\n", encoding="utf-8")

            with patch.object(area_picker, "ROOT", root):
                payload = area_picker._downloaded_area_status()

        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["area_ids"], ["area_raw", "area_snapshot"])
        # 无 macro-tile 下载时，quick_jumps 仅含 9 个预置城市书签，tile 数均为 0。
        self.assertEqual(len(payload["quick_jumps"]), len(area_picker.PRESET_CITY_JUMPS))
        self.assertTrue(all(j["source"] == "preset_city" for j in payload["quick_jumps"]))
        self.assertTrue(all(j["tile_count"] == 0 for j in payload["quick_jumps"]))
        self.assertTrue(all(j["jumpable"] and len(j["bbox"]) == 4 for j in payload["quick_jumps"]))

    def test_downloaded_area_status_builds_macro_tile_quick_jumps(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tiles = root / "RawData" / "_tiles"
            tiles.mkdir(parents=True)
            (tiles / "pattaya_dem.tif").write_bytes(b"tif")
            (tiles / "pattaya_osm.osm").write_text("<osm/>", encoding="utf-8")
            (tiles / "pattaya_bld.geojson").write_text("{}", encoding="utf-8")
            (tiles / "_index.json").write_text(json.dumps({
                "pattaya": {
                    "bbox": [100.84, 12.89, 100.92, 12.97],
                    "dem_tif": "F:\\VirtualCity\\RawData\\_tiles\\pattaya_dem.tif",
                    "osm_xml": "F:\\VirtualCity\\RawData\\_tiles\\pattaya_osm.osm",
                    "bld_geojson": "F:\\VirtualCity\\RawData\\_tiles\\pattaya_bld.geojson",
                }
            }), encoding="utf-8")

            with patch.object(area_picker, "ROOT", root):
                payload = area_picker._downloaded_area_status()

        self.assertEqual(payload["count"], 0)
        # pattaya 中心不属于任何预置城市，作为孤儿排在 9 个预置城市之前。
        self.assertEqual(len(payload["quick_jumps"]), 1 + len(area_picker.PRESET_CITY_JUMPS))
        jump = payload["quick_jumps"][0]
        self.assertEqual(jump["id"], "pattaya")
        self.assertEqual(jump["label"], "Pattaya")
        # 无真实清单时，按 bbox 反推得到 10x10=100 个格子，聚合成一片。
        self.assertEqual(jump["tile_count"], 100)
        self.assertTrue(jump["jumpable"])
        self.assertEqual(jump["source"], "downloaded_area")

    def test_macro_tile_prefers_manifest_tile_count_over_bbox_reverse_calc(self):
        # 真实下载清单存在时，tile_count 取一手记录，不再用粗 bbox 反推（121 不再塌成 100）。
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tiles = root / "RawData" / "_tiles"
            tiles.mkdir(parents=True)
            (tiles / "pattaya_dem.tif").write_bytes(b"tif")
            (tiles / "pattaya_osm.osm").write_text("<osm/>", encoding="utf-8")
            (tiles / "pattaya_bld.geojson").write_text("{}", encoding="utf-8")
            (tiles / "_index.json").write_text(json.dumps({
                "pattaya": {
                    "bbox": [100.84, 12.89, 100.92, 12.97],
                    "dem_tif": str(tiles / "pattaya_dem.tif"),
                    "osm_xml": str(tiles / "pattaya_osm.osm"),
                    "bld_geojson": str(tiles / "pattaya_bld.geojson"),
                }
            }), encoding="utf-8")
            areas = root / "RawData" / "_areas"
            areas.mkdir(parents=True)
            (areas / "pattaya.json").write_text(json.dumps({
                "area_id": "pattaya",
                "tile_count": 121,
                "tile_ids": [f"z47n_e{700000 + i * 1000}_n1429000_s1000" for i in range(121)],
                "bbox": [100.84, 12.89, 100.92, 12.97],
            }), encoding="utf-8")

            with patch.object(area_picker, "ROOT", root):
                payload = area_picker._downloaded_area_status()

        jump = payload["quick_jumps"][0]
        self.assertEqual(jump["id"], "pattaya")
        self.assertEqual(jump["tile_count"], 121)
        self.assertEqual(jump["source"], "downloaded_area")

    def test_downloaded_area_manifest_without_index_entry_appears_as_jump(self):
        # 真实下载（selection_id 命名）未进 _index.json 时，仍凭清单出现在跳转列表。
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            areas = root / "RawData" / "_areas"
            areas.mkdir(parents=True)
            sel_id = "z47n_e700000_n1429000_w11000_h11000_s1000"
            (areas / f"{sel_id}.json").write_text(json.dumps({
                "area_id": sel_id,
                "tile_count": 121,
                "tile_ids": [f"z47n_e{700000 + i * 1000}_n1429000_s1000" for i in range(121)],
                "bbox": [100.84, 12.89, 100.92, 12.97],
            }), encoding="utf-8")

            with patch.object(area_picker, "ROOT", root):
                payload = area_picker._downloaded_area_status()

        orphans = [j for j in payload["quick_jumps"] if j["source"] == "downloaded_area"]
        self.assertEqual(len(orphans), 1)
        self.assertEqual(orphans[0]["id"], sel_id)
        self.assertEqual(orphans[0]["tile_count"], 121)
        # bbox 现在是真实格子的几何外包，而非清单里的粗 bbox。
        self.assertEqual(len(orphans[0]["bbox"]), 4)
        west, south, east, north = orphans[0]["bbox"]
        self.assertLess(west, east)
        self.assertLess(south, north)

    def test_downloaded_area_inside_preset_city_folds_into_bookmark(self):
        # 已下载区域中心落在 Tokyo bbox 内：不另列孤儿，tile 数折叠进 Tokyo 书签。
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tiles = root / "RawData" / "_tiles"
            tiles.mkdir(parents=True)
            (tiles / "tk_dem.tif").write_bytes(b"tif")
            (tiles / "tk_osm.osm").write_text("<osm/>", encoding="utf-8")
            (tiles / "tk_bld.geojson").write_text("{}", encoding="utf-8")
            (tiles / "_index.json").write_text(json.dumps({
                "tokyo_shinjuku": {
                    "bbox": [139.69, 35.68, 139.71, 35.70],
                    "dem_tif": str(tiles / "tk_dem.tif"),
                    "osm_xml": str(tiles / "tk_osm.osm"),
                    "bld_geojson": str(tiles / "tk_bld.geojson"),
                }
            }), encoding="utf-8")

            with patch.object(area_picker, "ROOT", root):
                payload = area_picker._downloaded_area_status()

        jumps = payload["quick_jumps"]
        self.assertEqual(len(jumps), len(area_picker.PRESET_CITY_JUMPS))
        self.assertTrue(all(j["source"] == "preset_city" for j in jumps))
        tokyo = next(j for j in jumps if j["id"] == "tokyo")
        self.assertGreater(tokyo["tile_count"], 0)


        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg_dir = root / "Config"
            cfg_dir.mkdir()
            (root / "RawData" / "OSM").mkdir(parents=True)
            (root / "RawData" / "Overture").mkdir(parents=True)
            (root / "RawData" / "DEM").mkdir(parents=True)
            (root / "RawData" / "OSM" / "area_osm.osm").write_text("<osm></osm>", encoding="utf-8")
            (root / "RawData" / "Overture" / "area_buildings.geojson").write_text(
                '{"type":"FeatureCollection","features":[]}', encoding="utf-8")
            (root / "RawData" / "DEM" / "area_dem.csv").write_text("x,y,z\n0,0,0\n", encoding="utf-8")
            (cfg_dir / "active_area.json").write_text(json.dumps({
                "area_id": "area_test",
                "osm_file": "RawData/OSM/area_osm.osm",
                "buildings_file": "RawData/Overture/area_buildings.geojson",
                "dem_csv": "RawData/DEM/area_dem.csv",
                "dem_source": "fabdem",
                "sources": {
                    "roads": "tile_cache_osm_else_overpass_v1",
                    "buildings": "tile_cache_overture_else_overture_api_v1",
                    "dem": "fabdem_else_tile_cache_else_nasadem_v1",
                },
                "cache": {
                    "clip": {"status": "hit", "key": "bbox_test"}
                },
            }), encoding="utf-8")

            with patch.object(area_picker, "ROOT", root):
                payload = area_picker._data_sources_status()

        self.assertTrue(payload["available"])
        self.assertEqual(payload["area_id"], "area_test")
        self.assertEqual([item["key"] for item in payload["items"]], ["roads", "buildings", "terrain"])
        self.assertTrue(all(item["file"]["exists"] for item in payload["items"]))
        self.assertIn("OpenStreetMap", payload["items"][0]["provider"])
        self.assertIn("Overture", payload["items"][1]["provider"])
        self.assertIn("FABDEM", payload["items"][2]["provider"])
        self.assertIn("clip cache hit", payload["items"][0]["current"])
        self.assertIn("Overpass API", payload["items"][0]["strategy_label"])
        self.assertIn("Google 高度补全", payload["items"][1]["strategy_label"])
        self.assertIn("NASADEM 兜底", payload["items"][2]["strategy_label"])

class TestSelectionMemory(unittest.TestCase):
    def tearDown(self):
        area_picker._clear_remembered_selection()

    def test_selection_memory_round_trips_tile_ids(self):
        payload = area_picker._remember_selection([
            "z47n_e704000_n1429000_s1000",
            "z47n_e705000_n1429000_s1000",
        ])
        self.assertTrue(payload["available"])
        self.assertEqual(payload["selection_id"], "z47n_e704000_n1429000_w2000_h1000_s1000")
        self.assertEqual(payload["tile_count"], 2)

        status = area_picker._remembered_selection_status()
        self.assertTrue(status["available"])
        self.assertEqual(status["tile_ids"], payload["tile_ids"])
        self.assertGreater(status["updated_at"], 0)

        area_picker._clear_remembered_selection()
        self.assertFalse(area_picker._remembered_selection_status()["available"])


class TestRootLauncher(unittest.TestCase):
    def test_root_launcher_starts_native_desktop_window(self):
        launcher = ROOT / "启动WorldBuilder.cmd"
        self.assertTrue(launcher.exists())
        source = launcher.read_text(encoding="utf-8")
        self.assertIn("launch_virtualcity_console.ps1", source)

        launch_script = ROOT / "Scripts" / "launch_virtualcity_console.ps1"
        self.assertTrue(launch_script.exists())
        launch_source = launch_script.read_text(encoding="utf-8")
        # 桌面外壳模型：启动器跑 desktop.py（pywebview 原生窗口 + 同进程内嵌服务），
        # 不再开浏览器，也不再依赖网页心跳自杀（SHUTDOWN_WITH_PAGE）。
        self.assertIn("desktop.py", launch_source)
        self.assertNotIn("VC_AREA_PICKER_SHUTDOWN_WITH_PAGE", launch_source)
        self.assertNotIn("url.dll,FileProtocolHandler", launch_source)
        self.assertIn("Test-AreaPickerReady", launch_source)

        desktop = ROOT / "Scripts" / "desktop.py"
        self.assertTrue(desktop.exists())
        desktop_source = desktop.read_text(encoding="utf-8")
        self.assertIn("import webview", desktop_source)
        self.assertIn("VC_AREA_PICKER_NO_BROWSER", desktop_source)

    def test_root_reset_shortcut_uses_reset_script(self):
        shortcut = ROOT / "重置WorldBuilder服务.cmd"
        self.assertTrue(shortcut.exists())
        source = shortcut.read_text(encoding="utf-8")
        self.assertIn("reset_virtualcity_servers.ps1", source)
        self.assertNotIn("-StopUnknownPortOwners", source)


class TestFrontendAssetVersion(unittest.TestCase):
    def test_version_changes_when_asset_content_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            static_root = root / "_static"
            static_root.mkdir(parents=True)
            for name in (
                "app.js",
                "workspace.js",
                "selection_search.js",
                "pipeline_status.js",
                "dcc_bridge.js",
                "game_workbench.js",
                "vc_glb.js",
                "houdini_preview.js",
                "asset_dir.js",
                "styles.css",
                "index.html",
            ):
                (root / name).write_text("v1", encoding="utf-8")
            with patch.object(area_picker, "FRONTEND_ROOT", root), patch.object(area_picker, "STATIC_ROOT", static_root):
                first = area_picker._frontend_asset_version()
                # 改动 app.js 内容（size 变化），版本串必须随之变化。
                (root / "app.js").write_text("v2-longer-content", encoding="utf-8")
                second = area_picker._frontend_asset_version()
                (root / "styles.css").write_text("v3-longer-styles-content", encoding="utf-8")
                third = area_picker._frontend_asset_version()
                (root / "houdini_preview.js").write_text("v4-preview-content", encoding="utf-8")
                fourth = area_picker._frontend_asset_version()
        self.assertNotEqual(first, second)
        self.assertNotEqual(second, third)
        self.assertNotEqual(third, fourth)

    def test_version_is_stable_without_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            static_root = root / "_static"
            static_root.mkdir(parents=True)
            for name in (
                "app.js",
                "workspace.js",
                "selection_search.js",
                "pipeline_status.js",
                "dcc_bridge.js",
                "game_workbench.js",
                "vc_glb.js",
                "houdini_preview.js",
                "asset_dir.js",
                "styles.css",
                "index.html",
            ):
                (root / name).write_text("same", encoding="utf-8")
            with patch.object(area_picker, "FRONTEND_ROOT", root), patch.object(area_picker, "STATIC_ROOT", static_root):
                self.assertEqual(
                    area_picker._frontend_asset_version(),
                    area_picker._frontend_asset_version(),
                )

    def test_version_does_not_raise_on_missing_assets(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(area_picker, "FRONTEND_ROOT", Path(td)), patch.object(area_picker, "STATIC_ROOT", Path(td) / "_static"):
                self.assertIsInstance(area_picker._frontend_asset_version(), str)


class TestHoudiniStatus(unittest.TestCase):
    def test_build_status_records_whitebox_artifact_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            whitebox = root / "Houdini" / "Export" / "whitebox_v001.glb"
            whitebox.parent.mkdir(parents=True)
            whitebox.write_bytes(b"glb-data")
            with patch.object(houdini_status_writer, "ROOT", root):
                houdini_status_writer.write_build_status(
                    "area_test",
                    "completed",
                    root / "Houdini" / "Hip" / "area.hip",
                    "done",
                    "pass",
                    "Reports/model_qa/area_test.json",
                    "run_test",
                    whitebox_path=whitebox,
                )

            payload = json.loads((root / "Config" / "houdini_build_status.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["whitebox_path"], "Houdini/Export/whitebox_v001.glb")

    def test_run_terminal_confirms_completed_for_matching_run(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = root / "Reports" / "pipeline_runs"
            run_dir.mkdir(parents=True)
            (run_dir / "run_new.json").write_text(json.dumps({
                "run_id": "run_new",
                "area_id": "area_test",
                "status": "completed",
                "phase": "pipeline_completed",
                "events": [{"status": "completed", "phase": "pipeline_completed", "message": "done"}],
            }), encoding="utf-8")
            with patch.object(area_picker, "ROOT", root):
                done, ok, status, message = area_picker._read_run_terminal("run_new")
                self.assertTrue(done)
                self.assertTrue(ok)
                self.assertEqual(status, "completed")
                self.assertEqual(message, "done")

    def test_run_terminal_reports_failed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = root / "Reports" / "pipeline_runs"
            run_dir.mkdir(parents=True)
            (run_dir / "run_new.json").write_text(json.dumps({
                "run_id": "run_new",
                "area_id": "area_test",
                "status": "failed",
                "phase": "houdini_recook",
                "events": [{"status": "failed", "phase": "houdini_recook", "message": "QA failed"}],
            }), encoding="utf-8")
            with patch.object(area_picker, "ROOT", root):
                done, ok, status, message = area_picker._read_run_terminal("run_new")
                self.assertTrue(done)
                self.assertFalse(ok)
                self.assertEqual(status, "failed")

    def test_run_terminal_not_done_while_running(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = root / "Reports" / "pipeline_runs"
            run_dir.mkdir(parents=True)
            (run_dir / "run_new.json").write_text(json.dumps({
                "run_id": "run_new",
                "area_id": "area_test",
                "status": "running",
                "phase": "houdini_recook",
                "events": [],
            }), encoding="utf-8")
            with patch.object(area_picker, "ROOT", root):
                done, ok, _status, _message = area_picker._read_run_terminal("run_new")
                self.assertFalse(done)
                self.assertFalse(ok)

    def test_run_terminal_missing_record_is_not_done(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "Reports" / "pipeline_runs").mkdir(parents=True)
            with patch.object(area_picker, "ROOT", root):
                done, ok, _status, _message = area_picker._read_run_terminal("run_absent")
                self.assertFalse(done)
                self.assertFalse(ok)

    def test_failure_summary_extracts_model_qa_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "Config"
            qa_dir = root / "Reports" / "model_qa"
            run_dir = root / "Reports" / "pipeline_runs"
            cfg.mkdir(parents=True)
            qa_dir.mkdir(parents=True)
            run_dir.mkdir(parents=True)
            report = qa_dir / "area_test_quick.json"
            report.write_text(json.dumps({
                "status": "fail",
                "summary": {"pass": 1, "warn": 1, "fail": 1},
                "checks": [
                    {"name": "required_nodes", "status": "pass", "message": "ok"},
                    {
                        "name": "road_clipped_faces",
                        "status": "fail",
                        "message": "road_clipped geometry has invalid faces",
                        "details": {
                            "self_intersection_count": 954,
                            "self_intersecting_prim_count": 475,
                            "max_vertices": 210,
                        },
                    },
                    {
                        "name": "road_terrain_fit",
                        "status": "warn",
                        "message": "road_clipped has many terrain ray misses",
                        "details": {"misses": 1200, "sampled_points": 2934},
                    },
                ],
            }), encoding="utf-8")
            (cfg / "active_area.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
            }), encoding="utf-8")
            (cfg / "houdini_build_status.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "failed",
                "message": "model QA failed (see Reports/model_qa/area_test_quick.json)",
                "qa_status": "fail",
                "qa_report": "Reports/model_qa/area_test_quick.json",
            }), encoding="utf-8")
            (run_dir / "run_test.json").write_text(json.dumps({
                "run_id": "run_test",
                "area_id": "area_test",
                "status": "failed",
                "phase": "houdini_recook",
                "events": [
                    {"status": "failed", "phase": "houdini_recook", "message": "model QA failed"}
                ],
            }), encoding="utf-8")

            with patch.object(area_picker, "ROOT", root):
                summary = area_picker._failure_summary({
                    "done": True,
                    "ok": False,
                    "name": "area_test",
                    "run_id": "run_test",
                    "returncode": 1,
                })

        self.assertTrue(summary["available"])
        self.assertEqual(summary["stage"], "Houdini 7/7 Model QA")
        self.assertEqual(summary["check"], "road_clipped_faces")
        self.assertIn("invalid faces", summary["reason"])
        self.assertEqual(summary["report"], "Reports/model_qa/area_test_quick.json")
        self.assertIn("self intersections=954", summary["metrics_line"])
        self.assertEqual(summary["warnings"][0]["name"], "road_terrain_fit")

    def test_failure_summary_hides_while_pipeline_is_running(self):
        self.assertFalse(area_picker._failure_summary({"running": True})["available"])


class TestExportAvailability(unittest.TestCase):
    class _Geo:
        def __init__(self, points=10, prims=5):
            self._values = {"pointcount": points, "primitivecount": prims}

        def intrinsicValue(self, name):
            return self._values[name]

    class _Node:
        def __init__(self, *, visible=True, points=10, prims=5):
            self._visible = visible
            self._geo = TestExportAvailability._Geo(points, prims)

        def isDisplayFlagSet(self):
            return self._visible

        def geometry(self):
            return self._geo

    class _Conn:
        def __init__(self, node):
            self._config = {}
            self.modules = SimpleNamespace(hou=SimpleNamespace(node=lambda path: node))
            self.closed = False

        def close(self):
            self.closed = True

    def _probe_model(self, node):
        conn = self._Conn(node)
        fake_rpyc = SimpleNamespace(classic=SimpleNamespace(connect=lambda *args, **kwargs: conn))
        with patch.object(area_picker, "_probe_houdini", return_value=True), \
                patch.dict(sys.modules, {"rpyc": fake_rpyc}):
            result = area_picker._houdini_model_available({})
        self.assertTrue(conn.closed)
        return result

    def test_live_houdini_model_requires_visible_non_empty_out_city(self):
        self.assertTrue(self._probe_model(self._Node()))
        self.assertFalse(self._probe_model(self._Node(visible=False)))
        self.assertFalse(self._probe_model(self._Node(points=0)))
        self.assertFalse(self._probe_model(self._Node(prims=0)))
        self.assertFalse(self._probe_model(None))

    def test_houdini_asset_status_reports_export_readiness(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "Config"
            qa = root / "Reports" / "model_qa"
            cfg.mkdir()
            qa.mkdir(parents=True)
            (cfg / "active_area.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
            }), encoding="utf-8")
            (cfg / "houdini_build_status.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "completed",
                "qa_status": "pass",
                "qa_report": "Reports/model_qa/area_test_quick.json",
                "whitebox_path": "Houdini/Export/whitebox_v001.glb",
            }), encoding="utf-8")
            whitebox = root / "Houdini" / "Export" / "whitebox_v001.glb"
            whitebox.parent.mkdir(parents=True)
            whitebox.write_bytes(b"glb-data")
            (qa / "area_test_quick.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "pass",
            }), encoding="utf-8")
            with patch.object(area_picker, "ROOT", root), \
                    patch.object(area_picker, "_houdini_model_available", return_value=True):
                payload = area_picker._houdini_asset_status(True)
        self.assertTrue(payload["qa_ok"])
        self.assertTrue(payload["model_ready"])
        self.assertTrue(payload["export_ready"])
        self.assertTrue(payload["whitebox"]["available"])
        self.assertEqual(payload["whitebox"]["run_id"], "run_test")
        self.assertEqual(payload["whitebox"]["path"], "Houdini/Export/whitebox_v001.glb")
        self.assertIn("/whitebox.glb?", payload["whitebox"]["url"])

    def test_houdini_asset_status_reports_missing_whitebox_without_blocking_export(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "Config"
            qa = root / "Reports" / "model_qa"
            cfg.mkdir()
            qa.mkdir(parents=True)
            (cfg / "active_area.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
            }), encoding="utf-8")
            (cfg / "houdini_build_status.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "completed",
                "qa_status": "pass",
                "qa_report": "Reports/model_qa/area_test_quick.json",
                "whitebox_path": "Houdini/Export/missing.glb",
            }), encoding="utf-8")
            (qa / "area_test_quick.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "pass",
            }), encoding="utf-8")
            with patch.object(area_picker, "ROOT", root), \
                    patch.object(area_picker, "_houdini_model_available", return_value=True):
                payload = area_picker._houdini_asset_status(True)
        self.assertTrue(payload["export_ready"])
        self.assertFalse(payload["whitebox"]["available"])
        self.assertEqual(payload["whitebox"]["run_id"], "run_test")

    def test_export_requires_both_completed_qa_and_live_model(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "Config"
            qa = root / "Reports" / "model_qa"
            cfg.mkdir()
            qa.mkdir(parents=True)
            (cfg / "active_area.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
            }), encoding="utf-8")
            (cfg / "houdini_build_status.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "completed",
                "qa_status": "pass",
                "qa_report": "Reports/model_qa/area_test_quick.json",
            }), encoding="utf-8")
            (qa / "area_test_quick.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "pass",
            }), encoding="utf-8")
            with patch.object(area_picker, "ROOT", root), \
                    patch.object(area_picker, "_houdini_model_available", return_value=False):
                self.assertFalse(area_picker._export_available())
            (cfg / "houdini_build_status.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "failed",
                "qa_status": "fail",
                "qa_report": "Reports/model_qa/area_test_quick.json",
            }), encoding="utf-8")
            with patch.object(area_picker, "ROOT", root), \
                    patch.object(area_picker, "_houdini_model_available", return_value=True):
                self.assertFalse(area_picker._export_available())
            (cfg / "houdini_build_status.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "completed",
                "qa_status": "pass",
                "qa_report": "Reports/model_qa/area_test_quick.json",
            }), encoding="utf-8")
            with patch.object(area_picker, "ROOT", root), \
                    patch.object(area_picker, "_houdini_model_available", return_value=True):
                self.assertTrue(area_picker._export_available())

    def test_export_gate_blocks_stale_houdini_status(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "Config"
            cfg.mkdir()
            (cfg / "active_area.json").write_text(json.dumps({
                "area_id": "area_new",
                "run_id": "run_new",
            }), encoding="utf-8")
            (cfg / "houdini_build_status.json").write_text(json.dumps({
                "area_id": "area_old",
                "run_id": "run_old",
                "status": "completed",
            }), encoding="utf-8")
            gate = pipeline_status.export_gate(root, live_model_ready=True)
        self.assertFalse(gate["allowed"])
        self.assertIn("stale houdini status", gate["primary_reason"])

    def test_manual_review_required_gate_needs_same_run_approval(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "Config"
            qa = root / "Reports" / "model_qa"
            cfg.mkdir()
            qa.mkdir(parents=True)
            active = {
                "area_id": "area_test",
                "run_id": "run_test",
            }
            (cfg / "active_area.json").write_text(json.dumps(active), encoding="utf-8")
            (cfg / "houdini_build_status.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "completed",
                "qa_status": "warn",
                "qa_report": "Reports/model_qa/area_test_quick.json",
            }), encoding="utf-8")
            (qa / "area_test_quick.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "warn",
            }), encoding="utf-8")

            blocked = pipeline_status.export_gate(root, active, live_model_ready=True)
            manual_review.write_review("area_test", "run_old", root=root)
            still_blocked = pipeline_status.export_gate(root, active, live_model_ready=True)
            manual_review.write_review("area_test", "run_test", root=root)
            allowed = pipeline_status.export_gate(root, active, live_model_ready=True)

        self.assertFalse(blocked["allowed"])
        self.assertFalse(still_blocked["allowed"])
        self.assertTrue(allowed["allowed"])

    def test_export_gate_qa_fail_requires_review_not_hard_block(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "Config"
            qa = root / "Reports" / "model_qa"
            cfg.mkdir()
            qa.mkdir(parents=True)
            active = {
                "area_id": "area_test",
                "run_id": "run_test",
            }
            (cfg / "active_area.json").write_text(json.dumps(active), encoding="utf-8")
            (cfg / "houdini_build_status.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "completed",
                "qa_status": "fail",
                "qa_report": "Reports/model_qa/area_test_quick.json",
            }), encoding="utf-8")
            (qa / "area_test_quick.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "fail",
            }), encoding="utf-8")

            blocked = pipeline_status.export_gate(root, active, live_model_ready=True)
            manual_review.write_review("area_test", "run_test", root=root)
            allowed = pipeline_status.export_gate(root, active, live_model_ready=True)

        self.assertFalse(blocked["allowed"])
        self.assertTrue(blocked["requires_manual_review"])
        self.assertTrue(allowed["allowed"])
        previous = dict(area_picker._state)
        try:
            with area_picker._state_lock:
                area_picker._state["running"] = True
                area_picker._state["export_running"] = False
            with patch.object(area_picker, "_probe_houdini", return_value=True), \
                    patch.object(area_picker, "_export_available", side_effect=AssertionError("must not probe")):
                payload = area_picker._service_payload()
            self.assertFalse(payload["export_available"])
        finally:
            with area_picker._state_lock:
                area_picker._state.update(previous)


class TestSetAreaDataOnly(unittest.TestCase):
    def test_set_area_exposes_data_only_mode(self):
        source = (ROOT / "Scripts" / "acquisition" / "set_area.py").read_text(encoding="utf-8")
        self.assertIn("--data-only", source)
        self.assertIn("--acquire-only", source)
        self.assertIn("data_download_completed", source)
        self.assertIn("跳过 refine_data 与 Houdini 重算", source)

    def test_legacy_set_area_wrapper_points_to_acquisition_layer(self):
        source = (ROOT / "Scripts" / "set_area.py").read_text(encoding="utf-8")
        self.assertIn('SCRIPTS / "acquisition" / "set_area.py"', source)
        self.assertIn("runpy.run_path", source)

    def test_data_only_does_not_emit_houdini_completion_warning(self):
        source = (ROOT / "Scripts" / "app" / "area_picker" / "server.py").read_text(encoding="utf-8")
        self.assertIn("if ok and not houdini_done and not data_only:", source)

    def test_full_pipeline_uses_explicit_orchestrator(self):
        source = (ROOT / "Scripts" / "app" / "area_picker" / "server.py").read_text(encoding="utf-8")
        self.assertIn("orchestration/run_pipeline.py", source)
        self.assertIn("--tile-ids", source)
        self.assertIn("'acquisition/set_area.py', '--data-only'", source)

    def test_pipeline_command_builder_keeps_layered_entrypoints(self):
        selection = {
            "selection_id": "z47n_e704000_n1429000_w1000_h1000_s1000",
            "tile_ids": ["z47n_e704000_n1429000_s1000"],
            "bbox": [100.8802921, 12.9195947, 100.8895736, 12.9286991],
        }

        data_cmd = area_picker._pipeline_command_for_selection(selection, data_only=True)
        self.assertEqual(data_cmd[:6], ["uv", "run", "python", "-u", "acquisition/set_area.py", "--data-only"])
        self.assertNotIn("orchestration/run_pipeline.py", data_cmd)

        run_cmd = area_picker._pipeline_command_for_selection(selection, data_only=False)
        self.assertIn("orchestration/run_pipeline.py", run_cmd)
        self.assertIn("--tile-ids", run_cmd)
        self.assertIn("z47n_e704000_n1429000_s1000", run_cmd)

    def test_run_pipeline_orchestrator_exists(self):
        source = (ROOT / "Scripts" / "orchestration" / "run_pipeline.py").read_text(encoding="utf-8")
        self.assertIn("acquisition/set_area.py", source)
        self.assertIn("--acquire-only", source)
        self.assertIn("VC_PIPELINE_TILE_IDS", source)
        self.assertIn("cleaning/refine_data.py", source)
        self.assertIn("houdini_build/recook_new_area.py", source)


class TestServerStartup(unittest.TestCase):
    def test_current_server_is_reused(self):
        existing = {
            "server_version": area_picker.APP_VERSION,
            "pid": 123,
            "running": False,
            "run_id": "",
        }
        with patch.object(area_picker, "_probe_existing_server", return_value=existing), \
                patch.object(area_picker, "_open_browser") as open_browser:
            self.assertEqual(area_picker.main(), 0)
            open_browser.assert_called_once_with(f"http://{area_picker.PICKER_HOST}:{area_picker.PORT}")

    def test_legacy_server_is_rejected(self):
        existing = {
            "server_version": "",
            "legacy_server": True,
            "running": False,
            "run_id": "",
        }
        with patch.object(area_picker, "_probe_existing_server", return_value=existing), \
                patch.object(area_picker.urllib.request, "urlopen", side_effect=OSError("mocked shutdown request")), \
                patch.object(area_picker, "_open_browser") as open_browser:
            self.assertEqual(area_picker.main(), 2)
            open_browser.assert_not_called()


class TestPageShutdown(unittest.TestCase):
    def setUp(self):
        self._page_state = dict(area_picker._page_state)
        self._state = dict(area_picker._state)

    def tearDown(self):
        with area_picker._page_lock:
            area_picker._page_state.update(self._page_state)
        with area_picker._state_lock:
            area_picker._state.update(self._state)

    def test_page_shutdown_waits_for_close_grace(self):
        with area_picker._page_lock:
            area_picker._page_state.update({
                "seen": True,
                "last_seen": 10.0,
                "close_requested": True,
                "closed_at": 10.5,
            })
        with area_picker._state_lock:
            area_picker._state["running"] = False
            area_picker._state["export_running"] = False

        self.assertFalse(area_picker._page_shutdown_due(12.0, enabled=True))
        self.assertTrue(area_picker._page_shutdown_due(15.0, enabled=True))

    def test_page_shutdown_does_not_interrupt_running_pipeline(self):
        with area_picker._page_lock:
            area_picker._page_state.update({
                "seen": True,
                "last_seen": 10.0,
                "close_requested": True,
                "closed_at": 10.0,
            })
        with area_picker._state_lock:
            area_picker._state["running"] = True
            area_picker._state["export_running"] = False

        self.assertFalse(area_picker._page_shutdown_due(20.0, enabled=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
