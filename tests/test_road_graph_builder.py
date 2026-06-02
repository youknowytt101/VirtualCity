"""Offline tests for road_graph conflict prechecks."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))

from road_graph_builder import build_road_graph


def _feature(seg_id, from_node, to_node, coords, highway="residential", width=10.0):
    return {
        "type": "Feature",
        "properties": {
            "seg_id": seg_id,
            "from_node": from_node,
            "to_node": to_node,
            "highway": highway,
            "width": width,
            "lanes": 2,
        },
        "geometry": {
            "type": "LineString",
            "coordinates": coords,
        },
    }


class TestRoadGraphBuilder(unittest.TestCase):
    ORIGIN_LON = 100.0
    ORIGIN_LAT = 12.0

    def _build(self, features):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "roads_clean.geojson"
            dst = root / "road_graph.json"
            src.write_text(json.dumps({
                "type": "FeatureCollection",
                "features": features,
            }), encoding="utf-8")
            graph = build_road_graph(src, dst, self.ORIGIN_LON, self.ORIGIN_LAT)
            self.assertEqual(json.loads(dst.read_text(encoding="utf-8")), graph)
            return graph

    def test_simple_chain_is_not_marked_as_short_conflict(self):
        graph = self._build([
            _feature(1, "a", "b", [[100.0, 12.0], [100.001, 12.0]], width=0.0),
            _feature(2, "b", "c", [[100.001, 12.0], [100.002, 12.0]], width=0.0),
        ])

        self.assertEqual(graph["qa"]["short_conflict_edges"], 0)
        self.assertTrue(all(edge["conflict_short_edge"] is False for edge in graph["edges"]))
        first = graph["edges"][0]
        self.assertEqual(first["width_m"], 6.4)
        self.assertGreater(first["length_m"], 0.0)

    def test_short_edge_between_junctions_is_collapsed(self):
        a = [100.0, 12.0]
        b = [100.00008, 12.0]
        graph = self._build([
            _feature(10, "a", "b", [a, b]),
            _feature(11, "a", "a_west", [a, [99.999, 12.0]]),
            _feature(12, "a", "a_north", [a, [100.0, 12.001]]),
            _feature(13, "b", "b_east", [b, [100.001, 12.0]]),
            _feature(14, "b", "b_north", [b, [100.00008, 12.001]]),
        ])

        self.assertNotIn("edge_10", {edge["id"] for edge in graph["edges"]})
        self.assertEqual(graph["qa"]["short_conflict_edges_precollapse"], 1)
        self.assertEqual(graph["qa"]["collapsed_conflict_edges"], 1)
        self.assertEqual(graph["qa"]["collapsed_node_groups"], 1)
        self.assertEqual(graph["qa"]["collapse_iterations"], 1)
        self.assertEqual(graph["qa"]["short_conflict_edges"], 0)
        self.assertGreater(graph["qa"]["max_conflict_ratio_precollapse"], 1.0)

        junction_nodes = {node["id"]: node["junction_style"] for node in graph["nodes"]}
        merged_node = next(node for node in graph["nodes"] if node["id"].startswith("merged_"))
        self.assertEqual(merged_node["junction_style"], "Crossing")
        self.assertEqual(merged_node["degree"], 4)
        self.assertEqual(junction_nodes[merged_node["id"]], "Crossing")
        self.assertTrue(
            all(
                edge["from_node"] == merged_node["id"] or edge["to_node"] == merged_node["id"]
                for edge in graph["edges"]
            )
        )

    def test_short_dead_end_stub_at_junction_is_collapsed(self):
        a = [100.0, 12.0]
        stub = [100.00003, 12.0]
        graph = self._build([
            _feature(20, "a", "stub", [a, stub], width=4.0),
            _feature(21, "a", "west", [a, [99.999, 12.0]]),
            _feature(22, "a", "north", [a, [100.0, 12.001]]),
            _feature(23, "a", "south", [a, [100.0, 11.999]]),
        ])

        self.assertNotIn("edge_20", {edge["id"] for edge in graph["edges"]})
        self.assertEqual(graph["qa"]["short_conflict_edges"], 0)
        self.assertEqual(graph["qa"]["collapsed_conflict_edges"], 1)
        self.assertTrue(any(node["id"].startswith("merged_") for node in graph["nodes"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
