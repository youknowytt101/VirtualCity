"""Connected-component aggregation of downloaded tiles into derived areas."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))

import area_aggregate
import vc_grid


def _tid(easting: int, northing: int, *, zone: int = 47, size: int = 1000) -> str:
    return f"z{zone}n_e{easting}_n{northing}_s{size}"


class TestAggregate(unittest.TestCase):
    def test_edge_adjacent_tiles_merge_into_one_area(self):
        # 一片 2x2 命名块，外加东侧紧邻 2x2 东边的一格，应并成单一区域。
        named_block = [_tid(e, n) for e in (700000, 701000) for n in (1424000, 1425000)]
        east_neighbor = [_tid(702000, 1424000)]  # 紧贴 701000 列东侧，共享一条边
        areas = area_aggregate.aggregate([
            {"id": "pattaya", "label": "Pattaya", "named": True, "tile_ids": named_block},
            {"id": "downloaded_area_x", "label": "", "named": False, "tile_ids": east_neighbor},
        ])
        self.assertEqual(len(areas), 1)
        self.assertEqual(areas[0]["tile_count"], 5)
        # 命名源在连通块内胜出，决定区域名。
        self.assertEqual(areas[0]["id"], "pattaya")
        self.assertEqual(areas[0]["label"], "Pattaya")

    def test_disconnected_tiles_stay_separate(self):
        block = [_tid(700000, 1424000)]
        far = [_tid(720000, 1424000)]  # 相距 20km，不连通
        areas = area_aggregate.aggregate([
            {"id": "pattaya", "label": "Pattaya", "named": True, "tile_ids": block},
            {"id": "downloaded_area_y", "label": "", "named": False, "tile_ids": far},
        ])
        self.assertEqual(len(areas), 2)
        # 按格子数降序、id 升序排列。
        ids = {a["id"] for a in areas}
        self.assertEqual(ids, {"pattaya", "downloaded_area_y"})

    def test_diagonal_only_tiles_do_not_merge(self):
        # 只在角点相接（对角）不算相邻，不应合并。
        a = [_tid(700000, 1424000)]
        b = [_tid(701000, 1425000)]
        areas = area_aggregate.aggregate([
            {"id": "a", "label": "", "named": False, "tile_ids": a},
            {"id": "b", "label": "", "named": False, "tile_ids": b},
        ])
        self.assertEqual(len(areas), 2)

    def test_named_source_wins_over_anonymous_in_component(self):
        # 匿名源贡献更多格子，但命名源仍应主导命名。
        anon = [_tid(700000, 1424000), _tid(701000, 1424000), _tid(702000, 1424000)]
        named = [_tid(703000, 1424000)]
        areas = area_aggregate.aggregate([
            {"id": "downloaded_area_z", "label": "", "named": False, "tile_ids": anon},
            {"id": "pattaya", "label": "Pattaya", "named": True, "tile_ids": named},
        ])
        self.assertEqual(len(areas), 1)
        self.assertEqual(areas[0]["id"], "pattaya")
        self.assertEqual(areas[0]["tile_count"], 4)

    def test_envelope_covers_all_tiles(self):
        block = [_tid(e, n) for e in (700000, 701000) for n in (1424000, 1425000)]
        areas = area_aggregate.aggregate([
            {"id": "pattaya", "label": "Pattaya", "named": True, "tile_ids": block},
        ])
        env = areas[0]["bbox"]
        for tid in block:
            west, south, east, north = vc_grid.tile_by_id(tid)["bbox"]
            self.assertLessEqual(env[0], west)
            self.assertLessEqual(env[1], south)
            self.assertGreaterEqual(env[2], east)
            self.assertGreaterEqual(env[3], north)

    def test_duplicate_tile_counted_once(self):
        shared = _tid(700000, 1424000)
        areas = area_aggregate.aggregate([
            {"id": "pattaya", "label": "Pattaya", "named": True, "tile_ids": [shared]},
            {"id": "other", "label": "", "named": False, "tile_ids": [shared]},
        ])
        self.assertEqual(len(areas), 1)
        self.assertEqual(areas[0]["tile_count"], 1)
        self.assertEqual(areas[0]["id"], "pattaya")


if __name__ == "__main__":
    unittest.main()