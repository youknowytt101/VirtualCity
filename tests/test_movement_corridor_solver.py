"""Offline tests for movement corridor candidate generation."""

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ProjectManagement" / "RoadResearch" / "road_test_pipeline" / "scripts" / "solve_movement_corridors.py"
spec = importlib.util.spec_from_file_location("solve_movement_corridors", SCRIPT)
solver = importlib.util.module_from_spec(spec)
sys.modules["solve_movement_corridors"] = solver
assert spec.loader is not None
spec.loader.exec_module(solver)


def _lane(
    lane_id,
    edge_id,
    points,
    confidence=0.42,
    turn_source="missing",
    direction_policy="inferred_bidirectional_prior",
    lateral_offset_m=0.0,
):
    return {
        "lane_id": lane_id,
        "edge_id": edge_id,
        "direction": "forward",
        "travel_from_node": "n0",
        "travel_to_node": "n1",
        "width_m": 3.2,
        "lateral_offset_m": lateral_offset_m,
        "centerline_xz": points,
        "sources": {
            "turn_lanes": turn_source,
        },
        "traffic_direction_policy": direction_policy,
        "overall_confidence": confidence,
        "issues": [] if turn_source != "missing" else ["missing_turn_lanes"],
    }


class TestMovementCorridorSolver(unittest.TestCase):
    def test_junction_lane_link_generates_candidate_corridor(self):
        lane_graph = {
            "lanes": [
                _lane("ln_a", "e_a", [[0.0, 0.0], [8.0, 0.0]], confidence=0.42),
                _lane("ln_b", "e_b", [[10.0, 2.0], [18.0, 2.0]], confidence=0.42),
            ],
            "lane_links": [
                {
                    "lane_link_id": "ll_000",
                    "from_lane_id": "ln_a",
                    "to_lane_id": "ln_b",
                    "junction_id": "j0",
                    "node_id": "n1",
                    "link_kind": "junction_movement",
                    "movement_kind": "right",
                    "confidence": 0.42,
                    "issues": ["inferred_without_turn_lanes"],
                }
            ],
        }

        output, report = solver.solve_movement_corridors(area_id="unit", lane_graph=lane_graph)
        case = output["cases"][0]

        self.assertEqual(report["counts"]["corridor_cases"], 1)
        self.assertEqual(report["counts"]["candidate_curves"], 3)
        self.assertEqual(report["counts"]["reference_errors"], 0)
        self.assertEqual(case["status"], "qa_candidate")
        self.assertIn("inferred_without_turn_lanes", case["issues"])
        self.assertEqual(case["traffic_direction_policies"]["from_lane"], "inferred_bidirectional_prior")
        self.assertEqual(len(case["candidates"]), 3)
        self.assertTrue(all(candidate["centerline_xz"] for candidate in case["candidates"]))
        self.assertLess(report["metrics"]["avg_confidence"], 0.5)
        self.assertIn("inferred_bidirectional_prior->inferred_bidirectional_prior", report["counts"]["traffic_direction_policy_pair_counts"])
        self.assertEqual(report["counts"]["fallback_anchors"], 2)
        self.assertEqual(report["metrics"]["anchor_fallback_ratio"], 1.0)

    def test_engineering_entry_poses_generate_lane_level_anchors(self):
        lane_graph = {
            "lanes": [
                _lane("ln_in", "e_in", [[-10.0, 3.0], [0.0, 3.0]], confidence=0.8, turn_source="source_tag", lateral_offset_m=3.0),
                _lane("ln_out", "e_out", [[-2.0, 0.0], [-2.0, 10.0]], confidence=0.8, turn_source="source_tag", lateral_offset_m=2.0),
            ],
            "lane_links": [
                {
                    "lane_link_id": "ll_001",
                    "from_lane_id": "ln_in",
                    "to_lane_id": "ln_out",
                    "junction_id": "j0",
                    "node_id": "n1",
                    "link_kind": "junction_movement",
                    "movement_kind": "left",
                    "confidence": 0.8,
                    "issues": [],
                }
            ],
        }
        engineering_reference = {
            "approach_entry_poses": [
                {
                    "pose_id": "j0_e_in_entry",
                    "junction_id": "j0",
                    "node_id": "n1",
                    "edge_id": "e_in",
                    "entry_xz": [0.0, 0.0],
                    "tangent_out_xz": [-1.0, 0.0],
                    "entry_trim_m": 8.0,
                    "can_enter_junction": True,
                    "can_exit_junction": False,
                    "issues": [],
                },
                {
                    "pose_id": "j0_e_out_entry",
                    "junction_id": "j0",
                    "node_id": "n1",
                    "edge_id": "e_out",
                    "entry_xz": [0.0, 0.0],
                    "tangent_out_xz": [0.0, 1.0],
                    "entry_trim_m": 8.0,
                    "can_enter_junction": False,
                    "can_exit_junction": True,
                    "issues": [],
                },
            ]
        }

        output, report = solver.solve_movement_corridors(
            area_id="unit",
            lane_graph=lane_graph,
            engineering_reference=engineering_reference,
        )
        case = output["cases"][0]

        self.assertEqual(case["start_xz"], [0.0, 3.0])
        self.assertEqual(case["end_xz"], [-2.0, 0.0])
        self.assertEqual(case["start_tangent_xz"], [1.0, -0.0])
        self.assertEqual(case["end_tangent_xz"], [0.0, 1.0])
        self.assertEqual(case["lane_entry_anchor"]["source"], "engineering_entry_pose_lateral_offset")
        self.assertEqual(case["lane_exit_anchor"]["source"], "engineering_entry_pose_lateral_offset")
        self.assertEqual(case["lane_entry_anchor"]["pose_id"], "j0_e_in_entry")
        self.assertEqual(case["lane_exit_anchor"]["pose_id"], "j0_e_out_entry")
        self.assertEqual(report["counts"]["fully_anchored_cases"], 1)
        self.assertEqual(report["counts"]["fallback_anchors"], 0)
        self.assertEqual(report["counts"]["missing_anchor_poses"], 0)
        self.assertEqual(report["metrics"]["fully_anchored_case_ratio"], 1.0)
        self.assertEqual(report["metrics"]["anchor_fallback_ratio"], 0.0)

    def test_transaction_ready_short_edge_absorption_generates_planned_anchor(self):
        lane_graph = {
            "lanes": [
                _lane("ln_in", "e_short", [[-3.5, 2.0], [0.0, 2.0]], confidence=0.8, turn_source="source_tag", lateral_offset_m=2.0),
                _lane("ln_out", "e_out", [[0.0, 0.0], [0.0, 12.0]], confidence=0.8, turn_source="source_tag", lateral_offset_m=0.0),
            ],
            "lane_links": [
                {
                    "lane_link_id": "ll_002",
                    "from_lane_id": "ln_in",
                    "to_lane_id": "ln_out",
                    "junction_id": "j0",
                    "node_id": "n1",
                    "link_kind": "junction_movement",
                    "movement_kind": "right",
                    "confidence": 0.8,
                    "issues": [],
                }
            ],
        }
        engineering_reference = {
            "approach_entry_poses": [
                {
                    "pose_id": "j0_e_short_entry",
                    "junction_id": "j0",
                    "node_id": "n1",
                    "edge_id": "e_short",
                    "entry_xz": [-3.5, 0.0],
                    "tangent_out_xz": [-1.0, 0.0],
                    "entry_trim_m": 3.5,
                    "can_enter_junction": True,
                    "can_exit_junction": True,
                    "issues": ["entry_trim_capacity_limited", "short_edge_absorption_candidate"],
                },
                {
                    "pose_id": "j0_e_out_entry",
                    "junction_id": "j0",
                    "node_id": "n1",
                    "edge_id": "e_out",
                    "entry_xz": [0.0, 0.0],
                    "tangent_out_xz": [0.0, 1.0],
                    "entry_trim_m": 8.0,
                    "can_enter_junction": True,
                    "can_exit_junction": True,
                    "issues": [],
                },
            ]
        }
        short_edge_absorptions = {
            "candidates": [
                {
                    "candidate_id": "n1_e_short_short_edge_absorption",
                    "status": "transaction_ready",
                    "risk": "low",
                    "issues": [],
                    "junction_node_id": "n1",
                    "short_edge_id": "e_short",
                    "path_edge_ids": ["e_short", "e_next"],
                    "successor_edge_ids": ["e_next"],
                    "current_entry_pose": {
                        "entry_trim_m": 3.5,
                        "entry_xz": [-3.5, 0.0],
                        "issues": ["entry_trim_capacity_limited", "short_edge_absorption_candidate"],
                    },
                    "planned_entry_pose": {
                        "entry_trim_m": 8.0,
                        "entry_xz": [-8.0, 0.0],
                        "tangent_out_xz": [-1.0, 0.0],
                    },
                    "metrics": {
                        "trim_recovery_m": 4.5,
                    },
                }
            ]
        }

        output, report = solver.solve_movement_corridors(
            area_id="unit",
            lane_graph=lane_graph,
            engineering_reference=engineering_reference,
            short_edge_absorptions=short_edge_absorptions,
        )
        case = output["cases"][0]

        self.assertEqual(case["start_xz"], [-8.0, 2.0])
        self.assertEqual(case["lane_entry_anchor"]["source"], "junction_zone_expansion_planned_pose_lateral_offset")
        self.assertEqual(case["lane_entry_anchor"]["entry_trim_m"], 8.0)
        self.assertEqual(case["lane_entry_anchor"]["virtualization"]["base_entry_trim_m"], 3.5)
        self.assertEqual(case["lane_entry_anchor"]["virtualization"]["trim_recovery_m"], 4.5)
        self.assertEqual(case["lane_entry_anchor"]["issues"], [])
        self.assertEqual(report["counts"]["short_edge_absorption_planned_poses_indexed"], 1)
        self.assertEqual(report["counts"]["planned_virtual_anchors"], 1)
        self.assertEqual(report["counts"]["planned_virtual_anchor_cases"], 1)
        self.assertEqual(report["metrics"]["fully_anchored_case_ratio"], 1.0)

    def test_missing_lane_reference_is_reported(self):
        lane_graph = {
            "lanes": [
                _lane("ln_a", "e_a", [[0.0, 0.0], [8.0, 0.0]], confidence=0.8, turn_source="source_tag"),
            ],
            "lane_links": [
                {
                    "lane_link_id": "ll_000",
                    "from_lane_id": "ln_a",
                    "to_lane_id": "missing",
                    "link_kind": "junction_movement",
                    "confidence": 0.8,
                }
            ],
        }

        _output, report = solver.solve_movement_corridors(area_id="unit", lane_graph=lane_graph)

        self.assertEqual(report["counts"]["corridor_cases"], 0)
        self.assertEqual(report["counts"]["reference_errors"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
