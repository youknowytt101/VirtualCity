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
import manual_review
import pipeline_status

FRONTEND_ROOT = Path(area_picker.FRONTEND_ROOT)
_PICKER_INDEX_HTML = area_picker._HTML
_PICKER_STYLES = (FRONTEND_ROOT / "styles.css").read_text(encoding="utf-8")
_PICKER_APP_JS = (FRONTEND_ROOT / "app.js").read_text(encoding="utf-8")
_PICKER_FRONTEND = "\n".join([_PICKER_INDEX_HTML, _PICKER_STYLES, _PICKER_APP_JS])


class TestProgressParsing(unittest.TestCase):
    def test_final_main_step_leaves_room_for_houdini_stages(self):
        update = area_picker._line_progress_update("[6/6] Houdini 重算...", 0)
        self.assertEqual(update["pct"], 75)
        self.assertEqual(update["step"], 6)
        self.assertIn("Houdini", update["step_label"])

    def test_houdini_stage_advances_progress(self):
        update = area_picker._line_progress_update("[Houdini 4/7] 全链路验证", 75)
        self.assertGreater(update["pct"], 85)
        self.assertEqual(update["step_label"], "[Houdini 4/7] 全链路验证")

    def test_houdini_completion_reaches_nearly_done(self):
        update = area_picker._line_progress_update("[OK] 全部通过，hip 已保存", 90)
        self.assertEqual(update["pct"], 99)


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
        self.assertIn('/area-picker/styles.css?v=__VERSION__', _PICKER_INDEX_HTML)
        self.assertIn('/area-picker/app.js?v=__VERSION__', _PICKER_INDEX_HTML)
        self.assertIn("window.VC_CONFIG", _PICKER_INDEX_HTML)
        self.assertNotIn("<style>", _PICKER_INDEX_HTML)
        self.assertIn("def _frontend_static", Path(area_picker.__file__).read_text(encoding="utf-8"))

    def test_picker_uses_draw_rectangle_for_fixed_grid_blocks(self):
        self.assertIn("固定网格框选器", _PICKER_FRONTEND)
        self.assertIn("leaflet.draw", _PICKER_FRONTEND)
        self.assertIn("selectTilesByBounds", _PICKER_FRONTEND)
        self.assertIn("function tileLatLngBounds(tile)", _PICKER_FRONTEND)
        self.assertIn("function tileDisplayBbox(tile)", _PICKER_FRONTEND)
        self.assertIn("function assignDisplayGridBounds(tiles)", _PICKER_FRONTEND)
        self.assertIn("tile.display_bbox =", _PICKER_FRONTEND)
        self.assertIn("bboxIntersects(bounds, tileDisplayBbox(tile))", _PICKER_FRONTEND)
        self.assertIn("L.rectangle(tileLatLngBounds(tile), options)", _PICKER_FRONTEND)
        self.assertNotIn("L.polygon(tile.corners, options)", _PICKER_FRONTEND)
        self.assertIn("tile_ids", _PICKER_FRONTEND)
        self.assertIn("downloadData", _PICKER_FRONTEND)
        self.assertIn("zoomControl: false", _PICKER_FRONTEND)
        self.assertIn(".leaflet-control-zoom", _PICKER_FRONTEND)
        self.assertIn('id="selection-tools"', _PICKER_FRONTEND)
        self.assertIn("map-tool-control", _PICKER_FRONTEND)
        self.assertIn("activateRectangleTool", _PICKER_FRONTEND)
        self.assertIn("selectTileByLatLng", _PICKER_FRONTEND)
        self.assertIn("clearSelectionFromMapTool", _PICKER_FRONTEND)
        self.assertIn("bindSelectionTools", _PICKER_FRONTEND)
        self.assertNotIn("L.Control.Draw", _PICKER_FRONTEND)
        self.assertNotIn("leaflet-draw-edit-remove", _PICKER_FRONTEND)
        self.assertNotIn('id="clear-btn"', _PICKER_FRONTEND)
        self.assertNotIn('id="legend"', _PICKER_FRONTEND)
        self.assertNotIn("未缓存：整体压暗", _PICKER_FRONTEND)
        self.assertNotIn("swatch-dim", _PICKER_FRONTEND)
        self.assertNotIn("cached-only", _PICKER_FRONTEND)
        self.assertNotIn("只显示已有缓存", _PICKER_FRONTEND)

    def test_picker_version_uses_public_date_semver_format(self):
        self.assertRegex(area_picker.APP_VERSION, r"^\d{2}-\d{2}-\d{2}_v\d+\.\d+$")

    def test_picker_uses_local_web_assets_and_online_basemap(self):
        self.assertIn('/static/leaflet/leaflet.css', _PICKER_FRONTEND)
        self.assertIn('/static/leaflet/leaflet.js', _PICKER_FRONTEND)
        self.assertIn('/static/leaflet-draw/leaflet.draw.css', _PICKER_FRONTEND)
        self.assertIn('/static/leaflet-draw/leaflet.draw.js', _PICKER_FRONTEND)
        self.assertNotIn('unpkg.com/leaflet', _PICKER_FRONTEND)
        self.assertNotIn('cdnjs.cloudflare.com/ajax/libs/leaflet.draw', _PICKER_FRONTEND)
        self.assertIn('tile.openstreetmap.org', _PICKER_FRONTEND)
        self.assertNotIn('run-mode', _PICKER_FRONTEND)
        self.assertNotIn('local-basemap-enabled', _PICKER_FRONTEND)
        self.assertNotIn('loadLocalBasemap', _PICKER_FRONTEND)
        self.assertIn('type="button" class="badge badge-warn" onclick="openOrProbeHoudini()"', _PICKER_FRONTEND)
        self.assertIn('function openOrProbeHoudini()', _PICKER_FRONTEND)
        self.assertIn('function probeHoudini()', _PICKER_FRONTEND)
        self.assertNotIn('setInterval(refreshServiceState', _PICKER_FRONTEND)
        self.assertIn('var shutdownWithPage = window.VC_CONFIG.shutdownWithPage;', _PICKER_FRONTEND)
        self.assertIn("navigator.sendBeacon('/session/closed'", _PICKER_FRONTEND)
        self.assertIn("fetch('/session'", _PICKER_FRONTEND)
        self.assertTrue(hasattr(area_picker, "_schedule_page_close_shutdown"))
        self.assertIn('exportFbx', _PICKER_FRONTEND)
        self.assertIn('id="download-btn" disabled onclick="downloadData()"', _PICKER_FRONTEND)
        self.assertIn('class="source-action-btn"', _PICKER_FRONTEND)
        self.assertIn("submitSelectedArea('/download-data'", _PICKER_FRONTEND)
        self.assertIn("filter: grayscale(1) saturate(0) contrast(1.38) brightness(0.44);", _PICKER_FRONTEND)
        self.assertIn("var isCached = !!tile.cached;", _PICKER_FRONTEND)
        self.assertIn("var cachedColor = '#f8fffd';", _PICKER_FRONTEND)
        self.assertIn("var gridLineColor = '#000000';", _PICKER_FRONTEND)
        self.assertIn("color: gridLineColor,", _PICKER_FRONTEND)
        self.assertIn("fillOpacity: isSelected ? (isCached ? 0.58 : 0.54) : (isCached ? 0.32 : 0),", _PICKER_FRONTEND)
        self.assertIn("opacity: 0.25,", _PICKER_FRONTEND)
        self.assertNotIn("opacity: isSelected ? 1.0 : 0.6", _PICKER_FRONTEND)
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
        self.assertIn("工作流", _PICKER_FRONTEND)
        self.assertIn("数据处理", _PICKER_FRONTEND)
        self.assertIn("软件链接", _PICKER_FRONTEND)
        self.assertIn("执行状态", _PICKER_FRONTEND)
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
        self.assertEqual(jump["tile_count"], 100)
        self.assertEqual(jump["bbox"], [100.84, 12.89, 100.92, 12.97])
        self.assertTrue(jump["jumpable"])
        self.assertEqual(jump["source"], "macro_tile")

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
    def test_root_launcher_starts_picker_with_page_lifecycle_shutdown(self):
        launcher = ROOT / "启动VirtualCity操作台.cmd"
        self.assertTrue(launcher.exists())
        source = launcher.read_text(encoding="utf-8")
        self.assertIn("launch_virtualcity_console.ps1", source)

        launch_script = ROOT / "Scripts" / "launch_virtualcity_console.ps1"
        self.assertTrue(launch_script.exists())
        launch_source = launch_script.read_text(encoding="utf-8")
        self.assertIn("VC_AREA_PICKER_SHUTDOWN_WITH_PAGE=1", launch_source)
        self.assertIn("VC_AREA_PICKER_NO_BROWSER=1", launch_source)
        self.assertIn("http://127.0.0.1:$Port/", launch_source)
        self.assertIn("Test-AreaPickerReady", launch_source)
        self.assertIn("Open-ConsoleUrl", launch_source)
        self.assertIn("url.dll,FileProtocolHandler", launch_source)

    def test_root_reset_shortcut_uses_reset_script(self):
        shortcut = ROOT / "重置VirtualCity网页服务.cmd"
        self.assertTrue(shortcut.exists())
        source = shortcut.read_text(encoding="utf-8")
        self.assertIn("reset_virtualcity_servers.ps1", source)
        self.assertNotIn("-StopUnknownPortOwners", source)


