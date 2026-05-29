"""
test_vc_buildings.py — 建筑清洗纯函数回归测试（离线，无 IO，无 Houdini）
=======================================================================
覆盖 vc_buildings.transform_buildings 的过滤 / 高度清洗 / 去重 / MultiPolygon 决策。

运行:
    python -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))

import vc_buildings
from vc_geo import LocalProjector


# ── 构造小建筑 footprint 的辅助：在某经纬度造一个边长 side(米) 的方块 ────────
_ORIGIN_LON, _ORIGIN_LAT = 100.87, 12.92
_M_PER_DEG_LAT = 111319.9


def _square(lon, lat, side_m, height=None):
    dlat = side_m / _M_PER_DEG_LAT
    import math
    dlon = side_m / (_M_PER_DEG_LAT * math.cos(math.radians(lat)))
    ring = [
        [lon, lat], [lon + dlon, lat], [lon + dlon, lat + dlat],
        [lon, lat + dlat], [lon, lat],
    ]
    props = {} if height is None else {"height": height}
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": props}


class TestFiltering(unittest.TestCase):
    def test_null_geometry_removed(self):
        feats = [{"type": "Feature", "geometry": None, "properties": {}}]
        kept, stats = vc_buildings.transform_buildings(feats)
        self.assertEqual(kept, [])
        self.assertEqual(stats["removed_null"], 1)

    def test_non_polygon_removed(self):
        feats = [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}, "properties": {}}]
        kept, stats = vc_buildings.transform_buildings(feats)
        self.assertEqual(kept, [])
        self.assertEqual(stats["removed_null"], 1)

    def test_degenerate_removed(self):
        ring = [[100.87, 12.92], [100.8700001, 12.92], [100.87, 12.92]]
        feats = [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": {}}]
        kept, stats = vc_buildings.transform_buildings(feats)
        self.assertEqual(kept, [])
        self.assertEqual(stats["removed_degenerate"], 1)

    def test_tiny_removed(self):
        # 1m x 1m = 1 m^2 < MIN_AREA_M2 (5)
        feats = [_square(_ORIGIN_LON, _ORIGIN_LAT, 1.0)]
        kept, stats = vc_buildings.transform_buildings(feats)
        self.assertEqual(kept, [])
        self.assertEqual(stats["removed_tiny"], 1)

    def test_valid_kept(self):
        feats = [_square(_ORIGIN_LON, _ORIGIN_LAT, 10.0, height=12.0)]
        kept, stats = vc_buildings.transform_buildings(feats)
        self.assertEqual(len(kept), 1)
        self.assertEqual(stats["total_out"], 1)
        self.assertEqual(kept[0]["properties"]["height"], 12.0)


class TestHeight(unittest.TestCase):
    def test_missing_height_set_zero(self):
        feats = [_square(_ORIGIN_LON, _ORIGIN_LAT, 10.0)]  # no height
        kept, stats = vc_buildings.transform_buildings(feats)
        self.assertEqual(kept[0]["properties"]["height"], 0.0)
        self.assertEqual(stats["fixed_height"], 1)

    def test_nonpositive_height_set_zero(self):
        feats = [_square(_ORIGIN_LON, _ORIGIN_LAT, 10.0, height=0)]
        kept, stats = vc_buildings.transform_buildings(feats)
        self.assertEqual(kept[0]["properties"]["height"], 0.0)
        self.assertEqual(stats["fixed_height"], 1)

    def test_height_clamped(self):
        feats = [_square(_ORIGIN_LON, _ORIGIN_LAT, 10.0, height=9999)]
        kept, stats = vc_buildings.transform_buildings(feats)
        self.assertEqual(kept[0]["properties"]["height"], vc_buildings.MAX_HEIGHT_M)
        self.assertEqual(stats["clamped_height"], 1)


class TestDedup(unittest.TestCase):
    def test_near_duplicate_removed_keeps_first(self):
        a = _square(_ORIGIN_LON, _ORIGIN_LAT, 10.0, height=10)
        b = _square(_ORIGIN_LON, _ORIGIN_LAT, 10.0, height=99)  # same spot
        kept, stats = vc_buildings.transform_buildings([a, b])
        self.assertEqual(len(kept), 1)
        self.assertEqual(stats["removed_duplicate"], 1)
        self.assertEqual(kept[0]["properties"]["height"], 10)  # first kept

    def test_far_apart_both_kept(self):
        import math
        a = _square(_ORIGIN_LON, _ORIGIN_LAT, 10.0, height=10)
        # 50m east -> beyond 3m dedup threshold
        dlon = 50.0 / (_M_PER_DEG_LAT * math.cos(math.radians(_ORIGIN_LAT)))
        b = _square(_ORIGIN_LON + dlon, _ORIGIN_LAT, 10.0, height=20)
        kept, stats = vc_buildings.transform_buildings([a, b])
        self.assertEqual(len(kept), 2)
        self.assertEqual(stats["removed_duplicate"], 0)


class TestMultiPolygon(unittest.TestCase):
    def test_multipolygon_area_summed_and_geometry_preserved(self):
        import math
        # two 10m squares as one MultiPolygon
        s = 10.0
        dlat = s / _M_PER_DEG_LAT
        dlon = s / (_M_PER_DEG_LAT * math.cos(math.radians(_ORIGIN_LAT)))
        def ring(olon, olat):
            return [[olon, olat], [olon + dlon, olat], [olon + dlon, olat + dlat], [olon, olat + dlat], [olon, olat]]
        geom = {"type": "MultiPolygon", "coordinates": [[ring(_ORIGIN_LON, _ORIGIN_LAT)],
                                                         [ring(_ORIGIN_LON + 2 * dlon, _ORIGIN_LAT)]]}
        feats = [{"type": "Feature", "geometry": geom, "properties": {"height": 8}}]
        kept, stats = vc_buildings.transform_buildings(feats)
        self.assertEqual(len(kept), 1)
        # geometry passed through unchanged (MultiPolygon preserved)
        self.assertEqual(kept[0]["geometry"]["type"], "MultiPolygon")
        self.assertEqual(len(kept[0]["geometry"]["coordinates"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
