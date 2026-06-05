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
        self.assertIn("cached-only", area_picker._HTML)
        self.assertIn("leaflet.draw", area_picker._HTML)
        self.assertIn("selectTilesByBounds", area_picker._HTML)
        self.assertIn("tile_ids", area_picker._HTML)
        self.assertIn("downloadData", area_picker._HTML)

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
        self.assertIn('type="button" class="badge badge-warn" onclick="probeHoudini()"', area_picker._HTML)
        self.assertIn('function probeHoudini()', area_picker._HTML)
        self.assertNotIn('setInterval(refreshServiceState', area_picker._HTML)
        self.assertIn('var shutdownWithPage = __SHUTDOWN_WITH_PAGE__;', area_picker._HTML)
        self.assertIn("navigator.sendBeacon('/session/closed'", area_picker._HTML)
        self.assertIn("fetch('/session'", area_picker._HTML)
        self.assertTrue(hasattr(area_picker, "_schedule_page_close_shutdown"))
        self.assertIn('exportFbx', area_picker._HTML)
        self.assertIn('id="download-btn" disabled onclick="downloadData()"', area_picker._HTML)
        self.assertIn("submitSelectedArea('/download-data'", area_picker._HTML)


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

    def test_export_requires_both_completed_qa_and_live_model(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "Config"
            cfg.mkdir()
            (cfg / "active_area.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
            }), encoding="utf-8")
            with patch.object(area_picker, "ROOT", root), \
                    patch.object(area_picker, "_read_houdini_status", return_value=(True, "completed", "ok")), \
                    patch.object(area_picker, "_houdini_model_available", return_value=False):
                self.assertFalse(area_picker._export_available())
            with patch.object(area_picker, "ROOT", root), \
                    patch.object(area_picker, "_read_houdini_status", return_value=(False, "failed", "bad")), \
                    patch.object(area_picker, "_houdini_model_available", return_value=True):
                self.assertFalse(area_picker._export_available())
            with patch.object(area_picker, "ROOT", root), \
                    patch.object(area_picker, "_read_houdini_status", return_value=(True, "completed", "ok")), \
                    patch.object(area_picker, "_houdini_model_available", return_value=True):
                self.assertTrue(area_picker._export_available())

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
        source = (ROOT / "Scripts" / "set_area.py").read_text(encoding="utf-8")
        self.assertIn("--data-only", source)
        self.assertIn("data_download_completed", source)
        self.assertIn("跳过 refine_data 与 Houdini 重算", source)

    def test_data_only_does_not_emit_houdini_completion_warning(self):
        source = (ROOT / "Scripts" / "area_picker.py").read_text(encoding="utf-8")
        self.assertIn("if ok and not houdini_done and not data_only and not lane_upgrade_prepare:", source)


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


class TestLaneForgeViewerStartup(unittest.TestCase):
    def test_laneforge_viewer_starts_direct_python_server(self):
        source = (ROOT / "Scripts" / "area_picker.py").read_text(encoding="utf-8")
        self.assertIn("laneforge_viewer_server.py", source)
        self.assertIn("subprocess.Popen", source)
        self.assertIn("_laneforge_ready(timeout=0.8, area_id=area_id)", source)
        self.assertNotIn("start_laneforge_viewer.ps1'\n", source)


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
