"""Offline tests for topology-only lane graph generation."""

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ProjectManagement" / "RoadResearch" / "road_test_pipeline" / "scripts" / "build_lane_graph.py"
spec = importlib.util.spec_from_file_location("build_lane_graph", SCRIPT)
lane_graph_builder = importlib.util.module_from_spec(spec)
sys.modules["build_lane_graph"] = lane_graph_builder
assert spec.loader is not None
spec.loader.exec_module(lane_graph_builder)


def _edge(edge_id, from_node, to_node, lanes=2, width=6.0, oneway=True, oneway_direction=None):
    return {
        "edge_id": edge_id,
        "from_node": from_node,
        "to_node": to_node,
        "source_feature_id": edge_id,
        "road_class": "residential",
        "highway": "residential",
        "lanes": lanes,
        "lanes_source": "tag",
        "width_m": width,
        "width_source": "tag",
        "oneway": oneway,
        "oneway_direction": oneway_direction if oneway_direction is not None else "forward" if oneway else "bidirectional",
        "length_m": 20.0,
        "geometry_xz": [[0.0, 0.0], [20.0, 0.0]] if from_node < to_node else [[20.0, 0.0], [0.0, 0.0]],
        "provider_tags": {},
    }


def _attr(edge_id, lanes=2, width=6.0, oneway=True, general_turn_lanes=None, oneway_source="source_tag", oneway_direction=None):
    turn_lanes = {
        "source": "missing",
        "confidence": 0.0,
        "general": [],
        "forward": [],
        "backward": [],
        "issues": ["missing_turn_lanes"],
    }
    issues = ["missing_turn_lanes"]
    if general_turn_lanes is not None:
        turn_lanes = {
            "source": "source_tag",
            "confidence": 0.9,
            "general": general_turn_lanes,
            "forward": [],
            "backward": [],
            "issues": [],
        }
        issues = []
    return {
        "edge_id": edge_id,
        "source_feature_id": edge_id,
        "road_class": "residential",
        "highway": "residential",
        "length_m": 20.0,
        "lane_count": {"value": lanes, "source": "source_tag", "confidence": 0.9, "issues": []},
        "width": {"value": width, "source": "source_tag", "confidence": 0.9, "issues": []},
        "per_lane_width_m": width / lanes,
        "oneway": {
            "value": {"oneway": oneway, "direction": oneway_direction if oneway_direction is not None else "forward" if oneway else "bidirectional"},
            "source": oneway_source,
            "confidence": 0.9,
            "issues": [],
        },
        "turn_lanes": turn_lanes,
        "overall_confidence": 0.9 if general_turn_lanes is not None else 0.45,
        "issues": issues,
    }


