"""Offline tests for confidence-tagged lane attribute normalization."""

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ProjectManagement" / "RoadResearch" / "road_test_pipeline" / "scripts" / "build_lane_attribute_model.py"
spec = importlib.util.spec_from_file_location("build_lane_attribute_model", SCRIPT)
lane_model = importlib.util.module_from_spec(spec)
sys.modules["build_lane_attribute_model"] = lane_model
assert spec.loader is not None
spec.loader.exec_module(lane_model)


class TestLaneAttributeModel(unittest.TestCase):
    def test_missing_turn_lanes_and_default_width_stay_visible(self):
        road_graph = {
            "edges": [
                {
                    "edge_id": "e_0001",
                    "source_feature_id": "way_1",
                    "highway": "residential",
                    "road_class": "residential",
                    "lanes": 2,
                    "lanes_source": "tag",
                    "width_m": 6.0,
                    "width_source": "default",
                    "oneway": False,
                    "oneway_direction": "bidirectional",
                    "length_m": 50.0,
                    "provider_tags": {"lanes": "2", "highway": "residential"},
                }
            ]
        }

        model, report = lane_model.build_lane_attribute_model(area_id="unit", road_graph=road_graph)
        item = model["edge_lane_attributes"][0]

        self.assertEqual(item["lane_count"]["value"], 2)
        self.assertEqual(item["lane_count"]["source"], "stage_policy_override")
        self.assertEqual(item["oneway"]["value"], {"oneway": False, "direction": "bidirectional"})
        self.assertEqual(item["oneway"]["source"], "stage_policy_override")
        self.assertEqual(item["width"]["value"], 6.4)
        self.assertEqual(item["width"]["source"], "stage_policy_override")
        self.assertEqual(item["turn_lanes"]["source"], "missing")
        self.assertIn("width_inferred", item["issues"])
        self.assertIn("lane_count_forced_bidirectional_two_lane_policy", item["issues"])
        self.assertIn("direction_forced_bidirectional_two_lane_policy", item["issues"])
        self.assertIn("missing_turn_lanes", item["issues"])
        self.assertLess(item["overall_confidence"], 0.6)
        self.assertEqual(report["counts"]["issue_counts"]["missing_turn_lanes"], 1)

    def test_turn_lanes_count_mismatch_is_flagged(self):
        road_graph = {
            "edges": [
                {
                    "edge_id": "e_0002",
                    "source_feature_id": "way_2",
                    "highway": "secondary",
                    "road_class": "secondary",
                    "lanes": 2,
                    "lanes_source": "tag",
                    "width_m": 7.0,
                    "width_source": "tag",
                    "oneway": True,
                    "oneway_direction": "forward",
                    "length_m": 80.0,
                    "provider_tags": {
                        "lanes": "2",
                        "width": "7",
                        "oneway": "yes",
                        "turn:lanes": "left|through|right",
                    },
                }
            ]
        }

        model, _report = lane_model.build_lane_attribute_model(area_id="unit", road_graph=road_graph)
        item = model["edge_lane_attributes"][0]

        self.assertEqual(item["turn_lanes"]["source"], "source_tag")
        self.assertIn("turn_lanes_count_mismatch", item["issues"])

    def test_explicit_source_oneway_is_overridden_to_bidirectional_two_lane_policy(self):
        road_graph = {
            "edges": [
                {
                    "edge_id": "e_0003",
                    "source_feature_id": "way_3",
                    "highway": "residential",
                    "road_class": "residential",
                    "lanes": 1,
                    "lanes_source": "tag",
                    "width_m": 3.2,
                    "width_source": "tag",
                    "oneway": True,
                    "oneway_direction": "forward",
                    "length_m": 60.0,
                    "provider_tags": {
                        "lanes": "1",
                        "width": "3.2",
                        "oneway": "yes",
                    },
                }
            ]
        }

        model, report = lane_model.build_lane_attribute_model(area_id="unit", road_graph=road_graph)
        item = model["edge_lane_attributes"][0]

        self.assertEqual(item["lane_count"]["value"], 2)
        self.assertEqual(item["width"]["value"], 6.4)
        self.assertEqual(item["per_lane_width_m"], 3.2)
        self.assertEqual(item["oneway"]["value"], {"oneway": False, "direction": "bidirectional"})
        self.assertTrue(item["source_observation"]["oneway"]["value"]["oneway"])
        self.assertIn("source_oneway_overridden_by_bidirectional_two_lane_policy", item["issues"])
        self.assertEqual(report["metrics"]["lane_count_policy_override_ratio"], 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
