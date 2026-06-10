"""Offline regression tests for pipeline run state and ready publication."""
import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))

import data_cleaning_cache as dcc
import pipeline_state
import refine_data
from orchestration import build_history


def _write_ready_file(path: Path, marker: str) -> None:
    path.write_text(marker * 1200, encoding="utf-8")


def _fingerprint(path: Path) -> dict:
    data = path.read_bytes()
    return {
        "path": path.name,
        "exists": True,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


class TestPipelineState(unittest.TestCase):
    def test_run_manifest_tracks_phase_and_completion(self):
        with tempfile.TemporaryDirectory() as td:
            runs = Path(td) / "pipeline_runs"
            with patch.object(pipeline_state, "RUNS_DIR", runs), \
                    patch.object(pipeline_state, "LATEST_RUN", runs / "latest.json"):
                cfg = {"area_id": "area_test", "bbox": [1, 2, 3, 4]}
                created = pipeline_state.create_run(cfg, source="unit-test", run_id="run_test")
                self.assertEqual(created["status"], "running")

                pipeline_state.update_run("run_test", phase="refine_data", message="started")
                completed = pipeline_state.complete_run("run_test")

                self.assertEqual(completed["status"], "completed")
                self.assertEqual(completed["phase"], "completed")
                self.assertEqual(json.loads((runs / "latest.json").read_text(encoding="utf-8"))["run_id"],
                                 "run_test")
                self.assertEqual(len(completed["events"]), 3)

    def test_run_id_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            pipeline_state.run_path("../outside")


class TestBuildHistory(unittest.TestCase):
    def _sample_run(self) -> dict:
        return {
            "schema": 1,
            "run_id": "run_hist",
            "area_id": "area_hist",
            "bbox": [1, 2, 3, 4],
            "source": "unit-test",
            "status": "completed",
            "phase": "completed",
            "created": "2026-06-11T02:00:00",
            "updated": "2026-06-11T02:03:20",
            "events": [
                {"time": "2026-06-11T02:00:00", "status": "running", "phase": "created", "message": "created"},
                {"time": "2026-06-11T02:00:10", "status": "running", "phase": "refine_data", "message": "refine started"},
                {"time": "2026-06-11T02:00:20", "status": "running", "phase": "houdini_recook", "message": "recook started"},
                {"time": "2026-06-11T02:03:20", "status": "completed", "phase": "completed", "message": "done"},
            ],
        }

    def test_render_includes_module_breakdown_and_durations(self):
        md = build_history.render_markdown(self._sample_run())
        self.assertIn("## 模块耗时分解", md)
        self.assertIn("数据获取", md)
        self.assertIn("数据清洗", md)
        self.assertIn("Houdini 构建", md)
        # 总耗时 3m20s，Houdini 段 3m00s 应占绝大多数。
        self.assertIn("3m20s", md)
        self.assertIn("3m00s", md)

    def test_write_history_creates_per_run_file(self):
        with tempfile.TemporaryDirectory() as td:
            history = Path(td) / "build_history"
            target = build_history.write_history(self._sample_run(), history_dir=history)
            self.assertTrue(target.exists())
            self.assertEqual(target.name, "run_hist.md")
            self.assertIn("area_hist", target.read_text(encoding="utf-8"))

    def test_complete_run_archives_history(self):
        with tempfile.TemporaryDirectory() as td:
            runs = Path(td) / "pipeline_runs"
            history = Path(td) / "build_history"
            with patch.object(pipeline_state, "RUNS_DIR", runs), \
                    patch.object(pipeline_state, "LATEST_RUN", runs / "latest.json"), \
                    patch.object(build_history, "HISTORY_DIR", history):
                pipeline_state.create_run({"area_id": "area_hist"}, source="unit-test", run_id="run_hist")
                pipeline_state.complete_run("run_hist")
            self.assertTrue((history / "run_hist.md").exists())

    def test_write_history_for_unknown_run_is_silent(self):
        with tempfile.TemporaryDirectory() as td:
            runs = Path(td) / "pipeline_runs"
            with patch.object(pipeline_state, "RUNS_DIR", runs), \
                    patch.object(pipeline_state, "LATEST_RUN", runs / "latest.json"):
                self.assertIsNone(build_history.write_history_for_run("does_not_exist"))


class TestReadyPublication(unittest.TestCase):
    def _populate(self, directory: Path, marker: str, *, run_id: str) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        for name in dcc.OUTPUT_NAMES.values():
            _write_ready_file(directory / name, marker)
        (directory / "meta.json").write_text(json.dumps({
            "area_id": "area_test",
            "run_id": run_id,
        }), encoding="utf-8")
        (directory / "ready_manifest.json").write_text(json.dumps({
            "manifest_type": "virtualcity.houdini_ready",
            "area_id": "area_test",
            "run_id": run_id,
            "outputs": {
                name: _fingerprint(directory / name)
                for name in dcc.OUTPUT_NAMES.values()
            },
        }), encoding="utf-8")

    def test_ready_outputs_require_matching_run(self):
        with tempfile.TemporaryDirectory() as td:
            ready = Path(td) / "area_test"
            self._populate(ready, "new", run_id="run_new")
            self.assertTrue(dcc.ready_outputs_exist(
                ready, expected_area_id="area_test", expected_run_id="run_new"))
            self.assertFalse(dcc.ready_outputs_exist(
                ready, expected_area_id="area_test", expected_run_id="run_old"))

    def test_publish_replaces_previous_ready_directory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            staging_root = root / ".staging"
            staging = staging_root / "candidate"
            final = root / "area_test"
            self._populate(final, "old", run_id="run_old")
            self._populate(staging, "new", run_id="run_new")

            refine_data._publish_ready_dir(staging, final)

            meta = json.loads((final / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["run_id"], "run_new")
            self.assertFalse(staging.exists())
            self.assertFalse(any(staging_root.iterdir()))

    def test_publish_failure_restores_previous_ready_directory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            staging = root / ".staging" / "candidate"
            final = root / "area_test"
            self._populate(final, "old", run_id="run_old")
            self._populate(staging, "new", run_id="run_new")
            original_replace = Path.replace

            def fail_candidate(path, target):
                if path == staging:
                    raise OSError("simulated publish failure")
                return original_replace(path, target)

            with patch.object(Path, "replace", new=fail_candidate):
                with self.assertRaises(OSError):
                    refine_data._publish_ready_dir(staging, final)

            meta = json.loads((final / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["run_id"], "run_old")
            self.assertTrue(staging.exists())

    def test_ready_manifest_uses_final_ready_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            staging = root / ".staging" / "candidate"
            staging.mkdir(parents=True)
            for name in dcc.OUTPUT_NAMES.values():
                _write_ready_file(staging / name, "new")
            (staging / "meta.json").write_text("{}", encoding="utf-8")

            with patch.object(refine_data, "HOUDINI_READY", ROOT / "RawData" / "_houdini_ready"):
                ready = refine_data._write_ready_manifest(
                    staging,
                    {
                        "area_id": "area_test",
                        "run_id": "run_test",
                        "bbox": [1, 2, 3, 4],
                        "tile_ids": ["tile_a"],
                    },
                    {"levels": {"buildings": {"current": 3}, "roads": {"current": 2}, "dem": {"current": 2}}},
                    {"key": "cache_key", "fingerprint": "cache_fp"},
                    {"time": "now", "passed": True, "summary": {"pass": 1, "warn": 0, "fail": 0}},
                )

            self.assertEqual(ready["tile_ids"], ["tile_a"])
            self.assertEqual(
                ready["outputs"]["buildings.geojson"]["path"],
                "RawData/_houdini_ready/area_test/buildings.geojson",
            )
            self.assertNotIn(".staging", ready["outputs"]["buildings.geojson"]["path"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
