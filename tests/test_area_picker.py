"""Offline tests for area_picker state and progress helpers."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
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
            open_browser.assert_called_once_with(f"http://localhost:{area_picker.PORT}")

    def test_legacy_server_is_rejected(self):
        existing = {
            "server_version": "",
            "legacy_server": True,
            "running": False,
            "run_id": "",
        }
        with patch.object(area_picker, "_probe_existing_server", return_value=existing), \
                patch.object(area_picker, "_open_browser") as open_browser:
            self.assertEqual(area_picker.main(), 2)
            open_browser.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