class TestLaneGraphBuilder(unittest.TestCase):
    def test_lane_graph_is_structured_artifact_with_inferred_links_flagged(self):
        road_graph = {
            "metadata": {"schema": "road_test_pipeline.road_graph.v1"},
            "nodes": [
                {"node_id": "n0", "kind": "boundary", "degree": 1, "incident_edges": ["e0"]},
                {"node_id": "n1", "kind": "junction", "degree": 2, "incident_edges": ["e0", "e1"]},
                {"node_id": "n2", "kind": "boundary", "degree": 1, "incident_edges": ["e1"]},
            ],
            "edges": [
                _edge("e0", "n0", "n1", lanes=2, width=6.0, oneway=True),
                _edge("e1", "n1", "n2", lanes=2, width=6.0, oneway=True),
            ],
        }
        lane_attribute_model = {"edge_lane_attributes": [_attr("e0"), _attr("e1")]}
        junction_semantics = {
            "metadata": {"schema": "road_test_pipeline.junction_semantics.v1"},
            "junctions": [
                {
                    "junction_id": "j0",
                    "node_id": "n1",
                    "type": "T",
                    "degree": 2,
                    "movements": [
                        {
                            "movement_id": "m0",
                            "from_edge": "e0",
                            "to_edge": "e1",
                            "kind": "through",
                            "allowed": True,
                            "confidence": 0.8,
                        }
                    ],
                }
            ],
        }

        graph, report = lane_graph_builder.build_lane_graph(
            area_id="unit",
            road_graph=road_graph,
            lane_attribute_model=lane_attribute_model,
            junction_semantics=junction_semantics,
            traffic_side="left",
        )

        self.assertEqual(graph["type"], "lane_graph")
        self.assertIn("structured graph data", graph["metadata"]["artifact_contract"])
        self.assertEqual(report["counts"]["lanes"], 4)
        self.assertEqual(report["counts"]["junction_lane_links"], 2)
        self.assertEqual(report["metrics"]["lane_link_reference_errors"], 0)
        self.assertGreater(report["counts"]["issue_counts"]["inferred_without_turn_lanes"], 0)
        self.assertLess(report["metrics"]["avg_lane_link_confidence"], 0.5)

    def test_single_lane_bidirectional_edge_becomes_shared_directed_lanes(self):
        road_graph = {
            "metadata": {},
            "nodes": [
                {"node_id": "n0", "kind": "boundary", "degree": 1, "incident_edges": ["e0"]},
                {"node_id": "n1", "kind": "boundary", "degree": 1, "incident_edges": ["e0"]},
            ],
            "edges": [_edge("e0", "n0", "n1", lanes=1, width=4.0, oneway=False)],
        }
        lane_attribute_model = {"edge_lane_attributes": [_attr("e0", lanes=1, width=4.0, oneway=False)]}

        graph, report = lane_graph_builder.build_lane_graph(
            area_id="unit",
            road_graph=road_graph,
            lane_attribute_model=lane_attribute_model,
            junction_semantics={"junctions": []},
            traffic_side="left",
        )

        self.assertEqual(report["counts"]["lanes"], 2)
        self.assertTrue(all(lane["shared_physical_lane"] for lane in graph["lanes"]))
        self.assertTrue(all(lane["lateral_offset_m"] == 0.0 for lane in graph["lanes"]))
        self.assertIn("bidirectional_shared_physical_lane", report["counts"]["issue_counts"])

    def test_unknown_direction_uses_bidirectional_prior_policy(self):
        road_graph = {
            "metadata": {},
            "nodes": [
                {"node_id": "n0", "kind": "boundary", "degree": 1, "incident_edges": ["e0"]},
                {"node_id": "n1", "kind": "boundary", "degree": 1, "incident_edges": ["e0"]},
            ],
            "edges": [_edge("e0", "n0", "n1", lanes=2, width=6.0, oneway=False, oneway_direction="unknown")],
        }
        lane_attribute_model = {
            "edge_lane_attributes": [
                _attr("e0", lanes=2, width=6.0, oneway=False, oneway_source="assumed_default", oneway_direction="unknown")
            ]
        }

        graph, report = lane_graph_builder.build_lane_graph(
            area_id="unit",
            road_graph=road_graph,
            lane_attribute_model=lane_attribute_model,
            junction_semantics={"junctions": []},
            traffic_side="left",
        )

        self.assertEqual(report["counts"]["lanes"], 2)
        self.assertEqual(graph["edge_lane_groups"][0]["traffic_direction_policy"], "inferred_bidirectional_prior")
        self.assertTrue(all(lane["traffic_direction_policy"] == "inferred_bidirectional_prior" for lane in graph["lanes"]))
        self.assertIn("direction_inferred_bidirectional_prior", report["counts"]["issue_counts"])
        self.assertEqual(report["traffic_direction_policy_counts"]["inferred_bidirectional_prior"], 2)

    def test_stage_policy_override_forces_source_oneway_to_bidirectional_two_lane_graph(self):
        road_graph = {
            "metadata": {},
            "nodes": [
                {"node_id": "n0", "kind": "boundary", "degree": 1, "incident_edges": ["e0"]},
                {"node_id": "n1", "kind": "boundary", "degree": 1, "incident_edges": ["e0"]},
            ],
            "edges": [_edge("e0", "n0", "n1", lanes=1, width=3.2, oneway=True)],
        }
        lane_attribute_model = {
            "edge_lane_attributes": [
                _attr("e0", lanes=2, width=6.4, oneway=False, oneway_source="stage_policy_override", oneway_direction="bidirectional")
            ]
        }

        graph, report = lane_graph_builder.build_lane_graph(
            area_id="unit",
            road_graph=road_graph,
            lane_attribute_model=lane_attribute_model,
            junction_semantics={"junctions": []},
            traffic_side="left",
        )

        self.assertEqual(report["counts"]["lanes"], 2)
        self.assertEqual(graph["edge_lane_groups"][0]["physical_lane_count"], 2)
        self.assertEqual(graph["edge_lane_groups"][0]["traffic_direction_policy"], "temporary_bidirectional_two_lane_policy")
        self.assertEqual({lane["direction"] for lane in graph["lanes"]}, {"forward", "backward"})
        self.assertEqual(report["traffic_direction_policy_counts"]["temporary_bidirectional_two_lane_policy"], 2)

    def test_source_turn_lanes_select_specific_incoming_lane(self):
        road_graph = {
            "metadata": {},
            "nodes": [
                {"node_id": "n0", "kind": "boundary", "degree": 1, "incident_edges": ["e0"]},
                {"node_id": "n1", "kind": "junction", "degree": 2, "incident_edges": ["e0", "e1"]},
                {"node_id": "n2", "kind": "boundary", "degree": 1, "incident_edges": ["e1"]},
            ],
            "edges": [
                _edge("e0", "n0", "n1", lanes=2, width=6.0, oneway=True),
                _edge("e1", "n1", "n2", lanes=1, width=3.0, oneway=True),
            ],
        }
        lane_attribute_model = {
            "edge_lane_attributes": [
                _attr("e0", lanes=2, width=6.0, general_turn_lanes=[["left"], ["through"]]),
                _attr("e1", lanes=1, width=3.0, general_turn_lanes=[["through"]]),
            ]
        }
        junction_semantics = {
            "junctions": [
                {
                    "junction_id": "j0",
                    "node_id": "n1",
                    "type": "T",
                    "degree": 2,
                    "movements": [
                        {
                            "movement_id": "m0",
                            "from_edge": "e0",
                            "to_edge": "e1",
                            "kind": "left",
                            "allowed": True,
                            "confidence": 0.8,
                        }
                    ],
                }
            ],
        }

        graph, report = lane_graph_builder.build_lane_graph(
            area_id="unit",
            road_graph=road_graph,
            lane_attribute_model=lane_attribute_model,
            junction_semantics=junction_semantics,
            traffic_side="left",
        )

        self.assertEqual(report["counts"]["junction_lane_links"], 1)
        link = graph["lane_links"][0]
        self.assertTrue(link["source"].startswith("source_turn_lanes"))
        self.assertNotIn("inferred_without_turn_lanes", link["issues"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
