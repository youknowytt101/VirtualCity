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


class TestPickerHtml(unittest.TestCase):
    def test_picker_uses_draw_rectangle_for_fixed_grid_blocks(self):
        self.assertIn("固定网格框选器", area_picker._HTML)
        self.assertIn("leaflet.draw", area_picker._HTML)
        self.assertIn("selectTilesByBounds", area_picker._HTML)
        self.assertIn("tile_ids", area_picker._HTML)
        self.assertIn("downloadData", area_picker._HTML)
        self.assertIn("zoomControl: false", area_picker._HTML)
        self.assertIn(".leaflet-control-zoom", area_picker._HTML)
        self.assertIn('id="selection-tools"', area_picker._HTML)
        self.assertIn("map-tool-control", area_picker._HTML)
        self.assertIn("activateRectangleTool", area_picker._HTML)
        self.assertIn("selectTileByLatLng", area_picker._HTML)
        self.assertIn("clearSelectionFromMapTool", area_picker._HTML)
        self.assertIn("bindSelectionTools", area_picker._HTML)
        self.assertNotIn("L.Control.Draw", area_picker._HTML)
        self.assertNotIn("leaflet-draw-edit-remove", area_picker._HTML)
        self.assertNotIn('id="clear-btn"', area_picker._HTML)
        self.assertNotIn("cached-only", area_picker._HTML)
        self.assertNotIn("只显示已有缓存", area_picker._HTML)

    def test_picker_uses_local_web_assets_and_online_basemap(self):
        self.assertIn('/static/leaflet/leaflet.css', area_picker._HTML)
        self.assertIn('/static/leaflet/leaflet.js', area_picker._HTML)
        self.assertIn('/static/leaflet-draw/leaflet.draw.css', area_picker._HTML)
        self.assertIn('/static/leaflet-draw/leaflet.draw.js', area_picker._HTML)
        self.assertNotIn('unpkg.com/leaflet', area_picker._HTML)
        self.assertNotIn('cdnjs.cloudflare.com/ajax/libs/leaflet.draw', area_picker._HTML)
        self.assertIn('tile.openstreetmap.org', area_picker._HTML)
        self.assertNotIn('run-mode', area_picker._HTML)
        self.assertNotIn('local-basemap-enabled', area_picker._HTML)
        self.assertNotIn('loadLocalBasemap', area_picker._HTML)
        self.assertIn('type="button" class="badge badge-warn" onclick="openOrProbeHoudini()"', area_picker._HTML)
        self.assertIn('function openOrProbeHoudini()', area_picker._HTML)
        self.assertIn('function probeHoudini()', area_picker._HTML)
        self.assertNotIn('setInterval(refreshServiceState', area_picker._HTML)
        self.assertIn('var shutdownWithPage = __SHUTDOWN_WITH_PAGE__;', area_picker._HTML)
        self.assertIn("navigator.sendBeacon('/session/closed'", area_picker._HTML)
        self.assertIn("fetch('/session'", area_picker._HTML)
        self.assertTrue(hasattr(area_picker, "_schedule_page_close_shutdown"))
        self.assertIn('exportFbx', area_picker._HTML)
        self.assertIn('id="download-btn" disabled onclick="downloadData()"', area_picker._HTML)
        self.assertIn('class="source-action-btn"', area_picker._HTML)
        self.assertIn("submitSelectedArea('/download-data'", area_picker._HTML)

    def test_lane_preview_button_is_not_exposed(self):
        removed_endpoint = "lane" + "-upgrade"
        self.assertNotIn(removed_endpoint, area_picker._HTML)
        self.assertNotIn("updateLaneUpgradeButton", area_picker._HTML)
        self.assertNotIn("handleLaneUpgrade", area_picker._HTML)

    def test_selection_survives_page_reload(self):
        self.assertIn("selectionStorageKey = 'vc.areaPicker.selection.v1'", area_picker._HTML)
        self.assertIn("function selectionPayloadFromSelection", area_picker._HTML)
        self.assertIn("function persistSelection()", area_picker._HTML)
        self.assertIn("function restoreSelectionFromPayload", area_picker._HTML)
        self.assertIn("function restoreRememberedSelection", area_picker._HTML)
        self.assertIn("function restorePendingSelection", area_picker._HTML)
        self.assertIn("fetch('/selection'", area_picker._HTML)
        self.assertIn("fetch('/selection/clear'", area_picker._HTML)
        self.assertIn("restoreRememberedSelection();", area_picker._HTML)
        self.assertIn("persistSelection();", area_picker._HTML)
        self.assertIn("syncDrawnSelectionLayer();", area_picker._HTML)
        self.assertIn("setRunStatus('warn', '待命', 0, '已选择区域，等待执行');", area_picker._HTML)
        self.assertIn("已恢复上次框选", area_picker._HTML)

    def test_selection_metrics_show_complete_data_area_count_and_bbox_only(self):
        self.assertIn("完整数据区域", area_picker._HTML)
        self.assertIn('id="downloaded-area-count"', area_picker._HTML)
        self.assertIn('id="selection-bbox"', area_picker._HTML)
        self.assertNotIn("已下载区域数量", area_picker._HTML)
        self.assertNotIn("网格数量", area_picker._HTML)
        self.assertNotIn("区域尺寸", area_picker._HTML)
        self.assertNotIn("缓存覆盖", area_picker._HTML)
        self.assertNotIn("网格矩阵", area_picker._HTML)
        self.assertNotIn('id="selection-count"', area_picker._HTML)
        self.assertNotIn('id="selection-size"', area_picker._HTML)
        self.assertNotIn('id="selection-cache"', area_picker._HTML)
        self.assertNotIn('id="selection-matrix"', area_picker._HTML)

    def test_picker_exposes_current_data_sources(self):
        self.assertIn('id="source-list"', area_picker._HTML)
        self.assertIn("function refreshDataSources()", area_picker._HTML)
        self.assertIn("fetch('/data-sources'", area_picker._HTML)
        self.assertIn("Overture Maps + Google Open Buildings", area_picker._HTML)

    def test_action_panel_groups_workflow_modules(self):
        self.assertIn('id="action-panel"', area_picker._HTML)
        self.assertIn("执行工作流", area_picker._HTML)
        self.assertIn("数据处理", area_picker._HTML)
        self.assertIn("软件链接", area_picker._HTML)
        self.assertIn("执行状态", area_picker._HTML)
        self.assertIn("建筑", area_picker._HTML)
        self.assertIn("地形", area_picker._HTML)
        self.assertIn("植被", area_picker._HTML)
        self.assertIn("车道", area_picker._HTML)
        self.assertIn("车道数据处理入口待接入", area_picker._HTML)
        self.assertIn("placeholder-btn", area_picker._HTML)
        self.assertIn('id="run-status-panel"', area_picker._HTML)
        self.assertIn('id="run-status-bar"', area_picker._HTML)
        self.assertIn("function updateRunStatusFromHealth", area_picker._HTML)
        self.assertIn('id="failure-summary"', area_picker._HTML)
        self.assertIn("function setFailureSummary", area_picker._HTML)
        self.assertIn("function logFailureSummary", area_picker._HTML)
        self.assertIn("上次失败", area_picker._HTML)
        self.assertNotIn("打开输出", area_picker._HTML)

    def test_workspace_uses_gapless_three_column_layout(self):
        self.assertIn('grid-template-areas: "controls map actions";', area_picker._HTML)
        self.assertIn("gap: 0;", area_picker._HTML)
        self.assertIn("grid-area: controls;", area_picker._HTML)
        self.assertIn("grid-area: map;", area_picker._HTML)
        self.assertIn("grid-area: actions;", area_picker._HTML)
        self.assertIn("border-radius: 0;", area_picker._HTML)
        self.assertNotIn("left: 18px;", area_picker._HTML)
        self.assertNotIn("right: 18px;", area_picker._HTML)
        self.assertNotIn("top: 18px;", area_picker._HTML)
        self.assertNotIn("max-height: calc(100% - 36px);", area_picker._HTML)

    def test_houdini_status_lives_in_action_panel(self):
        self.assertIn('id="houdini-badge"', area_picker._HTML)
        self.assertIn('id="houdini-connection-value"', area_picker._HTML)
        self.assertIn('id="houdini-asset-value"', area_picker._HTML)
        self.assertIn('id="houdini-export-value"', area_picker._HTML)
        self.assertIn("function updateHoudiniStatusPanel", area_picker._HTML)


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

    def test_data_sources_status_reads_active_area_files(self):
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

    def test_service_payload_skips_live_probe_while_pipeline_runs(self):
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
