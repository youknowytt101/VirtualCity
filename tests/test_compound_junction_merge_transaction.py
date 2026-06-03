"""Offline tests for trial compound junction merge transactions."""

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "ProjectManagement" / "RoadResearch" / "road_test_pipeline" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
SCRIPT = SCRIPTS_DIR / "apply_compound_junction_merges.py"
spec = importlib.util.spec_from_file_location("apply_compound_junction_merges", SCRIPT)
transaction = importlib.util.module_from_spec(spec)
sys.modules["apply_compound_junction_merges"] = transaction
assert spec.loader is not None
spec.loader.exec_module(transaction)


def _lane(lane_id, edge_id, lateral_offset=0.0):
    return {
        "lane_id": lane_id,
        "edge_id": edge_id,
        "width_m": 3.2,
        "lateral_offset_m": lateral_offset,
        "centerline_xz": [[0.0, 0.0], [10.0, 0.0]],
        "sources": {"turn_lanes": "missing"},
        "traffic_direction_policy": "temporary_bidirectional_two_lane_policy",
        "overall_confidence": 0.42,
    }


class TestCompoundJunctionMergeTransaction(unittest.TestCase):
    def test_composes_external_to_external_corridor_across_bridge_lane(self):
        compound_candidates = {
            "candidates": [
                {
                    "candidate_id": "unit_compound_merge_000",
                    "status": "transaction_candidate",
                    "risk": "low",
                    "member_junction_node_ids": ["j_a", "j_b"],
                    "bridge_edge_ids": ["e_bridge"],
                    "affected_anchor_records": 1,
                }
            ]
        }
        lane_graph = {
            "lanes": [
                _lane("ln_w_in", "e_w", lateral_offset=1.0),
                _lane("ln_bridge_f", "e_bridge", lateral_offset=1.0),
                _lane("ln_e_out", "e_e", lateral_offset=1.0),
            ],
            "lane_links": [
                {
                    "lane_link_id": "ll_entry",
                    "from_lane_id": "ln_w_in",
                    "to_lane_id": "ln_bridge_f",
                    "node_id": "j_a",
                    "junction_id": "ja",
                    "link_kind": "junction_movement",
                    "movement_kind": "through",
                    "confidence": 0.42,
                    "issues": ["inferred_without_turn_lanes"],
                },
                {
                    "lane_link_id": "ll_exit",
                    "from_lane_id": "ln_bridge_f",
                    "to_lane_id": "ln_e_out",
                    "node_id": "j_b",
                    "junction_id": "jb",
                    "link_kind": "junction_movement",
                    "movement_kind": "through",
                    "confidence": 0.42,
                    "issues": ["inferred_without_turn_lanes"],
                },
            ],
        }
        engineering_reference = {
            "approach_entry_poses": [
                {
                    "pose_id": "ja_e_w_entry",
                    "junction_id": "ja",
                    "node_id": "j_a",
                    "edge_id": "e_w",
                    "entry_xz": [-8.0, 0.0],
                    "tangent_out_xz": [-1.0, 0.0],
                    "entry_trim_m": 8.0,
                    "can_enter_junction": True,
                    "can_exit_junction": True,
                    "issues": [],
                },
                {
                    "pose_id": "jb_e_e_entry",
                    "junction_id": "jb",
                    "node_id": "j_b",
                    "edge_id": "e_e",
                    "entry_xz": [8.0, 0.0],
                    "tangent_out_xz": [1.0, 0.0],
                    "entry_trim_m": 8.0,
                    "can_enter_junction": True,
                    "can_exit_junction": True,
                    "issues": [],
                },
            ]
        }

        output, report = transaction.apply_compound_merges(
            area_id="unit",
            compound_candidates=compound_candidates,
            lane_graph=lane_graph,
            engineering_reference=engineering_reference,
            short_edge_absorptions={},
        )

        self.assertEqual(report["counts"]["accepted_for_staging"], 1)
        self.assertEqual(report["counts"]["compound_movement_corridor_cases"], 1)
        self.assertEqual(report["counts"]["exposed_bridge_edge_cases"], 0)
        self.assertEqual(report["counts"]["capacity_limited_anchor_cases"], 0)
        case = output["compound_movement_corridor_cases"][0]
        self.assertEqual(case["from_edge_id"], "e_w")
        self.assertEqual(case["to_edge_id"], "e_e")
        self.assertEqual(case["internal_bridge_edge_ids"], ["e_bridge"])
        self.assertEqual(case["lane_entry_anchor"]["source"], "engineering_entry_pose_lateral_offset")
        self.assertEqual(case["lane_exit_anchor"]["source"], "engineering_entry_pose_lateral_offset")
        self.assertNotIn("entry_trim_capacity_limited", " ".join(case["issues"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
