"""Offline tests for the downloaded-area manifest read/write layer."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))

import area_manifest


class TestAreaManifest(unittest.TestCase):
    def test_write_records_real_tile_facts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ids = [f"z47n_e{700000 + i * 1000}_n1429000_s1000" for i in range(121)]
            record = area_manifest.write(
                "pattaya", tile_ids=ids,
                bbox=[100.84, 12.89, 100.92, 12.97],
                label="Pattaya", root=root,
            )
            self.assertEqual(record["tile_count"], 121)
            self.assertEqual(record["tile_ids"], ids)
            self.assertEqual(record["bbox"], [100.84, 12.89, 100.92, 12.97])

            on_disk = json.loads(
                (root / "RawData" / "_areas" / "pattaya.json").read_text(encoding="utf-8"))
            self.assertEqual(on_disk["tile_count"], 121)

    def test_write_dedupes_and_counts_clean_ids(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            record = area_manifest.write(
                "area_x", tile_ids=["a", " a ", "", "b"],
                bbox=[0, 0, 1, 1], root=root,
            )
            self.assertEqual(record["tile_count"], 3)
            self.assertEqual(record["tile_ids"], ["a", "a", "b"])

    def test_load_missing_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(area_manifest.load("nope", root=Path(td)))

    def test_load_all_collects_records_by_area_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            area_manifest.write("a", tile_ids=["t1"], bbox=[0, 0, 1, 1], root=root)
            area_manifest.write("b", tile_ids=["t1", "t2"], bbox=[1, 1, 2, 2], root=root)
            allrec = area_manifest.load_all(root)
            self.assertEqual(set(allrec), {"a", "b"})
            self.assertEqual(allrec["b"]["tile_count"], 2)

    def test_invalid_area_id_rejected(self):
        with self.assertRaises(ValueError):
            area_manifest.manifest_path("../escape")


if __name__ == "__main__":
    unittest.main()