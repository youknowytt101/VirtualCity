"""Offline tests for compound junction merge planning."""

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ProjectManagement" / "RoadResearch" / "road_test_pipeline" / "scripts" / "plan_compound_junction_merges.py"
spec = importlib.util.spec_from_file_location("plan_compound_junction_merges", SCRIPT)
planner = importlib.util.module_from_spec(spec)
sys.modules["plan_compound_junction_merges"] = planner
assert spec.loader is not None
spec.loader.exec_module(planner)


class TestCompoundJunctionMergePlanner(unittest.TestCase):
    def test_adjacent_junction_short_link_becomes_transaction_candidate(self):
        movement_anchor_gap_audit = {
            "remaining_anchor_records": [
                {
                    "corridor_id": "mc_000",
                    "lane_link_id": "ll_000",
                    "junction_node_id": "j_a",
                    "edge_id": "e_bridge",
                    "edge_length_m": 5.8,
                    "desired_trim_m": 6.3,
                    "entry_trim_m": 5.3,
                    "trim_deficit_m": 1.0,
                    "road_class": "secondary",
                    "classification": "adjacent_junction_short_link",
                    "recommended_action": "compound_junction_merge",
                },
                {
                    "corridor_id": "mc_001",
                    "lane_link_id": "ll_001",
                    "junction_node_id": "j_b",
                    "edge_id": "e_bridge",
                    "edge_length_m": 5.8,
                    "desired_trim_m": 6.3,
                    "entry_trim_m": 5.3,
                    "trim_deficit_m": 1.0,
                    "road_class": "secondary",
                    "classification": "adjacent_junction_short_link",
                    "recommended_action": "compound_junction_merge",
                },
            ]
        }
        junction_areas = {
            "junction_areas": [
                {
                    "junction_id": "ja",
                    "node_id": "j_a",
                    "center_xz": [0.0, 0.0],
                    "conflict_zone_radius_m": 7.0,
                    "approaches": [
                        {"edge_id": "e_bridge", "edge_length_m": 5.8, "desired_trim_m": 6.3, "entry_trim_m": 5.3},
                        {"edge_id": "e_west", "edge_length_m": 20.0, "desired_trim_m": 6.3, "entry_trim_m": 6.3},
                    ],
                },
                {
                    "junction_id": "jb",
                    "node_id": "j_b",
                    "center_xz": [5.8, 0.0],
                    "conflict_zone_radius_m": 7.0,
                    "approaches": [
                        {"edge_id": "e_bridge", "edge_length_m": 5.8, "desired_trim_m": 6.3, "entry_trim_m": 5.3},
                        {"edge_id": "e_east", "edge_length_m": 20.0, "desired_trim_m": 6.3, "entry_trim_m": 6.3},
                    ],
                },
            ]
        }
        road_graph = {
            "nodes": [
                {"node_id": "j_a", "kind": "junction", "degree": 3, "x": 0.0, "z": 0.0, "incident_edges": ["e_west", "e_bridge", "e_north"]},
                {"node_id": "j_b", "kind": "junction", "degree": 3, "x": 5.8, "z": 0.0, "incident_edges": ["e_bridge", "e_east", "e_south"]},
                {"node_id": "w", "kind": "connector", "degree": 1, "x": -20.0, "z": 0.0, "incident_edges": ["e_west"]},
                {"node_id": "e", "kind": "connector", "degree": 1, "x": 25.8, "z": 0.0, "incident_edges": ["e_east"]},
                {"node_id": "n", "kind": "connector", "degree": 1, "x": 0.0, "z": 20.0, "incident_edges": ["e_north"]},
                {"node_id": "s", "kind": "connector", "degree": 1, "x": 5.8, "z": -20.0, "incident_edges": ["e_south"]},
            ],
            "edges": [
                {"edge_id": "e_bridge", "from_node": "j_a", "to_node": "j_b", "length_m": 5.8, "road_class": "secondary"},
                {"edge_id": "e_west", "from_node": "j_a", "to_node": "w", "length_m": 20.0, "road_class": "secondary"},
                {"edge_id": "e_east", "from_node": "j_b", "to_node": "e", "length_m": 20.0, "road_class": "secondary"},
                {"edge_id": "e_north", "from_node": "j_a", "to_node": "n", "length_m": 20.0, "road_class": "residential"},
                {"edge_id": "e_south", "from_node": "j_b", "to_node": "s", "length_m": 20.0, "road_class": "residential"},
            ],
        }

        candidate_doc, report = planner.plan_compound_junction_merges(
            area_id="unit",
            movement_anchor_gap_audit=movement_anchor_gap_audit,
            junction_areas=junction_areas,
            road_graph=road_graph,
        )

        self.assertEqual(report["counts"]["candidates"], 1)
        self.assertEqual(report["counts"]["transaction_candidates"], 1)
        self.assertEqual(report["counts"]["affected_corridors"], 2)
        candidate = candidate_doc["candidates"][0]
        self.assertEqual(candidate["status"], "transaction_candidate")
        self.assertEqual(candidate["risk"], "low")
        self.assertEqual(candidate["member_junction_node_ids"], ["j_a", "j_b"])
        self.assertEqual(candidate["bridge_edge_ids"], ["e_bridge"])
        self.assertEqual(candidate["affected_anchor_records"], 2)
        self.assertEqual(candidate["planned_compound_zone"]["model"], "union_of_member_junction_zones（成员路口影响区并集）")

    def test_non_compound_anchor_classes_are_ignored(self):
        movement_anchor_gap_audit = {
            "remaining_anchor_records": [
                {
                    "corridor_id": "mc_dead",
                    "lane_link_id": "ll_dead",
                    "junction_node_id": "j",
                    "edge_id": "e_dead",
                    "classification": "dead_end_stub_capacity_limited",
                    "recommended_action": "keep_qa",
                },
                {
                    "corridor_id": "mc_low",
                    "lane_link_id": "ll_low",
                    "junction_node_id": "j",
                    "edge_id": "e_low",
                    "classification": "low_value_short_edge_absorption",
                    "recommended_action": "defer",
                },
            ]
        }

        candidate_doc, report = planner.plan_compound_junction_merges(
            area_id="unit",
            movement_anchor_gap_audit=movement_anchor_gap_audit,
            junction_areas={"junction_areas": []},
            road_graph={"nodes": [], "edges": []},
        )

        self.assertEqual(candidate_doc["candidates"], [])
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["counts"]["ignored_classification_counts"]["dead_end_stub_capacity_limited"], 1)
        self.assertEqual(report["counts"]["ignored_classification_counts"]["low_value_short_edge_absorption"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