class TestFrontendAssetVersion(unittest.TestCase):
    def test_version_changes_when_asset_content_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ("app.js", "styles.css", "index.html"):
                (root / name).write_text("v1", encoding="utf-8")
            with patch.object(area_picker, "FRONTEND_ROOT", root):
                first = area_picker._frontend_asset_version()
                # 改动 app.js 内容（size 变化），版本串必须随之变化。
                (root / "app.js").write_text("v2-longer-content", encoding="utf-8")
                second = area_picker._frontend_asset_version()
        self.assertNotEqual(first, second)

    def test_version_is_stable_without_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ("app.js", "styles.css", "index.html"):
                (root / name).write_text("same", encoding="utf-8")
            with patch.object(area_picker, "FRONTEND_ROOT", root):
                self.assertEqual(
                    area_picker._frontend_asset_version(),
                    area_picker._frontend_asset_version(),
                )

    def test_version_does_not_raise_on_missing_assets(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(area_picker, "FRONTEND_ROOT", Path(td)):
                self.assertIsInstance(area_picker._frontend_asset_version(), str)


class TestHoudiniStatus(unittest.TestCase):
    def test_status_requires_matching_run_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "Config"
            cfg.mkdir()
            (cfg / "houdini_build_status.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_new",
                "status": "completed",
                "message": "ok",
            }), encoding="utf-8")

            with patch.object(area_picker, "ROOT", root):
                ok, status, message = area_picker._read_houdini_status("area_test", "run_new")
                self.assertTrue(ok)
                self.assertEqual(status, "completed")
                self.assertEqual(message, "ok")

                ok, status, message = area_picker._read_houdini_status("area_test", "run_old")
                self.assertFalse(ok)
                self.assertEqual(status, "completed")
                self.assertIn("run mismatch", message)

    def test_status_belongs_to_run_rejects_stale_other_run(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "Config"
            cfg.mkdir()
            # 状态文件停留在上一轮的 area/run（陈旧残留），本次 run 不应采信。
            (cfg / "houdini_build_status.json").write_text(json.dumps({
                "area_id": "area_old",
                "run_id": "run_old",
                "status": "failed",
                "message": "previous run failed",
            }), encoding="utf-8")
            with patch.object(area_picker, "ROOT", root):
                self.assertFalse(
                    area_picker._houdini_status_belongs_to_run("area_new", "run_new"))
                self.assertFalse(
                    area_picker._houdini_status_belongs_to_run("area_old", "run_new"))
                self.assertTrue(
                    area_picker._houdini_status_belongs_to_run("area_old", "run_old"))

    def test_status_belongs_to_run_false_when_file_missing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "Config").mkdir()
            with patch.object(area_picker, "ROOT", root):
                self.assertFalse(
                    area_picker._houdini_status_belongs_to_run("area_new", "run_new"))

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
            }), encoding="utf-8")
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
