import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "ProjectManagement" / "RoadResearch" / "road_test_pipeline" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
SCRIPT = SCRIPT_DIR / "score_movement_corridors.py"
spec = importlib.util.spec_from_file_location("score_movement_corridors", SCRIPT)
scorer = importlib.util.module_from_spec(spec)
sys.modules["score_movement_corridors"] = scorer
assert spec.loader is not None
spec.loader.exec_module(scorer)


class TestMovementCorridorScoring(unittest.TestCase):
    def test_legacy_lane_reference_alias_excludes_current_target_lanes(self):
        lane_graph = {
            "lanes": [
                {
                    "lane_id": "e_a_f_1",
                    "road_id": "e_a",
                    "direction": "forward",
                    "centerline_xz": [[0.0, 0.0], [10.0, 0.0]],
                },
                {
                    "lane_id": "e_b_f_1",
                    "road_id": "e_b",
                    "direction": "forward",
                    "centerline_xz": [[10.0, 2.0], [20.0, 2.0]],
                },
                {
                    "lane_id": "e_far_f_1",
                    "road_id": "e_far",
                    "direction": "forward",
                    "centerline_xz": [[0.0, 20.0], [20.0, 20.0]],
                },
            ]
        }
        movement_corridors = {
            "cases": [
                {
                    "corridor_id": "mc_alias",
                    "movement_kind": "through",
                    "from_lane_id": "ln_e_a_f_00",
                    "to_lane_id": "ln_e_b_f_00",
                    "candidates": [
                        {
                            "family": "topology_straight_baseline",
                            "centerline_xz": [[10.0, 0.0], [10.0, 2.0]],
                        }
                    ],
                }
            ]
        }

        scoring_doc, _report = scorer.score_document(
            area_id="unit",
            lane_graph=lane_graph,
            movement_corridors=movement_corridors,
            compound_transactions=None,
        )

        score = scoring_doc["cases"][0]["candidate_scores"][0]
        self.assertEqual(score["status"], "scored_qa_candidate")
        self.assertNotIn("collision_risk_non_target_lane_centerline", score["scoring_issues"])
        self.assertEqual(score["metrics"]["closest_non_target_lane_id"], "e_far_f_1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
