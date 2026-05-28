"""
test_vc_geo.py — vc_geo 坐标约定回归测试（零依赖 stdlib unittest）
================================================================
锁定 VirtualCity 全项目唯一坐标约定，防止 H-002 / D-003 类 bug 回归。

运行:
    python -m unittest discover -s tests
或:
    python tests/test_vc_geo.py
"""
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))

import vc_geo
from _utm_lite import wgs84_to_utm, zone_number


class TestLocalProjector(unittest.TestCase):
    ORIGIN_LON = 100.865
    ORIGIN_LAT = 12.918

    def _legacy_to_local(self, lon, lat):
        """换 vc_geo 之前散落各脚本的旧实现，用作回归基准。"""
        z = zone_number(self.ORIGIN_LON)
        ox, oy, _ = wgs84_to_utm(self.ORIGIN_LAT, self.ORIGIN_LON, force_zone=z)
        x, y, _ = wgs84_to_utm(lat, lon, force_zone=z)
        return x - ox, y - oy

    def test_matches_legacy_implementation(self):
        proj = vc_geo.LocalProjector(self.ORIGIN_LON, self.ORIGIN_LAT)
        for dlon in (-0.01, 0.0, 0.005, 0.012):
            for dlat in (-0.008, 0.0, 0.006, 0.011):
                lon, lat = self.ORIGIN_LON + dlon, self.ORIGIN_LAT + dlat
                ex, ez = self._legacy_to_local(lon, lat)
                ax, az = proj.to_local(lon, lat)
                self.assertAlmostEqual(ax, ex, places=6)
                self.assertAlmostEqual(az, ez, places=6)

    def test_origin_is_local_zero(self):
        proj = vc_geo.LocalProjector(self.ORIGIN_LON, self.ORIGIN_LAT)
        x, z = proj.to_local(self.ORIGIN_LON, self.ORIGIN_LAT)
        self.assertAlmostEqual(x, 0.0, places=4)
        self.assertAlmostEqual(z, 0.0, places=4)

    def test_east_north_signs(self):
        """+经度 → +x(东)，+纬度 → +z(北)，数据域不翻 z。"""
        proj = vc_geo.LocalProjector(self.ORIGIN_LON, self.ORIGIN_LAT)
        xe, _ = proj.to_local(self.ORIGIN_LON + 0.01, self.ORIGIN_LAT)
        _, zn = proj.to_local(self.ORIGIN_LON, self.ORIGIN_LAT + 0.01)
        self.assertGreater(xe, 0.0)
        self.assertGreater(zn, 0.0)


class TestHoudiniConvention(unittest.TestCase):
    def test_z_flip_only_in_local_to_houdini(self):
        hx, hy, hz = vc_geo.local_to_houdini(10.0, 7.0)
        self.assertEqual((hx, hy, hz), (10.0, 0.0, -7.0))
        self.assertEqual(vc_geo.local_xz_to_houdini_xz(10.0, 7.0), (10.0, -7.0))


class TestWinding(unittest.TestCase):
    def test_needs_winding_flip_rule(self):
        # H-002: 数据域 signed_area > 0 时写入 Houdini 后法线朝下，需翻转
        self.assertTrue(vc_geo.needs_winding_flip(5.0))
        self.assertFalse(vc_geo.needs_winding_flip(-5.0))
        self.assertFalse(vc_geo.needs_winding_flip(0.0))

    def test_signed_area_ccw_positive(self):
        # XZ 平面逆时针正方形，shoelace > 0
        square = [(0, 0), (1, 0), (1, 1), (0, 1)]
        self.assertAlmostEqual(vc_geo.signed_area_xz(square), 1.0, places=6)


class TestBboxSize(unittest.TestCase):
    def test_matches_legacy_formula(self):
        w, s, e, n = 100.859, 12.912, 100.870, 12.923
        cl = (s + n) / 2.0
        ow = (e - w) * math.cos(math.radians(cl)) * 111319.9
        oh = (n - s) * 111319.9
        bw, bh = vc_geo.bbox_size_m([w, s, e, n])
        self.assertAlmostEqual(bw, ow, places=3)
        self.assertAlmostEqual(bh, oh, places=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
