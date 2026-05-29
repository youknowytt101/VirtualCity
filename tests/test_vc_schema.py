"""
test_vc_schema.py — 语义契约校验回归测试（离线，无 Houdini）
============================================================
验证 vc_schema 的建筑属性完整性 / provenance 校验与道路连通性校验。

运行:
    python -m unittest discover -s tests
"""
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))

import vc_schema


def _status(checks, name):
    for c in checks:
        if c["name"] == name:
            return c["status"]
    return None


def _bld(height=10.0, source="overture"):
    props = {"height": height, "height_source": source, "class": "residential"}
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}


class TestBuildingContract(unittest.TestCase):
    def test_all_valid(self):
        checks = vc_schema.check_buildings([_bld(), _bld(20, "osm"), _bld(0, "estimated_pending")])
        self.assertEqual(_status(checks, "bld_height_present"), "pass")
        self.assertEqual(_status(checks, "bld_height_source"), "pass")

    def test_missing_height_source_fails(self):
        f = _bld()
        del f["properties"]["height_source"]
        checks = vc_schema.check_buildings([f])
        self.assertEqual(_status(checks, "bld_height_source"), "fail")

    def test_bad_height_source_fails(self):
        checks = vc_schema.check_buildings([_bld(10, "made_up")])
        self.assertEqual(_status(checks, "bld_height_source"), "fail")

    def test_missing_height_fails(self):
        f = _bld()
        del f["properties"]["height"]
        checks = vc_schema.check_buildings([f])
        self.assertEqual(_status(checks, "bld_height_present"), "fail")

    def test_empty_fails(self):
        checks = vc_schema.check_buildings([])
        self.assertEqual(checks[0]["status"], "fail")


def _osm(ways):
    """ways: list of (highway, [node_ids], extra_tags_dict). 自动生成 node 元素。"""
    root = ET.Element("osm")
    nodes = set()
    for _, refs, _ in ways:
        nodes.update(refs)
    for nid in sorted(nodes):
        ET.SubElement(root, "node", {"id": str(nid), "lon": "100.87", "lat": "12.92"})
    for hw, refs, extra in ways:
        w = ET.SubElement(root, "way", {"id": str(abs(hash((hw, tuple(refs)))) % 100000)})
        for r in refs:
            ET.SubElement(w, "nd", {"ref": str(r)})
        ET.SubElement(w, "tag", {"k": "highway", "v": hw})
        for k, v in (extra or {}).items():
            ET.SubElement(w, "tag", {"k": k, "v": str(v)})
    return root


class TestRoadContract(unittest.TestCase):
    def test_connected_chain_passes(self):
        # 1-2-3-4 全连通
        root = _osm([
            ("residential", [1, 2], {"lanes": 2, "oneway": "no"}),
            ("residential", [2, 3], {}),
            ("residential", [3, 4], {}),
        ])
        checks = vc_schema.check_roads(root)
        self.assertEqual(_status(checks, "road_connectivity"), "pass")
        self.assertEqual(_status(checks, "road_attr_coverage"), "pass")

    def test_fragmented_warns(self):
        # 多个互不相连的孤立段
        root = _osm([
            ("residential", [1, 2], {}),
            ("residential", [3, 4], {}),
            ("residential", [5, 6], {}),
            ("residential", [7, 8], {}),
        ])
        checks = vc_schema.check_roads(root)
        self.assertEqual(_status(checks, "road_connectivity"), "warn")

    def test_no_highway_fails(self):
        root = ET.Element("osm")
        checks = vc_schema.check_roads(root)
        self.assertEqual(checks[0]["status"], "fail")


if __name__ == "__main__":
    unittest.main(verbosity=2)
