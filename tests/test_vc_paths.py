"""Regression tests for project-root path helpers."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))

import vc_paths
from shared import vc_paths as shared_vc_paths


class TestProjectPaths(unittest.TestCase):
    def test_shared_vc_paths_resolves_project_root_after_package_move(self):
        self.assertIs(vc_paths, shared_vc_paths)
        self.assertEqual(vc_paths.ROOT, ROOT)
        self.assertEqual(vc_paths.SCRIPTS, ROOT / "Scripts")
        self.assertEqual(vc_paths.CONFIG, ROOT / "Config")
        self.assertEqual(vc_paths.DATA_ROOT, ROOT / "RawData")
        self.assertTrue((vc_paths.SCRIPTS / "pyproject.toml").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
