"""Offline tests for lane geometry debug contract output."""

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ProjectManagement" / "RoadResearch" / "road_test_pipeline" / "scripts" / "generate_lane_geometry_debug.py"
spec = importlib.util.spec_from_file_location("generate_lane_geometry_debug", SCRIPT)
debug_builder = importlib.util.module_from_spec(spec)
sys.modules["generate_lane_geometry_debug"] = debug_builder
assert spec.loader is not None
spec.loader.exec_module(debug_builder)


class TestLaneGeometryDebug(unittest.TestCase):
    def test_debug_centerlines_follow_physical_lane_contract(self):
        lane_graph = {
            "metadata": {"junction_trim_m": 8.0},
            "lanes": [
                {
                    "lane_id": "e0_f_1",
                    "road_id": "e0",
                    "direction": "forward",
                    "width_m": 3.2,
                    "centerline_xz": [[0.0, 0.0], [10.0, 0.0]],
                },
                {
                    "lane_id": "e1_f_1",
                    "road_id": "e1",
                    "direction": "forward",
                    "width_m": 3.2,
                    "centerline_xz": [[10.0, 0.0], [20.0, 0.0]],
                },
            ],
            "physical_lane_centerlines": [
                {
                    "centerline_id": "plg_unit",
                    "source": "physical_lane_group_centerline_v1",
                    "source_lane_ids": ["e0_f_1", "e1_f_1"],
                    "road_ids": ["e0", "e1"],
                    "direction": "forward",
                    "member_count": 2,
                    "width_m": 3.2,
                    "physical_lane_group_id": "plg_unit",
                    "centerline_xz": [[0.0, 0.0], [10.0, 0.0], [20.0, 0.0]],
                },
            ],
            "junctions": [],
            "continuity_links": [
                {
                    "continuity_link_id": "micro_seam",
                    "from_lane": "e0_f_1",
                    "to_lane": "e1_f_1",
                    "same_physical_lane_continuity": True,
                    "micro_seam_absorbed": True,
                    "from_lane_trim_end_m": 3.0,
                    "to_lane_trim_start_m": 3.0,
                    "connecting_curve_xz": [[10.0, 0.0], [10.0, 0.0]],
                },
            ],
        }

        features, counts = debug_builder.geojson_features(lane_graph)
        centerlines = [
            feature
            for feature in features
            if feature["properties"]["vc_part"] == "lane_debug_centerline"
        ]

        self.assertEqual(len(centerlines), 1)
        self.assertEqual(counts["lane_centerlines"], 1)
        self.assertEqual(counts["debug_centerline_source_physical_lane_centerlines"], 1)
        self.assertEqual(counts["skipped_micro_seam_continuity_curve"], 1)
        self.assertEqual(centerlines[0]["properties"]["lane_id"], "plg_unit")
        self.assertEqual(centerlines[0]["properties"]["source_lane_ids"], ["e0_f_1", "e1_f_1"])
        self.assertEqual(centerlines[0]["properties"]["centerline_source"], "physical_lane_centerlines")
        self.assertEqual(centerlines[0]["geometry"]["coordinates"], [[0.0, 0.0], [10.0, 0.0], [20.0, 0.0]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
