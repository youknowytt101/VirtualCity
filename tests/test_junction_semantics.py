"""Offline tests for road-level junction semantic direction policy."""

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ProjectManagement" / "RoadResearch" / "road_test_pipeline" / "scripts" / "build_junction_semantics.py"
spec = importlib.util.spec_from_file_location("build_junction_semantics", SCRIPT)
junction_semantics = importlib.util.module_from_spec(spec)
sys.modules["build_junction_semantics"] = junction_semantics
assert spec.loader is not None
spec.loader.exec_module(junction_semantics)


def _edge(edge_id, from_node, to_node, points):
    return {
        "edge_id": edge_id,
        "from_node": from_node,
        "to_node": to_node,
        "road_class": "residential",
        "highway": "residential",
        "lanes": 1,
        "width_m": 3.2,
        "oneway": True,
        "oneway_direction": "forward",
        "geometry_xz": points,
    }


class TestJunctionSemantics(unittest.TestCase):
    def test_source_oneway_is_retained_but_temporary_policy_allows_bidirectional_movements(self):
        node = {"node_id": "n1", "incident_edges": ["e_in", "e_out"]}
        edges = {
            "e_in": _edge("e_in", "n0", "n1", [[0.0, 0.0], [10.0, 0.0]]),
            "e_out": _edge("e_out", "n1", "n2", [[10.0, 0.0], [20.0, 0.0]]),
        }

        approaches = junction_semantics.build_approaches(node, edges)
        movements = junction_semantics.build_movements(node, approaches, set(), "T")

        self.assertTrue(all(approach["can_enter_junction"] for approach in approaches))
        self.assertTrue(all(approach["can_exit_junction"] for approach in approaches))
        self.assertTrue(all(approach["source_oneway"] for approach in approaches))
        self.assertTrue(all(approach["oneway"] is False for approach in approaches))
        self.assertTrue(all(approach["lanes"] == 2 for approach in approaches))
        self.assertTrue(all(movement["allowed"] for movement in movements))
        self.assertTrue(any(not movement["source_direction_allowed"] for movement in movements))
        self.assertTrue(any(
            "source_oneway_ignored_by_temporary_bidirectional_two_lane_policy" in movement["notes"]
            for movement in movements
        ))


if __name__ == "__main__":
    unittest.main(verbosity=2)
