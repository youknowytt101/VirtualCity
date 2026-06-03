"""Offline tests for the road-test short-edge absorption planner."""

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ProjectManagement" / "RoadResearch" / "road_test_pipeline" / "scripts" / "plan_short_edge_absorptions.py"
spec = importlib.util.spec_from_file_location("plan_short_edge_absorptions", SCRIPT)
planner = importlib.util.module_from_spec(spec)
sys.modules["plan_short_edge_absorptions"] = planner
assert spec.loader is not None
spec.loader.exec_module(planner)


class TestShortEdgeAbsorptionPlanner(unittest.TestCase):
    def test_simple_collinear_short_edge_is_transaction_ready(self):
        road_graph = {
            "metadata": {"area_id": "unit"},
            "nodes": [
                {"node_id": "j", "kind": "junction", "degree": 3, "incident_edges": ["e_short", "e_west", "e_north"], "x": 0.0, "z": 0.0},
                {"node_id": "c", "kind": "connector", "degree": 2, "incident_edges": ["e_short", "e_next"], "x": 4.0, "z": 0.0},
                {"node_id": "f", "kind": "connector", "degree": 2, "incident_edges": ["e_next", "e_far"], "x": 24.0, "z": 0.0},
            ],
            "edges": [
                {"edge_id": "e_short", "from_node": "j", "to_node": "c", "length_m": 4.0, "geometry_xz": [[0.0, 0.0], [4.0, 0.0]]},
                {"edge_id": "e_next", "from_node": "c", "to_node": "f", "length_m": 20.0, "geometry_xz": [[4.0, 0.0], [24.0, 0.0]]},
                {"edge_id": "e_west", "from_node": "j", "to_node": "w", "length_m": 20.0, "geometry_xz": [[0.0, 0.0], [-20.0, 0.0]]},
                {"edge_id": "e_north", "from_node": "j", "to_node": "n", "length_m": 20.0, "geometry_xz": [[0.0, 0.0], [0.0, 20.0]]},
                {"edge_id": "e_far", "from_node": "f", "to_node": "x", "length_m": 20.0, "geometry_xz": [[24.0, 0.0], [44.0, 0.0]]},
            ],
        }
        junction_areas = {
            "junction_areas": [
                {
                    "junction_id": "j_000",
                    "node_id": "j",
                    "center_xz": [0.0, 0.0],
                    "approaches": [
                        {
                            "pose_id": "j_000_e_short_entry",
                            "edge_id": "e_short",
                            "node_id": "j",
                            "desired_trim_m": 8.0,
                            "entry_trim_m": 3.5,
                            "entry_xz": [3.5, 0.0],
                            "center_distance_m": 3.5,
                            "short_edge_absorption": {
                                "candidate": True,
                                "other_node_id": "c",
                                "other_node_kind": "connector",
                            },
                            "issues": ["entry_trim_capacity_limited", "short_edge_absorption_candidate"],
                        }
                    ],
                }
            ]
        }
        connector_candidates = {
            "cases": [
                {
                    "connector_id": "j_c_00",
                    "junction_node_id": "j",
                    "from_edge_id": "e_short",
                    "to_edge_id": "e_west",
                    "needs_solver": True,
                    "replacement_ready": False,
                }
            ]
        }

        candidate_doc, report = planner.plan_absorptions(
            area_id="unit",
            road_graph=road_graph,
            junction_areas=junction_areas,
            connector_candidates=connector_candidates,
        )

        candidate = candidate_doc["candidates"][0]
        self.assertEqual(candidate["status"], "transaction_ready")
        self.assertEqual(candidate["risk"], "low")
        self.assertEqual(candidate["path_edge_ids"], ["e_short", "e_next"])
        self.assertAlmostEqual(candidate["metrics"]["trim_recovery_m"], 4.5)
        self.assertEqual(report["counts"]["status_counts"]["transaction_ready"], 1)
        self.assertEqual(report["counts"]["affected_unresolved_connectors"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
