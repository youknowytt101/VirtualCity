"""Offline tests for remaining movement anchor gap audit."""

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ProjectManagement" / "RoadResearch" / "road_test_pipeline" / "scripts" / "audit_movement_anchors.py"
spec = importlib.util.spec_from_file_location("audit_movement_anchors", SCRIPT)
auditor = importlib.util.module_from_spec(spec)
sys.modules["audit_movement_anchors"] = auditor
assert spec.loader is not None
spec.loader.exec_module(auditor)


class TestMovementAnchorAudit(unittest.TestCase):
    def test_classifies_adjacent_junction_short_link(self):
        movement_corridors = {
            "cases": [
                {
                    "corridor_id": "mc_000",
                    "lane_link_id": "ll_000",
                    "node_id": "j_a",
                    "junction_id": "ja",
                    "movement_kind": "through",
                    "lane_entry_anchor": {
                        "role": "entry",
                        "source": "engineering_entry_pose_lateral_offset",
                        "edge_id": "e_ab",
                        "entry_trim_m": 5.4,
                        "issues": ["entry_anchor_entry_trim_capacity_limited"],
                    },
                    "lane_exit_anchor": {
                        "role": "exit",
                        "source": "engineering_entry_pose_lateral_offset",
                        "edge_id": "e_other",
                        "entry_trim_m": 8.0,
                        "issues": [],
                    },
                }
            ]
        }
        junction_areas = {
            "junction_areas": [
                {
                    "junction_id": "ja",
                    "node_id": "j_a",
                    "approaches": [
                        {
                            "edge_id": "e_ab",
                            "road_class": "secondary",
                            "edge_length_m": 5.9,
                            "desired_trim_m": 6.3,
                            "entry_trim_m": 5.4,
                        }
                    ],
                }
            ]
        }
        road_graph = {
            "nodes": [
                {"node_id": "j_a", "kind": "junction"},
                {"node_id": "j_b", "kind": "junction"},
            ],
            "edges": [
                {"edge_id": "e_ab", "from_node": "j_a", "to_node": "j_b", "length_m": 5.9, "road_class": "secondary"},
            ],
        }

        audit, report = auditor.audit_remaining_anchors(
            area_id="unit",
            movement_corridors=movement_corridors,
            junction_areas=junction_areas,
            road_graph=road_graph,
            short_edge_absorptions={"candidates": []},
        )

        self.assertEqual(report["counts"]["remaining_capacity_limited_anchors"], 1)
        self.assertEqual(report["counts"]["classification_counts"]["adjacent_junction_short_link"], 1)
        self.assertEqual(report["counts"]["recommended_action_counts"]["compound_junction_merge"], 1)
        self.assertEqual(audit["remaining_anchor_records"][0]["classification"], "adjacent_junction_short_link")

    def test_classifies_low_value_short_edge_absorption(self):
        movement_corridors = {
            "cases": [
                {
                    "corridor_id": "mc_001",
                    "lane_link_id": "ll_001",
                    "node_id": "j",
                    "junction_id": "j0",
                    "movement_kind": "right",
                    "lane_entry_anchor": {
                        "role": "entry",
                        "source": "engineering_entry_pose_lateral_offset",
                        "edge_id": "e_short",
                        "entry_trim_m": 5.95,
                        "issues": ["entry_anchor_entry_trim_capacity_limited", "entry_anchor_short_edge_absorption_candidate"],
                    },
                    "lane_exit_anchor": {
                        "role": "exit",
                        "source": "engineering_entry_pose_lateral_offset",
                        "edge_id": "e_out",
                        "entry_trim_m": 8.0,
                        "issues": [],
                    },
                }
            ]
        }
        junction_areas = {
            "junction_areas": [
                {
                    "junction_id": "j0",
                    "node_id": "j",
                    "approaches": [
                        {
                            "edge_id": "e_short",
                            "road_class": "secondary",
                            "edge_length_m": 6.4,
                            "desired_trim_m": 6.3,
                            "entry_trim_m": 5.95,
                        }
                    ],
                }
            ]
        }
        road_graph = {
            "nodes": [
                {"node_id": "j", "kind": "junction"},
                {"node_id": "c", "kind": "connector"},
            ],
            "edges": [
                {"edge_id": "e_short", "from_node": "j", "to_node": "c", "length_m": 6.4, "road_class": "secondary"},
            ],
        }
        short_edge_absorptions = {
            "candidates": [
                {
                    "candidate_id": "j_e_short_short_edge_absorption",
                    "junction_node_id": "j",
                    "short_edge_id": "e_short",
                    "status": "qa_candidate",
                    "issues": ["low_trim_recovery"],
                }
            ]
        }

        _audit, report = auditor.audit_remaining_anchors(
            area_id="unit",
            movement_corridors=movement_corridors,
            junction_areas=junction_areas,
            road_graph=road_graph,
            short_edge_absorptions=short_edge_absorptions,
        )

        self.assertEqual(report["counts"]["classification_counts"]["low_value_short_edge_absorption"], 1)
        self.assertEqual(report["counts"]["recommended_action_counts"]["defer"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
