"""Offline tests for canonical road chain geometry refinement."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ProjectManagement" / "RoadResearch" / "road_test_pipeline" / "scripts" / "build_canonical_roads.py"
spec = importlib.util.spec_from_file_location("build_canonical_roads", SCRIPT)
canonical_builder = importlib.util.module_from_spec(spec)
sys.modules["build_canonical_roads"] = canonical_builder
assert spec.loader is not None
spec.loader.exec_module(canonical_builder)


ORIGIN_LON = 100.0
ORIGIN_LAT = 12.0


def _coord(x, z):
    lon, lat = canonical_builder.to_lonlat(x, z, ORIGIN_LON, ORIGIN_LAT)
    return [lon, lat]


def _feature(source_id, start, end):
    return {
        "type": "Feature",
        "properties": {
            "source_feature_id": source_id,
            "highway": "residential",
            "road_class": "residential",
            "lanes": "2",
            "width_m": "6",
            "oneway": "no",
        },
        "geometry": {
            "type": "LineString",
            "coordinates": [_coord(*start), _coord(*end)],
        },
    }


class TestCanonicalRoads(unittest.TestCase):
    def _build(self, features):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "repaired.geojson"
            dst = root / "canonical.geojson"
            report = root / "report.json"
            src.write_text(json.dumps({
                "type": "FeatureCollection",
                "metadata": {
                    "origin_lon": ORIGIN_LON,
                    "origin_lat": ORIGIN_LAT,
                },
                "features": features,
            }), encoding="utf-8")
            result = canonical_builder.build_canonical_roads(src, dst, report, "unit")
            return json.loads(dst.read_text(encoding="utf-8")), result

    def test_nearly_straight_chain_simplifies_internal_control_point(self):
        fc, report = self._build([
            _feature("a", (0.0, 0.0), (10.0, 0.03)),
            _feature("b", (10.0, 0.03), (20.0, 0.0)),
        ])

        self.assertEqual(len(fc["features"]), 1)
        props = fc["features"][0]["properties"]
        self.assertEqual(len(fc["features"][0]["geometry"]["coordinates"]), 2)
        self.assertEqual(props["canonical_vertices_removed"], 1)
        self.assertIn("centerline_vertex_simplification", props["canonical_ops"])
        self.assertEqual(report["geometry_refinement"]["vertices_removed"], 1)

    def test_sharp_corner_control_point_is_preserved(self):
        fc, report = self._build([
            _feature("a", (0.0, 0.0), (10.0, 0.0)),
            _feature("b", (10.0, 0.0), (10.0, 10.0)),
        ])

        self.assertEqual(len(fc["features"]), 1)
        props = fc["features"][0]["properties"]
        self.assertEqual(len(fc["features"][0]["geometry"]["coordinates"]), 3)
        self.assertEqual(props["canonical_vertices_removed"], 0)
        self.assertEqual(props["canonical_vertices_smoothed"], 0)
        self.assertEqual(report["geometry_refinement"]["vertices_removed"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
