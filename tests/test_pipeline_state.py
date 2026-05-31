"""Offline regression tests for pipeline run state and ready publication."""
import json
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


def _write_ready_file(path: Path, marker: str) -> None:
    path.write_text(marker * 1200, encoding="utf-8")


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


class TestReadyPublication(unittest.TestCase):
    def _populate(self, directory: Path, marker: str, *, run_id: str) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        for name in dcc.OUTPUT_NAMES.values():
            _write_ready_file(directory / name, marker)
        (directory / "meta.json").write_text(json.dumps({
            "area_id": "area_test",
            "run_id": run_id,
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
