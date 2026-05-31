"""Offline tests for fixed UTM area-picker grid tiles."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))

import vc_grid


class TestTileIds(unittest.TestCase):
    def test_parse_and_build_tile_from_id(self):
        tile_id = "z47n_e704000_n1430000_s1000"
        with patch.object(vc_grid, "cache_coverage", return_value={"cached": False, "source": ""}):
            tile = vc_grid.tile_by_id(tile_id)
        self.assertEqual(tile["tile_id"], tile_id)
        self.assertEqual(tile["zone"], 47)
        self.assertTrue(tile["northern"])
        self.assertEqual(tile["easting"], 704000)
        self.assertEqual(tile["northing"], 1430000)
        self.assertEqual(tile["size_m"], 1000)
        self.assertEqual(len(tile["corners"]), 4)

    def test_rejects_unaligned_or_wrong_size_ids(self):
        with self.assertRaises(ValueError):
            vc_grid.parse_tile_id("z47n_e704001_n1430000_s1000")
        with self.assertRaises(ValueError):
            vc_grid.parse_tile_id("z47n_e704000_n1430000_s2000")
        with self.assertRaises(ValueError):
            vc_grid.parse_tile_id("../area")


class TestGridGeneration(unittest.TestCase):
    def test_tiles_are_aligned_to_fixed_one_km_grid(self):
        bbox = [100.86, 12.91, 100.89, 12.94]
        with patch.object(vc_grid, "cache_coverage", return_value={"cached": False, "source": ""}):
            data = vc_grid.tiles_for_bbox(bbox, max_tiles=100)
        self.assertFalse(data["truncated"])
        self.assertGreater(len(data["tiles"]), 0)
        for tile in data["tiles"]:
            self.assertEqual(tile["size_m"], vc_grid.TILE_SIZE_M)
            self.assertEqual(tile["easting"] % vc_grid.TILE_SIZE_M, 0)
            self.assertEqual(tile["northing"] % vc_grid.TILE_SIZE_M, 0)
            self.assertTrue(tile["tile_id"].startswith("z47n_"))

    def test_large_view_is_truncated(self):
        with patch.object(vc_grid, "cache_coverage", return_value={"cached": False, "source": ""}):
            data = vc_grid.tiles_for_bbox([100.0, 12.0, 102.0, 14.0], max_tiles=4)
        self.assertTrue(data["truncated"])
        self.assertEqual(data["tiles"], [])


class TestGridSelection(unittest.TestCase):
    def test_single_tile_selection_keeps_tile_bbox(self):
        with patch.object(vc_grid, "cache_coverage", return_value={"cached": False, "source": ""}):
            selection = vc_grid.selection_from_tile_ids(["z47n_e704000_n1430000_s1000"])
        self.assertEqual(selection["selection_id"], "z47n_e704000_n1430000_w1000_h1000_s1000")
        self.assertEqual(selection["cols"], 1)
        self.assertEqual(selection["rows"], 1)
        self.assertEqual(selection["tile_count"], 1)
        self.assertEqual(selection["width_m"], 1000)
        self.assertEqual(selection["height_m"], 1000)

    def test_rectangular_multi_tile_selection(self):
        ids = [
            "z47n_e704000_n1430000_s1000",
            "z47n_e705000_n1430000_s1000",
            "z47n_e704000_n1431000_s1000",
            "z47n_e705000_n1431000_s1000",
        ]
        with patch.object(vc_grid, "cache_coverage", return_value={"cached": True, "source": "unit"}):
            selection = vc_grid.selection_from_tile_ids(ids)
        self.assertEqual(selection["selection_id"], "z47n_e704000_n1430000_w2000_h2000_s1000")
        self.assertEqual(selection["cols"], 2)
        self.assertEqual(selection["rows"], 2)
        self.assertEqual(selection["tile_count"], 4)
        self.assertTrue(selection["cached"])
        self.assertEqual(selection["cached_tiles"], 4)

    def test_selection_rejects_gaps(self):
        ids = [
            "z47n_e704000_n1430000_s1000",
            "z47n_e706000_n1430000_s1000",
        ]
        with self.assertRaises(ValueError):
            vc_grid.selection_from_tile_ids(ids)

    def test_selection_rejects_non_rectangular_sets(self):
        ids = [
            "z47n_e704000_n1430000_s1000",
            "z47n_e705000_n1430000_s1000",
            "z47n_e704000_n1431000_s1000",
        ]
        with self.assertRaises(ValueError):
            vc_grid.selection_from_tile_ids(ids)

    def test_selection_rejects_too_many_tiles(self):
        ids = [
            f"z47n_e{704000 + i * 1000}_n1430000_s1000"
            for i in range(4)
        ]
        with self.assertRaises(ValueError):
            vc_grid.selection_from_tile_ids(ids, max_tiles=3)


class TestCacheCoverage(unittest.TestCase):
    def test_macro_tile_counts_as_cached(self):
        with patch.object(vc_grid._tile_cache, "find_covering_tile", return_value={"name": "macro"}), \
                patch.object(vc_grid.dcc, "find_covering_clip_cache") as clip:
            coverage = vc_grid.cache_coverage([100.86, 12.91, 100.88, 12.93])
        self.assertTrue(coverage["cached"])
        self.assertEqual(coverage["source"], "macro_tile")
        clip.assert_not_called()

    def test_covering_clip_cache_counts_as_cached(self):
        with patch.object(vc_grid._tile_cache, "find_covering_tile", return_value=None), \
                patch.object(vc_grid.dcc, "find_covering_clip_cache", return_value={"key": "bbox_parent"}):
            coverage = vc_grid.cache_coverage([100.86, 12.91, 100.88, 12.93])
        self.assertTrue(coverage["cached"])
        self.assertEqual(coverage["source"], "clip_cache")
        self.assertEqual(coverage["cache_key"], "bbox_parent")

    def test_missing_local_sources_are_uncached(self):
        with patch.object(vc_grid._tile_cache, "find_covering_tile", return_value=None), \
                patch.object(vc_grid.dcc, "find_covering_clip_cache", return_value=None):
            coverage = vc_grid.cache_coverage([100.86, 12.91, 100.88, 12.93])
        self.assertFalse(coverage["cached"])
        self.assertEqual(coverage["source"], "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
