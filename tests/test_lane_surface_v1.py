"""Offline tests for lane surface and junction envelope generation."""

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ProjectManagement" / "RoadResearch" / "road_test_pipeline" / "scripts" / "generate_lane_surface_v1.py"
spec = importlib.util.spec_from_file_location("generate_lane_surface_v1", SCRIPT)
surface_builder = importlib.util.module_from_spec(spec)
sys.modules["generate_lane_surface_v1"] = surface_builder
assert spec.loader is not None
spec.loader.exec_module(surface_builder)


class TestLaneSurfaceV1(unittest.TestCase):
    def test_junction_envelope_is_built_from_lane_link_ribbon_bounds(self):
        lane_graph = {
            "metadata": {"junction_trim_m": 8.0, "approach_centerlines_trimmed": True},
            "lanes": [
                {
                    "lane_id": "a_f_1",
                    "road_id": "a",
                    "direction": "forward",
                    "centerline_xz": [[0.0, 0.0], [8.0, 0.0]],
                    "approach_centerline_trimmed": True,
                },
                {
                    "lane_id": "b_f_1",
                    "road_id": "b",
                    "direction": "forward",
                    "centerline_xz": [[12.0, 10.0], [20.0, 10.0]],
                    "approach_centerline_trimmed": True,
                },
            ],
            "junctions": [
                {
                    "junction_id": "j0",
                    "node_id": "n0",
                    "type": "T",
                    "incident_roads": ["a", "b"],
                    "connections": [
                        {
                            "connection_id": "j0_c0",
                            "turn": "right",
                            "lane_links": [
                                {
                                    "lane_link_id": "j0_c0_ll0",
                                    "from_lane": "a_f_1",
                                    "to_lane": "b_f_1",
                                    "turn": "right",
                                    "connecting_curve_xz": [
                                        [8.0, 0.0],
                                        [10.0, 5.0],
                                        [12.0, 10.0],
                                    ],
                                    "width_m": 3.2,
                                    "width_start_m": 3.2,
                                    "width_end_m": 3.2,
                                },
                            ],
                        },
                    ],
                },
            ],
            "continuity_links": [],
        }

        features, stats = surface_builder.build_features(lane_graph)
        envelope = next(
            feature
            for feature in features
            if feature["properties"]["vc_part"] == "junction_envelope_surface_v1"
        )
        turn_surface = next(
            feature
            for feature in features
            if feature["properties"]["vc_part"] == "lane_turn_surface_v1"
        )

        self.assertEqual(stats["counts"]["junction_envelope_surfaces"], 1)
        self.assertEqual(envelope["properties"]["junction_id"], "j0")
        self.assertEqual(envelope["properties"]["lane_link_count"], 1)
        self.assertEqual(envelope["properties"]["turn_counts"], {"right": 1})
        self.assertGreater(envelope["properties"]["area_m2"], turn_surface["properties"]["area_m2"])
        self.assertGreaterEqual(len(envelope["geometry"]["coordinates"][0]), 4)

    def test_empty_junction_does_not_create_envelope(self):
        self.assertIsNone(surface_builder.junction_envelope_feature({
            "junction_id": "j0",
            "connections": [],
        }))


if __name__ == "__main__":
    unittest.main(verbosity=2)
